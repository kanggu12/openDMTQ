"""The version the launcher shows: one source for the logo's, the Launcher page's and the command line's, the installed
version first, so that after an update none of them says an older number than the others."""

import ast
import os
import types
import unittest
from unittest import mock

from opendmtq_client import __version__, updates

PACKAGE = os.path.join(os.path.dirname(__file__), "..", "opendmtq_client")


class ShownVersion(unittest.TestCase):
    def test_the_installed_version_first(self):
        # Velopack's installed version: what the installer put in and the updates moved on.
        with mock.patch.object(updates, "current_version", return_value="9.8.7"):
            self.assertEqual(updates.shown_version(), "9.8.7")

    def test_the_codes_own_outside_an_install(self):
        # Run from source or a copied folder: no installed version, the code's own.
        with mock.patch.object(updates, "current_version", return_value=None):
            self.assertEqual(updates.shown_version(), __version__)

    def test_the_logo_shows_the_same_version(self):
        # The header's version block beside the wordmark (app.make_header) takes it from shown_version, as the Launcher
        # page does: an installed 9.8.7 is v9.8.7 there, whatever the code says.
        from opendmtq_client import app as app_module
        from opendmtq_client import art, widgets
        fake = types.SimpleNamespace(scale=1.0, ui=None)
        with mock.patch.object(updates, "current_version", return_value="9.8.7"), \
                mock.patch.object(art, "brand") as brand, mock.patch.object(widgets, "Header"):
            app_module.LauncherApp.make_header(fake, None)
        self.assertEqual(brand.call_args[0][1], "v9.8.7")

    def test_no_other_place_works_the_version_out_itself(self):
        # Every place that shows the launcher's version asks shown_version: the installed version is asked for in
        # updates.py alone, so that the logo, the Launcher page and --status cannot drift apart again.
        asking = []
        for name in sorted(os.listdir(PACKAGE)):
            if not name.endswith(".py") or name == "updates.py":
                continue
            with open(os.path.join(PACKAGE, name), encoding="utf-8") as f:
                tree = ast.parse(f.read())
            # A call of current_version() anywhere but in updates.py is a place that works it out on its own.
            asking.extend(name for node in ast.walk(tree) if isinstance(node, ast.Call)
                          and isinstance(node.func, ast.Attribute) and node.func.attr == "current_version")
        self.assertEqual(asking, [])


if __name__ == "__main__":
    unittest.main()
