// The admin pages' script: one file that every page loads (defer, after the page is read) and the browser keeps. First what
// every page does (the bar, its forms, upload boxes, tooltips, copy buttons, lists that sort), then what one page does,
// each part only where its page has what it works on, and last the way back to where a form was sent from. The page's
// words come from the page itself, in its language (data-* attributes).

// The bar's shadow once the page has moved under it.
(() => {
  const bar = document.querySelector('.bar');
  const under = () => bar.classList.toggle('under', scrollY > 2);
  addEventListener('scroll', under, { passive: true });
  // Also at once: a page shown again may come back scrolled.
  under();
})();

// A form the page checks itself (novalidate): what is wrong is said in the page's own look and language, not in the
// browser's bubble in the browser's. A field with a rule carries the words for it (data-bad): the server's own for the same
// check, which the server still makes. The first field that breaks its rule is said just above its form and gets the
// focus, and nothing is sent. In the capture phase: before the question of what cannot be undone and the busy button.
document.addEventListener('submit', e => {
  const form = e.target;
  if (!form.noValidate) return;
  // The first field that breaks its rule: empty, too short, not the pattern, out of range, a date typed in part.
  const wrong = [...form.elements].find(f => f.willValidate && !f.validity.valid);
  if (!wrong) return;
  e.preventDefault();
  // Nothing else hears of this press: no question opens, no button says it is busy.
  e.stopPropagation();
  // One message per form, said again for the next field. On the sign-in, in place of the server's last one.
  let says = form.previousElementSibling;
  if (!says || !says.matches('.form-says, .signin .error, .signin .done')) {
    says = document.createElement('p');
    form.before(says);
  }
  // The sign-in box's own error look, as its server message has; the message look of the other pages.
  says.className = form.closest('.signin') ? 'form-says error' : 'form-says flash bad';
  says.setAttribute('role', 'alert');
  // The rule's words; the browser's own only for a field that has none.
  says.textContent = wrong.dataset.bad || wrong.validationMessage;
  // The field itself, marked and in reach of the keyboard.
  wrong.setAttribute('aria-invalid', 'true');
  wrong.focus();
}, true);
// A field put right: its mark and its form's message go.
document.addEventListener('input', e => {
  const field = e.target;
  if (!field.form || field.getAttribute('aria-invalid') !== 'true' || !field.validity.valid) return;
  field.removeAttribute('aria-invalid');
  const says = field.form.previousElementSibling;
  if (says && says.classList.contains('form-says')) says.remove();
});

// Upload boxes: name the chosen or dropped file, refuse one over the size limit, and enable the form's button only when
// there is something to send. The box says its limit (data-max) and its words for a file that is too big (data-too-big,
// with {size} and {max}) and for its button once a file is there (data-change).
for (const box of document.querySelectorAll('.drop')) {
  const input = box.querySelector('input[type=file]');
  const title = box.querySelector('.drop-title'), hint = box.querySelector('.drop-hint');
  // The box's own texts, markup included (the hint's drop-only part hides on touch screens).
  const blank = [title.innerHTML, hint.innerHTML];
  // The visible "Choose file" button: "Change" once a file is there.
  const pick = box.querySelector('.drop-pick'), pickLabel = pick ? pick.textContent : '';
  const button = box.closest('form').querySelector('button');
  const max = Number(box.dataset.max) || Infinity;
  const size = n => n < 1048576 ? Math.max(1, Math.round(n / 1024)) + ' KB'
    : n < 1073741824 ? (n / 1048576).toFixed(1).replace(/\.0$/, '') + ' MB' : (n / 1073741824).toFixed(1).replace(/\.0$/, '') + ' GB';
  const show = () => {
    const f = input.files[0];
    const tooBig = !!f && f.size > max;
    box.classList.toggle('has-file', !!f && !tooBig);
    box.classList.toggle('too-big', tooBig);
    button.disabled = !f || tooBig;
    // A file's name and size go in as text; only the box's own markup is put back as HTML.
    if (f) {
      title.textContent = f.name;
      hint.textContent = tooBig ? box.dataset.tooBig.replace('{size}', size(f.size)).replace('{max}', size(max)) : size(f.size);
    } else {
      title.innerHTML = blank[0];
      hint.innerHTML = blank[1];
    }
    if (pick) pick.textContent = f ? box.dataset.change : pickLabel;
  };
  input.addEventListener('change', show);
  box.addEventListener('dragover', e => { e.preventDefault(); box.classList.add('over'); });
  box.addEventListener('dragleave', () => box.classList.remove('over'));
  box.addEventListener('drop', e => {
    e.preventDefault();
    box.classList.remove('over');
    if (e.dataTransfer.files.length) { input.files = e.dataTransfer.files; show(); }
  });
  // Also right after a reload, when the browser may have kept the file. At once: the button's colours ease from one
  // state to the other, and it would show in the main colour first and fade to grey on every load.
  button.style.transition = 'none';
  show();
  // (Reading its size makes the browser lay it out as it now is, before the easing comes back.)
  void button.offsetWidth;
  button.style.transition = '';
}

