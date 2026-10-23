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
    "prooflens.paper": ("paper_claims", "apply_audits", "write_paper_site", "claim_map"),
    "prooflens.published": ("load_published_audit", "audit_version"),
    "prooflens.pdfclaims": ("claims_from_pdf",),
}
# Keyword arguments of `write_paper_site` the site passes.
REQUIRED_PARAMETERS = ("stars", "claim_maps")


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
    if "prooflens.paper.write_paper_site" not in missing and "prooflens.paper" not in missing:
        import inspect
        from prooflens.paper import write_paper_site
        given = inspect.signature(write_paper_site).parameters
        missing += [f"prooflens.paper.write_paper_site({k}=…)" for k in REQUIRED_PARAMETERS
                    if k not in given]
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


def page_claims(found: dict | None, audits: dict) -> list[dict]:
    """The claims a page lists: the statements found in its PDF (`claims.claims_for`) joined with
    its loaded audits (by repository) by MachineChecked, then the audits' entries that no
    statement found in the PDF carries."""
    from prooflens.paper import apply_audits
    found = found if found and "claims" in found else None
    return apply_audits([dict(c) for c in found["claims"]] if found else [], audits,
                        found.get("pdf_sha256") if found else None)


def write_paper(out: Path, p: dict, found: dict | None, audits: dict, where: Path | None = None,
                pdf: str | None = None, version: str | None = None,
                versions: list[dict] | None = None, stars: dict | None = None,
                claim_maps: list[dict] | None = None) -> dict:
    """One paper page's data under `<page>/data/` (the page is `out/papers/<slug>/`, or `where`),
    in the reader's format: its claims (`page_claims`). A page of one version of the paper shows
    that version's PDF (`pdf`, or none), and gets its `version`, every version's entry
    (`versions`) and the claim maps between the versions (`claim_maps`). `stars` (repository:
    GitHub star count, or None) orders the page's audits: the reader opens on the most-starred,
    and keeps the registry's order when a count is missing. Returns the page's index."""
    import claims
    import papers
    from prooflens.paper import write_paper_site
    found = found if found and "claims" in found else None
    records = page_claims(found, audits)
    for f in p["formalisations"]:
        if f["repository"] in audits:
            a = audits[f["repository"]]
            f["audit_state"] = {k: a[k] for k in ("state", "detail", "release", "commit") if k in a}
    # The reader's panel offers each listing's report link as the static page builds it.
    entry = {**p, "formalisations": [{**f, "report_url": papers.report_url(p, f)}
                                     for f in p["formalisations"]]}
    return write_paper_site(where or out / "papers" / papers.slug(p["id"]), entry, records,
                            found and found["page_size"], pdf if version else claims.view_pdf(p),
                            audits=audits, versions=versions, version=version,
                            stars={r: n for r, n in (stars or {}).items() if n is not None},
                            claim_maps=claim_maps or None)


# -- versions of a paper ------------------------------------------------------------------------
#
# The audits of a paper may pin different versions of it (arXiv v1, an unpublished manuscript at a
# commit). Each version then has its own page, `/papers/<slug>/<version>/`, with its own PDF,
# statements and audits, and the reader's drop-down between them; each claim links to what it
# became in the other versions (`version_claim_maps`). The paper's plain address shows its latest
# published version. A paper whose audits pin at most one version keeps the one page it had.

def label_audits(p: dict, audits: dict) -> None:
    """Give each registered audit of `p` the version it pins (`version_id`, `version_label`) and
    the project commit it audits, from its loaded record (`claims.audits_for` keys a repository's
    n-th audit `<repository>@<n>`)."""
    for f in p["formalisations"]:
        for n, a in enumerate(f.get("audits", []), 1):
            got = audits.get(f["repository"] if n == 1 else f"{f['repository']}@{n}") or {}
            if got.get("state") != "loaded":
                continue
            pv = got.get("paper_version")
            if pv and pv.get("label"):
                a["version_label"], a["version_id"] = pv["label"], pv["id"]
            if re.fullmatch(r"[0-9a-f]{40}", got.get("commit") or ""):
                a["commit"] = got["commit"]


def pinned_versions(audits: dict) -> dict:
    """The versions of the paper its loaded audits pin, by identifier, in the order a reader
    lists them: published versions by number, then manuscripts."""
    vs = {}
    for a in audits.values():
        pv = a.get("paper_version") if a.get("state") == "loaded" else None
        if pv and pv.get("id"):
            vs.setdefault(pv["id"], pv)

    def order(v):
        n = v.get("number") or ""
        return (0, int(n[1:]) if re.fullmatch(r"v[0-9]+", n) else 0, v["id"]) \
            if v["kind"] == "published" else (1, 0, v["id"])
    return dict(sorted(vs.items(), key=lambda kv: order(kv[1])))


