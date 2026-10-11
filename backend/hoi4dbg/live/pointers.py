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
# [country + 0xfa0] + 0x1c0: 0 = visible to the player, 1 = hidden by fog of war. With fog of war ON only the
# player's own country is 0 (2026-10-09, player switched GER -> ITA -> SOV: the only location that followed the
# player). CORRECTION (same day): after the console command `fow` (fog of war off) all 99 existing countries had 0
# - it is a visibility flag, not an AI flag. It identifies the player only when exactly one country has 0.
PLAYER_FLAG = (0xFA0, 0x1C0)
# int32 at country + 0x484: number of states the country owns (0 = does not exist). 2026-10-10: equal to the
# owner count of the save for 439/439 tags (99 existing, 340 not), next best location 437/439.
OWNED_STATES = 0x484

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


def country_objects(memory, module_base: int, tags: list[str]) -> dict[str, int]:
    """{tag: country object} for every readable slot of the country table ({} when it is not readable)."""
    table = _ptr(memory, module_base + COUNTRY_TABLE[0])
    array = _ptr(memory, table + COUNTRY_TABLE[1]) if table else None
    data = memory.read(array + 8, 8 * len(tags)) if array else None
    if not data:
        return {}
    out = {}
    for i, tag in enumerate(tags):
        country = struct.unpack_from("<Q", data, 8 * i)[0]
        if 0x10000 <= country < 0x7FFF_FFFF_FFFF:
            out[tag] = country
    return out


def player_tags(memory, module_base: int, tags: list[str]) -> list[str]:
    """Countries not hidden by fog of war - the player's own country when that is unambiguous. Empty when the flag
    is not readable or too many countries are visible (fog of war off). Not a multiplayer indicator."""
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


def owned_states(memory, module_base: int, tags: list[str]) -> dict[str, int]:
    """{tag: number of owned states} for every tag of the country table ({} when it is not readable)."""
    table = _ptr(memory, module_base + COUNTRY_TABLE[0])
    array = _ptr(memory, table + COUNTRY_TABLE[1]) if table else None
    data = memory.read(array + 8, 8 * len(tags)) if array else None
    if not data:
        return {}
    out = {}
    for i, tag in enumerate(tags):
        country = struct.unpack_from("<Q", data, 8 * i)[0]
        raw = memory.read(country + OWNED_STATES, 4) if 0x10000 <= country < 0x7FFF_FFFF_FFFF else None
        if raw:
            out[tag] = struct.unpack("<i", raw)[0]
    # sanity: counts are small and non-negative; otherwise the layout does not match
    return out if out and all(0 <= n <= 5000 for n in out.values()) else {}


# Party popularity (2026-10-10, 99/99 countries equal to the save, ruling party 99/99):
# [country + 0xf90] = politics object; [politics + 0x20] = array of party objects, one per ideology in the order of
# common/ideologies; party + 0x88 = popularity (fixed64 / 100000, in %); [politics + 0xd0] = the ruling party object.
POLITICS = 0xF90
PARTIES = 0x20
RULING_PARTY = 0xD0
PARTY_POPULARITY = 0x88


def read_parties(memory, country: int, ideologies: list[str]) -> dict:
    """{"popularity": {ideology: %}, "ruling": ideology or None} of a country object."""
    pol = _ptr(memory, country + POLITICS)
    array = _ptr(memory, pol + PARTIES) if pol else None
    if array is None:
        raise PointerError("no_politics", "The country's politics object is not readable")
    popularity, parties = {}, []
    for i, ideology in enumerate(ideologies):
        party = _ptr(memory, array + 8 * i)
        raw = memory.read(party + PARTY_POPULARITY, 8) if party else None
        if raw is None:
            raise PointerError("no_party", f"Party {ideology} is not readable")
        value = struct.unpack("<q", raw)[0] / 100000
        if not -0.001 <= value <= 100.001:
            raise PointerError("implausible", f"Party popularity {value} out of range - layout does not match")
        popularity[ideology] = value
        parties.append(party)
    ruling = _ptr(memory, pol + RULING_PARTY)
    return {"popularity": popularity, "ruling": ideologies[parties.index(ruling)] if ruling in parties else None}


