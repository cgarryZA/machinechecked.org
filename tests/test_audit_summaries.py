"""Each listed audit's semantic summary (`prooflens/semantic-summary@1`) on its paper's page:
read from the audit's own index, checked against its audit, shown with its units, its
correspondence and evidence basis apart, its reviews and findings, each count linked into that
audit's Overview; and an audit without one shown as before.

The two audits (`fixtures/semantic-audit/a/`, `b/`) are zero-configuration exports, by
MachineChecked's main branch (a94617a, which computes the summary), of MachineChecked's
synthetic project `tests/fixtures/coverage` with a notation record and a proof equation added,
at one commit of a synthetic repository `example/even-sums`. Audit A's links file records every
basis and an unresolved question; audit B's, other readings, with one independent review
recorded through `machinechecked review`. Their descriptors name the public paper
`curated:even-sums`.

The tests marked `needs_summary_support` show a summary's counts, in MachineChecked's words for
them, and run when the installed MachineChecked reads the summary (a release after 0.1.21); with
an older one the summary is reported as unsupported, which the other tests check."""

import html
import json
import re
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import build  # noqa: E402
import claims  # noqa: E402
import follow  # noqa: E402
import papers  # noqa: E402
import prepare  # noqa: E402
import summary  # noqa: E402
from test_paper_audits import AUDIT as TOY, AUDIT_URL as TOY_URL  # noqa: E402
from test_snapshot import no_network, reader, registry, tree  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "semantic-audit"
REPO = "example/even-sums"
A_URL, B_URL = "https://audit.example/even-sums/a/", "https://audit.example/even-sums/b/"
PDF_URL = "https://paper.example/even-sums.pdf"

needs_summary_support = pytest.mark.skipif(
    summary.support() is None,
    reason="the installed MachineChecked does not read prooflens/semantic-summary@1")


def paper(*urls):
    return {"id": "curated:even-sums", "title": "Sums of Even Numbers",
            "authors": ["A synthetic example"], "listing": "curated", "links": {"pdf": PDF_URL},
            "formalisations": [{"repository": REPO, "commit": "9" * 40,
                                "stated_by": {"source": "curated"},
                                "audits": [{"url": u, "author": a} for u, a in urls]}]}


A = (A_URL, "A. Auditor")
B = (B_URL, "B. Auditor")


@pytest.fixture
def served(tmp_path, monkeypatch):
    """The audits, copied so that a test may change them (`roots`: address → directory);
    anything else is offline."""
    roots = {}
    for url, name in ((A_URL, "a"), (B_URL, "b")):
        roots[url] = tmp_path / "served" / name
        shutil.copytree(FIXTURES / name, roots[url])
    roots[TOY_URL] = TOY

    def fetch(url, limit=100_000_000, headers=None):
        for base, root in roots.items():
            if url.startswith(base) and (root / url[len(base):]).is_file():
                return (root / url[len(base):]).read_bytes()
        raise OSError(f"offline: {url}")
    monkeypatch.setattr(claims, "fetch", fetch)
    monkeypatch.setattr(claims, "alignment", lambda repo, commit: None)
    return roots


def edit_index(root: Path, change) -> dict:
    path = root / "data" / "index.json"
    idx = json.loads(path.read_text())
    change(idx)
    path.write_text(json.dumps(idx))
    return idx


def exported(name: str) -> dict:
    return json.loads((FIXTURES / name / "data" / "index.json").read_text())["semantic"]


def labelled(p: dict) -> dict:
    audits = claims.audits_for(p, log=lambda m: None)
    build.label_audits(p, audits)
    return audits


def lines(page: str) -> list[str]:
    """The audit lines of a page."""
    return [li for li in page.split("\n<li>")[1:] if "Open the audit" in li]


def label(dimension: str, key: str) -> str:
    return html.escape(summary.support()["words"][dimension][key]["label"], quote=True)


def link(url: str, release: str, **filters) -> str:
    return html.escape(summary.overview(papers.reader_url(url), release, **filters), quote=True)


# -- an audit without a summary, and a summary that is not shown -------------------------------

