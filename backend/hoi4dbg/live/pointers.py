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

import math
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
# [hoi4.exe + COUNTRY_TABLE[0]] + 0x520 = slot of the player's country (int32, index in the tag order + 1). Found
# 2026-10-13 by the console command `tag` (USA -> MEX -> USA): 68 -> 51 -> 68, the only value in the game state
# following the player; works with fog of war off, where PLAYER_FLAG cannot tell the player apart.
PLAYER_SLOT = 0x520
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


def player_country(memory, module_base: int, tags: list[str]) -> str | None:
    """Tag of the local player's country from the game state (None when not readable or out of range)."""
    table = _ptr(memory, module_base + COUNTRY_TABLE[0])
    raw = memory.read(table + PLAYER_SLOT, 4) if table else None
    slot = struct.unpack("<i", raw)[0] if raw else 0
    return tags[slot - 1] if 0 < slot <= len(tags) else None


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


# Dynamic modifiers (2026-10-11, 99/99 countries / 76 modifiers equal to the save, names and every value):
# country + 0xe80 = array of 0x40-byte SDynamicModifierEntry (pointer, int32 capacity, int32 size - inline entries,
# not pointers); entry + 0x18 = CDynamicModifier (+ 0x28 = its id, std::string), entry + 0x20 = 1 (enabled; only 1
# seen), entry + 0x28 = int64 values / 100000 in the order of the definition in common/dynamic_modifiers, size at
# entry + 0x34.
DYNAMIC_MODIFIERS = 0xE80
DYNAMIC_ENTRY = 0x40
DYNAMIC = {"definition": 0x18, "enabled": 0x20, "values": 0x28}
DYNAMIC_NAME = 0x28


def read_dynamic_modifiers(memory, country: int) -> list[dict]:
    """[{"id", "values": [float], "enabled"}] of a country object, like the save's dynamic_modifier blocks."""
    raw = memory.read(country + DYNAMIC_MODIFIERS, 16)
    if not raw:
        raise PointerError("unreadable", "The dynamic modifiers of the country are not readable")
    array, capacity, size = struct.unpack("<Qii", raw)
    if size == 0:
        return []
    if not 0 < size <= min(capacity, 200):
        raise PointerError("implausible", f"{size}/{capacity} dynamic modifiers - layout does not match")
    out = []
    for k in range(size):
        entry = array + DYNAMIC_ENTRY * k
        head = memory.read(entry + DYNAMIC["definition"], 0x20)
        if not head:
            raise PointerError("unreadable", "A dynamic modifier is not readable")
        definition, enabled, values, _cap, count = struct.unpack("<QqQii", head)
        name = _msvc_string(memory, definition + DYNAMIC_NAME)
        if not name or not re.fullmatch(r"[A-Za-z0-9_.\-]+", name) or not 0 <= count <= 500:
            raise PointerError("implausible", "A dynamic modifier has no readable id - layout does not match")
        data = memory.read(values, 8 * count) if count else b""
        if data is None:
            raise PointerError("unreadable", f"Values of {name} are not readable")
        out.append({"id": name, "values": [v / 100000 for v in struct.unpack(f"<{count}q", data)],
                    "enabled": enabled != 0})
    return out


# Advisors (2026-10-11, 98/99 countries equal to the save; TUR had hired one in the game day after it):
# [country + 0xff0] = CCountryCharacters; its array + 0x58 (read_array) = hired advisors (CAdvisor*, political
# advisors, theorists, chiefs of staff and high command alike); CAdvisor + 0x80 = slot (std::string),
# [CAdvisor + 0x10] = CCharacter whose int32 + 0xc is the character id of the save.
COUNTRY_CHARACTERS = 0xFF0
HIRED_ADVISORS = 0x58
ADVISOR_CHARACTER = 0x10
ADVISOR_SLOT = 0x80
CHARACTER_ID = 0xC


def read_advisors(memory, country: int) -> list[dict]:
    """Hired advisors of a country object: [{"slot", "id": character id as in the save}]."""
    chars = _ptr(memory, country + COUNTRY_CHARACTERS)
    if chars is None:
        raise PointerError("no_characters", "The country's characters object is not readable")
    out = []
    for adv in read_array(memory, chars + HIRED_ADVISORS, 100):
        slot = _msvc_string(memory, adv + ADVISOR_SLOT) if adv else None
        ch = _ptr(memory, adv + ADVISOR_CHARACTER) if adv else None
        raw = memory.read(ch + CHARACTER_ID, 4) if ch else None
        if not slot or not re.fullmatch(r"[a-z_]+", slot) or raw is None:
            raise PointerError("implausible", "An advisor has no readable slot or character - layout does not match")
        out.append({"slot": slot, "id": str(struct.unpack("<i", raw)[0])})
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


# Leader (2026-10-11, 99/99 countries equal to the save: character and sub-ideology): [ruling party + 0x70] = array
# of CCountryLeader* (read_array), the first one rules; leader + 0x8 = CCharacter (id + 0xc), [leader + 0x140] =
# CIdeology whose std::string + 0x10 is the sub-ideology (e.g. stalinism).
PARTY_LEADERS = 0x70
LEADER_CHARACTER = 0x8
LEADER_IDEOLOGY = 0x140
IDEOLOGY_NAME = 0x10

# Faction (2026-10-11, 99/99 countries: same members in the same order, the faction leader first):
# [[country + 0xf88] (CDiplomacyStatus) + 0x290] = CFaction (NFactions), 0 outside a faction; + 0x38 = name as
# shown (std::string), + 0x58 = members (read_array of CCountry*), + 0x548 = icon sprite (std::string).
# Template and rules are interned tokens there (no text) - they stay from the save.
DIPLOMACY = 0xF88
FACTION = 0x290
FACTION_FIELDS = {"name": 0x38, "members": 0x58, "icon": 0x548}


def read_leader(memory, country: int) -> dict | None:
    """{"id": character id as in the save, "ideology": sub-ideology} of the ruling party's leader, or None."""
    pol = _ptr(memory, country + POLITICS)
    party = _ptr(memory, pol + RULING_PARTY) if pol else None
    if party is None:
        return None
    leaders = read_array(memory, party + PARTY_LEADERS, 50)
    if not leaders or leaders[0] is None:
        return None
    ch = _ptr(memory, leaders[0] + LEADER_CHARACTER)
    raw = memory.read(ch + CHARACTER_ID, 4) if ch else None
    ideology = _ptr(memory, leaders[0] + LEADER_IDEOLOGY)
    name = _msvc_string(memory, ideology + IDEOLOGY_NAME) if ideology else None
    if raw is None or (name is not None and not re.fullmatch(r"[a-z_]+", name)):
        raise PointerError("implausible", "The country leader is not readable - layout does not match")
    return {"id": str(struct.unpack("<i", raw)[0]), "ideology": name}


# Wars (2026-10-13, SOV 1941 at war with GER, 439 countries consistent from both sides, e.g. ENG-GER in both):
# CDiplomacyStatus + 0x8 = array of CRelationStatus* (read_array), one per country slot; relation + 0x50 = slot of
# the other country (int32), + 0x2e8 = CWarRelation or 0 in peace; CWarRelation + 0x10 / + 0x14 = slots of the
# two sides (slot = index in the tag order + 1), the attacker first: GER-SOV, GER-POL, ENG-GER, JAP-CHI (the
# saves' war_relation first="..." with first_was_instigator=yes, the only value seen in 10 text saves).
RELATIONS = 0x8
RELATION_SLOT = 0x50
RELATION_WAR = 0x2E8
WAR_SIDES = 0x10


