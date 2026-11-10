// The live page's own script (live.php): who is on air, one of them on video with the site's own controls, a recording
// played back with its songs, and the past broadcasts, kept up to date. A file of its own, so that a browser keeps it
// between visits instead of getting it again with every page; what the server knew at page load comes in the page itself,
// in the JSON block #live-data, read once here.
const livePage = JSON.parse(document.getElementById('live-data').textContent);
// What the server knows at page load, and the page's words.
let cards = livePage.cards;
let past = livePage.past;
// The sign of that list of recordings (live_past_rev() in lib.php): a look that brings another one means the list changed.
let pastRev = livePage.past_rev;
// The live player on screen; whether a link or a click chose them (the page then stays with them
// rather than moving on to whoever else is on); the recording on screen instead, if any.
let current = livePage.current, pinned = livePage.pinned, replay = livePage.replay;
const words = livePage.words;
const el = id => document.getElementById(id);
const video = el('live-video'), msg = el('live-msg'), none = el('live-none'), wait = el('live-wait');
// What the video is attached to ('': nothing), and hls.js's object for it.
let attached = '', hls = null;
// The live player the video was last on, until the page has said that they ended.
let watching = 0;

function say(text) {
  msg.textContent = text || '';
  msg.hidden = !text;
}

// The box around the video, and the few controls a broadcast has.
const stage = el('live-stage'), ctl = el('live-ctl'), topBar = el('live-top');
const ctlPlay = el('ctl-play'), ctlMute = el('ctl-mute'), ctlVol = el('ctl-vol'), ctlFull = el('ctl-full');
const ctlSeek = el('ctl-seek'), ctlTime = el('ctl-time'), track = el('ctl-track'), bubble = el('ctl-bubble');
const ctlBack = el('ctl-back'), ctlFwd = el('ctl-fwd'), ctlRate = el('ctl-rate'), ctlStats = el('ctl-stats'), ctlPip = el('ctl-pip'), ctlWide = el('ctl-wide');
const goLive = el('go-live'), stats = el('live-stats'), ending = el('live-end'), watchBox = el('watch');
const icon = path => `<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true"><path d="${path}"/></svg>`;
const icon10 = path => `<svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor" aria-hidden="true"><path d="${path}"/><text x="12" y="16.4" text-anchor="middle" font-size="7.6" font-weight="800">10</text></svg>`;
const icons = {
  play: icon('M8 5v14l11-7z'), pause: icon('M6 5h4v14H6zM14 5h4v14h-4z'),
  again: icon('M12 5V1L7 6l5 5V7a6 6 0 1 1-6 6H4a8 8 0 1 0 8-8z'),
  sound: icon('M4 9v6h4l5 5V4L8 9zM15.5 8.5v7a4 4 0 0 0 0-7zM15.5 4.5v2.1a6 6 0 0 1 0 10.8v2.1a8 8 0 0 0 0-15z'),
  muted: icon('M4 9v6h4l5 5V4L8 9zM21 9.4 19.6 8 17.5 10.1 15.4 8 14 9.4l2.1 2.1L14 13.6l1.4 1.4 2.1-2.1 2.1 2.1 1.4-1.4-2.1-2.1z'),
  full: icon('M5 5h6v2H7v4H5zM13 5h6v6h-2V7h-4zM5 13h2v4h4v2H5zM17 13h2v6h-6v-2h4z'),
  exit: icon('M9 5h2v6H5V9h4zM13 5h2v4h4v2h-6zM5 13h6v6H9v-4H5zM13 13h6v2h-4v4h-2z'),
  // A circle turning that way with the seconds in it: two triangles would read as the previous or next song.
  back: icon10('M12 5V1.5L7 6l5 4.5V7a6 6 0 1 1-6 6H4a8 8 0 1 0 8-8z'), fwd: icon10('M12 5V1.5L17 6l-5 4.5V7a6 6 0 1 0 6 6h2a8 8 0 1 1-8-8z'),
  pip: icon('M3 5h18v14H3zm2 2v10h14V7zm6 4h7v5h-7z'), wide: icon('M3 7h18v10H3zm2 2v6h14V9z'),
  stats: icon('M11 10h2v7h-2zM11 7h2v2h-2zM12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zm0 2a7 7 0 1 1 0 14 7 7 0 0 1 0-14z'),
};
// A button's picture and its name for a screen reader and a pointer's tooltip.
function face(button, name, label) {
  button.innerHTML = icons[name];
  button.setAttribute('aria-label', label);
  button.title = label;
}
function drawControls() {
  face(ctlPlay, video.ended ? 'again' : video.paused ? 'play' : 'pause', video.paused ? words.ctl_play : words.ctl_pause);
  face(ctlMute, video.muted ? 'muted' : 'sound', video.muted ? words.ctl_unmute : words.ctl_mute);
  ctlVol.value = video.muted ? 0 : video.volume;
  ctlVol.style.setProperty('--p', `${ctlVol.value * 100}%`);
  const full = !!document.fullscreenElement;
  face(ctlFull, full ? 'exit' : 'full', full ? words.ctl_exit : words.ctl_full);
  face(ctlBack, 'back', words.ctl_back);
  face(ctlFwd, 'fwd', words.ctl_fwd);
  face(ctlStats, 'stats', words.ctl_stats);
  face(ctlPip, 'pip', words.ctl_pip);
  face(ctlWide, 'wide', words.ctl_wide);
  ctlWide.setAttribute('aria-pressed', watchBox.classList.contains('wide'));
}
// The same player for both. Live: the LIVE mark, nothing that seeks. A recording: the REPLAY mark and the timeline.
function liveMode(on) {
  ctl.hidden = topBar.hidden = false;
  track.hidden = ctlTime.hidden = on;
  for (const b of stage.querySelectorAll('.vod-only')) b.hidden = on;
  goLive.hidden = true;
  ending.hidden = true;
  // A broadcast at its own speed; a recording at the one this viewer last chose.
  video.playbackRate = on ? 1 : recordingRate;
  ctlRate.textContent = `${video.playbackRate}×`;
  stage.classList.toggle('is-live', on);
  el('top-pill').classList.toggle('replay', !on);
  el('pill-word').textContent = on ? 'LIVE' : 'REPLAY';
  stage.classList.remove('idle');
  wake();
}
// m:ss, or h:mm:ss for an hour and more.
function timeText(seconds) {
  const s = Math.max(0, Math.floor(seconds || 0)), mm = Math.floor(s / 60) % 60, ss = String(s % 60).padStart(2, '0');
  return s >= 3600 ? `${Math.floor(s / 3600)}:${String(mm).padStart(2, '0')}:${ss}` : `${mm}:${ss}`;
}
// The speed chosen for recordings, kept from one to the next.
let recordingRate = 1;
// The timeline: where it is, how far it has loaded, and the time; while dragged, where it would go.
let dragging = false;
function drawTimeline() {
  if (track.hidden) return;
  const d = video.duration;
  if (!(d > 0 && isFinite(d))) {
    ctlTime.textContent = '';
    return;
  }
  if (!dragging) ctlSeek.value = Math.round(video.currentTime / d * 1000);
  ctlSeek.style.setProperty('--p', `${ctlSeek.value / 10}%`);
  let loaded = 0;
  for (let i = 0; i < video.buffered.length; i++) {
    if (video.buffered.start(i) <= video.currentTime + 0.25 && video.currentTime < video.buffered.end(i)) loaded = video.buffered.end(i);
  }
  ctlSeek.style.setProperty('--b', `${loaded / d * 100}%`);
  ctlTime.textContent = `${timeText(dragging ? ctlSeek.value / 1000 * d : video.currentTime)} / ${timeText(d)}`;
}
for (const type of ['timeupdate', 'durationchange', 'progress', 'seeked', 'loadedmetadata', 'emptied']) video.addEventListener(type, drawTimeline);
ctlSeek.oninput = () => { dragging = true; drawTimeline(); };
ctlSeek.onchange = () => {
  dragging = false;
  if (video.duration > 0 && isFinite(video.duration)) video.currentTime = ctlSeek.value / 1000 * video.duration;
};
// A drag that ends where it began has no change event, and the timeline would stay put until the next seek. After the
// release, so that a change that does come still finds the place it was dragged to.
for (const type of ['pointerup', 'pointercancel', 'blur']) {
  ctlSeek.addEventListener(type, () => setTimeout(() => { dragging = false; drawTimeline(); }, 0));
}
// A recording's timeline in parts, one per song, with a thin cut where each begins (none at the very start, where
// the timeline begins anyway); the time before the first song, while one was being chosen, is a part as well. Under
// the pointer: its part stands out, and over it the time there with the song and its jacket.
let songMarks = [];
function drawMarks() {
  const d = video.duration, box = el('ctl-marks');
  box.replaceChildren();
  if (!(d > 0 && isFinite(d)) || !songMarks.length) return;
  const edges = [...new Set([0, ...songMarks.map(m => m.at).filter(at => at < d)])].sort((a, b) => a - b);
  edges.forEach((at, i) => {
    const part = document.createElement('i');
    part.dataset.at = at;
    part.style.left = `${at / d * 100}%`;
    part.style.width = `${((i + 1 < edges.length ? edges[i + 1] : d) - at) / d * 100}%`;
    if (at > 0) part.className = 'cut';
    box.append(part);
  });
}
video.addEventListener('durationchange', drawMarks);
const bubblePic = el('bubble-pic'), bubbleText = el('bubble-text');
track.addEventListener('pointermove', e => {
  const d = video.duration;
  if (!(d > 0 && isFinite(d))) return;
  const r = track.getBoundingClientRect(), part = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), at = part * d;
  const song = songMarks.filter(m => m.at <= at).pop();
  bubbleText.textContent = timeText(at) + (song ? `  ${song.title}` : '');
  // The jacket only for a song that has one; set again only when it is another, so that it does not flicker.
  bubblePic.hidden = !(song && song.jacket);
  if (song && song.jacket && bubblePic.getAttribute('src') !== song.jacket) bubblePic.src = song.jacket;
  bubble.hidden = false;
  // The part under the pointer: the last that begins at or before it.
  const parts = [...el('ctl-marks').children];
  const hot = parts.filter(p => Number(p.dataset.at) <= at).pop();
  for (const p of parts) p.classList.toggle('hot', p === hot);
  // Inside the picture, whatever its words: its own width says how close to the ends it may stand.
  const half = bubble.offsetWidth / 2;
  bubble.style.left = `${Math.min(r.width - half, Math.max(half, part * r.width))}px`;
});
track.addEventListener('pointerleave', () => {
  bubble.hidden = true;
  for (const p of el('ctl-marks').children) p.classList.remove('hot');
});

