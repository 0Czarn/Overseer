"""The game's map for the Game summary campaign map (2026-10-21, user's request: "automatically the game's map, also
from mods"): the files are taken as the game loads them - the game folder, then the mods it runs with (a later root's
file replaces the earlier one, replace_path drops the folder of the roots before it, gamefiles.merged_files).

- raster(): map/provinces.bmp scaled down, each pixel = its province (2026-10-22: provinces, not states, so the State
  Editor can draw province borders), written as a PNG the renderer decodes: red = province id >> 8, green = province
  id & 255, blue = LAND, SEA, LAKE or NO_STATE (a colour not in definition.csv); "province_state": the state of each
  province id (0: none). Built once per set of files (numpy) and cached in the app's data folder.
- states(): {state id: {"provinces", "vp", "name_key", "vps": {province id: victory points}}} - victory points of a
  state = the sum of its provinces' (2026-10-23: also per province, for the city names on the campaign map).
- country_colors(): {tag: "#rrggbb"} - common/countries/colors.txt (what the map uses), else the country file's colour.
- borders() (2026-10-23, user's request "sharp edges when zoomed in"): the province outlines as lines - the borders
  between two provinces traced on provinces.bmp (arcs between the corners where 3 or more provinces meet), smoothed
  (the middle of each pixel edge, Douglas-Peucker within BORDER_TOLERANCE pixels) and the rings of arcs around each land
  and lake province; both neighbours draw the same arc, so there is no gap between them. Binary, cached (see borders).
- terrain() (2026-10-23, user's request "terrain like the game, simplified"): the relief - map/heightmap.bmp shaded
  as lit from the north-west, at half size, grey 128 = flat (the renderer blends it soft-light over the colours) - and
  the rivers of map/rivers.bmp as lines (pixel centres, Douglas-Peucker) with their width class.
"""

from __future__ import annotations

import colorsys
import hashlib
import json
import re
import struct
import zlib
from functools import lru_cache
from pathlib import Path

from . import gamefiles

LAND, SEA, LAKE, NO_STATE = 255, 0, 1, 2
STEP = 1   # map pixels per raster pixel (2026-10-23, user's request "a sharper map": the game's 5632 x 2048 whole)
CACHE_VERSION = 3
BORDER_TOLERANCE = 0.5   # pixels a smoothed border may be off the pixel edges
BORDERS_MAGIC = b"OVB1"

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


BUILDINGS_BLOCK = re.compile(r"^buildings\s*=\s*\{", re.M)
TOP_KEY = re.compile(r"^\t?([A-Za-z0-9_]+)\s*=\s*\{", re.M)


def building_types(roots) -> list[str]:
    """Names of the building types in the order the game numbers them (type t = item t - 1): the entries of the
    buildings = { } blocks of common/buildings, files as the game loads them (game, then mods)."""
    return list(_building_types(tuple(map(str, roots))))


