"""What the game needs of a song's own files: the music pack (.fpk), the charts, the background video and the preview.

Each check passes every file of the game's own songs and turns away only what the game could not load or play: an
added song's package is checked before it is taken (songs.py), and a chart the imported files carry that the game
could not read is served from its pair (songs.rebuild()).

The layouts, as the game reads them (all numbers little-endian):

  .fpk   A 28-byte head of seven 32-bit words: a version, a kind, the size of the entries' data (twice), where the
         table starts, how many entries it has, a flag. Then the entries' data, then the table: 144 bytes an entry,
         where its data starts, its size (twice), the length of its name, and the name in 128 bytes. Most entries are
         the song's sounds in Ogg; a few are images or text.
  chart  A 32-bit word, then where the head is. From byte 8: the sounds, 67 bytes each (number, stream flag, file
         name in 64 bytes); the tracks, each a 74-byte header (type, name in 64 bytes, length, event count) and its
         events, 13 bytes each (tick, type, 8 bytes of data; type 1 is a note). Last, the 26-byte head: sound count,
         track count, ticks a measure, tempo, a tick, the play time, the end tick, and the events in all.
"""

import math
import struct

# The .fpk head: seven 32-bit words.
FPK_HEAD = 28
# One entry of the .fpk table.
FPK_ENTRY = 144
# Where a chart's sounds start: after its first word and the head's place.
CHART_START = 8
# The chart head's size and layout: three 16-bit counts, a float, a word, a float and two words.
CHART_HEAD = struct.Struct("<3HfIfII")
# One sound of a chart: number, stream flag, and a 64-byte name.
SOUND = 67
# One track header: type, a 64-byte name, length, event count.
TRACK = 74
# Where a track header keeps its event count.
TRACK_EVENTS = 70
# One event: tick, type, and 8 bytes of data.
EVENT = struct.Struct("<IB8x")
# The event type of a note.
NOTE = 1
# How every Ogg stream starts.
OGG = b"OggS"
# How a WebM (Matroska) file starts.
WEBM = b"\x1a\x45\xdf\xa3"
# What the first page of an Ogg Opus stream names.
OPUS = b"OpusHead"


def fpk_problem(data):
    """None when data is a music pack the game can read its sounds from, else a strings.py key and its values."""
    # Too short for the head: not a pack at all.
    if len(data) < FPK_HEAD:
        return "song.fpk_format", {}
    # The head's fifth and sixth words: where the table starts and how many entries it holds.
    table, count = struct.unpack_from("<2I", data, 16)
    # A pack with no entries, or a table that starts in the head or runs past the end, is not one the game can read.
    if count == 0 or table < FPK_HEAD or table + count * FPK_ENTRY > len(data):
        return "song.fpk_format", {}
    # The Ogg sounds the pack holds: a song needs at least one.
    sounds = 0
    for i in range(count):
        at = table + i * FPK_ENTRY
        # Where the entry's data starts and how long it is.
        start, size = struct.unpack_from("<2I", data, at)
        # The name, NUL-padded in its 128 bytes (the game's are ASCII).
        name = data[at + 16:at + FPK_ENTRY].split(b"\0", 1)[0].decode("latin-1")
        # Data outside the part between the head and the table: the game would read the wrong bytes.
        if start < FPK_HEAD or start + size > table:
            return "song.fpk_format", {}
        # A sound must be Ogg: the game plays them as such. Images and text in the pack are left as they are.
        if name.lower().endswith(".ogg"):
            if data[start:start + len(OGG)] != OGG:
                return "song.fpk_sound", {"name": repr(name)}
            sounds += 1
    if not sounds:
        return "song.fpk_no_sounds", {}
    return None


def _chart_head(data):
    """The chart's head as a tuple, and the end of its body (where the head is), or None when the game could not even
    find them."""
    # The first word and the head's place are needed at least.
    if len(data) < CHART_START:
        return None
    head, = struct.unpack_from("<I", data, 4)
    # The head must sit after the body's start and fit in the file: the game reads it there first.
    if head < CHART_START or head + CHART_HEAD.size > len(data):
        return None
    return CHART_HEAD.unpack_from(data, head), head


def _tracks(data, sounds, tracks, end):
    """Each track's events as (start, count), or None when the sounds and tracks the head counts do not fit before the
    head: the game reads them in order from byte 8, so it would run off its data."""
    at = CHART_START + sounds * SOUND
    found = []
    for _ in range(tracks):
        # The track header must fit before the head.
        if at + TRACK > end:
            return None
        count, = struct.unpack_from("<I", data, at + TRACK_EVENTS)
        at += TRACK
        # And so must its events.
        if at + count * EVENT.size > end:
            return None
        found.append((at, count))
        at += count * EVENT.size
    return found


def chart_readable(data):
    """True when the game can load the chart: its head and every track it counts are where the head says. Quick (no
    event is read), for checking every imported chart at each rebuild."""
    head = _chart_head(data)
    return head is not None and _tracks(data, head[0][0], head[0][1], head[1]) is not None


def chart_problem(data):
    """None when the game can load and play the chart, else a strings.py key and its values (the caller adds the
    file's name). Beyond loading: it has notes, a tempo and a measure length, and it does not end before its last
    note (the game stops the song at the chart's end)."""
    head = _chart_head(data)
    if head is None:
        return "song.chart_format", {}
    (sounds, tracks, per_measure, tempo, tick, _play_time, end_tick, _events), end = head
    found = _tracks(data, sounds, tracks, end)
    if found is None:
        return "song.chart_format", {}
    # The notes and the last one's tick.
    notes, last = 0, 0
    for start, count in found:
        for t, kind in EVENT.iter_unpack(data[start:start + count * EVENT.size]):
            if kind == NOTE:
                notes += 1
                last = max(last, t)
    if not notes:
        return "song.chart_no_notes", {}
    # Without a measure length or a tempo the game cannot place a note in time.
    if not per_measure or not (math.isfinite(tempo) and tempo > 0):
        return "song.chart_timing", {}
    # The chart's end: its end tick, or its tick when the end tick is 0, as the game takes it.
    if (end_tick or tick) < last:
        return "song.chart_ends_early", {}
    return None


def video_problem(start):
    """None when the first bytes of song.webm are a WebM video's, else a strings.py key and its values."""
    return None if start[:len(WEBM)] == WEBM else ("song.video_format", {})


def preview_problem(data):
    """None when preview.opus is Opus audio in Ogg, as the game's previews are, else a strings.py key and its values."""
    # An Ogg stream whose first page names Opus (its first page is a few dozen bytes).
    if data[:len(OGG)] == OGG and OPUS in data[:256]:
        return None
    return "song.preview_format", {}
