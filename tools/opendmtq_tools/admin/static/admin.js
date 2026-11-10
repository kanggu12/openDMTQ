// Small helps on every admin page: the charts' tooltips, copy buttons, tables sorted by a click on a heading.

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

// A job a page started (the app's build, the setup's import), followed in its log box until it ends. The box says where to
// ask (data-job), where to go once the job is done (data-done), and where once this service no longer knows it
// (data-gone: it started again). A look that fails, on the network or in a reply that does not read, is tried again 3
// seconds later: one blip, or this service starting again, must not leave the log frozen and the buttons waiting.
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
      // Done: the page again, which now says what came of it.
      if (j.state === 'done') { setTimeout(() => location.replace(log.dataset.done), 800); return; }
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
