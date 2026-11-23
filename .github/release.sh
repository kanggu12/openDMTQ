#!/usr/bin/env bash
# A release, made and published from the computer that holds the project's signing key: the steps of release.yml's publish
# job (which stops on GitHub, where there is no key) with the release's own checks before anything goes out. How a release
# is made, step by step: CONTRIBUTING.md, Releases.
#
#   OPENDMTQ_SIGNING_KEY=<key file> .github/release.sh [--dry-run] VERSION [OUT]
#
# VERSION is the release's number (1.2.3; its tag is v1.2.3), OUT the folder everything is made in (default
# _work/release/VERSION). It runs in this checkout, which must be clean: the files the release puts beside the tools' code
# (the runtime for newer phones, the PC client's installer and its update files, all git-ignored) are taken away again
# at the end. Its steps, each with its log in OUT/logs and one line on the screen:
#   1. gates: the tag is HEAD's, the chart and CHANGELOG.md name VERSION and have its notes, the README's and the guides'
#      download lines name it, CI and qa/local passed on it
#   2. the runtime for newer phones and the player for Windows (arm32/), then the PC client's installer and its update
#      packages, the delta from the last release's full package
#   3. the Windows bundle, with the runtime and the installer beside the tools' code as a release has them
#   4. the release's files under their names, checksummed and signed (.github/release_assets.py), and checked against
#      the project's key (tools/opendmtq_tools/signing.py); the PC client's update files beside the tools' code
#   5. the release's checks: the Windows bundle under Wine, a host install on Debian 12, and the last release's PC client
#      updating to these files under Wine (tests/windows/wine.sh, tests/host/run.sh, tests/release/update.sh)
#   6. the images, the server's for amd64 and arm64 and the tools' for amd64, built from this checkout
#   7. published: release.yml held while main and the tag go up, the images and the chart pushed to GHCR, the GitHub
#      release made with its notes and files, release.yml on again
# --dry-run does 2 to 6 and publishes nothing: no tag is needed (HEAD is laid out as VERSION), the gates of 1 are said
# without stopping it, and without OPENDMTQ_SIGNING_KEY the files are laid out unsigned (a rehearsal no client takes).
#
# OPENDMTQ_PREVIOUS_RELEASE: a folder with the last release's files (its installer, update feed and full package): the
#   delta package starts from it and the update check installs it. Without it they come from the latest release on GitHub.
# APK: the game's client (an APK file), for the checks that build the phone app (the bundle under Wine, the host install);
#   without it those checks go without the app, as CI's do.
# NAME_PREFIX, PORT and SUBNET: the checks' own Docker names, port and network, as the tests take them (a run beside
#   another); the images' builder is NAME_PREFIX-release.
# Needs Docker with buildx, git, gh (signed in, for the gates, the last release's files and the publishing), Helm and
# Python 3.
set -euo pipefail

DRY=
if [ "${1:-}" = --dry-run ]; then
  DRY=yes
  shift
fi
VERSION=${1:?usage: .github/release.sh [--dry-run] VERSION [OUT]}
case $VERSION in
  v*) echo "the version without its v: ${VERSION#v}" >&2; exit 2 ;;
esac
[[ $VERSION =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]] || { echo "not a version: $VERSION" >&2; exit 2; }
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
# Buildx's builder for the images of every platform, by this run's names.
BUILDER=${NAME_PREFIX:-odq}-release
OUT=$(realpath -m "${2:-$ROOT/_work/release/$VERSION}")
LOGS=$OUT/logs
T=$ROOT/tools/opendmtq_tools
# No step changes the firewall of a Windows host or asks for its administrator (a WSL machine): every command line takes it.
export OPENDMTQ_NO_FIREWALL=1
# The runtime's build never asks for an Android NDK or SDK of this computer: it fetches the one CI tests with.
export ANDROID_NDK="" ANDROID_HOME=/nonexistent

