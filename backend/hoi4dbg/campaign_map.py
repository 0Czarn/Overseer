"""The game's map for the Game summary campaign map (2026-10-21, user's request: "automatically the game's map, also
from mods"): the files are taken as the game loads them - the game folder, then the mods it runs with (a later root's
file replaces the earlier one, replace_path drops the folder of the roots before it, gamefiles.merged_files).

- raster(): map/provinces.bmp scaled down, each pixel = the state its province belongs to (history/states), written as a
  PNG the renderer decodes: red = state id >> 8, green = state id & 255, blue = LAND (state), SEA, LAKE or NO_STATE.
  Built once per set of files (numpy) and cached in the app's data folder.
- states(): {state id: {"provinces", "vp", "name_key"}} - victory points of a state = the sum of its provinces'.
- country_colors(): {tag: "#rrggbb"} - common/countries/colors.txt (what the map uses), else the country file's colour.
"""

from __future__ import annotations

import colorsys
import hashlib
import re
import struct
import zlib
from functools import lru_cache
from pathlib import Path

from . import gamefiles

LAND, SEA, LAKE, NO_STATE = 255, 0, 1, 2
STEP = 2   # map pixels per raster pixel (5632 x 2048 -> 2816 x 1024)
CACHE_VERSION = 1

STATE_ID = re.compile(r"\bid\s*=\s*(\d+)")
STATE_NAME = re.compile(r'\bname\s*=\s*"([^"]+)"')
STATE_PROVINCES = re.compile(r"\bprovinces\s*=\s*\{([^}]*)\}")
VICTORY_POINTS = re.compile(r"\bvictory_points\s*=\s*\{\s*(\d+)\s+(-?[\d.]+)\s*\}")
TAG_FILE = re.compile(r'^\s*([A-Z][A-Z0-9]{2})\s*=\s*"([^"]+)"', re.M)
COLOR = re.compile(r"\bcolor\s*=\s*(rgb|RGB|hsv|HSV)?\s*\{\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\}")
COLORS_ENTRY = re.compile(r"^\s*([A-Z][A-Z0-9]{2})\s*=\s*\{", re.M)
STATE_NAME_LINE = re.compile(r'^\s*(STATE_\d+):\d*\s*"(.*)"', re.M)


def _strip(text: str) -> str:
    return re.sub(r"#[^\n]*", "", text)


def last_file(roots, rel: str) -> Path | None:
    """The file `rel` (e.g. map/provinces.bmp) as the game loads it: the last root that has it (replace_path of a mod
    hides the folder in the roots before it, but the map folder is replaced by files, not by replace_path)."""
    found = None
    for root in roots:
        path = Path(root) / rel
        if path.is_file():
            found = path
    return found


def states(roots) -> dict[int, dict]:
    return dict(_states(tuple(map(str, roots))))


@lru_cache(maxsize=4)
def _states(roots: tuple[str, ...]) -> tuple:
    out = {}
    for path in gamefiles.merged_files(roots, "history/states"):
        text = _strip(path.read_text(encoding="utf-8-sig", errors="replace"))
        sid, name, provs = STATE_ID.search(text), STATE_NAME.search(text), STATE_PROVINCES.search(text)
        if not sid:
            continue
        vp = sum(float(v) for _p, v in VICTORY_POINTS.findall(text))
        out[int(sid.group(1))] = {"name_key": name.group(1) if name else None, "vp": round(vp, 2),
                                  "provinces": [int(x) for x in provs.group(1).split() if x.isdigit()] if provs else []}
    return tuple(out.items())


def state_names(roots, lang: str = "english") -> dict[str, str]:
    """STATE_<n> -> localised name from every root's localisation (a later root wins)."""
    names: dict[str, str] = {}
    for root in roots:
        folder = Path(root) / "localisation"
        for path in sorted(folder.rglob(f"*_l_{lang}.yml")) if folder.is_dir() else []:
            if "state" not in path.name.lower():
                continue
            try:
                names.update(STATE_NAME_LINE.findall(path.read_text(encoding="utf-8-sig", errors="replace")))
            except OSError:
                continue
    return names


def _hex(kind: str | None, a: float, b: float, c: float) -> str:
    if kind and kind.lower() == "hsv":
        a, b, c = (round(x * 255) for x in colorsys.hsv_to_rgb(min(a, 1), min(b, 1), min(c, 1)))
    elif max(a, b, c) <= 1 and any(isinstance(x, float) and x % 1 for x in (a, b, c)):   # 0..1 floats
        a, b, c = (round(x * 255) for x in (a, b, c))
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(x))) for x in (a, b, c))


def country_colors(roots) -> dict[str, str]:
    return dict(_country_colors(tuple(map(str, roots))))


