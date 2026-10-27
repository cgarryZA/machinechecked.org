"""The semantic summary a listed audit exports, on its paper's page.

MachineChecked computes one summary of the semantic work an audit records
(`prooflens/semantic-summary@1`, in the audit's `data/index.json`): per paper and per unit
(statements, notation records, proof steps), how far each set of readings says the Lean states
each claim (the correspondence), how that is supported (the evidence basis, a separate count),
the reviews with their provenance, and the kinds of finding recorded. The site reads it from the
index its load of the audit read (`claims.audits_for`), checks that it names the same release,
project commit and paper as its audit, and shows its counts as they are, in MachineChecked's
words for them, with links into that audit's Overview filtered to each count. It derives nothing
from proof statuses, adds no count to another and makes no score or percentage.

The summary is shown only when the installed MachineChecked reads its format: the package
supplies the schema it is validated against and the words for its keys. An audit without a
summary is shown as before. A summary that cannot be shown keeps the audit's link and says why:
`unsupported` (a format this site's MachineChecked does not read), `incompatible` (it names
another release, commit, paper or author than its audit) or `unreadable` (not valid data).
"""

from __future__ import annotations

import functools
import json
import re
from urllib.parse import quote, urlencode

SCHEMA = "prooflens/semantic-summary@1"
DIGEST = re.compile(r"[0-9a-f]{64}")


@functools.cache
def support() -> dict | None:
    """What the installed MachineChecked supplies to read a summary: the schema it is validated
    against (the `semantic` definition of the package's `manifest-index` schema) and the words
    for its keys (`prooflens.semantic.VOCABULARY`); None when the package does not read
    `SCHEMA`."""
    try:
        from prooflens import semantic
        from prooflens.schemas import schema
    except ImportError:
        return None
    defs = schema("manifest-index").get("$defs") or {}
    const = ((defs.get("semantic") or {}).get("properties") or {}).get("schema") or {}
    words = getattr(semantic, "VOCABULARY", None)
    if getattr(semantic, "SCHEMA", None) != SCHEMA or const.get("const") != SCHEMA or \
            not isinstance(words, dict):
        return None
    return {"schema": {"$ref": "#/$defs/semantic", "$defs": defs}, "words": words}


def installed() -> str:
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version("machinechecked")
    except PackageNotFoundError:
        return "(not installed)"


def index_url(audit_url: str, descriptor: bytes) -> str | None:
    """The address of the index an audit's descriptor names (its `data`), resolved inside the
    audit's directory as MachineChecked resolves it; None when the descriptor does not name one."""
    from prooflens.published import relative_url
    try:
        return relative_url(audit_url.rstrip("/") + "/", json.loads(descriptor)["data"])
    except (ValueError, KeyError, TypeError):
        return None


def _differs(s: dict, loaded: dict, repository: str, key: str) -> str | None:
    """How the summary's pins differ from those of the audit it was loaded with, or None. The
    release and project commit must be the audit's; the repository, the paper's revision and
    version, and the author must be the audit's when the summary names them."""
    audit = s.get("audit") if isinstance(s.get("audit"), dict) else {}
    project = audit.get("project") if isinstance(audit.get("project"), dict) else {}
    if audit.get("release") != loaded.get("release"):
        return "The summary names another release than its audit."
    if project.get("commit") != loaded.get("commit"):
        return "The summary names another project commit than its audit."
    repo = project.get("repository")
    if repo is not None and (not isinstance(repo, str) or repo.lower() != repository.lower()):
        return "The summary names another repository than its audit."
    papers = s.get("papers") if isinstance(s.get("papers"), dict) else {}
    block = papers.get(key)
    if not isinstance(block, dict):
        return "The summary has no counts for the audited paper."
    revision = (loaded.get("paper") or {}).get("revision")
    if block.get("revision") is not None and block["revision"] != revision:
        return "The summary names another revision of the paper than its audit."
    pinned = (loaded.get("paper_version") or {}).get("id")
    if block.get("paper_version") is not None and block["paper_version"] != pinned:
        return "The summary names another version of the paper than its audit."
    if audit.get("author") is not None and audit["author"] != loaded.get("author"):
        return "The summary names another author than its audit."
    return None


