"""Assemble machinechecked.org into a directory to publish, from a snapshot.

The site is static: the landing page and its files (`site/`), the MachineChecked reader at
`/read/` (copied from the installed `machinechecked` package, at the version `TOOL_VERSION`
pins), a page per paper with its data in the reader's format, a sitemap, `robots.txt` and
`llms.txt`. Everything read from the network is in the snapshot `prepare.py` writes; rendering
reads nothing else, so the same snapshot gives the same site. Nothing here builds Lean or runs
code from an audit.

Usage: python3 scripts/build.py --snapshot .cache/snapshot --out _site [--reader DIR]
       python3 scripts/build.py --check-package   (the installed package is the one pinned)
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORIGIN = "https://machinechecked.org"


# What the site uses of the MachineChecked package. A release without one of these cannot build
# the site: the build stops and names what is missing instead of publishing pages without it.
REQUIRED_API = {
    "prooflens.paper": ("paper_claims", "apply_audits", "write_paper_site"),
    "prooflens.published": ("load_published_audit", "audit_version"),
    "prooflens.pdfclaims": ("claims_from_pdf",),
}


def pinned() -> str:
    """The MachineChecked release (or commit) the site is built with: `TOOL_VERSION`."""
    return (ROOT / "TOOL_VERSION").read_text(encoding="utf-8").strip()


def require_package(exact: bool = False) -> str:
    """Stop unless the installed package has everything the site uses (and, with `exact`, is the
    pinned release); return its version."""
    import importlib
    from importlib.metadata import PackageNotFoundError, version
    try:
        have = version("machinechecked")
    except PackageNotFoundError:
        sys.exit(f"machinechecked is not installed; install the pinned {pinned()}")
    missing = []
    for module, names in REQUIRED_API.items():
        try:
            m = importlib.import_module(module)
        except ImportError:
            missing.append(module)
            continue
        missing += [f"{module}.{n}" for n in names if not hasattr(m, n)]
    if missing:
        sys.exit(f"machinechecked {have} lacks what the site uses: {', '.join(missing)}; "
                 f"TOOL_VERSION pins {pinned()}")
    want = pinned()
    if exact and not re.fullmatch(r"[0-9a-f]{40}", want) and have != want:
        sys.exit(f"machinechecked {have} is installed, but TOOL_VERSION pins {want}")
    return have


def reader_dir() -> Path:
    """The built reader shipped in the installed `machinechecked` package."""
    import prooflens
    web = Path(prooflens.__file__).parent / "web"
    if not (web / "index.html").is_file():
        sys.exit(f"no built reader in {web}; install machinechecked first")
    return web


def pages(out: Path) -> list[str]:
    """The site's public pages, for the sitemap: every index.html outside the reader and
    the demo (which forwards to the reader)."""
    urls = []
    for p in sorted(out.rglob("index.html")):
        rel = p.parent.relative_to(out).as_posix()
        if rel.split("/")[0] in ("read", "demo"):
            continue
        urls.append(ORIGIN + "/" + ("" if rel == "." else rel + "/"))
    return urls


def write_paper(out: Path, p: dict, found: dict | None, audits: dict) -> dict:
    """One paper page's data under `out/papers/<slug>/data/`, in the reader's format: the
    statements found in its PDF (`claims.claims_for`) joined with its loaded audits
    (`claims.audits_for`) by MachineChecked. Returns the page's index."""
    import claims
    import papers
    from prooflens.paper import write_paper_site, apply_audits
    found = found if found and "claims" in found else None
    records = apply_audits([dict(c) for c in found["claims"]] if found else [], audits,
                           found.get("pdf_sha256") if found else None)
    for f in p["formalisations"]:
        if f["repository"] in audits:
            a = audits[f["repository"]]
            f["audit_state"] = {k: a[k] for k in ("state", "detail", "release", "commit") if k in a}
    # The reader's panel offers each listing's report link as the static page builds it.
    entry = {**p, "formalisations": [{**f, "report_url": papers.report_url(p, f)}
                                     for f in p["formalisations"]]}
    return write_paper_site(out / "papers" / papers.slug(p["id"]), entry, records,
                            found and found["page_size"], claims.view_pdf(p), audits=audits)


def build(out: Path, reader: Path, snapshot: Path) -> None:
    """Render the site from `snapshot` (see `prepare.py`) into `out`, replacing it."""
    import json
    import papers
    import prepare
    package = require_package()
    snap = prepare.read(snapshot)
    ps = snap["registry"]
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "site", out)
    shutil.copytree(reader, out / "read")
    # Each paper page's data, in the reader's standard format, beside the page (written first:
    # it replaces the page's directory).
    for p in ps:
        write_paper(out, p, snap["found"].get(p["id"]), snap["audits"].get(p["id"], {}))
    papers.write(out, ps, (out / "read" / "index.html").read_text(encoding="utf-8"))
    urls = pages(out)
    (out / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"  <url><loc>{u}</loc></url>\n" for u in urls) + "</urlset>\n")
    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {ORIGIN}/sitemap.xml\n")
    shutil.copyfile(ROOT / "llms.txt", out / "llms.txt")
    (out / "follow.json").write_text(json.dumps(snap["follow"], indent=1) + "\n")
    (out / "build.json").write_text(json.dumps(provenance(out, ps, package), indent=1) + "\n")
    for need in ("index.html", "read/index.html", "read/theme.css", "demo/index.html", "llms.txt"):
        if not (out / need).is_file():
            sys.exit(f"missing {need}")
    print(f"site written to {out}: {len(urls)} page(s) in the sitemap")


def provenance(out: Path, ps: list[dict], package: str) -> dict:
    """What this build of the site was made from, published as `/build.json` so that a stale
    deployment is visible: the site's commit, the pinned and installed MachineChecked, a digest of
    the reader's files, and per paper each listing's commit and the audit release it showed."""
    import os
    digest = hashlib.sha256()
    for f in sorted((out / "read").rglob("*")):
        if f.is_file():
            digest.update(f.relative_to(out).as_posix().encode() + b"\0" + f.read_bytes())
    return {"site_commit": os.environ.get("GITHUB_SHA"), "tool_version": pinned(),
            "machinechecked": package, "reader_sha256": digest.hexdigest(),
            "papers": {p["id"]: [{"repository": f["repository"], "commit": f["commit"],
                                  **({"audit": f["audit_state"]} if f.get("audit_state") else {})}
                                 for f in p["formalisations"]] for p in ps}}


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    a.add_argument("--out", default="_site")
    a.add_argument("--reader", help="a built reader directory (default: the installed package's)")
    a.add_argument("--snapshot", help="the snapshot to render (written by scripts/prepare.py)")
    a.add_argument("--check-package", action="store_true",
                   help="only check that the installed MachineChecked is the pinned one and has "
                   "what the site uses")
    args = a.parse_args()
    if args.check_package:
        print(f"machinechecked {require_package(exact=True)} (TOOL_VERSION {pinned()})")
        return
    if not args.snapshot:
        a.error("--snapshot is required: run scripts/prepare.py first")
    build(Path(args.out).resolve(), Path(args.reader).resolve() if args.reader else reader_dir(),
          Path(args.snapshot).resolve())


if __name__ == "__main__":
    main()
