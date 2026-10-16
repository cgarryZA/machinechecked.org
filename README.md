# machinechecked.org

The website of [MachineChecked](https://github.com/cgarryZA/MachineChecked): the landing page,
the reader, and (to come) the index of papers, the Lean repositories that formalise them, and
published audits.

The site is static and builds no Lean. Its reader comes from the MachineChecked package at the
commit [`TOOL_VERSION`](TOOL_VERSION) pins; audits are published by their authors where they
choose and read by the reader as data (`/read/?audit=<address of the audit>`). An audit records
what its author linked, checked and reviewed; the site does not endorse it.

## Layout

| Path | What |
|---|---|
| `site/` | the landing page, its preview images, the paper pages' stylesheet, `demo/` (forwards to the toy audit in the reader) |
| `registry/papers/*.json` | one file per paper: where it is, the Lean repositories that formalise it and who says so, and published audits (`registry/schema.json`) |
| `scripts/papers.py` | builds `/papers/` and a plain HTML page per paper from the registry |
| `scripts/build.py` | assembles the site into `_site/`: `site/`, the reader at `/read/`, `sitemap.xml`, `robots.txt`, `llms.txt` |
| `TOOL_VERSION` | the MachineChecked commit whose reader the site serves |
| `llms.txt` | a short description for language models |

## Build

```sh
pip install "machinechecked @ git+https://github.com/cgarryZA/MachineChecked@$(cat TOOL_VERSION)"
python3 scripts/build.py --out _site
```

The `Site` workflow runs the tests (`tests/`) and does this on every push, and deploys `main` to
GitHub Pages.

## Adding a paper

Add `registry/papers/<name>.json` following `registry/schema.json`. An arXiv paper is listed when
a repository's `formalization.yaml` names it as a source it formalizes (`listing: "arxiv"`,
`stated_by.source: "formalization.yaml"`); a paper not on arXiv is added by the maintainer
(`listing: "curated"`). An audit is added by its address (where its `audit.json` is) and its
author's name; the page opens it in the reader.

To update the reader, set `TOOL_VERSION` to a newer MachineChecked commit. The landing page's
screenshots are made by `scripts/site_preview.mjs` in the MachineChecked repository.
