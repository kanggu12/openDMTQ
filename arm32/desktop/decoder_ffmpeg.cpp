// The decoders on Linux: FFmpeg's H.264 and AAC decoders, from the libavcodec the computer has (FFmpeg 4 to 8), loaded
// on first use. Only FFmpeg's functions and the first fields of its frame and packet are used, which have stayed where
// they are through those versions, so that one player runs with any of them. AAC goes in with an ADTS header on each
// frame, which carries what the stream's setup says: no codec field has to be set.
#include "decoder.h"

#include "jvm.h"

#include <algorithm>
#include <cerrno>
#include <climits>
#include <cmath>
#include <deque>
#include <dlfcn.h>
#include <mutex>
#include <string>
#include <thread>
#include <type_traits>

namespace player::media {

namespace {

// The start of FFmpeg's AVFrame and AVPacket: the fields read and written here.
struct AvFrame {
    std::uint8_t* data[8];
    int linesize[8];
    std::uint8_t** extended_data;
    int width, height;
    int nb_samples;
    int format;
};
struct AvPacket {
    void* buf;
    std::int64_t pts, dts;
    std::uint8_t* data;
    int size;
};

// FFmpeg's numbers: its "no time" value, its "not now" error (AVERROR(EAGAIN)), its log level that prints nothing,
// the pixel formats of an 8-bit 4:2:0 stream (YUV420P, and YUVJ420P for the full range), and its sample formats.
constexpr std::int64_t kNoPts = INT64_MIN;
constexpr int kAgain = -EAGAIN, kQuiet = -8;
constexpr int kYuv420p = 0, kYuvj420p = 12;
constexpr int kS16 = 1, kFlt = 3, kS16p = 6, kFltp = 8;

// The functions, from libavcodec and libavutil.
struct Av {
    const void* (*find_decoder_by_name)(const char*) = nullptr;
    void* (*alloc_context3)(const void*) = nullptr;
    int (*open2)(void*, const void*, void**) = nullptr;
    int (*send_packet)(void*, const AvPacket*) = nullptr;
    int (*receive_frame)(void*, AvFrame*) = nullptr;
    void (*free_context)(void**) = nullptr;
    void (*flush_buffers)(void*) = nullptr;
    AvPacket* (*packet_alloc)() = nullptr;
    void (*packet_free)(AvPacket**) = nullptr;
    AvFrame* (*frame_alloc)() = nullptr;
    void (*frame_free)(AvFrame**) = nullptr;
    void (*frame_unref)(AvFrame*) = nullptr;
    int (*opt_set_int)(void*, const char*, std::int64_t, int) = nullptr;
    void (*log_set_level)(int) = nullptr;
    std::string loaded;
};

// FFmpeg's libraries, once: the newest pair of libavcodec and the libavutil of its release that the computer has.
const Av* ffmpeg(std::string& error) {
    static std::once_flag once;
    static Av av;
    static bool ok = false;
    std::call_once(once, [] {
        static const int kPairs[][2] = {{62, 60}, {61, 59}, {60, 58}, {59, 57}, {58, 56}};
        for (const auto& pair : kPairs) {
            std::string codec_name = "libavcodec.so." + std::to_string(pair[0]), util_name = "libavutil.so." + std::to_string(pair[1]);
            void* util = dlopen(util_name.c_str(), RTLD_NOW | RTLD_LOCAL);
            void* codec = util ? dlopen(codec_name.c_str(), RTLD_NOW | RTLD_LOCAL) : nullptr;
            if (!codec) continue;
            auto get = [&](void* lib, const char* name, auto& fn) { fn = reinterpret_cast<std::remove_reference_t<decltype(fn)>>(dlsym(lib, name)); };
            get(codec, "avcodec_find_decoder_by_name", av.find_decoder_by_name);
            get(codec, "avcodec_alloc_context3", av.alloc_context3);
            get(codec, "avcodec_open2", av.open2);
            get(codec, "avcodec_send_packet", av.send_packet);
            get(codec, "avcodec_receive_frame", av.receive_frame);
            get(codec, "avcodec_free_context", av.free_context);
            get(codec, "avcodec_flush_buffers", av.flush_buffers);
            get(codec, "av_packet_alloc", av.packet_alloc);
            get(codec, "av_packet_free", av.packet_free);
            get(util, "av_frame_alloc", av.frame_alloc);
            get(util, "av_frame_free", av.frame_free);
            get(util, "av_frame_unref", av.frame_unref);
            get(util, "av_opt_set_int", av.opt_set_int);
            get(util, "av_log_set_level", av.log_set_level);
            ok = av.find_decoder_by_name && av.alloc_context3 && av.open2 && av.send_packet && av.receive_frame && av.free_context &&
                 av.flush_buffers && av.packet_alloc && av.packet_free && av.frame_alloc && av.frame_free && av.frame_unref && av.opt_set_int &&
                 av.log_set_level;
            if (ok) {
                av.loaded = codec_name;
                // FFmpeg's own messages about damaged streams stay out of the player's log: the game's video carries on.
                av.log_set_level(kQuiet);
                return;
            }
        }
    });
    if (!ok) error = "no FFmpeg (libavcodec 58 to 62) on this computer";
    return ok ? &av : nullptr;
}

// A decoder of FFmpeg's, which turns its frames into ours.
class Ffmpeg : public Decoder {
public:
    Ffmpeg(const Av& av, void* ctx) : av_(av), ctx_(ctx), packet_(av.packet_alloc()), frame_(av.frame_alloc()) {}
    ~Ffmpeg() override {
        av_.frame_free(&frame_);
        av_.packet_free(&packet_);
        av_.free_context(&ctx_);
    }
    bool send(const std::uint8_t* data, std::size_t size) override {
        const std::vector<std::uint8_t>& unit = wrap(data, size);
        packet_->data = const_cast<std::uint8_t*>(unit.empty() ? data : unit.data());
        packet_->size = static_cast<int>(unit.empty() ? size : unit.size());
        packet_->pts = packet_->dts = kNoPts;
        for (;;) {
            int r = av_.send_packet(ctx_, packet_);
            if (r == 0) return true;
            // Its frames waiting to come out first: taken into ours, and the packet goes in after them.
            if (r != kAgain || !take()) return false;
        }
    }
    bool drain() override { return av_.send_packet(ctx_, nullptr) == 0; }
    bool receive(Frame& out) override {
        if (ready_.empty() && !take()) return false;
        out = std::move(ready_.front());
        ready_.pop_front();
        return true;
    }
    void flush() override {
        av_.flush_buffers(ctx_);
        ready_.clear();
    }

protected:
    // What goes to FFmpeg for an access unit: the unit itself (empty: as it is), or with a header of the decoder's.
    virtual const std::vector<std::uint8_t>& wrap(const std::uint8_t*, std::size_t) { return none_; }
    // FFmpeg's frame as ours.
    virtual void convert(const AvFrame& f, Frame& out) = 0;
    const Av& av_;

private:
    // One frame from the decoder into ready_; false when it has none now.
    bool take() {
        if (av_.receive_frame(ctx_, frame_) != 0) return false;
        Frame f;
        convert(*frame_, f);
        av_.frame_unref(frame_);
        ready_.push_back(std::move(f));
        return true;
    }

