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
// check, which the server still makes. The first field that breaks its rule is said right under it and gets the focus, and
// nothing is sent. In the capture phase: before the question of what cannot be undone and the busy button.
//
// Right under it: in a form of fields one under the other (the sign-in, a phone's narrow forms), inside the field under its
// box; in a form of fields side by side, on a line of its own right under that field's row, across the form, so that the
// fields of the row stay in line. A field that is not in a labelled box of its own is said just above its form.
document.addEventListener('submit', e => {
  const form = e.target;
  // A button that needs none of the fields (formnovalidate: taking a notice down) sends the form unchecked.
  if (!form.noValidate || (e.submitter && e.submitter.formNoValidate)) return;
  // A field that must say what another says (a password typed again, data-same names the other): different, it breaks its
  // rule, with its own words for that (data-same-bad).
  for (const f of form.querySelectorAll('[data-same]')) {
    const other = form.elements[f.dataset.same];
    f.setCustomValidity(other && f.value !== other.value ? f.dataset.sameBad : '');
  }
  // The first field that breaks its rule: empty, too short, not the pattern, out of range, a date typed in part.
  const wrong = [...form.elements].find(f => f.willValidate && !f.validity.valid);
  if (!wrong) return;
  e.preventDefault();
  // Nothing else hears of this press: no question opens, no button says it is busy.
  e.stopPropagation();
  for (const f of form.querySelectorAll('[aria-invalid]')) unmark(f);
  // The field's own box: its labelled field, or the drop box a file field is in.
  const holder = wrong.closest('.field, .drop');
  let says;
  if (holder && form.contains(holder)) {
    says = document.createElement('span');
    says.className = 'field-error';
    says.id = `${wrong.id || wrong.name}-error`;
    const look = getComputedStyle(form);
    const columns = look.display.includes('grid') ? look.gridTemplateColumns.split(' ').length : 1;
    const row = look.display.includes('flex') && !look.flexDirection.startsWith('column');
    if (columns > 1) {
      // Fields side by side in a grid: a line across the form, placed right after the field's row (dense).
      says.classList.add('field-error-row');
      form.classList.add('says-in-grid');
      holder.after(says);
    } else if (row) {
      // Fields side by side in a row that wraps: a line of its own right after the field's line (the last of the form's
      // parts that stand on it, whose feet are in line with the field's), so a row wrapped on a phone keeps it under the field.
      says.classList.add('field-error-row');
      form.classList.add('says-in-row');
      const foot = holder.getBoundingClientRect().bottom;
      let last = holder;
      for (const part of [...form.children].filter(c => c.getClientRects().length && (holder.compareDocumentPosition(c) & Node.DOCUMENT_POSITION_FOLLOWING))) {
        if (Math.abs(part.getBoundingClientRect().bottom - foot) < 2) last = part;
      }
      last.after(says);
    } else if (holder.matches('.field')) {
      // One under the other: in the field, under its box.
      holder.append(says);
    } else {
      // A drop box: right under it.
      holder.after(says);
    }
    // The server's last word (a wrong password, a refusal) was about the last try.
    const last = form.previousElementSibling;
    if (last && last.matches('.signin .error, .signin .done, .form-says')) last.remove();
  } else {
    says = form.previousElementSibling;
    if (!says || !says.matches('.form-says, .signin .error, .signin .done')) {
      says = document.createElement('p');
      form.before(says);
    }
    // The sign-in box's own error look, as its server message has; the message look of the other pages.
    says.className = form.closest('.signin') ? 'form-says error' : 'form-says flash bad';
    says.id = says.id || `${wrong.id || wrong.name}-error`;
  }
  says.setAttribute('role', 'alert');
  // The rule's words; the browser's own only for a field that has none.
  says.textContent = (wrong.validity.customError && wrong.validationMessage) || wrong.dataset.bad || wrong.validationMessage;
  // The field itself, marked, named by its words, and in reach of the keyboard.
  wrong.setAttribute('aria-invalid', 'true');
  wrong.setAttribute('aria-describedby', says.id);
  wrong.focus();
}, true);
// A field's mark gone, and its own words with it (wherever they were put: the field names them).
function unmark(field) {
  field.removeAttribute('aria-invalid');
  const id = field.getAttribute('aria-describedby');
  const line = id && document.getElementById(id);
  if (line && line.matches('.field-error')) {
    line.remove();
    field.removeAttribute('aria-describedby');
  }
  if (field.form && !field.form.querySelector('.field-error-row')) field.form.classList.remove('says-in-grid', 'says-in-row');
}
// A field put right: its mark and its form's message go.
document.addEventListener('input', e => {
  const field = e.target;
  // A typed-again password is checked against the other again at the next press, not while it is typed.
  if (field.form) for (const f of field.form.querySelectorAll('[data-same]')) if (f === field || f.dataset.same === field.name) f.setCustomValidity('');
  if (!field.form || field.getAttribute('aria-invalid') !== 'true' || !field.validity.valid) return;
  unmark(field);
  const says = field.form.previousElementSibling;
  if (says && says.classList.contains('form-says')) says.remove();
});
// A file chosen in a drop box puts its field right too.
document.addEventListener('change', e => {
  const field = e.target;
  if (field.matches && field.matches('input[type=file]') && field.getAttribute('aria-invalid') === 'true' && field.validity.valid) unmark(field);
});

