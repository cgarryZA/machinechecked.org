"""Read everything the site needs from the network into a snapshot, which `build.py` renders.

This is the site's only network step besides discovery (`discover.py`) and the follow check
(`follow.py check`). For the validated registry it asks GitHub for the heads of followed
branches, finds each paper's statements in its PDF (`claims.claims_for`, cached), and loads each
registered audit (`claims.audits_for`), and asks GitHub for the star count of each audited
repository. It writes them to a directory:

    snapshot.json     the registry as shown (followed listings at their resolved commits), each
                      paper's statements or why its PDF was not read (and, for a paper whose
                      audits pin several arXiv versions, each version's), each audit as loaded or
                      why it was not (a loaded one with its semantic summary, `summary.read`, when
                      it exports one), what the follow check compares (`follow.json`), and the
                      GitHub star count of each repository with an audit (`stars`, None when
                      GitHub did not answer), which orders a paper's audits
    pdfs/<edition>    the audited PDFs the audits carry

Rendering the same snapshot again gives the same site, without the network. A fetch that fails
is recorded as that failure, never as an absent audit or a status.

Usage: python3 scripts/prepare.py --out .cache/snapshot --claims-cache .cache/claims [--follow]
       [--offline]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = "machinechecked.org/snapshot@2"


def audit_versions(audits: dict) -> dict:
    """The publication each registered audit was at when it was read (`follow.publication`, by
    `follow.audit_key`): the descriptor its load read, else (an audit whose descriptor could not
    be read then) its descriptor's now. A failed audit is recorded too, so that the follow check
    rebuilds when it is republished, not on every check while it stays broken."""
    import follow as fl
    out = {}
    for a in audits.values():
        version = a.get("publication") or fl.published_audit_version(a["url"])
        if version:
            out[fl.audit_key(a["url"])] = version
    return out


def prepare(registry: Path, out: Path, claims_cache: Path | None, follow: bool = False,
            offline: bool = False, log=print) -> dict:
    """Write the snapshot to `out` (replacing it) and return it. With `offline`, nothing is
    fetched: every PDF and audit is recorded as not read in this snapshot."""
    import build
    import claims
    import follow as fl
    import papers
    ps = papers.load(registry)
    used = fl.resolve(ps, log=log) if follow and not offline else {}
    if out.exists():
        import shutil
        shutil.rmtree(out)
    (out / "pdfs").mkdir(parents=True)
    found, audits, found_versions, counts = {}, {}, {}, {}
    for p in ps:
        if offline or claims_cache is None:
            found[p["id"]] = {"state": "not-read", "detail": "This build did not read the PDF."}
        else:
            claims_cache.mkdir(parents=True, exist_ok=True)
            found[p["id"]] = claims.claims_for(p, claims_cache, log=log)
        if offline:
            loaded = {(f["repository"] if n == 1 else f"{f['repository']}@{n}"):
                      {"state": "unavailable", "url": a["url"], "repository": f["repository"],
                       "listing_version": a.get("version"),
                       "detail": "This build did not load the audit."}
                      for f in p["formalisations"] for n, a in enumerate(f.get("audits", []), 1)}
        else:
            loaded = claims.audits_for(p, log=log)
            used.update(audit_versions(loaded))
            # A paper whose audits pin several versions has a page per version: the statements
            # of each arXiv version are read from that version's PDF.
            if claims_cache is not None and len(build.pinned_versions(loaded)) > 1:
                found_versions[p["id"]] = {
                    v["id"]: claims.claims_for(p, claims_cache, log=log, version=v["number"])
                    for v in build.pinned_versions(loaded).values() if v.get("number")}
        for repo, a in loaded.items():
            for edition, raw in a.pop("pdfs", {}).items():
                (out / "pdfs" / f"{edition}.pdf").write_bytes(raw)
                a.setdefault("pdf_files", []).append(edition)
        audits[p["id"]] = loaded
        # The star count of each repository with an audit, which orders a page's audits; one
        # GitHub does not give is recorded as None.
        if not offline:
            for f in p["formalisations"]:
                if f.get("audits") and f["repository"] not in counts:
                    counts[f["repository"]] = claims.stars(f["repository"])
    snap = {"schema": SCHEMA, "registry": ps, "found": found, "found_versions": found_versions,
            "audits": audits, "follow": used, "stars": counts}
    (out / "snapshot.json").write_text(json.dumps(snap, sort_keys=True), encoding="utf-8")
    return snap


def read(snapshot: Path) -> dict:
    """A snapshot written by `prepare`, its registry entries validated again; the audits' PDFs
    are restored from `pdfs/`. Stops with the reason when it is missing or malformed."""
    import papers
    try:
        snap = json.loads((snapshot / "snapshot.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        sys.exit(f"{snapshot}: no readable snapshot ({e}); run scripts/prepare.py first")
    if not isinstance(snap, dict) or snap.get("schema") != SCHEMA:
        sys.exit(f"{snapshot}: not a {SCHEMA} snapshot; run scripts/prepare.py again")
    for key in ("registry", "found", "found_versions", "audits", "follow"):
        if key not in snap:
            sys.exit(f"{snapshot}: the snapshot has no {key}")
    snap.setdefault("stars", {})
    for p in snap["registry"]:
        papers.validate(p, f"{snapshot.name}: {p.get('id')}")
    for loaded in snap["audits"].values():
        for a in loaded.values():
            a["pdfs"] = {e: (snapshot / "pdfs" / f"{e}.pdf").read_bytes()
                         for e in a.pop("pdf_files", [])}
    return snap


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    a.add_argument("--out", required=True, help="the snapshot directory to write")
    a.add_argument("--claims-cache", help="find each paper's statements in its PDF (needs "
                   "poppler), caching the results here")
    a.add_argument("--follow", action="store_true",
                   help="show listings that follow a branch at its current commit (asks GitHub)")
    a.add_argument("--offline", action="store_true",
                   help="fetch nothing; record every PDF and audit as not read")
    args = a.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    snap = prepare(ROOT / "registry", Path(args.out).resolve(),
                   Path(args.claims_cache).resolve() if args.claims_cache else None,
                   args.follow, args.offline)
    states = [a["state"] for loaded in snap["audits"].values() for a in loaded.values()]
    print(f"snapshot written to {args.out}: {len(snap['registry'])} paper(s), "
          f"{states.count('loaded')} of {len(states)} audit(s) loaded")


if __name__ == "__main__":
    main()
