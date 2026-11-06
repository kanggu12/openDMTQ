// Plays a recording on the portal's live page in a real browser window, its sound going to the test's sound card.
// Usage: node play.js <site port> <guid-id>
const puppeteer = require('puppeteer');

const [port, key] = process.argv.slice(2);
const SITE = `http://127.0.0.1:${port}`;
// Long enough to pass the start, where a replay used to break, and go on a while as a replay does afterwards.
const SECONDS = 16;
const pause = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  // Not headless: Chromium's headless mode does not use the sound card. The window goes to the container's own screen.
  const browser = await puppeteer.launch({ executablePath: '/usr/bin/chromium-browser', headless: false,
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--autoplay-policy=no-user-gesture-required'] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 900 });
  // What hls.js hands the browser, before any decoder hears it. A gap in the sound (a phone's starts after its picture)
  // is filled with silent frames, which must be of the sound's own kind: HE-AAC silence in AAC-LC sound turns the
  // decoder of Chrome on Windows to HE-AAC, and all the sound after it comes out garbled. This browser's decoder takes it
  // in its stride, so the sound alone cannot show it: the frames are counted as they go in. hls.js 1.5.17's stereo silent
  // frames (getSilentFrame), the start of the HE-AAC v2 one and the whole AAC-LC one:
  const HE_SILENCE = [1, 64, 34, 128, 163, 94, 230, 128, 186, 8, 0, 0, 0, 0, 149, 0, 6, 241, 161, 10];
  const LC_SILENCE = [33, 0, 73, 144, 2, 25, 0, 35, 128];
  await page.evaluateOnNewDocument((he, lc) => {
    window.__silence = { he: 0, lc: 0 };
    // How many times a run of bytes occurs in a buffer.
    const count = (bytes, run) => {
      let n = 0;
      next: for (let i = 0; i + run.length <= bytes.length; i++) {
        for (let j = 0; j < run.length; j++) if (bytes[i + j] !== run[j]) continue next;
        n++;
      }
      return n;
    };
    const append = SourceBuffer.prototype.appendBuffer;
    SourceBuffer.prototype.appendBuffer = function (data) {
      const bytes = data instanceof ArrayBuffer ? new Uint8Array(data) : new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
      window.__silence.he += count(bytes, he);
      window.__silence.lc += count(bytes, lc);
      return append.call(this, data);
    };
  }, HE_SILENCE, LC_SILENCE);
  // Through the sign-in, as a viewer comes: the account smoke.py made on the Accounts page.
  await page.goto(`${SITE}/opendmtq/live.php?r=${key}`, { waitUntil: 'domcontentloaded' });
  await page.type('input[name=user]', 'dmtq');
  await page.type('input[name=password]', 'smoke-site');
  await Promise.all([page.waitForNavigation({ waitUntil: 'domcontentloaded' }), page.keyboard.press('Enter')]);
  await pause(SECONDS * 1000);
  // A video that did not play would make this a test of silence.
  const state = await page.$eval('#live-video', v => ({ t: v.currentTime, muted: v.muted, paused: v.paused }));
  console.log(`played ${JSON.stringify(state)}`);
  if (state.t < SECONDS / 2 || state.muted || state.paused) process.exitCode = 1;
  // The gap at the start was filled (the test's sound has one, as a phone's does), and only with AAC-LC silence.
  const silence = await page.evaluate(() => window.__silence);
  const filled = silence.lc > 0 && silence.he === 0;
  console.log(`${filled ? 'PASS' : 'FAIL'} a gap in the sound is filled with silence of its own kind | ${silence.lc} AAC-LC, ${silence.he} HE-AAC frames`);
  if (!filled) process.exitCode = 1;
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
