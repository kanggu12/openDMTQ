"""Small charts for the admin pages, drawn on the server as plain HTML and SVG: no library, no script needed to see them.

Every mark carries data-tip, which the page's small script shows on hover and on keyboard focus (base.html). Text stays in
the page's text colours; the marks carry the colour. All values go through html.escape: names come from players.
"""

from html import escape

from markupsafe import Markup

# The categorical order for parts of a whole, stepped for the dark panel (checked with the data visualisation validator).
PARTS = ("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#9085e9")
# A whole's part that is no part of anything (free space): the panel's own quiet grey. And what is there but not ours.
QUIET = "#46505b"
# OpenDMTQ's own part of a whole: the console's light (its section colour, style.css), the brightest of the three.
OURS = "#dfe5eb"
OTHER = "#7b8794"
# OpenDMTQ's own parts at their own scale: plain light as the other meters, no hue (on these pages colour marks a state),
# each a step darker than the one before, from OURS to OTHER, so that neighbours part and the legend's keys say which is
# which. Dark words read on every step (4.5 to 1 at least: tests/test_charts.py).
LIGHTS = ("#dfe5eb", "#ced5dc", "#bec6ce", "#adb6c0", "#9ca6b1", "#8c97a2", "#7b8794")
# The drawing space of a chart over time: as wide as this, 100 high, and this much of the height kept free over the top guide.
PLOT_WIDTH = 720
PLOT_HEAD = 6


def tip(text):
    """The attribute that gives a mark its tooltip."""
    return f'data-tip="{escape(str(text), quote=True)}" tabindex="0"'


