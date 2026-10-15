"""Game icons: sprite names (interface/*.gfx) -> texture files, and DDS -> PNG (standard library only).

Idea icons of 1.19.3 are uncompressed 32-bit DDS (7 000+ files checked 2026-10-10), large leader portraits 16-bit
X1R5G5B5; any uncompressed 16/24/32-bit layout is decoded through its channel masks. Compressed (DXT) textures are
not decoded and return None.
"""

from __future__ import annotations

import base64
import re
import struct
import zlib
from functools import lru_cache
from pathlib import Path

SPRITE_RE = re.compile(r'name\s*=\s*"?(GFX_[A-Za-z0-9_.\-]+)"?\s*(?:#[^\n]*)?\s*texturefile\s*=\s*"([^"]+)"', re.I)
MAX_SIDE = 512


@lru_cache(maxsize=2)
def sprites(roots: tuple[str, ...]) -> dict[str, str]:
    """{sprite name: absolute texture path}; later roots (mods) override."""
    out: dict[str, str] = {}
    for root in map(Path, roots):
        for path in sorted((root / "interface").rglob("*.gfx")):
            src = path.read_text(encoding="utf-8-sig", errors="replace")
            for name, texture in SPRITE_RE.findall(src):
                out[name] = str(root / texture.replace("\\", "/"))
    return out


FRAMES_RE = re.compile(r'name\s*=\s*"?(GFX_[A-Za-z0-9_.\-]+)"?[^{}]*?noOfFrames\s*=\s*(\d+)', re.I)


@lru_cache(maxsize=2)
def sprite_frames(roots: tuple[str, ...]) -> dict[str, int]:
    """{sprite name: noOfFrames} of the sprites that are horizontal strips (unit icons: 2 - normal and white)."""
    out: dict[str, int] = {}
    for root in map(Path, roots):
        for path in sorted((root / "interface").rglob("*.gfx")):
            src = path.read_text(encoding="utf-8-sig", errors="replace")
            out.update((name, int(n)) for name, n in FRAMES_RE.findall(src))
    return out


def sprite_uri(roots: tuple[str, ...], name: str) -> str | None:
    """data: URI of a sprite's first frame."""
    texture = sprites(roots).get(name)
    if not texture:
        return None
    frames = sprite_frames(roots).get(name, 1)
    return frame_data_uri(texture, 1, frames) if frames > 1 else icon_data_uri(texture)


def _png(width: int, height: int, rgba: bytes) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    rows = b"".join(b"\x00" + rgba[y * width * 4:(y + 1) * width * 4] for y in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b""))


def dds_to_png(data: bytes) -> bytes | None:
    """Uncompressed 16/24/32-bit DDS (channel order and widths from its masks) -> PNG bytes; None otherwise."""
    decoded = _dds_rgba(data, MAX_SIDE)
    return _png(*decoded) if decoded else None


def _dds_rgba(data: bytes, max_side: int) -> tuple[int, int, bytes] | None:
    """(width, height, RGBA bytes) of an uncompressed 16/24/32-bit DDS; None otherwise."""
    if len(data) < 128 or data[:4] != b"DDS ":
        return None
    height, width = struct.unpack_from("<II", data, 12)
    pf_flags, fourcc, bits, rm, gm, bm, am = struct.unpack_from("<I4sIIIII", data, 80)
    if pf_flags & 0x4 and fourcc in (b"DXT1", b"DXT3", b"DXT5") and 0 < width <= max_side and 0 < height <= max_side:
        return _dxt_rgba(data[128:], width, height, fourcc)
    if pf_flags & 0x4 or bits not in (16, 24, 32) or not (0 < width <= max_side and 0 < height <= max_side):
        return None
    if not (pf_flags & 0x1):   # DDPF_ALPHAPIXELS not set: the alpha mask is not used
        am = 0
    size = bits // 8
    pixels = data[128:128 + width * height * size]
    if len(pixels) < width * height * size:
        return None
    channels = []
    for mask in (rm, gm, bm, am):
        shift = (mask & -mask).bit_length() - 1 if mask else 0
        top = (mask >> shift) if mask else 0
        channels.append((mask, shift, top))
    out = bytearray(width * height * 4)
    for i in range(width * height):
        v = int.from_bytes(pixels[i * size:(i + 1) * size], "little")
        for c, (mask, shift, top) in enumerate(channels):
            out[i * 4 + c] = ((v & mask) >> shift) * 255 // top if mask else 0xFF
    return width, height, bytes(out)


