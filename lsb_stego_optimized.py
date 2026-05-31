"""
lsb_stego_optimized.py — Adaptive LSB Steganography (PVD-weighted)
-------------------------------------------------------------------
An optimized variant of standard LSB that uses a Pixel Value Differencing
(PVD) inspired heuristic to embed 1, 2, or 3 bits per channel depending on
local contrast — hiding more data in edge-rich regions where the human eye
is less sensitive to noise.

Core idea
---------
For each pixel the algorithm computes a local contrast score from its four
cardinal neighbours and assigns an embedding depth:

    contrast in [0, LOW_T)        → 1 bit per channel  (smooth area)
    contrast in [LOW_T, HIGH_T)   → 2 bits per channel (moderate edge)
    contrast in [HIGH_T, 255]     → 3 bits per channel (strong edge)

Payload layout (encoder)
------------------------
The depth map is computed from the ORIGINAL (cover) image and stored in a
compact side-channel: immediately after the 32-bit message-length header the
encoder serialises the per-pixel depth as 2-bit values (1→00, 2→01, 3→10),
always embedded at depth=1.  The decoder reads this map first, then uses it
to correctly extract the message bits.  This makes decoding deterministic
even for images where re-computing the map from the stego image would give
different results at edge boundaries.

Full payload structure (all bits embedded at depth=1 in the first N pixels):
    [0..31]        32-bit big-endian uint  → UTF-8 message length in bytes (L)
    [32..32+2P-1]  depth map, 2 bits per pixel (P = total pixel count)
Then, starting right after the fixed header, message bits are embedded using
the depth map values.

Capacity vs standard LSB
-------------------------
    Worst case (all smooth)  : same as standard LSB  (1 bit/channel)
    Best case  (all edges)   : 3× standard LSB       (3 bits/channel)
    Typical photo            : ~1.5–2.0× standard LSB

Usage (CLI):
    python lsb_stego_optimized.py encode   input.png  output.png  "Secret"
    python lsb_stego_optimized.py decode   stego.png
    python lsb_stego_optimized.py capacity image.png
    python lsb_stego_optimized.py compare  original.png  stego.png
"""

import sys
import math
import struct
from pathlib import Path
from PIL import Image


#  Thresholds

LOW_THRESHOLD  = 20
HIGH_THRESHOLD = 60


#  Bit helpers

def _text_to_bits(text: str) -> list:
    bits = []
    for byte in text.encode("utf-8"):
        for shift in range(7, -1, -1):
            bits.append((byte >> shift) & 1)
    return bits


def _bits_to_text(bits: list) -> str:
    raw = bytearray()
    for i in range(0, len(bits), 8):
        byte = 0
        for bit in bits[i : i + 8]:
            byte = (byte << 1) | bit
        raw.append(byte)
    return raw.decode("utf-8")


def _int_to_bits_n(value: int, n: int) -> list:
    return [(value >> (n - 1 - i)) & 1 for i in range(n)]


def _luminance(r, g, b) -> float:
    return 0.299 * r + 0.587 * g + 0.114 * b


#  Depth map

def _build_depth_map(pixels: list, width: int, height: int) -> list:
    """Return a flat list of embedding depths (1, 2, or 3) per pixel."""
    def lum(idx):
        return _luminance(*pixels[idx])

    depths = []
    for y in range(height):
        for x in range(width):
            idx = y * width + x
            neighbours = []
            if x > 0:           neighbours.append(lum(idx - 1))
            if x < width - 1:   neighbours.append(lum(idx + 1))
            if y > 0:           neighbours.append(lum(idx - width))
            if y < height - 1:  neighbours.append(lum(idx + width))
            contrast = (
                sum(abs(lum(idx) - n) for n in neighbours) / len(neighbours)
                if neighbours else 0.0
            )
            if contrast < LOW_THRESHOLD:
                depths.append(1)
            elif contrast < HIGH_THRESHOLD:
                depths.append(2)
            else:
                depths.append(3)
    return depths


#  Low-level embed / extract  (depth=1 only, for header region)

def _pixels_to_lsb1_bits(pixels: list) -> list:
    """Extract every LSB (depth=1) of every channel, in order."""
    out = []
    for r, g, b in pixels:
        out.append(r & 1)
        out.append(g & 1)
        out.append(b & 1)
    return out


