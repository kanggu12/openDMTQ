"""The launcher's words, in English and Korean.

The launcher speaks the language Windows is shown in (Korean, else English; state.system_language) until the player
picks one on the guide's first page, under Launcher or with --language. The installer follows the same rule: the
launcher's choice when there is one, else Windows'. Each entry is (English, Korean). Placeholders use str.format names.
"""

from opendmtq_client import errors, safety
from opendmtq_client.errors import Worded

TEXT = {
    # ---------------------------------------------------------------------------------------------- frame
    "bottom.play": ("PLAY", "PLAY"),
    "bottom.playing": ("PLAYING", "PLAYING"),
    "status.ready": ("Ready to play.", "플레이할 준비가 됐습니다."),
    "status.server_down": ("The server does not answer. PLAY starts the app on this PC.",
                           "서버가 응답하지 않습니다. PLAY를 누르면 이 PC의 앱으로 시작합니다."),
    "status.no_server": ("Connect to a server on the ONLINE page.", "ONLINE 페이지에서 서버에 연결하세요."),
    "status.signin_ended": ("Your sign-in ended. PLAY starts the app on this PC.",
                            "로그인이 만료되었습니다. PLAY를 누르면 이 PC의 앱으로 시작합니다."),
    "status.not_signed": ("Not signed in yet. PLAY starts the app on this PC.",
                          "아직 로그인하지 않았습니다. PLAY를 누르면 이 PC의 앱으로 시작합니다."),
    "status.fix_first": ("Something needs fixing first: see the ready check.", "먼저 고칠 것이 있습니다. 준비 점검을 보세요."),
    "status.app_check": ("Asking the server for its app...", "서버의 앱을 확인하는 중..."),
    "status.downloading": ("Downloading the app: {done} of {total} MB", "앱을 다운로드하는 중: {total} MB 중 {done} MB"),
    "status.app_ready": ("The app is downloaded.", "앱을 다운로드했습니다."),
    "status.newest": ("This is the server's newest app.", "서버의 최신 앱입니다."),
    "status.download_cancelled": ("The download stopped. Nothing half done was kept.", "다운로드를 멈췄습니다. 다운로드하던 파일은 남기지 않았습니다."),
    "status.stopping": ("Stopping the download...", "다운로드를 멈추는 중..."),
    "status.starting": ("Starting the game...", "게임을 시작하는 중..."),
    "status.offline": ("The server did not answer: the game starts with the app on this PC.",
                       "서버가 응답하지 않아 이 PC의 앱으로 시작합니다."),
    "status.playing": ("The game is open. The launcher waits until it closes.", "게임이 열려 있습니다. 닫힐 때까지 런처가 기다립니다."),
    "status.ended": ("The game closed after {time}.", "{time} 동안 플레이하고 게임이 닫혔습니다."),
    "status.crashed": ("The game closed by itself.", "게임이 예기치 않게 종료되었습니다."),
    "status.failed_start": ("The game could not start.", "게임을 시작하지 못했습니다."),
    "status.open_log": ("Open the game log", "게임 로그 열기"),
    "status.saved": ("Saved. It applies at the next PLAY.", "저장했습니다. 다음 PLAY부터 적용됩니다."),
    "status.preset.later": ("The installer added a server: {name}. Choose it on the ONLINE page.",
                            "설치 파일이 서버를 추가했습니다: {name}. ONLINE 페이지에서 고를 수 있습니다."),
    "status.preset": ("The installer added a server: {name}. You play on it from now on.",
                      "설치 파일이 서버를 추가했습니다: {name}. 이제 이 서버에서 플레이합니다."),
    "status.preset.switched": ("Switched to the installer's server: {name}. You play on it from now on.",
                               "설치 파일의 서버로 바꿨습니다: {name}. 이제 이 서버에서 플레이합니다."),
    "status.updated": ("Updated to {v}.", "{v} 버전으로 업데이트했습니다."),
    "status.not_updated": ("The update to {v} was not installed. This is still {now}. Try again on the LAUNCHER page.",
                           "{v} 버전으로 업데이트하지 못했습니다. 지금 버전은 {now}입니다. LAUNCHER 페이지에서 다시 해 보세요."),
    "status.error": ("{error}", "{error}"),
    "status.mypage": ("Opening your page on the site...", "사이트의 내 페이지를 여는 중..."),
    "status.mypage.opened": ("Your page on the site is open in the browser.", "브라우저에서 사이트의 내 페이지를 열었습니다."),
    "status.site.opened": ("The server's site is open in the browser.", "브라우저에서 서버의 사이트를 열었습니다."),
    # PLAY linked the site account to this PC's game player (actions.link_player), said once; after the line of how the
    # game ended when the game's end made the link.
    "status.linked": ("This PC's player is now linked to your site account {account}.",
                      "이 PC의 플레이어를 사이트 계정 {account}에 연결했습니다."),
    "status.and": ("{first} {then}", "{first} {then}"),
    "status.signed_out": ("Your sign-in ended (it ran out, or the password changed). Sign in again on the ONLINE page.",
                          "로그인이 만료되었습니다(기간이 지났거나 비밀번호가 바뀌었습니다). ONLINE 페이지에서 다시 로그인하세요."),

    # ---------------------------------------------------------------------------------- connection test
    # Its steps' names (connection.STEPS), what each found, the verdict over them, and the card's buttons.
    "test.title": ("Connection test", "연결 테스트"),
    "test.button": ("Test connection", "연결 테스트"),
    "test.again": ("Test again", "다시 테스트"),
    "test.copy": ("Copy", "복사"),
    "test.copied": ("Copied the connection test's result.", "연결 테스트 결과를 복사했습니다."),
    "test.use": ("Use this address", "이 주소 쓰기"),
    "test.used": ("Playing on {name} from now on.", "이제 {name}에서 플레이합니다."),
    "test.address": ("Address", "주소"),
    "test.lookup": ("Name lookup", "이름 조회"),
    "test.port": ("Port", "포트"),
    "test.server": ("OpenDMTQ server", "OpenDMTQ 서버"),
    "test.version": ("Version", "버전"),
    "test.signin": ("Sign-in", "로그인"),
    "test.game": ("Game server", "게임 서버"),
    "test.broadcasts": ("Broadcasts", "방송"),
    "test.downloads": ("Downloads", "다운로드"),
    "test.round_trip": ("Round trip", "응답 시간"),
    "test.waiting": ("...", "..."),
    "test.skip": ("Not tried.", "확인하지 않았습니다."),
    "test.address.ok": ("{url}: {scheme}, host {host}, port {port}.", "{url}: {scheme}, 호스트 {host}, 포트 {port}."),
    "test.address.bad": ("{error}", "{error}"),
    "test.lookup.literal": ("{host} is an address: nothing to look up.", "{host}: 주소라서 찾아볼 이름이 없습니다."),
    "test.lookup.ok": ("{host} is at {addresses}.", "{host}의 주소: {addresses}"),
    "test.lookup.bad": ("{host} leads to no address ({why}).", "{host}에 해당하는 주소가 없습니다({why})."),
    "test.port.ok": ("Port {port} of {host} takes the connection.", "{host}의 {port} 포트가 연결을 받습니다."),
    "test.port.refused_none": ("{host} refuses the connection on port {port}, and no OpenDMTQ server answers on ports {first} to {last} either.",
                               "{host}의 {port} 포트가 연결을 거부하고, {first}~{last} 포트에서도 OpenDMTQ 서버가 응답하지 않습니다."),
    "test.port.timeout_none": ("No answer from port {port} of {host} in {seconds} s, and no OpenDMTQ server answers on ports {first} to {last} either.",
                               "{host}의 {port} 포트가 {seconds}초 안에 응답하지 않고, {first}~{last} 포트에서도 OpenDMTQ 서버가 응답하지 않습니다."),
    "test.port.refused_moved": ("{host} refuses the connection on port {port}. An OpenDMTQ server answers at {url}.",
                                "{host}의 {port} 포트가 연결을 거부합니다. {url}에서 OpenDMTQ 서버가 응답합니다."),
    "test.port.timeout_moved": ("No answer from port {port} of {host} in {seconds} s. An OpenDMTQ server answers at {url}.",
                                "{host}의 {port} 포트가 {seconds}초 안에 응답하지 않습니다. {url}에서 OpenDMTQ 서버가 응답합니다."),
    "test.port.unreachable_none": ("{host} cannot be reached from this PC on port {port} ({why}), and no OpenDMTQ server "
                                   "answers on ports {first} to {last} either.",
                                   "이 PC에서 {host}의 {port} 포트에 연결할 수 없습니다({why}). {first}~{last} 포트에서도 "
                                   "OpenDMTQ 서버가 응답하지 않습니다."),
    "test.port.unreachable_moved": ("{host} cannot be reached from this PC on port {port} ({why}). An OpenDMTQ server "
                                    "answers at {url}.",
                                    "이 PC에서 {host}의 {port} 포트에 연결할 수 없습니다({why}). {url}에서 OpenDMTQ 서버가 "
                                    "응답합니다."),
    "test.server.ok": ("{name}, OpenDMTQ {version}.", "{name}, OpenDMTQ {version}."),
    "test.server.ok_https_windows": ("{name}, OpenDMTQ {version}, over HTTPS with a certificate Windows trusts.",
                                     "{name}, OpenDMTQ {version}. HTTPS 인증서는 Windows가 신뢰하는 인증서입니다."),
    "test.server.ok_https_own": ("{name}, OpenDMTQ {version}, over HTTPS with the server's own certificate, trusted for this server alone.",
                                 "{name}, OpenDMTQ {version}. HTTPS 인증서는 이 서버에만 신뢰하는 서버 자체 인증서입니다."),
    "test.server.certificate": ("This PC does not trust the certificate the server answers HTTPS with: {why}.",
                                "서버가 HTTPS에 쓰는 인증서를 이 PC가 신뢰하지 않습니다: {why}."),
    "test.server.certificate_moved": ("This PC does not trust the certificate the server answers HTTPS with: {why}. An "
                                      "OpenDMTQ server answers at {url}.",
                                      "서버가 HTTPS에 쓰는 인증서를 이 PC가 신뢰하지 않습니다: {why}. {url}에서 OpenDMTQ "
                                      "서버가 응답합니다."),
    "test.server.too_old": ("An OpenDMTQ server older than 0.8 answers: it does not support the PC client.",
                            "PC 클라이언트를 지원하지 않는 0.8 이전 버전의 OpenDMTQ가 응답합니다."),
    "test.server.not_opendmtq": ("Something answers on the port, but it is not an OpenDMTQ server for PCs.",
                                 "포트에서 응답은 오지만 PC용 OpenDMTQ 서버가 아닙니다."),
    "test.server.not_opendmtq_moved": ("Something answers on the port, but it is not an OpenDMTQ server for PCs. An OpenDMTQ "
                                       "server answers at {url}.",
                                       "포트에서 응답은 오지만 PC용 OpenDMTQ 서버가 아닙니다. {url}에서 OpenDMTQ 서버가 "
                                       "응답합니다."),
    "test.server.error": ("{error}", "{error}"),
    "test.version.same": ("{version}, as this launcher.", "이 런처와 같은 {version} 버전입니다."),
    "test.version.older": ("The server runs {server}, older than this launcher's {launcher}.",
                           "서버는 {server} 버전으로, 이 런처의 {launcher} 버전보다 오래되었습니다."),
    "test.version.newer": ("The server runs {server}, newer than this launcher's {launcher}.",
                           "서버는 {server} 버전으로, 이 런처의 {launcher} 버전보다 새 버전입니다."),
    "test.version.unknown": ("The server does not say its version; this launcher is {launcher}.",
                             "서버가 버전을 알려 주지 않습니다. 이 런처는 {launcher} 버전입니다."),
    "test.signin.ok": ("Signed in as {account} until {until}.", "{until}까지 {account} 계정으로 로그인되어 있습니다."),
    "test.signin.ok_app": ("Signed in as {account}. Of its app the server says: {error}",
                           "{account} 계정으로 로그인되어 있습니다. 앱에 대한 서버의 응답: {error}"),
    "test.signin.app_building": ("Signed in as {account}. The server is building its app (about 20 seconds).",
                                 "{account} 계정으로 로그인되어 있습니다. 서버가 앱을 만드는 중입니다(약 20초)."),
    "test.signin.app_rebuilding": ("Signed in as {account}. The server's address changed, and it is building its app again.",
                                   "{account} 계정으로 로그인되어 있습니다. 서버 주소가 바뀌어 서버가 앱을 다시 만드는 중입니다."),
    "test.signin.app_failed": ("Signed in as {account}. The server could not build its app.",
                               "{account} 계정으로 로그인되어 있습니다. 서버가 앱을 만들지 못했습니다."),
    "test.signin.app_named": ("Signed in as {account}. The server offers an app without a proper name.",
                              "{account} 계정으로 로그인되어 있습니다. 서버가 이름이 올바르지 않은 앱을 내놓았습니다."),
    "test.signin.none": ("Not signed in to this server on this PC.", "이 PC에서 이 서버에 로그인하지 않았습니다."),
    "test.signin.ended": ("The server no longer takes the sign-in of {account}.", "서버가 {account} 계정의 로그인을 더 이상 받지 않습니다."),
    "test.game.ok": ("The game server answers: patch {patch}.", "게임 서버가 응답합니다(패치 {patch})."),
    "test.game.maintenance": ("The game server answers, under maintenance: patch {patch}.",
                              "게임 서버가 응답하지만 점검 중입니다(패치 {patch})."),
    "test.game.down": ("The game server answers that it cannot serve the game: {problem}.",
                       "게임 서버가 게임을 제공할 수 없다고 응답합니다: {problem}."),
    "test.game.no_data": ("The game server answers without its client data: the game cannot start.",
                          "게임 서버에 클라이언트 데이터가 없어 게임을 시작할 수 없습니다."),
    "test.game.no_database": ("The game server answers without its database.", "게임 서버에 데이터베이스가 없습니다."),
    "test.game.read_only": ("The game server cannot write its database: plays are not kept.",
                            "게임 서버가 데이터베이스에 쓸 수 없어 플레이 기록이 남지 않습니다."),
    "test.game.no_host": ("The game server answers with no address of its own set.", "게임 서버에 서버 주소가 정해져 있지 않습니다."),
    "test.game.no_answer": ("No answer from the game server's health page: {error}.", "게임 서버의 상태 페이지가 응답하지 않습니다: {error}."),
    "test.broadcasts.on": ("Broadcasts are on for the server.", "서버의 방송이 켜져 있습니다."),
    "test.broadcasts.off": ("Broadcasts are off for the server.", "서버의 방송이 꺼져 있습니다."),
    "test.broadcasts.no_answer": ("No answer from the broadcast state: {error}.", "방송 상태 요청에 응답이 없습니다: {error}."),
    "test.downloads.ok": ("The app ({app} MB) and the client data's list ({listing} KB) are there to download.",
                          "앱({app} MB)과 클라이언트 데이터 목록({listing} KB)을 다운로드할 수 있습니다."),
    "test.downloads.ok_no_app": ("The client data's list ({listing} KB) is there to download; the app downloads after a sign-in.",
                                 "클라이언트 데이터 목록({listing} KB)을 다운로드할 수 있습니다. 앱은 로그인한 뒤 다운로드됩니다."),
    "test.downloads.bad_listing": ("The client data's list does not download: {error}.", "클라이언트 데이터 목록을 다운로드할 수 없습니다: {error}."),
    "test.downloads.bad_app": ("The app does not download: {error}.", "앱을 다운로드할 수 없습니다: {error}."),
    "test.round_trip.all": ("All {of} requests answered: median {median} ms ({fast} to {slow} ms).",
                            "{of}번 모두 응답: 중앙값 {median} ms, {fast}~{slow} ms."),
    "test.round_trip.all_same": ("All {of} requests answered: {median} ms each.", "{of}번 모두 응답: 각 {median} ms."),
    "test.round_trip.ok": ("{n} of {of} requests answered: median {median} ms ({fast} to {slow} ms).",
                           "{of}번 중 {n}번 응답: 중앙값 {median} ms, {fast}~{slow} ms."),
    "test.round_trip.ok_same": ("{n} of {of} requests answered: {median} ms each.", "{of}번 중 {n}번 응답: 각 {median} ms."),
    "test.round_trip.bad": ("None of the {of} timed requests was answered.", "응답 시간 측정 요청 {of}번에 모두 응답이 없었습니다."),
    "test.verdict.ok": ("The server answers, and so does everything the game uses.",
                        "서버와 게임이 쓰는 기능이 모두 응답합니다."),
    "test.verdict.running": ("Testing the connection...", "연결을 테스트하는 중..."),
    "test.verdict.moved": ("Nothing answers at {url}. An OpenDMTQ server answers at {found}.",
                           "{url}에서는 응답이 없고, {found}에서 OpenDMTQ 서버가 응답합니다."),
    "test.verdict.moved_other": ("Another server answers at {url}. An OpenDMTQ server answers at {found}.",
                                 "{url}에서는 다른 서버가 응답하고, {found}에서 OpenDMTQ 서버가 응답합니다."),
    "test.verdict.bad": ("{found}", "{found}"),
    "test.verdict.warn": ("The server answers. {step}: {found}", "서버가 응답합니다. {step}: {found}"),
    "test.verdict.version.older": ("The server answers; it runs {server}, older than this launcher's {launcher}.",
                                   "서버가 응답합니다. 이 런처({launcher})보다 오래된 {server} 버전입니다."),
    "test.verdict.version.newer": ("The server answers; it runs {server}, newer than this launcher's {launcher}.",
                                   "서버가 응답합니다. 이 런처({launcher})보다 새로운 {server} 버전입니다."),
    "test.verdict.version.unknown": ("The server answers without saying its version; this launcher is {launcher}.",
                                     "서버가 응답하지만 버전을 알려 주지 않습니다. 이 런처는 {launcher} 버전입니다."),
    "test.verdict.signin.none": ("The server answers; this PC is not signed in to it.",
                                 "서버가 응답합니다. 이 PC에서 이 서버에 로그인하지 않았습니다."),
    "test.verdict.game.maintenance": ("The server answers; its game server is under maintenance (patch {patch}).",
                                      "서버가 응답하지만 게임 서버가 점검 중입니다(패치 {patch})."),
    "test.text.title": ("Connection test of {url}, {at}", "{url} 연결 테스트, {at}"),
    "check.server.test": ("Test connection", "연결 테스트"),

    # ------------------------------------------------------------------------------------------- common
    "common.cancel": ("Cancel", "취소"),
    "common.ok": ("OK", "확인"),
    "common.open": ("Open", "열기"),
    "common.minutes": ("{m} min", "{m}분"),
    "common.seconds": ("{s} s", "{s}초"),

    # --------------------------------------------------------------------------------------------- play
    "play.no_server": ("No server yet. Connect to the OpenDMTQ server you play on.",
                       "아직 서버가 없습니다. 플레이할 OpenDMTQ 서버에 연결하세요."),
    "play.server": ("Server", "서버"),
    "play.connect": ("Connect", "연결"),
    "play.signed": ("Signed in as {account}.", "로그인: {account}"),
    "play.not_signed": ("{account}: your sign-in ended. Sign in again to get the server's updates.",
                        "{account}: 로그인이 만료되었습니다. 서버의 업데이트를 다운로드하려면 다시 로그인하세요."),
    "play.no_account": ("Not signed in yet.", "아직 로그인하지 않았습니다."),
    "play.server_down": ("The server does not answer.", "서버가 응답하지 않습니다."),
    "play.ready": ("Ready check", "준비 점검"),
    "play.will_get": ("PLAY downloads it", "PLAY를 누르면 다운로드"),
    "play.mypage": ("My page on the site", "사이트의 내 페이지"),
    "play.records": ("My records", "내 기록"),
    "play.records.recent": ("Recent plays", "최근 플레이"),
    "play.records.best": ("Best records", "최고 기록"),
    "play.records.none": ("No plays recorded yet.", "아직 플레이 기록이 없습니다."),
    "play.records.unlinked": ("{account} is not linked to a player on this server.",
                              "이 서버에는 {account} 계정과 연결된 플레이어가 없습니다."),
    "play.records.place": ("#{n} of {all}", "{all}명 중 {n}위"),
    "play.records.new": ("New record", "새 기록"),
    "play.records.grade": ("Grade {grade}", "{grade} 등급"),
    "play.records.keys": ("Keyboard play", "키보드 플레이"),
    "play.records.chart": ("Chart {id}", "{id}번 차트"),
    # How long ago a play was, as the site says it (server/portal/strings.php ago.*).
    "ago.now": ("just now", "방금"),
    "ago.min": ("{n} min ago", "{n}분 전"),
    "ago.h": ("{n} h ago", "{n}시간 전"),
    "ago.d": ("{n} d ago", "{n}일 전"),
    "ago.mo": ("{n} mo ago", "{n}개월 전"),
    "play.last": ("Last game", "지난 플레이"),
    "play.last.none": ("No game on this PC yet.", "이 PC에서 아직 플레이하지 않았습니다."),
    "play.last.unit.min": ("min", "분"),
    "play.last.unit.s": ("s", "초"),
    "play.last.end.ok": ("Closed normally.", "정상적으로 닫았습니다."),
    "play.last.end.crash": ("The game closed by itself.", "게임이 예기치 않게 종료되었습니다."),
    "play.last.failed": ("The game could not start. Its log says why.", "게임을 시작하지 못했습니다. 로그에 이유가 있습니다."),

    # ----------------------------------------------------------------------------------- ready-check lines
    "check.player": ("Game program for Windows", "Windows용 게임 프로그램"),
    "check.server": ("Server", "서버"),
    "check.account": ("Sign-in", "로그인"),
    "check.app": ("The server's app", "서버의 앱"),
    "check.app_update": ("A newer app on the server", "서버에 새 앱이 있음"),
    "check.player.missing": ("not found: run the installer again", "없음. 설치 프로그램을 다시 실행하세요"),
    # What a row that is not fine says of its state, before the way to fix it (Repair, the connection test, ONLINE).
    "check.player.none": ("not found", "없음"),
    "check.player.repair": ("Repair", "복구"),
    "check.server.down": ("not answering", "응답 없음"),
    "check.server.none": ("none yet", "아직 없음"),
    "check.account.none": ("not signed in", "로그인하지 않음"),
    "check.account.ended": ("sign-in ended", "로그인 만료"),
    "check.app.none": ("not on this PC", "이 PC에 없음"),
    "check.running": ("The game is open: close it first", "게임이 열려 있습니다. 먼저 닫으세요"),

    # ------------------------------------------------------------------------------------------- screen
    "screen.sub": ("Full screen or a window, the frames and the picture's quality.", "전체 화면이나 창, 프레임과 화질을 고릅니다."),
    "screen.display": ("Display", "디스플레이"),
    "screen.mode": ("Mode", "화면 모드"),
    "screen.mode.fullscreen": ("Full screen", "전체 화면"),
    "screen.mode.window": ("Window", "창"),
    "screen.mode.hint.fullscreen": ("A borderless window over the whole display, sharp at any Windows scaling.",
                                    "모니터 전체를 덮는 테두리 없는 창입니다. Windows 배율과 상관없이 선명합니다."),
    "screen.mode.hint.window": ("A window you can move and resize. The game fills it from 4:3 to 21:9.",
                                "옮기고 크기를 바꿀 수 있는 창입니다. 게임은 4:3부터 21:9까지 창을 채웁니다."),
    "screen.size": ("Window size", "창 크기"),
    "screen.size.auto": ("Fitted to the display", "모니터에 맞춤"),
    "screen.size.hint": ("The game's area in the window.", "창 안 게임 영역의 크기입니다."),
    "screen.main": ("Main display: {w} × {h}", "주 모니터: {w} × {h}"),
    "screen.main.hz": (" at {hz} Hz", ", {hz} Hz"),
    "screen.main.up_to": (" (up to {top} Hz)", "(최대 {top} Hz)"),
    "screen.others": ("Other displays: {rates}", "다른 모니터: {rates}"),
    "screen.frames": ("Frames", "프레임"),
    "screen.vsync": ("VSync", "VSync"),
    "screen.vsync.hint.on": ("Frames go out on the display's refreshes: smooth notes, no tearing.",
                             "모니터 주사율에 맞춰 화면을 그립니다. 노트가 부드럽고 화면이 찢어지지 않습니다."),
    "screen.vsync.hint.off": ("Frames go out as soon as they are drawn, for a little less delay.",
                              "그린 프레임을 바로 화면에 보여 줘서 지연이 조금 줄어듭니다."),
    "screen.fps": ("Frame limit", "프레임 제한"),
    "screen.fps.auto": ("The display's rate", "모니터 주사율"),
    "screen.fps.auto.hz": ("The display's rate ({hz} Hz)", "모니터 주사율({hz} Hz)"),
    "screen.fps.unlimited": ("No limit", "제한 없음"),
    "screen.fps.n": ("{n} fps", "{n} fps"),
    "screen.fps.hint.vsync": ("With VSync, a limit the display's rate divides by is kept exactly, others very nearly.",
                              "VSync가 켜져 있어 주사율의 약수인 값은 정확히, 다른 값은 거의 비슷하게 맞춥니다."),
    "screen.fps.hint.vsync.exact": ("On this {hz} Hz display: {fps} fps exactly.",
                                    "이 {hz} Hz 모니터에서 정확히 {fps} fps로 보입니다."),
    "screen.fps.hint.vsync.near": ("On this {hz} Hz display: very nearly {n} fps.",
                                   "이 {hz} Hz 모니터에서 {n} fps에 아주 가깝게 보입니다."),
    "screen.fps.hint.vsync.above": ("Above this display's {hz} Hz: with VSync the game shows {hz} fps.",
                                    "이 모니터의 주사율({hz} Hz)보다 높습니다. VSync가 켜져 있어 {hz} fps로 보입니다."),
    "screen.fps.hint.vsync_rate": ("With VSync, frames follow the display's refreshes.",
                                   "VSync가 켜져 있어 모니터 주사율에 맞춰 화면을 그립니다."),
    "screen.fps.hint.free": ("Without VSync, the game holds this limit itself.",
                             "VSync가 꺼져 있어 게임이 이 제한을 직접 지킵니다."),
    "screen.fps.hint.free.unlimited": ("Without VSync, the game draws its frames without a limit.",
                                       "VSync가 꺼져 있어 게임이 프레임 수를 제한하지 않습니다."),
    "screen.counter": ("FPS counter", "FPS 표시"),
    "screen.counter.hint.on": ("The frames a second and the time of a frame, shown small over the game.",
                               "초당 프레임 수와 한 프레임의 시간을 게임 화면 위에 작게 표시합니다."),
    "screen.counter.hint.off": ("Turn it on to see the frames a second over the game.",
                                "켜면 초당 프레임 수를 게임 화면 위에 표시합니다."),
    "screen.counter.position": ("Position", "위치"),
    "screen.counter.position.top_left": ("Top left", "왼쪽 위"),
    "screen.counter.position.top_right": ("Top right", "오른쪽 위"),
    "screen.counter.position.bottom_left": ("Bottom left", "왼쪽 아래"),
    "screen.counter.position.bottom_right": ("Bottom right", "오른쪽 아래"),
    # Where the counter really stands: the corner chosen in a song, clear of the game's buttons; in the menus it waits,
    # since no place there is clear of the game's own on every screen (the player places it so, overlay_scale.h).
    "screen.counter.position.hint": ("In a song it stands in this corner, clear of the game's buttons; in the menus it is not "
                                     "shown.",
                                     "곡 중에는 고른 모서리에서 게임 버튼을 피해 표시되고, 메뉴에서는 표시되지 않습니다."),
    "screen.picture": ("Quality", "화질"),
    "screen.scale": ("Render scale", "렌더 배율"),
    "screen.scale.full": ("100% (sharpest)", "100%(가장 선명)"),
    "screen.scale.hint": ("The share of the resolution the game really draws. Lower is lighter for the graphics card, and softer.",
                          "실제로 그리는 해상도의 비율입니다. 낮추면 그래픽 카드 부담이 줄고 화면이 흐려집니다."),
    "screen.upscaler": ("Upscaler", "업스케일러"),
    "screen.upscaler.bilinear": ("Bilinear", "쌍선형"),
    "screen.upscaler.fsr1": ("AMD FSR 1", "AMD FSR 1"),
    "screen.upscaler.nis": ("NVIDIA NIS", "NVIDIA NIS"),
    "screen.upscaler.hint.bilinear": ("Stretches the picture as it is, the lightest way.",
                                      "그림을 그대로 늘리는 가장 가벼운 방식입니다."),
    "screen.upscaler.hint.fsr1": ("Enlarges the picture keeping its edges crisp, then sharpens it.",
                                  "가장자리를 살려 그림을 키운 뒤 선명하게 다듬습니다."),
    "screen.upscaler.hint.nis": ("Enlarges the picture in one pass, following its edges.",
                                 "가장자리를 따라 그림을 한 번에 키웁니다."),
    "screen.aa": ("Anti-aliasing", "안티에일리어싱"),
    "screen.aa.off": ("Off", "끔"),
    "screen.aa.cmaa2": ("CMAA 2", "CMAA 2"),
    "screen.aa.smaa": ("SMAA", "SMAA"),
    "screen.aa.hint.off": ("The edges of shapes stay as the game draws them.", "도형의 가장자리를 게임이 그린 그대로 둡니다."),
    "screen.aa.hint.cmaa2": ("Smooths jagged edges and keeps text and thin lines sharp.",
                             "계단처럼 각진 가장자리를 매끄럽게 하면서 글자와 가는 선은 선명하게 둡니다."),
    "screen.aa.hint.smaa": ("Smooths jagged edges with a light pass over the finished picture.",
                            "완성된 화면을 한 번 더 가볍게 다듬어 각진 가장자리를 매끄럽게 합니다."),

    # -------------------------------------------------------------------------------------------- sound
    "sound.sub": ("The game's volumes, its equaliser and the device it plays on.",
                  "게임 음량과 이퀄라이저, 소리를 재생할 장치를 설정합니다."),
    "sound.volume": ("Volume", "음량"),
    "sound.volume.master": ("Master", "마스터"),
    "sound.volume.music": ("Music", "음악"),
    "sound.volume.effects": ("Effects", "효과음"),
    "sound.volume.master.hint": ("Everything the game plays, from 0 to 100. Windows' own volume still applies.",
                                 "게임 소리 전체를 0~100으로 맞춥니다. Windows 음량도 그대로 적용됩니다."),
    "sound.volume.music.hint": ("Songs and the game's background music, as a share of the master volume.",
                                "곡과 게임 배경 음악의 크기를 마스터 음량 기준 비율로 맞춥니다."),
    "sound.volume.effects.hint": ("Key sounds, judgements and the menus' sounds, as a share of the master volume.",
                                  "키음, 판정음, 메뉴 효과음의 크기를 마스터 음량 기준 비율로 맞춥니다."),
    "sound.eq": ("Equaliser", "이퀄라이저"),
    "sound.eq.preset": ("Preset", "프리셋"),
    "sound.eq.flat": ("Flat", "기본"),
    "sound.eq.bass": ("Bass", "베이스"),
    "sound.eq.vocal": ("Vocal", "보컬"),
    "sound.eq.treble": ("Treble", "트레블"),
    "sound.eq.custom": ("Custom", "커스텀"),
    "sound.eq.hint.flat": ("The game's sound as it is.", "게임 소리를 그대로 들려줍니다."),
    "sound.eq.hint.bass": ("The low end lifted: kicks and bass lines come forward.",
                           "저음을 올려 킥과 베이스가 두드러집니다."),
    "sound.eq.hint.vocal": ("The middle lifted: voices and leads come forward.",
                            "중음을 올려 보컬과 멜로디가 두드러집니다."),
    "sound.eq.hint.treble": ("The high end lifted: hi-hats and key sounds come forward.",
                             "고음을 올려 하이햇과 키음이 두드러집니다."),
    "sound.eq.hint.custom": ("Your own three bands, set below.", "아래 세 대역을 직접 맞춘 설정입니다."),
    "sound.eq.low": ("Low 120 Hz", "저음 120 Hz"),
    "sound.eq.mid": ("Mid 1 kHz", "중음 1 kHz"),
    "sound.eq.high": ("High 6 kHz", "고음 6 kHz"),
    "sound.db": ("{sign}{n} dB", "{sign}{n} dB"),
    "sound.output": ("Output", "출력"),
    "sound.device": ("Device", "장치"),
    "sound.device.looking": ("Looking for sound devices...", "소리 장치를 찾는 중..."),
    "sound.device.default": ("Windows' default output", "Windows 기본 출력"),
    "sound.device.now_default": (" (the default now)", " (현재 기본 장치)"),
    "sound.device.gone": ("The device chosen before (not connected)", "전에 고른 장치(연결되지 않음)"),
    "sound.device.hint": ("Windows' default follows the output Windows plays through, also when it changes mid-game.",
                          "Windows 기본은 Windows가 쓰는 출력을 따르며, 플레이 중에 바뀌어도 따라갑니다."),
    "sound.device.none": ("No sound devices were found. The game plays through Windows' default output.",
                          "소리 장치를 찾지 못했습니다. 게임 소리는 Windows 기본 출력으로 재생합니다."),
    "sound.mode": ("Mode", "방식"),
    "sound.mode.shared": ("Shared", "공유"),
    "sound.mode.exclusive": ("Exclusive", "독점"),
    "sound.mode.hint.shared": ("Plays alongside other programs' sound.", "다른 프로그램 소리와 함께 재생합니다."),
    "sound.mode.hint.exclusive": ("Takes the device for the game alone, for the least delay. Other programs are silent meanwhile; when Windows does not allow it, the sound is shared.",
                                  "장치를 게임만 쓰게 해서 지연을 가장 줄입니다. 그동안 다른 프로그램은 소리가 나지 않습니다. Windows가 허락하지 않으면 공유 방식으로 재생합니다."),
    "sound.buffer": ("Buffer", "버퍼"),
    "sound.buffer.low": ("Low", "낮음"),
    "sound.buffer.normal": ("Normal", "보통"),
    "sound.buffer.safe": ("Safe", "안정"),
    "sound.buffer.hint.low": ("The least delay between a hit and its sound: the shortest period Windows has for the device.",
                              "치는 순간과 소리 사이의 지연이 가장 적습니다. Windows가 이 장치에 쓸 수 있는 가장 짧은 주기로 재생합니다."),
    "sound.buffer.hint.normal": ("A 20 ms buffer, a little more delay than Low.", "20 ms 버퍼로, 낮음보다 지연이 조금 깁니다."),
    "sound.buffer.hint.safe": ("More sound kept ahead: no breaks on a busy PC, a little more delay.",
                               "소리를 더 앞서 준비해 부하가 큰 PC에서도 끊기지 않습니다. 지연이 조금 늘어납니다."),
    # The last game's sound as the player measured it (player.last_sound): how it had the device, the device's period,
    # the time from the game's sound to the device's output, and the gaps.
    "sound.last": ("Last game's sound", "지난 플레이의 소리"),
    "sound.last.none": ("No game on this PC yet.", "이 PC에서 아직 플레이하지 않았습니다."),
    "sound.last.mode.shared": ("Shared", "공유"),
    "sound.last.mode.shared-low": ("Shared (low latency)", "공유(저지연)"),
    "sound.last.mode.exclusive": ("Exclusive", "독점"),
    "sound.last.mode.none": ("No sound device", "소리 장치 없음"),
    "sound.last.period": ("{ms} ms period", "주기 {ms} ms"),
    "sound.last.out": ("{ms} ms output delay", "출력 지연 {ms} ms"),
    "sound.last.no_gaps": ("no gaps", "끊김 없음"),
    "sound.last.gap": ("1 gap", "끊김 1번"),
    "sound.last.gaps": ("{n} gaps", "끊김 {n}번"),

    # ----------------------------------------------------------------------------------------- controls
    "controls.sub": ("The keys that play the lanes.", "줄을 치는 키를 설정합니다."),
    "controls.keys": ("Keyboard play", "키보드 플레이"),
    "controls.keys.play": ("Play with keys", "키로 플레이"),
    "controls.keys.play.hint.on": ("In a song, each lane plays with its keys below.", "곡에서 줄마다 아래 키로 칩니다."),
    "controls.keys.play.hint.off": ("The keys play no lane. The mouse and a touch screen play.",
                                    "키로는 줄을 치지 않습니다. 마우스와 터치스크린으로 칩니다."),
    "controls.keys.reset": ("Reset keys", "기본 키로 되돌리기"),
    "controls.keys.hint": ("Lanes from the top. Click a box, then press the key for it; + adds a second key.",
                           "줄은 위에서부터입니다. 칸을 누른 뒤 그 줄에 쓸 키를 누르세요. +는 두 번째 키를 더합니다."),
    "controls.keys.hint.print": ("A key is named for its place on a US keyboard; in grey, what this keyboard prints there.",
                                 "키 이름은 미국 자판 기준이고, 회색 글자는 이 키보드에서 같은 자리에 있는 글자입니다."),
    "controls.keys.wait": ("Press a key for lane {lane} of {mode}. Esc keeps {keyname}.",
                           "{mode} {lane}번 줄에 쓸 키를 누르세요. Esc를 누르면 {keyname} 키 그대로입니다."),
    "controls.keys.wait.delete": ("Delete takes it away.", "Delete를 누르면 이 키를 뺍니다."),
    "controls.keys.wait.second": ("Press a second key for lane {lane} of {mode}. Esc adds none.",
                                  "{mode} {lane}번 줄에 더할 두 번째 키를 누르세요. Esc를 누르면 더하지 않습니다."),
    "controls.keys.cannot": ("{keyname} cannot play a lane. Lanes take the letters, the digits above them, Space and "
                             "the signs a US keyboard has around the letters.",
                             "{keyname} 키로는 줄을 칠 수 없습니다. 줄에는 글자 키, 그 위의 숫자 키, Space, 미국 자판에서 "
                             "글자 키 둘레에 있는 기호 키를 씁니다."),
    "controls.keys.cannot.any": ("This key cannot play a lane. Lanes take the letters, the digits above them, Space and "
                                 "the signs a US keyboard has around the letters.",
                                 "이 키로는 줄을 칠 수 없습니다. 줄에는 글자 키, 그 위의 숫자 키, Space, 미국 자판에서 "
                                 "글자 키 둘레에 있는 기호 키를 씁니다."),

    # ------------------------------------------------------------------------------------------- online
    "online.sub": ("The server you play on, your sign-in and its app on this PC.", "플레이하는 서버와 로그인, 이 PC에 다운로드한 앱입니다."),
    "online.server": ("Server", "서버"),
    "online.address": ("Server address", "서버 주소"),
    "online.address.example": ("192.168.1.10:8791", "192.168.1.10:8791"),
    "online.connect": ("Connect", "연결"),
    "online.connecting": ("Connecting...", "연결하는 중..."),
    "online.connected": ("Connected to {name}.", "{name}에 연결했습니다."),
    "online.to_play": ("Server to play on: {name}", "플레이할 서버: {name}"),
    "online.busy": ("Wait until the game or the download is over.", "게임이나 다운로드가 끝날 때까지 기다리세요."),
    "online.account": ("Sign in", "로그인"),
    "online.account.signed": ("Signed in", "로그인됨"),
    "online.id": ("ID", "아이디"),
    "online.password": ("Password", "비밀번호"),
    "online.password.show": ("Show", "보기"),
    "online.password.hide": ("Hide", "숨기기"),
    "online.signin.on": ("Server: {name}", "서버: {name}"),
    "online.signin": ("Sign in", "로그인"),
    "online.signing": ("Signing in...", "로그인하는 중..."),
    "online.signin.hint": ("With the ID and password the server's owner made for you. The launcher keeps the sign-in, never the password.",
                           "서버 소유자가 만들어 준 아이디와 비밀번호로 로그인합니다. 런처는 로그인 상태만 기억하고 비밀번호는 저장하지 않습니다."),
    "online.signed": ("{account}", "{account}"),
    "online.signout": ("Sign out", "로그아웃"),
    "online.app": ("The server's app", "서버의 앱"),
    "online.app.have": ("The app on this PC: {date}.", "이 PC의 앱: {date}"),
    "online.app.newer": ("The server has a newer app ({date}). PLAY gets it too.", "서버에 새 앱이 있습니다({date}). PLAY를 누르면 함께 다운로드합니다."),
    "online.app.newest": ("This is the server's newest app.", "서버의 최신 앱입니다."),
    "online.app.none": ("Not on this PC yet.", "아직 이 PC에 없습니다."),
    "online.app.signin": ("Sign in to download it.", "로그인하면 다운로드할 수 있습니다."),
    "online.app.signin_newer": ("Sign in to get the server's newer apps.", "로그인하면 서버의 새 앱을 다운로드할 수 있습니다."),
    "online.app.get": ("Download the app", "앱 다운로드"),
    "online.app.update": ("Get the newer app", "새 앱 다운로드"),
    "online.app.check": ("Check for a newer app", "새 앱 확인"),
    "online.stopping": ("Stopping...", "멈추는 중..."),
    "online.others": ("Other servers", "다른 서버"),
    "online.pick": ("Play here", "여기서 플레이"),
    "online.forget": ("Forget", "목록에서 빼기"),
    "online.forget.title": ("Forget server", "목록에서 서버 빼기"),
    "online.forget.ask": ("Forget this server?", "이 서버를 목록에서 뺄까요?"),
    "online.forget.detail": ("This removes the sign-in and the app of {name} on this PC. Your records stay on the server.",
                             "{name}의 로그인과 앱을 이 PC에서 지웁니다. 기록은 서버에 그대로 있습니다."),

    # --------------------------------------------------------------------------------------------- help
    "help.sub": ("The ready check, and what to do when something goes wrong.", "준비 점검과 문제가 생겼을 때 할 일입니다."),
    "help.checks": ("Checks", "점검"),
    "help.recheck": ("Check again", "다시 점검"),
    "help.tools": ("Tools", "도구"),
    "help.player_log": ("Game log", "게임 로그"),
    "help.player_log.hint": ("What the game wrote while it ran, with the reason when it stopped.",
                             "게임이 실행되는 동안 남긴 로그입니다. 멈췄다면 그 이유도 있습니다."),
    "help.logs": ("The launcher's log", "런처 로그"),
    "help.logs.hint": ("What the launcher did: connecting, signing in, downloads, updates.", "런처가 한 일입니다. 연결, 로그인, 다운로드, 업데이트."),
    "help.report": ("Save a report", "보고서 저장"),
    "help.report.row": ("Report", "보고서"),
    "help.report.hint": ("One zip for whoever helps: the logs, the settings, the displays, the sound devices, Windows and the graphics card. Your user name, the servers' addresses and the sign-ins are left out.",
                         "도와주는 사람에게 보낼 zip 파일 하나입니다. 로그, 설정, 디스플레이, 소리 장치, Windows와 그래픽 카드 정보가 들어가고, 사용자 이름, 서버 주소, 로그인 정보는 빠집니다."),
    "help.report.working": ("Making the report...", "보고서를 만드는 중..."),
    "help.report.done": ("Saved the report: {name}", "보고서를 저장했습니다: {name}"),
    "help.report.done.detail": ("It is in {folder}, selected in the File Explorer window that opened. Left out: {left}.",
                                "{folder} 폴더에 있습니다. 열린 파일 탐색기 창에서 선택해 두었습니다. 뺀 것: {left}."),
    "help.report.failed": ("The report was not saved.", "보고서를 저장하지 못했습니다."),
    # What a report leaves out (report.KINDS), in the list the dialog and --report say after it is made.
    "report.left.user": ("your Windows user name in paths", "경로 속 Windows 사용자 이름"),
    "report.left.person": ("people's names in sound devices' names", "소리 장치 이름 속 사람 이름"),
    "report.left.account": ("your site ID", "사이트 아이디"),
    "report.left.server": ("the servers' addresses", "서버 주소"),
    "report.left.server_name": ("the servers' names", "서버 이름"),
    "report.left.cookie": ("the sign-in cookies", "로그인 쿠키"),
    "report.left.token": ("tokens and keys", "토큰과 키"),
    "report.left.device": ("this PC's player id", "이 PC의 기기 ID"),
    "report.left.typed": ("what was typed in the game", "게임에서 입력한 글"),
    "report.left.none": ("nothing of the kind was found", "해당하는 것이 없었습니다"),
    "help.reset": ("Start over", "처음부터"),
    "help.reset.row": ("Servers and settings", "서버와 설정"),
    "help.reset.hint": ("Forgets the servers, the sign-ins, the downloaded apps and the settings, and opens the first-start guide. The game's own data stays.",
                        "서버, 로그인, 다운로드한 앱, 설정을 지우고 처음 시작 안내를 엽니다. 게임 자체의 데이터는 그대로 둡니다."),
    "help.reset.title": ("Start over", "처음부터"),
    "help.reset.ask": ("Forget everything the launcher keeps?", "런처가 기억하는 것을 모두 지울까요?"),
    "help.reset.detail": ("This removes the servers, sign-ins, downloaded apps and settings. Your records stay on the servers.",
                          "서버, 로그인, 다운로드한 앱, 설정을 지웁니다. 기록은 서버에 그대로 있습니다."),
    "help.reset.confirm": ("Start over", "처음부터"),
    "help.reset.busy": ("Wait until the game or the download is over.", "게임이나 다운로드가 끝날 때까지 기다리세요."),
    "help.repair": ("Repair", "복구"),
    "help.repair.row": ("Program files", "프로그램 파일"),
    "help.repair.hint": ("Compares the program's files with the installed package and puts back what is missing or changed. Settings and the game's data are not touched.",
                         "프로그램 파일을 설치된 패키지와 대조해 없거나 바뀐 파일을 되돌립니다. 설정과 게임 데이터는 건드리지 않습니다."),
    "help.repair.working": ("Checking the program's files...", "프로그램 파일을 확인하는 중..."),
    "help.repair.working.detail": ("What is missing or changed comes back from the installed package.",
                                   "없거나 바뀐 파일은 설치된 패키지에서 되돌립니다."),
    "help.repair.fine": ("Nothing to repair.", "복구할 것이 없습니다."),
    "help.repair.fine.detail": ("All {n} files of the program are as installed.", "프로그램 파일 {n}개가 모두 설치된 그대로입니다."),
    "help.repair.done": ("Repaired.", "복구했습니다."),
    "help.repair.done.detail": ("Files put back: {n}.", "되돌린 파일: {n}개."),
    "help.repair.done.restart": ("Files put back: {n}, some of them the launcher's own. Close the launcher and open it "
                                 "again.", "되돌린 파일: {n}개. 런처 파일도 되돌렸으니 런처를 닫고 다시 여세요."),
    # One file put back, the launcher's own: said of the one file.
    "help.repair.done.restart.one": ("One file put back, the launcher's own. Close the launcher and open it again.",
                                     "런처 파일 1개를 되돌렸습니다. 런처를 닫고 다시 여세요."),
    "help.repair.partly": ("Not everything could be repaired.", "일부를 복구하지 못했습니다."),
    "help.repair.partly.detail": ("Files put back: {n}. Not put back: {failed}. Run the installer again and choose Repair.",
                                  "되돌린 파일: {n}개. 되돌리지 못한 파일: {failed}개. 설치 프로그램을 다시 실행해 복구를 고르세요."),
    "help.repair.failed": ("Repair failed.", "복구하지 못했습니다."),
    "help.remove": ("Reset and remove", "초기화와 제거"),
    "help.counting": ("Counting the data on this PC...", "이 PC의 데이터 크기를 확인하는 중..."),
    "help.clear": ("Clear game data", "게임 데이터 지우기"),
    "help.clear.row": ("Game data", "게임 데이터"),
    "help.clear.hint": ("Deletes what the game keeps on this PC: its downloads and its own settings. The game downloads its data again at the next start, and this PC stays the same player.",
                        "게임이 이 PC에 둔 것(다운로드한 데이터와 게임 안 설정)을 지웁니다. 다음에 시작할 때 다시 다운로드하고, 이 PC의 플레이어는 그대로입니다."),
    "help.clear.ask": ("Delete the game's data on this PC?", "이 PC의 게임 데이터를 지울까요?"),
    "help.clear.detail": ("Deletes {size}; the game downloads its data again at the next start. Your records stay on the server and this PC stays the same player.",
                          "{size}를 지우고, 다음에 시작할 때 다시 다운로드합니다. 기록은 서버에 그대로 있고 이 PC의 플레이어도 그대로입니다."),
    "help.clear.confirm": ("Clear", "지우기"),
    "help.clear.working": ("Deleting the game's data...", "게임 데이터를 지우는 중..."),
    "help.clear.none": ("There is no game data on this PC.", "이 PC에 게임 데이터가 없습니다."),
    "help.clear.done": ("Cleared the game's data ({size}).", "게임 데이터를 지웠습니다({size})."),
    "help.clear.partly": ("Not everything could be deleted.", "일부를 지우지 못했습니다."),
    "help.clear.partly.detail": ("In use and left in place: {n}. The first is {path}. Close what uses them and clear again.",
                                 "사용 중이라 남은 항목: {n}개. 첫 항목: {path}. 쓰고 있는 프로그램을 닫고 다시 지우세요."),
    "help.uninstall": ("Uninstall", "제거"),
    "help.uninstall.row": ("OpenDMTQ", "OpenDMTQ"),
    "help.uninstall.hint": ("Removes OpenDMTQ from this PC. You choose then whether the settings and the game's data stay.",
                            "이 PC에서 OpenDMTQ를 제거합니다. 설정과 게임 데이터를 남길지는 그때 고릅니다."),
    "help.uninstall.ask": ("Uninstall OpenDMTQ from this PC?", "이 PC에서 OpenDMTQ를 제거할까요?"),
    "help.uninstall.detail": ("The launcher closes and the program is gone a few seconds later. Your records stay on the server.\n\nKeep data: the settings, sign-ins and game data stay for a later install.\nDelete all: they are deleted too ({size}), with the id this PC plays by, and a later install starts as a new player.",
                              "런처가 닫히고 몇 초 뒤 프로그램이 지워집니다. 기록은 서버에 그대로 있습니다.\n\n데이터 남기기: 설정, 로그인, 게임 데이터를 남겨 다시 설치할 때 그대로 씁니다.\n모두 삭제: 이 PC의 기기 ID까지 모두 지웁니다({size}). 다시 설치하면 새 플레이어로 시작합니다."),
    "help.uninstall.keep": ("Keep data", "데이터 남기기"),
    "help.uninstall.all": ("Delete all", "모두 삭제"),
    "help.uninstall.working": ("Deleting OpenDMTQ's data on this PC...", "이 PC의 OpenDMTQ 데이터를 지우는 중..."),
    "help.uninstall.working.detail": ("Then the launcher closes, and the program is gone a few seconds later.",
                                      "끝나면 런처가 닫히고, 몇 초 뒤 프로그램이 지워집니다."),
    "help.uninstall.left": ("Some files stayed.", "남은 파일이 있습니다."),
    "help.uninstall.left.detail": ("In use and left in place: {n}, in {folder}. The program is uninstalled now; delete that folder afterwards.",
                                   "사용 중이라 남은 항목: {n}개({folder}). 프로그램은 지금 제거됩니다. 그 폴더는 나중에 직접 지우세요."),
    "help.uninstall.failed": ("Uninstall failed.", "제거하지 못했습니다."),
    "help.uninstall.failed.detail": ("The uninstaller did not start: {error}\nWindows' Settings, Apps removes OpenDMTQ too.",
                                     "제거 프로그램이 시작되지 않았습니다: {error}\nWindows 설정의 앱에서도 OpenDMTQ를 제거할 수 있습니다."),
    # The card after an uninstall from Windows' Settings, Apps (removal.show_uninstalled): what went, what stayed.
    "uninstalled.done": ("OpenDMTQ is uninstalled.", "OpenDMTQ를 제거했습니다."),
    "uninstalled.gone": ("Removed: the program, its shortcuts and its entry in Windows' Apps.",
                         "지운 것: 프로그램, 바로 가기, Windows 앱 목록의 항목."),
    "uninstalled.kept": ("Kept for a later install: the settings, sign-ins and game data ({size}) in {folder}. Your records stay on the server.",
                         "다시 설치할 때 쓰도록 남긴 것: {folder}의 설정, 로그인, 게임 데이터({size}). 기록은 서버에 그대로 있습니다."),
    "uninstalled.nothing": ("Nothing of OpenDMTQ's stays on this PC. Your records stay on the server.",
                            "이 PC에 OpenDMTQ 파일은 남지 않았습니다. 기록은 서버에 그대로 있습니다."),

    # -------------------------------------------------------------------------------------------- about
    "about.sub": ("The launcher's own settings and updates.", "런처 자체의 설정과 업데이트입니다."),
    "about.general": ("General", "일반"),
    "about.language": ("Language", "언어"),
    "about.language.system": ("Same as Windows", "Windows 언어 따르기"),
    "about.updates": ("Updates", "업데이트"),
    "about.version": ("Version {v}", "버전 {v}"),
    "about.check": ("Check for updates", "업데이트 확인"),
    "about.checking": ("Checking...", "확인하는 중..."),
    "about.available": ("OpenDMTQ {v} is available.", "OpenDMTQ {v} 버전이 나왔습니다."),
    # Where the update comes from, when it is the server PLAY plays on (updates.py: the server first, GitHub second).
    "about.available.from": ("OpenDMTQ {v} is available from {source}.", "{source}에서 OpenDMTQ {v} 버전을 다운로드할 수 있습니다."),
    "about.uptodate.from": ("This is the newest version for {source}.", "{source}에 맞는 최신 버전입니다."),
    # An update whose release is not signed by the project (updates.py, signing.py): a fact, and what the launcher does.
    "about.refused": ("The update from {source} is not signed by the OpenDMTQ project, so the launcher does not install it.",
                      "{source}의 업데이트는 OpenDMTQ 프로젝트가 서명한 것이 아니어서 설치하지 않습니다."),
    "about.update_now": ("Update to {v}", "{v} 버전으로 업데이트"),
    "about.uptodate": ("This is the newest version.", "최신 버전입니다."),
    "about.not_installed": ("Updates work in the launcher the installer put on this PC.",
                            "업데이트는 설치 프로그램으로 설치한 런처에서 됩니다."),
    "about.no_source": ("No update address is set for this build.", "이 빌드에는 업데이트 주소가 없습니다."),
    "about.update_failed": ("Could not check for updates.", "업데이트를 확인하지 못했습니다."),
    "about.apply_failed": ("The update was not installed.", "업데이트를 설치하지 못했습니다."),
    "about.updating.title": ("Update", "업데이트"),
    "about.updating.message": ("Updating OpenDMTQ to {v}...", "OpenDMTQ를 {v} 버전으로 업데이트하는 중..."),
    "about.updating.detail": ("The launcher closes and starts again in a few seconds. Your servers and settings stay.",
                              "런처가 닫혔다가 몇 초 뒤 다시 열립니다. 서버와 설정은 그대로입니다."),
    "about.update_failed.title": ("Update failed", "업데이트 실패"),
    "about.update_busy": ("Close the game first: the update replaces the game program.",
                          "먼저 게임을 닫으세요. 업데이트가 게임 프로그램을 바꿉니다."),
    "about.guide": ("First-start guide", "처음 시작 안내"),
    "about.guide.run": ("Show it again", "다시 보기"),
    "about.legal": ("About", "정보"),
    "about.license": ("OpenDMTQ is MIT licensed. The launcher brings no game files: the app comes from the server you play on.",
                      "OpenDMTQ는 MIT 라이선스입니다. 런처에는 게임 파일이 없고, 앱은 플레이하는 서버에서 다운로드합니다."),
    "about.notice": ("An unofficial, non-commercial project, not affiliated with or endorsed by NEOWIZ. DJMAX and TECHNIKA Q belong to NEOWIZ.",
                     "NEOWIZ와 관련이 없는 비공식·비상업 프로젝트입니다. DJMAX와 TECHNIKA Q의 권리는 NEOWIZ에 있습니다."),
    # The notice's second line, the owner's sentence word for word, as the site's footers have it.
    "about.notice.2": ("OpenDMTQ contains no game data. If the copyright holder requests it, this project may be made private or shut down.",
                       "OpenDMTQ에는 게임 데이터가 포함되어 있지 않습니다. 저작권자의 요청이 있는 경우 본 프로젝트는 비공개되거나 폐쇄될 수 있습니다."),

    # -------------------------------------------------------------------------------------------- guide
    "guide.skip": ("Skip: I set it up myself", "건너뛰기(직접 설정)"),
    "guide.back": ("Back", "뒤로"),
    "guide.next": ("Next", "다음"),
    "guide.need.server": ("Connect to a server to go on.", "서버에 연결하면 다음으로 넘어갑니다."),
    "guide.need.login": ("Sign in to go on.", "로그인하면 다음으로 넘어갑니다."),
    "guide.need.download": ("Get the app to go on.", "앱을 다운로드하면 다음으로 넘어갑니다."),
    "guide.power.name": ("POWER ON", "POWER ON"),
    "guide.power.title": ("Welcome to OpenDMTQ", "OpenDMTQ에 오신 것을 환영합니다"),
    "guide.power.text": ("A few steps to your first song.", "첫 곡까지 몇 단계면 됩니다."),
    "guide.power.notice.title": ("The app comes from your server", "앱은 플레이할 서버에서"),
    "guide.power.notice": ("The launcher brings no game files. It downloads the app from the OpenDMTQ server you play on, once you sign in there.",
                           "런처에는 게임 파일이 없습니다. 플레이할 OpenDMTQ 서버에 로그인하면 그 서버에서 앱을 다운로드합니다."),
    "guide.power.need": ("What you need", "준비물"),
    "guide.power.need.1": ("An OpenDMTQ server's address, and the ID and password the server's owner made for you.",
                           "OpenDMTQ 서버 주소와, 서버 소유자가 만들어 준 아이디와 비밀번호."),
    "guide.power.need.2": ("64-bit Windows 10 or 11, and a touch screen or a mouse; a keyboard plays the lanes too.",
                           "64비트 Windows 10이나 11, 그리고 터치스크린이나 마우스. 키보드로도 줄을 칠 수 있습니다."),
    "guide.server.name": ("SERVER", "SERVER"),
    "guide.server.title": ("Which server?", "어느 서버인가요?"),
    "guide.server.text": ("The address of the OpenDMTQ server's site, as the server's owner gave it (the one a phone opens to get the app).",
                          "OpenDMTQ 서버 사이트의 주소입니다. 서버 소유자가 알려 준 주소(휴대폰으로 앱을 다운로드할 때 여는 주소)를 쓰세요."),
    "guide.login.name": ("SIGN IN", "SIGN IN"),
    "guide.login.title": ("Who plays?", "누가 플레이하나요?"),
    "guide.login.text": ("Sign in to the server's site with your account. The game keeps its own records on the server.",
                         "서버 사이트에 계정으로 로그인합니다. 플레이 기록은 게임이 서버에 남깁니다."),
    "guide.download.name": ("DOWNLOAD", "DOWNLOAD"),
    "guide.download.title": ("Get the app", "앱 다운로드"),
    "guide.download.text": ("The server builds it for its own address, the same one its phones install. It comes once, and again only when the server has a newer one.",
                            "서버 주소에 맞춰 만든 앱으로, 휴대폰에 설치하는 앱과 같습니다. 한 번 다운로드하고, 서버에 새 버전이 있을 때만 다시 다운로드합니다."),
    # The step named as its page names it (Sound and screen), one name for one step (main: SOUND CHECK in the column).
    "guide.sound.name": ("SOUND & SCREEN", "SOUND & SCREEN"),
    "guide.sound.title": ("Sound and screen", "소리와 화면"),
    # The step's card of the screen beside the volumes: the display's mode and the frames.
    "guide.sound.screen": ("Screen", "화면"),
    "guide.stage.name": ("STAGE START", "STAGE START"),
    "guide.stage.title": ("Ready for stage 1", "1스테이지 준비 끝"),
    "guide.stage.text": ("PLAY starts the game with these settings. The launcher waits while you play.",
                         "PLAY를 누르면 이 설정으로 게임을 시작합니다. 게임을 하는 동안 런처는 기다립니다."),

    # ------------------------------------------------------------------------------------- the installer
    "setup.window": ("OpenDMTQ Setup", "OpenDMTQ 설치"),
    # The window's own buttons at the top right of its header, as screen readers say them (Windows' names for its own).
    "setup.window.minimize": ("Minimize", "최소화"),
    "setup.window.close": ("Close", "닫기"),
    # Velopack's setup makes both shortcuts (vpk's default places): the one on the desktop and the one in the Start menu.
    "setup.install": ("Install", "설치"),
    "setup.update": ("Update", "업데이트"),
    "setup.back": ("Install {here}", "{here} 버전 설치"),
    "setup.closing": ("The launcher is open: it closes first.", "열려 있는 런처는 먼저 닫힙니다."),
    "setup.repair": ("Repair", "복구"),
    "setup.open": ("Open OpenDMTQ", "OpenDMTQ 열기"),
    "setup.cancel": ("Cancel", "취소"),
    "setup.close": ("Close", "닫기"),
    "setup.retry": ("Try again", "다시 시도"),
    "setup.game": ("The game is open.", "게임이 열려 있습니다."),
    "setup.work.install": ("Installing", "설치 중"),
    "setup.work.install.line": ("Installing OpenDMTQ {v}...", "OpenDMTQ {v} 버전을 설치하는 중..."),
    "setup.work.update": ("Updating", "업데이트 중"),
    "setup.work.update.line": ("Updating OpenDMTQ to {v}...", "OpenDMTQ를 {v} 버전으로 업데이트하는 중..."),
    "setup.work.repair": ("Repairing", "복구 중"),
    "setup.work.repair.line": ("Repairing OpenDMTQ {v}...", "OpenDMTQ {v} 버전을 복구하는 중..."),
    "setup.work.back": ("Installing", "설치 중"),
    "setup.work.back.line": ("Going back to OpenDMTQ {v}...", "OpenDMTQ {v} 버전으로 되돌리는 중..."),
    "setup.done": ("OpenDMTQ {v} is installed.", "OpenDMTQ {v} 버전을 설치했습니다."),
    "setup.failed": ("OpenDMTQ could not be installed.", "OpenDMTQ를 설치하지 못했습니다."),
    "setup.failed.log": ("The log is {path}", "로그 파일: {path}"),
    "setup.open_log": ("Open the log", "로그 열기"),
    "setup.not_started": ("OpenDMTQ did not start.", "OpenDMTQ가 열리지 않았습니다."),
    "setup.not_started.detail": ("OpenDMTQ is installed, but it did not start.", "OpenDMTQ는 설치됐지만 열리지 않았습니다."),
    "setup.no_setup": ("The setup inside this installer did not start.", "설치 파일 안의 설치 프로그램이 시작되지 않았습니다."),
    "setup.too_long": ("The setup did not finish in {m} minutes.", "설치가 {m}분 안에 끝나지 않았습니다."),
    "setup.wrong_version": ("The setup finished, but the installed version is {found} (this installer has {here}).",
                            "설치는 끝났지만 설치된 버전이 {found}입니다(이 설치 파일은 {here})."),

    # --------------------------------------------- the installer's window: its pages, install, repair and uninstall
    # The steps down its column, in the wide face, English in both languages as the launcher's menu and the guide's steps.
    "setup.step.ready": ("READY", "READY"),
    "setup.step.install": ("INSTALL", "INSTALL"),
    "setup.step.choose": ("CHOOSE", "CHOOSE"),
    "setup.step.repair": ("REPAIR", "REPAIR"),
    "setup.step.update": ("UPDATE", "UPDATE"),
    "setup.step.open": ("OPEN", "OPEN"),
    "setup.step.data": ("YOUR DATA", "YOUR DATA"),
    "setup.step.uninstall": ("UNINSTALL", "UNINSTALL"),
    "setup.step.done": ("DONE", "DONE"),
    # Each page's title and the line under it.
    "setup.title.install": ("Install", "설치"),
    "setup.lead.install": ("OpenDMTQ {v} for this Windows user: the launcher, and the player that runs the game.",
                           "OpenDMTQ {v} 버전을 현재 Windows 사용자 계정에 설치합니다. 런처와 게임 프로그램이 함께 설치됩니다."),
    "setup.title.installed": ("OpenDMTQ {v}", "OpenDMTQ {v}"),
    "setup.lead.installed": ("Installed on this PC.", "이 PC에 설치돼 있습니다."),
    "setup.lead.newer": ("{have} is installed on this PC. This installer has {v}.",
                         "이 PC에는 {have} 버전이 설치돼 있고, 이 설치 파일은 {v} 버전입니다."),
    "setup.title.uninstall": ("Uninstall", "제거"),
    "setup.lead.uninstall": ("Removes the program, its shortcuts and its entry in Windows' Apps. Your records stay on the server.",
                             "프로그램과 바로 가기, Windows 앱 목록의 항목을 지웁니다. 기록은 서버에 그대로 남습니다."),
    "setup.title.installing": ("Installing", "설치 중"),
    "setup.title.updating": ("Updating", "업데이트 중"),
    "setup.title.repairing": ("Repairing", "복구 중"),
    "setup.title.uninstalling": ("Uninstalling", "제거 중"),
    "setup.title.done": ("Done", "완료"),
    "setup.title.failed": ("Not done", "완료하지 못함"),
    "setup.title.wait": ("One moment", "잠시 기다려 주세요"),
    # The install page's card: what goes where.
    "setup.card.install": ("What goes where", "설치 내용"),
    "setup.row.program": ("Program", "프로그램"),
    "setup.row.shortcuts": ("Shortcuts", "바로 가기"),
    "setup.row.shortcuts.where": ("On the desktop and in the Start menu", "바탕 화면과 시작 메뉴"),
    "setup.row.rights": ("Rights", "권한"),
    "setup.row.rights.what": ("This Windows user's own, no administrator rights", "현재 Windows 사용자 권한(관리자 권한 필요 없음)"),
    "setup.row.server": ("Server", "서버"),
    # The installed PC's choices.
    "setup.card.choose": ("What to do", "작업 선택"),
    "setup.opt.open": ("Open OpenDMTQ", "OpenDMTQ 열기"),
    "setup.opt.open.line": ("The launcher as it is installed.", "설치된 그대로 런처를 엽니다."),
    "setup.opt.update": ("Update to {v}", "{v} 버전으로 업데이트"),
    "setup.opt.update.line": ("Updates the program from {have} to {v}. Your servers, sign-ins and settings stay.",
                              "프로그램을 {have} 버전에서 {v} 버전으로 바꿉니다. 서버와 로그인 정보, 설정은 그대로 둡니다."),
    "setup.opt.back": ("Install {v}", "{v} 버전 설치"),
    "setup.opt.back.line": ("Installs {v} in place of {have}. Your servers, sign-ins and settings stay.",
                            "프로그램을 {have} 버전에서 {v} 버전으로 되돌립니다. 서버와 로그인 정보, 설정은 그대로 둡니다."),
    "setup.opt.repair": ("Repair", "복구"),
    "setup.opt.repair.line": ("Installs {v} again, every file of the program put back as it came. Your servers, sign-ins and settings stay.",
                              "{v} 버전을 다시 설치해 프로그램 파일을 모두 처음 그대로 되돌립니다. 서버와 로그인 정보, 설정은 그대로 둡니다."),
    "setup.opt.uninstall": ("Uninstall", "제거"),
    "setup.opt.uninstall.line": ("Removes OpenDMTQ from this PC. You choose next whether your data stays.",
                                 "이 PC에서 OpenDMTQ를 제거합니다. 데이터를 남길지는 다음 화면에서 고릅니다."),
    "setup.next": ("Next", "다음"),
    "setup.previous": ("Back", "뒤로"),
    # The uninstall's choice: the data kept or deleted, each with its size.
    "setup.card.data": ("Your data on this PC", "이 PC의 데이터"),
    "setup.data.keep": ("Keep my data", "데이터 남기기"),
    "setup.data.keep.line": ("The settings and sign-ins ({settings}) and the game data ({game}) stay in {folder} for a later install.",
                             "설정과 로그인 정보({settings}), 게임 데이터({game})를 {folder}에 남겨 두고 다음 설치 때 그대로 씁니다."),
    "setup.data.all": ("Delete everything", "모두 삭제"),
    "setup.data.all.line": ("Deletes the settings, sign-ins and game data too ({total}), with the id this PC plays by: a later install starts as a new player.",
                            "설정과 로그인 정보, 게임 데이터({total})를 이 PC의 기기 ID와 함께 지웁니다. 다음에 설치하면 새 플레이어로 시작합니다."),
    "setup.data.counting": ("Counting the data on this PC...", "이 PC의 데이터 크기를 확인하는 중..."),
    "setup.data.none": ("There is no OpenDMTQ data on this PC: only the program is removed.",
                        "이 PC에 OpenDMTQ 데이터가 없어 프로그램만 지웁니다."),
    "setup.do.uninstall": ("Uninstall", "제거"),
    # The work under way: its steps.
    "setup.stage.ready": ("Getting ready", "준비"),
    "setup.stage.copy": ("Copying the program", "프로그램 복사"),
    "setup.stage.shortcuts": ("Making the shortcuts", "바로 가기 만들기"),
    "setup.stage.finish": ("Finishing", "마무리"),
    "setup.stage.remove": ("Removing the program, its shortcuts and its Apps entry", "프로그램과 바로 가기, 앱 목록 항목 지우기"),
    "setup.stage.data": ("Deleting the data on this PC", "이 PC의 데이터 지우기"),
    "setup.stage.logs": ("Clearing OpenDMTQ's logs", "OpenDMTQ 로그 지우기"),
    "setup.working.stay": ("This takes a few seconds.", "몇 초면 끝납니다."),
    # What came of it.
    "setup.done.program": ("The program is in {folder}.", "프로그램은 {folder}에 있습니다."),
    "setup.done.shortcuts": ("Its shortcuts are on the desktop and in the Start menu.", "바로 가기는 바탕 화면과 시작 메뉴에 있습니다."),
    "setup.done.server": ("It plays on {name} from its first start.", "처음 열 때부터 {name}에서 플레이합니다."),
    "setup.done.repaired": ("OpenDMTQ {v} is repaired: every file of the program is as it came.",
                            "OpenDMTQ {v} 버전을 복구해 프로그램 파일을 모두 처음 그대로 되돌렸습니다."),
    "setup.done.updated": ("OpenDMTQ is updated to {v}.", "OpenDMTQ를 {v} 버전으로 업데이트했습니다."),
    "setup.done.stayed": ("Your servers, sign-ins and settings stayed as they were.", "서버와 로그인 정보, 설정은 그대로입니다."),
    "setup.done.deleted": ("Deleted too: the settings, sign-ins and game data ({size}). Your records stay on the server.",
                           "설정과 로그인 정보, 게임 데이터({size})도 지웠습니다. 기록은 서버에 그대로 남습니다."),
    "setup.done.left": ("In use and left in place: {n}, in {folder}.", "사용 중이라 지우지 못한 항목 {n}개가 {folder}에 남았습니다."),
    # What stopped it.
    "setup.failed.update": ("OpenDMTQ could not be updated.", "OpenDMTQ를 업데이트하지 못했습니다."),
    "setup.failed.repair": ("OpenDMTQ could not be repaired.", "OpenDMTQ를 복구하지 못했습니다."),
    "setup.failed.uninstall": ("OpenDMTQ could not be uninstalled.", "OpenDMTQ를 제거하지 못했습니다."),
    "setup.failed.start_uninstaller": ("The uninstaller did not start: {error}", "제거 프로그램이 시작되지 않았습니다: {error}"),
    "setup.failed.uninstaller": ("The uninstaller ended with {code}.", "제거 프로그램이 {code} 코드로 끝났습니다."),
    "setup.failed.program_stayed": ("The program is still in {folder}.", "프로그램이 아직 {folder}에 있습니다."),
    "setup.not_installed": ("There is no OpenDMTQ installed in {folder}.", "{folder}에 설치된 OpenDMTQ가 없습니다."),
    "setup.notice.game": ("The game is open: repairing, updating and uninstalling wait until it closes.",
                          "게임이 열려 있습니다. 복구, 업데이트, 제거는 게임을 닫은 뒤에 진행됩니다."),
    "setup.waiting": ("Waiting for the game to close...", "게임이 닫히기를 기다리는 중..."),
    "setup.game.install": ("Installing replaces the game program: it waits until the game is closed.",
                           "설치하면 게임 프로그램이 바뀌므로 게임이 닫힐 때까지 기다립니다."),
    "setup.game.update": ("Updating replaces the game program: it waits until the game is closed.",
                          "업데이트하면 게임 프로그램이 바뀌므로 게임이 닫힐 때까지 기다립니다."),
    "setup.game.repair": ("Repairing puts back the game program's files: it waits until the game is closed.",
                          "복구하면 게임 프로그램 파일을 되돌리므로 게임이 닫힐 때까지 기다립니다."),
    "setup.game.uninstall": ("Uninstalling removes the game program: it waits until the game is closed.",
                             "제거하면 게임 프로그램도 지워지므로 게임이 닫힐 때까지 기다립니다."),

    # ------------------------------------------------------------------------- the launcher cannot start
    "start.title": ("Cannot start", "시작할 수 없음"),
    "start.newer": ("These settings are from a newer OpenDMTQ.", "더 새로운 OpenDMTQ에서 저장한 설정입니다."),
    "start.newer.detail": ("Install the newer launcher again to go on.\n{path}",
                           "계속하려면 새 버전 런처를 다시 설치하세요.\n{path}"),
    "start.broken": ("The launcher's settings cannot be read.", "런처 설정을 읽을 수 없습니다."),
    "start.broken.detail": ("Start over keeps the file under another name and opens the first-start guide.\n{path}",
                            "'처음부터'를 누르면 이 파일을 다른 이름으로 남겨 두고 처음 시작 안내를 엽니다.\n{path}"),
    "start.close": ("Close", "닫기"),
    "stopped.title": ("OpenDMTQ stopped", "OpenDMTQ가 멈춤"),
    "stopped.message": ("OpenDMTQ stopped because of an error.", "오류로 OpenDMTQ가 멈췄습니다."),
    "stopped.logs": ("Open the log folder", "로그 폴더 열기"),
    "stopped.detail": ("{error}\n\nWhat happened is in the log: {path}", "{error}\n\n자세한 내용은 로그에 있습니다: {path}"),
    "failed.message": ("Something went wrong.", "문제가 생겼습니다."),
    "failed.detail": ("{error}\n\nThe launcher goes on. What happened is in its log: {path}",
                      "{error}\n\n런처는 계속 쓸 수 있습니다. 자세한 내용은 로그에 있습니다: {path}"),
    "start.over": ("Start over", "처음부터"),

    # ------------------------------------------------------------------------------------------- errors
    # Why another program's work failed, by its kind (errors.fault), after the words that say what failed; anything
    # else says no more, its own words in the log.
    "fault.network": ("This PC cannot reach the internet.", "이 PC에서 인터넷에 연결할 수 없습니다."),
    "fault.no_answer": ("The update server did not answer.", "업데이트 서버가 응답하지 않았습니다."),
    "fault.disk_full": ("There is not enough space on the disk.", "디스크 공간이 부족합니다."),
    "fault.in_use": ("A file is in use by another program.", "다른 프로그램이 사용 중인 파일이 있습니다."),
    "fault.denied": ("Windows refused access to a file.", "Windows가 파일 접근을 거부했습니다."),
    "error.choice": ("{name} cannot be {value}", "{name}: 쓸 수 없는 값입니다({value})."),
    "error.fps": ("fps is auto, unlimited or a number from {least} to {most}, not {value}.",
                  "fps에는 auto, unlimited, {least}~{most} 사이의 숫자만 쓸 수 있습니다: {value}"),
    "error.number": ("{name} is a number from {least} to {most}, not {value}.",
                     "{name}에는 {least}~{most} 사이의 숫자만 쓸 수 있습니다: {value}"),
    "error.no_setting": ("there is no setting {name}", "없는 설정입니다: {name}"),
    "error.keys.lanes": ("{mode} has {n} lanes from the top, separated by spaces, each one key or two joined by /.",
                         "{mode}에는 위에서부터 줄이 {n}개 있습니다. 줄은 띄어 쓰고, 줄마다 키 하나나 /로 이은 키 둘을 씁니다."),
    "error.keys.lane": ("Lane {lane} has one key, or two joined by /.", "{lane}번 줄에는 키 하나나 /로 이은 키 둘을 씁니다."),
    "error.keys.name": ("{keyname} is no key a lane takes: A to Z, 0 to 9, Space, Semicolon, Quote, Comma, Period, Slash, "
                        "LeftBracket, RightBracket, Backslash, Minus, Equals or Grave.",
                        "{keyname}: 줄에 쓸 수 없는 키입니다. A~Z, 0~9, Space, Semicolon, Quote, Comma, Period, Slash, "
                        "LeftBracket, RightBracket, Backslash, Minus, Equals, Grave 중에서 씁니다."),
    "error.keys.twice": ("{keyname} is in lane {first} and lane {second}: a key plays one lane.",
                         "{keyname} 키가 {first}번 줄과 {second}번 줄에 있습니다. 키 하나는 한 줄만 칩니다."),
    "error.keys.twice_in_lane": ("{keyname} is in lane {lane} twice.", "{keyname} 키가 {lane}번 줄에 두 번 있습니다."),
    "error.keys.taken": ("{keyname} already plays lane {lane} of {mode}.", "{keyname} 키는 이미 {mode} {lane}번 줄을 칩니다."),
    "error.keys.one": ("Lane {lane} of {mode} keeps one key at least: another key pressed takes its place.",
                       "{mode} {lane}번 줄에는 키가 하나는 있어야 합니다. 다른 키를 누르면 그 키로 바뀝니다."),
    "error.window.too_big": ("{size} does not fit this {w} × {h} display with the window's title bar and the taskbar.",
                             "제목 표시줄과 작업 표시줄을 포함하면 이 모니터({w} × {h})에 들어가지 않는 크기입니다: {size}"),
    "error.window.too_small": ("{size} is smaller than the game's window can be on this display ({least}).",
                               "이 모니터에서 게임 창이 될 수 있는 가장 작은 크기({least})보다 작습니다: {size}"),
    "error.server.empty": ("Type the server's address.", "서버 주소를 입력하세요."),
    "error.server.address": ("{address} is not an address.", "주소로 읽을 수 없습니다: {address}"),
    "error.server.unreachable": ("Cannot reach {base}.", "{base}에 연결할 수 없습니다."),
    "error.server.refused": ("{base} refused the connection.", "연결을 거부했습니다: {base}"),
    "error.server.unknown_host": ("Cannot find {base}.", "주소를 찾을 수 없습니다: {base}"),
    "error.server.timeout": ("{base} does not answer.", "{base}에서 응답이 없습니다."),
    "error.server.not_opendmtq": ("{base} is not an OpenDMTQ server for PCs.", "PC용 OpenDMTQ 서버가 아닙니다: {base}"),
    "error.server.too_old": ("{base} runs an older OpenDMTQ without the PC client's part: its owner can update it to 0.8 or newer.",
                             "{base}의 OpenDMTQ는 PC 클라이언트를 지원하지 않는 이전 버전입니다. 서버 소유자가 0.8 이상으로 업데이트하면 연결할 수 있습니다."),
    "error.server.answered": ("The server answered {status}.", "서버 응답: {status}"),
    "error.server.none": ("Connect to a server first.", "먼저 서버에 연결하세요."),
    "error.signin.no_id": ("Type your ID.", "아이디를 입력하세요."),
    "error.signin.no_password": ("Type your password.", "비밀번호를 입력하세요."),
    "error.signin.wrong": ("The ID or the password is wrong.", "아이디나 비밀번호가 맞지 않습니다."),
    "error.signin.banned": ("This account cannot sign in: {reason}", "이 계정은 로그인할 수 없습니다: {reason}"),
    "error.signin.banned_until": ("This account cannot sign in until {when}: {reason}",
                                  "이 계정은 {when}까지 로그인할 수 없습니다: {reason}"),
    "error.signin.off": ("This account is disabled and cannot sign in.", "이 계정은 비활성화되어 로그인할 수 없습니다."),
    "error.signin.throttled": ("Too many tries: wait a minute and try again.", "시도가 너무 많습니다. 1분 뒤에 다시 해 보세요."),
    "error.signin.down": ("The server cannot sign anyone in right now.", "서버가 지금 로그인을 받지 못합니다."),
    "error.signin.ended": ("Your sign-in ended (it ran out, or the password changed). Sign in again.",
                           "로그인이 만료되었습니다(기간이 지났거나 비밀번호가 바뀌었습니다). 다시 로그인하세요."),
    "error.signin.needed": ("Sign in to the server first.", "먼저 서버에 로그인하세요."),
    "error.link.none": ("This server makes no sign-in links for the site (it is older than 0.11).",
                        "이 서버는 사이트 로그인 링크를 만들지 않습니다(0.11보다 오래된 버전입니다)."),
    "error.app.none": ("The server is building its app (about 20 seconds). Try again in a moment.",
                       "서버가 앱을 만드는 중입니다(약 20초). 잠시 뒤 다시 해 보세요."),
    "error.app.stale": ("The server's address changed, so it is building its app again. Try again in a moment.",
                        "주소가 바뀌어 서버가 앱을 다시 만드는 중입니다. 잠시 뒤 다시 해 보세요."),
    "error.app.failed": ("The server could not build its app.", "서버가 앱을 만들지 못했습니다."),
    "error.app.not_sent": ("The server sent no app. Sign in again, or try again later.", "서버가 앱을 보내지 않았습니다. 다시 로그인하거나 나중에 해 보세요."),
    "error.app.damaged": ("The app arrived damaged. Try again.", "앱이 손상된 채로 왔습니다. 다시 해 보세요."),
    "error.app.named": ("The server offered an app without a proper name.", "서버가 이름이 올바르지 않은 앱을 내놓았습니다."),
    "error.app.package": ("The app on this PC has no proper package name, so the game does not start. Get the app again on the ONLINE page.",
                          "이 PC의 앱에 올바른 패키지 이름이 없어 게임을 시작하지 않습니다. ONLINE 페이지에서 앱을 다시 다운로드하세요."),
    "error.repair.not_installed": ("Repair works in the launcher the installer put on this PC.",
                                   "복구는 설치 프로그램으로 설치한 런처에서 됩니다."),
    "error.update.unsigned": ("The update to {v} from {source} is not signed by the OpenDMTQ project, so it was not installed.",
                              "{source}의 {v} 업데이트는 OpenDMTQ 프로젝트가 서명한 것이 아니어서 설치하지 않았습니다."),
    "error.update.download": ("The update to {v} could not be downloaded.", "{v} 업데이트를 다운로드하지 못했습니다."),
    "error.repair.no_package": ("The installed package is not on this PC. Run the installer again and choose Repair.",
                                "설치된 패키지가 이 PC에 없습니다. 설치 프로그램을 다시 실행해 복구를 고르세요."),
    "error.repair.package": ("The installed package cannot be read. Run the installer again and choose Repair.",
                             "설치된 패키지를 읽을 수 없습니다. 설치 프로그램을 다시 실행해 복구를 고르세요."),
    "error.uninstall.not_installed": ("Uninstalling works in the launcher the installer put on this PC.",
                                      "제거는 설치 프로그램으로 설치한 런처에서 됩니다."),
}