def _rgb565(c: int) -> tuple[int, int, int]:
    return ((c >> 11) & 31) * 255 // 31, ((c >> 5) & 63) * 255 // 63, (c & 31) * 255 // 31


def _dxt_rgba(blocks: bytes, width: int, height: int, fourcc: bytes) -> tuple[int, int, bytes] | None:
    """(width, height, RGBA) of a block-compressed DDS (DXT1 / DXT3 / DXT5, 4x4 pixel blocks; the mod icons)."""
    size = 8 if fourcc == b"DXT1" else 16
    bw, bh = (width + 3) // 4, (height + 3) // 4
    if len(blocks) < bw * bh * size:
        return None
    out = bytearray(width * height * 4)
    pos = 0
    for by in range(bh):
        for bx in range(bw):
            block = blocks[pos:pos + size]
            pos += size
            alpha = [255] * 16
            if fourcc == b"DXT3":
                bits = int.from_bytes(block[:8], "little")
                alpha = [((bits >> (4 * i)) & 15) * 17 for i in range(16)]
            elif fourcc == b"DXT5":
                a0, a1 = block[0], block[1]
                table = [a0, a1] + ([((7 - i) * a0 + i * a1) // 7 for i in range(1, 7)] if a0 > a1
                                    else [((5 - i) * a0 + i * a1) // 5 for i in range(1, 5)] + [0, 255])
                bits = int.from_bytes(block[2:8], "little")
                alpha = [table[(bits >> (3 * i)) & 7] for i in range(16)]
            color = block[size - 8:]
            c0, c1 = struct.unpack_from("<HH", color)
            p0, p1 = _rgb565(c0), _rgb565(c1)
            if c0 > c1 or fourcc != b"DXT1":
                palette = [p0, p1, tuple((2 * a + b) // 3 for a, b in zip(p0, p1)), tuple((a + 2 * b) // 3 for a, b in zip(p0, p1))]
                opaque = [True] * 4
            else:
                palette = [p0, p1, tuple((a + b) // 2 for a, b in zip(p0, p1)), (0, 0, 0)]
                opaque = [True, True, True, False]
            idx = struct.unpack_from("<I", color, 4)[0]
            for i in range(16):
                x, y = bx * 4 + i % 4, by * 4 + i // 4
                if x >= width or y >= height:
                    continue
                k = (idx >> (2 * i)) & 3
                o = (y * width + x) * 4
                out[o:o + 3] = bytes(palette[k])
                out[o + 3] = alpha[i] if opaque[k] else 0
    return width, height, bytes(out)


@lru_cache(maxsize=4096)
def icon_data_uri(texture: str) -> str | None:
    """data: URI of a texture file (.dds or .png), cached."""
    path = Path(texture)
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if path.suffix.lower() == ".png":
        png = raw
    else:
        png = dds_to_png(raw)
    return "data:image/png;base64," + base64.b64encode(png).decode() if png else None


@lru_cache(maxsize=128)
def frame_data_uri(texture: str, frame: int, frames: int) -> str | None:
    """data: URI of one frame (1-based, as the game's icon_frame) of a horizontal sprite strip of `frames` frames."""
    try:
        decoded = _dds_rgba(Path(texture).read_bytes(), 4096)
    except OSError:
        return None
    if not decoded or not 1 <= frame <= frames:
        return None
    width, height, rgba = decoded
    w = width // frames
    x = (frame - 1) * w
    rows = b"".join(rgba[(y * width + x) * 4:(y * width + x + w) * 4] for y in range(height))
    return "data:image/png;base64," + base64.b64encode(_png(w, height, rows)).decode()