// A short word on the picture, for what has no place of its own: where a tap went, what the speed is now.
let flashTimer = 0;
function flash(text) {
  const f = el('live-flash');
  f.textContent = text;
  f.classList.add('on');
  clearTimeout(flashTimer);
  flashTimer = setTimeout(() => f.classList.remove('on'), 700);
}
function skip(by) {
  if (!(video.duration > 0)) return;
  video.currentTime = Math.min(video.duration, Math.max(0, video.currentTime + by));
  flash(`${by > 0 ? '+' : '−'}${Math.abs(by)}s`);
}
ctlBack.onclick = () => skip(-10);
ctlFwd.onclick = () => skip(10);
const rates = [1, 1.25, 1.5, 2, 0.75];
function nextRate() {
  const next = rates[(rates.indexOf(video.playbackRate) + 1) % rates.length];
  recordingRate = next;
  video.playbackRate = next;
  ctlRate.textContent = `${next}×`;
  flash(`${next}×`);
}
ctlRate.onclick = nextRate;
// Picture in picture, where the browser has it.
ctlPip.hidden = !(document.pictureInPictureEnabled && video.requestPictureInPicture);
ctlPip.onclick = () => {
  (document.pictureInPictureElement ? document.exitPictureInPicture() : video.requestPictureInPicture()).catch(() => {});
};
// A wide view on a large screen: the picture across the page, the lists under it. Remembered for the next visit.
function setWide(on) {
  watchBox.classList.toggle('wide', on);
  try { localStorage.setItem('opendmtq.wide', on ? '1' : ''); } catch (_) { /* No storage here. */ }
  drawControls();
}
ctlWide.onclick = () => setWide(!watchBox.classList.contains('wide'));
try { if (localStorage.getItem('opendmtq.wide')) watchBox.classList.add('wide'); } catch (_) { /* No storage here. */ }
// Connection details on the picture, once a second while they are open.
let fragRate = 0;
function drawStats() {
  if (stats.hidden) return;
  const q = video.getVideoPlaybackQuality ? video.getVideoPlaybackQuality() : null;
  const edge = attached[0] === 'p' ? liveEdge() : null;
  const lines = [[words.stats_size, video.videoWidth ? `${video.videoWidth}×${video.videoHeight}` : '–'],
    [words.stats_buffer, `${bufferLeft().toFixed(1)} s`]];
  if (fragRate) lines.push([words.stats_stream, `${(fragRate / 1e6).toFixed(1)} Mbit/s`]);
  if (hls && hls.bandwidthEstimate) lines.push([words.stats_rate, `${(hls.bandwidthEstimate / 1e6).toFixed(1)} Mbit/s`]);
  if (edge) lines.push([words.stats_behind, `${Math.max(0, edge - video.currentTime).toFixed(1)} s`]);
  if (q) lines.push([words.stats_frames, `${q.droppedVideoFrames} / ${q.totalVideoFrames}`]);
  stats.replaceChildren(...lines.flatMap(([k, v]) => {
    const dt = document.createElement('dt'), dd = document.createElement('dd');
    dt.textContent = k;
    dd.textContent = v;
    return [dt, dd];
  }));
}
ctlStats.onclick = () => { stats.hidden = !stats.hidden; ctlStats.classList.toggle('on', !stats.hidden); drawStats(); };
setInterval(drawStats, 1000);

