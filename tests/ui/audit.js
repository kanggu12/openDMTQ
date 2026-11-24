// The pages' tests in a real browser. Prints PASS and FAIL lines, writes the layout findings and screenshots to OUT.
//   node audit.js self     the checker itself finds each planted defect (defects.html)
//   node audit.js empty    every page of a server with nothing on it
//   node audit.js full     every page with players, plays, recordings and an app, at five widths, in both languages
//   node audit.js keys     the keyboard's marks on the site and the admin pages, held to the database (keys.json in OUT)
//   node audit.js air      the pages that change while players are on air, and the video playing
//   node audit.js maint    the owner turns maintenance on: the notice, whole, on every page that shows it; then off again
//   node audit.js down     the game server stopped: the owner's pages keep their look and say what is wrong
//   node audit.js flows    what people do: signing in, searching, the replay player, the owner's forms; every floating
//                          layer (menus, tooltips, questions) opened and measured whole and on top
//   node audit.js quiet    broadcasts off for the server with everything in place: nothing of them on the site
//   node audit.js patterns nothing said only under a mouse pointer, switches that change the page in place, the owner's
//                          forms saying what is wrong under the field
//   node audit.js notice   the owner's notice on the site: put up by the Notices page's card, on every page whole at every
//                          width, closed for a visit, shown again with new words, and coming and going on pages left open
//   node audit.js notices  the site's pages left open while the owner begins, changes and ends maintenance, twice: the bar's
//                          word and the sentence under it come and go by themselves each time
//   node audit.js away     the owner's pages left open while the game server stops and starts again, twice (run.sh does
//                          that when this says it is ready, through files in OUT): the word and the sentence come and go
//   node audit.js mine     MY PAGE: for an account linked to its player, one that is not and the owner's, at every width in
//                          both languages; the account's changes and the other sign-ins; its JSON twin
// Exit status 1 when anything failed. Reads SITE, ADMIN (addresses), PASSWORD and OUT from the environment.
const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

const stage = process.argv[2];
const SITE = process.env.SITE;
const ADMIN = process.env.ADMIN;
const PASSWORD = process.env.PASSWORD;
const OUT = process.env.OUT || '/out';
const P = `${SITE}/opendmtq`;
const A = `${ADMIN}/opendmtq/admin`;
const layout = fs.readFileSync(path.join(__dirname, 'layout.js'), 'utf8');
// The room between things (boxes touching, text against an edge, gaps off the page's scale), measured beside the layout.
const spacing = fs.readFileSync(path.join(__dirname, 'spacing.js'), 'utf8');
const pause = ms => new Promise(r => setTimeout(r, ms));

// The screens every page is looked at on: a phone, the narrowest tablet (an iPad mini held upright), a tablet held sideways,
// a laptop, a large monitor. Between the phone's stacked rows and a laptop's width is where a table has the least room.
const ALL_WIDTHS = [360, 744, 1024, 1280, 1920];
// For the states that only change a part of a page.
const FEW_WIDTHS = [360, 1280];
// Player numbers and song numbers from seed.php and make_content.php: 1 plays much, 4 and 5 have the longest names, 10 has no
// plays; song 25 has the longest name, song 26 has no jacket.
// The setup's steps as a host install shows them: run.sh puts a client and a folder of the client data and the song
// data in the owner's Downloads.
const SETUP = [
  ['admin-setup', `${A}/setup?step=files`],
  ['admin-setup-picker', `${A}/setup?step=files&dir=%2Fhome%2Fplayer%2FDownloads`],
  ['admin-setup-address', `${A}/setup?step=address`],
  ['admin-setup-players', `${A}/setup?step=players`],
  ['admin-setup-app', `${A}/setup?step=app`],
];
const FULL = [
  // Signed out, a page asked for: the sign-in page is all there is.
  ['sign-in-first', `${P}/ranking.php`, { anon: true }],
  ['home', `${P}/`],
  ['download', `${P}/download.php`],
  ['rankings', `${P}/ranking.php`],
  ['rankings-s', `${P}/ranking.php?sort=s_count`],
  ['rankings-month', `${P}/ranking.php?sort=month`],
  ['songs', `${P}/songs.php`],
  ['song', `${P}/song.php?id=1`],
  ['song-long-name', `${P}/song.php?id=25`],
  ['song-no-jacket', `${P}/song.php?id=26`],
  ['song-unknown', `${P}/song.php?id=8888`, { status: 404 }],
  ['player', `${P}/player.php?id=1`],
  ['player-no-plays', `${P}/player.php?id=10`],
  ['player-long-name', `${P}/player.php?id=5`],
  ['player-unknown', `${P}/player.php?id=999`, { status: 404 }],
  ['live', `${P}/live.php`, { settle: 1500 }],
  ['sign-in', `${P}/login.php?next=%2Fapk`, { anon: true }],
  ['not-found', `${SITE}/nope`, { status: 404 }],
  ['licenses', `${P}/licenses.php`],
  ['admin-sign-in', `${A}/login`, { anon: true }],
  ['admin-status', `${A}/`],
  ['admin-app', `${A}/app`],
  ['admin-songs', `${A}/songs`],
  ['admin-players', `${A}/players`],
  // A player's own page (PAGE-75): one who plays much with nothing changed, one with a balance of his own and purchases,
  // and a long name banned with the longest reason, unlimited, items given and taken, and changes listed (seed.php).
  ['admin-player', `${A}/players/1`],
  ['admin-player-kept', `${A}/players/2`],
  ['admin-player-banned', `${A}/players/6`],
  ['admin-player-no-plays', `${A}/players/10`],
  ['admin-accounts', `${A}/accounts`],
  ['admin-recordings', `${A}/recordings`],
  ['admin-backups', `${A}/backups`],
  ['admin-maintenance', `${A}/maintenance`],
  // The Server page as a host install has it (these pages' service runs as one): restart and stop, the port, the
  // repair, the data and uninstall.
  ['admin-server', `${A}/server`],
  ['admin-requests', `${A}/logs`],
  ['admin-plays', `${A}/logs?tab=plays`],
  // Narrowed, by the player with one of the longest names: the form holds what was picked, and has a way back.
  ['admin-plays-narrowed', `${A}/logs?tab=plays&player=4&from=2020-01-01&to=2030-12-31`],
  ['admin-changes', `${A}/logs?tab=changes`],
  ['admin-not-found', `${A}/nope`, { status: 404 }],
  ...SETUP,
];
const EMPTY = [
  ['home', `${P}/`],
  // Signed out, a page asked for: the sign-in page is all there is.
  ['sign-in-first', `${P}/ranking.php`, { anon: true }],
  ['rankings', `${P}/ranking.php`],
  ['songs', `${P}/songs.php`],
  ['live', `${P}/live.php`, { settle: 800 }],
  ['download', `${P}/download.php`],
  ['no-app', `${SITE}/apk`, { status: 404 }],
  ['player-unknown', `${P}/player.php?id=1`, { status: 404 }],
  ['admin-status', `${A}/`],
  ['admin-app', `${A}/app`],
  ['admin-songs', `${A}/songs`],
  ['admin-players', `${A}/players`],
  ['admin-accounts', `${A}/accounts`],
  ['admin-recordings', `${A}/recordings`],
  ['admin-backups', `${A}/backups`],
  ['admin-requests', `${A}/logs`],
  ['admin-plays', `${A}/logs?tab=plays`],
  ['admin-changes', `${A}/logs?tab=changes`],
  ...SETUP,
];
const AIR = [
  ['home', `${P}/`, { settle: 800 }],
  ['live', `${P}/live.php`, { settle: 3000 }],
  ['live-one', `${P}/live.php?id=1`, { settle: 3000 }],
  ['rankings', `${P}/ranking.php`],
  ['player', `${P}/player.php?id=1`],
  ['admin-status', `${A}/`],
  ['admin-players', `${A}/players`],
  ['admin-accounts', `${A}/accounts`],
  ['admin-recordings', `${A}/recordings`],
];
const MAINT = [
  ['home', `${P}/`],
  // Signed out, a page asked for: the sign-in page is all there is.
  ['sign-in-first', `${P}/ranking.php`, { anon: true }],
  ['rankings', `${P}/ranking.php`],
  ['live', `${P}/live.php`, { settle: 800 }],
  ['admin-maintenance', `${A}/maintenance`],
  ['admin-status', `${A}/`],
];
// Broadcasts off for the server, with players, records and recordings: the pages that showed broadcasts, whole without
// them, and the owner's pages that say they are off.
const QUIET = [
  ['home', `${P}/`],
  ['rankings', `${P}/ranking.php`],
  ['player', `${P}/player.php?id=1`],
  ['player-long-name', `${P}/player.php?id=5`],
  ['live', `${P}/live.php`],
  ['download', `${P}/download.php`],
  ['admin-status', `${A}/`],
  ['admin-players', `${A}/players`],
  ['admin-recordings', `${A}/recordings`],
];
// The owner's pages, with the game server gone: run.sh stops it for this stage and starts it again afterwards.
const DOWN = [
  ['admin-sign-in', `${A}/login`, { anon: true }],
  ['admin-status', `${A}/`],
  ['admin-app', `${A}/app`],
  ['admin-songs', `${A}/songs`],
  ['admin-players', `${A}/players`],
  ['admin-accounts', `${A}/accounts`],
  ['admin-recordings', `${A}/recordings`],
  ['admin-backups', `${A}/backups`],
  ['admin-maintenance', `${A}/maintenance`],
  ['admin-requests', `${A}/logs`],
];
// The owner's notice up, its words long enough to wrap on a phone: every page of the site has it under the bar, and the
// Notices page its card.
const NOTICE = [
  ['home', `${P}/`],
  ['rankings', `${P}/ranking.php`],
  ['songs', `${P}/songs.php`],
  ['song', `${P}/song.php?id=1`],
  ['player', `${P}/player.php?id=1`],
  ['live', `${P}/live.php`, { settle: 800 }],
  ['download', `${P}/download.php`],
  ['licenses', `${P}/licenses.php`],
  ['not-found', `${SITE}/nope`, { status: 404 }],
  ['admin-notices', `${A}/maintenance`],
];
// Asked for and not there, on purpose: the jacket of song 26 (the page must go on without it).
const MISSING_ON_PURPOSE = /\/fixture26\.(png|jpg)$/;

let failed = 0;
const check = (name, ok, detail = '') => {
  console.log(`${ok ? 'PASS' : 'FAIL'} ${stage}: ${name}${detail ? ` | ${detail}` : ''}`);
  if (!ok) failed++;
};

// One browser with its own signed-in sessions, one without.
async function open() {
  const browser = await puppeteer.launch({ executablePath: '/usr/bin/chromium-browser', headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--autoplay-policy=no-user-gesture-required', '--mute-audio'] });
  const signed = await browser.createBrowserContext();
  const anon = await browser.createBrowserContext();
  return { browser, signed, anon };
}

async function signIn(context) {
  const page = await context.newPage();
  // (With the game server stopped, only the owner's pages are there to sign in to; from the server PC's own network, too.)
  if (stage !== 'down' && stage !== 'thispc') {
    await page.goto(`${P}/login.php?next=%2Fopendmtq%2F`, { waitUntil: 'domcontentloaded' });
    await typeId(page, 'input[name=user]', 'dmtq');
    await page.type('input[name=password]', PASSWORD);
    await Promise.all([page.waitForNavigation({ waitUntil: 'domcontentloaded' }), page.keyboard.press('Enter')]);
  }
  await page.goto(`${A}/login`, { waitUntil: 'domcontentloaded' });
  await typeId(page, 'input[name=name]', 'admin');
  await page.type('input[name=password]', PASSWORD);
  await Promise.all([page.waitForNavigation({ waitUntil: 'domcontentloaded' }), page.keyboard.press('Enter')]);
  await page.close();
}

// A page's own faults while it was open: failed requests and script errors. A page that is itself a 404 expects that.
function watch(page, url) {
  const faults = [];
  page.on('response', r => {
    const where = r.url().split('?')[0];
    if (r.status() >= 400 && r.url() !== url && !MISSING_ON_PURPOSE.test(where)) faults.push(`${r.status()} ${where.replace(/^https?:\/\/[^/]+/, '')}`);
  });
  page.on('pageerror', e => faults.push(`script: ${String(e).slice(0, 160)}`));
  page.on('console', m => {
    if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) faults.push(`console: ${m.text().slice(0, 160)}`);
  });
  return faults;
}

// The owner's pages give a screen one primary button: two that one screen holds at once, on an admin page, are a finding
// (two-primaries), wherever on the page they are. A far one on a long page is no second on this screen. Only what can be
// pressed counts: a disabled one is drawn plain.
function twoPrimaries(page) {
  return page.evaluate(() => {
    if (!location.pathname.startsWith('/opendmtq/admin')) return [];
    const shown = [...document.querySelectorAll('.btn-primary')].filter(b => {
      const s = getComputedStyle(b), r = b.getBoundingClientRect();
      return !b.disabled && s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
    }).map(b => {
      const r = b.getBoundingClientRect();
      return { words: b.textContent.trim().replace(/\s+/g, ' ').slice(0, 30), top: r.top + scrollY, bottom: r.bottom + scrollY };
    });
    const found = [];
    for (let i = 0; i < shown.length; i++) {
      for (let j = i + 1; j < shown.length; j++) {
        // Both within one screen's height: a screen can show them together.
        if (Math.max(shown[i].bottom, shown[j].bottom) - Math.min(shown[i].top, shown[j].top) <= innerHeight) {
          found.push({ kind: 'two-primaries', at: `${shown[i].words} + ${shown[j].words}`, detail: `${innerWidth}x${innerHeight}` });
        }
      }
    }
    return found;
  });
}

// The checker on the page as it is now.
async function audit(page) {
  // What moves as a page arrives (style.css, "motion": bars filling, the player's row glowing) is measured where it
  // comes to rest: every animation with an end is waited for (those that loop, like the front page's sweep, are not),
  // three seconds at most.
  await page.evaluate(() => Promise.race([
    Promise.all(document.getAnimations().filter(a => a.effect && Number.isFinite(a.effect.getComputedTiming().endTime)).map(a => a.finished.catch(() => {}))),
    new Promise(done => setTimeout(done, 3000)),
  ]));
  // And the site's arrival itself (lib.php: the class "arriving", gone after 1.6 s): until it goes, a finished glow holds
  // its last frame, a colour the browser reads back in oklab (which the checkers do not read), so the row it lights was a
  // box to them or not by the moment they looked. Waited for only where something moves.
  await page.waitForFunction(() => !document.documentElement.classList.contains('arriving') || !document.getAnimations().length,
    { timeout: 3000, polling: 100 }).catch(() => {});
  await page.addScriptTag({ content: `${layout}\n${spacing}` });
  return page.evaluate(() => [...window.layoutAudit(), ...window.spacingAudit()]);
}

// Views side by side, SWEEP_WORKERS of them at once (run.sh sets it): each worker has windows of its own, signed in as the
// contexts given are (their cookies copied into them), and opens one view at a time in them. The browser keeps only the
// front tab of a window in sight, and a view out of sight would neither finish its motion nor look at the server: each view
// is the only one of its window, and says so (out of sight is a fault). The first worker is the contexts given.
const WORKERS = Math.max(1, parseInt(process.env.SWEEP_WORKERS || '1', 10) || 1);

// A context of its own with the cookies of another (its sign-ins on the site and the admin pages, its language).
async function twin(context) {
  const copy = await context.browser().createBrowserContext();
  const page = await context.newPage();
  const cookies = (await page.cookies(`${SITE}/opendmtq/`, `${ADMIN}/opendmtq/admin/`)).map(c => ({
    name: c.name, value: c.value, domain: c.domain, path: c.path, httpOnly: c.httpOnly, secure: c.secure, sameSite: c.sameSite,
    // A session cookie stays one.
    ...(c.session || !(c.expires > 0) ? {} : { expires: c.expires }),
  }));
  await page.close();
  if (cookies.length) {
    const into = await copy.newPage();
    await into.setCookie(...cookies);
    await into.close();
  }
  return copy;
}

// One view: the page at a width in a language, in a worker's window; the faults found, as the keys sweep() groups them by.
async function lookAt(worker, { name, url, options, width, lang }) {
  const page = await (options.anon ? worker.anon : worker.signed).newPage();
  await page.setViewport({ width, height: width < 500 ? 740 : 900, hasTouch: width < 500, isMobile: width < 500 });
  await page.setCookie({ name: 'opendmtq_lang', value: lang, url });
  const faults = watch(page, url);
  let status = 0;
  try {
    const answer = await page.goto(url, { waitUntil: options.settle ? 'domcontentloaded' : 'networkidle2', timeout: 30000 });
    status = answer ? answer.status() : 0;
  } catch (e) {
    faults.push(`did not load: ${String(e).slice(0, 120)}`);
  }
  if (options.settle) await pause(options.settle);
  if (status !== (options.status || 200)) faults.push(`status ${status}, expected ${options.status || 200}`);
  // The layout, and on the owner's pages one primary button to a screen.
  const items = [...await audit(page), ...await twoPrimaries(page)];
  // Measured in sight, as a person sees it (with views side by side, each in a window of its own).
  const sight = await page.evaluate(() => document.visibilityState).catch(() => 'gone');
  if (sight !== 'visible') faults.push(`out of sight while measured (${sight})`);
  for (const f of faults) items.push({ kind: 'page-fault', at: f, detail: '' });
  // Pictures for people to look through: the default language on phone and laptop, the other on a phone.
  // SHOTS_ALL=1: both languages at the phone's width and the desktop's, for a look at a page in each.
  if ((process.env.SHOTS_ALL && (width === 360 || width === 1280)) || (lang === 'en' && (width === 360 || width === 1280)) || (lang === 'ko' && width === 360)) {
    await page.screenshot({ path: path.join(OUT, 'shots', `${stage}-${name}-${lang}-${width}.jpg`), type: 'jpeg', quality: 72, fullPage: true }).catch(() => {});
  }
  await page.close();
  return items.map(f => `${f.kind} | ${name} | ${f.at} | ${f.detail}`);
}

// Every page of a list on every width, in both languages; findings grouped, so that one fault on eight views is one line.
async function sweep(contexts, pages, widths, langs = ['en', 'ko']) {
  const views = [];
  for (const [name, url, options = {}] of pages) {
    for (const width of widths) {
      for (const lang of langs) views.push({ name, url, options, width, lang });
    }
  }
  // Each finding's views, by their place in the list: grouped and listed in that order, however the workers took them.
  const found = {};
  const workers = [contexts];
  for (let i = 1; i < Math.min(WORKERS, views.length); i++) {
    workers.push({ signed: await twin(contexts.signed), anon: await twin(contexts.anon), own: true });
  }
  let next = 0;
  await Promise.all(workers.map(async worker => {
    while (next < views.length) {
      const at = next++;
      for (const key of await lookAt(worker, views[at])) (found[key] = found[key] || []).push(at);
    }
  }));
  for (const worker of workers.filter(w => w.own)) {
    await worker.signed.close();
    await worker.anon.close();
  }
  // The language cookies as one view after another leaves them: each view sets its own for its address, and the flows
  // after a sweep read the last one set (a sweep ends in the language they read). Set again in the views' order, on the
  // contexts given, whichever worker looked at each view last.
  for (const kind of ['signed', 'anon']) {
    const mine = views.filter(v => (kind === 'anon') === !!v.options.anon);
    if (!mine.length) continue;
    const page = await contexts[kind].newPage();
    for (const { url, lang } of mine) await page.setCookie({ name: 'opendmtq_lang', value: lang, url });
    await page.close();
  }
  const where = key => found[key].sort((a, b) => a - b).map(i => `${views[i].lang}${views[i].width}`);
  const keys = Object.keys(found).sort();
  fs.appendFileSync(path.join(OUT, 'findings.txt'), keys.map(k => `${stage} | ${k} @${where(k).join(',')}\n`).join(''));
  check(`${views.length} views, ${keys.length} findings`, keys.length === 0, keys.slice(0, 30).map(k => `\n  ${k.slice(0, 170)} @${where(k).slice(0, 4).join(',')}`).join(''));
}

// Broadcasts off for the server: the site shows nothing of them, its live page says so in the site's own way, and the
// owner's Broadcasts page has the way to turn them on. held: a player's switch is on underneath, which the owner's
// Players page shows as kept for then.
async function broadcastsOff(contexts, held) {
  const page = await contexts.signed.newPage();
  await page.setViewport({ width: 1280, height: 900 });
  await page.goto(`${P}/`, { waitUntil: 'domcontentloaded' });
  check('with broadcasts off the menu has no LIVE', (await page.$$('.nav a[href="/opendmtq/live.php"], .tabbar a[href="/opendmtq/live.php"]')).length === 0);
  check('nor the home page a way to watch, or a box of broadcasts', (await page.$('#watch-live')) === null && (await page.$('.broadcasts')) === null);
  await page.goto(`${P}/player.php?id=1`, { waitUntil: 'domcontentloaded' });
  check('nor a player page their past broadcasts', !(await page.$$eval('.card h2', hs => hs.some(h => /Past broadcasts/.test(h.textContent)))));
  const answer = await page.goto(`${P}/live.php?p=1`, { waitUntil: 'domcontentloaded' });
  check('a link to the live page says broadcasts are off', answer.status() === 200 && /Broadcasts are off/.test(await textOf(page, '.live-off')), await textOf(page, 'main'));
  const listed = await page.evaluate(async () => (await fetch('/opendmtq/live.php?list=1')).json());
  check("and the live page's own look says so too", listed.off === true && listed.live.length === 0, JSON.stringify(listed));
  const media = await page.evaluate(async () => (await fetch('/opendmtq/live-media.php/1/index.m3u8')).status);
  check('no broadcast is served', media === 404, String(media));
  await page.goto(`${A}/recordings`, { waitUntil: 'domcontentloaded' });
  check("the owner's Broadcasts page says they are off, with the way to turn them on",
    /Broadcasts are off/.test(await textOf(page, '#broadcasts')) && (await page.$('#broadcasts button[value="broadcasts-on"]')) !== null);
  if (held) {
    await page.goto(`${A}/players`, { waitUntil: 'domcontentloaded' });
    check("and the Players page that the switches wait for them", /Broadcasts are off for the whole server/.test(await textOf(page, 'main')) && /On · server off/.test(await textOf(page, 'main')));
    // The note above the search keeps room under it (it sat against the search's edge).
    const gap = await page.evaluate(() => {
      const note = document.querySelector('main .flash.note'), search = document.querySelector('#player-search');
      return note && search ? search.getBoundingClientRect().top - note.getBoundingClientRect().bottom : null;
    });
    check("and its note has room between it and the search under it", gap !== null && gap >= 8, String(gap));
  }
  await page.close();
}

// No app for this server yet (the empty stage: nothing built, nothing being built): the home page's download is drawn
// waiting, no way to a page that says the same, with the line under it saying why (SRV-91).
async function noAppYet(contexts) {
  const page = await contexts.signed.newPage();
  await page.setViewport({ width: 1280, height: 900 });
  await page.setCookie({ name: 'opendmtq_lang', value: 'en', url: P });
  await page.goto(`${P}/`, { waitUntil: 'domcontentloaded' });
  const got = await page.$eval('.stage-acts .button.get', b => ({
    link: b.tagName === 'A' && b.hasAttribute('href'), waiting: b.getAttribute('aria-disabled') === 'true',
    lit: getComputedStyle(b).backgroundImage !== 'none',
    why: (document.getElementById(b.getAttribute('aria-describedby') || '-') || { textContent: '' }).textContent.trim(),
  })).catch(e => ({ error: String(e) }));
  check('with no app yet the home page draws its download waiting, the line under it saying why',
    got.link === false && got.waiting && !got.lit && got.why === 'There is no app for this server yet.', JSON.stringify(got));
  await page.close();
}

// The bars on screens held sideways, from a phone on its side to a laptop at 200 % (600 to 1000 px wide, 360 and 400
// tall), in both languages, with LIVE and its count in the site's menu (the widest it gets): the site's sections either
// all in the top row, each one's words 8 px or more clear of the keys at its end and its middle its own to press, or all at
// the thumb, each pressed where it is; the admin pages' ten pages all in view, none past the row's edge. Before: from 600
// to 700 px the site's last section ran under the language keys (a press on SONGS switched the language), and below 620
// px the admin pages' Logs lay past the screen's edge with no sign there was more. One page each, its window resized.
async function barsSideways(contexts) {
  const misses = [];
  let views = 0;
  for (const lang of ['en', 'ko']) {
    for (const url of [`${P}/ranking.php`, `${A}/players`]) {
      const page = await contexts.signed.newPage();
      await page.setViewport({ width: 1000, height: 400 });
      await page.setCookie({ name: 'opendmtq_lang', value: lang, url });
      await page.goto(url, { waitUntil: 'networkidle2' });
      for (let width = 600; width <= 1000; width += 20) {
        for (const height of [360, 400]) {
          await page.setViewport({ width, height });
          views++;
          const miss = await page.evaluate(() => {
            const shown = el => !!el && getComputedStyle(el).display !== 'none' && el.getBoundingClientRect().width > 0;
            const words = a => { const r = document.createRange(); r.selectNodeContents(a); return [...r.getClientRects()].filter(x => x.width > 0.5); };
            const own = a => { const b = a.getBoundingClientRect(); const hit = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2); return hit && a.contains(hit) ? '' : `${a.textContent.trim()} is under ${hit ? hit.tagName.toLowerCase() + (typeof hit.className === 'string' && hit.className ? '.' + hit.className.split(' ')[0] : '') : 'nothing'}`; };
            if (document.documentElement.scrollWidth > innerWidth) return `the page is ${document.documentElement.scrollWidth} px wide`;
            const pages = document.querySelector('.bar .nav.pages');
            if (pages) {
              // The admin pages: every page whole inside the row (and the window), nothing reached only by scrolling it.
              const row = pages.getBoundingClientRect();
              for (const a of pages.querySelectorAll('a')) {
                const b = a.getBoundingClientRect();
                if (b.left < Math.max(0, row.left) - 1 || b.right > Math.min(innerWidth, row.right) + 1) return `${a.textContent.trim()} at ${Math.round(b.left)}..${Math.round(b.right)}, past the row's edge (${Math.round(row.left)}..${Math.round(row.right)})`;
              }
              return '';
            }
            const nav = document.querySelector('.bar .nav'), tab = document.querySelector('.tabbar'), keys = document.querySelector('.bar-end');
            if (!shown(nav)) {
              if (!shown(tab)) return 'the sections are nowhere';
              for (const a of tab.querySelectorAll('a')) { const o = own(a); if (o) return `at the thumb: ${o}`; }
              return '';
            }
            const edge = keys.getBoundingClientRect().left;
            for (const a of nav.querySelectorAll('a')) {
              const right = Math.max(...words(a).map(r => r.right));
              if (right > edge - 8) return `${a.textContent.trim().replace(/\s+/g, ' ')} ends at ${Math.round(right)}, the keys start at ${Math.round(edge)}`;
              const o = own(a);
              if (o) return o;
            }
            return '';
          });
          if (miss) misses.push(`${url.includes('/admin') ? 'admin' : 'site'} ${lang} ${width}x${height}: ${miss}`);
        }
      }
      // What the views between were like, at the narrowest: a picture for people to look at.
      await page.setViewport({ width: 640, height: 360 });
      await page.screenshot({ path: path.join(OUT, 'shots', `sideways-${url.includes('/admin') ? 'admin' : 'site'}-${lang}-640x360.jpg`), type: 'jpeg', quality: 72 });
      await page.close();
    }
  }
  check(`on screens held sideways the bars keep every section whole, clear of the keys and its own to press (${views} views)`, misses.length === 0, misses.slice(0, 8).join(' ; '));
}

