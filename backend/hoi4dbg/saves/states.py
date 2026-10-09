"""States of a save: owner, controller, buildings, resources, manpower pool, cores and claims.

Save layout (1.19.3, verified on the text/binary pair 11.hoi4 / 2-1.hoi4 by aligning both structures):
- top-level `states` (0x2e3b): id -> owner (0x283e), buildings (0x2f59: type -> level 0x286c),
  manpower_pool (0x3635: available 0x2fe8, locked 0x2de4, total 0x2a12), resources (0x2e42), state_category (0x3618);
- top-level `provinces` (0x2830): id -> controller (0x283f, only where it differs from the owner), buildings;
- countries: cores (0x3361) and claims (0x3360) as lists of state ids.
Binary saves write some names as tokens and others as plain strings; unknown tokens are shown as `#xxxx`.
Province -> state assignment and state names come from the game files (gamefiles.state_definitions).
"""

from __future__ import annotations

import bisect
import collections
import re

from . import binary, binvalues, countries, text

T = {"states": 0x2E3B, "provinces": 0x2830, "owner": 0x283E, "controller": 0x283F, "buildings": 0x2F59,
     "level": 0x286C, "manpower_pool": 0x3635, "available": 0x2FE8, "locked": 0x2DE4, "total": 0x2A12,
     "resources": 0x2E42, "state_category": 0x3618, "cores": 0x3361, "claims": 0x3360}
NAMES = {
    # building types (voted over 1032/336/87/18 states and 3134/534/728/8 provinces)
    0x2FAB: "infrastructure", 0x2FB6: "air_base", 0x4BF6: "dockyard", 0x3C8F: "fuel_silo",
    0x4CC1: "rail_way", 0x31F6: "naval_base", 0x4CBE: "supply_node", 0x27D2: "naval_supply_hub",
    # resources
    0x3E05: "rubber", 0x3E06: "tungsten", 0x3E07: "chromium",
}
NAMES.update({v: k for k, v in T.items()})


def _name(key) -> str:
    if isinstance(key, binary.Token):
        return NAMES.get(key.id, f"#{key.id:04x}")
    return str(key)


def _normalise(block) -> list:
    """Binary block -> text-like shape (names for known tokens, plain numbers)."""
    if not isinstance(block, list):
        if isinstance(block, binary.Raw):
            return binvalues.decode(block)
        if isinstance(block, bool):
            return "yes" if block else "no"
        return block if isinstance(block, str) else str(block) if not isinstance(block, binary.Token) else _name(block)
    out = []
    for item in block:
        if isinstance(item, tuple):
            out.append((_name(item[0]), _normalise(item[1])))
        else:
            out.append(_normalise(item))
    return out


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _levels(block) -> dict[str, float]:
    out = {}
    for item in block if isinstance(block, list) else []:
        if isinstance(item, tuple) and isinstance(item[1], list):
            level = _num(text.get(item[1], "level"))
            if level:
                out[item[0]] = level
    return out


def _state(block: list) -> dict:
    pool = text.get(block, "manpower_pool") or []
    resources = text.get(block, "resources") or []
    return {
        "owner": text.get(block, "owner"),
        "category": text.get(block, "state_category"),
        "buildings": _levels(text.get(block, "buildings")),
        "resources": {k: _num(v) for k, v in resources if isinstance(resources, list) and _num(v)}
        if isinstance(resources, list) else {},
        "manpower": {k: _num(text.get(pool, k)) for k in ("available", "locked", "total")},
    }


def _ids(value) -> list[int]:
    if isinstance(value, list):
        return [int(x) for x in value if isinstance(x, (int, str)) and str(x).isdigit()]
    return []


