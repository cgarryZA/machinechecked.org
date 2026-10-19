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


def fetch(url: str, limit: int = 100_000_000, headers: dict | None = None) -> bytes:
    """The bytes at `url`, at most `limit` of them; the site's one way of reading the network
    (besides discovery). Raises OSError when it cannot, ValueError when the answer is too large."""
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=120) as r:
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
    except (OSError, ValueError, yaml.YAMLError):
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
    paper_claims`), its page size and its PDF's digest; None when it has no PDF address, and
    `{"state": "unreadable", "detail": …}` when its PDF could not be read."""
    import subprocess
    from prooflens.paper import paper_claims
    from prooflens.pdfclaims import claims_from_pdf

    url = pdf_address(paper)
    if not url:
        return None
    fs = paper.get("formalisations", [])
    # Keyed also by MachineChecked's version: a newer one may find more in the same PDF.
    from importlib.metadata import version
    key = hashlib.sha256(json.dumps(["pdf-digest-v1", version("machinechecked"), url,
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
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        log(f"{paper['id']}: PDF not read ({e})")
        return {"state": "unreadable", "detail": str(e)}
    claims = paper_claims(anchors, paper["title"],
                          [(f, alignment(f["repository"], f["commit"])) for f in fs])
    out = {"claims": claims, "page_size": list(size) if size else None,
           "pdf_sha256": hashlib.sha256(data).hexdigest()}
    hit.write_text(json.dumps(out))
    log(f"{paper['id']}: {len(claims)} statements, "
        f"{sum(1 for c in claims if c['links'])} linked by formalization.yaml")
    return out


def audits_for(paper: dict, log=print) -> dict:
    """Complete public snapshots, or a visible import state for each registered audit."""
    from prooflens.paper import load_published_audit
    out = {}
    for f in paper.get("formalisations", []):
        for a in f.get("audits", [])[:1]:
            try:
                out[f["repository"]] = load_published_audit(paper, f, a, fetch)
            except (OSError, ValueError, KeyError, TypeError) as e:
                state = "unavailable" if isinstance(e, OSError) else "incompatible"
                out[f["repository"]] = {"state": state, "detail": str(e), "url": a["url"]}
                log(f"{paper['id']}: audit {state}: {e}")
    return out