def test_an_audit_without_a_summary_is_shown_as_before(tmp_path, served):
    p = {"id": "curated:toy-paper", "title": "A Toy Paper on Even and Triangular Numbers",
         "authors": ["A. Author"], "listing": "curated", "links": {},
         "formalisations": [{"repository": "cgarryZA/MachineChecked", "commit": "9" * 40,
                             "stated_by": {"source": "curated"},
                             "audits": [{"url": TOY_URL, "author": "A. Author"}]}]}
    audits = labelled(p)
    a = p["formalisations"][0]["audits"][0]
    assert audits["cgarryZA/MachineChecked"]["state"] == "loaded"
    assert "semantic" not in audits["cgarryZA/MachineChecked"] and "semantic" not in a
    assert papers.audit_line(a, True) == (
        '<li><a class="btn primary" href="/read/?audit=https%3A%2F%2Faudit.example%2Ftoy%2F">'
        'Open the audit</a> by A. Author · commit <code>956fe0b95b0b</code></li>')
    built = build.provenance(tmp_path, [p], "0")["papers"][p["id"]][0]
    assert "semantic" not in built["audits"][0]


def test_a_summary_this_sites_machinechecked_does_not_read_keeps_its_audit(served, monkeypatch):
    monkeypatch.setattr(summary, "support", lambda: None)
    p = paper(A)
    audits = labelled(p)
    got = audits[REPO]
    assert got["state"] == "loaded" and got["claims"]
    assert got["semantic"]["state"] == "unsupported"
    assert "does not read prooflens/semantic-summary@1" in got["semantic"]["detail"]
    # Its identity is kept: where it was read, its format and its digest.
    assert got["semantic"]["url"] == A_URL + "data/index.json"
    assert got["semantic"]["schema"] == summary.SCHEMA
    assert got["semantic"]["digest"] == exported("a")["digest"]
    [line] = lines(papers.paper_page(p))
    assert 'href="/read/?audit=https%3A%2F%2Faudit.example%2Feven-sums%2Fa%2F">Open the audit' in line
    assert "Semantic summary unsupported: MachineChecked" in line
    assert "overview" not in line and "(0)" not in line and 'class="semantic' not in line


@pytest.mark.parametrize("change, detail", [
    (lambda s: s["audit"].update(release="v-another"), "another release"),
    (lambda s: s["audit"]["project"].update(commit="1" * 40), "another project commit"),
    (lambda s: s["audit"]["project"].update(repository="example/other"), "another repository"),
    (lambda s: s["papers"]["P"].update(revision="2" * 40), "another revision of the paper"),
    (lambda s: s["papers"]["P"].update(paper_version="manuscript:2222222"),
     "another version of the paper"),
    (lambda s: s["audit"].update(author="C. Somebody"), "another author"),
    (lambda s: s["papers"].update(Q=s["papers"].pop("P")), "no counts for the audited paper"),
])
def test_a_summary_whose_pins_differ_from_its_audit_is_not_shown(served, change, detail):
    """A summary that names another release, commit, repository, paper revision or version, or
    author than its audit is marked incompatible; the audit keeps its link and its claims, and no
    count of the summary is shown under it."""
    edit_index(served[A_URL], lambda idx: change(idx["semantic"]))
    p = paper(A)
    got = labelled(p)[REPO]
    assert got["state"] == "loaded" and got["claims"]
    assert got["semantic"]["state"] == "incompatible" and detail in got["semantic"]["detail"]
    [line] = lines(papers.paper_page(p))
    assert "Open the audit" in line and "Semantic summary incompatible: " in line
    assert "overview" not in line and 'class="semantic' not in line


def test_a_summary_that_is_not_valid_data_shows_no_counts():
    loaded = {"state": "loaded", "release": "r", "commit": "c" * 40, "author": "A",
              "paper": {"id": "P", "revision": None}, "paper_version": None}

    def read(semantic):
        return summary.read(json.dumps({"semantic": semantic}).encode(), loaded, REPO,
                            "https://audit.example/x/data/index.json")
    assert summary.read(b'{"claims": []}', loaded, REPO, None) is None
    assert summary.read(None, loaded, REPO, None) is None
    assert read("a summary")["state"] == "unreadable"
    assert read({"schema": "prooflens/semantic-summary@2"})["state"] == "unsupported"
    # The right pins, without the counts: never shown as zeros.
    hollow = read({"schema": summary.SCHEMA, "audit": {"release": "r", "project": {"commit": "c" * 40}},
                   "selected": "audit", "sets": [], "papers": {"P": {}}, "digest": "0" * 64})
    assert hollow["state"] in ("unreadable", "unsupported")
    for rec in (read("a summary"), hollow):
        shown = summary.html(rec, "/read/?audit=x")
        assert shown.startswith('<br><span class="small muted">Semantic summary ')
        assert "(0)" not in shown and "overview" not in shown


# -- a summary on the page ---------------------------------------------------------------------

