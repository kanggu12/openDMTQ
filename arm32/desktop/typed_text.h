// The text the computer's keyboard types into the game's soft keyboard (input.cpp), as plain rules apart from the game
// and the windows, so that a check (settingstest.cpp) can take it through them. The text the game opens the keyboard
// with is taken as a desktop field has its text when it opens, all of it selected: the first character typed, or the
// first syllable an input method composes, takes its place; Backspace or Delete takes it away whole; an arrow, Home or
// End leaves it as it is, no longer selected. Past that the caret is at the text's end, where this keyboard types:
// characters are added there, Backspace takes back the last one, Delete has nothing after it to take. What an input
// method is still composing shows after the text, as a phone's text field holds it.
#pragma once

#include <string>

namespace player {

struct TypedText {
    // The text so far, and what an input method still composes after it.
    std::string text, composing;
    // Whether the text is still the one the game opened with, all of it selected: nothing typed, taken back or moved
    // over since.
    bool selected = false;

    // The keyboard opened with the game's own text, selected whole (an empty text has nothing to select).
    void open(const std::string& with) {
        text = with;
        composing.clear();
        selected = !text.empty();
    }
    // What the game is told the field holds now.
    std::string shown() const { return text + composing; }

    // Characters typed (UTF-8): over the selected text, in its place; else at the end.
    void type(const std::string& utf8) {
        if (selected) text.clear();
        selected = false;
        text += utf8;
    }
    // What an input method composes now ("" when nothing); whether that changed what the game is told. Its first
    // syllable takes the selected text's place, as a typed character does.
    bool compose(const std::string& utf8) {
        if (composing == utf8) return false;
        if (selected && !utf8.empty()) {
            text.clear();
            selected = false;
        }
        composing = utf8;
        return true;
    }
    // Backspace (`back`) or Delete; whether the text changed. Over the selected text, either takes it away whole;
    // else Backspace takes back the last character, whatever its UTF-8 length, and Delete at the end takes nothing.
    bool erase(bool back) {
        if (selected) {
            text.clear();
            selected = false;
            return true;
        }
        if (!back || text.empty()) return false;
        std::size_t cut = text.size() - 1;
        // Back over a character's continuation bytes to its first byte.
        while (cut > 0 && (static_cast<unsigned char>(text[cut]) & 0xc0) == 0x80) --cut;
        text.erase(cut);
        return true;
    }
    // An arrow, Home or End: the text stays as it is, no longer selected (the caret at its end, where typing adds).
    void move() { selected = false; }
};

}  // namespace player
