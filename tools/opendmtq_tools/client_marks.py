"""The client's own names, for the patcher, the importer and their tests: the game's addresses as the original client
has them, its package name, the parts of its platform SDK and of its screens the patcher edits, the runtime's tweaks of
its code, the bundle of its data that added songs' tiles are made from, the original server's pictures the game server
offers (written into server/game/src/client_names.php), and the names the runtime and the player look up in its code
(written into arm32/src/client_names.h). The
repository's text names none of the game's servers, its app or its code (the owner's rule for every page, comment, test
and name of the project), so they are kept here as one table, compressed (zlib) and base64-encoded, and read by their
role: the rest of the code says what each is for, never what it is called.

    python3 -m opendmtq_tools.client_marks          prints the table, decoded, as JSON (for whoever changes it)
    python3 -m opendmtq_tools.client_marks FILE     prints this table's lines made again from a JSON file
    python3 -m opendmtq_tools.client_marks --cpp    prints arm32/src/client_names.h as this table makes it
    python3 -m opendmtq_tools.client_marks --php    prints server/game/src/client_names.php as this table makes it
"""
import base64
import json
import sys
import textwrap
import zlib

# The table: {"rpc_hosts", "addresses", "package", "sdk_edits", "screen_edits", "screen_needs", "tweaks",
# "tile_template", "server_pictures", "player"}, compressed and encoded (how it is made: main() below).
_TABLE = (
    "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"
    "YfBmNb2+8O2/s3PLFA=="
)


def _decoded():
    """The table as the code reads it."""
    return json.loads(zlib.decompress(base64.b64decode("".join(_TABLE))).decode("utf-8"))


_MARKS = _decoded()
# The hosts the original client calls for the game's requests (/DMQ/rpc), its live one first.
RPC_HOSTS = tuple(_MARKS["rpc_hosts"])
# The game's own other addresses, the platform's API and its web base, each with what it becomes ({host}: this server).
ADDRESSES = dict(_MARKS["addresses"])
# Each of the two by its role: the API base becomes this server's /api, the web base this server itself.
API_BASE = next(old for old, new in ADDRESSES.items() if new == "http://{host}/api")
WEB_BASE = next(old for old, new in ADDRESSES.items() if new == "http://{host}")
# The original app's package name: each server's app adds its own part after it (patch_apk.package_id).
PACKAGE = _MARKS["package"]
# The SDK's edits, in order: (what it does, what kind: an address, the scheme, or what the SDK does; the file under
# smali/; the text there; the text it becomes ({host}: this server's address); how many times it is there).
SDK_EDITS = [tuple(edit) for edit in _MARKS["sdk_edits"]]
# The screens' edits: the asset file by its name in the APK, and each edit (hide, or move by x and y) of an object by
# its path in the scene; and the path prefixes whose edits go with a code edit (by the code edit's name).
SCREEN_EDITS = {name: [tuple(edit) for edit in edits] for name, edits in _MARKS["screen_edits"].items()}
SCREEN_NEEDS = dict(_MARKS["screen_needs"])
# The runtime's tweaks file's lines for the game's frame caps:
# <assembly> <namespace or -> <class> <field> <value or fps>.
TWEAKS = _MARKS["tweaks"]
# The shipped jacket atlas's bundle that added songs' tile bundles are made from (any would do: all have one layout), by
# its path in the client data's patch folder (songs.py).
TILE_TEMPLATE = _MARKS["tile_template"]
# The original server's pictures the game server offers from the imported content when it has them, by their role (the
# two pages of the "how to play" popup, two banners of old screens), each by its path under the content's web folder.
SERVER_PICTURES = dict(_MARKS["server_pictures"])
# The names the runtime and the player look up in the game's code and define for its SDKs, in the header's order: (its
# constant, what it is for, the name); a heading has no constant and no name, only its words.
PLAYER = [tuple(entry) for entry in _MARKS["player"]]
# The header's encoding of a name: each byte XORed with this key plus the byte's place (mod 256), as two hex digits.
CPP_KEY = 0x5C
# The header's opening: what it is, how it is read and where it comes from (its comment lines, then its code).
CPP_HEAD = """\
// The names the runtime and the player look up in the game's code and define for its SDKs: classes, their namespaces,
// methods, fields, the Unity object the platform's SDK answers and the events it sends, each by its role. The
// repository's text names none of the game's code, its app or its platform (the project's rule for its pages, comments,
// tests and names), so each name is kept here encoded and read where it is used: client_names::text(kInputClass). The
// encoding: each byte XORed with 0x5c plus the byte's place (mod 256), as two hex digits.
//
// Written by tools/opendmtq_tools/client_marks.py, from the table the patcher reads the client's names from (in tools/:
// python3 -m opendmtq_tools.client_marks --cpp > ../arm32/src/client_names.h); cli/tests/test_repo.py checks that this
// file is what the table makes.
#pragma once

#include <cstddef>
#include <string>

namespace client_names {

// A name as its text: each pair of hex digits one byte, XORed back with the key at its place.
inline std::string text(const char* hex) {
    // One hex digit's value (the header writes them in lower case).
    auto digit = [](char c) { return c <= '9' ? c - '0' : c - 'a' + 10; };
    std::string out;
    for (std::size_t i = 0; hex[i] != '\\0' && hex[i + 1] != '\\0'; i += 2) {
        // The byte as written, and the key at the byte's place.
        const int byte = digit(hex[i]) << 4 | digit(hex[i + 1]);
        const int key = (0x5c + static_cast<int>(i / 2)) & 0xff;
        out.push_back(static_cast<char>(byte ^ key));
    }
    return out;
}
"""


