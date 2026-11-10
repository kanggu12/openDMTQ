/*
 * Cards for the players on air: a picture of each broadcast, how long it has run, who and what. The pictures are taken
 * here in the browser, from the stream itself: one segment of it, one player at a time, every few minutes at most, only
 * of the cards on the screen, and only for those allowed to watch. The server never opens what phones send, and needs no
 * video tools for this.
 */
(function () {
  'use strict';
  const HLS_JS = '/opendmtq/hls/hls-1.5.17.min.js';
  // How old a picture may get before the next one is taken. Each costs a whole segment of the stream (300 KB and more at
  // the standard quality): at the half minute it was, a home page left open with two players on air took 46 MB an hour.
  const PICTURE_AGE = 150000;
  // The newest picture of each player: { url, at }.
  const pictures = new Map();
  let taking = false;
  // The cards on the screen now (a card scrolled out of sight gets no new picture), and what the last round of pictures
  // was for, so that a card coming into sight gets its picture then instead of at the next look.
  const onScreen = new Set();
  let wanted = null;
  const sight = 'IntersectionObserver' in window ? new IntersectionObserver(entries => {
    for (const e of entries) {
      if (e.isIntersecting) onScreen.add(e.target); else onScreen.delete(e.target);
    }
    if (wanted && entries.some(e => e.isIntersecting)) takePictures(...wanted);
  }) : null;
  // Whether a card is on the screen: every card is, where the browser cannot tell.
  const seen = a => !sight || onScreen.has(a);
  // The stream answered that this visitor may not watch (signed out in another tab): no more asking.
  let denied = false;
  let hlsLoaded = null;

  function element(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  // m:ss, or h:mm:ss after an hour.
  function clock(seconds) {
    const s = Math.max(0, Math.floor(seconds));
    const mm = Math.floor(s / 60) % 60, ss = String(s % 60).padStart(2, '0');
    return s >= 3600 ? `${Math.floor(s / 3600)}:${String(mm).padStart(2, '0')}:${ss}` : `${mm}:${ss}`;
  }

  // When a broadcast began by this device's clock, whatever that clock says: the server sends how long ago (seconds; 0:
  // not known). 0 for a broadcast with no known start. Worked out once per broadcast, so that the whole seconds of each look
  // do not make the clock skip. A start a good while off is another broadcast of theirs.
  const began = new Map();
  function since(c) {
    if (!(c.age > 0)) return 0;
    const fresh = Date.now() / 1000 - c.age, known = began.get(c.id);
    if (known && Math.abs(known - fresh) < 10) return known;
    began.set(c.id, fresh);
    return fresh;
  }

  // The time a card or the player shows for a broadcast that began at `from` (from since()).
  function airTime(from) {
    return from ? clock(Date.now() / 1000 - from) : '';
  }

  // hls.js only when a picture is wanted: the home page without broadcasts never loads it. Asked for once.
  function loadHls() {
    if (window.Hls) return Promise.resolve();
    if (!hlsLoaded) {
      hlsLoaded = new Promise(done => {
        const s = document.createElement('script');
        s.src = HLS_JS;
        s.onload = s.onerror = () => done();
        document.head.append(s);
      });
    }
    return hlsLoaded;
  }

  // One picture of a player's stream as a data URL, or null.
  function grab(id) {
    return new Promise(resolve => {
      const url = `/opendmtq/live-media.php/${id}/index.m3u8`;
      const video = document.createElement('video');
      video.muted = true;
      video.playsInline = true;
      let hls = null, over = false, timer = 0;
      const finish = result => {
        if (over) return;
        over = true;
        clearTimeout(timer);
        if (hls) hls.destroy();
        video.removeAttribute('src');
        video.load();
        resolve(result);
      };
      timer = setTimeout(() => finish(null), 12000);
      // A moment after it starts, when there is a picture to draw.
      video.addEventListener('playing', () => setTimeout(() => {
        if (!video.videoWidth) return finish(null);
        const canvas = document.createElement('canvas');
        canvas.width = 480;
        canvas.height = Math.round(480 * video.videoHeight / video.videoWidth);
        try {
          canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
          finish(canvas.toDataURL('image/jpeg', 0.75));
        } catch (e) {
          finish(null);
        }
      }, 200), { once: true });
      if (window.Hls && Hls.isSupported()) {
        // As little as will do: one segment's worth, from as near now as it can.
        hls = new Hls({ liveSyncDurationCount: 1, maxBufferLength: 2, maxMaxBufferLength: 4, backBufferLength: 0 });
        hls.on(Hls.Events.ERROR, (_, d) => {
          if (d.response && d.response.code === 403) denied = true;
          if (d.fatal) finish(null);
        });
        hls.on(Hls.Events.MANIFEST_PARSED, () => video.play().catch(() => finish(null)));
        hls.loadSource(url);
        hls.attachMedia(video);
      } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
        video.src = url;
        video.play().catch(() => finish(null));
      } else {
        finish(null);
      }
    });
  }

  // The running time on a card.
  function setTime(a, c) {
    const from = since(c);
    let time = a.querySelector('.thumb-time');
    if (!from) {
      if (time) time.remove();
      return;
    }
    if (!time) {
      time = element('span', 'thumb-time');
      a.querySelector('.thumb-pic').append(time);
    }
    time.dataset.since = from;
    time.textContent = airTime(from);
  }

  // A new card. onclick, if given, chooses them on the page instead of following the link.
  function card(c, onclick) {
    const a = element('a', 'thumb');
    a.href = `/opendmtq/live.php?p=${c.id}`;
    a.dataset.id = c.id;
    const pic = element('span', 'thumb-pic');
    const known = pictures.get(c.id);
    if (known) {
      const img = element('img');
      img.alt = '';
      img.src = known.url;
      pic.append(img);
    }
    const pill = element('span', 'live-pill');
    pill.append(element('i'), 'LIVE');
    pic.append(pill);
    a.append(pic, element('b', 'thumb-who', c.name), element('span', 'thumb-what', c.doing));
    setTime(a, c);
    if (onclick) a.onclick = onclick;
    return a;
  }

  // The cards in root become these players. A card that stays is the same element, so a keyboard's focus and a press in
  // progress stay on it. A player no longer on the list loses their picture: the next broadcast is another one.
  function render(root, list, onclickFor) {
    const have = new Map([...root.querySelectorAll('.thumb')].map(a => [Number(a.dataset.id), a]));
    const shown = list.map(c => {
      const a = have.get(c.id);
      if (!a) return card(c, onclickFor && onclickFor(c));
      have.delete(c.id);
      a.querySelector('.thumb-who').textContent = c.name;
      a.querySelector('.thumb-what').textContent = c.doing;
      setTime(a, c);
      return a;
    });
    // Gone from the list: from the page, and from what is watched for the screen.
    for (const a of have.values()) {
      a.remove();
      onScreen.delete(a);
      if (sight) sight.unobserve(a);
    }
    shown.forEach((a, i) => { if (root.children[i] !== a) root.insertBefore(a, root.children[i] || null); });
    // Every card, the page's own first ones too, watched for whether it is on the screen (once each: again is nothing).
    if (sight) for (const a of shown) sight.observe(a);
    for (const id of pictures.keys()) if (!list.some(c => c.id === id)) pictures.delete(id);
  }

  // New pictures for those whose picture is old, one at a time, while the page is looked at and the card is on the screen.
  // Data savers get none.
  async function takePictures(cards, root) {
    // What to take pictures of when a card comes into sight: these cards, in this box.
    wanted = [cards, root];
    if (taking || denied || document.hidden || (navigator.connection && navigator.connection.saveData)) return;
    // Nothing on the screen wants a picture: hls.js is not even loaded for it.
    const due = c => {
      const a = root.querySelector(`.thumb[data-id="${c.id}"]`), known = pictures.get(c.id);
      return !!a && seen(a) && !(known && Date.now() - known.at < PICTURE_AGE);
    };
    if (!cards.some(due)) return;
    taking = true;
    try {
      await loadHls();
      if (!window.Hls && !document.createElement('video').canPlayType('application/vnd.apple.mpegurl')) return;
      for (const c of cards) {
        // Gone from the page while the ones before them were taken.
        const pic = () => root.querySelector(`.thumb[data-id="${c.id}"] .thumb-pic`);
        const known = pictures.get(c.id);
        // Gone, out of sight, or with a picture young enough.
        if (denied || !pic() || !due(c)) continue;
        const url = await grab(c.id);
        // One that failed waits its turn like one that worked, not until the next look a few seconds on.
        pictures.set(c.id, { url: url || (known && known.url), at: Date.now() });
        if (!url || !pic()) continue;
        let img = pic().querySelector('img');
        if (!img) {
          img = element('img');
          img.alt = '';
          pic().prepend(img);
        }
        img.src = url;
      }
    } finally {
      taking = false;
    }
  }

  // The count of who is on air on the menu's LIVE, in both menus (the bar's, and the one at the thumb on phones), as the
  // server drew it when the page loaded, kept up to date.
  function headerCount(n, words) {
    const says = n ? words.count.replace('{n}', n) : words.nav;
    for (const head of document.querySelectorAll('.nav a[href="/opendmtq/live.php"], .tabbar a[href="/opendmtq/live.php"]')) {
      let mark = head.querySelector('.onair');
      if (n && !mark) {
        mark = element('span', 'onair');
        head.append(' ', mark);
      } else if (!n && mark) {
        mark.remove();
      }
      if (n) {
        mark.textContent = n;
        mark.title = says;
      }
    }
  }

  // The running times on the cards, every second.
  setInterval(() => {
    for (const t of document.querySelectorAll('.thumb-time')) t.textContent = airTime(Number(t.dataset.since));
  }, 1000);

  // The home page: the cards of who is on air show while someone is, at the head of the box of broadcasts, and follow who
  // that is; the heading's dot is lit meanwhile.
  function home(cards, signedIn, words) {
    const section = document.getElementById('live'), root = section, dot = document.getElementById('on-air-dot');
    // Under them: the newest recordings, or, before there are any, what shows while nobody is on air (only then).
    const past = document.getElementById('replays');
    // The stage's way to the live page: lit, with the count, while someone is on air.
    const watch = document.getElementById('watch-live'), count = document.getElementById('watch-count');
    // What is read further down stays where it is when the section comes or goes above it: done here, with the browser's own
    // way of doing that off, since it does not always step in and the two together would go twice as far.
    document.documentElement.style.overflowAnchor = 'none';
    const draw = list => {
      // The next thing on the page with a place on the screen (a script next to the section has none).
      let below = section.nextElementSibling;
      while (below && !below.getClientRects().length) below = below.nextElementSibling;
      const before = below ? below.getBoundingClientRect().top : 0;
      section.hidden = list.length === 0;
      if (dot) dot.hidden = list.length === 0;
      if (past && past.dataset.offAirOnly === '1') past.hidden = list.length > 0;
      if (watch) {
        watch.classList.toggle('on', list.length > 0);
        // With nobody on air and no recordings there is nothing to watch: the box under it says so instead.
        watch.hidden = list.length === 0 && watch.dataset.past !== '1';
      }
      if (count) {
        count.hidden = list.length === 0;
        count.textContent = list.length;
      }
      render(root, list);
      if (below && window.scrollY > 0) window.scrollBy(0, below.getBoundingClientRect().top - before);
      headerCount(list.length, words);
      if (signedIn && list.length) takePictures(list, root);
    };
    draw(cards);
    setInterval(() => {
      if (document.hidden) return;
      fetch('/opendmtq/?live=1').then(r => {
        // Broadcasts turned off for the server meanwhile: the page again, without anything of them (as the live page does).
        if (r.ok && r.headers.get('X-Live') === 'off') {
          location.reload();
          return Promise.reject();
        }
        return r.ok ? r.json() : Promise.reject();
      }).then(draw).catch(() => {});
    }, 15000);
  }

  window.liveThumbs = { home, render, takePictures, headerCount, airTime, since };
})();
