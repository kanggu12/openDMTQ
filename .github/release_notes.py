"""A release's notes and its one version, before release.yml builds anything.

    python3 .github/release_notes.py v1.2.3 [--root DIR]

Checks that the tag, the Helm chart's version and appVersion (deploy/helm/opendmtq/Chart.yaml) and a section of
CHANGELOG.md all name the same version, then prints that section, which release.yml publishes as the release's notes.
Exits 1, saying what differs or what is missing: a release does not go out under a number its chart does not carry,
or without notes. The standard library only: it runs on the runner's own Python, before any setup.
"""
import argparse
import re
import sys
from pathlib import Path

# The repository: this file is in .github/.
ROOT = Path(__file__).resolve().parent.parent
# MAJOR.MINOR.PATCH, with an optional pre-release part, as semver.org writes it and Helm takes it.
SEMVER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z.-]+)?")


def chart_versions(root):
    """The chart's version and appVersion, each "" when it is not there; top-level keys only, quotes taken off."""
    try:
        text = (root / "deploy" / "helm" / "opendmtq" / "Chart.yaml").read_text(encoding="utf-8")
    except OSError:
        return "", ""

    def key(name):
        found = re.search(rf"^{name}:\s*(.+?)\s*$", text, re.M)
        return found.group(1).strip("'\"") if found else ""

    return key("version"), key("appVersion")


def section(text, version):
    """The body under `## [version]`, up to the next `## [` heading or the link list at the end; None if absent."""
    found = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|^\[[^\]\n]+\]: |\Z)", text, re.S | re.M)
    return found.group(1).strip() if found else None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tag", help="the release's tag, v1.2.3, or the bare number")
    parser.add_argument("--root", type=Path, default=ROOT, help="the tree to read (the tests give their own)")
    args = parser.parse_args(argv)
    # The tag's name or the bare number: the number is what every file carries.
    version = args.tag[1:] if args.tag.startswith("v") else args.tag
    problems = []
    if not SEMVER.fullmatch(version):
        problems.append(f"{args.tag} is not a version like v1.2.3")
    chart, app = chart_versions(args.root)
    # The chart is packaged with the tag's number either way; the file in the tree must say the same, or a chart built
    # from the source says another.
    if chart != version or app != version:
        problems.append(f"deploy/helm/opendmtq/Chart.yaml says version {chart or '?'}, appVersion {app or '?'}: "
                        f"set both to {version}")
    try:
        changelog = (args.root / "CHANGELOG.md").read_text(encoding="utf-8")
    except OSError:
        changelog = ""
    body = section(changelog, version)
    if not body:
        problems.append(f"CHANGELOG.md has no notes for {version}: add a '## [{version}] - YYYY-MM-DD' section")
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
