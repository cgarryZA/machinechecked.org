"""The site's release wiring: the package it is built with, what a build records, and the check
that starts a rebuild."""

import json
import sys
from importlib.metadata import version
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build  # noqa: E402
import follow  # noqa: E402


def test_a_package_without_what_the_site_uses_stops_the_build(monkeypatch):
    monkeypatch.setattr(build, "REQUIRED_API", {**build.REQUIRED_API,
                                                "prooflens.paper": ("apply_audits", "gone_api"),
                                                "prooflens.nowhere": ("x",)})
    with pytest.raises(SystemExit) as e:
        build.require_package()
    assert "prooflens.paper.gone_api" in str(e.value) and "prooflens.nowhere" in str(e.value)
    assert "TOOL_VERSION pins" in str(e.value)


def test_a_package_whose_page_writer_lacks_an_argument_the_site_passes_stops_the_build(
        monkeypatch):
    assert {"stars", "claim_maps"} <= set(build.REQUIRED_PARAMETERS)
    monkeypatch.setattr(build, "REQUIRED_PARAMETERS", (*build.REQUIRED_PARAMETERS, "gone"))
    with pytest.raises(SystemExit, match=r"write_paper_site\(gone=…\)"):
        build.require_package()


def test_the_installed_package_must_be_the_pinned_release(monkeypatch):
    have = version("machinechecked")
    assert build.require_package() == have
    monkeypatch.setattr(build, "pinned", lambda: have)
    assert build.require_package(exact=True) == have
    monkeypatch.setattr(build, "pinned", lambda: "0.0.0")
    with pytest.raises(SystemExit, match="pins 0.0.0"):
        build.require_package(exact=True)
    # A pinned commit is installed from git; its version number is the package's own.
    monkeypatch.setattr(build, "pinned", lambda: "a" * 40)
    assert build.require_package(exact=True) == have


def test_a_build_records_what_it_was_made_from(tmp_path, monkeypatch):
    reader = tmp_path / "reader"
    (reader / "assets").mkdir(parents=True)
    (reader / "index.html").write_text('<script type="module" src="./assets/index-x.js"></script>')
    (reader / "theme.css").write_text(":root { --bg: #fff; }")
    monkeypatch.setenv("GITHUB_SHA", "f" * 40)
    import prepare
    snapshot = tmp_path / "snapshot"
    prepare.prepare(ROOT / "registry", snapshot, None, offline=True, log=lambda m: None)
    out = tmp_path / "out"
    build.build(out, reader, snapshot)
    record = json.loads((out / "build.json").read_text())
    assert record["tool_version"] == build.pinned()
    assert record["machinechecked"] == version("machinechecked")
    assert record["site_commit"] == "f" * 40 and len(record["reader_sha256"]) == 64
    import papers
    assert set(record["papers"]) == {p["id"] for p in papers.load(ROOT / "registry")}
    # The digest is the reader's files: another reader is another digest.
    (reader / "theme.css").write_text(":root { --bg: #000; }")
    build.build(out, reader, snapshot)
    assert json.loads((out / "build.json").read_text())["reader_sha256"] != record["reader_sha256"]


@pytest.mark.parametrize("published, moved, code", [
    (OSError("unreachable"), [], 2),
    (b"not json", [], 2),
    (b"{}", [], 0),
    (b"{}", ["o/r@main: x -> y"], 1),
])
def test_the_follow_check_never_reads_a_failure_as_a_change(monkeypatch, published, moved, code):
    import claims

    def fetch(url, limit=None, headers=None):
        assert url == "https://site.example/follow.json"
        if isinstance(published, Exception):
            raise published
        return published
    monkeypatch.setattr(claims, "fetch", fetch)
    monkeypatch.setattr(follow, "moved", lambda ps, pub: moved)
    monkeypatch.setattr(sys, "argv", ["follow.py", "check", "https://site.example"])
    with pytest.raises(SystemExit) as e:
        follow.main()
    assert e.value.code == code
