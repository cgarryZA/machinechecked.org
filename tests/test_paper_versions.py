"""A paper whose audits pin different versions of it gets a page per version: arXiv v1 at
`/papers/<id>/v1/` (also the paper's plain address) and the latest manuscript at
`/papers/<id>/manuscript-<commit>/`, each with its own PDF, statements and audits, and the
reader's version drop-down between them; each claim links to what it became in the other
version. The two audits are the synthetic toy export (`fixtures/paper-audit/toy/`), its
descriptor and index made to pin each version of a synthetic arXiv paper
(`write_version_fixture`); for the claim maps, the manuscript's is also revised (`revise`)."""

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import build  # noqa: E402
import claims  # noqa: E402
import papers  # noqa: E402
import prepare  # noqa: E402
from test_paper_audits import AUDIT, REPO, needs_poppler  # noqa: E402
from test_snapshot import no_network, reader, registry  # noqa: E402

PAPER_ID = "arxiv:2601.00001"
V1_URL, LATEST_URL = "https://audit.example/v1/", "https://audit.example/latest/"
REVISION = "956fe0b95b0b16794dd7d0a52827ec9bd260f745"


def write_version_fixture(out: Path, version: dict) -> Path:
    """The toy audit, its descriptor and index naming the synthetic arXiv paper and pinning
    `version`."""
    shutil.copytree(AUDIT, out)
    d = json.loads((out / "audit.json").read_text())
    published = version["kind"] == "published"
    d["papers"][0].update(id=PAPER_ID, version="v1" if published else None,
                          url="https://arxiv.org/abs/2601.00001v1", paper_version=version)
    (out / "audit.json").write_text(json.dumps(d))
    idx = json.loads((out / "data" / "index.json").read_text())
    idx["papers"][0]["paper_version"] = version
    (out / "data" / "index.json").write_text(json.dumps(idx))
    return out


def revise(root: Path) -> Path:
    """The toy audit at `root` as a later manuscript has it: Theorem 2.5's statement changed,
    and Remark 3.1 replaced by a new Remark 3.2 (another number, label and statement)."""
    index = root / "data" / "index.json"
    idx = json.loads(index.read_text())
    rows = {c["id"]: c for c in idx["claims"]}
    for cid, number, label, text in (
            ("T:thm:bound", "Theorem 2.5", "thm:bound", r"There is a constant $C$, independent "
             r"of $n$, such that $T_n \le C n^2$ for every natural number $n \ge 1$."),
            ("T:rem:history", "Remark 3.2", "rem:gauss", r"Theorem~\ref{thm:triangle} is often "
             r"told as a story about the young Gauss.")):
        chunk = root / "data" / "claims" / rows[cid]["file"]
        rec = json.loads(chunk.read_text())
        rec["anchor"]["label"] = label
        rec["statement_tex"] = rf"\label{{{label}}} {text}"
        rec["number"] = rows[cid]["number"] = number
        chunk.write_text(json.dumps(rec))
    index.write_text(json.dumps(idx))
    return root


V1 = {"kind": "published", "id": "arxiv:2601.00001v1", "revision": REVISION, "checked": True}
MANUSCRIPT = {"kind": "manuscript", "id": "manuscript:956fe0b", "revision": REVISION,
              "checked": True}


def entry(audits):
    return {"id": PAPER_ID, "title": "A Toy Paper on Even and Triangular Numbers",
            "authors": ["A. Author"], "listing": "arxiv",
            "links": {"arxiv": "https://arxiv.org/abs/2601.00001"},
            "formalisations": [{"repository": REPO, "commit": "9" * 40,
                                "stated_by": {"source": "curated"}, "audits": audits}]}


TWO = [{"url": LATEST_URL, "author": "A. Author"},
       {"url": V1_URL, "author": "A. Author", "version": "arxiv:2601.00001v1"}]


