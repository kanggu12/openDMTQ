"""The server on an installer's end: read back as the site writes it, and nothing from an end that is not one."""

import json
import os
import struct
import tempfile
import unittest

from opendmtq_client import preset

# A certificate authority's certificate as a server's tls.py writes it: a made-up body, never used to connect.
CA = "-----BEGIN CERTIFICATE-----\nMIIBszCCAVmgAwIBAgIUQmFkZ2Vy+/made/up=\n-----END CERTIFICATE-----"

# The site's own writer of the end (tools/opendmtq_tools/windows_client.py), read here as text: its format must stay
# the one this module reads.
WINDOWS_CLIENT = os.path.join(os.path.dirname(__file__), "..", "..", "tools", "opendmtq_tools", "windows_client.py")


class Preset(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.exe = os.path.join(self.dir, "OpenDMTQ-Setup.exe")

    def write(self, data):
        with open(self.exe, "wb") as f:
            f.write(b"MZ" + b"\0" * 5000 + data)

    def test_the_end_is_read(self):
        self.write(preset.tail("http://example.test:8790", "클럽 서버"))
        self.assertEqual(preset.read(self.exe), {"url": "http://example.test:8790", "name": "클럽 서버"})

    def test_a_release_installer_has_none(self):
        self.write(b"")
        self.assertIsNone(preset.read(self.exe))

    def test_damaged_ends_are_none(self):
        good = preset.tail("http://example.test", "x")
        for bad in (good[:-1] + b"X",                                       # another mark
                    b"{}" + struct.pack("<I", 2) + preset.MAGIC,            # no address
                    b"{]" + struct.pack("<I", 2) + preset.MAGIC,            # not JSON
                    b"x" + struct.pack("<I", 10 ** 9) + preset.MAGIC,       # a length past the file
                    b'{"version":2,"url":"http://a.test"}' + struct.pack("<I", 35) + preset.MAGIC,   # a newer format
                    b'{"version":1,"url":"file:///c:/x"}' + struct.pack("<I", 34) + preset.MAGIC):    # no web address
            self.write(bad)
            self.assertIsNone(preset.read(self.exe), bad)

    def test_the_sites_writer_makes_the_same_end(self):
        with open(WINDOWS_CLIENT, encoding="utf-8") as f:
            source = f.read()
        self.assertIn('MAGIC = b"%s"' % preset.MAGIC.decode(), source)
        self.assertIn('struct.pack("<I", len(data)) + MAGIC', source)
        self.assertIn('{"version": PRESET_FORMAT, "url": url, "name": name}', source)
        self.assertIn('details["ca"] = ca', source)

    def test_the_servers_own_authority_comes_with_an_https_address(self):
        self.write(preset.tail("https://example.test:80", "x", CA))
        self.assertEqual(preset.read(self.exe), {"url": "https://example.test:80", "name": "x", "ca": CA})
        # Over plain HTTP there is no certificate for it to vouch for: left out.
        self.write(preset.tail("http://example.test", "x", CA))
        self.assertEqual(preset.read(self.exe), {"url": "http://example.test", "name": "x"})
        # Anything but one whole certificate is left out, and the rest still read.
        for bad in ("", "not a certificate", CA[:40], 7, "-----BEGIN CERTIFICATE-----" + "A" * 20000 + "-----END CERTIFICATE-----"):
            data = json.dumps({"version": 1, "url": "https://example.test:80", "name": "x", "ca": bad}).encode()
            self.write(data + struct.pack("<I", len(data)) + preset.MAGIC)
            self.assertEqual(preset.read(self.exe), {"url": "https://example.test:80", "name": "x"}, str(bad)[:30])


if __name__ == "__main__":
    unittest.main()
