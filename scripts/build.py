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


def build(out: Path, reader: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "site", out)
    shutil.copytree(reader, out / "read")
    urls = pages(out)
    (out / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"  <url><loc>{u}</loc></url>\n" for u in urls) + "</urlset>\n")
    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {ORIGIN}/sitemap.xml\n")
    shutil.copyfile(ROOT / "llms.txt", out / "llms.txt")
    for need in ("index.html", "read/index.html", "demo/index.html", "llms.txt"):
        if not (out / need).is_file():
            sys.exit(f"missing {need}")
    print(f"site written to {out}: {len(urls)} page(s) in the sitemap")


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    a.add_argument("--out", default="_site")
    a.add_argument("--reader", help="a built reader directory (default: the installed package's)")
    args = a.parse_args()
    build(Path(args.out).resolve(), Path(args.reader).resolve() if args.reader else reader_dir())


if __name__ == "__main__":
    main()