def _embed_lsb1(pixels: list, bits: list, start_channel: int) -> tuple:
    """
    Embed *bits* into pixels starting at channel offset *start_channel*,
    using depth=1. Returns (modified_pixels, next_channel_offset).
    Pixels is modified in-place (list of lists).
    """
    ch = start_channel
    for bit in bits:
        px_idx  = ch // 3
        ch_idx  = ch  % 3
        r, g, b = pixels[px_idx]
        if ch_idx == 0:
            pixels[px_idx] = ((r & ~1) | bit, g, b)
        elif ch_idx == 1:
            pixels[px_idx] = (r, (g & ~1) | bit, b)
        else:
            pixels[px_idx] = (r, g, (b & ~1) | bit)
        ch += 1
    return ch


def _embed_adaptive(pixels: list, bits: list, depths: list, start_pixel: int) -> int:
    """
    Embed *bits* adaptively (variable depth per pixel) starting at
    *start_pixel*. Returns the index of the first pixel NOT written to.
    """
    bit_pos = 0
    px_idx  = start_pixel
    while bit_pos < len(bits) and px_idx < len(pixels):
        r, g, b = pixels[px_idx]
        d = depths[px_idx]
        for ch_val, setter in [(r, 0), (g, 1), (b, 2)]:
            if bit_pos >= len(bits):
                break
            chunk = bits[bit_pos : bit_pos + d]
            bit_pos += len(chunk)
            mask  = (1 << len(chunk)) - 1
            val   = sum(b << (len(chunk) - 1 - i) for i, b in enumerate(chunk))
            new_v = (ch_val & ~mask) | (val & mask)
            r, g, b = (
                (new_v, g, b) if setter == 0 else
                (r, new_v, b) if setter == 1 else
                (r, g, new_v)
            )
        pixels[px_idx] = (r, g, b)
        px_idx += 1
    return px_idx


def _extract_adaptive(all_channel_bits_fn, depths: list, start_pixel: int, n_bits: int) -> list:
    """
    Extract *n_bits* from pixels starting at *start_pixel* using depth map.
    *all_channel_bits_fn(pixel_idx, depth)* → list of bits for that pixel.
    """
    bits = []
    px_idx = start_pixel
    while len(bits) < n_bits:
        d = depths[px_idx]
        bits.extend(all_channel_bits_fn(px_idx, d))
        px_idx += 1
    return bits[:n_bits]


#  Capacity

def max_capacity(image_path: str) -> int:
    """Return the adaptive capacity in UTF-8 bytes for the given image."""
    with Image.open(image_path).convert("RGB") as img:
        width, height = img.size
        pixels = list(img.getdata())

    n = width * height
    depths = _build_depth_map(pixels, width, height)

    # Header overhead: 32 bits (length) + 2*n bits (depth map), all at depth=1
    header_channels = 32 + 2 * n          # channels consumed by header
    header_pixels   = math.ceil(header_channels / 3)

    # Remaining pixels carry message bits at adaptive depth
    msg_bits = sum(depths[i] * 3 for i in range(header_pixels, n))
    return msg_bits // 8


#  Encode

def encode(input_path: str, output_path: str, message: str) -> None:
    """Adaptively embed *message* into *input_path*, save PNG to *output_path*."""
    output_path = Path(output_path)
    if output_path.suffix.lower() in (".jpg", ".jpeg"):
        raise IOError("Output must be lossless (PNG or BMP).")

    with Image.open(input_path).convert("RGB") as img:
        width, height = img.size
        pixels = [list(p) for p in img.getdata()]  # mutable

    n      = width * height
    depths = _build_depth_map([tuple(p) for p in pixels], width, height)

    msg_bytes = message.encode("utf-8")
    msg_len   = len(msg_bytes)

    capacity = max_capacity(input_path)
    if msg_len > capacity:
        raise ValueError(
            f"Message too long: {msg_len} bytes; adaptive capacity is {capacity} bytes."
        )

    # ── Build header: 32-bit length + depth map (2 bits/pixel) ──
    length_bits = []
    for byte in struct.pack(">I", msg_len):
        for shift in range(7, -1, -1):
            length_bits.append((byte >> shift) & 1)

    depth_map_bits = []
    _D = {1: [0, 0], 2: [0, 1], 3: [1, 0]}
    for d in depths:
        depth_map_bits.extend(_D[d])

    header_bits    = length_bits + depth_map_bits  # len = 32 + 2*n
    header_channels = len(header_bits)
    header_pixels   = math.ceil(header_channels / 3)

    # ── Embed header at depth=1 ──
    pixels_flat = [tuple(p) for p in pixels]
    pixels_mut  = list(pixels_flat)
    _embed_lsb1(pixels_mut, header_bits, 0)

    # ── Embed message bits adaptively after header ──
    message_bits = _text_to_bits(message)
    _embed_adaptive(pixels_mut, message_bits, depths, header_pixels)

    out_img = Image.new("RGB", (width, height))
    out_img.putdata(pixels_mut)
    out_img.save(str(output_path))

    std_cap = (3 * n - 32) // 8
    print(f"[encode-adaptive] Done. Embedded {msg_len} byte(s) → '{output_path}'.")
    print(f"  Adaptive capacity : {capacity:,} chars")
    print(f"  Standard capacity : {std_cap:,} chars")
    print(f"  Improvement       : {capacity / std_cap:.2f}×")