    void* ctx_;
    AvPacket* packet_;
    AvFrame* frame_;
    std::deque<Frame> ready_;
    std::vector<std::uint8_t> none_;
};

class H264 : public Ffmpeg {
public:
    using Ffmpeg::Ffmpeg;

protected:
    void convert(const AvFrame& f, Frame& out) override {
        out.width = f.width;
        out.height = f.height;
        out.rgba.assign(static_cast<std::size_t>(f.width) * static_cast<std::size_t>(f.height) * 4, 0);
        if (f.format == kYuv420p || f.format == kYuvj420p) {
            yuv420_to_rgba(f.data[0], f.linesize[0], f.data[1], f.data[2], f.linesize[1], 1, f.width, f.height, f.format == kYuvj420p, out.rgba.data());
        } else if (!warned_) {
            // 10-bit and 4:2:2 streams are no game's: the picture stays black, and the log says why.
            jvm::log("player: video: FFmpeg gives pixel format %d, which the player does not convert", f.format);
            warned_ = true;
        }
    }

private:
    bool warned_ = false;
};

class Aac : public Ffmpeg {
public:
    // The AudioSpecificConfig's object type, rate (its index among AAC's) and channels, for each frame's ADTS header.
    Aac(const Av& av, void* ctx, int profile, int rate_index, int channels, int rate)
        : Ffmpeg(av, ctx), profile_(profile), rate_index_(rate_index), channels_(channels), rate_(rate) {}

protected:
    const std::vector<std::uint8_t>& wrap(const std::uint8_t* data, std::size_t size) override {
        // ADTS: the sync word, MPEG-4, no checksum; the profile, the rate and the channels; the frame's whole length;
        // the buffer fullness of a variable rate; one raw block.
        const std::size_t len = size + 7;
        unit_.resize(len);
        unit_[0] = 0xFF;
        unit_[1] = 0xF1;
        unit_[2] = static_cast<std::uint8_t>(((profile_ & 3) << 6) | ((rate_index_ & 15) << 2) | ((channels_ >> 2) & 1));
        unit_[3] = static_cast<std::uint8_t>(((channels_ & 3) << 6) | ((len >> 11) & 3));
        unit_[4] = static_cast<std::uint8_t>((len >> 3) & 0xFF);
        unit_[5] = static_cast<std::uint8_t>(((len & 7) << 5) | 0x1F);
        unit_[6] = 0xFC;
        std::copy(data, data + size, unit_.begin() + 7);
        return unit_;
    }
    void convert(const AvFrame& f, Frame& out) override {
        out.rate = rate_;
        out.channels = channels_;
        const int n = f.nb_samples;
        out.pcm.resize(static_cast<std::size_t>(n) * static_cast<std::size_t>(channels_));
        auto s16 = [](float x) { return static_cast<std::int16_t>(std::lround(std::clamp(x, -1.0f, 1.0f) * 32767.0f)); };
        for (int c = 0; c < channels_; ++c) {
            for (int k = 0; k < n; ++k) {
                std::int16_t v = 0;
                // Planar formats keep a plane a channel; packed ones interleave them in the first.
                if (f.format == kFltp) v = s16(reinterpret_cast<const float*>(f.extended_data[c])[k]);
                else if (f.format == kFlt) v = s16(reinterpret_cast<const float*>(f.extended_data[0])[k * channels_ + c]);
                else if (f.format == kS16p) v = reinterpret_cast<const std::int16_t*>(f.extended_data[c])[k];
                else if (f.format == kS16) v = reinterpret_cast<const std::int16_t*>(f.extended_data[0])[k * channels_ + c];
                out.pcm[static_cast<std::size_t>(k) * static_cast<std::size_t>(channels_) + static_cast<std::size_t>(c)] = v;
            }
        }
    }

private:
    int profile_, rate_index_, channels_, rate_;
    std::vector<std::uint8_t> unit_;
};

// A decoder of FFmpeg's by name, opened with a few of the computer's cores for video.
void* open_context(const Av& av, const char* name, bool threads, std::string& error) {
    const void* codec = av.find_decoder_by_name(name);
    if (!codec) {
        error = av.loaded + " has no " + name + " decoder";
        return nullptr;
    }
    void* ctx = av.alloc_context3(codec);
    if (!ctx) {
        error = "FFmpeg cannot make a decoder";
        return nullptr;
    }
    // A 720p picture in a few milliseconds, with as many pictures of delay as threads.
    if (threads) av.opt_set_int(ctx, "threads", std::min(4u, std::max(1u, std::thread::hardware_concurrency())), 0);
    if (av.open2(ctx, codec, nullptr) < 0) {
        av.free_context(&ctx);
        error = std::string("FFmpeg cannot open its ") + name + " decoder";
        return nullptr;
    }
    return ctx;
}

}  // namespace

std::unique_ptr<Decoder> open_h264(std::string& error) {
    const Av* av = ffmpeg(error);
    if (!av) return nullptr;
    void* ctx = open_context(*av, "h264", true, error);
    return ctx ? std::make_unique<H264>(*av, ctx) : nullptr;
}

std::unique_ptr<Decoder> open_aac(const std::vector<std::uint8_t>& config, std::string& error) {
    // The AudioSpecificConfig: its object type (5 bits, 31 says six more follow), its rate's index (4 bits) and its
    // channels (4 bits).
    if (config.size() < 2) {
        error = "no AudioSpecificConfig";
        return nullptr;
    }
    std::uint32_t bits = static_cast<std::uint32_t>(config[0]) << 24 | static_cast<std::uint32_t>(config[1]) << 16 |
                         (config.size() > 2 ? static_cast<std::uint32_t>(config[2]) << 8 : 0) | (config.size() > 3 ? config[3] : 0u);
    int at = 0;
    auto read = [&](int n) {
        std::uint32_t v = (bits << at) >> (32 - n);
        at += n;
        return static_cast<int>(v);
    };
    int object = read(5);
    if (object == 31) object = 32 + read(6);
    int rate_index = read(4);
    int channels = read(4);
    static const int kRates[] = {96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000, 7350};
    if (rate_index > 12 || channels < 1 || channels > 7) {
        error = "an AAC stream ADTS cannot carry";
        return nullptr;
    }
    // ADTS names AAC Main, LC, SSR and LTP; HE-AAC goes as LC, its core, and the decoder finds the rest in the stream.
    int profile = object >= 1 && object <= 4 ? object - 1 : 1;
    const Av* av = ffmpeg(error);
    if (!av) return nullptr;
    void* ctx = open_context(*av, "aac", false, error);
    return ctx ? std::make_unique<Aac>(*av, ctx, profile, rate_index, channels, kRates[rate_index]) : nullptr;
}

}  // namespace player::media
