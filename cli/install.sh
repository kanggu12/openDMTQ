#!/usr/bin/env bash
# Host install: checks prerequisites and puts `opendmtq` on PATH. Optionally adds a systemd unit
# that starts the server at boot (under WSL: when WSL starts). Safe to run again; --uninstall
# reverses it.
#
#   cli/install.sh               check prerequisites, link /usr/local/bin/opendmtq
#   cli/install.sh --service     also install and enable opendmtq.service (start at boot)
#   cli/install.sh --uninstall   remove the link and the unit (data/ is left alone)
set -euo pipefail

# The repository: this script's folder is cli/ in it.
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
LINK=/usr/local/bin/opendmtq
# The server's name on this machine (.env, when this is not the first copy here): one unit per server. A new clone has
# no .env yet, and that must not stop the script: with pipefail, a failed sed would.
NAME=
if [[ -f $REPO/.env ]]; then
  NAME=$(sed -n 's/^COMPOSE_PROJECT_NAME=//p' "$REPO/.env" | tail -n 1)
fi
NAME=${NAME:-opendmtq}
UNIT=/etc/systemd/system/$NAME.service
# Use sudo only for the system paths, and only when not already root.
SUDO=""; [[ $(id -u) -eq 0 ]] || SUDO="sudo"
# The user the server's containers run as when the command line runs as root (www-data).
CONTAINER_UID=33

ok()   { printf '  \033[32mok\033[0m    %s\n' "$*"; }
# To stderr: it also stops unit_user, whose output is captured.
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$*" >&2; exit 1; }

# The user the unit runs `opendmtq up` as, printed; stops when no user could run it from there.
# Whoever owns data/, so its files keep their owner: normally the one installing (under sudo, the one
# who ran sudo). ./opendmtq run as root hands data/ to www-data (uid 33): then the unit runs as root,
# as the command line did, since anyone else would stop at every boot on "data/state belongs to
# uid 33". Under sudo the checks in main ran as root, so the user's own access to Docker is checked
# here.
unit_user() {
  local user=${SUDO_USER:-$(id -un)} state=$REPO/data/state owner
  if [[ -d $state ]]; then
    owner=$(stat -c %u "$state")
    if [[ $owner -eq $CONTAINER_UID ]]; then
      user=root
    elif [[ $owner -ne $(id -u "$user") ]]; then
      if [[ $user == root ]] && id -nu "$owner" >/dev/null 2>&1; then
        # Installed by root for a user's own install: the unit runs as that user, as they do.
        user=$(id -nu "$owner")
      else
        fail "data/state belongs to uid $owner, not to $user, who would run the server; take it back once: sudo chown -R $(id -u "$user"):$(id -g "$user") $REPO/data"
      fi
    fi
  fi
  # Root reaches Docker anyway, and the installing user was checked in main. Another user needs the
  # docker group (and a new sign-in after joining it).
  if [[ $user != root && $user != "$(id -un)" ]] && ! sudo -u "$user" docker info >/dev/null 2>&1; then
    fail "$user cannot use Docker (add it to the docker group, sign in again, then run this again)"
  fi
  printf '%s\n' "$user"
}

main() {
  if [[ "${1:-}" == "--uninstall" ]]; then
    if [[ -f $UNIT ]]; then
      # Under the same name it can be another copy's, which has to keep running.
      if grep -qxF "WorkingDirectory=$REPO" "$UNIT"; then
        $SUDO systemctl disable --now "$NAME.service" || true
        $SUDO rm -f "$UNIT" && $SUDO systemctl daemon-reload
        ok "removed $NAME.service"
      else
        ok "$NAME.service belongs to another copy: left alone"
      fi
    fi
    # Only this copy's link: another copy may be the one on PATH.
    if [[ -L $LINK && $(readlink "$LINK") == "$REPO/opendmtq" ]]; then
      $SUDO rm -f "$LINK" && ok "removed $LINK"
    fi
    exit 0
  fi

  echo "Checking prerequisites"
  command -v docker >/dev/null || fail "Docker is not installed: https://docs.docker.com/engine/install/"
  docker info >/dev/null 2>&1 || fail "Docker is installed but not running (or this user cannot use it)"
  docker compose version >/dev/null 2>&1 || fail "the Docker Compose plugin is missing (docker compose)"
  ok "Docker $(docker version -f '{{.Server.Version}}'), $(docker compose version --short | sed 's/^/Compose /')"
  command -v python3 >/dev/null || fail "python3 is not installed"
  python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || fail "python3 3.9 or newer is required"
  ok "Python $(python3 -c 'import platform; print(platform.python_version())')"

  # One name on PATH: the first copy keeps it, the others run as ./opendmtq from their own folders.
  if [[ -L $LINK && $(readlink "$LINK") != "$REPO/opendmtq" && -e $LINK ]]; then
    ok "$LINK stays with $(readlink "$LINK"); this copy runs as ./opendmtq from its folder"
  else
    $SUDO ln -sfn "$REPO/opendmtq" "$LINK"
    ok "linked $LINK -> $REPO/opendmtq"
  fi

  if [[ "${1:-}" == "--service" ]]; then
    if ! command -v systemctl >/dev/null || [[ ! -d /run/systemd/system ]]; then
      fail "systemd is not running here"
    fi
    # Docker Desktop runs its engine outside this system: there is no docker.service to start after.
    systemctl cat docker.service >/dev/null 2>&1 \
      || fail "no docker.service here (Docker Desktop?); set RESTART=unless-stopped in .env instead and let Docker Desktop start when you sign in"
    # Another copy's unit under this name: ./opendmtq setup gives this copy a name of its own while that one runs.
    if [[ -f $UNIT ]] && ! grep -qxF "WorkingDirectory=$REPO" "$UNIT"; then
      fail "$NAME.service belongs to another copy; set COMPOSE_PROJECT_NAME in .env to a name of this copy's own, then run this again"
    fi
    local user
    user=$(unit_user)
    $SUDO tee "$UNIT" >/dev/null <<UNITFILE
[Unit]
Description=OpenDMTQ game server ($NAME)
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
User=$user
WorkingDirectory=$REPO
ExecStart="$REPO/opendmtq" up
ExecStop="$REPO/opendmtq" down
TimeoutStartSec=600

[Install]
WantedBy=multi-user.target
UNITFILE
    $SUDO systemctl daemon-reload
    $SUDO systemctl enable "$NAME.service" >/dev/null
    if grep -qi microsoft /proc/version 2>/dev/null; then
      ok "$NAME.service enabled, runs as $user (starts when WSL starts, not when Windows does; now: sudo systemctl start $NAME)"
    else
      ok "$NAME.service enabled, runs as $user (starts at boot; now: sudo systemctl start $NAME)"
    fi
  fi

  echo
  echo "Next: opendmtq setup"
}

# Run when executed; a test sources the file for unit_user alone.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
