"""Several audits of one paper version: the site records each audited repository's GitHub star
count, and the reader opens on the most-starred audit (MachineChecked #212). Without a count for
every audit, the registry's order holds. The two audits are the synthetic toy export
(`fixtures/paper-audit/toy/`), the second made another repository's."""

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
import prepare  # noqa: E402
from test_paper_audits import AUDIT, AUDIT_URL, PDFS, REPO, needs_poppler, paper  # noqa: E402
from test_snapshot import no_network, reader, registry  # noqa: E402

OTHER, OTHER_URL = "synthetic/second", "https://audit.example/second/"


def second(out: Path) -> Path:
    """The toy audit, published as `OTHER`'s."""
    shutil.copytree(AUDIT, out)
    d = json.loads((out / "audit.json").read_text())
    d["formalisation"]["repository"] = OTHER
    (out / "audit.json").write_text(json.dumps(d))
    idx = json.loads((out / "data" / "index.json").read_text())
    idx["project"]["repository"] = OTHER
    (out / "data" / "index.json").write_text(json.dumps(idx))
    return out


@pytest.fixture
def served(tmp_path, monkeypatch):
    """Both audits, the PDF and GitHub's answers (`answers`: repository → star count, or an
    exception to raise); anything else is offline."""
    roots = {AUDIT_URL: AUDIT, OTHER_URL: second(tmp_path / "second")}
    answers = {}

    def fetch(url, limit=100_000_000, headers=None):
        for base, root in roots.items():
            if url.startswith(base) and (root / url[len(base):]).is_file():
                return (root / url[len(base):]).read_bytes()
        if url in PDFS:
            return PDFS[url].read_bytes()
        repo = url.removeprefix("https://api.github.com/repos/")
        if repo in answers:
            if isinstance(answers[repo], Exception):
                raise answers[repo]
            return json.dumps({"full_name": repo, "stargazers_count": answers[repo]}).encode()
        raise OSError(f"offline: {url}")
    monkeypatch.setattr(claims, "fetch", fetch)
    monkeypatch.setattr(claims, "alignment", lambda repo, commit: None)
    return answers


def entry():
    p = paper()
    p["formalisations"].append({"repository": OTHER, "commit": "8" * 40,
                                "stated_by": {"source": "curated"},
                                "audits": [{"url": OTHER_URL, "author": "B. Author"}]})
    return p


def site(tmp_path, monkeypatch):
    snap = prepare.prepare(registry(tmp_path, entry()), tmp_path / "snapshot", tmp_path / "cache",
                           log=lambda m: None)
    no_network(monkeypatch)
    build.build(tmp_path / "out", reader(tmp_path), tmp_path / "snapshot")
    page = tmp_path / "out" / "papers" / "toy-paper" / "data" / "index.json"
    return snap, json.loads(page.read_text())


@needs_poppler
def test_the_most_starred_audit_is_the_default(tmp_path, monkeypatch, served):
    served.update({REPO: 3, OTHER: 12})
    snap, idx = site(tmp_path, monkeypatch)
    assert snap["stars"] == {REPO: 3, OTHER: 12}
    assert (idx["audit_order"], idx["audit_order_by"]) == ([OTHER, REPO], "stars")
    assert idx["stars"] == {OTHER: 12, REPO: 3}
    # Each audit keeps its own statuses; the default one gives the summary's.
    assert all(set(c["by_project"]) == {REPO, OTHER} for c in idx["claims"])


@needs_poppler
@pytest.mark.parametrize("failure", [OSError("rate limited"), ValueError("not JSON"), -1])
def test_without_every_count_the_registry_order_holds(tmp_path, monkeypatch, served, failure):
    served.update({REPO: 3, OTHER: failure})
    snap, idx = site(tmp_path, monkeypatch)
    assert snap["stars"] == {REPO: 3, OTHER: None}
    assert (idx["audit_order"], idx["audit_order_by"]) == ([REPO, OTHER], "listing")


def test_a_count_is_asked_with_the_token_when_there_is_one(monkeypatch):
    asked = []

    def fetch(url, limit=0, headers=None):
        asked.append((url, (headers or {}).get("Authorization")))
        return b'{"stargazers_count": 5}'
    monkeypatch.setattr(claims, "fetch", fetch)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert claims.stars("a/b") == 5
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    assert claims.stars("a/b") == 5
    assert asked == [("https://api.github.com/repos/a/b", None),
                     ("https://api.github.com/repos/a/b", "Bearer t")]


def test_an_older_snapshot_without_counts_still_renders(tmp_path):
    out = tmp_path / "snap"
    (out / "pdfs").mkdir(parents=True)
    (out / "snapshot.json").write_text(json.dumps({
        "schema": prepare.SCHEMA, "registry": [], "found": {}, "found_versions": {},
        "audits": {}, "follow": {}}))
    assert prepare.read(out)["stars"] == {}