@lru_cache(maxsize=4)
def _building_types(roots: tuple[str, ...]) -> tuple:
    out = []
    for path in gamefiles.merged_files(roots, "common/buildings"):
        text = _strip(path.read_text(encoding="utf-8-sig", errors="replace"))
        for block in BUILDINGS_BLOCK.finditer(text):
            depth, i = 1, block.end()
            start = i
            while i < len(text) and depth:   # the block's own entries: depth 1
                c = text[i]
                if c == "{":
                    if depth == 1:
                        m = re.search(r"([A-Za-z0-9_]+)\s*=\s*$", text[start:i])
                        if m:
                            out.append(m.group(1))
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 1:
                        start = i + 1
                i += 1
    return tuple(out)


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
        found = VICTORY_POINTS.findall(text)
        vp = sum(float(v) for _p, v in found)
        out[int(sid.group(1))] = {"name_key": name.group(1) if name else None, "vp": round(vp, 2),
                                  "vps": {int(p): float(v) for p, v in found},
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


def png(width: int, height: int, rgb: bytes, channels: int = 3) -> bytes:
    """A truecolour PNG of `rgb` (rows top to bottom, 3 bytes a pixel; `channels` 1: grey)."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    stride = width * channels
    raw = b"".join(b"\0" + rgb[y * stride:(y + 1) * stride] for y in range(height))
    kind = 0 if channels == 1 else 2
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, kind, 0, 0, 0))
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


def _province_ids(bmp: Path, colours: dict[int, int]):
    """(height, width) int32 array of the province id of each pixel of provinces.bmp (0: a colour not in
    definition.csv), rows top to bottom."""
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
    uniq, inverse = np.unique(colour, return_inverse=True)
    pid = np.array([p if (p := colours.get(c, 0)) <= 0xFFFF else 0 for c in uniq.tolist()], dtype=np.int32)
    return pid[inverse.reshape(colour.shape)]


def _kind_of(kinds: dict[int, str], top: int):
    """uint8 array: LAND, SEA, LAKE of each province id up to `top`, NO_STATE for the unknown ones (and 0)."""
    import numpy as np
    out = np.full(top + 1, NO_STATE, dtype=np.uint8)
    for pid, k in kinds.items():
        if 0 < pid <= top:
            out[pid] = SEA if k == "sea" else LAKE if k == "lake" else LAND
    return out


def raster(roots, cache_dir: Path | None = None) -> dict:
    """{"width", "height", "png", "key", "province_state"} of the province map (see the module text); the PNG is cached
    in `cache_dir`."""
    roots = [str(r) for r in roots]
    key, bmp, definition = _key(roots)
    state_of = {p: sid for sid, s in states(roots).items() for p in s["provinces"]}
    colours, kinds = _province_kinds(definition)
    top = max(list(kinds) + list(state_of) + [0])
    province_state = [state_of.get(p, 0) for p in range(top + 1)]
    cache = Path(cache_dir) / f"campaign_map_{key}.png" if cache_dir else None
    if cache and cache.is_file():
        data = cache.read_bytes()
        width, height = struct.unpack(">II", data[16:24])
        return {"width": width, "height": height, "png": data, "key": key, "province_state": province_state}
    import numpy as np
    ids = _province_ids(bmp, colours)
    kd = _kind_of(kinds, int(ids.max()))[ids]
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
    return {"width": w, "height": h, "png": data, "key": key, "province_state": province_state}


def _simplify(xy, tol: float):
    """Douglas-Peucker of the points `xy` ((n, 2) array), the first and last one kept."""
    import numpy as np
    n = len(xy)
    if n <= 2:
        return xy
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        if j - i < 2:
            continue
        p, d = xy[i], xy[j] - xy[i]
        seg = xy[i + 1:j] - p
        length = float(np.hypot(d[0], d[1]))
        dist = np.hypot(seg[:, 0], seg[:, 1]) if length == 0 else np.abs(d[0] * seg[:, 1] - d[1] * seg[:, 0]) / length
        k = int(np.argmax(dist))
        if dist[k] > tol:
            keep[i + 1 + k] = True
            stack += [(i, i + 1 + k), (i + 1 + k, j)]
    return xy[keep]


def trace(ids, kind_of, tol: float = BORDER_TOLERANCE) -> tuple[list, dict]:
    """(arcs, rings) of the province map `ids` ((height, width) province ids, 0: none; `kind_of`: kind per id).
    arcs: [(p, q, points)] - a border between provinces p and q (0: outside the map or an unknown colour), p on the
    side where cross(direction, side) > 0 in map pixels (y down), points [(x, y), ...] in half pixels (x 2) from
    corner to corner, or a closed ring (first point = last). Only arcs with a land or lake province on a side.
    rings: {province id: [[arc ref, ...], ...]} of the land and lake provinces - ref i: arc i forwards, ~i: backwards;
    each ring has its province on the same side, so the rings fill it with the non-zero rule (holes included)."""
    import numpy as np
    height, width = ids.shape
    lab = np.zeros((height + 2, width + 2), dtype=np.int32)
    lab[1:-1, 1:-1] = ids
    w1 = width + 1   # corner (x, y) = y * w1 + x
    vy, vx = np.nonzero(lab[1:-1, :-1] != lab[1:-1, 1:])   # (x, y)-(x, y + 1) between pixel x - 1 and x
    hy, hx = np.nonzero(lab[:-1, 1:-1] != lab[1:, 1:-1])   # (x, y)-(x + 1, y) between pixel row y - 1 and y
    a = np.concatenate([vy * w1 + vx, hy * w1 + hx]).astype(np.int64)
    b = np.concatenate([(vy + 1) * w1 + vx, hy * w1 + hx + 1]).astype(np.int64)
    west_south = np.concatenate([lab[vy + 1, vx], lab[hy + 1, hx + 1]])   # the p side going from a to b
    east_north = np.concatenate([lab[vy + 1, vx + 1], lab[hy, hx + 1]])
    n = len(a)
    ends = np.concatenate([a, b])
    edge = np.concatenate([np.arange(n), np.arange(n)])
    order = np.argsort(ends, kind="stable")
    ends, edge = ends[order], edge[order]
    corner, first, count = np.unique(ends, return_index=True, return_counts=True)
    through = first[count == 2]   # a corner of two edges only: the border goes on (3 or 4: provinces meet)
    via_a, via_b = np.full(n, -1, dtype=np.int64), np.full(n, -1, dtype=np.int64)
    for e, other in ((edge[through], edge[through + 1]), (edge[through + 1], edge[through])):
        at_a = a[e] == ends[through]
        via_a[e[at_a]] = other[at_a]
        via_b[e[~at_a]] = other[~at_a]
    la, lb, A, B = via_a.tolist(), via_b.tolist(), a.tolist(), b.tolist()
    ws, en = west_south.tolist(), east_north.tolist()
    kinds = kind_of.tolist()
    seen = bytearray(n)

    def walk(e: int, c: int) -> tuple[int, int, list]:
        p, q = (ws[e], en[e]) if A[e] == c else (en[e], ws[e])
        path = [c]
        while True:
            seen[e] = 1
            c, nxt = (B[e], lb[e]) if A[e] == c else (A[e], la[e])
            path.append(c)
            if nxt < 0 or seen[nxt]:
                return p, q, path
            e = nxt

    raw = []
    for e in range(n):   # from a corner where provinces meet
        if not seen[e] and (la[e] < 0 or lb[e] < 0):
            raw.append(walk(e, A[e] if la[e] < 0 else B[e]))
    for e in range(n):   # closed borders (an island, a province inside another)
        if not seen[e]:
            raw.append(walk(e, A[e]))
    filled = lambda pid: 0 < pid < len(kinds) and kinds[pid] in (LAND, LAKE)
    arcs, ends_of = [], []
    for p, q, path in raw:
        if not (filled(p) or filled(q)):
            continue
        c = np.array(path, dtype=np.int64)
        xy = np.stack([c % w1, c // w1], axis=1).astype(np.float64)
        mid = (xy[:-1] + xy[1:]) / 2
        line = np.vstack([mid, mid[:1]]) if path[0] == path[-1] else np.vstack([xy[:1], mid, xy[-1:]])
        pts = np.rint(_simplify(line, tol) * 2).astype(np.int64)
        arcs.append((p, q, [tuple(x) for x in pts.tolist()]))
        ends_of.append((path[0], path[-1]))
    rings: dict[int, list] = {}
    pieces: dict[int, list] = {}   # province -> [(start corner, end corner, ref)] with the province on the p side
    for i, (p, q, _pts) in enumerate(arcs):
        s, t = ends_of[i]
        if filled(p):
            pieces.setdefault(p, []).append((s, t, i))
        if filled(q):
            pieces.setdefault(q, []).append((t, s, ~i))
    for pid, parts in pieces.items():
        starts: dict[int, list] = {}
        for part in parts:
            starts.setdefault(part[0], []).append(part)
        used = set()
        out = []
        for part in parts:
            if part[2] in used:
                continue
            ring, cur = [], part
            while cur is not None and cur[2] not in used:
                used.add(cur[2])
                ring.append(cur[2])
                cur = next((x for x in starts.get(cur[1], ()) if x[2] not in used), None)
            out.append(ring)
        rings[pid] = out
    return arcs, rings


def encode_borders(width: int, height: int, arcs: list, rings: dict) -> bytes:
    """The binary the renderer reads (lib/mapview.js decodeBorders), little-endian, 4-byte aligned:
    "OVB1", uint32 width, height, arcs, points, ring words; uint32 x (arcs + 1) the first point of each arc;
    uint16 x 2 x arcs the provinces p, q of each arc; uint16 x 2 x points the points
    (half pixels); int32 ring words: per province its id, number of rings, then per ring its length and arc refs."""
    import numpy as np
    offsets = np.zeros(len(arcs) + 1, dtype="<u4")
    np.cumsum([len(pts) for _p, _q, pts in arcs], out=offsets[1:])
    sides = np.array([(p, q) for p, q, _pts in arcs], dtype="<u2").reshape(-1)
    points = np.array([xy for _p, _q, pts in arcs for xy in pts], dtype="<u2").reshape(-1)
    words = []
    for pid in sorted(rings):
        words += [pid, len(rings[pid])]
        for ring in rings[pid]:
            words += [len(ring), *ring]
    head = BORDERS_MAGIC + struct.pack("<5I", width, height, len(arcs), int(offsets[-1]), len(words))
    return (head + offsets.tobytes() + sides.tobytes() + points.tobytes()
            + np.array(words, dtype="<i4").tobytes())


def borders(roots, cache_dir: Path | None = None) -> dict:
    """{"key", "data"}: the province outlines (trace, encode_borders) of the map the game loads, cached in
    `cache_dir` (a few seconds to trace the game's map)."""
    roots = [str(r) for r in roots]
    key, bmp, definition = _key(roots)
    cache = Path(cache_dir) / f"campaign_borders_{key}.bin" if cache_dir else None
    if cache and cache.is_file():
        return {"key": key, "data": cache.read_bytes()}
    colours, kinds = _province_kinds(definition)
    ids = _province_ids(bmp, colours)
    arcs, rings = trace(ids, _kind_of(kinds, max(int(ids.max()), max(kinds, default=0))))
    data = encode_borders(ids.shape[1], ids.shape[0], arcs, rings)
    if cache:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            for old in cache.parent.glob("campaign_borders_*.bin"):
                old.unlink(missing_ok=True)
            cache.write_bytes(data)
        except OSError:
            pass
    return {"key": key, "data": data}


RELIEF_STEP = 2       # map pixels per relief pixel
RELIEF_STRENGTH = 80  # grey levels from flat (128) of the steepest 1% of slopes
TERRAIN_VERSION = 2
RIVER_WIDTHS = range(3, 12)   # rivers.bmp: 0 source, 1 flow in, 2 flow out, 3..11 narrow to wide, 254 sea, 255 land


def _bmp8(path: Path):
    """(height, width) uint8 array of an 8-bit BMP's palette indexes, rows top to bottom."""
    import numpy as np
    raw = path.read_bytes()
    if raw[:2] != b"BM":
        raise ValueError(f"{path.name} is not a BMP file")
    offset = struct.unpack_from("<I", raw, 10)[0]
    width, height = struct.unpack_from("<ii", raw, 18)
    bits, compression = struct.unpack_from("<HI", raw, 28)
    if bits != 8 or compression != 0:
        raise ValueError(f"{path.name} is not an uncompressed 8-bit BMP")
    stride = (width + 3) & ~3
    rows = np.frombuffer(raw, dtype=np.uint8, count=stride * abs(height), offset=offset).reshape(abs(height), stride)
    return (rows[::-1] if height > 0 else rows)[:, :width]


def relief(heights, land) -> tuple[int, int, bytes]:
    """(width, height, grey pixels) of the relief: `heights` (heightmap) shaded as lit from the north-west at
    1 / RELIEF_STEP of the size, 128 = flat and off land (`land`: bool array), the steepest 1% at the ends."""
    import numpy as np
    s = RELIEF_STEP
    h, w = heights.shape[0] // s * s, heights.shape[1] // s * s
    z = heights[:h, :w].astype(np.float32).reshape(h // s, s, w // s, s).mean(axis=(1, 3))
    on = land[:h, :w].reshape(h // s, s, w // s, s).mean(axis=(1, 3)) > 0.5
    if min(z.shape) < 2:   # too small for slopes
        return z.shape[1], z.shape[0], bytes([128]) * z.size
    dy, dx = np.gradient(z)
    light = -(dx + dy)   # higher to the south-east: lit
    steep = float(np.percentile(np.abs(light[on]), 99)) if on.any() else 0
    shade = np.where(on, 128 + light * (RELIEF_STRENGTH / steep if steep else 0), 128)
    out = np.clip(np.rint(shade), 0, 255).astype(np.uint8)
    return out.shape[1], out.shape[0], out.tobytes()


def rivers(river_px) -> list[list]:
    """[[width class, x0, y0, x1, y1, ...]] of the rivers in `river_px` (rivers.bmp indexes): lines through the centres
    of the river pixels between their ends, forks and changes of width (Douglas-Peucker 0.5 px, 1 decimal)."""
    import numpy as np
    river = river_px <= max(RIVER_WIDTHS)
    height, width = river.shape
    ys, xs = np.nonzero(river)
    cls = river_px[ys, xs].astype(np.int32)
    index = -np.ones(river.shape, dtype=np.int64)
    index[ys, xs] = np.arange(len(xs))
    pad = np.pad(index, 1, constant_values=-1)
    near = np.stack([pad[ys, xs + 1], pad[ys + 2, xs + 1], pad[ys + 1, xs], pad[ys + 1, xs + 2]], axis=1)   # N S W E
    marks = cls < min(RIVER_WIDTHS)   # a source / fork marker takes the width of a neighbour
    for _ in range(2):
        for k in range(4):
            fix = marks & (near[:, k] >= 0)
            cls[fix] = np.where(cls[near[fix, k]] >= min(RIVER_WIDTHS), cls[near[fix, k]], cls[fix])
    cls = np.maximum(cls, min(RIVER_WIDTHS))
    nb = near.tolist()
    cl = cls.tolist()
    degree = [sum(1 for j in row if j >= 0) for row in nb]
    stop = [degree[i] != 2 or any(j >= 0 and cl[j] != cl[i] for j in nb[i]) for i in range(len(nb))]
    used: set[tuple[int, int]] = set()
    out = []

    def follow(i: int, j: int) -> list[int]:
        path = [i]
        while True:
            used.add((min(i, j), max(i, j)))
            path.append(j)
            if stop[j]:
                return path
            nxt = next((k for k in nb[j] if k >= 0 and k != i and (min(j, k), max(j, k)) not in used), -1)
            if nxt < 0:
                return path
            i, j = j, nxt

    starts = [i for i in range(len(nb)) if stop[i]] + list(range(len(nb)))   # loops last
    for i in starts:
        for j in nb[i]:
            if j >= 0 and (min(i, j), max(i, j)) not in used:
                path = follow(i, j)
                c = max(cl[path[1]], cl[path[0]]) if len(path) == 2 else cl[path[len(path) // 2]]
                xy = np.stack([xs[path] + 0.5, ys[path] + 0.5], axis=1).astype(np.float64)
                pts = _simplify(xy, 0.5)
                out.append([c, *np.round(pts, 1).reshape(-1).tolist()])
    for i in range(len(nb)):   # a river pixel with no river next to it
        if degree[i] == 0:
            out.append([cl[i], float(xs[i]) + 0.2, float(ys[i]) + 0.5, float(xs[i]) + 0.8, float(ys[i]) + 0.5])
    return out


def terrain(roots, cache_dir: Path | None = None) -> dict:
    """{"key", "relief": {"width", "height", "png"}, "rivers": rivers()} of the map the game loads (heightmap.bmp,
    rivers.bmp of the game or a mod), cached in `cache_dir`; relief None without a heightmap, rivers [] without
    rivers.bmp."""
    roots = [str(r) for r in roots]
    key, bmp, definition = _key(roots)
    heights, river_bmp = last_file(roots, "map/heightmap.bmp"), last_file(roots, "map/rivers.bmp")
    parts = [key, str(TERRAIN_VERSION)] + [f"{f}:{f.stat().st_size}:{int(f.stat().st_mtime)}" for f in (heights, river_bmp) if f]
    key = hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]
    cache = Path(cache_dir) / f"campaign_terrain_{key}.json" if cache_dir else None
    if cache and cache.is_file():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except ValueError:
            pass
    import base64
    colours, kinds = _province_kinds(definition)
    ids = _province_ids(bmp, colours)
    out = {"key": key, "relief": None, "rivers": []}
    if heights:
        z = _bmp8(heights)
        if z.shape == ids.shape:
            w, h, grey = relief(z, _kind_of(kinds, int(ids.max()))[ids] == LAND)
            out["relief"] = {"width": w, "height": h,
                             "png": "data:image/png;base64," + base64.b64encode(png(w, h, grey, 1)).decode("ascii")}
    if river_bmp:
        r = _bmp8(river_bmp)
        if r.shape == ids.shape:
            out["rivers"] = rivers(r)
    if cache:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            for old in cache.parent.glob("campaign_terrain_*.json"):
                old.unlink(missing_ok=True)
            cache.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
        except OSError:
            pass
    return out