// The controls leave the picture after a few seconds, but stay while paused or while the browser has refused sound: the
// way to the sound must never be out of reach. Any touch or movement brings them back.
let idleTimer = 0;
function wake() {
  stage.classList.remove('idle');
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => { if (!video.paused && !autoMuted) stage.classList.add('idle'); }, 3000);
}
for (const type of ['pointermove', 'pointerdown', 'focusin']) stage.addEventListener(type, wake);
// After the end of a recording, from its start.
function togglePlay() {
  if (video.ended) video.currentTime = 0;
  video.paused ? video.play().catch(() => {}) : video.pause();
}
ctlPlay.onclick = togglePlay;
// A click on the picture does the same, but a tap that only brings the controls back does nothing more. Two in quick
// succession are another thing: the full screen, or on a touch screen at the sides of a recording a jump of ten seconds.
// So a first press waits to see, and the controls it brought back take no press until then: the second must not land on
// the timeline they just put under the finger.
const twice = 320;
let wasIdle = false, tapAt = 0, tapTimer = 0, wokeTimer = 0;
stage.addEventListener('pointerdown', () => {
  wasIdle = stage.classList.contains('idle');
  if (!wasIdle) return;
  stage.classList.add('just-woke');
  clearTimeout(wokeTimer);
  wokeTimer = setTimeout(() => stage.classList.remove('just-woke'), twice + 40);
}, true);
video.addEventListener('click', e => {
  const now = performance.now();
  if (now - tapAt < twice) {
    clearTimeout(tapTimer);
    tapAt = 0;
    if (!replay || !matchMedia('(pointer: coarse)').matches) { ctlFull.click(); return; }
    const r = video.getBoundingClientRect(), x = (e.clientX - r.left) / r.width;
    if (x < 0.42) skip(-10); else if (x > 0.58) skip(10); else ctlFull.click();
    return;
  }
  tapAt = now;
  if (!wasIdle) tapTimer = setTimeout(togglePlay, twice);
});
// The usual keys, unless a link or a button has them for itself. The player's own sliders are no exception: having
// just been used, they have the focus, and the keys must go on working. By the key's place and not its letter: with
// Korean input on, or Caps Lock, the letters are other ones.
document.addEventListener('keydown', e => {
  if (!attached || e.altKey || e.ctrlKey || e.metaKey) return;
  const on = e.target.tagName, slider = e.target === ctlSeek || e.target === ctlVol;
  if ((on === 'INPUT' && !slider) || on === 'TEXTAREA' || on === 'SELECT') return;
  // On the volume slider the arrow keys are its own.
  const seeks = replay && e.target !== ctlVol;
  // A key held down repeats: fine for a seek, not for what switches something on and off.
  if (e.repeat && !['ArrowLeft', 'ArrowRight', 'KeyJ', 'KeyL'].includes(e.code)) return;
  if (e.code === 'Space' && on !== 'BUTTON' && on !== 'A' && on !== 'SUMMARY') togglePlay();
  else if (e.code === 'ArrowLeft' && seeks) skip(-5);
  else if (e.code === 'ArrowRight' && seeks) skip(5);
  else if (e.code === 'KeyJ' && replay) skip(-10);
  else if (e.code === 'KeyL' && replay) skip(10);
  else if (e.code === 'KeyK') togglePlay();
  else if (e.code === 'KeyM') ctlMute.click();
  else if (e.code === 'KeyF') ctlFull.click();
  else if (e.code === 'KeyI') ctlStats.click();
  else if (e.code === 'KeyT') ctlWide.click();
  else if (e.code === 'KeyS' && replay) nextRate();
  else return;
  e.preventDefault();
  wake();
});
ctlMute.onclick = () => { video.muted = !video.muted; if (!video.muted && !video.volume) video.volume = 1; };
ctlVol.oninput = () => { video.volume = Number(ctlVol.value); video.muted = !video.volume; };
ctlFull.onclick = () => {
  if (document.fullscreenElement) return document.exitFullscreen();
  // The box, so that the controls come along. An iPhone can only do it with the video alone.
  if (stage.requestFullscreen) {
    // The game is wide: a phone held upright would show a strip in the middle of its screen. Only a phone can do this.
    return stage.requestFullscreen().then(() => screen.orientation.lock('landscape')).catch(() => {});
  }
  if (video.webkitEnterFullscreen) video.webkitEnterFullscreen();
};
document.addEventListener('fullscreenchange', () => {
  if (!document.fullscreenElement && screen.orientation && screen.orientation.unlock) {
    try { screen.orientation.unlock(); } catch (_) { /* Not a phone. */ }
  }
});
// A phone turned on its side has room for the picture alone: the page brings it into view, with its controls.
const sideways = window.matchMedia('(orientation: landscape) and (max-height: 500px)');
const toPicture = () => { if (sideways.matches && attached && !document.fullscreenElement) stage.scrollIntoView({ block: 'center' }); };
sideways.addEventListener('change', toPicture);
// The level a viewer chose, for the next stream and the next visit. Only a convenience: the page works without it.
try {
  const level = Number(localStorage.getItem('opendmtq.volume'));
  if (level > 0 && level <= 1) video.volume = ctlVol.value = level;
} catch (_) { /* No storage here. */ }
video.addEventListener('volumechange', () => {
  try { if (video.volume > 0) localStorage.setItem('opendmtq.volume', video.volume); } catch (_) { /* No storage here. */ }
});
document.addEventListener('fullscreenchange', () => { drawControls(); wake(); });
for (const type of ['play', 'pause', 'volumechange', 'ended']) video.addEventListener(type, () => { drawControls(); wake(); });

