"""Apache's piped logs on Windows (host/opendmtq_host/logpipe.py): the circle of files rotatelogs -n keeps, written by a
program with no console of its own."""

import importlib.util
import io
import os
import tempfile
import time
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = importlib.util.spec_from_file_location("logpipe", os.path.join(HERE, "..", "..", "host", "opendmtq_host", "logpipe.py"))
logpipe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(logpipe)


def read(path):
    with open(path, "rb") as f:
        return f.read()


class LogPipeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, "access.log")

    def test_lines_go_round_the_circle_of_files(self):
        lines = [f"line {i:02d} ".encode() + b"x" * 20 + b"\n" for i in range(9)]
        # 29 bytes a line, 70 a file: two lines in each, then the next file.
        logpipe.run(io.BytesIO(b"".join(lines)), self.path, 3, 70)
        # The circle went round once: access.log was emptied and written again with the last lines.
        self.assertEqual(read(self.path), lines[6] + lines[7])
        self.assertEqual(read(self.path + ".1"), lines[8])
        self.assertEqual(read(self.path + ".2"), lines[4] + lines[5])

    def test_a_new_run_goes_on_in_the_file_written_last(self):
        logpipe.run(io.BytesIO(b"a" * 40 + b"\n" + b"b" * 40 + b"\n"), self.path, 3, 60)
        self.assertEqual(read(self.path + ".1"), b"b" * 40 + b"\n")
        # Apache started again: the next line goes on in .1, the newest.
        time.sleep(0.01)
        logpipe.run(io.BytesIO(b"c\n"), self.path, 3, 60)
        self.assertEqual(read(self.path + ".1"), b"b" * 40 + b"\nc\n")
        self.assertEqual(read(self.path), b"a" * 40 + b"\n")

    def test_a_line_longer_than_a_file_is_kept_whole(self):
        logpipe.run(io.BytesIO(b"y" * 100 + b"\n"), self.path, 3, 50)
        self.assertEqual(read(self.path), b"y" * 100 + b"\n")

    def test_the_command_line_and_the_folder(self):
        nested = os.path.join(os.path.dirname(self.path), "logs", "server.log")
        with unittest.mock.patch.object(logpipe.sys, "stdin", io.TextIOWrapper(io.BytesIO(b"ok\n"))):
            self.assertEqual(logpipe.main(["logpipe.py", nested, "3", "10485760"]), 0)
        self.assertEqual(read(nested), b"ok\n")


if __name__ == "__main__":
    unittest.main()
