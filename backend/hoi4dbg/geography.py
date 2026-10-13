"""Map geography from the game files: which provinces touch (map/provinces.bmp, one colour per province from
map/definition.csv) and the continent of each province (definition.csv, last column, names in map/continent.txt).
Used for "shared border" and "same continent" of the trade advisor. The adjacency is computed once per map file
(numpy when installed, else pure Python - slower, about a minute) and cached as JSON in the app's data folder.
"""

from __future__ import annotations

import json
import struct
from functools import lru_cache
from pathlib import Path

CACHE_VERSION = 1


def _definitions(install: Path) -> tuple[dict[int, int], dict[int, int]]:
    """({rgb colour: province id}, {province id: continent index}) of land provinces."""
    colours, continents = {}, {}
    path = Path(install) / "map" / "definition.csv"
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        parts = line.split(";")
        if len(parts) < 8 or not parts[0].isdigit() or int(parts[0]) == 0:
            continue
        pid = int(parts[0])
        colours[(int(parts[1]) << 16) | (int(parts[2]) << 8) | int(parts[3])] = pid
        if parts[4] == "land" and parts[7].strip().isdigit():
            continents[pid] = int(parts[7])
    return colours, continents


def _bmp(path: Path) -> tuple[int, int, bytes, int, int]:
    """(width, height, pixel data, row stride, data offset) of an uncompressed 24-bit BMP."""
    data = path.read_bytes()
    if data[:2] != b"BM":
        raise ValueError("provinces.bmp is not a BMP file")
    offset = struct.unpack_from("<I", data, 10)[0]
    width, height = struct.unpack_from("<ii", data, 18)
    bits, compression = struct.unpack_from("<HI", data, 28)
    if bits != 24 or compression != 0:
        raise ValueError("provinces.bmp is not an uncompressed 24-bit BMP")
    return width, abs(height), data, (width * 3 + 3) & ~3, offset


def _pairs_numpy(width, height, data, stride, offset) -> set[tuple[int, int]]:
    import numpy as np
    rows = np.frombuffer(data, dtype=np.uint8, count=stride * height, offset=offset).reshape(height, stride)
    px = rows[:, :width * 3].reshape(height, width, 3).astype(np.uint32)
    c = (px[:, :, 2] << 16) | (px[:, :, 1] << 8) | px[:, :, 0]   # BMP stores blue, green, red
    pairs = set()
    for a, b in ((c[:, :-1], c[:, 1:]), (c[:-1, :], c[1:, :])):
        diff = a != b
        both = np.stack([a[diff], b[diff]], axis=1)
        both.sort(axis=1)
        pairs.update(map(tuple, np.unique(both, axis=0).tolist()))
    return pairs


def _pairs_python(width, height, data, stride, offset) -> set[tuple[int, int]]:
    pairs = set()
    prev = None
    for y in range(height):
        start = offset + y * stride
        row = [int.from_bytes(data[start + 3 * x:start + 3 * x + 3], "little") for x in range(width)]
        for x in range(width - 1):
            if row[x] != row[x + 1]:
                pairs.add((min(row[x], row[x + 1]), max(row[x], row[x + 1])))
        if prev is not None:
            for x in range(width):
                if row[x] != prev[x]:
                    pairs.add((min(row[x], prev[x]), max(row[x], prev[x])))
        prev = row
    return pairs


@lru_cache(maxsize=2)
def province_neighbours(install: str, cache_dir: str = "") -> dict[int, frozenset[int]]:
    """{province id: ids of the provinces it touches on the map}."""
    bmp = Path(install) / "map" / "provinces.bmp"
    stat = bmp.stat()
    key = f"{CACHE_VERSION}:{stat.st_size}:{int(stat.st_mtime)}"
    cache = Path(cache_dir) / "province_adjacency.json" if cache_dir else None
    if cache and cache.is_file():
        try:
            saved = json.loads(cache.read_text(encoding="utf-8"))
            if saved.get("key") == key:
                return _neighbours(saved["pairs"])
        except (OSError, ValueError, KeyError):
            pass
    colours, _ = _definitions(Path(install))
    raw = _bmp(bmp)
    try:
        pairs = _pairs_numpy(*raw)
    except ImportError:
        pairs = _pairs_python(*raw)
    ids = [[colours[a], colours[b]] for a, b in pairs if a in colours and b in colours]
    if cache:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"key": key, "pairs": ids}), encoding="utf-8")
        except OSError:
            pass
    return _neighbours(ids)


def _neighbours(pairs) -> dict[int, frozenset[int]]:
    out: dict[int, set[int]] = {}
    for a, b in pairs:
        out.setdefault(a, set()).add(b)
        out.setdefault(b, set()).add(a)
    return {k: frozenset(v) for k, v in out.items()}


@lru_cache(maxsize=2)
def province_continents(install: str) -> dict[int, int]:
    """{land province id: continent index (1 = first in map/continent.txt)}."""
    return _definitions(Path(install))[1]


def countries_touching(owned: dict[str, list[int]], neighbours: dict[int, frozenset[int]], tag: str) -> set[str]:
    """Countries with a province next to one of `tag`'s; `owned` = {country: its provinces}."""
    owner = {p: t for t, provs in owned.items() for p in provs}
    out = set()
    for p in owned.get(tag, []):
        for q in neighbours.get(p, ()):
            other = owner.get(q)
            if other and other != tag:
                out.add(other)
    return out


def main_continent(provinces: list[int], continents: dict[int, int]) -> int | None:
    """The continent most of these provinces lie on."""
    counts: dict[int, int] = {}
    for p in provinces:
        c = continents.get(p)
        if c:
            counts[c] = counts.get(c, 0) + 1
    return max(counts, key=lambda c: (counts[c], -c)) if counts else None