// Where "now" is for a broadcast, as near as the stream allows: hls.js says, Safari's own player from
// the end of what it can seek to, as far back as hls.js would stay (two segments).
function liveEdge() {
  if (hls) return hls.liveSyncPosition;
  const s = video.seekable;
  return s.length ? s.end(s.length - 1) - 4 : null;
}
function toLiveEdge() {
  const edge = liveEdge();
  if (edge) video.currentTime = edge;
}
// How much video is ready to play from where it is now, in seconds.
function bufferLeft() {
  for (let i = 0; i < video.buffered.length; i++) {
    if (video.buffered.start(i) <= video.currentTime + 0.25 && video.currentTime < video.buffered.end(i)) return video.buffered.end(i) - video.currentTime;
  }
  return 0;
}
// Is this point of the stream already here? A viewer whose connection is slower than the stream does not
// have it, and a jump there would throw away what is playing and wait for it.
function isBuffered(at) {
  for (let i = 0; i < video.buffered.length; i++) {
    if (video.buffered.start(i) <= at && at < video.buffered.end(i)) return true;
  }
  return false;
}
// Back to now after a stall. That point itself moves in steps of a segment as the playlist updates, so
// a little under two segments behind it (about three and a half behind the stream) is really behind, and
// a jump gets a few seconds to take effect before the next.
let lastJump = 0;
setInterval(() => {
  if (attached[0] !== 'p' || video.paused || video.seeking) return;
  // The one on screen left the list and what was buffered has played out: this says so.
  if (!cards.some(x => x.id === current) && bufferLeft() < 0.5) { show(); return; }
  if (Date.now() - lastJump < 6000) return;
  // Phones send two-second segments (docs/live.md).
  const edge = liveEdge();
  if (edge && edge - video.currentTime > 2 * 1.75 && isBuffered(edge)) {
    lastJump = Date.now();
    video.currentTime = edge;
  }
  // Further behind than that and not here yet (a slow connection): the viewer can choose to skip ahead.
  goLive.hidden = !(edge && edge - video.currentTime > 8);
}, 1000);
goLive.onclick = () => { lastJump = Date.now(); toLiveEdge(); goLive.hidden = true; };
// After a pause, now as well: a broadcast does not continue from where it was left. Only then, and only if that is a real
// step: at the first start or a step of a moment, a seek would only break the sound that has just begun.
let pausedByViewer = false;
video.addEventListener('pause', () => { pausedByViewer = attached[0] === 'p'; stage.classList.add('paused'); });
video.addEventListener('play', () => {
  stage.classList.remove('paused');
  if (attached[0] !== 'p' || !pausedByViewer) return;
  pausedByViewer = false;
  const edge = liveEdge();
  if (edge && edge - video.currentTime > 1) toLiveEdge();
});
drawControls();

// Detach from the stream: the video stops, and the next look at the list may attach again.
let autoMuted = false;
let lastRecovery = 0;
let retryTimer = 0;
let startTimer = 0;
function detach() {
  el('live-muted').hidden = true;
  // What the browser refused for one stream it may allow for the next, chosen with a tap; if not, start() says so again.
  if (autoMuted) video.muted = false;
  clearTimeout(retryTimer);
  clearTimeout(startTimer);
  autoMuted = false;
  pausedByViewer = false;
  stage.classList.remove('waiting');
  if (hls) { hls.destroy(); hls = null; }
  video.removeAttribute('src');
  video.load();
  attached = '';
}
// A stream beyond repair: the page says so and tries again in a moment, while it is on the list.
let retryAt = 0;
function broken() {
  savePlace(true);
  detach();
  retryAt = Date.now() + 3000;
  show();
  retryTimer = setTimeout(show, 3100);
}

// Seconds of a recording fetched ahead of where it plays.
const recordingAhead = 10;
// Since when the network has failed this stream (0: it has not). With what is in hand played out, the picture says so.
let lostAt = 0;
setInterval(() => {
  el('live-lost').hidden = !(lostAt && performance.now() - lostAt > 3000 && bufferLeft() < 0.5);
}, 1000);

