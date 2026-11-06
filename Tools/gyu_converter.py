#!/usr/bin/env python3
"""
OpenEXhibit GYU <-> PNG Image Converter
Specialized for Visual Novel interface assets (res/g/sy/), CGs, and backgrounds.

Supports:
- 8-bit Paletted GYU with 4-bit alpha mask (flags=1)
- 8-bit Paletted GYU with 8-bit wide alpha mask (flags=3)
- 8-bit Paletted GYU with colorkey transparency (flags=0, index 255)
- 24-bit Truecolor GYU with/without alpha mask
- 32-bit RGBA GYU / BMP-in-GYU format
- Fast LZSS compression & decompression matching ExHIBIT resident.dll
- MT1997 Mersenne Twister scrambling / unscrambling
- High quality median-cut palette quantization
- Template preservation (matches original GYU parameters on re-pack)
- Batch folder unpack / pack
- Drag & drop support
"""

import os
import sys
import struct
import zlib
import argparse
from typing import Tuple, List, Optional, Dict

# ==============================================================================
# MT1997 Mersenne Twister (Exact 1997 Matsumoto & Nishimura, multiplier 69069)
# ==============================================================================
class MT1997:
    def __init__(self, seed: int):
        s = seed & 0xFFFFFFFF
        self.mt = [0] * 624
        for i in range(624):
            v1 = s & 0xFFFF0000
            s = (69069 * s + 1) & 0xFFFFFFFF
            v2 = (s & 0xFFFF0000) >> 16
            s = (69069 * s + 1) & 0xFFFFFFFF
            self.mt[i] = (v1 | v2) & 0xFFFFFFFF
        self.mti = 624

    def next(self) -> int:
        mag01 = [0x0, 0x9908B0DF]
        if self.mti >= 624:
            for kk in range(624 - 397):
                y = (self.mt[kk] & 0x80000000) | (self.mt[kk + 1] & 0x7FFFFFFF)
                self.mt[kk] = self.mt[kk + 397] ^ (y >> 1) ^ mag01[y & 1]
            for kk in range(624 - 397, 623):
                y = (self.mt[kk] & 0x80000000) | (self.mt[kk + 1] & 0x7FFFFFFF)
                self.mt[kk] = self.mt[kk + (397 - 624)] ^ (y >> 1) ^ mag01[y & 1]
            y = (self.mt[623] & 0x80000000) | (self.mt[0] & 0x7FFFFFFF)
            self.mt[623] = self.mt[396] ^ (y >> 1) ^ mag01[y & 1]
            self.mti = 0

        y = self.mt[self.mti]
        self.mti += 1
        y ^= (y >> 11)
        y ^= (y << 7) & 0x9D2C5680
        y ^= (y << 15) & 0xEFC60000
        y ^= (y >> 18)
        return y & 0xFFFFFFFF


def unscramble(data: bytes, seed: int) -> bytes:
    if not data or not seed or (seed & 0xFFFFFFFF) == 0xFFFFFFFF:
        return data
    mt = MT1997(seed)
    b = bytearray(data)
    l = len(b)
    for _ in range(10):
        i1 = mt.next() % l
        i2 = mt.next() % l
        b[i1], b[i2] = b[i2], b[i1]
    return bytes(b)


def scramble(data: bytes, seed: int) -> bytes:
    if not data or not seed or (seed & 0xFFFFFFFF) == 0xFFFFFFFF:
        return data
    mt = MT1997(seed)
    swaps = []
    l = len(data)
    for _ in range(10):
        swaps.append((mt.next() % l, mt.next() % l))
    b = bytearray(data)
    for i1, i2 in reversed(swaps):
        b[i1], b[i2] = b[i2], b[i1]
    return bytes(b)


