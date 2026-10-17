"""Assemble machinechecked.org into a directory to publish.

The site is static: the landing page and its files (`site/`), the MachineChecked reader at
`/read/` (copied from the installed `machinechecked` package, at the version `TOOL_VERSION`
pins), a sitemap, `robots.txt` and `llms.txt`. Nothing here builds Lean or runs code from an
audit; audits are read by the reader, as data, from where their authors publish them.

Usage: python3 scripts/build.py --out _site [--reader DIR]
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORIGIN = "https://machinechecked.org"


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


def audit_answers(url: str) -> bool:
    """Whether an audit is published at `url`: its descriptor answers and says it is one."""
    import json
    import urllib.request
    try:
        req = urllib.request.Request(url.rstrip("/") + "/audit.json",
                                     headers={"User-Agent": "machinechecked.org (audit check)"})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read(1_000_000))
        return str(d.get("schema", "")).startswith("machinechecked/audit@")
    except Exception:
        return False


def drop_unreachable_audits(ps: list[dict], log=print) -> None:
    """Leave out audits whose address does not answer as an audit (not published yet, or gone):
    the page then says what is listed without linking a reader to nothing. A later build lists
    them again once they answer."""
    for p in ps:
        for f in p["formalisations"]:
            live = [a for a in f.get("audits") or [] if audit_answers(a["url"])]
            for a in f.get("audits") or []:
                if a not in live:
                    log(f"{p['id']}: the audit at {a['url']} does not answer; not listed")
            if "audits" in f:
                f["audits"] = live


def build(out: Path, reader: Path, claims_cache: Path | None = None,
          check_audits: bool = False, follow: bool = False) -> None:
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "site", out)
    shutil.copytree(reader, out / "read")
    import claims
    import papers
    from prooflens.paper import write_paper_site
    ps = papers.load(ROOT / "registry")
    # Listings that follow a branch are shown at its current commit; what was used is
    # published, so the check workflow can tell when to rebuild.
    import json
    import follow as fl
    used = fl.resolve(ps) if follow else {}
    if check_audits:
        drop_unreachable_audits(ps)
    if claims_cache is not None:
        claims_cache.mkdir(parents=True, exist_ok=True)
    # Each paper page's data, in the reader's standard format, beside the page (written first:
    # it replaces the page's directory).
    for p in ps:
        found = claims.claims_for(p, claims_cache) if claims_cache is not None else None
        # The reader's panel offers each listing's report link as the static page builds it.
        entry = {**p, "formalisations": [{**f, "report_url": papers.report_url(p, f)}
                                         for f in p["formalisations"]]}
        write_paper_site(out / "papers" / papers.slug(p["id"]), entry,
                         found["claims"] if found else [], found and found["page_size"],
                         claims.view_pdf(p))
    papers.write(out, ps, (out / "read" / "index.html").read_text(encoding="utf-8"))
    urls = pages(out)
    (out / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"  <url><loc>{u}</loc></url>\n" for u in urls) + "</urlset>\n")
    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {ORIGIN}/sitemap.xml\n")
    shutil.copyfile(ROOT / "llms.txt", out / "llms.txt")
    (out / "follow.json").write_text(json.dumps(used, indent=1) + "\n")
    for need in ("index.html", "read/index.html", "read/theme.css", "demo/index.html", "llms.txt"):
        if not (out / need).is_file():
            sys.exit(f"missing {need}")
    print(f"site written to {out}: {len(urls)} page(s) in the sitemap")


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    a.add_argument("--out", default="_site")
    a.add_argument("--reader", help="a built reader directory (default: the installed package's)")
    a.add_argument("--claims-cache", help="find each paper's statements in its PDF (needs "
                   "poppler), caching the results here")
    a.add_argument("--check-audits", action="store_true",
                   help="list only the audits whose address answers as an audit")
    a.add_argument("--follow", action="store_true",
                   help="show listings that follow a branch at its current commit (asks GitHub)")
    args = a.parse_args()
    build(Path(args.out).resolve(), Path(args.reader).resolve() if args.reader else reader_dir(),
          Path(args.claims_cache).resolve() if args.claims_cache else None, args.check_audits,
          args.follow)


if __name__ == "__main__":
    main()
