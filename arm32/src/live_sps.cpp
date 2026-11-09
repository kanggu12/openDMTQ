// The colours of a computer's broadcast in its H.264 stream (live_sps.h).
#include "live_sps.h"

namespace arm32 {

namespace {

// The bytes of a NAL unit's payload without the emulation-prevention bytes (00 00 03), and back.
std::vector<std::uint8_t> unescape(const std::uint8_t* p, std::size_t n) {
    std::vector<std::uint8_t> out;
    out.reserve(n);
    int zeros = 0;
    for (std::size_t i = 0; i < n; ++i) {
        if (zeros >= 2 && p[i] == 3) {
            zeros = 0;
            continue;
        }
        zeros = p[i] == 0 ? zeros + 1 : 0;
        out.push_back(p[i]);
    }
    return out;
}
std::vector<std::uint8_t> escape(const std::vector<std::uint8_t>& rbsp) {
    std::vector<std::uint8_t> out;
    out.reserve(rbsp.size() + 8);
    int zeros = 0;
    for (std::uint8_t b : rbsp) {
        if (zeros >= 2 && b <= 3) {
            out.push_back(3);
            zeros = 0;
        }
        zeros = b == 0 ? zeros + 1 : 0;
        out.push_back(b);
    }
    return out;
}

// Bits of an RBSP, most significant first, read and written with Exp-Golomb codes as H.264 has them.
struct Bits {
    const std::vector<std::uint8_t>& in;
    std::size_t pos = 0;  // bits read
    bool ok = true;       // false once a read went past the end
    std::vector<std::uint8_t> out;
    int out_bits = 0;     // bits written

