// What the decoders of every computer share (decoder.h): the conversion of their YUV pictures to RGBA, and the blank
// decoder that stands in for a missing one.
#include "decoder.h"

namespace player::media {

void yuv420_to_rgba(const std::uint8_t* y, int y_stride, const std::uint8_t* u, const std::uint8_t* v, int uv_stride, int chroma_step, int width,
                    int height, bool full, std::uint8_t* out) {
    // The matrices, times 1024: the luma's scale and offset, red from V, green from U and V, blue from U.
    int ky, y0, rv, gu, gv, bu;
    if (full) {
        // The JPEG range (BT.601, nothing reserved).
        ky = 1024, y0 = 0, rv = 1436, gu = 352, gv = 731, bu = 1815;
    } else if (height >= 720) {
        // BT.709, video range.
        ky = 1192, y0 = 16, rv = 1836, gu = 218, gv = 546, bu = 2163;
    } else {
        // BT.601, video range.
        ky = 1192, y0 = 16, rv = 1634, gu = 401, gv = 833, bu = 2065;
    }
    auto clamp = [](int x) { return static_cast<std::uint8_t>(x < 0 ? 0 : x > 255 ? 255 : x); };
    for (int row = 0; row < height; ++row) {
        const std::uint8_t* yr = y + static_cast<std::ptrdiff_t>(row) * y_stride;
        // One chroma row for two luma rows, one chroma sample for two luma samples.
        const std::uint8_t* ur = u + static_cast<std::ptrdiff_t>(row / 2) * uv_stride;
        const std::uint8_t* vr = v + static_cast<std::ptrdiff_t>(row / 2) * uv_stride;
        std::uint8_t* o = out + static_cast<std::ptrdiff_t>(row) * width * 4;
        for (int x = 0; x < width; ++x) {
            int l = (yr[x] - y0) * ky;
            int cb = ur[(x / 2) * chroma_step] - 128, cr = vr[(x / 2) * chroma_step] - 128;
            o[4 * x] = clamp((l + rv * cr + 512) >> 10);
            o[4 * x + 1] = clamp((l - gu * cb - gv * cr + 512) >> 10);
            o[4 * x + 2] = clamp((l + bu * cb + 512) >> 10);
            o[4 * x + 3] = 255;
        }
    }
}

namespace {

// One output per unit sent: a decoder gives a picture for every access unit (and a run of sound for every AAC frame),
// and the codec gives each output the earliest time of the units in.
class Blank : public Decoder {
public:
    Blank(bool audio, int width, int height, int rate, int channels) {
        if (audio) {
            frame_.rate = rate;
            frame_.channels = channels;
            frame_.pcm.assign(static_cast<std::size_t>(1024 * channels), 0);
        } else {
            frame_.width = width;
            frame_.height = height;
            // Black, opaque.
            frame_.rgba.assign(static_cast<std::size_t>(width) * static_cast<std::size_t>(height) * 4, 0);
            for (std::size_t i = 3; i < frame_.rgba.size(); i += 4) frame_.rgba[i] = 255;
        }
    }
    bool send(const std::uint8_t*, std::size_t size) override {
        if (size) ++pending_;
        return true;
    }
    bool drain() override { return true; }
    bool receive(Frame& out) override {
        if (!pending_) return false;
        --pending_;
        out = frame_;
        return true;
    }
    void flush() override { pending_ = 0; }

private:
    Frame frame_;
    std::size_t pending_ = 0;
};

}  // namespace

std::unique_ptr<Decoder> open_blank(bool audio, int width, int height, int rate, int channels) {
    return std::make_unique<Blank>(audio, width, height, rate, channels);
}

}  // namespace player::media
