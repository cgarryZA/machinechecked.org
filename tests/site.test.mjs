// The built site in a browser, with the reader TOOL_VERSION pins: what a new reader must still
// open before it is deployed. Run after `python scripts/build.py --out _site --claims-cache …`:
//   node tests/site.test.mjs [_site]
// Needs the `playwright` package (`npm install --no-save playwright@1.56.1`); set CHROMIUM to a
// browser binary if Playwright has none.
//
// Cases: a paper with two formalisations (the selector, and one project's links at a time), a
// paper whose audits pin two versions (a page per version, the drop-down between them, and each
// claim's link to what it became in the other version), a paper whose one audit read another
// PDF than arXiv's (shown at the audited version), a paper with no audit, a paper page with a
// published audit (a synthetic export of the toy paper, tests/fixtures/paper-audit/, joined by
// the site's own build code), a paper whose audits export semantic summaries
// (tests/fixtures/semantic-audit/: each summary in the Formalisations dialog as exported, and
// each count's link to that audit's filtered Overview), and audits opened in the reader from
// their data: the toy audit as this version exports it is the demo's; an export frozen from an
// older version (tests/fixtures/) must keep opening.

import { chromium } from "playwright";
import http from "node:http";
import os from "node:os";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const site = path.resolve(process.argv[2] || "_site");
const fixtures = path.join(here, "fixtures");
const types = { ".html": "text/html", ".json": "application/json", ".js": "text/javascript",
  ".mjs": "text/javascript", ".css": "text/css", ".woff2": "font/woff2", ".svg": "image/svg+xml",
  ".pdf": "application/pdf", ".webp": "image/webp" };

// The two-project case is synthetic: the live registry may contain only single-project papers.
const synthetic = fs.mkdtempSync(path.join(os.tmpdir(), "mc-site-status-"));
const made = spawnSync(process.env.PYTHON || "python3", ["-c", `
import sys
from pathlib import Path
from prooflens.paper import write_paper_site
write_paper_site(Path(sys.argv[1]), {
    "id": "synthetic:two-projects", "title": "Synthetic project selection", "authors": [], "links": {},
    "formalisations": [{"repository": "synthetic/alpha", "commit": "a" * 40},
                       {"repository": "synthetic/beta", "commit": "b" * 40}]},
    [], None, None, Path(sys.argv[2]))
`, synthetic, path.join(site, "read")], { encoding: "utf8" });
if (made.status !== 0) throw new Error(made.stderr);

// The site, frozen audit fixtures, and generated test data are served from separate roots.
const audited_site = fs.mkdtempSync(path.join(os.tmpdir(), "mc-site-audited-"));
const server = http.createServer((req, res) => {
  let url = decodeURIComponent(req.url.split("?")[0]);
  const base = url.startsWith("/synthetic/") ? synthetic : url.startsWith("/fixtures/") ? fixtures
    : url.startsWith("/audited/") ? audited_site : site;
  if (base === synthetic) url = url.slice("/synthetic".length);
  if (base === fixtures) url = url.slice("/fixtures".length);
  if (base === audited_site) url = url.slice("/audited".length);
  let p = path.join(base, url);
  if (fs.existsSync(p) && fs.statSync(p).isDirectory()) p = path.join(p, "index.html");
  if (!p.startsWith(base) || !fs.existsSync(p)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": types[path.extname(p)] || "application/octet-stream",
    "access-control-allow-origin": "*" });
  fs.createReadStream(p).pipe(res);
}).listen(0);
const origin = `http://127.0.0.1:${server.address().port}`;

// A paper page with a published audit, built by the site's own code (scripts/build.py) from the
// synthetic audit fixture, as a build fetches it; the displayed PDF is the audited one.
const toyPdf = `${origin}/fixtures/paper-audit/toy/data/papers/T.pdf`;
const built = spawnSync(process.env.PYTHON || "python3", ["-c", `
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[4])
import build, claims, papers
out, fixture, pdf = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
def fetch(url, limit=100_000_000, headers=None):
    if url.startswith("https://audit.example/toy/"):
        return (fixture / url[len("https://audit.example/toy/"):]).read_bytes()
    if url == "https://paper.example/toy.pdf":
        return (fixture / "data" / "papers" / "T.pdf").read_bytes()
    raise OSError("offline")
claims.fetch, claims.alignment, claims.view_pdf = fetch, lambda r, c: None, lambda p: pdf
p = {"id": "curated:toy-paper", "title": "A Toy Paper on Even and Triangular Numbers",
     "authors": ["A. Author"], "listing": "curated", "links": {"pdf": "https://paper.example/toy.pdf"},
     "formalisations": [{"repository": "cgarryZA/MachineChecked", "commit": "9" * 40,
                         "stated_by": {"source": "curated"},
                         "audits": [{"url": "https://audit.example/toy/", "author": "A. Author"}]}]}
(out / "cache").mkdir()
found = claims.claims_for(p, out / "cache", log=lambda m: None)
index = build.write_paper(out, p, found, claims.audits_for(p, log=lambda m: None))
assert index["audits"]["cgarryZA/MachineChecked"]["state"] == "loaded", index["audits"]
papers.write(out, [p], Path(sys.argv[5]).read_text(encoding="utf-8"))
`, audited_site, path.join(fixtures, "paper-audit", "toy"), toyPdf, path.join(here, "..", "scripts"),
  path.join(site, "read", "index.html")], { encoding: "utf8" });