def read(raw: bytes | None, loaded: dict, repository: str, url: str | None) -> dict | None:
    """The summary of a loaded audit (`loaded`, as `load_published_audit` returned it, of the
    listing's `repository`), from the bytes of the index that load read (`raw`, at `url`): None
    when the index has none; else its `state` (`loaded`, or why it is not shown, with `detail`),
    `url`, `schema` and `digest`, and, loaded, the pins it names and the counts of the audited
    paper (`paper`), with the sets of readings (`sets`, `selected`)."""
    try:
        idx = json.loads(raw) if raw is not None else None
    except ValueError:
        idx = None
    if not isinstance(idx, dict) or "semantic" not in idx:
        return None
    s = idx["semantic"]
    rec = {"url": url}
    if not isinstance(s, dict):
        return {**rec, "state": "unreadable", "detail": "The summary is not a JSON object."}
    rec["schema"] = s.get("schema") if isinstance(s.get("schema"), str) else None
    if isinstance(s.get("digest"), str) and DIGEST.fullmatch(s["digest"]):
        rec["digest"] = s["digest"]
    if s.get("schema") != SCHEMA:
        return {**rec, "state": "unsupported",
                "detail": f"The summary's format is not {SCHEMA}, which this site reads."}
    key = (loaded.get("paper") or {}).get("id")
    differs = _differs(s, loaded, repository, key)
    if differs:
        return {**rec, "state": "incompatible", "detail": differs}
    known = support()
    if known is None:
        return {**rec, "state": "unsupported",
                "detail": f"MachineChecked {installed()}, which builds this site, does not read "
                          f"{SCHEMA}."}
    import jsonschema
    try:
        jsonschema.validate(s, known["schema"])
    except jsonschema.ValidationError as e:
        return {**rec, "state": "unreadable", "detail": "The summary is not valid at "
                + "/".join(map(str, e.absolute_path)) + "."}
    block = s["papers"][key]
    return {**rec, "state": "loaded", "release": s["audit"]["release"],
            "commit": s["audit"]["project"]["commit"], "author": s["audit"].get("author"),
            "paper_key": key, "revision": block.get("revision"),
            "paper_version": block.get("paper_version"), "selected": s["selected"],
            "sets": s["sets"], "paper": {k: v for k, v in block.items()
                                         if k not in ("revision", "paper_version")}}


# -- on the paper's page ------------------------------------------------------------------------

def e(s) -> str:
    import html
    return html.escape(str(s), quote=True)


def _count(n) -> bool:
    return type(n) is int and n > 0


def overview(reader: str, release: str, **filters) -> str:
    """The audit's Overview in the reader (`reader`, the address that opens the audit), at the
    audit's release and filtered as `filters` say: the reader keeps its filters in the address."""
    query = urlencode({k: v for k, v in filters.items() if v}, quote_via=quote)
    return f"{reader}#/r/{quote(release, safe='')}/overview" + (f"?{query}" if query else "")


def _counts(table, words: dict, link) -> str:
    """Each key of `table` that counts a claim, in the order of the words for its dimension,
    with its label and count, linked to the claims it counts; zero counts are left out and a
    missing count is never shown as one."""
    if not isinstance(table, dict):
        return ""
    def one(k, w):
        why = f' title="{e(w["explanation"])}"' if w.get("explanation") else ""
        return f'<a href="{e(link(k))}"{why}>{e(w["label"])} ({table[k]})</a>'
    return " · ".join(one(k, w) for k, w in words.items() if _count(table.get(k)))


def _inventory(p: dict, unit: str, words: dict) -> str | None:
    """A unit's claims in words: how many, how many are linked, and to how many declarations
    (for proof steps, how many are equations and passages); None when the paper has none."""
    inv = (p.get("inventory") or {}).get(unit) or {}
    n = inv.get("records")
    if not _count(n):
        return None
    w = words["units"][unit]
    out = f"{n} {w['one'] if n == 1 else w['many']}"
    if unit == "proof_steps":
        kinds = [f"{k} {name}{'' if k == 1 else 's'}" for k, name in
                 ((p["inventory"].get("proof_equations"), "equation"),
                  (p["inventory"].get("proof_passages"), "passage")) if _count(k)]
        out += f" ({', '.join(kinds)})" if kinds else ""
    if type(inv.get("linked")) is int:
        d = inv.get("declarations")
        out += f", {inv['linked']} linked" + \
            (f" to {d} declaration{'' if d == 1 else 's'}" if _count(d) else "")
    return out