def read(data: bytes, fmt: str, float_width: int | None, version: str | None) -> dict:
    """{"states": {id: {...}}, "provinces": {id: {"controller", "buildings"}}, "cores"/"claims": {tag: [ids]}}"""
    if fmt == "text":
        states = {int(k): _state(v) for k, v in text.parse(countries._section(data, b"states").decode(
            "utf-8", "replace"))[0][1] if isinstance(v, list) and str(k).isdigit()} if b"\nstates={" in data else {}
        provinces = {}
        section = countries._section(data, b"provinces")
        if section:
            for k, v in text.parse(section.decode("utf-8", "replace"))[0][1]:
                if isinstance(v, list) and str(k).isdigit():
                    provinces[int(k)] = {"controller": text.get(v, "controller"),
                                         "buildings": _levels(text.get(v, "buildings"))}
        cores, claims = {}, {}
        block = countries._section(data, b"countries")
        heads = [(m.start(), m.group(1).decode()) for m in re.finditer(rb"\n\t([A-Z][A-Z0-9]{2})=\{", block)]
        starts = [p for p, _ in heads]
        for name, target in ((b"cores", cores), (b"claims", claims)):
            for m in re.finditer(rb"\n\t\t" + name + rb"=\{([^}]*)\}", block):
                i = bisect.bisect_right(starts, m.start()) - 1
                if i >= 0:
                    target[heads[i][1]] = [int(x) for x in m.group(1).split() if x.isdigit()]
        return {"states": states, "provinces": provinces, "cores": cores, "claims": claims}
    if not binvalues.VERIFIED_VERSION.search(version or "") or float_width != 8:
        raise binary.SaveFormatError("binary_values_unmapped", f"Binary states are only mapped for 1.19.3 "
                                     f"(this save: {version or 'unknown'}). Use a text save (-force_text_save).")
    p = binary.Parser(data, float_width)
    states, provinces, cores, claims = {}, {}, {}, {}
    while p.peek() is not None:
        key = p._u16()
        if p._u16() != binary.EQUALS:
            raise binary.SaveFormatError("corrupt", "Expected '=' after a top-level field", p.pos - 2)
        if key in (T["states"], T["provinces"]) and p.peek() == binary.OPEN:
            p._u16()
            for item in p.block([200_000_000]):
                # ids are integers for states and digit strings for provinces
                if isinstance(item, tuple) and isinstance(item[1], list) and str(item[0]).isdigit():
                    norm, sid = _normalise(item[1]), int(item[0])
                    if key == T["states"]:
                        states[sid] = _state(norm)
                    else:
                        provinces[sid] = {"controller": text.get(norm, "controller"),
                                              "buildings": _levels(text.get(norm, "buildings"))}
        elif key == binvalues.TOKENS["countries"] and p.peek() == binary.OPEN:
            p._u16()
            while p.peek() not in (None, binary.CLOSE):
                tag = p.scalar(p._u16())
                p._u16()
                if p.peek() != binary.OPEN:
                    p.skip_value()
                    continue
                p._u16()
                while p.peek() not in (None, binary.CLOSE):
                    if p.peek() == binary.OPEN:
                        p.skip_value()
                        continue
                    k = p.scalar(p._u16())
                    if p.peek() != binary.EQUALS:
                        continue
                    p._u16()
                    kid = k.id if isinstance(k, binary.Token) else None
                    if kid in (T["cores"], T["claims"]) and p.peek() == binary.OPEN:
                        p._u16()
                        (cores if kid == T["cores"] else claims)[tag] = _ids(p.block([1_000_000]))
                    else:
                        p.skip_value()
                p._u16()
            p._u16()
        else:
            p.skip_value()
    return {"states": states, "provinces": provinces, "cores": cores, "claims": claims}


def assemble(save: dict, definitions: dict[int, dict], names: dict[str, str]) -> list[dict]:
    """One row per state: save data + controller from its provinces + cores/claims + names from the game files."""
    core_of, claim_of = collections.defaultdict(list), collections.defaultdict(list)
    for tag, ids in save["cores"].items():
        for sid in ids:
            core_of[sid].append(tag)
    for tag, ids in save["claims"].items():
        for sid in ids:
            claim_of[sid].append(tag)
    rows = []
    for sid, st in sorted(save["states"].items()):
        definition = definitions.get(sid) or {}
        provinces = definition.get("provinces") or []
        controllers = collections.Counter((save["provinces"].get(p) or {}).get("controller") or st["owner"]
                                          for p in provinces) if provinces else collections.Counter({st["owner"]: 1})
        province_buildings: dict[str, float] = {}
        for prov in provinces:
            for b, lvl in ((save["provinces"].get(prov) or {}).get("buildings") or {}).items():
                province_buildings[b] = province_buildings.get(b, 0) + lvl
        rows.append({
            "id": sid, "name": names.get(definition.get("name_key") or "", definition.get("name_key") or f"State {sid}"),
            "owner": st["owner"], "controller": controllers.most_common(1)[0][0],
            "controllers": dict(controllers), "category": st["category"],
            "buildings": st["buildings"], "province_buildings": province_buildings,
            "resources": st["resources"], "manpower": st["manpower"],
            "cores": sorted(core_of.get(sid, [])), "claims": sorted(claim_of.get(sid, [])),
            "provinces": len(provinces),
        })
    return rows
