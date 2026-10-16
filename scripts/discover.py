"""Find Lean repositories that state they formalise an arXiv paper, and list them.

A repository is listed under an arXiv paper, with no one approving it, when its
`formalization.yaml` (the mathlib-initiative format) names that paper among the `sources` it
formalizes, the arXiv identifier exists, and the repository is a Lean project (a lakefile at its
root). The job reads metadata only: it never clones, builds or runs anything from a repository.

GitHub's code search finds the files (it needs a token, returns at most 1,000 results per query
and may miss repositories it has not indexed); repositories tagged `machinechecked` are found
too. The result replaces `registry/discovered/` entirely, so a repository that stops naming a
paper drops off. `registry/delisted.json` removes a listing.

Usage: GITHUB_TOKEN=… python3 scripts/discover.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "registry" / "discovered"
API = "https://api.github.com"
ARXIV_ID = re.compile(r"(?:arxiv\.org/(?:abs|pdf)/|arxiv:\s*)(\d{4}\.\d{4,5})(?:v\d+)?", re.I)
ATOM = "{http://www.w3.org/2005/Atom}"


def get(url: str, raw: bool = False, token: str | None = None):
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json",
        "User-Agent": "machinechecked.org-discovery",
        **({"Authorization": f"Bearer {token}"} if token else {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
    return body.decode("utf-8", "replace") if raw else json.loads(body)


def search(token: str) -> tuple[set[str], dict]:
    """Repositories with a formalization.yaml at their root, or tagged `machinechecked`."""
    found, stats = set(), {}
    for q, kind in (("filename:formalization.yaml", "code"), ("topic:machinechecked", "repositories")):
        n = 0
        for page in range(1, 11):
            url = f"{API}/search/{kind}?q={urllib.parse.quote(q)}&per_page=100&page={page}"
            try:
                d = get(url, token=token)
            except urllib.error.HTTPError as e:
                print(f"search {q!r} page {page}: HTTP {e.code} {e.read()[:200]!r}")
                break
            items = d.get("items", [])
            for it in items:
                repo = it["full_name"] if kind == "repositories" else it["repository"]["full_name"]
                if kind == "code" and it.get("path") != "formalization.yaml":
                    continue        # only the file at the repository's root counts
                found.add(repo)
            n = d.get("total_count", n)
            if len(items) < 100:
                break
            time.sleep(7)           # code search allows 10 requests a minute
        stats[q] = n
    return found, stats


def declarations(repo: str, token: str) -> list[dict]:
    """The arXiv papers a repository's formalization.yaml says it formalizes, at its current
    commit, if it is a Lean project; otherwise nothing."""
    import yaml
    info = get(f"{API}/repos/{repo}", token=token)
    if info.get("fork") or info.get("archived") or info.get("private"):
        return []
    sha = get(f"{API}/repos/{repo}/commits/{info['default_branch']}", token=token)["sha"]
    files = {x["name"] for x in get(f"{API}/repos/{repo}/contents?ref={sha}", token=token)
             if isinstance(x, dict)}
    if not files & {"lakefile.toml", "lakefile.lean"} or "formalization.yaml" not in files:
        return []
    try:
        fy = yaml.safe_load(get(f"{API}/repos/{repo}/contents/formalization.yaml?ref={sha}",
                                raw=True, token=token))
    except Exception as e:  # a malformed file is the repository's problem: skip it
        print(f"{repo}: formalization.yaml unreadable: {e}")
        return []
    if not isinstance(fy, dict):
        return []
    review = fy.get("review") if isinstance(fy.get("review"), dict) else {}
    out = []
    for s in fy.get("sources") or []:
        if not isinstance(s, dict) or s.get("relationship", "formalizes") != "formalizes":
            continue
        m = ARXIV_ID.search(" ".join(str(s.get(k, "")) for k in ("id", "url", "arxiv", "doi")))
        if m:
            out.append({"arxiv": m.group(1), "repository": info["full_name"], "commit": sha,
                        "review_status": str(review.get("status"))[:60] if review.get("status")
                        else None})
    return out


def arxiv_records(ids: list[str]) -> dict[str, dict]:
    """Title, authors and year of each arXiv identifier that exists."""
    out = {}
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        url = ("https://export.arxiv.org/api/query?max_results=50&id_list="
               + ",".join(chunk))
        with urllib.request.urlopen(url, timeout=60) as r:
            feed = ET.fromstring(r.read())
        for e in feed.iter(f"{ATOM}entry"):
            m = re.search(r"abs/(\d{4}\.\d{4,5})", e.findtext(f"{ATOM}id") or "")
            title = " ".join((e.findtext(f"{ATOM}title") or "").split())
            if not m or not title or title == "Error":
                continue
            out[m.group(1)] = {
                "title": title,
                "authors": [a.findtext(f"{ATOM}name") for a in e.iter(f"{ATOM}author")][:50],
                "year": int((e.findtext(f"{ATOM}published") or "0")[:4] or 0)}
        time.sleep(3)
    return out


def main() -> None:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("GITHUB_TOKEN is needed: GitHub's code search requires authentication")
    delisted = {(d["paper"], d["repository"].lower())
                for d in json.loads((ROOT / "registry" / "delisted.json").read_text())}
    repos, stats = search(token)
    print(f"search: {stats}; {len(repos)} candidate repositories")
    decl = []
    for repo in sorted(repos):
        try:
            decl += declarations(repo, token)
        except Exception as e:
            print(f"{repo}: skipped ({e})")
    records = arxiv_records(sorted({d["arxiv"] for d in decl}))
    papers: dict[str, dict] = {}
    for d in decl:
        pid = f"arxiv:{d['arxiv']}"
        rec = records.get(d["arxiv"])
        if rec is None or (pid, d["repository"].lower()) in delisted:
            continue
        p = papers.setdefault(pid, {
            "id": pid, "title": rec["title"], "authors": rec["authors"] or ["(unknown)"],
            **({"year": rec["year"]} if rec["year"] else {}), "listing": "arxiv",
            "links": {"arxiv": f"https://arxiv.org/abs/{d['arxiv']}"}, "formalisations": []})
        f = {"repository": d["repository"], "commit": d["commit"],
             "stated_by": {"source": "formalization.yaml", "file": "formalization.yaml"}}
        if d["review_status"]:
            f["review_status"] = d["review_status"]
        p["formalisations"].append(f)
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    (OUT / ".gitkeep").write_text("")
    for pid, p in sorted(papers.items()):
        (OUT / f"{pid.split(':', 1)[1]}.json").write_text(
            json.dumps(p, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"listed {len(papers)} paper(s) from {len(decl)} declaration(s)")


if __name__ == "__main__":
    main()
