"""The network step and the render are separate: `prepare.py` reads what the site needs into a
snapshot, and `build.py` renders a snapshot without the network, the same way every time."""

import json
import sys
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import build  # noqa: E402
import claims  # noqa: E402
import prepare  # noqa: E402
from test_paper_audits import AUDIT, REPO, paper, served, needs_poppler  # noqa: E402,F401


def registry(tmp_path, *entries):
    reg = tmp_path / "registry"
    (reg / "papers").mkdir(parents=True)
    (reg / "schema.json").write_text((ROOT / "registry" / "schema.json").read_text())
    for i, e in enumerate(entries):
        (reg / "papers" / f"{i}.json").write_text(json.dumps(e))
    return reg


def reader(tmp_path):
    r = tmp_path / "reader"
    (r / "assets").mkdir(parents=True)
    (r / "index.html").write_text('<script type="module" src="./assets/index-x.js"></script>')
    (r / "theme.css").write_text(":root { --bg: #fff; }")
    return r


def tree(d: Path) -> dict:
    return {f.relative_to(d).as_posix(): f.read_bytes() for f in sorted(d.rglob("*")) if f.is_file()}


def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("the render used the network")
    monkeypatch.setattr(claims, "fetch", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)


@needs_poppler
def test_a_snapshot_renders_the_same_site_without_the_network(tmp_path, monkeypatch, served):
    snap = prepare.prepare(registry(tmp_path, paper()), tmp_path / "snapshot", tmp_path / "cache",
                           log=lambda m: None)
    assert snap["audits"]["curated:toy-paper"][REPO]["state"] == "loaded"
    assert snap["found"]["curated:toy-paper"]["claims"]
    assert list(snap["follow"]) == ["audit:https://audit.example/toy/"]
    no_network(monkeypatch)
    r = reader(tmp_path)
    build.build(tmp_path / "a", r, tmp_path / "snapshot")
    build.build(tmp_path / "b", r, tmp_path / "snapshot")
    assert tree(tmp_path / "a") == tree(tmp_path / "b")
    index = json.loads((tmp_path / "a" / "papers" / "toy-paper" / "data" / "index.json").read_text())
    assert index["audits"][REPO]["state"] == "loaded"
    assert {c["status_code"] for c in index["claims"]} >= {"formal.accepted", "formal.open"}
    # The audited PDF travels in the snapshot and reaches the page.
    [edition] = index["editions"]
    assert (tmp_path / "a" / "papers" / "toy-paper" / "data" / edition["pdf"]).read_bytes() == \
        (AUDIT / "data" / "papers" / "T.pdf").read_bytes()
    assert json.loads((tmp_path / "a" / "follow.json").read_text()) == snap["follow"]
    built = json.loads((tmp_path / "a" / "build.json").read_text())
    assert built["papers"]["curated:toy-paper"][0]["audit"]["state"] == "loaded"


def test_failures_are_recorded_as_failures(tmp_path, monkeypatch, served):
    def fetch(url, limit=None, headers=None):
        raise OSError("offline")
    monkeypatch.setattr(claims, "fetch", fetch)
    snap = prepare.prepare(registry(tmp_path, paper()), tmp_path / "snapshot", tmp_path / "cache",
                           log=lambda m: None)
    assert snap["found"]["curated:toy-paper"]["state"] == "unreadable"
    assert snap["audits"]["curated:toy-paper"][REPO]["state"] == "unavailable"
    no_network(monkeypatch)
    build.build(tmp_path / "out", reader(tmp_path), tmp_path / "snapshot")
    index = json.loads((tmp_path / "out" / "papers" / "toy-paper" / "data" / "index.json").read_text())
    assert index["audits"][REPO]["state"] == "unavailable"
    assert "awaiting publication" not in (tmp_path / "out" / "papers" / "toy-paper" / "index.html").read_text()


def test_an_offline_snapshot_reads_nothing_and_says_so(tmp_path, monkeypatch):
    no_network(monkeypatch)
    snap = prepare.prepare(registry(tmp_path, paper()), tmp_path / "snapshot", tmp_path / "cache",
                           follow=True, offline=True, log=lambda m: None)
    assert snap["found"]["curated:toy-paper"]["state"] == "not-read"
    assert snap["audits"]["curated:toy-paper"][REPO]["state"] == "unavailable"
    assert snap["follow"] == {}


@pytest.mark.parametrize("damage, reason", [
    (lambda d: (d / "snapshot.json").unlink(), "no readable snapshot"),
    (lambda d: (d / "snapshot.json").write_text("{"), "no readable snapshot"),
    (lambda d: (d / "snapshot.json").write_text('{"schema": "other"}'), "not a machinechecked.org"),
    (lambda d: (d / "snapshot.json").write_text(json.dumps(
        {"schema": prepare.SCHEMA, "registry": [], "found": {}, "audits": {}})), "has no follow"),
    (lambda d: (d / "snapshot.json").write_text(json.dumps(
        {"schema": prepare.SCHEMA, "registry": [{**paper(), "links": {"pdf": "javascript:x"}}],
         "found": {}, "audits": {}, "follow": {}})), "curated:toy-paper"),
])
def test_a_missing_or_malformed_snapshot_stops_the_render(tmp_path, damage, reason):
    prepare.prepare(registry(tmp_path, paper()), tmp_path / "snapshot", None, offline=True,
                    log=lambda m: None)
    damage(tmp_path / "snapshot")
    with pytest.raises(SystemExit, match=reason):
        build.build(tmp_path / "out", reader(tmp_path), tmp_path / "snapshot")
