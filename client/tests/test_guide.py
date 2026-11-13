"""The first-start guide's line under a step's card: what Next waits for, while it waits (guide.waits_for)."""

import unittest

from opendmtq_client import guide, i18n


class WaitsFor(unittest.TestCase):
    def test_each_step_that_waits_says_for_what(self):
        # SERVER waits for a server that answered, SIGN IN for a sign-in, DOWNLOAD for the app: each says so.
        self.assertEqual(guide.waits_for("server", can=False), "guide.need.server")
        self.assertEqual(guide.waits_for("login", can=False), "guide.need.login")
        self.assertEqual(guide.waits_for("download", can=False), "guide.need.download")

    def test_nothing_once_next_can_go_on(self):
        # Next lit: nothing to wait for, no line on any step.
        for step in guide.STEPS:
            self.assertIsNone(guide.waits_for(step, can=True), step)

    def test_nothing_while_the_steps_own_work_is_under_way(self):
        # A server being asked or the app downloading: the card says what it does, the line would only repeat it.
        self.assertIsNone(guide.waits_for("server", can=False, busy=True))
        self.assertIsNone(guide.waits_for("download", can=False, busy=True))

    def test_steps_that_never_make_next_wait_say_nothing(self):
        # POWER ON and SOUND CHECK always go on; STAGE START's PLAY waits on the ready check, whose rows say why.
        for step in ("power", "sound", "stage"):
            self.assertIsNone(guide.waits_for(step, can=False), step)

    def test_the_lines_say_what_to_do_in_both_languages(self):
        # Every line a step can show has its words, each saying the thing to do and that it leads on.
        for key in guide.NEEDS.values():
            en, ko = i18n.TEXT[key]
            self.assertTrue(en.endswith("to go on."), key)
            self.assertIn("다음으로 넘어갑니다", ko, key)


if __name__ == "__main__":
    unittest.main()
