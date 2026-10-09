"""Maps save fields to places in the country object, using all countries at once (read-only).

For every numeric field of a country block (depth <= 2) the save gives one value per country; the
country table gives each country's object in memory. A location (offset in the object, or offset
behind one pointer of the object) in some encoding counts as the field only if it holds the save
value for nearly all countries that have the field AND those values differ between countries -
one country could match by chance, dozens of different values cannot.
The game must be paused between the save and the scan (otherwise values move).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from ..integration.memory import ENCODINGS

OBJECT_SIZE = 0x3000
HOP_SIZE = 0x800
MAX_DEPTH = 2
ENCS = ("int32", "int64", "fixed64_100000", "fixed64_32768", "fixed32_1000", "float32", "float64")
MIN_COUNTRIES = 5
PTR_RANGE = (0x100_0000_0000, 0x7FF0_0000_0000)  # user-mode heap of the 64-bit game
MIN_RATIO = 0.9
MIN_DISTINCT = 3


@dataclass(frozen=True)
class Location:
    hop: int | None   # offset of a pointer in the country object, or None for a direct field
    offset: int
    encoding: str

    def describe(self) -> str:
        return (f"[+{self.hop:#x}]" if self.hop is not None else "") + f"+{self.offset:#x} {self.encoding}"


def numeric_leaves(block: list, depth: int = MAX_DEPTH, prefix: tuple = ()) -> dict[tuple, float]:
    """{path: number} for scalar fields up to `depth` levels (first occurrence of a repeated key)."""
    out: dict[tuple, float] = {}
    for item in block:
        if not isinstance(item, tuple):
            continue
        key, value = item
        path = prefix + (str(key),)
        if isinstance(value, list):
            if depth > 1:
                for k, v in numeric_leaves(value, depth - 1, path).items():
                    out.setdefault(k, v)
        else:
            try:
                out.setdefault(path, float(value))
            except (TypeError, ValueError):
                pass
    return out


def _read_upto(memory, address: int, size: int) -> bytes:
    """As many bytes as are readable from `address` (objects may end right before an unmapped page)."""
    data = memory.read(address, size)
    if data:
        return data
    out = b""
    page_end = (address // 0x1000 + 1) * 0x1000
    while len(out) < size:
        chunk = memory.read(address + len(out), min(page_end - address - len(out), size - len(out)))
        if not chunk:
            break
        out += chunk
        page_end += 0x1000
    return out


def snapshot(memory, country: int) -> dict:
    obj = _read_upto(memory, country, OBJECT_SIZE)
    hops = {}
    for off in range(0, len(obj) - 7, 8):
        ptr = struct.unpack_from("<Q", obj, off)[0]
        if PTR_RANGE[0] <= ptr < PTR_RANGE[1]:
            data = _read_upto(memory, ptr, HOP_SIZE)
            if data:
                hops[off] = data
    return {"obj": obj, "hops": hops}


def _value_at(snap: dict, loc: Location) -> float | None:
    data = snap["obj"] if loc.hop is None else snap["hops"].get(loc.hop)
    enc = ENCODINGS[loc.encoding]
    if data is None or loc.offset + enc.size > len(data):
        return None
    return enc.unpack(data[loc.offset:loc.offset + enc.size])


def _close(found: float, value: float, tol: float, encoding: str) -> bool:
    if encoding in ("float32",):
        tol = max(tol, abs(value) * 1e-6)
    return abs(found - value) <= tol + 1e-9


def candidates(snap: dict, value: float, tol: float) -> set[Location]:
    """Every location of one country's snapshot that holds `value` in some encoding."""
    out = set()
    for encoding in ENCS:
        enc = ENCODINGS[encoding]
        if enc.scale == 1 and value != int(value):
            continue
        packed = enc.pack(value)
        if packed is None:
            continue
        step = 4 if enc.size == 4 else 8
        for hop, data in [(None, snap["obj"])] + list(snap["hops"].items()):
            if enc.scale is not None and tol < 1 / enc.scale:
                # exact representation: a byte search is enough
                start = data.find(packed)
                while start != -1:
                    if start % step == 0:
                        out.add(Location(hop, start, encoding))
                    start = data.find(packed, start + 1)
                continue
            for off in range(0, len(data) - enc.size + 1, step):
                if _close(enc.unpack(data[off:off + enc.size]), value, tol, encoding):
                    out.add(Location(hop, off, encoding))
    return out


def map_field(snaps: dict[str, dict], values: dict[str, tuple[float, float]]) -> list[dict]:
    """Locations holding `values` ({tag: (value, tolerance)}) for nearly all countries."""
    usable = {t: v for t, v in values.items() if t in snaps and v[0] != 0}
    if len(usable) < MIN_COUNTRIES or len({round(v[0], 6) for v in usable.values()}) < MIN_DISTINCT:
        return []
    # start from the most distinctive values (large, non-integer) so the first candidate sets are small
    order = sorted(usable, key=lambda t: (usable[t][0] == int(usable[t][0]), -abs(usable[t][0])))
    cands = candidates(snaps[order[0]], *usable[order[0]])
    for tag in order[1:4]:
        cands = {c for c in cands if (v := _value_at(snaps[tag], c)) is not None
                 and _close(v, usable[tag][0], usable[tag][1], c.encoding)}
    results = []
    for loc in cands:
        hits = [t for t in usable if (v := _value_at(snaps[t], loc)) is not None
                and _close(v, usable[t][0], usable[t][1], loc.encoding)]
        if len(hits) >= max(MIN_COUNTRIES, MIN_RATIO * len(usable)):
            results.append({"location": loc, "matched": len(hits), "countries": len(usable),
                            "missed": sorted(set(usable) - set(hits))[:10]})
    return sorted(results, key=lambda r: (-r["matched"], r["location"].hop is not None, r["location"].offset))
