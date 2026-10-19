"""The paper pages: one plain HTML page per registered paper, and the list of papers.

Each page says what the site knows about one paper and who says it: where the paper is, the
Lean repositories that state they formalise it (or that the maintainer listed), the project's own
description of its review, and the audits published of each repository, opened in the reader.
The pages are static HTML so that search engines and language models can read them; every
string from the registry is escaped. Nothing here judges a formalisation or an audit.
"""

from __future__ import annotations

import html
import json

from texmath import tex_text
from pathlib import Path
from urllib.parse import quote

ORIGIN = "https://machinechecked.org"


SCHEMA = Path(__file__).resolve().parent.parent / "registry" / "schema.json"


def validate(d: dict, where: str, schema: dict | None = None) -> dict:
    """`d`, if it is a valid registry entry; else stop, saying where and why. The one place the
    registry's entries are checked, whether read from `registry/` or from a build's snapshot."""
    import jsonschema
    schema = schema or json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(d, schema)
    except jsonschema.ValidationError as e:
        raise SystemExit(f"{where}: {e.message} (at {'/'.join(map(str, e.path))})")
    return d


def _read(path: Path, schema: dict) -> dict:
    return validate(json.loads(path.read_text(encoding="utf-8")), path.name, schema)


def load(registry: Path) -> list[dict]:
    """Every paper in the registry, validated against its schema: the maintained entries
    (`papers/`) merged with those the discovery job found (`discovered/`). A maintained entry's
    fields win; a repository listed in both keeps the maintained record and its audits."""
    schema = json.loads((registry / "schema.json").read_text(encoding="utf-8"))
    papers: dict[str, dict] = {}
    for p in sorted((registry / "papers").glob("*.json")):
        d = _read(p, schema)
        if d["id"] in papers:
            raise SystemExit(f"{p.name}: {d['id']} is registered twice")
        papers[d["id"]] = d
    for p in sorted((registry / "discovered").glob("*.json")) if (registry / "discovered").is_dir() else []:
        d = _read(p, schema)
        if d["id"] not in papers:
            papers[d["id"]] = d
            continue
        have = {f["repository"].lower() for f in papers[d["id"]]["formalisations"]}
        papers[d["id"]]["formalisations"] += [f for f in d["formalisations"]
                                              if f["repository"].lower() not in have]
    delisted = registry / "delisted.json"
    gone = {(x["paper"], x["repository"].lower())
            for x in (json.loads(delisted.read_text()) if delisted.exists() else [])}
    for d in papers.values():
        d["formalisations"] = [f for f in d["formalisations"]
                               if (d["id"], f["repository"].lower()) not in gone]
    return list(papers.values())


def slug(paper_id: str) -> str:
    """The page's path segment: the arXiv identifier, or the curated name."""
    kind, rest = paper_id.split(":", 1)
    return rest.replace("/", "-")


def e(s) -> str:
    return html.escape(str(s), quote=True)


def reader_url(audit_url: str) -> str:
    return "/read/?audit=" + quote(audit_url, safe="")


def reader_head(reader_index: str) -> str:
    """The reader's stylesheet and script tags, from its built index.html, pointing at /read/."""
    import re
    tags = re.findall(r'<(?:script|link)\b[^>]*(?:src|href)="\./assets/[^"]+"[^>]*>(?:</script>)?',
                      reader_index)
    if not tags:
        raise SystemExit("the reader's index.html names no assets")
    return "\n".join(t.replace('"./assets/', '"/read/assets/') for t in tags)


def page(title: str, description: str, body: str, canonical: str, jsonld: dict | None = None,
         depth: int = 2, reader: str | None = None) -> str:
    """A page of the site. With `reader` (the reader's asset tags), the page is the reader,
    showing the data beside the page (`data/`, written by MachineChecked's `write_paper_site`);
    its text stays in the page, shown only without JavaScript, so that search engines and
    language models read it."""
    up = "../" * depth
    app = ""
    if reader:
        app = ("<script>document.documentElement.classList.add('reader');</script>\n"
               "<style>html.reader body > .wrap { display: none; }</style>\n" + reader + "\n")
    ld = ""
    if jsonld:
        data = json.dumps(jsonld, ensure_ascii=False).replace("</", "<\\/")
        ld = f'<script type="application/ld+json">{data}</script>\n'
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(description)}">
<link rel="canonical" href="{e(canonical)}">
{f'<noscript><link rel="stylesheet" href="/read/theme.css"><link rel="stylesheet" href="{up}assets/site.css"><style>#app {{ display: none; }}</style></noscript>' if app else f'<link rel="stylesheet" href="/read/theme.css"><link rel="stylesheet" href="{up}assets/site.css">'}
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Ccircle cx='13' cy='13' r='9' fill='none' stroke='%232f6f73' stroke-width='3'/%3E%3Cpath d='M20 20l8 8' stroke='%232f6f73' stroke-width='3' stroke-linecap='round'/%3E%3C/svg%3E">
{ld}{app}</head>
<body>
{'<div id="app"></div>' if app else ''}
<div class="wrap">
  <header class="top">
    <a class="brand" href="{up}"><svg viewBox="0 0 32 32" width="22" height="22" aria-hidden="true"><circle cx="13" cy="13" r="9" fill="none" stroke="currentColor" stroke-width="3"/><path d="M20 20l8 8" stroke="currentColor" stroke-width="3" stroke-linecap="round"/></svg>MachineChecked</a>
    <nav><a href="{up}papers/">Papers</a><a href="{up}demo/">Demo</a><a href="https://github.com/cgarryZA/MachineChecked">GitHub</a></nav>
  </header>
{body}
  <footer>
    <span>MachineChecked · Apache-2.0</span>
    <a href="https://github.com/cgarryZA/machinechecked.org/issues/new?title={quote('Listing: ' + title)}">Report a problem with this page</a>
  </footer>
