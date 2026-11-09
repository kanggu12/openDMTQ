// The colours of a computer's broadcast in its H.264 stream (see live_sps.cpp): Windows' H.264 encoder leaves them out
// of its sequence header, and a player then guesses (BT.601 or BT.709 by its own rule), which shifts the game's greens
// and reds. They go into the header's video signal description here: BT.709 primaries, transfer and matrix, in the
// limited range video uses, as the player's conversion makes them (desktop/live_desktop.cpp).
#pragma once

#include <cstdint>
#include <vector>

namespace arm32 {

// An access unit (Annex B: start codes before NAL units) with each sequence parameter set in it given the colours; the
// same bytes for one without, and for an SPS that cannot be read here (a scaling matrix).
std::vector<std::uint8_t> with_colours(const std::vector<std::uint8_t>& unit);

}  // namespace arm32
