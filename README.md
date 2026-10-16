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
| `site/` | the landing page, its preview images, `demo/` (forwards to the toy audit in the reader) |
| `scripts/build.py` | assembles the site into `_site/`: `site/`, the reader at `/read/`, `sitemap.xml`, `robots.txt`, `llms.txt` |
| `TOOL_VERSION` | the MachineChecked commit whose reader the site serves |
| `llms.txt` | a short description for language models |

## Build

```sh
pip install "machinechecked @ git+https://github.com/cgarryZA/MachineChecked@$(cat TOOL_VERSION)"
python3 scripts/build.py --out _site
```

The `Site` workflow does this on every push and deploys `main` to GitHub Pages.

To update the reader, set `TOOL_VERSION` to a newer MachineChecked commit. The landing page's
screenshots are made by `scripts/site_preview.mjs` in the MachineChecked repository.
