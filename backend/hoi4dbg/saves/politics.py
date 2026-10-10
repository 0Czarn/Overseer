"""Political state of one country from a save: ideas, party popularity, leader, advisors, dynamic modifiers.

Binary token ids (1.19.3) come from walking the text save `11.hoi4` and the binary save `2-1.hoi4` of the same
paused game side by side (2026-10-10): the GER country block (470 keys) and `character_manager` aligned with no
conflict for the tokens used here (e.g. ideas 1/1, popularity 4/4, character 144/144, traits 11979/11996).
"""

from __future__ import annotations

import re

from . import binary, binvalues, text

TOKENS = {
    "ideas": 0x2FEF, "ruling_party": 0x3008, "parties": 0x2FF8, "popularity": 0x2FF7,
    "dynamic_modifier": 0x3C01, "modifier": 0x2965, "value": 0x0308, "enabled": 0x02C1,
    "characters": 0x4C14, "appointed_advisors": 0x4C1D, "slot": 0x3442, "character": 0x4C16, "id": 0x000B,
    "type": 0x00E1, "country_leader": 0x3035, "ideology": 0x2E3E,
    "character_manager": 0x4C26, "historical": 0x3022, "dynamic": 0x3313, "token": 0x4A47, "name": 0x001B,
    "country": 0x289A, "country_leaders": 0x4E05, "traits": 0x2FF6, "advisors": 0x4C1C, "advisor": 0x28D6,
    "idea_token": 0x4C1B, "major": 0x2BE9, "pride_of_the_fleet": 0x3A9A,
    # top level (located by content in SOV_1936_03_12_01.hoi4: faction blocks hold GFX_faction_logo_*, the threat
    # block holds the world tension events; 4.815 there = the +1.92 % war support the game showed, x 0.4)
    "faction": 0x2A7D, "members": 0x2AA6, "rule_status": 0x4C65, "rules": 0x317B, "threat": 0x2BBD,
}
NAMES = {**binvalues.NAMES, **{v: k for k, v in TOKENS.items()}}
TEXT_TOP_KEY = re.compile(rb"\n[a-z_]+=")


def _named(items: list) -> list:
    saved = dict(binvalues.NAMES)
    binvalues.NAMES.update(NAMES)
    try:
        return binvalues._named(items)
    finally:
        binvalues.NAMES.clear()
        binvalues.NAMES.update(saved)


def _char_id(value) -> str | None:
    """`character = { id = N type = 73 }` (country block) or `id = { id = N type = 73 }` -> "N"."""
    found = text.get(value, "id") if isinstance(value, list) else None
    return found if isinstance(found, str) else None


def characters_of(manager: list, tag: str) -> dict[str, dict]:
    """{character id: {token, name, leader_traits, advisors: [{slot, idea_token, traits}]}} of one country."""
    out = {}
    for group, chars in manager:
        if group not in ("historical", "dynamic") or not isinstance(chars, list):
            continue
        for key, ch in chars:
            if key != "character" or not isinstance(ch, list) or text.get(ch, "country") != tag:
                continue
            leader_traits = [t for k, cl in (text.get(ch, "country_leaders") or []) if k == "country_leader"
                             for t in (text.get(cl, "traits") or []) if isinstance(t, str)]
            advisors = [{"slot": text.get(a, "slot"), "idea_token": text.get(a, "idea_token"),
                         "traits": [t for t in (text.get(a, "traits") or []) if isinstance(t, str)]}
                        for k, a in (text.get(ch, "advisors") or []) if k == "advisor" and isinstance(a, list)]
            out[_char_id(text.get(ch, "id"))] = {
                "token": text.get(ch, "token"), "name": text.get(ch, "name"),
                "leader_traits": leader_traits, "advisors": advisors}
    return out


def world(factions: list[list], threat: list | None) -> dict:
    """{"factions": [{"members", "rules"}], "tension": world tension in %} from the top-level blocks.
    Tension = sum of the current value (first number) of every threat entry."""
    out = []
    for f in factions:
        members = [m for m in (text.get(f, "members") or []) if isinstance(m, str)]
        rules = [r for r in (text.get(text.get(f, "rule_status") or [], "rules") or []) if isinstance(r, str)]
        out.append({"members": members, "rules": rules})
    tension = 0.0
    for entry in threat or []:
        body = entry[1] if isinstance(entry, tuple) else entry
        first = next((v for k, v in body if isinstance(v, str)), None) if isinstance(body, list) else None
        tension += _float(first) or 0.0
    return {"factions": out, "tension": min(100.0, tension)}


