"""What the tests share: a launcher folder of their own for each test, and a stand-in for the player."""

import os
import shutil
import tempfile
import textwrap
import unittest

# A stand-in for the player: a script that writes the arguments it was started with and the settings file it was given
# into a file beside itself, lists two made-up sound devices for --audio-devices, and ends with the code it is told.
FAKE_PLAYER = textwrap.dedent('''\
    import json, os, sys
    here = os.path.dirname(os.path.abspath(__file__))
    if sys.argv[1:] == ["--audio-devices"]:
        print(json.dumps({"id": "{0.0.0.00000000}.{aaaa}", "name": "Speakers (made up)", "default": True}))
        print("a line that is no device")
        print(json.dumps({"id": "{0.0.0.00000000}.{bbbb}", "name": "Headphones (made up)", "default": False}))
        sys.exit(0)
    args = sys.argv[1:]
    print("stand-in player: started")
    settings = open(args[args.index("--settings") + 1], encoding="utf-8").read() if "--settings" in args else ""
    with open(os.path.join(here, "started.json"), "w", encoding="utf-8") as f:
        json.dump({"args": args, "settings": settings}, f)
    sys.exit(int(os.environ.get("FAKE_PLAYER_EXIT", "0")))
''')


class Folder(unittest.TestCase):
    """A test with its own launcher folder (OPENDMTQ_CLIENT_DIR), its own user folder, and the stand-in player."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="odq-client-test-")
        self.saved = {k: os.environ.get(k) for k in ("OPENDMTQ_CLIENT_DIR", "LOCALAPPDATA", "XDG_DATA_HOME",
                                                     "OPENDMTQ_PLAYER", "FAKE_PLAYER_EXIT")}
        os.environ["OPENDMTQ_CLIENT_DIR"] = os.path.join(self.home, "client")
        os.environ["LOCALAPPDATA"] = os.path.join(self.home, "local")
        os.environ["XDG_DATA_HOME"] = os.path.join(self.home, "local")
        os.environ.pop("FAKE_PLAYER_EXIT", None)
        self.player = os.path.join(self.home, "player", "fake_player.py")
        os.makedirs(os.path.dirname(self.player))
        with open(self.player, "w", encoding="utf-8") as f:
            f.write(FAKE_PLAYER)
        os.environ["OPENDMTQ_PLAYER"] = self.player

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.home, ignore_errors=True)

    def started(self):
        """What the stand-in player was started with: {"args", "settings"}, or None."""
        import json
        path = os.path.join(os.path.dirname(self.player), "started.json")
        if not os.path.isfile(path):
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)