// A password field's Show (.pw-toggle, inside the field): the password as typed, until pressed again. The field keeps the
// focus and its cursor, so typing goes on; a form that goes takes the password hidden again. The button's words and its
// name for screen readers come from the page (data-show, data-hide, data-show-label, data-hide-label).
for (const toggle of document.querySelectorAll('.pw-toggle')) {
  const field = document.getElementById(toggle.getAttribute('aria-controls'));
  if (!field) continue;
  toggle.hidden = false;
  const set = shown => {
    field.type = shown ? 'text' : 'password';
    toggle.classList.toggle('on', shown);
    toggle.textContent = shown ? toggle.dataset.hide : toggle.dataset.show;
    toggle.setAttribute('aria-label', shown ? toggle.dataset.hideLabel : toggle.dataset.showLabel);
  };
  // A press with the mouse leaves the focus in the field.
  toggle.addEventListener('mousedown', e => e.preventDefault());
  toggle.addEventListener('click', () => {
    const at = [field.selectionStart, field.selectionEnd];
    set(field.type === 'password');
    if (document.activeElement !== toggle) {
      field.focus();
      try { field.setSelectionRange(at[0], at[1]); } catch (_) { /* a field that keeps no cursor */ }
    }
  });
  if (field.form) field.form.addEventListener('submit', e => { if (!e.defaultPrevented) set(false); });
}

// The ID last used to sign in on this browser, back in a sign-in form marked data-remember: the focus then on the password.
// Browser storage may be off (a private window): then nothing is kept and nothing breaks.
for (const form of document.querySelectorAll('form[data-remember]')) {
  const key = `opendmtq.id.${form.dataset.remember}`;
  const id = form.querySelector('input[autocomplete=username]'), password = form.querySelector('input[type=password]');
  if (!id) continue;
  let kept = '';
  try { kept = localStorage.getItem(key) || ''; } catch (_) { /* storage off */ }
  if (!id.value && kept) id.value = kept;
  // The first field left to fill takes the focus, not where a finger is the pointer (a phone's keyboard would cover the
  // page), and not over the field the server's answer chose (autofocus).
  if (!matchMedia('(pointer: coarse)').matches && !form.querySelector('[autofocus]')) (id.value && password ? password : id).focus();
  form.addEventListener('submit', e => {
    if (e.defaultPrevented || !id.value.trim()) return;
    try { localStorage.setItem(key, id.value.trim()); } catch (_) { /* storage off */ }
  });
}

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
// What deletes for good asks for a word to be typed as well (data-type on the button, data-type-label its label): the
// button that goes ahead waits for it, Enter in the field goes ahead once it is right, and the word goes with the form
// (its confirm field), which the server checks again. A button with data-need asks only once a box of that name is
// ticked; without one, its form says so (data-need-words) and nothing opens.
document.addEventListener('submit', e => {
  const form = e.target, button = e.submitter, ask = document.getElementById('ask');
  if (form.method === 'dialog') return;
  const question = (button && button.dataset.ask) || form.dataset.ask;
  if (!question || form.dataset.answered) { delete form.dataset.answered; return; }
  e.preventDefault();
  const need = button && button.dataset.need;
  if (need && !form.querySelector(`input[name="${need}"]:checked`)) {
    // Said beside the button that was pressed, where the eyes are; the first box takes the keyboard, the page stays.
    formSays(form, button.dataset.needWords || '', button.closest('.btn-line'));
    form.querySelector(`input[name="${need}"]`)?.focus({ preventScroll: true });
    return;
  }
  ask.querySelector('p').textContent = question.replace('{n}', form.querySelectorAll('input[name=sel]:checked').length);
  const yes = ask.querySelector('[value=yes]');
  yes.textContent = (button && button.dataset.yes) || form.dataset.yes || yes.dataset.word;
  // The word to type, when there is one; otherwise the field stays hidden and the button ready.
  const word = (button && button.dataset.type) || '';
  const typed = ask.querySelector('.ask-type'), field = typed.querySelector('input');
  typed.hidden = !word;
  field.value = '';
  yes.disabled = Boolean(word);
  if (word) {
    // The label's words with the word to type in them, that word set apart ({word} in data-type-label).
    const [before, after] = (button.dataset.typeLabel || '{word}').split('{word}');
    const label = typed.querySelector('span'), strong = document.createElement('b');
    strong.textContent = word;
    label.replaceChildren(before || '', strong, after || '');
    field.oninput = () => { yes.disabled = field.value.trim().toLowerCase() !== word.toLowerCase(); };
    field.onkeydown = ev => {
      if (ev.key !== 'Enter') return;
      // Not the dialog form's own Enter, whose first button is Cancel.
      ev.preventDefault();
      if (!yes.disabled) ask.close('yes');
    };
  }
  ask.returnValue = '';
  ask.onclose = () => {
    if (ask.returnValue !== 'yes') return;
    if (word) {
      const confirm = form.querySelector('input[name=confirm]');
      if (confirm) confirm.value = field.value.trim();
    }
    form.dataset.answered = '1';
    form.requestSubmit(button || undefined);
  };
  ask.showModal();
  // The field first, where there is one: the keyboard types the word at once.
  if (word) field.focus();
});