// What cannot be undone asks first, in the site's own look: data-ask on the button or its form says what is lost, data-yes
// names the button that goes ahead. A form that was asked about comes back through here with its answer.
document.addEventListener('submit', e => {
  const form = e.target, button = e.submitter, ask = document.getElementById('ask');
  if (form.method === 'dialog') return;
  const question = (button && button.dataset.ask) || form.dataset.ask;
  if (!question || form.dataset.answered) { delete form.dataset.answered; return; }
  e.preventDefault();
  ask.querySelector('p').textContent = question.replace('{n}', form.querySelectorAll('input[name=sel]:checked').length);
  const yes = ask.querySelector('[value=yes]');
  yes.textContent = (button && button.dataset.yes) || form.dataset.yes || yes.dataset.word;
  ask.returnValue = '';
  ask.onclose = () => {
    if (ask.returnValue !== 'yes') return;
    form.dataset.answered = '1';
    form.requestSubmit(button || undefined);
  };
  ask.showModal();
});

// Forms: a button that was pressed shows that it is working (a backup or an upload takes a while; its data-busy says what
// is happening), and a second press sends nothing.
document.addEventListener('submit', e => {
  const form = e.target, button = e.submitter;
  if (e.defaultPrevented || form.method === 'dialog') return;
  if (form.dataset.sent) { e.preventDefault(); return; }
  form.dataset.sent = '1';
  if (button) {
    button.setAttribute('aria-busy', 'true');
    if (button.dataset.busy) button.textContent = button.dataset.busy;
  }
  // After a change the page comes back as it was: same place in the list, same search (the end of this file).
  if (form.method === 'post') {
    const search = document.querySelector('input[type=search]');
    sessionStorage.setItem('odq-back', JSON.stringify({ path: location.pathname, y: scrollY, q: search ? search.value : '' }));
  }
});
// Back to a page whose form was sent: it may be shown again as it was, and works again.
addEventListener('pageshow', e => {
  if (!e.persisted) return;
  for (const f of document.forms) delete f.dataset.sent;
  for (const b of document.querySelectorAll('[aria-busy]')) b.removeAttribute('aria-busy');
});

// One tooltip for every mark with data-tip, under the pointer or the finger, and on keyboard focus. Its words go in as text.
(() => {
  const box = document.createElement('div');
  box.className = 'chart-tip';
  box.hidden = true;
  document.body.append(box);
  const place = (x, y) => {
    const w = box.offsetWidth, h = box.offsetHeight;
    box.style.left = `${Math.min(innerWidth - w - 8, Math.max(8, x - w / 2))}px`;
    box.style.top = `${y - h - 12 < 4 ? y + 18 : y - h - 12}px`;
  };
  const show = (target, x, y) => {
    box.textContent = target.dataset.tip;
    box.hidden = false;
    place(x, y);
  };
  const answer = e => {
    const t = e.target.closest && e.target.closest('[data-tip]');
    if (t) show(t, e.clientX, e.clientY); else box.hidden = true;
  };
  document.addEventListener('pointermove', answer, { passive: true });
  // A finger only ever presses: the press does what moving over it does with a mouse, and leaves the words up to be read.
  document.addEventListener('pointerdown', answer, { passive: true });
  document.addEventListener('focusin', e => {
    const t = e.target.closest && e.target.closest('[data-tip]');
    if (!t) return;
    const r = t.getBoundingClientRect();
    show(t, r.left + r.width / 2, r.top);
  });
  document.addEventListener('focusout', () => { box.hidden = true; });
  addEventListener('scroll', () => { box.hidden = true; }, { passive: true });
})();

