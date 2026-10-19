"""A published audit on its paper's page: the site fetches it, MachineChecked joins it with the
statements found in the paper's PDF, and the page keeps the audit's statuses, attribution and
locations. The audit is a synthetic export of MachineChecked's toy paper
(`fixtures/paper-audit/toy/`, its descriptor naming the public paper `curated:toy-paper`, and its
index's places those of its exported anchors); `fixtures/toy-audit-0.1.5/` holds another revision
of the same paper's PDF."""

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build  # noqa: E402
import claims  # noqa: E402
import follow  # noqa: E402
import papers  # noqa: E402
import prepare  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
AUDIT = FIXTURES / "paper-audit" / "toy"
AUDIT_URL = "https://audit.example/toy/"
REPO = "cgarryZA/MachineChecked"
PDFS = {"https://paper.example/toy.pdf": AUDIT / "data" / "papers" / "T.pdf",
        "https://paper.example/toy-older.pdf": FIXTURES / "toy-audit-0.1.5" / "data" / "papers" / "T.pdf"}

needs_poppler = pytest.mark.skipif(shutil.which("pdftotext") is None,
                                   reason="reading a PDF's statements needs poppler")


def paper(pdf="https://paper.example/toy.pdf", audits=True):
    return {"id": "curated:toy-paper", "title": "A Toy Paper on Even and Triangular Numbers",
            "authors": ["A. Author"], "listing": "curated", "links": {"pdf": pdf},
            "formalisations": [{"repository": REPO, "commit": "9" * 40,
                                "stated_by": {"source": "curated"},
                                **({"audits": [{"url": AUDIT_URL, "author": "A. Author"}]}
                                   if audits else {})}]}


@pytest.fixture
def served(monkeypatch):
    """The audit and the PDFs, served from the fixtures; anything else is offline."""
    def fetch(url, limit=100_000_000):
        if url.startswith(AUDIT_URL):
            path = AUDIT / url[len(AUDIT_URL):]
            if path.is_file():
                return path.read_bytes()
        if url in PDFS:
            return PDFS[url].read_bytes()
        raise OSError(f"offline: {url}")
    monkeypatch.setattr(claims, "fetch", fetch)
    monkeypatch.setattr(claims, "alignment", lambda repo, commit: None)
    return fetch


def statements(tmp_path, p):
    (tmp_path / "cache").mkdir(exist_ok=True)
    return claims.claims_for(p, tmp_path / "cache", log=lambda m: None)


def page_index(tmp_path, p, found="read"):
    """The page's index as the build writes it, and its directory."""
    if found == "read":
        found = statements(tmp_path, p)
    audits = claims.audits_for(p, log=lambda m: None)
    out = tmp_path / "out"
    return build.write_paper(out, p, found, audits), out / "papers" / papers.slug(p["id"])


def audit_claims():
    return json.loads((AUDIT / "data" / "index.json").read_text())["claims"]


@needs_poppler
def test_a_published_audit_supplies_statuses_attribution_and_exact_places(tmp_path, served):
    p = paper()
    index, d = page_index(tmp_path, p)
    assert index["audits"][REPO]["state"] == "loaded"
    assert index["audits"][REPO]["author"] and index["audits"][REPO]["release"]
    by_number = {c["number"]: c for c in audit_claims()}
    assert len(index["claims"]) == len(by_number)
    for c in index["claims"]:
        mine = c["by_project"][REPO]
        # The audit's own code, unchanged, at the top level and for its project.
        assert c["status_code"] == mine["status_code"] == by_number[c["number"]]["status_code"]
        # The displayed PDF is the audited one: the audit's exact places carry over.
        assert mine["anchor"] == by_number[c["number"]]["anchor"]
        assert mine["anchor"]["kind"] == "exact"
    # The static page and the papers list say an audit is published.
    assert papers.level(p) == "Audit published"


