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

# The latest release's tag (v1.2.3), or nothing when there is no release; fails when GitHub cannot be asked. Its page
# answers with a redirect to the tag's: not the API, whose limit for unnamed callers a shared address runs into.
latest_tag() {
  where=$(curl -fsSI --connect-timeout 15 --max-time 30 -o /dev/null -w '%{redirect_url}' \
    "https://github.com/$REPO/releases/latest") || return 1
  case $where in
    */releases/tag/*) printf '%s\n' "${where##*/}" ;;
  esac
}

# Where the code comes from: the release tagged $1, or the main branch while there is none. OPENDMTQ_TARBALL gives
# another copy (the host install's test gives its own).
code_url() {
  if [ -n "${OPENDMTQ_TARBALL:-}" ]; then
    printf '%s\n' "$OPENDMTQ_TARBALL"
  elif [ -n "$1" ]; then
    printf '%s\n' "https://github.com/$REPO/archive/refs/tags/$1.tar.gz"
  else
    printf '%s\n' "https://github.com/$REPO/archive/refs/heads/main.tar.gz"
  fi
}

# The code, into the folder only when it has come whole. Over what is there: only the program's files are in it, so the
# settings (.env), the data (data/) and this install's own programs (.host/) stay.
fetch_code() {
  tag=
  if [ -z "${OPENDMTQ_TARBALL:-}" ]; then
    # Not knowing is not "no release": that would put the newest code, tried by no release, in its place.
    tag=$(latest_tag) || die "GitHub could not be asked for the latest release: check the connection, then run this again${updating:+ (./opendmtq start starts the server meanwhile)}"
  fi
  url=$(code_url "$tag")
  say "Downloading OpenDMTQ into $DIR"
  mkdir -p "$(dirname "$DIR")"
  work=$(mktemp -d "$DIR.new.XXXXXX")
  # A stalled download (under 10 KB/s for a minute) stops with the message below. No retry: what curl already wrote has
  # gone into tar, and a second try would add to it.
  if ! curl -fsSL --connect-timeout 30 --speed-limit 10000 --speed-time 60 "$url" \
      | tar -xz --strip-components=1 -C "$work"; then
    rm -rf "$work"
    die "the download did not work: $url${updating:+. The server was stopped for the update: ./opendmtq start starts it again}"
  fi
  mkdir -p "$DIR"
  cp -R "$work/." "$DIR/"
  rm -rf "$work"
  # The release it is, which the site and the admin pages show and a bug report asks for. Code from elsewhere has none:
  # the number an earlier update wrote would be another's.
  if [ -n "$tag" ]; then
    printf '%s\n' "${tag#v}" > "$DIR/VERSION"
  else
    rm -f "$DIR/VERSION"
  fi
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
