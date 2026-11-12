"""Tests for the admin pages' charts: what they draw, that names cannot break out of them, and that their words stay readable."""

import importlib.util
import re
import unittest

# The admin package makes its Flask application as it is imported (admin/__init__.py), so this module needs Flask, not
# only markupsafe: both are in the tools image only.
HAVE_FLASK = importlib.util.find_spec("flask") is not None
if HAVE_FLASK:
    from opendmtq_tools.admin import charts

# The colours the status page paints blocks in (GRADE_COLOURS in admin/status.py).
GRADE_COLOURS = ("#78cf2e", "#2fa8e0", "#a783f2", "#d9a11a", "#e07a3c", "#5c6773", "#46505b")


def contrast(one, other):
    """The WCAG contrast ratio of two #rrggbb colours."""

    def luminance(colour):
        channels = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        r, g, b = (c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    a, b = sorted((luminance(one), luminance(other)), reverse=True)
    return (a + 0.05) / (b + 0.05)


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class NumbersTest(unittest.TestCase):
    def test_a_count_is_short_only_when_large(self):
        for value, shown in ((0, "0"), (999, "999"), (1000, "1,000"), (9999, "9,999"), (12000, "12K"), (1500000, "1.5M")):
            self.assertEqual(charts.number(value), shown)

    def test_the_axis_ends_on_a_round_number_at_or_over_the_highest(self):
        for value, top in ((0, 4), (3, 4), (5, 6), (7, 8), (12, 12), (22, 24), (180, 200), (328, 400), (5000, 5000), (5001, 6000)):
            self.assertEqual(charts.nice_top(value), top)


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class OverTimeTest(unittest.TestCase):
    POINTS = [("10-01", "1 play", 1), ("", "none", 0), ("", "3 plays", 3), ("10-04", "9 plays", 9)]

    def test_columns_draw_a_bar_for_each_value_and_a_target_for_each_day(self):
        html = str(charts.columns(self.POINTS, "Plays"))
        self.assertEqual(html.count('class="bar"'), 3)
        self.assertEqual(html.count('class="hit"'), 4)
        self.assertIn('aria-label="Plays"', html)

    def test_the_stretched_drawing_holds_no_text(self):
        # Letters inside an SVG that stretches to its card stretch with it, wide on a phone's chart and thin on a monitor's.
        for html in (str(charts.columns(self.POINTS, "Plays")), str(charts.stacked([("a", "t", 1, 2)], ("Fine", "Failed"), "Requests"))):
            svg = html[html.index("<svg"):html.index("</svg>")]
            self.assertNotIn("<text", svg)
            self.assertIn('preserveAspectRatio="none"', svg)

    def test_the_axes_are_text_beside_the_drawing(self):
        html = str(charts.columns(self.POINTS, "Plays"))
        self.assertRegex(html, r'class="chart-y"[^>]*>.*>10<.*>5<')
        self.assertRegex(html, r'class="chart-x"[^>]*>.*>10-01<.*>10-04<')

    def test_every_label_is_centred_on_its_own_column(self):
        # The last one too: held in by its right end, it stood off its own bar, over the one before (it may reach a
        # little past the plot, into the card's padding).
        html = str(charts.columns([("", "t", 1)] * 29 + [("last", "t", 1)], "Plays"))
        self.assertRegex(html, r'style="left:[\d.]+%;transform:translateX\(-50%\)">last<')
        self.assertNotIn('style="right:', html)

    def test_no_points_no_chart(self):
        self.assertEqual(str(charts.columns([], "Plays")), "")
        self.assertEqual(str(charts.stacked([], ("a", "b"), "Requests")), "")

    def test_stacked_draws_only_the_parts_that_exist_and_names_them(self):
        html = str(charts.stacked([("a", "t", 5, 0), ("b", "t", 0, 2), ("c", "t", 0, 0)], ("Fine", "Failed"), "Requests"))
        self.assertEqual(html.count('class="bar-quiet"'), 1)
        self.assertEqual(html.count('class="bar-bad"'), 1)
        self.assertIn("Fine", html)
        self.assertIn("Failed", html)

    def test_a_tooltip_cannot_break_out_of_its_attribute(self):
        html = str(charts.columns([("x", '"><script>alert(1)</script>', 1)], "Plays"))
        self.assertNotIn("<script>", html)


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class HeatmapTest(unittest.TestCase):
    def test_a_cell_for_every_hour_of_every_day_stronger_with_more(self):
        rows = [[0] * 24 for _ in range(7)]
        rows[2][5] = 8
        rows[3][6] = 1
        html = str(charts.heatmap(rows, list("MTWTFSS"), lambda d, h, n: f"{d} {h}: {n}", "When"))
        self.assertEqual(html.count("<i class="), 7 * 24)
        self.assertEqual(html.count('class="c5"'), 1)
        self.assertEqual(html.count('class="c1"'), 1)
        self.assertEqual(html.count('class="c0"'), 7 * 24 - 2)

    def test_nobody_played(self):
        html = str(charts.heatmap([[0] * 24 for _ in range(7)], list("MTWTFSS"), lambda d, h, n: "", "When"))
        self.assertEqual(html.count('class="c0"'), 7 * 24)


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class SegmentsTest(unittest.TestCase):
    def test_a_share_is_printed_only_where_it_fits(self):
        html = str(charts.segments([("Big", 95, "95 GB"), ("Small", 5, "5 GB")], "Disk"))
        self.assertIn(">95%</span>", html)
        self.assertNotIn(">5%</span>", html)

    def test_a_part_at_zero_stays_in_the_legend_with_no_block(self):
        html = str(charts.segments([("Some", 10, "10"), ("None", 0, "0")], "Disk"))
        self.assertEqual(html.count("flex:"), 1)
        self.assertIn("None", html)

    def test_every_block_colour_gets_words_that_can_be_read(self):
        for colour in charts.PARTS + charts.LIGHTS + (charts.QUIET,) + GRADE_COLOURS:
            ratio = contrast(charts.ink_on(colour), colour)
            self.assertGreaterEqual(ratio, 4.5, f"{colour}: {ratio:.1f}")

    def test_a_name_cannot_break_out(self):
        html = str(charts.segments([("<b>x</b>", 1, "<i>1</i>")], "Disk"))
        self.assertNotIn("<b>x</b>", html)
        self.assertNotIn("<i>1</i>", html)


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class RankedAndSparkTest(unittest.TestCase):
    def test_the_bars_are_long_by_their_value_against_the_first(self):
        html = str(charts.ranked([("A", 10, "10", None), ("B", 5, "5", None), ("C", 0, "0", None)], "Who"))
        self.assertEqual(re.findall(r'width:([\d.]+)%', html), ["100.0", "50.0", "2.0"])

    def test_a_link_and_a_name_are_escaped(self):
        html = str(charts.ranked([("<x>", 1, "1", 'http://a/"b')], "Who"))
        self.assertNotIn("<x>", html)
        self.assertIn("&quot;b", html)

    def test_a_small_line_with_nothing_to_show_is_flat(self):
        self.assertNotIn("polyline", str(charts.spark([0, 0, 0])))
        self.assertIn("polyline", str(charts.spark([0, 2, 1])))


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class ResourcesTest(unittest.TestCase):
    """The status page's resources: a level over the day with its gaps, how full something is, a strip of states."""

    def test_a_gap_in_the_day_breaks_the_line(self):
        points = [("", "a", 10), ("", "b", 20), ("", "", None), ("", "c", 30)]
        out = str(charts.area(points, "CPU"))
        # Two runs of the line, each with its wash under it; the y axis in percent.
        self.assertEqual(out.count("<polyline"), 2)
        self.assertEqual(out.count('class="area"'), 2)
        self.assertIn(">100%<", out)
        self.assertIn(">50%<", out)
        # Only where something was known does the pointer get words.
        self.assertEqual(out.count('class="hit"'), 3)

    def test_a_value_past_the_top_stays_in_the_plot(self):
        out = str(charts.area([("", "x", 250), ("", "y", -5)], "CPU"))
        ys = [float(y) for y in re.findall(r",(-?[\d.]+)", re.search(r'<polyline class="line" points="([^"]+)"', out).group(1))]
        self.assertTrue(all(0 <= y <= 100 for y in ys), ys)

    def test_a_meter_says_when_it_is_nearly_full(self):
        self.assertIn('class="meter high"', str(charts.meter(0.95, "Disk")))
        self.assertIn('width:40.0%', str(charts.meter(0.4, "Memory")))
        self.assertNotIn("high", str(charts.meter(None, "CPU")))

    def test_a_strip_has_a_cell_per_slot_and_a_key_in_words(self):
        out = str(charts.strip([("ok", "10:00: up"), ("bad", "10:30: down"), ("none", "11:00: nothing")], "Game server", ("24 h ago", "Now"),
                               [("ok", "Answering"), ("bad", "Not answering")]))
        self.assertEqual(len(re.findall(r'<i class="s-(?:ok|bad|none)" data-tip', out)), 3)
        self.assertIn("--cells:3", out)
        self.assertIn("Answering", out)
        self.assertIn("24 h ago", out)

    def test_every_players_days_are_on_one_scale(self):
        quiet = str(charts.days([0, 1, 0], 8, ["a", "b", "c"], "Plays"))
        busy = str(charts.days([0, 8, 0], 8, ["a", "b", "c"], "Plays"))
        # One play on a day is a faint cell next to someone with eight, not as strong as theirs.
        self.assertIn('class="c1"', quiet)
        self.assertIn('class="c5"', busy)