</div>
</body>
</html>
"""


def level(paper: dict) -> str:
    """The furthest the site's knowledge of the paper goes, in words."""
    fs = paper["formalisations"]
    if any(f.get("audit_state", {}).get("state") in ("unavailable", "incompatible") for f in fs):
        return "Audit needs attention"
    if any(f.get("audits") for f in fs):
        return "Audit published"
    if fs:
        return "Lean repository linked"
    return "No Lean formalisation listed"


def stated(f: dict) -> str:
    s = f["stated_by"]
    if s["source"] == "formalization.yaml":
        words = "Linked by the repository’s <code>formalization.yaml</code>."
    else:
        words = "Listed by the site's maintainer."
    return words + (f" {e(s['note'])}" if s.get("note") and s["source"] == "curated" else "")


def report_url(paper: dict, f: dict) -> str:
    """A pre-filled issue on the site's repository about one listing."""
    title = f"Listing: {f['repository']} for {paper['id']}"
    body = (f"**Paper:** {paper['title']} (`{paper['id']}`)\n**Repository:** {f['repository']} at "
            f"`{f['commit'][:12]}`\n\n### What is wrong with this listing\n\n"
            "<!-- For example: the repository does not formalise this paper, or it is spam. -->\n")
    return ("https://github.com/cgarryZA/machinechecked.org/issues/new?title="
            + quote(title) + "&body=" + quote(body))


def formalisation(f: dict, paper: dict) -> str:
    repo, commit = f["repository"], f["commit"]
    url = f"https://github.com/{repo}/tree/{commit}"
    parts = [f'<div class="card"><h3><a href="{e(url)}">{e(repo)}</a> '
             f'<span class="faint small">at <code>{e(commit[:12])}</code></span></h3>',
             f"<p>{stated(f)}</p>"]
    if f.get("review_status"):
        parts.append(f'<p class="small muted">Project review: '
                     f'{e(f["review_status"])}</p>')
    if f.get("audit_state", {}).get("state") in ("unavailable", "incompatible"):
        parts.append(f'<p class="small muted">Audit {e(f["audit_state"]["state"])}: {e(f["audit_state"].get("detail", ""))}</p>')
    audits = f.get("audits") or []
    if audits:
        parts.append("<ul class=\"audits\">")
        for a in audits:
            parts.append(f'<li><a class="btn primary" href="{e(reader_url(a["url"]))}">Open the audit</a> '
                         f'by {e(a["author"])}'
                         + (f' <span class="small muted">— {e(a["note"])}</span>' if a.get("note") else "")
                         + "</li>")
        parts.append("</ul>")
    else:
        parts.append('<p class="small muted">Audit: awaiting publication.</p>')
    parts.append(f'<p class="small"><a href="{e(report_url(paper, f))}">Report this listing</a></p>')
    parts.append("</div>")
    return "\n".join(parts)