def read_wars(memory, country: int, order: list[str], tag: str) -> list[dict]:
    """[{"enemy": tag, "offensive": bool}] of the country's wars."""
    dip = _ptr(memory, country + DIPLOMACY)
    if dip is None:
        raise PointerError("unreadable", "The country's diplomacy object is not readable")
    own = order.index(tag) + 1
    out = []
    for relation in read_array(memory, dip + RELATIONS, 2000):
        raw = memory.read(relation, RELATION_WAR + 8) if relation else None
        if raw is None:
            raise PointerError("unreadable", "A diplomatic relation is not readable")
        war = struct.unpack_from("<Q", raw, RELATION_WAR)[0]
        if not war:
            continue
        other = struct.unpack_from("<i", raw, RELATION_SLOT)[0]
        sides = memory.read(war + WAR_SIDES, 8)
        first, second = struct.unpack("<ii", sides) if sides else (0, 0)
        if {first, second} != {own, other} or not 0 < other <= len(order):
            raise PointerError("implausible", "War sides do not match the relation - layout does not match")
        out.append({"enemy": order[other - 1], "offensive": first == own})
    return out


def read_faction(memory, country: int, tags: dict[int, str]) -> dict | None:
    """{"name", "icon", "members": [tag]} of the country's faction (None outside one); `tags` = {object: tag}."""
    dip = _ptr(memory, country + DIPLOMACY)
    if dip is None:
        raise PointerError("unreadable", "The country's diplomacy object is not readable")
    faction = _ptr(memory, dip + FACTION)
    if faction is None:
        return None
    members = [tags.get(c) for c in read_array(memory, faction + FACTION_FIELDS["members"], 500)]
    if not members or None in members:
        raise PointerError("implausible", "Faction members are not countries - layout does not match")
    return {"name": _msvc_string(memory, faction + FACTION_FIELDS["name"]),
            "icon": _msvc_string(memory, faction + FACTION_FIELDS["icon"]), "members": members}


# Doctrines (2026-10-11, 99/99 countries: the save's grand doctrines and subdoctrines, same order):
# [[hoi4.exe + COUNTRY_TABLE[0]] + 0x400] = CDoctrineSystem; [+ 0x8] = inline array of CCountryDoctrineStatus, 0xa0
# bytes each, one per country table slot (entry + 0x8 = the slot); entry + 0x10 = folders (inline, 0x50 bytes each,
# int32 size + 0x1c): folder + 0x10 = CGrandDoctrineTemplate or 0, + 0x18 = tracks (inline, 0x60 bytes each, int32
# size + 0x24 of the folder): track + 0x8 = CSubDoctrineTemplate or 0. Templates hold no id, only the name key
# (std::string + 0x28, e.g. GRAND_DOCTRINE_MASS_ASSAULT) - the id comes from common/doctrines. Unlocked rewards
# are not located yet.
DOCTRINE_SYSTEM = 0x400
DOCTRINE_COUNTRIES = 0x8
DOCTRINE_ENTRY = 0xA0
DOCTRINE_FOLDERS = 0x10
FOLDER_SIZE, TRACK_SIZE = 0x50, 0x60
FOLDER_GRAND, FOLDER_TRACKS = 0x10, 0x18
TRACK_SUB = 0x8
TEMPLATE_NAME = 0x28


def read_doctrines(memory, module_base: int, tags: list[str], tag: str) -> list[str]:
    """Name keys of the grand doctrines and slotted subdoctrines of `tag`, folder by folder, as in the save."""
    table = _ptr(memory, module_base + COUNTRY_TABLE[0])
    system = _ptr(memory, table + DOCTRINE_SYSTEM) if table else None
    array = _ptr(memory, system + DOCTRINE_COUNTRIES) if system else None
    if array is None:
        raise PointerError("no_doctrines", "The doctrine system is not readable")
    slot = tags.index(tag) + 1
    entry = array + DOCTRINE_ENTRY * slot
    raw = memory.read(entry + 8, 24)
    if not raw:
        raise PointerError("unreadable", f"Doctrines of {tag} are not readable")
    own_slot, folders, _cap, count = struct.unpack("<QQii", raw)
    if own_slot != slot or not 0 <= count <= 16:
        raise PointerError("implausible", "Doctrine entry does not belong to the country - layout does not match")
    out = []

    def name(template):
        key = _msvc_string(memory, template + TEMPLATE_NAME)
        if not key or not re.fullmatch(r"[A-Za-z0-9_]+", key):
            raise PointerError("implausible", "A doctrine has no readable name - layout does not match")
        return key
    for k in range(count):
        folder = folders + FOLDER_SIZE * k
        head = memory.read(folder + FOLDER_GRAND, 0x18)
        if not head:
            raise PointerError("unreadable", "A doctrine folder is not readable")
        grand, tracks, _tcap, tcount = struct.unpack("<QQii", head)
        if grand:
            out.append(name(grand))
        if not 0 <= tcount <= 16:
            raise PointerError("implausible", "Doctrine tracks out of range - layout does not match")
        for t in range(tcount):
            sub = _ptr(memory, tracks + TRACK_SIZE * t + TRACK_SUB)
            if sub:
                out.append(name(sub))
    return out


# War support penalties that build up weekly (2026-10-11, before/after one game week at war, SOV vs POL):
# fixed64 / 32768 at country + 0x14c8 (enemy bombing) and + 0x14d0 (combat casualties); equal to the save's
# being_bombed_support_penalty / heroes_dying_war_support_penalty to the 5th decimal in 2 saves (SOV and POL),
# 0 for the 96 countries at peace.
PENALTIES = {"bombing_penalty": 0x14C8, "casualties_penalty": 0x14D0}


# Summed country modifiers (2026-10-13, RTTI CModifier embedded at country + 0x5a8): + 0x10 pointer to entries of
# 16 bytes (int32 modifier index, int64 value fixed64 / 100000) sorted by index, + 0x18 int32 capacity, + 0x1c int32
# size. Index 141 = stability_factor without the ruling party popularity term (93/99 countries equal to the app's
# known modifiers), 149 = war_support_factor incl. world tension (95/99); the rest differed by modifiers the app
# does not know. 145 = war_stability_factor (SOV 1941: 0.02195, "At war" -20 % + 2.195 % = -17.80 % in the game
# tooltip, unchanged a month later). Indices are the engine's modifier order of 1.19.3 (mods append their own
# definitions after it).
COUNTRY_MODIFIER = 0x5A8
MODIFIER_INDEX = {"stability_factor": 141, "war_stability_factor": 145, "war_support_factor": 149}


def read_modifier_sums(memory, country: int) -> dict[str, float]:
    """{"stability_factor", "war_stability_factor", "war_support_factor"}: the game's own sums (0 when none)."""
    raw = memory.read(country + COUNTRY_MODIFIER + 0x10, 16)
    if not raw:
        raise PointerError("unreadable", "Country modifiers are not readable")
    data, capacity, size = struct.unpack("<Qii", raw)
    if size == 0:
        return dict.fromkeys(MODIFIER_INDEX, 0.0)
    if not 0 < size <= min(capacity, 5000) or not 0x10000 <= data < 0x7FFF_FFFF_FFFF:
        raise PointerError("implausible", f"Country modifiers {size}/{capacity} - layout does not match")
    entries = memory.read(data, 16 * size)
    if not entries:
        raise PointerError("unreadable", "Country modifier entries are not readable")
    values = {struct.unpack_from("<i", entries, i)[0]: struct.unpack_from("<q", entries, i + 8)[0] / 100000
              for i in range(0, len(entries), 16)}
    return {name: values.get(index, 0.0) for name, index in MODIFIER_INDEX.items()}