@pytest.fixture
def served(tmp_path, monkeypatch):
    """Both audits and arXiv's PDFs, served from the fixtures; anything else is offline."""
    roots = {V1_URL: write_version_fixture(tmp_path / "v1", V1),
             LATEST_URL: write_version_fixture(tmp_path / "latest", MANUSCRIPT)}
    pdf = (AUDIT / "data" / "papers" / "T.pdf").read_bytes()

    def fetch(url, limit=100_000_000, headers=None):
        for base, root in roots.items():
            if url.startswith(base) and (root / url[len(base):]).is_file():
                return (root / url[len(base):]).read_bytes()
        if url.startswith("https://export.arxiv.org/pdf/2601.00001"):
            return pdf
        raise OSError(f"offline: {url}")
    monkeypatch.setattr(claims, "fetch", fetch)
    monkeypatch.setattr(claims, "alignment", lambda repo, commit: None)
    return fetch


def site(tmp_path, monkeypatch, audits):
    prepare.prepare(registry(tmp_path, entry(audits)), tmp_path / "snapshot", tmp_path / "cache",
                    log=lambda m: None)
    no_network(monkeypatch)
    out = tmp_path / "out"
    build.build(out, reader(tmp_path), tmp_path / "snapshot")
    return out / "papers" / "2601.00001"


def index(d: Path) -> dict:
    return json.loads((d / "data" / "index.json").read_text())


@needs_poppler
def test_each_version_has_its_page_and_the_plain_address_shows_the_published_one(
        tmp_path, monkeypatch, served):
    d = site(tmp_path, monkeypatch, TWO)
    plain, v1, latest = index(d), index(d / "v1"), index(d / "manuscript-956fe0b")
    assert plain["version"] == v1["version"] == "arxiv:2601.00001v1"
    assert latest["version"] == "manuscript:956fe0b"
    # The drop-down's entries: MachineChecked's labels, each version's page and audits.
    for i in (plain, v1, latest):
        assert [(v["id"], v["label"], v["href"]) for v in i["versions"]] == [
            ("arxiv:2601.00001v1", "arXiv v1", "/papers/2601.00001/v1/"),
            ("manuscript:956fe0b", "Latest manuscript (commit 956fe0b)",
             "/papers/2601.00001/manuscript-956fe0b/")]
        assert [[a["url"] for a in v["audits"]] for v in i["versions"]] == [[V1_URL],
                                                                           [LATEST_URL]]
    # Each page loads only the audit that pins its version.
    assert plain["audits"][REPO]["url"] == v1["audits"][REPO]["url"] == V1_URL
    assert latest["audits"][REPO]["url"] == LATEST_URL
    for i in (plain, v1, latest):
        assert i["audits"][REPO]["state"] == "loaded"
        assert i["audits"][REPO]["paper_version"]["id"] == i["version"]
    # arXiv v1 is shown from arXiv; the manuscript from the PDF its audit carries.
    assert v1["papers"][0]["pdf_url"] == "https://arxiv.org/pdf/2601.00001v1"
    [edition] = latest["editions"]
    assert latest["papers"][0]["pdf_url"] == \
        f"/papers/2601.00001/manuscript-956fe0b/data/papers/{edition['edition']}.pdf"
    assert (d / "manuscript-956fe0b" / "data" / "papers" / f"{edition['edition']}.pdf").is_file()


@needs_poppler
def test_switching_version_changes_no_status_and_the_manuscript_keeps_exact_places(
        tmp_path, monkeypatch, served):
    d = site(tmp_path, monkeypatch, TWO)
    exported = {c["number"]: c for c in
                json.loads((AUDIT / "data" / "index.json").read_text())["claims"]}
    for page in (d, d / "v1", d / "manuscript-956fe0b"):
        for c in index(page)["claims"]:
            mine = c["by_project"][REPO]
            assert mine["status_code"] == exported[c["number"]]["status_code"]
    # The manuscript's page shows the audited PDF, so the audit's exact places carry over.
    for c in index(d / "manuscript-956fe0b")["claims"]:
        assert c["by_project"][REPO]["anchor"] == exported[c["number"]]["anchor"]