// Where this viewer left a recording: on this device, a convenience only. Near its start or end there is nothing to
// come back to.
const placeKey = key => `opendmtq.pos.${key}`;
function savedPlace(key) {
  try { return Number(JSON.parse(localStorage.getItem(placeKey(key)) || '{}').at) || 0; } catch (_) { return 0; }
}
function savedPart(key) {
  try { return Number(JSON.parse(localStorage.getItem(placeKey(key)) || '{}').part) || 0; } catch (_) { return 0; }
}
let lastSave = 0;
function savePlace(force) {
  if (attached[0] !== 'r' || !(video.duration > 0)) return;
  const now = Date.now();
  if (!force && now - lastSave < 4000) return;
  lastSave = now;
  const key = attached.slice(1), at = video.currentTime, part = at / video.duration;
  try {
    if (at < 10 || video.duration - at < 12) localStorage.removeItem(placeKey(key));
    else localStorage.setItem(placeKey(key), JSON.stringify({ at, part }));
  } catch (_) { /* No storage here. */ }
}
video.addEventListener('timeupdate', () => savePlace(false));
video.addEventListener('pause', () => savePlace(true));
addEventListener('pagehide', () => savePlace(true));
let resumeTimer = 0;
function offerResume(at) {
  el('live-resume').hidden = !at;
  clearTimeout(resumeTimer);
  if (!at) return;
  el('resume-word').textContent = words.resume.replace('{time}', timeText(at));
  resumeTimer = setTimeout(() => { el('live-resume').hidden = true; }, 8000);
}
el('resume-restart').onclick = () => { video.currentTime = 0; el('live-resume').hidden = true; };

// key says what is attached: 'p<guid>' or 'r<recording>'.
function attach(key, url) {
  detach();
  // Start with sound; a browser that refuses that (no click on this page yet) starts muted. Only that refusal:
  // a play() cut short by the next stream being chosen says nothing about sound.
  const start = () => video.play().catch(e => {
    if (e.name !== 'NotAllowedError') return;
    autoMuted = video.muted = true;
    video.play().catch(() => {});
  });
  if (window.Hls && Hls.isSupported()) {
    // Further behind than a dozen segments (a slow connection), hls.js itself goes back to now. A recording has
    // minutes ahead of it, and left alone hls.js fetches half a minute of it as fast as the network goes, right
    // as the sound starts. So it keeps less in hand.
    const recording = key[0] === 'r';
    // What has played does not stay in memory for ever: on a phone a long broadcast would fill what the browser allows.
    // A recording keeps a minute to go back in without asking; its segments also stay in the browser's cache.
    const resume = recording ? savedPlace(key.slice(1)) : 0;
    // The sound is AAC-LC: the runtime on every phone encodes it so (arm32/src/live.cpp). The playlist names no
    // codecs, and without this hls.js labels the sound HE-AAC for Chrome and fills a gap in it (a stream's sound
    // starts a moment after its picture) with HE-AAC silence. That turns the browser's decoder to HE-AAC: all the
    // sound after it comes out garbled while the picture plays on, until the page is loaded again.
    const sound = { defaultAudioCodec: 'mp4a.40.2' };
    hls = new Hls(recording ? { ...sound, maxBufferLength: recordingAhead, maxMaxBufferLength: recordingAhead * 2, backBufferLength: 60, startPosition: resume || -1 }
      : { ...sound, liveSyncDurationCount: 2, liveMaxLatencyDurationCount: 12, backBufferLength: 20 });
    fragRate = 0;
    hls.on(Hls.Events.FRAG_LOADED, (_, d) => { if (d.frag.duration) fragRate = d.frag.stats.total * 8 / d.frag.duration; });
    offerResume(resume);
    hls.loadSource(url);
    hls.attachMedia(video);
    // Playing starts with a few seconds in hand, or after a while with what there is: started on the first segment
    // that arrives, over a connection not warmed up yet, it would stop again and again until the buffer caught up.
    // A recording waits for that whole stretch, so the fetching is over before the sound begins, unless that is
    // taking a while: then the network is what paces the fetching. What is in hand can start a little after the 0
    // that play() asks for; hls.js would stall there and seek over the hole with the sound already on its way, so
    // the player starts where the media does.
    const attachedAt = performance.now();
    let started = false;
    const begin = () => {
      if (started) return;
      started = true;
      clearTimeout(startTimer);
      const have = video.buffered;
      if (have.length && video.currentTime < have.start(0)) video.currentTime = have.start(0);
      // Sound starts once the page is done with its own start-up work, so that nothing holds up its first moments.
      if (window.requestIdleCallback) requestIdleCallback(start, { timeout: 400 }); else start();
    };
    stage.classList.add('waiting');
    startTimer = setTimeout(begin, 6000);
    hls.on(Hls.Events.FRAG_BUFFERED, () => {
      // The network is back.
      lostAt = 0;
      el('live-lost').hidden = true;
      const left = bufferLeft();
      if (left >= 3 && (!recording || left >= recordingAhead - 2 || performance.now() - attachedAt > 1500)) begin();
    });
    hls.on(Hls.Events.ERROR, (_, d) => {
      if (!d.fatal) return;
      const mine = hls;
      // The network dropped, or the stream's list is gone for now. What is buffered keeps playing while this asks again,
      // for a recording as for a broadcast: the box, the place and what is in hand all stay, and the picture says so
      // once it has run out. Whether a broadcast really ended is for the next look at the list to say. With no list yet
      // (it failed on the way in) only asking for it from the start brings anything.
      if (d.type === Hls.ErrorTypes.NETWORK_ERROR) {
        clearTimeout(retryTimer);
        lostAt = lostAt || performance.now();
        retryTimer = setTimeout(() => {
          if (hls !== mine) return;
          if (mine.levels && mine.levels.length) mine.startLoad(key[0] === 'r' ? video.currentTime : -1); else mine.loadSource(url);
        }, 2000);
      } else if (d.type === Hls.ErrorTypes.MEDIA_ERROR && Date.now() - lastRecovery > 10000) {
        // Once in a while the decoder can be brought back; a stream that keeps failing starts over.
        lastRecovery = Date.now();
        mine.recoverMediaError();
      } else {
        broken();
      }
    });
  } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
    // Safari plays HLS itself.
    video.src = url;
    const resume = key[0] === 'r' ? savedPlace(key.slice(1)) : 0;
    if (resume) video.addEventListener('loadedmetadata', () => { video.currentTime = resume; }, { once: true });
    offerResume(resume);
    start();
  } else {
    say(words.unsupported);
    return;
  }
  attached = key;
  goneShown = false;
  lostAt = 0;
  el('live-lost').hidden = true;
  liveMode(key[0] === 'p');
  toPicture();
}
// Safari's own player: nothing to retry inside, so the whole stream again in a moment.
video.addEventListener('error', () => { if (attached && !hls && video.error) broken(); });
// Video late: the picture alone would look frozen.
video.addEventListener('waiting', () => { if (attached) stage.classList.add('waiting'); });
// Paused while it waited: nothing would say the wait is over until it plays again.
for (const type of ['playing', 'seeked', 'pause']) video.addEventListener(type, () => stage.classList.remove('waiting'));