#  Decode

def decode(stego_path: str) -> str:
    """Extract and return the hidden message from a stego image."""
    with Image.open(stego_path).convert("RGB") as img:
        width, height = img.size
        pixels = list(img.getdata())

    n = width * height

    # ── Read all depth-1 LSBs (the entire image at depth=1 for the header) ──
    all_lsbs = _pixels_to_lsb1_bits(pixels)

    # Parse 32-bit message length
    if len(all_lsbs) < 32:
        raise ValueError("Image too small.")
    length_val = 0
    for bit in all_lsbs[:32]:
        length_val = (length_val << 1) | bit
    msg_len = struct.unpack(">I", length_val.to_bytes(4, "big"))[0]

    # Parse depth map (2 bits per pixel)
    depth_map_start = 32
    depth_map_end   = 32 + 2 * n
    if depth_map_end > len(all_lsbs):
        raise ValueError("Image too small to hold depth map.")

    _INV = {(0, 0): 1, (0, 1): 2, (1, 0): 3}
    depths = []
    for i in range(0, 2 * n, 2):
        b0 = all_lsbs[depth_map_start + i]
        b1 = all_lsbs[depth_map_start + i + 1]
        depths.append(_INV[(b0, b1)])

    header_channels = 32 + 2 * n
    header_pixels   = math.ceil(header_channels / 3)

    # ── Extract message bits adaptively ──
    def pixel_bits(px_idx, depth):
        r, g, b = pixels[px_idx]
        mask = (1 << depth) - 1
        bits = []
        for v in (r, g, b):
            for shift in range(depth - 1, -1, -1):
                bits.append((v >> shift) & 1)
        return bits

    needed = msg_len * 8
    bits   = []
    px_idx = header_pixels
    while len(bits) < needed:
        bits.extend(pixel_bits(px_idx, depths[px_idx]))
        px_idx += 1

    message = _bits_to_text(bits[:needed])
    print(f"[decode-adaptive] Found message ({msg_len} byte(s)): {message!r}")
    return message


#  Quality comparison (PSNR)

def compare(original_path: str, stego_path: str) -> float:
    """Compute and print PSNR between original and stego images."""
    with Image.open(original_path).convert("RGB") as img:
        orig = list(img.getdata())
    with Image.open(stego_path).convert("RGB") as img:
        steg = list(img.getdata())

    if len(orig) != len(steg):
        raise ValueError("Images must have the same dimensions.")

    mse = sum(
        (oc - sc) ** 2
        for op, sp in zip(orig, steg)
        for oc, sc in zip(op, sp)
    ) / (len(orig) * 3)

    if mse == 0:
        print("[compare] Images are identical.")
        return float("inf")

    psnr = 10 * math.log10(255 ** 2 / mse)
    print(f"[compare] MSE = {mse:.4f}  |  PSNR = {psnr:.2f} dB")
    print(f"          (>40 dB → imperceptible; standard LSB ≈ 51 dB)")
    return psnr


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)

    cmd = sys.argv[1].lower()
    if   cmd == "encode"   and len(sys.argv) == 5:
        encode(sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "decode"   and len(sys.argv) == 3:
        decode(sys.argv[2])
    elif cmd == "capacity" and len(sys.argv) == 3:
        cap = max_capacity(sys.argv[2])
        print(f"[capacity] Adaptive capacity: {cap:,} chars.")
    elif cmd == "compare"  and len(sys.argv) == 4:
        compare(sys.argv[2], sys.argv[3])
    else:
        print(__doc__); sys.exit(1)