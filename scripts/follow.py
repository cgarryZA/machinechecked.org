"""Listings that follow a branch: a formalisation with `"follow": "<branch>"` in its registry entry
is shown at that branch's current commit, not at the commit the entry pins (which stays as the
fallback when GitHub cannot be asked). The owner of a paper uses this for their own repository, so
that the site shows the repository as it is without a registry change on every push.

The build resolves the heads (`resolve`) and publishes what it used as `/follow.json`; the check
workflow (`.github/workflows/follow.yml`) compares that with the heads now (`moved`) and rebuilds
the site when one moved. Nothing here runs code from a listed repository: it reads commit ids.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request

SHA = re.compile(r"^[0-9a-f]{40}$")


def head(repo: str, branch: str) -> str | None:
    """The commit `branch` of `repo` is at, or None if GitHub does not say."""
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/commits/{branch}",
                                 headers={"Accept": "application/vnd.github.sha",
                                          "User-Agent": "machinechecked.org"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            sha = r.read(100).decode().strip()
    except OSError:
        return None
    return sha if SHA.match(sha) else None


def followed(ps: list[dict]) -> list[tuple[dict, dict]]:
    return [(p, f) for p in ps for f in p["formalisations"] if f.get("follow")]


def key(f: dict) -> str:
    return f"{f['repository']}@{f['follow']}"


def resolve(ps: list[dict], log=print) -> dict:
    """Each followed formalisation at its branch's current commit (in place); what was used, by
    `repository@branch`."""
    used = {}
    for p, f in followed(ps):
        sha = head(f["repository"], f["follow"])
        if sha is None:
            log(f"{p['id']}: {key(f)}: the branch's head is unknown; showing the pinned commit")
        else:
            f["commit"] = sha
        used[key(f)] = f["commit"]
    return used


def moved(ps: list[dict], published: dict) -> list[str]:
    """The followed branches whose head is not the commit the published site used."""
    out = []
    for _, f in followed(ps):
        sha = head(f["repository"], f["follow"])
        if sha is not None and published.get(key(f)) != sha:
            out.append(f"{key(f)}: {str(published.get(key(f)))[:12]} -> {sha[:12]}")
    return out


def main() -> None:
    """`python3 scripts/follow.py check URL`: print the branches that moved since the site at URL
    was built, and exit 1 if any did (the workflow then rebuilds)."""
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import papers
    ps = papers.load(Path(__file__).resolve().parent.parent / "registry")
    try:
        with urllib.request.urlopen(sys.argv[2].rstrip("/") + "/follow.json", timeout=30) as r:
            published = json.loads(r.read(1_000_000))
    except (OSError, ValueError):
        published = {}
    changes = moved(ps, published)
    for c in changes:
        print(c)
    sys.exit(1 if changes else 0)


if __name__ == "__main__":
    main()