// The page changes what it shows without reloading: the language keys and the sign-in link come back to what is on
// screen now, not to what the page was opened for.
function keepPlace() {
  for (const a of document.querySelectorAll('.bar-end a[href*="next="]')) {
    const to = new URL(a.href);
    to.searchParams.set('next', location.pathname + location.search);
    a.href = to;
  }
}

// Who this is, on the picture and under it. Only a broadcast has a running time.
let onAirSince = 0, captionDoing = '';
function caption(c, live) {
  el('live-info').hidden = !c;
  onAirSince = live && c ? liveThumbs.since(c) : 0;
  el('live-clock').textContent = liveThumbs.airTime(onAirSince);
  if (!c) return;
  const profile = `/opendmtq/player.php?id=${c.id}`;
  el('top-who').textContent = el('info-name').textContent = c.name;
  // A recording's songs all at once; while one of them plays, that one instead (see the time's handler below).
  captionDoing = c.doing;
  el('top-what').textContent = el('info-doing').textContent = c.doing;
  for (const id of ['info-name', 'info-profile']) el(id).href = profile;
  el('info-profile').setAttribute('aria-label', words.profile.replace('{name}', c.name));
}
setInterval(() => { el('live-clock').textContent = liveThumbs.airTime(onAirSince); }, 1000);

// A recording's songs under the picture, each a jump to where it begins, the one playing marked.
// An empty picture for a song without a jacket, as the rest of the site uses.
const BLANK = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
let chaptersFor = '';
function drawChapters(r) {
  const key = r ? r.key : '';
  if (key === chaptersFor) return;
  chaptersFor = key;
  songMarks = r ? r.songs.filter(x => x.at >= 0) : [];
  drawMarks();
  el('live-chapters').hidden = !r || !r.songs.length;
  el('chapter-list').replaceChildren(...(r ? r.songs : []).map(x => {
    const li = document.createElement('li'), b = document.createElement('button');
    b.type = 'button';
    b.dataset.at = x.at;
    b.disabled = x.at < 0;
    const time = document.createElement('span'), name = document.createElement('b'), chart = document.createElement('span');
    time.className = 'ch-time'; time.textContent = x.at >= 0 ? timeText(x.at) : '';
    // The song's jacket between the time and the name; a song with no picture keeps the dark square.
    const pic = document.createElement('img');
    pic.className = 'ch-jacket'; pic.alt = ''; pic.loading = 'lazy'; pic.width = pic.height = 36;
    pic.onerror = () => { pic.onerror = null; pic.src = BLANK; };
    pic.src = x.jacket || BLANK;
    name.textContent = x.title;
    // The chart in the colour the game gives its difficulty, as on the song's page.
    chart.className = x.sig >= 0 ? `ch-chart sig${x.sig}` : 'ch-chart'; chart.textContent = x.chart;
    b.append(time, pic, name, chart);
    b.onclick = () => { video.currentTime = x.at; if (video.paused) video.play().catch(() => {}); };
    li.append(b);
    return li;
  }));
}
video.addEventListener('timeupdate', () => {
  if (!songMarks.length) return;
  const t = video.currentTime, now = songMarks.filter(m => m.at <= t + 0.5).pop();
  // How far into the song playing: from where it begins to where the next one does (or the end).
  const next = now ? songMarks.find(m => m.at > now.at) : null, end = next ? next.at : video.duration;
  const share = now && end > now.at ? Math.min(1, Math.max(0, (t - now.at) / (end - now.at))) : 0;
  for (const b of el('chapter-list').querySelectorAll('button')) {
    const on = !!now && Number(b.dataset.at) === now.at;
    b.classList.toggle('on', on);
    b.style.setProperty('--done', on ? `${(share * 100).toFixed(1)}%` : '0%');
  }
  // Under the picture, and on it in full screen: the song playing and its chart; between songs, all of them.
  const words = now ? `${now.title} · ${now.chart}` : captionDoing;
  if (el('info-doing').textContent !== words) el('top-what').textContent = el('info-doing').textContent = words;
});
// Copying this page's address; over plain HTTP the browser only has the older way.
el('info-share').onclick = async e => {
  // The one on screen, by name: a bare address would show a friend whoever is first on air then.
  const b = e.currentTarget, url = replay || !current ? location.href : `${location.origin}${location.pathname}?p=${current}`;
  try {
    await navigator.clipboard.writeText(url);
  } catch (_) {
    const box = document.createElement('textarea');
    box.value = url;
    document.body.append(box);
    box.select();
    document.execCommand('copy');
    box.remove();
  }
  b.textContent = b.dataset.done;
  setTimeout(() => { b.textContent = words.share; }, 1600);
};