# ==============================================================================
# Haruhiko Okumura LZSS Compressor & Decompressor (Matching ExHIBIT unlzss)
# ==============================================================================
def unlzss(data: bytes, out_len: int) -> bytes:
    ring = bytearray(4096)
    r_pos = 4096 - 18  # 0x0FEE
    in_idx = 0
    out = bytearray()

    while in_idx < len(data) and len(out) < out_len:
        flags = data[in_idx]
        in_idx += 1
        for _ in range(8):
            if len(out) >= out_len:
                break
            if flags & 1:
                if in_idx >= len(data):
                    break
                b = data[in_idx]
                in_idx += 1
                ring[r_pos] = b
                r_pos = (r_pos + 1) & 4095
                out.append(b)
            else:
                if in_idx + 1 >= len(data):
                    break
                b1 = data[in_idx]
                b2 = data[in_idx + 1]
                in_idx += 2
                offset = b1 | ((b2 & 0xF0) << 4)
                length = (b2 & 0x0F) + 3
                for _ in range(length):
                    if len(out) >= out_len:
                        break
                    c = ring[offset & 4095]
                    offset += 1
                    ring[r_pos] = c
                    r_pos = (r_pos + 1) & 4095
                    out.append(c)
            flags >>= 1
    return bytes(out)


def lzss_compress(src: bytes) -> bytes:
    ring = bytearray(4096)
    r_pos = 4096 - 18
    src_len = len(src)
    src_idx = 0
    out = bytearray()

    # 2-byte hash table indexer for fast matching
    head = [-1] * 65536
    prev = [-1] * 4096

    while src_idx < src_len:
        chunk_flags = 0
        chunk_bytes = bytearray()

        for bit in range(8):
            if src_idx >= src_len:
                break

            max_len = min(18, src_len - src_idx)
            best_len = 0
            best_offset = 0

            if max_len >= 3:
                key = src[src_idx] | (src[src_idx + 1] << 8)
                curr = head[key]
                chain_len = 0
                while curr != -1 and chain_len < 32:
                    chain_len += 1
                    cur_len = 0
                    while cur_len < max_len:
                        read_pos = (curr + cur_len) & 4095
                        if cur_len > 0 and ((read_pos - r_pos) & 4095) < cur_len:
                            c = src[src_idx + ((read_pos - r_pos) & 4095)]
                        else:
                            c = ring[read_pos]
                        if c != src[src_idx + cur_len]:
                            break
                        cur_len += 1

                    if cur_len > best_len:
                        best_len = cur_len
                        best_offset = curr
                        if best_len == 18:
                            break
                    curr = prev[curr]

            if best_len >= 3:
                chunk_bytes.append(best_offset & 0xFF)
                chunk_bytes.append(((best_offset >> 4) & 0xF0) | (best_len - 3))
                for k in range(best_len):
                    b = src[src_idx + k]
                    ring[r_pos] = b
                    if r_pos < 4095:
                        k2 = ring[r_pos] | (ring[r_pos + 1] << 8)
                        prev[r_pos] = head[k2]
                        head[k2] = r_pos
                    r_pos = (r_pos + 1) & 4095
                src_idx += best_len
            else:
                chunk_flags |= (1 << bit)
                b = src[src_idx]
                chunk_bytes.append(b)
                ring[r_pos] = b
                if r_pos < 4095:
                    k2 = ring[r_pos] | (ring[r_pos + 1] << 8)
                    prev[r_pos] = head[k2]
                    head[k2] = r_pos
                r_pos = (r_pos + 1) & 4095
                src_idx += 1

        out.append(chunk_flags)
        out.extend(chunk_bytes)

    return bytes(out)


# ==============================================================================
# Standalone PNG Decoder & Encoder (Pure Python, Zero Dependency)
# ==============================================================================
def save_png(filename: str, width: int, height: int, rgba_data: bytes):
    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', crc)

    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)  # Filter 0: None
        raw.extend(rgba_data[y * stride : (y + 1) * stride])

    compressed = zlib.compress(bytes(raw), 6)
    ihdr = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)

    png_bytes = (
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', ihdr)
        + chunk(b'IDAT', compressed)
        + chunk(b'IEND', b'')
    )

    os.makedirs(os.path.dirname(os.path.abspath(filename)), exist_ok=True)
    with open(filename, 'wb') as f:
        f.write(png_bytes)