def summary(block: list, manager: list | None, tag: str, world_state: dict | None = None) -> dict:
    """What decides stability / war support besides the base value (country block + character manager)."""
    politics = text.get(block, "politics") or []
    ruling = text.get(politics, "ruling_party")
    parties = text.get(politics, "parties") or []
    popularity = {k: float(text.get(v, "popularity") or 0) for k, v in parties if isinstance(v, list)}
    leader_id = None
    leaders = text.get(text.get(parties, ruling) or [], "country_leader") or []
    for entry in leaders:  # { { ideology=... character={ id=.. } } }: the first one rules
        if isinstance(entry, list):
            leader_id = _char_id(text.get(entry, "character"))
            break
    advisors = []
    for entry in text.get(text.get(block, "characters") or [], "appointed_advisors") or []:
        if isinstance(entry, list):
            advisors.append({"slot": text.get(entry, "slot"), "id": _char_id(text.get(entry, "character"))})
    dynamic = [{"id": text.get(m, "modifier"), "values": [v for v in (text.get(m, "value") or []) if isinstance(v, str)],
                "enabled": text.get(m, "enabled") != "no"}
               for k, m in (text.get(block, "dynamic_modifier") or []) if k == "modifier" and isinstance(m, list)]
    return {
        "tag": tag, "stability": _float(text.get(block, "stability")), "war_support": _float(text.get(block, "war_support")),
        "ideas": [i for i in (text.get(politics, "ideas") or []) if isinstance(i, str)],
        "ruling_party": ruling, "popularity": popularity, "leader": leader_id, "advisors": advisors,
        "dynamic_modifiers": dynamic, "characters": characters_of(manager or [], tag),
        "major": text.get(block, "major") == "yes",
        "pride_of_the_fleet": text.get(block, "pride_of_the_fleet") is not None,
        "faction": next(({**f, "leader": f["members"][0] == tag} for f in (world_state or {}).get("factions", [])
                         if tag in f["members"]), None),
        "tension": (world_state or {}).get("tension"),
    }


def _float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _text_top(data: bytes, key: str) -> list:
    """Every top-level `key = { ... }` block of a text save."""
    out = []
    needle = b"\n" + key.encode() + b"={"
    start = data.find(needle)
    while start >= 0:
        end = TEXT_TOP_KEY.search(data, start + len(needle))
        chunk = data[start + 1:end.start() if end else len(data)].decode("utf-8", errors="replace")
        out.append(text.get(text.parse(chunk), key))
        start = data.find(needle, start + len(needle))
    return out


def read_text(data: bytes, tags: set[str]) -> dict[str, dict]:
    manager = next(iter(_text_top(data, "character_manager")), None)
    state = world(_text_top(data, "faction"), next(iter(_text_top(data, "threat")), None))
    out = {}
    for tag in tags:
        block = text.country_block(data, tag)
        if block is not None:
            out[tag] = summary(block, manager, tag, state)
    return out


def read_binary(data: bytes, tags: set[str], float_width: int, version: str | None) -> dict[str, dict]:
    if not binvalues.VERIFIED_VERSION.search(version or ""):
        raise binary.SaveFormatError("binary_values_unmapped", f"Binary politics are only mapped for 1.19.3 "
                                     f"(this save: {version or 'unknown'}). Use a text save (-force_text_save).")
    blocks: dict[str, list] = {}
    manager = None
    factions, threat = [], None
    p = binary.Parser(data, float_width)
    while p.peek() is not None:
        key = p._u16()
        if p._u16() != binary.EQUALS:
            raise binary.SaveFormatError("corrupt", "Expected '=' after a top-level field", p.pos - 2)
        if key == TOKENS["character_manager"] and p.peek() == binary.OPEN:
            p._u16()
            manager = _named(p.block([200_000_000]))
        elif key in (TOKENS["faction"], TOKENS["threat"]) and p.peek() == binary.OPEN:
            p._u16()
            value = _named(p.block([5_000_000]))
            if key == TOKENS["faction"]:
                factions.append(value)
            else:
                threat = value
        elif key == binvalues.TOKENS["countries"] and p.peek() == binary.OPEN:
            p._u16()
            while p.peek() not in (None, binary.CLOSE):
                name = p.scalar(p._u16())
                if p._u16() != binary.EQUALS:
                    raise binary.SaveFormatError("corrupt", "Expected '=' after a country tag", p.pos - 2)
                if name in tags and p.peek() == binary.OPEN:
                    p._u16()
                    blocks[name] = _named(p.block([50_000_000]))
                else:
                    p.skip_value()
            p._u16()  # closing brace of countries
        else:
            p.skip_value()
    state = world(factions, threat)
    return {tag: summary(block, manager, tag, state) for tag, block in blocks.items()}


def read(data: bytes, fmt: str, float_width: int | None, version: str | None, tags: set[str]) -> dict[str, dict]:
    """{tag: summary()} for the wanted countries that exist in the save (one pass over the file)."""
    if fmt == "text":
        return read_text(data, tags)
    return read_binary(data, tags, float_width or 8, version)