// A message said in the page's look (as the page's own checks say theirs), one per form: just above the form, or above
// the part of it given (the line of the button that was pressed).
function formSays(form, words, at) {
  const place = at || form;
  let says = place.previousElementSibling;
  if (!says || !says.matches('.form-says')) {
    says = document.createElement('p');
    place.before(says);
  }
  says.className = 'form-says flash bad';
  says.setAttribute('role', 'alert');
  says.textContent = words;
}
// A box ticked: the form's message about it goes.
document.addEventListener('change', e => {
  const box = e.target;
  if (box.type !== 'checkbox' || !box.form || !box.form.querySelector('input[type=checkbox]:checked')) return;
  for (const says of box.form.parentElement.querySelectorAll('.form-says')) {
    if (says.closest('form') === box.form || says.nextElementSibling === box.form) says.remove();
  }
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

// One tooltip for every mark with words of its own (data-tip), on every page: what a mark means, a day's plays, a level's
// records. Nothing is said only under a mouse pointer, where a finger and the keyboard never reach:
// - a mouse pointer over a mark shows its words until the pointer leaves it;
// - a finger's press shows them beside the mark, and a second press on it, a press anywhere else or Escape takes them away;
// - the keyboard's focus on a mark (each one can be reached with Tab) shows them until the focus moves on, or Escape.
// A mark that is itself a link or a button does what it does when pressed; its words show to the pointer and the focus.
// The box is the page's one, on top of everything and inside the window; its words go in as text, and a screen reader hears
// them as the mark's description while they show. The same as the site's tips.js, which these pages do not load.
(() => {
  const box = document.createElement('div');
  box.className = 'chart-tip';
  box.id = 'odq-tip';
  box.setAttribute('role', 'tooltip');
  box.hidden = true;
  document.body.append(box);
  // The mark whose words show, and whether a press or the focus holds them up (a pointer's leaving then does not end them).
  let shown = null;
  let held = false;
  // The mark an element belongs to, if any.
  const markOf = el => (el && el.closest ? el.closest('[data-tip]') : null);
  // Marks a press already does something with: their words are for the pointer and the focus only.
  const acts = mark => mark.matches('a, button, summary, input, select, textarea, label');
  // The words of a mark, over the point given (a mouse pointer), or else just over the mark, below it when there is no room
  // above; never past the window's edges.
  const show = (mark, x, y) => {
    if (shown && shown !== mark) shown.removeAttribute('aria-describedby');
    shown = mark;
    box.textContent = mark.dataset.tip;
    box.hidden = false;
    mark.setAttribute('aria-describedby', box.id);
    const w = box.offsetWidth, h = box.offsetHeight;
    let top;
    if (x === undefined) {
      const r = mark.getBoundingClientRect();
      x = r.left + r.width / 2;
      top = r.top - h - 8 >= 4 ? r.top - h - 8 : r.bottom + 8;
    } else {
      top = y - h - 12 >= 4 ? y - h - 12 : y + 18;
    }
    box.style.left = `${Math.min(innerWidth - w - 8, Math.max(8, x - w / 2))}px`;
    box.style.top = `${Math.min(innerHeight - h - 4, Math.max(4, top))}px`;
  };
  const hide = () => {
    box.hidden = true;
    held = false;
    if (shown) shown.removeAttribute('aria-describedby');
    shown = null;
  };
  // A mouse (or a pen held over the screen): the words of the mark under it, gone when it leaves. Words a press or the focus
  // holds up stay, until the pointer comes over another mark.
  document.addEventListener('pointermove', e => {
    if (e.pointerType === 'touch') return;
    const mark = markOf(e.target);
    if (held) {
      if (mark && mark !== shown) { held = false; show(mark, e.clientX, e.clientY); }
      return;
    }
    if (mark) show(mark, e.clientX, e.clientY); else if (shown) hide();
  }, { passive: true });
  // A press: a finger's on a mark shows its words, or takes them away when they already show; a press anywhere else takes
  // them away.
  document.addEventListener('pointerdown', e => {
    const mark = markOf(e.target);
    if (e.pointerType === 'mouse') {
      if (held && mark !== shown) hide();
      return;
    }
    if (!mark || acts(mark)) { if (shown) hide(); return; }
    if (held && shown === mark) { hide(); return; }
    show(mark);
    held = true;
  }, { passive: true });
  // The focus (the keyboard's, or a press that gave it): the words of the mark it is on, until it moves on.
  document.addEventListener('focusin', e => {
    const mark = markOf(e.target);
    if (!mark) return;
    show(mark);
    held = true;
  });
  document.addEventListener('focusout', e => {
    if (shown && !(e.relatedTarget && shown.contains(e.relatedTarget)) && shown.contains(e.target)) hide();
  });
  // Escape takes them away, wherever the focus is.
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && shown) hide();
  });
  // Marks that come many together (a chart's, a grid of days: data-tips on their box) are one stop of the Tab key, not one
  // each: the arrow keys go from mark to mark by where they are drawn (the next one to the right, below and so on), Home and
  // End to the first and the last, and the mark reached shows its words. The stop is the mark last reached.
  const marksIn = group => [...group.querySelectorAll('[data-tip]')].filter(m => m.getClientRects().length);
  const rove = group => {
    const marks = marksIn(group);
    const current = marks.find(m => m.tabIndex === 0 && m.dataset.stop) || marks[0];
    for (const m of group.querySelectorAll('[data-tip]')) m.tabIndex = m === current ? 0 : -1;
    if (current) current.dataset.stop = '1';
  };
  for (const group of document.querySelectorAll('[data-tips]')) rove(group);
  // The nearest mark in a direction (dx, dy: -1, 0 or 1) from one, on its row or its column.
  const toward = (marks, from, dx, dy) => {
    const a = from.getBoundingClientRect(), ax = a.left + a.width / 2, ay = a.top + a.height / 2;
    let best = null, far = Infinity;
    for (const m of marks) {
      if (m === from) continue;
      const b = m.getBoundingClientRect(), bx = b.left + b.width / 2, by = b.top + b.height / 2;
      const along = dx ? (bx - ax) * dx : (by - ay) * dy, across = dx ? Math.abs(by - ay) : Math.abs(bx - ax);
      if (along <= 0 || across > (dx ? a.height : a.width) / 2) continue;
      if (along < far) { far = along; best = m; }
    }
    return best;
  };
  document.addEventListener('keydown', e => {
    const mark = markOf(e.target);
    const group = mark && mark.closest('[data-tips]');
    if (!group || e.altKey || e.ctrlKey || e.metaKey) return;
    const marks = marksIn(group);
    const ways = { ArrowRight: [1, 0], ArrowLeft: [-1, 0], ArrowDown: [0, 1], ArrowUp: [0, -1] };
    const next = e.key === 'Home' ? marks[0] : e.key === 'End' ? marks[marks.length - 1]
      : ways[e.key] ? toward(marks, mark, ...ways[e.key]) : undefined;
    if (next === undefined) return;
    // At the edge: nothing moves, and the page does not scroll either.
    e.preventDefault();
    if (!next) return;
    for (const m of group.querySelectorAll('[data-tip]')) { m.tabIndex = -1; delete m.dataset.stop; }
    next.tabIndex = 0;
    next.dataset.stop = '1';
    next.focus();
  });
  // Words held up follow their mark as the page scrolls; a pointer's go.
  addEventListener('scroll', () => {
    if (held && shown) show(shown); else if (shown) hide();
  }, { passive: true, capture: true });
  addEventListener('resize', () => { if (shown) hide(); }, { passive: true });
})();

