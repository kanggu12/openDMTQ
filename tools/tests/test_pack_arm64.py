"""Tests for the runtime packer: what goes where in the app, on small files instead of a real game."""

import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile

from opendmtq_tools import pack_arm64

from .test_axml import manifest


class ShimTest(unittest.TestCase):
    """The shim goes with the game's own libraries, and the runtime has no proxy for it."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        d = self.dir.name
        self.bundle = os.path.join(d, "bundle")
        for sub in ("arm64-v8a", "sysroot/bin", "sysroot/lib", "armeabi-v7a"):
            os.makedirs(os.path.join(self.bundle, sub))
        for rel in ("arm64-v8a/libarm32.so", "arm64-v8a/libarm32proxy.so", "sysroot/bin/linker", "sysroot/lib/libc.so",
                    "arm32-agent", "armeabi-v7a/libopendmtq.so"):
            with open(os.path.join(self.bundle, rel), "wb") as f:
                f.write(rel.encode())
        self.src = os.path.join(d, "src.apk")
        with zipfile.ZipFile(self.src, "w") as z:
            z.writestr("AndroidManifest.xml", manifest())
            z.writestr("lib/armeabi-v7a/libunity.so", b"unity")

    def pack(self, only_64bit=False):
        out = os.path.join(self.dir.name, "out.apk")
        pack_arm64.pack(self.src, out, self.bundle, "arm64-v8a", only_64bit, tweaks="server a.b:1\n")
        with zipfile.ZipFile(out) as z:
            return set(z.namelist())

    def test_the_licenses_go_along(self):
        os.makedirs(os.path.join(self.bundle, "notices"))
        for name in ("NOTICES.txt", "android-NOTICE.html.gz"):
            with open(os.path.join(self.bundle, "notices", name), "w") as f:
                f.write(name)
        self.assertLessEqual({"assets/opendmtq/NOTICES.txt", "assets/opendmtq/android-NOTICE.html.gz"}, self.pack())
        # In the app for phones with no 32-bit support too.
        self.assertIn("assets/opendmtq/NOTICES.txt", self.pack(only_64bit=True))

    def test_a_bundle_without_licenses_still_packs(self):
        self.assertFalse([n for n in self.pack() if n.startswith("assets/opendmtq/")])

    def test_with_the_game_libraries(self):
        names = self.pack()
        self.assertIn("lib/armeabi-v7a/libopendmtq.so", names)
        self.assertIn("lib/armeabi-v7a/libarm32t-tweaks.so", names)
        self.assertIn("lib/arm64-v8a/libarm32t-tweaks.so", names)
        self.assertNotIn("lib/arm64-v8a/libopendmtq.so", names)
        self.assertNotIn("lib/arm64-v8a/libarm32g-libopendmtq.so", names)

    def test_packing_again_keeps_one_of_each(self):
        out = os.path.join(self.dir.name, "again.apk")
        pack_arm64.pack(self.src, out, self.bundle, "arm64-v8a", False, tweaks="server a.b:1\n")
        pack_arm64.pack(out, self.src, self.bundle, "arm64-v8a", False, tweaks="server a.b:1\n")
        with zipfile.ZipFile(self.src) as z:
            names = z.namelist()
        self.assertEqual(names.count("lib/armeabi-v7a/libopendmtq.so"), 1)
        self.assertNotIn("lib/arm64-v8a/libopendmtq.so", names)

    def test_not_in_a_64_bit_only_app(self):
        names = self.pack(only_64bit=True)
        self.assertFalse([n for n in names if n.startswith("lib/armeabi-v7a/")])

    def test_a_bundle_without_the_shim_still_packs(self):
        os.remove(os.path.join(self.bundle, "armeabi-v7a", "libopendmtq.so"))
        self.assertNotIn("lib/armeabi-v7a/libopendmtq.so", self.pack())


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(os.path.isfile(pack_arm64.SIGNER) and shutil.which("keytool"), "needs the signer and Java (the tools image has them)")
class RealSignerTest(unittest.TestCase):
    """The pinned signer, run as a build runs it: its arguments in Java's argument file, the password in nothing a process
    list shows."""

    def test_an_app_comes_out_signed_with_the_key_through_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            # A folder with a space, a quote and a # in its name: the file keeps each argument whole.
            here = os.path.join(d, 'my "server" #1')
            os.makedirs(here)
            app = os.path.join(here, "unsigned.apk")
            with zipfile.ZipFile(app, "w") as z:
                z.writestr("AndroidManifest.xml", manifest())
                z.writestr("classes.dex", b"dex\n035\0" + bytes(100))
            key = os.path.join(here, "opendmtq.jks")
            password = "a-password_of-24-letters"
            subprocess.run(["keytool", "-genkeypair", "-keystore", key, "-alias", "opendmtq", "-keyalg", "RSA", "-keysize", "2048",
                            "-validity", "2", "-storepass:env", "PW", "-keypass:env", "PW", "-dname", "CN=signer test"],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env={**os.environ, "PW": password})
            out = os.path.join(here, "signed.apk")
            pack_arm64.sign(app, out, key, password)
            # Signed with that key (apksigner, in the signer's own jar, says whose certificate it carries).
            r = subprocess.run([pack_arm64.JAVA, "-cp", pack_arm64.SIGNER, "com.android.apksigner.ApkSignerTool", "verify",
                                "--print-certs", out], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("certificate DN: CN=signer test", r.stdout)
