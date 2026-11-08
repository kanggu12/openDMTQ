// The computer's own decoders, behind android.media.MediaCodec (media.cpp): FFmpeg's libavcodec on Linux, loaded when
// a video first plays rather than linked (a computer without it plays no video), and Media Foundation on Windows. They
// take access units as Android's extractor gives them (H.264's NAL units after start codes, AAC's raw frames) and give
// what a phone's decoder would: pictures in display order, here as RGBA, and sound as 16-bit samples.
#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace player::media {

// What a decoder gives: a picture (video) or a run of sound (audio).
struct Frame {
    // RGBA, rows from the top.
    int width = 0, height = 0;
    std::vector<std::uint8_t> rgba;
    // 16-bit samples, the channels interleaved, as Android's AAC decoder gives them.
    int rate = 0, channels = 0;
    std::vector<std::int16_t> pcm;
};

class Decoder {
public:
    virtual ~Decoder() = default;
    // One access unit (or H.264's parameter sets alone); false when the decoder failed.
    virtual bool send(const std::uint8_t* data, std::size_t size) = 0;
    // The end of the stream: what the decoder still holds comes out.
    virtual bool drain() = 0;
    // The next frame when one is ready, in display order.
    virtual bool receive(Frame& out) = 0;
    // A seek: what the decoder holds goes, and it starts again at the next key frame.
    virtual void flush() = 0;
};

// The computer's H.264 decoder, or null with `error` set.
std::unique_ptr<Decoder> open_h264(std::string& error);
// Its AAC decoder for the stream `config` describes (the AudioSpecificConfig of the track's csd-0), or null.
std::unique_ptr<Decoder> open_aac(const std::vector<std::uint8_t>& config, std::string& error);
// What stands in for a decoder the computer lacks or that refuses the stream: a black picture of `width` x `height`
// for every unit, or as much silence as an AAC frame holds (1024 samples) at `rate` and `channels`. A video then plays
// its time out without a picture or a sound, and the game, which waits for its end, goes on.
std::unique_ptr<Decoder> open_blank(bool audio, int width, int height, int rate, int channels);

// YUV 4:2:0 planes into RGBA: BT.709 for pictures 720 rows high or more, BT.601 below (what a phone takes for a stream
// that does not say), the video range unless `full` (the JPEG range a decoder may report). `u` and `v` may be one
// interleaved plane (NV12), with `chroma_step` 2.
void yuv420_to_rgba(const std::uint8_t* y, int y_stride, const std::uint8_t* u, const std::uint8_t* v, int uv_stride, int chroma_step, int width,
                    int height, bool full, std::uint8_t* out);

}  // namespace player::media
