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
import re
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

UA = {"User-Agent": "machinechecked.org (paper pages; https://machinechecked.org)"}


def pdf_address(paper: dict, version: str | None = None) -> str | None:
    """Where the build fetches the PDF: arXiv's address for automated access (of `version`, such
    as `v1`, when given), else the link."""
    links = paper.get("links", {})
    if paper["id"].startswith("arxiv:"):
        return "https://export.arxiv.org/pdf/" + paper["id"].split(":", 1)[1] + (version or "")
    return links.get("pdf")


RETRIES = 4  # further attempts after a transient failure, waiting 1, 2, 4 and 8 seconds


def _transient(e: OSError) -> bool:
    """A failure worth retrying: rate limiting, a server error, a dropped or timed-out
    connection. A host answering a burst of requests (an audit's hundreds of files) with 503
    is the common case."""
    if isinstance(e, urllib.error.HTTPError):
        return e.code == 429 or e.code >= 500
    return True


def fetch(url: str, limit: int = 100_000_000, headers: dict | None = None) -> bytes:
    """The bytes at `url`, at most `limit` of them; the site's one way of reading the network
    (besides discovery). A transient failure is retried. Raises OSError when it cannot,
    ValueError when the answer is too large."""
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    for attempt in range(RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read(limit + 1)
            break
        except OSError as e:
            if attempt == RETRIES or not _transient(e):
                raise
            time.sleep(2 ** attempt)
    if len(data) > limit:
        raise ValueError(f"{url}: larger than {limit} bytes")
    return data


def stars(repo: str) -> int | None:
    """The repository's GitHub star count, or None when GitHub does not say (the site then keeps
    the registry's order of the paper's audits). Uses `GITHUB_TOKEN` when it is set; GitHub
    answers without one, with a lower rate limit."""
    import os
    token = os.environ.get("GITHUB_TOKEN")
    try:
        d = json.loads(fetch(f"https://api.github.com/repos/{repo}", 1_000_000,
                             {"Accept": "application/vnd.github+json",
                              **({"Authorization": f"Bearer {token}"} if token else {})}))
    except (OSError, ValueError):
        return None
    n = d.get("stargazers_count") if isinstance(d, dict) else None
    return n if type(n) is int and n >= 0 else None


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


def view_pdf(paper: dict, version: str | None = None) -> str | None:
    """The PDF the reader shows: the paper's own PDF link, else arXiv's (of `version`, such as
    `v1`, when given)."""
    links = paper.get("links", {})
    if version is None and (links.get("pdf") or "").startswith("https://"):
        return links["pdf"]
    if (links.get("arxiv") or "").startswith("https://arxiv.org/abs/"):
        pdf = links["arxiv"].replace("/abs/", "/pdf/", 1)
        return re.sub(r"v[0-9]+$", "", pdf) + (version or "")
    return None


def claims_for(paper: dict, cache: Path, log=print, version: str | None = None) -> dict | None:
    """The paper's statements, with each repository's declared links (`prooflens.paper.
    paper_claims`), its page size and its PDF's digest; None when it has no PDF address, and
    `{"state": "unreadable", "detail": …}` when its PDF could not be read. With `version` (an
    arXiv version number such as `v1`), the statements of that version's PDF."""
    import subprocess
    from prooflens.paper import paper_claims
    from prooflens.pdfclaims import claims_from_pdf

    url = pdf_address(paper, version)
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
    """Complete public snapshots, or a visible import state, of every registered audit. A
    repository's first audit is under the repository's name; a further one, such as an audit of
    another version of the paper, under `<repository>@<n>` (n = 2, 3, …). Each record names its
    `repository` and the version its listing names (`listing_version`, or None)."""
    from prooflens.paper import load_published_audit
    out = {}
    for f in paper.get("formalisations", []):
        for n, a in enumerate(f.get("audits", []), 1):
            key = f["repository"] if n == 1 else f"{f['repository']}@{n}"
            # A listing that names its audit's version supersedes the formalisation's
            # `paper_version`, which names one version for all its audits.
            project = {k: v for k, v in f.items() if k != "paper_version"} if a.get("version") \
                else f
            try:
                rec = load_published_audit(paper, project, a, fetch)
            except (OSError, ValueError, KeyError, TypeError) as e:
                state = "unavailable" if isinstance(e, OSError) else "incompatible"
                rec = {"state": state, "detail": str(e), "url": a["url"]}
                log(f"{paper['id']}: audit {state}: {e}")
            out[key] = {**rec, "repository": f["repository"], "listing_version": a.get("version")}
    return out