// A list of choices sent once (a <template> of its options) and put into every <select> that names it (data-choice): the
// Accounts page's players, which in every row made the page grow as accounts times players. Each keeps the choice it came
// with; one the list does not have reads as its first, none.
for (const select of document.querySelectorAll('select[data-choice]')) {
  const kept = select.value, list = document.getElementById(select.dataset.choice);
  if (!list) continue;
  select.replaceChildren(list.content.cloneNode(true));
  select.value = kept;
  if (select.selectedIndex < 0) select.selectedIndex = 0;
}

// A button with data-copy copies what the element it names holds. Over plain HTTP the browser only has the older way.
document.addEventListener('click', async e => {
  const b = e.target.closest && e.target.closest('[data-copy]');
  if (!b) return;
  const from = document.querySelector(b.dataset.copy);
  const text = 'value' in from ? from.value : from.textContent;
  let copied = true;
  try {
    await navigator.clipboard.writeText(text);
  } catch (_) {
    if (from.select) from.select();
    // The older way says whether it worked; where it did not, the text stays selected to copy by hand.
    try { copied = document.execCommand('copy'); } catch (_) { copied = false; }
  }
  const was = b.textContent;
  b.textContent = copied ? b.dataset.done : (b.dataset.fail || b.dataset.done);
  setTimeout(() => { b.textContent = was; }, 1600);
});

// A message in a box at its full height, while it is typed too: it wraps differently on every screen.
for (const box of document.querySelectorAll('textarea')) {
  const fit = () => { box.style.height = 'auto'; box.style.height = `${box.scrollHeight + 2}px`; };
  fit();
  box.addEventListener('input', fit);
  addEventListener('resize', fit);
}

// A job a page started (the app's build, the setup's import, a backup, a restore, a change to the songs), followed in its
// log box until it ends. The box says where to ask (data-job), where to go once the job is done (data-done) or has failed
// (data-failed, where the page itself says why), and where once this service no longer knows it (data-gone: it started
// again). A look that fails, on the network or in a reply that does not read, is tried again 3 seconds later: one blip,
// or this service starting again, must not leave the log frozen and the buttons waiting.
function followJob(log) {
  const look = async () => {
    try {
      // Asked as the page's own look: signed out meanwhile, the answer is a plain 401, not the sign-in page.
      const r = await fetch(log.dataset.job, { headers: { 'X-Requested-With': 'fetch' }, cache: 'no-store' });
      // Gone with a restart of this service: the page as it is now.
      if (r.status === 404) { location.replace(log.dataset.gone); return; }
      // Signed out meanwhile: the whole page finds out, with the sign-in's own words on why.
      if (r.status === 401) { location.reload(); return; }
      // A proxy's error while this service starts, say: the next look.
      if (!r.ok) { setTimeout(look, 3000); return; }
      const j = await r.json();
      // The job's last lines, the newest in sight.
      log.textContent = j.log.join('\n') || '…';
      log.scrollTop = log.scrollHeight;
      if (j.state === 'running') { setTimeout(look, 1000); return; }
      // Its end in the box's colour: done or failed.
      log.classList.add(j.state);
      // Done: the page again, which now says what came of it; failed too where the page says why itself (data-failed).
      const next = j.state === 'done' ? log.dataset.done : log.dataset.failed;
      if (next) { setTimeout(() => location.replace(next), 800); return; }
      // Failed: the log stays, and the buttons work again with their own words back (a build's said "Building…").
      for (const b of document.querySelectorAll('button[disabled][data-again]')) {
        b.disabled = false;
        if (b.dataset.label) b.textContent = b.dataset.label;
      }
      // Why, in the page's words, where the page has a place for it and the job's own lines say it.
      const failed = document.getElementById('job-failed');
      if (failed) {
        if (j.why) failed.textContent = j.why;
        failed.hidden = false;
      }
    } catch (_) {
      // No answer at all, or one that is not the job's: the next look.
      setTimeout(look, 3000);
    }
  };
  look();
}
for (const log of document.querySelectorAll('.log[data-job]')) followJob(log);

