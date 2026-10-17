"""The statements of a listed paper, for its page in the reader.

For a paper with a public PDF, MachineChecked's PDF reader finds the numbered statements by
their bold headings (`prooflens.pdfclaims`: the positions are approximate, and a statement in
unusual type can be missed). Each listed repository's `formalization.yaml`, read at its pinned
commit, says which statements it maps to Lean declarations (`prooflens.paper`, which also writes the page's data
and its statuses). Nothing here runs Lean or anything from a repository, and no statement's text is kept:
only its number, heading title and place on the page. An audit, when one is published, is what
says what Lean establishes.

The results are cached by PDF address and repository commits, so a build fetches only what is
new.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import urllib.request
from pathlib import Path

UA = {"User-Agent": "machinechecked.org (paper pages; https://machinechecked.org)"}


def pdf_address(paper: dict) -> str | None:
    """Where the build fetches the PDF: arXiv's address for automated access, else the link."""
    links = paper.get("links", {})
    if paper["id"].startswith("arxiv:"):
        return "https://export.arxiv.org/pdf/" + paper["id"].split(":", 1)[1]
    return links.get("pdf")


def fetch(url: str, limit: int = 100_000_000) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"{url}: larger than {limit} bytes")
    return data


def alignment(repo: str, commit: str) -> dict | None:
    """The repository's formalization.yaml at the commit, parsed, or None."""
    import yaml
    try:
        text = fetch(f"https://raw.githubusercontent.com/{repo}/{commit}/formalization.yaml",
                     2_000_000).decode("utf-8", "replace")
        fy = yaml.safe_load(text)
    except Exception:
        return None
    return fy if isinstance(fy, dict) else None


def view_pdf(paper: dict) -> str | None:
    """The PDF the reader shows: the paper's own PDF link, else arXiv's."""
    links = paper.get("links", {})
    if (links.get("pdf") or "").startswith("https://"):
        return links["pdf"]
    if (links.get("arxiv") or "").startswith("https://arxiv.org/abs/"):
        return links["arxiv"].replace("/abs/", "/pdf/", 1)
    return None


def claims_for(paper: dict, cache: Path, log=print) -> dict | None:
    """The paper's statements, with each repository's declared links (`prooflens.paper.
    paper_claims`), and its page size; None when its PDF cannot be read."""
    from prooflens.paper import paper_claims
    from prooflens.pdfclaims import claims_from_pdf

    url = pdf_address(paper)
    if not url:
        return None
    fs = paper.get("formalisations", [])
    # Keyed also by MachineChecked's version: a newer one may find more in the same PDF.
    from importlib.metadata import version
    key = hashlib.sha256(json.dumps([version("machinechecked"), url,
                                     [(f["repository"], f["commit"]) for f in fs]],
                                    sort_keys=True).encode()).hexdigest()[:20]
    hit = cache / f"{key}.json"
    if hit.exists():
        return json.loads(hit.read_text())
    try:
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "paper.pdf"
            data = fetch(url)
            if not data.startswith(b"%PDF"):
                raise ValueError("not a PDF")
            pdf.write_bytes(data)
            anchors, size = claims_from_pdf(pdf)
    except Exception as e:
        log(f"{paper['id']}: PDF not read ({e})")
        return None
    claims = paper_claims(anchors, paper["title"],
                          [(f, alignment(f["repository"], f["commit"])) for f in fs])
    out = {"claims": claims, "page_size": list(size) if size else None}
    hit.write_text(json.dumps(out))
    log(f"{paper['id']}: {len(claims)} statements, "
        f"{sum(1 for c in claims if c['links'])} linked by formalization.yaml")
    return out


def audits_for(paper: dict, numbers: set[str], log=print) -> dict:
    """For each listed formalisation with a published audit, the audit's claims whose printed
    number is one of `numbers` (the statements found on the page), as the audit records them:
    status, class, its Lean names and a link to the claim in the site's reader. Read as data
    from the audit's own files; an audit that cannot be read is left out (its statements keep
    the page's own wording)."""
    from urllib.parse import quote
    import papers
    out = {}
    for f in paper.get("formalisations", []):
        for a in f.get("audits", [])[:1]:
            base = a["url"].rstrip("/") + "/"
            try:
                desc = json.loads(fetch(base + "audit.json", 1_000_000))
                index = json.loads(fetch(base + desc.get("data", "data/index.json"), 20_000_000))
            except Exception as e:
                log(f"{paper['id']}: audit {base} not read ({e})")
                continue
            claims = []
            for c in index.get("claims", []):
                if c.get("number") not in numbers or not c.get("file"):
                    continue
                try:
                    rec = json.loads(fetch(base + "data/claims/" + c["file"], 5_000_000))
                except Exception:
                    rec = {}
                lean = [x for cl in rec.get("clauses", [])
                        for x in ([cl.get("accept"), cl.get("refute")] if cl.get("accept") or
                                  cl.get("refute") else [cl.get("spec")]) + cl.get("defs", [])
                        if x]
                claims.append({"id": c["id"], "number": c["number"], "status": c["status"],
                               "class": c["class"], "lean": list(dict.fromkeys(lean)),
                               "link": papers.reader_url(base) + f"#/r/{index['release']}/read/"
                                       f"{c['paper']}/{quote(c['id'], safe='')}"})
            out[f["repository"]] = {"author": a.get("author"), "url": base,
                                    "commit": f["commit"], "claims": claims}
    return out
