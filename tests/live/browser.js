// Plays a closed recording in headless Chromium, on the portal's live page and in the admin pages.
// tests/live/run.sh runs this with BROWSER=1. Usage: node browser.js <site port> <admin port> <guid/id>
const puppeteer = require('puppeteer');

const [site, admin, key] = process.argv.slice(2);
const SITE = `http://127.0.0.1:${site}`;
const ADMIN = `http://127.0.0.1:${admin}`;
const pause = ms => new Promise(r => setTimeout(r, ms));

// The video's clock now, and again a few seconds later: only a playing video moves.
async function playing(page, selector, name) {
  await pause(4000);
  const look = () => page.$eval(selector, v => ({ t: v.currentTime, w: v.videoWidth, duration: v.duration }));
  const a = await look();
  await pause(3000);
  const b = await look();
  const ok = b.t > a.t + 2 && b.w === 1280 && b.duration > 10;
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name} | ${JSON.stringify(b)}`);
  if (!ok) process.exitCode = 1;
  // The box takes the stream's shape: no bars above, below or beside the picture.
  const shape = await page.$eval(selector, v => ({ box: v.clientWidth / v.clientHeight, video: v.videoWidth / v.videoHeight }));
  const fits = Math.abs(shape.box - shape.video) < 0.02;
  console.log(`${fits ? 'PASS' : 'FAIL'} ${name}: the box has the video's shape | ${JSON.stringify(shape)}`);
  if (!fits) process.exitCode = 1;
}