def cpp_text(name):
    """A name as arm32/src/client_names.h holds it: its bytes, each XORed with the key at its place, in hex."""
    return "".join(f"{b ^ ((CPP_KEY + i) & 0xFF):02x}" for i, b in enumerate(name.encode("utf-8")))


def cpp_header():
    """arm32/src/client_names.h, as this table makes it: the opening, then each heading and each name with its role."""
    lines = CPP_HEAD.split("\n")
    for const, role, name in PLAYER:
        # The words of a heading or a role, in comment lines the repository's width allows.
        words = textwrap.wrap(role, 113 if const is None else 117)
        if const is None:
            # A blank line between one part and the next.
            lines += ([""] if lines[-1] else []) + ["// ---- " + words[0]] + ["// " + more for more in words[1:]]
            continue
        lines += ["// " + line for line in words]
        line = f'constexpr const char {const}[] = "{cpp_text(name)}";'
        if len(line) <= 120:
            lines.append(line)
            continue
        # A long name in pieces of 112 hex digits, one a line, which the compiler joins into one string.
        hexed = cpp_text(name)
        pieces = [hexed[i:i + 112] for i in range(0, len(hexed), 112)]
        lines += [f"constexpr const char {const}[] ="] + [f'    "{piece}"' for piece in pieces[:-1]]
        lines.append(f'    "{pieces[-1]}";')
    return "\n".join(lines + ["", "}  // namespace client_names", ""])


# The game server's file of those paths: its opening, what it is and how it is read.
PHP_HEAD = """\
<?php
/*
 * The original server's pictures the game server offers from the imported content when it has them, each by its role:
 * the two pages of the "how to play" popup and two banners of old screens (game.getDefaultSetting). The repository's
 * text names none of the game's servers or their files (the project's rule for its pages, comments, tests and names),
 * so their paths are kept here encoded (base64 of a JSON object) and read by role: odq_client_path('howto_play').
 *
 * Written by tools/opendmtq_tools/client_marks.py from the table of the client's names (in tools/:
 * python3 -m opendmtq_tools.client_marks --php > ../server/game/src/client_names.php); cli/tests/test_repo.py checks
 * that this file is what the table makes.
 */
"""


def php_text():
    """server/game/src/client_names.php, as this table makes it: the paths by role, base64 of their JSON in pieces."""
    raw = json.dumps(SERVER_PICTURES, separators=(",", ":"), sort_keys=True).encode("utf-8")
    blob = base64.b64encode(raw).decode("ascii")
    pieces = [blob[i:i + 100] for i in range(0, len(blob), 100)]
    lines = PHP_HEAD.split("\n")
    lines += ["/* The paths by role: base64 of a JSON object, in pieces. */", "const ODQ_CLIENT_PATHS ="]
    lines += [f"    '{pieces[0]}'"]
    lines += [f"    . '{piece}'" for piece in pieces[1:]]
    lines[-1] += ";"
    lines += ["", "/* A picture's path under the content's web folder, by its role. */",
              "function odq_client_path(string $role): string", "{", "    static $paths = null;",
              "    // Decoded once a request.", "    $paths ??= json_decode(base64_decode(ODQ_CLIENT_PATHS), true);",
              "    return $paths[$role];", "}", ""]
    return "\n".join(lines)


def encode(table):
    """The lines of _TABLE for a table: JSON, compressed, base64, in pieces of 112 characters."""
    raw = json.dumps(table, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    blob = base64.b64encode(zlib.compress(raw, 9)).decode("ascii")
    return [blob[i:i + 112] for i in range(0, len(blob), 112)]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(json.dumps(_MARKS, ensure_ascii=False, indent=1))
        return 0
    if argv[0] == "--cpp":
        # The header, whole, with no newline of print's own after its last.
        sys.stdout.write(cpp_header())
        return 0
    if argv[0] == "--php":
        # The game server's file, whole, likewise.
        sys.stdout.write(php_text())
        return 0
    with open(argv[0], encoding="utf-8") as f:
        for line in encode(json.load(f)):
            print(f'    "{line}"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
