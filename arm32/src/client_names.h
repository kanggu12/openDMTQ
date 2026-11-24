// The names the runtime and the player look up in the game's code and define for its SDKs: classes, their namespaces,
// methods, fields, the Unity object the platform's SDK answers and the events it sends, each by its role. The
// repository's text names none of the game's code, its app or its platform (the project's rule for its pages, comments,
// tests and names), so each name is kept here encoded and read where it is used: client_names::text(kInputClass). The
// encoding: each byte XORed with 0x5c plus the byte's place (mod 256), as two hex digits.
//
// Written by tools/opendmtq_tools/client_marks.py, from the table the patcher reads the client's names from (in tools/:
// python3 -m opendmtq_tools.client_marks --cpp > ../arm32/src/client_names.h); cli/tests/test_repo.py checks that this
// file is what the table makes.
#pragma once

#include <cstddef>
#include <string>

namespace client_names {

// A name as its text: each pair of hex digits one byte, XORed back with the key at its place.
inline std::string text(const char* hex) {
    // One hex digit's value (the header writes them in lower case).
    auto digit = [](char c) { return c <= '9' ? c - '0' : c - 'a' + 10; };
    std::string out;
    for (std::size_t i = 0; hex[i] != '\0' && hex[i + 1] != '\0'; i += 2) {
        // The byte as written, and the key at the byte's place.
        const int byte = digit(hex[i]) << 4 | digit(hex[i + 1]);
        const int key = (0x5c + static_cast<int>(i / 2)) & 0xff;
        out.push_back(static_cast<char>(byte ^ key));
    }
    return out;
}

// ---- The game's code: its score, input, notes and sounds (keyboard play and the sound's mix)
// The namespace of the score player, the input's base class and the notes.
constexpr const char kScoreNamespace[] = "1817131e383527202c2b2f2c29";
// The game's input class (in no namespace), whose virtual table keyboard play takes four slots of.
constexpr const char kInputClass[] = "18100f160e111717";
// The input's base class, whose method takes a press.
constexpr const char kInputBaseClass[] = "18100a160e11171726041502";
// The score player, which plays a song's chart and judges the presses against its notes.
constexpr const char kScorePlayerClass[] = "18100a0c030e10063409071e0d1b";
// A note of a chart.
constexpr const char kNoteClass[] = "18100a0c030e1006211303091c";
// The namespace of the score's clock.
constexpr const char kTimerNamespace[] = "0f3e312d05310e021d0014492a08190e423907021503";
// The score's clock of ticks to milliseconds.
constexpr const char kTimeSectionClass[] = "0f3e312d05350b0e013603041c000505";
// The sounds the score plays (in no namespace).
constexpr const char kSoundClass[] = "18100a0a0e08161a370a13090c";
// The input's method at each play's start (a retry too).
constexpr const char kReset[] = "13330c3a130416";
// The input's method once a frame while a song plays, and the score player's own.
constexpr const char kUpdate[] = "13330b2f04001606";
// The input's method when a song is paused.
constexpr const char kPause[] = "0c3c2b2c05";
// The input's method when a song stops.
constexpr const char kStop[] = "0f29312f";
// The input base's method that takes a press with its place.
constexpr const char kSetPress[] = "0f382a0f12041110";
// The score player's method that gives the place of a track at a tick.
constexpr const char kTickToPlace[] = "08343d34340e3006050936081b001e020303";
// The score player's method that gives a drag's point on its curve.
constexpr const char kDragPlace[] = "1b382a1b1200052d0b1103241d1b1c0e3c021d";
// The clock's method that gives a tick's time in milliseconds.
constexpr const char kTickToTime[] = "1f3c323c34080108300a320e050c";
// The sound class's method that plays a sound of the score.
constexpr const char kPlay[] = "0c313f26";
// The score player's field: the song's tick.
constexpr const char kFieldTick[] = "601e2b2d340801085a0e39382a0809000503092919141e17";
// The score player's field: the song's time as the game judges by, its calibration in it.
constexpr const char kFieldJudgedTime[] = "601e2b2d23000e0a06170713010604261f390702154f192c2b3717141310141c3a141b13e4";
// The score player's field: its state (playing, paused, stopped, closed).
constexpr const char kFieldState[] = "600e2a3e14045c083b3a24060b0203050b2b070a1c15";
// The score player's field: the first of the tracks played.
constexpr const char kFieldTrackStart[] = "600d323e19351002070e3513091b1e25190050042f2e3012171e1f191f3f131e1019";
// The score player's field: the count of the tracks played.
constexpr const char kFieldTrackCount[] = "600d323e19351002070e25091c570134332f0f0c1b181c14321c131b1c";
// The score player's field: its clock.
constexpr const char kFieldTimeSection[] = "6009373205320700100c0909560235342e0c0d04191f15351d101a13";
// The score player's field: whether the song is over before its end.
constexpr const char kFieldGameover[] = "601a3f32050e1406165b0d38372b0b08070400083618171f10";
// The score player's field: whether the song is at its end.
constexpr const char kFieldEnd[] = "6018303b5e0a3d3c2604050c01070d2d0508020b";
// The score player's field: its notes.
constexpr const char kFieldNotes[] = "6013312b052414060a111559033635290d0e05061e16341a111912";
// The score player's field: its tracks.
constexpr const char kFieldTracks[] = "60092c3e030a2b0d020a580c3736280a0f06070117371b161811";
// A note's field: its track.
constexpr const char kNoteTrack[] = "60092c3e030a2b071c5b0d38372b0b08070400083618171f10";
// A note's field: its tick.
constexpr const char kNoteTick[] = "28343d34";
// A note's field: its length in ticks.
constexpr const char kNoteDuration[] = "38282c3e14080d0d";
// A note's field: its judgement, 0 until judged.
constexpr const char kNoteJudgement[] = "60172b3b07040f060a11580c3736280a0f06070117371b161811";
// A note's field: its place.
constexpr const char kNotePlace[] = "600f3b3e0c310d100d110f0806570134332f0f0c1b181c14321c131b1c";
// A note's field: the tick a hold or a drag was taken at, 0 until then.
constexpr const char kNoteStartTick[] = "60172b3b07040f060a113513091b1e3f050e05511b2e2d3115161d1e161e3c1219111a";
// A note's field: its type.
constexpr const char kNoteType[] = "6013312b05351b13015b0d38372b0b08070400083618171f10";
// A note's field: a repeat point's group's first note.
constexpr const char kNoteFirst[] = "601b372d13152c0c1000580c3736280a0f06070117371b161811";
// A track's field: whether the player plays it (else it is the song's background).
constexpr const char kTrackPlayed[] = "60142d0f0c001b371604050c560235342e0c0d04191f15351d101a13";
// A track's field: its volume.
constexpr const char kTrackVolume[] = "600b3133150c075d0f3a3925090a0102020a2806151d16";

// ---- The game's code: its low resolution and its older UI system's screen (the runtime's resolution)
// The namespace of the game's low resolution.
constexpr const char kResolutionNamespace[] = "1d2f3b2c4e34160a080c121e";
// The game's low resolution, which its option turns on.
constexpr const char kLowResolutionClass[] = "1032290d05120d0f11110f0806";
// Its method that turns it on or off.
constexpr const char kLowResolutionApply[] = "1d2d2e3319";
// Its getter of the width it draws at.
constexpr const char kResolutionWidth[] = "3b382a00370806170c";
// Its getter of the height it draws at.
constexpr const char kResolutionHeight[] = "3b382a0028040b040c11";
// The older of the game's two UI systems' screen (in no namespace).
constexpr const char kOldUiScreenClass[] = "121a0b1652320111010008";
// Its method that takes a new size.
constexpr const char kOldUiResize[] = "092d3a3e14043006170a0a121c000505";

// ---- The platform's SDK as the game's C# reaches it (the player stands in for it, the phone's runtime reads it)
// The SDK's class the game's C# calls.
constexpr const char kPlatformFacade[] = "3f323370100c030d03150a121b461f050519175c145e2223321415161c1c";
// The Unity object the SDK's messages go to.
constexpr const char kPlatformObject[] = "0c303f3107310e1617";
// That object's method that takes them.
constexpr const char kPlatformMessage[] = "13331b29050f1651";
// The SDK's call at the game's start.
constexpr const char kPlatformInitialize[] = "3533372b09000e0a1e00";
// The SDK's call with its settings.
constexpr const char kPlatformProperties[] = "2f382a0f120e120616110f021b";
// The SDK's question whether a permission is granted.
constexpr const char kPlatformPermission[] = "343c2d0f05130f0a17160f0806";
// The SDK's call to finish a purchase left unfinished.
constexpr const char kPlatformRetryPurchase[] = "2e382a2d19340c050d0b0f14000c0e3b191f0d07110217";
// The SDK's sign-in with the device's guest account.
constexpr const char kPlatformLogin[] = "303239360e231b240508033704081322082a1b0a03052d373924";
// The SDK's request to the platform's API.
constexpr const char kPlatformRequest[] = "2e382f2a051216";
// The SDK's call for the store's prices in the player's currency.
constexpr const char kPlatformPrices[] = "3b382a0f12080106280a05060400100a18040101";
// The SDK's answer to the call to finish a purchase.
constexpr const char kEventRetryPurchase[] = "33330c3a14131b360a030f09011a020e083d1b1d1319130011";
// The SDK's answer to the sign-in.
constexpr const char kEventLogin[] = "3333123007080c";
// The SDK's answer to a request.
constexpr const char kEventRequest[] = "33330c3a1114071010";
// The SDK's answer when the store's prices cannot be had.
constexpr const char kEventPricesFailed[] = "33330e2d0902072f0b06070b01130b1f0502002911181e";
// The SDK's class with the device's ids in its static fields.
constexpr const char kPlatformDevice[] = "3f323370100c030d03150a121b460e0e1a040d0a5f21223711031f141d";
// The SDK's class with the app's context in a static field.
constexpr const char kPlatformBase[] = "3f323370100c030d03150a121b46080a1f08413f2033130011";
// The device class's field: the device's id.
constexpr const char kDeviceId[] = "2939373b";
// The device class's field: the device's id shared between apps.
constexpr const char kDeviceSharedId[] = "2939373b3f120a021600";
// The base class's field: the app's context.
constexpr const char kBaseContext[] = "3d2d2e1c0f0f16061c11";

// ---- The game's own Java code (the player stands in for it)
// The game's own SDK class.
constexpr const char kGameSdk[] = "3f3233700e040d140d1f4902101d0f19020c021c141a1511185a330f0c1c08151d112d3bcb";
// Its method that reads the clipboard.
constexpr const char kGameSdkClipboard[] = "1b382a1c0c0812010b041403";
// The game's reader of its APK's assets.
constexpr const char kAssetReader[] =
    "3f3233700e040d140d1f0106050c19441c011b08191f015c151b120517101e1a0f0e1b0be1e2e1e6f7f6e9f5a7c8e4effee2e7ebd1e2e1f6"
    "e0d4f5f4fdeae9f4ee";
// Its method that reads an asset whole.
constexpr const char kAssetRead[] = "0e383f3b211211061023140805230b19";
// Its method that says whether an asset is there.
constexpr const char kAssetExists[] = "1f353b3c0b270b0f01201e0e1b1d19210d1f";

}  // namespace client_names
