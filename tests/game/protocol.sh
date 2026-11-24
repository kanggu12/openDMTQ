#!/usr/bin/env bash
# The game server's contract with the game (tests/game/protocol.py) on a throwaway server: builds the server image from
# this working tree, makes the stand-in game files of the pages' tests (tests/ui/make_content.php), starts the server on
# loopback with an empty database, runs the checks, and removes everything again. Needs nothing but Docker and Python 3.
#
# Usage: tests/game/protocol.sh        (PORT, default 18701; KEEP=1 leaves the server up; NO_BUILD=1 uses the image
#                                       already tagged opendmtq-server:TAG)
# Also runs tests/game/lock.php, tests/game/names.php, tests/game/keys.php, tests/game/state.php, tests/game/trust.php,
# tests/game/moved.php and tests/game/signin.php on the same database, and fails on any PHP warning in the server's log.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
# NAME_PREFIX and TAG keep a run's containers, network and images apart from another run's on the same machine.
TAG=${TAG:-protocol}
NAME=${NAME_PREFIX:-odq}-protocol
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

if [ -z "${NO_BUILD:-}" ]; then
  docker build -q -t "opendmtq-server:$TAG" "$ROOT/server" >/dev/null
fi
mkdir -p "$DATA/content" "$DATA/state" "$DATA/custom" "$DATA/apk"
chmod -R a+rwX "$DATA"
docker run --rm -u 33:33 -v "$DATA/content:/content" -v "$ROOT/tests/ui:/ui:ro" --entrypoint php "opendmtq-server:$TAG" /ui/make_content.php /content >/dev/null
# The song list as the tools write it once the owner hides a song (songs.py rebuild()): the stand-in songs, the last one
# kept in the list and marked hidden. A play of its charts is still a play of this server's (protocol.py).
# Its number goes to protocol.py, which then holds the hidden song's checks to it.
HIDDEN_SONG=$(python3 -c 'import json, sys; songs = json.load(open(sys.argv[1], encoding="utf-8")); songs[-1]["hidden_yn"] = "Y"; json.dump(songs, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False); print(songs[-1]["song_id"])' \
  "$DATA/content/songs.json" "$DATA/custom/songList.json")
# The catalog as the tools make it from the client's tables (songs.py's rebuild): made up, for the players' game state
# (tests/game/state.php): characters and a skin everyone has, notes for MAX POINT nobody has at first, a pack of MAX POINT
# for Q and a free one, and song 7's first 4LINE chart costing MAX POINT.
cat > "$DATA/custom/catalog.json" <<'CATALOG'
{"items": [30001, 30002, 100001], "unlock_product": null,
 "point_charts": [{"pattern_id": 61, "song_id": 7, "point_type": 1, "point_value": 350}],
 "products": {"90001": {"item": 90001, "kind": "N", "point": 2000, "cash": 0, "amount": 0},
              "90002": {"item": 90002, "kind": "N", "point": 2000, "cash": 0, "amount": 0},
              "90003": {"item": 90003, "kind": "N", "point": 2000, "cash": 0, "amount": 0},
              "50001": {"item": 50001, "kind": "M", "point": 0, "cash": 10, "amount": 2500},
              "59001": {"item": 59001, "kind": "M", "point": 0, "cash": 0, "amount": 150}},
 "gear": {"C": [[30001, "Made Partner"], [30002, "Second Partner"]], "N": [[90001, "Made Note"], [90002, "Made Note 2"], [90003, "Made Note 3"]],
          "K": [[100001, "Made Skin"]]}}
