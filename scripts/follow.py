"""Listings that follow a branch: a formalisation with `"follow": "<branch>"` in its registry entry
is shown at that branch's current commit, not at the commit the entry pins (which stays as the
fallback when GitHub cannot be asked). The owner of a paper uses this for their own repository, so
that the site shows the repository as it is without a registry change on every push.

The build resolves the heads (`resolve`) and publishes what it used as `/follow.json`; the check
workflow (`.github/workflows/follow.yml`) compares that with the heads now (`moved`) and rebuilds
the site when one moved. A check that cannot run fails the workflow; it never starts a rebuild. Nothing here runs code from a listed repository: it reads commit ids.
"""

from __future__ import annotations

import json
import os
import re
import sys

SHA = re.compile(r"^[0-9a-f]{40}$")


def head(repo: str, branch: str) -> str | None:
    """The commit `branch` of `repo` is at, or None if GitHub does not say."""
    from claims import fetch
    token = os.environ.get("GITHUB_TOKEN")
    try:
        sha = fetch(f"https://api.github.com/repos/{repo}/commits/{branch}", 100,
                    {"Accept": "application/vnd.github.sha",
                     **({"Authorization": f"Bearer {token}"} if token else {})}).decode().strip()
    except (OSError, ValueError, UnicodeDecodeError):
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


def audit_key(url: str) -> str:
    return "audit:" + url.rstrip("/") + "/"


def publication(desc) -> str | None:
    """Which publication of an audit its descriptor (`audit.json`) is: MachineChecked's identity
    of what it publishes (`audit_version`: its release, project commit, paper and data path) and
    when the descriptor was written (`created`, new on every export). A new release at the same
    project commit is a new publication, and so is a re-export of the same release (by a newer
    MachineChecked, or with another display). None for a descriptor the site cannot read."""
    from prooflens.published import audit_version
    if not isinstance(desc, dict) or desc.get("schema") != "machinechecked/audit@1":
        return None
    created = desc.get("created")
    return audit_version(desc) + (f"@{created}" if isinstance(created, str) and created else "")


def published_audit_version(url: str) -> str | None:
    """The publication (`publication`) the audit at `url` is at now, or None when its descriptor
    cannot be read."""
    from claims import fetch
    try:
        return publication(json.loads(fetch(url.rstrip("/") + "/audit.json", 1_000_000)))
    except (OSError, ValueError):
        return None


def moved(ps: list[dict], published: dict) -> list[str]:
    """The followed branches whose head is not the commit the published site used."""
    out = []
    for _, f in followed(ps):
        sha = head(f["repository"], f["follow"])
        if sha is not None and published.get(key(f)) != sha:
            out.append(f"{key(f)}: {str(published.get(key(f)))[:12]} -> {sha[:12]}")
    for p in ps:
        for f in p["formalisations"]:
            for a in f.get("audits", []):
                current = published_audit_version(a["url"])
                k = audit_key(a["url"])
                if current and published.get(k) != current:
                    out.append(f"{k}: publication changed")
    return out


def main() -> None:
    """`python3 scripts/follow.py check URL`: print what moved since the site at URL was built.
    Exits 0 when nothing moved, 1 when something did (the workflow then rebuilds), and 2 when the
    published site's record cannot be read: a failure to ask is not a change."""
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import papers
    ps = papers.load(Path(__file__).resolve().parent.parent / "registry")
    from claims import fetch
    try:
        published = json.loads(fetch(sys.argv[2].rstrip("/") + "/follow.json", 1_000_000))
    except (OSError, ValueError) as e:
        print(f"the published site's follow.json could not be read: {e}", file=sys.stderr)
        sys.exit(2)
    changes = moved(ps, published)
    for c in changes:
        print(c)
    sys.exit(1 if changes else 0)


if __name__ == "__main__":
    main()
