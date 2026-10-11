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
    # balance of power (aligned with 11.hoi4 / 2-1.hoi4: FIN_power_balance value -0.48 in both)
    "power_balance": 0x4DDF, "power_balances": 0x4DDB, "template": 0x4C1A,
    # doctrines (aligned with 11.hoi4 / 2-1.hoi4): doctrine = { countries = { { folder = { { grand_doctrine
    # tracks = { { sub_doctrine rewards mastery } } } } country = TAG } } }
    "doctrine": 0x35F9, "folder": 0x2E61, "grand_doctrine": 0x4187, "tracks": 0x4184, "rewards": 0x4182,
    "sub_doctrine": 0x418A,
    # MIOs (country production.industrial_organisations; GER block aligned with 11.hoi4). The unlocked traits
    # (0x38a4 = { 0x2e8e = trait }) and the active policy (0x28fc) were identified in SOV_1942_06_10_22.hoi4: a
    # size-10 MIO lists exactly 10 such traits; text names of these three keys are not known yet.
    "production": 0x2FB4, "industrial_organisations": 0x4ADA, "size": 0x002F, "funds": 0x4AD9, "icon": 0x00B5,
    "research_bonus": 0x3161, "mio_unlocked_trait": 0x38A4, "mio_trait": 0x2E8E, "mio_policy": 0x28FC,
    "long_name": 0x34EB,
    # resources (country block; aligned with 11.hoi4 / 2-1.hoi4): produced, imported, to_export (= resources to
    # market), exported (sold), to_use = { available-at-home, (unused), -used-by-production }, export = trade deals
    "resources": 0x2E42, "produced": 0x2FAC, "imported": 0x30C2, "to_use": 0x30C3, "to_export": 0x30C4,
    "exported": 0x30C5, "export": 0x30C6, "resource": 0x3064, "delivered": 0x30C9, "receiver": 0x00C6,
    "steel": 0x3E03, "rubber": 0x3E05, "tungsten": 0x3E06, "chromium": 0x3E07,   # party long name (SOV_communism_party_russian_long in the SOV 1936 save)
    "portraits": 0x4C29, "civilian": 0x4B26, "army": 0x289D, "navy": 0x289E, "small": 0x30D7, "large": 0x4C28,
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
            portraits: dict[str, dict] = {}
            for kind, body in (text.get(ch, "portraits") or []):
                if isinstance(body, list):
                    for size, sprite in body:
                        if isinstance(sprite, str):
                            portraits.setdefault(kind, {})[size] = sprite
            out[_char_id(text.get(ch, "id"))] = {
                "token": text.get(ch, "token"), "name": text.get(ch, "name"), "portraits": portraits,
                "leader_traits": leader_traits, "advisors": advisors}
    return out


def doctrines_of(doctrine: list | None) -> dict[str, list[dict]]:
    """{tag: [{"id": grand doctrine or subdoctrine, "rewards": unlocked rewards}]} from the top-level doctrine block."""
    out = {}
    for entry in text.get(doctrine or [], "countries") or []:
        tag = text.get(entry, "country") if isinstance(entry, list) else None
        if not isinstance(tag, str):
            continue
        items = []
        for folder in text.get(entry, "folder") or []:
            if not isinstance(folder, list):
                continue
            if isinstance(text.get(folder, "grand_doctrine"), str):
                items.append({"id": text.get(folder, "grand_doctrine"), "rewards": 0})
            for track in text.get(folder, "tracks") or []:
                sub = text.get(track, "sub_doctrine") if isinstance(track, list) else None
                if isinstance(sub, str):
                    items.append({"id": sub, "rewards": int(_float(text.get(track, "rewards")) or 0)})
        out[tag] = items
    return out


def world(factions: list[list], threat: list | None, power_balance: list | None = None,
          doctrine: list | None = None) -> dict:
    """{"factions": [{"members", "rules"}], "tension": world tension in %} from the top-level blocks.
    Tension = sum of the current value (first number) of every threat entry."""
    out = []
    for f in factions:
        members = [m for m in (text.get(f, "members") or []) if isinstance(m, str)]
        rules = [r for r in (text.get(text.get(f, "rule_status") or [], "rules") or []) if isinstance(r, str)]
        out.append({"members": members, "rules": rules,
                    **{k: text.get(f, k) if isinstance(text.get(f, k), str) else None for k in ("template", "icon", "name")}})
    tension = 0.0
    for entry in threat or []:
        body = entry[1] if isinstance(entry, tuple) else entry
        first = next((v for k, v in body if isinstance(v, str)), None) if isinstance(body, list) else None
        tension += _float(first) or 0.0
    balances = []
    for entry in text.get(power_balance or [], "power_balances") or []:
        if isinstance(entry, list):
            balances.append({"id": text.get(entry, "template"), "value": _float(text.get(entry, "value")),
                             "countries": [c for c in (text.get(entry, "countries") or []) if isinstance(c, str)],
                             "modifier": text.get(entry, "modifier") if isinstance(text.get(entry, "modifier"), str) else None})
    return {"factions": out, "tension": min(100.0, tension), "power_balances": balances,
            "doctrines": doctrines_of(doctrine)}