# This repository on GitHub, from its remote: the registry, the update source the PC client is built with, the release.
ORIGIN=$(git remote get-url origin)
REPO=$(sed -E 's#^(git@[^:]+:|https?://[^/]+/)##; s#\.git$##' <<<"$ORIGIN")
OWNER=${REPO%%/*}
REGISTRY=ghcr.io/$(tr '[:upper:]' '[:lower:]' <<<"$OWNER")
SOURCE=https://github.com/$REPO

mkdir -p "$OUT" "$LOGS"
# The PC client's packages take their version from the chart: a release's files of another number would not lay out.
CHART=$(sed -n 's/^version:[[:space:]]*"\{0,1\}\([0-9A-Za-z.+-]*\)"\{0,1\}[[:space:]]*$/\1/p' deploy/helm/opendmtq/Chart.yaml | head -n 1)
[ "$CHART" = "$VERSION" ] || { echo "the chart says $CHART: set version and appVersion in deploy/helm/opendmtq/Chart.yaml to $VERSION first" >&2; exit 1; }
# One step: its function in a shell of its own that stops at its first failure (a function tested by an if would not),
# its output to its log, one line on the screen; the release stops at a step that failed.
step() {
  local name=$1 began status
  shift
  began=$(date +%s)
  set +e
  (set -e; "$@") > "$LOGS/$name.log" 2>&1
  status=$?
  set -e
  if [ "$status" -eq 0 ]; then
    echo "PASS $name ($(($(date +%s) - began)) s)"
  else
    echo "FAIL $name ($(($(date +%s) - began)) s): see $LOGS/$name.log"
    exit 1
  fi
}
# The files a release puts beside the tools' code, for the Windows bundle and the tools image: taken away again whatever
# happens, so that the checkout is as it was.
STAGED=("$T/opendmtq-arm32-runtime.zip" "$T/OpenDMTQ-Setup.exe" "$T/OpenDMTQ-Setup.exe.version" "$T/pc-client-updates")
unstage() {
  rm -rf "${STAGED[@]}"
}
trap unstage EXIT
# A Windows program left executable here would run on the host's Windows under WSL: none stays so.
# (An if, not an &&: the loop's status is its last command's, and a step stops at the first that fails.)
quiet_programs() {
  find "$@" -type f -perm /111 -print0 2>/dev/null | while IFS= read -r -d '' f; do
    if [ "$(head -c 2 "$f" | tr -d '\0')" = MZ ]; then
      chmod a-x "$f"
    fi
  done
}

# ---- 1. gates
gates() {
  local problems=0 sha state
  sha=$(git rev-parse HEAD)
  if [ -n "$(git status --porcelain)" ]; then
    echo "the tree has changes that are not committed"
    problems=1
  fi
  if [ "$(git rev-parse -q --verify "refs/tags/v$VERSION^{commit}" || true)" != "$sha" ]; then
    echo "the tag v$VERSION is not HEAD's (an annotated tag: git tag -a v$VERSION)"
    problems=1
  fi
  # One version in the chart and CHANGELOG.md, with notes for it.
  python3 .github/release_notes.py "v$VERSION" > "$OUT/release-notes.md" || problems=1
  # The README's quick start and the guides download this release's files by their names (the release commit runs
  # .github/doc_versions.py --write), so that a line copied from them fetches what it says.
  python3 .github/doc_versions.py || problems=1
  # CI on GitHub: every check of this commit finished and passed (a skipped one counts as passed, as for a deploy).
  if ! gh api "repos/$REPO/commits/$sha/check-runs?per_page=100" --jq '.check_runs[] | "\(.name)=\(.status)/\(.conclusion)"' \
      > "$OUT/check-runs.txt"; then
    echo "cannot ask GitHub about $sha (is gh signed in, is the commit pushed?)"
    problems=1
  elif [ ! -s "$OUT/check-runs.txt" ] || grep -vE '=completed/(success|skipped)$' "$OUT/check-runs.txt" | grep -vE '^(qa|publish)='; then
    echo "CI has not passed on $sha (above)"
    problems=1
  fi
  state=$(gh api "repos/$REPO/commits/$sha/status" --jq '[.statuses[] | select(.context == "qa/local")][0].state' || true)
  if [ "$state" != success ]; then
    echo "qa/local is ${state:-not there} on $sha: run tests/qa.sh on it"
    problems=1
  fi
  return "$problems"
}
if [ -n "$DRY" ]; then
  # Said, not a stop: a dry run comes before the tag and the gates.
  if gates > "$LOGS/gates.log" 2>&1; then
    echo "PASS gates"
  else
    echo "(a real run would stop here: $(paste -sd ';' "$LOGS/gates.log"))"
    python3 .github/release_notes.py "v$VERSION" > "$OUT/release-notes.md" 2>/dev/null \
      || python3 .github/release_notes.py "v$(sed -n 's/^version: *//p' deploy/helm/opendmtq/Chart.yaml)" > "$OUT/release-notes.md"
  fi
else
  [ -n "${OPENDMTQ_SIGNING_KEY:-}" ] && [ -f "$OPENDMTQ_SIGNING_KEY" ] \
    || { echo "no signing key: OPENDMTQ_SIGNING_KEY names the project's key file" >&2; exit 1; }
  step gates gates
fi
# The project's key, by its full path (steps run in other folders).
SIGN=()
if [ -n "${OPENDMTQ_SIGNING_KEY:-}" ]; then
  OPENDMTQ_SIGNING_KEY=$(realpath "$OPENDMTQ_SIGNING_KEY")
  export OPENDMTQ_SIGNING_KEY
else
  SIGN=(--unsigned)
fi

# ---- 2. the runtime, the player, the PC client
D=$OUT/dist
mkdir -p "$D"
# The runtime for newer phones from this source, with the NDK CI tests with, as a release's zip (licences in it).
runtime() {
  arm32/bundle.sh "$OUT/arm32"
  python3 tools/opendmtq_tools/runtime.py --pack "$OUT/arm32" "$D/opendmtq-arm32-runtime.zip"
}
step runtime runtime
# The player for Windows, from the same guest system and Dynarmic, packed as the PC client's installer carries it.
player() {
  arm32/build_windows.sh player
  arm32/bundle_windows.sh "$D/opendmtq-player-windows.zip"
}
step player player
# The last release's files: as given, or the latest release's on GitHub (before this one is published, the one before it).
previous() {
  local dir=$OUT/previous tag
  if [ -n "${OPENDMTQ_PREVIOUS_RELEASE:-}" ]; then
    dir=$(realpath "$OPENDMTQ_PREVIOUS_RELEASE")
  else
    rm -rf "$dir" && mkdir -p "$dir"
    tag=$(gh release view -R "$REPO" --json tagName --jq .tagName)
    [ "$tag" != "v$VERSION" ] || { echo "v$VERSION is published already"; return 1; }
    gh release download "$tag" -R "$REPO" -D "$dir" --pattern '*-full.nupkg' --pattern 'releases.win.json' \
      --pattern '*setup.exe' --pattern 'OpenDMTQ-Setup.exe*'
    echo "${tag#v}" > "$dir/version"
  fi
  # As the update check takes it: the installer and its version under the names it had before release names were
  # lower case.
  mkdir -p "$OUT/previous-installed"
  cp "$dir"/*-full.nupkg "$dir/releases.win.json" "$OUT/previous-installed/"
  local setup
  setup=$(find "$dir" -maxdepth 1 \( -name 'OpenDMTQ-Setup.exe' -o -name '*-windows-x64-setup.exe' \) | head -1)
  [ -n "$setup" ] || { echo "no installer among the last release's files in $dir"; return 1; }
  cp "$setup" "$OUT/previous-installed/OpenDMTQ-Setup.exe"
  if [ -f "$dir/OpenDMTQ-Setup.exe.version" ]; then
    cp "$dir/OpenDMTQ-Setup.exe.version" "$OUT/previous-installed/"
  elif [ -f "$dir/version" ]; then
    cp "$dir/version" "$OUT/previous-installed/OpenDMTQ-Setup.exe.version"
  else
    basename "$setup" | sed -nE 's/^opendmtq-pc-client-([0-9][^-]*)-windows.*/\1/p' > "$OUT/previous-installed/OpenDMTQ-Setup.exe.version"
  fi
  echo "the last release: $(cat "$OUT/previous-installed/OpenDMTQ-Setup.exe.version") from $dir"
  PREVIOUS=$dir
  echo "$PREVIOUS" > "$OUT/previous.path"
  quiet_programs "$dir" "$OUT/previous-installed"
}
step previous previous
# (Each step runs in a shell of its own: what one leaves for the next is in OUT.)
PREVIOUS=$(cat "$OUT/previous.path")
# The PC client's installer and its update packages, updating from this repository's releases, the delta from the last
# release's full package.
client() {
  OPENDMTQ_PREVIOUS_RELEASE=$PREVIOUS OPENDMTQ_UPDATE_SOURCE=$SOURCE PLAYER_ZIP="$D/opendmtq-player-windows.zip" \
    client/packaging/windows/build.sh "$OUT/client"
  # Only this build's files: an earlier build's would go up with the release.
  rm -rf "$D/client" && mkdir -p "$D/client"
  cp "$OUT/client/releases/"* "$D/client/"
  quiet_programs "$OUT/client" "$D"
  echo "PC client $(cat "$OUT/client/releases/OpenDMTQ-Setup.exe.version"): $(ls "$D/client" | tr '\n' ' ')"
}
step client client

# ---- 3. the Windows bundle, with the runtime and the installer as a release has them beside the tools' code
windows() {
  # Beside the tools' code, as the bundle and the tools image carry them (git-ignored; unstage takes them away).
  cp "$D/opendmtq-arm32-runtime.zip" "$T/"
  cp "$D/client/OpenDMTQ-Setup.exe" "$D/client/OpenDMTQ-Setup.exe.version" "$T/"
  chmod a-x "$T/OpenDMTQ-Setup.exe"
  rm -rf "$OUT/windows" && mkdir -p "$OUT/windows"
  VERSION=$VERSION ARM32_BUNDLE="$OUT/arm32" host/windows/build.sh "$OUT/windows"
  cp "$OUT/windows/OpenDMTQ-windows.zip" "$D/"
  quiet_programs "$OUT/windows"
}
step windows windows

# ---- 4. the release's files, signed and checked; the PC client's update files beside the tools' code
layout() {
  rm -rf "$D/release"
  helm package deploy/helm/opendmtq --version "$VERSION" --app-version "$VERSION" -d "$D"
  python3 .github/release_assets.py layout "$VERSION" "$D/release" --runtime "$D/opendmtq-arm32-runtime.zip" \
    --client "$D/client" --windows "$D/OpenDMTQ-windows.zip" --chart "$D/opendmtq-$VERSION.tgz" ${SIGN[@]+"${SIGN[@]}"}
  if [ "${#SIGN[@]}" -eq 0 ]; then
    # The signature, by a key every launcher and server takes.
    python3 tools/opendmtq_tools/signing.py check "$D/release/opendmtq-$VERSION-sha256sums.txt"
  fi
  # A test's key in the tools would make the image take a test's releases: a release's tools take the project's alone.
  [ ! -s "$T/update-test-keys.txt" ] || { echo "$T/update-test-keys.txt is not empty"; return 1; }
  rm -rf "$T/pc-client-updates" && mkdir -p "$T/pc-client-updates"
  cp "$D/release/releases.win.json" "$D/release/opendmtq.client-$VERSION-"*.nupkg "$D/release/opendmtq-$VERSION-sha256sums.txt" "$T/pc-client-updates/"
  [ "${#SIGN[@]}" -ne 0 ] || cp "$D/release/opendmtq-$VERSION-sha256sums.txt.sig" "$T/pc-client-updates/"
  ls -l "$D/release"
}
step layout layout

# ---- 5. the release's checks
APKS=()
[ -z "${APK:-}" ] || APKS=(APK="$(realpath "$APK")")
bundle_wine() {
  env NO_BUILD=1 OUT="$OUT/windows" ${APKS[@]+"${APKS[@]}"} tests/windows/wine.sh
}
step wine bundle_wine
# With the release's own runtime for newer phones, which the app built there takes.
host_debian() {
  env DISTRO=debian:12 ARM32_BUNDLE="$OUT/arm32" ${APKS[@]+"${APKS[@]}"} tests/host/run.sh
}
step debian host_debian
# The last release's launchers updating to these files, and servers taking the runtime the release carries: by the
# version its build wrote (the tag's, v1.2.3-<its hash>; a rehearsal's from its commit, which has no tag).
update() {
  local runtime
  runtime=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["version"])' "$OUT/arm32/bundle.json")
  RUNTIME_VERSION=$runtime tests/release/update.sh "$OUT/previous-installed" "$D/release" "$OUT/update"
  quiet_programs "$OUT/update"
}
if [ "${#SIGN[@]}" -eq 0 ]; then
  step update update
