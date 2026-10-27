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
    def fetch(url, limit=100_000_000, headers=None):
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
        # The claim's record on the page carries the same code, beside the audit's own record.
        chunk = json.loads((d / "data" / "claims" / c["file"]).read_text())
        assert chunk["status_code"] == chunk["by_project"][REPO]["status_code"] == \
            chunk["by_project"][REPO]["record"]["status_code"] == c["status_code"]
        # The displayed PDF is the audited one: the audit's exact places carry over.
        assert mine["anchor"] == by_number[c["number"]]["anchor"]
        assert mine["anchor"]["kind"] == "exact"
    # The static page and the papers list say an audit is published.
    assert papers.level(p) == "Audit published"


@needs_poppler
def test_a_place_the_audit_gives_approximately_stays_approximate(tmp_path, monkeypatch, served):
    """On the audited PDF, a statement the audit locates only approximately is drawn as
    approximate; the audit's exact places stay exact."""
    from prooflens import manifest as mf
    root = tmp_path / "audit"
    shutil.copytree(AUDIT, root)
    idx = json.loads((root / "data" / "index.json").read_text())
    row = idx["claims"][1]
    chunk = root / "data" / "claims" / row["file"]
    rec = json.loads(chunk.read_text())
    rec["anchor"]["kind"] = "approximate"
    row["anchor"] = mf.index_anchor(rec["anchor"], "approximate")
    chunk.write_text(json.dumps(rec))
    (root / "data" / "index.json").write_text(json.dumps(idx))

    def fetch(url, limit=100_000_000, headers=None):
        if url.startswith(AUDIT_URL) and (root / url[len(AUDIT_URL):]).is_file():
            return (root / url[len(AUDIT_URL):]).read_bytes()
        return served(url, limit)
    monkeypatch.setattr(claims, "fetch", fetch)
    index, _ = page_index(tmp_path, paper())
    kinds = {c["number"]: c["by_project"][REPO]["anchor"]["kind"] for c in index["claims"]}
    assert kinds.pop(row["number"]) == "approximate"
    assert set(kinds.values()) == {"exact"}


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
    exported = {c["number"]: c for c in audit_claims()}[missed["number"]]
    assert len(extra) == 1 and extra[0]["by_project"][REPO]["status_code"] == \
        exported["status_code"]
    # It is the audit's entry, under the audit's identifier, and attributed to the audit.
    assert extra[0]["projects"] == [REPO]
    meta = extra[0]["by_project"][REPO]["audit"]
    assert meta["claim"] == exported["id"] and meta["audit"] == AUDIT_URL
    assert meta["author"] == index["audits"][REPO]["author"]


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
    def fetch(url, limit=100_000_000, headers=None):
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


@needs_poppler
@pytest.mark.parametrize("failure, code", [(OSError("offline"), "audit.unavailable"),
                                           (None, "audit.incompatible")])
def test_each_statement_says_its_audit_did_not_load_rather_than_that_none_is_published(
        tmp_path, monkeypatch, served, failure, code):
    found = statements(tmp_path, paper())

    def fetch(url, limit=100_000_000, headers=None):
        if url.startswith(AUDIT_URL):
            if failure:
                raise failure
            return b'{"schema": "machinechecked/audit@0"}'
        return served(url, limit)
    monkeypatch.setattr(claims, "fetch", fetch)
    index, _ = page_index(tmp_path, paper(), found)
    assert index["claims"] and {c["by_project"][REPO]["status_code"]
                                for c in index["claims"]} == {code}
    # Without a registered audit, the same statements are only unlinked.
    index, _ = page_index(tmp_path, paper(audits=False), found)
    assert {c["by_project"][REPO]["status_code"] for c in index["claims"]} == {"link.none"}