// The background at the top of every page against its content column, at seven widths from a phone's to a large monitor's:
// the shards (.facets) and the lit panes (body::before), each drawn alone (the page's content and its perforation hidden)
// and read back pixel by pixel. No shard's light anywhere within 16 px of the column (so none under a card, at its edge or
// in its cut corner, nor at a key of the bar, which stand in it), and no pane's edge in it: no step of more than 5 levels
// between two pixels side by side or one under the other. What is drawn is measured, whatever draws it. Both scroll with
// the page, so the top of it, whole, is every place they can be. Before: the shards stood in cards' cut corners and ended
// at their edges on 50 of 147 views, and the panes' edges ran down through the column on every page.
const BACKGROUND_PAGES = [
  ['home', `${P}/`], ['rankings', `${P}/ranking.php`], ['rankings-month', `${P}/ranking.php?sort=month`], ['songs', `${P}/songs.php`],
  ['song', `${P}/song.php?id=1`], ['player', `${P}/player.php?id=1`], ['live', `${P}/live.php`], ['download', `${P}/download.php`],
  ['my page', `${P}/me.php`], ['licenses', `${P}/licenses.php`],
  ['admin-status', `${A}/`], ['admin-app', `${A}/app`], ['admin-songs', `${A}/songs`], ['admin-players', `${A}/players`],
  ['admin-player', `${A}/players/1`], ['admin-accounts', `${A}/accounts`], ['admin-recordings', `${A}/recordings`],
  ['admin-backups', `${A}/backups`], ['admin-notices', `${A}/maintenance`], ['admin-server', `${A}/server`],
  ['admin-requests', `${A}/logs`], ['admin-setup', `${A}/setup?step=files`],
];
async function backgroundClear(contexts) {
  const misses = [];
  let views = 0;
  // A page of its own reads the pictures back (a canvas), with nothing else on it.
  const reader = await contexts.anon.newPage();
  await reader.setContent('<canvas></canvas>');
  const read = (png, band, mode) => reader.evaluate(async (b64, band, mode) => {
    const img = new Image();
    img.src = `data:image/png;base64,${b64}`;
    await img.decode();
    const c = document.querySelector('canvas');
    c.width = img.width;
    c.height = img.height;
    const g = c.getContext('2d', { willReadFrequently: true });
    g.drawImage(img, 0, 0);
    const d = g.getImageData(0, 0, c.width, c.height).data;
    // The band's pixels: from its left edge up to the one before its right edge (a shard may start at that edge).
    const x0 = Math.max(0, Math.floor(band[0])), x1 = Math.min(c.width - 1, Math.ceil(band[1]) - 1);
    const at = (x, y) => (y * c.width + x) * 4;
    let found = 0, first = '';
    for (let y = 0; y < c.height; y++) {
      for (let x = x0; x <= x1; x++) {
        const i = at(x, y);
        let hit;
        if (mode === 'shards') {
          // Anything but the page's own field (#11151a): a shard's light.
          hit = Math.abs(d[i] - 17) + Math.abs(d[i + 1] - 21) + Math.abs(d[i + 2] - 26) > 6;
        } else {
          // A step from this pixel to the next one across or down: an edge, where a light ends on a line. More than the
          // browser's own dithering of a smooth light (2 levels either way, so steps of 4), less than the panes' old edge
          // (14 levels where it was whole).
          const step = j => Math.max(Math.abs(d[i] - d[j]), Math.abs(d[i + 1] - d[j + 1]), Math.abs(d[i + 2] - d[j + 2]));
          hit = (x < x1 && step(at(x + 1, y)) > 5) || (y + 1 < c.height && step(at(x, y + 1)) > 5);
        }
        if (hit && !found++) first = `${x},${y} rgb(${d[i]},${d[i + 1]},${d[i + 2]})`;
      }
    }
    return { found, first };
  }, png, band, mode);
  for (const [name, url] of BACKGROUND_PAGES) {
    const page = await contexts.signed.newPage();
    await page.setViewport({ width: 1280, height: 900 });
    await page.setCookie({ name: 'opendmtq_lang', value: 'en', url });
    await page.goto(url, { waitUntil: 'networkidle2' });
    // The motion as a page arrives, at rest.
    await page.waitForFunction(() => !document.documentElement.classList.contains('arriving'), { timeout: 3000, polling: 100 }).catch(() => {});
    for (const width of [360, 640, 744, 1024, 1280, 1440, 1920]) {
      await page.setViewport({ width, height: 900 });
      await page.evaluate(() => scrollTo(0, 0));
      // The column the page's content stands in: its main's own room inside its padding (the bar's is the same).
      const column = await page.evaluate(() => {
        const main = document.querySelector('main.wrap');
        const r = main.getBoundingClientRect(), s = getComputedStyle(main);
        return [r.left + parseFloat(s.paddingLeft), r.right - parseFloat(s.paddingRight)];
      });
      const band = [column[0] - 16, column[1] + 16];
      for (const mode of ['shards', 'panes']) {
        views++;
        await page.evaluate(mode => {
          let style = document.getElementById('background-alone');
          if (!style) { style = document.createElement('style'); style.id = 'background-alone'; document.head.append(style); }
          // The content and the perforation out of the way; then the one of the two being measured.
          style.textContent = `body > *:not(.facets) { visibility: hidden !important; } body { background-image: none !important; }
            ${mode === 'shards' ? 'body::before { display: none !important; }' : '.facets { display: none !important; }'}`;
        }, mode);
        const png = await page.screenshot({ encoding: 'base64' });
        const seen = await read(png, band, mode);
        if (seen.found) misses.push(`${name} ${width}: ${mode === 'shards' ? 'a shard' : "a pane's edge"} within the column (${Math.round(band[0])}..${Math.round(band[1])}) at ${seen.first}, ${seen.found} px`);
      }
      await page.evaluate(() => document.getElementById('background-alone').remove());
    }
    await page.close();
  }
  await reader.close();
  check(`no shard and no pane's edge in the content column, at its cards or the bar's keys, on every page at every width (${views} views)`, misses.length === 0,
    misses.slice(0, 8).join(' ; '));
}

// The hall of fame (the Rankings page's This month tab: the months before) at a laptop's width and a phone's, in both
// languages: its months are columns of the card itself, no fill, edge or shadow of their own (no box in the card), and side
// by side they run across all of the card's room, the last one ending where that room does. Before: each month a filled
// box, the two of them on the card's left half (589 of 1192 px), its right half empty.
async function hallOfFame(contexts) {
  for (const [width, height] of [[1280, 900], [360, 740]]) {
    for (const lang of ['en', 'ko']) {
      const page = await contexts.signed.newPage();
      await page.setViewport({ width, height, ...(width < 700 ? { isMobile: true, hasTouch: true } : {}) });
      await page.setCookie({ name: 'opendmtq_lang', value: lang, url: P });
      await page.goto(`${P}/ranking.php?sort=month`, { waitUntil: 'networkidle2' });
      const seen = await page.evaluate(() => {
        const months = [...document.querySelectorAll('.past-month')];
        if (!months.length) return { months: 0 };
        const card = months[0].closest('.card'), cs = getComputedStyle(card);
        const room = card.getBoundingClientRect().right - parseFloat(cs.paddingRight) - parseFloat(cs.borderRightWidth);
        // A box of its own: a fill, an edge or a shadow.
        const boxed = months.filter(m => {
          const s = getComputedStyle(m);
          return s.backgroundImage !== 'none' || !/^(transparent|rgba\(0, 0, 0, 0\))$/.test(s.backgroundColor) || parseFloat(s.borderLeftWidth) > 0
            || parseFloat(s.borderTopWidth) > 0 || s.boxShadow !== 'none';
        }).length;
        return { months: months.length, boxed, right: Math.round(Math.max(...months.map(m => m.getBoundingClientRect().right))), room: Math.round(room) };
      });
      check(`the hall of fame's months are columns of its card across all of its room, no box of their own (${width}px, ${lang})`,
        seen.months >= 1 && seen.boxed === 0 && Math.abs(seen.right - seen.room) <= 2, JSON.stringify(seen));
      await page.close();
    }
  }
}

// A row's More on the Players page and the Accounts page, at a phone's width and a laptop's: an account's row has one
// button of its own beside its player's Link (its More, as a player's row has), its four changes in the panel More opens,
// whole and on top; Esc closes an open panel and puts the keyboard's place back on its More. Before: each account carried
// its four buttons (on a phone across the row, about 395 px an account), and Esc left a panel open.
async function rowMore(contexts) {
  for (const [width, height] of [[1280, 800], [360, 740]]) {
    const page = await contexts.signed.newPage();
    await page.setViewport({ width, height, ...(width < 700 ? { isMobile: true, hasTouch: true } : {}) });
    for (const [where, url] of [['players', `${A}/players`], ['accounts', `${A}/accounts`]]) {
      await page.goto(url, { waitUntil: 'domcontentloaded' });
      if (where === 'accounts') {
        // The buttons a row shows beside its player's Link, and the row's height on the screen.
        const rows = await page.$$eval('table.accounts tbody tr', all => all.map(tr => ({
          own: [...tr.querySelectorAll('button, summary')].filter(b => !b.closest('.account-link') && b.getClientRects().length
            && !(b.closest('details:not([open])') && !b.closest('summary'))).map(b => b.textContent.trim()),
          high: Math.round(tr.getBoundingClientRect().height),
        })));
        check(`an account's row has its More alone beside its player's Link (${width}px)`,
          rows.length > 0 && rows.every(r => r.own.length === 1), JSON.stringify(rows.slice(0, 3)));
      }
      const more = `table.${where === 'players' ? 'players' : 'accounts'} tbody tr:first-child .row-more`;
      // A row with no More (an account's, before): said, and on to the next.
      if (!await page.$(more)) { check(`a row of the ${where} page has its More (${width}px)`, false); continue; }
      await page.$eval(`${more} > summary`, s => { s.scrollIntoView({ block: 'center' }); s.click(); });
      await page.waitForFunction(m => { const d = document.querySelector(m); return d.open && d.querySelector('.row-more-in'); }, {}, more);
      await pause(250);
      await page.$eval(more, d => d.setAttribute('data-measured', ''));
      const whole = await wholeOnTop(page, '.row-more[data-measured] > .row-more-in');
      const buttons = await page.$$eval('.row-more[data-measured] > .row-more-in button', bs => bs.length);
      await page.$eval(more, d => d.removeAttribute('data-measured'));
      if (where === 'accounts') check(`an account's More opens its four changes whole and on top (${width}px)`, whole.ok && buttons === 4, `${buttons} ${whole.detail}`);
      await page.keyboard.press('Escape');
      await pause(150);
      const closed = await page.$eval(more, d => ({ open: d.open, focus: document.activeElement === d.querySelector('summary') }));
      check(`Esc closes ${where === 'players' ? "a player's" : "an account's"} More and gives the focus back to it (${width}px)`, !closed.open && closed.focus, JSON.stringify(closed));
    }
    await page.close();
  }
}

// The Server page's forms on a laptop's screen: the port's field as wide as a port, its button beside it; and the answer
// to the name's form (sent as it is, which the server refuses as the same name) comes back to the name's card with its
// heading clear of the bar and of the band of the answer's words under it. Before: the port's field was 1011 px for five
// digits, and the answer's page landed with the card's heading and first lines under the bar and the band.
async function serverForms(contexts) {
  for (const width of [1280, 1024]) {
    const page = await contexts.signed.newPage();
    await page.setViewport({ width, height: 800 });
    await page.setCookie({ name: 'opendmtq_lang', value: 'en', url: A });
    await page.goto(`${A}/server`, { waitUntil: 'domcontentloaded' });
    const port = await page.evaluate(() => {
      const field = document.querySelector('#port input[name=port]'), button = document.querySelector('#port form button');
      if (!field || !button) return null;
      const f = field.getBoundingClientRect(), b = button.getBoundingClientRect();
      return { field: Math.round(f.width), beside: b.left >= f.right && b.top < f.bottom && b.bottom > f.top };
    });
    check(`the Server page's port field is as wide as a port, its button beside it (${width}px)`, port && port.field <= 240 && port.beside, JSON.stringify(port));
    await page.$eval('#name form', f => f.scrollIntoView({ block: 'center' }));
    await settle(page, () => page.click('#name form button'));
    await pause(600);
    const card = await page.evaluate(() => {
      const bar = document.querySelector('.bar').getBoundingClientRect();
      const band = document.querySelector('.bar > .said-stack');
      const heading = document.querySelector('#name h2').getBoundingClientRect();
      return { at: location.hash, heading: Math.round(heading.top), bar: Math.round(bar.bottom), band: band ? Math.round(band.getBoundingClientRect().bottom) : null };
    });
    check(`an answer about the name comes back to its card with its heading clear of the bar and the band (${width}px)`,
      card.at === '#name' && card.heading >= Math.max(card.bar, card.band || 0) + 8, JSON.stringify(card));
    await page.close();
  }
}

// The setup's list of what it found on the server PC (run.sh puts them in the owner's home): the folder of the game's
// files with no songs in it is named the client data folder, as the look at it says, and its row asks nothing about songs;
// an archive that cannot be read leaves its row with no Import to press and no choice of songs once the look says so.
// Before: "Client data and song data folder" beside "client data alone: no song data", and "Import the songs too" ticked
// on both rows, the second beside an archive nothing can be imported from.
async function setupFound(contexts) {
  const page = await contexts.signed.newPage();
  await page.setViewport({ width: 1280, height: 900 });
  await page.setCookie({ name: 'opendmtq_lang', value: 'en', url: A });
  await page.goto(`${A}/setup?step=files`, { waitUntil: 'domcontentloaded' });
  // Every file's look answered (admin.js asks two at a time).
  const looked = await until(page, () => [...document.querySelectorAll('.setup-found [data-what]')].every(w => w.matches('.ok, .bad')), null, 30000);
  const rows = await page.$$eval('.setup-found > li', all => all.map(li => ({
    path: li.querySelector('.setup-path').textContent.trim(),
    trees: [...li.querySelectorAll('.setup-tree')].map(t => t.textContent.trim().split(':')[0]),
    songs: [...li.querySelectorAll('label.check')].filter(l => !l.hidden && l.getClientRects().length).length,
    pressable: [...li.querySelectorAll('button')].filter(b => !b.disabled).length,
    files: [...li.querySelectorAll('.setup-file')].map(f => f.textContent.trim()),
  })));
  const alone = rows.find(r => r.path.endsWith('/Downloads/DMTQ')) || {};
  const archive = rows.find(r => r.files.some(f => f.startsWith('dmtq-files.rar'))) || {};
  check('the setup names the folder it found by what it holds and offers its songs only where there may be some',
    looked && alone.trees && alone.trees[0] === 'Client data folder' && alone.songs === 0 && alone.pressable === 1, JSON.stringify(alone));
  check('an archive that cannot be read leaves its row with nothing to press and no choice of songs',
    looked && archive.pressable === 0 && archive.songs === 0, JSON.stringify(archive));
  await page.close();
}

// The checker itself: one of each thing it looks for must be seen.
async function self(contexts) {
  const page = await contexts.anon.newPage();
  await page.setViewport({ width: 800, height: 600 });
  await page.goto(`file://${path.join(__dirname, 'defects.html')}`, { waitUntil: 'load' });
  const seenOnPage = await audit(page);
  const kinds = new Set(seenOnPage.map(f => f.kind));
  for (const kind of ['clipped', 'sticks-out', 'overlap', 'rows', 'columns', 'past-screen', 'page-wide', 'covered', 'contrast', 'default-control', 'no-style', 'small-target', 'broken-image', 'side-scroll', 'broken-word', 'broken-figure', 'split-sentence',
    'touching', 'edge-touch', 'tight-padding', 'uneven-gaps', 'off-scale']) {
    check(`the checker sees ${kind}`, kinds.has(kind));
  }
  // A box filled with a colour the stylesheet mixes (color-mix, as the pages' red and green message boxes are): the browser
  // reads it back as color(srgb ...), and a button right under it touches it all the same.
  check('the checker sees a box with a mixed colour touching the button under it',
    seenOnPage.some(f => f.kind === 'touching' && /#mixed-box/.test(f.detail) && /#mixed-under/.test(f.detail)),
    seenOnPage.filter(f => /mixed/.test(`${f.at} ${f.detail}`)).map(f => `${f.kind} ${f.detail}`).join(' ; '));
  // A band across the page lies on the next one by design (the site's alert on the home page's stage), but a box right
  // under a band is set against it: the room the checker leaves the page's bands is theirs alone.
  check("the checker sees a box set against the page's band, though the page's bands may lie one on the other",
    seenOnPage.some(f => f.kind === 'touching' && /#band/.test(f.detail) && /#under-band/.test(f.detail)),
    seenOnPage.filter(f => /band/.test(`${f.at} ${f.detail}`)).map(f => `${f.kind} ${f.detail}`).join(' ; '));
  // And the room between things laid out as the site lays them out (panels a gap apart, buttons in a row, words inside
  // their padding) is no finding: the checker sees faults, not every box.
  await page.setContent(`<!doctype html><style>:root { --gap: 20px; --pad: 24px } body { margin: 0; background: #11151a; color: #eee; font: 14px/1.6 sans-serif }
    main { display: grid; gap: var(--gap); padding: 24px } .card { padding: var(--pad); background: #222 } .line { display: flex; gap: 10px; margin: 14px 0 0 }
    .btn { display: inline-flex; align-items: center; height: 42px; padding: 0 16px; background: #333 } p { margin: 0 0 14px }</style>
    <div style="position: relative; height: 110px"><div class="said-stack" style="position: absolute; left: 0; right: 0; top: 0; box-shadow: 0 12px 26px -12px rgba(0, 0, 0, 0.8)">
      <p style="margin: 0; padding: 11px 24px; background: color-mix(in srgb, #8cf23d 13%, #1a1f25)">A message, as the admin pages say one under their bar.</p>
      <p style="margin: 0; padding: 11px 24px; background: color-mix(in srgb, #8cf23d 13%, #1a1f25); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06)">And the next one, right under it.</p></div></div>
    <div style="padding: 11px 24px; background: color-mix(in srgb, #ffcf3d 12%, #11151a)">A band across the page, as the site's notice under its bar.</div>
    <div style="height: 80px; padding: 0 24px; background: #0b0e12">The page's stage right under it, edge to edge as well.</div>
    <main><div class="card"><p>A panel with words in its padding.</p><div class="line"><span class="btn">One</span><span class="btn">Two</span><span class="btn">Three</span></div></div>
    <div class="card"><p>Another, a gap below the first.</p></div></main>`);
  await page.addScriptTag({ content: spacing });
  const clean = await page.evaluate(() => window.spacingAudit());
  check('the checker sees no fault in a page laid out well', clean.length === 0, JSON.stringify(clean).slice(0, 300));
  // And two primary buttons on one screen of an owner's page (its address makes it one), not one of them far down the
  // page, nor one that cannot be pressed.
  const owner = await contexts.anon.newPage();
  await owner.setViewport({ width: 800, height: 600 });
  await owner.goto(`${A}/login`, { waitUntil: 'domcontentloaded' });
  const planted = async html => { await owner.setContent(html); return (await twoPrimaries(owner)).length; };
  const together = await planted('<button class="btn btn-primary">One</button><button class="btn btn-primary">Two</button>');
  const apart = await planted('<button class="btn btn-primary">One</button><div style="height:1200px"></div><button class="btn btn-primary">Two</button>');
  const waiting = await planted('<button class="btn btn-primary">One</button><button class="btn btn-primary" disabled>Two</button>');
  check('the checker sees two-primaries', together === 1 && apart === 0 && waiting === 0, `${together} ${apart} ${waiting}`);
  await owner.close();
}

const visible = (page, selector) => page.$eval(selector, e => !e.hidden && getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().height > 0).catch(() => false);
const textOf = (page, selector) => page.$eval(selector, e => e.textContent).catch(() => '');
// An ID typed into a sign-in's field as a person does, over whatever the page put there: the field comes back filled with the
// ID last used on that browser (forms.js and admin.js, data-remember).
const typeId = async (page, selector, text) => {
  await page.$eval(selector, e => { e.value = ''; });
  await page.type(selector, text);
};
const noFindings = async (page, name) => {
  // The layout, and on the owner's pages one primary button to a screen, in whatever state the steps left the page.
  const items = [...await audit(page), ...await twoPrimaries(page)];
  check(`${name}: nothing wrong with the layout`, items.length === 0, items.slice(0, 6).map(f => `${f.kind} ${f.at} ${f.detail}`.slice(0, 140)).join(' ; '));
};

// What a press does, done: the page loaded again, or a change made in place (admin.js counts those, window.odqChanges).
// Thirty seconds at most.
async function settle(page, act) {
  const before = await page.evaluate(() => window.odqChanges || 0).catch(() => 0);
  const loaded = page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 30000 });
  const changed = page.waitForFunction(n => (window.odqChanges || 0) > n, { timeout: 30000, polling: 100 }, before);
  // The one that does not happen ends in an error later, which nobody waits for.
  loaded.catch(() => {});
  changed.catch(() => {});
  const never = p => p.catch(() => new Promise(() => {}));
  let timer;
  const late = new Promise((_, fail) => { timer = setTimeout(() => fail(new Error('the press neither loaded a page nor changed this one')), 30000); });
  // The press itself may fail (nothing there to press): its own error then, and no timer left to fail the run later.
  try {
    await act();
    await Promise.race([never(loaded), never(changed), late]);
  } finally {
    clearTimeout(timer);
  }
}


// Pages left open while things change (the notices and away stages): their own looks run ten times as often, their
// timers sped up before the page's scripts run, so that a change shows in seconds; the server's answers are as they are.
function quickTimers() {
  const every = window.setInterval;
  window.setInterval = (fn, ms, ...rest) => every(fn, Math.max(250, (ms || 0) / 10), ...rest);
}
// A mark put on the window once the page is open (openAlone()), which only a page opened anew would lose: what changed
// came by itself into the same page.
const keptOpen = page => page.evaluate(() => window.keptOpen === true).catch(() => false);
// A page left open in a window of its own (a context of its own, signed in): the browser keeps only the front tab of a
// window in sight, and a page out of sight rightly asks nothing (it catches up when it is looked at again).
async function openAlone(contexts, url) {
  const context = await contexts.browser.createBrowserContext();
  await signIn(context);
  const page = await context.newPage();
  await page.evaluateOnNewDocument(quickTimers);
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  await page.evaluate(() => { window.keptOpen = true; });
  return page;
}
// Pictures of pages left open, as they are now, at a phone's width and a laptop's (changing a page's width does not open it
// anew): OUT/shots/<prefix>-<name>-<width>.jpg.
async function shots(pages, names, prefix) {
  for (const [i, page] of pages.entries()) {
    for (const width of [360, 1280]) {
      await page.setViewport({ width, height: 900 });
      await pause(400);
      await page.screenshot({ path: path.join(OUT, 'shots', `${prefix}-${names[i]}-${width}.jpg`), type: 'jpeg', quality: 72, fullPage: true }).catch(() => {});
    }
  }
}
// Until the page says so (test, run in the page with arg), for ms at most: whether it came.
async function until(page, test, arg, ms = 90000) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    if (await page.evaluate(test, arg).catch(() => false)) return true;
    await pause(500);
  }
  return false;
}

// A form on the page, sent by pressing its button: the page coming back afterwards, or changed in place.
async function press(page, selector) {
  await settle(page, () => page.click(selector));
}

// A press that asks first: the question is the site's own, not the browser's, and its Continue goes on.
async function pressAndConfirm(page, selector) {
  await page.click(selector);
  await page.waitForSelector('#ask[open]');
  await settle(page, () => page.click('#ask [value=yes]'));
}

// A floating layer (a row's menu, a tooltip, a question) whole and on top: points over all of it, five by five just
// inside its edges, each in the window and each hitting the layer itself (elementFromPoint), not a card drawn over it or
// the page behind a part cut off. A layer the pointer passes through (a tooltip) takes the pointer for the measurement.
// Pictures cannot tell a menu drawn under a card's glass from one on top of it; this can.
async function wholeOnTop(page, selector) {
  return page.$eval(selector, layer => {
    const passes = getComputedStyle(layer).pointerEvents === 'none';
    if (passes) layer.style.pointerEvents = 'auto';
    const r = layer.getBoundingClientRect();
    const missed = [];
    for (let i = 0; i < 5; i++) {
      for (let j = 0; j < 5; j++) {
        const x = r.left + 3 + (r.width - 6) * i / 4, y = r.top + 3 + (r.height - 6) * j / 4;
        if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) { missed.push(`${Math.round(x)},${Math.round(y)} off the window`); continue; }
        const hit = document.elementFromPoint(x, y);
        if (!hit || !layer.contains(hit)) {
          missed.push(`${Math.round(x)},${Math.round(y)} ${hit ? hit.tagName.toLowerCase() + (hit.className && typeof hit.className === 'string' ? '.' + hit.className.split(' ')[0] : '') : 'nothing'}`);
        }
      }
    }
    if (passes) layer.style.pointerEvents = '';
    return { ok: r.width > 0 && r.height > 0 && missed.length === 0, detail: `${Math.round(r.width)}x${Math.round(r.height)} at ${Math.round(r.left)},${Math.round(r.top)}; ${missed.slice(0, 4).join(' ; ')}` };
  }).catch(e => ({ ok: false, detail: String(e).slice(0, 120) }));
}

