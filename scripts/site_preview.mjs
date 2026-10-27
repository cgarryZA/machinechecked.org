// Screenshots of the demo reader for the landing page (site/preview-*.webp), light and dark,
// taken with headless Chromium. The reader is the site's own (`_site/read`, after
// `python scripts/build.py`; set READER to use another), showing the data of an exported audit
// (`machinechecked export`, with or without --data-only; the demo is the toy paper's).
//
//   npm install --no-save playwright@1.56.1
//   node scripts/site_preview.mjs <audit dir> <out dir>
//
// Set CHROMIUM to a browser binary if Playwright has none, and CLAIM to the claim to open.
// Convert the screenshots to WebP with Pillow:
//   python3 -c "from PIL import Image as I; [I.open(f'preview-{s}.png').convert('RGB')
//     .save(f'site/preview-{s}.webp', quality=82, method=6) for s in ('light', 'dark', 'mobile-light', 'mobile-dark')]"
import { chromium } from "playwright";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";

const [audit, out] = process.argv.slice(2);
const reader = path.resolve(process.env.READER || "_site/read");
if (!audit || !out || !fs.existsSync(path.join(reader, "index.html"))) {
  console.error("usage: node scripts/site_preview.mjs <audit dir> <out dir> (build the site first, or set READER)");
  process.exit(2);
}
const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css",
  ".json": "application/json", ".pdf": "application/pdf", ".svg": "image/svg+xml",
  ".woff2": "font/woff2", ".mjs": "text/javascript" };
// The reader at the root, with the audit's data beside it, as an export with its reader has it.
const server = http.createServer((req, res) => {
  const url = decodeURIComponent(req.url.split("?")[0]);
  const fromAudit = url.startsWith("/data/") || url === "/audit.json";
  let p = path.join(fromAudit ? audit : reader, url);
  if (fs.existsSync(p) && fs.statSync(p).isDirectory()) p = path.join(p, "index.html");
  if (!fs.existsSync(p)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": types[path.extname(p)] || "application/octet-stream" });
  fs.createReadStream(p).pipe(res);
}).listen(0);
const port = server.address().port;
const index = JSON.parse(fs.readFileSync(path.join(audit, "data", "index.json")));
const claim = process.env.CLAIM || "T:thm:even-add";
const paper = index.papers[0].id;
const url = `http://127.0.0.1:${port}/#/r/${encodeURIComponent(index.release)}/read/` +
  `${encodeURIComponent(paper)}/${encodeURIComponent(claim)}?compare=1`;

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined });
fs.mkdirSync(out, { recursive: true });
for (const width of [1360, 390]) for (const scheme of ["light", "dark"]) {
  const page = await browser.newPage({ viewport: { width, height: width < 500 ? 900 : 620 },
    deviceScaleFactor: 2, colorScheme: scheme });
  await page.goto(url);
  await page.locator(".exact pre").waitFor();
  await page.waitForLoadState("networkidle");
  await page.evaluate(() => document.fonts.ready);
  // The phone screenshot frames the comparison, under whichever class the pinned reader gives it.
  const target = width < 500 ? page.locator(".cmp, .comparison-grid").first() : page;
  await target.screenshot({ path: path.join(out, `preview-${width < 500 ? "mobile-" : ""}${scheme}.png`) });
  await page.close();
}
await browser.close();
server.close();
