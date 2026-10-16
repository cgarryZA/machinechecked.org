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

// The site at /, the fixtures at /fixtures/, as audits published elsewhere would be.
const server = http.createServer((req, res) => {
  let url = decodeURIComponent(req.url.split("?")[0]);
  const base = url.startsWith("/fixtures/") ? fixtures : site;
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
  const errors = [];
  pg.on("pageerror", (e) => errors.push(String(e)));
  try {
    await fn(pg);
    assert.deepEqual(errors, [], "no page errors");
    console.log(`ok   ${name}`);
  } catch (e) {
    failures++;
    console.log(`FAIL ${name}: ${e.message}`);
  } finally {
    await pg.close();
  }
}

const two = pages.find((p) => p.index.projects.length > 1);
await check(`a paper with two formalisations (${two?.slug})`, async (pg) => {
  assert.ok(two, "the registry lists no paper with two formalisations");
  await pg.goto(`${origin}/papers/${two.slug}/`);
  const select = pg.locator("select[aria-label='Formalisation shown']");
  await select.waitFor();
  assert.deepEqual(await select.locator("option").allTextContents(), two.index.projects);
  await pg.selectOption("select[aria-label='Formalisation shown']", two.index.projects[1]);
  assert.equal(new URL(pg.url()).searchParams.get("project"), two.index.projects[1]);
});

const plain = pages.find((p) => !audited(p) && p.index.claims.length);
await check(`a paper with no audit (${plain?.slug})`, async (pg) => {
  assert.ok(plain, "no listed paper without an audit has statements found in its PDF");
  await pg.goto(`${origin}/papers/${plain.slug}/`);
  await pg.waitForSelector("nav.toc li");
  assert.equal(await pg.locator("nav.toc li").count(), plain.index.claims.length);
  assert.match(await pg.locator("body").textContent(), /No claim-level audit is published yet/);
  // Without an audit nothing says what Lean establishes.
  assert.doesNotMatch(await pg.locator("nav.toc").innerHTML(), /st-(proved|accepted)/);
});

for (const dir of fs.readdirSync(fixtures).filter((d) => fs.existsSync(path.join(fixtures, d, "audit.json")))) {
  await check(`an audit exported by an older version (${dir})`, async (pg) => {
    const index = JSON.parse(fs.readFileSync(path.join(fixtures, dir, "data", "index.json")));
    await pg.goto(`${origin}/read/?audit=${encodeURIComponent(`${origin}/fixtures/${dir}/`)}`);
    await pg.waitForSelector("nav.toc li");
    assert.equal(await pg.locator("nav.toc li").count(),
      index.claims.filter((c) => !String(c.status).startsWith("out of scope")).length);
    assert.match(await pg.locator(".banner").first().textContent(), /does not endorse it/);
    await pg.locator("nav.toc li button").first().click();
    await pg.waitForSelector("aside h1");
  });
}

const demo = fs.readFileSync(path.join(site, "demo", "index.html"), "utf8");
await check("the demo page opens the toy audit in the site's reader", async () => {
  assert.match(demo, /location\.replace\("\.\.\/read\/\?audit="/);
});

await browser.close();
server.close();
if (failures) {
  console.log(`${failures} failure(s)`);
  process.exit(1);
}
console.log("all site tests passed");