# Resources (2026-10-11, 97/99 countries equal to the save in all six parts; the 2 others differed only by a trade
# deal made in game after the save). Found by RTTI class names (CCountryResources, CStrategicResourcePool,
# CResourceExchange) after a before/after memory diff of a new trade deal:
# [country + 0x11f8] = CCountryResources; inside it pools of 0xb0 bytes, each with 8 inline slots of 16 bytes from
# pool + 0x38: fixed64/100000 amount, then the token of the resource (int32) - slot k = k-th resource of
# common/resources. used is stored negative. [CR + 0x740] = array of this country's imports (CResourceExchange*),
# int32 count at CR + 0x74c; exchange + 0x38 = buyer country object, + 0x80 = seller's CCountryResources,
# + 0x90 = resource object (token int32 at + 0x8), + 0x98 = amount (fixed64/100000).
# Pools are recomputed by the game on the daily tick, except "exported" which follows new deals at once.
COUNTRY_RESOURCES = 0x11F8
RESOURCE_POOLS = {"produced": 0x28, "imported": 0x188, "available": 0x238, "used": 0x398, "to_market": 0x450,
                  "exported": 0x5B0}
POOL_SLOTS = 0x38
IMPORTS = 0x740  # array of CResourceExchange* (see read_array)
EXCHANGE = {"buyer": 0x38, "seller_resources": 0x80, "resource": 0x90, "amount": 0x98}
RESOURCE_TOKEN = 0x8


def read_array(memory, address: int, limit: int) -> list[int | None]:
    """Elements of the game's pointer arrays: pointer to the data, int32 capacity, int32 size (2026-10-11: size is
    the second number - a 9-slot array of RAJ held 8 ideas and a stale 9th slot)."""
    raw = memory.read(address, 16)
    if not raw:
        raise PointerError("unreadable", "Array header is not readable")
    data, capacity, size = struct.unpack("<Qii", raw)
    if size == 0:
        return []
    if not 0 < size <= min(capacity, limit) or not 0x10000 <= data < 0x7FFF_FFFF_FFFF:
        raise PointerError("implausible", f"Array of {size}/{capacity} elements - layout does not match")
    items = memory.read(data, 8 * size)
    if not items:
        raise PointerError("unreadable", "Array data is not readable")
    return [v if 0x10000 <= v < 0x7FFF_FFFF_FFFF else None for v in struct.unpack(f"<{size}Q", items)]


# Ideas (2026-10-11, 99/99 countries equal to the save's politics ideas, same order): [politics + 0x50] = array of
# CIdea* (read_array); CIdea + 0x18 = its id (MSVC std::string). National spirits, laws and companies are all ideas.
IDEAS = 0x50
IDEA_NAME = 0x18


def read_ideas(memory, country: int) -> list[str]:
    pol = _ptr(memory, country + POLITICS)
    if pol is None:
        raise PointerError("no_politics", "The country's politics object is not readable")
    out = []
    for idea in read_array(memory, pol + IDEAS, 1000):
        name = _msvc_string(memory, idea + IDEA_NAME) if idea else None
        if not name or not re.fullmatch(r"[A-Za-z0-9_.\-]+", name):
            raise PointerError("implausible", "An idea has no readable id - layout does not match")
        out.append(name)
    return out


def resources_object(memory, country: int) -> int:
    cr = _ptr(memory, country + COUNTRY_RESOURCES)
    if cr is None:
        raise PointerError("no_resources", "The country's resources object is not readable")
    return cr


def read_resources(memory, cr: int, resources: list[str]) -> dict:
    """{part: {resource: amount per day}} for the RESOURCE_POOLS of a CCountryResources object, plus
    "_tokens": {token: resource} for decoding trade deals."""
    if not 0 < len(resources) <= 8:
        raise PointerError("implausible", f"{len(resources)} resources do not fit the 8 slots of a pool")
    data = memory.read(cr, max(RESOURCE_POOLS.values()) + POOL_SLOTS + 16 * 8)
    if not data:
        raise PointerError("no_resources", "The country's resources object is not readable")
    out: dict = {}
    tokens = None
    for part, pool in RESOURCE_POOLS.items():
        slots = [struct.unpack_from("<qI", data, pool + POOL_SLOTS + 16 * k) for k in range(len(resources))]
        if tokens is None:
            tokens = [t for _, t in slots]
            if len(set(tokens)) != len(tokens) or 0 in tokens:
                raise PointerError("implausible", "Resource tokens are not distinct - layout does not match")
        elif [t for _, t in slots] != tokens:
            raise PointerError("implausible", f"Resource pool {part} has other tokens - layout does not match")
        values = {name: (-raw if part == "used" else raw) / 100000 for name, (raw, _) in zip(resources, slots)}
        if any(not -1_000_000 <= v <= 1_000_000 for v in values.values()):
            raise PointerError("implausible", f"Resource pool {part} out of range - layout does not match")
        out[part] = values
    out["_tokens"] = dict(zip(tokens, resources))
    return out


