# machinechecked.org

The website of [MachineChecked](https://github.com/cgarryZA/MachineChecked): the landing page,
the reader, the index of papers and Lean repositories that state they formalise them, and
links to published audits.

The site is static and builds no Lean. Its reader comes from the MachineChecked package at the
version [`TOOL_VERSION`](TOOL_VERSION) pins (a release, or a commit); audits are published by their authors where they
choose and read by the reader as data (`/read/?audit=<address of the audit>`). An audit records
what its author linked, checked and reviewed; the site does not endorse it.

## Layout

| Path | What |
|---|---|
| `site/` | the landing page, its preview images, the paper pages' layout (colours and type are the reader's `/read/theme.css`), `demo/` (forwards to the toy audit in the reader) |
| `registry/papers/*.json` | one file per paper: where it is, the Lean repositories that formalise it and who says so, and published audits (`registry/schema.json`) |
| `scripts/papers.py` | builds `/papers/` and a plain HTML page per paper from the registry |
| `scripts/claims.py` | finds each paper's statements in its PDF and the links each repository's `formalization.yaml` declares; MachineChecked (`prooflens.paper`) writes them beside the page as the reader's data |
| `scripts/build.py` | assembles the site into `_site/`: `site/`, the reader at `/read/`, `sitemap.xml`, `robots.txt`, `llms.txt` |
| `TOOL_VERSION` | the MachineChecked release (or commit) whose reader the site serves |
| `llms.txt` | a short description for language models |

## Build

```sh
pip install "machinechecked==$(cat TOOL_VERSION)"   # or, for a commit: "machinechecked @ git+https://github.com/cgarryZA/MachineChecked@<commit>"
python3 scripts/build.py --out _site --claims-cache .cache/claims
npm install --no-save playwright@1.56.1 && node tests/site.test.mjs _site
```

The `Site` workflow runs the tests (`tests/`), builds the site and tests it in a browser on every
push, and deploys `main` to GitHub Pages. The browser test opens a paper with two formalisations, a paper with no audit, the
fixture audit (`tests/fixtures/`), and the demo. Keep fixtures aligned with the pinned
reader's supported data format; prelaunch generated formats can be rebuilt rather than
maintained indefinitely.

## How papers get listed

Every day the `Discover` workflow (`scripts/discover.py`) searches GitHub for repositories whose
`formalization.yaml` names an arXiv paper among the sources they formalize, checks that the
arXiv identifier exists and that the repository is a Lean project, and rewrites
`registry/discovered/`. Nobody approves these listings; each says it is the repository's own
statement, and each has a "Report this listing" link. To remove one, add
`{"paper": "arxiv:…", "repository": "owner/repo", "reason": "…"}` to `registry/delisted.json`.

## Adding a paper by hand

Add `registry/papers/<name>.json` following `registry/schema.json`. An arXiv paper is listed when
a repository's `formalization.yaml` names it as a source it formalizes (`listing: "arxiv"`,
`stated_by.source: "formalization.yaml"`); a paper not on arXiv is added by the maintainer
(`listing: "curated"`). An audit is added by its address (where its `audit.json` is) and its
author's name; the page opens it in the reader.

The reader is updated by pull request: the daily `Propose reader update` workflow notices a newer
MachineChecked release on PyPI, opens a pull request pinning it, and runs the Site workflow on it
(build and browser test, no deploy). Merging it deploys. To test an unreleased commit, pin the
commit by hand. The landing page's
screenshots (`site/preview-*.webp`) are made by `scripts/site_preview.mjs` from the built site's
reader and an exported audit; how to run it is at the top of the script.
