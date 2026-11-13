// Keyboard play: a song's lanes played with the computer's keys, a key (or two) a lane, each press at the place the game
// judges (keyplay.cpp says how; keyboard_play.h has the rules it follows). The window gives it the keys by their places
// on the keyboard; the game's own code turns its presses into judgements, as it does a touch screen's fingers.
#pragma once

#include "thread.h"

#include <string>
#include <utility>
#include <vector>

namespace player {

// A library of the game's came in (main.cpp's load_library): libil2cpp.so is the one keyboard play reaches the game by.
void keyplay_library_loaded(const std::string& name, arm32::gaddr handle);
// On Unity's main thread before each native render call (the runtime's render hook, tweaks.h): puts the hook in its
// place once the game's classes are there, or says once why it stays out.
void keyplay_render(arm32::Thread& th);

// A key of the computer's keyboard came down or went up, by its place (the scan code Windows gives, and its extended
// flag), on the window's thread; `repeat` when Windows says it was down already. True when it is a lane's key while a
// song is being played (it is the lane's then, never the game's), or a lane's key coming up that was down.
bool keyplay_key(unsigned scan, bool extended, bool down, bool repeat);
// Every lane key lets go at once, for `why` (the log says it when a key was down): the window lost the keyboard, was
// minimised, the question before quitting came, the game asked for text. From any thread.
void keyplay_let_go(const char* why);
// The game held still (the question is up, or the window is minimised) or going on: no lane key plays while it is held.
void keyplay_hold(bool held);
// Whether a lane key is down: the game is being played (the overlay's bar waits, as for a finger on the game).
bool keyplay_any_down();

// A check's key at a song's time (PLAYER_KEYS "@song+seconds:..."): a key's place going down or up when the song's own
// clock reaches `ms`, in each song played, sent to the window as Windows sends a key.
struct SongKey {
    double ms;
    unsigned scan;
    bool down;
};
void keyplay_song_keys(std::vector<SongKey> keys);

// A request of the game's about to go to its server (web.cpp): when it saves a play (game.savePlayResult) whose lanes a
// lane key pressed, the header that marks a keyboard play goes with it (X-OpenDMTQ-Keys: 1). Said in the log.
void keyplay_mark_save(const std::string& method, const std::string& body, std::vector<std::pair<std::string, std::string>>& headers);

// The window's side, which keyplay.cpp calls (window_win32.cpp; on Linux, keyplay.cpp's own): a check's key sent to the
// window as Windows sends one, from any thread; and, on the window's thread, the lane keys let go (the overlay hears that
// nothing is down on the game any more, as at a finger's lift).
void keyplay_post_key(unsigned scan, bool down);
void keyplay_released();

}  // namespace player
