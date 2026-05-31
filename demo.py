"""
demo.py — End-to-end demonstration of both LSB steganography implementations
----------------------------------------------------------------------------
Generates synthetic test images, encodes messages, decodes them, and prints
a capacity/PSNR report. Run this to verify everything works before your demo.

    python demo.py

Requires: Pillow  (pip install Pillow)
"""

import math
import struct
from PIL import Image, ImageDraw, ImageFont

import lsb_stego            as std
import lsb_stego_optimized  as opt


def make_sample_images():
    """Generate three simple test images (gradient, checkerboard, photo-like)."""

    # 1. Smooth gradient – worst case for adaptive (all smooth → depth=1)
    img = Image.new("RGB", (400, 300))
    pix = img.load()
    for y in range(300):
        for x in range(400):
            v = int(x / 400 * 200 + y / 300 * 55)
            pix[x, y] = (v, v // 2 + 30, 255 - v)
    img.save("sample_gradient.png")
    print("Created: sample_gradient.png")

    # 2. High-frequency checkerboard – best case for adaptive (all edges → depth=3)
    img = Image.new("RGB", (400, 300))
    pix = img.load()
    for y in range(300):
        for x in range(400):
            if (x // 8 + y // 8) % 2 == 0:
                pix[x, y] = (220, 220, 220)
            else:
                pix[x, y] = (30, 30, 30)
    img.save("sample_checker.png")
    print("Created: sample_checker.png")

    # 3. Mixed (gradient background + hard shapes)
    img = Image.new("RGB", (400, 300), color=(180, 200, 230))
    draw = ImageDraw.Draw(img)
    draw.rectangle([50, 50, 350, 250], outline=(20, 20, 20), width=4)
    draw.ellipse([120, 90, 280, 210], fill=(240, 120, 40))
    draw.line([0, 0, 400, 300], fill=(10, 10, 10), width=3)
    img.save("sample_mixed.png")
    print("Created: sample_mixed.png")


DEMOS = [
    {
        "image":   "sample_gradient.png",
        "message": "Steganography hides the existence of a message, not just its content.",
    },
    {
        "image":   "sample_checker.png",
        "message": (
            "Ada je rekla: 'Svaki piksel čuva tajnu.' "
            "Adaptive LSB koristi ivice slike da sakrije više podataka. "
            "Ovo je duža poruka za testiranje kapaciteta."
        ),
    },
    {
        "image":   "sample_mixed.png",
        "message": "Mixed-content image: adaptive depth varies across regions. 🔐",
    },
]


def run_demo(demo: dict, idx: int):
    image   = demo["image"]
    message = demo["message"]
    print(f"\n{'═'*62}")
    print(f"  Demo {idx + 1}: {image}")
    print(f"{'═'*62}")

    # ── Standard LSB ──
    std_out = f"stego_std_{idx + 1}.png"
    print(f"\n── Standard LSB ──")
    std.encode(image, std_out, message)
    decoded_std = std.decode(std_out)
    assert decoded_std == message, "Standard decode mismatch!"
    print("  ✓ Decoded message matches original.")
    opt.compare(image, std_out)
    cap_std = std.max_capacity(image)
    print(f"  Capacity: {cap_std:,} chars")

    # ── Adaptive LSB ──
    adp_out = f"stego_adp_{idx + 1}.png"
    print(f"\n── Adaptive LSB ──")
    opt.encode(image, adp_out, message)
    decoded_adp = opt.decode(adp_out)
    assert decoded_adp == message, "Adaptive decode mismatch!"
    print("  ✓ Decoded message matches original.")
    opt.compare(image, adp_out)
    cap_adp = opt.max_capacity(image)
    print(f"  Capacity: {cap_adp:,} chars")


def capacity_formula_demo():
    print(f"\n{'═'*62}")
    print("  Capacity formula: ⌊(3 × W × H − 32) / 8⌋")
    print(f"{'═'*62}")
    examples = [
        ("400×300 (test)",  400,  300),
        ("1280×720 (HD)",  1280,  720),
        ("1920×1080 (FHD)", 1920, 1080),
        ("3840×2160 (4K)",  3840, 2160),
    ]
    print(f"  {'Resolution':<22}  {'Std LSB chars':>14}")
    print(f"  {'-'*22}  {'-'*14}")
    for label, w, h in examples:
        cap = (3 * w * h - 32) // 8
        print(f"  {label:<22}  {cap:>14,}")


if __name__ == "__main__":
    make_sample_images()

    for i, demo in enumerate(DEMOS):
        run_demo(demo, i)

    capacity_formula_demo()

    print("\n✓ All demos passed.\n")