@needs_poppler
def test_the_static_pages_link_every_version(tmp_path, monkeypatch, served):
    d = site(tmp_path, monkeypatch, TWO)
    plain = (d / "index.html").read_text()
    latest = (d / "manuscript-956fe0b" / "index.html").read_text()
    assert '<a href="/papers/2601.00001/v1/" aria-current="page">arXiv v1</a>' in plain
    assert ('<a href="/papers/2601.00001/manuscript-956fe0b/" aria-current="page">'
            "Latest manuscript (commit 956fe0b)</a>") in latest
    assert '<link rel="canonical" href="https://machinechecked.org/papers/2601.00001/' \
        'manuscript-956fe0b/">' in latest
    # Each audit names the version it pins and its commit; on a version's page, the audit of that
    # version is the action, and the other version's audit links to its page (#42).
    commit = index(d)["audits"][REPO]["commit"][:12]
    v1_button = (f'<a class="btn primary" href="/read/?audit=https%3A%2F%2Faudit.example%2Fv1%2F">'
                 f'Open the audit of arXiv v1</a> by A. Author · commit <code>{commit}</code>')
    latest_button = ('<a class="btn primary" href="/read/?audit=https%3A%2F%2Faudit.example%2F'
                     'latest%2F">Open the audit of Latest manuscript (commit 956fe0b)</a> by A. '
                     f'Author · commit <code>{commit}</code>')
    for page in (plain, (d / "v1" / "index.html").read_text()):
        assert v1_button in page and "Open the audit of Latest" not in page
        assert ('<li><a href="/papers/2601.00001/manuscript-956fe0b/">Latest manuscript (commit '
                f'956fe0b)</a> · by A. Author · commit <code>{commit}</code></li>') in page
    assert latest_button in latest and "Open the audit of arXiv v1" not in latest
    assert (f'<li><a href="/papers/2601.00001/v1/">arXiv v1</a> · by A. Author · commit '
            f'<code>{commit}</code></li>') in latest
    # The reader gets each version's audits with their commits.
    for v in index(d)["versions"]:
        assert [a.get("commit") for a in v["audits"]] == [index(d)["audits"][REPO]["commit"]]
    sitemap = (tmp_path / "out" / "sitemap.xml").read_text()
    for page in ("", "v1/", "manuscript-956fe0b/"):
        assert f"<loc>https://machinechecked.org/papers/2601.00001/{page}</loc>" in sitemap


@needs_poppler
def test_an_audit_that_pins_another_version_than_its_listing_names_is_refused(
        tmp_path, monkeypatch, served):
    audits = [{"url": LATEST_URL, "author": "A. Author", "version": "arxiv:2601.00001v1"},
              {"url": V1_URL, "author": "A. Author", "version": "arxiv:2601.00001v1"}]
    d = site(tmp_path, monkeypatch, audits)
    # One version is pinned: one page, as before, showing the audit that loaded.
    assert "versions" not in index(d) and not (d / "v1").exists()
    assert index(d)["audits"][REPO]["url"] == V1_URL
    snap = json.loads((tmp_path / "snapshot" / "snapshot.json").read_text())
    assert snap["audits"][PAPER_ID][REPO]["state"] == "incompatible"
    assert "another version" in snap["audits"][PAPER_ID][REPO]["detail"]


def test_one_version_keeps_the_one_page(tmp_path, monkeypatch, served):
    d = site(tmp_path, monkeypatch, TWO[:1])
    assert "versions" not in index(d) and not (d / "manuscript-956fe0b").exists()
    assert index(d)["audits"][REPO]["paper_version"]["id"] == "manuscript:956fe0b"
    assert not any("counterparts" in c for c in index(d)["claims"])