// Tables with headings that say data-sort: a click puts the rows in that column's order, a second reverses it.
for (const table of document.querySelectorAll('table.sortable')) {
  const heads = [...table.tHead.rows[0].cells], sortKey = `opendmtq.sort.${location.pathname}`;
  let kept = null;
  try { kept = JSON.parse(sessionStorage.getItem(sortKey)); } catch (_) { /* No storage here. */ }
  heads.forEach((th, col) => {
    if (!th.dataset.sort) return;
    th.tabIndex = 0;
    th.classList.add('can-sort');
    const go = () => {
      const down = th.getAttribute('aria-sort') !== 'descending';
      for (const other of heads) other.removeAttribute('aria-sort');
      th.setAttribute('aria-sort', down ? 'descending' : 'ascending');
      const body = table.tBodies[0];
      const value = r => (r.cells[col].dataset.v !== undefined ? r.cells[col].dataset.v : r.cells[col].textContent).trim();
      const rows = [...body.rows].sort((a, b) => {
        const order = th.dataset.sort === 'num' ? Number(value(a)) - Number(value(b)) : value(a).localeCompare(value(b));
        return down ? -order : order;
      });
      body.append(...rows);
      // Remembered for this tab: a form on the page brings it back as it was.
      try { sessionStorage.setItem(sortKey, JSON.stringify([col, down])); } catch (_) { /* No storage here. */ }
    };
    th.addEventListener('click', go);
    th.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
    // As it was left. A first press sorts downwards, so an upward order is two.
    if (kept && kept[0] === col) { go(); if (!kept[1]) go(); }
  });
}

// A list narrowed to a word as it is typed (the Players and Songs pages): the rows whose data-k has it, a count of those
// shown (the count's data-of says it, with {shown} and {all}; the number alone without), and the line that says none was
// found. The page's own search box names them: data-rows, data-count, data-none, and data-scroll for a box to hide too.
for (const search of document.querySelectorAll('input[type=search][data-rows]')) {
  search.addEventListener('input', () => {
    const q = search.value.trim().toLowerCase(), rows = document.querySelectorAll(search.dataset.rows);
    let shown = 0;
    for (const r of rows) {
      const hit = !q || r.dataset.k.includes(q);
      r.style.display = hit ? '' : 'none';
      shown += hit;
    }
    const count = document.querySelector(search.dataset.count);
    count.textContent = q ? (count.dataset.of || '{shown} / {all}').replace('{shown}', shown).replace('{all}', rows.length) : rows.length;
    document.querySelector(search.dataset.none).hidden = shown > 0;
    // No empty table under the message.
    if (search.dataset.scroll) document.querySelector(search.dataset.scroll).hidden = !shown;
  });
}

// The Players page's More: one open at a time, and it closes by a press anywhere else. Rename does nothing until the name
// has changed.
for (const more of document.querySelectorAll('.row-more')) {
  more.addEventListener('toggle', () => {
    if (!more.open) return;
    for (const other of document.querySelectorAll('.row-more[open]')) if (other !== more) other.open = false;
  });
  const field = more.querySelector('input[name=name]'), rename = more.querySelector('.rename button'), was = field.value;
  const check = () => { rename.disabled = field.value.trim() === was; };
  field.addEventListener('input', check);
  check();
}
if (document.querySelector('.row-more')) {
  document.addEventListener('pointerdown', e => {
    if (e.target.closest('.row-more') || document.getElementById('ask').open) return;
    for (const open of document.querySelectorAll('.row-more[open]')) open.open = false;
  });
}

