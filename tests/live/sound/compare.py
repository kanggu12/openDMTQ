"""What a viewer heard against what the recording holds, sample by sample.

Walks the captured sound in small steps and asks of each short block where in the recording it came from. A clean playback
has one constant offset and matches almost to the bit, since the browser decodes with the same decoder as the reference.
Anything else is a fault with a time: a jump (samples skipped or repeated), a hole (silence where the recording has sound),
garbage (nothing in the recording looks like it). Usage: compare.py <heard.raw> <reference.raw> (16-bit stereo, 48 kHz).
"""

import sys

import numpy as np

RATE = 48000
# 20 ms blocks, a new one every 5 ms: a fault shorter than a block still spoils a few of them.
BLOCK = 960
STEP = 240
# Below this a block counts as silence (full scale is 32767).
SILENT = 30
# A block this much alike is the same sound: decoding differences are far smaller, and any real fault far larger.
SAME = 0.97
# The last moments of the capture hold the browser closing, not the playback: on a busy machine the close took longer than
# a second, and the silence after it was read as a hole in the playback.
TAIL = 3 * RATE


def load(path):
    """A raw file as one channel, as floats."""
    data = np.fromfile(path, dtype=np.int16)
    # A capture stopped by a signal can end halfway through a frame.
    data = data[: len(data) // 2 * 2].reshape(-1, 2).astype(np.float64)
    return data.mean(axis=1)


def best_place(block, reference, low, high):
    """Where in reference[low:high] the block fits best, and how well (normalised correlation)."""
    low = max(low, 0)
    high = min(high, len(reference) - len(block))
    if high <= low:
        return None, 0.0
    part = reference[low: high + len(block)]
    size = int(2 ** np.ceil(np.log2(len(part) + len(block))))
    # Correlation at every offset at once, through the FFT.
    product = np.fft.rfft(part, size) * np.conj(np.fft.rfft(block, size))
    correlation = np.fft.irfft(product, size)[: high - low]
    # The energy of the reference under the block at each offset, for the normalising.
    running = np.cumsum(np.concatenate(([0.0], part ** 2)))
    energy = running[len(block): len(block) + (high - low)] - running[: high - low]
    score = correlation / np.sqrt(np.maximum(energy, 1.0) * max((block ** 2).sum(), 1.0))
    place = int(np.argmax(score))
    return low + place, float(score[place])


def faults_in(heard, reference):
    """(faults, median likeness, seconds compared). A fault is (seconds after the first sound, kind, detail)."""
    sounding = np.nonzero(np.abs(heard) > SILENT)[0]
    if not len(sounding):
        return [(0.0, "nothing heard", 0)], 0.0, 0.0
    first = int(sounding[0])
    # The first lock: half a second in, anywhere in the recording.
    probe = first + RATE // 2
    place, _ = best_place(heard[probe: probe + 8192], reference, 0, len(reference))
    if place is None:
        return [(0.0, "too short", 0)], 0.0, 0.0
    offset = place - probe
    faults, alike = [], []
    position = first
    end = len(heard) - TAIL
    while position + BLOCK <= end:
        block = heard[position: position + BLOCK]
        there = position + offset
        # Past the end of the recording: nothing to compare with.
        if there < 0 or there + BLOCK > len(reference):
            break
        expected = reference[there: there + BLOCK]
        block_level = np.sqrt((block ** 2).mean())
        expected_level = np.sqrt((expected ** 2).mean())
        when = (position - first) / RATE
        if block_level < SILENT:
            # Silence is only wrong where the recording has sound.
            if expected_level >= SILENT:
                faults.append((when, "hole", 0))
        else:
            scale = np.sqrt((block ** 2).sum() * (expected ** 2).sum())
            likeness = float((block * expected).sum() / scale) if scale else 0.0
            if likeness > SAME:
                alike.append(likeness)
            else:
                # Not what should come here: from somewhere else nearby (a jump), or from nowhere.
                place, score = best_place(block, reference, there - 2 * RATE, there + 2 * RATE)
                if place is not None and score > SAME and place != there:
                    faults.append((when, "jump", round((place - there) / RATE * 1000, 1)))
                    offset = place - position
                else:
                    faults.append((when, "garbage", round(likeness, 3)))
        position += STEP
    return merged(faults), float(np.median(alike)) if alike else 0.0, (position - first) / RATE


def merged(faults):
    """Runs of one kind as one fault: a hole of 100 ms spoils twenty blocks."""
    runs = []
    for when, kind, detail in faults:
        if runs and runs[-1][1] == kind and kind != "jump" and when - runs[-1][3] <= 2 * STEP / RATE:
            runs[-1][3] = when
        else:
            runs.append([when, kind, detail, when])
    return [(round(r[0], 3), r[1], r[2] if r[1] == "jump" else round((r[3] - r[0]) * 1000 + BLOCK / RATE * 1000)) for r in runs]


def self_test(reference):
    """This comparison finds what it is for: damage made on purpose, each kind where it was put."""
    start = RATE
    clean = reference[start: start + 12 * RATE].copy()
    if faults_in(np.concatenate((clean, np.zeros(TAIL))), reference)[0]:
        return "it finds faults in an undamaged copy"
    # At 3 s: 10 ms skipped. At 5 s: 100 ms of silence. At 7 s: 50 ms of something else.
    damaged = clean.copy()
    damaged[7 * RATE: 7 * RATE + 2400] = np.random.default_rng(1).normal(0, 3000, 2400)
    damaged[5 * RATE: 5 * RATE + 4800] = 0
    damaged = np.concatenate((damaged[: 3 * RATE], damaged[3 * RATE + 480:], np.zeros(TAIL)))
    found = faults_in(damaged, reference)[0]
    kinds = {f[1] for f in found}
    if not {"jump", "hole"} <= kinds or not any(k in kinds for k in ("garbage", "jump")) or len(found) < 3:
        return f"it misses damage made on purpose: {found}"
    return None


def main():
    heard, reference = load(sys.argv[1]), load(sys.argv[2])
    problem = self_test(reference)
    if problem:
        print(f"FAIL the sound comparison itself: {problem}")
        return 1
    faults, likeness, seconds = faults_in(heard, reference)
    good = not faults and likeness > 0.999 and seconds >= 10
    print(f"{'PASS' if good else 'FAIL'} what a viewer hears is the recording | {seconds:.1f} s after the first sound, "
          f"likeness {likeness:.4f}, {len(faults)} faults {faults[:12]}")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
