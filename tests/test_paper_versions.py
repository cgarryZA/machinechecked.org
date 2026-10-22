"""A paper whose audits pin different versions of it gets a page per version: arXiv v1 at
`/papers/<id>/v1/` (also the paper's plain address) and the latest manuscript at
`/papers/<id>/manuscript-<commit>/`, each with its own PDF, statements and audits, and the
reader's version drop-down between them. The two audits are the synthetic toy export
(`fixtures/paper-audit/toy/`), its descriptor and index made to pin each version of a synthetic
arXiv paper (`write_version_fixture`)."""

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

    def fetch(url, limit=100_000_000):
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
