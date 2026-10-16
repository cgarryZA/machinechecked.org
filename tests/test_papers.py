"""The registry and the paper pages built from it."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import papers  # noqa: E402


def test_the_registry_is_valid():
    ps = papers.load(ROOT / "registry")
    assert ps and all(p["id"] for p in ps)


def _registry(tmp_path, paper):
    (tmp_path / "papers").mkdir(parents=True)
    (tmp_path / "schema.json").write_text((ROOT / "registry" / "schema.json").read_text())
    (tmp_path / "papers" / "x.json").write_text(json.dumps(paper))
    return tmp_path


PAPER = {"id": "arxiv:2601.01234", "title": "A <b>bold</b> claim", "authors": ["A. Author"],
         "listing": "arxiv", "links": {"arxiv": "https://arxiv.org/abs/2601.01234"},
         "formalisations": [{"repository": "someone/proj", "commit": "a" * 40,
                             "stated_by": {"source": "formalization.yaml"},
                             "audits": [{"url": "https://someone.github.io/audit/",
                                         "author": "<script>x</script>"}]}]}


def test_registry_text_is_escaped_and_audits_open_in_the_reader(tmp_path):
    out = tmp_path / "out"
    papers.write(out, papers.load(_registry(tmp_path / "reg", PAPER)))
    page = (out / "papers" / "2601.01234" / "index.html").read_text()
    assert "<b>bold</b>" not in page and "&lt;b&gt;bold&lt;/b&gt;" in page
    assert "<script>x</script>" not in page
    assert "/read/?audit=https%3A%2F%2Fsomeone.github.io%2Faudit%2F" in page
    assert "Audit published" in page and "does not endorse" in page


@pytest.mark.parametrize("bad", [
    {"links": {"pdf": "javascript:alert(1)"}},
    {"formalisations": [{"repository": "x/y", "commit": "abc", "stated_by": {"source": "curated"}}]},
    {"id": "doi:10.1/x"},
])
def test_the_schema_refuses_bad_entries(tmp_path, bad):
    with pytest.raises(SystemExit):
        papers.load(_registry(tmp_path, {**PAPER, **bad}))


def test_a_repository_without_an_audit_says_nothing_about_lean(tmp_path):
    p = {**PAPER, "formalisations": [{"repository": "someone/proj", "commit": "b" * 40,
                                      "stated_by": {"source": "formalization.yaml"}}]}
    out = tmp_path / "out"
    papers.write(out, papers.load(_registry(tmp_path / "reg", p)))
    page = (out / "papers" / "2601.01234" / "index.html").read_text()
    assert "Lean repository linked" in page and "says nothing about what Lean establishes" in page


def test_discovered_entries_merge_and_delisting_removes_one_listing(tmp_path):
    reg = _registry(tmp_path / "reg", PAPER)
    (reg / "discovered").mkdir()
    found = {**PAPER, "title": "Found title", "formalisations": [
        {"repository": "someone/proj", "commit": "c" * 40, "stated_by": {"source": "formalization.yaml"}},
        {"repository": "other/proj", "commit": "d" * 40, "stated_by": {"source": "formalization.yaml"}}]}
    (reg / "discovered" / "2601.01234.json").write_text(json.dumps(found))
    [p] = papers.load(reg)
    # The maintained entry wins: its title, and its record (with the audit) of someone/proj.
    assert p["title"] == PAPER["title"]
    assert [f["repository"] for f in p["formalisations"]] == ["someone/proj", "other/proj"]
    assert p["formalisations"][0].get("audits")
    (reg / "delisted.json").write_text(json.dumps(
        [{"paper": "arxiv:2601.01234", "repository": "Other/Proj", "reason": "spam"}]))
    [p] = papers.load(reg)
    assert [f["repository"] for f in p["formalisations"]] == ["someone/proj"]


def test_every_listing_can_be_reported(tmp_path):
    out = tmp_path / "out"
    papers.write(out, papers.load(_registry(tmp_path / "reg", PAPER)))
    page = (out / "papers" / "2601.01234" / "index.html").read_text()
    assert "machinechecked.org/issues/new?title=Listing%3A%20someone/proj" in page
