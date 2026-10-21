// Deterministic frame-by-frame render of /trailer.html -> silent H.264 MP4.
// Usage: serve web/out on 127.0.0.1:8765, then: node render.mjs <out.mp4> [frameDir]
// Other pages: URL=... DURATION=<s> WIDTH=<px> HEIGHT=<px> node render.mjs ... (defaults = the 30.8 s 1920x1080 trailer)
import { chromium } from 'playwright';
import ffmpeg from 'ffmpeg-static';
import { execFileSync } from 'node:child_process';
import { mkdirSync, rmSync } from 'node:fs';

const [out = 'trailer.mp4', dir = 'frames'] = process.argv.slice(2);
const URL = process.env.URL ?? 'http://127.0.0.1:8765/trailer.html';
const FPS = 60, FRAMES = Math.round(Number(process.env.DURATION ?? 30.8) * FPS); // trailer: 7 scenes = 30.8 s, then it loops
const LOGOS = [1610612752, 1610612738].map((id) => `https://cdn.nba.com/logos/nba/${id}/global/L/logo.svg`); // NYK, BOS

rmSync(dir, { recursive: true, force: true });
mkdirSync(dir, { recursive: true });
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: Number(process.env.WIDTH ?? 1920), height: Number(process.env.HEIGHT ?? 1080) }, deviceScaleFactor: 1 });
// cdn.nba.com's bot filter kills headless Chromium's logo requests (ERR_HTTP2_PROTOCOL_ERROR); proxy them via Node fetch.
await page.route('https://cdn.nba.com/logos/**', async (route) => {
  const r = await fetch(route.request().url());
  await route.fulfill({ status: r.status, contentType: r.headers.get('content-type'), body: Buffer.from(await r.arrayBuffer()) });
});
await page.clock.install({ time: 0 });
await page.clock.pauseAt(1000); // fake time frozen; only advanced by runFor below
await page.addInitScript(() => {
  delete Element.prototype.animate; // no WAAPI -> Motion animates in JS on the (fake) clock
  const q = [];
  window.__raf = q;
  window.requestAnimationFrame = (cb) => q.push(cb); // exactly one rAF tick per captured frame
  window.cancelAnimationFrame = () => {};
  window.__frame = async () => {
    const tick = () => new Promise((r) => { const c = new MessageChannel(); c.port1.onmessage = r; c.port2.postMessage(0); });
    for (let i = 0; i < 3; i++) await tick(); // let React (MessageChannel scheduler) commit + run effects
    await Promise.all([...document.images].map((i) => i.decode().catch(() => {})));
    const t = performance.now();
    q.splice(0).forEach((cb) => cb(t));
  };
});
await page.goto(URL, { waitUntil: 'load' });
// globals.css's Inter @import lands mid-stylesheet in the build, so browsers ignore it; load Inter explicitly.
await page.addStyleTag({ url: 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap' });
await page.evaluate(async (logos) => {
  await Promise.all([...document.fonts].map((f) => f.load().catch(() => {})));
  await document.fonts.ready;
  await Promise.all(logos.map((src) => { const i = new Image(); i.src = src; return i.decode(); }));
}, LOGOS);
await page.waitForFunction(() => window.__raf.length > 0); // hydrated, Motion loop running

let elapsed = 0;
for (let f = 0; f < FRAMES; f++) {
  const target = Math.round((f * 1000) / FPS);
  if (target > elapsed) await page.clock.runFor(target - elapsed);
  elapsed = target;
  await page.evaluate(() => window.__frame());
  await page.screenshot({ path: `${dir}/frame_${String(f).padStart(5, '0')}.jpg`, type: 'jpeg', quality: 95 });
  if (f % 120 === 0) console.log(`frame ${f}/${FRAMES}, WAAPI animations: ${await page.evaluate(() => document.getAnimations().length)}`);
}
await browser.close();

execFileSync(ffmpeg, ['-y', '-hide_banner', '-loglevel', 'error', '-framerate', String(FPS), '-i', `${dir}/frame_%05d.jpg`,
  '-c:v', 'libx264', '-preset', 'slow', '-crf', '16', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-an', out], { stdio: 'inherit' });
rmSync(dir, { recursive: true, force: true });
console.log(`wrote ${out}`);