def read_penalties(memory, country: int) -> dict[str, float]:
    """{"bombing_penalty", "casualties_penalty"}: war support penalties as fractions (negative or 0)."""
    raw = memory.read(country + PENALTIES["bombing_penalty"], 16)
    if not raw:
        raise PointerError("unreadable", "War support penalties are not readable")
    out = dict(zip(PENALTIES, (v / 32768 for v in struct.unpack("<qq", raw))))
    if any(not -1.0 <= v <= 0.0 for v in out.values()):
        raise PointerError("implausible", "War support penalties out of range - layout does not match")
    return out


# Research (2026-10-11, SOV: 3 slots, the user started excavation1 and interwar_artillery in slots 1 and 2):
# [country + 0xf60] = CTechnologyStatus; its array + 0xa0 (read_array) = CResearchSlot*, one per research slot;
# slot + 0x18 = CTechnology being researched or 0 (empty), slot + 0x38 = research points per day of the slot
# (fixed64 / 100000; 1.13 for SOV, already divided by the ahead-of-time penalty: 0.20327 for antiair1 2.28 years
# ahead = 1.13 / (1 + 2 x 2.2795)); [CTechnology + 0x160] = CTechnologyTemplate whose std::string + 0x10 is the id;
# CTechnology + 0x198 = research points collected, + 0x190 = extra daily points of this technology (both fixed64 /
# 100000; 2026-10-11 'Badania po 5 dniach': 41.28 / 0.1 for excavation1, 40.68 / 0 for interwar_artillery - the
# save's research_points, and (cost - points) / (speed + extra) gave the 146 / 111 days the game showed).
# Current game date (2026-10-11): int32 at [hoi4.exe + COUNTRY_TABLE[0]] + 0x468 = hours, (year + 5000) x 8760 +
# day of year x 24 + hour (365-day years); 1936 day 263 while the user's save said 1936.9.21, and the ahead-of-time
# penalty of antiair1 (start 1939) computed from it matched the slot speed above.
GAME_DATE = 0x468
TECHNOLOGY_STATUS = 0xF60
RESEARCH_SLOTS = 0xA0
SLOT_TECHNOLOGY = 0x18
SLOT_SPEED = 0x38
TECHNOLOGY_TEMPLATE = 0x160
TEMPLATE_ID = 0x10
TECHNOLOGY_POINTS = 0x198
TECHNOLOGY_BONUS = 0x190


# Limited (one-time) research bonuses (2026-10-11, SOV 1 and GER 2 bonuses, equal to the save's
# technology.limited_use_bonus blocks): CTechnologyStatus + 0xe8 = array of CLimitedUseTechBonus* (read_array);
# bonus + 0x8 = uses left (int32), + 0x10 = name (std::string, localisation key), + 0x30 = id (int32), + 0x50 =
# categories (array of pointers to std::string names, int32 size + 0x5c), + 0x70 = bonus (fixed64 / 100000, 0.5 =
# +50 % research speed).
LIMITED_BONUSES = 0xE8
BONUS = {"uses": 0x8, "name": 0x10, "id": 0x30, "categories": 0x50, "bonus": 0x70}


def read_limited_bonuses(memory, country: int) -> list[dict]:
    """[{"id", "name", "bonus", "uses", "categories": [..]}] - one-time research bonuses of a country object."""
    status = _ptr(memory, country + TECHNOLOGY_STATUS)
    if status is None:
        raise PointerError("no_research", "The country's technology status is not readable")
    out = []
    for item in read_array(memory, status + LIMITED_BONUSES, 200):
        raw = memory.read(item, 0x78) if item else None
        if raw is None:
            raise PointerError("unreadable", "A research bonus is not readable")
        uses, bonus_id = struct.unpack_from("<i", raw, BONUS["uses"])[0], struct.unpack_from("<i", raw, BONUS["id"])[0]
        bonus = struct.unpack_from("<q", raw, BONUS["bonus"])[0] / 100000
        categories = [_msvc_string(memory, c) for c in read_array(memory, item + BONUS["categories"], 50) if c]
        name = _msvc_string(memory, item + BONUS["name"])
        # a bonus may have no name (USA 1936: +75 %, id 9, empty string) - only an unreadable one is wrong;
        # used up bonuses keep 0 uses in memory (the service hides them)
        if not 0 <= uses <= 1000 or not 0 <= bonus <= 100 or name is None or None in categories:
            raise PointerError("implausible", "Research bonus out of range - layout does not match")
        out.append({"id": bonus_id, "name": name, "bonus": bonus, "uses": uses, "categories": categories})
    return out


# Researched technologies (2026-10-11): CTechnologyStatus + 0x40 = array of CTechnology* (read_array), 52 for SOV
# in 1936, without the ones in progress; name through TECHNOLOGY_TEMPLATE as for the research slots.
RESEARCHED = 0x40


def read_researched(memory, country: int) -> list[str]:
    status = _ptr(memory, country + TECHNOLOGY_STATUS)
    if status is None:
        raise PointerError("no_research", "The country's technology status is not readable")
    out = []
    for tech in read_array(memory, status + RESEARCHED, 2000):
        template = _ptr(memory, tech + TECHNOLOGY_TEMPLATE) if tech else None
        name = _msvc_string(memory, template + TEMPLATE_ID) if template else None
        if not name or not re.fullmatch(r"[A-Za-z0-9_.\-]+", name):
            raise PointerError("implausible", "A researched technology has no readable id - layout does not match")
        out.append(name)
    return out