def load_png(filename: str) -> Tuple[int, int, bytes]:
    # Check if PIL is available for accelerated reading
    try:
        from PIL import Image
        with Image.open(filename) as img:
            img = img.convert('RGBA')
            return img.width, img.height, img.tobytes()
    except ImportError:
        pass

    with open(filename, 'rb') as f:
        data = f.read()

    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('Not a valid PNG file')

    pos = 8
    width = height = bit_depth = color_type = 0
    idat = bytearray()
    palette = []
    trns = None

    while pos < len(data):
        length = struct.unpack('>I', data[pos : pos + 4])[0]
        chunk_type = data[pos + 4 : pos + 8]
        chunk_data = data[pos + 8 : pos + 8 + length]
        pos += 12 + length

        if chunk_type == b'IHDR':
            width, height, bit_depth, color_type = struct.unpack('>IIBB', chunk_data[:10])
        elif chunk_type == b'PLTE':
            palette = [chunk_data[i : i + 3] for i in range(0, len(chunk_data), 3)]
        elif chunk_type == b'tRNS':
            trns = chunk_data
        elif chunk_type == b'IDAT':
            idat.extend(chunk_data)
        elif chunk_type == b'IEND':
            break

    decomp = zlib.decompress(bytes(idat))

    if color_type == 6: bpp = 4
    elif color_type == 2: bpp = 3
    elif color_type == 3: bpp = 1
    elif color_type == 0: bpp = 1
    elif color_type == 4: bpp = 2
    else: raise ValueError(f'Unsupported PNG color type {color_type}')

    stride = width * bpp
    line_len = 1 + stride
    pixels = bytearray(height * width * 4)
    prev_line = bytearray(stride)

    def paeth(a: int, b: int, c: int) -> int:
        p = a + b - c
        pa = abs(p - a)
        pb = abs(p - b)
        pc = abs(p - c)
        if pa <= pb and pa <= pc: return a
        elif pb <= pc: return b
        else: return c

    for y in range(height):
        offset = y * line_len
        filter_type = decomp[offset]
        line = bytearray(decomp[offset + 1 : offset + line_len])

        if filter_type == 1:
            for x in range(bpp, stride):
                line[x] = (line[x] + line[x - bpp]) & 0xFF
        elif filter_type == 2:
            for x in range(stride):
                line[x] = (line[x] + prev_line[x]) & 0xFF
        elif filter_type == 3:
            for x in range(stride):
                left = line[x - bpp] if x >= bpp else 0
                above = prev_line[x]
                line[x] = (line[x] + ((left + above) >> 1)) & 0xFF
        elif filter_type == 4:
            for x in range(stride):
                left = line[x - bpp] if x >= bpp else 0
                above = prev_line[x]
                upper_left = prev_line[x - bpp] if x >= bpp else 0
                line[x] = (line[x] + paeth(left, above, upper_left)) & 0xFF

        prev_line = bytearray(line)

        dst_off = y * width * 4
        if color_type == 6:
            pixels[dst_off : dst_off + stride] = line
        elif color_type == 2:
            for x in range(width):
                pixels[dst_off + x * 4 : dst_off + x * 4 + 3] = line[x * 3 : x * 3 + 3]
                pixels[dst_off + x * 4 + 3] = 255
        elif color_type == 3:
            for x in range(width):
                idx = line[x]
                rgb = palette[idx] if idx < len(palette) else b'\x00\x00\x00'
                a = 255
                if trns and idx < len(trns):
                    a = trns[idx]
                pixels[dst_off + x * 4 : dst_off + x * 4 + 3] = rgb
                pixels[dst_off + x * 4 + 3] = a

    return width, height, bytes(pixels)


