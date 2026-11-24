"""Prints the name the game's own server gave its host's folder, which the import knows the client data and the song data
by (as by what is in them): the tests lay their stand-in files out under it, as the game's files come. The name is
tools/opendmtq_tools/client_marks.py's, which keeps the client's names encoded (the repository's text names none of
them); that file is read alone, with the standard library only, so that any Python runs this.

    python3 tests/game_host.py
"""
import importlib.util
import os

# The table's module, by its path in this tree: the tools' package around it needs what a test machine may not have.
MARKS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "opendmtq_tools", "client_marks.py")
spec = importlib.util.spec_from_file_location("client_marks", MARKS)
marks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(marks)
# The game host's folder is named after its live RPC host.
print(marks.RPC_HOSTS[0])
