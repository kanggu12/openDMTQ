#!/bin/sh
# From nothing to the setup with one command, on Debian, Ubuntu, or macOS with Homebrew:
#
#   curl -fsSL https://raw.githubusercontent.com/kanggu12/openDMTQ/main/host/get.sh | sh
#
# Puts OpenDMTQ in ~/openDMTQ (OPENDMTQ_DIR says where), installs what the server needs without containers
# (host/install.sh), and opens the setup in the browser. Run again, it updates that folder: the settings and the data
# in it stay. Docker's way is the README's "With Docker".
#
# All of it is in functions, called on the last line: a shell reads a script from a pipe as it goes, so nothing runs from
# a download cut short, and nothing here may read this shell's own input, which is the script.
set -eu

REPO=kanggu12/openDMTQ

say() { printf '%s\n' "$*"; }
die() { printf 'OpenDMTQ: %s\n' "$*" >&2; exit 1; }

# Where the code comes from: the latest release, or the main branch while there is none. OPENDMTQ_TARBALL gives another
# copy (the host install's test gives its own).
code_url() {
  if [ -n "${OPENDMTQ_TARBALL:-}" ]; then
    printf '%s\n' "$OPENDMTQ_TARBALL"
    return
  fi
  tag=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null \
    | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -n 1) || tag=
  if [ -n "$tag" ]; then
    printf '%s\n' "https://github.com/$REPO/archive/refs/tags/$tag.tar.gz"
  else
    printf '%s\n' "https://github.com/$REPO/archive/refs/heads/main.tar.gz"
  fi
}

# The code, into the folder only when it has come whole. Over what is there: only the program's files are in it, so the
# settings (.env), the data (data/) and this install's own programs (.host/) stay.
fetch_code() {
  url=$(code_url)
  say "Downloading OpenDMTQ into $DIR"
  mkdir -p "$(dirname "$DIR")"
  work=$(mktemp -d "$DIR.new.XXXXXX")
  if ! curl -fsSL "$url" | tar -xz --strip-components=1 -C "$work"; then
    rm -rf "$work"
    die "the download did not work: $url"
  fi
  mkdir -p "$DIR"
  cp -R "$work/." "$DIR/"
  rm -rf "$work"
}

main() {
  DIR=${OPENDMTQ_DIR:-$HOME/openDMTQ}
  [ "$(id -u)" -ne 0 ] || die "please run this as the user who will run the server, not as root; it asks for sudo when it needs it"
  command -v curl >/dev/null 2>&1 || die "curl is needed: install it, then run this again"
  command -v tar >/dev/null 2>&1 || die "tar is needed: install it, then run this again"
  # What runs next may ask things, and must ask a person: this shell's own input is this script.
  if (: </dev/tty) 2>/dev/null; then
    input=/dev/tty
  else
    input=/dev/null
  fi
  # An update: the server stops first, and starts again with the setup below.
  updating=
  if [ -f "$DIR/.host/installed" ]; then
    updating=yes
    "$DIR/opendmtq" stop <"$input" || true
  fi
  fetch_code
  cd "$DIR"
  host/install.sh <"$input"
  # And it brings the latest release's runtime for newer phones. Not being able to changes nothing: the one there stays.
  if [ -n "$updating" ] && [ -f .env ]; then
    ./opendmtq runtime --no-app <"$input" || true
  fi
  # OPENDMTQ_NO_SETUP: only as far as this (the host install's test goes on by itself).
  if [ -n "${OPENDMTQ_NO_SETUP:-}" ]; then
    return 0
  fi
  exec ./opendmtq setup <"$input"
}

main