// Everything on the page from what is known now; the video follows.
let goneShown = false;
// Who was on screen, and whose broadcast has just ended there.
let watchingName = '', endedName = '';
function show() {
  const r = replay ? past.find(x => x.key === replay) : null;
  // The heading says what this is, also while the page says the recording is gone, and so does the tab, with whose it is.
  const isReplay = !!(replay || goneShown);
  el('mast').classList.toggle('is-replay', isReplay);
  el('mast').querySelector('.word').textContent = isReplay ? 'REPLAY' : 'LIVE';
  const whose = r ? r.name : (cards.find(x => x.id === current) || {}).name;
  document.title = `${whose ? `${whose} · ` : ''}${isReplay ? words.replay : attached[0] === 'p' || whose ? 'LIVE' : words.title} · OpenDMTQ`;
  // Hidden or deleted while on screen, or a link to one that is gone.
  if (replay && !r) {
    detach();
    replay = '';
    goneShown = true;
    say(words.gone);
  }
  let c = cards.find(x => x.id === current);
  // Nobody chosen, or the chosen one left: the next one on, if any.
  if (!r && !c && !attached && !pinned && !watching && cards.length) {
    current = cards[0].id;
    c = cards[0];
  }
  drawChapters(r);
  if (r) {
    say(Date.now() < retryAt && attached !== 'r' + r.key ? words.reconnecting : '');
    caption(r, false);
    if (attached !== 'r' + r.key && Date.now() >= retryAt) {
      attach('r' + r.key, `/opendmtq/live-media.php/rec/${r.key.replace('-', '/')}/index.m3u8`);
      watching = 0;
    }
  } else {
    // Back from a recording to the page of who is on: it does not go on playing under another heading.
    if (attached[0] === 'r') detach();
    caption(c, true);
    if (c) say(Date.now() < retryAt && attached !== 'p' + c.id ? words.reconnecting : '');
    if (c && attached !== 'p' + c.id && Date.now() >= retryAt) {
      attach('p' + c.id, `/opendmtq/live-media.php/${c.id}/index.m3u8`);
      watching = c.id;
      watchingName = c.name;
    }
    // The one being watched is gone: what is buffered plays out, then the page says they ended. A
    // stream cut off (the owner switched it off) has no video left to wait for.
    if (!c && watching && (!attached || video.ended || video.paused || bufferLeft() < 0.5)) {
      endedName = watchingName;
      detach();
      watching = 0;
      // Nobody in particular was chosen and somebody else is on: straight on to them, with the box staying in place.
      if (!pinned && cards.length) { endedName = ''; return show(); }
      // Its recording is about to appear: a look now, whose sign of the list says when it has.
      look();
    }
  }
  if (c || r) endedName = '';
  // The page no longer has anything to show in full screen: back to the page itself, or the browser stays there.
  if (!attached && document.fullscreenElement) document.exitFullscreen().catch(() => {});
  video.hidden = stage.hidden = !attached;
  watchBox.classList.toggle('has-player', !!attached);
  // A link's player off air: the page says it waits for them. Otherwise "nobody" only with nothing
  // else to see or read.
  el('live-ended').hidden = !endedName || !!attached;
  if (endedName) el('ended-word').textContent = words.ended_of.replace('{name}', endedName);
  const waiting = pinned && !r && !c && !attached && msg.hidden;
  if (wait) wait.hidden = !waiting;
  none.hidden = cards.length > 0 || !!attached || !msg.hidden || waiting || !!endedName;
  // The others on air.
  const others = cards.filter(x => r || x.id !== current);
  el('live-others').hidden = others.length === 0;
  // Who can be picked from the past broadcasts: every player in them.
  drawWho();
  liveThumbs.render(el('live-list'), others, x => e => {
    // Held down, or the middle button: a new tab is what is asked for.
    if (e.ctrlKey || e.metaKey || e.shiftKey || e.button) return;
    e.preventDefault();
    // Each its own step, so that Back goes through what was watched.
    history.pushState(null, '', `?p=${x.id}`);
    keepPlace();
    replay = '';
    current = x.id;
    pinned = true;
    retryAt = 0;
    clearTimeout(retryTimer);
    show();
    window.scrollTo(0, 0);
  });
  if (others.length) liveThumbs.takePictures(others, el('live-list'));
  // The past broadcasts.
  drawPast();
}