def default_version(versions: dict) -> str:
    """The version the paper's plain address shows: its latest published version, else the first
    one listed."""
    published = [v for v in versions.values() if v["kind"] == "published"]
    return (published[-1] if published else next(iter(versions.values())))["id"]


def version_slug(v: dict) -> str:
    """The path segment of a version's page: `v1` for arXiv v1, `manuscript-abc1234` for an
    unpublished manuscript at commit abc1234, `published-<digest>` for another published
    version."""
    if v["kind"] == "manuscript":
        return "manuscript-" + v["revision"][:7]
    if re.fullmatch(r"v[0-9]+", v.get("number") or ""):
        return v["number"]
    return "published-" + hashlib.sha256(v["id"].encode()).hexdigest()[:12]


def page_audits(audits: dict, version: str | None, default: str | None) -> dict:
    """The audits a page shows, by repository: each repository's first loaded audit that pins the
    page's version (any version, on a paper with one page); else, on the page of the version its
    listing names (or, when it names none, on the default version's page), its first audit that
    failed to load, shown with its import state. A loaded audit that names no version, on a paper
    with several, is shown there as incompatible."""
    from prooflens.published import same_version
    out = {}
    for a in audits.values():
        if a["repository"] in out or a.get("state") != "loaded":
            continue
        pv = a.get("paper_version")
        if version is None or (pv and same_version(pv["id"], version)):
            out[a["repository"]] = a
    for a in audits.values():
        if a["repository"] in out or (a.get("state") == "loaded" and a.get("paper_version")):
            continue
        named = a.get("listing_version")
        if version is None or (same_version(named, version) if named else version == default):
            out[a["repository"]] = a if a.get("state") != "loaded" else {
                "state": "incompatible", "url": a["url"], "repository": a["repository"],
                "detail": "The audit does not name the version of the paper it pins"}
    return out


def version_pdf(p: dict, v: dict, audits: dict, here: str) -> tuple[str | None, dict | None]:
    """A version page's PDF and, for a manuscript, the statements found in it (none: the page
    lists its audits' claims, at their places in that PDF). A published arXiv version is shown
    from arXiv; an unpublished manuscript from the PDF its audit carries, under the page's own
    `data/papers/` (`here` is the page's address)."""
    import claims
    if v["kind"] == "published" and v.get("number"):
        return claims.view_pdf(p, v["number"]), None
    for a in audits.values():
        ap = a.get("paper") or {}
        if a.get("state") == "loaded" and ap.get("edition"):
            return (f"{here}data/papers/{ap['edition']}.pdf",
                    {"claims": [], "page_size": ap.get("page_size"),
                     "pdf_sha256": ap.get("pdf_sha256")})
    return None, None


def related_versions(versions: dict) -> list[tuple[str, str]]:
    """The pairs of a paper's versions whose claims the site relates, each (earlier, later):
    arXiv versions in the order of their numbers, and each of them before the unpublished
    manuscript (shown as the latest). Two manuscripts, or a published version without an arXiv
    number, have no order the site knows, and are not related."""
    def rank(v):
        n = v.get("number") or ""
        if v["kind"] == "published" and re.fullmatch(r"v[0-9]+", n):
            return (0, int(n[1:]))
        return (1, 0) if v["kind"] == "manuscript" else None
    ranked = [(rank(v), vid) for vid, v in versions.items() if rank(v)]
    return [(a, b) for ra, a in ranked for rb, b in ranked if ra < rb]


LABEL = re.compile(r"\\label\s*\{[^{}]*\}")


def claim_inventory(records: list[dict]) -> list[dict]:
    """A page's claims as `claim_map` compares them: each claim's `key` and `number`, and its
    source label (`label`, such as its LaTeX label) and statement text (`statement`, without the
    `\\label` commands, which are not printed), read from its audits' records when every record
    on the claim gives the same one. A claim without a printed number is left out (a map names
    claims by number)."""
    out = []
    for c in records:
        if not isinstance(c.get("number"), str) or not c["number"]:
            continue
        recs = [a["record"] for a in (c.get("audit") or {}).values() if a.get("record")]
        labels = {(r.get("anchor") or {}).get("label") for r in recs}
        texts = {" ".join(LABEL.sub(" ", r["statement_tex"]).split())
                 if isinstance(r.get("statement_tex"), str) else None for r in recs}
        label = labels.pop() if len(labels) == 1 else None
        text = texts.pop() if len(texts) == 1 else None
        out.append({"key": c["key"], "number": c["number"],
                    **({"label": label} if isinstance(label, str) and label else {}),
                    **({"statement": text} if text else {})})
    return out