// A list of choices sent once (a <template> of its options) and put into every <select> that names it (data-choice): the
// Accounts page's players, which in every row made the page grow as accounts times players. Each keeps the choice it came
// with; one the list does not have reads as its first, none.
function fillChoices(root) {
  for (const select of root.querySelectorAll('select[data-choice]')) {
    const kept = select.value, list = document.getElementById(select.dataset.choice);
    if (!list) continue;
    select.replaceChildren(list.content.cloneNode(true));
    select.value = kept;
    if (select.selectedIndex < 0) select.selectedIndex = 0;
  }
}
fillChoices(document);

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

// A message in a box at its full height, while it is typed too: it wraps differently on every screen. Each box as the page
// comes and again when a part of the page is changed in place (fitBoxes), as it is typed, and when the window changes.
const fitBox = box => { box.style.height = 'auto'; box.style.height = `${box.scrollHeight + 2}px`; };
function fitBoxes(root) { for (const box of root.querySelectorAll('textarea')) fitBox(box); }
fitBoxes(document);
document.addEventListener('input', e => { if (e.target.matches && e.target.matches('textarea')) fitBox(e.target); });
addEventListener('resize', () => fitBoxes(document));

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
    // A key can sort it too; its look (admin.css) is the markup's, there from the start.
    th.tabIndex = 0;
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