@lru_cache(maxsize=4)
def _country_colors(roots: tuple[str, ...]) -> tuple:
    out: dict[str, str] = {}
    for path in gamefiles.merged_files(roots, "common/country_tags"):
        for tag, rel in TAG_FILE.findall(_strip(path.read_text(encoding="utf-8-sig", errors="replace"))):
            country = last_file(roots, f"common/{rel}")
            m = COLOR.search(_strip(country.read_text(encoding="utf-8-sig", errors="replace"))) if country else None
            if m:
                out[tag] = _hex(m.group(1), *(float(m.group(i)) for i in (2, 3, 4)))
    colors = last_file(roots, "common/countries/colors.txt")
    if colors:
        text = _strip(colors.read_text(encoding="utf-8-sig", errors="replace"))
        entries = list(COLORS_ENTRY.finditer(text))
        for i, e in enumerate(entries):
            block = text[e.end():entries[i + 1].start() if i + 1 < len(entries) else len(text)]
            m = COLOR.search(block)
            if m:
                out[e.group(1)] = _hex(m.group(1), *(float(m.group(i)) for i in (2, 3, 4)))
    return tuple(out.items())


def _province_kinds(definition: Path) -> tuple[dict[int, int], dict[int, str]]:
    """({rgb colour: province id}, {province id: land / sea / lake}) of map/definition.csv."""
    colours, kinds = {}, {}
    for line in definition.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        parts = line.split(";")
        if len(parts) < 5 or not parts[0].strip().isdigit():
            continue
        try:
            pid, r, g, b = (int(parts[i]) for i in range(4))
        except ValueError:
            continue
        if pid == 0:
            continue
        colours[(r << 16) | (g << 8) | b] = pid
        kinds[pid] = parts[4].strip()
    return colours, kinds


def png(width: int, height: int, rgb: bytes) -> bytes:
    """A truecolour PNG of `rgb` (rows top to bottom, 3 bytes a pixel)."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    stride = width * 3
    raw = b"".join(b"\0" + rgb[y * stride:(y + 1) * stride] for y in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def _key(roots) -> tuple[str, Path, Path]:
    """(cache key, provinces.bmp, definition.csv) - the files and the states the raster is made of."""
    bmp, definition = last_file(roots, "map/provinces.bmp"), last_file(roots, "map/definition.csv")
    if bmp is None or definition is None:
        raise FileNotFoundError("map/provinces.bmp or map/definition.csv not found in the game or its mods")
    parts = [str(CACHE_VERSION), str(STEP)]
    for f in (bmp, definition, *gamefiles.merged_files(roots, "history/states")):
        st = f.stat()
        parts.append(f"{f}:{st.st_size}:{int(st.st_mtime)}")
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16], bmp, definition


def raster(roots, cache_dir: Path | None = None) -> dict:
    """{"width", "height", "png", "key"} of the state map (see the module text); cached in `cache_dir`."""
    roots = [str(r) for r in roots]
    key, bmp, definition = _key(roots)
    cache = Path(cache_dir) / f"campaign_map_{key}.png" if cache_dir else None
    if cache and cache.is_file():
        data = cache.read_bytes()
        width, height = struct.unpack(">II", data[16:24])
        return {"width": width, "height": height, "png": data, "key": key}
    import numpy as np
    raw = bmp.read_bytes()
    if raw[:2] != b"BM":
        raise ValueError("provinces.bmp is not a BMP file")
    offset = struct.unpack_from("<I", raw, 10)[0]
    width, height = struct.unpack_from("<ii", raw, 18)
    bits, compression = struct.unpack_from("<HI", raw, 28)
    if bits != 24 or compression != 0:
        raise ValueError("provinces.bmp is not an uncompressed 24-bit BMP")
    bottom_up, height = height > 0, abs(height)
    stride = (width * 3 + 3) & ~3
    rows = np.frombuffer(raw, dtype=np.uint8, count=stride * height, offset=offset).reshape(height, stride)
    if bottom_up:
        rows = rows[::-1]
    px = rows[STEP // 2::STEP, :width * 3].reshape(-1, width, 3)[:, STEP // 2::STEP].astype(np.uint32)
    colour = (px[:, :, 2] << 16) | (px[:, :, 1] << 8) | px[:, :, 0]   # BMP stores blue, green, red
    colours, kinds = _province_kinds(definition)
    state_of = {p: sid for sid, s in states(roots).items() for p in s["provinces"]}
    uniq, inverse = np.unique(colour, return_inverse=True)
    sid = np.zeros(len(uniq), dtype=np.uint32)
    kind = np.full(len(uniq), NO_STATE, dtype=np.uint8)
    for i, c in enumerate(uniq.tolist()):
        pid = colours.get(c)
        s = state_of.get(pid) if pid else None
        if s:
            sid[i], kind[i] = s, LAND
        elif pid and kinds.get(pid) == "sea":
            kind[i] = SEA
        elif pid and kinds.get(pid) == "lake":
            kind[i] = LAKE
    inverse = inverse.reshape(colour.shape)
    ids, kd = sid[inverse], kind[inverse]
    out = np.stack([(ids >> 8) & 255, ids & 255, kd], axis=2).astype(np.uint8)
    h, w = out.shape[:2]
    data = png(w, h, out.tobytes())
    if cache:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            for old in cache.parent.glob("campaign_map_*.png"):   # another map before (other mods)
                old.unlink(missing_ok=True)
            cache.write_bytes(data)
        except OSError:
            pass
    return {"width": w, "height": h, "png": data, "key": key}