# ==============================================================================
# Median-Cut Color Quantization (for generating high-quality 8-bit palettes)
# ==============================================================================
def median_cut_palette(colors: List[Tuple[int, int, int]], max_colors: int = 256, reserve_colorkey: bool = False) -> List[Tuple[int, int, int]]:
    limit = max_colors - 1 if reserve_colorkey else max_colors
    unique_colors = list(set(colors))

    if len(unique_colors) <= limit:
        pal = list(unique_colors)
        if reserve_colorkey:
            while len(pal) < 255:
                pal.append((0, 0, 0))
            pal.append((255, 255, 255))
        else:
            while len(pal) < 256:
                pal.append((0, 0, 0))
        return pal

    boxes = [unique_colors]
    while len(boxes) < limit:
        best_box_idx = -1
        max_range = -1
        split_channel = 0

        for i, box in enumerate(boxes):
            if len(box) <= 1:
                continue
            r_vals = [c[0] for c in box]
            g_vals = [c[1] for c in box]
            b_vals = [c[2] for c in box]
            r_rng = max(r_vals) - min(r_vals)
            g_rng = max(g_vals) - min(g_vals)
            b_rng = max(b_vals) - min(b_vals)
            rng = max(r_rng, g_rng, b_rng)
            if rng > max_range:
                max_range = rng
                best_box_idx = i
                split_channel = 0 if rng == r_rng else (1 if rng == g_rng else 2)

        if best_box_idx == -1:
            break

        box_to_split = boxes.pop(best_box_idx)
        box_to_split.sort(key=lambda c: c[split_channel])
        mid = len(box_to_split) // 2
        boxes.append(box_to_split[:mid])
        boxes.append(box_to_split[mid:])

    pal = []
    for box in boxes:
        r_avg = sum(c[0] for c in box) // len(box)
        g_avg = sum(c[1] for c in box) // len(box)
        b_avg = sum(c[2] for c in box) // len(box)
        pal.append((r_avg, g_avg, b_avg))

    if reserve_colorkey:
        while len(pal) < 255:
            pal.append((0, 0, 0))
        pal.append((255, 255, 255))
    else:
        while len(pal) < 256:
            pal.append((0, 0, 0))
    return pal


def map_pixels_to_palette(pixels: bytes, width: int, height: int, palette: List[Tuple[int, int, int]], reserve_colorkey: bool = False) -> bytearray:
    lut: Dict[Tuple[int, int, int], int] = {}
    search_limit = 255 if reserve_colorkey else len(palette)
    indexed = bytearray(width * height)

    for i in range(width * height):
        r = pixels[i * 4 + 0]
        g = pixels[i * 4 + 1]
        b = pixels[i * 4 + 2]
        a = pixels[i * 4 + 3]

        if reserve_colorkey and a < 128:
            indexed[i] = 255
            continue

        c = (r, g, b)
        idx = lut.get(c)
        if idx is None:
            best_dist = 999999999
            best_idx = 0
            for p_idx in range(search_limit):
                pr, pg, pb = palette[p_idx]
                dist = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
                if dist < best_dist:
                    best_dist = dist
                    best_idx = p_idx
                    if dist == 0:
                        break
            idx = best_idx
            lut[c] = idx

        indexed[i] = idx

    return indexed


