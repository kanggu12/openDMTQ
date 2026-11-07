<?php
/*
 * A stand-in for the game files an operator imports (data/content), for testing the pages on a machine without them
 * (CI has none, and they cannot go in this repository). It holds no game code or data: made-up songs, plain coloured
 * jackets, and a client data folder with an empty manifest, which is all the server checks for.
 *
 * Usage (inside the server image): php make_content.php <empty folder>
 */

// Where to write.
$tree = rtrim($argv[1] ?? '', '/');
if ($tree === '' || !is_dir($tree)) {
    fwrite(STDERR, "usage: php make_content.php <empty folder>\n");
    exit(2);
}

// The client data folder: a manifest that lists nothing, in the game's container for a file kept as it is (type 2, the
// length as a varint, the bytes). Phones would get no file from it; the pages only need to see client data there.
$manifest = "file_name,file_size,checksum,compressed_file_size,compressed_checksum,acquire_on_demand,compressed,platform,tag,\r\n";
$varint = function (int $n): string {
    $out = '';
    do {
        $b = $n & 0x7F;
        $n >>= 7;
        $out .= chr($b | ($n ? 0x80 : 0));
    } while ($n);
    return $out;
};
@mkdir("$tree/web/patch/phone_new/1.003.005/android", 0755, true);
file_put_contents("$tree/web/patch/phone_new/1.003.005/android/patch_new.csv.lz4", chr(2) . $varint(strlen($manifest)) . $manifest);
// The songs' folders, as an import leaves them.
foreach (['web/DMQ/Songs', 'web/DMQ/Patterns', 'web/viewImg/eye', 'web/viewImg/news'] as $folder) {
    @mkdir("$tree/$folder", 0755, true);
}

/* A 160x120 PNG of one colour with a lighter band across it, written by hand: the server image has no image library. */
function jacket(int $r, int $g, int $b): string
{
    $rows = '';
    for ($y = 0; $y < 120; $y++) {
        // Each row starts with its filter byte (none).
        $pixel = $y >= 40 && $y < 80 ? chr(min(255, $r + 70)) . chr(min(255, $g + 40)) . chr(min(255, $b + 70)) : chr($r) . chr($g) . chr($b);
        $rows .= "\0" . str_repeat($pixel, 160);
    }
    // A chunk: its length, its name and data, and their checksum.
    $chunk = fn(string $name, string $data) => pack('N', strlen($data)) . $name . $data . pack('N', crc32($name . $data));
    return "\x89PNG\r\n\x1a\n" . $chunk('IHDR', pack('NNCCCCC', 160, 120, 8, 2, 0, 0, 0)) . $chunk('IDAT', gzcompress($rows)) . $chunk('IEND', '');
}

// Made-up songs. One name of the longest kind and some Korean, for what the pages must cope with; every chart level.
$titles = ['First Light', 'Paper Planes', 'Neon Rain', 'Glass Garden', 'Midnight Relay', 'Static Bloom', 'Harbor Lights', 'Second Wind',
    'Cold Coffee', 'Violet Hour', 'Long Way Home', 'Tin Soldier', '새벽의 정원', '별이 지는 곳', '바람의 노래', 'Red Line', 'Blue Hour', 'Gold Rush',
    'Silver Thread', 'Iron Lung', 'Grace Note', 'Wild Card', 'Slow Burn', 'Last Train',
    'An Extremely Long Song Title That Has To Wrap Over Several Lines In Every List It Appears In (Extended Orchestral Remix) feat. Everyone Who Was There',
    '어느 긴 겨울밤에 멀리서 들려오는 아주 오래된 노래의 처음부터 끝까지 이어지는 끝나지 않는 이야기'];
$list = [];
$pattern = 0;
foreach ($titles as $i => $title) {
    $id = $i + 1;
    $charts = [];
    // The game counts a chart's lines with one more than its name says: 3 is 2LINE.
    foreach ([3, 4, 5] as $line) {
        foreach ([1, 4, 7] as $level => $difficulty) {
            $charts[] = ['difficulty' => $difficulty + $i % 3, 'line' => $line, 'pattern_id' => ++$pattern, 'signature' => $level + 1];
        }
    }
    // Easy, on the first few songs only, as in the game; numbered apart so that the other charts keep their numbers.
    if ($i < 3) {
        $charts[] = ['difficulty' => 1, 'line' => 3, 'pattern_id' => 1000 + $id, 'signature' => 0];
    }
    $list[] = ['cost_game_point' => 0, 'status' => '', 'song_id' => $id, 'feat_by' => '', 'cost_game_cash' => 0, 'name' => "fixture$id", 'loop_bga_yn' => 'N',
        'visualized_by' => 'Fixture Visuals', 'free_yn' => 'Y', 'composed_by' => 'Fixture Composer', 'singer' => '', 'artist_name' => $i === 24 ? 'The Extremely Long Named Artist Collection and Friends of the Orchestra' : 'Fixture Artist ' . ($i % 7 + 1),
        'hidden_yn' => 'N', 'flag' => 0, 'arranged_by' => '', 'full_name' => $title, 'original_bga_yn' => 'Y', 'genre' => ['Trance', 'Rock', 'Pop', 'House'][$i % 4], 'song_patterns' => $charts];
    // A plain jacket, in its own colour; all but the last, for a song whose picture is missing.
    if ($i < count($titles) - 1) {
        file_put_contents("$tree/web/viewImg/eye/fixture$id.png", jacket(40 + $i * 8, 200 - $i * 6, 90 + $i * 5));
    }
}
file_put_contents("$tree/songs.json", json_encode($list, JSON_UNESCAPED_UNICODE));
echo 'make_content: ' . count($list) . " songs\n";