if (built.status !== 0) throw new Error(built.stderr);
const toyIndex = JSON.parse(fs.readFileSync(path.join(audited_site, "papers", "toy-paper", "data", "index.json")));

// A paper whose two audits pin different versions (arXiv v1 and the latest manuscript, which
// changes one statement and replaces a remark), built by the site's own code from the synthetic
// audit fixture made to pin each (tests/test_paper_versions.py), and served at the root of its
// own origin: version pages are addressed from the site's root.
const versioned_site = fs.mkdtempSync(path.join(os.tmpdir(), "mc-site-versions-"));
const versionedBuild = spawnSync(process.env.PYTHON || "python3", ["-c", `
import sys, tempfile
from pathlib import Path
sys.path.insert(0, sys.argv[2]); sys.path.insert(0, sys.argv[3])
import build, claims, prepare
import test_paper_versions as t
from test_snapshot import registry
out, reader = Path(sys.argv[1]), Path(sys.argv[4])
work = Path(tempfile.mkdtemp())
roots = {t.V1_URL: t.write_version_fixture(work / "v1", t.V1),
         t.LATEST_URL: t.revise(t.write_version_fixture(work / "latest", t.MANUSCRIPT))}
pdf = (t.AUDIT / "data" / "papers" / "T.pdf").read_bytes()
def fetch(url, limit=100_000_000, headers=None):
    for base, root in roots.items():
        if url.startswith(base) and (root / url[len(base):]).is_file():
            return (root / url[len(base):]).read_bytes()
    if url.startswith("https://export.arxiv.org/pdf/2601.00001"):
        return pdf
    raise OSError("offline")
claims.fetch, claims.alignment = fetch, lambda r, c: None
prepare.prepare(registry(work, t.entry(t.TWO)), work / "snapshot", work / "cache", log=lambda m: None)
build.build(out, reader, work / "snapshot")
`, versioned_site, path.join(here, "..", "scripts"), here, path.join(site, "read")], { encoding: "utf8" });
if (versionedBuild.status !== 0) throw new Error(versionedBuild.stderr);
const versionedServer = http.createServer((req, res) => {
  let p = path.join(versioned_site, decodeURIComponent(req.url.split("?")[0]));
  if (fs.existsSync(p) && fs.statSync(p).isDirectory()) p = path.join(p, "index.html");
  if (!p.startsWith(versioned_site) || !fs.existsSync(p)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": types[path.extname(p)] || "application/octet-stream" });
  fs.createReadStream(p).pipe(res);
}).listen(0);
const versionedOrigin = `http://127.0.0.1:${versionedServer.address().port}`;
const versionIndex = (dir) => JSON.parse(fs.readFileSync(path.join(versioned_site, "papers", "2601.00001", dir, "data", "index.json")));

// A paper whose one audit pins the latest manuscript and read another PDF than arXiv's (#55),
// built by the site's own code: it is shown at the audited manuscript, not joined by printed
// number to the statements of arXiv's PDF. Served at the root of its own origin.
const one_site = fs.mkdtempSync(path.join(os.tmpdir(), "mc-site-one-version-"));
const oneBuild = spawnSync(process.env.PYTHON || "python3", ["-c", `
import sys, tempfile
from pathlib import Path
sys.path.insert(0, sys.argv[2]); sys.path.insert(0, sys.argv[3])
import build, claims, prepare
import test_paper_versions as t
from test_snapshot import registry
out, reader = Path(sys.argv[1]), Path(sys.argv[4])
work = Path(tempfile.mkdtemp())
root = t.write_version_fixture(work / "latest", t.MANUSCRIPT)
older = (t.AUDIT.parent.parent / "toy-audit-0.1.5" / "data" / "papers" / "T.pdf").read_bytes()
def fetch(url, limit=100_000_000, headers=None):
    if url.startswith(t.LATEST_URL) and (root / url[len(t.LATEST_URL):]).is_file():
        return (root / url[len(t.LATEST_URL):]).read_bytes()
    if url.startswith("https://export.arxiv.org/pdf/2601.00001"):
        return older
    raise OSError("offline")
claims.fetch, claims.alignment = fetch, lambda r, c: None
prepare.prepare(registry(work, t.entry(t.TWO[:1])), work / "snapshot", work / "cache", log=lambda m: None)
build.build(out, reader, work / "snapshot")
`, one_site, path.join(here, "..", "scripts"), here, path.join(site, "read")], { encoding: "utf8" });
if (oneBuild.status !== 0) throw new Error(oneBuild.stderr);
const oneServer = http.createServer((req, res) => {
  let p = path.join(one_site, decodeURIComponent(req.url.split("?")[0]));
  if (fs.existsSync(p) && fs.statSync(p).isDirectory()) p = path.join(p, "index.html");
  if (!p.startsWith(one_site) || !fs.existsSync(p)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": types[path.extname(p)] || "application/octet-stream" });
  fs.createReadStream(p).pipe(res);
}).listen(0);
const oneOrigin = `http://127.0.0.1:${oneServer.address().port}`;
const oneIndex = JSON.parse(fs.readFileSync(path.join(one_site, "papers", "2601.00001", "data", "index.json")));

// A paper whose one repository has three audits, each with its semantic summary (#32), built by
// the site's own code from a snapshot of the exported audits in tests/fixtures/semantic-audit/
// (see tests/test_audit_summaries.py): A and B as exported, and C, A's export with a summary
// that names another release than its audit. Served at the root of its own origin, with its
// reader at /read/; the audits themselves are served at their addresses by the browser check.
const semanticFixtures = path.join(fixtures, "semantic-audit");
const C_URL = "https://audit.example/even-sums/c/";
const summarised_site = fs.mkdtempSync(path.join(os.tmpdir(), "mc-site-summaries-"));
const summarisedBuild = spawnSync(process.env.PYTHON || "python3", ["-c", `
import shutil, sys, tempfile
from pathlib import Path
sys.path.insert(0, sys.argv[2]); sys.path.insert(0, sys.argv[3])
import build, claims, prepare
import test_audit_summaries as t
from test_snapshot import registry
out, reader, c_url = Path(sys.argv[1]), Path(sys.argv[4]), sys.argv[5]
work = Path(tempfile.mkdtemp())
shutil.copytree(t.FIXTURES / "a", work / "c")
t.edit_index(work / "c", lambda idx: idx["semantic"]["audit"].update(release="v-another"))
roots = {t.A_URL: t.FIXTURES / "a", t.B_URL: t.FIXTURES / "b", c_url: work / "c"}
def fetch(url, limit=100_000_000, headers=None):
    for base, root in roots.items():
        if url.startswith(base) and (root / url[len(base):]).is_file():
            return (root / url[len(base):]).read_bytes()
    raise OSError("offline")
claims.fetch, claims.alignment = fetch, lambda r, c: None
prepare.prepare(registry(work, t.paper(t.A, t.B, (c_url, "A. Auditor"))), work / "snapshot", None,
                log=lambda m: None)
build.build(out, reader, work / "snapshot")
`, summarised_site, path.join(here, "..", "scripts"), here, path.join(site, "read"), C_URL], { encoding: "utf8" });
if (summarisedBuild.status !== 0) throw new Error(summarisedBuild.stderr);
const summarisedServer = http.createServer((req, res) => {
  let p = path.join(summarised_site, decodeURIComponent(req.url.split("?")[0]));
  if (fs.existsSync(p) && fs.statSync(p).isDirectory()) p = path.join(p, "index.html");
  if (!p.startsWith(summarised_site) || !fs.existsSync(p)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": types[path.extname(p)] || "application/octet-stream" });
  fs.createReadStream(p).pipe(res);
}).listen(0);
const summarisedOrigin = `http://127.0.0.1:${summarisedServer.address().port}`;

// The paper pages, from the data written beside each.
const pages = fs.readdirSync(path.join(site, "papers"), { withFileTypes: true })
  .filter((d) => d.isDirectory() && fs.existsSync(path.join(site, "papers", d.name, "data", "index.json")))
  .map((d) => ({ slug: d.name, index: JSON.parse(fs.readFileSync(path.join(site, "papers", d.name, "data", "index.json"))) }));
const audited = (p) => (p.index.paper.formalisations || []).some((f) => (f.audits || []).length);

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined });
let failures = 0;

async function check(name, fn) {
  const pg = await browser.newPage({ viewport: { width: 1300, height: 900 } });
  pg.setDefaultTimeout(10000);
  const errors = [];
  pg.on("pageerror", (e) => errors.push(String(e)));
  try {
    await fn(pg);
    assert.deepEqual(errors, [], "no page errors");
    console.log(`ok   ${name}`);
  } catch (e) {
    failures++;
    console.log(`FAIL ${name}: ${e.message}`);
    if (process.env.SHOTS) { fs.mkdirSync(process.env.SHOTS, { recursive: true }); await pg.screenshot({ path: path.join(process.env.SHOTS, `failure-${failures}.png`), fullPage: true }); }
  } finally {
    await pg.close();
  }
}

await check("a paper with two formalisations (synthetic)", async (pg) => {
  await pg.goto(`${origin}/synthetic/`);
  const select = pg.locator("select[aria-label='Formalisation shown']");
  await select.waitFor();
  assert.deepEqual(await select.locator("option").allTextContents(), ["synthetic/alpha", "synthetic/beta"]);
  await pg.selectOption("select[aria-label='Formalisation shown']", "synthetic/beta");
  assert.equal(new URL(pg.url()).searchParams.get("project"), "synthetic/beta");
});

await check("a paper page shows its published audit's statuses at the canonical address", async (pg) => {
  await pg.goto(`${origin}/audited/papers/toy-paper/`);
  await pg.waitForSelector("nav.toc li");
  // Each listed claim carries its audit's status, for the audit's own project; scope decisions
  // are listed on request.
  const shown = await pg.locator(".reader-layout > nav.toc li a").evaluateAll((as) =>
    as.map((a) => [decodeURIComponent(a.getAttribute("href").split("/").pop()), a.title]));
  const expected = toyIndex.claims.filter((c) => !c.status_code.startsWith("scope."))
    .map((c) => [c.id, c.by_project["cgarryZA/MachineChecked"].status]);
  assert.deepEqual(shown, expected);
  assert.ok(shown.some(([, s]) => s === "formal: accepted") && shown.some(([, s]) => s === "formal: open"));
  assert.doesNotMatch(await pg.locator("body").textContent(), /no audit published/);
});

await check("a deep link to an audited claim opens the audit's record at its exact place", async (pg) => {
  const claim = toyIndex.claims.find((c) => c.status_code === "formal.accepted");
  await pg.goto(`${origin}/audited/papers/toy-paper/#/r/paper/read/P/${encodeURIComponent(claim.id)}`);
  const side = pg.locator(".reader-layout > .claim-view");
  await side.getByText(claim.number, { exact: false }).first().waitFor();
  // The audit's record of the claim, at the audited revision and its exact place.
  const text = await side.textContent();
  assert.match(text, /audited revision/i);
  assert.match(text, /exact location/);
  assert.doesNotMatch(text, /approximate/i);
  assert.equal(new URL(pg.url()).pathname, "/audited/papers/toy-paper/");
});

for (const width of [1300, 390]) await check(`a paper's versions, each on its own page, at ${width}px`, async (pg) => {
  await pg.setViewportSize({ width, height: 900 });
  // arXiv's PDF of v1, offline.
  await pg.route("https://arxiv.org/**", (r) => r.fulfill({ path: path.join(fixtures, "paper-audit", "toy", "data", "papers", "T.pdf"), contentType: "application/pdf" }));
  const statuses = async () => (await pg.locator(".reader-layout > nav.toc li a").evaluateAll((as) =>
    as.map((a) => a.title))).sort();
  const expected = (dir) => versionIndex(dir).claims.filter((c) => !c.status_code.startsWith("scope."))
    .map((c) => c.by_project["cgarryZA/MachineChecked"].status).sort();
  // The plain address shows arXiv v1, with the drop-down between the two versions.
  await pg.goto(`${versionedOrigin}/papers/2601.00001/`);
  const select = pg.locator("select[aria-label='Paper version shown']");
  await select.waitFor();
  assert.deepEqual(await select.locator("option").allTextContents(), ["arXiv v1", "Latest manuscript (commit 956fe0b)"]);
  assert.equal(await select.inputValue(), "arxiv:2601.00001v1");
  await pg.waitForSelector("nav.toc li", { state: "attached" });
  // The contents list is a panel of its own at phone width.
  if (width > 700) assert.deepEqual(await statuses(), expected(""));
  // Its PDF is arXiv's v1.
  if (width > 700) await pg.locator(".pdf .page canvas").first().waitFor();
  // The panel names each audit's version and commit: this version's audit is the action, and the
  // other version's audit links to its page (#42).
  await pg.locator(".reader-tools button", { hasText: "Formalisations" }).click();
  const card = pg.locator(".info .card");
  await card.waitFor();
  const commit = versionIndex("").audits["cgarryZA/MachineChecked"].commit.slice(0, 12);
  assert.deepEqual((await card.locator(".audit.here .btn").allTextContents()).map((t) => t.trim()), ["Open the audit of arXiv v1"]);
  assert.match(await card.locator(".audit.here").textContent(), new RegExp(`by A\\. Author · commit ${commit}`));
  assert.deepEqual((await card.locator(".elsewhere a").allTextContents()).map((t) => t.trim()), ["Latest manuscript (commit 956fe0b)"]);
  assert.equal(new URL(await card.locator(".elsewhere a").getAttribute("href")).pathname, "/papers/2601.00001/manuscript-956fe0b/");
  await pg.getByRole("button", { name: "Close formalisations" }).click();
  // Choosing the manuscript opens its page, with the chosen formalisation and without a claim.
  await Promise.all([pg.waitForURL(/manuscript-956fe0b/), select.selectOption("manuscript:956fe0b")]);
  const url = new URL(pg.url());
  assert.equal(url.pathname, "/papers/2601.00001/manuscript-956fe0b/");
  assert.equal(url.searchParams.get("project"), "cgarryZA/MachineChecked");
  await pg.locator("select[aria-label='Paper version shown']").waitFor();
  assert.equal(await pg.locator("select[aria-label='Paper version shown']").inputValue(), "manuscript:956fe0b");
  await pg.waitForSelector("nav.toc li", { state: "attached" });
  await pg.locator(".reader-tools button", { hasText: "Formalisations" }).click();
  await pg.locator(".info .card").waitFor();
  assert.deepEqual((await pg.locator(".info .audit.here .btn").allTextContents()).map((t) => t.trim()), ["Open the audit of Latest manuscript (commit 956fe0b)"]);
  assert.deepEqual((await pg.locator(".info .elsewhere a").allTextContents()).map((t) => t.trim()), ["arXiv v1"]);
  await pg.getByRole("button", { name: "Close formalisations" }).click();
  // Each version's page keeps its own audit's statuses.
  if (width > 700) assert.deepEqual(await statuses(), expected("manuscript-956fe0b"));
  // The manuscript is shown from the PDF its audit carries, the audit's claims at their exact
  // places in it.
  if (width > 700) {
    await pg.locator(".pdf .page .band").first().waitFor();
    assert.equal(await pg.locator(".pdf .page .band.approximate").count(), 0);
  }
  // A deep link to a claim opens it in its own version's page.
  const claim = versionIndex("manuscript-956fe0b").claims.find((c) => c.status_code === "formal.accepted");
  await pg.goto(`${versionedOrigin}/papers/2601.00001/manuscript-956fe0b/#/r/paper/read/P/${encodeURIComponent(claim.id)}`);
  await pg.locator(".reader-layout > .claim-view").getByText(claim.number, { exact: false }).first().waitFor();
  assert.equal(await pg.locator("select[aria-label='Paper version shown']").inputValue(), "manuscript:956fe0b");
  assert.ok(await pg.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
  if (process.env.SHOTS) { fs.mkdirSync(process.env.SHOTS, { recursive: true }); await pg.screenshot({ path: path.join(process.env.SHOTS, `versions-${width}.png`) }); }
});

for (const width of [1300, 390]) await check(`a claim links to what it became in the other version, at ${width}px`, async (pg) => {
  await pg.setViewportSize({ width, height: 900 });
  await pg.route("https://arxiv.org/**", (r) => r.fulfill({ path: path.join(fixtures, "paper-audit", "toy", "data", "papers", "T.pdf"), contentType: "application/pdf" }));
  const v1 = versionIndex("v1"), latest = versionIndex("manuscript-956fe0b");
  const side = pg.locator(".reader-layout > .claim-view");
  const open = async (dir, claim) => {
    await pg.goto(`${versionedOrigin}/papers/2601.00001/${dir}#/r/paper/read/P/${encodeURIComponent(claim.id)}`);
    await side.getByText(claim.number, { exact: false }).first().waitFor();
  };
  const lines = async () => (await side.locator(".counterpart").allTextContents()).map((t) => t.trim());
  // On arXiv v1, a claim whose statement the manuscript changed links to it there.
  const theorem = v1.claims.find((c) => c.number === "Theorem 2.5");
  await open("v1/", theorem);
  await side.locator(".counterpart").first().waitFor();
  assert.deepEqual(await lines(), ["Theorem 2.5 in Latest manuscript (commit 956fe0b), statement changed."]);
  const there = theorem.counterparts[0].claims[0].id;
  assert.ok(latest.claims.some((c) => c.id === there));
  await Promise.all([pg.waitForURL(/manuscript-956fe0b/), side.locator(".counterpart a").click()]);
  const url = new URL(pg.url());
  assert.equal(url.pathname, "/papers/2601.00001/manuscript-956fe0b/");
  assert.equal(decodeURIComponent(url.hash.split("/").pop()), there);
  assert.equal(url.searchParams.get("project"), "cgarryZA/MachineChecked");
  // The manuscript's page opens on that claim, which links back.
  await pg.locator("select[aria-label='Paper version shown']").waitFor();
  assert.equal(await pg.locator("select[aria-label='Paper version shown']").inputValue(), "manuscript:956fe0b");
  await side.getByText("Theorem 2.5", { exact: false }).first().waitFor();
  await side.locator(".counterpart").first().waitFor();
  assert.deepEqual(await lines(), ["Theorem 2.5 in arXiv v1, statement changed."]);
  assert.equal(new URL(await side.locator(".counterpart a").getAttribute("href")).pathname, "/papers/2601.00001/v1/");
  // An unchanged claim says so; a claim the manuscript no longer has, and one it adds, say so
  // without a link.
  await open("v1/", v1.claims.find((c) => c.number === "Definition 1.1"));
  await side.locator(".counterpart").first().waitFor();
  assert.deepEqual(await lines(), ["Definition 1.1 in Latest manuscript (commit 956fe0b), same statement."]);
  await open("v1/", v1.claims.find((c) => c.number === "Remark 3.1"));
  await side.locator(".counterpart").first().waitFor();
  assert.deepEqual(await lines(), ["Removed in Latest manuscript (commit 956fe0b)."]);
  assert.equal(await side.locator(".counterpart a").count(), 0);
  await open("manuscript-956fe0b/", latest.claims.find((c) => c.number === "Remark 3.2"));
  await side.locator(".counterpart").first().waitFor();
  assert.deepEqual(await lines(), ["New in this version: not in arXiv v1."]);
  assert.ok(await pg.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
  if (process.env.SHOTS) { fs.mkdirSync(process.env.SHOTS, { recursive: true }); await pg.screenshot({ path: path.join(process.env.SHOTS, `counterparts-${width}.png`) }); }
});

for (const width of [1300, 390]) await check(`a paper whose one audit read another PDF opens at the audited version, at ${width}px`, async (pg) => {
  await pg.setViewportSize({ width, height: 900 });
  assert.equal(oneIndex.version, "manuscript:956fe0b");
  await pg.goto(`${oneOrigin}/papers/2601.00001/`);
  await pg.waitForSelector("nav.toc li", { state: "attached" });
  // The audit's own claims, with its statuses, on the PDF the audit read (served beside the page).
  if (width > 700) {
    const shown = await pg.locator(".reader-layout > nav.toc li a").evaluateAll((as) => as.map((a) => a.title));
    assert.deepEqual(shown.sort(), oneIndex.claims.filter((c) => !c.status_code.startsWith("scope."))
      .map((c) => c.by_project["cgarryZA/MachineChecked"].status).sort());
    await pg.locator(".pdf .page canvas").first().waitFor();
  }
  // One version: no drop-down; the panel names the version the audit pins.
  assert.equal(await pg.locator("select[aria-label='Paper version shown']").count(), 0);
  await pg.locator(".reader-tools button", { hasText: "Formalisations" }).click();
  await pg.locator(".info .card").waitFor();
  assert.deepEqual((await pg.locator(".info .audit.here .btn").allTextContents()).map((t) => t.trim()),
    ["Open the audit of Latest manuscript (commit 956fe0b)"]);
  // A claim opens at the audit's exact place.
  const claim = oneIndex.claims.find((c) => c.status_code === "formal.accepted");
  await pg.goto(`${oneOrigin}/papers/2601.00001/#/r/paper/read/P/${encodeURIComponent(claim.id)}`);
  const side = pg.locator(".reader-layout > .claim-view");
  await side.getByText(claim.number, { exact: false }).first().waitFor();
  const text = await side.textContent();
  assert.match(text, /exact location/);
  assert.doesNotMatch(text, /approximate/i);
  assert.ok(await pg.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
});

// Each listed audit's semantic summary (#32), in the pinned reader's Formalisations dialog: the
// counts its export gives, unit by unit, as the static page shows them, each linked to that
// audit's Overview filtered to the claims it counts; a summary the site could not show says why,
// under its audit's link.
await check("each listed audit shows the semantic summary it exports, linked to its Overview", async (pg) => {
  await pg.route("https://paper.example/**", (r) => r.fulfill({ path: path.join(semanticFixtures, "a", "data", "papers", "P.pdf"), contentType: "application/pdf" }));
  await pg.route("https://audit.example/even-sums/**", (r) => {
    const p = path.join(semanticFixtures, new URL(r.request().url()).pathname.slice("/even-sums/".length));
    if (!p.startsWith(semanticFixtures + path.sep) || !fs.existsSync(p)) return r.fulfill({ status: 404 });
    return r.fulfill({ path: p, contentType: types[path.extname(p)] || "application/octet-stream",
      headers: { "access-control-allow-origin": "*" } });
  });
  const exported = (name) => JSON.parse(fs.readFileSync(path.join(semanticFixtures, name, "data", "index.json"))).semantic;
  const PARAM = { coverage: "coverage", basis: "basis", review: "review", findings: "finding" };
  // Where a link leads: the page, the audit it opens, and the reader's route and filters.
  const target = (href) => {
    const u = new URL(href, summarisedOrigin), [route, query] = u.hash.slice(1).split("?");
    return { page: u.pathname, audit: u.searchParams.get("audit"), route, filters: Object.fromEntries(new URLSearchParams(query || "")) };
  };
  await pg.goto(`${summarisedOrigin}/papers/even-sums/`);
  await pg.waitForSelector("nav.toc li", { state: "attached" });
  await pg.locator(".reader-tools button", { hasText: "Formalisations" }).click();
  const panel = pg.locator(".info-dialog[open] .info");
  await panel.locator(".semantic").first().waitFor();
  assert.equal(await panel.locator(".semantic").count(), 2);
  const audits = [["a", "https://audit.example/even-sums/a/", "A. Auditor"], ["b", "https://audit.example/even-sums/b/", "B. Auditor"]];
  const links = [];
  for (const [name, url, author] of audits) {
    const s = exported(name), block = s.papers.P, release = s.audit.release;
    const sum = panel.locator(`.semantic[data-audit="${url}"]`);
    assert.equal(await sum.getAttribute("data-digest"), s.digest);
    // Under its own audit's line, which names its author.
    const [opens, says] = await sum.evaluate((el) => [el.previousElementSibling.querySelector("a").getAttribute("href"), el.previousElementSibling.textContent]);
    assert.equal(opens, "/read/?audit=" + encodeURIComponent(url));
    assert.ok(says.includes(`by ${author}`), says);
    // Every positive count of the export, and nothing else: the selected readings' correspondence
    // and evidence basis, and the reviews and findings, for each unit with claims.
    const want = [];
    for (const unit of ["statements", "notation", "proof_steps"]) {
      if (!(block.inventory[unit].records > 0)) continue;
      for (const [dim, table] of [["coverage", block.coverage[s.selected][unit]], ["basis", block.basis[s.selected][unit]],
                                  ["review", block.review[unit]], ["findings", block.findings[unit]]]) {
        for (const [key, n] of Object.entries(table)) if (n > 0) want.push([unit, dim, key, n]);
      }
    }
    const shown = await sum.locator(".unit [data-dimension] a").evaluateAll((as) => as.map((a) => ({
      unit: a.closest(".unit").dataset.unit, dim: a.closest("[data-dimension]").dataset.dimension,
      key: a.dataset.key, text: a.textContent, href: a.getAttribute("href") })));
    const key = ([unit, dim, k, n]) => `${unit} ${dim} ${k} ${n}`;
    assert.deepEqual(shown.map((x) => key([x.unit, x.dim, x.key, Number(x.text.match(/\((\d+)\)$/)?.[1])])).sort(), want.map(key).sort());
    for (const x of shown) {
      assert.deepEqual(target(x.href), { page: "/read/", audit: url, route: `/r/${release}/overview`,
        filters: { set: s.selected, unit: x.unit, [PARAM[x.dim]]: x.key } });
      links.push({ url, digest: s.digest, href: x.href, dim: x.dim, key: x.key, n: Number(x.text.match(/\((\d+)\)$/)[1]) });
    }
    // The static page shows the same summary: its words, counts and links.
    const plainPage = pg.locator(`.wrap .semantic[data-digest="${s.digest}"]`);
    assert.equal(await plainPage.locator("p").first().textContent(), (await sum.locator("p").first().textContent()).trim());
    assert.deepEqual((await plainPage.locator("ul strong").allTextContents()).map((t) => t.replace(/\.$/, "")),
      (await sum.locator(".unit .head").allTextContents()).map((t) => t.trim()));
    const pairs = (as) => as.map((a) => [a.textContent, a.getAttribute("href")]);
    assert.deepEqual((await plainPage.locator("ul a").evaluateAll(pairs)).map(([t, h]) => [t, target(h)]),
      shown.map((x) => [x.text, target(x.href)]));
    // Other sets of readings are linked, counted apart.
    const others = s.sets.filter((o) => o.id !== s.selected);
    const apart = await sum.locator(".others a").evaluateAll(pairs);
    assert.deepEqual(apart.map(([, h]) => target(h)), others.map((o) => ({ page: "/read/", audit: url, route: `/r/${release}/overview`, filters: { set: o.id, unit: "statements" } })));
    assert.deepEqual((await plainPage.locator("p a").evaluateAll(pairs)).map(([t, h]) => [t, target(h)]),
      apart.map(([t, h]) => [t, target(h)]));
    for (const [, h] of apart) links.push({ url, digest: s.digest, href: h, set: target(h).filters.set });
  }
  assert.ok(links.some((l) => l.set), "a set of readings counted apart");
  // The reviewed composition is a basis of statements counted under one correspondence, never a
  // correspondence of its own; unresolved and not assessed are counted apart.
  const a = panel.locator('.semantic[data-audit="https://audit.example/even-sums/a/"] .unit[data-unit="statements"]');
  assert.equal(await a.locator('[data-dimension="basis"] a[data-key="reviewed_composition"]').count(), 1);
  assert.equal(await a.locator('[data-dimension="coverage"] a[data-key="reviewed_composition"]').count(), 0);
  assert.equal(await a.locator('[data-dimension="coverage"] a[data-key="unresolved"]').count(), 1);
  assert.equal(await a.locator('[data-dimension="coverage"] a[data-key="not_assessed"]').count(), 1);
  // C's summary names another release than its audit: it says so under C's own link, with no count.
  const c = panel.locator(`.semantic-state[data-audit="${C_URL}"]`);
  assert.equal(await c.getAttribute("data-state"), "incompatible");
  assert.equal((await c.textContent()).trim(), "Semantic summary incompatible: The summary names another release than its audit.");
  assert.equal(await c.evaluate((el) => el.previousElementSibling.querySelector("a").getAttribute("href")), "/read/?audit=" + encodeURIComponent(C_URL));
  assert.match(await pg.locator(".wrap").innerHTML(), /Semantic summary incompatible: The summary names another release than its audit\./);
  await pg.getByRole("button", { name: "Close formalisations" }).click();
  // Each count's link, opened as from the paper's page, opens its audit's own Overview, with the
  // same summary, on the claims it counts.
  for (const l of links) {
    await pg.goto("about:blank");
    await pg.goto(new URL(l.href, summarisedOrigin).href);
    const overview = pg.locator(`.coverage .semantic[data-digest="${l.digest}"]`);
    await overview.waitFor();
    if (l.set) {
      assert.equal(await pg.locator(".coverage .readings select").inputValue(), l.set);
      continue;
    }
    await pg.locator(".coverage .count").filter({ hasText: new RegExp(`^${l.n} claims?\\b`) }).waitFor();
    const listed = pg.locator(".coverage .claims li");
    assert.equal(await listed.count(), l.n, `${l.href}`);
    if (l.dim !== "findings") {
      assert.deepEqual(await listed.evaluateAll((lis, d) => lis.map((li) => li.dataset[d]), l.dim), Array(l.n).fill(l.key), `${l.href}`);
    }
  }
});

const plain = pages.find((p) => !audited(p) && p.index.claims.length);
await check(`a paper with no audit (${plain?.slug})`, async (pg) => {
  assert.ok(plain, "no listed paper without an audit has statements found in its PDF");
  await pg.goto(`${origin}/papers/${plain.slug}/`);
  await pg.waitForSelector("nav.toc li");
  assert.equal(await pg.locator(".reader-layout > nav.toc li").count(), plain.index.claims.length);
  // Formalisations, a dialog opened from its button, says that no audit is published.
  await pg.locator(".reader-tools button", { hasText: "Formalisations" }).click();
  assert.match(await pg.locator(".info-dialog[open] .info-body").textContent(), /No claim-level audit is published yet/);
  await pg.getByRole("button", { name: "Close formalisations" }).click();
  // Without an audit nothing says what Lean establishes.
  assert.doesNotMatch(await pg.locator(".reader-layout > nav.toc").innerHTML(), /st-(proved|accepted)/);
});

for (const dir of fs.readdirSync(fixtures).filter((d) => fs.existsSync(path.join(fixtures, d, "audit.json")))) {
  await check(`an audit exported by an older version (${dir})`, async (pg) => {
    const index = JSON.parse(fs.readFileSync(path.join(fixtures, dir, "data", "index.json")));
    await pg.goto(`${origin}/read/?audit=${encodeURIComponent(`${origin}/fixtures/${dir}/`)}`);
    await pg.waitForSelector("main.state");
    assert.match(await pg.locator("main.state").textContent(), /rebuild the audit/i);
    assert.equal(await pg.locator(".reader-layout > nav.toc li").count(), 0);

  });
}

const demo = fs.readFileSync(path.join(site, "demo", "index.html"), "utf8");
await check("the demo page opens the toy audit in the site's reader", async () => {
  assert.match(demo, /location\.replace\("\.\.\/read\/\?audit="/);
});

await check("arXiv addresses find the same local listing without external requests", async (pg) => {
  let calls = 0;
  await pg.route("https://api.openalex.org/**", (r) => { calls++; return r.fulfill({ json: { results: [] } }); });
  await pg.goto(`${origin}/papers/`);
  const row = pg.locator("#listed > li[data-paper^='arxiv:']").first();
  const id = (await row.getAttribute("data-paper")).slice(6);
  for (const value of [id, `arxiv:${id}v2`, `https://arxiv.org/abs/${id}v3`, `https://arxiv.org/pdf/${id}v2.pdf`]) {
    await pg.getByRole("searchbox", { name: "Search papers" }).fill(value);
    assert.equal(await pg.locator("#listed > li:visible").count(), 1);
    assert.equal(await pg.locator("#listed > li:visible").getAttribute("data-paper"), `arxiv:${id}`);
  }
  assert.equal(calls, 0);
});

await check("catalogue filters, external errors and delayed results remain distinct", async (pg) => {
  let finish, started;
  const requested = new Promise((resolve) => started = resolve);
  await pg.route("https://api.openalex.org/**", async (r) => {
    if (r.request().url().includes("delayed")) { started(); await new Promise((resolve) => finish = resolve); try { await r.fulfill({ json: { results: [{ display_name: "Obsolete result", ids: { openalex: "https://openalex.org/W1" } }] } }); } catch {} }
    else await r.fulfill({ status: 503 });
  });
  await pg.goto(`${origin}/papers/`);
  await pg.getByRole("button", { name: "Published audits", exact: true }).click();
  assert.ok((await pg.locator("#listed > li:visible").evaluateAll((es) => es.map((e) => e.dataset.level))).every((v) => v === "audits"));
  await pg.getByRole("button", { name: "All", exact: true }).click();
  const query = pg.getByRole("searchbox", { name: "Search papers" });
  await query.fill("missing example");
  assert.match(await pg.locator("#search-status").textContent(), /No listed papers/);
  await pg.getByRole("button", { name: "Search other papers" }).click();
  await pg.getByRole("button", { name: "Retry external search" }).waitFor();
  await query.fill("delayed"); await pg.getByRole("button", { name: "Search other papers" }).click();
  await pg.waitForFunction(() => document.querySelector("#found").textContent.includes("Searching"));
  await requested;
  await query.fill(""); finish();
  await pg.waitForLoadState("networkidle");
  assert.equal(await pg.locator("#found").textContent(), "");
  assert.ok(await pg.locator("#listed > li:visible").count());
  await pg.setViewportSize({ width: 320, height: 900 });
  assert.ok(await pg.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
  if (process.env.SHOTS) { fs.mkdirSync(process.env.SHOTS, { recursive: true }); await pg.screenshot({ path: path.join(process.env.SHOTS, "catalogue-320.png"), fullPage: true }); }
});

for (const width of [1360, 390, 320]) await check(`homepage layout and preview at ${width}px`, async (pg) => {
  await pg.setViewportSize({ width, height: 900 }); await pg.goto(origin + "/");
  await pg.locator(".preview img").waitFor();
  await pg.waitForLoadState("networkidle");
  assert.equal(await pg.locator(".preview img").evaluate((i) => i.complete && i.naturalWidth > 0), true);
  assert.ok(await pg.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
  if (width < 700) assert.match(await pg.locator(".preview img").evaluate((i) => i.currentSrc), /mobile/);
  if (process.env.SHOTS) { fs.mkdirSync(process.env.SHOTS, { recursive: true }); await pg.screenshot({ path: path.join(process.env.SHOTS, `homepage-${width}.png`), fullPage: true }); }
});

await browser.close();
server.close();
versionedServer.close();
oneServer.close();
summarisedServer.close();
fs.rmSync(versioned_site, { recursive: true, force: true });
fs.rmSync(one_site, { recursive: true, force: true });
fs.rmSync(summarised_site, { recursive: true, force: true });
fs.rmSync(synthetic, { recursive: true, force: true });
fs.rmSync(audited_site, { recursive: true, force: true });
if (failures) {
  console.log(`${failures} failure(s)`);
  process.exit(1);
}
console.log("all site tests passed");