// Every floating layer of the pages, opened as people open them, at a phone's width and a laptop's: whole and on top.
// The Players page's More on its first row, its last, the only row left after a search, and a row at the window's foot; the
// question one of its buttons asks; the tooltips of the owner's charts and of a player's days on the site.
async function floatingLayers(contexts) {
  for (const [width, height] of [[360, 740], [1280, 800]]) {
    const page = await contexts.signed.newPage();
    await page.setViewport({ width, height, ...(width < 700 ? { isMobile: true, hasTouch: true } : {}) });
    const at = `${width}px`;
    const shown = 'table.players tbody tr:not([style*="none"])';
    const openRow = async (which, name) => {
      // Any open panel closed first, by a press outside, as a person closes one.
      await page.evaluate(() => { for (const d of document.querySelectorAll('.row-more[open]')) d.open = false; });
      const more = await page.evaluateHandle((rows, which) => {
        const all = [...document.querySelectorAll(rows)];
        return (which === 'last' ? all[all.length - 1] : all[0]).querySelector('.row-more');
      }, shown, which);
      await more.evaluate(d => d.querySelector('summary').scrollIntoView({ block: 'nearest' }));
      await more.evaluate(d => d.querySelector('summary').click());
      await page.waitForFunction(d => d.open && d.querySelector('.row-more-in'), {}, more);
      await pause(250);
      await more.evaluate(d => d.setAttribute('data-measured', ''));
      const found = await wholeOnTop(page, '.row-more[data-measured] > .row-more-in');
      await more.evaluate(d => d.removeAttribute('data-measured'));
      check(`a player's More opens whole and on top: ${name}, ${at}`, found.ok, found.detail);
    };
    await page.goto(`${A}/players`, { waitUntil: 'domcontentloaded' });
    await openRow('first', 'the first row');
    await openRow('last', 'the last row');
    // A row at the window's foot: the window made just tall enough for the first row's More and a few pixels more, so that
    // its panel has no room below it.
    await page.evaluate(() => { for (const d of document.querySelectorAll('.row-more[open]')) d.open = false; scrollTo(0, 0); });
    const foot = await page.$eval(`${shown} .row-more > summary`, e => Math.ceil(e.getBoundingClientRect().bottom));
    await page.setViewport({ width, height: foot + 12, ...(width < 700 ? { isMobile: true, hasTouch: true } : {}) });
    await openRow('first', 'a row at the window\'s foot');
    await page.setViewport({ width, height, ...(width < 700 ? { isMobile: true, hasTouch: true } : {}) });
    // A search that leaves one row.
    const name = await page.$eval('table.players tbody tr:nth-child(3)', r => r.dataset.k);
    await page.$eval('#player-search', (e, v) => { e.value = v; e.dispatchEvent(new Event('input', { bubbles: true })); }, name);
    await openRow('first', 'the only row a search leaves');
    // A server with one player, as a new one has: the other rows taken off the page.
    await page.goto(`${A}/players`, { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => { for (const r of document.querySelectorAll('table.players tbody tr:not(:first-child)')) r.remove(); });
    await openRow('first', 'the list of a server with one player');
    // Reset's question over the open panel.
    await page.click('.row-more[open] > .row-more-in button[value=reset]');
    await page.waitForSelector('#ask[open]');
    const ask = await wholeOnTop(page, '#ask[open] > *');
    check(`the question a panel's button asks is whole and on top, ${at}`, ask.ok, ask.detail);
    await page.click('#ask [value=no]');
    await page.screenshot({ path: path.join(OUT, 'shots', `floating-players-one-row-${width}.jpg`), type: 'jpeg', quality: 72 });
    // The tooltips: a mark brought to the middle of the window and pointed at (a finger presses it: the same words), its
    // tooltip measured. The marks pointed at are those a person can reach: drawn, a few pixels at least, and the mark itself
    // under its middle (not one under the bar).
    const tipOf = async (index, of = '[data-tip]') => {
      const mark = (await page.$$(of))[index];
      await mark.evaluate(e => e.scrollIntoView({ block: 'center', inline: 'nearest' }));
      await pause(80);
      const box = await mark.boundingBox();
      const x = box.x + box.width / 2, y = box.y + box.height / 2;
      if (width < 700) await page.touchscreen.tap(x, y); else await page.mouse.move(x, y);
      await pause(150);
      return wholeOnTop(page, '.chart-tip:not([hidden])');
    };
    const reachable = (of = '[data-tip]') => page.$$eval(of, all => all.map((e, i) => {
      const r = e.getBoundingClientRect();
      return r.width >= 4 && r.height >= 4 && getComputedStyle(e).visibility !== 'hidden' ? i : -1;
    }).filter(i => i >= 0));
    // The owner's charts on the status page: the first mark, one in the middle, the last.
    await page.goto(`${A}/`, { waitUntil: 'domcontentloaded' });
    const marks = await reachable();
    for (const index of [marks[0], marks[Math.floor(marks.length / 2)], marks[marks.length - 1]].filter((v, i, a) => v !== undefined && a.indexOf(v) === i)) {
      const tip = await tipOf(index);
      check(`a chart's tooltip on the status page is whole and on top: mark ${index + 1}, ${at}`, tip.ok, tip.detail);
    }
    // The site's: a player's days of plays, the first and the last: the grid's own marks (the bar's name and badge, which
    // carry words too, lead to MY PAGE when pressed).
    await page.goto(`${P}/player.php?id=1`, { waitUntil: 'domcontentloaded' });
    const days = await reachable('.activity [data-tip]');
    check(`a player's page has days to point at, ${at}`, days.length > 0);
    for (const index of [days[0], days[days.length - 1]].filter((v, i, a) => v !== undefined && a.indexOf(v) === i)) {
      const tip = await tipOf(index, '.activity [data-tip]');
      check(`a player's day tooltip on the site is whole and on top: mark ${index + 1}, ${at}`, tip.ok, tip.detail);
    }
    await page.close();
  }
}

// The sign-in forms, the site's and the admin pages', and the Accounts page's password fields, as a person uses them, at a
// phone's width and a laptop's, in both languages: every field named by its label; Show inside the password field, the
// typed text kept clear of it, showing the password and hiding it again with the cursor left in the field; a field left
// empty said right under itself; Enter sending the form; the ID typed last back in its field the next time, the focus then
// on the password (on a computer).
async function signInForms(contexts) {
  const words = { en: ['Show', 'Hide', 'Enter your ID.', 'Enter your password.'], ko: ['보기', '숨기기', '아이디를 입력하세요.', '비밀번호를 입력하세요.'] };
  for (const [form, url, idName, who] of [['site', `${P}/login.php`, 'user', 'dmtq'], ['admin', `${A}/login`, 'name', 'admin']]) {
    for (const [width, height] of [[360, 740], [1280, 800]]) {
      for (const lang of ['en', 'ko']) {
        const at = `${form}, ${width}px, ${lang}`;
        const own = await contexts.browser.createBrowserContext();
        const page = await own.newPage();
        await page.setViewport({ width, height, ...(width < 700 ? { isMobile: true, hasTouch: true } : {}) });
        await page.setCookie({ name: 'opendmtq_lang', value: lang, url: SITE });
        // (The language's cookie is the host's, whatever the port: the admin pages read the same one.)
        await page.goto(url, { waitUntil: 'domcontentloaded' });
        const id = `.signin-form input[name=${idName}]`, pw = '.signin-form input[name=password]';
        const labelled = await page.$$eval('.signin-form input:not([type=hidden])', all => all.every(i => i.labels && i.labels.length && i.labels[0].textContent.trim()));
        check(`every field of the sign-in has its label (${at})`, labelled);
        // Show, inside the field at its right end, the text clear of it.
        const place = await page.evaluate(sel => {
          const f = document.querySelector(sel), b = document.querySelector('.signin-form .pw-toggle');
          if (!b || b.hidden) return null;
          const fr = f.getBoundingClientRect(), br = b.getBoundingClientRect();
          return { inside: br.left >= fr.left && br.right <= fr.right && br.top >= fr.top && br.bottom <= fr.bottom,
            clear: parseFloat(getComputedStyle(f).paddingRight) >= br.width + 4, word: b.textContent.trim() };
        }, pw);
        check(`the password field has Show inside it, the text kept clear of it (${at})`, place && place.inside && place.clear && place.word === words[lang][0], JSON.stringify(place));
        await page.type(pw, 'secret-1');
        // (A page without Show fails here and goes on to the rest.)
        const toggle = await page.$('.signin-form .pw-toggle:not([hidden])');
        if (toggle) await toggle.click();
        const shown = await page.evaluate(sel => [document.querySelector(sel).type, (document.querySelector('.signin-form .pw-toggle') || { textContent: '' }).textContent.trim(), document.activeElement === document.querySelector(sel)], pw);
        if (toggle) await toggle.click();
        const hidden = await page.$eval(pw, e => e.type);
        check(`Show shows the password as typed and hides it again, the field kept (${at})`,
          shown[0] === 'text' && shown[1] === words[lang][1] && (width < 700 || shown[2]) && hidden === 'password', JSON.stringify([shown, hidden]));
        if (width >= 700) await page.screenshot({ path: path.join(OUT, 'shots', `forms-${form}-shown-${lang}-${width}.jpg`), type: 'jpeg', quality: 80 });
        // Empty: the ID's words under the ID.
        await page.$eval(pw, e => { e.value = ''; });
        await page.$eval(id, e => { e.value = ''; });
        await page.click('.signin-form button[type=submit], .signin-form .button');
        await pause(150);
        const under = await page.$eval(`.field:has(${id.replace('.signin-form ', '')}) .field-error`, e => e.textContent.trim()).catch(() => '');
        const focus = await page.evaluate(() => document.activeElement.name);
        check(`a field left empty is said under itself, the focus on it (${at})`, (form === 'site' ? under === words[lang][2] : under !== '') && focus === idName,
          JSON.stringify([under, focus]));
        await page.screenshot({ path: path.join(OUT, 'shots', `forms-${form}-empty-${lang}-${width}.jpg`), type: 'jpeg', quality: 80 });
        await noFindings(page, `the sign-in with a field left empty (${at})`);
        // Enter sends it: a wrong password, said by the server. Only on some of the views: each wrong password counts toward
        // the sign-in's limit for this address (five in ten minutes on the admin pages), and the stages after this one sign
        // in from the same address.
        if (!(width >= 700 && lang === 'en') && !(form === 'site' && width < 700 && lang === 'ko')) {
          await own.close();
          continue;
        }
        await page.type(id, who);
        await page.type(pw, 'not-the-password');
        const sent = await Promise.all([page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 10000 }).then(() => true, () => false), page.keyboard.press('Enter')]);
        check(`Enter in the password field sends the form (${at})`, sent[0] && /\S/.test(await textOf(page, '.signin .error')));
        await page.screenshot({ path: path.join(OUT, 'shots', `forms-${form}-wrong-${lang}-${width}.jpg`), type: 'jpeg', quality: 80 });
        // The next visit: the ID back, the focus on the password on a computer.
        await page.goto(url, { waitUntil: 'domcontentloaded' });
        await pause(100);
        const back = await page.evaluate((sel, pw) => [document.querySelector(sel).value, document.activeElement === document.querySelector(pw)], id, pw);
        check(`the ID typed last is back the next time${width >= 700 ? ', the focus on the password' : ''} (${at})`,
          back[0] === who && (width < 700 || back[1]), JSON.stringify(back));
        await own.close();
      }
    }
  }
  // The Accounts page: Show in both password fields, and two different passwords said before anything is sent.
  const page = await contexts.signed.newPage();
  await page.setViewport({ width: 1280, height: 800 });
  await page.goto(`${A}/accounts`, { waitUntil: 'domcontentloaded' });
  check('both password fields of Make an account have Show', (await page.$$('.account-form .pw-toggle:not([hidden])')).length === 2);
  await page.type('.account-form input[name=name]', 'twotyped');
  await page.type('.account-form input[name=password]', 'one-password');
  await page.type('.account-form input[name=password2]', 'another-one');
  await page.click('.account-form .btn-primary');
  await pause(300);
  // Said under the second field's row (admin.js), which names the words.
  const said = await page.$eval('.account-form input[name=password2]', f => {
    const w = document.getElementById(f.getAttribute('aria-describedby') || '');
    return w ? w.textContent : '';
  }).catch(() => '');
  check('two different passwords are said before anything is sent', /not the same/.test(said) && new URL(page.url()).pathname === '/opendmtq/admin/accounts'
    && await page.evaluate(() => document.activeElement.name) === 'password2', said);
  await page.close();
}

// The pages the patterns below are looked for on: the site's and the owner's, with players, plays and recordings in place.
const PATTERN_PAGES = [
  ['home', `${P}/`], ['rankings', `${P}/ranking.php`], ['player', `${P}/player.php?id=1`], ['song', `${P}/song.php?id=1`],
  ['songs', `${P}/songs.php`], ['live', `${P}/live.php`], ['download', `${P}/download.php`],
  ['admin-status', `${A}/`], ['admin-players', `${A}/players`], ['admin-player', `${A}/players/2`], ['admin-player-banned', `${A}/players/6`],
  ['admin-accounts', `${A}/accounts`],
  ['admin-recordings', `${A}/recordings`], ['admin-songs', `${A}/songs`], ['admin-requests', `${A}/logs`],
  ['admin-plays', `${A}/logs?tab=plays`], ['admin-changes', `${A}/logs?tab=changes`], ['admin-maintenance', `${A}/maintenance`],
  ['admin-backups', `${A}/backups`], ['admin-app', `${A}/app`],
];

// A link in a sentence is drawn in the sentence's own colour, told by its underline: the section's colour is the screen's
// main button's. Every page of the patterns' list, at a phone's width and a laptop's: each link that stands inline among
// loose words of its own line's box (a sentence, not a list's name or a cell's) has the colour of the words around it.
// Before: the home page's "How to install" was a lime link right under the lime download, and the owner's pages' links
// were their amber next to the amber main button.
async function textLinks(contexts) {
  const misses = [];
  for (const [width, height] of [[1280, 900], [360, 740]]) {
    for (const [name, url] of PATTERN_PAGES) {
      const page = await contexts.signed.newPage();
      await page.setViewport({ width, height, ...(width < 700 ? { isMobile: true, hasTouch: true } : {}) });
      await page.setCookie({ name: 'opendmtq_lang', value: 'en', url });
      await page.goto(url, { waitUntil: 'domcontentloaded' });
      const found = await page.evaluate(() => [...document.querySelectorAll('a[href]')].filter(a => {
        const s = getComputedStyle(a), box = a.parentElement;
        if (s.display !== 'inline' || !box || a.closest('.btn, .button, nav, .tabs, [aria-hidden="true"]') || !a.getClientRects().length) return false;
        // Among words of its own: loose text beside it in the same box.
        return [...box.childNodes].some(n => n.nodeType === Node.TEXT_NODE && n.nodeValue.trim());
      }).filter(a => getComputedStyle(a).color !== getComputedStyle(a.parentElement).color)
        .map(a => `"${a.textContent.trim().slice(0, 30)}" ${getComputedStyle(a).color} in ${getComputedStyle(a.parentElement).color}`));
      for (const f of found) misses.push(`${name} ${width}: ${f}`);
      await page.close();
    }
  }
  check('a link in a sentence has the colour of its words, the section\'s colour left to the main button', misses.length === 0, misses.slice(0, 8).join(' ; '));
}

// P1: nothing said only under a mouse pointer. No title anywhere on the pages (a title shows to a mouse alone: a finger and
// the keyboard never see it); every mark with words of its own (data-tip) is reached by the keyboard; and its words show,
// whole and on top, when it has the focus (gone with Escape), when a finger presses it (gone with a second press, or a press
// elsewhere), and under a mouse pointer (gone when the pointer leaves).
async function hoverOnly(contexts) {
  for (const [width, height] of [[360, 740], [1280, 800]]) {
    const touch = width < 700;
    const page = await contexts.signed.newPage();
    await page.setViewport({ width, height, ...(touch ? { isMobile: true, hasTouch: true } : {}) });
    const at = `${width}px`;
    for (const [name, url] of PATTERN_PAGES) {
      await page.goto(url, { waitUntil: 'domcontentloaded' });
      await pause(400);
      const found = await page.evaluate(() => ({
        titled: [...document.querySelectorAll('body [title]')].filter(e => !e.closest('svg') && e.tagName !== 'IFRAME')
          .map(e => `${e.tagName.toLowerCase()}${typeof e.className === 'string' && e.className ? '.' + e.className.split(' ')[0] : ''}: ${e.getAttribute('title').slice(0, 30)}`),
        // Out of the keyboard's reach: not a stop of the Tab key itself, nor a mark of a group of marks (data-tips) that has
        // one, from which the arrow keys go to the others.
        unreached: [...document.querySelectorAll('[data-tip]')].filter(e => e.tabIndex < 0
          && !(e.closest('[data-tips]') && [...e.closest('[data-tips]').querySelectorAll('[data-tip]')].some(m => m.tabIndex === 0)))
          .map(e => `${e.tagName.toLowerCase()}${typeof e.className === 'string' && e.className ? '.' + e.className.split(' ')[0] : ''}`),
        tips: document.querySelectorAll('[data-tip]').length,
      }));
      const titled = [...new Set(found.titled)];
      check(`nothing on ${name} is said only under a mouse pointer: no title, every mark's words reached by the keyboard (${at})`,
        found.titled.length === 0 && found.unreached.length === 0,
        `${found.titled.length} titles: ${titled.slice(0, 4).join(' ; ')} | ${found.unreached.length} marks out of the keyboard's reach: ${[...new Set(found.unreached)].slice(0, 3).join(' ; ')}`);
      if (!found.tips) continue;
      // A group of marks (a chart's, a grid of days) is one stop of the Tab key: from its stop the arrow keys go to the other
      // marks, each showing its words. On a laptop's screen, once a page.
      if (!touch && await page.$('[data-tips] [data-tip]')) {
        const moved = await page.evaluate(async () => {
          // A group with marks to go between: a group of one (the Status page's resources an admin service has sampled
          // once, a server minutes old) has no other mark for an arrow key to reach.
          const groups = [...document.querySelectorAll('[data-tips]')].filter(g => [...g.querySelectorAll('[data-tip]')].some(m => m.getClientRects().length && m.tabIndex === 0));
          const group = groups.find(g => [...g.querySelectorAll('[data-tip]')].filter(m => m.getClientRects().length).length > 1) || groups[0];
          if (!group) return 'no group with a stop';
          const stops = [...group.querySelectorAll('[data-tip]')].filter(m => m.tabIndex === 0);
          if (stops.length !== 1) return `${stops.length} stops in one group`;
          stops[0].scrollIntoView({ block: 'center' });
          stops[0].focus();
          return 'ok';
        });
        const keys = [];
        for (const key of ['ArrowRight', 'ArrowDown', 'ArrowLeft', 'ArrowUp']) {
          const before = await page.evaluate(() => document.activeElement && document.activeElement.dataset.tip);
          await page.keyboard.press(key);
          await pause(80);
          const after = await page.evaluate(() => {
            const a = document.activeElement, box = [...document.querySelectorAll('.chart-tip')].find(b => !b.hidden);
            return a && a.dataset.tip !== undefined ? [a.dataset.tip, box ? box.textContent : ''] : null;
          });
          // Moved to another mark with its words up, or stayed at an edge (a row of one, the last column).
          keys.push(after && (after[0] === before || after[1] === after[0]) ? (after[0] !== before ? 'moved' : 'edge') : 'lost');
        }
        check(`the marks of a group are one stop of the Tab key, the arrow keys going from mark to mark with their words (${name}, ${at})`,
          moved === 'ok' && keys.includes('moved') && !keys.includes('lost'), `${moved} ${keys.join(' ')}`);
        await page.keyboard.press('Escape');
        await page.evaluate(() => document.activeElement && document.activeElement.blur());
      }
      // The first mark and the last one on the page that a person can reach: drawn, a few pixels at least. On a touch
      // screen those a press shows the words of: a mark that is itself a link or a button (the bar's name and badge, which
      // lead to MY PAGE) does what it does when pressed, and shows its words to the pointer and the focus (tips.js).
      const marks = await page.$$eval('[data-tip]', (all, touchScreen) => all.map((e, i) => {
        const r = e.getBoundingClientRect();
        const acts = e.matches('a, button, summary, input, select, textarea, label');
        return r.width >= 4 && r.height >= 4 && getComputedStyle(e).visibility !== 'hidden' && !(touchScreen && acts) ? i : -1;
      }).filter(i => i >= 0), touch);
      for (const index of [marks[0], marks[marks.length - 1]].filter((v, i, a) => v !== undefined && a.indexOf(v) === i)) {
        const mark = (await page.$$('[data-tip]'))[index];
        if (!mark) continue;
        const words = await mark.evaluate(e => e.dataset.tip);
        await mark.evaluate(e => e.scrollIntoView({ block: 'center', inline: 'nearest' }));
        await pause(150);
        const shown = async () => page.evaluate(w => {
          const box = [...document.querySelectorAll('.chart-tip')].find(b => !b.hidden && getComputedStyle(b).display !== 'none');
          return !!box && box.textContent === w;
        }, words);
        const where = `${name}, mark ${index + 1}, ${at}`;
        // The keyboard: its focus shows the words, whole and on top; Escape takes them away. (By the page's own focus(): a
        // chart's mark is a drawing's part, which the test's own way to focus refuses.)
        await mark.evaluate(e => e.focus());
        await pause(150);
        const focused = await shown();
        const whole = await wholeOnTop(page, '.chart-tip:not([hidden])');
        await page.keyboard.press('Escape');
        await pause(150);
        const escaped = !(await shown());
        check(`a mark's words show on its keyboard focus, whole and on top, and go with Escape (${where})`, focused && whole.ok && escaped,
          `${focused} ${whole.detail} ${escaped}`);
        await page.evaluate(() => document.activeElement && document.activeElement.blur());
        const box = await mark.boundingBox();
        if (!box) continue;
        const x = box.x + box.width / 2, y = box.y + box.height / 2;
        if (touch) {
          // A finger: a press shows them, a second press takes them away, and a press elsewhere too.
          await page.touchscreen.tap(x, y);
          await pause(200);
          const tapped = await shown();
          await page.touchscreen.tap(x, y);
          await pause(200);
          const again = !(await shown());
          await page.touchscreen.tap(x, y);
          await pause(200);
          // Elsewhere: the nearest point of the screen where a press does nothing (no link, button, field or mark there).
          const elsewhere = await page.evaluate(() => {
            for (let y = 80; y < innerHeight - 80; y += 12) {
              for (let x = 6; x < innerWidth - 6; x += 12) {
                const hit = document.elementFromPoint(x, y);
                if (hit && !hit.closest('a, button, input, select, textarea, summary, label, [data-tip], [tabindex], video, .nav, .tabbar')) return [x, y];
              }
            }
            return null;
          });
          if (elsewhere) await page.touchscreen.tap(elsewhere[0], elsewhere[1]);
          await pause(200);
          const away = !(await shown());
          check(`a mark's words show when a finger presses it, and go with a second press or a press elsewhere (${where})`, tapped && again && away,
            `${tapped} ${again} ${away}`);
        } else {
          // A mouse: over the mark they show, away from it they go.
          await page.mouse.move(x, y);
          await pause(150);
          const over = await shown();
          await page.mouse.move(2, height - 2);
          await pause(150);
          const left = !(await shown());
          check(`a mark's words show under the mouse pointer and go when it leaves (${where})`, over && left, `${over} ${left}`);
        }
      }
    }
    await page.close();
  }
}

// P7: a switch or a small change on the owner's pages changes the page where it is, without loading the whole page again
// (which flashed it white and lost what was in view): the page's own state changes in place, the server's words come as the
// pages' message at the foot of the screen, and the page itself is the same one (a mark set on it before is still there).
// Without scripts the same buttons still work, by loading the page again.
async function sameWay(page, press, changed, arg) {
  // A mark on the page as it is, and no message left from before.
  await page.evaluate(() => { window.odqSamePage = 'yes'; for (const m of document.querySelectorAll('.flash.float')) m.remove(); });
  const navigated = page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 8000 }).then(() => 'loaded again', () => '');
  await press();
  const done = await Promise.race([navigated, page.waitForFunction(changed, { timeout: 8000 }, arg).then(() => 'changed', () => 'unchanged')]);
  // The server's words, which come with the change.
  await page.waitForSelector('.flash.float', { timeout: 5000 }).catch(() => {});
  await pause(200);
  const same = await page.evaluate(() => window.odqSamePage === 'yes').catch(() => false);
  const said = await page.$eval('.flash.float', e => e.textContent.trim()).catch(() => '');
  const now = await page.evaluate(changed, arg).catch(() => false);
  return { ok: same && now && said !== '', detail: `${done}; same page ${same}; changed ${now}; said "${said.slice(0, 60)}"` };
}

