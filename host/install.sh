#!/usr/bin/env bash
# Installs what OpenDMTQ needs to run without containers; ./opendmtq then runs the server that way.
#
#   host/install.sh              Debian or Ubuntu (apt), or macOS (Homebrew)
#   host/install.sh --from DIR   Debian or Ubuntu with no internet: all of it from a folder carried in (docs/closed-network.md)
#   host/install.sh --uninstall  removes .host/ and the link on the PATH (data/ and the system packages stay)
#
# System packages: Apache with PHP's module, the PHP command line with SQLite and mbstring, Java, and Python with the
# admin pages' libraries. Into .host/ (beside data/, never committed): a Python environment that sees them, the pinned
# Android tools (apktool, uber-apk-signer) and the official 7-Zip, each checked against the hash of the copy that was
# tested. Safe to run again: it only does what is missing.
set -euo pipefail

# The clone this script is in, and this install's own folder in it.
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
LOCAL=$REPO/.host
# sudo for the system's own folders and packages, unless this already runs as root.
SUDO=""
if [[ $(id -u) -ne 0 ]]; then
  SUDO=sudo
fi

ok()   { printf '  \033[32mok\033[0m    %s\n' "$*"; }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }
fail() { printf '  \033[31merror\033[0m %s\n' "$*" >&2; exit 1; }

# The server runs as the user who installs it: as root, Apache would have to be told whom to become, and every file would
# end up root's. sudo is asked for where it is needed.
if [[ $(id -u) -eq 0 && ${1:-} != --uninstall ]]; then
  fail "please run this as the user who will run the server, not as root"
fi

# The pinned downloads: name, address, SHA-256. The same apktool and signer as the tools image (tools/Dockerfile).
APKTOOL_URL=https://github.com/iBotPeaches/Apktool/releases/download/v2.12.1/apktool_2.12.1.jar
APKTOOL_SHA=66cf4524a4a45a7f56567d08b2c9b6ec237bcdd78cee69fd4a59c8a0243aeafa
SIGNER_URL=https://github.com/patrickfav/uber-apk-signer/releases/download/v1.3.0/uber-apk-signer-1.3.0.jar
SIGNER_SHA=e1299fd6fcf4da527dd53735b56127e8ea922a321128123b9c32d619bba1d835
# Official 7-Zip 25.01: the distributions' 7-Zip and p7zip leave out RAR, which the game's archives use.
SEVENZIP_LINUX_X64_URL=https://www.7-zip.org/a/7z2501-linux-x64.tar.xz
SEVENZIP_LINUX_X64_SHA=4ca3b7c6f2f67866b92622818b58233dc70367be2f36b498eb0bdeaaa44b53f4
SEVENZIP_LINUX_ARM64_URL=https://www.7-zip.org/a/7z2501-linux-arm64.tar.xz
SEVENZIP_LINUX_ARM64_SHA=39c5140f02ce4436599303c59a149f654cb1bbc47cdc105a942120d747ae040d
SEVENZIP_MAC_URL=https://www.7-zip.org/a/7z2501-mac.tar.xz
SEVENZIP_MAC_SHA=26aa75bc262bb10bf0805617b95569c3035c2c590a99f7db55c7e9607b2685e0

# Debian's and Ubuntu's packages: what the system asks for, from its own sources or from the folder carried in.
APT_PACKAGES=(
  apache2 libapache2-mod-php php-cli php-sqlite3 php-mbstring
  default-jre-headless
  python3 python3-venv python3-flask python3-waitress python3-lz4 python3-pil python3-qrcode
  ca-certificates curl xz-utils
)
# The folder carried in (--from), on a network with no way out: empty when things are downloaded.
KIT=""

# A file put in its place only when whole and when its hash is the expected one: downloaded, or from the folder carried in, where
# it has the name it has here.
fetch() {
  local url=$1 sha=$2 dest=$3
  if [[ -f $dest ]] && echo "$sha  $dest" | sha_check; then
    return 0
  fi
  mkdir -p "$(dirname "$dest")"
  if [[ -n $KIT ]]; then
    cp "$KIT/$(basename "$dest")" "$dest.part" || fail "$(basename "$dest") is not in $KIT (docs/closed-network.md)"
  else
    # A stalled download (under 100 KB/s for a minute) is cut and tried again rather than waited on for ever.
    curl -fsSL --retry 3 --retry-delay 5 --connect-timeout 30 --speed-limit 100000 --speed-time 60 \
      -o "$dest.part" "$url" \
      || fail "could not download $url"
  fi
  echo "$sha  $dest.part" | sha_check || { rm -f "$dest.part"; fail "$url is not the tested file (its SHA-256 differs)"; }
  mv "$dest.part" "$dest"
}

