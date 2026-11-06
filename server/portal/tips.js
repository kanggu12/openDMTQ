// One tooltip for every mark with data-tip, under the pointer or the finger. Its words go in as text.
(() => {
  const box = document.createElement('div');
  box.className = 'chart-tip';
  box.hidden = true;
  document.body.append(box);
  const answer = e => {
    const t = e.target.closest && e.target.closest('[data-tip]');
    if (!t) { box.hidden = true; return; }
    box.textContent = t.dataset.tip;
    box.hidden = false;
    const w = box.offsetWidth, h = box.offsetHeight;
    box.style.left = `${Math.min(innerWidth - w - 8, Math.max(8, e.clientX - w / 2))}px`;
    box.style.top = `${e.clientY - h - 12 < 4 ? e.clientY + 18 : e.clientY - h - 12}px`;
  };
  document.addEventListener('pointermove', answer, { passive: true });
  // A finger only ever presses: the press does what moving over it does with a mouse, and leaves the words up to be read.
  document.addEventListener('pointerdown', answer, { passive: true });
  addEventListener('scroll', () => { box.hidden = true; }, { passive: true });
})();
