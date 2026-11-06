"""Tests for the HTTPS certificates: made once, kept while they fit, and accepted by OpenSSL's own
verification for the server's names only."""

import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from opendmtq_tools import tls


@unittest.skipUnless(shutil.which("openssl"), "needs the openssl command")
class TlsTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d)

    def verify(self, name):
        """openssl's verdict on the server certificate for one host name or IP."""
        flag = "-verify_ip" if tls.is_ip(name) else "-verify_hostname"
        r = subprocess.run(["openssl", "verify", "-CAfile", os.path.join(self.d, "ca.crt"), flag, name,
                            os.path.join(self.d, "serve", "server.crt")], capture_output=True, text=True)
        return r.returncode == 0

    def test_makes_everything_once(self):
        self.assertEqual(tls.ensure(self.d, "myhome.example.com"), ["authority", "server certificate"])
        for f in ("ca.key", "ca.crt", "serve/server.crt", "serve/server.key", "public/ca.crt"):
            self.assertTrue(os.path.isfile(os.path.join(self.d, f)), f)
        # Keys are for their owner only.
        self.assertEqual(os.stat(os.path.join(self.d, "ca.key")).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(os.path.join(self.d, "serve", "server.key")).st_mode & 0o777, 0o600)
        # A second start changes nothing.
        before = open(os.path.join(self.d, "serve", "server.crt")).read()
        self.assertEqual(tls.ensure(self.d, "myhome.example.com"), [])
        self.assertEqual(open(os.path.join(self.d, "serve", "server.crt")).read(), before)

    def test_valid_for_the_server_only(self):
        tls.ensure(self.d, "myhome.example.com")
        self.assertTrue(self.verify("myhome.example.com"))
        self.assertTrue(self.verify("localhost"))
        self.assertTrue(self.verify("127.0.0.1"))
        self.assertFalse(self.verify("example.org"))

    def test_constrained_authority_cannot_sign_other_names(self):
        tls.ensure(self.d, "myhome.example.com")
        # Even with the authority's key, a certificate for another site fails verification.
        with self.assertRaises(SystemExit):
            tls.make_server(self.d, ["bank.example.org"])

    def test_other_name_types_are_constrained_too(self):
        tls.ensure(self.d, "myhome.example.com")
        text = subprocess.run(["openssl", "x509", "-noout", "-text", "-in", os.path.join(self.d, "ca.crt")],
                              capture_output=True, text=True).stdout
        self.assertIn("email:.invalid", text)
        self.assertIn("URI:.invalid", text)
        self.assertIn("TLS Web Server Authentication", text)

    def test_a_new_profile_makes_a_new_authority(self):
        tls.ensure(self.d, "myhome.example.com")
        old_ca = open(os.path.join(self.d, "ca.crt")).read()
        tls.PROFILE, saved = tls.PROFILE + 1, tls.PROFILE
        try:
            self.assertEqual(tls.ensure(self.d, "myhome.example.com"), ["authority", "server certificate"])
        finally:
            tls.PROFILE = saved
        self.assertNotEqual(open(os.path.join(self.d, "ca.crt")).read(), old_ca)

    def test_new_address_new_authority(self):
        tls.ensure(self.d, "myhome.example.com")
        old_ca = open(os.path.join(self.d, "ca.crt")).read()
        self.assertEqual(tls.ensure(self.d, "192.168.0.10"), ["authority", "server certificate"])
        self.assertNotEqual(open(os.path.join(self.d, "ca.crt")).read(), old_ca)
        self.assertTrue(self.verify("192.168.0.10"))
        self.assertFalse(self.verify("myhome.example.com"))

    def read(self, rel):
        with open(os.path.join(self.d, rel), encoding="utf-8") as f:
            return f.read()

    def test_a_key_that_does_not_belong_to_the_certificate_is_replaced(self):
        # A renewal cut off between writing the key and the certificate: nginx refuses such a pair,
        # and the edge proxy would not start at all (or fall back to plain HTTP for good).
        tls.ensure(self.d, "myhome.example.com")
        old_ca = self.read("ca.crt")
        subprocess.run(["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout",
                        "-out", os.path.join(self.d, "serve", "server.key")], check=True)
        self.assertFalse(tls.pair_matches(os.path.join(self.d, "serve")))
        self.assertEqual(tls.ensure(self.d, "myhome.example.com"), ["server certificate"])
        self.assertTrue(tls.pair_matches(os.path.join(self.d, "serve")))
        # The authority phones may have installed stays.
        self.assertEqual(self.read("ca.crt"), old_ca)

    def test_an_empty_key_is_replaced(self):
        # A full disk while the key was written.
        tls.ensure(self.d, "myhome.example.com")
        open(os.path.join(self.d, "serve", "server.key"), "w").close()
        self.assertEqual(tls.ensure(self.d, "myhome.example.com"), ["server certificate"])
        self.assertTrue(tls.pair_matches(os.path.join(self.d, "serve")))

    def test_a_write_that_fails_leaves_the_old_file(self):
        tls.ensure(self.d, "myhome.example.com")
        key = os.path.join(self.d, "serve", "server.key")
        before = self.read("serve/server.key")

        class FullDisk(Exception):
            pass

        def full(*args, **kwargs):
            raise FullDisk()

        # The temporary file is written; swapping it in fails.
        with mock.patch("os.replace", full), self.assertRaises(FullDisk):
            tls.write_file(key, "half a key", private=True)
        self.assertEqual(self.read("serve/server.key"), before)
        self.assertFalse(os.path.exists(key + ".tmp"))

    def test_server_certificate_renewed_before_expiry(self):
        tls.ensure(self.d, "myhome.example.com")
        old_ca = open(os.path.join(self.d, "ca.crt")).read()
        # As if the server certificate were about to run out.
        tls.RENEW_SECONDS, saved = tls.SERVER_DAYS * 86400 + 86400, tls.RENEW_SECONDS
        try:
            made = tls.ensure(self.d, "myhome.example.com")
        finally:
            tls.RENEW_SECONDS = saved
        # The authority runs ten years and stays; only the server certificate is new.
        self.assertEqual(made, ["server certificate"])
        self.assertEqual(open(os.path.join(self.d, "ca.crt")).read(), old_ca)


if __name__ == "__main__":
    unittest.main()
