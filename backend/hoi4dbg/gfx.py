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


def _png(width: int, height: int, rgba: bytes) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    rows = b"".join(b"\x00" + rgba[y * width * 4:(y + 1) * width * 4] for y in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b""))


def dds_to_png(data: bytes) -> bytes | None:
    """Uncompressed 16/24/32-bit DDS (channel order and widths from its masks) -> PNG bytes; None otherwise."""
    if len(data) < 128 or data[:4] != b"DDS ":
        return None
    height, width = struct.unpack_from("<II", data, 12)
    pf_flags, _fourcc, bits, rm, gm, bm, am = struct.unpack_from("<I4sIIIII", data, 80)
    if pf_flags & 0x4 or bits not in (16, 24, 32) or not (0 < width <= MAX_SIDE and 0 < height <= MAX_SIDE):
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
    return _png(width, height, bytes(out))


@lru_cache(maxsize=512)
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
