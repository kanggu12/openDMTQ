#!/usr/bin/env bash
# The game server's contract with the game (tests/game/protocol.py) on a throwaway server: builds the server image from
# this working tree, makes the stand-in game files of the pages' tests (tests/ui/make_content.php), starts the server on
# loopback with an empty database, runs the checks, and removes everything again. Needs nothing but Docker and Python 3.
#
# Usage: tests/game/protocol.sh        (PORT, default 18701; KEEP=1 leaves the server up)
# Also runs tests/game/lock.php and tests/game/names.php on the same database, and fails on any PHP warning in the server's
# log.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
TAG=protocol
NAME=odq-protocol
PORT=${PORT:-18701}
DATA=$(mktemp -d)

# What the container wrote belongs to its user: removed from inside the image.
cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker run --rm -u 0 -v "$DATA:/d" --entrypoint sh "opendmtq-server:$TAG" -c 'rm -rf /d/* /d/.[!.]*' >/dev/null 2>&1 || true
  rmdir "$DATA" 2>/dev/null || true
}
if [ -z "${KEEP:-}" ]; then
  trap cleanup EXIT
fi

docker build -q -t "opendmtq-server:$TAG" "$ROOT/server" >/dev/null
mkdir -p "$DATA/content" "$DATA/state" "$DATA/custom" "$DATA/apk"
chmod -R a+rwX "$DATA"
docker run --rm -u 33:33 -v "$DATA/content:/content" -v "$ROOT/tests/ui:/ui:ro" --entrypoint php "opendmtq-server:$TAG" /ui/make_content.php /content >/dev/null
# The song list as the tools write it once the owner hides a song (songs.py rebuild()): the stand-in songs, the last one
# kept in the list and marked hidden. A play of its charts is still a play of this server's (protocol.py).
# Its number goes to protocol.py, which then holds the hidden song's checks to it.
HIDDEN_SONG=$(python3 -c 'import json, sys; songs = json.load(open(sys.argv[1], encoding="utf-8")); songs[-1]["hidden_yn"] = "Y"; json.dump(songs, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False); print(songs[-1]["song_id"])' \
  "$DATA/content/songs.json" "$DATA/custom/songList.json")
docker rm -f "$NAME" >/dev/null 2>&1 || true
# As compose starts it: read-only, unprivileged, capped.
docker run -d --name "$NAME" --cpus 2 --memory 1g -u 33:33 --read-only --tmpfs /var/opendmtq:mode=1777 --tmpfs /tmp:mode=1777 \
  -e PUBLIC_HOST="127.0.0.1:$PORT" -e ADMIN_ON_PUBLIC_PORT=no -e TZ=Asia/Seoul \
  -v "$DATA/content:/srv/content:ro" -v "$DATA/state:/data" -v "$DATA/apk:/srv/apk:ro" -v "$DATA/custom:/srv/custom:ro" \
  -p "127.0.0.1:$PORT:8080" "opendmtq-server:$TAG" >/dev/null
# Until it answers, or give up with its log.
for _ in $(seq 1 60); do
  curl -sf -m 3 -o /dev/null "http://127.0.0.1:$PORT/opendmtq/health.php" && break
  sleep 1
done
if ! curl -sf -m 3 -o /dev/null "http://127.0.0.1:$PORT/opendmtq/health.php"; then
  echo "FAIL the server did not come up on the stand-in game files" >&2
  docker logs --tail 30 "$NAME" >&2
  exit 1
fi
failed=0
PROTOCOL_HIDDEN_SONG="$HIDDEN_SONG" python3 "$ROOT/tests/game/protocol.py" "http://127.0.0.1:$PORT" || failed=1
# Storing achievements while another writer holds the database, on the same database, beside the running server.
docker run --rm -u 33:33 -v "$DATA/state:/data" -v "$ROOT/tests/game:/t:ro" --entrypoint php "opendmtq-server:$TAG" \
  /t/lock.php /data/dmtq.db3 || failed=1
