// An MP4 file's tracks and samples, as android.media.MediaExtractor hands them over: each track's format (its MIME
// type, size or rate and channels, duration, largest sample, and its codec's setup in csd-0 and csd-1), and its samples
// in decoding order with their time, flags and bytes. H.264 comes out as Android's extractor gives it: NAL units after
// start codes (00 00 00 01) rather than after their lengths, and the sequence and picture parameter sets in csd-0 and
// csd-1 likewise; AAC's csd-0 is its AudioSpecificConfig. Read from part of a file (an entry stored in an APK).
#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace player::media {

// Where the bytes come from: a file descriptor, from `offset` for `length` bytes.
struct Source {
    int fd = -1;
    std::int64_t offset = 0, length = 0;
};

struct Sample {
    std::int64_t offset = 0;   // in the file, from the source's start
    std::uint32_t size = 0;    // as stored
    std::int64_t time_us = 0;  // presentation time: decoding time, its composition offset, less the edit's start
    std::int64_t decode_us = 0;
    bool sync = false;  // a key frame: decoding may start here
};

struct Track {
    std::string mime;  // "video/avc", "audio/mp4a-latm", or the sample entry's own name for anything else
    int width = 0, height = 0;
    int sample_rate = 0, channels = 0;
    std::int64_t duration_us = 0;
    std::vector<std::uint8_t> csd0, csd1;
    // H.264's NAL lengths: 1, 2 or 4 bytes before each unit (0 for other formats).
    int nal_length = 0;
    std::uint32_t max_sample = 0;
    std::vector<Sample> samples;
};

class Mp4 {
public:
    // Reads the file's tracks; false with `error` set when it is no MP4 this can read.
    bool open(const Source& source, std::string& error);
    const std::vector<Track>& tracks() const { return tracks_; }
    // Sample `k` of track `t` as the extractor gives it, into `out` (resized); false when it cannot be read.
    bool read(std::size_t t, std::size_t k, std::vector<std::uint8_t>& out) const;
    // The largest size a sample of track `t` can have once read (H.264's start codes can be longer than its lengths).
    std::uint32_t max_read_size(std::size_t t) const;

private:
    bool read_at(std::int64_t at, void* buf, std::size_t n) const;
    Source source_;
    std::vector<Track> tracks_;
};

}  // namespace player::media
