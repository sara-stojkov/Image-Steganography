"""
lsb_file_stego.py — Binary File LSB Steganography
--------------------------------------------------
Extends the standard LSB method to embed *any file* (CSV, JSON, PDF, ZIP …)
into a PNG image as raw bytes, preserving the exact binary content.

Payload layout inside the image (all at depth-1 LSB):
    [0..7]      1 byte  — filename length  (uint8,  max 255 chars)
    [8..N]      filename bytes             (UTF-8)
    [N..N+31]   4 bytes — file size        (uint32 big-endian, max ~512 MB)
    [N+32..]    raw file bytes

This means the decoder can reconstruct the original file with its original
name, without any out-of-band metadata.

Capacity:
    max_file_bytes = ⌊(3 × W × H) / 8⌋  −  1  −  len(filename)  −  4

Usage (CLI):
    python lsb_file_stego.py encode  cover.png  stego.png  secret.csv
    python lsb_file_stego.py decode  stego.png  [output_dir]
    python lsb_file_stego.py capacity cover.png  secret.csv
"""

import sys
import struct
from pathlib import Path
from PIL import Image


#  Core bit helpers

def _bytes_to_bits(data: bytes) -> list:
    bits = []
    for byte in data:
        for shift in range(7, -1, -1):
            bits.append((byte >> shift) & 1)
    return bits


def _bits_to_bytes(bits: list) -> bytes:
    out = bytearray()
    for i in range(0, len(bits), 8):
        byte = 0
        for bit in bits[i : i + 8]:
            byte = (byte << 1) | bit
        out.append(byte)
    return bytes(out)


#  Capacity check

def max_file_bytes(image_path: str, filename: str = "") -> int:
    """
    Return how many raw bytes can be hidden in the image.
    Pass *filename* to account for the header overhead of that specific name.
    """
    with Image.open(image_path) as img:
        w, h = img.size
    total_lsb_bits  = 3 * w * h
    overhead_bits   = (1 + len(filename.encode("utf-8")) + 4) * 8
    return (total_lsb_bits - overhead_bits) // 8


#  Encode

def encode(image_path: str, output_path: str, file_path: str) -> None:
    """
    Embed the file at *file_path* into *image_path*, saving to *output_path*.

    Raises:
        IOError    — if output is JPEG or file is too large.
        ValueError — if the file doesn't fit.
    """
    output_path = Path(output_path)
    if output_path.suffix.lower() in (".jpg", ".jpeg"):
        raise IOError("Output must be lossless (PNG or BMP).")

    file_path   = Path(file_path)
    filename    = file_path.name
    file_data   = file_path.read_bytes()

    fname_bytes = filename.encode("utf-8")
    if len(fname_bytes) > 255:
        raise ValueError("Filename too long (max 255 UTF-8 bytes).")

    capacity = max_file_bytes(image_path, filename)
    if len(file_data) > capacity:
        raise ValueError(
            f"File too large: {len(file_data):,} bytes, "
            f"but image can hold {capacity:,} bytes."
        )

    # ── Build payload ──
    header = (
        bytes([len(fname_bytes)])       # 1 byte: filename length
        + fname_bytes                   # variable: filename
        + struct.pack(">I", len(file_data))  # 4 bytes: file size
    )
    payload_bits = _bytes_to_bits(header + file_data)

    # ── Load image and embed ──
    with Image.open(image_path).convert("RGB") as img:
        width, height = img.size
        pixels = list(img.getdata())  # Pillow ≥14: replace with list(img.get_flattened_data())  # type: ignore

    new_pixels = []
    bit_index  = 0
    total_bits = len(payload_bits)

    for r, g, b in pixels:
        if bit_index < total_bits:
            r = (r & ~1) | payload_bits[bit_index]; bit_index += 1
        if bit_index < total_bits:
            g = (g & ~1) | payload_bits[bit_index]; bit_index += 1
        if bit_index < total_bits:
            b = (b & ~1) | payload_bits[bit_index]; bit_index += 1
        new_pixels.append((r, g, b))

    out_img = Image.new("RGB", (width, height))
    out_img.putdata(new_pixels)
    out_img.save(str(output_path))

    pct = len(payload_bits) / (3 * width * height) * 100
    print(f"[encode-file] Done.")
    print(f"  Embedded : '{filename}'  ({len(file_data):,} bytes)")
    print(f"  Output   : '{output_path}'")
    print(f"  LSB used : {len(payload_bits):,} / {3 * width * height:,}  ({pct:.2f}%)")


#  Decode

def decode(stego_path: str, output_dir: str = ".") -> Path:
    """
    Extract the hidden file from *stego_path* and write it to *output_dir*.
    Returns the path of the reconstructed file.
    """
    with Image.open(stego_path).convert("RGB") as img:
        pixels = list(img.getdata())  # Pillow ≥14: replace with list(img.get_flattened_data())  # type: ignore

    # Collect all LSBs
    lsbs = []
    for r, g, b in pixels:
        lsbs.append(r & 1)
        lsbs.append(g & 1)
        lsbs.append(b & 1)

    def read_bytes(bit_offset: int, n_bytes: int) -> tuple:
        """Read n_bytes from lsbs starting at bit_offset. Returns (data, new_offset)."""
        bits = lsbs[bit_offset : bit_offset + n_bytes * 8]
        return _bits_to_bytes(bits), bit_offset + n_bytes * 8

    # ── Parse header ──
    fname_len_bytes, offset = read_bytes(0, 1)
    fname_len  = fname_len_bytes[0]

    fname_bytes, offset = read_bytes(offset, fname_len)
    filename   = fname_bytes.decode("utf-8")

    file_size_bytes, offset = read_bytes(offset, 4)
    file_size  = struct.unpack(">I", file_size_bytes)[0]

    # ── Extract file data ──
    file_bits  = lsbs[offset : offset + file_size * 8]
    file_data  = _bits_to_bytes(file_bits)

    out_path = Path(output_dir) / filename
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(file_data)

    print(f"[decode-file] Extracted '{filename}'  ({file_size:,} bytes) → '{out_path}'")
    return out_path



if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "encode" and len(sys.argv) == 5:
        encode(sys.argv[2], sys.argv[3], sys.argv[4])

    elif cmd == "decode" and len(sys.argv) in (3, 4):
        out_dir = sys.argv[3] if len(sys.argv) == 4 else "."
        decode(sys.argv[2], out_dir)

    elif cmd == "capacity" and len(sys.argv) in (3, 4):
        fname = Path(sys.argv[3]).name if len(sys.argv) == 4 else ""
        cap   = max_file_bytes(sys.argv[2], fname)
        label = f" (accounting for filename '{fname}')" if fname else ""
        print(f"[capacity] '{sys.argv[2]}' can hold {cap:,} bytes{label}.")

    else:
        print(__doc__); sys.exit(1)