// A list narrowed to a word as it is typed (the Players and Songs pages): the rows whose data-k has it, or whose number
// (data-n, the songs' # column) is the one typed, a count of those shown (the count's data-of says it, with {shown} and
// {all}; the number alone without), and the line that says none was found. The page's own search box names them:
// data-rows, data-count, data-none, and data-scroll for a box to hide too.
for (const search of document.querySelectorAll('input[type=search][data-rows]')) {
  search.addEventListener('input', () => {
    const q = search.value.trim().toLowerCase(), rows = document.querySelectorAll(search.dataset.rows);
    let shown = 0;
    for (const r of rows) {
      // A number typed is that row's number, whole: 12 is song 12, not 112 too.
      const hit = !q || r.dataset.k.includes(q) || r.dataset.n === q;
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

// A row's More (the Players page's, the Accounts page's). On the Players page a row's panel is made from the page's one
// (the template player-more) when its More first opens, for that row's player as its data-* say: the address it sends to
// (data-act), the name to change (data-name), the name its questions say (data-who) and the number in its words
// (data-id). A row the owner never opens carries none of it: four forms in every row made a page of many players slow to
// lay out. The Accounts page's rows carry their own panel, its four buttons, from the start. One open at a time, and it
// closes by a press anywhere else or Esc. Rename does nothing until the name has changed.
(() => {
  const made = document.getElementById('player-more');
  if (!document.querySelector('.row-more')) return;
  // A row's own panel: the page's one, its places filled in for the row's player.
  const panel = more => {
    const { act, name, who, id } = more.dataset;
    const form = made.content.firstElementChild.cloneNode(true);
    // Rename, Reset and Delete go to this player's address, which says whom the page saw the number belong to.
    // By its attribute: its buttons named "action" stand in for form.action.
    form.setAttribute('action', act);
    const field = form.querySelector('input[name=name]'), rename = form.querySelector('button[value=rename]');
    // The name as it is now; none yet leaves the field empty, its placeholder the "Player <n>" the pages show.
    field.value = name;
    field.placeholder = field.placeholder.replace('{id}', id);
    field.setAttribute('aria-label', field.getAttribute('aria-label').replace('{id}', id));
    // The questions before what cannot be undone name the player (by a function: a name with a $ in it stays as typed).
    for (const b of form.querySelectorAll('[data-ask]')) b.dataset.ask = b.dataset.ask.replace('{who}', () => who);
    const check = () => { rename.disabled = field.value.trim() === name; };
    field.addEventListener('input', check);
    check();
    return form;
  };
  // The panel floats over the page, not inside its card: a card is clipped to its cut corner and blurs what is behind it,
  // so anything inside it that reaches past its edge is cut off or drawn under the next card, and the table's own scroll
  // box cuts it too (a list of one or two players opened it below the card). So the panel goes on the page's top layer (a
  // popover), placed by hand under its More, right-aligned to it, or above it when the window has no room below; on a
  // phone across the whole row, as it opened in place before. Placed again as the page or the table scrolls, or the
  // window changes size. A browser without popovers keeps the panel where it is.
  const floats = 'showPopover' in HTMLElement.prototype;
  const place = more => {
    const box = more.querySelector('.row-more-in');
    if (!floats || !box || !more.open) return;
    if (!box.matches(':popover-open')) box.showPopover();
    const at = more.querySelector('summary').getBoundingClientRect();
    // On a phone the row's width, as it was; elsewhere the panel's own 300 px; never wider than the window allows.
    const row = more.closest('tr').getBoundingClientRect();
    const phone = matchMedia('(max-width: 700px)').matches;
    const width = Math.min(phone ? row.width : 300, innerWidth - 16);
    box.style.width = `${width}px`;
    // Its right edge on More's (a phone: the row's left), and inside the window by 8 px on both sides.
    const left = phone ? row.left : at.right - width;
    box.style.left = `${Math.max(8, Math.min(left, innerWidth - width - 8))}px`;
    // Below More, overlapping its foot a little as before; above it when the panel would pass the window's foot and fits
    // above; otherwise as low as it fits.
    const high = box.offsetHeight;
    const below = at.bottom - 4, above = at.top + 4 - high;
    const top = below + high <= innerHeight - 8 ? below : above >= 8 ? above : Math.max(8, innerHeight - 8 - high);
    box.style.top = `${top}px`;
  };
  // A details' toggle does not bubble: heard on its way down, once for every row.
  document.addEventListener('toggle', e => {
    const more = e.target;
    if (!more.matches || !more.matches('.row-more')) return;
    if (!more.open) {
      // Closed: its panel leaves the top layer with it.
      const box = more.querySelector('.row-more-in');
      if (floats && box && box.matches(':popover-open')) box.hidePopover();
      return;
    }
    // Made once: closed and opened again, the row keeps what was typed in it, as a form of its own did. A row that carries
    // its own (the Accounts page's) has it already.
    let box = more.querySelector('.row-more-in');
    if (!box) {
      if (!made) return;
      box = panel(more);
      more.append(box);
    }
    // Shown and hidden by the page itself (manual): a press elsewhere closes it through the details, below.
    if (floats && !box.popover) box.popover = 'manual';
    for (const other of document.querySelectorAll('.row-more[open]')) if (other !== more) other.open = false;
    place(more);
  }, true);
  // Kept beside its More while anything scrolls (the page, the table's own box) or the window changes.
  const follow = () => { for (const open of document.querySelectorAll('.row-more[open]')) place(open); };
  document.addEventListener('scroll', follow, { capture: true, passive: true });
  addEventListener('resize', follow, { passive: true });
  document.addEventListener('pointerdown', e => {
    if (e.target.closest('.row-more') || document.getElementById('ask').open) return;
    for (const open of document.querySelectorAll('.row-more[open]')) open.open = false;
  });
  // Esc closes an open panel too, as a press elsewhere does, the keyboard's place back on its More (a disclosure's own
  // close; the question a panel's button asks closes first, by itself).
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape' || document.getElementById('ask').open) return;
    const open = document.querySelector('.row-more[open]');
    if (!open) return;
    e.preventDefault();
    open.open = false;
    open.querySelector('summary').focus();
  });
})();

// The Recordings page's delete of those ticked: the button says how many it would delete (data-n, with {n}; data-none
// before any), waits until there is at least one, and stays at the screen's foot once something is ticked.
// Heard on the page, and counted again when the list is changed in place (bulkCount).
function bulkCount() {
  const bulk = document.getElementById('rec-bulk');
  if (!bulk) return;
  const n = bulk.form.querySelectorAll('input[name=sel]:checked').length;
  bulk.disabled = n === 0;
  bulk.parentElement.classList.toggle('on', n > 0);
  bulk.textContent = n ? bulk.dataset.n.replace('{n}', n) : bulk.dataset.none;
}
document.addEventListener('change', e => { if (e.target.matches && e.target.matches('input[name=sel]')) bulkCount(); });
bulkCount();

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

// The game server's state as a page just fetched shows it (this page again, or the frame alone: look() in status.py): the
// bar's word for a server that is not answering and the sentence above the page, put in place or taken away, every time.
// Only from a whole page: a refusal (signed out meanwhile) has neither, and must not take them away.
function serverState(page) {
  if (!page.querySelector('.bar-end')) return;
  const end = document.querySelector('.bar-end');
  const now = end && end.querySelector(':scope > .state'), fresh = page.querySelector('.bar-end > .state');
  if (end) {
    // The word where it stands, at the bar's end before the language keys, as the page itself puts it.
    if (fresh && now) now.replaceWith(fresh);
    else if (fresh) end.prepend(fresh);
    else if (now) now.remove();
  }
  const slot = document.getElementById('server-alert'), said = page.getElementById('server-alert');
  if (slot && said) slot.replaceChildren(...said.childNodes);
}

// The status page's tiles and resources look again by themselves: an owner may keep this page open on the side. A new
// point every five minutes in the resources' charts. The things to look at first, the bar's word and the sentence above the
// page with them.
if (document.getElementById('tiles')) {
  const lookAgain = async () => {
    if (document.hidden) return;
    try {
      const page = new DOMParser().parseFromString(await (await fetch(location.href, { headers: { 'X-Requested-With': 'fetch' } })).text(), 'text/html');
      const fresh = page.getElementById('tiles');
      if (fresh) document.getElementById('tiles').replaceChildren(...fresh.children);
      const res = page.getElementById('resources');
      if (res) document.getElementById('resources').replaceChildren(...res.children);
      const attention = page.getElementById('attention');
      if (attention) document.getElementById('attention').replaceChildren(...attention.childNodes);
      serverState(page);
    } catch (_) { /* The next look. */ }
  };
  setInterval(lookAgain, 30000);
  // A tab out of sight asks nothing; looked at again, it catches up at once.
  document.addEventListener('visibilitychange', () => { if (!document.hidden) lookAgain(); });
} else if (document.querySelector('.auth-form') && document.getElementById('server-alert')) {
  // Every other page signed in looks at the frame alone, as often: the bar's word and the sentence come and go with the
  // game server while the page stays open. Asked for this page (for=), whose own rules say which sentence it shows.
  const look = new URL('look', document.querySelector('.bar .logo').href);
  look.searchParams.set('for', document.body.dataset.page || '');
  const lookAgain = async () => {
    if (document.hidden) return;
    try {
      const r = await fetch(look, { headers: { 'X-Requested-With': 'fetch' }, cache: 'no-store' });
      if (r.ok) serverState(new DOMParser().parseFromString(await r.text(), 'text/html'));
    } catch (_) { /* The admin service itself away a moment: the next look. */ }
  };
  setInterval(lookAgain, 30000);
  // A tab out of sight asks nothing; looked at again, it catches up at once.
  document.addEventListener('visibilitychange', () => { if (!document.hidden) lookAgain(); });
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

// The Maintenance page: a ready-made message in the field, to change or send as it is. Heard on the page, so that it works
// in a part of the page changed in place too.
document.addEventListener('click', e => {
  const b = e.target.closest && e.target.closest('.presets button[data-text]');
  if (!b) return;
  const f = document.querySelector('textarea[name=message]');
  f.value = b.dataset.text;
  f.dispatchEvent(new Event('input', { bubbles: true }));
  f.focus();
});

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
      // A file of no use here: its own import goes (the import would find nothing in it), and the choice of its songs
      // with it, which would do nothing. In the list of what was found, a row goes once none of its files is of use.
      const own = el.closest('li.file') || el.closest('.setup-found > li');
      if (!j.ok && own && ![...own.querySelectorAll('[data-what]')].some(w => !w.classList.contains('bad'))) {
        for (const b of own.querySelectorAll('button')) b.disabled = true;
        for (const choice of own.querySelectorAll('.setup-import label.check')) choice.hidden = true;
      }
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
// data-instance) on two looks in a row, then the page goes on (data-back), signed in by the one-time key it carries: a
// new process that answered once may still be bringing the server's other parts up, and the page it went on to was then
// an error. After a minute it says that this takes longer than usual.
(() => {
  const wait = document.getElementById('restart-wait');
  if (!wait) return;
  const started = Date.now();
  let seen = null;
  (async function look() {
    try {
      const r = await fetch(wait.dataset.ping, { cache: 'no-store' });
      const now = r.ok ? (await r.json()).instance : null;
      // The same new process a second time: it has stayed up, and the way back is open.
      if (now && now !== wait.dataset.instance && now === seen) { location.replace(wait.dataset.back); return; }
      seen = now && now !== wait.dataset.instance ? now : null;
    } catch (e) {
      // Not answering yet: it is starting.
      seen = null;
    }
    if (Date.now() - started > 60000) document.getElementById('slow').hidden = false;
    setTimeout(look, 1500);
  })();
})();

// The server stopping (or removing itself) from the Server page: which process answers is asked (data-ping), as a
// restart's page does. Once nothing answers, it has stopped: the heading says so (data-stopped, data-stopped-lead) and
// its light goes off. Should another process answer later (the server started again on its PC), it runs again
// (data-again), with the way back to the Server page.
(() => {
  const wait = document.getElementById('stop-wait');
  if (!wait) return;
  const head = document.getElementById('stop-head'), lead = document.getElementById('stop-lead');
  const lamp = document.getElementById('stop-lamp');
  let stopped = false;
  (async function look() {
    let instance = null;
    try {
      const r = await fetch(wait.dataset.ping, { cache: 'no-store' });
      if (r.ok) instance = (await r.json()).instance;
    } catch (e) {
      // Nothing answers: the server has stopped.
    }
    if (instance === null && !stopped) {
      stopped = true;
      head.textContent = wait.dataset.stopped;
      if (wait.dataset.stoppedLead) lead.textContent = wait.dataset.stoppedLead;
      lamp.className = 'lamp off';
    } else if (instance !== null && instance !== wait.dataset.instance && wait.dataset.again) {
      head.textContent = wait.dataset.again;
      lamp.className = 'lamp on';
      document.getElementById('stop-back').hidden = false;
      return;
    }
    setTimeout(look, 2000);
  })();
})();

// The server's words on what was just done, as a band under the bar when the page changed in place or came back further
// down (where the words at the page's top are out of sight): part of the bar, across it, over the page for a few seconds
// with nothing under it moving; its words where the page's text starts. Several at once (a repair's steps, a restore's
// lines) stand one under another in one place under the bar, each in its own colour: each laid over the last, only the
// last could be read. A press takes them away (each one's cross says so), and they go together by themselves, sooner
// when all went well, later the more there are to read.
function band(said) {
  const words = document.createElement('span');
  words.className = 'wrap';
  words.append(...said.childNodes);
  said.append(words);
  said.classList.add('float');
  // The one place under the bar for the messages of one answer.
  const bar = document.querySelector('.bar');
  let stack = bar.querySelector(':scope > .said-stack');
  if (!stack) {
    stack = document.createElement('div');
    stack.className = 'said-stack';
    stack.addEventListener('click', () => stack.remove());
    bar.append(stack);
  }
  stack.append(said);
  // Five seconds for one good message, fifteen when one went wrong, and two more for each further line to read.
  const lines = stack.querySelectorAll('.flash.float');
  const wait = ([...lines].every(m => m.classList.contains('ok')) ? 5000 : 15000) + 2000 * (lines.length - 1);
  clearTimeout(stack.leaving);
  stack.leaving = setTimeout(() => stack.remove(), wait);
}

// A switch or a small change (a form marked data-inplace) changes the page where it is: sent in the background, the page as
// the server now has it is read, and the parts of this page that show what changed (marked data-region, each by its id)
// are put in place of their old selves; a part the page no longer has (a player deleted) goes. The server's words on
// what was done (data-said) come as the pages' message at the foot of the screen. Nothing else moves: no white flash, the
// same place on the page, the same search, the focus on the same button. The form works as before without scripts (the
// page loads again), and does so here too when the sending fails or the sign-in has ended (the server then says why).
// An answer that is a job to follow (data-job) or another page loads that page.
(() => {
  // The message at the foot of the screen, as the pages float the server's words: a press takes it away, and it goes by
  // itself, a good one sooner.
  const say = doc => {
    for (const old of document.querySelectorAll('.flash[data-said]')) old.remove();
    for (const m of doc.querySelectorAll('.flash[data-said]')) band(document.importNode(m, true));
  };
  // The parts that changed, put in place; the focus kept on the same control of a part that was replaced.
  const swap = doc => {
    const active = document.activeElement;
    let refocus = null;
    for (const old of document.querySelectorAll('[data-region][id]')) {
      const fresh = doc.getElementById(old.id);
      if (!fresh) { old.remove(); continue; }
      if (fresh.outerHTML === old.outerHTML) continue;
      // Which of the part's controls had the focus, by its place among them.
      if (active && old.contains(active)) {
        const all = [...old.querySelectorAll('button, a[href], input, select, textarea, summary, [tabindex]')];
        refocus = [old.id, all.indexOf(active)];
      }
      old.replaceWith(document.importNode(fresh, true));
    }
    // What the pages do to their parts as they come: the players' choices, the boxes' height, the list's search, the count
    // on the recordings' delete.
    fillChoices(document);
    fitBoxes(document);
    for (const search of document.querySelectorAll('input[type=search][data-rows]')) if (search.value) search.dispatchEvent(new Event('input'));
    bulkCount();
    if (refocus) {
      const part = document.getElementById(refocus[0]);
      const all = part ? [...part.querySelectorAll('button, a[href], input, select, textarea, summary, [tabindex]')] : [];
      const next = all[refocus[1]] || all[0];
      if (next) next.focus({ preventScroll: true });
    }
  };
  document.addEventListener('submit', async e => {
    const form = e.target, button = e.submitter;
    // The form's own attributes, not its properties: a field named "action" (most of these forms have one) stands in for
    // form.action.
    const method = (form.getAttribute('method') || 'get').toLowerCase();
    if (e.defaultPrevented || method !== 'post' || !(form.dataset.inplace !== undefined || (button && button.dataset.inplace !== undefined))) return;
    // Sent the usual way once: after a failure here, or for the sign-in that ended.
    if (form.dataset.plain) { delete form.dataset.plain; return; }
    e.preventDefault();
    // Where it goes: the pressed button's own address, or the form's, or this page's when it names none, as a browser sends it.
    const url = button && button.hasAttribute('formaction') ? button.formAction : new URL(form.getAttribute('action') || location.href, location.href).href;
    const body = new FormData(form);
    if (button && button.name) body.append(button.name, button.value);
    // Done, either way: the form can be sent again, and the page is not taken back to where it was (nothing moved).
    const done = () => {
      delete form.dataset.sent;
      if (button) button.removeAttribute('aria-busy');
      sessionStorage.removeItem('odq-back');
    };
    // The usual way: the page loads again with the answer. A question asked before (data-ask) is not asked twice.
    const plain = () => {
      done();
      form.dataset.plain = '1';
      if ((button && button.dataset.ask) || form.dataset.ask) form.dataset.answered = '1';
      form.requestSubmit(button || undefined);
    };
    let r, html;
    try {
      r = await fetch(url, { method: 'POST', body, headers: { 'X-Requested-With': 'fetch' }, credentials: 'same-origin' });
      html = await r.text();
    } catch (_) {
      plain();
      return;
    }
    // The sign-in ended: nothing was done, and the usual way says so on the sign-in page.
    if (r.status === 401) { plain(); return; }
    done();
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const there = new URL(r.url, location.href);
    // A job to follow, or another page: that page, as it would have come.
    if (doc.querySelector('[data-job]') || there.pathname !== location.pathname) { location.assign(there.href); return; }
    // An answer without any of the parts this changes in place (the service's own error page, or a list now empty): the
    // page as it would have come.
    if (!doc.querySelector('[data-region][id]')) { document.open(); document.write(html); document.close(); window.odqChanges = (window.odqChanges || 0) + 1; return; }
    swap(doc);
    say(doc);
    // How many changes the page has made in place: the pages' tests wait for the next one.
    window.odqChanges = (window.odqChanges || 0) + 1;
  });
})();

// Back to a page whose form was sent (the busy button's part above kept where it was): the same search, the same place in
// the list. Last, once the lists above can narrow to a search. A page that answers with what it shows only once (a new
// password, a new token: data-once) shows that instead, wherever the form was sent from.
(() => {
  const back = JSON.parse(sessionStorage.getItem('odq-back') || 'null');
  sessionStorage.removeItem('odq-back');
  const once = document.querySelector('[data-once]');
  if (once) {
    // Its top just under the bar where the bar stays on the screen (wider screens); on a phone the bar scrolls away.
    const bar = document.querySelector('.bar');
    const cover = bar && getComputedStyle(bar).position === 'sticky' ? bar.offsetHeight : 0;
    // Where the page arrives (its top), it may be whole on the screen already, under the bar and the menu: then the page
    // stays there. Otherwise its top comes up, with a little room above it, so that its edge and heading read as the top
    // of what is on the screen.
    const at = once.getBoundingClientRect();
    if (at.top < cover || at.bottom > innerHeight) scrollTo(0, Math.max(0, at.top + scrollY - cover - 14));
    // The focus on it too, already in place: the next Tab reaches its copy button, and a screen reader says its heading.
    once.focus({ preventScroll: true });
    return;
  }
  if (!back || back.path !== location.pathname) return;
  const search = document.querySelector('input[type=search]');
  if (search && back.q) { search.value = back.q; search.dispatchEvent(new Event('input')); }
  scrollTo(0, back.y);
  // Further down the page, the message about what was done comes as a band under the bar: it would be out of sight at the
  // top. A good one leaves by itself.
  if (scrollY > 0) {
    // The band under the bar, as a change made in place says it.
    for (const m of document.querySelectorAll('main .flash[data-said]')) band(m);
  }
})();