// The Recordings page's delete of those ticked: the button says how many it would delete (data-n, with {n}; data-none
// before any), waits until there is at least one, and stays at the screen's foot once something is ticked.
(() => {
  const bulk = document.getElementById('rec-bulk');
  if (!bulk) return;
  const count = () => {
    const n = bulk.form.querySelectorAll('input[name=sel]:checked').length;
    bulk.disabled = n === 0;
    bulk.parentElement.classList.toggle('on', n > 0);
    bulk.textContent = n ? bulk.dataset.n.replace('{n}', n) : bulk.dataset.none;
  };
  bulk.form.addEventListener('change', count);
  count();
})();

// A recording to watch (the Recordings page, data-src): hls.js where it works; Safari plays HLS itself.
(() => {
  const video = document.getElementById('rec-video');
  if (!video) return;
  const url = video.dataset.src;
  // The box takes the recording's shape (admin.css has the usual phone stream's).
  video.addEventListener('resize', () => {
    if (video.videoWidth && video.videoHeight) video.style.setProperty('--ar', video.videoWidth / video.videoHeight);
  });
  if (window.Hls && Hls.isSupported()) {
    // Ten seconds fetched ahead, as on the portal: left alone hls.js fetches half a minute at once, right as the sound starts.
    const ahead = 10;
    // The sound is AAC-LC, as phones encode it. Unnamed, hls.js takes it for HE-AAC in Chrome and fills the gap where a
    // recording's sound starts after its picture with HE-AAC silence, which garbles all the sound after it (as on the portal).
    const hls = new Hls({ defaultAudioCodec: 'mp4a.40.2', maxBufferLength: ahead, maxMaxBufferLength: ahead * 2 });
    hls.loadSource(url);
    hls.attachMedia(video);
    // Watch was just clicked: straight on, if the browser lets it, once that stretch is in. If that takes a while, the
    // network paces the fetching: a few seconds in hand are enough then (or after a while what there is: a very short
    // recording). From where the media starts, which can be a little after 0: hls.js would stall there and seek over it.
    const clicked = performance.now();
    let started = false;
    const begin = () => {
      if (started) return;
      started = true;
      if (video.buffered.length && video.currentTime < video.buffered.start(0)) video.currentTime = video.buffered.start(0);
      video.play().catch(() => {});
    };
    setTimeout(begin, 6000);
    hls.on(Hls.Events.FRAG_BUFFERED, () => {
      if (!video.buffered.length) return;
      const left = video.buffered.end(video.buffered.length - 1) - video.currentTime;
      if (left >= 3 && (left >= ahead - 2 || performance.now() - clicked > 1500)) begin();
    });
  } else {
    video.src = url;
  }
})();

// The status page's tiles and resources look again by themselves: an owner may keep this page open on the side. A new
// point every five minutes in the resources' charts.
if (document.getElementById('tiles')) {
  setInterval(async () => {
    if (document.hidden) return;
    try {
      const page = new DOMParser().parseFromString(await (await fetch(location.href, { headers: { 'X-Requested-With': 'fetch' } })).text(), 'text/html');
      const fresh = page.getElementById('tiles');
      if (fresh) document.getElementById('tiles').replaceChildren(...fresh.children);
      const res = page.getElementById('resources');
      if (res) document.getElementById('resources').replaceChildren(...res.children);
    } catch (_) { /* The next look. */ }
  }, 30000);
}

// The Logs page's requests: new ones come in by themselves while Keep updating is ticked, and a tap on an address filters
// by it.
(() => {
  const box = document.getElementById('log-rows'), follow = document.getElementById('log-follow');
  if (!box || !follow) return;
  const url = () => { const u = new URL(location.href); u.searchParams.set('rows', '1'); return u; };
  try { follow.checked = !!localStorage.getItem('opendmtq.follow'); } catch (_) { /* No storage here. */ }
  follow.addEventListener('change', () => { try { localStorage.setItem('opendmtq.follow', follow.checked ? '1' : ''); } catch (_) { /* No storage here. */ } });
  // What the page has of the list, by its tag (ETag): asked with it, the answer is 304 and nothing until a request comes in.
  let have = box.dataset.have || '';
  setInterval(async () => {
    if (!follow.checked || document.hidden) return;
    try {
      const r = await fetch(url(), { headers: have ? { 'If-None-Match': have } : {} });
      // Nothing new.
      if (r.status === 304) return;
      // Signed out meanwhile, or the page failed: the whole page finds out, not a sign-in form in the middle of the list.
      if (r.redirected || !r.ok) { location.reload(); return; }
      box.innerHTML = await r.text();
      have = r.headers.get('ETag') || '';
    } catch (_) { /* The next look. */ }
  }, 4000);
  box.addEventListener('click', e => {
    const ip = e.target.dataset && e.target.dataset.filter;
    if (!ip) return;
    document.querySelector('#log-form [name=q]').value = ip;
    document.getElementById('log-form').submit();
  });
})();