def paper_page(paper: dict, reader: str | None = None) -> str:
    s = slug(paper["id"])
    links = paper["links"]
    ident = (f'arXiv:{e(paper["id"].split(":", 1)[1])}' if paper["id"].startswith("arxiv:")
             else "Curated listing")
    src = []
    for key, label in (("arxiv", "arXiv"), ("pdf", "PDF"), ("page", "Paper's page")):
        if links.get(key):
            src.append(f'<a href="{e(links[key])}">{label}</a>')
    if links.get("doi"):
        src.append(f'<a href="https://doi.org/{e(links["doi"])}">DOI {e(links["doi"])}</a>')
    fs = paper["formalisations"]
    body = [f'  <main class="paper">',
            f'    <p class="eyebrow">{e(level(paper))}</p>',
            f"    <h1>{e(tex_text(paper['title']))}</h1>",
            f'    <p class="authors">{e(", ".join(paper["authors"]))}'
            + (f" · {paper['year']}" if paper.get("year") else "") + "</p>",
            f'    <p class="small muted">{ident}' + (" · " + " · ".join(src) if src else "") + "</p>"]
    if paper.get("abstract"):
        body.append(f'    <p class="abstract">{e(paper["abstract"])}</p>')
    body.append(f"    <h2>Lean formalisations ({len(fs)})</h2>")
    if len(fs) > 1:
        body.append('    <p class="small muted">Choose a formalisation to inspect its evidence.</p>')
    body += [formalisation(f, paper) for f in fs] or ['    <p class="muted">None listed.</p>']
    if paper.get("related"):
        body.append("    <h2>Related</h2><ul>")
        for r in paper["related"]:
            who = f' — {e(", ".join(r["authors"]))}' if r.get("authors") else ""
            body.append(f'<li><a href="{e(r["url"])}">{e(r["title"])}</a>{who}. '
                        f'<span class="muted">{e(r["note"])}</span></li>')
        body.append("</ul>")
    body.append("  </main>")
    jsonld = {"@context": "https://schema.org", "@type": "ScholarlyArticle",
              "name": tex_text(paper["title"]), "author": [{"@type": "Person" if a != "OpenAI" else
                                                  "Organization", "name": a}
                                                 for a in paper["authors"]],
              "url": links.get("arxiv") or links.get("page") or links.get("pdf"),
              "mainEntityOfPage": f"{ORIGIN}/papers/{s}/"}
    if paper.get("year"):
        jsonld["datePublished"] = str(paper["year"])
    desc = (f"{tex_text(paper['title'])}: its Lean formalisations and published audits on MachineChecked. "
            f"{level(paper)}.")
    return page(f"{tex_text(paper['title'])} — MachineChecked", desc, "\n".join(body),
                f"{ORIGIN}/papers/{s}/", jsonld, reader=reader)


# Local papers filter immediately; readers can also request external discovery.
SEARCH_JS = r"""
(() => {
  const query = document.getElementById("q"), found = document.getElementById("found"), status = document.getElementById("search-status");
  const more = document.getElementById("search-external"), filters = [...document.querySelectorAll("[data-filter]")];
  const rows = [...document.querySelectorAll("#listed > li[data-paper]")];
  let filter = "all", generation = 0, request = null;
  const el = (tag, cls, text) => { const node = document.createElement(tag); if (cls) node.className = cls; if (text != null) node.textContent = text; return node; };
  function arxiv(value) {
    const match = value.trim().match(/^(?:(?:https?:\/\/(?:www\.)?arxiv\.org\/(?:abs|pdf)\/)|arxiv:\s*)?(\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z]{2})?\/\d{7})(?:v\d+)?(?:\.pdf)?(?:[?#].*)?$/i);
    return match?.[1].toLowerCase() || null;
  }
  function link(url, text) {
    const node = el("a", null, text);
    try { const u = new URL(url); if (["https:", "http:"].includes(u.protocol)) node.href = u.href; } catch {}
    node.rel = "noopener noreferrer"; return node;
  }
  function update() {
    generation++; request?.abort(); request = null; found.replaceChildren();
    more.disabled = false; more.textContent = "Search other papers";
    const value = query.value.trim().toLowerCase(), id = arxiv(value), words = value.split(/\s+/).filter(Boolean);
    let count = 0;
    for (const row of rows) {
      const matches = id ? row.dataset.paper.toLowerCase() === `arxiv:${id}` : words.every((w) => row.textContent.toLowerCase().includes(w));
      row.hidden = !matches || (filter !== "all" && row.dataset.level !== filter);
      if (!row.hidden) count++;
    }
    status.textContent = count ? `${count} listed paper${count === 1 ? "" : "s"}` : "No listed papers match this search.";
    more.hidden = value.length < 4;
    for (const button of filters) button.setAttribute("aria-pressed", String(button.dataset.filter === filter));
  }
  async function external() {
    request?.abort(); request = new AbortController();
    const mine = ++generation, value = query.value.trim(), id = arxiv(value);
    const signal = request.signal;
    found.replaceChildren(el("p", "muted", "Searching OpenAlex…")); more.disabled = true;
    try {
      const response = await fetch("https://api.openalex.org/works?per-page=5&select=display_name,publication_year,authorships,doi,ids&search=" + encodeURIComponent(id || value), { signal });
      if (!response.ok) throw new Error("search unavailable");
      const data = await response.json();
      if (mine !== generation) return;
      found.replaceChildren(el("h2", null, "Other papers · OpenAlex"));
      if (id && !rows.some((r) => r.dataset.paper.toLowerCase() === `arxiv:${id}`)) found.append(link("https://arxiv.org/abs/" + id, "Open arXiv:" + id));
      if (!data.results?.length) found.append(el("p", "muted", "No other papers found."));
      const list = el("ul", "papers");
      for (const work of data.results || []) {
        const item = el("li");
        item.append(link(work.doi || work.ids?.openalex, work.display_name || "Untitled paper"));
        const authors = (work.authorships || []).slice(0, 4).map((a) => a.author?.display_name).filter(Boolean).join(", ");
        item.append(el("span", "muted", ` — ${authors}${work.publication_year ? " · " + work.publication_year : ""}`));
        list.append(item);
      }
      found.append(list);
    } catch (error) {
      if (mine === generation && error.name !== "AbortError") {
        found.replaceChildren(el("p", "muted", "OpenAlex search is unavailable. Try again."));
        more.textContent = "Retry external search";
      }
    } finally { if (mine === generation) more.disabled = false; }
  }
  query.addEventListener("input", update);
  more.addEventListener("click", external);
  for (const button of filters) button.addEventListener("click", () => { filter = button.dataset.filter; update(); });
  update();
})();
"""


