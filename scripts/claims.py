"""The claims of a listed paper, for its page in the reader.

For a paper with a public PDF, MachineChecked's PDF reader finds the numbered statements by
their bold headings (`prooflens.pdfclaims`: the positions are approximate, and a statement in
unusual type can be missed). Each listed repository's `formalization.yaml`, read at its pinned
commit, says which statements it maps to Lean declarations (`prooflens.formalization`). A mapped
statement reads "linked: Lean not checked here (no audit published)"; the others read "not
linked". Nothing here runs Lean or anything from a repository, and no statement's text is kept:
only its number, heading title and place on the page. An audit, when one is published, is what
says what Lean establishes.

The results are cached by PDF address and repository commits, so a build fetches only what is
new.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import urllib.request
from pathlib import Path

NOT_CHECKED = "linked: Lean not checked here (no audit published)"
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


def claims_for(paper: dict, cache: Path, log=print) -> dict | None:
    """The paper's claims and page size for the reader, or None when its PDF cannot be read."""
    from prooflens import formalization as fz
    from prooflens.pdfclaims import claims_from_pdf

    url = pdf_address(paper)
    if not url:
        return None
    fs = paper.get("formalisations", [])
    key = hashlib.sha256(json.dumps([url, [(f["repository"], f["commit"]) for f in fs]],
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
    yamls = [(f, alignment(f["repository"], f["commit"])) for f in fs]
    claims = []
    for a in anchors:
        number = f"{a['env'].capitalize()} {a['number']}"
        links = []
        for f, fy in yamls:
            if not fy:
                continue
            for row in fz.links_for(fy, a["env"], number, paper["title"]):
                for name in row["lean"]:
                    if re.fullmatch(r"[\w.'«»]+", name):
                        links.append({"name": name, "repository": f["repository"],
                                      "commit": f["commit"], "source": "formalization.yaml",
                                      "status": NOT_CHECKED, "class": "unspecified"})
        same = a["end"] and a["end"][0] == a["begin"][0]
        claims.append({
            "id": f"P:{a['env']}-{a['number']}", "number": number, "kind": a["env"],
            "title": a.get("title"),
            "anchor": {"kind": "approximate", "page": a["begin"][0], "y0": a["begin"][2],
                       "y1": a["end"][2] if same else None,
                       "page_end": a["end"][0] if a["end"] else None},
            "status": NOT_CHECKED if links else "not linked",
            "class": "unspecified", "links": links})
    out = {"claims": claims, "page_size": list(size) if size else None, "pdf": url}
    hit.write_text(json.dumps(out))
    log(f"{paper['id']}: {len(claims)} statements, "
        f"{sum(1 for c in claims if c['links'])} linked by formalization.yaml")
    return out