def _unlocked_traits(org: list, size: int) -> list[str]:
    """Trait tokens of `{ <key> = { <key> = trait } }` entries. Binary saves: the known token; text saves (key names
    unknown): the key that repeats `size` times (another such list holds traits that are not unlocked)."""
    groups: dict[str, list[str]] = {}
    for k, v in org:
        if isinstance(v, list) and len(v) == 1 and isinstance(v[0], tuple) and isinstance(v[0][1], str) \
                and isinstance(k, str) and k not in ("id", "allowed_policies", "history", "variables", "flags"):
            groups.setdefault(k, []).append(v[0][1])
    if "mio_unlocked_trait" in groups:
        return groups["mio_unlocked_trait"]
    return next((g for g in groups.values() if len(g) == size), [])


def _amounts(block) -> dict[str, float]:
    out = {}
    for k, v in block if isinstance(block, list) else []:
        if isinstance(k, str) and isinstance(v, str) and _float(v) is not None:
            out[k] = _float(v)
    return out


def resources_of(block: list) -> dict:
    """{"produced", "to_market", "exported", "imported", "available", "used": {resource: amount},
    "exports": [{receiver, resource, amount}]} of a country block (amounts per day, as the game shows them)."""
    r = text.get(block, "resources") or []
    to_use = [b for b in (text.get(r, "to_use") or []) if isinstance(b, list)]
    used = {k: -v for k, v in _amounts(to_use[2] if len(to_use) > 2 else []).items()}
    deals = [{"receiver": text.get(e, "receiver"), "resource": text.get(e, "resource"),
              "amount": _float(text.get(e, "delivered")) or 0.0}
             for k, e in r if k == "export" and isinstance(e, list)]
    return {"produced": _amounts(text.get(r, "produced")), "to_market": _amounts(text.get(r, "to_export")),
            "exported": _amounts(text.get(r, "exported")), "imported": _amounts(text.get(r, "imported")),
            "available": _amounts(to_use[0] if to_use else []), "used": used, "exports": deals}


def mios_of(block: list) -> list[dict]:
    out = []
    for mio_id, org in text.get(text.get(block, "production") or [], "industrial_organisations") or []:
        if not isinstance(org, list) or not isinstance(mio_id, str):
            continue
        size = int(_float(text.get(org, "size")) or 0)
        policy = text.get(org, "mio_policy")
        out.append({"id": mio_id, "size": size, "funds": _float(text.get(org, "funds")),
                    "research_bonus": _float(text.get(org, "research_bonus")),
                    "icon": text.get(org, "icon") if isinstance(text.get(org, "icon"), str) else None,
                    "policy": policy if isinstance(policy, str) else None, "traits": _unlocked_traits(org, size)})
    return out