async function inPlace(contexts) {
  const page = await contexts.signed.newPage();
  await page.setViewport({ width: 1280, height: 800 });
  // The Players page: a player's switch on, then off again, each in place.
  await page.goto(`${A}/players`, { waitUntil: 'domcontentloaded' });
  const sw = 'button[form="player-switch"][formaction^="/opendmtq/admin/players/3?"]';
  const stateOf = sel => document.querySelector(sel) && document.querySelector(sel).closest('tr').querySelector('.live-state').className;
  const before = await page.evaluate(stateOf, sw);
  const on = await sameWay(page, () => page.click(sw), ([sel, was]) => {
    const b = document.querySelector(sel);
    return !!b && b.closest('tr').querySelector('.live-state').className !== was;
  }, [sw, before]);
  check("a player's broadcast switch changes their row in place, with the server's words, without loading the page again", on.ok, on.detail);
  const after = await page.evaluate(stateOf, sw);
  const off = await sameWay(page, () => page.click(sw), ([sel, was]) => {
    const b = document.querySelector(sel);
    return !!b && b.closest('tr').querySelector('.live-state').className !== was;
  }, [sw, after]);
  check('and back off the same way', off.ok, off.detail);
  // The Broadcasts page: the server's switch on and off again.
  await page.goto(`${A}/recordings`, { waitUntil: 'domcontentloaded' });
  const word = () => document.querySelector('#broadcasts .auto-line b').textContent;
  await page.waitForSelector('#broadcasts .auto-line b');
  const was = await page.evaluate(word);
  const flip = () => page.click('#broadcasts button[name=action][value^="broadcasts-"]').then(async () => {
    // Turning them off with someone on air asks first: yes.
    if (await page.$('#ask[open]')) await page.click('#ask [value=yes]');
  });
  const server1 = await sameWay(page, flip, w => document.querySelector('#broadcasts .auto-line b').textContent !== w, was);
  const was2 = await page.evaluate(word);
  const server2 = await sameWay(page, flip, w => document.querySelector('#broadcasts .auto-line b').textContent !== w, was2);
  check("the Broadcasts page's switch for the server changes the page in place, both ways", server1.ok && server2.ok, `${server1.detail} | ${server2.detail}`);
  // What new players start with and the quality, saved in place.
  const saved = await sameWay(page, () => page.click('#broadcasts form:has(input[name=action][value=settings]) button'), () => !!document.querySelector('.flash.float'));
  check("the Broadcasts page's settings are saved in place", saved.ok, saved.detail);
  // The Accounts page: an account switched off and on again.
  await page.goto(`${A}/accounts`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('tr:has(input[value="manager"]) .account-state');
  const stateText = () => document.querySelector('tr:has(input[value="manager"]) .account-state').textContent.trim();
  const acc = await page.evaluate(stateText);
  const accOff = await sameWay(page, () => page.click('tr:has(td.primary) form:has(input[value=off]):has(input[value="manager"]) button'),
    w => { const c = document.querySelector('tr:has(input[value="manager"]) .account-state'); return !!c && c.textContent.trim() !== w; }, acc);
  const acc2 = await page.evaluate(stateText);
  const accOn = await sameWay(page, () => page.click('tr:has(td.primary) form:has(input[value=on]):has(input[value="manager"]) button'),
    w => { const c = document.querySelector('tr:has(input[value="manager"]) .account-state'); return !!c && c.textContent.trim() !== w; }, acc2);
  check('an account is switched off and on again in place', accOff.ok && accOn.ok, `${accOff.detail} | ${accOn.detail}`);
  // The Songs page: a song hidden and shown again.
  await page.goto(`${A}/songs`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('tr[data-n="2"]');
  const hidden = () => !!document.querySelector('tr[data-n="2"] .mark.off');
  const hide = await sameWay(page, () => page.click('tr[data-n="2"] form:has(input[name=action][value=hide]) button'), () => !!document.querySelector('tr[data-n="2"] .mark.off'));
  const show = await sameWay(page, () => page.click('tr[data-n="2"] form:has(input[name=action][value=show]) button'), () => !document.querySelector('tr[data-n="2"] .mark.off'));
  check('a song is hidden and shown again in place', hide.ok && show.ok && !(await page.evaluate(hidden)), `${hide.detail} | ${show.detail}`);
  // The Notices page's maintenance card (the site's notice has the card above it): on (it asks first), then off.
  await page.goto(`${A}/maintenance`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#maintenance .auto-line b');
  const maintWord = () => document.querySelector('#maintenance .auto-line b').textContent;
  const m1 = await page.evaluate(maintWord);
  const mOn = await sameWay(page, async () => { await page.click('#maintenance button[name=action][value=on]'); await page.waitForSelector('#ask[open]'); await page.click('#ask [value=yes]'); },
    w => document.querySelector('#maintenance .auto-line b').textContent !== w, m1);
  const m2 = await page.evaluate(maintWord);
  const mOff = await sameWay(page, () => page.click('#maintenance button[name=action][value=off]'), w => document.querySelector('#maintenance .auto-line b').textContent !== w, m2);
  check('maintenance is turned on and off again in place', mOn.ok && mOff.ok, `${mOn.detail} | ${mOff.detail}`);
  await page.screenshot({ path: path.join(OUT, 'shots', 'patterns-in-place-maintenance-1280.jpg'), type: 'jpeg', quality: 80 });
  await page.close();
  // Without scripts the switch still works: the page loads again with the change and the server's words.
  const plain = await contexts.signed.newPage();
  await plain.setJavaScriptEnabled(false);
  await plain.setViewport({ width: 1280, height: 800 });
  await plain.goto(`${A}/players`, { waitUntil: 'domcontentloaded' });
  const plainBefore = await plain.$eval(sw, b => b.textContent.trim());
  await Promise.all([plain.waitForNavigation({ waitUntil: 'domcontentloaded' }), plain.click(sw)]);
  const plainAfter = await plain.$eval(sw, b => b.textContent.trim());
  const plainSaid = await textOf(plain, '.flash');
  await Promise.all([plain.waitForNavigation({ waitUntil: 'domcontentloaded' }), plain.click(sw)]);
  check("without scripts a player's switch still works, by loading the page again", plainBefore !== plainAfter && /\S/.test(plainSaid), `${plainBefore} -> ${plainAfter}: ${plainSaid}`);
  await plain.close();
}

// P9: the owner's other forms as the sign-in is: every field named by a label; a field that cannot go as it is said right
// under it (not in a message at the top of the page), with the focus on it; the search boxes marked as what they are.
async function formsLook(contexts) {
  const FORMS = [
    ['Make an account', `${A}/accounts`, '.account-form', 'input[name=name]', 'a', '.account-form button.btn-primary'],
    ['Make token', `${A}/accounts`, '#tokens form', 'input[name=token_name]', '', '#tokens form button:not([type=button])'],
    ["the setup's account", `${A}/setup?step=players`, 'form[action$="/setup/player"]', 'input[name=name]', '!', 'form[action$="/setup/player"] button'],
    ["the recordings' limits", `${A}/recordings`, '.rec-limits', 'input[name=cap_gb]', '0', '.rec-limits button'],
    ['Add a webhook', `${A}/maintenance`, '.hook-new', 'input[name=url]', 'not an address', '.hook-new button:not([type=button])'],
    ["The app's name", `${A}/server`, '#name form', 'input[name=name]', 'My "server"', '#name form button'],
  ];
  for (const [width, height] of [[360, 740], [1280, 800]]) {
    for (const lang of ['en', 'ko']) {
      const page = await contexts.signed.newPage();
      await page.setViewport({ width, height, ...(width < 700 ? { isMobile: true, hasTouch: true } : {}) });
      await page.setCookie({ name: 'opendmtq_lang', value: lang, url: ADMIN });
      const at = `${width}px, ${lang}`;
      for (const [name, url, form, field, bad, send] of FORMS) {
        await page.goto(url, { waitUntil: 'domcontentloaded' });
        const named = await page.$$eval(`${form} :is(input, select, textarea):not([type=hidden])`, all => all.filter(f => {
          const r = f.getBoundingClientRect();
          return r.width > 0 && !(f.labels && f.labels.length) && !f.getAttribute('aria-label') && !f.getAttribute('aria-labelledby');
        }).map(f => f.name));
        if (bad !== null) await page.$eval(`${form} ${field}`, (f, v) => { f.value = v; }, bad);
        await page.$eval(send, b => b.scrollIntoView({ block: 'center' }));
        await page.click(send);
        await pause(400);
        const said = await page.evaluate((formSel, fieldSel) => {
          const f = document.querySelector(`${formSel} ${fieldSel}`);
          const ids = (f.getAttribute('aria-describedby') || '').split(' ').filter(Boolean);
          const words = ids.map(id => document.getElementById(id)).find(Boolean);
          if (!words) return { found: false };
          // The field's own box: a file field is the drop box around it.
          const own = (f.type === 'file' ? f.closest('.drop') : f).getBoundingClientRect(), w = words.getBoundingClientRect();
          return { found: true, text: words.textContent.trim(), gap: Math.round(w.top - own.bottom), atTop: !!words.closest('main > .flash, .form-says.flash'),
            focus: document.activeElement === f, invalid: f.getAttribute('aria-invalid') === 'true' };
        }, form, field);
        check(`${name}: every field named, and what is wrong said right under the field, the focus on it (${at})`,
          named.length === 0 && said.found && said.text !== '' && said.gap >= 0 && said.gap <= 60 && !said.atTop && said.focus && said.invalid,
          `${named.length ? 'unnamed: ' + named.join(',') + '; ' : ''}${JSON.stringify(said)}`);
        if (name === 'Make an account') await page.screenshot({ path: path.join(OUT, 'shots', `patterns-form-account-${lang}-${width}.jpg`), type: 'jpeg', quality: 80 });
      }
      // The search boxes: each marked as one (its magnifier) and named for screen readers.
      for (const [name, url, box] of [['players', `${A}/players`, '#player-search'], ['songs', `${A}/songs`, 'input.search'], ["site's songs", `${P}/songs.php`, 'input[type=search]']]) {
        await page.goto(url, { waitUntil: 'domcontentloaded' });
        const look = await page.$eval(box, b => ({ icon: getComputedStyle(b).backgroundImage, named: !!(b.getAttribute('aria-label') || (b.labels && b.labels.length)) })).catch(() => null);
        check(`the ${name} search box shows a magnifier and has a name (${at})`, !!look && /url\(/.test(look.icon) && look.named, JSON.stringify(look));
      }
      await page.close();
    }
  }
}

// The Notices page's Discord and Slack card (ADM-123): the two webhooks run.sh added, one whose messages went through to the
// stand-in chat (chat.py) and one its chat deleted, said in red with why; a third added pointing at the chat, its address
// masked, never whole; its test sent and arriving in the chat; its deletion asking first; the card whole at a phone's
// width and a laptop's, in both languages.
async function webhookFlows(contexts) {
  const page = await contexts.signed.newPage();
  // In front: a page behind others has its timers held back by the browser, and the presses below wait on them.
  await page.bringToFront();
  const errors = watch(page, `${A}/maintenance`);
  await page.setViewport({ width: 1280, height: 900 });
  const hooks = () => page.$$eval('#hooks .hook', all => all.map(h => ({ text: h.textContent.replace(/\s+/g, ' ').trim(), bad: !!h.querySelector('.lamp.bad'), sent: !!h.querySelector('.lamp.on') })));
  // Each sends a test now, whatever the stages before sent them (the server's plays, broadcasts and maintenance).
  await page.goto(`${A}/maintenance`, { waitUntil: 'domcontentloaded' });
  await press(page, '#hooks .hook:nth-child(1) button[value=test]');
  await press(page, '#hooks .hook:nth-child(2) button[value=test]');
  check('a test to a chat that deleted its webhook says why', /did not go through: the chat says this webhook is not there/.test(await textOf(page, '.bar .flash, main .flash')),
    await textOf(page, '.bar .flash, main .flash'));
  await page.goto(`${A}/maintenance`, { waitUntil: 'domcontentloaded' });
  let listed = await hooks();
  check('the card lists the two webhooks, the one that went through with when, the one its chat deleted in red with why',
    listed.length === 2 && listed[0].sent && /Sent/.test(listed[0].text) && listed[1].bad && /not there/.test(listed[1].text), JSON.stringify(listed));
  check('their addresses masked, never whole', !(await page.content()).includes('ui-secret-'), '');
  await noFindings(page, 'the Notices page with a webhook that works and one that fails');
  // A third: the chat's address typed, the page's language, what it hears of as the form comes.
  await page.type('.hook-new input[name=url]', `${process.env.CHAT}/api/webhooks/77/ui-secret-7777`);
  await press(page, '.hook-new button:not([type=button])');
  listed = await hooks();
  check('a webhook added on the card is there, masked', listed.length === 3 && /••••7777/.test(listed[2].text) && /Nothing sent yet/.test(listed[2].text)
    && !(await page.content()).includes('ui-secret-7777'), JSON.stringify(listed[2] || null));
  // The same address again: refused by the server, said in the band, and the page stays with what was typed (the form is
  // sent in place: an answer at another address would take the page away).
  await page.type('.hook-new input[name=url]', `${process.env.CHAT}/api/webhooks/77/ui-secret-7777`);
  await press(page, '.hook-new button:not([type=button])');
  check('the same webhook again is refused on the page, with what was typed', new URL(page.url()).pathname === '/opendmtq/admin/maintenance'
    && /That webhook is here already/.test(await textOf(page, '.bar .flash, main .flash'))
    && (await page.$eval('.hook-new input[name=url]', f => f.value).catch(() => '')).endsWith('/api/webhooks/77/ui-secret-7777')
    && (await hooks()).length === 3, `${page.url()} ${await textOf(page, '.bar .flash, main .flash')}`);
  // On from the page itself, wherever that answer left the browser.
  await page.goto(`${A}/maintenance`, { waitUntil: 'domcontentloaded' });
  await press(page, '#hooks .hook:last-child button[value=test]');
  check('Send a test says it was sent', /Test message sent/.test(await textOf(page, '.bar .flash, main .flash')), await textOf(page, '.bar .flash, main .flash'));
  const got = await (await fetch(`${process.env.CHAT_LOCAL}/got`)).json();
  const test = got.filter(m => m.path === '/api/webhooks/77/ui-secret-7777');
  check('and the chat got it, its words and the site\'s link', test.length === 1 && /^Test message: /.test(test[0].body.text)
    && /\/opendmtq\//.test(JSON.stringify(test[0].body.blocks)), JSON.stringify(test).slice(0, 300));
  listed = await hooks();
  check('the card says when it went', listed.length === 3 && listed[2].sent && /Sent just now/.test(listed[2].text), JSON.stringify(listed[2] || null));
  // Deleting asks first, in the page's own question; then it is gone.
  await page.click('#hooks .hook:last-child button[value=delete]');
  await page.waitForSelector('#ask[open]');
  check('deleting a webhook asks first', /Delete this webhook/.test(await textOf(page, '#ask p')), await textOf(page, '#ask p'));
  await settle(page, () => page.click('#ask [value=yes]'));
  check('and then it is gone', (await hooks()).length === 2);
  // The card at a laptop's width and a phone's, in both languages: measured, and its picture at its real size, cut out of
  // the whole page (the bar stays at the page's top, not over the card as in a picture of the screen scrolled to it). The
  // page loaded anew each time (its address without a #: the same address with one would only move on the page).
  for (const [width, height] of [[1280, 900], [360, 740]]) {
    await page.setViewport({ width, height, ...(width < 700 ? { isMobile: true, hasTouch: true } : {}) });
    for (const lang of ['ko', 'en']) {
      await page.setCookie({ name: 'opendmtq_lang', value: lang, url: ADMIN });
      await page.goto(`${A}/maintenance`, { waitUntil: 'domcontentloaded' });
      await noFindings(page, `the Discord and Slack card at ${width} px (${lang})`);
      const clip = await page.$eval('#hooks', e => { scrollTo(0, 0); const r = e.getBoundingClientRect(); return { x: 0, y: Math.max(0, r.top - 12), width: innerWidth, height: r.height + 24 }; });
      await page.screenshot({ path: path.join(OUT, 'shots', `flows-hooks-card-${lang}-${width}.png`), clip, captureBeyondViewport: true });
    }
  }
  check('the card in Korean says why in Korean', /채팅방에 이 웹후크가 없습니다/.test(await (async () => {
    await page.setCookie({ name: 'opendmtq_lang', value: 'ko', url: ADMIN });
    await page.goto(`${A}/maintenance`, { waitUntil: 'domcontentloaded' });
    return textOf(page, '#hooks');
  })()));
  check('no failed request or script error on the card', errors.length === 0, errors.slice(0, 4).join(' ; '));
  await page.close();
}

async function portalFlows(contexts) {
  // A stranger: the sign-in page first, whatever page was asked for, with nothing of what is inside, and that page after
  // signing in. In a browser of its own: signing in here would sign in the other signed-out pages of this run.
  const own = await contexts.browser.createBrowserContext();
  const fresh = await own.newPage();
  await fresh.setExtraHTTPHeaders({ 'Accept-Language': 'ko-KR,ko;q=0.9' });
  await fresh.goto(`${P}/ranking.php`, { waitUntil: 'domcontentloaded' });
  check('a stranger gets the sign-in page first', new URL(fresh.url()).pathname === '/opendmtq/login.php' && await visible(fresh, '.signin-form'), fresh.url());
  check('and nothing of what is inside', (await fresh.$$('.nav, .tabbar, .onair, .site-alert, .stage, main .card:not(.signin)')).length === 0);
  // English until the visitor picks otherwise, whatever the browser's language.
  check('a browser set to Korean first sees English', await fresh.$eval('html', e => e.lang) === 'en');
  await press(fresh, '.lang-switch a:not(.on)');
  check('the language switch changes the page', await fresh.$eval('html', e => e.lang) === 'ko');
  await press(fresh, '.lang-switch a:not(.on)');
  check('and back', await fresh.$eval('html', e => e.lang) === 'en');
  await typeId(fresh, 'input[name=user]', 'dmtq');
  await fresh.type('input[name=password]', PASSWORD);
  await press(fresh, '.signin-form button[type=submit]');
  check('signing in leads to the page asked for', new URL(fresh.url()).pathname === '/opendmtq/ranking.php', fresh.url());
  await own.close();
  // The front page: the big logo carries the server's version, and what the site is for comes first, the app one press
  // away (its size and date, the way to the steps) and the way to the broadcasts.
  const front = await contexts.signed.newPage();
  const arrived = await front.goto(`${P}/`, { waitUntil: 'domcontentloaded' });
  // The release (run.sh passes 0.9.3-abc1234, as a clone past a release's tag has it): v0.9.3, the commit in its words
  // (data-tip: under a pointer, on a press, on the focus).
  check('the home page shows the version beside the logo', /v\d+\.\d+\.\d+$/.test((await textOf(front, '.stage-mark')).trim())
    && await front.$eval('.server-ver', e => e.dataset.tip) === 'abc1234', await textOf(front, '.stage-mark'));
  check('the front page offers the app and the broadcasts first',
    await front.$eval('.stage-acts .button', a => new URL(a.href).pathname).catch(() => '') === '/apk' && await visible(front, '#watch-live') && await visible(front, '.stage-meta a[href="download.php"]'));
  // The site's answers, its pages, files and JSON alike, are never shown inside another site's page, never taken for
  // another type than they say, and never tell another site the address of the page they were on (site.conf).
  const guarded = ['x-frame-options', 'x-content-type-options', 'referrer-policy'];
  const fetched = await front.evaluate(async names => Promise.all(['/opendmtq/style.css', '/opendmtq/live.js', '/opendmtq/client.php?about']
    .map(async u => { const r = await fetch(u); return names.map(n => r.headers.get(n)).join(' '); })), guarded);
  const said = [guarded.map(n => arrived.headers()[n]).join(' '), ...fetched];
  check('the site is never framed, sniffed or named to another site', said.every(s => s === 'DENY nosniff same-origin'), JSON.stringify(said));
  // The site's own files come by their versions (lib.php asset_url()), which a browser keeps a year without asking, so
  // that an upgrade's pages never meet an older stylesheet; without a version it asks each time (the admin pages' way to
  // them); fonts carry their versions in their names (site.conf).
  const kept = await front.evaluate(async () => {
    const css = document.querySelector('link[rel=stylesheet]').getAttribute('href');
    const scripts = [...document.scripts].map(x => x.getAttribute('src')).filter(Boolean);
    const said = async u => (await fetch(u, { cache: 'no-store' })).headers.get('cache-control');
    return { css, scripts, versioned: await said(css), bare: await said('/opendmtq/style.css'), font: await said('/opendmtq/fonts/dmtq-wide-800.woff2') };
  });
  check('the site names its own files by their versions, and a browser keeps them a year',
    /^\/opendmtq\/style\.css\?v=\d+$/.test(kept.css) && kept.scripts.length > 0 && kept.scripts.every(x => /^\/opendmtq\/[a-z]+\.js\?v=\d+$/.test(x))
    && kept.versioned === 'max-age=31536000, immutable' && kept.bare === 'no-cache' && kept.font === 'max-age=31536000, immutable', JSON.stringify(kept));
  // Only an answer that depends on Accept says so (Vary: Accept, site.conf): the site's files are one answer for every
  // cache, and an address with nothing there still answers a browser with the site's page and anything else short.
  const varied = await front.evaluate(async () => {
    const ask = async (u, accept) => {
      const r = await fetch(u, { cache: 'no-store', headers: accept ? { Accept: accept } : {} });
      return [r.status, (r.headers.get('vary') || '').split(',').map(v => v.trim().toLowerCase()).includes('accept'), (await r.text()).length];
    };
    return [await ask('/opendmtq/style.css'), await ask('/opendmtq/fonts/dmtq-wide-800.woff2'), await ask('/opendmtq/favicon.svg'),
      await ask('/opendmtq/no-such-page', 'text/html'), await ask('/opendmtq/no-such-page.png', 'image/png')];
  });
  check('only the answers that depend on Accept say so', varied.slice(0, 3).every(([status, vary]) => status === 200 && !vary)
    && varied[3][0] === 404 && varied[3][2] > 1000 && varied[4][0] === 404 && varied[4][2] < 400, JSON.stringify(varied));
  await front.close();
  // The download page's part for computers: the installer for Windows (the PC client), its button the site's /windows,
  // which hands a signed-in visitor the installer with this server's address on its end and sends a stranger to the
  // sign-in page first.
  const dl = await contexts.signed.newPage();
  await dl.goto(`${P}/download.php`, { waitUntil: 'domcontentloaded' });
  check('the download page offers the installer for Windows', await dl.$eval('#computer .get', a => new URL(a.href).pathname).catch(() => '') === '/windows');
  // One lime button on the page, the app's: the installer's is the quiet one beside it, at the width of a computer.
  await dl.setViewport({ width: 1280, height: 900 });
  const lime = await dl.$$eval('.button, .btn-primary', els => els.filter(e => e.offsetParent).map(e => e.getAttribute('href')));
  check('the download page has one lime button, the app\'s', lime.length === 1 && lime[0] === '/apk', JSON.stringify(lime));
  const setup = await dl.evaluate(async () => {
    const r = await fetch('/windows');
    const body = new Uint8Array(await r.arrayBuffer());
    // The installer's last bytes: the server's details, their length and the mark.
    return [r.status, r.headers.get('content-type'), r.headers.get('content-disposition'), new TextDecoder().decode(body.slice(-300))];
  });
  check('and /windows hands a signed-in visitor the installer set up for this server',
    setup[0] === 200 && /portable-executable/.test(setup[1] || '') && /filename="opendmtq-pc-client-[0-9a-z.+-]*-?windows-x64-setup-[0-9a-z.-]+\.exe"/.test(setup[2] || '') &&
    setup[3].endsWith('OPENDMTQ-PRESET1') && setup[3].includes(`"url":"${SITE}"`), JSON.stringify(setup.slice(0, 3)));
  // And the app under the name its builder gives it (patch_apk.app_file_name): what it is, the day's stamp, the system and the
  // server's address, in lower case, as every file the server hands a person is named.
  const appName = await dl.evaluate(async () => {
    const r = await fetch('/apk');
    // Only its name is wanted: the rest of the file is left unread.
    await r.body.cancel();
    return [r.status, r.headers.get('content-disposition')];
  });
  check("and /apk hands out the app under its builder's name for it",
    appName[0] === 200 && /filename="opendmtq-phone-app-\d{4}\.\d{2}\.\d{2}-android-[0-9a-z.-]+\.apk"/.test(appName[1] || ''), JSON.stringify(appName));
  // A broken download goes on where it stopped, the app's (a hundred megabytes and more on a phone's network) and the
  // installer's alike (apk.php, windows.php): the headers that say so, a part as asked (the last 200 bytes, which for the
  // installer reach from its own bytes into the server's details after them), the whole again once the file is another
  // (If-Range, and If-Match as Android's downloads ask), and nothing past the end.
  const resumed = await dl.evaluate(async () => {
    const out = {};
    for (const path of ['/apk', '/windows']) {
      const whole = new Uint8Array(await (await fetch(path)).arrayBuffer());
      const head = await fetch(path, { method: 'HEAD' });
      const tag = head.headers.get('etag'), size = whole.length;
      const part = await fetch(path, { headers: { Range: `bytes=${size - 200}-`, 'If-Range': tag } });
      const got = new Uint8Array(await part.arrayBuffer());
      const other = await fetch(path, { headers: { Range: 'bytes=0-9', 'If-Range': '"another"' } });
      const otherSize = (await other.arrayBuffer()).byteLength;
      const moved = await fetch(path, { headers: { Range: 'bytes=0-9', 'If-Match': '"another"' } });
      const past = await fetch(path, { headers: { Range: `bytes=${size}-` } });
      out[path] = {
        // What a download manager reads before it trusts a part: one of bytes, a strong tag, the file's time.
        offered: head.headers.get('accept-ranges') === 'bytes' && /^"[^"]+"$/.test(tag || '') && !!head.headers.get('last-modified'),
        part: part.status === 206 && part.headers.get('content-range') === `bytes ${size - 200}-${size - 1}/${size}`
          && got.length === 200 && got.every((b, i) => b === whole[size - 200 + i]),
        another: other.status === 200 && otherSize === size,
        moved: moved.status === 412,
        past: past.status === 416 && past.headers.get('content-range') === `bytes */${size}`,
      };
    }
    return out;
  });
  check('a broken download of the app or the installer goes on where it stopped',
    Object.values(resumed).every(r => Object.values(r).every(Boolean)), JSON.stringify(resumed));
  // What the PC client asks the site (client.php): whether it is an OpenDMTQ server, then the app on offer, which only a
  // signed-in visitor gets.
  const asked = await dl.evaluate(async () => {
    const about = await (await fetch('/opendmtq/client.php?about')).json();
    const app = await fetch('/opendmtq/client.php?app');
    return [about, app.status, await app.json()];
  });
  check('the PC client finds the server and, signed in, the app on offer',
    asked[0].app === true && typeof asked[0].address === 'string' && asked[1] === 200 && /\.apk$/.test(asked[2].file || ''), JSON.stringify(asked));
  await dl.close();
  const stranger = await contexts.anon.newPage();
  await stranger.goto(`${SITE}/windows`, { waitUntil: 'domcontentloaded' });
  check('a stranger asking for /windows gets the sign-in first', new URL(stranger.url()).pathname === '/opendmtq/login.php' && new URL(stranger.url()).searchParams.get('next') === '/windows', stranger.url());
  // The client's sign-in: a wrong password says so as JSON, and the app stays closed to a stranger.
  const refused = await stranger.evaluate(async () => {
    const wrong = await fetch('/opendmtq/client.php?signin', { method: 'POST', body: new URLSearchParams({ user: 'dmtq', password: 'wrong' }) });
    const app = await fetch('/opendmtq/client.php?app');
    return [wrong.status, await wrong.json(), app.status];
  });
  check("the PC client's sign-in refuses a wrong password, and the app needs a sign-in",
    refused[0] === 401 && refused[1].error === 'wrong' && refused[2] === 403, JSON.stringify(refused));
  await stranger.close();
  // The right password, in a browser of its own: the site's cookie, which the client keeps in place of the password.
  const clientSide = await contexts.browser.createBrowserContext();
  const client = await clientSide.newPage();
  await client.goto(`${P}/client.php?about`, { waitUntil: 'domcontentloaded' });
  const signedIn = await client.evaluate(async password => {
    const r = await fetch('/opendmtq/client.php?signin', { method: 'POST', body: new URLSearchParams({ user: 'dmtq', password }) });
    const app = await fetch('/opendmtq/client.php?app');
    return [r.status, await r.json(), app.status];
  }, PASSWORD);
  check("the PC client's sign-in gives the site's cookie, and with it the app", signedIn[0] === 200 && signedIn[1].account === 'dmtq' && signedIn[2] === 200,
    JSON.stringify(signedIn));
  // My page on the site: the client's sign-in asks for a one-time link (a POST: a GET is refused), which signs another
  // browser in to the same account and opens its page, once; the account's records come as JSON, each with its place on
  // its chart and the keyboard's mark.
  const linked = await client.evaluate(async () => {
    const get = await fetch('/opendmtq/client.php?link');
    const r = await fetch('/opendmtq/client.php?link', { method: 'POST' });
    const records = await fetch('/opendmtq/client.php?records');
    return [get.status, r.status, await r.json(), records.status, await records.json()];
  });
  const [linkGet, linkStatus, link, recordsStatus, records] = linked;
  check("the PC client's one-time link comes for its sign-in, by a POST alone",
    linkGet === 405 && linkStatus === 200 && /^\/opendmtq\/login\.php\?once=[A-Za-z0-9_-]{43}$/.test(link.url || '') && typeof link.page === 'string',
    JSON.stringify(linked).slice(0, 300));
  const rows = [...(records.recent || []), ...(records.best || [])];
  check("the PC client's records: the account's player's plays and bests, each with its place on its chart",
    recordsStatus === 200 && records.account === 'dmtq' && (records.player === null
      ? rows.length === 0 : rows.every(r => Number.isInteger(r.score) && typeof r.keys === 'boolean' && (r.rank === null || r.rank >= 1) && r.players >= 0)),
    JSON.stringify(records).slice(0, 300));
  const opener = await contexts.browser.createBrowserContext();
  const opened = await opener.newPage();
  await opened.goto(`${SITE}${link.url}`, { waitUntil: 'domcontentloaded' });
  const landed = new URL(opened.url());
  check("the one-time link signs a browser in and opens the player's page", landed.pathname + landed.search === link.page
    && await opened.$('.auth-who') !== null, opened.url());
  await opener.close();
  const again = await contexts.browser.createBrowserContext();
  const twice = await again.newPage();
  await twice.goto(`${SITE}${link.url}`, { waitUntil: 'domcontentloaded' });
  check('the same link a second time signs nobody in and says so on the sign-in page',
    new URL(twice.url()).pathname === '/opendmtq/login.php' && await visible(twice, '.signin .error') && await twice.$('.auth-who') === null, twice.url());
  await noFindings(twice, 'a one-time link used already');
  await again.close();
  await clientSide.close();

  // A wrong password says so and keeps the form.
  const login = await contexts.anon.newPage();
  await login.setViewport({ width: 360, height: 740, isMobile: true, hasTouch: true });
  await login.goto(`${P}/login.php?next=%2Fapk`, { waitUntil: 'domcontentloaded' });
  await typeId(login, 'input[name=user]', 'dmtq');
  await login.type('input[name=password]', 'wrong');
  await Promise.all([login.waitForNavigation({ waitUntil: 'domcontentloaded' }), login.keyboard.press('Enter')]);
  // (The note for iPhones stands above the form, hidden elsewhere: the error is what says it.)
  check('a wrong password says so', await visible(login, '.signin .error'));
  await noFindings(login, 'wrong password on a phone');
  await login.close();

  // The text face in two files by script (style.css, unicode-range): the sign-in in English, every visitor's first page,
  // takes the Latin one alone; in Korean the Hangul one too, its Korean drawn in the site's face. Each in a browser of its
  // own, with nothing kept from before.
  const facesOf = async lang => {
    const own = await contexts.browser.createBrowserContext();
    const p = await own.newPage();
    const got = [];
    p.on('response', r => { if (/\/fonts\/dmtq-text-/.test(r.url())) got.push(r.url().split('/').pop()); });
    await p.setCookie({ name: 'opendmtq_lang', value: lang, url: SITE });
    await p.goto(`${P}/login.php`, { waitUntil: 'networkidle0' });
    const drawn = await p.evaluate(() => document.fonts.ready.then(() => document.fonts.check('16px "DMTQ Text"', '로그인')));
    await own.close();
    return [got.sort(), drawn];
  };
  const faces = [await facesOf('en'), await facesOf('ko')];
  check('a page in English takes the Latin half of the text face alone, a page in Korean the Hangul half too',
    JSON.stringify(faces[0][0]) === '["dmtq-text-2-latin.woff2"]' && JSON.stringify(faces[1][0]) === '["dmtq-text-2-hangul.woff2","dmtq-text-2-latin.woff2"]'
    && faces[1][1], JSON.stringify(faces));

  // A field left empty: the page's own check says what is missing, in the page's language, right under that field, and
  // the field takes the focus (forms.js), where the browser's bubble said it in the browser's language. The form stays.
  for (const [lang, noId, noPassword] of [['en', 'Enter your ID.', 'Enter your password.'], ['ko', '아이디를 입력하세요.', '비밀번호를 입력하세요.']]) {
    const empty = await contexts.anon.newPage();
    await empty.setViewport({ width: 360, height: 740, isMobile: true, hasTouch: true });
    await empty.setCookie({ name: 'opendmtq_lang', value: lang, url: SITE });
    await empty.goto(`${P}/login.php`, { waitUntil: 'domcontentloaded' });
    // No ID kept from this browser's earlier sign-ins: both fields empty.
    await empty.evaluate(() => localStorage.clear());
    await empty.reload({ waitUntil: 'domcontentloaded' });
    await empty.click('.signin-form button[type=submit]');
    // The words under the field they are about.
    const under = name => empty.$eval(`.field:has(input[name=${name}]) .field-error`, e => e.textContent).catch(() => '');
    const first = [await under('user'), await empty.evaluate(() => document.activeElement.name)];
    await typeId(empty, 'input[name=user]', 'dmtq');
    await empty.click('.signin-form button[type=submit]');
    const second = [await under('password'), await empty.evaluate(() => document.activeElement.name),
      await empty.$eval('input[name=password]', e => e.getAttribute('aria-invalid'))];
    check(`a field left empty is said by the site in its own words (${lang})`, first[0] === noId && first[1] === 'user'
      && second[0] === noPassword && second[1] === 'password' && second[2] === 'true' && new URL(empty.url()).pathname === '/opendmtq/login.php',
      JSON.stringify([first, second]));
    await noFindings(empty, `a field left empty on a phone (${lang})`);
    await empty.close();
  }
  // A form sent without that check (a browser without scripts) gets the same words from the server, and an empty form is
  // no guess at a password: ten of them, more than one address may fail, and the right password still signs in.
  const blank = await contexts.browser.createBrowserContext();
  const sender = await blank.newPage();
  await sender.goto(`${P}/login.php`, { waitUntil: 'domcontentloaded' });
  const blanks = await sender.evaluate(async password => {
    const said = [];
    for (let i = 0; i < 10; i++) {
      const r = await fetch('/opendmtq/login.php', { method: 'POST', body: new URLSearchParams({ user: i % 2 ? 'dmtq' : '', password: '' }) });
      // The server's words for a field left empty, under that field as the page's own check puts them.
      said.push((await r.text()).match(/<span class="field-error"[^>]*>([^<]*)</)?.[1] || '');
    }
    const right = await fetch('/opendmtq/login.php', { method: 'POST', body: new URLSearchParams({ user: 'dmtq', password }), redirect: 'manual' });
    return [said, right.type === 'opaqueredirect' || right.redirected];
  }, PASSWORD);
  check('an empty form is not counted as a wrong password', blanks[0].every((s, i) => s === (i % 2 ? 'Enter your password.' : 'Enter your ID.')) && blanks[1],
    JSON.stringify(blanks));
  await blank.close();

  // The game's own window: its score viewer is behind the sign-in, on a phone held sideways. The form, its button too, is
  // on the screen without scrolling, at a big phone's size and a small one's.
  for (const [width, height] of [[915, 412], [640, 320]]) {
    const game = await contexts.anon.newPage();
    await game.setViewport({ width, height, isMobile: true, hasTouch: true, isLandscape: true });
    await game.goto(`${P}/login.php?next=%2Fscore%2F`, { waitUntil: 'domcontentloaded' });
    const bottom = await game.$eval('.signin-form .button', b => Math.round(b.getBoundingClientRect().bottom)).catch(() => 9999);
    check(`the sign-in fits the game's window sideways (${width}x${height})`, bottom <= height, `button's foot at ${bottom}`);
    await noFindings(game, `the sign-in in the game's window (${width}x${height})`);
    await game.close();
  }

  // The rankings' This month tab: this month's players (the seed plays in the last days too), when it starts anew, and
  // under them the months before with their first three (the seed goes back months).
  const month = await contexts.signed.newPage();
  await month.setViewport({ width: 1280, height: 900 });
  await month.goto(`${P}/ranking.php?sort=month`, { waitUntil: 'domcontentloaded' });
  const onPodium = (await month.$$('.podium .pod')).length, monthsBefore = (await month.$$('.past-month')).length;
  // The day and the month are held together by a no-break space (lib.php month_moment()): \s in the text, &nbsp; in the
  // markup page.content() gives.
  const startsAnew = /Starts anew on \d+(?:\s|&nbsp;)\w+ at \d\d:\d\d/.test(await month.content());
  check("the month's tab ranks this month and keeps the months before", onPodium > 0 && monthsBefore > 0 && startsAnew, `${onPodium} on the podium, ${monthsBefore} months before, ${startsAnew}`);
  await month.close();

  // An account linked to its game player (the owner links it on the Accounts page): the site's top shows that player's
  // name leading to their page, and the rankings mark their place. Unlinked again afterwards, as the other views expect.
  const linker = await contexts.signed.newPage();
  await linker.setViewport({ width: 1280, height: 900 });
  const linkTo = async guid => {
    await linker.goto(`${A}/accounts`, { waitUntil: 'domcontentloaded' });
    await linker.select('form.account-link:has(input[name=name][value=dmtq]) select', guid);
    // Linked in place (admin.js), or with the page loaded again.
    await press(linker, 'form.account-link:has(input[name=name][value=dmtq]) button');
  };
  await linkTo('1');
  await linker.goto(`${P}/ranking.php`, { waitUntil: 'domcontentloaded' });
  // The profile in the bar: the player's name (beside the badge and over the place and the account's ID), leading to MY PAGE.
  const me = await linker.$eval('.auth-who', e => [e.tagName, (e.querySelector('.who-name') || e).textContent, e.getAttribute('href') || '']).catch(() => []);
  const marked = (await linker.$$('.pod.me, .board tr.me')).length;
  check('a linked account shows its player and marks their place', me[0] === 'A' && me[1] === 'Sena' && me[2] === '/opendmtq/me.php' && marked === 1, `${me} ${marked}`);
  // The PC client's records of a linked account (client.php?records with the client's sign-in): Sena's, who plays by
  // touch, then 민호's, who plays with the keyboard. Each list newest or best first, each row's chart named, its place on
  // the chart among those with a record there, and the keyboard's mark as the play had it. Sena linked again after.
  const pcSide = await contexts.browser.createBrowserContext();
  const pc = await pcSide.newPage();
  await pc.goto(`${P}/client.php?about`, { waitUntil: 'domcontentloaded' });
  await pc.evaluate(async password => {
    await fetch('/opendmtq/client.php?signin', { method: 'POST', body: new URLSearchParams({ user: 'dmtq', password }) });
  }, PASSWORD);
  const recordsNow = async () => pc.evaluate(async () => {
    const r = await fetch('/opendmtq/client.php?records');
    return [r.status, await r.json()];
  });
  // Rows as the PC client shows them, in their list's order.
  const rowsFit = (list, inOrder) => Array.isArray(list) && list.length > 0 && list.every((r, i) => Number.isInteger(r.score)
    && typeof r.title === 'string' && typeof r.chart_name === 'string' && Number.isInteger(r.rank) && r.rank >= 1
    && r.rank <= r.players && (i === 0 || inOrder(list[i - 1], r)));
  const newestFirst = (a, b) => a.at >= b.at, bestFirst = (a, b) => a.score >= b.score;
  const [senaStatus, sena] = await recordsNow();
  check("the PC client's records of a linked account: its player's latest plays and best records, each placed on its chart",
    senaStatus === 200 && !!sena.player && sena.player.id === 1 && sena.player.name === 'Sena' && rowsFit(sena.recent, newestFirst)
      && rowsFit(sena.best, bestFirst) && [...sena.recent, ...sena.best].every(r => r.keys === false), JSON.stringify(sena).slice(0, 400));
  await linkTo('2');
  const [, minho] = await recordsNow();
  check("and of a player who plays with the keyboard, each row with the keyboard's mark",
    !!minho.player && minho.player.id === 2 && rowsFit(minho.recent, newestFirst) && rowsFit(minho.best, bestFirst)
      && [...minho.recent, ...minho.best].every(r => r.keys === true), JSON.stringify(minho).slice(0, 400));
  await pcSide.close();
  await linkTo('1');
  // Measured while linked too, where the player's own place shows: the name in the bar is a key of its own (a finger
  // can hit it), and the marked rows and podium card carry their ring.
  // Korean first and English last: a sweep leaves its last language in the browser's cookie, and the flows after this
  // one read English.
  await sweep(contexts, [['home, linked', `${P}/`], ['rankings, linked', `${P}/ranking.php`], ['this month, linked', `${P}/ranking.php?sort=month`],
                         ['a player, linked', `${P}/player.php?id=1`]], [412, 1280], ['ko', 'en']);
  // The bar fits at every width between a phone's and a desktop's: its sections never scroll sideways. With the longest
  // name linked (20 letters, player 4), the site held upright (the menu at the thumb up to 900 px) and on its side (the
  // sections in the top bar, smaller up to 1000 px, the profile its badge alone below 1100 px); the admin pages with the
  // game server's OFFLINE light on, where the profile is its badge alone (it pushed the pages 35 px out at 1280).
  await linkTo('4');
  const bar = await contexts.signed.newPage();
  const spill = async () => bar.$eval('.bar .nav', n => getComputedStyle(n).display === 'none' ? 0 : n.scrollWidth - n.clientWidth).catch(() => 0);
  const spilled = [];
  for (const [w, h] of [[760, 1000], [820, 1100], [900, 1200], [740, 400], [820, 420], [900, 500], [1024, 700], [1099, 760], [1100, 760], [1280, 800]]) {
    await bar.setViewport({ width: w, height: h });
    await bar.goto(`${P}/ranking.php`, { waitUntil: 'domcontentloaded' });
    const over = await spill();
    if (over > 1) spilled.push(`site ${w}x${h} ${over}px`);
  }
  for (const w of [740, 1024, 1180, 1200, 1240, 1241, 1280, 1600]) {
    await bar.setViewport({ width: w, height: 800 });
    await bar.goto(`${A}/`, { waitUntil: 'domcontentloaded' });
    await bar.evaluate(() => document.querySelector('.bar-end').insertAdjacentHTML('afterbegin', '<span class="state down"><i></i>OFFLINE</span>'));
    const over = await spill();
    if (over > 1) spilled.push(`admin ${w} ${over}px`);
  }
  check('the bar fits at every width, with the longest name and the OFFLINE light', spilled.length === 0, spilled.join(', '));
  await bar.close();
  await linkTo('');
  await linker.close();

  // The songs' search narrows the list, and says when nothing is left.
  const songs = await contexts.signed.newPage();
  await songs.setViewport({ width: 1280, height: 900 });
  await songs.goto(`${P}/songs.php`, { waitUntil: 'networkidle2' });
  const shown = () => songs.$$eval('#songs > *', tiles => tiles.filter(e => getComputedStyle(e).display !== 'none').length);
  const all = await shown();
  await songs.type('#search', 'Neon');
  await pause(300);
  const some = await shown();
  check('the song search narrows the list', some >= 1 && some < all, `${all} -> ${some}`);
  await songs.$eval('#search', e => { e.value = 'no such song anywhere'; e.dispatchEvent(new Event('input')); });
  await pause(300);
  check('and says when nothing is left', await shown() === 0 && await visible(songs, '#no-match'));
  await noFindings(songs, 'a song search with no result');
  // The charts by the names and in the order of the game's chart screen.
  await songs.goto(`${P}/song.php?id=1`, { waitUntil: 'domcontentloaded' });
  const names = await songs.$eval('.chart-row', row => [...row.querySelectorAll('a')].map(a => a.textContent.trim().split(' ')[0]));
  check('a song names its charts as the game does', names.join() === 'Easy,Normal,Hard,Expert', names.join());
  // The catalog beside the longest title there is (song 25's, five lines and more): no tile has a hole in it. Each one's
  // artist follows its title, its line of records follows the artist, and the tile ends there; and a row's tiles start on
  // one line.
  const catalog = await contexts.signed.newPage();
  await catalog.setViewport({ width: 1280, height: 900 });
  await catalog.goto(`${P}/songs.php`, { waitUntil: 'networkidle0' });
  const holes = await catalog.$$eval('#songs .song', tiles => tiles.map(t => {
    const box = r => t.querySelector(r).getBoundingClientRect();
    const [title, artist, records, all] = [box('.t'), box('.a'), box('.p'), t.getBoundingClientRect()];
    return { name: t.querySelector('.t').textContent.slice(0, 20), gaps: [artist.top - title.bottom, records.top - artist.bottom], end: all.bottom - records.bottom, top: Math.round(all.top) };
  }));
  const hollow = holes.filter(h => h.gaps.some(g => g > 4) || h.end > 12);
  const tops = new Set(holes.slice(0, 6).map(h => h.top));
  check('a long title leaves no hole in the song tiles beside it', holes.length > 6 && hollow.length === 0 && tops.size === 1,
    JSON.stringify(hollow.slice(0, 3)) + ` tops ${[...tops]}`);
  await catalog.close();
  await songs.close();
}

// The keyboard's mark (PAGE-36 to PAGE-39, ADM-93 to ADM-95): the PC client's player says a play was made with the keyboard,
// and the game server keeps it with the play and with the best that play set (seed.php writes them so: 민호 always, 유나 every
// fourth play). Held to what the database says (run.sh writes it to keys.json beside the report): each play and best a keyboard
// play made has the mark before its score, and no other; each total, month's score and past month's score that counts such
// bests has it with how many, worked out here from the plays themselves. Both languages, a phone's width and a laptop's.
const KEY_WORDS = { en: ['Keyboard play', n => (n === 1 ? 'Includes 1 keyboard record' : `Includes ${n} keyboard records`)],
  ko: ['키보드 플레이', n => `키보드 플레이 기록 ${n}개 포함`] };
async function keyboardMarks(contexts) {
  const truth = JSON.parse(fs.readFileSync(path.join(OUT, 'keys.json'), 'utf8'));
  // Every play [id, player, chart, score, when, keys, record] and every best [player, chart, score, keys], from the database.
  const plays = truth.plays, bests = truth.bests;
  const best = new Map(bests.map(([who, chart, score, keys]) => [`${who}-${chart}`, { score, keys: !!keys }]));
  // A month's scores as the game adds them up: each chart's top score that month (capped as the rankings cap it), the play
  // that got there first; a player's count is how many of those a keyboard play set. Months begin at midnight UTC.
  const monthKeys = (since, until) => {
    const top = new Map();
    for (const [id, who, chart, score, at, keys] of plays) {
      if (at < since || at >= until) continue;
      const capped = Math.min(Math.max(score, 0), 2147483647), k = `${who}-${chart}`, b = top.get(k);
      if (!b || capped > b.score || (capped === b.score && (at < b.at || (at === b.at && id < b.id)))) top.set(k, { score: capped, at, id, keys, who });
    }
    const out = {};
    for (const b of top.values()) if (b.keys) out[b.who] = (out[b.who] || 0) + 1;
    return out;
  };
  const monthStart = back => { const d = new Date(); return Date.UTC(d.getUTCFullYear(), d.getUTCMonth() - back, 1) / 1000; };
  // How many of each player's bests a keyboard play set: what the rankings' totals count.
  const allTime = {};
  for (const [who, , , keys] of bests) if (keys) allTime[who] = (allTime[who] || 0) + 1;
  check('the stand-in players include keyboard plays and bests, and plays by touch', plays.some(p => p[5]) && plays.some(p => !p[5])
    && bests.some(b => b[3]) && bests.some(b => !b[3]) && !allTime[1], JSON.stringify(allTime));
  const wrong = [], hidden = [], shot = [], layout = [];
  // Views looked at, and marks whose place was measured: a measure of no mark at all would pass without seeing one.
  let viewsSeen = 0, marksPlaced = 0;
  // Every mark of a page with what it stands for: its row's key (player, chart, score as the row shows them) and its words.
  const read = page => page.evaluate(() => {
    const num = el => Number((el && el.textContent || '').replace(/[^0-9]/g, '')) || 0;
    const id = (a, key) => a ? Number(new URL(a.href, location.href).searchParams.get(key)) : 0;
    const mark = el => { const m = el && el.querySelector('.keys-mark'); return m ? [m.getAttribute('data-tip'), m.getAttribute('aria-label'), m.getAttribute('role')] : null; };
    // Each mark where it stands: on a line with what it marks, 4 to 8 px from it (before a score's first figure, or after a
    // name on the podium), at a phone's width too, whole and on the screen.
    const placed = [...document.querySelectorAll('.keys-mark')].map(m => {
      const r = m.getBoundingClientRect(), s = getComputedStyle(m);
      const after = !!m.closest('.pod-who');
      let text = after ? m.previousSibling : m.nextSibling;
      while (text && text.nodeType === 1 && !text.textContent.trim()) text = after ? text.previousSibling : text.nextSibling;
      const range = document.createRange();
      if (text) range.selectNodeContents(text);
      const t = text ? range.getBoundingClientRect() : { left: 0, right: 0, top: 0, bottom: 0 };
      const gap = after ? r.left - t.right : t.left - r.right, middle = (r.top + r.bottom) / 2 - (t.top + t.bottom) / 2;
      return { ok: s.display !== 'none' && s.visibility !== 'hidden' && Math.round(r.width) === 20 && Math.round(r.height) === 12 && r.left >= 0
        && r.right <= document.documentElement.clientWidth && !!text && gap >= 4 && gap <= 8 && Math.abs(middle) <= 4,
        at: `${m.parentElement.className || m.parentElement.tagName} ${Math.round(gap)}px ${Math.round(middle)}px` };
    });
    const rows = sel => [...document.querySelectorAll(sel)];
    return {
      placed,
      // A song's leaderboard: the player and the mark of each row.
      board: rows('table.board tbody tr').map(r => ({ who: id(r.querySelector('td.name a'), 'id'), mark: mark(r) })),
      // A player's page: their recent plays and best records (chart, score, mark), and the count beside the grades.
      lists: rows('.stack .card table.plays').map(t => [...t.querySelectorAll('tbody tr')].map(r => ({
        chart: id(r.querySelector('td.song-cell a'), 'chart'), score: num(r.querySelector('td.r')), mark: mark(r.querySelector('td.r')) }))),
      counted: rows('.grades .g-item').filter(g => g.querySelector('.keys-mark')).map(g => [num(g), mark(g)]),
      // The home page: the newest records (player, chart, score, mark) and the top players (player, mark).
      records: rows('#records .feed li').map(l => ({ who: id(l.querySelector('.who a'), 'id'), chart: id(l.querySelector('.what a'), 'chart'),
        score: num(l.querySelector('.feed-score > span:last-child')), mark: mark(l.querySelector('.feed-score')) })),
      top: rows('.feed.ranks li').map(l => ({ who: id(l.querySelector('.who a'), 'id'), mark: mark(l) })),
      // The rankings: the podium and the table (player, mark), and each month before (its name, its first three).
      ranked: [...rows('.podium .pod').map(p => ({ who: id(p.querySelector('.pod-name'), 'id'), mark: mark(p.querySelector('.pod-who')), pod: true })),
        ...rows('table.board tbody tr').map(r => ({ who: id(r.querySelector('td.name a'), 'id'), mark: mark(r) }))],
      months: rows('.past-month').map(m => ({ name: m.querySelector('h3').textContent.trim(),
        top: [...m.querySelectorAll('.past-top li')].map(l => ({ who: id(l.querySelector('a'), 'id'), mark: mark(l.querySelector('b')) })) })),
      // The admin pages' plays: the status page's newest and the Plays tab (player, score, mark).
      admin: rows('table.compact.recent tbody tr, table.playlog tbody tr').map(r => ({
        who: id(r.querySelector('td.who a'), 'id') || id(r.querySelector('td.primary a'), 'player'), score: num(r.querySelector('td.r')), mark: mark(r.querySelector('td.r')) })),
      all: document.querySelectorAll('.keys-mark').length,
    };
  });
  // A mark is as it should be: there when wanted (true: a play's or a best's; a number: a total's, counting that many), with
  // its words in the page's language, named for a screen reader; none when not (null).
  const same = (where, got, want, lang) => {
    const words = want === true ? KEY_WORDS[lang][0] : typeof want === 'number' && want > 0 ? KEY_WORDS[lang][1](want) : null;
    const ok = words === null ? got === null : !!got && got[0] === words && got[1] === words && got[2] === 'img';
    if (!ok) wrong.push(`${where}: ${JSON.stringify(got)}, wanted ${JSON.stringify(words)}`);
  };
  // What every row of a page should have, and the page's own marks, at a laptop's width in English, a phone's in Korean and in
  // English. In those three views the marks are where they belong and nowhere else.
  const views = [['en', 1280], ['ko', 360], ['en', 360]];
  const look = async (name, url, judge) => {
    for (const [lang, width] of views) {
      const page = await contexts.signed.newPage();
      await page.setViewport({ width, height: width < 500 ? 740 : 900, hasTouch: width < 500, isMobile: width < 500 });
      await page.setCookie({ name: 'opendmtq_lang', value: lang, url });
      await page.goto(url, { waitUntil: 'networkidle2' });
      const seen = await read(page);
      const before = wrong.length;
      judge(seen, lang, `${name} ${lang}${width}`);
      for (const p of seen.placed) if (!p.ok) hidden.push(`${name} ${lang}${width}: ${p.at}`);
      // Counted, so that the check of their places knows it measured some.
      marksPlaced += seen.placed.length;
      // The views with marks, for people to look at.
      if (seen.all) {
        await page.screenshot({ path: path.join(OUT, 'shots', `keys-${name}-${lang}-${width}.jpg`), type: 'jpeg', quality: 80, fullPage: true });
        shot.push(`${name}-${lang}-${width}`);
      }
      if (wrong.length > before) console.log(`  ${name} ${lang}${width}: ${seen.all} marks`);
      // The layout with the marks in it, as the sweeps measure every page (one check for all these views, below).
      for (const f of [...await audit(page), ...await twoPrimaries(page)]) layout.push(`${name} ${lang}${width}: ${f.kind} ${f.at} ${f.detail}`.slice(0, 160));
      viewsSeen++;
      await page.close();
    }
  };
  // Song boards: charts whose bests are some the keyboard's and some by touch, and one with none of the keyboard's.
  const charts = new Map();
  for (const [who, chart, , keys] of bests) {
    const c = charts.get(chart) || { keys: 0, touch: 0 };
    c[keys ? 'keys' : 'touch']++;
    charts.set(chart, c);
  }
  const mixed = [...charts].filter(([, c]) => c.keys && c.touch).map(([chart]) => chart).slice(0, 2);
  const plain = [...charts].filter(([, c]) => !c.keys && c.touch > 1).map(([chart]) => chart).slice(0, 1);
  let boardRows = 0;
  for (const chart of [...mixed, ...plain]) {
    await look(`song-chart-${chart}`, `${P}/song.php?id=${truth.songs[chart]}&chart=${chart}`, (seen, lang, at) => {
      for (const r of seen.board) same(`${at} player ${r.who}`, r.mark, best.get(`${r.who}-${chart}`).keys ? true : null, lang);
      boardRows += seen.board.length;
    });
  }
  check("a song's leaderboard marks the bests a keyboard play set, and no other", mixed.length === 2 && plain.length === 1 && boardRows > 6
    && wrong.length === 0, wrong.slice(0, 6).join(' ; '));
  // Players' pages: all of one's plays by keys, some of another's, none of Sena's.
  const before = wrong.length;
  for (const who of [2, 3, 1]) {
    await look(`player-${who}`, `${P}/player.php?id=${who}`, (seen, lang, at) => {
      const [recent = [], records = []] = seen.lists;
      for (const r of recent) {
        // The play of that chart and score. Two such plays that differ in the mark cannot tell the row: not judged.
        const found = plays.filter(p => p[1] === who && p[2] === r.chart && p[3] === r.score);
        if (!found.length) wrong.push(`${at} recent ${r.chart} ${r.score}: no such play`);
        else if (new Set(found.map(p => !!p[5])).size === 1) same(`${at} recent ${r.chart} ${r.score}`, r.mark, found[0][5] ? true : null, lang);
      }
      for (const r of records) same(`${at} best ${r.chart}`, r.mark, best.get(`${who}-${r.chart}`).keys ? true : null, lang);
      const count = bests.filter(b => b[0] === who && b[3]).length;
      if (count ? !(seen.counted.length === 1 && seen.counted[0][0] === count) : seen.counted.length) wrong.push(`${at} count ${JSON.stringify(seen.counted)} for ${count}`);
      for (const [, m] of seen.counted) same(`${at} count`, m, true, lang);
      if (!recent.length || !records.length) wrong.push(`${at}: no plays or records listed`);
    });
  }
  check("a player's page marks their plays and bests the keyboard made, and counts them beside the grades; none on a player who plays by touch",
    wrong.length === before, wrong.slice(before, before + 6).join(' ; '));
  // The home page: the newest records, and the top players' totals.
  const home = wrong.length;
  await look('home', `${P}/`, (seen, lang, at) => {
    for (const r of seen.records) {
      const found = plays.filter(p => p[1] === r.who && p[2] === r.chart && p[3] === r.score && p[6]);
      same(`${at} record ${r.who} ${r.chart} ${r.score}`, r.mark, found.length === 1 && found[0][5] ? true : null, lang);
    }
    for (const r of seen.top) same(`${at} top ${r.who}`, r.mark, allTime[r.who] || null, lang);
    if (!seen.records.some(r => r.mark) || !seen.top.some(r => r.mark)) wrong.push(`${at}: no mark among the records or the top players`);
  });
  check("the home page marks the newest records a keyboard play set, and the totals that count such bests with how many",
    wrong.length === home, wrong.slice(home, home + 6).join(' ; '));
  // The rankings: every tab of totals, this month (the month's own bests), and the months before.
  const ranks = wrong.length;
  // The podium of a tab that ranks another figure (S grades) shows that figure, which the count does not describe: no mark
  // there, for a player whose total has keyboard bests too (podiumKeys counts those, so that the look sees one at least).
  const podium = [];
  let podiumKeys = 0;
  for (const sort of ['total', 's_count']) {
    await look(`rankings-${sort}`, `${P}/ranking.php?sort=${sort}`, (seen, lang, at) => {
      for (const r of seen.ranked) {
        // The total's count: on every row of the table, and on the podium of the Total score tab.
        if (!r.pod || sort === 'total') {
          same(`${at} ${r.who}`, r.mark, allTime[r.who] || null, lang);
          continue;
        }
        // On the S grades tab's podium: none, whatever the total counts.
        podiumKeys += allTime[r.who] ? 1 : 0;
        if (r.mark) podium.push(`${at} podium ${r.who}: ${JSON.stringify(r.mark)}`);
      }
    });
  }
  const thisMonth = monthKeys(monthStart(0), Number.MAX_SAFE_INTEGER);
  // Months named, and month scores that should carry the mark among those looked at: the seed's keyboard plays go back weeks,
  // so there are some (this month's alone can have none in a month's first hours).
  let pastNamed = 0, monthMarks = 0;
  await look('rankings-month', `${P}/ranking.php?sort=month`, (seen, lang, at) => {
    for (const r of seen.ranked) {
      same(`${at} ${r.who}`, r.mark, thisMonth[r.who] || null, lang);
      monthMarks += thisMonth[r.who] ? 1 : 0;
    }
    // The months before with plays, newest first, as the page lists them; each by its name in English.
    const months = [];
    for (let back = 1; back <= 6; back++) {
      if (plays.some(p => p[4] >= monthStart(back) && p[4] < monthStart(back - 1))) months.push(back);
    }
    seen.months.forEach((m, i) => {
      const back = months[i], counts = monthKeys(monthStart(back), monthStart(back - 1));
      const name = new Date(monthStart(back) * 1000).toLocaleString('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' });
      if (lang === 'en' && m.name !== name) wrong.push(`${at} month ${i}: ${m.name}, wanted ${name}`);
      pastNamed++;
      for (const r of m.top) {
        same(`${at} ${m.name} ${r.who}`, r.mark, counts[r.who] || null, lang);
        monthMarks += counts[r.who] ? 1 : 0;
      }
    });
  });
  check("the rankings mark each total, this month's score and each past month's score that counts bests a keyboard play set, with how many",
    wrong.length === ranks && pastNamed > 0 && monthMarks > 0, wrong.slice(ranks, ranks + 6).join(' ; ') + ` ${pastNamed} months, ${monthMarks} marks`);
  check("the podium has the keyboard's count on the Total score and This month tabs alone, none beside S grades",
    podium.length === 0 && podiumKeys > 0, podium.slice(0, 6).join(' ; ') + ` (${podiumKeys} podium places with keyboard bests)`);
  // Nowhere else: pages that show no scores have no mark. The home page, looked at the same way, must have some: a look that
  // finds no mark anywhere would pass these pages without seeing anything.
  const nowhere = wrong.length;
  let control = 0;
  for (const [name, url] of [['songs', `${P}/songs.php`], ['live', `${P}/live.php`], ['download', `${P}/download.php`], ['home', `${P}/`]]) {
    const page = await contexts.signed.newPage();
    await page.setViewport({ width: 1280, height: 900 });
    await page.goto(url, { waitUntil: 'networkidle2' });
    const n = await page.$$eval('.keys-mark', ms => ms.length);
    // The home page is the look's control; every other page must have none.
    if (name === 'home') control = n;
    else if (n) wrong.push(`${name}: ${n} marks`);
    await page.close();
  }
  check('pages that show no score have no keyboard mark', wrong.length === nowhere && control > 0,
    wrong.slice(nowhere).join(' ; ') + ` (the home page, looked at the same way: ${control} marks)`);
  // The admin pages: the status page's newest plays and the Plays tab, by the player and the score of each row.
  const owner = wrong.length;
  let adminRows = 0;
  for (const [name, url] of [['admin-status', `${A}/`], ['admin-plays', `${A}/logs?tab=plays`]]) {
    await look(name, url, (seen, lang, at) => {
      for (const r of seen.admin) {
        const found = plays.filter(p => p[1] === r.who && p[3] === r.score);
        // Two plays of one player with one score that differ in the mark cannot tell the row: not judged.
        if (found.length && found.every(p => !!p[5] === !!found[0][5])) {
          same(`${at} ${r.who} ${r.score}`, r.mark, found[0][5] ? true : null, lang);
          adminRows++;
        }
      }
      if (!seen.admin.some(r => r.mark)) wrong.push(`${at}: no marked play`);
    });
  }
  check("the admin pages mark the plays a keyboard play made, on the status page and the Plays tab", wrong.length === owner && adminRows > 20,
    wrong.slice(owner, owner + 6).join(' ; ') + ` (${adminRows} rows)`);
  check("every keyboard mark stands beside what it marks, on its line, whole and on the screen, at a phone's width too",
    hidden.length === 0 && marksPlaced > 0, hidden.slice(0, 8).join(' ; ') + ` (${marksPlaced} marks measured)`);
  check(`the pages with keyboard marks: nothing wrong with the layout (${viewsSeen} views)`, layout.length === 0 && viewsSeen >= 30,
    layout.slice(0, 8).join(' ; '));
  console.log(`  pictures: ${shot.join(', ')}`);
}

// The replay player as a viewer uses it.
async function replayFlows(contexts) {
  const page = await contexts.signed.newPage();
  const errors = watch(page, `${P}/live.php`);
  await page.setViewport({ width: 1280, height: 800 });
  await page.goto(`${P}/live.php`, { waitUntil: 'domcontentloaded' });
  await pause(1500);
  // The newest recording of player 1 with its three songs; the list is newest first.
  const key = await page.$$eval('#past-list .past', links => {
    const withSongs = links.map(a => a.getAttribute('href')).filter(Boolean);
    return withSongs[withSongs.length - 1].replace(/^.*r=/, '');
  });
  await page.goto(`${P}/live.php?r=${key}`, { waitUntil: 'domcontentloaded' });
  await pause(3000);
  const now = () => page.$eval('#live-video', e => e.currentTime);
  check('a recording plays', await page.$eval('#live-video', e => !e.paused && e.currentTime > 0.3));
  check('marked as a replay', await textOf(page, '#pill-word') === 'REPLAY');
  check('with its timeline', await visible(page, '#ctl-track'));
  await page.mouse.move(500, 300);
  await pause(200);
  await page.screenshot({ path: path.join(OUT, 'shots', 'flows-replay-controls-1280.jpg'), type: 'jpeg', quality: 72 });
  await noFindings(page, 'the replay on a laptop');
  const before = await now();
  await page.click('#ctl-fwd');
  await pause(1200);
  check('+10 s', await now() > before + 9);
  await page.click('#ctl-rate');
  check('the speed button', await page.$eval('#live-video', e => e.playbackRate) === 1.25);
  await page.keyboard.press('KeyS');
  check('the speed key', await page.$eval('#live-video', e => e.playbackRate) === 1.5);
  for (let i = 0; i < 3; i++) await page.keyboard.press('KeyS');
  check('the speed comes round to normal', await page.$eval('#live-video', e => e.playbackRate) === 1);
  await page.click('#ctl-stats');
  await pause(1200);
  const stats = await textOf(page, '#live-stats');
  check('the connection details', /\d+×\d+/.test(stats) && /Mbit/.test(stats), stats.slice(0, 100));
  await page.click('#ctl-stats');
  // The first song begins where the timeline does, and needs no mark.
  check('the songs are marked on the timeline', (await page.$$('#ctl-marks .cut')).length === 2);
  check('and listed as chapters', (await page.$$('#chapter-list button, #chapter-list a')).length === 3);
  // Each with its song's jacket: the first one's picture loads, and is not the empty stand-in a song without one gets.
  const jacket = await page.waitForFunction(() => { const i = document.querySelector('#chapter-list img'); return !!i && i.complete && i.naturalWidth > 1; }, { timeout: 8000 }).then(() => true, () => false);
  check('each with its jacket', jacket, await page.$eval('#chapter-list img', i => i.currentSrc.slice(0, 90)).catch(() => 'no picture'));
  await page.$eval('#chapter-list button, #chapter-list a', e => e.click());
  await pause(800);
  // Left half-way, the page offers to go on from there.
  await page.$eval('#live-video', e => { e.currentTime = 30; });
  await pause(6000);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await pause(2500);
  check('coming back continues where it was left', await now() > 10);
  check('and says so', await visible(page, '#live-resume'));
  // To the end: what next.
  await page.$eval('#live-video', e => { e.currentTime = e.duration - 0.5; });
  await pause(2500);
  check('the end screen', await visible(page, '#live-end'));
  await page.click('#end-again');
  await pause(1500);
  check('watch again', await page.$eval('#live-video', e => !e.paused && e.currentTime < 8));
  // The list's search.
  await page.type('#past-search', 'no such thing');
  await pause(300);
  check('the recordings search says when nothing is found', await visible(page, '#past-none'));
  await page.$eval('#past-search', e => { e.value = ''; e.dispatchEvent(new Event('input')); });
  // Another recording from the list, without the page being loaded again.
  await page.evaluate(() => { window.stillHere = true; });
  await page.click('#past-list li:first-child a');
  await pause(2500);
  check('another recording from the list, without a reload', await page.evaluate(() => window.stillHere === true) && await page.$eval('#live-video', e => !e.paused));
  await page.goBack();
  await pause(1500);
  check('back returns to the one before', page.url().includes(key));
  check('the tab says whose recording it is', /Replay/.test(await page.title()) && (await page.title()).split(' · ').length === 3, await page.title());
  check('the heading says replay, not live', await textOf(page, '#mast .word') === 'REPLAY');
  // Back again, to the list with nobody on air: nothing goes on playing under the heading of another page.
  await page.goto(`${P}/live.php`, { waitUntil: 'domcontentloaded' });
  await pause(1000);
  await page.click('#past-list li:first-child a');
  await pause(2500);
  await page.goBack();
  await pause(1500);
  check('back from a recording to the list stops it', await page.$eval('#live-video', e => e.paused || !e.currentSrc) && await textOf(page, '#mast .word') === 'LIVE');
  check('no failed requests or script errors in all that', errors.length === 0, errors.slice(0, 5).join(' ; '));
  await page.close();

  // The same on a phone, with its controls in view.
  const phone = await contexts.signed.newPage();
  await phone.setViewport({ width: 360, height: 740, isMobile: true, hasTouch: true });
  await phone.goto(`${P}/live.php?r=${key}`, { waitUntil: 'domcontentloaded' });
  await pause(3000);
  await phone.tap('#live-video');
  await pause(300);
  await phone.screenshot({ path: path.join(OUT, 'shots', 'flows-replay-controls-360.jpg'), type: 'jpeg', quality: 72 });
  await noFindings(phone, 'the replay on a phone');
  // Two quick taps at the side jump ten seconds, from the controls being away as well: the first brings them back, and the
  // second must not land on the timeline that has just appeared under the finger. Upper and lower half of the picture.
  const box = await (await phone.$('#live-video')).boundingBox();
  const time = () => phone.$eval('#live-video', e => e.currentTime);
  // Playing, with sound: the controls only go away then. (The tap above may have paused it, a browser may have refused sound.)
  await phone.$eval('#live-video', e => { e.muted = false; return e.play(); });
  for (const [where, y] of [['upper', box.y + box.height * 0.3], ['lower', box.y + box.height * 0.8]]) {
    await phone.waitForFunction(() => document.getElementById('live-stage').classList.contains('idle'), { timeout: 9000 });
    const was = await time();
    await phone.touchscreen.tap(box.x + box.width * 0.85, y);
    await pause(90);
    await phone.touchscreen.tap(box.x + box.width * 0.85, y);
    await pause(900);
    const now = await time();
    check(`a double tap on the ${where} half jumps ten seconds`, now > was + 8 && now < was + 16, `${was} -> ${now}`);
    check('and it keeps playing', await phone.$eval('#live-video', e => !e.paused));
  }
  await phone.close();
}

// The owner's forms.
// A name made of the characters HTML is written with, given by the owner's own rename on the Players page: every page
// shows it as it is, escaped once (the live page said "Sena&#039;s &amp; ..." where t() escaped what h() had escaped
// already). Player 5 broadcast today (feed.py), so the live page's line about who was last on air, its list and the
// tooltips of its two weeks name them; their profile and the rankings too. Then the name they had, for the stages after.
async function escapedOnce(contexts, admin) {
  const odd = `Ann's & <Co> "1"`;
  const entity = /&(?:amp|lt|gt|quot|#0*39|#x0*27|apos);/;
  // The row's More, its name field, and Rename: as the owner does it.
  const rename = async (to) => {
    await admin.goto(`${A}/players`, { waitUntil: 'domcontentloaded' });
    const row = '.row-more[data-act^="/opendmtq/admin/players/5?"]';
    await admin.$eval(row, e => e.querySelector('summary').click());
    await admin.waitForSelector(`${row} > form.row-more-in`, { visible: true });
    const before = await admin.$eval(`${row} input[name=name]`, e => e.value);
    await admin.$eval(`${row} input[name=name]`, (e, value) => { e.value = value; e.dispatchEvent(new Event('input', { bubbles: true })); }, to);
    await press(admin, `${row} button[value=rename]`);
    return before;
  };
  const was = await rename(odd);
  const site = await contexts.signed.newPage();
  await site.setViewport({ width: 1280, height: 900 });
  await site.goto(`${P}/live.php`, { waitUntil: 'domcontentloaded' });
  // Nobody is on air in this stage: the box says who was last, and how the last two weeks went.
  const box = await site.$eval('#live-none', e => ({ text: e.textContent, tips: [...e.querySelectorAll('[data-tip]')].map(i => i.getAttribute('data-tip')) }));
  const cards = await site.$$eval('#past-list .who', bs => bs.map(b => b.textContent));
  const first = cards[0] || '';
  check('a name with & \' < > " reads as itself on the live page: who was last on air, the list, the days',
    !entity.test(box.text) && !box.tips.some(t => entity.test(t)) && box.text.includes(first) && cards.includes(odd) && box.tips[box.tips.length - 1].includes(odd),
    `${box.text.replace(/\s+/g, ' ').slice(0, 140)} | ${box.tips[box.tips.length - 1]} | ${cards.slice(0, 3)}`);
  await site.goto(`${P}/player.php?id=5`, { waitUntil: 'domcontentloaded' });
  const head = await textOf(site, '.playerhead h2');
  await site.goto(`${P}/ranking.php`, { waitUntil: 'domcontentloaded' });
  const listed = await site.$$eval('.board td.name a, .pod-name', es => es.map(e => e.textContent.trim()));
  check('and on their page, its tab and the rankings', head.trim().startsWith(odd) && (await site.title()) !== '' && listed.includes(odd),
    `${head} | ${listed.slice(0, 6)}`);
  await site.goto(`${P}/player.php?id=5`, { waitUntil: 'domcontentloaded' });
  check('the tab names them as they are', (await site.title()).startsWith(odd), await site.title());
  await site.close();
  await rename(was);
}

// PAGE-78, PAGE-79: a player's own page (game.py, seed.php's 민호 with a balance of his own): a currency set, a level set and
// an item given, each in place (the page not opened anew, its figure changed, the server's words as the band); a refusal said
// in the server's words with nothing changed; the questions before a ban and before a reset in the page's own look, whole
// and on top, naming the player, Cancel leaving everything as it was; the layout clean after each. At a phone's width and a
// laptop's.
async function gameFlows(contexts) {
  for (const [width, height] of [[360, 740], [1280, 800]]) {
    const page = await contexts.signed.newPage();
    await page.setViewport({ width, height, ...(width < 700 ? { isMobile: true, hasTouch: true } : {}) });
    const at = `${width}px`;
    await page.goto(`${A}/players/2`, { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => { window.keptOpen = true; });
    // A press of one of the page's buttons: the server's words, from the message it brings at the foot of the screen
    // (none left from the press before).
    const said = async selector => {
      await page.evaluate(() => { for (const m of document.querySelectorAll('.flash.float')) m.remove(); });
      await press(page, selector);
      await page.waitForSelector('.flash.float', { timeout: 5000 }).catch(() => {});
      return page.$eval('.flash.float', e => e.textContent.trim()).catch(() => '');
    };
    // A figure of its own at each width, so that the second run is not the first one's figure left over.
    const figure = (width === 360 ? 7000 : 8000) + 77;
    await page.$eval('#game-currency .purse input[name=amount]', (e, v) => { e.value = String(v); }, figure);
    const setWords = await said('#game-currency .purse button[value=set]');
    check(`a player's MAX POINT set changes the page in place, the figure and the words (${at})`,
      await keptOpen(page) && (await textOf(page, '#purse-max')) === figure.toLocaleString('en-US') && /MAX POINT of 민호/.test(setWords),
      `${await textOf(page, '#purse-max')} | ${setWords}`);
    await page.$eval('#game-currency .purse input[name=amount]', e => { e.value = '99999999'; });
    const tooMuch = await said('#game-currency .purse button[value=add]');
    check(`more than the game shows is refused in the server's words, nothing changed (${at})`,
      /99,999,999 at most/.test(tooMuch) && (await textOf(page, '#purse-max')) === figure.toLocaleString('en-US'), tooMuch);
    await page.$eval('#game-level input[name=level]', e => { e.value = '20'; });
    const levelWords = await said('#game-level button[value=level]');
    check(`a level set in place: the badge and the gauge follow (${at})`,
      await keptOpen(page) && (await page.$eval('#game-level .lv-badge b', e => e.textContent)) === '20' && /Lv\.20/.test(levelWords), levelWords);
    // Every kind open, as a person opens the one they want: the first item to give is a note.
    await page.$$eval('#game-items details', ds => ds.forEach(d => { d.open = true; }));
    const giveWords = await said('#game-items button[value=give]');
    check(`an item given in place (${at})`, await keptOpen(page) && /given to 민호/.test(giveWords), giveWords);
    await noFindings(page, `a player's page after its changes (${at})`);
    // The question before a ban: whole, on top, naming the player; Cancel leaves no ban.
    await page.$eval('#game-ban textarea[name=reason]', e => { e.value = 'Made-up scores'; });
    await page.click('#game-ban button[value=ban]');
    await page.waitForSelector('#ask[open]');
    const ban = await wholeOnTop(page, '#ask[open] > *');
    check(`the question before a ban is whole and on top, and names the player (${at})`, ban.ok && (await textOf(page, '#ask p')).includes('민호'), ban.detail);
    await noFindings(page, `the question before a ban (${at})`);
    await page.click('#ask [value=no]');
    await pause(400);
    check(`cancel leaves the player unbanned (${at})`, !(await page.$('#game-ban button[value=unban]')) && await keptOpen(page));
    // The question before a reset of the game state, likewise.
    await page.click('#game-player button[value=reset]');
    await page.waitForSelector('#ask[open]');
    const reset = await wholeOnTop(page, '#ask[open] > *');
    check(`the question before a game reset is whole and on top, and says a backup comes first (${at})`,
      reset.ok && /backup/i.test(await textOf(page, '#ask p')), reset.detail);
    await page.click('#ask [value=no]');
    await page.screenshot({ path: path.join(OUT, 'shots', `game-flows-${width}.jpg`), type: 'jpeg', quality: 72, fullPage: true }).catch(() => {});
    await page.close();
  }
}

// The repair's answer, pressed from its card on a laptop's screen (the page comes back there): every step it took said,
// each one in sight and none laid over another (they were bands on one spot under the bar, the last alone readable)
// (ADM-198). It takes the song list afresh from the stand-in files, as the admin flows' hidden song does: run.sh writes
// the stand-in catalog again before MY PAGE.
async function repairSaid(contexts) {
  const page = await contexts.signed.newPage();
  await page.setViewport({ width: 1280, height: 900 });
  await page.goto(`${A}/server`, { waitUntil: 'domcontentloaded' });
  await page.$eval('#repair button', b => b.scrollIntoView({ block: 'center' }));
  await settle(page, () => page.click('#repair button'));
  // Its words, under the bar where the page came back further down, or at the page's top after a longer repair followed
  // on the page: five steps at least.
  await page.waitForFunction(() => document.querySelectorAll('.flash[data-said]').length >= 5, { timeout: 30000 }).catch(() => {});
  await pause(300);
  const lines = await page.$$eval('.flash[data-said]', els => els.map(e => {
    const r = e.getBoundingClientRect();
    return { text: e.textContent.trim().slice(0, 50), top: Math.round(r.top), bottom: Math.round(r.bottom) };
  }));
  const apart = lines.every((l, i) => i === 0 || l.top >= lines[i - 1].bottom - 1);
  const inView = lines.every(l => l.top >= 0 && l.bottom <= 900);
  // Read in the language the flows left the pages in: each step's name starts its line in either.
  check('the repair says every step it took, each in sight and none over another',
    lines.length >= 5 && apart && inView && lines.some(l => /^(Folders|폴더):/.test(l.text)) && lines.some(l => /^(Database|데이터베이스):/.test(l.text)),
    JSON.stringify(lines));
  await page.screenshot({ path: path.join(OUT, 'shots', 'flows-repair-said-1280.jpg'), type: 'jpeg', quality: 80 });
  await page.close();
  // On a phone held upright the bar goes away with the page, so the steps stand at the foot of the screen, each in sight
  // one under another, the last on the screen's edge (under the bar they stood at the page's own foot, out of sight).
  const phone = await contexts.signed.newPage();
  await phone.setViewport({ width: 360, height: 780, isMobile: true, hasTouch: true });
  await phone.goto(`${A}/server`, { waitUntil: 'domcontentloaded' });
  await phone.$eval('#repair button', b => b.scrollIntoView({ block: 'center' }));
  await settle(phone, () => phone.click('#repair button'));
  await phone.waitForFunction(() => document.querySelectorAll('.flash[data-said]').length >= 5, { timeout: 30000 }).catch(() => {});
  await pause(300);
  const held = await phone.$$eval('.flash[data-said]', els => els.map(e => {
    const r = e.getBoundingClientRect();
    return { top: Math.round(r.top), bottom: Math.round(r.bottom) };
  }));
  const stacked = held.every((l, i) => i === 0 || l.top >= held[i - 1].bottom - 1);
  const atFoot = held.length > 0 && Math.abs(held[held.length - 1].bottom - 780) <= 2;
  check('on a phone held upright the repair says every step at the foot of the screen, each in sight',
    held.length >= 5 && stacked && atFoot && held.every(l => l.top >= 0 && l.bottom <= 780), JSON.stringify(held));
  await phone.screenshot({ path: path.join(OUT, 'shots', 'flows-repair-said-360.jpg'), type: 'jpeg', quality: 80 });
  await phone.close();
}

async function adminFlows(contexts) {
  // A wrong password says so.
  const login = await contexts.anon.newPage();
  await login.setViewport({ width: 360, height: 740, isMobile: true, hasTouch: true });
  await login.goto(`${A}/login`, { waitUntil: 'domcontentloaded' });
  await typeId(login, 'input[name=name]', 'admin');
  await login.type('input[name=password]', 'wrong');
  await Promise.all([login.waitForNavigation({ waitUntil: 'domcontentloaded' }), login.keyboard.press('Enter')]);
  check('a wrong admin password says so', /\S/.test(await textOf(login, '.flash, .error')));
  await noFindings(login, 'the admin sign-in after a wrong password');
  await login.close();

  const page = await contexts.signed.newPage();
  const errors = watch(page, `${A}/`);
  await page.setViewport({ width: 1280, height: 900 });

  // Renaming shows what happened, in a message with the site's look, and it stays done. Player 7's More, whose panel is made
  // from the page's one when it opens (admin.js): until then the row holds no form.
  await page.goto(`${A}/players`, { waitUntil: 'domcontentloaded' });
  const row = '.row-more[data-act^="/opendmtq/admin/players/7?"]';
  const panel = `${row} > form.row-more-in`;
  const openMore = async p => {
    await p.$eval(row, e => e.querySelector('summary').click());
    await p.waitForSelector(panel, { visible: true });
  };
  check('what is not done every day waits under More', await page.$eval(row, e => !e.open && !e.querySelector('form')));
  await openMore(page);
  await noFindings(page, 'the players page with a row opened');
  check('rename waits for a new name', await page.$eval(`${panel} button[value=rename]`, e => e.disabled));
  await page.$eval(`${panel} input[name=name]`, e => { e.value = 'Doyun Two'; e.dispatchEvent(new Event('input', { bubbles: true })); });
  await press(page, `${panel} button[value=rename]`);
  check('renaming says so', /Doyun Two/.test(await textOf(page, '.flash')));
  await noFindings(page, 'the players page with a message');
  await openMore(page);
  check('and the new name stays', await page.$eval(`${panel} input[name=name]`, e => e.value) === 'Doyun Two');
  // What cannot be undone asks in the site's own look, and Cancel leaves everything as it was.
  await page.click(`${panel} button[value=reset]`);
  await page.waitForSelector('#ask[open]');
  check('a reset asks first, and says a backup comes first', /backup/i.test(await textOf(page, '#ask p')), await textOf(page, '#ask p'));
  // The panel was made for this row: the question names its player.
  check('and names the player it is about', (await textOf(page, '#ask p')).includes('Doyun Two'), await textOf(page, '#ask p'));
  await noFindings(page, 'the question before a reset');
  await page.evaluate(() => { window.stillHere = true; });
  await page.click('#ask [value=no]');
  await pause(500);
  check('cancel leaves the page as it was', await page.evaluate(() => window.stillHere === true && !document.getElementById('ask').open));
  // From the keyboard: More opens with Enter, and the next stop is the name to change.
  await page.goto(`${A}/players`, { waitUntil: 'domcontentloaded' });
  await page.focus(`${row} > summary`);
  await page.keyboard.press('Enter');
  await page.waitForSelector(panel, { visible: true });
  await page.keyboard.press('Tab');
  check('More opens from the keyboard, the name the next stop', await page.evaluate(sel => document.activeElement.name === 'name'
    && document.activeElement.closest('.row-more') === document.querySelector(sel), row));
  // A row's switch sends the page's one form to its player's address: on, then off again as it was, each said in a message.
  const switchOf = `button[form="player-switch"][formaction^="/opendmtq/admin/players/7?"]`;
  await press(page, switchOf);
  const on = await textOf(page, '.flash');
  await press(page, switchOf);
  const off = await textOf(page, '.flash');
  check("a row's switch sends the page's one form for its player", /Doyun Two/.test(on) && / on/.test(on) && /Doyun Two/.test(off) && / off/.test(off),
    `${on} | ${off}`);
  await escapedOnce(contexts, page);
  // The same panel on a phone, where it opens across the row.
  const small = await contexts.signed.newPage();
  await small.setViewport({ width: 360, height: 740, isMobile: true, hasTouch: true });
  await small.goto(`${A}/players`, { waitUntil: 'domcontentloaded' });
  await openMore(small);
  await pause(200);
  await noFindings(small, 'the players page on a phone with a row opened');
  await small.screenshot({ path: path.join(OUT, 'shots', 'flows-players-more-360.jpg'), type: 'jpeg', quality: 72 });
  await small.close();
  // A page's name is a name: no script or markup in the tab.
  for (const name of ['players', 'maintenance', 'songs', 'backups', 'recordings', 'app', 'logs', '']) {
    await page.goto(`${A}/${name}`, { waitUntil: 'domcontentloaded' });
    const title = await page.title();
    check(`the tab of ${name || 'status'} says its name`, title.length < 60 && !title.includes('<'), title.slice(0, 80));
  }
  await page.goto(`${A}/players`, { waitUntil: 'domcontentloaded' });
  // The list: its search, its sort, its download.
  await page.type('#player-search', 'sena');
  await pause(200);
  check('the players search', await page.$$eval('table.players tbody tr', r => r.filter(x => !x.hidden && x.getBoundingClientRect().height > 0).length) === 1);
  await page.$eval('#player-search', e => { e.value = ''; e.dispatchEvent(new Event('input')); });
  await page.click('table.players th[data-sort="text"]');
  check('sorting by name', await page.$eval('table.players tbody tr td.primary', e => e.dataset.v) !== undefined && await page.$eval('table.players th[data-sort="text"]', e => e.hasAttribute('aria-sort')));
  const csv = await page.evaluate(async url => (await fetch(url)).text(), `${A}/players?csv=1`).catch(() => '');
  check('the players download', /Doyun Two/.test(csv), csv.slice(0, 80));
  const firstByte = await page.evaluate(async url => new Uint8Array(await (await fetch(url)).arrayBuffer())[0], `${A}/players?csv=1`).catch(() => 0);
  check('and a spreadsheet reads it as UTF-8', firstByte === 0xef, String(firstByte));

  // The plays: by a player, then by days too, and the file holds what the page found, not one page of it.
  await page.goto(`${A}/logs?tab=plays`, { waitUntil: 'domcontentloaded' });
  const playsCount = async () => Number(await textOf(page, 'section.card h2 .meta-inline'));
  const everyPlay = await playsCount();
  await page.select('.plays-filters select[name=player]', '1');
  await Promise.all([page.waitForNavigation({ waitUntil: 'domcontentloaded' }), page.click('.plays-filters button.btn')]);
  const onePlayer = await playsCount();
  // One player's plays: whose they are is said once over the list, and no row repeats the name.
  const namesInRows = (await page.$$('table.playlog td.primary')).length, whose = await textOf(page, '.plays-of');
  check('the plays narrow to one player', onePlayer > 0 && onePlayer < everyPlay && namesInRows === 0 && /\S/.test(whose), `${onePlayer} of ${everyPlay}: ${namesInRows} names in rows, ${whose}`);
  // A week back: the player has plays from then on and from before, and the server's clock decides which day is which.
  const weekAgo = new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10);
  await page.$eval('.plays-filters input[name=from]', (e, day) => { e.value = day; }, weekAgo);
  await Promise.all([page.waitForNavigation({ waitUntil: 'domcontentloaded' }), page.click('.plays-filters button.btn')]);
  const lately = await playsCount();
  const whenPlayed = await page.$$eval('table.playlog td.date', c => c.map(e => e.textContent.trim()));
  check('and to days', lately > 0 && lately < onePlayer && whenPlayed.every(at => at >= weekAgo), `${lately} of ${onePlayer}, from ${weekAgo}, oldest here ${whenPlayed[whenPlayed.length - 1]}`);
  check('the form holds what was picked', await page.$eval('.plays-filters select[name=player]', e => e.value) === '1' && await page.$eval('.plays-filters input[name=from]', e => e.value) === weekAgo);
  const playsFile = await page.$eval('section.card h2 a.more', e => e.href);
  const playsCsv = await page.evaluate(async url => (await fetch(url)).text(), playsFile).catch(() => '');
  check('the plays download holds what the page found', playsCsv.trim().split('\n').length === lately + 1 && /^\ufeff?time,player_id,player,song,chart,score,grade,accuracy,new_record/.test(playsCsv), `${playsCsv.trim().split('\n').length} lines for ${lately}`);
  await page.click('.plays-filters a.btn');
  await page.waitForFunction(() => !location.search.includes('player='));
  check('and the filter can be cleared', await playsCount() === everyPlay);

  // The log of changes says it in words, under the player's name.
  await page.goto(`${A}/logs?tab=changes`, { waitUntil: 'domcontentloaded' });
  const changes = await textOf(page, '.changes');
  check('the change log says what was done, in words', /Renamed a player/.test(changes) && /Doyun Two/.test(changes), changes.slice(0, 120));
  check('and when, as a date', /\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(changes), changes.slice(0, 120));

  // An account for a friend: made on the Accounts page, its password shown once with the message to send; it signs in
  // to the site in a browser of its own, and is signed out there once switched off.
  await page.goto(`${A}/accounts`, { waitUntil: 'domcontentloaded' });
  await page.type('.account-form input[name=name]', 'friend1');
  await page.type('.account-form input[name=note]', 'A friend');
  await press(page, '.account-form button.btn-primary');
  const made = await textOf(page, '.account-keys code');
  check('an account is made with a password shown once', /^[a-z2-9]{10}$/.test(made) && /friend1/.test(await page.$eval('#account-message', e => e.value)), made);
  await noFindings(page, 'the accounts page with a new password');
  const theirs = await contexts.browser.createBrowserContext();
  const friend = await theirs.newPage();
  await friend.goto(`${P}/`, { waitUntil: 'domcontentloaded' });
  await typeId(friend, 'input[name=user]', 'friend1');
  await friend.type('input[name=password]', made);
  await press(friend, '.signin-form button[type=submit]');
  check('the new account signs in to the site', new URL(friend.url()).pathname === '/opendmtq/' && await visible(friend, '.stage'), friend.url());
  await page.goto(`${A}/accounts`, { waitUntil: 'domcontentloaded' });
  check('the password is not shown again', !(await page.$('.account-keys')));
  await press(page, 'tr:has(td.primary) form:has(input[value=off]):has(input[value="friend1"]) button');
  await friend.goto(`${P}/ranking.php`, { waitUntil: 'domcontentloaded' });
  check('switched off, the account is signed out', new URL(friend.url()).pathname === '/opendmtq/login.php', friend.url());
  await theirs.close();

  // What shows once comes into view, with the focus, wherever its form was: Make token at the page's foot, and a row's New
  // password down the list. The page used to come back where it was, the panel above, off the screen. At a laptop's screen
  // and a phone's; the new password for an account of this check's own (dmtq's is the one every stage signs in with).
  await page.goto(`${A}/accounts`, { waitUntil: 'domcontentloaded' });
  await page.type('.account-form input[name=name]', 'inview');
  await press(page, '.account-form button.btn-primary');
  // The panel against the screen, and whether it has the focus.
  const panelAt = p => p.$eval('section.account-made', e => {
    const r = e.getBoundingClientRect();
    return { top: Math.round(r.top), bottom: Math.round(r.bottom), screen: innerHeight, focused: document.activeElement === e };
  }).catch(() => null);
  // The page's primary buttons that can be pressed: one on each of these screens, Make an account's. The copy buttons, Make
  // token and the setup's Next are plain, with a panel shown once or without.
  const primaries = p => p.$$eval('.btn-primary', bs => bs.filter(b => !b.disabled && b.getBoundingClientRect().height > 0)
    .map(b => b.textContent.trim()));
  const outOfView = [], notOne = [];
  for (const [size, width, height] of [['laptop', 1366, 768], ['phone', 390, 844]]) {
    const p = await contexts.signed.newPage();
    await p.setViewport({ width, height, isMobile: width < 500, hasTouch: width < 500 });
    await p.goto(`${A}/accounts`, { waitUntil: 'domcontentloaded' });
    const plain = await primaries(p);
    await p.$eval('#tokens input[name=token_name]', e => e.scrollIntoView({ block: 'center' }));
    await p.type('#tokens input[name=token_name]', `in view ${size}`);
    await press(p, '#tokens form button');
    const token = await panelAt(p);
    const withToken = await primaries(p);
    const row = 'table.accounts form:has(input[name=action][value=password]):has(input[name=name][value="inview"]) button';
    await p.$eval(row, e => e.scrollIntoView({ block: 'center' }));
    await pressAndConfirm(p, row);
    const password = await panelAt(p);
    const withPassword = await primaries(p);
    // The setup's Players step, before and after it makes an account.
    await p.goto(`${A}/setup?step=players`, { waitUntil: 'domcontentloaded' });
    const step = await primaries(p);
    await p.type('main form.form-row input[name=name]', `step${size}`);
    await press(p, 'main form.form-row button');
    const made = await p.$eval('section.account-made', e => {
      const r = e.getBoundingClientRect();
      return { top: Math.round(r.top), bottom: Math.round(r.bottom), screen: innerHeight, focused: document.activeElement === e };
    }).catch(() => null);
    const stepMade = await primaries(p);
    for (const [what, at] of [['Make token', token], ['New password', password], ["the setup's Make an account", made]]) {
      if (!at || at.top < 0 || at.bottom > at.screen || !at.focused) outOfView.push(`${what} at ${size}: ${JSON.stringify(at)}`);
    }
    for (const [what, found] of [['accounts', plain], ['accounts with a token', withToken], ['accounts with a password', withPassword],
      ["the setup's Players step", step], ["the setup's Players step with an account made", stepMade]]) {
      if (found.length !== 1) notOne.push(`${what} at ${size}: ${found.join(' + ') || 'none'}`);
    }
    await p.close();
  }
  check('what shows once is in view with the focus after Make token and New password, on a laptop and a phone', outOfView.length === 0,
    outOfView.join('; '));
  check("one primary button on the Accounts page and the setup's Players step, with what shows once or without", notOne.length === 0,
    notOne.join('; '));

  // The accounts' buttons stand in the same columns in every row: a button whose word depends on the account (Disable or
  // Enable, Give or Remove admin rights) is as wide as its other word too. Now with an admin, a player and a switched-off
  // account, at the narrowest tablet, a tablet on its side, both sides of the width where the buttons leave the row,
  // and a laptop, in both languages; the layout measured at each, where the player's list showed "Not linked" cut.
  const ragged = [];
  for (const lang of ['ko', 'en']) {
    await page.goto(`${A}/lang?to=${lang}&next=%2Fopendmtq%2Fadmin%2Faccounts`, { waitUntil: 'domcontentloaded' });
    for (const w of [744, 1024, 1240, 1241, 1280]) {
      await page.setViewport({ width: w, height: 900 });
      // Each row's buttons by their left edges: one set of edges for every row, or the columns are ragged.
      const lefts = await page.$$eval('table.accounts tbody tr', rows => rows.map(r => [...r.querySelectorAll('.btns .btn')].map(b => Math.round(b.getBoundingClientRect().left)).join('/')));
      if (new Set(lefts).size > 1) ragged.push(`${lang} ${w}: ${lefts.join(' ')}`);
      await noFindings(page, `the accounts at ${w} px, ${lang}`);
    }
  }
  check('the buttons of every account stand in the same columns', ragged.length === 0, ragged.join('; '));
  // Back to the width and the language the rest of these steps expect.
  await page.setViewport({ width: 1280, height: 900 });

  // An API token: made on the Accounts page and shown once, measured at every width while it is there (the list itself is
  // in every sweep of the page), in both languages; it works against the API at once, and is revoked there. The width
  // alone changes: a viewport that changes to a phone's would load the page again, and the token is shown only once.
  for (const lang of ['ko', 'en']) {
    await page.goto(`${A}/lang?to=${lang}&next=%2Fopendmtq%2Fadmin%2Faccounts`, { waitUntil: 'domcontentloaded' });
    await page.type('#tokens input[name=token_name]', `flow token ${lang}`);
    await page.select('#tokens select[name=scope]', 'write');
    await press(page, '#tokens form button');
    const secret = await textOf(page, '#token-secret');
    // The report names the token by its id alone (odq_<id>_), as the list does: none of its secret goes into a report.
    check(`a token is made on the Accounts page and shown once (${lang})`, /^odq_[0-9a-f]{12}_[A-Za-z0-9_-]{43}$/.test(secret), secret.slice(0, 17));
    for (const w of ALL_WIDTHS) {
      await page.setViewport({ width: w, height: 900 });
      await noFindings(page, `the accounts page with a new token at ${w} px, ${lang}`);
    }
    await page.setViewport({ width: 1280, height: 900 });
    if (lang !== 'en') continue;
    // Asked as a program with the token asks: from here, not from the page. The page's own failed requests are what this
    // stage counts, and a revoked token's 401 is the answer wanted.
    const ask = async sent => {
      const r = await fetch(`${ADMIN}/opendmtq/api/v1/status`, { headers: { Authorization: `Bearer ${sent}` } });
      return [r.status, (await r.json()).address || ''];
    };
    const works = await ask(secret);
    check('and works against the API at once', works[0] === 200 && works[1] !== '', String(works));
    await page.goto(`${A}/accounts`, { waitUntil: 'domcontentloaded' });
    check('and is not shown again', !(await page.$('#token-secret')));
    await pressAndConfirm(page, `table.tokens form:has(input[name=token][value="${secret.split('_')[1]}"]) button`);
    const revoked = await ask(secret);
    check('a revoked token no longer works', revoked[0] === 401 && /revoked/.test(await textOf(page, '.flash')), String(revoked));
  }

  // A backup at the press of a button; the list and the status page show it.
  await page.goto(`${A}/backups`, { waitUntil: 'domcontentloaded' });
  await press(page, 'form:has(input[name=action][value=create]) button');
  check('a backup is made and listed', /\.tar\.gz/.test(await textOf(page, 'table.data')));
  await noFindings(page, 'the backups page with a backup');
  await page.goto(`${A}/`, { waitUntil: 'domcontentloaded' });
  check('the status page knows about it', /\.tar\.gz/.test(await textOf(page, '.tiles')));

  // A file that is no song package: refused, in words, in the page's look.
  await page.goto(`${A}/songs`, { waitUntil: 'domcontentloaded' });
  const bad = '/tmp/not-a-package.zip';
  fs.writeFileSync(bad, 'not a zip file');
  await (await page.$('input[type=file]')).uploadFile(bad);
  // With a file chosen the upload's button can be pressed, and is the page's one primary button to a screen; on the
  // Backups page too, where Back up now is that one, with a file chosen in its upload box (not sent).
  const songChosen = await twoPrimaries(page);
  const backups = await contexts.signed.newPage();
  await backups.setViewport({ width: 1280, height: 900 });
  await backups.goto(`${A}/backups`, { waitUntil: 'domcontentloaded' });
  await (await backups.$('form.upload input[type=file]')).uploadFile(bad);
  const backupChosen = await twoPrimaries(backups);
  await backups.close();
  check('one primary button to a screen with a file chosen to upload, on the Songs and the Backups pages',
    songChosen.length === 0 && backupChosen.length === 0, [...songChosen, ...backupChosen].map(f => f.at).join('; '));
  await press(page, 'form[enctype] button:not([type=button])');
  check('a bad song package is refused in words', /\S/.test(await textOf(page, '.flash')), (await textOf(page, '.flash')).slice(0, 100));
  await noFindings(page, 'the songs page after a refused package');
  // What did not happen is not in the log of changes.
  await page.goto(`${A}/logs?tab=changes`, { waitUntil: 'domcontentloaded' });
  check('a refused package is no change', !/Added a song/.test(await textOf(page, '.changes')));

  // A player's records by level count the songs players can see (player.php): with the first song hidden on the Songs
  // page, its charts go from every level's count (four of level 1 with its Easy, three of 4 and of 7, make_content.php),
  // and no level says more records than charts; shown again, the counts are as they were.
  const levelsOf = async () => {
    const p = await contexts.signed.newPage();
    await p.goto(`${P}/player.php?id=1`, { waitUntil: 'domcontentloaded' });
    const rows = await p.$$eval('.levels .level', ls => ls.map(l => [Number(l.querySelector('.level-name').textContent.replace(/\D/g, '')),
      ...l.querySelector('b').textContent.split('/').map(n => Number(n.trim()))]));
    await p.close();
    return Object.fromEntries(rows.map(([lv, held, all]) => [lv, [held, all]]));
  };
  const shownLevels = await levelsOf();
  await page.goto(`${A}/songs`, { waitUntil: 'domcontentloaded' });
  await press(page, 'form:has(input[name=song_id][value="1"]):has(input[name=action][value=hide]) button');
  const hiddenLevels = await levelsOf();
  await page.goto(`${A}/songs`, { waitUntil: 'domcontentloaded' });
  await press(page, 'form:has(input[name=song_id][value="1"]):has(input[name=action][value=show]) button');
  const backLevels = await levelsOf();
  const dropped = Object.fromEntries(Object.entries(shownLevels).map(([lv, [, all]]) => [lv, all - ((hiddenLevels[lv] || [0, 0])[1])]).filter(([, d]) => d));
  check("a player's levels count only the songs players can see",
    Object.keys(shownLevels).length > 0 && JSON.stringify(dropped) === '{"1":4,"4":3,"7":3}'
    && Object.values(hiddenLevels).every(([held, all]) => held <= all) && JSON.stringify(backLevels) === JSON.stringify(shownLevels),
    JSON.stringify({ shownLevels, hiddenLevels, dropped }));

  // A recording hidden from the public list comes back when shown again. A live page open all the while asks for that list
  // only when it changed (live.php, live_past_rev()): not at its looks while nothing changes, once right after each change.
  await page.goto(`${A}/recordings`, { waitUntil: 'domcontentloaded' });
  const hide = await page.$('button[name=action][value^="hide"]');
  check('a recording can be hidden', !!hide);
  if (hide) {
    const name = await hide.evaluate(e => e.value.split(' ')[1]);
    const key = name.replace('/', '-');
    // The viewer's page, and every look it takes: 'past' for the list of recordings, 'look' for who is on alone.
    const viewer = await contexts.signed.newPage();
    await viewer.setViewport({ width: 1280, height: 900 });
    const asked = [];
    viewer.on('request', r => { if (/\/live\.php\?list=1/.test(r.url())) asked.push(r.url().includes('past=1') ? 'past' : 'look'); });
    await viewer.goto(`${P}/live.php`, { waitUntil: 'domcontentloaded' });
    // In front, as a page someone watches: a page out of sight with nothing playing takes no looks.
    await viewer.bringToFront();
    // The sign of the list, as a look carries it.
    const rev = () => viewer.evaluate(async () => (await (await fetch('/opendmtq/live.php?list=1')).json()).past_rev);
    const before = await rev();
    // Two looks and more with nothing changed.
    await pause(11000);
    const quiet = [...asked];
    const card = shown => viewer.waitForFunction((k, on) => !!document.querySelector(`#past-list .past[data-key="${k}"]`) === on,
      { timeout: 15000 }, key, shown).then(() => true, () => false);
    // The owner's page in front for its button, then the viewer's again, which looks at once on coming back.
    await page.bringToFront();
    await press(page, 'button[name=action][value^="hide"]');
    await viewer.bringToFront();
    const hiddenRev = await rev();
    const goneThere = await card(false);
    const afterHide = asked.length;
    const list = () => contexts.signed.newPage().then(async p => {
      await p.goto(`${P}/live.php?list=1&past=1`, { waitUntil: 'domcontentloaded' });
      const text = await p.evaluate(() => document.body.textContent);
      await p.close();
      return text;
    });
    check('and is gone from the public list', !(await list()).includes(key));
    await page.bringToFront();
    await press(page, `button[name=action][value="show ${name}"]`);
    await viewer.bringToFront();
    const shownRev = await rev();
    const backThere = await card(true);
    check('and is back when shown', (await list()).includes(key));
    const pastAsked = asked.filter(a => a === 'past').length;
    check("an open live page asks for the recordings' list only when it changed",
      quiet.length >= 2 && !quiet.includes('past') && hiddenRev !== before && shownRev === before && goneThere && backThere
      && asked.slice(quiet.length, afterHide).filter(a => a === 'past').length === 1 && pastAsked === 2,
      `${quiet.join(',')} | ${asked.slice(quiet.length).join(',')} | ${before} ${hiddenRev} ${shownRev} ${goneThere} ${backThere}`);
    await viewer.close();
  }
  check('no failed requests or script errors in all that', errors.length === 0, errors.slice(0, 5).join(' ; '));
  await page.close();
  // Signing out is no error, and says so in the colour of what went well. In a browser of its own: the rest stays signed in.
  const out = await contexts.anon.newPage();
  await out.goto(`${A}/login`, { waitUntil: 'domcontentloaded' });
  await typeId(out, 'input[name=name]', 'admin');
  await out.type('input[name=password]', PASSWORD);
  await Promise.all([out.waitForNavigation({ waitUntil: 'domcontentloaded' }), out.keyboard.press('Enter')]);
  await press(out, '.auth-form button');
  check('signing out is said as what went well', await visible(out, '.signin .done') && !(await out.$('.signin .error')));
  await out.close();
}

// The admin pages from the server PC itself (the browser on the admin service's own network: its loopback): Play on this
// PC on the App page and the setup's last step, as the Windows bundle shows it (WINDOWS=1: the button that installs the PC
// client here); a host install on Linux shows nothing for it (how to play from a Windows PC is the docs', ADM-201). Swept
// at every width in both languages; on the bundle, pressed, its job followed on the page to its end, which says what came
// of it (no Windows program runs here).
async function thisPc(contexts) {
  const windows = process.env.WINDOWS === '1';
  const kind = windows ? 'the Windows bundle' : 'a host install on Linux';
  const page = await contexts.signed.newPage();
  for (const [where, url] of [['the App page', `${A}/app`], ["the setup's last step", `${A}/setup?step=app`]]) {
    await page.goto(url, { waitUntil: 'networkidle2' });
    const words = await textOf(page, '#this-pc');
    if (windows) {
      check(`${kind}: ${where}, from the server PC, has Play on this PC`,
        (await page.$('#this-pc button')) !== null && /Installs the PC client on this PC/.test(words), words.slice(0, 200));
    } else {
      check(`${kind}: ${where}, from the server PC, has no card of how to play from a Windows PC`,
        (await page.$('#this-pc')) === null && !/Play on a Windows PC/.test(await textOf(page, 'main')), words.slice(0, 200));
    }
  }
  await page.close();
  const variant = windows ? 'windows' : 'linux';
  await sweep(contexts, [[`app-here-${variant}`, `${A}/app`], [`setup-here-${variant}`, `${A}/setup?step=app`]], ALL_WIDTHS);
  if (!windows) return;
  const pressed = await contexts.signed.newPage();
  await pressed.setViewport({ width: 1280, height: 900 });
  // In English, as its picture's name says: the sweep above left the browser on the last language it swept.
  await pressed.setCookie({ name: 'opendmtq_lang', value: 'en', url: ADMIN });
  await pressed.goto(`${A}/app`, { waitUntil: 'networkidle2' });
  await Promise.all([pressed.waitForNavigation({ waitUntil: 'domcontentloaded' }), pressed.click('#this-pc button')]);
  // Followed while it runs, then the page with what it said.
  await until(pressed, () => !document.querySelector('#here-log'), null, 60000);
  await pressed.waitForSelector('.flash', { timeout: 30000 }).catch(() => {});
  const said = await textOf(pressed, '.flash');
  check('pressed on the Windows bundle, Play on this PC says what came of it, its button there again', /PC client/.test(said)
    && (await pressed.$('#this-pc button:not([disabled])')) !== null, said.slice(0, 200));
  await noFindings(pressed, 'Play on this PC after a press');
  await pressed.screenshot({ path: path.join(OUT, 'shots', 'thispc-pressed-en-1280.jpg'), type: 'jpeg', quality: 72, fullPage: true });
  await pressed.close();
}

// PAGE-65..68: the owner's notice on the site (the Notices page's first card, admin/notice.py; lib.php notice_band()). Put up
// by the owner's own form with words that wrap on a phone: under the bar on every page for those signed in, never for a
// stranger; every page whole with it at every width in both languages; closed for this visit by its cross, back on the next
// visit and with new words; on the pages left open it comes, changes and goes by itself. Before: there was no notice.
async function ownersNotice(contexts) {
  const LONG = 'Tonight the server stays open until 1 AM. Three new songs come on Friday, and the monthly ranking starts again on the first at nine.';
  const owner = await contexts.signed.newPage();
  await owner.setViewport({ width: 1280, height: 900 });
  // The card's Show, with these words and no end.
  // The owner's tab in front first: a tab out of sight for minutes has its timers held back by the browser, and the press
  // would wait for a page that looks only once a minute.
  const putUp = async text => {
    await owner.bringToFront();
    await owner.goto(`${A}/maintenance`, { waitUntil: 'domcontentloaded' });
    await owner.$eval('#notice input[name=text]', (e, v) => { e.value = v; }, text);
    await press(owner, '#notice button[name=action][value=show]');
  };
  // The card's Take down.
  const takeDown = async () => {
    await owner.bringToFront();
    await owner.goto(`${A}/maintenance`, { waitUntil: 'domcontentloaded' });
    await press(owner, '#notice button[name=action][value=clear]');
  };
  await owner.goto(`${A}/maintenance`, { waitUntil: 'domcontentloaded' });
  check('the Notices page has the notice card first, saying there is none', /No notice/.test(await textOf(owner, '#notice'))
    && await owner.evaluate(() => document.querySelector('#notice').compareDocumentPosition(document.querySelector('#maintenance')) === Node.DOCUMENT_POSITION_FOLLOWING));
  // Refused (an end that has passed): said on the same page, in place, with the words typed still in their field.
  await owner.$eval('#notice input[name=text]', e => { e.value = 'Words for a moment gone by.'; });
  await owner.$eval('#notice input[name=until]', e => { e.value = '2020-01-01T09:00'; });
  await press(owner, '#notice button[name=action][value=show]');
  check('PAGE-69: a refused notice is said on the Notices page, its words kept in the field',
    new URL(owner.url()).pathname === '/opendmtq/admin/maintenance' && /That moment has passed already/.test(await textOf(owner, '.bar .flash'))
    && await owner.$eval('#notice input[name=text]', e => e.value) === 'Words for a moment gone by.', `${owner.url()} | ${await textOf(owner, '.bar .flash')}`);
  await putUp(LONG);
  check("the owner's form puts it up, and the card says so in place", /Shown on the site/.test(await textOf(owner, '#notice')), await textOf(owner, '#notice .auto-line'));
  // Under the bar on the site, for someone signed in; nothing of it for a stranger at the sign-in.
  const site = await contexts.signed.newPage();
  await site.setViewport({ width: 1280, height: 900 });
  await site.goto(`${P}/`, { waitUntil: 'domcontentloaded' });
  check('PAGE-65: every page of the site has it under the bar, its words whole', await textOf(site, 'body > .site-notice .notice-text') === LONG
    && await site.evaluate(() => document.querySelector('body > .site-notice').compareDocumentPosition(document.querySelector('body > h1.page-title')) === Node.DOCUMENT_POSITION_FOLLOWING));
  // On every page of the site the sweep looks at, its words whole there too.
  const without = [];
  for (const [name, url] of NOTICE.filter(([n]) => !n.startsWith('admin'))) {
    await site.goto(url, { waitUntil: 'domcontentloaded' });
    if (await textOf(site, 'body > .site-notice .notice-text') !== LONG) without.push(name);
  }
  check('PAGE-65: and on every other page of the site', without.length === 0, without.join(' '));
  const stranger = await contexts.anon.newPage();
  await stranger.goto(`${P}/ranking.php`, { waitUntil: 'domcontentloaded' });
  check('PAGE-65: a stranger at the sign-in sees nothing of it', (await stranger.$('.site-notice')) === null && !(await stranger.content()).includes('Three new songs'));
  await stranger.close();
  // Every page with it, at every width, in both languages: nothing cut off, touching or under another box.
  await sweep(contexts, NOTICE, ALL_WIDTHS);
  // Its cross: a key a finger can hit, named in the page's language.
  check('PAGE-66: its cross is named for what it does', await site.$eval('.notice-close', b => b.getAttribute('aria-label')) === 'Close the notice');
  await site.setCookie({ name: 'opendmtq_lang', value: 'ko', url: `${P}/` });
  await site.goto(`${P}/songs.php`, { waitUntil: 'domcontentloaded' });
  check('PAGE-66: and in Korean in Korean', await site.$eval('.notice-close', b => b.getAttribute('aria-label')) === '공지 닫기');
  await site.setCookie({ name: 'opendmtq_lang', value: 'en', url: `${P}/` });
  // Closed: gone at once, and for the rest of this visit (this tab) before it is ever drawn; back on the next visit.
  await site.goto(`${P}/`, { waitUntil: 'domcontentloaded' });
  await site.click('.notice-close');
  check('PAGE-66: its cross closes it at once', (await site.$('body > .site-notice')) === null);
  await site.goto(`${P}/ranking.php`, { waitUntil: 'domcontentloaded' });
  check('PAGE-66: and it stays closed on the next page of the visit, never drawn', await site.$eval('body > .site-notice', b => getComputedStyle(b).display).catch(() => 'gone') === 'none');
  await site.reload({ waitUntil: 'domcontentloaded' });
  check('PAGE-66: and after a reload', await site.$eval('body > .site-notice', b => getComputedStyle(b).display).catch(() => 'gone') === 'none');
  const next = await contexts.signed.newPage();
  await next.goto(`${P}/`, { waitUntil: 'domcontentloaded' });
  check('PAGE-66: the next visit shows it again', !['none', 'gone'].includes(await next.$eval('body > .site-notice', b => getComputedStyle(b).display).catch(() => 'gone')));
  await next.close();
  // New words: shown again where the old ones were closed.
  await putUp('Open late tonight.');
  await site.goto(`${P}/`, { waitUntil: 'domcontentloaded' });
  check('PAGE-67: new words show again where the old were closed', await textOf(site, 'body > .site-notice .notice-text') === 'Open late tonight.'
    && await site.$eval('body > .site-notice', b => getComputedStyle(b).display) !== 'none');
  await site.close();
  // PAGE-68: the home page and the live page left open (both look at the server by themselves): a notice put up, given new
  // words and taken down comes, changes and goes there by itself, the page not opened anew.
  await takeDown();
  const open = [];
  for (const url of [`${P}/`, `${P}/live.php`]) open.push(await openAlone(contexts, url));
  const says = words => {
    const band = document.querySelector('body > .site-notice');
    return words === null ? !band : !!band && band.textContent.includes(words) && getComputedStyle(band).display !== 'none';
  };
  const all = async (words, name) => {
    const came = [];
    for (const page of open) came.push(await until(page, says, words) && await keptOpen(page));
    check(name, came.every(Boolean), came.join(' '));
  };
  await putUp('The server is open all night.');
  await all('The server is open all night.', 'PAGE-68: put up, the pages left open show it by themselves');
  // Closed on the home page left open; the live page keeps it.
  const [home, live] = open;
  await home.click('.notice-close');
  // Maintenance begun: both pages put its sentence in place by themselves. On the live page the notice comes under it; on
  // the home page, where it was closed, it stays closed (the page's own look takes the page again).
  await owner.bringToFront();
  await owner.goto(`${A}/maintenance`, { waitUntil: 'domcontentloaded' });
  await pressAndConfirm(owner, '#maintenance button[name=action][value=on]');
  const ordered = await until(live, () => {
    const alert = document.querySelector('body > .site-alert'), band = document.querySelector('body > .site-notice');
    return !!alert && !!band && alert.compareDocumentPosition(band) === Node.DOCUMENT_POSITION_FOLLOWING;
  });
  check('PAGE-68: with maintenance begun, its sentence comes above the notice', ordered);
  const stayed = await until(home, () => !!document.querySelector('body > .site-alert')) && await home.evaluate(() => {
    const band = document.querySelector('body > .site-notice');
    return !band || getComputedStyle(band).display === 'none';
  });
  check('PAGE-68: and where it was closed it stays closed as the page takes maintenance in', stayed && await keptOpen(home));
  await owner.bringToFront();
  await owner.goto(`${A}/maintenance`, { waitUntil: 'domcontentloaded' });
  await press(owner, '#maintenance button[name=action][value=off]');
  await putUp('Back to normal hours tomorrow.');
  await all('Back to normal hours tomorrow.', 'PAGE-68: new words, the pages left open say them by themselves, where the old were closed too');
  await takeDown();
  await all(null, 'PAGE-68: taken down, it goes from the pages left open by themselves');
  for (const page of open) await page.browserContext().close();
  await owner.close();
}

// MY PAGE (PAGE-60 to PAGE-64): a signed-in player's own page, from the bar's name and badge, for an account linked to its
// game player, one that is not and the server's own, at every width in both languages; what each change of the account
// does to the other sign-ins; its JSON twin, refused to a visitor who has not signed in and to another site. Its changes are
// made on an account of this stage's own (run.sh makes it: mypage, with admin rights, linked to the seed's Sena, with a read
// token in OUT/mypage-token.txt), so that the account every stage signs in with stays as it is.
const MINE = { id: 'mypage', password: 'mypage-pass-1', next: 'mypage-pass-2', moved: 'mypage2' };

// A browser of its own signed in to the site; true when the sign-in led to MY PAGE.
async function siteSignIn(context, id, password) {
  const page = await context.newPage();
  await page.goto(`${P}/login.php?next=%2Fopendmtq%2Fme.php`, { waitUntil: 'domcontentloaded' });
  await typeId(page, 'input[name=user]', id);
  await page.type('input[name=password]', password);
  await Promise.all([page.waitForNavigation({ waitUntil: 'domcontentloaded' }), page.keyboard.press('Enter')]);
  const inside = new URL(page.url()).pathname === '/opendmtq/me.php';
  await page.close();
  return inside;
}

// Whether a browser is still signed in: MY PAGE answers it, not the sign-in.
async function stillIn(context) {
  const page = await context.newPage();
  await page.goto(`${P}/me.php`, { waitUntil: 'domcontentloaded' });
  const inside = new URL(page.url()).pathname === '/opendmtq/me.php';
  await page.close();
  return inside;
}

// One of the account tab's forms, filled in and sent as a person does it: its fields by their ids, then its button.
async function sendForm(page, form, fields) {
  // A page that sat behind the other browsers' pages: in front first, or Chrome holds its timers back.
  await page.bringToFront();
  for (const [id, text] of Object.entries(fields)) {
    await page.$eval(`#${id}`, e => { e.value = ''; });
    await page.type(`#${id}`, text);
  }
  await Promise.all([page.waitForNavigation({ waitUntil: 'domcontentloaded' }), page.click(`form[action*="do=${form}"] button:not([type=button])`)]);
}

async function myPage(contexts) {
  // The bar's name and badge, for the account every stage signs in with (linked to no player): MY PAGE, which says so.
  const page = await contexts.signed.newPage();
  await page.setViewport({ width: 1280, height: 900 });
  await page.goto(`${P}/ranking.php`, { waitUntil: 'domcontentloaded' });
  const href = await page.$eval('.auth-who', e => e.getAttribute('href')).catch(() => '');
  check("the bar's name and badge open MY PAGE, for an account linked to no player too", href === '/opendmtq/me.php', href);
  await page.goto(`${P}/me.php`, { waitUntil: 'domcontentloaded' });
  const unlinked = await textOf(page, '.me-head');
  const tabs = await page.$$eval('.tabs a', as => as.map(a => a.textContent.trim()));
  check("an account linked to no player says so, and has no tabs of plays", /not linked to a game player/.test(unlinked) && tabs.join() === 'Profile,Account',
    `${unlinked.slice(0, 80)} ${tabs}`);
  await page.close();
  await sweep(contexts, [['my page, not linked', `${P}/me.php`], ['my account, not linked', `${P}/me.php?tab=account`]], ALL_WIDTHS);

  // The linked account in a browser of its own: every tab, at every width, in both languages.
  const linked = await contexts.browser.createBrowserContext();
  check("MY PAGE's account signs in to the site", await siteSignIn(linked, MINE.id, MINE.password));
  const mine = { signed: linked, anon: contexts.anon };
  await sweep(mine, [['my page', `${P}/me.php`], ['my plays', `${P}/me.php?tab=plays`], ['my records', `${P}/me.php?tab=records`],
                     ['my account', `${P}/me.php?tab=account`]], ALL_WIDTHS);
  const me = await linked.newPage();
  await me.setViewport({ width: 1280, height: 900 });
  await me.setCookie({ name: 'opendmtq_lang', value: 'en', url: P });
  // The profile against the JSON twin, and the twin against what the game's player is.
  await me.goto(`${P}/me.php`, { waitUntil: 'domcontentloaded' });
  const facts = await me.evaluate(async () => (await fetch('/opendmtq/me.php?json')).json());
  const head = await textOf(me, '.me-head h2');
  check("the linked account's profile is its game player's, as its JSON twin says", head.startsWith('Sena') && facts.player && facts.player.name === 'Sena'
    && facts.account.id === MINE.id && facts.game && facts.game.level > 0 && Array.isArray(facts.achievements.held), `${head} ${JSON.stringify(facts).slice(0, 200)}`);
  check('its public page is one link away', await me.$eval('.me-public a', a => a.getAttribute('href')).catch(() => '') === '/opendmtq/player.php?id=1');
  // The four slots name their items as the game shows them, by the catalog's names (run.sh's stand-in gives 30001 and
  // 100001 theirs), the JSON twin as the page; an item the catalog has no name for keeps its number. Before: numbers only.
  const named = { 30001: 'Jimmy', 100001: 'Yellow' };
  const slots = Object.entries((facts.game && facts.game.equipped) || {});
  const shown = await textOf(me, '.me-items');
  check("MY PAGE names the equipped items as the game shows them, and its JSON twin too",
    !!facts.game.equipped_names && slots.length === 4
      && slots.every(([slot, id]) => (facts.game.equipped_names[slot] || '') === (named[id] || ''))
      && slots.every(([, id]) => !id || shown.includes(named[id] || `No. ${id}`))
      // seed.php equips Jimmy, Yellow and an unnamed note: the names and the number all seen.
      && shown.includes('Jimmy') && shown.includes('Yellow') && shown.includes('No. 90001'),
    `${JSON.stringify(facts.game.equipped)} ${JSON.stringify(facts.game.equipped_names)} | ${shown.slice(0, 200)}`);
  const total = facts.player.total;
  // Every play of the player, a page at a time: the twin counts them as the page does.
  await me.goto(`${P}/me.php?tab=plays`, { waitUntil: 'domcontentloaded' });
  const listed = (await me.$$('table.plays tr')).length;
  const plays = await me.evaluate(async () => (await fetch('/opendmtq/me.php?json&tab=plays')).json());
  check('every play, as its JSON twin pages them', listed > 15 && listed === Math.min(50, plays.plays.total) && plays.plays.items.length === listed, `${listed} ${plays.plays.total}`);
  // Nothing of the account on what others see of the player.
  const public_ = await contexts.signed.newPage();
  await public_.goto(`${P}/player.php?id=1`, { waitUntil: 'domcontentloaded' });
  const seen = await public_.content();
  check("nothing of the player's account on their public page", !seen.includes(MINE.id) && !seen.includes("my page's checks"), '');
  await public_.close();

  // A wrong current password: said under its field, and nothing changes.
  await me.goto(`${P}/me.php?tab=account`, { waitUntil: 'domcontentloaded' });
  await sendForm(me, 'password', { 'me-current': 'not-my-password', 'me-new': MINE.next, 'me-new2': MINE.next });
  const wrong = await textOf(me, '#me-current-error');
  check('a wrong current password is said under its field', wrong === 'That is not your current password.' && await me.$eval('#me-current', e => e.getAttribute('aria-invalid')) === 'true', wrong);
  await noFindings(me, 'a wrong current password on MY PAGE');
  // Another browser of the account's, signed in before the change: its sign-in ends; this one's stays.
  const other = await contexts.browser.createBrowserContext();
  await siteSignIn(other, MINE.id, MINE.password);
  await sendForm(me, 'password', { 'me-current': MINE.password, 'me-new': MINE.next, 'me-new2': MINE.next });
  check('the password changed, said so, this browser still signed in', new URL(me.url()).searchParams.get('done') === 'password'
    && /Your password is changed/.test(await textOf(me, '.done')) && await stillIn(linked));
  check("another browser's sign-in ended with the old password", !(await stillIn(other)));
  const fresh = await contexts.browser.createBrowserContext();
  check('the old password signs in no more, the new one does', !(await siteSignIn(fresh, MINE.id, MINE.password)) && await siteSignIn(fresh, MINE.id, MINE.next));
  // Sign out everywhere else: the browser signed in just now ends, this one stays.
  await sendForm(me, 'signout', {});
  check('signed out everywhere else, this browser still signed in', new URL(me.url()).searchParams.get('done') === 'signout' && await stillIn(linked));
  check("the other browser's sign-in ended", !(await stillIn(fresh)));
  // A change sent from another site (a page of the admin pages' address, another origin): refused, nothing changed. The
  // browser signs in again a second after the sign-out, which ended every sign-in up to its own second.
  const elsewhere = await linked.newPage();
  await elsewhere.goto(`${A}/login`, { waitUntil: 'domcontentloaded' });
  await pause(1200);
  await siteSignIn(fresh, MINE.id, MINE.next);
  await elsewhere.evaluate(async url => { await fetch(url, { method: 'POST', mode: 'no-cors', credentials: 'include' }).catch(() => null); }, `${P}/me.php?json&do=signout`);
  check('a change sent from another site is refused', await stillIn(fresh) && await stillIn(linked));
  await elsewhere.close();
  // The ID: the plays and records stay (they go with the game player), and the account's API token follows it.
  await sendForm(me, 'id', { 'me-id': MINE.moved, 'me-id-current': MINE.next });
  check('the ID changed and said so', new URL(me.url()).searchParams.get('done') === 'id' && (await textOf(me, '.done')).includes(MINE.moved));
  const after = await me.evaluate(async () => (await fetch('/opendmtq/me.php?json')).json());
  check('the plays and records stay with it', after.account.id === MINE.moved && after.player && after.player.name === 'Sena' && after.player.total === total,
    JSON.stringify(after.account) + JSON.stringify(after.player));
  const token = fs.readFileSync(path.join(OUT, 'mypage-token.txt'), 'utf8').trim();
  const listing = await fetch(`${ADMIN}/opendmtq/api/v1/tokens`, { headers: { Authorization: `Bearer ${token}` } });
  const items = listing.ok ? (await listing.json()).items : [];
  check('its API token follows it, and works', listing.status === 200 && items.some(i => i.admin === MINE.moved && i.works), `${listing.status} ${JSON.stringify(items).slice(0, 160)}`);
  check('the old ID signs in no more, the new one does', !(await siteSignIn(fresh, MINE.id, MINE.next)) && await siteSignIn(fresh, MINE.moved, MINE.next));
  await me.close();
  await fresh.close();
  await other.close();
  await linked.close();

  // Nothing of MY PAGE or its twin for a visitor who has not signed in: the sign-in, and the twin's refusal in its shape.
  const stranger = await contexts.anon.newPage();
  await stranger.goto(`${P}/me.php`, { waitUntil: 'domcontentloaded' });
  const door = new URL(stranger.url()).pathname;
  const twin = await stranger.evaluate(async () => { const r = await fetch('/opendmtq/me.php?json'); return [r.status, await r.text()]; });
  check('nothing of MY PAGE for a visitor who has not signed in', door === '/opendmtq/login.php' && twin[0] === 403 && JSON.parse(twin[1]).error.code === 'signin', `${door} ${twin}`);
  await stranger.close();

  // The owner's account (from .env) on the site: its password is the server's, changed on the Server page.
  const owner = await contexts.browser.createBrowserContext();
  check("the owner's account signs in to the site", await siteSignIn(owner, 'admin', PASSWORD));
  const own = await owner.newPage();
  await own.setCookie({ name: 'opendmtq_lang', value: 'en', url: P });
  await own.goto(`${P}/me.php?tab=account`, { waitUntil: 'domcontentloaded' });
  check("its account tab says the password is the server's, with the way to the Server page, and no password form",
    /owner's account/.test(await textOf(own, 'main')) && (await own.$('a[href="/opendmtq/admin/server#password"]')) !== null && (await own.$('#me-current')) === null);
  // Called the owner, as the admin pages call them, in both languages; the way to the Server page named as the admin
  // pages' menu names that page (ADM-194).
  const ownerNamed = {};
  // The admin pages' menu as the admin signed in to them sees it, in each language.
  const pages = await contexts.signed.newPage();
  for (const lang of ['en', 'ko']) {
    await own.setCookie({ name: 'opendmtq_lang', value: lang, url: P });
    await own.goto(`${P}/me.php?tab=account`, { waitUntil: 'domcontentloaded' });
    const words = await textOf(own, 'main');
    const button = await own.$eval('a[href="/opendmtq/admin/server#password"]', a => a.textContent.trim()).catch(() => '');
    await pages.goto(`${A}/lang?to=${lang}&next=%2Fopendmtq%2Fadmin%2Fserver`, { waitUntil: 'domcontentloaded' });
    const menu = await pages.$eval('.nav.pages a[href="/opendmtq/admin/server"]', a => a.textContent.trim()).catch(() => '?');
    ownerNamed[lang] = { owner: lang === 'en' ? /owner's account/.test(words) && !/server's own account/.test(words) : /소유자 계정/.test(words) && !/서버 자체/.test(words), button, menu };
  }
  // The language the stages after this one read.
  await pages.goto(`${A}/lang?to=en&next=%2Fopendmtq%2Fadmin%2F`, { waitUntil: 'domcontentloaded' });
  await pages.close();
  check("MY PAGE calls the owner's account the owner's, and names its way to the Server page as the admin pages' menu does",
    Object.values(ownerNamed).every(n => n.owner && n.button === n.menu), JSON.stringify(ownerNamed));
  await own.close();
  await sweep({ signed: owner, anon: contexts.anon }, [['my page, the owner', `${P}/me.php`], ['my account, the owner', `${P}/me.php?tab=account`]], ALL_WIDTHS);
  await owner.close();
}

(async () => {
  fs.mkdirSync(path.join(OUT, 'shots'), { recursive: true });
  const contexts = await open();
  if (stage !== 'self') await signIn(contexts.signed);
  if (stage === 'self') {
    await self(contexts);
  } else if (stage === 'empty') {
    await broadcastsOff(contexts, false);
    await noAppYet(contexts);
    await sweep(contexts, EMPTY, FEW_WIDTHS);
  } else if (stage === 'full') {
    await sweep(contexts, FULL, ALL_WIDTHS);
    await backgroundClear(contexts);
    await hallOfFame(contexts);
  } else if (stage === 'keys') {
    await keyboardMarks(contexts);
  } else if (stage === 'thispc') {
    await thisPc(contexts);
  } else if (stage === 'air') {
    // The video really runs, and the page says who is on.
    const page = await contexts.signed.newPage();
    await page.setViewport({ width: 1280, height: 800 });
    await page.goto(`${P}/live.php?id=1`, { waitUntil: 'domcontentloaded' });
    await pause(5000);
    const a = await page.$eval('#live-video', e => e.currentTime);
    await pause(3000);
    const b = await page.$eval('#live-video', e => e.currentTime);
    check('the broadcast plays', b > a + 1.5, `${a} -> ${b}`);
    check('marked as live', await textOf(page, '#pill-word') === 'LIVE');
    check('both players are listed', (await page.$$('#live-list > *, #live-others li')).length >= 1);
    await page.close();
    // The home page while players are on air: one lit button, the app's download; the way to the broadcasts is quiet
    // metal, its light the on-air red, with the count (SRV-92).
    const lit = await contexts.signed.newPage();
    await lit.setViewport({ width: 1280, height: 900 });
    await lit.goto(`${P}/`, { waitUntil: 'domcontentloaded' });
    await lit.waitForSelector('#watch-live.on', { timeout: 20000 }).catch(() => {});
    const acts = await lit.$$eval('.stage-acts > *', els => els.map(e => ({ cls: e.className, img: getComputedStyle(e).backgroundImage,
      dot: e.querySelector('i') ? getComputedStyle(e.querySelector('i')).backgroundColor : '' })));
    const filled = acts.filter(a => a.img !== 'none');
    const watch = acts.find(a => /watch-live/.test(a.cls)) || {};
    check("on air the home page has one lit button, the app's: the way to the broadcasts is plain metal with the red light",
      filled.length === 1 && /\bbutton\b/.test(filled[0].cls) && /\bon\b/.test(watch.cls || '') && watch.img === 'none' && watch.dot === 'rgb(255, 49, 72)',
      JSON.stringify(acts));
    await lit.close();
    // The home page's cards of who is on air: a picture of each broadcast, taken from a whole piece of its stream
    // (thumbs.js), only of the cards on the screen and then not again for minutes (it was every half minute). On a short
    // phone screen the cards start below it (the stage above them is 420 px at least, style.css .stage-in): nothing of the
    // streams is asked for until they are scrolled to.
    const home = await contexts.signed.newPage();
    await home.setViewport({ width: 360, height: 400, isMobile: true, hasTouch: true });
    const pieces = [];
    home.on('request', r => { if (/\/live-media\.php\/\d+\//.test(r.url())) pieces.push(r.url().split('?')[0]); });
    await home.goto(`${P}/`, { waitUntil: 'domcontentloaded' });
    await home.bringToFront();
    await pause(8000);
    const below = await home.$eval('#live', e => !e.hidden && e.getBoundingClientRect().top > innerHeight).catch(() => false);
    const unseen = pieces.length;
    await home.$eval('#live', e => e.scrollIntoView({ block: 'center' }));
    const pictured = await home.waitForFunction(() => {
      const cards = [...document.querySelectorAll('#live .thumb')];
      return cards.length >= 2 && cards.every(a => a.querySelector('.thumb-pic img'));
    }, { timeout: 40000 }).then(() => true, () => false);
    const taken = pieces.length;
    // Longer than the half minute pictures were taken again after.
    await pause(35000);
    check('the home page takes pictures of the broadcasts on the screen only, and not again for minutes',
      below && unseen === 0 && pictured && taken > 0 && pieces.length === taken, `${below} ${unseen} ${pictured} ${taken} ${pieces.length}`);
    await home.close();
    // With LIVE's count in the menu, as wide as the site's bar gets.
    await barsSideways(contexts);
    await sweep(contexts, AIR, FEW_WIDTHS);
  } else if (stage === 'maint') {
    // On, by the owner's own form; a long message, so that it has to wrap.
    const page = await contexts.signed.newPage();
    await page.goto(`${A}/maintenance`, { waitUntil: 'domcontentloaded' });
    await page.$eval('textarea', e => { e.value = 'Back at 21:00. Moving the server to a bigger disk, with a longer notice than usual so that it has to wrap over several lines on a phone.'; });
    await pressAndConfirm(page, 'button[name=action][value=on]');
    await page.goto(`${P}/`, { waitUntil: 'domcontentloaded' });
    check('the public site shows the notice', /Back at 21:00/.test(await textOf(page, '.site-alert')));
    await sweep(contexts, MAINT, FEW_WIDTHS);
    await page.goto(`${A}/maintenance`, { waitUntil: 'domcontentloaded' });
    await press(page, 'button[name=action][value=off]');
    await page.goto(`${P}/`, { waitUntil: 'domcontentloaded' });
    check('and goes when it is turned off', (await page.$('.site-alert')) === null);
    await page.close();
  } else if (stage === 'down') {
    const page = await contexts.signed.newPage();
    await page.goto(`${A}/`, { waitUntil: 'domcontentloaded' });
    check('the status page says the game server is not answering', /\S/.test(await textOf(page, '.site-alert')));
    // Its stylesheet is the copy it kept while the server was there, not the plain one for a server never seen.
    check('and keeps the look it had', await page.$eval('head', () => getComputedStyle(document.querySelector('.card, .stat')).clipPath !== 'none'));
    await page.close();
    await sweep(contexts, DOWN, FEW_WIDTHS);
  } else if (stage === 'flows') {
    await floatingLayers(contexts);
    await signInForms(contexts);
    await portalFlows(contexts);
    await replayFlows(contexts);
    // Before the admin flows: their song hidden and shown again rebuilds the catalog from the stand-in game files, which
    // have none of the items run.sh's stand-in catalog gives a player's page.
    await gameFlows(contexts);
    await adminFlows(contexts);
    await rowMore(contexts);
    await serverForms(contexts);
    await setupFound(contexts);
    await webhookFlows(contexts);
    await repairSaid(contexts);
  } else if (stage === 'mine') {
    await myPage(contexts);
  } else if (stage === 'patterns') {
    await textLinks(contexts);
    await hoverOnly(contexts);
    await inPlace(contexts);
    await formsLook(contexts);
  } else if (stage === 'notice') {
    await ownersNotice(contexts);
  } else if (stage === 'notices') {
    // PAGE-55..57: the home page and the live page left open (both look at the server by themselves) while the owner
    // begins maintenance, gives it a new message, ends it, and begins and ends it again: each time the bar's word and the
    // sentence under the bar come, change or go, without the page being opened anew. Before: they stayed as drawn.
    const owner = await contexts.signed.newPage();
    const open = [];
    for (const url of [`${P}/`, `${P}/live.php`]) open.push(await openAlone(contexts, url));
    check('the pages left open are in sight, as a page someone looks at', (await Promise.all(open.map(p => p.evaluate(() => document.visibilityState)))).every(v => v === 'visible'));
    const maintenance = async (action, message) => {
      await owner.goto(`${A}/maintenance`, { waitUntil: 'domcontentloaded' });
      if (message !== undefined) await owner.$eval('textarea', (e, m) => { e.value = m; }, message);
      // Beginning it asks first; a new message and the end do not.
      if (await owner.$(`button[name=action][value=${action}][data-ask]`)) await pressAndConfirm(owner, `button[name=action][value=${action}]`);
      else await press(owner, `button[name=action][value=${action}]`);
    };
    // The word and the sentence as maintenance shows them, with these words in the sentence; or neither.
    const saying = words => {
      const said = document.querySelector('body > .site-alert.maint'), word = document.querySelector('.bar-end > .state.maint');
      return words === null ? !said && !word : !!said && !!word && said.textContent.includes(words);
    };
    const all = async (words, name, shot) => {
      const came = [];
      for (const page of open) came.push(await until(page, saying, words) && await keptOpen(page));
      check(name, came.every(Boolean), came.join(' '));
      // What came by itself, at a phone's width and a laptop's: the same as a page opened then.
      if (shot) await shots(open, ['home', 'live'], `notices-${shot}`);
    };
    for (const round of [1, 2]) {
      await maintenance('on', round === 1 ? 'Back at nine.' : '');
      await all(round === 1 ? 'Back at nine.' : '', `round ${round}: maintenance begun, the home page and the live page left open say so by themselves`,
        round === 1 ? 'maint-begun' : '');
      if (round === 1) {
        await maintenance('on', 'Back at ten.');
        await all('Back at ten.', 'a new message: the pages left open say the new words');
      }
      await maintenance('off');
      await all(null, `round ${round}: maintenance ended, the word and the sentence go by themselves`);
    }
    // PAGE-57 too: broadcasts off for the server and on again, twice, with the same pages left open.
    // Off, they open anew without anything of broadcasts (as before); on again, they open anew with them, by themselves.
    // Before: off came by itself, on did not (the pages waited to be opened again).
    const broadcasts = async on => {
      await owner.goto(`${A}/recordings`, { waitUntil: 'domcontentloaded' });
      const button = `#broadcasts button[value=${on ? 'broadcasts-on' : 'broadcasts-off'}]`;
      if (await owner.$(`${button}[data-ask]`)) await pressAndConfirm(owner, button);
      else await press(owner, button);
    };
    // LIVE in the menu and, on the live page, the live page itself (not the page that says broadcasts are off); or neither.
    const live = on => {
      const menu = !!document.querySelector('.nav a[href="/opendmtq/live.php"]');
      const offPage = !!document.querySelector('.live-off');
      return on ? menu && !offPage : !menu;
    };
    for (const round of [1, 2]) {
      await broadcasts(false);
      const went = [];
      for (const page of open) went.push(await until(page, live, false));
      check(`round ${round}: broadcasts off, the pages left open lose LIVE by themselves`, went.every(Boolean), went.join(' '));
      await broadcasts(true);
      const came = [];
      for (const page of open) came.push(await until(page, live, true));
      check(`round ${round}: broadcasts on again, the pages left open bring LIVE back by themselves`, came.every(Boolean), came.join(' '));
    }
    for (const page of open) await page.browserContext().close();
    await owner.close();
  } else if (stage === 'away') {
    // ADM-117, ADM-118: the Players page and the status page left open while the game server stops and starts again, twice
    // (run.sh stops and starts it when this says it is ready): each time the bar's OFFLINE and the sentence above the page
    // come and go by themselves. Before: they stayed as each page was first drawn.
    const flag = name => fs.writeFileSync(path.join(OUT, name), '');
    const sign = async name => {
      const end = Date.now() + 240000;
      while (Date.now() < end) {
        if (fs.existsSync(path.join(OUT, name))) return true;
        await pause(500);
      }
      return false;
    };
    const open = [];
    for (const url of [`${A}/players`, `${A}/`]) open.push(await openAlone(contexts, url));
    const down = () => !!document.querySelector('.bar-end > .state.down') && !!document.querySelector('#server-alert > .site-alert.down');
    const up = () => !document.querySelector('.bar-end > .state') && !document.querySelector('#server-alert > .site-alert');
    for (const round of [1, 2]) {
      flag(`away-ready-${round}`);
      const stopped = await sign(`away-down-${round}`);
      const gone = [];
      for (const page of open) gone.push(stopped && await until(page, down) && await keptOpen(page));
      check(`round ${round}: the game server stopped, the pages left open say so by themselves`, gone.every(Boolean), gone.join(' '));
      if (round === 1) await shots(open, ['players', 'status'], 'away-down');
      flag(`away-seen-down-${round}`);
      const started = await sign(`away-up-${round}`);
      const back = [];
      for (const page of open) back.push(started && await until(page, up) && await keptOpen(page));
      check(`round ${round}: the game server back, the word and the sentence go by themselves`, back.every(Boolean), back.join(' '));
      flag(`away-seen-up-${round}`);
    }
    for (const page of open) await page.browserContext().close();
  } else if (stage === 'quiet') {
    await broadcastsOff(contexts, true);
    await sweep(contexts, QUIET, ALL_WIDTHS);
  } else {
    throw new Error(`no stage ${stage}`);
  }
  await contexts.browser.close();
  process.exit(failed ? 1 : 0);
})().catch(e => {
  console.error(`FAIL ${stage}: the test itself stopped | ${String(e.stack || e).slice(0, 600)}`);
  process.exit(1);
});