// The past broadcasts as cards: the first song's jacket, how long, how far this viewer got, who, what, when. A search
// and a choice of player narrow them down here in the page.
const pastSearch = el('past-search'), pastWho = el('past-who');
// A player asked for in the address (their page leads here so): chosen once, as soon as their name is on the list.
let whoAsked = new URLSearchParams(location.search).get('who') || '';
function drawWho() {
  const names = [...new Map(past.map(x => [x.id, x.name])).entries()];
  const have = [...pastWho.options].slice(1).map(o => o.value).join();
  if (have === names.map(n => n[0]).join()) return;
  const keep = pastWho.value;
  pastWho.replaceChildren(pastWho.options[0], ...names.map(([id, name]) => {
    const o = document.createElement('option');
    o.value = id;
    o.textContent = name;
    return o;
  }));
  pastWho.value = keep;
  if (whoAsked && [...pastWho.options].some(o => o.value === whoAsked)) {
    pastWho.value = whoAsked;
    whoAsked = '';
  }
}
function pastCard(x) {
  const li = document.createElement('li'), a = document.createElement('a');
  a.href = `?r=${x.key}`;
  a.dataset.key = x.key;
  a.className = 'past' + (x.key === replay ? ' on' : '');
  const pic = document.createElement('span');
  pic.className = 'past-pic';
  if (x.pic) {
    const img = document.createElement('img');
    img.src = x.pic;
    img.alt = '';
    img.loading = 'lazy';
    img.decoding = 'async';
    img.onerror = () => img.remove();
    pic.append(img);
  }
  const len = document.createElement('span');
  len.className = 'past-len';
  len.textContent = x.length;
  pic.append(len);
  const part = savedPart(x.key);
  if (part > 0) {
    const bar = document.createElement('i');
    bar.className = 'past-seen';
    bar.style.width = `${Math.round(part * 100)}%`;
    pic.append(bar);
  }
  const text = document.createElement('span');
  text.className = 'past-text';
  // How long ago, as the other pages say it, with the date itself under the pointer.
  for (const [tag, cls, words_, full] of [['b', 'who', x.name, ''], ['span', 'doing', x.doing, x.find], ['span', 'past-when', x.ago, x.when]]) {
    const part_ = document.createElement(tag);
    part_.className = cls;
    part_.textContent = words_;
    if (full) part_.title = full;
    text.append(part_);
  }
  a.append(pic, text);
  a.onclick = e => {
    // Held down, or the middle button: a new tab is what is asked for.
    if (e.ctrlKey || e.metaKey || e.shiftKey || e.button) return;
    e.preventDefault();
    goRecording(x.key);
  };
  li.append(a);
  return li;
}
// On to a recording, in this page. Another choice owes nothing to the trouble of the one before.
function goRecording(key) {
  history.pushState(null, '', `?r=${key}`);
  keepPlace();
  replay = key;
  retryAt = 0;
  clearTimeout(retryTimer);
  show();
  window.scrollTo(0, 0);
}
// What the page came with from the server is already what would be drawn. How many a look shows: more when asked for.
const pastStep = 24;
let pastShown = pastStep;
let pastDrawn = JSON.stringify(past.slice(0, pastStep).map(x => x.key));
function drawPast() {
  el('live-past').hidden = past.length === 0;
  const q = pastSearch.value.trim().toLowerCase(), who = pastWho.value;
  // Every song of a recording counts, not only the three that fit on its card.
  const list = past.filter(x => (!who || String(x.id) === who) && (!q || `${x.name} ${x.find || x.doing} ${x.when}`.toLowerCase().includes(q)));
  const shown = list.slice(0, pastShown);
  el('past-more').hidden = list.length <= pastShown;
  el('past-none').hidden = list.length > 0;
  el('past-count').textContent = list.length === past.length ? past.length : `${list.length} / ${past.length}`;
  // Only when the list changed: built anew at every look, it would lose the keyboard's place and a press held on a card.
  const drawn = JSON.stringify(shown.map(x => x.key));
  if (drawn !== pastDrawn) {
    pastDrawn = drawn;
    el('past-list').replaceChildren(...shown.map(pastCard));
  }
  // The one on screen is marked in place, for the same reason.
  for (const a of el('past-list').querySelectorAll('.past')) a.classList.toggle('on', a.dataset.key === replay);
}
el('past-more').querySelector('button').onclick = () => { pastShown += pastStep; drawPast(); };
pastSearch.addEventListener('input', drawPast);
pastWho.addEventListener('change', drawPast);
// Back and forward between what was watched.
addEventListener('popstate', () => {
  const q = new URLSearchParams(location.search);
  replay = q.get('r') || '';
  // The player in the address, if any, is the one on screen again; without one, whoever is first on.
  const p = Number(q.get('p')) || 0;
  if (p) current = p;
  pinned = !!p;
  retryAt = 0;
  keepPlace();
  show();
});

// The box takes the shape of what plays: phones stream wider than 16:9 (style.css has the usual one).
video.addEventListener('resize', () => {
  if (video.videoWidth && video.videoHeight) stage.style.setProperty('--ar', video.videoWidth / video.videoHeight);
});

// A browser that refused sound said nothing: the page does, until the sound is on. A viewer's own mute
// needs no explaining.
const mutedNote = () => {
  if (!video.muted) autoMuted = false;
  el('live-muted').hidden = !attached || !autoMuted;
};
video.addEventListener('playing', mutedNote);
video.addEventListener('volumechange', mutedNote);

// A stream that ran out of video.
video.addEventListener('ended', () => {
  // A recording stops on its last picture: play it again, or go on to the next one.
  if (replay) {
    const at = past.findIndex(x => x.key === replay), next = past[at + 1];
    el('end-next').hidden = !next;
    if (next) {
      el('end-next').href = `?r=${next.key}`;
      // Held down, or the middle button: a new tab is what is asked for. Otherwise on in this page.
      el('end-next').onclick = e => { if (e.ctrlKey || e.metaKey || e.shiftKey || e.button) return; e.preventDefault(); goRecording(next.key); };
    }
    el('live-resume').hidden = true;
    ending.hidden = false;
    savePlace(true);
    return;
  }
  detach();
  // Whatever the last look at the list said: attaching again would replay the last segments.
  cards = cards.filter(c => c.id !== current);
  show();
});

el('end-again').onclick = () => { ending.hidden = true; video.currentTime = 0; video.play().catch(() => {}); };
video.addEventListener('play', () => { ending.hidden = true; });
// Back from the end by the keys or the timeline: the buttons for the end leave, and the play button is itself again.
video.addEventListener('seeking', () => { if (!video.ended) { ending.hidden = true; drawControls(); } });

// Who is on, every few seconds, with the sign of the list of recordings; the list itself, which costs the server a file
// per recording and a viewer some 60 KB at 300 of them, only when that sign says it changed (it was every half minute, 7 MB
// an hour per open page). A tab out of sight with nothing playing asks nothing, and catches up when it is looked at again.
let looking = false, pastWanted = false;
function look() {
  if (looking || (document.hidden && (video.paused || !attached))) return;
  // One at a time: a slow answer must not arrive after, and overwrite, a newer one.
  looking = true;
  const withPast = pastWanted;
  // Signed out meanwhile (here or in another tab): the page itself asks for the sign-in. Any other failure
  // is the network's: what is on screen stays, and the next look decides.
  fetch(withPast ? '?list=1&past=1' : '?list=1').then(r => {
    if (r.status === 401 || r.status === 403) { location.reload(); return Promise.reject(); }
    return r.ok ? r.json() : Promise.reject();
  }).then(l => {
    // Broadcasts turned off for the server meanwhile: the page as it is now says so.
    if (l.off) { location.reload(); return; }
    cards = l.live;
    if (l.past) {
      // The list, with the sign of that very list: the next looks compare against it.
      past = l.past;
      pastRev = l.past_rev;
      pastWanted = false;
    } else if (l.past_rev !== pastRev) {
      // A recording ended, or one was hidden, shown again or deleted: the list, right after this look.
      pastWanted = true;
    }
    show();
    liveThumbs.headerCount(cards.length, words);
  }).catch(() => {}).finally(() => {
    looking = false;
    // The list asked for at once, once: a look for it that failed waits for the next turn like any other.
    if (pastWanted && !withPast) look();
  });
}
setInterval(look, 5000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) look(); });
show();