else
  # The last release's launchers take only what the project's key signed: an unsigned rehearsal is not theirs to take.
  echo "(update: not without the project's key; the last release's launchers would rightly refuse these files)"
fi

# ---- 6. the images, for every platform a release publishes them for
images() {
  local push=()
  [ -n "$DRY" ] || push=(--push)
  docker buildx inspect "$BUILDER" >/dev/null 2>&1 || docker buildx create --name "$BUILDER" --driver docker-container
  docker buildx build --builder "$BUILDER" --platform linux/amd64,linux/arm64 ${push[@]+"${push[@]}"} \
    --label "org.opencontainers.image.source=$SOURCE" --build-arg "OPENDMTQ_VERSION=$VERSION" \
    -t "$REGISTRY/opendmtq-server:$VERSION" -t "$REGISTRY/opendmtq-server:latest" server
  docker buildx build --builder "$BUILDER" --platform linux/amd64 ${push[@]+"${push[@]}"} \
    --label "org.opencontainers.image.source=$SOURCE" --build-arg "OPENDMTQ_VERSION=$VERSION" \
    -t "$REGISTRY/opendmtq-tools:$VERSION" -t "$REGISTRY/opendmtq-tools:latest" tools
}
if [ -n "$DRY" ]; then
  step images images
  docker buildx rm "$BUILDER" >/dev/null 2>&1 || true
  echo "dry run of $VERSION done: the release's files in $D/release$([ "${#SIGN[@]}" -eq 0 ] || echo ' (unsigned: a rehearsal)'); nothing was pushed or published"
  exit 0
fi

# ---- 7. published
publish() {
  # release.yml runs on the tag and stops without a key, by design: held while the tag goes up.
  gh workflow disable release -R "$REPO"
  git push origin HEAD:main
  git push origin "v$VERSION"
  gh auth token | docker login ghcr.io -u "$OWNER" --password-stdin
  gh auth token | helm registry login ghcr.io -u "$OWNER" --password-stdin
  images
  helm push "$D/opendmtq-$VERSION.tgz" "oci://$REGISTRY/charts"
  # The notes are this version's part of CHANGELOG.md, with the compare link GitHub adds; the files are the release's
  # folder alone, as layout made and checked it.
  gh release create "v$VERSION" -R "$REPO" "$D"/release/* --notes-file "$OUT/release-notes.md" --generate-notes --verify-tag
  gh workflow enable release -R "$REPO"
  docker buildx rm "$BUILDER" || true
  docker logout ghcr.io || true
  helm registry logout ghcr.io || true
}
step publish publish
echo "published v$VERSION: $SOURCE/releases/tag/v$VERSION"
