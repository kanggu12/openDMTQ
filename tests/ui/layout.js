// What can be measured about a page's layout, run inside the page. Used by audit.js. Returns a list of findings:
//   clipped   text cut off by its own box or a box around it (ellipsis, line clamp, hidden overflow)
//   sticks-out  text past the edge of the box that holds it
//   overlap   two pieces of text on top of each other
//   rows      boxes side by side that do not start or end on the same line
//   columns   the same part of repeated rows not lined up from row to row
//   past-screen  something past the screen's edge with no scrolling box around it
//   page-wide   the page itself wider than the screen
//   covered   text with another box on top of it
//   contrast  text too close in colour to what is behind it
//   default-control  a control still in the browser's own look
//   no-style  a class the markup uses and no stylesheet mentions
//   small-target  something to press that a finger or pointer can hardly hit
//   broken-image  a picture that did not load
//   side-scroll  a box whose content is wider than it: what is past the edge looks cut off until one thinks of swiping
//   broken-word  an ordinary word split over two lines, because its column is too narrow
//   split-sentence  a sentence a flex or grid box has cut into pieces, each on a line of its own
// Marks on an element: data-layout-ok says why it is allowed; things that are decoration (aria-hidden) do not count.
window.layoutAudit = function layoutAudit() {
  const out = [];
  const say = (kind, el, detail) => out.push({ kind, at: describe(el), detail });
  function describe(el) {
    if (!el || !el.tagName) return '';
    const cls = (el.getAttribute('class') || '').trim().split(/\s+/).filter(Boolean).slice(0, 2).join('.');
    return el.tagName.toLowerCase() + (cls ? '.' + cls : '') + (el.id ? '#' + el.id : '');
  }
  const seen = el => {
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || Number(s.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  // Not drawn for reading, or drawn on purpose as it is: the hidden page title, the wordmark whose letters sit close.
  const decoration = el => !!el.closest('[aria-hidden="true"], .chart-tip, video, script, style, option, .page-title, .logo, [data-layout-ok]');
  const short = t => t.replace(/\s+/g, ' ').trim().slice(0, 50);

  // Every piece of text on the page and where it really is drawn, line by line.
  const pieces = [];
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const range = document.createRange();
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    if (!n.nodeValue.trim()) continue;
    const el = n.parentElement;
    if (!el || decoration(el) || !seen(el)) continue;
    // Folded away: browsers still answer with a place for what is inside a closed <details>.
    if (el.closest('details:not([open])') && !el.closest('summary')) continue;
    range.selectNodeContents(n);
    const rects = [...range.getClientRects()].filter(r => r.width > 0.5 && r.height > 0.5);
    if (!rects.length) continue;
    // Where the letters are: a line's rectangle is the font's whole height, with room above and below them that a tight
    // line height lets stick out without anything showing. About this much of the font size is letters.
    const letters = 0.76 * parseFloat(getComputedStyle(el).fontSize);
    for (let i = 0; i < rects.length; i++) {
      const r = rects[i], mid = (r.top + r.bottom) / 2;
      rects[i] = { left: r.left, right: r.right, top: mid - letters / 2, bottom: mid + letters / 2 };
    }
    const box = { left: Math.min(...rects.map(r => r.left)), right: Math.max(...rects.map(r => r.right)), top: Math.min(...rects.map(r => r.top)), bottom: Math.max(...rects.map(r => r.bottom)) };
    // What a box that scrolls leaves in view: text scrolled away is not on anything, and can be reached.
    let view = { ...box }, gone = false;
    for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
      const as = getComputedStyle(a);
      if (['auto', 'scroll'].includes(as.overflowX) || ['auto', 'scroll'].includes(as.overflowY)) {
        const r = a.getBoundingClientRect();
        view = { left: Math.max(view.left, r.left), right: Math.min(view.right, r.right), top: Math.max(view.top, r.top), bottom: Math.min(view.bottom, r.bottom) };
        if (view.right <= view.left || view.bottom <= view.top) gone = true;
      }
    }
    pieces.push({ el, text: n.nodeValue, box, rects, view, gone });
  }
  // What floats over the page on purpose hides what is under it: the site's question all of the page, a row's opened panel what
  // lies beneath it. That is no fault of what is hidden.
  const meets = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
  const question = document.querySelector('dialog[open]');
  const panels = [...document.querySelectorAll('details[open] > .row-more-in')].map(el => [el, el.getBoundingClientRect()]);
  for (let i = pieces.length - 1; i >= 0; i--) {
    const p = pieces[i];
    if (question ? !question.contains(p.el) : panels.some(([el, r]) => !el.contains(p.el) && meets(p.box, r))) pieces.splice(i, 1);
  }

  // Text cut off.
  for (const p of pieces) {
    const s = getComputedStyle(p.el);
    // Its own box: an ellipsis, or a line clamp.
    if (s.overflowX !== 'visible' || s.overflowY !== 'visible') {
      if (p.el.scrollWidth > p.el.clientWidth + 1 && s.overflowX !== 'auto' && s.overflowX !== 'scroll') say('clipped', p.el, short(p.text));
      else if (p.el.scrollHeight > p.el.clientHeight + 2 && s.overflowY !== 'auto' && s.overflowY !== 'scroll') say('clipped', p.el, short(p.text));
    }
    // A box around it that hides what passes its edge (not one that scrolls: that can be reached).
    for (let a = p.el.parentElement; a && a !== document.body; a = a.parentElement) {
      const as = getComputedStyle(a);
      const hides = v => v === 'hidden' || v === 'clip';
      if (!hides(as.overflowX) && !hides(as.overflowY) && as.clipPath === 'none') continue;
      const r = a.getBoundingClientRect();
      if ((hides(as.overflowX) && (p.box.right > r.right + 1 || p.box.left < r.left - 1)) || (hides(as.overflowY) && (p.box.bottom > r.bottom + 1 || p.box.top < r.top - 1))) {
        say('clipped', p.el, `${short(p.text)} (by ${describe(a)})`);
        break;
      }
    }
  }

  // Text past the edge of what holds it. "What holds it": the nearest box with a background, a border or a size of its own.
  const holds = el => el.matches('.card, .btn, .button, .auth, .pod, .stat, .song, .past, .thumb, .mark, .code, .tabs a, td, th, .alert, .warn, .done, .error, .flash, .drop, .steps li');
  for (const p of pieces) {
    let box = p.el.closest('.card, .btn, .button, .auth, .pod, .stat, .song, .past, .thumb, .mark, .code, .tabs a, td, th, .alert, .warn, .done, .error, .flash, .drop, .steps li');
    // A cell laid out as display: contents has no box: what holds the text is further out.
    while (box && getComputedStyle(box).display === 'contents') box = box.parentElement && box.parentElement.closest('.card, .btn, .button, .auth, .pod, .stat, .song, .past, .thumb, .mark, .code, .tabs a, td, th, .alert, .warn, .done, .error, .flash, .drop, .steps li');
    if (!box || !holds(box) || p.gone) continue;
    const r = box.getBoundingClientRect();
    // A table may scroll sideways on purpose; a cell's text can still not leave the cell.
    if (p.box.right > r.right + 1 || p.box.left < r.left - 1 || p.box.bottom > r.bottom + 1 || p.box.top < r.top - 1) say('sticks-out', p.el, `${short(p.text)} (out of ${describe(box)})`);
  }

  // Text on text. Inside one element's own lines this cannot happen; between elements it should not.
  // The bars stay in place over the page as it scrolls: that is what they are for.
  const sorted = pieces.filter(p => !p.gone && !p.el.closest('.bar, .tabbar')).sort((a, b) => a.box.top - b.box.top);
  for (let i = 0; i < sorted.length; i++) {
    const a = sorted[i];
    for (let j = i + 1; j < sorted.length && sorted[j].box.top < a.box.bottom; j++) {
      const b = sorted[j];
      if (a.el === b.el || a.el.contains(b.el) || b.el.contains(a.el)) continue;
      // A little touching of line boxes is normal; the letters' own height is about 70% of the box.
      const w = Math.min(a.box.right, b.box.right) - Math.max(a.box.left, b.box.left);
      const h = Math.min(a.box.bottom, b.box.bottom) - Math.max(a.box.top, b.box.top);
      if (w > 2 && h > 1) {
        // Lines overlap only if real line rectangles do: a wrapped block's outline may not.
        const inView = (r, p) => ({ left: Math.max(r.left, p.view.left), right: Math.min(r.right, p.view.right), top: Math.max(r.top, p.view.top), bottom: Math.min(r.bottom, p.view.bottom) });
        const real = a.rects.some(x => b.rects.some(y => {
          const u = inView(x, a), v = inView(y, b);
          return Math.min(u.right, v.right) - Math.max(u.left, v.left) > 2 && Math.min(u.bottom, v.bottom) - Math.max(u.top, v.top) > 1;
        }));
        if (real) say('overlap', a.el, `${short(a.text)} / ${short(b.text)}`);
      }
    }
  }

  // Boxes side by side: same top, same bottom.
  for (const parent of document.querySelectorAll('.two, .three, .home-lists, .tiles, .dash-grid, .podium, .songs, .thumbs, .past-list, .stats, .steps, .chapters, .watch')) {
    if (!seen(parent) || parent.matches('.podium, .watch')) continue;
    const kids = [...parent.children].filter(seen);
    const lines = new Map();
    for (const k of kids) {
      const top = Math.round(k.getBoundingClientRect().top);
      const line = [...lines.keys()].find(t => Math.abs(t - top) <= 2);
      lines.set(line === undefined ? top : line, [...(lines.get(line === undefined ? top : line) || []), k]);
    }
    for (const row of lines.values()) {
      if (row.length < 2) continue;
      const bottoms = row.map(k => k.getBoundingClientRect().bottom);
      if (Math.max(...bottoms) - Math.min(...bottoms) > 1.5) say('rows', parent, `bottoms differ by ${Math.round(Math.max(...bottoms) - Math.min(...bottoms))}px in a row of ${row.length}`);
    }
  }

  // Repeated rows: the same part of each row lines up (by its left, its right or its middle).
  for (const parent of document.querySelectorAll('.feed, .past-list, .ranked, .changes, .live-rows, tbody, .levels, .chapters')) {
    if (!seen(parent)) continue;
    const rows = [...parent.children].filter(seen);
    if (rows.length < 3) continue;
    // Cards in a grid of several columns are compared as boxes above; this is for one list going down.
    if (Math.abs(rows[0].getBoundingClientRect().top - rows[1].getBoundingClientRect().top) < 2) continue;
    // Stacked rows on a phone have other rules; a row's first line is what is compared there.
    const classes = new Map();
    rows.forEach((row, i) => {
      for (const el of row.querySelectorAll('[class]')) {
        if (!seen(el) || el.closest('[aria-hidden="true"]') || el.closest('details') || el.matches('.btn, .btn *, form, form *, .live-mark, .mark')) continue;
        // Inside a box marked as laid out on purpose (cells coloured by value): its parts are not columns. The box is.
        if (el.parentElement && el.parentElement.closest('[data-layout-ok]')) continue;
        const key = el.classList[0];
        if (!classes.has(key)) classes.set(key, new Map());
        if (!classes.get(key).has(i)) classes.get(key).set(i, el);
      }
    });
    for (const [key, byRow] of classes) {
      if (byRow.size < 3 || byRow.size < rows.length * 0.6) continue;
      const boxes = [...byRow.values()].map(el => el.getBoundingClientRect());
      const spread = f => Math.max(...boxes.map(f)) - Math.min(...boxes.map(f));
      if (spread(r => r.left) > 1.5 && spread(r => r.right) > 1.5 && spread(r => r.left + r.width / 2) > 1.5) say('columns', parent, `.${key} wanders by ${Math.round(spread(r => r.left))}px`);
    }
  }

  // Text that cannot be read: its colour against what is behind it (solid colours only; over a picture nothing is said).
  const parse = c => { const m = /rgba?\(([^)]+)\)/.exec(c); if (!m) return null; const v = m[1].split(/[ ,/]+/).map(Number); return { r: v[0], g: v[1], b: v[2], a: v.length > 3 ? v[3] : 1 }; };
  const lum = c => { const f = x => { x /= 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const contrast = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  // Every colour that may be behind the element's text: a gradient counts with each of its stops. Over a picture, nothing.
  const behind = el => {
    const layers = [];
    for (let a = el; a; a = a.parentElement) {
      const st = getComputedStyle(a);
      if (a.matches('.stage, .song-pic, .thumb-pic, .past-pic, .live-stage, .songhead') || /url\(|conic|radial/.test(st.backgroundImage)) return [];
      if (st.backgroundImage !== 'none') layers.push([...st.backgroundImage.matchAll(/rgba?\([^)]+\)/g)].map(m => parse(m[0])));
      const c = parse(st.backgroundColor);
      if (c && c.a > 0) { layers.push([c]); if (c.a >= 1) break; }
    }
    // The page's own colour under everything, then each layer from the bottom up, keeping the list short.
    let under = [{ r: 17, g: 21, b: 26 }];
    for (const stops of layers.reverse()) {
      const next = [];
      for (const b of under) for (const c of stops) next.push({ r: c.r * c.a + b.r * (1 - c.a), g: c.g * c.a + b.g * (1 - c.a), b: c.b * c.a + b.b * (1 - c.a) });
      under = next.slice(0, 16);
    }
    return under;
  };
  for (const p of pieces) {
    if (p.gone) continue;
    const st = getComputedStyle(p.el);
    // Text painted by a gradient (the leaning headings, the first place's number): its colour says nothing.
    if (st.webkitBackgroundClip === 'text' || st.backgroundClip === 'text') continue;
    const fg = parse(st.color);
    if (!fg || fg.a === 0) continue;
    // The worst of what may be behind it.
    let ratio = Infinity;
    for (const bg of behind(p.el)) ratio = Math.min(ratio, contrast({ r: fg.r * fg.a + bg.r * (1 - fg.a), g: fg.g * fg.a + bg.g * (1 - fg.a), b: fg.b * fg.a + bg.b * (1 - fg.a) }, bg));
    if (ratio === Infinity) continue;
    const big = parseFloat(st.fontSize) >= 24 || (parseFloat(st.fontSize) >= 18.5 && Number(st.fontWeight) >= 700);
    if (ratio < (big ? 3 : 4.5)) say('contrast', p.el, `${ratio.toFixed(1)}:1  ${short(p.text)}`);
  }

  // Controls in the browser's own clothes: a design that forgot them.
  for (const el of document.querySelectorAll('button, select, textarea, input:not([type=hidden]):not([type=file]):not([type=range]):not([type=checkbox]):not([type=radio])')) {
    if (!seen(el) || el.closest('.live-ctl, .drop')) continue;
    const st = getComputedStyle(el), bg = parse(st.backgroundColor);
    // Light grey or white is what a browser gives a control; nothing on this dark site is meant to be.
    if (bg && bg.a > 0.5 && bg.r > 200 && bg.g > 200 && bg.b > 200) say('default-control', el, short(el.textContent || el.getAttribute('placeholder') || ''));
  }
  // Classes the page uses and no rule mentions: markup a stylesheet forgot, or a leftover. (Only sheets of this site.)
  const known = new Set();
  const note = rules => { for (const r of rules) { if (r.selectorText) for (const m of r.selectorText.matchAll(/\.([\w-]+)/g)) known.add(m[1]); if (r.cssRules) note(r.cssRules); } };
  for (const sheet of document.styleSheets) { try { note(sheet.cssRules); } catch (_) { /* Another site's. */ } }
  // A script's handle or a level with the base look has no rule of its own by design.
  for (const c of ['c0', 'get-app', 'sortable', 'vod-only']) known.add(c);
  const missing = new Set();
  for (const el of document.querySelectorAll('body [class]')) for (const c of el.classList) if (!known.has(c)) missing.add(c);
  out.push(...[...missing].map(c => ({ kind: 'no-style', at: c, detail: '' })));

  // Text under another box: what is on top at the text's place is something else. Only what is on the screen can be asked
  // about, so the page is walked a part of a screen at a time; a bar that stays in place is simply asked about again later.
  const startY = scrollY;
  const stretched = el => { const a = el.closest('a, button'); return !!a && getComputedStyle(a, '::after').position === 'absolute'; };
  // What stays in place while the page scrolls is only where it was measured before the first scroll.
  const stays = el => { for (let a = el; a; a = a.parentElement) { const v = getComputedStyle(a).position; if (v === 'sticky' || v === 'fixed') return true; } return false; };
  // (What lets the pointer through, as the marks on a video do, is not hit by the question: it is not asked about.)
  const waiting = new Set(pieces.filter(p => !p.gone && !p.el.closest('.bar, .tabbar') && getComputedStyle(p.el).pointerEvents !== 'none'));
  for (let y = 0; waiting.size && y < document.documentElement.scrollHeight; y += innerHeight / 2) {
    scrollTo({ top: y, behavior: 'instant' });
    for (const p of waiting) {
      if (scrollY !== startY && stays(p.el)) { waiting.delete(p); continue; }
      const r = p.rects[0], cx = (r.left + r.right) / 2, middle = (r.top + r.bottom) / 2, cy = middle + startY - scrollY;
      // Past the edge of a box that scrolls: not on the screen now, and it can be reached.
      if (middle < p.view.top || middle > p.view.bottom || cx < p.view.left || cx > p.view.right) { waiting.delete(p); continue; }
      if (cy < 0 || cy >= innerHeight || cx < 0 || cx >= innerWidth) continue;
      // The list's first, not elementFromPoint: that one answers with a nearby box under a CSS filter (the hero's logo).
      const hit = document.elementsFromPoint(cx, cy)[0];
      if (!hit || hit.closest('.bar, .tabbar')) continue;
      waiting.delete(p);
      // A drop zone's file input lies over its words on purpose, see-through: that is what makes all of it a target.
      if (!p.el.contains(hit) && !hit.contains(p.el) && !stretched(hit) && !hit.matches('input[type=file]')) say('covered', p.el, `${short(p.text)} (under ${describe(hit)})`);
    }
  }
  scrollTo({ top: startY, behavior: 'instant' });

  // Too small to press (the least the accessibility guideline allows, on any screen). What a link's ::after stretches counts.
  for (const el of document.querySelectorAll('a[href], button, input:not([type=hidden]), select, summary')) {
    if (!seen(el) || el.closest('[aria-hidden="true"], .live-ctl, .page-title') || el.closest('p, li, dd, small, .prose')) continue;
    const r = el.getBoundingClientRect(), after = getComputedStyle(el, '::after');
    if (after.position === 'absolute') continue;
    if (r.height < 24 || r.width < 24) say('small-target', el, `${Math.round(r.width)}x${Math.round(r.height)}  ${short(el.textContent || el.getAttribute('aria-label') || '')}`);
  }
  for (const img of document.images) if (img.complete && !img.naturalWidth && seen(img)) say('broken-image', img, img.getAttribute('src') || '');

  // A box that scrolls sideways: its last column looks cut off. Where that is what is meant (a log's long lines, on a narrow
  // screen) the box says so with data-layout-ok.
  for (const el of document.querySelectorAll('body *')) {
    const v = getComputedStyle(el).overflowX;
    if ((v === 'auto' || v === 'scroll') && seen(el) && el.scrollWidth > el.clientWidth + 1 && !el.closest('[data-layout-ok]')) say('side-scroll', el, `${el.scrollWidth} in ${el.clientWidth}`);
  }
  // A word split over two lines. Only ordinary ones: a name of twenty letters has to break somewhere, and Korean may break
  // anywhere.
  const word = document.createRange();
  for (const p of pieces) {
    if (p.gone || p.rects.length < 2 || p.text.length > 400) continue;
    const node = [...p.el.childNodes].find(n => n.nodeType === Node.TEXT_NODE && n.nodeValue === p.text);
    if (!node) continue;
    for (const m of p.text.matchAll(/\b[A-Za-z][a-z]{1,13}\b/g)) {
      word.setStart(node, m.index);
      word.setEnd(node, m.index + m[0].length);
      const tops = new Set([...word.getClientRects()].filter(r => r.width > 0.5).map(r => Math.round(r.top)));
      if (tops.size > 1) { say('broken-word', p.el, m[0]); break; }
    }
  }

  // A sentence a flex or grid box has cut up. In such a box each run of loose text and each <b>, <code> or link between
  // them is an item of its own, so a column puts "Open", the bold name and "and play" one under another. Only a column or a
  // grid: a row that wraps does it on purpose (a heading, and its small words under it when there is no room beside it).
  const inline = /^(A|ABBR|B|CODE|EM|I|KBD|MARK|S|SMALL|SPAN|STRONG|SUB|SUP|TIME|U)$/;
  for (const el of document.querySelectorAll('body *')) {
    const st = getComputedStyle(el);
    const stacks = (st.display.includes('flex') && st.flexDirection.startsWith('column')) || st.display.includes('grid');
    if (!stacks || !seen(el) || decoration(el)) continue;
    const items = [];
    for (const n of el.childNodes) {
      if (n.nodeType === Node.TEXT_NODE && n.nodeValue.trim()) {
        range.selectNodeContents(n);
        const r = [...range.getClientRects()].filter(x => x.width > 0.5);
        if (r.length) items.push({ loose: true, top: Math.min(...r.map(x => x.top)), bottom: Math.max(...r.map(x => x.bottom)) });
      } else if (n.nodeType === Node.ELEMENT_NODE && inline.test(n.tagName) && seen(n)) {
        const r = n.getBoundingClientRect();
        items.push({ loose: false, top: r.top, bottom: r.bottom });
      }
    }
    if (!items.some(i => i.loose) || !items.some(i => !i.loose)) continue;
    if (items.some((a, i) => i > 0 && (a.top >= items[i - 1].bottom - 1 || items[i - 1].top >= a.bottom - 1))) say('split-sentence', el, short(el.textContent));
  }

  // Words in a control that do not fit it: a placeholder, or the choice a list shows.
  const ruler = document.createElement('canvas').getContext('2d');
  for (const el of document.querySelectorAll('input[placeholder], select')) {
    if (!seen(el) || el.closest('[aria-hidden="true"]') || el.closest('details:not([open])') || (el.matches('input') && el.value)) continue;
    const st = getComputedStyle(el);
    const words = el.matches('select') ? (el.selectedOptions[0] ? el.selectedOptions[0].textContent : '') : el.placeholder;
    ruler.font = `${st.fontWeight} ${st.fontSize} ${st.fontFamily}`;
    const room = el.clientWidth - parseFloat(st.paddingLeft) - parseFloat(st.paddingRight);
    if (ruler.measureText(words).width > room + 1) say('clipped', el, short(words));
  }

  // Words a text box cannot show all of.
  for (const el of document.querySelectorAll('textarea')) if (seen(el) && el.value && el.scrollHeight > el.clientHeight + 2) say('clipped', el, short(el.value));

  // Past the screen.
  const scroller = el => { for (let p = el.parentElement; p; p = p.parentElement) { const v = getComputedStyle(p).overflowX; if (v === 'auto' || v === 'scroll' || v === 'hidden' || v === 'clip') return true; } return false; };
  for (const el of document.querySelectorAll('main *, header *, nav *, footer *')) {
    if (!seen(el) || decoration(el)) continue;
    const r = el.getBoundingClientRect();
    // (Folded away: not on the screen at all, whatever place browsers answer with.)
    if (el.closest('details:not([open])') && !el.closest('summary')) continue;
    if ((r.right > innerWidth + 1 || r.left < -1) && !scroller(el)) { say('past-screen', el, `${Math.round(r.left)}..${Math.round(r.right)} of ${innerWidth}`); }
  }
  if (document.documentElement.scrollWidth > innerWidth) say('page-wide', document.documentElement, `${document.documentElement.scrollWidth} wide on a ${innerWidth} screen`);
  return out;
};