# sha256sum on Linux, shasum on macOS; reads "hash  file" lines.
sha_check() {
  if command -v sha256sum >/dev/null; then
    sha256sum -c --quiet -
  else
    shasum -a 256 -c --quiet -
  fi
}

# Where the command goes: /usr/local/bin when this user or sudo (without asking again) may write there, else
# ~/.local/bin.
link_dir() {
  if [[ -w /usr/local/bin ]]; then
    echo /usr/local/bin
  elif [[ -n $SUDO ]] && sudo -n true 2>/dev/null; then
    echo /usr/local/bin
  else
    echo "$HOME/.local/bin"
  fi
}

uninstall() {
  step "Removing the host install"
  # The link on the PATH, when it is this clone's.
  for dir in /usr/local/bin "$HOME/.local/bin"; do
    if [[ -L $dir/opendmtq ]] && [[ $(readlink "$dir/opendmtq") == "$REPO/opendmtq" ]]; then
      if [[ -w $dir ]]; then rm -f "$dir/opendmtq"; else $SUDO rm -f "$dir/opendmtq"; fi
      ok "removed $dir/opendmtq"
    fi
  done
  # The Python environment, the pinned tools and the marker: ./opendmtq is the Docker command line again.
  rm -rf "$LOCAL"
  ok "removed $LOCAL (data/ is left as it is)"
}

