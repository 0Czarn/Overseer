"""Country values through the game's own country table (read-only, no calibration).

Verified 2026-10-09 on Operation Postern v1.19.3.0.c01a, vanilla tags, by searching backwards from
calibrated addresses and checking against saves:
- hoi4.exe+COUNTRY_TABLE[0] holds a pointer; +COUNTRY_TABLE[1] in that object points to an array of
  country object pointers; slot i = the i-th tag of common/country_tags/*.txt (1-based; 440 slots for 439 tags).
- Field offsets inside the country object are the same in every process (4 game processes, after loading
  other saves, for GER/ITA as player): 80/80 countries matched a save exactly after a game restart.
Other game versions are refused: offsets of a compiled program are not stable across updates.
"""

from __future__ import annotations

import re
import struct
from pathlib import Path

from ..integration.memory import ENCODINGS

MODULE = "hoi4.exe"
VERIFIED_VERSION = re.compile(r"v1\.19\.3\.0\.c01a\b")
COUNTRY_TABLE = (0x332F260, 0x310)
MAX_TAGS = 2000

# field -> (offsets inside the country object: all but the last are pointer hops, encoding)
FIELDS: dict[str, tuple[tuple[int, ...], str]] = {
    "political_power": ((0xF90, 0xE0), "fixed64_100000"),
    "stability": ((0x10D0,), "fixed64_100000"),
    "war_support": ((0x10D8,), "fixed64_100000"),
    "command_power": ((0x1F0,), "fixed64_100000"),
    "fuel": ((0x1580, 0x8), "fixed64_32768"),
    "army_experience": ((0x1588, 0x10), "fixed64_32768"),
    "navy_experience": ((0x1588, 0x28), "fixed64_32768"),
    "air_experience": ((0x1588, 0x40), "fixed64_32768"),
}

TAG_LINE = re.compile(r"^\s*([A-Z][A-Z0-9]{2})\s*=", re.M)


class PointerError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def supported(version: str | None) -> bool:
    return bool(VERIFIED_VERSION.search(version or ""))


def tag_order(install: Path) -> list[str]:
    """Tags in the order the game loads them (files of common/country_tags by name, lines in order)."""
    tags: list[str] = []
    for path in sorted((install / "common" / "country_tags").glob("*.txt"), key=lambda p: p.name.lower()):
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        text = re.sub(r"#[^\n]*", "", text)
        tags += [t for t in TAG_LINE.findall(text) if t not in tags]
    return tags[:MAX_TAGS]


def _ptr(memory, address: int) -> int | None:
    data = memory.read(address, 8)
    if not data:
        return None
    value = struct.unpack("<Q", data)[0]
    return value if 0x10000 <= value < 0x7FFF_FFFF_FFFF else None


def country_object(memory, module_base: int, tags: list[str], tag: str) -> int:
    if tag not in tags:
        raise PointerError("unknown_tag", f"{tag} is not a country tag of this game installation")
    table = _ptr(memory, module_base + COUNTRY_TABLE[0])
    array = _ptr(memory, table + COUNTRY_TABLE[1]) if table else None
    if array is None:
        raise PointerError("no_country_table", "The country table is not readable (main menu, loading, or another "
                                               "game version)")
    country = _ptr(memory, array + 8 * (tags.index(tag) + 1))
    if country is None:
        raise PointerError("country_missing", f"{tag} has no country object in the running game")
    return country


def read_field(memory, country: int, field: str) -> float:
    offsets, enc = FIELDS[field]
    addr = country
    for off in offsets[:-1]:
        addr = _ptr(memory, addr + off)
        if addr is None:
            raise PointerError("unreadable", f"{field}: pointer inside the country object is not readable")
    data = memory.read(addr + offsets[-1], ENCODINGS[enc].size)
    if not data:
        raise PointerError("unreadable", f"{field}: value is not readable")
    value = ENCODINGS[enc].unpack(data)
    if field in ("stability", "war_support") and not -0.001 <= value <= 1.001:
        raise PointerError("implausible", f"{field} = {value} is outside 0..1 - the layout does not match")
    return value