def set_label(s: dict, words: dict) -> str:
    """A set of readings in MachineChecked's words: the audit's own (with their authors), a
    reviewer's, a workspace's (with its mode)."""
    head = ((words.get("sets") or {}).get(s.get("kind")) or {}).get("label") or str(s.get("id"))
    if s.get("kind") == "audit":
        by = [b for b in s.get("by") or [] if isinstance(b, str) and b]
        return head + (f", by {', '.join(by)}" if by else "")
    rv = s.get("reviewer") if isinstance(s.get("reviewer"), dict) else {}
    who = rv.get("name") or rv.get("id") or ""
    mode = f" ({s['mode']})" if s.get("kind") == "workspace" and s.get("mode") else ""
    return f"{head} {who}".strip() + mode


def html(rec: dict | None, reader: str, version_label: str | None = None) -> str:
    """The summary on one audit's line of the paper's page (`reader` opens that audit): nothing
    when the audit exports none; why, when it cannot be shown; else, per unit, its claims, the
    correspondence and evidence basis of the summary's selected set of readings, the reviews and
    the recorded findings, each count linked to the claims it counts in the audit's Overview;
    the other sets of readings, counted apart; and where the summary was read from."""
    if not rec:
        return ""
    known = support()
    if rec.get("state") == "loaded" and known is None:
        rec = {**rec, "state": "unsupported",
               "detail": f"MachineChecked {installed()}, which builds this site, does not read "
                         f"{SCHEMA}."}
    if rec.get("state") != "loaded":
        return (f'<br><span class="small muted">Semantic summary {e(rec.get("state"))}: '
                f'{e(rec.get("detail") or "")}</span>')
    words, p, release, chosen = known["words"], rec["paper"], rec["release"], rec["selected"]
    sets = [s for s in rec.get("sets") or []
            if isinstance(s, dict) and isinstance(s.get("id"), str)]
    coverage = (p.get("coverage") or {}).get(chosen) or {}
    basis = (p.get("basis") or {}).get(chosen) or {}
    rows = []
    for unit in words["units"]:
        head = _inventory(p, unit, words)
        if head is None:
            continue
        parts = [f"<strong>{e(head)}.</strong>"]
        for label, param, table, vocab in (
                ("Correspondence", "coverage", coverage.get(unit), words["coverage"]),
                ("Evidence basis", "basis", basis.get(unit), words["basis"]),
                ("Reviews", "review", (p.get("review") or {}).get(unit),
                 words["step_review"] if unit == "proof_steps" else words["review"]),
                ("Recorded findings (a claim may have several kinds)", "finding",
                 (p.get("findings") or {}).get(unit), words["findings"])):
            shown = _counts(table, vocab, lambda k, param=param, unit=unit:
                            overview(reader, release, set=chosen, unit=unit, **{param: k}))
            if shown:
                parts.append(f"{label}: {shown}.")
        rows.append(f"<li>{' '.join(parts)}</li>")
    if not rows:
        return ""
    selected = next((s for s in sets if s["id"] == chosen), {"id": chosen})
    others = [f'<a href="{e(overview(reader, release, set=s["id"], unit="statements"))}">'
              f'{e(set_label(s, words))}</a>' for s in sets if s["id"] != chosen]
    source = [f'<a href="{e(rec["url"])}">its data</a>' if rec.get("url") else "its data",
              f"<code>{e(rec.get('schema') or SCHEMA)}</code>",
              f"release <code>{e(release)}</code>",
              f"project commit <code>{e(str(rec.get('commit'))[:12])}</code>"]
    if rec.get("revision"):
        source.append(f"paper revision <code>{e(str(rec['revision'])[:12])}</code>")
    if version_label:
        source.append(e(version_label))
    if rec.get("digest"):
        source.append(f"digest <code>{e(rec['digest'][:12])}</code>")
    whose = set_label(selected, words)
    return ('\n<div class="semantic small" data-digest="' + e(rec.get("digest") or "") + '">'
            f"<p>Semantic summary. Correspondence and evidence basis: "
            f"{e(whose[:1].lower() + whose[1:])}.</p>"
            f"<ul>{''.join(rows)}</ul>"
            + (f"<p>Counted apart: {' · '.join(others)}.</p>" if others else "")
            + f"<details><summary>Source</summary>Read from {', '.join(source)}.</details></div>")