@needs_summary_support
def test_an_audit_shows_its_summary_with_its_units_relations_basis_and_reviews(served):
    p = paper(A)
    got = labelled(p)[REPO]
    s = exported("a")
    assert got["semantic"]["state"] == "loaded"
    assert got["semantic"]["digest"] == s["digest"]
    assert got["semantic"]["paper"] == {k: v for k, v in s["papers"]["P"].items()
                                        if k not in ("revision", "paper_version")}
    [line] = lines(papers.paper_page(p))
    block = line[line.index('<div class="semantic'):]
    release = s["audit"]["release"]
    # The audit's author, and the authors of the readings counted.
    assert "by A. Auditor" in line and "the audit&#x27;s readings, by A. Auditor" in block
    # Units are named, and each unit is counted apart.
    rows = re.findall(r"<li>(.*?)</li>", block)
    assert [r[:r.index("</strong>")] for r in rows] == [
        "<strong>5 statements, 4 linked to 3 declarations.",
        "<strong>1 notation record, 1 linked to 1 declaration.",
        "<strong>1 proof step (1 equation), 1 linked to 1 declaration."]
    statements, notation, steps = rows
    # Every count of the summary is shown as it is, with MachineChecked's words, linked to the
    # claims it counts in this audit's Overview; zero counts are left out.
    p_ = s["papers"]["P"]
    for unit, row in zip(("statements", "notation", "proof_steps"), rows):
        for dimension, param, table in (
                ("coverage", "coverage", p_["coverage"]["audit"][unit]),
                ("basis", "basis", p_["basis"]["audit"][unit]),
                ("step_review" if unit == "proof_steps" else "review", "review", p_["review"][unit]),
                ("findings", "finding", p_["findings"][unit])):
            for key, n in table.items():
                text = f">{label(dimension, key)} ({n})</a>"
                assert (text in row) == (n > 0), (unit, key)
                if n:
                    href = link(A_URL, release, set="audit", unit=unit, **{param: key})
                    assert f'<a href="{href}"' in row
    # A reviewed composition and a checked bridge are bases of statements counted under one
    # relation, never another coverage category.
    assert f">{label('coverage', 'full')} (3)</a>" in statements
    assert f">{label('basis', 'reviewed_composition')} (1)</a>" in statements
    assert f">{label('basis', 'direct')} (1)</a>" in statements
    assert label("basis", "reviewed_composition") not in statements.split("Evidence basis:")[0]
    # Unresolved and not assessed stay apart; the open question is a link to those claims.
    assert f">{label('coverage', 'unresolved')} (1)</a>" in statements
    assert f">{label('coverage', 'not_assessed')} (1)</a>" in statements
    assert link(A_URL, release, set="audit", unit="statements", finding="open-question") in statements
    # No score, no percentage, no total.
    assert "%" not in re.sub(r'href="[^"]*"', "", block) and "total" not in block
    # Where it was read from, and the pins it names.
    assert f'<a href="{A_URL}data/index.json">' in block
    assert f"release <code>{release}</code>" in block and s["digest"][:12] in block
    assert "Counted apart" not in block


@needs_summary_support
def test_two_audits_of_one_repository_keep_their_own_summaries(served):
    """Each audit line shows its own summary, author and release; neither takes the other's
    counts, and the first audit's claims are the ones the page draws on."""
    p = paper(A, B)
    audits = labelled(p)
    assert audits[REPO]["semantic"]["digest"] == exported("a")["digest"]
    assert audits[f"{REPO}@2"]["semantic"]["digest"] == exported("b")["digest"]
    line_a, line_b = lines(papers.paper_page(p))
    ra, rb = exported("a")["audit"]["release"], exported("b")["audit"]["release"]
    assert "by A. Auditor" in line_a and "by B. Auditor" not in line_a
    assert "by B. Auditor" in line_b and "by A. Auditor" not in line_b
    for line, mine, other, url in ((line_a, ra, rb, A_URL), (line_b, rb, ra, B_URL)):
        hrefs = re.findall(r'href="([^"]*overview[^"]*)"', line)
        assert hrefs and all(h.startswith(html.escape(papers.reader_url(url)) + f"#/r/{mine}/")
                             for h in hrefs)
        assert other not in line
    assert f'data-digest="{exported("a")["digest"]}"' in line_a
    assert f'data-digest="{exported("b")["digest"]}"' in line_b
    # The counts are each audit's own.
    assert f">{label('coverage', 'full')} (3)</a>" in line_a
    assert f">{label('coverage', 'full')} (2)</a>" in line_b
    assert label("coverage", "related") not in line_a and label("coverage", "related") in line_b
    # B's review is recorded with its provenance, by its reviewer, as a set counted apart.
    assert f">{label('review', 'independent')} (1)</a>" in line_b
    assert label("review", "independent") not in line_a
    assert "Counted apart: <a href=" in line_b and ">Reviews by B. Reviewer</a>" in line_b
    assert link(B_URL, rb, set="review:human:B.-Reviewer", unit="statements") in line_b
    # The page's data keeps each audit's summary on its own entry.
    index = build.write_paper(Path(served[A_URL]).parent / "out", p, None,
                              build.page_audits(audits, None, None))
    entries = index["paper"]["formalisations"][0]["audits"]
    assert [a["semantic"]["digest"] for a in entries] == [exported("a")["digest"],
                                                          exported("b")["digest"]]
    assert index["audits"][REPO]["url"] == A_URL