@needs_poppler
def test_a_claim_links_to_what_it_became_in_the_other_version(tmp_path, monkeypatch, served):
    revise(tmp_path / "latest")
    d = site(tmp_path, monkeypatch, TWO)
    plain, v1, latest = index(d), index(d / "v1"), index(d / "manuscript-956fe0b")
    assert plain["claims"] == v1["claims"]
    pages = {"arxiv:2601.00001v1": v1, "manuscript:956fe0b": latest}

    def shown(page):
        return {c["number"]: [(cp["version"], cp["change"], cp["later"],
                               [x["number"] for x in cp["claims"]]) for cp in c["counterparts"]]
                for c in page["claims"] if "counterparts" in c}
    ms, arxiv = "manuscript:956fe0b", "arxiv:2601.00001v1"
    same = ["Definition 1.1", "Theorem 2.1", "Theorem 2.2", "Proposition 2.3", "Remark 2.4",
            "Corollary 2.6"]
    assert shown(v1) == {**{n: [(ms, "same", True, [n])] for n in same},
                         "Theorem 2.5": [(ms, "changed", True, ["Theorem 2.5"])],
                         "Remark 3.1": [(ms, "removed", True, [])]}
    assert shown(latest) == {**{n: [(arxiv, "same", False, [n])] for n in same},
                             "Theorem 2.5": [(arxiv, "changed", False, ["Theorem 2.5"])],
                             "Remark 3.2": [(arxiv, "new", False, [])]}
    # Each counterpart is a claim of the other version's page: the same audit entry, under that
    # page's own claim identifier (v1's from its PDF's headings, the manuscript's from its audit).
    for page in (v1, latest):
        for c in page["claims"]:
            for cp in c.get("counterparts", []):
                there = {x["id"]: x for x in pages[cp["version"]]["claims"]}
                for x in cp["claims"]:
                    assert there[x["id"]]["number"] == x["number"]
                    assert there[x["id"]]["by_project"][REPO]["audit"]["claim"] == \
                        c["by_project"][REPO]["audit"]["claim"]
    assert next(c for c in v1["claims"] if c["number"] == "Theorem 2.5")["counterparts"][0][
        "claims"][0]["id"].startswith("P:audit-")


@needs_poppler
def test_a_claim_map_changes_no_status(tmp_path, monkeypatch, served):
    revise(tmp_path / "latest")
    d = site(tmp_path, monkeypatch, TWO)

    def data(page):
        """The page's data, its index without the counterparts."""
        files = {f.relative_to(page).as_posix(): f.read_bytes()
                 for f in sorted((page / "data").rglob("*")) if f.is_file()}
        i = json.loads(files.pop("data/index.json"))
        counted = sum("counterparts" in c for c in i["claims"])
        for c in i["claims"]:
            c.pop("counterparts", None)
        return files, i, counted
    pages = ("", "v1", "manuscript-956fe0b")
    mapped = {p: data(d / p) for p in pages}
    assert all(counted == 8 for _, _, counted in mapped.values())
    monkeypatch.setattr(build, "version_claim_maps", lambda versions, records: [])
    build.build(tmp_path / "out", reader(tmp_path / "again"), tmp_path / "snapshot")
    for p in pages:
        assert data(d / p) == (*mapped[p][:2], 0)


def record(key, number, label=None, text=None, repos=("o/r",)):
    """A page's claim as `build.page_claims` gives it, with a record from each of `repos`."""
    return {"key": key, "number": number,
            "audit": {r: {"record": {"anchor": {"label": label}, "statement_tex": text}}
                      for r in repos}}


def test_the_claim_inventory_reads_labels_and_statements_its_records_agree_on():
    two = record("t", "Theorem 1", "thm:a", r"\label{thm:a}  For  all $n$.", ("o/r", "o/s"))
    disagree = record("l", "Lemma 2", "lem:b", "Some $n$.", ("o/r", "o/s"))
    disagree["audit"]["o/s"]["record"] = {"anchor": {"label": "lem:c"}, "statement_tex": "Any $n$."}
    pdf_only = {"key": "remark-3", "number": "Remark 3", "audit": {}}
    unnumbered = {**record("x", None, "eq:x", "x = 1"), "number": None}
    assert build.claim_inventory([two, disagree, pdf_only, unnumbered]) == [
        {"key": "t", "number": "Theorem 1", "label": "thm:a", "statement": "For all $n$."},
        {"key": "l", "number": "Lemma 2"},
        {"key": "remark-3", "number": "Remark 3"}]