def test_an_audit_that_fails_beside_one_that_loads_is_reported(tmp_path, served):
    """A repository's further audit that does not load is reported on its own line, on the
    papers list and in `/build.json`, while the page shows the audit that loaded."""
    missing = "https://audit.example/missing/"
    p = paper()
    p["formalisations"][0]["audits"].append({"url": missing, "author": "B. Author"})
    audits = claims.audits_for(p, log=lambda m: None)
    assert audits[REPO]["state"] == "loaded" and audits[f"{REPO}@2"]["state"] == "unavailable"
    build.label_audits(p, audits)
    out = tmp_path / "out"
    index = build.write_paper(out, p, None, build.page_audits(audits, None, None))
    assert index["audits"][REPO]["url"] == AUDIT_URL and index["audits"][REPO]["state"] == "loaded"
    assert [a.get("state") for a in index["paper"]["formalisations"][0]["audits"]] == \
        ["loaded", "unavailable"]
    assert papers.level(p) == "Audit needs attention"
    page = papers.paper_page(p)
    loaded, failed = [li for li in page.split("<li>") if "Open the audit" in li]
    assert 'class="btn primary"' in loaded and "Audit unavailable" not in loaded
    assert 'class="btn"' in failed and \
        f"Audit unavailable: offline: {missing}audit.json" in failed
    assert page.count("Audit unavailable") == 1 and "awaiting publication" not in page
    built = build.provenance(out, [p], "0")["papers"][p["id"]][0]
    assert built["audit"]["state"] == "loaded"
    assert [(a["url"], a["state"]) for a in built["audits"]] == [(AUDIT_URL, "loaded"),
                                                               (missing, "unavailable")]
    assert built["audits"][0]["release"] == audits[REPO]["release"]
    assert built["audits"][1]["detail"] == audits[f"{REPO}@2"]["detail"]


def test_an_audit_that_fails_to_load_does_not_rebuild_the_site_on_every_check(
        monkeypatch, served):
    """The build records the publication of a failed audit too: the check workflow rebuilds when
    it is republished, not every time it runs while the audit stays broken."""
    p = paper()
    state = {"descriptor": json.loads((AUDIT / "audit.json").read_text())}
    state["descriptor"]["papers"][0]["id"] = "curated:another-paper"

    def fetch(url, limit=100_000_000, headers=None):
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
    descriptor = json.loads((AUDIT / "audit.json").read_text())
    assert used == {follow.audit_key(AUDIT_URL): follow.publication(descriptor)}
    # MachineChecked's identity of the publication, and when its descriptor was written.
    assert used[follow.audit_key(AUDIT_URL)] == \
        f"{audits[REPO]['version']}@{descriptor['created']}"
    assert follow.moved([paper()], used) == []


@pytest.mark.parametrize("republish", [
    pytest.param(lambda d: {**d, "release": "r-republished",
                            "created": "2026-10-20T08:00:00+00:00"}, id="a new release"),
    pytest.param(lambda d: {**d, "created": "2026-10-20T08:00:00+00:00"},
                 id="the same release exported again"),
])
def test_an_audit_republished_at_the_same_commit_rebuilds_the_site(monkeypatch, served,
                                                                   republish):
    """The follow check rebuilds the site when a loaded audit is republished at the project
    commit it already had: with a new release, or the same release exported again (a newer
    MachineChecked, or another display, writes other data under the same release)."""
    p = paper()
    state = {"descriptor": json.loads((AUDIT / "audit.json").read_text())}

    def fetch(url, limit=100_000_000, headers=None):
        if url == AUDIT_URL + "audit.json":
            return json.dumps(state["descriptor"]).encode()
        return served(url, limit)
    monkeypatch.setattr(claims, "fetch", fetch)
    audits = claims.audits_for(p, log=lambda m: None)
    assert audits[REPO]["state"] == "loaded"
    used = prepare.audit_versions(audits)
    assert follow.moved([p], used) == []
    commit = state["descriptor"]["formalisation"]["commit"]
    state["descriptor"] = republish(state["descriptor"])
    assert state["descriptor"]["formalisation"]["commit"] == commit
    assert follow.moved([p], used) == [f"{follow.audit_key(AUDIT_URL)}: publication changed"]


def test_a_transient_failure_is_retried_and_a_missing_file_is_not(monkeypatch):
    """A host that answers a burst of requests with 503 does not make an audit unavailable; a
    404 is not retried."""
    import io
    import urllib.error
    calls = []

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout):
        calls.append(req.full_url)
        if req.full_url.endswith("busy") and len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, 503, "Service Unavailable", {}, None)
        if req.full_url.endswith("missing"):
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
        return Response(b"ok")
    monkeypatch.setattr(claims.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(claims.time, "sleep", lambda s: None)
    assert claims.fetch("https://audit.example/busy") == b"ok" and len(calls) == 2
    calls.clear()
    with pytest.raises(urllib.error.HTTPError):
        claims.fetch("https://audit.example/missing")
    assert len(calls) == 1