CATALOG
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
# The keyboard's mark (X-OpenDMTQ-Keys on a save of the PC client's player): what the play's row and the best keep, as the
# best changes hands, and the column a database from before it gets at the next start (tests/game/keys.php), inside the
# running server, on its database and at its own address.
docker exec -i "$NAME" php -- /data/dmtq.db3 http://127.0.0.1:8080 < "$ROOT/tests/game/keys.php" || failed=1
# A player's game state (tests/game/state.php): what the game is told of their currencies, level and items, what a purchase,
# a save and a chart's cost do to them, unlimited currency, and a ban in the game, on the site and in the PC client, inside
# the running server, on its database and at its own address, with the catalog written above.
docker exec -i "$NAME" php -- /data/dmtq.db3 http://127.0.0.1:8080 < "$ROOT/tests/game/state.php" || failed=1
# What a call may change of a player's game state, and whose game may make it (tests/game/trust.php): a ban whatever form the
# id takes, unlimited currency and a pack of MAX POINT, items equipped, inside the running server, with the same catalog.
docker exec -i "$NAME" php -- /data/dmtq.db3 http://127.0.0.1:8080 < "$ROOT/tests/game/trust.php" || failed=1
# A server moved to another address: each start notes the move, and the download page says players need the new app
# (tests/game/moved.php).
docker exec -i "$NAME" php -- /data/dmtq.db3 http://127.0.0.1:8080 < "$ROOT/tests/game/moved.php" || failed=1
# The site's sign-in (tests/game/signin.php): the owner's ID of any length it may have, a banned player's one-time link, an
# account switched off, inside the running server, on its database and state folder. After the other sign-ins: its tries
# count toward the limit on one address's failures.
docker exec -i "$NAME" php -- /data/dmtq.db3 http://127.0.0.1:8080 < "$ROOT/tests/game/signin.php" || failed=1
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
# A player looked up by their player id or their platform account (the sign-in, every call of a player's that asks for a
# ban, getUserAsset) reads the players' indexes (Member_guid, Member_puid; setup-db.php), their first row in order without a
# sort, never every player (20 to 35 microseconds a look at 1,000 players, growing with them). The plans of the statement
# the server runs (odq_member_sql()).
# shellcheck disable=SC2016  # PHP code: its $variables are PHP's, not the shell's.
plan=$(docker exec "$NAME" php -r '
  require "/opt/opendmtq/game/src/db.php";
  foreach (["guid", "puid"] as $column) {
      $r = odq_db()->query("EXPLAIN QUERY PLAN " . odq_member_sql($column));
      while ($r && ($row = $r->fetchArray(SQLITE3_ASSOC))) {
          echo $column, ": ", $row["detail"], "\n";
      }
  }' 2>&1) || true
if grep -qx 'guid: SEARCH Member USING INDEX Member_guid (guid=?)' <<<"$plan" \
  && grep -qx 'puid: SEARCH Member USING INDEX Member_puid (puid=?)' <<<"$plan" && ! grep -q 'TEMP B-TREE\|SCAN' <<<"$plan"; then
  echo "PASS a player is looked up by their player id and by their account from the players' indexes"
else
  echo "FAIL a player's lookup reads more of the players than an index:"
  echo "$plan" | sed 's/^/  /'
  failed=1
fi
# The batch after a sign-in (fourteen calls, nine of them a player's, seven the live view follows) asks for the player's
# ban once and reads their row of the live view once, not once a call: the statements SQLite makes of each table, as an
# authorizer sees each one made, while the server's own code answers the batch on its database, signed as the game signs.
# shellcheck disable=SC2016  # PHP code: its $variables are PHP's, not the shell's.
once=$(docker exec "$NAME" php -r '
  require "/opt/opendmtq/game/src/rpc.php";
  $g = (int)odq_db()->querySingle("SELECT CAST(guid AS INTEGER) FROM Member WHERE udid IS NOT NULL AND code IS NOT NULL
                                     AND CAST(guid AS INTEGER) NOT IN (SELECT guid FROM PlayerBan) ORDER BY rowid LIMIT 1");
  $made = [];
  odq_db()->setAuthorizer(function (int $action, ...$what) use (&$made) {
      if ($action === SQLite3::READ && in_array($what[0] . "." . $what[1], ["PlayerBan.reason", "LiveSwitch.playing"], true)) {
          $made[$what[0]] = ($made[$what[0]] ?? 0) + 1;
      }
      return SQLite3::OK;
  });
  $calls = [["game.getLineTopRankWithLevel", [0, 1, 20, [$g]]], ["game.getAchievementCount", []], ["board.getNoticeList", ["US", 0, 4]],
            ["user.getConnectUuid", [$g, "ANDROID"]], ["memo.getMemoList", [$g, 0, 50]], ["game.getUserAsset", [$g]],
            ["game.getOwnSongList", [$g]], ["shop.getOwnItemList", [$g]], ["game.getOwnAchievementList", [$g]],
            ["game.getOwnQuestList", [$g]], ["game.getOwnPatternScore", [$g]], ["shop.getUnlockedProductList", [$g]],
            ["game.getFirstResourceSongList", []], ["user.getUsersByPuid", [[(string)$g], ["display_name"]]]];
  $body = json_encode(array_map(fn($c, $i) => ["id" => $i, "method" => $c[0], "params" => $c[1]], $calls, array_keys($calls)));
  // Signed as the player'"'"'s own game signs after its sign-in, with the key that sign-in keeps (signin.php).
  odq_sign_in_table(odq_db());
  $w = odq_db()->prepare("INSERT OR REPLACE INTO SignIn (access, puid, at, key, guid) VALUES (:a, :p, :t, :k, :g)");
  foreach ([":a" => "protocol-once", ":p" => (string)$g, ":t" => time(), ":k" => "protocol-once-key", ":g" => $g] as $name => $value) {
      $w->bindValue($name, $value);
  }
  $w->execute();
  $_SERVER["HTTP_FP"] = md5("protocol-once-key" . $body);
  [$status, $out] = odq_rpc($body);
  $errors = array_filter(array_column(json_decode($out, true) ?: [], "error"));
  ksort($made);
  echo $g > 0 ? "" : "no player ", $status, " ", count(json_decode($out, true) ?: []), " errors ", count($errors), " ", json_encode($made);' 2>&1) || true
if [ "$once" = '200 14 errors 0 {"LiveSwitch":1,"PlayerBan":1}' ]; then
  echo "PASS the batch after a sign-in asks for the player's ban once and reads their live view's row once"
else
  echo "FAIL the batch after a sign-in asks the same of a player more than once: $once"
  failed=1
fi
# Phones signing in at the same moment: the game's login of one, with another phone's sign-in written between its look at
# its sign-in and its write of the key (an authorizer of the server's own handle writes through a second handle as the
# login's write is made), gets its key once the other's write is done, where it failed at once ("database is locked").
# shellcheck disable=SC2016  # PHP code: its $variables are PHP's, not the shell's.
crowd=$(docker exec "$NAME" php -r '
  require "/opt/opendmtq/game/src/rpc.php";
  $db = odq_db();
  odq_sign_in_table($db);
  $w = $db->prepare("INSERT OR REPLACE INTO SignIn (access, puid, at) VALUES (:a, :p, :t)");
  $w->bindValue(":a", hash("sha256", "9311|576|ANDROID|KR|crowd|1"));
  $w->bindValue(":p", "9311");
  $w->bindValue(":t", time());
  $w->execute();
  $w->close();
  $other = new SQLite3(odq_db_path());
  $other->busyTimeout(5000);
  $wrote = false;
  $db->setAuthorizer(function (int $action, ...$what) use ($other, &$wrote) {
      if (!$wrote && $action === SQLite3::UPDATE && $what[0] === "SignIn") {
          $wrote = true;
          // Another phone'"'"'s sign-in, committed through its own handle.
          $other->exec("INSERT INTO SignIn (access, puid, at) VALUES (lower(hex(randomblob(16))), 9312, " . time() . ")");
      }
      return SQLite3::OK;
  });
  $key = odq_sign_in_key("9311|576|ANDROID|KR|crowd|1", 9311);
  echo $wrote ? "" : "no write between ", $key === null ? "refused" : (strlen($key) === 32 ? "key" : "odd key");' 2>&1) || true
if [ "$crowd" = "key" ]; then
  echo "PASS a sign-in with another phone's sign-in written meanwhile gets its key"
else
  echo "FAIL a sign-in with another phone's sign-in written meanwhile: $crowd"
  failed=1
fi
# Two game logins with one access token at the same moment: the other login's key written (through a second handle, as a
# second request's write) just as this login writes its own (an authorizer of the server's own handle sees the write being
# made). Both replies then hold the one key the sign-in keeps: the first written stays, and this login hands out that one.
# Two keys handed out left one of the two games refused at its next start, purchase or save.
# shellcheck disable=SC2016  # PHP code: its $variables are PHP's, not the shell's.
crossed=$(docker exec "$NAME" php -r '
  require "/opt/opendmtq/game/src/rpc.php";
  $db = odq_db();
  odq_sign_in_table($db);
  $access = "9313|576|ANDROID|KR|crossed|1";
  $w = $db->prepare("INSERT OR REPLACE INTO SignIn (access, puid, at) VALUES (:a, :p, :t)");
  $w->bindValue(":a", hash("sha256", $access));
  $w->bindValue(":p", "9313");
  $w->bindValue(":t", time());
  $w->execute();
  $w->close();
  $other = new SQLite3(odq_db_path());
  $other->busyTimeout(5000);
  $wrote = false;
  $db->setAuthorizer(function (int $action, ...$what) use ($other, $access, &$wrote) {
      if (!$wrote && $action === SQLite3::UPDATE && $what[0] === "SignIn") {
          $wrote = true;
          // The other login of the same token, its key written and committed first.
          $other->exec("UPDATE SignIn SET key = \x27the-other-login-key\x27, guid = 9313 WHERE access = \x27" . hash("sha256", $access) . "\x27");
      }
      return SQLite3::OK;
  });
  $key = odq_sign_in_key($access, 9313);
  $db->setAuthorizer(null);
  $kept = $db->querySingle("SELECT key FROM SignIn WHERE access = \x27" . hash("sha256", $access) . "\x27");
  echo $wrote ? "" : "no crossing ", $key === $kept && $key === "the-other-login-key" ? "one key" : "two keys: this login handed out " . var_export($key, true) . ", the sign-in keeps " . var_export($kept, true);' 2>&1) || true
if [ "$crossed" = "one key" ]; then
  echo "PASS two game logins with one token at the same moment hand out the one key the sign-in keeps"
else
  echo "FAIL two game logins with one token at the same moment: $crossed"
  failed=1
fi
# A page of the site opens the database once and works out the signed-in player's figures once, whoever asks: the header
# (the name and place at the top of every page) and MY PAGE (its profile, its account, its places) asked three times each.
# The reads SQLite makes of the best scores' table, as an authorizer sees each statement made, on the server's database.
# shellcheck disable=SC2016  # PHP code: its $variables are PHP's, not the shell's.
figures=$(docker exec "$NAME" php -r '
  require "/opt/opendmtq/portal/lib.php";
  $db = db();
  $g = (int)$db->querySingle("SELECT user_id FROM Play ORDER BY rowid LIMIT 1");
  // Everyone'"'"'s totals, kept in the run folder (the rank compares with them): worked out before the count.
  play_totals($db);
  $made = 0;
  $db->setAuthorizer(function (int $action, ...$what) use (&$made) {
      if ($action === SQLite3::READ && $what[0] === "Play" && $what[1] === "score") {
          $made++;
      }
      return SQLite3::OK;
  });
  $seen = [];
  foreach ([1, 2, 3] as $_) {
      $seen[] = player_figures(db(), $g);
  }
  echo $g > 0 ? "" : "no player ", db() === $db ? "one handle" : "handles", " ", $seen[0] !== null && $seen[0] === $seen[2] ? "same" : "differ", " ", $made;' 2>&1) || true
if [ "$figures" = "one handle same 1" ]; then
  echo "PASS a page opens the database once and works out the signed-in player's figures once"
else
  echo "FAIL a page opens the database again or works out a player's figures again: $figures"
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
# The site's keyboard counts beside a total and a month's score (setup-db.php's indexes): the bests a keyboard play set from
# the index of those bests alone (Play_keys); a month first from one look at the index of the keyboard's plays (PlayLog_keys),
# then, only when there are some, from the plays of that month of the players asked for (the board's, or the first three of a
# month before) through the board's own index (PlayLog_board), never the whole log.
# shellcheck disable=SC2016  # PHP code: its $variables are PHP's, not the shell's.
plan=$(docker exec "$NAME" php -r '
  require "/opt/opendmtq/portal/ranking_lib.php";
  foreach (["bests" => KEYS_BESTS, "any" => KEYS_IN_MONTH, "month" => MONTH_KEYS] as $what => $sql) {
      $r = odq_db()->query("EXPLAIN QUERY PLAN " . $sql);
      while ($r && ($row = $r->fetchArray(SQLITE3_ASSOC))) {
          echo $what, ": ", $row["detail"], "\n";
      }
  }' 2>&1) || true
if grep -qx 'bests: SCAN p USING COVERING INDEX Play_keys' <<<"$plan" \
  && grep -qx 'any: SEARCH l USING COVERING INDEX PlayLog_keys (played_at>? AND played_at<?)' <<<"$plan" \
  && grep -qx 'month: SEARCH l USING INDEX PlayLog_board (user_id=? AND played_at>? AND played_at<?)' <<<"$plan" \
  && ! grep -q 'SCAN l\b' <<<"$plan"; then
  echo "PASS the site's keyboard counts read the keyboard's bests from their own index, and a month's from the asked players' plays of that month alone"
else
  echo "FAIL the site's keyboard counts read more than they need:"
  echo "$plan" | sed 's/^/  /'
  failed=1
fi
# A month nobody played with the keyboard costs that one look: the site's own count (month_keys(), on the site's read-only
# handle) reads the mark and the time of the play log, and the statement that reads its scores is not even made. An
# authorizer sees every column each statement reads as SQLite makes it.
# shellcheck disable=SC2016  # PHP code: its $variables are PHP's, not the shell's.
looked=$(docker exec "$NAME" php -r '
  require "/opt/opendmtq/portal/lib.php";
  $db = new SQLite3(DB, SQLITE3_OPEN_READONLY);
  $read = [];
  $db->setAuthorizer(function (int $action, ...$what) use (&$read) {
      if ($action === SQLite3::READ) {
          $read[$what[0] . "." . $what[1]] = true;
      }
      return SQLite3::OK;
  });
  $counts = month_keys($db, gmmktime(0, 0, 0, 1, 1, 2001), gmmktime(0, 0, 0, 2, 1, 2001), [1, 2]);
  ksort($read);
  echo json_encode($counts), " ", implode(" ", array_keys($read));' 2>&1) || true
if [ "$looked" = "[] BoardStamp.n PlayLog.keys PlayLog.played_at" ]; then
  echo "PASS a month nobody played with the keyboard costs one look at the keyboard's plays, none of its scores read"
else
  echo "FAIL a month nobody played with the keyboard reads more than one look: $looked"
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
# The song a phone downloads first (game.getFirstResourceSongList, in the batch after every sign-in) comes from the song
# list's index too, never from decoding the list: the lowest id on offer, a hidden one left out; and with the list's bytes
# made blanks behind the index (the same file, size and time, so the same index), the next request still names it.
# shellcheck disable=SC2016  # PHP code: its $variables are PHP's, not the shell's.
first=$(docker exec "$NAME" sh -c '
  d=$(mktemp -d) && mkdir -p "$d/custom" "$d/run" && export OPENDMTQ_CUSTOM="$d/custom" OPENDMTQ_RUN="$d/run"
  ask="require \"/opt/opendmtq/game/src/rpc.php\"; echo json_encode(odq_game_first_resource_songs([]));"
  echo "[{\"song_id\":9,\"name\":\"nine\",\"song_patterns\":[]},{\"song_id\":3,\"name\":\"three\",\"song_patterns\":[]},{\"song_id\":1,\"name\":\"one\",\"hidden_yn\":\"Y\",\"song_patterns\":[]}]" > "$d/custom/songList.json"
  php -r "$ask"; echo -n " "
  php -r "\$f = getenv(\"OPENDMTQ_CUSTOM\") . \"/songList.json\"; \$t = filemtime(\$f); \$h = fopen(\$f, \"r+\"); fwrite(\$h, str_repeat(\" \", filesize(\$f))); fclose(\$h); touch(\$f, \$t);"
  php -r "$ask"; rm -rf "$d"' 2>&1) || true
if [ "$first" = '{"first_resource_songs":[{"song_id":3,"name":"three"}]} {"first_resource_songs":[{"song_id":3,"name":"three"}]}' ]; then
  echo "PASS the first song a phone downloads comes from the song list's index, without decoding the list"
else
  echo "FAIL the first song a phone downloads is not the index's: $first"
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
