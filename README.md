# 🔏 LSB Image Steganography

A Python implementation of **Least Significant Bit (LSB) steganography** — hiding secret text messages inside PNG images with no visible change to the human eye.

Built as a faculty project demonstrating both a standard LSB implementation and an optimised adaptive variant based on Pixel Value Differencing (PVD) principles.

---

## What is steganography?

Steganography is the art of hiding the *existence* of a message, not just its content. Unlike cryptography (which makes a message unreadable), steganography makes the message invisible — a potential observer has no reason to look for it in the first place.

The word comes from the Greek *steganos* (covered) + *graphein* (to write).

In digital images, the **LSB method** works by replacing the least significant bit of each colour channel (R, G, B) with one bit of the secret message. Changing a pixel's value by ±1 is completely imperceptible to the human eye.

---

## Project structure

```
├── lsb_stego.py             # Standard LSB — clean, minimal, easy to follow
├── lsb_stego_optimized.py   # Adaptive LSB with PVD-weighted depth selection
├── demo.py                  # End-to-end demo: generates test images, encodes, decodes, reports PSNR
└── README.md
```

---

## Requirements

Python 3.10+ and [Pillow](https://pillow.readthedocs.io/):

```bash
pip install Pillow
```

---

## Quick start

### Standard LSB

```bash
# Hide a message
python lsb_stego.py encode  original.png  stego.png  "This is a secret"

# Recover the message
python lsb_stego.py decode  stego.png

# Check how many characters fit in an image
python lsb_stego.py capacity original.png
```

### Adaptive LSB

```bash
python lsb_stego_optimized.py encode   original.png  stego.png  "This is a secret"
python lsb_stego_optimized.py decode   stego.png
python lsb_stego_optimized.py capacity original.png
python lsb_stego_optimized.py compare  original.png  stego.png   # prints PSNR
```

### Run the full demo

```bash
python demo.py
```

Generates three test images (gradient, checkerboard, mixed), encodes messages into each using both algorithms, decodes them, and prints a capacity + PSNR report.

---

## How it works

### Standard LSB (`lsb_stego.py`)

**Encoding**

1. Convert the message to UTF-8 bytes, then to a flat list of bits.
2. Prepend a 32-bit big-endian header containing the message length in bytes.
3. Walk through every pixel left-to-right, top-to-bottom, replacing the LSB of R, G, B with successive payload bits.
4. Save as PNG (lossless — JPEG compression would destroy the embedded bits).

**Decoding**

1. Read the LSB of every channel into a flat bit array.
2. Parse the first 32 bits as the message length `L`.
3. Read the next `L × 8` bits and decode as UTF-8.

**Capacity formula**

```
max_chars = ⌊(3 × width × height − 32) / 8⌋
```

| Resolution    | Max characters |
|---------------|---------------:|
| 400 × 300     |         44,996 |
| 1280 × 720    |        345,596 |
| 1920 × 1080   |        777,596 |
| 3840 × 2160   |      3,110,396 |

A Full HD image can hide roughly **780,000 characters** — the size of a short novel — with no visible artefacts.

---

### Adaptive LSB (`lsb_stego_optimized.py`)

The standard method always uses one bit per channel. This variant uses **1, 2, or 3 bits** depending on local contrast.

The human visual system is less sensitive to noise in high-contrast (edge) areas, so more bits can be embedded there without the change becoming visible.

**Depth assignment**

For each pixel, the mean absolute luminance difference to its four cardinal neighbours is computed:

| Contrast range       | Embedding depth | Bits per pixel |
|----------------------|:---------------:|:--------------:|
| `< 20` (smooth)      | 1               | 3              |
| `20 – 60` (moderate) | 2               | 6              |
| `≥ 60` (strong edge) | 3               | 9              |

**Robust decoding via embedded depth map**

Re-computing the depth map from a *modified* stego image can give slightly different results at edge boundaries — causing decode errors. This implementation avoids that problem by serialising the depth map into the header:

```
[0..31]           32-bit length header         (always depth-1)
[32..32+2P−1]     2 bits per pixel depth map   (always depth-1)
[32+2P..]         message bits                 (adaptive depth)
```

The decoder reads the depth map from the header itself, making decoding fully deterministic and independent of re-computation.

**When is it better than standard LSB?**

On real photographs with lots of edges and texture (e.g. nature, cityscapes, portraits), the adaptive method typically achieves **1.5–2× the capacity** of standard LSB while maintaining higher PSNR in smooth regions. On synthetic smooth-gradient images it underperforms standard LSB because the depth-1 header overhead dominates — but those are not realistic cover images.

---

## Steganalysis (recovering the message)

If you know the encoding convention (which in a real attack scenario would have to be guessed or inferred), recovering the message is straightforward:

```python
from lsb_stego import decode

message = decode("suspicious_image.png")
print(message)
```

The 32-bit length header is the key assumption. Without knowing its format an attacker must also guess how many bits to read. With it, extraction is deterministic and takes milliseconds.

### Visual detection

While the naked eye cannot distinguish a stego image from the original, statistical tests can. Chi-square analysis of LSB distributions often reveals non-random patterns caused by the embedding. Dedicated tools like **StegExpose** or **zsteg** automate this detection.

---

## Image quality — PSNR

Peak Signal-to-Noise Ratio measures how different the stego image is from the original:

```
PSNR = 10 × log₁₀(255² / MSE)   [dB]
```

| PSNR range | Perception                           |
|------------|--------------------------------------|
| > 40 dB    | Difference is imperceptible          |
| 30–40 dB   | Minor artefacts, barely noticeable   |
| < 30 dB    | Visible degradation                  |

Standard LSB on a message that fills < 1% of the image typically yields **> 70 dB**.

---

## Important: always use lossless formats

The output file **must** be PNG or BMP. JPEG compression rounds pixel values and destroys the embedded LSB bits. If you save a stego PNG as JPEG the message will be lost.

---

## Limitations

- **No encryption** — the message is hidden but not encrypted. Combine with a cipher (e.g. AES) for real security.
- **Fragile to compression, resizing, and colour-space conversion** — any post-processing that changes pixel values will corrupt the payload.
- **Detectable by statistical analysis** — a determined analyst with the right tools can detect that LSB embedding has taken place, even without recovering the content.
