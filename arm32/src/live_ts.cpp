// A small MPEG transport stream writer for live segments.
//
// Android's media muxer writes MP4, WebM and a few others, but not what HLS players take in plain
// segments, so the packets are made here: 188-byte packets, one program with one H.264 and one AAC
// stream. Each segment starts with the two tables (PAT and PMT), so a player can start on any of
// them. A frame's first packet carries its time; video frames also carry the clock reference (PCR),
// which needs to come at least every 100 ms: a live stream's lowest frame rate is 15 fps here, so
// the 67 ms between frames keeps to that.
#include "live_ts.h"

#include <algorithm>
#include <cstring>

namespace arm32 {

namespace {

constexpr std::size_t kPacket = 188;
constexpr std::uint16_t kPidPat = 0, kPidPmt = 0x1000, kPidVideo = 0x100, kPidAudio = 0x101;
// The clock reference runs this far (90 kHz: 300 ms) behind the frames, so a frame's time is never
// in the past for a player, also when audio comes out of its encoder a little behind the video.
constexpr std::uint64_t kPcrLead = 27000;

// The CRC of MPEG tables: polynomial 0x04C11DB7, no reflection, all ones to start with.
std::uint32_t crc32_mpeg(const std::uint8_t* data, std::size_t size) {
    std::uint32_t crc = 0xFFFFFFFFu;
    for (std::size_t i = 0; i < size; ++i) {
        crc ^= static_cast<std::uint32_t>(data[i]) << 24;
        for (int bit = 0; bit < 8; ++bit) crc = (crc & 0x80000000u) ? (crc << 1) ^ 0x04C11DB7u : crc << 1;
    }
    return crc;
}

// A 33-bit time in the five bytes a PES header has for it; `tag` is 2 for a PTS alone.
void put_time(std::uint8_t* p, std::uint8_t tag, std::uint64_t t) {
    p[0] = static_cast<std::uint8_t>((tag << 4) | (((t >> 30) & 7) << 1) | 1);
    p[1] = static_cast<std::uint8_t>(t >> 22);
    p[2] = static_cast<std::uint8_t>(((t >> 15) & 0x7F) << 1 | 1);
    p[3] = static_cast<std::uint8_t>(t >> 7);
    p[4] = static_cast<std::uint8_t>((t & 0x7F) << 1 | 1);
}

// The six bytes of a clock reference: 33 bits at 90 kHz, reserved bits, no 27 MHz extension.
void put_pcr(std::uint8_t* p, std::uint64_t t) {
    p[0] = static_cast<std::uint8_t>(t >> 25);
    p[1] = static_cast<std::uint8_t>(t >> 17);
    p[2] = static_cast<std::uint8_t>(t >> 9);
    p[3] = static_cast<std::uint8_t>(t >> 1);
    p[4] = static_cast<std::uint8_t>(((t & 1) << 7) | 0x7E);
    p[5] = 0;
}

}  // namespace

// One table in one packet: both are far smaller than a packet. The rest of the packet is 0xFF.
void TsWriter::section(std::uint16_t pid, std::uint8_t* counter, const std::uint8_t* body, std::size_t size) {
    std::size_t start = out_.size();
    out_.resize(start + kPacket, 0xFF);
    std::uint8_t* p = out_.data() + start;
    p[0] = 0x47;
    // Payload start, the PID.
    p[1] = static_cast<std::uint8_t>(0x40 | (pid >> 8));
    p[2] = static_cast<std::uint8_t>(pid);
    // Payload only.
    p[3] = static_cast<std::uint8_t>(0x10 | (*counter & 0x0F));
    *counter = static_cast<std::uint8_t>((*counter + 1) & 0x0F);
    // The pointer to the section: right here.
    p[4] = 0;
    std::memcpy(p + 5, body, size);
}

void TsWriter::begin_segment() {
    out_.clear();
    // The program association table: program 1's table is on kPidPmt. Length 13 counts from after
    // the length field to the end of the CRC.
    std::uint8_t pat[16] = {0x00, 0xB0, 13, 0x00, 0x01, 0xC1, 0x00, 0x00, 0x00, 0x01,
                            static_cast<std::uint8_t>(0xE0 | (kPidPmt >> 8)), static_cast<std::uint8_t>(kPidPmt)};
    std::uint32_t crc = crc32_mpeg(pat, 12);
    for (int i = 0; i < 4; ++i) pat[12 + i] = static_cast<std::uint8_t>(crc >> (24 - i * 8));
    section(kPidPat, &pat_counter_, pat, sizeof pat);
    // The program map table: the clock on the video stream, H.264 (0x1B) and ADTS AAC (0x0F).
    std::uint8_t pmt[26] = {0x02, 0xB0, 23, 0x00, 0x01, 0xC1, 0x00, 0x00,
                            static_cast<std::uint8_t>(0xE0 | (kPidVideo >> 8)), static_cast<std::uint8_t>(kPidVideo), 0xF0, 0x00,
                            0x1B, static_cast<std::uint8_t>(0xE0 | (kPidVideo >> 8)), static_cast<std::uint8_t>(kPidVideo), 0xF0, 0x00,
                            0x0F, static_cast<std::uint8_t>(0xE0 | (kPidAudio >> 8)), static_cast<std::uint8_t>(kPidAudio), 0xF0, 0x00};
    crc = crc32_mpeg(pmt, 22);
    for (int i = 0; i < 4; ++i) pmt[22 + i] = static_cast<std::uint8_t>(crc >> (24 - i * 8));
    section(kPidPmt, &pmt_counter_, pmt, sizeof pmt);
}

void TsWriter::pes(std::uint16_t pid, std::uint8_t* counter, std::uint8_t stream_id, const std::uint8_t* data, std::size_t size,
                   std::uint64_t pts, bool with_pcr, bool key) {
    // The PES header: start code, stream, length (0: unbounded, allowed for video and needed for a
    // frame over 64 KB), flags saying a PTS follows, and the PTS.
    std::uint8_t header[14] = {0, 0, 1, stream_id, 0, 0, 0x80, 0x80, 5};
    const std::size_t body = size + 8;
    if (stream_id != 0xE0 && body <= 0xFFFF) {
        header[4] = static_cast<std::uint8_t>(body >> 8);
        header[5] = static_cast<std::uint8_t>(body);
    }
    put_time(header + 9, 2, pts);

    std::size_t sent = 0;
    bool first = true;
    while (first || sent < size) {
        const std::size_t head = first ? sizeof header : 0;
        const std::size_t left = head + (size - sent);
        std::size_t start = out_.size();
        out_.resize(start + kPacket);
        std::uint8_t* p = out_.data() + start;
        p[0] = 0x47;
        p[1] = static_cast<std::uint8_t>((first ? 0x40 : 0x00) | (pid >> 8));
        p[2] = static_cast<std::uint8_t>(pid);
        // The adaptation field: the clock reference on a frame's first packet, stuffing on its last.
        std::size_t field = 0;  // bytes of the field with its length byte
        const bool pcr = first && with_pcr;
        const std::size_t room = kPacket - 4;
        if (pcr) field = 8;
        if (left + field < room) field = room - left;
        p[3] = static_cast<std::uint8_t>((field ? 0x30 : 0x10) | (*counter & 0x0F));
        *counter = static_cast<std::uint8_t>((*counter + 1) & 0x0F);
        std::size_t at = 4;
        if (field) {
            p[at++] = static_cast<std::uint8_t>(field - 1);
            if (field > 1) {
                // Flags: random access on a key frame's first packet, and whether a PCR follows.
                std::uint8_t flags = 0;
                if (first && key) flags |= 0x40;
                if (pcr) flags |= 0x10;
                p[at++] = flags;
                if (pcr) {
                    put_pcr(p + at, pts > kPcrLead ? pts - kPcrLead : 0);
                    at += 6;
                }
                // Stuffing up to the end of the field.
                while (at < 4 + field) p[at++] = 0xFF;
            }
        }
        if (first) {
            std::memcpy(p + at, header, sizeof header);
            at += sizeof header;
        }
        const std::size_t n = kPacket - at;
        std::memcpy(p + at, data + sent, n);
        sent += n;
        first = false;
    }
}

void TsWriter::video(const std::uint8_t* data, std::size_t size, std::uint64_t pts, bool key) {
    pes(kPidVideo, &video_counter_, 0xE0, data, size, pts, true, key);
}

void TsWriter::audio(const std::uint8_t* data, std::size_t size, std::uint64_t pts) {
    pes(kPidAudio, &audio_counter_, 0xC0, data, size, pts, false, false);
}

bool adts_header(std::uint8_t out[7], int sample_rate, int channels, std::size_t payload) {
    static const int rates[] = {96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000, 7350};
    int index = -1;
    for (int i = 0; i < 13; ++i)
        if (rates[i] == sample_rate) index = i;
    if (index < 0) return false;
    const std::size_t length = payload + 7;
    out[0] = 0xFF;
    // MPEG-4, no CRC.
    out[1] = 0xF1;
    // AAC-LC (object type 2, written as 1), the rate's index, the channels' top bit.
    out[2] = static_cast<std::uint8_t>((1 << 6) | (index << 2) | ((channels >> 2) & 1));
    out[3] = static_cast<std::uint8_t>(((channels & 3) << 6) | ((length >> 11) & 3));
    out[4] = static_cast<std::uint8_t>(length >> 3);
    // The fullness field all ones: variable bitrate.
    out[5] = static_cast<std::uint8_t>(((length & 7) << 5) | 0x1F);
    out[6] = 0xFC;
    return true;
}

}  // namespace arm32
