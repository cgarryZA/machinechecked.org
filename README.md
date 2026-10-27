# machinechecked.org

The website of [MachineChecked](https://github.com/cgarryZA/MachineChecked): the landing page,
paper index and reader for published Lean audits.

The static site uses the MachineChecked package pinned in [`TOOL_VERSION`](TOOL_VERSION).
Paper pages load their listed projects’ audit records, with proof results, reviews and source
locations. Each audit carries its author and revision. Readers choose the original paper or an
explicit audited PDF revision. `/read/?audit=<address>` opens a published audit directly.

An audit that exports MachineChecked's semantic summary (`prooflens/semantic-summary@1`, in its
`data/index.json`) shows it under its link on the paper's page, as that audit records it: per
unit (statements, notation records, proof steps), the claims and their links, the correspondence
and evidence basis of the audit's readings, the reviews with their provenance and the recorded
findings, each count linked to those claims in the audit's Overview. Other sets of readings (a
reviewer's, a workspace's) are linked and counted apart. The site shows the counts as they are, in
MachineChecked's words, and derives nothing from proof statuses. A summary that names another
release, project commit, repository, paper revision or version, or author than its audit is
marked incompatible, and one the pinned package does not read is marked unsupported; the audit
keeps its link. An audit without a summary is shown as before.

A paper version with audits from several repositories opens on the audit of the most-starred
repository (GitHub star counts, read when the site builds; the registry's order when GitHub does
not answer). A claim that audit does not map shows the next audit's evidence, labelled with its
author, repository and commit. Choosing one repository shows only its audit.

## Layout

| Path | What |
|---|---|
| `site/` | the landing page, its preview images, the paper pages' layout (colours and type are the reader's `/read/theme.css`), `demo/` (forwards to the toy audit in the reader) |
| `registry/papers/*.json` | one file per paper: where it is, the Lean repositories that formalise it and who says so, and published audits (`registry/schema.json`) |
| `scripts/papers.py` | builds `/papers/` and a plain HTML page per paper from the registry |
| `scripts/claims.py` | finds each paper's statements in its PDF and the links each repository's `formalization.yaml` declares; MachineChecked (`prooflens.paper`) writes them beside the page as the reader's data |
| `scripts/summary.py` | each audit's semantic summary: read from the index its load read, checked against its audit, and shown on its line of the paper's page |
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
exact places), a paper's versions (a page each, the drop-down between them, and each claim's link
to what it became in the other version, at desktop and phone widths), audit import errors,
catalogue queries and filters,
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

**Versions of a paper.** An audit pins one version of its paper (arXiv v1, or an unpublished
manuscript at a commit), as its `audit.json` says. A formalisation can list an audit of each
version; an audit's `version` (`arxiv:<id>v1`, `manuscript:<commit>`) names the version it must
pin, and one left out (an audit that follows the latest manuscript) is shown at the version it
pins. When a paper's audits pin several versions, each version has its own page,
`/papers/<id>/v1/` or `/papers/<id>/manuscript-<commit>/`, with its own PDF (arXiv's, or the one
the manuscript's audit carries), statements and audits, and the reader offers a drop-down between
them; `/papers/<id>/` shows the latest published version.

A paper whose audits pin one version is shown with its own PDF when that PDF is the one they read
(the same bytes). When they read another PDF, the paper is shown at the version they pin, as
above: arXiv's PDF of that version, or the PDF the manuscript's audit carries, with the audit's
places. When the site cannot show that version (an audit that names no version, or a manuscript's
audit without its PDF), the statements found in the paper's PDF are matched to the audit's entries
by printed number: each match records it (`matched` on the claim's audit record), and the
listing's card says so.

Each claim says what it became in the paper's other versions, with a link to it there ("Theorem
3.1 in Latest manuscript (commit 1f67672), statement changed"). MachineChecked relates the claims
of two versions (`claim_map`) by their LaTeX labels, else by their statement texts, as the
versions' audits record them. arXiv versions follow their numbers, and the manuscript follows
them. A claim is shown as removed, or new, only when it has a label, no claim of the other version
has its label or statement, and no claim there under its number is unmatched or lacks a statement
text. The relation never changes a status.

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
                        and its semantic summary (summary.read, from the index that load read)
                     ──▶ snapshot: registry as shown, statements, audits, follow.json data
build.py (no network) ── per paper: prooflens apply_audits + write_paper_site → data/
                        (a paper's versions also related by prooflens claim_map)
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
published". Each registered audit keeps its own state: one that did not load is reported on its
own line, on the papers list and in `/build.json`, also when another audit of the same repository
loaded. Each also keeps its own semantic summary: the snapshot records where it was read, its
format, digest and state, the pins it names and the audited paper's counts, and the page shows
each audit's summary on that audit's line, never another's. `prepare.py --offline` writes a
snapshot that reads nothing.

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
                       each listing's commit, the audit release shown, and every
                       registered audit's state (and its semantic summary's state and digest)
          /follow.json followed branches' commits and audits' publications, for the follow check
```

Every workflow installs the package the same way (`.github/actions/machinechecked`). The build
stops, naming what is missing, if the installed package lacks what the site uses. The reader
update proposes a release only once pip can install it. The `Follow listed branches` check rebuilds
when a followed branch moves or an audit is republished: its descriptor (`audit.json`) names a
new release, or was written again for the same release, also at an unchanged project commit
(`follow.publication`). An audit exported again with other readings or reviews is such a
publication, so its new semantic summary is shown after the rebuild. If the check cannot run, the
workflow fails and starts no rebuild. To test an unreleased commit, pin the commit by hand.
The semantic summary is shown once `TOOL_VERSION` pins a release that reads it; its tests
(`tests/test_audit_summaries.py`) run when the installed package does.

The landing page's screenshots (`site/preview-*.webp`) are made by `scripts/site_preview.mjs` from
the built site's reader and an exported audit; how to run it is at the top of the script.