@needs_poppler
def test_another_revision_of_the_pdf_gets_no_coordinates_from_the_audit(tmp_path, served):
    index, d = page_index(tmp_path, paper("https://paper.example/toy-older.pdf"))
    assert index["audits"][REPO]["state"] == "loaded"
    for c in index["claims"]:
        anchor = c["by_project"][REPO].get("anchor")
        assert anchor is None or anchor["kind"] != "exact"
    # The audited revision stays available beside the original.
    [edition] = index["editions"]
    assert (d / "data" / "papers" / f"{edition['edition']}.pdf").read_bytes() == \
        (AUDIT / "data" / "papers" / "T.pdf").read_bytes()


@needs_poppler
def test_an_audit_entry_the_pdf_headings_miss_is_still_on_the_page(tmp_path, served):
    p = paper()
    found = statements(tmp_path, p)
    missed = found["claims"].pop(0)
    index, _ = page_index(tmp_path, p, found)
    extra = [c for c in index["claims"] if c["number"] == missed["number"]]
    assert len(extra) == 1 and extra[0]["by_project"][REPO]["status_code"] == \
        {c["number"]: c for c in audit_claims()}[missed["number"]]["status_code"]


def test_without_a_readable_pdf_the_audit_still_lists_its_claims(tmp_path, served):
    index, _ = page_index(tmp_path, paper(), found=None)
    assert sorted(c["number"] for c in index["claims"]) == \
        sorted(c["number"] for c in audit_claims())


@pytest.mark.parametrize("failure, code, level", [
    (OSError("offline"), "audit.unavailable", "Audit needs attention"),
    (None, "audit.incompatible", "Audit needs attention"),
])
def test_a_registered_audit_that_fails_to_load_is_not_an_absent_audit(
        tmp_path, monkeypatch, served, failure, code, level):
    def fetch(url, limit=100_000_000):
        if url.startswith(AUDIT_URL):
            if failure:
                raise failure
            return b'{"schema": "machinechecked/audit@0"}'
        return served(url, limit)
    monkeypatch.setattr(claims, "fetch", fetch)
    p = paper()
    index, _ = page_index(tmp_path, p, found=None)
    assert index["audits"][REPO]["state"] == code.split(".")[1]
    assert index["audits"][REPO]["detail"]
    assert papers.level(p) == level
    page = papers.paper_page(p)
    assert "Audit " + code.split(".")[1] in page and "awaiting publication" not in page

    # A repository with no audit registered says only that.
    q = paper(audits=False)
    index, _ = page_index(tmp_path, q, found=None)
    assert index["audits"] == {}
    assert papers.level(q) == "Lean repository linked"
    assert "Audit: awaiting publication" in papers.paper_page(q)


def test_an_audit_that_fails_to_load_does_not_rebuild_the_site_on_every_check(
        monkeypatch, served):
    """The build records the publication of a failed audit too: the check workflow rebuilds when
    it is republished, not every time it runs while the audit stays broken."""
    p = paper()
    state = {"descriptor": json.loads((AUDIT / "audit.json").read_text())}
    state["descriptor"]["papers"][0]["id"] = "curated:another-paper"

    def fetch(url, limit=100_000_000):
        if url == AUDIT_URL + "audit.json":
            return json.dumps(state["descriptor"]).encode()
        return served(url, limit)
    monkeypatch.setattr(claims, "fetch", fetch)
    audits = claims.audits_for(p, log=lambda m: None)
    assert audits[REPO]["state"] == "incompatible"
    used = prepare.audit_versions(audits)
    assert follow.moved([p], used) == []
    state["descriptor"]["release"] = "r-republished"
    assert follow.moved([p], used) == [f"{follow.audit_key(AUDIT_URL)}: publication changed"]


def test_a_loaded_audit_records_the_publication_it_was_read_at(served):
    audits = claims.audits_for(paper(), log=lambda m: None)
    assert audits[REPO]["state"] == "loaded"
    used = prepare.audit_versions(audits)
    assert used == {follow.audit_key(AUDIT_URL): audits[REPO]["version"]}
    assert follow.moved([paper()], used) == []