def summary(block: list, manager: list | None, tag: str, world_state: dict | None = None) -> dict:
    """What decides stability / war support besides the base value (country block + character manager)."""
    politics = text.get(block, "politics") or []
    ruling = text.get(politics, "ruling_party")
    parties = text.get(politics, "parties") or []
    popularity = {k: float(text.get(v, "popularity") or 0) for k, v in parties if isinstance(v, list)}
    leader_id, leader_ideology = None, None
    leaders = text.get(text.get(parties, ruling) or [], "country_leader") or []
    for entry in leaders:  # { { ideology=... character={ id=.. } } }: the first one rules
        if isinstance(entry, list):
            leader_id = _char_id(text.get(entry, "character"))
            leader_ideology = text.get(entry, "ideology") if isinstance(text.get(entry, "ideology"), str) else None
            break
    party_names = {k: {"name": text.get(v, "name") if isinstance(text.get(v, "name"), str) else None,
                       "long_name": text.get(v, "long_name") if isinstance(text.get(v, "long_name"), str) else None}
                   for k, v in parties if isinstance(v, list)}
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
        "leader_ideology": leader_ideology, "party_names": party_names,
        "dynamic_modifiers": dynamic, "characters": characters_of(manager or [], tag),
        "major": text.get(block, "major") == "yes",
        "mios": mios_of(block),
        "resources": resources_of(block),
        "pride_of_the_fleet": text.get(block, "pride_of_the_fleet") is not None,
        # war support penalties that build up weekly (text saves; binary tokens not known yet)
        "bombing_penalty": _float(text.get(block, "being_bombed_support_penalty")) or 0.0,
        "casualties_penalty": _float(text.get(block, "heroes_dying_war_support_penalty")) or 0.0,
        "wars": wars_of(block, tag),
        "research": research_of(block),
        "faction": next(({**f, "leader": f["members"][0] == tag} for f in (world_state or {}).get("factions", [])
                         if tag in f["members"]), None),
        "tension": (world_state or {}).get("tension"),
        "doctrines": (world_state or {}).get("doctrines", {}).get(tag, []),
        "power_balances": [b for b in (world_state or {}).get("power_balances", []) if tag in b["countries"]],
    }


def research_of(block: list) -> list[dict]:
    """[{"slot", "technology" or None, "speed", "points"}] from technology.slots of a text save (`empty = {
    points = 30 }` for an empty slot, `<technology id> = { points_factor = 1.13 }` while researching; the points
    collected are technologies.<id>.research_points)."""
    tech = text.get(block, "technology") or []
    slots = text.get(tech, "slots") or []
    known = text.get(tech, "technologies") or []
    out = []
    for i, (key, body) in enumerate((e for e in slots if isinstance(e, tuple)), start=1):
        if key == "empty":
            out.append({"slot": i, "technology": None, "speed": None, "points": None})
            continue
        entry = text.get(known, key)
        out.append({"slot": i, "technology": key, "speed": _float(text.get(body, "points_factor")) if isinstance(body, list) else None,
                    "points": (_float(text.get(entry, "research_points")) or 0.0) if isinstance(entry, list) else 0.0})
    return out


def wars_of(block: list, tag: str) -> list[dict]:
    """[{"enemy", "offensive"}] from the country's diplomacy (text saves, 2026-10-11 'Stest 1': SOV attacked POL ->
    active_relations.POL.war_relation = { first="SOV" second="POL" first_was_instigator=yes ... })."""
    out = []
    relations = text.get(text.get(block, "diplomacy") or [], "active_relations") or []
    for enemy, rel in (r for r in relations if isinstance(r, tuple)):
        war = text.get(rel, "war_relation") if isinstance(rel, list) else None
        if not isinstance(war, list):
            continue
        instigator_first = text.get(war, "first_was_instigator") == "yes"
        out.append({"enemy": enemy, "offensive": (text.get(war, "first") == tag) == instigator_first})
    return out


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
    state = world(_text_top(data, "faction"), next(iter(_text_top(data, "threat")), None),
                  next(iter(_text_top(data, "power_balance")), None), next(iter(_text_top(data, "doctrine")), None))
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
    factions, threat, balance, doctrine = [], None, None, None
    p = binary.Parser(data, float_width)
    while p.peek() is not None:
        key = p._u16()
        if p._u16() != binary.EQUALS:
            raise binary.SaveFormatError("corrupt", "Expected '=' after a top-level field", p.pos - 2)
        if key == TOKENS["character_manager"] and p.peek() == binary.OPEN:
            p._u16()
            manager = _named(p.block([200_000_000]))
        elif key in (TOKENS["faction"], TOKENS["threat"], TOKENS["power_balance"], TOKENS["doctrine"]) \
                and p.peek() == binary.OPEN:
            p._u16()
            value = _named(p.block([5_000_000]))
            if key == TOKENS["faction"]:
                factions.append(value)
            elif key == TOKENS["threat"]:
                threat = value
            elif key == TOKENS["doctrine"]:
                doctrine = value
            else:
                balance = value
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
    state = world(factions, threat, balance, doctrine)
    return {tag: summary(block, manager, tag, state) for tag, block in blocks.items()}


def read(data: bytes, fmt: str, float_width: int | None, version: str | None, tags: set[str]) -> dict[str, dict]:
    """{tag: summary()} for the wanted countries that exist in the save (one pass over the file)."""
    if fmt == "text":
        return read_text(data, tags)
    return read_binary(data, tags, float_width or 8, version)
