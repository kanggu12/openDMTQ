// A small MPEG transport stream writer for live segments: H.264 and AAC (see live_ts.cpp).
#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace arm32 {

class TsWriter {
public:
    // Starts a new segment: the bytes so far are the caller's to take, the next ones begin with the
    // stream's tables. Continuity counters run on, as one stream cut in pieces.
    void begin_segment();
    // One H.264 access unit in Annex B form at `pts` (90 kHz). `key` marks a frame a player can start
    // on: it gets the clock reference's random access flag.
    void video(const std::uint8_t* data, std::size_t size, std::uint64_t pts, bool key);
    // One AAC frame with its ADTS header at `pts` (90 kHz).
    void audio(const std::uint8_t* data, std::size_t size, std::uint64_t pts);
    // The segment so far.
    std::vector<std::uint8_t>& bytes() { return out_; }

private:
    void section(std::uint16_t pid, std::uint8_t* counter, const std::uint8_t* body, std::size_t size);
    void pes(std::uint16_t pid, std::uint8_t* counter, std::uint8_t stream_id, const std::uint8_t* data, std::size_t size,
             std::uint64_t pts, bool with_pcr, bool key);

    std::vector<std::uint8_t> out_;
    std::uint8_t pat_counter_ = 0, pmt_counter_ = 0, video_counter_ = 0, audio_counter_ = 0;
};

// The ADTS header of an AAC-LC frame of `payload` bytes. False for a rate ADTS has no index for.
bool adts_header(std::uint8_t out[7], int sample_rate, int channels, std::size_t payload);

}  // namespace arm32
