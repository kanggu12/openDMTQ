"""The release the README's and the guides' download lines name, against the one the chart carries.

    python3 .github/doc_versions.py [--write] [--root DIR]

The README's quick start and the guides download a release's files from that release's own address
(releases/download/v1.2.3/opendmtq-server-1.2.3-windows-x64.zip), run the one-line install from its tag
(raw.githubusercontent.com/kanggu12/openDMTQ/v1.2.3/host/get.sh) and clone the source at its tag for Docker (git
clone --branch v1.2.3, and git fetch origin tag v1.2.3 to update), so a line copied from them fetches what it names.
Every version written so must be the Helm chart's (deploy/helm/opendmtq/Chart.yaml), which a release raises, and every
file such a link names must be one of that release's (.github/release_assets.py) or of the tree. 1.2.3 is no release:
the guides write it where any release goes. Lists each place that names another version, or a file that is not there,
and exits 1; --write puts the chart's version in place of every other (a release raises the chart, then runs this with
--write). CHANGELOG.md keeps each release's own names and is not read. The standard library only, as
release_notes.py.
"""
import argparse
import importlib.util
import re
import sys
from pathlib import Path

# The repository: this file is in .github/.
ROOT = Path(__file__).resolve().parent.parent
# The project on GitHub, as the links name it.
REPO = "kanggu12/openDMTQ"
# A release's number as its files carry it: a pre-release part only as rc.N, alpha.N or beta.N, so that the rest of a
# file's name (-windows-x64) is never read as part of the number.
V = r"\d+\.\d+\.\d+(?:-(?:rc|alpha|beta)\.\d+)?"
# The number the guides write for "the release you want": no release carries it, so it stays as it is.
ANY = "1.2.3"
# Where a version is part of something to download, the version the pattern's one group.
PATTERNS = [
    # A release's own address on GitHub, the one-line install's script at a release's tag, and a release's source.
    re.compile(r"github\.com/" + REPO + r"/releases/download/v(" + V + r")/"),
    re.compile(r"raw\.githubusercontent\.com/" + REPO + r"/v(" + V + r")/"),
    re.compile(r"github\.com/" + REPO + r"/archive/refs/tags/v(" + V + r")\.tar\.gz"),
    # The release's files by their names (release_assets.py FILES): the server's, the PC client's, the phone runtime's,
    # the checksums and the PC client's update packages.
    re.compile(r"opendmtq-(?:server|pc-client|phone-runtime)-(" + V + r")-"),
    re.compile(r"opendmtq-(" + V + r")-sha256sums"),
    re.compile(r"opendmtq\.client-(" + V + r")-"),
    # The release's images on GitHub's registry.
    re.compile(r"ghcr\.io/kanggu12/opendmtq-(?:server|tools):(" + V + r")\b"),
    # The Docker way's clone of the release by its tag, and its update to a release's tag: a copy of the source is of one
    # release, as the downloads are, and follows no branch.
    re.compile(r"git (?:clone --branch|fetch origin tag|checkout -q) v(" + V + r")\b"),
]
# A link to one file to download, with its version and the file: a release's file, or the tree's file at a tag. It ends
# where Markdown, a shell or a quote ends it.
LINKS = [
    ("release", re.compile(r"github\.com/" + REPO + r"/releases/download/v(" + V + r")/([^\s)`\"'<>]+)")),
    ("tree", re.compile(r"raw\.githubusercontent\.com/" + REPO + r"/v(" + V + r")/([^\s)`\"'<>]+)")),
]
# The pages people copy download lines from, besides every guide in docs/.
PAGES = ["README.md", "CONTRIBUTING.md", "client/README.md", "arm32/README.md", "host/windows/README.txt"]


def _release_assets():
    """.github/release_assets.py, loaded from its file (it is no package's), for the names a release's files have."""
    spec = importlib.util.spec_from_file_location("release_assets", Path(__file__).resolve().parent / "release_assets.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def chart_version(root):
    """The chart's version, as release_notes.py reads it: the number a release raises first ("" when there is none)."""
    try:
        text = (root / "deploy" / "helm" / "opendmtq" / "Chart.yaml").read_text(encoding="utf-8")
    except OSError:
        return ""
    found = re.search(r"^version:\s*(.+?)\s*$", text, re.M)
    # Quoted or not, the number alone.
    return found.group(1).strip("'\"") if found else ""


def pages(root):
    """Every page read, as paths from the tree's top: the fixed ones the tree has, and every guide in docs/."""
    fixed = [p for p in PAGES if (root / p).is_file()]
    return fixed + sorted("docs/" + p.name for p in (root / "docs").glob("*.md"))


def stale(root, version=None):
    """Each place that names another release than the chart's, or a file its link cannot fetch, as (page, line number,
    what it names, why)."""
    version = version or chart_version(root)
    # The names the chart's release gives its files; a link of another version is reported for its version already.
    names = set(_release_assets().names(version).values())
    found = []
    for page in pages(root):
        for number, line in enumerate((root / page).read_text(encoding="utf-8").splitlines(), 1):
            for pattern in PATTERNS:
                for m in pattern.finditer(line):
                    # The chart's version, or the guides' stand-in for any release; a line that names it twice (a link
                    # and its file) said once.
                    place = (page, number, m.group(1), f"the chart is {version}")
                    if m.group(1) not in (version, ANY) and place not in found:
                        found.append(place)
            for kind, pattern in LINKS:
                for m in pattern.finditer(line):
                    # Only links of the chart's release: a stand-in's names a file of a release to come.
                    if m.group(1) != version:
                        continue
                    if kind == "release" and m.group(2) not in names:
                        found.append((page, number, m.group(2), f"release {version} has no such file"))
                    elif kind == "tree" and not (root / m.group(2)).is_file():
                        found.append((page, number, m.group(2), "the tree has no such file"))
    return found


def write(root, version=None):
    """Puts the chart's version in every place that names another release; returns the pages it changed."""
    version = version or chart_version(root)
    changed = []
    for page in pages(root):
        path = root / page
        text = path.read_text(encoding="utf-8")

        def put(m):
            # The match with its version swapped, the stand-in left as it is.
            if m.group(1) == ANY:
                return m.group(0)
            start, end = m.span(1)
            return m.group(0)[:start - m.start()] + version + m.group(0)[end - m.start():]
        new = text
        for pattern in PATTERNS:
            new = pattern.sub(put, new)
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed.append(page)
    return changed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="put the chart's version in place of every other")
    parser.add_argument("--root", type=Path, default=ROOT, help="the tree to read (the tests give their own)")
    args = parser.parse_args(argv)
    version = chart_version(args.root)
    if not version:
        print("deploy/helm/opendmtq/Chart.yaml has no version", file=sys.stderr)
        return 1
    if args.write:
        for page in write(args.root, version):
            print(f"{page}: now names {version}")
    problems = stale(args.root, version)
    # One line each, as the place, what it names and why, so that one run says everything there is to change; another
    # version has its fix in --write, a file that is not there needs the page itself changed.
    for page, number, what, why in problems:
        fix = " (.github/doc_versions.py --write)" if why.startswith("the chart") else ""
        print(f"{page}:{number} names {what}: {why}{fix}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
