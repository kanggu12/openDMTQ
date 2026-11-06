"""Every edit of the patcher against the real client: its code bytes are where the patcher expects them, and every object
it hides or moves exists in that screen. The game is not in this repository, so this only runs where a base APK is named
(OPENDMTQ_BASE_APK, set by tests/qa.sh)."""

import os
import unittest
import zipfile

from opendmtq_tools import axml, patch_apk, unity_assets

BASE = os.environ.get("OPENDMTQ_BASE_APK", "")


@unittest.skipUnless(BASE and os.path.isfile(BASE), "needs the client: OPENDMTQ_BASE_APK")
class RealClientTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.apk = zipfile.ZipFile(BASE)
        cls.code = cls.apk.read("lib/armeabi-v7a/libil2cpp.so")

    def test_the_app_says_it_is_for_android_9_with_all_it_then_needs(self):
        # Android 14 and later show older apps a notice at their start, and the game was made for 8.1.
        manifest = self.apk.read("AndroidManifest.xml")
        out = axml.add_optional_library(axml.set_target_sdk(manifest, patch_apk.TARGET_SDK), "org.apache.http.legacy")
        self.assertIn(b"org.apache.http.legacy", out.replace(b"\0", b""))
        # The game's own config is what decides about plain HTTP, and takes the flag.
        config = self.apk.read("res/xml/network_security_config.xml")
        self.assertIn(b"cleartextTrafficPermitted", axml.set_plain_flag(config, "base-config", "cleartextTrafficPermitted").replace(b"\0", b""))

    def test_it_is_taken_for_the_original_the_code_edits_were_made_for(self):
        # The order among several clients, and what the setup says of it, rest on this.
        info = patch_apk.inspect(BASE)
        self.assertEqual((info["kind"], info["version"], info["known"]), ("original", "1.3.4", True))

    def test_every_setting_edit_finds_its_byte(self):
        data = self.apk.read(f"{patch_apk.ASSET_DIR}/{patch_apk.SETTINGS_FILE}")
        for name, (place, old, _) in patch_apk.SETTING_EDITS.items():
            self.assertEqual(data[place], old, name)

    def test_every_code_edit_finds_its_bytes(self):
        for what, parts in patch_apk.IL2CPP_EDITS:
            for offset, old, new in parts:
                self.assertEqual(self.code[offset:offset + len(old)], old, what)
                self.assertEqual(len(old), len(new), what)

    def test_every_screen_edit_finds_its_object(self):
        for name, edits in patch_apk.ASSET_EDITS.items():
            data = self.apk.read(f"{patch_apk.ASSET_DIR}/{name}")
            # apply() raises for an object that is not there; the file keeps its size.
            self.assertEqual(len(unity_assets.apply(data, edits)), len(data), name)

    def test_what_is_hidden_is_not_already_hidden(self):
        for name, edits in patch_apk.ASSET_EDITS.items():
            asset = unity_assets.SerializedFile(self.apk.read(f"{patch_apk.ASSET_DIR}/{name}"))
            for edit in edits:
                if edit[0] == "hide":
                    self.assertTrue(asset.is_active(edit[1]), edit[1])


if __name__ == "__main__":
    unittest.main()
