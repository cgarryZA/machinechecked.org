// The built site in a browser, with the reader TOOL_VERSION pins: what a new reader must still
// open before it is deployed. Run after `python scripts/build.py --out _site --claims-cache …`:
//   node tests/site.test.mjs [_site]
// Needs the `playwright` package (`npm install --no-save playwright@1.56.1`); set CHROMIUM to a
// browser binary if Playwright has none.
//
// Cases: a paper with two formalisations (the selector, and one project's links at a time), a
// paper with no audit, and audits opened in the reader from their data: the toy audit as this
// version exports it is the demo's; an export frozen from an older version (tests/fixtures/)
// must keep opening.

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
const server = http.createServer((req, res) => {
  let url = decodeURIComponent(req.url.split("?")[0]);
  const base = url.startsWith("/synthetic/") ? synthetic : url.startsWith("/fixtures/") ? fixtures : site;
  if (base === synthetic) url = url.slice("/synthetic".length);
  if (base === fixtures) url = url.slice("/fixtures".length);
  let p = path.join(base, url);
  if (fs.existsSync(p) && fs.statSync(p).isDirectory()) p = path.join(p, "index.html");
  if (!p.startsWith(base) || !fs.existsSync(p)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": types[path.extname(p)] || "application/octet-stream",
    "access-control-allow-origin": "*" });
  fs.createReadStream(p).pipe(res);
}).listen(0);
const origin = `http://127.0.0.1:${server.address().port}`;

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

const plain = pages.find((p) => !audited(p) && p.index.claims.length);
await check(`a paper with no audit (${plain?.slug})`, async (pg) => {
  assert.ok(plain, "no listed paper without an audit has statements found in its PDF");
  await pg.goto(`${origin}/papers/${plain.slug}/`);
  await pg.waitForSelector("nav.toc li");
  assert.equal(await pg.locator(".reader-layout > nav.toc li").count(), plain.index.claims.length);
  assert.match(await pg.locator("body").textContent(), /No claim-level audit is published yet/);
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
fs.rmSync(synthetic, { recursive: true, force: true });
if (failures) {
  console.log(`${failures} failure(s)`);
  process.exit(1);
}
console.log("all site tests passed");
