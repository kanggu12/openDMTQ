#!/usr/bin/env python3
# Builds the time zone file the guest's C library reads (Android's tzdata) from a release of the tz database, for hosts
# that have no such file for the guest (the desktop players; a phone has its own).
#
#   python3 arm32/tools/tzdata.py <tzdataYYYYx.tar.gz> <out file>
#
# The zones are compiled as Android compiles its own: by zic, from the release's "rearguard" form (no negative daylight
# saving time, which Android's Java and its C library of the time never met) and with the 32-bit data ("-b fat"), the
# only part a C library with a 32-bit time_t reads. They are then put together as Android's ZoneCompactor does: a header,
# an index sorted by name, each zone's compiled file once, and zone.tab. The tz database is in the public domain.
import os
import struct
import subprocess
import sys
import tarfile
import tempfile

# The release's data files that zic compiles, as its Makefile lists them (TDATA): the regions, Etc/*, Factory, and
# the old names that link to current zones.
SOURCES = ["africa", "antarctica", "asia", "australasia", "europe", "northamerica", "southamerica", "etcetera",
           "factory", "backward"]
# The index's name field: the C library copies this many bytes and ends them itself.
NAME_BYTES = 40


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: tzdata.py <tzdataYYYYx.tar.gz> <out file>", file=sys.stderr)
        return 2
    tarball, out = sys.argv[1], sys.argv[2]
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(tarball) as t:
            # Only plain files and folders inside tmp, where Python can say so (3.12, and the 3.8 to 3.11 updates).
            if hasattr(tarfile, "data_filter"):
                t.extractall(tmp, filter="data")
            else:
                t.extractall(tmp)
        with open(os.path.join(tmp, "version"), encoding="ascii") as f:
            version = f.read().strip()
        # The header's 12 bytes: "tzdata", the release ("2026f") and a NUL, which the C library checks.
        magic = ("tzdata" + version).encode("ascii") + b"\0"
        if len(magic) != 12:
            print(f"tzdata.py: a release name of an unexpected length: {version!r}", file=sys.stderr)
            return 1
        # The rearguard form of the data, as the release's own Makefile makes it (rearguard.zi).
        zi = os.path.join(tmp, "rearguard.zi")
        with open(zi, "wb") as f:
            subprocess.run(["awk", "-v", "DATAFORM=rearguard", "-v", "PACKRATDATA=", "-v", "PACKRATLIST=",
                            "-f", "ziguard.awk", *SOURCES], cwd=tmp, stdout=f, check=True)
        zones = os.path.join(tmp, "zones")
        subprocess.run(["zic", "-b", "fat", "-d", zones, zi], check=True)
        # Every zone and link by its name ("Asia/Seoul"), in byte order: Android's index is sorted so.
        names = []
        for root, _dirs, files in os.walk(zones):
            for name in files:
                names.append(os.path.relpath(os.path.join(root, name), zones).replace(os.sep, "/"))
        names.sort(key=lambda n: n.encode("ascii"))
        # Each compiled file once: a link and its zone share their data, as in Android's file.
        data = bytearray()
        offsets = {}
        index = bytearray()
        for name in names:
            if len(name.encode("ascii")) > NAME_BYTES:
                print(f"tzdata.py: {name} is longer than the index's {NAME_BYTES} bytes", file=sys.stderr)
                return 1
            with open(os.path.join(zones, name), "rb") as f:
                body = f.read()
            if body not in offsets:
                offsets[body] = len(data)
                data += body
            # Name, start in the data, length, and a field the C library no longer reads (raw GMT offset, 0 since
            # Android's 2014f files).
            index += struct.pack(">40siii", name.encode("ascii"), offsets[body], len(body), 0)
        # zone.tab without its comment lines, as Android's file has it.
        with open(os.path.join(tmp, "zone.tab"), "rb") as f:
            zone_tab = b"".join(line for line in f if not line.startswith(b"#"))
        # Header: the magic, then where the index, the data and zone.tab start, big-endian.
        index_offset = 12 + 3 * 4
        data_offset = index_offset + len(index)
        zonetab_offset = data_offset + len(data)
        header = magic + struct.pack(">iii", index_offset, data_offset, zonetab_offset)
        # Written beside the target and renamed: a stopped build leaves the old file or none, never half of one.
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        part = out + ".part"
        with open(part, "wb") as f:
            f.write(header + index + data + zone_tab)
        os.replace(part, out)
        print(f"tzdata.py: {out}: {version}, {len(names)} names, {len(offsets)} zones")
    return 0


if __name__ == "__main__":
    sys.exit(main())