class Said:
    """Words to show now and again later, in whatever language the window speaks then: a key of TEXT and its gaps. The
    window keeps what it said this way (the status line, a page's last answer), so that a switch of language says it
    again in the new one instead of keeping the old one's sentence. A gap that is words itself (another Said, or an
    error, which Words.error says) is said in that language too; anything else (an address, a number) goes in as it
    is."""

    def __init__(self, key, **params):
        # The key of the words, and the values of their gaps.
        self.key, self.params = key, params

    def __call__(self, words):
        """The words in `words`' language, each gap that is words itself said in it too."""
        filled = {}
        for name, value in self.params.items():
            if isinstance(value, Said):
                # Words inside words: a span of time, a reason.
                filled[name] = value(words)
            elif isinstance(value, BaseException):
                # An error: its own words in this language when it has them (Words.error).
                filled[name] = words.error(value)
            else:
                filled[name] = value
        return words(self.key, **filled)

    def __repr__(self):
        return "Said(%r, %r)" % (self.key, self.params)


def ago(at, now=None):
    """How long ago a moment (Unix time) was, as words to say later, as the site says it: just now, minutes, hours, days,
    months."""
    import time
    gone = int((now or time.time()) - at)
    for unit, key in ((86400 * 30, "ago.mo"), (86400, "ago.d"), (3600, "ago.h"), (60, "ago.min")):
        if gone >= unit:
            return Said(key, n=gone // unit)
    return Said("ago.now")


def span(seconds):
    """How long something lasted, as words to say later: whole minutes, or seconds under one."""
    minutes = int(seconds) // 60
    return Said("common.minutes", m=minutes) if minutes else Said("common.seconds", s=int(seconds))


class Text(str):
    """Words looked up by their key with nothing filled in (a setting's name, a card's title): a str that keeps the key
    it came from, so that what is laid out for every language finds that entry's words, and none of another entry that
    happens to share them in one language (every_language)."""

    def __new__(cls, text, key):
        made = super().__new__(cls, text)
        made.key = key
        return made


class Words:
    """Looks words up in the chosen language; a missing Korean entry falls back to English. A key with no words shows as
    itself, except in a test run or the UI tests' container, where it is an error: the tests reach every page, dialog
    and step, and a word left out would otherwise go unseen until a player sees the raw key. Words with nothing filled
    in keep their key (Text)."""

    def __init__(self, language="en"):
        self.language = language

    def __call__(self, key, **kw):
        if key not in TEXT and (safety.testing() or safety.on_virtual_display()):
            raise KeyError("no words for %r" % key)
        en, ko = TEXT.get(key, (key, key))
        text = ko if self.language == "ko" and ko else en
        # Filled in, the words are the entry's no more; as they are, they keep the key they came from.
        return text.format(**kw) if kw else Text(text, key)

    def say(self, message):
        """A message kept to show (a Said, said in this language now), or plain text as it is; "" for none."""
        if message is None:
            return ""
        # A Said is said in this language; anything else is text already (a test's own words, a path).
        return message(self) if isinstance(message, Said) else str(message)

    def error(self, error):
        """What a raised error says, in this language: its words when it has them, else its own sentence."""
        key = getattr(error, "key", None)
        if isinstance(error, Worded) and key in TEXT or (key in TEXT and hasattr(error, "params")):
            try:
                return self(key, **error.params)
            except (KeyError, IndexError):
                # Words that name a gap the error does not fill: its own sentence instead.
                pass
        if isinstance(error, OSError) and error.strerror:
            # The system's reason and the file it is about, as written: not Python's "[Errno 28] ..." with each
            # backslash doubled.
            return "%s: %s" % (error.strerror, error.filename) if error.filename else error.strerror
        return str(error)

    def fault(self, failure, network=True):
        """Why another program's work failed (Velopack's, the system's), in plain words of this language by its kind
        (errors.fault): one sentence, or "" for anything else, whose own words stay in the log. `network` False for
        work that asks nothing over the network."""
        kind = errors.fault(failure, network)
        return self("fault." + kind) if kind else ""

    def failed(self, key, failure, network=True, **kw):
        """What failed (the words of `key`) and, when its kind is known, why (fault), as one or two sentences."""
        return sentences(self(key, **kw), self.fault(failure, network))


def every_language(text):
    """A text in every language the launcher speaks (a setting's name, shown in one language while the page keeps room
    for both): its own entry's words when it was looked up by its key (Text), else the words of each entry whose English
    or Korean words are `text`, or the text alone when none is. By its key, a name never takes the room of another
    entry's words that share its words in one language (Online's 서버 주소 took the report's "the servers' addresses",
    and Korean forms were laid out wider than English ones)."""
    key = getattr(text, "key", None)
    if key in TEXT:
        return sorted({words for words in TEXT[key] if words})
    found = {text}
    for en, ko in TEXT.values():
        if text in (en, ko):
            # A Korean entry left empty falls back to the English words (Words): only the words a page can show.
            found.update(words for words in (en, ko) if words)
    return sorted(found)


def sentences(*parts):
    """Sentences joined by a space, the empty ones left out."""
    return " ".join(p for p in parts if p)


def mb(size):
    """A size in bytes as megabytes with one decimal, as a download's progress says it ('103.2'). The words around it
    name the unit, each language in its own place (status.downloading), and so does the command line's own line."""
    return "%.1f" % (size / 1048576.0)
