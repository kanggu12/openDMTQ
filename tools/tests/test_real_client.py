"""Every edit of the patcher against the real clients: its code bytes are where the patcher expects them in the client's
version, its settings are in their objects, and every object it hides or moves exists in that screen. The game is not in
this repository, so this only runs where a client is named: OPENDMTQ_BASE_APK, the one tests/qa.sh finds in data/apk/base,
and every APK in the folder OPENDMTQ_CLIENTS (tests/qa.sh: CLIENTS=<folder>), other versions or copies changed for another
server. Each test runs per client, in a subtest of its own, so that one client's failure does not hide another's."""

import os
import unittest
import zipfile

from opendmtq_tools import axml, patch_apk, unity_assets

BASE = os.environ.get("OPENDMTQ_BASE_APK", "")
MORE = os.environ.get("OPENDMTQ_CLIENTS", "")


def clients():
    """The base client, then the folder's."""
    paths = [BASE] if BASE and os.path.isfile(BASE) else []
    if MORE and os.path.isdir(MORE):
        paths += sorted(os.path.join(MORE, f) for f in os.listdir(MORE) if f.lower().endswith(".apk"))
    return paths


@unittest.skipUnless(clients(), "needs a client: OPENDMTQ_BASE_APK or OPENDMTQ_CLIENTS")
class RealClientTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.apks = {path: zipfile.ZipFile(path) for path in clients()}

    def test_the_app_says_it_is_for_android_9_with_all_it_then_needs(self):
        for path, apk in self.apks.items():
            with self.subTest(client=os.path.basename(path)):
                # Android 14 and later show older apps a notice at their start, and the game was made for 8.1.
                manifest = apk.read("AndroidManifest.xml")
                out = axml.add_optional_library(axml.set_target_sdk(manifest, patch_apk.TARGET_SDK), "org.apache.http.legacy")
                self.assertIn(b"org.apache.http.legacy", out.replace(b"\0", b""))
                # The game's own config, where a client has one, is what decides about plain HTTP, and takes the flag.
                if "res/xml/network_security_config.xml" in apk.namelist():
                    config = apk.read("res/xml/network_security_config.xml")
                    flagged = axml.set_plain_flag(config, "base-config", "cleartextTrafficPermitted")
                    self.assertIn(b"cleartextTrafficPermitted", flagged.replace(b"\0", b""))

    def test_it_is_taken_for_a_client_every_code_edit_fits(self):
        # The order among several clients, and what the setup says of each, rest on this.
        for path in self.apks:
            with self.subTest(client=os.path.basename(path)):
                info = patch_apk.inspect(path)
                self.assertIn(info["kind"], ("original", "other server"))
                self.assertTrue(info["known"])

    def test_every_code_edit_fits_in_the_clients_own_version(self):
        for path, apk in self.apks.items():
            with self.subTest(client=os.path.basename(path)):
                version = axml.manifest_info(apk.read("AndroidManifest.xml"))["version"]
                code = apk.read(patch_apk.CODE_FILE)
                # Each edit in the version the client says it is: no other version's bytes are taken for it.
                self.assertEqual(patch_apk.code_versions(code), {what: version for what, _ in patch_apk.IL2CPP_EDITS})
                for what, versions in patch_apk.IL2CPP_EDITS:
                    for offset, old, new in versions[version]:
                        self.assertEqual(code[offset:offset + len(old)], old, what)
                        self.assertEqual(len(old), len(new), what)

    def test_every_setting_edit_finds_its_byte(self):
        for path, apk in self.apks.items():
            with self.subTest(client=os.path.basename(path)):
                places = patch_apk.setting_places(apk.read(f"{patch_apk.ASSET_DIR}/{patch_apk.SETTINGS_FILE}"))
                self.assertEqual(sorted(places), sorted(patch_apk.SETTING_EDITS))

    def test_every_screen_edit_finds_its_object(self):
        for path, apk in self.apks.items():
            with self.subTest(client=os.path.basename(path)):
                for name, edits in patch_apk.ASSET_EDITS.items():
                    data = apk.read(f"{patch_apk.ASSET_DIR}/{name}")
                    # apply() raises for an object that is not there; the file keeps its size.
                    self.assertEqual(len(unity_assets.apply(data, edits)), len(data), name)

    def test_what_is_hidden_is_not_already_hidden(self):
        for path, apk in self.apks.items():
            with self.subTest(client=os.path.basename(path)):
                for name, edits in patch_apk.ASSET_EDITS.items():
                    asset = unity_assets.SerializedFile(apk.read(f"{patch_apk.ASSET_DIR}/{name}"))
                    # An object the game turns on by itself as the screen opens (PLAY FOR FREE in 1.3.5) may start
                    # hidden: what takes it off the screen is its move off it, to the left.
                    off_screen = {e[1] for e in edits if e[0].startswith("move") and e[2] is not None and e[2] <= -4000}
                    for edit in edits:
                        if edit[0] == "hide" and edit[1] not in off_screen:
                            self.assertTrue(asset.is_active(edit[1]), edit[1])


if __name__ == "__main__":
    unittest.main()