def index_page(papers: list[dict]) -> str:
    rows = []
    for p in sorted(papers, key=lambda p: tex_text(p["title"]).lower()):
        rows.append(f'<li data-paper="{e(p["id"])}" data-level="{"audits" if any(f.get("audits") for f in p["formalisations"]) else "repositories"}"><a href="{e(slug(p["id"]))}/">{e(tex_text(p["title"]))}</a>'
                    f'<span class="muted"> — {e(", ".join(p["authors"]))}</span>'
                    f'<span class="pill">{e(level(p))}</span></li>')
    body = f"""  <main class="paper">
    <h1>Papers</h1>
    <p class="muted">Browse papers, Lean formalisations and published audits.</p>
    <form class="search" role="search" onsubmit="return false">
      <input id="q" type="search" placeholder="Search by title, author or arXiv identifier"
        aria-label="Search papers" autocomplete="off">
    </form>
    <div class="filters" aria-label="Filter papers">
      <button type="button" data-filter="all" aria-pressed="true">All</button>
      <button type="button" data-filter="audits" aria-pressed="false">Published audits</button>
      <button type="button" data-filter="repositories" aria-pressed="false">Repository links</button>
    </div>
    <p id="search-status" role="status"></p>
    <ul class="papers" id="listed">
{chr(10).join(rows) or '<li class="muted">None yet.</li>'}
    </ul>
    <button id="search-external" type="button" hidden>Search other papers</button>
    <section id="found" aria-live="polite" aria-label="External paper search"></section>
    <p class="small"><a href="https://github.com/cgarryZA/machinechecked.org#how-papers-get-listed">List your formalisation →</a></p>
  </main>
  <script>{SEARCH_JS}</script>"""
    return page("Papers — MachineChecked",
                "Mathematical papers with Lean formalisations, and published MachineChecked audits.",
                body, f"{ORIGIN}/papers/", depth=1)


def badge(text: str) -> str:
    """A README badge: "MachineChecked" and what the site lists for the paper. It says how far
    the site's knowledge of the paper goes, never that anything is verified."""
    left, right = "MachineChecked", text
    lw, rw = 8 + 7 * len(left), 10 + 6 * len(right)
    colour = "#2e7d4f" if text == "Audit published" else "#2f6f73"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{lw + rw}" height="20" role="img" aria-label="{e(left)}: {e(right)}">
<title>{e(left)}: {e(right)}</title>
<rect width="{lw}" height="20" fill="#555"/><rect x="{lw}" width="{rw}" height="20" fill="{colour}"/>
<g fill="#fff" font-family="Verdana,DejaVu Sans,sans-serif" font-size="11">
<text x="{lw / 2}" y="14" text-anchor="middle">{e(left)}</text>
<text x="{lw + rw / 2}" y="14" text-anchor="middle">{e(right)}</text></g>
</svg>
"""


def write(out: Path, papers: list[dict], reader_index: str | None = None) -> list[str]:
    """The paper pages and the list, under `out/papers/`; their addresses. With the reader's
    built index.html, each paper page opens in the reader."""
    reader = reader_head(reader_index) if reader_index else None
    urls = [f"{ORIGIN}/papers/"]
    (out / "papers").mkdir(parents=True, exist_ok=True)
    (out / "papers" / "index.html").write_text(index_page(papers), encoding="utf-8")
    for p in papers:
        d = out / "papers" / slug(p["id"])
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(paper_page(p, reader), encoding="utf-8")
        (d / "badge.svg").write_text(badge(level(p)), encoding="utf-8")
        urls.append(f"{ORIGIN}/papers/{slug(p['id'])}/")
    return urls