def read_date(memory, module_base: int) -> dict:
    """{"year", "day" (0-based day of the year), "hour"} of the running game."""
    table = _ptr(memory, module_base + COUNTRY_TABLE[0])
    raw = memory.read(table + GAME_DATE, 4) if table else None
    if raw is None:
        raise PointerError("unreadable", "The game date is not readable")
    hours = struct.unpack("<i", raw)[0]
    year, rest = divmod(hours, 8760)
    if not 1000 <= year - 5000 <= 9999:
        raise PointerError("implausible", "Game date out of range - layout does not match")
    return {"year": year - 5000, "day": rest // 24, "hour": rest % 24}


def read_research(memory, country: int) -> list[dict]:
    """[{"slot": 1.., "technology": id or None, "speed": factor, "points", "bonus"}] - one entry per research slot
    (points = research points collected, bonus = extra points per day of that technology; None when empty)."""
    status = _ptr(memory, country + TECHNOLOGY_STATUS)
    if status is None:
        raise PointerError("no_research", "The country's technology status is not readable")
    out = []
    for i, slot in enumerate(read_array(memory, status + RESEARCH_SLOTS, 20), start=1):
        raw = memory.read(slot + SLOT_TECHNOLOGY, 0x28) if slot else None
        if raw is None:
            raise PointerError("unreadable", "A research slot is not readable")
        tech, speed = struct.unpack_from("<Q", raw, 0)[0], struct.unpack_from("<q", raw, SLOT_SPEED - SLOT_TECHNOLOGY)[0]
        name, points, bonus = None, None, None
        if tech:
            extra = memory.read(tech + TECHNOLOGY_BONUS, 16)
            if extra is None:
                raise PointerError("unreadable", "A researched technology is not readable")
            bonus, points = (v / 100000 for v in struct.unpack("<qq", extra))
            if not 0 <= points <= 100_000 or not -10 <= bonus <= 100:
                raise PointerError("implausible", "Research progress out of range - layout does not match")
            template = _ptr(memory, tech + TECHNOLOGY_TEMPLATE)
            name = _msvc_string(memory, template + TEMPLATE_ID) if template else None
            if not name or not re.fullmatch(r"[A-Za-z0-9_.\-]+", name):
                raise PointerError("implausible", "A researched technology has no readable id - layout does not match")
        if not 0 <= speed / 100000 <= 100:
            raise PointerError("implausible", "Research speed out of range - layout does not match")
        out.append({"slot": i, "technology": name, "speed": speed / 100000, "points": points, "bonus": bonus})
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
# +0x40 -> array of completed focus definitions, +0x48 = capacity, +0x4c = count (int32). FIX 2026-10-13 (user: USA
# showed 30 completed focuses without any taken): the count was read from the capacity (+0x48, e.g. 42), so stale
# slots behind the real entries counted as completed; with +0x4c 15/15 countries equal the save's completed focuses
# (SPR one more: completed after the autosave).
# [country + 0x1370] = CNationalFocusTree of the country, + 0x8 = its id (std::string, the focus_tree id of
# common/national_focus; 439/439 countries known, 2026-10-13: usa_focus, german_focus, mexico_focus_tree ...).
FOCUS = {"state": 0x1380, "definition": 0x10, "id": 0x18, "progress": 0x38, "completed": 0x40, "completed_count": 0x4C,
         "tree": 0x1370, "tree_id": 0x8}
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
    """{"tree": focus tree id or None, "current": focus id or None, "progress_days": float, "completed": [ids]}."""
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
    tree = _ptr(memory, country + FOCUS["tree"])
    tree_id = (_msvc_string(memory, tree + FOCUS["tree_id"]) if tree else None) or None
    if tree_id is not None and not re.fullmatch(r"[A-Za-z0-9_.\-]{1,200}", tree_id):
        raise PointerError("implausible", f"Focus tree id {tree_id!r} does not look like an id - layout does not match")
    return {"tree": tree_id, "current": current or None, "progress_days": progress, "completed": completed}


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


# Construction queue (2026-10-13, FRA 1936 / SOV 1941 equal to the game's construction screen: lines in its order,
# state, levels, factories 15/15, 4/15 ..., progress and speed as the tooltip): [country + 0xf68] = CProductionStatus,
# + 0x70 = array of line pointers (read_array) in queue order, two classes told apart by their vtable (offset from the
# module base, 1.19.3):
# - CBuildingProductionLine: + 0xc = id (the save's general_lines id, type 59), + 0x18 = factories assigned (int32),
#   + 0x28 = cost of one level, + 0x30 = construction speed per day, + 0x38 = progress of the current level (fixed64
#   / 100000; SOV Krasnoyarsk 6309.79 / 7200 at 183.75 a day as the game tooltip), + 0x48 = levels still to build
#   (the save's amount), + 0x78 = levels to repair (the save's to_repair: 0 when building, SOV rail_way 1, infra 2 -
#   those lines have 0 levels to build), + 0x70 = CBuilding; CBuilding + 0x1d8 = CBuildingStatus (+ 0x6c = state id,
#   province id for province buildings: rail_way 11490, bunker), + 0x1e0 = CBuildingTemplate (+ 0x270 = its id,
#   std::string, e.g. "arms_factory");
# - CRailwayProductionLine (railway along a path): same fields up to + 0x48 (railways still needed, one per segment),
#   + 0x70 / + 0x74 = railway level from / to (int32), + 0x80 = path (int32 province ids, size at + 0x8c). FRA 1941
#   "Constantine - Algiers" as the game tooltip: upgrading level 2 railways to level 3, 4 railways needed, 6 provinces.
PRODUCTION_STATUS = 0xF68
CONSTRUCTION_LINES = 0x70
LINE_VTABLES = {0x297B958: "building", 0x2A2BE90: "railway"}
LINE = {"id": 0xC, "factories": 0x18, "cost": 0x28, "speed": 0x30, "produced": 0x38, "levels": 0x48, "building": 0x70,
        "repair": 0x78, "path": 0x80, "from_level": 0x70, "to_level": 0x74}
BUILDING = {"status": 0x1D8, "template": 0x1E0}
LINE_POSITION = 0x44   # int32 queue position (0-based, the save's priority - 1), kept equal to the array index
STATUS_LOCATION = 0x6C
BUILDING_NAME = 0x270


def read_construction(memory, country: int, module_base: int) -> list[dict]:
    """[{"id", "kind": "building" | "railway", "building", "location", "path", "levels", "repair", "factories", "cost",
    "speed", "produced", "railway_levels"}] in queue order. speed = construction points a day; location = state id, or
    province id for province buildings (None for a railway); path = province ids of a railway ([] otherwise); levels of
    a railway = railways still needed; railway_levels = (from, to) of a railway, else None."""
    status = _ptr(memory, country + PRODUCTION_STATUS)
    if status is None:
        raise PointerError("no_production", "The country's production status is not readable")
    out = []
    for line in read_array(memory, status + CONSTRUCTION_LINES, 5000):
        raw = memory.read(line, 0x90) if line else None
        if raw is None:
            raise PointerError("unreadable", "A construction line is not readable")
        kind = LINE_VTABLES.get(struct.unpack_from("<Q", raw, 0)[0] - module_base)
        if kind is None:
            raise PointerError("implausible", "Unknown construction line type - layout does not match")
        i32 = lambda key: struct.unpack_from("<i", raw, LINE[key])[0]  # noqa: E731
        cost, speed, produced = (struct.unpack_from("<q", raw, LINE[k])[0] / 100000 for k in ("cost", "speed", "produced"))
        name, location, path, repair, railway_levels = "rail_way", None, [], 0, None
        if kind == "building":
            building = struct.unpack_from("<Q", raw, LINE["building"])[0]
            template = _ptr(memory, building + BUILDING["template"])
            name = _msvc_string(memory, template + BUILDING_NAME) if template else None
            status_obj = _ptr(memory, building + BUILDING["status"])
            loc = memory.read(status_obj + STATUS_LOCATION, 4) if status_obj else None
            location = struct.unpack("<i", loc)[0] if loc else None
            repair = i32("repair")
        else:
            provinces = memory.read(line + LINE["path"], 16)
            data, _cap, size = struct.unpack("<Qii", provinces) if provinces else (0, 0, -1)
            items = memory.read(data, 4 * size) if 0 < size <= 10_000 else None
            path = list(struct.unpack(f"<{size}i", items)) if items else []
            railway_levels = (i32("from_level"), i32("to_level"))
            if (not path or not all(0 < p < 100_000 for p in path)
                    or not 0 <= railway_levels[0] <= railway_levels[1] <= 100):
                raise PointerError("implausible", "Railway line is not readable - layout does not match")
        if (not name or not re.fullmatch(r"[A-Za-z0-9_.\-]+", name) or not 0 <= i32("factories") <= 1000
                or not 0 < cost < 10_000_000 or not 0 <= produced <= cost or not 0 <= speed < 1_000_000
                or not 0 <= i32("levels") <= 1000 or not 0 <= repair <= 1000
                or location is not None and not 0 < location < 100_000):
            raise PointerError("implausible", "A construction line is out of range - layout does not match")
        out.append({"id": i32("id"), "kind": kind, "building": name, "location": location, "path": path,
                    "levels": i32("levels"), "repair": repair, "factories": i32("factories"), "cost": cost,
                    "speed": speed, "produced": produced, "railway_levels": railway_levels})
    return out


# Civilian factories (2026-10-13, SOV 1941 equal to the game's construction screen, cons_goods.png: 161/161, from
# trade 38, owned 123, consumer goods 60, market contracts 1, national projects 5, traded goods 3): CProductionStatus
# int32 fields + 0x43c = all civilian factories, + 0x3c8 = from trade, + 0x440 = consumer goods, + 0x4a0 = market
# contracts, + 0x458 = national projects, + 0x488 = traded goods (the task fields are 0x18 apart; GER 61 / 12 / 8 /
# 18, HOL 1 / 1 / 0 / 0 consistent with what is left after each task at + 0x454 and + 0x46c).
FACTORIES = {"total": 0x43C, "from_trade": 0x3C8, "consumer_goods": 0x440, "market_contracts": 0x4A0,
             "national_projects": 0x458, "traded_goods": 0x488}


def read_civilian_factories(memory, country: int) -> dict[str, int]:
    """{"total", "from_trade", "owned", "consumer_goods", "market_contracts", "national_projects", "traded_goods",
    "free"} - civilian factories of a country and what they are used for; free = left for construction."""
    status = _ptr(memory, country + PRODUCTION_STATUS)
    raw = memory.read(status + 0x3C8, 0xE0) if status else None
    if raw is None:
        raise PointerError("unreadable", "The country's production status is not readable")
    out = {k: struct.unpack_from("<i", raw, off - 0x3C8)[0] for k, off in FACTORIES.items()}
    used = sum(out[k] for k in ("consumer_goods", "market_contracts", "national_projects", "traded_goods"))
    out.update(owned=out["total"] - out["from_trade"], free=max(0, out["total"] - used))
    if not 0 <= out["total"] <= 100_000 or any(v < 0 for v in out.values()):
        raise PointerError("implausible", "Civilian factories out of range - layout does not match")
    return out



def construction_slots(memory, country: int) -> tuple[int, list[int]]:
    """(address of the line pointer array, [line pointers]) of the country's construction queue."""
    status = _ptr(memory, country + PRODUCTION_STATUS)
    if status is None:
        raise PointerError("no_production", "The country's production status is not readable")
    lines = read_array(memory, status + CONSTRUCTION_LINES, 5000)
    data = _ptr(memory, status + CONSTRUCTION_LINES)
    if lines and data is None or None in lines:
        raise PointerError("unreadable", "The construction queue is not readable")
    return data or 0, lines


def write_construction_order(writer, data: int, lines: list[int], order: list[int]) -> int:
    """Puts the queue in `order` (indices into `lines`, the pointers read at `data`): pointer array slots and each
    line's position field; returns how many slots changed. The same lines must stay in the queue."""
    if sorted(order) != list(range(len(lines))):
        raise PointerError("implausible", "The new order is not a permutation of the queue")
    changed = 0
    for i, k in enumerate(order):
        if k != i:
            writer.write(data + 8 * i, struct.pack("<Q", lines[k]))
            changed += 1
    for i, k in enumerate(order):
        pos = writer.read(lines[k] + LINE_POSITION, 4)
        if pos is None or struct.unpack("<i", pos)[0] != i:
            writer.write(lines[k] + LINE_POSITION, struct.pack("<i", i))
    return changed


# Relations between two countries (2026-10-13, USA 1936): [country + 0xf88] CDiplomacyStatus + 0x8 = array of
# CRelationStatus*, index = slot of the other country (index in the tag order + 1). Relation + 0x300 = opinion of
# the other country (int32; USA of GER -20, GER of USA -10, ENG of USA +22, MEX of USA -10 as the game tooltips).
# + 0x270 .. + 0x2f0 = pointers to relation objects, told apart by their vtable (module offset, 1.19.3): subject,
# guarantee, non-aggression pact, embargo, war, military access, lend-lease; each holds the slots of its two sides
# at + 0x10 / + 0x14, the first being the overlord / guarantor / attacker (USA-PHI, ENG-MAL, FRA-CZE, ITA-ETH).
RELATION_OPINION = 0x300
RELATION_LINKS = range(0x270, 0x2F8, 8)
RELATION_KINDS = {0x2960A08: "subject", 0x29607C8: "guarantee", 0x2960888: "non_aggression_pact",
                  0x2960B60: "embargo", 0x2960288: "war", 0x2960408: "military_access", 0x2960948: "lend_lease"}


def read_relation(memory, country: int, other_slot: int, module_base: int) -> dict:
    """{"opinion": the country's opinion of the other one, "links": {kind: (first slot, second slot)}}."""
    dip = _ptr(memory, country + DIPLOMACY)
    if dip is None:
        raise PointerError("unreadable", "The country's diplomacy object is not readable")
    raw = memory.read(dip + RELATIONS, 16)
    data, _cap, size = struct.unpack("<Qii", raw) if raw else (0, 0, 0)
    if not 0 <= other_slot < size:
        raise PointerError("implausible", "No relation slot for that country - layout does not match")
    rel = _ptr(memory, data + 8 * other_slot)
    body = memory.read(rel, RELATION_OPINION + 4) if rel else None
    if body is None or struct.unpack_from("<i", body, RELATION_SLOT)[0] != other_slot:
        raise PointerError("implausible", "Relation is for another country - layout does not match")
    opinion = struct.unpack_from("<i", body, RELATION_OPINION)[0]
    if not -1000 <= opinion <= 1000:
        raise PointerError("implausible", "Opinion out of range - layout does not match")
    links = {}
    for off in RELATION_LINKS:
        obj = struct.unpack_from("<Q", body, off)[0]
        head = memory.read(obj, 0x18) if 0x10000 <= obj < 0x7FFF_FFFF_FFFF else None
        if not head:
            continue
        kind = RELATION_KINDS.get(struct.unpack_from("<Q", head, 0)[0] - module_base)
        if kind:
            links[kind] = struct.unpack_from("<ii", head, 0x10)
    return {"opinion": opinion, "links": links}


# Wargoal justifications (2026-10-13, GER justifying against USA in the game; every other country empty):
# [country + 0xf90] CPoliticalStatus + 0x8 = array of CTimedWargoalActivity* (read_array); activity + 0x10 / + 0x14 =
# slots of the justifying country and of its target (1 GER -> 68 USA).
JUSTIFICATIONS = 0x8
JUSTIFICATION_SIDES = 0x10


def read_justifications(memory, country: int) -> list[tuple[int, int]]:
    """[(slot of the justifying country, slot of the target)] of a country's wargoal justifications in progress."""
    pol = _ptr(memory, country + POLITICS)
    if pol is None:
        raise PointerError("no_politics", "The country's politics object is not readable")
    out = []
    for act in read_array(memory, pol + JUSTIFICATIONS, 200):
        raw = memory.read(act + JUSTIFICATION_SIDES, 8) if act else None
        if raw is None:
            raise PointerError("unreadable", "A wargoal justification is not readable")
        sides = struct.unpack("<ii", raw)
        if not all(0 < s < 5000 for s in sides):
            raise PointerError("implausible", "Wargoal justification sides out of range - layout does not match")
        out.append(sides)
    return out


# Starting a focus (2026-10-13, USA 1936: the user picked USA_continue_the_new_deal in the paused game, memory
# before/after): the game sets the focus progress object's definition (+ 0x10) and keeps the saved days (+ 0x38, at
# most MAX_SAVED_FOCUS_PROGRESS = 10) - for which it takes political power ("Picking a focus will use 10 PP"). The
# app's start (user's choice) drops the saved days instead: progress 0, political power unchanged.
# The focuses of a tree: CNationalFocusTree + 0x30 = array of CNationalFocus* (read_array; USA 146 incl. shared).
TREE_FOCUSES = 0x30


def focus_definition(memory, country: int, focus_id: str) -> int | None:
    """Address of the CNationalFocus with id `focus_id` in the country's focus tree, or None."""
    tree = _ptr(memory, country + FOCUS["tree"])
    if tree is None:
        raise PointerError("unreadable", "The country's focus tree is not readable")
    for definition in read_array(memory, tree + TREE_FOCUSES, 5000):
        if definition and _msvc_string(memory, definition + FOCUS["id"]) == focus_id:
            return definition
    return None


def write_focus_start(writer, country: int, definition: int) -> None:
    """Makes `definition` the country's current focus with 0 days of progress. Only when no focus is selected."""
    state = _ptr(writer, country + FOCUS["state"])
    if state is None:
        raise PointerError("unreadable", "Focus state of the country is not readable")
    if _ptr(writer, state + FOCUS["definition"]) is not None:
        raise PointerError("busy", "A focus is already selected")
    writer.write(state + FOCUS["progress"], struct.pack("<q", 0))      # first: no saved days carried over
    writer.write(state + FOCUS["definition"], struct.pack("<Q", definition))


# Factories (2026-10-13, GER 1941 equal to the game's factory tooltip, fabryk.png: military 268 = owned 208 +
# occupation 61 + subjects 2 - damaged 3; dockyards 23 = 11 + 12; civilian 182 = 71 + 71 + 10 + trade 30; energy
# demand 4091.6 (97.1 %), generated 3974.0, 383 coal used). CProductionStatus holds one block per factory type
# (military + 0x2b0, dockyards + 0x310, civilian + 0x370): + 0x8 = total before damage, + 0x18 = owned, + 0x20 =
# damaged (fixed64 / 100000), + 0x44 = received from subjects, + 0x48 = given to the overlord (a subject: MAL 7
# military, 12 civilian), + 0x58 = from trade (civilian) (int32), + 0x38 = energy coverage (fixed64). Energy: + 0x508
# generated, + 0x530 demand, + 0x4f8 coal used, + 0x528 coal needed. The game shows whole numbers: total = floor(total)
# - floor(damaged) - given, owned = floor(owned), subject relations = received - given, occupation = the rest
# (civilian total = the verified CProductionStatus + 0x43c for 439/439 countries).
FACTORY_BLOCKS = {"military": 0x2B0, "dockyards": 0x310, "civilian": 0x370}
FACTORY_FIELDS = {"total": 0x8, "owned": 0x18, "damaged": 0x20, "energy_coverage": 0x38, "subjects": 0x44,
                  "to_overlord": 0x48, "trade": 0x58}
ENERGY = {"generated": 0x508, "demand": 0x530, "coal_used": 0x4F8, "coal_needed": 0x528}


def read_factories(memory, country: int) -> dict:
    """{"military"|"dockyards"|"civilian": {"total", "owned", "occupation", "subjects" (received - given to the
    overlord), "trade", "damaged"} as the
    game's factory tooltip shows them, "energy": {"demand", "generated", "coverage", "coal_used", "coal_needed"}}."""
    status = _ptr(memory, country + PRODUCTION_STATUS)
    raw = memory.read(status, 0x540) if status else None
    if raw is None:
        raise PointerError("unreadable", "The country's production status is not readable")
    fx = lambda off: struct.unpack_from("<q", raw, off)[0] / 100000  # noqa: E731
    i32 = lambda off: struct.unpack_from("<i", raw, off)[0]  # noqa: E731
    out = {}
    for kind, block in FACTORY_BLOCKS.items():
        total, owned, damaged = (fx(block + FACTORY_FIELDS[k]) for k in ("total", "owned", "damaged"))
        received, given = i32(block + FACTORY_FIELDS["subjects"]), i32(block + FACTORY_FIELDS["to_overlord"])
        trade = i32(block + FACTORY_FIELDS["trade"]) if kind == "civilian" else 0
        if not (0 <= owned <= total + 1e-6 <= 100_000 and 0 <= damaged <= total + 1e-6 and 0 <= received <= 10_000
                and 0 <= given <= total + 1e-6 and 0 <= trade <= 10_000):
            raise PointerError("implausible", f"{kind} factories out of range - layout does not match")
        dmg = math.floor(damaged + 1e-6)
        shown = math.floor(total + 1e-6) - dmg - given
        out[kind] = {"total": shown, "owned": math.floor(owned + 1e-6), "subjects": received - given, "trade": trade,
                     "damaged": dmg, "raw": round(total, 3)}
        out[kind]["occupation"] = shown - out[kind]["owned"] - (received - given) - trade + dmg
    energy = {k: round(fx(v), 3) for k, v in ENERGY.items()}
    energy["coverage"] = round(fx(FACTORY_BLOCKS["military"] + FACTORY_FIELDS["energy_coverage"]), 5)
    if not (0 <= energy["demand"] < 1e7 and 0 <= energy["generated"] < 1e7 and 0 <= energy["coverage"] <= 1.5):
        raise PointerError("implausible", "Energy out of range - layout does not match")
    out["energy"] = energy
    return out


# Doctrine mastery (2026-10-13, SOV 1941 equal to the game's doctrine screen, Doktryny.png): each track of a folder
# (TRACK_SIZE bytes) holds + 0x8 the slotted subdoctrine (0 = empty), + 0x10 rewards unlocked (int32; 221 -> 2,
# 148 -> 1, 5 -> 0), + 0x18 mastery (fixed64 / 100000: 221.82, 5.63, 148.0), + 0x20 banked mastery of an empty or
# finished track (68.75 shown "+68"; at most MASTERY_BANK_MAX 200), + 0x28 mastery gained per day (fixed64).
TRACK_FIELDS = {"rewards": 0x10, "mastery": 0x18, "bank": 0x20, "daily": 0x28}


def read_doctrine_state(memory, module_base: int, tags: list[str], tag: str) -> list[dict]:
    """[{"grand": name key or None, "tracks": [{"sub": name key or None, "mastery", "bank", "daily", "rewards"}]}]
    folder by folder in the order of common/doctrines/folders (land, naval, air, special forces)."""
    table = _ptr(memory, module_base + COUNTRY_TABLE[0])
    system = _ptr(memory, table + DOCTRINE_SYSTEM) if table else None
    array = _ptr(memory, system + DOCTRINE_COUNTRIES) if system else None
    if array is None:
        raise PointerError("no_doctrines", "The doctrine system is not readable")
    slot = tags.index(tag) + 1
    raw = memory.read(array + DOCTRINE_ENTRY * slot + 8, 24)
    if not raw:
        raise PointerError("unreadable", f"Doctrines of {tag} are not readable")
    own_slot, folders, _cap, count = struct.unpack("<QQii", raw)
    if own_slot != slot or not 0 <= count <= 16:
        raise PointerError("implausible", "Doctrine entry does not belong to the country - layout does not match")

    def name(template):
        key = _msvc_string(memory, template + TEMPLATE_NAME) if template else None
        if template and (not key or not re.fullmatch(r"[A-Za-z0-9_]+", key)):
            raise PointerError("implausible", "A doctrine has no readable name - layout does not match")
        return key
    out = []
    for k in range(count):
        head = memory.read(folders + FOLDER_SIZE * k + FOLDER_GRAND, 0x18)
        if not head:
            raise PointerError("unreadable", "A doctrine folder is not readable")
        grand, tracks, _tcap, tcount = struct.unpack("<QQii", head)
        if not 0 <= tcount <= 16:
            raise PointerError("implausible", "Doctrine tracks out of range - layout does not match")
        items = []
        for t in range(tcount):
            tr = memory.read(tracks + TRACK_SIZE * t, TRACK_SIZE)
            if not tr:
                raise PointerError("unreadable", "A doctrine track is not readable")
            fx = lambda off: struct.unpack_from("<q", tr, off)[0] / 100000  # noqa: E731
            item = {"sub": name(struct.unpack_from("<Q", tr, TRACK_SUB)[0]),
                    "rewards": struct.unpack_from("<i", tr, TRACK_FIELDS["rewards"])[0],
                    "mastery": round(fx(TRACK_FIELDS["mastery"]), 3), "bank": round(fx(TRACK_FIELDS["bank"]), 3),
                    "daily": round(fx(TRACK_FIELDS["daily"]), 4)}
            if not (0 <= item["rewards"] <= 50 and 0 <= item["mastery"] <= 100_000 and 0 <= item["bank"] <= 100_000
                    and 0 <= item["daily"] <= 1000):
                raise PointerError("implausible", "Doctrine mastery out of range - layout does not match")
            items.append(item)
        out.append({"grand": name(grand), "tracks": items})
    return out


# Army, navy and air force (2026-10-13, SOV 1941 equal to the game's military overview, Army.png / Navy.png /
# Air.png). Army: country + 0x290 = array of CArmy* - one per division (390); division + 0x3b8 = its
# CReferencedDivisionTemplate; country + 0x1b8 = array of the country's templates: + 0x20 name (std::string),
# + 0x68 battalion grid (CSubUnitDefinition*, empty slots have an empty id), + 0x88 support companies, + 0xa8
# regimental support; CSubUnitDefinition + 0x18 = its id ("infantry"). Strelkovaya Diviziya 350 / NKVD 15 /
# Gornostrelkovaya 13 / Mekhanizirovaniy Korpus 12 as the game; country + 0x348 = manpower in the field (4.35M,
# "4M"), + 0x338 = in training (int32; SOV 1941-11-01: 4 447 000 / 295 000, the game rounds both lines to two
# significant digits: "4.40M" / "300.00K", army "4.70M"). Navy: country + 0x278 = array of CFleet* (5), fleet +
# 0xb8 = CTaskForce* (9), task force + 0x348 =
# CShip* (119: 93 submarines, 18 destroyers, 5 light cruisers, 3 battleships); ship + 0x98 = type id, + 0x60 =
# variants (CEquipmentVariant*, its name = the class). Air: [game state + 0x690] = CStrategicAirManager, + 0x30 =
# array of CStrategicAir* by country slot; + 0x58 = its pools (CAirWingPool*): + 0x20 the role (CSubUnitDefinition,
# "fighter"), + 0x28 the wings (CAirWing*): + 0x1f8 = entries of 16 bytes (CEquipmentVariant*, planes fixed64) -
# I-16 100 fighters and DB-3 100 tactical bombers (an I-15 wing at the same air base is SIK's). A plane design's
# stats are fixed64 in the variant (PLANE_STATS, all equal to the game's design tooltip of the I-16).
ARMY = {"divisions": 0x290, "templates": 0x1B8, "division_template": 0x3B8, "manpower_field": 0x348,
        "manpower_training": 0x338}
# Free manpower (2026-10-13, SOV 1941-11-01): kept per state, as manpower_pool = { available locked total } in the
# save. [game state + 0x2c8] = array of CState* indexed by state id (1082 slots, slot 0 empty); state + 0xc8 = owner,
# + 0xcc = controller (country slot = tag index + 1, owner 439/439 tags equal to the owned state count), + 0x848 /
# + 0x84c / + 0x850 = available / locked / total (int32). Two `manpower 100000` in a paused game changed + 0x848 in
# 141 states by exactly 100 000 in all; the available manpower of the states SOV controls = 461 566 = the game's
# "Free Manpower: 461.56K" (by owner: 462 574 - occupied states do not count).
STATES = 0x2C8
STATE = {"owner": 0xC8, "controller": 0xCC, "available": 0x848, "locked": 0x84C, "total": 0x850}
DIVISION_TEMPLATE = {"name": 0x20, "battalions": 0x68, "support": 0x88, "regimental": 0xA8}
SUBUNIT_ID = 0x18
NAVY = {"fleets": 0x278, "task_forces": 0xB8, "ships": 0x348, "ship_type": 0x98, "ship_variants": 0x60}
AIR = {"manager": 0x690, "by_country": 0x30, "pools": 0x58, "role": 0x20, "wings": 0x28, "wing_variants": 0x1F8}
PLANE_STATS = {"range": 0x270, "air_defence": 0x278, "air_attack": 0x280, "air_agility": 0x288,
               "air_superiority": 0x298, "naval_strike_attack": 0x2A0, "naval_strike_targetting": 0x2A8,
               "maximum_speed": 0x2F0, "reliability": 0x308, "weight": 0x318, "thrust": 0x320,
               "fuel_consumption": 0x328, "build_cost_ic": 0x368}


def _id_list(memory, address: int) -> list[str]:
    """Ids of the CSubUnitDefinition* array at `address` (empty grid slots left out)."""
    out = []
    for item in read_array(memory, address, 200):
        name = _msvc_string(memory, item + SUBUNIT_ID) if item else None
        if name:
            out.append(name)
    return out


def read_army(memory, country: int) -> dict:
    """{"divisions", "manpower_field", "templates": [{"name", "count", "battalions", "support", "regimental"}]}."""
    divisions = read_array(memory, country + ARMY["divisions"], 20_000)
    counts: dict[int, int] = {}
    for d in divisions:
        t = _ptr(memory, d + ARMY["division_template"]) if d else None
        if t:
            counts[t] = counts.get(t, 0) + 1
    templates = []
    for t in read_array(memory, country + ARMY["templates"], 2000):
        if not t:
            continue
        name = _msvc_string(memory, t + DIVISION_TEMPLATE["name"])
        if name is None:
            raise PointerError("implausible", "A division template has no readable name - layout does not match")
        templates.append({"name": name, "count": counts.get(t, 0),
                          **{k: _id_list(memory, t + DIVISION_TEMPLATE[k]) for k in ("battalions", "support", "regimental")}})
    men = {}
    for key in ("manpower_field", "manpower_training"):
        raw = memory.read(country + ARMY[key], 4)
        men[key] = struct.unpack("<i", raw)[0] if raw else None   # int32 (the next 4 bytes are another field)
        if men[key] is not None and not 0 <= men[key] < 10**9:
            raise PointerError("implausible", f"{key} out of range - layout does not match")
    return {"divisions": len(divisions), **men, "templates": templates}


def read_free_manpower(memory, module_base: int, tags: list[str], tag: str) -> int:
    """Free manpower of `tag`: the available manpower of the states it controls (game memory)."""
    table = _ptr(memory, module_base + COUNTRY_TABLE[0])
    if table is None:
        raise PointerError("no_country_table", "The game state is not readable")
    slot = tags.index(tag) + 1
    total = 0
    for state in read_array(memory, table + STATES, 5000):
        raw = memory.read(state + STATE["controller"], 4) if state else None
        if not raw or struct.unpack("<i", raw)[0] != slot:
            continue
        available = struct.unpack("<i", memory.read(state + STATE["available"], 4) or b"\0\0\0\0")[0]
        if not 0 <= available < 10**9:
            raise PointerError("implausible", "State manpower out of range - layout does not match")
        total += available
    return total


def _variant_entries(memory, address: int, limit: int = 20) -> list[tuple[int, float]]:
    """[(CEquipmentVariant*, amount)] of a 16-byte entry array (pointer, fixed64) at `address`."""
    raw = memory.read(address, 16)
    data, _cap, size = struct.unpack("<Qii", raw) if raw else (0, 0, 0)
    if not 0 <= size <= limit:
        raise PointerError("implausible", "Equipment entries out of range - layout does not match")
    items = memory.read(data, 16 * size) if size else b""
    if size and not items:
        raise PointerError("unreadable", "Equipment entries are not readable")
    return [(struct.unpack_from("<Q", items, 16 * k)[0], struct.unpack_from("<q", items, 16 * k + 8)[0] / 100000)
            for k in range(size)]


def read_navy(memory, country: int) -> dict:
    """{"fleets", "task_forces", "ships": [{"type", "class", "count"}]}."""
    fleets = read_array(memory, country + NAVY["fleets"], 2000)
    task_forces, ships = 0, {}
    for f in fleets:
        for tf in read_array(memory, f + NAVY["task_forces"], 2000) if f else []:
            task_forces += 1
            for s in read_array(memory, tf + NAVY["ships"], 2000) if tf else []:
                kind = _msvc_string(memory, s + NAVY["ship_type"]) if s else None
                variants = _variant_entries(memory, s + NAVY["ship_variants"]) if s else []
                cls = _msvc_string(memory, variants[0][0] + VARIANT["name"], 120) if variants and variants[0][0] else None
                key = (kind or "unknown", cls or "")
                ships[key] = ships.get(key, 0) + 1
    return {"fleets": len(fleets), "task_forces": task_forces,
            "ships": [{"type": k, "class": c, "count": n} for (k, c), n in sorted(ships.items(), key=lambda x: -x[1])]}


def plane_stats(memory, variant: int) -> dict[str, float] | None:
    """Design stats of a plane variant (None when it is not a plane: no agility or no speed)."""
    raw = memory.read(variant, 0x370)
    if not raw:
        return None
    stats = {k: round(struct.unpack_from("<q", raw, off)[0] / 100000, 4) for k, off in PLANE_STATS.items()}
    return stats if stats["air_agility"] > 0 and stats["maximum_speed"] > 0 else None


# Equipment designs the division designer uses (2026-10-13, SOV 1941): [country + 0xf68] (production) + 0xb8 = array
# of CEquipmentVariant* - the newest design of each equipment type (47 for SOV: PPSz-41, 122-mm M-30, Plot. M1940 25 mm
# as the designer's equipment list; one per archetype for land equipment without a designer; tanks, planes and ships
# have several). + 0xa0 = all the country's designs (92). Variant + 0x3f0 = CEquipmentType (+ 0x18 = its id, std::string),
# + 0x28 = design name; land stats fixed64 / 100000 with the equipment bonuses included (PPSz-41: hard attack 1.875 =
# 1.5 + 25% army spirit, soft attack 10.215, reliability 0.972; tanks: hardness 0.8 / 0.85 / 0.95 for light / medium /
# heavy, BT-7 armor 31.25).
DESIGNS = {"current": 0xB8, "all": 0xA0, "type": 0x3F0, "type_id": 0x18}
LAND_STATS = {"defense": 0x108, "breakthrough": 0x110, "hardness": 0x118, "soft_attack": 0x120, "hard_attack": 0x128,
              "air_attack": 0x280, "maximum_speed": 0x2F0, "armor_value": 0x2F8, "ap_attack": 0x300, "reliability": 0x308,
              "build_cost_ic": 0x368}


def read_designs(memory, country: int) -> list[dict]:
    """[{"type": equipment id, "name": design name or "", "stats": {LAND_STATS}}] of the newest design of each
    equipment type (what the division designer uses)."""
    production = _ptr(memory, country + STOCKPILE["production"])
    if production is None:
        raise PointerError("unreadable", "Production object of the country is not readable")
    out = []
    for variant in read_array(memory, production + DESIGNS["current"], 2000):
        etype = _ptr(memory, variant + DESIGNS["type"]) if variant else None
        type_id = _msvc_string(memory, etype + DESIGNS["type_id"], 120) if etype else None
        raw = memory.read(variant, 0x370) if type_id else None
        if not raw:
            continue
        stats = {k: round(struct.unpack_from("<q", raw, off)[0] / 100000, 5) for k, off in LAND_STATS.items()}
        if not 0 <= stats["reliability"] <= 2:
            raise PointerError("implausible", "Design reliability out of range - layout does not match")
        out.append({"type": type_id, "name": _msvc_string(memory, variant + VARIANT["name"], 120) or "", "stats": stats})
    return out


def read_air(memory, module_base: int, tags: list[str], tag: str) -> list[dict]:
    """[{"role", "design", "planes", "wings", "stats"}] of the country's air wings, grouped by role and design."""
    table = _ptr(memory, module_base + COUNTRY_TABLE[0])
    manager = _ptr(memory, table + AIR["manager"]) if table else None
    if manager is None:
        raise PointerError("unreadable", "The air manager is not readable")
    per_country = read_array(memory, manager + AIR["by_country"], 5000)
    slot = tags.index(tag) + 1
    if slot >= len(per_country):
        raise PointerError("implausible", "No air data for the country - layout does not match")
    air = per_country[slot]
    groups: dict[tuple[str, str], dict] = {}
    for pool in read_array(memory, air + AIR["pools"], 2000) if air else []:
        if not pool:
            continue
        role_def = _ptr(memory, pool + AIR["role"])
        role = _msvc_string(memory, role_def + SUBUNIT_ID) if role_def else None
        for wing in read_array(memory, pool + AIR["wings"], 2000):
            for variant, planes in _variant_entries(memory, wing + AIR["wing_variants"]) if wing else []:
                design = _msvc_string(memory, variant + VARIANT["name"], 120) if variant else None
                g = groups.setdefault((role or "unknown", design or ""), {
                    "role": role or "unknown", "design": design or "", "planes": 0.0, "wings": 0,
                    "stats": plane_stats(memory, variant) if variant else None})
                g["planes"] += planes
                g["wings"] += 1
    # wings without planes (being refilled, Bf 109 D 0) are not shown by the game
    return sorted((g for g in groups.values() if g["planes"] >= 1), key=lambda g: (g["role"], -g["planes"]))


def read_stockpile_planes(memory, country: int) -> list[dict]:
    """[{"design", "amount", "stats"}] of the plane designs in the country's stockpile (planes in reserve)."""
    out = []
    for e in read_stockpile(memory, country):
        variant = _ptr(memory, e["address"] - 8)
        stats = plane_stats(memory, variant) if variant else None
        if stats and e["amount"] >= 1:
            out.append({"design": e["name"] or "", "amount": e["amount"], "stats": stats})
    return sorted(out, key=lambda x: -x["amount"])