@needs_summary_support
def test_strings_of_a_summary_are_escaped(served):
    edit_index(served[B_URL], lambda idx: idx["semantic"]["sets"][1]["reviewer"].update(
        name='<script>alert("x")</script>'))
    p = paper(B)
    labelled(p)
    [line] = lines(papers.paper_page(p))
    assert "<script>" not in line and "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in line


@needs_summary_support
def test_a_count_the_summary_does_not_give_is_never_shown_as_zero():
    words = summary.support()["words"]
    rec = {"state": "loaded", "release": "r", "commit": "c" * 40, "selected": "audit",
           "sets": [{"id": "audit", "kind": "audit", "by": []}],
           "paper": {"inventory": {"statements": {"records": 2}},
                     "coverage": {"audit": {"statements": {"full": 2}}}}}
    shown = summary.html(rec, "/read/?audit=x")
    assert f">{html.escape(words['coverage']['full']['label'], quote=True)} (2)</a>" in shown
    assert "(0)" not in shown and "Evidence basis" not in shown and "Reviews" not in shown
    assert "<strong>2 statements.</strong>" in shown


# -- the snapshot and the follow check ---------------------------------------------------------

def test_a_snapshot_keeps_each_summary_and_renders_it_without_the_network(tmp_path, monkeypatch,
                                                                           served):
    snap = prepare.prepare(registry(tmp_path, paper(A, B)), tmp_path / "snapshot", None,
                           log=lambda m: None)
    recs = snap["audits"]["curated:even-sums"]
    for key, name, url in ((REPO, "a", A_URL), (f"{REPO}@2", "b", B_URL)):
        rec = recs[key]["semantic"]
        assert rec["url"] == url + "data/index.json" and rec["schema"] == summary.SCHEMA
        assert rec["digest"] == exported(name)["digest"]
        assert rec["state"] == ("loaded" if summary.support() else "unsupported")
    no_network(monkeypatch)
    r = reader(tmp_path)
    build.build(tmp_path / "a", r, tmp_path / "snapshot")
    build.build(tmp_path / "b", r, tmp_path / "snapshot")
    assert tree(tmp_path / "a") == tree(tmp_path / "b")
    built = json.loads((tmp_path / "a" / "build.json").read_text())
    assert [a["semantic"]["digest"] for a in built["papers"]["curated:even-sums"][0]["audits"]] \
        == [exported("a")["digest"], exported("b")["digest"]]
    page = (tmp_path / "a" / "papers" / "even-sums" / "index.html").read_text()
    assert page.count('class="semantic small"') == (2 if summary.support() else 0)


def test_a_summary_only_republish_refreshes_the_tracked_publication(served):
    """An audit exported again with other readings, at the same release and project commit, is a
    new publication (its descriptor is written again), so the follow check rebuilds the site;
    the rebuild reads the new summary."""
    p = paper(A)
    before = claims.audits_for(p, log=lambda m: None)[REPO]
    used = prepare.audit_versions({REPO: before})
    assert follow.moved([p], used) == []
    root = served[A_URL]

    def reread(idx):
        cov = idx["semantic"]["papers"]["P"]["coverage"]["audit"]["statements"]
        cov["full"], cov["partial"] = cov["full"] - 1, cov["partial"] + 1
        idx["semantic"]["digest"] = "5" * 64
    edit_index(root, reread)
    d = json.loads((root / "audit.json").read_text())
    (root / "audit.json").write_text(json.dumps({**d, "created": "2026-10-28T09:00:00+00:00"}))
    assert follow.moved([p], used) == [f"{follow.audit_key(A_URL)}: publication changed"]
    after = claims.audits_for(p, log=lambda m: None)[REPO]
    assert after["release"] == before["release"] and after["commit"] == before["commit"]
    assert before["semantic"]["digest"] == exported("a")["digest"]
    assert after["semantic"]["digest"] == "5" * 64
