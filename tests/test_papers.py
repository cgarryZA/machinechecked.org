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


READER = '<script type="module" crossorigin src="./assets/index-x.js"></script>\n<link rel="stylesheet" crossorigin href="./assets/index-y.css">'


def test_a_paper_page_is_the_reader_with_its_text_kept(tmp_path):
    p = {**PAPER, "title": "A </script><script>alert(1)</script> claim"}
    out = tmp_path / "out"
    papers.write(out, papers.load(_registry(tmp_path / "reg", p)), READER)
    page = (out / "papers" / "2601.01234" / "index.html").read_text()
    assert 'src="/read/assets/index-x.js"' in page and '<div id="app"></div>' in page
    assert "window.__MACHINECHECKED_PAPER__ = " in page
    # The registry's text cannot close the inline script.
    script = page.split("window.__MACHINECHECKED_PAPER__ = ", 1)[1].split("</script>", 1)[0]
    assert "<" not in script
    assert json.loads(script.rstrip().rsplit(";document", 1)[0])["title"] == p["title"]
    # The text is still in the page, for readers without JavaScript and for search engines.
    assert "&lt;/script&gt;" in page and "Lean formalisations" in page


def test_tex_in_titles_reads_as_text(tmp_path):
    from texmath import tex_text
    assert tex_text(r"Marton's Conjecture in $\mathbb{F}_2^n$") == "Marton's Conjecture in 𝔽₂ⁿ"
    assert tex_text(r"Erd\H{o}s on $L^p$") == "Erdős on Lᵖ"
    assert tex_text(r"$x^{ab}$") == "xᵃᵇ" and tex_text(r"$x^{\star}$") == "x^⋆"
    p = {**PAPER, "title": r"Sets in $\mathbb{R}^3$"}
    out = tmp_path / "out"
    papers.write(out, papers.load(_registry(tmp_path / "reg", p)))
    assert "Sets in ℝ³" in (out / "papers" / "index.html").read_text()
    assert "<title>Sets in ℝ³ — MachineChecked</title>" in (out / "papers" / "2601.01234" / "index.html").read_text()


def test_each_paper_has_a_badge_saying_what_is_listed(tmp_path):
    out = tmp_path / "out"
    papers.write(out, papers.load(_registry(tmp_path / "reg", PAPER)))
    svg = (out / "papers" / "2601.01234" / "badge.svg").read_text()
    assert svg.startswith("<svg") and "Audit published" in svg and "verified" not in svg.lower()