    explicit Bits(const std::vector<std::uint8_t>& b) : in(b) {}
    std::uint32_t read(int n) {
        std::uint32_t v = 0;
        for (int i = 0; i < n; ++i) {
            if (pos >= in.size() * 8) {
                ok = false;
                return 0;
            }
            v = (v << 1) | ((in[pos >> 3] >> (7 - (pos & 7))) & 1);
            ++pos;
        }
        return v;
    }
    std::uint32_t read_ue() {
        int zeros = 0;
        while (ok && read(1) == 0 && zeros < 32) ++zeros;
        return zeros ? ((1u << zeros) - 1) + read(zeros) : 0;
    }
    void write(int n, std::uint32_t v) {
        for (int i = n - 1; i >= 0; --i) {
            if ((out_bits & 7) == 0) out.push_back(0);
            if ((v >> i) & 1) out.back() |= static_cast<std::uint8_t>(0x80 >> (out_bits & 7));
            ++out_bits;
        }
    }
    void write_ue(std::uint32_t v) {
        const std::uint32_t x = v + 1;
        int len = 0;
        while ((x >> len) > 1) ++len;
        write(len, 0);
        write(len + 1, x);
    }
    // Read and written as they were.
    std::uint32_t copy(int n) {
        const std::uint32_t v = read(n);
        write(n, v);
        return v;
    }
    std::uint32_t copy_ue() {
        const std::uint32_t v = read_ue();
        write_ue(v);
        return v;
    }
    void copy_se() { copy_ue(); }
};

// The video signal description with the stream's colours: BT.709 primaries, transfer and matrix, limited range.
void write_signal_type(Bits& b, std::uint32_t video_format) {
    b.write(1, 1);             // video_signal_type_present_flag
    b.write(3, video_format);  // video_format (5: unspecified)
    b.write(1, 0);             // video_full_range_flag: 16 to 235
    b.write(1, 1);             // colour_description_present_flag
    b.write(8, 1);             // colour_primaries: BT.709
    b.write(8, 1);             // transfer_characteristics: BT.709
    b.write(8, 1);             // matrix_coefficients: BT.709
}

// A sequence parameter set (its RBSP, after the NAL header) with the colours in its VUI; empty when it cannot be read
// (a scaling matrix, a profile this encoder does not make), and it then goes as it was.
std::vector<std::uint8_t> sps_with_colours(const std::vector<std::uint8_t>& rbsp) {
    Bits b(rbsp);
    const std::uint32_t profile = b.copy(8);
    b.copy(8);  // constraint flags
    b.copy(8);  // level
    b.copy_ue();  // seq_parameter_set_id
    if (profile == 100 || profile == 110 || profile == 122 || profile == 244 || profile == 44 || profile == 83 || profile == 86 || profile == 118 ||
        profile == 128 || profile == 138 || profile == 139 || profile == 134 || profile == 135) {
        if (b.copy_ue() == 3) b.copy(1);  // chroma_format_idc, separate_colour_plane_flag
        b.copy_ue();  // bit_depth_luma_minus8
        b.copy_ue();  // bit_depth_chroma_minus8
        b.copy(1);    // qpprime_y_zero_transform_bypass_flag
        if (b.copy(1)) return {};  // seq_scaling_matrix_present_flag: not read here
    }
    b.copy_ue();  // log2_max_frame_num_minus4
    const std::uint32_t poc_type = b.copy_ue();
    if (poc_type == 0) {
        b.copy_ue();  // log2_max_pic_order_cnt_lsb_minus4
    } else if (poc_type == 1) {
        b.copy(1);    // delta_pic_order_always_zero_flag
        b.copy_se();  // offset_for_non_ref_pic
        b.copy_se();  // offset_for_top_to_bottom_field
        const std::uint32_t cycle = b.copy_ue();
        for (std::uint32_t i = 0; i < cycle && b.ok; ++i) b.copy_se();
    }
    b.copy_ue();  // max_num_ref_frames
    b.copy(1);    // gaps_in_frame_num_value_allowed_flag
    b.copy_ue();  // pic_width_in_mbs_minus1
    b.copy_ue();  // pic_height_in_map_units_minus1
    if (!b.copy(1)) b.copy(1);  // frame_mbs_only_flag, mb_adaptive_frame_field_flag
    b.copy(1);    // direct_8x8_inference_flag
    if (b.copy(1)) {  // frame_cropping_flag, and its four offsets
        for (int i = 0; i < 4; ++i) b.copy_ue();
    }
    // Where the RBSP's stop bit is: everything up to it is the header's, the rest alignment.
    std::size_t stop = rbsp.size() * 8;
    while (stop > 0 && !((rbsp[(stop - 1) >> 3] >> (7 - ((stop - 1) & 7))) & 1)) --stop;
    if (!b.ok || stop == 0) return {};
    --stop;
    const bool vui = b.read(1);
    b.write(1, 1);  // vui_parameters_present_flag
    if (!vui) {
        // None: one of the colours alone.
        b.write(1, 0);  // aspect_ratio_info_present_flag
        b.write(1, 0);  // overscan_info_present_flag
        write_signal_type(b, 5);
        b.write(1, 0);  // chroma_loc_info_present_flag
        b.write(1, 0);  // timing_info_present_flag
        b.write(1, 0);  // nal_hrd_parameters_present_flag
        b.write(1, 0);  // vcl_hrd_parameters_present_flag
        b.write(1, 0);  // pic_struct_present_flag
        b.write(1, 0);  // bitstream_restriction_flag
    } else {
        if (b.copy(1) && b.copy(8) == 255) {  // aspect_ratio_info_present_flag, aspect_ratio_idc, and a SAR of its own
            b.copy(16);
            b.copy(16);
        }
        if (b.copy(1)) b.copy(1);  // overscan_info_present_flag, overscan_appropriate_flag
        std::uint32_t video_format = 5;
        if (b.read(1)) {  // the encoder's own signal type, replaced
            video_format = b.read(3);
            b.read(1);
            if (b.read(1)) b.read(24);
        }
        write_signal_type(b, video_format);
        // The rest of the VUI as it was, bit by bit, up to the stop bit.
        if (!b.ok || b.pos > stop) return {};
        while (b.pos < stop) b.copy(1);
    }
    if (!b.ok) return {};
    // The stop bit and the alignment after it.
    b.write(1, 1);
    while (b.out_bits & 7) b.write(1, 0);
    return b.out;
}

}  // namespace

// An access unit (Annex B) with each SPS in it given the colours; the same bytes when it has none.
std::vector<std::uint8_t> with_colours(const std::vector<std::uint8_t>& unit) {
    std::vector<std::uint8_t> out;
    out.reserve(unit.size() + 8);
    std::size_t i = 0;
    while (i < unit.size()) {
        // The next start code and the NAL unit after it, up to the one after that.
        std::size_t start = i;
        while (start + 2 < unit.size() && !(unit[start] == 0 && unit[start + 1] == 0 && unit[start + 2] == 1)) ++start;
        if (start + 2 >= unit.size()) {
            out.insert(out.end(), unit.begin() + static_cast<std::ptrdiff_t>(i), unit.end());
            break;
        }
        const std::size_t payload = start + 3;
        std::size_t next = payload;
        while (next + 2 < unit.size() && !(unit[next] == 0 && unit[next + 1] == 0 && (unit[next + 2] == 1 || (unit[next + 2] == 0 && next + 3 < unit.size() && unit[next + 3] == 1)))) ++next;
        if (next + 2 >= unit.size()) next = unit.size();
        // What came before the start code (a leading zero of a four-byte one), and the start code.
        out.insert(out.end(), unit.begin() + static_cast<std::ptrdiff_t>(i), unit.begin() + static_cast<std::ptrdiff_t>(payload));
        if (payload < next && (unit[payload] & 0x1f) == 7) {
            const std::vector<std::uint8_t> rbsp = unescape(unit.data() + payload + 1, next - payload - 1);
            const std::vector<std::uint8_t> coloured = sps_with_colours(rbsp);
            if (!coloured.empty()) {
                out.push_back(unit[payload]);
                const std::vector<std::uint8_t> escaped = escape(coloured);
                out.insert(out.end(), escaped.begin(), escaped.end());
                i = next;
                continue;
            }
        }
        out.insert(out.end(), unit.begin() + static_cast<std::ptrdiff_t>(payload), unit.begin() + static_cast<std::ptrdiff_t>(next));
        i = next;
    }
    return out;
}


}  // namespace arm32