def test_a_statement_that_only_gains_or_loses_a_label_is_the_same_text():
    """MachineChecked #315: removing a `\\label` leaves no space of its own (except between a
    control word and a letter, which it keeps apart), so a statement that only gains, loses or
    renames a label is the same text, and its claim the same claim in the map."""
    eq = r"\begin{equation}x = y\end{equation}"
    assert build.unlabelled(r"\begin{equation}\label{eq:a}x = y\end{equation}") == eq
    assert build.unlabelled(eq) == eq
    assert build.unlabelled("\\begin{equation}\n  \\label{eq:b}\n  x") == r"\begin{equation} x"
    assert build.unlabelled(r"\item\label{it:a}Each $n$.") == r"\item Each $n$."
    assert build.unlabelled(r"a\label{x}b") == "ab" and build.unlabelled(r"a \label{x} b") == "a b"
    [m] = build.version_claim_maps(
        {"arxiv:2601.00001v1": {"kind": "published", "number": "v1"},
         "arxiv:2601.00001v2": {"kind": "published", "number": "v2"}},
        {"arxiv:2601.00001v1": [record("e5", "(5)", "eq:a",
                                       r"\begin{equation}\label{eq:a}x = y\end{equation}"),
                                record("i1", "(i)", "it:a", r"\item\label{it:a}Each $n$.")],
         "arxiv:2601.00001v2": [record("E5", "(5)", None, eq),
                                record("I1", "(i)", None, r"\item Each $n$.")]})
    assert [([r["key"] for r in e["from"]], e["change"], [r["key"] for r in e["to"]])
            for e in m["claims"]] == [(["e5"], "same", ["E5"]), (["i1"], "same", ["I1"])]


def engine_pairs_by_number() -> bool:
    """Whether the installed MachineChecked's `claim_map` pairs the one unmatched claim of each
    version under the same number (MachineChecked #296, released after 0.1.21), read from its
    map of two unlabelled claims numbered (1) with different statements."""
    from prooflens.paper import claim_map
    m = claim_map("arxiv:2601.00001v1", [{"key": "a", "number": "(1)", "statement": "x = y"}],
                  "arxiv:2601.00001v2", [{"key": "b", "number": "(1)", "statement": "x = z"}])
    return [e["change"] for e in m["claims"]] == ["changed"]


def test_only_removals_and_additions_the_site_can_be_sure_of_are_shown():
    earlier = [record("t1", "Theorem 1", "thm:a", "A holds."),
               record("l2", "Lemma 2", "lem:b", "B holds."),
               record("e3", "(3)", None, "x = y"),
               record("r4", "Remark 4", None, "R holds."),
               record("p5", "Proposition 5", "prop:e", "E holds."),
               record("l7", "Lemma 7", "lem:g", r"\label{lem:g} G holds."),
               record("l8", "Lemma 8", "lem:k", "K holds.")]
    later = [record("T1", "Theorem 1", "thm:a", "A holds for all $n$."),
             record("E3", "(3)", None, "x = y + 0"),
             record("R4", "Remark 4", "rem:d", "R holds, as noted."),
             record("P5", "Proposition 5", "prop:e", None),
             record("C6", "Corollary 6", "cor:f", "F holds."),
             record("L7", "Lemma 7", "lem:h", r"\label{lem:h} G holds."),
             record("L9", "Lemma 9", "lem:k", "K holds for $n$."),
             record("L10", "Lemma 10", "lem:k", "K holds for $m$.")]
    [m] = build.version_claim_maps(
        {"arxiv:2601.00001v1": {"kind": "published", "number": "v1"},
         "manuscript:abcdef1": {"kind": "manuscript"}},
        {"arxiv:2601.00001v1": earlier, "manuscript:abcdef1": later})
    assert (m["from"], m["to"]) == ("arxiv:2601.00001v1", "manuscript:abcdef1")
    expected = [
        (["t1"], "changed", ["T1"]),       # one label, another statement
        (["l7"], "same", ["L7"]),          # another label, the same statement
        (["l2"], "removed", []),           # its label and statement are in no later claim
        ([], "new", ["C6"])]               # its label and statement are in no earlier claim
    # An engine that pairs the one unmatched claim of each version under a number relates an
    # edited statement without a label ((3)) and one that gained a label (Remark 4) as changed;
    # one that does not (0.1.21) leaves them unrelated. Neither engine's map, as the site shows
    # it, says they are removed or new.
    if engine_pairs_by_number():
        expected += [(["e3"], "changed", ["E3"]), (["r4"], "changed", ["R4"])]
    assert sorted(([r["key"] for r in e["from"]], e["change"], [r["key"] for r in e["to"]])
                  for e in m["claims"]) == sorted(expected)
    # Not related at all: a claim whose later claim has no statement text (Proposition 5), and
    # one whose label the other version gives to two claims (Lemma 8, Lemmas 9 and 10).


