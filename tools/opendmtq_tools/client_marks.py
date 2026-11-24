"""The client's own names, for the patcher, the importer and their tests: the game's addresses as the original client
has them, its package name, the parts of its platform SDK and of its screens the patcher edits, the runtime's tweaks of
its code, and the names the runtime and the player look up in its code (written into arm32/src/client_names.h). The
repository's text names none of the game's servers, its app or its code (the owner's rule for every page, comment, test
and name of the project), so they are kept here as one table, compressed (zlib) and base64-encoded, and read by their
role: the rest of the code says what each is for, never what it is called.

    python3 -m opendmtq_tools.client_marks          prints the table, decoded, as JSON (for whoever changes it)
    python3 -m opendmtq_tools.client_marks FILE     prints this table's lines made again from a JSON file
    python3 -m opendmtq_tools.client_marks --cpp    prints arm32/src/client_names.h as this table makes it
"""
import base64
import json
import sys
import textwrap
import zlib

# The table: {"rpc_hosts", "addresses", "package", "sdk_edits", "screen_edits", "screen_needs", "tweaks", "player"},
# compressed and encoded (how it is made: main() below).
_TABLE = (
    "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"
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
    with open(argv[0], encoding="utf-8") as f:
        for line in encode(json.load(f)):
            print(f'    "{line}"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