def number(n):
    """A count for an axis or a label: in full under ten thousand, then short."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 10_000:
        return f"{n // 1000}K"
    return f"{n:,}"


def nice_top(value):
    """The axis's top: the next round number at or above the highest value, close enough that the marks fill the plot, and
    even, so that the guide at its middle has a whole number too."""
    if value <= 4:
        return 4
    magnitude = 10 ** (len(str(int(value))) - 1)
    for tenths in (10, 12, 16, 20, 24, 30, 40, 50, 60, 80, 100):
        top = tenths * magnitude // 10
        if value <= top and top % 2 == 0:
            return top
    return 10 * magnitude


def _frame(marks, top, axis_labels, label, fmt=number, note=""):
    """What every chart over time shares: the value labels on the left, the plot, the time labels under it.

    The plot is an SVG that stretches to fill its card, in both directions, so it holds no text: letters in it would stretch
    with it. The labels are ordinary text around it, placed in percent of the plot. marks is the SVG's inside, in a space
    PLOT_WIDTH wide and 100 high with the floor at the bottom. A note is said in the middle of the plot, over it: why there
    is little to see yet."""
    y_labels = []
    grid = []
    for share, text in ((1, fmt(top)), (0.5, fmt(top // 2))):
        # From the foot up: the head room over the top guide is in percent of the plot's height, as everything here.
        y = 100 - (100 - PLOT_HEAD) * share
        y_labels.append(f'<span style="bottom:{100 - y:.1f}%">{text}</span>')
        grid.append(f'<line class="grid" x1="0" x2="{PLOT_WIDTH}" y1="{y:.1f}" y2="{y:.1f}" vector-effect="non-scaling-stroke"/>')
    grid.append(f'<line class="floor" x1="0" x2="{PLOT_WIDTH}" y1="100" y2="100" vector-effect="non-scaling-stroke"/>')
    x_labels = []
    for centre, text in axis_labels:
        share = 100 * centre / PLOT_WIDTH
        # Every label centred on its own column, the last ones too: held in by their right end they stood 6 to 12px off
        # their bar, over the one before. Past the plot's edge they reach at most about 11px, inside the card's padding.
        place = f'left:{share:.1f}%;transform:translateX(-50%)'
        x_labels.append(f'<span style="{place}">{escape(text)}</span>')
    svg = (f'<svg class="chart-svg" viewBox="0 0 {PLOT_WIDTH} 100" role="img" aria-label="{escape(label, quote=True)}" preserveAspectRatio="none">'
           f'{"".join(grid)}{"".join(marks)}</svg>')
    words = f'<p class="chart-note"><span>{escape(note)}</span></p>' if note else ""
    return (f'<div class="chart"><div class="chart-y" aria-hidden="true">{"".join(y_labels)}</div><div class="chart-plot">{svg}{words}</div>'
            f'<div class="chart-x" aria-hidden="true">{"".join(x_labels)}</div></div>')


def columns(points, label):
    """Columns over time: points are (axis label or '', tooltip, value). One colour (the section's), thin, round at the
    top and square at the foot, on a hairline floor, with one guide at the middle and the top's value."""
    if not points:
        return Markup("")
    top = nice_top(max(p[2] for p in points))
    slot = PLOT_WIDTH / len(points)
    bar = min(24, max(3, slot - 2))
    marks, axis = [], []
    for i, (name, words, value) in enumerate(points):
        x = slot * i + (slot - bar) / 2
        h = (100 - PLOT_HEAD) * value / top
        # A round top and a square foot, on the floor; a zero draws nothing, and is still there to point at.
        if value:
            r = min(3, bar / 2, h)
            marks.append(f'<path class="bar" d="M{x:.1f} 100V{100 - h + r:.1f}Q{x:.1f} {100 - h:.1f} {x + r:.1f} {100 - h:.1f}'
                         f'H{x + bar - r:.1f}Q{x + bar:.1f} {100 - h:.1f} {x + bar:.1f} {100 - h + r:.1f}V100Z"/>')
        # Bigger than the mark: the whole slot answers the pointer.
        marks.append(f'<rect class="hit" x="{slot * i:.1f}" y="{PLOT_HEAD}" width="{slot:.1f}" height="{100 - PLOT_HEAD}" {tip(words)}/>')
        if name:
            axis.append((slot * i + slot / 2, name))
    return Markup(_frame(marks, top, axis, label))


def stacked(points, names, label):
    """Two series on one axis, the second (what went wrong) on top in red and the first in a quiet grey: points are
    (axis label or '', tooltip, first, second)."""
    if not points:
        return Markup("")
    top = nice_top(max(p[2] + p[3] for p in points))
    slot = PLOT_WIDTH / len(points)
    bar = min(24, max(3, slot - 3))
    scale = (100 - PLOT_HEAD) / top
    marks, axis = [], []
    for i, (name, words, first, second) in enumerate(points):
        x = slot * i + (slot - bar) / 2
        h1, h2 = first * scale, second * scale
        if first:
            marks.append(f'<rect class="bar-quiet" x="{x:.1f}" y="{100 - h1:.1f}" width="{bar:.1f}" height="{h1:.1f}"/>')
        if second:
            # The surface's gap between the two.
            marks.append(f'<rect class="bar-bad" x="{x:.1f}" y="{100 - h1 - h2 - (1 if first else 0):.1f}" width="{bar:.1f}" height="{h2:.1f}"/>')
        marks.append(f'<rect class="hit" x="{slot * i:.1f}" y="{PLOT_HEAD}" width="{slot:.1f}" height="{100 - PLOT_HEAD}" {tip(words)}/>')
        if name:
            axis.append((slot * i + slot / 2, name))
    legend = "".join(f'<li><i class="{cls}"></i>{escape(n)}</li>' for cls, n in zip(("key-quiet", "key-bad"), names))
    return Markup(_frame(marks, top, axis, label) + f'<ul class="seglegend">{legend}</ul>')


def heatmap(rows, row_names, cell_tip, label, ends=("", "")):
    """A grid of counts (one row per day of the week, one column per hour): one colour, stronger with more. ends are the
    words at the two ends of the key under it."""
    top = max((v for row in rows for v in row), default=0)
    parts = [f'<div class="heat" role="img" aria-label="{escape(label, quote=True)}"><span class="heat-corner"></span>']
    for hour in range(24):
        parts.append(f'<span class="heat-hour">{hour if hour % 3 == 0 else ""}</span>')
    for name, row in zip(row_names, rows):
        parts.append(f'<span class="heat-day">{escape(name)}</span>')
        for hour, value in enumerate(row):
            # Five steps: past that the eye cannot tell them apart.
            step = 0 if not value or not top else 1 + min(4, int(4 * value / top))
            parts.append(f'<i class="c{step}" data-tip="{escape(cell_tip(name, hour, value), quote=True)}"></i>')
    parts.append("</div>")
    steps = "".join(f'<span class="k{step}"></span>' for step in range(6))
    parts.append(f'<div class="heat-key" aria-hidden="true">{escape(ends[0])}<span class="heat-steps">{steps}</span>{escape(ends[1])}</div>')
    return Markup("".join(parts))


def ink_on(colour):
    """The text colour that reads on a filled #rrggbb block: dark on the bright ones, white on the rest."""
    # Relative luminance by the WCAG formula: each channel is linearised, then weighted by how bright the eye finds it.
    channels = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = (c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    # Whichever of the two has the higher contrast ratio; the dark ink's own luminance is close to 0.01.
    return "#0f1318" if (luminance + 0.05) / 0.06 > 1.05 / (luminance + 0.05) else "#ffffff"


def segments(parts, label, colours=PARTS):
    """One whole split into parts, tall, with each part's share printed where it fits and a legend under it: parts are
    (name, value, shown value). Colour goes with the part's place in the list; a part at zero draws nothing."""
    total = sum(p[1] for p in parts) or 1
    bar, legend = [], []
    for i, (name, value, shown) in enumerate(parts):
        colour = colours[i % len(colours)]
        share = value / total
        legend.append(f'<li><i style="background:{colour}"></i>{escape(name)} <b>{escape(str(shown))}</b></li>')
        if not value:
            continue
        words = f"{name}: {shown} ({share:.0%})"
        inside = f"{share:.0%}" if share >= 0.09 else ""
        bar.append(f'<span style="flex:{value} 1 0;background:{colour};color:{ink_on(colour)}" {tip(words)}>{inside}</span>')
    return Markup(f'<div class="segbar" role="img" aria-label="{escape(label, quote=True)}">{"".join(bar)}</div><ul class="seglegend">{"".join(legend)}</ul>')


def ranked(rows, label):
    """Who or what has the most: rows are (name, value, shown value, link or None). A thin bar under each name, long by its
    value against the first."""
    top = max((r[1] for r in rows), default=0) or 1
    out = [f'<ol class="ranked" aria-label="{escape(label, quote=True)}">']
    for name, value, shown, link in rows:
        title = f'<a href="{escape(link, quote=True)}">{escape(name)}</a>' if link else escape(name)
        out.append(f'<li><span class="ranked-name">{title}</span><b>{escape(str(shown))}</b>'
                   f'<i style="width:{max(2, 100 * value / top):.1f}%"></i></li>')
    out.append("</ol>")
    return Markup("".join(out))


def spark(values, label=""):
    """A small line of how something went, for a table's row or a tile: no axis, its last point marked."""
    if not values or max(values) == 0:
        return Markup('<svg class="spark" viewBox="0 0 84 24" aria-hidden="true"><line x1="0" x2="84" y1="21" y2="21"/></svg>')
    top = max(values)
    step = 84 / max(1, len(values) - 1)
    points = [(i * step, 21 - 18 * v / top) for i, v in enumerate(values)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    area = f"0,22 {line} 84,22"
    x, y = points[-1]
    aria = f'role="img" aria-label="{escape(label, quote=True)}"' if label else 'aria-hidden="true"'
    return Markup(f'<svg class="spark" viewBox="0 0 84 24" {aria}><polygon class="spark-area" points="{area}"/>'
                  f'<polyline points="{line}"/><circle cx="{min(x, 82):.1f}" cy="{y:.1f}" r="2"/></svg>')


def percent(value):
    """A share on an axis: 100%, 50%."""
    return f"{value:g}%"


def area(points, label, top=100, fmt=percent, note=""):
    """A level over time, as a line with a light wash under it: points are (axis label or '', tooltip or '', value or None),
    oldest first. None leaves a gap: nothing was known then. One colour, the section's. A note goes in the middle."""
    if not points:
        return Markup("")
    slot = PLOT_WIDTH / len(points)
    runs, run = [], []
    for i, (_, _, value) in enumerate(points):
        if value is None:
            if run:
                runs.append(run)
            run = []
            continue
        run.append((slot * i + slot / 2, 100 - (100 - PLOT_HEAD) * max(0, min(top, value)) / top))
    if run:
        runs.append(run)
    marks = []
    for run in runs:
        # A lone point is a short level line, not a dot that the stretched plot would squash.
        if len(run) == 1:
            run = [(run[0][0] - slot / 2, run[0][1]), (run[0][0] + slot / 2, run[0][1])]
        line = " ".join(f"{x:.1f},{y:.1f}" for x, y in run)
        marks.append(f'<polygon class="area" points="{run[0][0]:.1f},100 {line} {run[-1][0]:.1f},100"/>')
        marks.append(f'<polyline class="line" points="{line}" vector-effect="non-scaling-stroke"/>')
    axis = []
    for i, (name, words, value) in enumerate(points):
        # Bigger than the line: the whole slot answers the pointer, where something was known.
        if words and value is not None:
            marks.append(f'<rect class="hit" x="{slot * i:.1f}" y="{PLOT_HEAD}" width="{slot:.1f}" height="{100 - PLOT_HEAD}" data-tip="{escape(str(words), quote=True)}"/>')
        if name:
            axis.append((slot * i + slot / 2, name))
    return Markup(_frame(marks, top, axis, label, fmt, note))


def meter(share, label, high=0.9):
    """How full something is, as a thin bar: share from 0 to 1, red from high on, empty while it is not known."""
    known = share is not None
    width = 0 if not known else max(0.0, min(1.0, share)) * 100
    state = " high" if known and share >= high else ""
    return Markup(f'<span class="meter{state}" role="img" aria-label="{escape(label, quote=True)}"><i style="width:{width:.1f}%"></i></span>')


def strip(cells, label, ends, legend):
    """A row of equal slots over time, oldest first, each in the colour of its state: cells are (state, tooltip), state one
    of ok, warn, bad or none. ends are the words under its two ends; legend is (state, words) for the key under it."""
    parts = [f'<div class="strip" role="img" aria-label="{escape(label, quote=True)}" style="--cells:{len(cells)}">']
    parts += [f'<i class="s-{state}" data-tip="{escape(str(words), quote=True)}"></i>' for state, words in cells]
    parts.append("</div>")
    parts.append(f'<div class="strip-ends" aria-hidden="true"><span>{escape(ends[0])}</span><span>{escape(ends[1])}</span></div>')
    parts.append('<ul class="seglegend">' + "".join(f'<li><i class="s-{state}"></i>{escape(words)}</li>' for state, words in legend) + "</ul>")
    return Markup("".join(parts))


def days(values, top, tips, label):
    """Someone's last days as a row of cells, one per day, oldest first, stronger with more: on one scale (top) for everyone
    in the list, so that rows can be compared."""
    cells = []
    for value, words in zip(values, tips):
        # Five steps, as the hours of the week have.
        step = 0 if not value or not top else 1 + min(4, int(4 * value / top))
        cells.append(f'<i class="c{step}" data-tip="{escape(str(words), quote=True)}"></i>')
    # A cell's colour says how many, not which part of a row it is: the layout check's lining up of rows passes it by.
    return Markup(f'<span class="daycells" role="img" aria-label="{escape(label, quote=True)}" data-layout-ok="cells by value">{"".join(cells)}</span>')