# ==============================================================================
# GYU File Decoder (GYU -> RGBA)
# ==============================================================================
def decode_gyu(gyu_bytes: bytes, filename: str = "") -> Tuple[int, int, bytes, dict]:
    # Check if standard BMP file with .gyu extension
    if gyu_bytes[:2] == b'BM':
        bfType, bfSize, _, _, bfOffBits = struct.unpack('<2sIHHI', gyu_bytes[:14])
        biWidth, biHeight, _, biBitCount = struct.unpack('<iiHH', gyu_bytes[18:30])
        w = abs(biWidth)
        h = abs(biHeight)
        bpp = biBitCount
        is_top_down = (biHeight < 0)

        pixels = bytearray(w * h * 4)
        row_stride = (w * (bpp // 8) + 3) & ~3

        for y in range(h):
            src_y = y if is_top_down else (h - 1 - y)
            row_off = bfOffBits + src_y * row_stride
            dst_off = y * w * 4

            if bpp == 32:
                for x in range(w):
                    b = gyu_bytes[row_off + x * 4 + 0]
                    g = gyu_bytes[row_off + x * 4 + 1]
                    r = gyu_bytes[row_off + x * 4 + 2]
                    a = gyu_bytes[row_off + x * 4 + 3]
                    pixels[dst_off + x * 4 + 0] = r
                    pixels[dst_off + x * 4 + 1] = g
                    pixels[dst_off + x * 4 + 2] = b
                    pixels[dst_off + x * 4 + 3] = a
            elif bpp == 24:
                for x in range(w):
                    b = gyu_bytes[row_off + x * 3 + 0]
                    g = gyu_bytes[row_off + x * 3 + 1]
                    r = gyu_bytes[row_off + x * 3 + 2]
                    pixels[dst_off + x * 4 + 0] = r
                    pixels[dst_off + x * 4 + 1] = g
                    pixels[dst_off + x * 4 + 2] = b
                    pixels[dst_off + x * 4 + 3] = 255

        header_info = {'is_bmp': True, 'width': w, 'height': h, 'depth': bpp}
        return w, h, bytes(pixels), header_info

    if gyu_bytes[:4] != b'GYU\x1a':
        raise ValueError('Invalid GYU signature')

    flags, gtype, seed, depth, w, h, rgb_len, alpha_len, pal_len = struct.unpack(
        '<HHIIIIIII', gyu_bytes[4:36]
    )

    offset = 36
    palette = []
    if pal_len > 0:
        for i in range(pal_len):
            b, g, r, a = gyu_bytes[offset + i * 4 : offset + (i + 1) * 4]
            palette.append((r, g, b, a))
        offset += pal_len * 4

    rgb_comp = unscramble(gyu_bytes[offset : offset + rgb_len], seed)
    offset += rgb_len

    alpha_comp = gyu_bytes[offset : offset + alpha_len] if alpha_len > 0 else b''

    depth_bytes = max(1, depth // 8)
    out_stride = (w * depth_bytes + 3) & ~3
    out_len = h * out_stride

    if rgb_len == out_len:
        rgb_raw = rgb_comp
    else:
        rgb_raw = unlzss(rgb_comp, out_len)

    if len(rgb_raw) < out_len:
        rgb_raw = rgb_raw.ljust(out_len, b'\x00')

    msk_stride = (w + 3) & ~3
    msk_len = h * msk_stride

    if alpha_len == msk_len:
        msk_raw = alpha_comp
    elif alpha_len > 0:
        msk_raw = unlzss(alpha_comp, msk_len)
    else:
        msk_raw = b''

    if alpha_len > 0 and len(msk_raw) < msk_len:
        msk_raw = msk_raw.ljust(msk_len, b'\x00')

    has_mask = (alpha_len > 0)
    wide_alpha = (flags == 3)

    is_sy = (
        'sy' in filename.lower()
        or '/sy/' in filename.replace('\\', '/')
        or '\\sy\\' in filename
    )

    pixels = bytearray(w * h * 4)
    for y in range(h):
        src_y = h - 1 - y  # GYU raw lines are bottom-up DIB
        rgb_line = rgb_raw[src_y * out_stride : (src_y + 1) * out_stride]
        msk_line = msk_raw[src_y * msk_stride : (src_y + 1) * msk_stride] if has_mask else None
        dst_off = y * w * 4

        for x in range(w):
            r = g = b = 0
            a = 255

            if depth_bytes == 1 and palette:
                idx = rgb_line[x] if x < len(rgb_line) else 0
                if idx < len(palette):
                    r, g, b, _ = palette[idx]
                if not has_mask and idx == 255 and len(palette) >= 256:
                    # System UI assets use white index 255 as transparent color key
                    if (
                        palette[255][0] >= 250
                        and palette[255][1] >= 250
                        and palette[255][2] >= 250
                        and (palette[0] != palette[255])
                    ):
                        a = 0
            elif depth_bytes >= 3:
                off = x * 3
                if off + 2 < len(rgb_line):
                    b = rgb_line[off + 0]
                    g = rgb_line[off + 1]
                    r = rgb_line[off + 2]

            if has_mask and msk_line:
                m = msk_line[x] if x < len(msk_line) else 0
                a = m if wide_alpha else (255 if m == 16 else m * 16)

            pixels[dst_off + x * 4 + 0] = r
            pixels[dst_off + x * 4 + 1] = g
            pixels[dst_off + x * 4 + 2] = b
            pixels[dst_off + x * 4 + 3] = a

    header_info = {
        'is_bmp': False,
        'flags': flags,
        'type': gtype,
        'seed': seed,
        'depth': depth,
        'width': w,
        'height': h,
        'pal_len': pal_len,
        'has_mask': has_mask,
    }
    return w, h, bytes(pixels), header_info


# ==============================================================================
# GYU File Encoder (RGBA -> GYU)
# ==============================================================================
def encode_gyu(
    pixels: bytes,
    width: int,
    height: int,
    template_info: Optional[dict] = None,
    force_depth: Optional[int] = None,
    force_flags: Optional[int] = None,
) -> bytes:
    if template_info and template_info.get('is_bmp'):
        # Write 32-bit BMP with .gyu extension (e.g. 01_070.gyu)
        row_stride = width * 4
        bmp_data_len = height * row_stride
        bfOffBits = 54
        bfSize = bfOffBits + bmp_data_len
        file_hdr = struct.pack('<2sIHHI', b'BM', bfSize, 0, 0, bfOffBits)
        info_hdr = struct.pack('<IiiHHIIiiII', 40, width, height, 1, 32, 0, bmp_data_len, 2835, 2835, 0, 0)
        raw_pixels = bytearray(bmp_data_len)
        for y in range(height):
            dst_y = height - 1 - y
            for x in range(width):
                r = pixels[(y * width + x) * 4 + 0]
                g = pixels[(y * width + x) * 4 + 1]
                b = pixels[(y * width + x) * 4 + 2]
                a = pixels[(y * width + x) * 4 + 3]
                raw_pixels[dst_y * row_stride + x * 4 + 0] = b
                raw_pixels[dst_y * row_stride + x * 4 + 1] = g
                raw_pixels[dst_y * row_stride + x * 4 + 2] = r
                raw_pixels[dst_y * row_stride + x * 4 + 3] = a
        return file_hdr + info_hdr + raw_pixels

    # 1. Determine parameters
    depth = 8
    flags = 1  # Standard UI 4-bit alpha mask by default
    gtype = 1024  # Standard LZSS
    seed = 0x3A5C9E1B  # Non-zero MT1997 seed

    if template_info:
        depth = template_info.get('depth', 8)
        flags = template_info.get('flags', 1)
        gtype = template_info.get('type', 1024)

    if force_depth is not None:
        depth = force_depth
    if force_flags is not None:
        flags = force_flags

    # Analyze transparency
    has_partial_alpha = False
    has_zero_alpha = False
    rgb_colors = []

    for i in range(width * height):
        r = pixels[i * 4 + 0]
        g = pixels[i * 4 + 1]
        b = pixels[i * 4 + 2]
        a = pixels[i * 4 + 3]
        if a < 255:
            if a == 0:
                has_zero_alpha = True
            else:
                has_partial_alpha = True
        rgb_colors.append((r, g, b))

    # Auto-adjust flags if not forced and no template
    if not template_info and force_flags is None:
        if has_partial_alpha:
            flags = 3  # Wide 8-bit alpha mask for smooth blending
        elif has_zero_alpha:
            flags = 1  # 4-bit alpha mask
        else:
            flags = 0  # No alpha mask needed

    # Auto-adjust depth if colors exceed 256 and no template/force
    unique_count = len(set(rgb_colors))
    if not template_info and force_depth is None:
        if unique_count > 256 and (width * height > 400 * 300 or flags == 3):
            depth = 24

    depth_bytes = max(1, depth // 8)
    out_stride = (width * depth_bytes + 3) & ~3
    rgb_raw = bytearray(height * out_stride)

    palette_entries = []

    if depth == 8:
        reserve_colorkey = (flags == 0 and has_zero_alpha)
        palette_entries = median_cut_palette(rgb_colors, 256, reserve_colorkey=reserve_colorkey)
        indexed = map_pixels_to_palette(pixels, width, height, palette_entries, reserve_colorkey=reserve_colorkey)

        for y in range(height):
            src_y = y
            dst_y = height - 1 - y  # Bottom-up DIB
            row_src = src_y * width
            row_dst = dst_y * out_stride
            rgb_raw[row_dst : row_dst + width] = indexed[row_src : row_src + width]
    else:
        # 24-bit Truecolor BGR
        for y in range(height):
            src_y = y
            dst_y = height - 1 - y
            for x in range(width):
                r = pixels[(src_y * width + x) * 4 + 0]
                g = pixels[(src_y * width + x) * 4 + 1]
                b = pixels[(src_y * width + x) * 4 + 2]
                rgb_raw[dst_y * out_stride + x * 3 + 0] = b
                rgb_raw[dst_y * out_stride + x * 3 + 1] = g
                rgb_raw[dst_y * out_stride + x * 3 + 2] = r

    # Mask stream (if flags == 1 or 3)
    msk_raw = bytearray()
    if flags in (1, 3):
        msk_stride = (width + 3) & ~3
        msk_raw = bytearray(height * msk_stride)
        for y in range(height):
            src_y = y
            dst_y = height - 1 - y
            for x in range(width):
                a = pixels[(src_y * width + x) * 4 + 3]
                if flags == 3:
                    m = a
                else:
                    m = 16 if a == 255 else (a * 16 // 255)
                msk_raw[dst_y * msk_stride + x] = m

    # Compress streams with LZSS
    rgb_comp = lzss_compress(bytes(rgb_raw))
    scrambled_rgb = scramble(rgb_comp, seed)

    msk_comp = b''
    if msk_raw:
        msk_comp = lzss_compress(bytes(msk_raw))

    # Header
    pal_len = len(palette_entries) if depth == 8 else 0
    hdr = struct.pack(
        '<4sHHIIIIIII',
        b'GYU\x1a',
        flags,
        1024,
        seed,
        depth,
        width,
        height,
        len(scrambled_rgb),
        len(msk_comp),
        pal_len,
    )

    pal_bytes = bytearray()
    for r, g, b in palette_entries:
        pal_bytes.extend([b, g, r, 0])

    return hdr + pal_bytes + scrambled_rgb + msk_comp


# ==============================================================================
# High-Level Conversion Routines
# ==============================================================================
def convert_gyu_to_png(gyu_path: str, png_path: str):
    with open(gyu_path, 'rb') as f:
        data = f.read()

    w, h, rgba, info = decode_gyu(data, filename=gyu_path)
    save_png(png_path, w, h, rgba)
    print(f'[+] Extracted: {gyu_path} -> {png_path} ({w}x{h}, depth={info.get("depth", 8)}, flags={info.get("flags", 0)})')


def convert_png_to_gyu(png_path: str, gyu_path: str, template_path: Optional[str] = None):
    w, h, rgba = load_png(png_path)

    template_info = None
    target_template = template_path if template_path else (gyu_path if os.path.exists(gyu_path) else None)
    if target_template and os.path.exists(target_template):
        try:
            with open(target_template, 'rb') as f:
                _, _, _, template_info = decode_gyu(f.read(), filename=target_template)
            print(f'[*] Using template: {target_template} (depth={template_info.get("depth")}, flags={template_info.get("flags")})')
        except Exception as e:
            template_info = None

    gyu_bytes = encode_gyu(rgba, w, h, template_info=template_info)
    os.makedirs(os.path.dirname(os.path.abspath(gyu_path)), exist_ok=True)
    with open(gyu_path, 'wb') as f:
        f.write(gyu_bytes)

    print(f'[+] Converted: {png_path} -> {gyu_path} ({w}x{h}, {len(gyu_bytes)} bytes)')


def batch_unpack(src_dir: str, dst_dir: str):
    count = 0
    for root, _, files in os.walk(src_dir):
        for file in files:
            if file.lower().endswith('.gyu'):
                src_file = os.path.join(root, file)
                rel_path = os.path.relpath(src_file, src_dir)
                png_rel = os.path.splitext(rel_path)[0] + '.png'
                dst_file = os.path.join(dst_dir, png_rel)
                try:
                    convert_gyu_to_png(src_file, dst_file)
                    count += 1
                except Exception as e:
                    print(f'[-] Error unpacking {src_file}: {e}')
    print(f'[*] Batch unpack finished! Total converted: {count} images.')


def batch_pack(src_dir: str, dst_dir: str, template_dir: Optional[str] = None):
    count = 0
    tmpl_base = template_dir if template_dir else dst_dir
    for root, _, files in os.walk(src_dir):
        for file in files:
            if file.lower().endswith('.png'):
                src_file = os.path.join(root, file)
                rel_path = os.path.relpath(src_file, src_dir)
                gyu_rel = os.path.splitext(rel_path)[0] + '.gyu'
                dst_file = os.path.join(dst_dir, gyu_rel)
                tmpl_file = os.path.join(tmpl_base, gyu_rel) if tmpl_base else None

                try:
                    convert_png_to_gyu(src_file, dst_file, template_path=tmpl_file)
                    count += 1
                except Exception as e:
                    print(f'[-] Error packing {src_file}: {e}')
    print(f'[*] Batch pack finished! Total converted: {count} images.')


# ==============================================================================
# CLI Entry Point
# ==============================================================================
def main():
    if len(sys.argv) < 2:
        print('OpenEXhibit GYU <-> PNG Converter')
        print('Usage:')
        print('  python gyu_converter.py <file.gyu> [out.png]')
        print('  python gyu_converter.py <file.png> [out.gyu]')
        print('  python gyu_converter.py unpack <gyu_folder> <out_png_folder>')
        print('  python gyu_converter.py pack <png_folder> <out_gyu_folder> [-t template_dir]')
        print('  (or drag and drop .gyu / .png files onto gyu_converter.bat)')
        return

    cmd = sys.argv[1].lower()
    if cmd == 'unpack':
        if len(sys.argv) < 4:
            print('Usage: python gyu_converter.py unpack <src_gyu_dir> <dst_png_dir>')
            return
        batch_unpack(sys.argv[2], sys.argv[3])
        return
    elif cmd == 'pack':
        if len(sys.argv) < 4:
            print('Usage: python gyu_converter.py pack <src_png_dir> <dst_gyu_dir> [-t template_dir]')
            return
        tmpl_dir = None
        if len(sys.argv) >= 6 and sys.argv[4] in ('-t', '--template_dir'):
            tmpl_dir = sys.argv[5]
        batch_pack(sys.argv[2], sys.argv[3], template_dir=tmpl_dir)
        return

    # Two files: input output
    if len(sys.argv) == 3:
        in_file = sys.argv[1]
        out_file = sys.argv[2]
        in_ext = os.path.splitext(in_file)[1].lower()
        out_ext = os.path.splitext(out_file)[1].lower()

        if in_ext == '.gyu' and out_ext == '.png':
            convert_gyu_to_png(in_file, out_file)
            return
        elif in_ext == '.png' and out_ext == '.gyu':
            convert_png_to_gyu(in_file, out_file)
            return

    # Multiple files or single file drag & drop
    for f in sys.argv[1:]:
        ext = os.path.splitext(f)[1].lower()
        if ext == '.gyu':
            out = os.path.splitext(f)[0] + '.png'
            convert_gyu_to_png(f, out)
        elif ext == '.png':
            out = os.path.splitext(f)[0] + '.gyu'
            convert_png_to_gyu(f, out)
        elif os.path.isdir(f):
            out = f + '_png'
            print(f'[*] Unpacking folder {f} -> {out}')
            batch_unpack(f, out)
        else:
            print(f'[-] Unsupported file extension: {f}')


if __name__ == '__main__':
    main()
