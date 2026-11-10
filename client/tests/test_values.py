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
        self.assertEqual(set(filled), set(choices.ORDER))
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
        self.assertEqual(choices.normalize({"anti_aliasing": "MSAA8"})["anti_aliasing"], "msaa8")
        for name, value in (("upscaler", "dlss"), ("upscaler", "fsr2"), ("anti_aliasing", "taa"), ("anti_aliasing", "fxaa"),
                            ("anti_aliasing", "msaa16")):
            with self.assertRaises(choices.ChoiceError, msg=(name, value)):
                choices.normalize({name: value})

    def test_the_frame_counter(self):
        # None by default; each corner by its name; a place that is no corner refused.
        self.assertEqual(choices.normalize({})["show_fps"], "off")
        for corner in ("top_left", "top_right", "bottom_left", "bottom_right"):
            self.assertEqual(choices.normalize({"show_fps": corner.upper()})["show_fps"], corner)
        with self.assertRaises(choices.ChoiceError):
            choices.normalize({"show_fps": "middle"})

    def test_a_bad_value_keeps_the_default_when_not_strict(self):
        filled = choices.normalize({"fps": "999", "volume": 40}, strict=False)
        self.assertEqual(filled["fps"], "auto")
        self.assertEqual(filled["volume"], 40)

    def test_window_sizes(self):
        self.assertEqual(choices.normalize({"window": "1920X1080"})["window"], "1920x1080")
        self.assertEqual(choices.size_of("1280x720"), (1280, 720))
        self.assertIsNone(choices.size_of("auto"))

    def test_settings_file(self):
        text = choices.settings_text({"display": "window", "window": "1600x900", "vsync": "off", "fps": "unlimited",
                                      "render_scale": "75", "upscaler": "nis", "anti_aliasing": "smaa", "show_fps": "top_left",
                                      "audio_device": "{0.0.0.00000000}.{x}",
                                      "audio_mode": "exclusive", "audio_buffer": "low", "volume": 35})
        lines = [line for line in text.splitlines() if not line.startswith("#")]
        self.assertEqual(lines, ["display=window", "window=1600x900", "vsync=off", "fps=unlimited", "render_scale=75",
                                 "upscaler=nis", "anti_aliasing=smaa", "show_fps=top_left", "audio_device={0.0.0.00000000}.{x}",
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