def settled(m: dict, earlier: list[dict], later: list[dict]) -> dict:
    """The claim map `m` between two versions' claims (`claim_inventory`) without the removals
    and additions it cannot be sure of. A claim that matches none of the other version's is said
    to be removed (or new) only when it has a label, no claim of the other version has that
    label, and no claim there under its number is unmatched or without statement text: an
    edited statement without a label, or one that gained a label, matches nothing either."""
    sides = {"from": earlier, "to": later}
    other = {"from": "to", "to": "from"}
    label = {s: {c["key"]: c.get("label") for c in cs} for s, cs in sides.items()}
    labels = {s: {c["label"] for c in cs if c.get("label")} for s, cs in sides.items()}
    # Per side, the numbers under which an unmatched claim's counterpart may be.
    unsure = {s: {c["number"] for c in cs if not c.get("statement")} |
              {r["number"] for e in m["claims"] if not e[other[s]] for r in e[s]}
              for s, cs in sides.items()}

    def sure(e):
        if e["change"] not in ("removed", "new"):
            return True
        side = "from" if e["change"] == "removed" else "to"
        [r] = e[side]
        mine = label[side].get(r["key"])
        return bool(mine) and mine not in labels[other[side]] \
            and r["number"] not in unsure[other[side]]
    return {**m, "claims": [e for e in m["claims"] if sure(e)]}


def version_claim_maps(versions: dict, records: dict, log=print) -> list[dict]:
    """The claim maps between a paper's related versions (`related_versions`), computed by
    MachineChecked (`claim_map`) from each version page's claims (`records`, by version id; see
    `claim_inventory`), without the removals and additions they cannot be sure of (`settled`).
    A map only says what a claim became in the other version; it changes no status. A pair
    whose map MachineChecked refuses is left unrelated, and the build says so."""
    from prooflens.paper import claim_map
    maps = []
    for a, b in related_versions(versions):
        earlier, later = claim_inventory(records[a]), claim_inventory(records[b])
        try:
            maps.append(settled(claim_map(a, earlier, b, later), earlier, later))
        except ValueError as e:
            log(f"claims of {a} and {b} not related: {e}")
    return maps


def write_versions(out: Path, p: dict, found: dict | None, by_version: dict,
                   audits: dict, stars: dict | None = None) -> list[dict]:
    """The pages of a paper whose audits pin several versions: the default version's at the
    paper's plain address and at its own, and every other version's at its own, each with the
    claim maps between the versions (`version_claim_maps`), so that a claim links to what it
    became in another version. Returns the versions as the static pages list them (`label`,
    `href`, `current` for the default)."""
    import copy
    import papers
    versions = pinned_versions(audits)
    default = default_version(versions)
    base = f"/papers/{papers.slug(p['id'])}/"
    pages = {}
    for vid, v in versions.items():
        here = base + version_slug(v) + "/"
        shown = page_audits(audits, vid, default)
        pdf, own = version_pdf(p, v, shown, here)
        pages[vid] = {"here": here, "audits": shown, "pdf": pdf,
                      "found": own if v["kind"] == "manuscript" else by_version.get(vid)}
    entries = [{"id": vid, "kind": v["kind"], "revision": v.get("revision"),
                "href": pages[vid]["here"], "pdf": pages[vid]["pdf"],
                "audits": [{"url": a["url"], "author": a.get("author"), "repository": r,
                            "commit": a.get("commit")}
                           for r, a in pages[vid]["audits"].items() if a.get("state") == "loaded"]}
               for vid, v in versions.items()]
    maps = version_claim_maps(versions, {vid: page_claims(page["found"], page["audits"])
                                         for vid, page in pages.items()})
    # The plain address first: writing a page replaces its directory, and the versions' pages
    # are inside it.
    order = [(default, out / "papers" / papers.slug(p["id"]))] + \
        [(vid, out / "papers" / papers.slug(p["id"]) / version_slug(v))
         for vid, v in versions.items()]
    for vid, where in order:
        page = pages[vid]
        q = copy.deepcopy(p)
        pdf = page["pdf"]
        if where.name != version_slug(versions[vid]) and pdf and pdf.startswith(page["here"]):
            pdf = base + pdf[len(page["here"]):]
        write_paper(out, q, page["found"], page["audits"], where, pdf, vid, entries, stars, maps)
        if vid == default and where == order[0][1]:
            p["formalisations"] = q["formalisations"]
    return [{"id": vid, "label": v["label"], "href": pages[vid]["here"], "slug": version_slug(v),
             "default": vid == default} for vid, v in versions.items()]


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
    # it replaces the page's directory); a page per version of a paper whose audits pin several.
    for p in ps:
        audits = snap["audits"].get(p["id"], {})
        label_audits(p, audits)
        if len(pinned_versions(audits)) > 1:
            p["versions_shown"] = write_versions(out, p, snap["found"].get(p["id"]),
                                                 snap["found_versions"].get(p["id"], {}), audits,
                                                 snap["stars"])
        else:
            write_paper(out, p, snap["found"].get(p["id"]), page_audits(audits, None, None),
                        stars=snap["stars"])
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
