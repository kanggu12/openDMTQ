#!/usr/bin/env bash
# What the load test does to a server's container beyond HTTP (tests/load/load.py runs these through run.sh's commands):
#   server.sh kill NAME PORT   SIGKILL, as a crash or the kernel's out-of-memory killer ends it, then started again as
#                              ./opendmtq up starts it; done once its health check answers on PORT, within a minute
#   server.sh check NAME       its database's integrity check ("ok" when it is whole)
#   server.sh fill NAME        the disk of its data folder filled to the last byte
#   server.sh free NAME        that room given back
set -u
case "${1:-}" in
  kill)
    # The kill, the container's end (a start while it is still going would be refused), and the start.
    docker kill -s KILL "$2" >/dev/null && docker wait "$2" >/dev/null && docker start "$2" >/dev/null || exit 1
    for _ in $(seq 1 120); do
      curl -sf -o /dev/null "http://127.0.0.1:$3/opendmtq/health.php" && exit 0
      sleep 0.5
    done
    echo "no answer a minute after the start"
    exit 1
    ;;
  check)
    # SQLite's own check of every page and index, in the server's PHP, on its database.
    docker exec "$2" php -r 'echo (new SQLite3("/data/dmtq.db3"))->querySingle("PRAGMA integrity_check"), "\n";'
    ;;
  fill)
    # Zeros until the disk refuses more, written as the server's own user; what is left, for the log.
    docker exec "$2" sh -c 'cat /dev/zero > /data/fill.bin 2>/dev/null; df -k /data | tail -n 1'
    ;;
  free)
    docker exec "$2" rm -f /data/fill.bin
    ;;
  *)
    echo "usage: server.sh kill NAME PORT | check NAME | fill NAME | free NAME" >&2
    exit 2
    ;;
esac