# Players' names that are no UTF-8, as an older server's database can hold them: the start batch that lists one, and the
# next start's repair of them (tests/game/names.php), inside the running server, on its database and at its own address.
docker exec -i "$NAME" php -- /data/dmtq.db3 http://127.0.0.1:8080 < "$ROOT/tests/game/names.php" || failed=1
# The monthly rankings read the play log from one index alone (PlayLog_board, setup-db.php), never the table once per
# play: the plan SQLite makes of the statement the server runs (odq_month_board_sql()), for TOTAL and a line's tab, on
# the server's own database.
# shellcheck disable=SC2016  # PHP code: its $variables are PHP's, not the shell's.
plan=$(docker exec "$NAME" php -r '
  require "/opt/opendmtq/game/src/ranking.php";
  foreach (["TOTAL" => NULL, "2LINE" => odq_patterns(3)] as $board => $patterns) {
      $r = odq_db()->query("EXPLAIN QUERY PLAN " . odq_month_board_sql($patterns));
      while ($r && ($row = $r->fetchArray(SQLITE3_ASSOC))) {
          echo $board, ": ", $row["detail"], "\n";
      }
  }' 2>&1) || true
# The lines that read the log (its alias is l): one per board, each from the index alone.
reads=$(grep -E '^[A-Z0-9]+: (SEARCH|SCAN) l( |$)' <<<"$plan" || true)
if [ "$(grep -c 'USING COVERING INDEX PlayLog_board ' <<<"$reads")" = 2 ] && [ "$(grep -c . <<<"$reads")" = 2 ]; then
  echo "PASS the monthly rankings read the play log from one index alone"
else
  echo "FAIL the monthly rankings read more of the play log than one index:"
  echo "$plan" | sed 's/^/  /'
  failed=1
fi
# A save works out the player's achievements twice, before it and after it: their best rows and their clears chart by
# chart, each from one index alone (Play_held, PlayLog_clears; setup-db.php) and in its order, never the table once per
# row (on a million plays that was 19 ms a save against 1.6). The plans of the statements the server runs.
# shellcheck disable=SC2016  # PHP code: its $variables are PHP's, not the shell's.
plan=$(docker exec "$NAME" php -r '
  require "/opt/opendmtq/game/src/rpc.php";
  foreach (["best" => odq_held_best_sql(), "clears" => odq_held_clears_sql()] as $what => $sql) {
      $r = odq_db()->query("EXPLAIN QUERY PLAN " . $sql);
      while ($r && ($row = $r->fetchArray(SQLITE3_ASSOC))) {
          echo $what, ": ", $row["detail"], "\n";
      }
  }' 2>&1) || true
if grep -q '^best: SEARCH Play USING COVERING INDEX Play_held ' <<<"$plan" \
  && grep -q '^clears: SEARCH PlayLog USING COVERING INDEX PlayLog_clears ' <<<"$plan" && ! grep -q 'TEMP B-TREE' <<<"$plan"; then
  echo "PASS a save's achievements read the player's rows from one index each"
else
  echo "FAIL a save's achievements read more than one index each:"
  echo "$plan" | sed 's/^/  /'
  failed=1
fi
# The home page's newest records come from the index of the record rows alone (PlayLog_records), in its order: never the
# whole log read back from its newest play (2.4 s a page on a million plays that were seldom records).
# shellcheck disable=SC2016  # PHP code: its $variables are PHP's, not the shell's.
plan=$(docker exec "$NAME" php -r '
  require "/opt/opendmtq/portal/ranking_lib.php";
  $r = odq_db()->query("EXPLAIN QUERY PLAN " . recent_records_sql());
  while ($r && ($row = $r->fetchArray(SQLITE3_ASSOC))) {
      echo $row["detail"], "\n";
  }' 2>&1) || true
if grep -q '^SCAN l USING INDEX PlayLog_records$' <<<"$plan"; then
  echo "PASS the home page's newest records come from the index of record rows"
else
  echo "FAIL the home page's newest records read the log otherwise:"
  echo "$plan" | sed 's/^/  /'
  failed=1
fi
# What saves and rankings need of the song list (every chart's line and difficulty, the charts of a line and of a song)
# is kept as one PHP file in the run folder, named after the list file, so that no request decodes the list for it; a
# list put in the first one's place gets its own file and the first one's goes. With a list of its own in a scratch
# folder, each step a new PHP process, as each request is.
# shellcheck disable=SC2016  # PHP code: its $variables are PHP's, not the shell's.
index=$(docker exec "$NAME" sh -c '
  d=$(mktemp -d) && mkdir -p "$d/custom" "$d/run" && export OPENDMTQ_CUSTOM="$d/custom" OPENDMTQ_RUN="$d/run"
  ask="require \"/opt/opendmtq/game/src/rpc.php\"; echo json_encode([odq_patterns(3), odq_patterns(3, 2), odq_patterns(4), array_keys(odq_chart_kinds()), odq_max_song_id()]), \" \";"
  echo "[{\"song_id\":2,\"song_patterns\":[{\"pattern_id\":11,\"line\":3,\"signature\":0},{\"pattern_id\":12,\"line\":4,\"signature\":1}]}]" > "$d/custom/songList.json"
  php -r "$ask"; php -r "$ask"; ls "$d/run/songs" | wc -l | tr -d "\n"; echo -n " "
  echo "[{\"song_id\":2,\"song_patterns\":[{\"pattern_id\":11,\"line\":3,\"signature\":0}]},{\"song_id\":7,\"song_patterns\":[{\"pattern_id\":21,\"line\":3,\"signature\":2}]}]" > "$d/custom/new.json"
  mv "$d/custom/new.json" "$d/custom/songList.json"
  php -r "$ask"; ls "$d/run/songs" | wc -l | tr -d "\n"; rm -rf "$d"' 2>&1) || true
if [ "$index" = '[[11],[11],[12],[11,12],2] [[11],[11],[12],[11,12],2] 1 [[11,21],[11],[],[11,21],7] 1' ]; then
  echo "PASS the song list's index is kept in one file, read again by the next request, and follows a new list"
else
  echo "FAIL the song list's index is not kept, or does not follow a new list: $index"
  failed=1
fi
# A request that read the list before the tools put a new one in its place makes the index from the list it then finds,
# never from the one it read first: an index made from the old list under the new list's name would stay in use until the
# list changed again. The first PHP process reads the list, sees it replaced, then asks; the second is the next request.
# shellcheck disable=SC2016  # PHP code: its $variables are PHP's, not the shell's.
raced=$(docker exec "$NAME" sh -c '
  d=$(mktemp -d) && mkdir -p "$d/custom" "$d/run" && export OPENDMTQ_CUSTOM="$d/custom" OPENDMTQ_RUN="$d/run" LIST_DIR="$d/custom"
  echo "[{\"song_id\":2,\"song_patterns\":[{\"pattern_id\":11,\"line\":3,\"signature\":0},{\"pattern_id\":12,\"line\":4,\"signature\":1}]}]" > "$d/custom/songList.json"
  echo "[{\"song_id\":2,\"song_patterns\":[{\"pattern_id\":11,\"line\":3,\"signature\":0}]},{\"song_id\":7,\"song_patterns\":[{\"pattern_id\":21,\"line\":3,\"signature\":2}]}]" > "$d/new.json"
  php -r "require \"/opt/opendmtq/game/src/rpc.php\"; odq_songs(); rename(getenv(\"LIST_DIR\") . \"/../new.json\", odq_song_list_path()); echo json_encode(array_keys(odq_chart_kinds())), \" \";"
  php -r "require \"/opt/opendmtq/game/src/rpc.php\"; echo json_encode(array_keys(odq_chart_kinds()));"; rm -rf "$d"' 2>&1) || true
if [ "$raced" = '[11,21] [11,21]' ]; then
  echo "PASS a request that read the list before a new one took its place makes the index from the new list"
else
  echo "FAIL a request that read the list before a new one took its place made the index from the old one: $raced"
  failed=1
fi
# A month's board worked out once is kept with the rankings' change number and served again while the number stays; any
# change of the log, the bests or the players raises it (the triggers of setup-db.php, whoever writes), and the next look
# works the board out again. On the server's own database and run folder.
# shellcheck disable=SC2016  # PHP code: its $variables are PHP's, not the shell's.
kept=$(docker exec "$NAME" php -r '
  require "/opt/opendmtq/game/src/rpc.php";
  $db = odq_db();
  $file = odq_run_dir() . "/boards/" . md5("month " . json_encode([odq_month_start(), PHP_INT_MAX, NULL])) . ".kept";
  $first = odq_board(NULL);
  $one = odq_board_kept($file);
  $was = odq_board_stamp($db);
  // A change of a player that changes nothing in it still counts as one: the number goes up.
  $db->exec("UPDATE Member SET nickname = nickname WHERE rowid = (SELECT MIN(rowid) FROM Member)");
  $raised = odq_board_stamp($db) > $was;
  $second = odq_board(NULL);
  $two = odq_board_kept($file);
  echo ($one !== null && $one[0] === $was && $one[1] === $first) ? "kept " : "not-kept ";
  echo $raised ? "raised " : "not-raised ";
  echo ($two !== null && $two[0] > $one[0] && $two[1] === $second) ? "again" : "not-again";' 2>&1) || true
if [ "$kept" = "kept raised again" ]; then
  echo "PASS a month's board is kept until the log, the bests or the players change, then worked out again"
else
  echo "FAIL a month's board is not kept, or not worked out again after a change: $kept"
  failed=1
fi
# The folder of the built apps that a deployment names (the Helm chart: OPENDMTQ_APK_OUT, APK_DIR in charts from before
# 2026-11) wins over the image's own default, or the site would find no app there.
for var in OPENDMTQ_APK_OUT APK_DIR; do
  # shellcheck disable=SC2016  # PHP code: its $variables are PHP's, not the shell's.
  got=$(docker run --rm -e "$var=/srv/apk-all/out" --entrypoint php "opendmtq-server:$TAG" \
    -r 'require "/opt/opendmtq/game/src/config.php"; echo odq_apk_dir();')
  if [ "$got" = /srv/apk-all/out ]; then
    echo "PASS the site finds the apps where $var says"
  else
    echo "FAIL the site looks for the apps in $got, not where $var says"
    failed=1
  fi
done
# The hall of fame's months (portal/lib.php month_name()) are the months the rankings count, which begin at midnight UTC
# (odq_month_start()): last month by its own name in zones west of UTC too, where that midnight is still the evening before,
# as in UTC and east of it. In both of the site's languages; the test stack itself runs in Asia/Seoul, east of UTC.
for lang in en ko; do
  # Last month in UTC by the shell's own calendar, in the site's words for it (C: English month names on any machine).
  format='+%B %Y'
  [ "$lang" = ko ] && format='+%Y년 %-m월'
  want=$(LC_ALL=C date -u -d "$(date -u +%Y-%m-01) -1 month" "$format")
  # Each zone in one PHP run: PHP's own zone set before the name is asked for, as entrypoint.sh sets it from TZ.
  # shellcheck disable=SC2016  # PHP code: its $variables are PHP's, not the shell's.
  got=$(docker run --rm --network none -e "ODQ_LANG=$lang" --entrypoint php "opendmtq-server:$TAG" -r '
    $_COOKIE["opendmtq_lang"] = getenv("ODQ_LANG");
    require "/opt/opendmtq/portal/lib.php";
    foreach (["America/Los_Angeles", "America/New_York", "UTC", "Asia/Seoul", "Pacific/Kiritimati"] as $zone) {
        date_default_timezone_set($zone);
        echo $zone, "=", month_name(odq_month_start(1)), "\n";
    }')
  # Every zone's line must end in the month UTC names; none may name another.
  wrong=$(grep -v "=$want\$" <<<"$got" || true)
  if [ "$(grep -c "=$want\$" <<<"$got")" = 5 ] && [ -z "$wrong" ]; then
    echo "PASS the hall of fame names last month as the rankings count it, in zones west of UTC too ($lang: $want)"
  else
    echo "FAIL the hall of fame names last month otherwise than the rankings count it ($lang, $want wanted):"
    echo "$got" | sed 's/^/  /'
    failed=1
  fi
done
# The installer's end as the site makes it (portal/lib.php) and as the admin pages make it (tools/opendmtq_tools/
# windows_client.py): the same bytes, for an address over plain HTTP, one over HTTPS on port 80 (its port named) with the
# server's own authority and a name in Korean, and one over HTTPS on a port of its own without an authority.
ca=$(printf -- '-----BEGIN CERTIFICATE-----\nMIIBszCCAVmgAwIBAgIUmadeup+/=\n-----END CERTIFICATE-----')
while IFS='|' read -r https host name with_ca; do
  given=""
  [ "$with_ca" = 1 ] && given=$ca
  # shellcheck disable=SC2016  # PHP code: its $variables are PHP's, not the shell's.
  site=$(docker run --rm --network none -e "ODQ_HTTPS=$https" -e "ODQ_HOST=$host" -e "ODQ_NAME=$name" -e "ODQ_CA=$given" \
    --entrypoint php "opendmtq-server:$TAG" -r 'require "/opt/opendmtq/portal/lib.php";
      echo bin2hex(windows_preset_for(site_url_for(getenv("ODQ_HTTPS") === "1", getenv("ODQ_HOST")), getenv("ODQ_NAME"),
                                      (string)getenv("ODQ_CA")));')
  admin=$(ODQ_HTTPS=$https ODQ_HOST=$host ODQ_NAME=$name ODQ_CA=$given PYTHONPATH="$ROOT/tools" python3 -c '
import os
from opendmtq_tools import windows_client as w
e = os.environ
print(w.preset(w.site_url(e["ODQ_HTTPS"] == "1", e["ODQ_HOST"]), e["ODQ_NAME"], e["ODQ_CA"]).hex())')
  if [ -n "$site" ] && [ "$site" = "$admin" ]; then
    echo "PASS the installer's end is the same from the site and from the admin pages ($https $host)"
  else
    echo "FAIL the installer's end differs between the site and the admin pages ($https $host):"
    echo "  site:  $site"
    echo "  admin: $admin"
    failed=1
  fi
done <<'CASES'
0|127.0.0.1:8080|127.0.0.1:8080|0
1|game.example.net|우리 서버|1
1|game.example.net:8790|game.example.net:8790|0
CASES
# Whatever PHP said in the server's log during all of the above: a warning there is a bug, even when the reply was right.
if docker logs "$NAME" 2>&1 | grep -E "PHP (Warning|Notice|Deprecated|Fatal error|Parse error)"; then
  echo "FAIL PHP complained in the server's log (above)"
  failed=1
else
  echo "PASS PHP said nothing in the server's log"
fi
if [ -n "${KEEP:-}" ]; then
  # The data belongs to the container's user: removed from inside the image, as the cleanup does.
  echo "left running: http://127.0.0.1:$PORT/ (data in $DATA); remove with: docker rm -f $NAME;" \
    "docker run --rm -u 0 -v $DATA:/d --entrypoint sh opendmtq-server:$TAG -c 'rm -rf /d/*'; rmdir $DATA"
fi
exit "$failed"