(async () => {
  const browser = await puppeteer.launch({ executablePath: '/usr/bin/chromium-browser', headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--autoplay-policy=no-user-gesture-required'] });
  // A direct link to the recording, through the sign-in.
  const page = await browser.newPage();
  await page.goto(`${SITE}/opendmtq/live.php?r=${key.replace('/', '-')}`, { waitUntil: 'networkidle2' });
  // The account smoke.py made on the Accounts page.
  await page.type('input[name=user]', 'dmtq');
  await page.type('input[name=password]', 'smoke-site');
  await Promise.all([page.waitForNavigation({ waitUntil: 'domcontentloaded' }), page.keyboard.press('Enter')]);
  await playing(page, '#live-video', 'the VOD playlist plays on the portal');
  // A recording has the site's own controls with the timeline, its own mark, and says it is no broadcast.
  const recording = await page.evaluate(() => ({ native: document.getElementById('live-video').controls, own: !document.getElementById('live-ctl').hidden, seek: !document.getElementById('ctl-seek').hidden, mark: document.getElementById('pill-word').textContent, time: document.getElementById('ctl-time').textContent, heading: document.querySelector('#mast .word').textContent, title: document.title }));
  const vod = !recording.native && recording.own && recording.seek && recording.mark === 'REPLAY' && /\d:\d\d \/ \d:\d\d/.test(recording.time) && recording.heading === 'REPLAY' && /Replay/.test(recording.title);
  console.log(`${vod ? 'PASS' : 'FAIL'} a recording: its own controls with the timeline, the REPLAY mark, and the title says so | ${JSON.stringify(recording)}`);
  if (!vod) process.exitCode = 1;
  // A recording fetches a short stretch ahead, not half a minute at once, and starts where its media does.
  const ahead = await page.evaluate(() => {
    const v = document.getElementById('live-video'), b = v.buffered;
    return { ahead: b.end(b.length - 1) - v.currentTime, t: v.currentTime, d: v.duration };
  });
  const short = ahead.d > 30 && ahead.ahead < 20;
  console.log(`${short ? 'PASS' : 'FAIL'} a recording fetches a short stretch ahead | ${JSON.stringify(ahead)}`);
  if (!short) process.exitCode = 1;
  // The timeline moves the video.
  const moved = await page.evaluate(async () => {
    const s = document.getElementById('ctl-seek'), v = document.getElementById('live-video');
    s.value = 500;
    s.dispatchEvent(new Event('input'));
    s.dispatchEvent(new Event('change'));
    await new Promise(r => setTimeout(r, 800));
    return { t: v.currentTime, d: v.duration };
  });
  const seeks = Math.abs(moved.t - moved.d / 2) < 2;
  console.log(`${seeks ? 'PASS' : 'FAIL'} the timeline moves the recording | ${JSON.stringify(moved)}`);
  if (!seeks) process.exitCode = 1;
  // A drag that ends where it began (no change event) does not leave the timeline stuck.
  const released = await page.evaluate(async () => {
    const s = document.getElementById('ctl-seek'), v = document.getElementById('live-video');
    v.currentTime = 5;
    await new Promise(r => setTimeout(r, 500));
    s.value = 900;
    s.dispatchEvent(new Event('input'));
    s.dispatchEvent(new Event('pointerup'));
    await new Promise(r => setTimeout(r, 1200));
    return { value: +s.value, expected: Math.round(v.currentTime / v.duration * 1000) };
  });
  const unstuck = Math.abs(released.value - released.expected) < 60;
  console.log(`${unstuck ? 'PASS' : 'FAIL'} a drag let go without a change does not stick the timeline | ${JSON.stringify(released)}`);
  if (!unstuck) process.exitCode = 1;
  // Paused during a wait: the spinner does not stay.
  const spinner = await page.evaluate(async () => {
    const stage = document.querySelector('.live-stage'), v = document.getElementById('live-video');
    await v.play().catch(() => {});
    stage.classList.add('waiting');
    v.pause();
    await new Promise(r => setTimeout(r, 200));
    const left = stage.classList.contains('waiting');
    await v.play().catch(() => {});
    return left;
  });
  console.log(`${spinner ? 'FAIL' : 'PASS'} pausing during a wait takes the spinner away`);
  if (spinner) process.exitCode = 1;
  // The keys go on working on the sliders, whatever the keyboard's language or Caps Lock make of the letters.
  await page.focus('#ctl-seek');
  const before = await page.$eval('#live-video', v => ({ t: v.currentTime, paused: v.paused, muted: v.muted }));
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('Space');
  await page.evaluate(() => document.getElementById('ctl-seek').dispatchEvent(new KeyboardEvent('keydown', { code: 'KeyM', key: 'ㅡ', bubbles: true })));
  await pause(300);
  const after = await page.$eval('#live-video', v => ({ t: v.currentTime, paused: v.paused, muted: v.muted }));
  const keys = after.t - before.t >= 4 && after.paused !== before.paused && after.muted !== before.muted;
  console.log(`${keys ? 'PASS' : 'FAIL'} the keys work on the timeline, in Korean input too | ${JSON.stringify({ before, after })}`);
  if (!keys) process.exitCode = 1;
  await page.evaluate(() => { const v = document.getElementById('live-video'); v.muted = false; return v.play().catch(() => {}); });
  // Nobody on air and nothing chosen: no empty player on the page.
  await page.goto(`${SITE}/opendmtq/live.php`, { waitUntil: 'domcontentloaded' });
  await pause(1000);
  const shown = await page.$eval('#live-video', v => getComputedStyle(v).display);
  console.log(`${shown === 'none' ? 'PASS' : 'FAIL'} the empty page shows no video box | ${shown}`);
  if (shown !== 'none') process.exitCode = 1;
  await page.screenshot({ path: '/shots/empty-with-past.png' });
  // In the admin pages.
  const own = await browser.newPage();
  await own.goto(`${ADMIN}/opendmtq/admin/login`, { waitUntil: 'networkidle2' });
  await own.type('input[name=name]', 'admin');
  await own.type('input[name=password]', 'smoke');
  await Promise.all([own.waitForNavigation({ waitUntil: 'networkidle2' }), own.keyboard.press('Enter')]);
  await own.goto(`${ADMIN}/opendmtq/admin/recordings?watch=${key}`, { waitUntil: 'domcontentloaded' });
  await playing(own, '#rec-video', 'the VOD playlist plays in the admin page');
  await own.screenshot({ path: '/shots/rec-admin.png' });
  // A recording whose list cannot be had: the page says so and asks again now and then, not hundreds of times a second.
  const broken = await browser.newPage();
  let asks = 0;
  await broken.setRequestInterception(true);
  broken.on('request', r => {
    if (r.url().includes('/rec/') && r.url().includes('index.m3u8')) { asks++; return r.respond({ status: 404, body: '' }); }
    r.continue();
  });
  await broken.goto(`${SITE}/opendmtq/live.php?r=${key.replace('/', '-')}`, { waitUntil: 'domcontentloaded' });
  await pause(10000);
  const said = await broken.$eval('#live-lost', e => (e.hidden ? '' : e.textContent));
  console.log(`${asks <= 8 && said ? 'PASS' : 'FAIL'} a recording that cannot be had: no hot loop | ${asks} asks in 10 s, ${JSON.stringify(said)}`);
  if (asks > 8 || !said) process.exitCode = 1;
  await broken.close();
  await browser.close();
})().catch(e => { console.error('FAIL', e); process.exit(1); });