def read_imports(memory, cr: int, tokens: dict[int, str], sellers: dict[int, str]) -> list[dict]:
    """Trade deals in which the country of `cr` buys: [{"seller": tag, "resource", "amount"}]."""
    out = []
    for deal in read_array(memory, cr + IMPORTS, 500):
        seller = _ptr(memory, deal + EXCHANGE["seller_resources"]) if deal else None
        res = _ptr(memory, deal + EXCHANGE["resource"]) if deal else None
        token = memory.read(res + RESOURCE_TOKEN, 4) if res else None
        amount = memory.read(deal + EXCHANGE["amount"], 8) if deal else None
        if token is None or amount is None:
            continue
        out.append({"seller": sellers.get(seller), "resource": tokens.get(struct.unpack("<I", token)[0]),
                    "amount": struct.unpack("<q", amount)[0] / 100000})
    return out


# Plausible ranges for direct (local) writes; the game itself clamps some of them.
WRITE_RANGES = {"stability": (0.0, 1.0), "war_support": (0.0, 1.0), "political_power": (-10_000.0, 100_000.0),
                "command_power": (0.0, 10_000.0), "fuel": (0.0, 100_000_000.0), "army_experience": (0.0, 100_000.0),
                "navy_experience": (0.0, 100_000.0), "air_experience": (0.0, 100_000.0)}


def field_address(memory, country: int, field: str) -> int:
    offsets, _ = FIELDS[field]
    addr = country
    for off in offsets[:-1]:
        addr = _ptr(memory, addr + off)
        if addr is None:
            raise PointerError("unreadable", f"{field}: pointer inside the country object is not readable")
    return addr + offsets[-1]


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


# Equipment stockpile: [country + 0xf68] = production object; +0x220 -> array of {variant*, amount (fixed64_100000)}
# entries, +0x22c = entry count (int32); variant object: +0xc = equipment id as in the save, +0x28 = design name.
# Verified 2026-10-09 (magazyn.hoi4): non-zero stockpile of all 99 countries identical to the save.
STOCKPILE = {"production": 0xF68, "array": 0x220, "count": 0x22C, "entry": 16, "amount": 8}
VARIANT = {"id": 0xC, "name": 0x28}
MAX_STOCKPILE_ENTRIES = 5000
STOCKPILE_RANGE = (0.0, 10_000_000.0)


def read_stockpile(memory, country: int) -> list[dict]:
    """[{"id": equipment id, "name": design name or None, "amount": float, "address": amount address}]."""
    production = _ptr(memory, country + STOCKPILE["production"])
    if production is None:
        raise PointerError("unreadable", "Production object of the country is not readable")
    raw = memory.read(production + STOCKPILE["count"], 4)
    count = struct.unpack("<i", raw)[0] if raw else -1
    if not 0 <= count <= MAX_STOCKPILE_ENTRIES:
        raise PointerError("implausible", f"Stockpile size {count} - layout does not match")
    array = _ptr(memory, production + STOCKPILE["array"]) if count else None
    data = memory.read(array, STOCKPILE["entry"] * count) if array else b""
    out = []
    for i in range(len(data or b"") // STOCKPILE["entry"]):
        variant, amount = struct.unpack_from("<Qq", data, STOCKPILE["entry"] * i)
        raw_id = memory.read(variant + VARIANT["id"], 4) if 0x10000 <= variant < 0x7FFF_FFFF_FFFF else None
        if raw_id is None:
            continue
        out.append({"id": str(struct.unpack("<i", raw_id)[0]),
                    "name": _msvc_string(memory, variant + VARIANT["name"], 120),
                    "amount": amount / 100000, "address": array + STOCKPILE["entry"] * i + STOCKPILE["amount"]})
    return out
