# machinechecked.org

The website of [MachineChecked](https://github.com/cgarryZA/MachineChecked): the landing page,
paper index and reader for published Lean audits.

The static site uses the MachineChecked package pinned in [`TOOL_VERSION`](TOOL_VERSION).
Paper pages load their listed projects’ audit records, with proof results, reviews and source
locations. Each audit carries its author and revision. Readers choose the original paper or an
explicit audited PDF revision. `/read/?audit=<address>` opens a published audit directly.

## Layout

| Path | What |
|---|---|
| `site/` | the landing page, its preview images, the paper pages' layout (colours and type are the reader's `/read/theme.css`), `demo/` (forwards to the toy audit in the reader) |
| `registry/papers/*.json` | one file per paper: where it is, the Lean repositories that formalise it and who says so, and published audits (`registry/schema.json`) |
| `scripts/papers.py` | builds `/papers/` and a plain HTML page per paper from the registry |
| `scripts/claims.py` | finds each paper's statements in its PDF and the links each repository's `formalization.yaml` declares; MachineChecked (`prooflens.paper`) writes them beside the page as the reader's data |
| `scripts/prepare.py` | the build's network step: reads followed branches' heads, the papers' statements and the registered audits into a snapshot |
| `scripts/build.py` | renders a snapshot into `_site/`, without the network: `site/`, the reader at `/read/`, the paper pages' data, `sitemap.xml`, `robots.txt`, `llms.txt`, `follow.json`, `build.json` |
| `TOOL_VERSION` | the MachineChecked release (or commit) whose reader the site serves |
| `.github/actions/machinechecked` | installs and checks the pinned package, for every workflow |
| `llms.txt` | a short description for language models |

## Build

```sh
pip install "machinechecked==$(cat TOOL_VERSION)"   # or, for a commit: "machinechecked @ git+https://github.com/cgarryZA/MachineChecked@<commit>"
python3 scripts/build.py --check-package             # the installed package is the pinned one
python3 scripts/prepare.py --out .cache/snapshot --claims-cache .cache/claims [--follow]   # or --offline
python3 scripts/build.py --snapshot .cache/snapshot --out _site
npm install --no-save playwright@1.56.1 && node tests/site.test.mjs _site
```

The `Site` workflow tests and builds each pull request, then deploys `main` to GitHub Pages.
Browser tests cover project switching, a paper page with a published audit (statuses, deep links,
exact places), audit import errors, catalogue queries and filters,
external search failures and cancellation, and responsive homepage previews.
Synthetic fixtures exercise the current data contract; older data requests an audit rebuild.

## How papers get listed

Every day the `Discover` workflow (`scripts/discover.py`) searches GitHub for repositories whose
`formalization.yaml` names an arXiv paper among the sources they formalize, checks that the
arXiv identifier exists and that the repository is a Lean project, and rewrites
`registry/discovered/`. Each listing cites its repository’s
`formalization.yaml` and includes a **Report this listing** link. To remove one, add
`{"paper": "arxiv:…", "repository": "owner/repo", "reason": "…"}` to `registry/delisted.json`.

To list your formalisation, publish a `formalization.yaml` with a source whose `relationship` is
`formalizes` and whose `arxiv` is `arxiv:<paper identifier>`. Keep the repository public and include
its Lean toolchain. The daily discovery run checks the source and records the repository revision.
For a claim-level audit, publish the output of `uvx machinechecked export` and add its `audit.json`
address and author to the registry. Repository links and published audits are separate catalogue filters.

## Adding a paper by hand

Add `registry/papers/<name>.json` following `registry/schema.json`. An arXiv paper is listed when
a repository's `formalization.yaml` names it as a source it formalizes (`listing: "arxiv"`,
`stated_by.source: "formalization.yaml"`); a paper not on arXiv is added by the maintainer
(`listing: "curated"`). An audit is added by its address (where its `audit.json` is) and its
author's name; the page opens it in the reader.

## How the site is built

```
GitHub code search ── discover.py (daily) ──▶ registry/discovered/*.json ─┐
maintainers ────────────────────────────────▶ registry/papers/*.json ─────┤ papers.load: the
                                                                          │ one validation
                                                                          ▼
prepare.py (network) ── followed branch heads (follow.resolve)
                     ── each paper's PDF → its statements (claims.claims_for, cached by
                        PDF address, listing commits and package version)
                     ── each listing's formalization.yaml at its commit (claims.alignment)
                     ── each registered audit (claims.audits_for → prooflens load_published_audit)
                     ──▶ snapshot: registry as shown, statements, audits, follow.json data
build.py (no network) ── per paper: prooflens apply_audits + write_paper_site → data/
                      ── papers.write → plain HTML pages, list, badges
                      ──▶ _site/ (+ /follow.json, /build.json) ── browser test ── Pages
follow.py check (every 15 min) ── compares /follow.json with heads and audit publications now
```

| Step | Owns | Network |
|---|---|---|
| `discover.py` | which repositories state they formalise an arXiv paper | GitHub, arXiv |
| `papers.load` / `papers.validate` | the registry: schema validation, merging, delisting | none |
| `prepare.py` | everything read from the network for a build, and how each read failed | papers' PDFs, GitHub, audit hosts |
| MachineChecked (`prooflens.published`, `prooflens.paper`) | what a published audit means: its validation, statuses, places and editions | none (given the site's `fetch`) |
| `build.py` | the static site, from a snapshot | none |
| `follow.py check` | whether a rebuild is due | GitHub, audit hosts, the live site |

All reads go through `claims.fetch` (discovery has its own client for GitHub's search API). A read
that fails is recorded as that failure: a PDF that was not read has no statements, and an audit
that did not load shows "Audit unavailable" or "Audit update required", never "no audit
published". `prepare.py --offline` writes a snapshot that reads nothing.

## Release

The reader has one source: the MachineChecked package. The site serves its built reader unchanged
at `/read/`, at the release `TOOL_VERSION` pins, and has no reader code of its own.

```
MachineChecked release on PyPI (web/ built and committed in the package)
  │  Propose reader update (daily): newer and installable → a branch changing only TOOL_VERSION
  ▼
pull request ── Site workflow: install the pin, check it (build.py --check-package),
  │               pytest, build, browser test; no deploy
  ▼ merge
main ── Site workflow: the same, then deploy to GitHub Pages
          /read/       the package's reader, copied unchanged
          /build.json  site commit, TOOL_VERSION, installed version, reader digest,
                       each listing's commit and the audit release shown
          /follow.json followed branches' commits and audits' publications, for the follow check
```

Every workflow installs the package the same way (`.github/actions/machinechecked`). The build
stops, naming what is missing, if the installed package lacks what the site uses. The reader
update proposes a release only once pip can install it. The `Follow listed branches` check rebuilds
when a followed branch moves or an audit is republished. If the check cannot run, the workflow
fails and starts no rebuild. To test an unreleased commit, pin the commit by hand.

The landing page's screenshots (`site/preview-*.webp`) are made by `scripts/site_preview.mjs` from
the built site's reader and an exported audit; how to run it is at the top of the script.
