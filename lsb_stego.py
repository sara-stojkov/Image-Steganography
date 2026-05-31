"""
lsb_stego.py — Standard LSB (Least Significant Bit) Steganography
------------------------------------------------------------------
Hides a text message inside a PNG image by replacing the LSB of
each colour channel (R, G, B) with one bit of the message.

Layout inside the image:
    bits [0..31]   → 32-bit big-endian unsigned int = message length in chars
    bits [32..]    → UTF-8 encoded message, one bit per LSB slot

Capacity formula:
    max_chars = ⌊(3 × width × height − 32) / 8⌋

Usage (CLI):
    python lsb_stego.py encode  input.png  output.png  "Secret message"
    python lsb_stego.py decode  stego.png
    python lsb_stego.py capacity image.png
"""

import sys
import struct
from pathlib import Path
from PIL import Image


# Helper functions

def _text_to_bits(text: str) -> list[int]:
    """Convert a UTF-8 string to a flat list of bits (MSB first per byte)."""
    bits = []
    for byte in text.encode("utf-8"):
        for shift in range(7, -1, -1):
            bits.append((byte >> shift) & 1)
    return bits


def _bits_to_text(bits: list[int]) -> str:
    """Convert a flat list of bits (MSB first per byte) to a UTF-8 string."""
    raw_bytes = bytearray()
    for i in range(0, len(bits), 8):
        byte = 0
        for bit in bits[i : i + 8]:
            byte = (byte << 1) | bit
        raw_bytes.append(byte)
    return raw_bytes.decode("utf-8")


def max_capacity(image_path: str) -> int:
    """Return the maximum number of UTF-8 characters that fit in the image."""
    with Image.open(image_path) as img:
        w, h = img.size
    return (3 * w * h - 32) // 8


# Encode function

def encode(input_path: str, output_path: str, message: str) -> None:
    """
    Embed *message* into the image at *input_path* and save to *output_path*.

    Raises:
        ValueError  – if the message is too long for the image.
        IOError     – if the output format is lossy (JPEG).
    """
    output_path = Path(output_path)
    if output_path.suffix.lower() in (".jpg", ".jpeg"):
        raise IOError(
            "Output must be a lossless format (PNG, BMP). "
            "JPEG compression destroys LSB data."
        )

    with Image.open(input_path).convert("RGB") as img:
        width, height = img.size
        pixels = list(img.getdata())  # list of (R, G, B) tuples

    # ── Build the full payload: 32-bit length header + message bits ──
    msg_bytes = message.encode("utf-8")
    msg_len   = len(msg_bytes)

    capacity_chars = (3 * width * height - 32) // 8
    if msg_len > capacity_chars:
        raise ValueError(
            f"Message too long: {msg_len} chars, "
            f"but this image holds at most {capacity_chars} chars."
        )

    header_bits = []
    length_packed = struct.pack(">I", msg_len)   # big-endian uint32
    for byte in length_packed:
        for shift in range(7, -1, -1):
            header_bits.append((byte >> shift) & 1)

    message_bits = _text_to_bits(message)
    payload      = header_bits + message_bits    # total bits to embed

    # ── Embed payload into pixels ──
    new_pixels = []
    bit_index  = 0
    payload_len = len(payload)

    for r, g, b in pixels:
        if bit_index < payload_len:
            r = (r & ~1) | payload[bit_index];     bit_index += 1
        if bit_index < payload_len:
            g = (g & ~1) | payload[bit_index];     bit_index += 1
        if bit_index < payload_len:
            b = (b & ~1) | payload[bit_index];     bit_index += 1
        new_pixels.append((r, g, b))

    # ── Save result ──
    out_img = Image.new("RGB", (width, height))
    out_img.putdata(new_pixels)
    out_img.save(str(output_path))

    print(f"[encode] Done. Embedded {msg_len} char(s) into '{output_path}'.")
    print(f"         Used {len(payload)} / {3 * width * height} LSB slots "
          f"({len(payload) / (3 * width * height) * 100:.2f}%).")


# Decode function

def decode(stego_path: str) -> str:
    """
    Extract and return the hidden message from *stego_path*.

    Raises:
        ValueError – if the embedded length header looks corrupt.
    """
    with Image.open(stego_path).convert("RGB") as img:
        pixels = list(img.getdata())
        width, height = img.size

    max_bits = 3 * width * height

    # ── Read all LSBs into one flat list ──
    lsbs = []
    for r, g, b in pixels:
        lsbs.append(r & 1)
        lsbs.append(g & 1)
        lsbs.append(b & 1)

    # ── Parse 32-bit length header ──
    if max_bits < 32:
        raise ValueError("Image too small to contain a valid header.")

    length_bits = lsbs[:32]
    length_byte = 0
    for bit in length_bits:
        length_byte = (length_byte << 1) | bit
    msg_len = struct.unpack(">I", length_byte.to_bytes(4, "big"))[0]

    needed_bits = 32 + msg_len * 8
    if needed_bits > max_bits:
        raise ValueError(
            f"Header claims {msg_len} chars, but the image can only hold "
            f"{(max_bits - 32) // 8} chars. Image may not contain a message."
        )

    # ── Extract message bits ──
    message_bits = lsbs[32 : 32 + msg_len * 8]
    message      = _bits_to_text(message_bits)

    print(f"[decode] Found message ({msg_len} char(s)): {message!r}")
    return message


def _usage():
    print(__doc__)
    sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        _usage()

    cmd = sys.argv[1].lower()

    if cmd == "encode" and len(sys.argv) == 5:
        encode(sys.argv[2], sys.argv[3], sys.argv[4])

    elif cmd == "decode" and len(sys.argv) == 3:
        decode(sys.argv[2])

    elif cmd == "capacity" and len(sys.argv) == 3:
        cap = max_capacity(sys.argv[2])
        print(f"[capacity] '{sys.argv[2]}' can hold up to {cap:,} characters.")

    else:
        _usage()