# Debian and Ubuntu: everything from the distribution, the Python libraries included (as in the tools image).
install_apt() {
  step "System packages (apt)"
  # Apache comes with a service of its own that takes port 80: noted now, so that a service this script brings is
  # turned off again (OpenDMTQ runs its own Apache), and one that was there before is left alone.
  local had_apache=no
  if dpkg -s apache2 >/dev/null 2>&1; then
    had_apache=yes
  fi
  if [[ -n $KIT && -d $KIT/debs ]]; then
    compgen -G "$KIT/debs/*.deb" >/dev/null || fail "$KIT/debs has no packages in it (docs/closed-network.md)"
    # Carried in: apt puts them in the order they need, which dpkg by itself does not.
    $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends "$KIT"/debs/*.deb >/dev/null
  else
    # From the system's sources: on a closed network without packages carried in, its own mirror.
    $SUDO env DEBIAN_FRONTEND=noninteractive apt-get update -qq
    $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends "${APT_PACKAGES[@]}" >/dev/null
  fi
  ok "Apache, PHP, Java and Python's libraries"
  if [[ $had_apache == no ]] && command -v systemctl >/dev/null && systemctl is-enabled apache2 >/dev/null 2>&1; then
    $SUDO systemctl disable --now apache2 >/dev/null 2>&1 || true
    ok "the system's own Apache service is off (OpenDMTQ starts its own)"
  fi
  # A Python environment that sees the distribution's libraries.
  python3 -m venv --system-site-packages "$LOCAL/venv"
}

# macOS: Homebrew's Apache, PHP, Java and Python; the Python libraries into the environment from PyPI.
install_brew() {
  step "System packages (Homebrew)"
  command -v brew >/dev/null || fail "Homebrew is needed: see https://brew.sh"
  brew install --quiet httpd php openjdk python@3.12 >/dev/null
  ok "Apache, PHP, Java and Python"
  # Homebrew's Apache is a service only when asked (brew services); nothing to turn off.
  "$(brew --prefix)/opt/python@3.12/bin/python3.12" -m venv "$LOCAL/venv"
  "$LOCAL/venv/bin/pip" install -q "Flask>=3.0" "waitress>=3.0" "lz4>=4.3" "Pillow>=10.2" "qrcode>=7.4"
  ok "Flask, waitress, lz4, Pillow and qrcode"
}

main() {
  if [[ ${1:-} == --uninstall ]]; then
    uninstall
    return
  fi
  if [[ ${1:-} == --from ]]; then
    [[ -d ${2:-} ]] || fail "--from needs the folder carried in (docs/closed-network.md)"
    KIT=$(cd "$2" && pwd)
  fi
  case "$(uname -s)" in
    Linux)
      command -v apt-get >/dev/null || fail "this script knows Debian and Ubuntu (apt); elsewhere, use Docker (README)"
      install_apt
      ;;
    Darwin)
      # Homebrew and PyPI do not install from a folder.
      [[ -z $KIT ]] || fail "on a Mac this cannot be done without the internet: use Docker Compose (docs/closed-network.md)"
      install_brew
      ;;
    *)
      fail "unsupported system $(uname -s); on Windows, use the Windows bundle (README)"
      ;;
  esac

  step "The tools OpenDMTQ pins"
  # The tools package and the command line's modules, found by the environment's Python in isolated mode (-I) too.
  site=$("$LOCAL/venv/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
  printf '%s\n' "$REPO/tools" > "$site/opendmtq.pth"
  ok "Python environment in .host/venv"
  fetch "$APKTOOL_URL" "$APKTOOL_SHA" "$LOCAL/jars/apktool.jar"
  fetch "$SIGNER_URL" "$SIGNER_SHA" "$LOCAL/jars/uber-apk-signer.jar"
  ok "apktool 2.12.1 and uber-apk-signer 1.3.0"
  # The 7-Zip for this system and processor.
  local url sha
  case "$(uname -s)-$(uname -m)" in
    Linux-x86_64) url=$SEVENZIP_LINUX_X64_URL; sha=$SEVENZIP_LINUX_X64_SHA ;;
    Linux-aarch64|Linux-arm64) url=$SEVENZIP_LINUX_ARM64_URL; sha=$SEVENZIP_LINUX_ARM64_SHA ;;
    Darwin-*) url=$SEVENZIP_MAC_URL; sha=$SEVENZIP_MAC_SHA ;;
    *) fail "no official 7-Zip build for $(uname -s) $(uname -m)" ;;
  esac
  fetch "$url" "$sha" "$LOCAL/downloads/7zip.tar.xz"
  mkdir -p "$LOCAL/bin" "$LOCAL/share/7-zip"
  tar -xJf "$LOCAL/downloads/7zip.tar.xz" -C "$LOCAL/bin" 7zz
  # Its license stays beside it.
  tar -xJf "$LOCAL/downloads/7zip.tar.xz" -C "$LOCAL/share/7-zip" License.txt readme.txt
  ok "7-Zip 25.01"
  # The runtime for newer phones, where the app builder takes it from.
  if [[ -f $KIT/opendmtq-arm32-runtime.zip ]]; then
    mkdir -p "$REPO/data/apk"
    cp "$KIT/opendmtq-arm32-runtime.zip" "$REPO/data/apk/"
    ok "the runtime for newer phones, for the next app"
  elif [[ -n $KIT ]]; then
    printf '  note  opendmtq-arm32-runtime.zip is not in %s: without it the app runs only on phones that run 32-bit apps\n' "$KIT"
  fi

  step "The opendmtq command"
  # From now on ./opendmtq in this clone runs the server without containers (the marker tells it so).
  date -u +%Y-%m-%dT%H:%M:%SZ > "$LOCAL/installed"
  ok "./opendmtq runs this install (host/opendmtq_host)"
  # On the PATH too, as the Docker install puts it (cli/install.sh).
  local dir
  dir=$(link_dir)
  mkdir -p "$dir" 2>/dev/null || $SUDO mkdir -p "$dir"
  if [[ -w $dir ]]; then
    ln -sfn "$REPO/opendmtq" "$dir/opendmtq"
  else
    $SUDO ln -sfn "$REPO/opendmtq" "$dir/opendmtq"
  fi
  ok "$dir/opendmtq"
  case ":$PATH:" in
    *":$dir:"*) ;;
    *) printf '  note  %s is not on your PATH; add it, or run %s\n' "$dir" "$REPO/opendmtq" ;;
  esac
  printf '\nNext: ./opendmtq setup (it finds the game files in Downloads or on the Desktop, or pass --from <folder>).\n'
}

main "$@"
