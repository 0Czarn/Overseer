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

from ..gamefiles import tag_order  # noqa: F401 - tag index = position in this list + 1
from ..integration.memory import ENCODINGS

MODULE = "hoi4.exe"
VERIFIED_VERSION = re.compile(r"v1\.19\.3\.0\.c01a\b")
COUNTRY_TABLE = (0x332F260, 0x310)
# [country + 0xfa0] + 0x1c0: 1 = AI-controlled, 0 = human player. Verified 2026-10-09 (PID 25320) with the player
# switched GER -> ITA -> SOV: the only location that followed the player; 438 of 439 tags had 1, the player 0.
PLAYER_FLAG = (0xFA0, 0x1C0)

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


class PointerError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def supported(version: str | None) -> bool:
    return bool(VERIFIED_VERSION.search(version or ""))


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


def player_tags(memory, module_base: int, tags: list[str]) -> list[str]:
    """Countries controlled by a human (more than one in multiplayer). Empty when the flag is not readable."""
    table = _ptr(memory, module_base + COUNTRY_TABLE[0])
    array = _ptr(memory, table + COUNTRY_TABLE[1]) if table else None
    if array is None:
        return []
    data = memory.read(array + 8, 8 * len(tags))
    if not data:
        return []
    humans, readable = [], 0
    for i, tag in enumerate(tags):
        country = struct.unpack_from("<Q", data, 8 * i)[0]
        sub = _ptr(memory, country + PLAYER_FLAG[0]) if 0x10000 <= country < 0x7FFF_FFFF_FFFF else None
        flag = memory.read(sub + PLAYER_FLAG[1], 1) if sub else None
        if flag is None:
            continue
        readable += 1
        if flag[0] == 0:
            humans.append(tag)
    # sanity: nearly all countries are AI; anything else means the layout does not match
    return humans if readable and len(humans) <= max(8, readable // 10) else []


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


# National focus of a country: [country + 0x1380] = focus state; +0x10 -> focus definition whose id (MSVC
# std::string) is at +0x18; +0x38 = progress in days (fixed64_100000). Verified 2026-10-09 (wariant3.hoi4):
# progress 99/99 countries (incl. SIA 23 vs 30 elsewhere), current focus id 99/99 countries.
# +0x40 -> array of completed focus definitions, +0x48 = count (int32): after 5 game days the list of every
# country contained all completed focuses of the save (99/99), the new ones being mostly the save's current focus.
FOCUS = {"state": 0x1380, "definition": 0x10, "id": 0x18, "progress": 0x38, "completed": 0x40, "completed_count": 0x48}
MAX_COMPLETED = 2000


def _msvc_string(memory, address: int, max_len: int = 200) -> str | None:
    raw = memory.read(address, 32)
    if not raw:
        return None
    size, capacity = struct.unpack_from("<QQ", raw, 16)
    if size > max_len or capacity < size:
        return None
    data = raw[:size] if capacity < 16 else (memory.read(struct.unpack_from("<Q", raw, 0)[0], size) if size else b"")
    return data.decode("utf-8", "replace") if data is not None else None


def read_focus(memory, country: int) -> dict:
    """{"current": focus id or None, "progress_days": float, "completed": [focus ids]}."""
    state = _ptr(memory, country + FOCUS["state"])
    if state is None:
        raise PointerError("unreadable", "Focus state of the country is not readable")
    data = memory.read(state + FOCUS["progress"], 8)
    progress = ENCODINGS["fixed64_100000"].unpack(data) if data else 0.0
    definition = _ptr(memory, state + FOCUS["definition"])
    current = _msvc_string(memory, definition + FOCUS["id"]) if definition else None
    if current is not None and not re.fullmatch(r"[A-Za-z0-9_.\-]{1,200}", current):
        raise PointerError("implausible", f"Focus id {current!r} does not look like an id - layout does not match")
    raw = memory.read(state + FOCUS["completed_count"], 4)
    count = struct.unpack("<I", raw)[0] if raw else 0
    array = _ptr(memory, state + FOCUS["completed"]) if count else None
    completed = []
    if count > MAX_COMPLETED:
        raise PointerError("implausible", f"{count} completed focuses - layout does not match")
    table = memory.read(array, 8 * count) if array else b""
    for i in range(len(table or b"") // 8):
        definition_i = struct.unpack_from("<Q", table, 8 * i)[0]
        fid = _msvc_string(memory, definition_i + FOCUS["id"]) if 0x10000 <= definition_i < 0x7FFF_FFFF_FFFF else None
        if fid:
            completed.append(fid)
    return {"current": current or None, "progress_days": progress, "completed": completed}
