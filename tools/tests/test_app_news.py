"""What the builder notes for the site when it makes an app that phones need (app-new.json): the site's home and download
pages then say there is a new app, and that installed over the one before it keeps the account (server/portal/lib.php
app_news())."""

import contextlib
import io
import json
import os
import tempfile
import time
import unittest
from unittest import mock

from opendmtq_tools import builder

HOST = "192.168.0.10"
# An app's manifest as the patcher writes it (patch_apk.main), made up: the fields that tell one app from another.
BEFORE = {"file": "opendmtq-phone-app-2026.11.01-android-192.168.0.10.apk", "host": HOST, "label": "TECHNIKA Q (192.168.0.10)",
          "base_sha256": "aa" * 32, "patcher": "1.11.0", "runtime": "v0.11.1-1234abcd", "key_sha256": "bb" * 32}


class NoteTest(unittest.TestCase):
    """note_new_app on its own, in a folder of its own (builder.OUT)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = tmp.name
        patch = mock.patch.object(builder, "OUT", self.out)
        patch.start()
        self.addCleanup(patch.stop)

    def noted(self):
        path = os.path.join(self.out, "app-new.json")
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def test_an_app_that_differs_for_phones_is_noted_with_its_file_and_when(self):
        # A new patcher (0.11.2's), a new client, the runtime, the app's name, the address: each is an app phones need
        # (SRV-111).
        for trait, value in (("patcher", "1.12.0"), ("base_sha256", "cc" * 32), ("runtime", "v0.11.2-c80ac6ad"),
                             ("label", "TECHNIKA Q (Sena's)"), ("host", "192.168.0.20")):
            after = dict(BEFORE, file="opendmtq-phone-app-2026.11.24-android-192.168.0.10.apk", **{trait: value})
            started = int(time.time())
            builder.note_new_app(BEFORE, after)
            noted = self.noted()
            self.assertEqual((noted["file"], noted["changed"]), (after["file"], [trait]), trait)
            self.assertGreaterEqual(noted["at"], started)

    def test_nothing_is_noted_for_a_first_app_the_same_app_or_another_key(self):
        # A first app (nobody has one to install it over), the same app built again (a forced build, a damaged file),
        # and one signed with another key, which would not install over the one before (SRV-111).
        builder.note_new_app(None, dict(BEFORE))
        builder.note_new_app(dict(BEFORE), dict(BEFORE, file="opendmtq-phone-app-2026.11.24-android-192.168.0.10.apk"))
        builder.note_new_app(dict(BEFORE), dict(BEFORE, patcher="1.12.0", key_sha256="dd" * 32))
        self.assertIsNone(self.noted())

    def test_a_note_stays_until_an_app_differs_again(self):
        builder.note_new_app(BEFORE, dict(BEFORE, patcher="1.12.0", file="new.apk"))
        first = self.noted()
        # The same app as the new one, built again: the note of the new one stays.
        builder.note_new_app(dict(BEFORE, patcher="1.12.0", file="new.apk"), dict(BEFORE, patcher="1.12.0", file="new.apk"))
        self.assertEqual(self.noted(), first)


class BuildTest(unittest.TestCase):
    """The builder's run, the patcher standing in: the app before it is read at its start, the new one at its end."""

    def test_a_build_for_a_new_patcher_notes_the_new_app(self):
        with tempfile.TemporaryDirectory() as apk:
            out = os.path.join(apk, "out")
            os.makedirs(out)
            os.makedirs(os.path.join(apk, "base"))
            with open(os.path.join(apk, "base", "client.apk"), "wb") as f:
                f.write(b"PK")
            with open(os.path.join(out, BEFORE["file"]), "wb") as f:
                f.write(b"PK old")
            with open(os.path.join(out, "latest.json"), "w", encoding="utf-8") as f:
                json.dump(BEFORE, f)
            new = dict(BEFORE, file="opendmtq-phone-app-2026.11.24-android-192.168.0.10.apk", patcher="1.12.0")

            def patcher(argv):
                # What the patcher leaves: the app and the manifest the site reads.
                with open(os.path.join(out, new["file"]), "wb") as f:
                    f.write(b"PK new")
                with open(os.path.join(out, "latest.json"), "w", encoding="utf-8") as f:
                    json.dump(new, f)
                return new["file"]

            with mock.patch.object(builder, "OUT", out), mock.patch.object(builder.patch_apk, "APK_DIR", apk), \
                    mock.patch.object(builder.patch_apk, "main", patcher), \
                    mock.patch.object(builder.patch_apk, "find_base", return_value=os.path.join(apk, "base", "client.apk")), \
                    mock.patch.object(builder, "reason_to_build", return_value="patcher updated (1.11.0 -> 1.12.0)"), \
                    mock.patch.object(builder.runtime, "add_or_note"), mock.patch.object(builder, "windows_installer"), \
                    contextlib.redirect_stdout(io.StringIO()):
                builder.main(["--host", HOST])
            with open(os.path.join(out, "app-new.json"), encoding="utf-8") as f:
                noted = json.load(f)
            self.assertEqual((noted["file"], noted["changed"]), (new["file"], ["patcher"]))


if __name__ == "__main__":
    unittest.main()
