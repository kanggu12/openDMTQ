"""The PC settings: their choices, their defaults, and the settings file the player reads."""

import os
import re
import unittest

from opendmtq_client import values as choices

# The player's own reader of the settings file: its keys and values are what this file must agree with.
SETTINGS_CPP = os.path.join(os.path.dirname(__file__), "..", "..", "arm32", "desktop", "settings.cpp")


class Values(unittest.TestCase):
    def test_defaults_fill_everything(self):
        filled = choices.normalize({})
        # Every setting the launcher keeps: the player's, and the counter's corner, which no key of the player's names.
        self.assertEqual(set(filled), set(choices.NAMES))
        self.assertEqual(set(choices.NAMES) - set(choices.ORDER), {"fps_position"})
        self.assertEqual(filled["display"], "fullscreen")
        self.assertEqual(filled["volume"], 100)

    def test_choices_are_checked(self):
        self.assertEqual(choices.normalize({"fps": "240"})["fps"], "240")
        self.assertEqual(choices.normalize({"vsync": "OFF"})["vsync"], "off")
        for name, value in (("fps", "241"), ("vsync", "maybe"), ("render_scale", "25"), ("volume", "101"),
                            ("volume", "loud"), ("window", "100x100"), ("audio_device", "a\nb"), ("nothing", "1")):
            with self.assertRaises(choices.ChoiceError, msg=(name, value)):
                choices.normalize({name: value})

    def test_upscaler_and_anti_aliasing(self):
        # The plain stretch and no anti-aliasing by default: a start as before these were offered.
        filled = choices.normalize({})
        self.assertEqual((filled["upscaler"], filled["anti_aliasing"]), ("bilinear", "off"))
        # Each offered value is kept, in any case; the temporal ones and FXAA are not offered.
        self.assertEqual(choices.normalize({"upscaler": "FSR1"})["upscaler"], "fsr1")
        self.assertEqual(choices.normalize({"anti_aliasing": "SMAA"})["anti_aliasing"], "smaa")
        for name, value in (("upscaler", "dlss"), ("upscaler", "fsr2"), ("anti_aliasing", "taa"), ("anti_aliasing", "fxaa"),
                            ("anti_aliasing", "msaa16")):
            with self.assertRaises(choices.ChoiceError, msg=(name, value)):
                choices.normalize({name: value})
        # MSAA is no choice any more (it left the game's picture as it was): what an earlier launcher kept, and --set as
        # before, read as CMAA 2, kept or not strict, and the player's file says cmaa2.
        self.assertEqual(choices.ANTI_ALIASING, ("off", "cmaa2", "smaa"))
        for old in ("msaa2", "msaa4", "MSAA8"):
            self.assertEqual(choices.normalize({"anti_aliasing": old})["anti_aliasing"], "cmaa2", old)
            self.assertEqual(choices.normalize({"anti_aliasing": old}, strict=False)["anti_aliasing"], "cmaa2", old)
        self.assertIn("anti_aliasing=cmaa2", choices.settings_text({"anti_aliasing": "msaa4"}).splitlines())

    def test_the_frame_counter(self):
        # Off by default, its corner the bottom right; on and off by name, in any case.
        filled = choices.normalize({})
        self.assertEqual((filled["show_fps"], filled["fps_position"]), ("off", "bottom_right"))
        self.assertEqual(choices.normalize({"show_fps": "ON"})["show_fps"], "on")
        # Its corner kept while it is off, for the next time it is on.
        kept = choices.normalize({"show_fps": "off", "fps_position": "top_right"})
        self.assertEqual((kept["show_fps"], kept["fps_position"]), ("off", "top_right"))
        # A corner as show_fps's value (an older launcher's file, --set as before): on, in that corner.
        for corner in ("top_left", "top_right", "bottom_left", "bottom_right"):
            filled = choices.normalize({"show_fps": corner.upper(), "fps_position": "top_left"})
            self.assertEqual((filled["show_fps"], filled["fps_position"]), ("on", corner))
        # A place that is no corner refused, for either.
        for name, value in (("show_fps", "middle"), ("fps_position", "middle"), ("fps_position", "on")):
            with self.assertRaises(choices.ChoiceError, msg=(name, value)):
                choices.normalize({name: value})
        # The player's file names the corner while it is on, off while it is not.
        def counter_line(values):
            return [line for line in choices.settings_text(values).splitlines() if line.startswith("show_fps=")]
        self.assertEqual(counter_line({}), ["show_fps=off"])
        self.assertEqual(counter_line({"show_fps": "on"}), ["show_fps=bottom_right"])
        self.assertEqual(counter_line({"show_fps": "on", "fps_position": "bottom_left"}), ["show_fps=bottom_left"])
        self.assertEqual(counter_line({"show_fps": "off", "fps_position": "bottom_left"}), ["show_fps=off"])
        self.assertNotIn("fps_position", choices.settings_text({"show_fps": "on"}))

    def test_a_bad_value_keeps_the_default_when_not_strict(self):
        filled = choices.normalize({"fps": "999", "volume": 40}, strict=False)
        self.assertEqual(filled["fps"], "auto")
        self.assertEqual(filled["volume"], 40)

    def test_window_sizes(self):
        self.assertEqual(choices.normalize({"window": "1920X1080"})["window"], "1920x1080")
        # The smallest area the player's window holds, 480x270: smaller is refused (the player would not take it).
        self.assertEqual(choices.normalize({"window": "480x270"})["window"], "480x270")
        for small in ("320x180", "479x270", "480x269"):
            with self.assertRaises(choices.ChoiceError, msg=small):
                choices.normalize({"window": small})
        with self.assertRaises(choices.ChoiceError) as refused:
            choices.normalize({"window": "320x180"})
        self.assertIn("480x270 or more", str(refused.exception))
        self.assertEqual(choices.size_of("1280x720"), (1280, 720))
        self.assertIsNone(choices.size_of("auto"))

    def test_vsync_pacing_is_the_players(self):
        # The refreshes a frame stays for with VSync, as the player's pacing_math.h has them (its own test's cases):
        # every refresh without a limit or at the rate and above, a whole fraction near the limit, else by the clock.
        cases = [(60.0, "60", 1), (59.94, "60", 1), (60.0, "120", 1), (144.0, "144", 1), (180.0, "240", 1),
                 (240.084, "240", 1), (240.084, "120", 2), (240.084, "60", 4), (144.0, "72", 2), (180.0, "60", 3),
                 (165.0, "60", 3), (360.0, "120", 3), (360.0, "180", 2), (120.0, "60", 2), (240.084, "130", 2),
                 (240.084, "144", 0), (144.0, "120", 0), (144.0, "60", 0), (165.0, "144", 0), (180.0, "144", 0),
                 (360.0, "240", 0), (144, "auto", 1), (144, "unlimited", 1)]
        for hz, fps, want in cases:
            self.assertEqual(choices.vsync_refreshes(hz, fps), want, (hz, fps))
        # Above the rate (the same 3 % margin): no limit, a number past it; not auto, not a rate a little under 144.
        self.assertTrue(choices.above_rate(144, "165"))
        self.assertTrue(choices.above_rate(60, "unlimited"))
        self.assertFalse(choices.above_rate(143, "144"))
        self.assertFalse(choices.above_rate(144, "auto"))
        self.assertFalse(choices.above_rate(None, "360"))

    def test_the_frame_limits_offered_and_their_words(self):
        # With VSync on a 144 Hz display: nothing above 144 offered, a limit kept from before keeps its row; the hint
        # names this display's rate and what the limit gives on it, never another display's.
        from opendmtq_client import i18n, pages
        offered = pages.fps_choices(True, 144, "auto")
        self.assertEqual(offered, ["auto", "30", "60", "120", "144"])
        self.assertEqual(pages.fps_choices(True, 144, "240")[-1], "240")
        self.assertEqual(pages.fps_choices(False, 144, "auto"), list(choices.FPS))
        self.assertEqual(pages.fps_choices(True, None, "auto"), list(choices.FPS))
        w = i18n.Words("en")
        self.assertEqual(pages.fps_hint(w, True, "72", 144), "On this 144 Hz display: 72 fps exactly.")
        self.assertEqual(pages.fps_hint(w, True, "60", 144), "On this 144 Hz display: very nearly 60 fps.")
        self.assertEqual(pages.fps_hint(w, True, "130", 240), "On this 240 Hz display: 120 fps exactly.")
        self.assertEqual(pages.fps_hint(w, True, "240", 144), w("screen.fps.hint.vsync.above", hz=144))
        self.assertEqual(pages.fps_hint(w, True, "auto", 144), w("screen.fps.hint.vsync_rate"))
        self.assertEqual(pages.fps_hint(w, False, "240", 144), w("screen.fps.hint.free"))
        self.assertNotIn("240", pages.fps_hint(w, True, "120", None))

    def test_settings_file(self):
        text = choices.settings_text({"display": "window", "window": "1600x900", "vsync": "off", "fps": "unlimited",
                                      "render_scale": "75", "upscaler": "nis", "anti_aliasing": "smaa", "show_fps": "on",
                                      "audio_device": "{0.0.0.00000000}.{x}",
                                      "audio_mode": "exclusive", "audio_buffer": "low", "volume": 35})
        lines = [line for line in text.splitlines() if not line.startswith("#")]
        self.assertEqual(lines, ["display=window", "window=1600x900", "vsync=off", "fps=unlimited", "render_scale=75",
                                 "upscaler=nis", "anti_aliasing=smaa", "show_fps=bottom_right", "audio_device={0.0.0.00000000}.{x}",
                                 "audio_mode=exclusive", "audio_buffer=low", "volume=35"])

    def test_the_player_reads_every_key_and_value(self):
        """Each key the launcher writes, and each fixed value it offers, is one the player's reader takes."""
        with open(SETTINGS_CPP, encoding="utf-8") as f:
            source = f.read()
        for name in choices.ORDER:
            self.assertIn('key == "%s"' % name, source, name)
        for name, offered in choices.CHOICES.items():
            for value in offered:
                if name in ("fps", "render_scale") and value not in ("auto", "unlimited"):
                    continue
                self.assertIn('"%s"' % value, source, (name, value))
        # Numbers: the player's ranges hold every number offered.
        fps = re.search(r'number\(value, (\d+), (\d+), n\)\)\) s\.fps', source)
        scale = re.search(r'number\(value, (\d+), (\d+), n\)\)\) s\.render_scale', source)
        self.assertTrue(fps and scale)
        for value in choices.FPS:
            if value.isdigit():
                self.assertTrue(int(fps.group(1)) <= int(value) <= int(fps.group(2)), value)
        for value in choices.RENDER_SCALE:
            self.assertTrue(int(scale.group(1)) <= int(value) <= int(scale.group(2)), value)


if __name__ == "__main__":
    unittest.main()