// The Maintenance page: a ready-made message in the field, to change or send as it is.
for (const b of document.querySelectorAll('.presets button')) {
  b.addEventListener('click', () => { const f = document.querySelector('textarea[name=message]'); f.value = b.dataset.text; f.focus(); });
}

// The setup's first step. A typed path that named a file: that file in sight in the list.
(() => {
  const picked = document.getElementById('picked');
  if (picked) picked.scrollIntoView({ block: 'nearest' });
})();
// What each file is, two at a time: an archive's look takes 7-Zip a moment, and the page is usable meanwhile. Asked of the
// address its card names (data-what-at).
(() => {
  const queue = Array.from(document.querySelectorAll('[data-what]'));
  async function next() {
    const el = queue.shift();
    if (!el) return;
    try {
      const r = await fetch(el.closest('[data-what-at]').dataset.whatAt + '?path=' + encodeURIComponent(el.dataset.what));
      const j = await r.json();
      el.textContent = j.text;
      el.classList.add(j.ok ? 'ok' : 'bad');
      // A file of no use here: its own import button goes (the import would find nothing in it).
      const own = el.closest('li.file');
      if (!j.ok && own) for (const b of own.querySelectorAll('button')) b.disabled = true;
    } catch (e) {
      el.textContent = '';
    }
    next();
  }
  next();
  next();
})();

// A page that looks again by itself after a while (data-reload, in milliseconds): the setup's step while the server's own
// build at its start runs, which has no output to follow.
for (const el of document.querySelectorAll('[data-reload]')) setTimeout(() => location.reload(), Number(el.dataset.reload));

// A restart the setup asked for (a new address): which process answers is asked (data-ping) until it is a new one (not
// data-instance), then the page goes on (data-back), signed in by the one-time key it carries. After a minute it says that
// this takes longer than usual.
(() => {
  const wait = document.getElementById('restart-wait');
  if (!wait) return;
  const started = Date.now();
  (async function look() {
    try {
      const r = await fetch(wait.dataset.ping, { cache: 'no-store' });
      if (r.ok && (await r.json()).instance !== wait.dataset.instance) { location.replace(wait.dataset.back); return; }
    } catch (e) {
      // Not answering yet: it is starting.
    }
    if (Date.now() - started > 60000) document.getElementById('slow').hidden = false;
    setTimeout(look, 1500);
  })();
})();

// Back to a page whose form was sent (the busy button's part above kept where it was): the same search, the same place in
// the list. Last, once the lists above can narrow to a search.
(() => {
  const back = JSON.parse(sessionStorage.getItem('odq-back') || 'null');
  sessionStorage.removeItem('odq-back');
  if (!back || back.path !== location.pathname) return;
  const search = document.querySelector('input[type=search]');
  if (search && back.q) { search.value = back.q; search.dispatchEvent(new Event('input')); }
  scrollTo(0, back.y);
  // Further down the page, the message about what was done comes to the screen's foot: it would be out of sight at the
  // top. A good one leaves by itself.
  if (scrollY > 0) {
    for (const m of document.querySelectorAll('.flash')) {
      m.classList.add('float');
      // It lies over the page: a click takes it away, and it leaves by itself, a good one sooner.
      m.addEventListener('click', () => m.remove());
      setTimeout(() => m.remove(), m.classList.contains('ok') ? 5000 : 15000);
    }
  }
})();
