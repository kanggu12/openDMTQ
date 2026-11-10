// The MP4 reader (mp4.h): the boxes ISO/IEC 14496-12 and -15 define, as far as a track's format and its sample table
// go, and the edit list's start.
#include "mp4.h"

#include <algorithm>
#include <cstring>
#include <unistd.h>

namespace player::media {

namespace {

constexpr std::uint32_t fourcc(const char (&s)[5]) {
    return static_cast<std::uint32_t>(static_cast<unsigned char>(s[0])) << 24 | static_cast<std::uint32_t>(static_cast<unsigned char>(s[1])) << 16 |
           static_cast<std::uint32_t>(static_cast<unsigned char>(s[2])) << 8 | static_cast<std::uint32_t>(static_cast<unsigned char>(s[3]));
}

// Big-endian fields of a box's contents, in order; past the end every field reads 0 and ok() turns false.
class Reader {
public:
    Reader(const std::uint8_t* p, std::size_t n) : p_(p), n_(n) {}
    std::uint64_t be(std::size_t bytes) {
        if (at_ + bytes > n_) {
            at_ = n_;
            ok_ = false;
            return 0;
        }
        std::uint64_t v = 0;
        for (std::size_t k = 0; k < bytes; ++k) v = v << 8 | p_[at_ + k];
        at_ += bytes;
        return v;
    }
    std::uint8_t u8() { return static_cast<std::uint8_t>(be(1)); }
    std::uint16_t u16() { return static_cast<std::uint16_t>(be(2)); }
    std::uint32_t u32() { return static_cast<std::uint32_t>(be(4)); }
    std::uint64_t u64() { return be(8); }
    void skip(std::size_t n) {
        if (at_ + n > n_) ok_ = false;
        at_ = std::min(at_ + n, n_);
    }
    const std::uint8_t* here() const { return p_ + at_; }
    std::size_t left() const { return n_ - at_; }
    bool ok() const { return ok_; }

private:
    const std::uint8_t* p_;
    std::size_t n_, at_ = 0;
    bool ok_ = true;
};

// Each box in `data`: f(type, contents, size of contents).
template <class F>
void boxes(const std::uint8_t* data, std::size_t size, F&& f) {
    std::size_t at = 0;
    while (at + 8 <= size) {
        Reader r(data + at, size - at);
        std::uint64_t box = r.u32();
        std::uint32_t type = r.u32();
        std::size_t header = 8;
        if (box == 1) {
            box = r.u64();
            header = 16;
        } else if (box == 0) {
            box = size - at;
        }
        if (box < header || box > size - at) return;
        f(type, data + at + header, static_cast<std::size_t>(box - header));
        at += static_cast<std::size_t>(box);
    }
}

// The first box of `type` in `data`, as its contents; empty when there is none.
std::pair<const std::uint8_t*, std::size_t> child(const std::uint8_t* data, std::size_t size, std::uint32_t type) {
    std::pair<const std::uint8_t*, std::size_t> found{nullptr, 0};
    boxes(data, size, [&](std::uint32_t t, const std::uint8_t* p, std::size_t n) {
        if (t == type && !found.first) found = {p, n};
    });
    return found;
}

// An MPEG-4 descriptor's length: 7 bits a byte while the top bit is set.
std::size_t descriptor_length(Reader& r) {
    std::size_t n = 0;
    for (int k = 0; k < 4; ++k) {
        std::uint8_t b = r.u8();
        n = n << 7 | (b & 0x7f);
        if (!(b & 0x80)) break;
    }
    return n;
}

// esds: the decoder's specific information (AAC's AudioSpecificConfig), and the object type (0x40 is AAC).
void read_esds(const std::uint8_t* p, std::size_t n, Track& t, int& object_type) {
    Reader r(p, n);
    r.skip(4);  // version and flags
    if (r.u8() != 3) return;  // ES_Descriptor
    descriptor_length(r);
    r.skip(2);  // ES_ID
    std::uint8_t flags = r.u8();
    if (flags & 0x80) r.skip(2);  // dependsOn_ES_ID
    if (flags & 0x40) r.skip(r.u8());  // URL
    if (flags & 0x20) r.skip(2);  // OCR_ES_Id
    if (r.u8() != 4) return;  // DecoderConfigDescriptor
    descriptor_length(r);
    object_type = r.u8();
    r.skip(1 + 3 + 4 + 4);  // stream type, buffer size, bit rates
    if (r.u8() != 5) return;  // DecoderSpecificInfo
    std::size_t len = descriptor_length(r);
    if (!r.ok() || len > r.left()) return;
    t.csd0.assign(r.here(), r.here() + len);
}

// avcC: the NAL length, and the parameter sets, each after a start code as Android's extractor gives them.
void read_avcc(const std::uint8_t* p, std::size_t n, Track& t) {
    static const std::uint8_t kStart[4] = {0, 0, 0, 1};
    Reader r(p, n);
    r.skip(4);  // version, profile, compatibility, level
    t.nal_length = (r.u8() & 3) + 1;
    for (int set = 0; set < 2; ++set) {
        std::size_t count = set == 0 ? (r.u8() & 0x1f) : r.u8();
        auto& out = set == 0 ? t.csd0 : t.csd1;
        for (std::size_t k = 0; k < count; ++k) {
            std::size_t len = r.u16();
            if (!r.ok() || len > r.left()) return;
            out.insert(out.end(), kStart, kStart + 4);
            out.insert(out.end(), r.here(), r.here() + len);
            r.skip(len);
        }
    }
}

// stsd: the first sample entry's format, as a MIME type and its setup.
void read_stsd(const std::uint8_t* p, std::size_t n, std::uint32_t handler, Track& t) {
    Reader r(p, n);
    r.skip(4);  // version and flags
    if (r.u32() == 0) return;
    std::uint32_t entry = r.u32();
    std::uint32_t format = r.u32();
    if (entry < 8 || entry - 8 > r.left()) return;
    const std::uint8_t* body = r.here();
    std::size_t size = entry - 8;
    char name[5] = {static_cast<char>(format >> 24), static_cast<char>(format >> 16), static_cast<char>(format >> 8), static_cast<char>(format), 0};
    if (handler == fourcc("vide")) {
        // VisualSampleEntry: 78 bytes of fields (the size among them), then its boxes.
        Reader v(body, size);
        v.skip(24);
        t.width = v.u16();
        t.height = v.u16();
        if (size < 78) return;
        if (format == fourcc("avc1") || format == fourcc("avc3")) {
            t.mime = "video/avc";
            auto [c, cn] = child(body + 78, size - 78, fourcc("avcC"));
            if (c) read_avcc(c, cn, t);
        } else if (format == fourcc("hvc1") || format == fourcc("hev1")) {
            t.mime = "video/hevc";
        } else if (format == fourcc("mp4v")) {
            t.mime = "video/mp4v-es";
        } else {
            t.mime = std::string("video/") + name;
        }
    } else if (handler == fourcc("soun")) {
        // AudioSampleEntry: 28 bytes of fields (QuickTime's versions 1 and 2 add 16 and 36), then its boxes.
        Reader a(body, size);
        a.skip(8);
        std::uint16_t version = a.u16();
        a.skip(6);
        t.channels = a.u16();
        a.skip(6);
        t.sample_rate = static_cast<int>(a.u32() >> 16);
        std::size_t fields = 28 + (version == 1 ? 16 : version == 2 ? 36 : 0);
        if (version == 2 && size >= 28 + 36) {
            // Version 2 keeps the rate as a double and the channels after it.
            Reader v2(body + 28, size - 28);
            v2.skip(4);
            std::uint64_t bits = v2.u64();
            double rate;
            std::memcpy(&rate, &bits, 8);
            t.sample_rate = static_cast<int>(rate);
            t.channels = static_cast<int>(v2.u32());
        }
        if (size < fields) return;
        if (format == fourcc("mp4a")) {
            int object_type = 0;
            // The esds may sit inside a QuickTime 'wave' box.
            std::pair<const std::uint8_t*, std::size_t> esds = child(body + fields, size - fields, fourcc("esds"));
            if (!esds.first) {
                std::pair<const std::uint8_t*, std::size_t> wave = child(body + fields, size - fields, fourcc("wave"));
                if (wave.first) esds = child(wave.first, wave.second, fourcc("esds"));
            }
            if (esds.first) read_esds(esds.first, esds.second, t, object_type);
            t.mime = object_type == 0x40 || (object_type >= 0x66 && object_type <= 0x68) || object_type == 0 ? "audio/mp4a-latm" : "audio/mpeg";
        } else {
            t.mime = std::string("audio/") + name;
        }
    }
}

}  // namespace

bool Mp4::read_at(std::int64_t at, void* buf, std::size_t n) const {
    // Within the source, compared without a sum that could overflow.
    if (at < 0 || at > source_.length || n > static_cast<std::uint64_t>(source_.length - at)) return false;
    auto* p = static_cast<std::uint8_t*>(buf);
    std::size_t done = 0;
    while (done < n) {
        ssize_t got = pread(source_.fd, p + done, n - done, source_.offset + at + static_cast<std::int64_t>(done));
        if (got <= 0) return false;
        done += static_cast<std::size_t>(got);
    }
    return true;
}

bool Mp4::open(const Source& source, std::string& error) {
    source_ = source;
    tracks_.clear();
    // The top level: the movie box is all that is read whole; the media data stays in the file.
    std::vector<std::uint8_t> moov;
    for (std::int64_t at = 0; at + 8 <= source_.length;) {
        std::uint8_t head[16];
        if (!read_at(at, head, 8)) break;
        Reader r(head, 8);
        std::uint64_t size = r.u32();
        std::uint32_t type = r.u32();
        std::int64_t header = 8;
        if (size == 1) {
            if (!read_at(at + 8, head + 8, 8)) break;
            Reader r64(head + 8, 8);
            size = r64.u64();
            header = 16;
        } else if (size == 0) {
            size = static_cast<std::uint64_t>(source_.length - at);
        }
        // Unsigned, as the field is: a size past the file's end stops the walk. Read as signed, a size of -16 would pass
        // and step back to a box already read, for ever.
        if (size < static_cast<std::uint64_t>(header) || size > static_cast<std::uint64_t>(source_.length - at)) break;
        if (type == fourcc("moov")) {
            // Kilobytes in practice; a movie box of more than 64 MB is no file a game plays.
            if (size > (64u << 20)) {
                error = "movie box too large";
                return false;
            }
            moov.resize(static_cast<std::size_t>(size) - static_cast<std::size_t>(header));
            if (!read_at(at + header, moov.data(), moov.size())) {
                error = "cannot read the movie box";
                return false;
            }
            break;
        }
        at += static_cast<std::int64_t>(size);
    }
    if (moov.empty()) {
        error = "no movie box";
        return false;
    }
    boxes(moov.data(), moov.size(), [&](std::uint32_t type, const std::uint8_t* trak, std::size_t trak_size) {
        if (type != fourcc("trak")) return;
        auto [mdia, mdia_n] = child(trak, trak_size, fourcc("mdia"));
        if (!mdia) return;
        Track t;
        std::uint32_t scale = 0;
        if (auto [h, hn] = child(mdia, mdia_n, fourcc("mdhd")); h) {
            Reader r(h, hn);
            std::uint8_t version = r.u8();
            r.skip(3 + (version == 1 ? 16 : 8));
            scale = r.u32();
            std::uint64_t duration = version == 1 ? r.u64() : r.u32();
            if (scale) t.duration_us = static_cast<std::int64_t>(duration * 1000000 / scale);
        }
        if (!scale) return;
        std::uint32_t handler = 0;
        if (auto [h, hn] = child(mdia, mdia_n, fourcc("hdlr")); h) {
            Reader r(h, hn);
            r.skip(8);
            handler = r.u32();
        }
        auto [minf, minf_n] = child(mdia, mdia_n, fourcc("minf"));
        auto [stbl, stbl_n] = minf ? child(minf, minf_n, fourcc("stbl")) : std::pair<const std::uint8_t*, std::size_t>{nullptr, 0};
        if (!stbl) return;
        if (auto [s, sn] = child(stbl, stbl_n, fourcc("stsd")); s) read_stsd(s, sn, handler, t);
        if (t.mime.empty()) return;
        // The edit list's start: where in the media the track begins (an encoder's B-frames delay it), as Android's
        // extractor takes it off every time. An empty edit first (-1) only delays the track and is passed over.
        std::int64_t start = 0;
        if (auto [edts, en] = child(trak, trak_size, fourcc("edts")); edts) {
            if (auto [elst, ln] = child(edts, en, fourcc("elst")); elst) {
                Reader r(elst, ln);
                std::uint8_t version = r.u8();
                r.skip(3);
                std::uint32_t entries = r.u32();
                for (std::uint32_t k = 0; k < entries && r.ok(); ++k) {
                    r.skip(version == 1 ? 8 : 4);
                    std::int64_t media_time = version == 1 ? static_cast<std::int64_t>(r.u64()) : static_cast<std::int32_t>(r.u32());
                    r.skip(4);
                    if (media_time >= 0) {
                        start = media_time;
                        break;
                    }
                }
            }
        }
        // Sizes.
        std::vector<std::uint32_t> sizes;
        if (auto [s, sn] = child(stbl, stbl_n, fourcc("stsz")); s) {
            Reader r(s, sn);
            r.skip(4);
            std::uint32_t uniform = r.u32(), count = r.u32();
            if (!r.ok() || count > (64u << 20)) return;
            // No more samples than can be there, before anything is made for each: with one size for all, as many as the
            // file has room for; with a size each, as many as the box lists. A count the file only states would otherwise
            // make gigabytes of tables for a file of a few bytes.
            if (uniform != 0 ? count > static_cast<std::uint64_t>(source_.length) / uniform : count > r.left() / 4) return;
            sizes.resize(count, uniform);
            if (uniform == 0)
                for (auto& v : sizes) v = r.u32();
            if (!r.ok()) return;
        }
        // Chunks: their offsets, and how many samples each holds.
        std::vector<std::int64_t> chunks;
        if (auto [s, sn] = child(stbl, stbl_n, fourcc("stco")); s) {
            Reader r(s, sn);
            r.skip(4);
            std::uint32_t count = r.u32();
            for (std::uint32_t k = 0; k < count && r.ok(); ++k) chunks.push_back(r.u32());
        } else if (auto [s64, sn64] = child(stbl, stbl_n, fourcc("co64")); s64) {
            Reader r(s64, sn64);
            r.skip(4);
            std::uint32_t count = r.u32();
            for (std::uint32_t k = 0; k < count && r.ok(); ++k) chunks.push_back(static_cast<std::int64_t>(r.u64()));
        }
        struct Run {
            std::uint32_t first_chunk, per_chunk;
        };
        std::vector<Run> runs;
        if (auto [s, sn] = child(stbl, stbl_n, fourcc("stsc")); s) {
            Reader r(s, sn);
            r.skip(4);
            std::uint32_t count = r.u32();
            for (std::uint32_t k = 0; k < count && r.ok(); ++k) {
                Run run{r.u32(), r.u32()};
                r.skip(4);
                runs.push_back(run);
            }
        }
        // Decoding times (time to sample), composition offsets, and the key frames (all of them without stss).
        std::vector<std::pair<std::uint32_t, std::uint32_t>> deltas, offsets;
        for (auto [box, list] : {std::pair{fourcc("stts"), &deltas}, std::pair{fourcc("ctts"), &offsets}}) {
            if (auto [s, sn] = child(stbl, stbl_n, box); s) {
                Reader r(s, sn);
                r.skip(4);
                std::uint32_t count = r.u32();
                for (std::uint32_t k = 0; k < count && r.ok(); ++k) {
                    std::uint32_t n = r.u32(), v = r.u32();
                    list->push_back({n, v});
                }
            }
        }
        std::vector<bool> sync(sizes.size(), true);
        if (auto [s, sn] = child(stbl, stbl_n, fourcc("stss")); s) {
            std::fill(sync.begin(), sync.end(), false);
            Reader r(s, sn);
            r.skip(4);
            std::uint32_t count = r.u32();
            for (std::uint32_t k = 0; k < count && r.ok(); ++k) {
                std::uint32_t number = r.u32();
                if (number >= 1 && number <= sync.size()) sync[number - 1] = true;
            }
        }
        // The samples: each chunk's run of samples, one after another from the chunk's offset. The runs come in the order
        // of their first chunks (numbered from 1), and the one a chunk is in is the last that starts at or before it: found
        // by walking them along with the chunks, as a look through all of them for each chunk would take chunks times
        // runs, hours for a made-up file of a few megabytes.
        t.samples.reserve(sizes.size());
        std::size_t k = 0, started = 0;
        for (std::size_t c = 0; c < chunks.size() && k < sizes.size(); ++c) {
            // The runs that have started by this chunk; none yet is no samples.
            while (started < runs.size() && runs[started].first_chunk <= c + 1) ++started;
            const std::uint32_t per = started ? runs[started - 1].per_chunk : 0;
            std::int64_t at = chunks[c];
            for (std::uint32_t s = 0; s < per && k < sizes.size(); ++s, ++k) {
                Sample sample;
                sample.offset = at;
                sample.size = sizes[k];
                sample.sync = sync[k];
                // The largest sample that is whole in the file: one past its end is never read (read), and the decoder's
                // input buffers are made as large as this (max_read_size), so a made-up size must not count.
                if (at >= 0 && at <= source_.length && sizes[k] <= static_cast<std::uint64_t>(source_.length - at))
                    t.max_sample = std::max(t.max_sample, sizes[k]);
                at += sizes[k];
                t.samples.push_back(sample);
            }
        }
        // Their times.
        std::int64_t dts = 0;
        std::size_t d = 0, d_left = deltas.empty() ? 0 : deltas[0].first;
        std::size_t o = 0, o_left = offsets.empty() ? 0 : offsets[0].first;
        for (Sample& s : t.samples) {
            while (d_left == 0 && d + 1 < deltas.size()) d_left = deltas[++d].first;
            while (o_left == 0 && o + 1 < offsets.size()) o_left = offsets[++o].first;
            // ctts offsets are signed in version 1 and, as QuickTime and others write them, in version 0 too.
            std::int64_t cts = dts + (o_left ? static_cast<std::int32_t>(offsets[o].second) : 0);
            s.decode_us = (dts - start) * 1000000 / scale;
            s.time_us = (cts - start) * 1000000 / scale;
            if (d_left) {
                dts += deltas[d].second;
                --d_left;
            }
            if (o_left) --o_left;
        }
        tracks_.push_back(std::move(t));
    });
    if (tracks_.empty()) {
        error = "no tracks this can read";
        return false;
    }
    return true;
}

std::uint32_t Mp4::max_read_size(std::size_t t) const {
    const Track& track = tracks_[t];
    // A start code is four bytes: a NAL unit after a 1- or 2-byte length grows by 3 or 2 at most, and is a byte at least.
    if (track.nal_length == 1) return track.max_sample * 5 / 2 + 4;
    if (track.nal_length == 2) return track.max_sample * 2 + 4;
    return track.max_sample;
}

bool Mp4::read(std::size_t t, std::size_t k, std::vector<std::uint8_t>& out) const {
    if (t >= tracks_.size() || k >= tracks_[t].samples.size()) return false;
    const Track& track = tracks_[t];
    const Sample& s = track.samples[k];
    // In the file whole, or not read: the size is the file's word, and a buffer of it (up to 4 GiB, zeroed) comes after
    // the check, not before.
    if (s.offset < 0 || s.offset > source_.length || s.size > static_cast<std::uint64_t>(source_.length - s.offset)) return false;
    std::vector<std::uint8_t> raw(s.size);
    if (!read_at(s.offset, raw.data(), raw.size())) return false;
    if (track.nal_length == 0) {
        out = std::move(raw);
        return true;
    }
    // Each NAL unit's length becomes a start code.
    out.clear();
    out.reserve(raw.size() + 16);
    std::size_t at = 0;
    const std::size_t n = static_cast<std::size_t>(track.nal_length);
    while (at + n <= raw.size()) {
        std::size_t len = 0;
        for (std::size_t b = 0; b < n; ++b) len = len << 8 | raw[at + b];
        at += n;
        if (len > raw.size() - at) return false;
        static const std::uint8_t kStart[4] = {0, 0, 0, 1};
        out.insert(out.end(), kStart, kStart + 4);
        out.insert(out.end(), raw.begin() + static_cast<std::ptrdiff_t>(at), raw.begin() + static_cast<std::ptrdiff_t>(at + len));
        at += len;
    }
    return true;
}

}  // namespace player::media