def test_the_site_drops_removals_and_additions_a_map_cannot_be_sure_of():
    """`settled` on a map that calls every unmatched claim removed or new, as MachineChecked
    0.1.21's `claim_map` does, so the site's own filter is checked whatever engine is
    installed."""
    def ref(c):
        return {"key": c["key"], "number": c["number"]}
    earlier = build.claim_inventory([record("l2", "Lemma 2", "lem:b", "B holds."),
                                     record("e3", "(3)", None, "x = y"),
                                     record("r4", "Remark 4", None, "R holds."),
                                     record("p5", "Proposition 5", "prop:e", "E holds."),
                                     record("l8", "Lemma 8", "lem:k", "K holds.")])
    later = build.claim_inventory([record("E3", "(3)", None, "x = y + 0"),
                                   record("R4", "Remark 4", "rem:d", "R holds, as noted."),
                                   record("P5", "Proposition 5", "prop:e", None),
                                   record("C6", "Corollary 6", "cor:f", "F holds."),
                                   record("L9", "Lemma 9", "lem:k", "K holds for $n$."),
                                   record("L10", "Lemma 10", "lem:k", "K holds for $m$.")])
    unsure = {"from": "arxiv:2601.00001v1", "to": "manuscript:abcdef1", "claims":
              [{"from": [ref(c)], "to": [], "change": "removed"} for c in earlier] +
              [{"from": [], "to": [ref(c)], "change": "new"} for c in later]}
    assert [([r["key"] for r in e["from"]], e["change"], [r["key"] for r in e["to"]])
            for e in build.settled(unsure, earlier, later)["claims"]] == [
        (["l2"], "removed", []), ([], "new", ["C6"])]


def test_versions_are_ordered_and_named():
    vs = build.pinned_versions({
        "a": {"state": "loaded", "paper_version": {"kind": "manuscript", "id": "manuscript:abcdef1",
                                                   "revision": "abcdef1" + "0" * 33}},
        "b": {"state": "loaded", "paper_version": {"kind": "published", "id": "arxiv:2601.00001v2",
                                                   "number": "v2"}},
        "c": {"state": "loaded", "paper_version": {"kind": "published", "id": "arxiv:2601.00001v1",
                                                   "number": "v1"}},
        "d": {"state": "unavailable"}})
    assert list(vs) == ["arxiv:2601.00001v1", "arxiv:2601.00001v2", "manuscript:abcdef1"]
    assert build.default_version(vs) == "arxiv:2601.00001v2"
    assert [build.version_slug(v) for v in vs.values()] == ["v1", "v2", "manuscript-abcdef1"]
    # Claims are related between versions whose order is known: arXiv's by number, then the
    # manuscript.
    assert build.related_versions(vs) == [("arxiv:2601.00001v1", "arxiv:2601.00001v2"),
                                          ("arxiv:2601.00001v1", "manuscript:abcdef1"),
                                          ("arxiv:2601.00001v2", "manuscript:abcdef1")]
    assert build.related_versions({
        "manuscript:abcdef1": {"kind": "manuscript"}, "manuscript:1234567": {"kind": "manuscript"},
        "doi:10.1/x": {"kind": "published"}}) == []
