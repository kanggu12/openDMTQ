"""The last game's sound as the player writes it (last-game-sound.txt beside the settings file) and as the Sound page's
Last game card and --status say it, in both languages."""

import os
import unittest

from opendmtq_client import i18n, player
from tests.base import SOUND_RESULT, Folder


class SoundResult(Folder):
    def write(self, text):
        os.makedirs(os.path.dirname(player.result_path()), exist_ok=True)
        with open(player.result_path(), "w", encoding="utf-8") as f:
            f.write(text)

    def test_read_as_the_player_writes_it(self):
        # Beside the settings file, by its own name; its notes left out, its numbers as numbers.
        self.assertEqual(os.path.dirname(player.result_path()), os.path.dirname(player.settings_path()))
        self.assertEqual(os.path.basename(player.result_path()), "last-game-sound.txt")
        self.assertIsNone(player.last_sound())
        self.write(SOUND_RESULT)
        result = player.last_sound()
        self.assertEqual(result["mode"], "shared")
        self.assertEqual(result["period_ms"], 10.0)
        self.assertEqual(result["latency_ms"], 18.4)
        self.assertEqual(result["latency_measures"], 31204)
        self.assertEqual((result["gaps"], result["game_gaps"]), (0, 0))

    def test_what_the_card_says_in_both_languages(self):
        self.write(SOUND_RESULT)
        result = player.last_sound()
        self.assertEqual(player.sound_words(i18n.Words("en"), result), ("ok", "Shared, 10 ms period, 18 ms output delay", "no gaps"))
        self.assertEqual(player.sound_words(i18n.Words("ko"), result), ("ok", "공유, 주기 10 ms, 출력 지연 18 ms", "끊김 없음"))

    def test_gaps_the_low_latency_mode_and_the_device_alone(self):
        # The device's gaps and the game's own together, one or many; a short period to a tenth.
        text = SOUND_RESULT.replace("mode=shared\n", "mode=shared-low\n").replace("period_ms=10.00", "period_ms=2.67")
        self.write(text.replace("gaps=0\ngame_gaps=0", "gaps=1\ngame_gaps=0"))
        self.assertEqual(player.sound_words(i18n.Words("en"), player.last_sound()),
                         ("change", "Shared (low latency), 2.7 ms period, 18 ms output delay", "1 gap"))
        self.write(text.replace("gaps=0\ngame_gaps=0", "gaps=2\ngame_gaps=3"))
        self.assertEqual(player.sound_words(i18n.Words("ko"), player.last_sound()),
                         ("change", "공유(저지연), 주기 2.7 ms, 출력 지연 18 ms", "끊김 5번"))
        self.write(SOUND_RESULT.replace("mode=shared\n", "mode=exclusive\n").replace("period_ms=10.00", "period_ms=3.00"))
        self.assertEqual(player.sound_words(i18n.Words("en"), player.last_sound())[1], "Exclusive, 3 ms period, 18 ms output delay")

    def test_a_latency_never_measured_and_no_device(self):
        # A clock that never answered: no time said; no device at all: no period either.
        self.write(SOUND_RESULT.replace("latency_measures=31204", "latency_measures=0"))
        self.assertEqual(player.sound_words(i18n.Words("en"), player.last_sound())[1], "Shared, 10 ms period")
        self.write(SOUND_RESULT.replace("mode=shared\n", "mode=none\n").replace("period_ms=10.00", "period_ms=0.00")
                   .replace("latency_measures=31204", "latency_measures=0").replace("game_gaps=0", "game_gaps=4"))
        # No device: no gaps said (the game was not heard), a ring as for what will change.
        self.assertEqual(player.sound_words(i18n.Words("en"), player.last_sound()), ("change", "No sound device", ""))

    def test_a_file_the_player_did_not_write(self):
        # No mode it knows, or a number that is none: no result, the card says no game yet.
        self.write("mode=loud\n")
        self.assertIsNone(player.last_sound())
        self.write(SOUND_RESULT.replace("latency_ms=18.4", "latency_ms=soon"))
        self.assertIsNone(player.last_sound())
        self.assertIsNone(player.sound_words(i18n.Words("en"), None))


if __name__ == "__main__":
    unittest.main()
