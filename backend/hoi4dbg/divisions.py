"""Division template stats like the game's division designer (2026-10-13, SOV 1941 Strelkovaya Diviziya: 19 of 20
stats equal to the designer, dywizja.png / batalion-piech.png).

Inputs: each sub-unit of common/units (stats, `need`, categories, `battalion_mult`), the country's newest design of
every equipment type (game memory - the designs carry the equipment bonuses: MIO traits, army spirits), the researched
technologies and the unlocked doctrine effects (grand doctrine, subdoctrines, rewards).

Rules found against the designer:
- a sub-unit's attack, defence, breakthrough and air attack = the stat of its equipment (one design per needed
  equipment type, summed) x (1 + the sub-unit's own factor + every technology / doctrine bonus for it): the bonuses
  ADD to the factor (anti-air battery: 26 x (1 - 0.6 + 0.2) = 15.6 air attack, as the game);
- `battalion_mult` blocks apply while their holder is in the division: inside a sub-unit (field hospital: +10% HP for
  infantry) or inside a technology / doctrine block keyed by a support company (commandos: logistics company gives
  light infantry +5 HP with `add = yes` - added before the factors: (25 + 5) x 1.1 = 33);
- organisation and recovery = average over all sub-units; HP, attacks, suppression, weight, supply, width, manpower,
  initiative, entrenchment, recon, trickleback and experience loss = sums; supply x (1 + supply factors); armor =
  0.3 max + 0.7 average, piercing = 0.4 max + 0.6 average; speed = the slowest sub-unit that affects speed;
- the designer cuts values off (122.96 -> "122.9", 0.768 -> "0.76").
Reliability does not follow a plain average yet (95.5% in the game, 92.9% by sub-unit) - shown as an estimate.
Doctrine milestones are not counted (when they unlock is not read from memory yet).
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from . import doctrines as doctrines_mod
from .saves import text

ATTACKS = ("soft_attack", "hard_attack", "defense", "breakthrough", "air_attack")
EQUIPMENT_STATS = ATTACKS + ("ap_attack", "armor_value")
SUMS = ("max_strength", "soft_attack", "hard_attack", "defense", "breakthrough", "air_attack", "suppression", "weight",
        "combat_width", "manpower", "initiative", "entrenchment", "recon", "casualty_trickleback",
        "experience_loss_factor")
# bonuses that multiply the stat (1 + sum); the rest add to it
FACTORS = {"max_strength", "maximum_speed", "armor_value", "ap_attack", "suppression_factor"}


def _parse(path: Path) -> list:
    try:
        return text.parse(re.sub(r"#[^\n]*", "", path.read_text(encoding="utf-8-sig", errors="replace")))
    except Exception:  # a broken (mod) file must not break the whole table
        return []


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _numbers(block) -> dict[str, float]:
    return {k: _num(v) for k, v in block if isinstance(v, str) and _num(v) is not None} if isinstance(block, list) else {}


def _battalion_mult(block) -> list[tuple[str, str, float, bool]]:
    """[(category, stat, value, add)] of a battalion_mult block."""
    if not isinstance(block, list):
        return []
    cat, add = text.get(block, "category"), text.get(block, "add") == "yes"
    return [(cat, k, v, add) for k, v in _numbers(block).items()] if cat else []


def _unit_blocks(body, units: dict) -> tuple[list, list]:
    """Bonuses of a technology / doctrine block: [(target, stat, value)] for blocks keyed by a sub-unit or category,
    [(holder, category, stat, value, add)] for battalion_mult blocks inside them."""
    mods, mults = [], []
    for k, v in body if isinstance(body, list) else []:
        if not isinstance(v, list) or not (k in units or k.startswith("category_")):
            continue
        mods += [(k, s, val) for s, val in _numbers(v).items()]
        for k2, v2 in v:
            if k2 == "battalion_mult":
                mults += [(k, *m) for m in _battalion_mult(v2)]
    return mods, mults


@lru_cache(maxsize=2)
def tables(roots: tuple[str, ...]) -> dict:
    """{"units": {id: {...}}, "techs": {id: (mods, mults)}, "doctrines": {key: (mods, mults)}} - later roots win."""
    units: dict[str, dict] = {}
    raw_techs: dict[str, list] = {}
    raw_doctrines: dict[str, list] = {}
    for root in map(Path, roots):
        for path in sorted((root / "common" / "units").glob("*.txt")):
            for key, value in _parse(path):
                if key != "sub_units" or not isinstance(value, list):
                    continue
                for unit, body in value:
                    if not isinstance(body, list):
                        continue
                    units[unit] = {"stats": _numbers(body), "need": _numbers(text.get(body, "need") or []),
                                   "cats": {unit, *[c for c in text.get(body, "categories") or [] if isinstance(c, str)]},
                                   "affects_speed": text.get(body, "affects_speed") != "no",
                                   "mult": _battalion_mult(text.get(body, "battalion_mult"))}
        for path in sorted((root / "common" / "technologies").glob("*.txt")):
            for key, value in _parse(path):
                if key == "technologies" and isinstance(value, list):
                    raw_techs.update({t: b for t, b in value if isinstance(b, list)})
        for path in sorted((root / "common" / "doctrines").rglob("*.txt")):
            for key, value in _parse(path):
                if not isinstance(value, list):
                    continue
                raw_doctrines[key] = value
                for rid, rbody in text.get(value, "rewards") or []:
                    if isinstance(rbody, list):
                        raw_doctrines[f"{key}/{rid}"] = rbody
    return {"units": units,
            "techs": {t: _unit_blocks(b, units) for t, b in raw_techs.items()},
            "doctrines": {d: _unit_blocks(b, units) for d, b in raw_doctrines.items()}}


def bonuses(tabs: dict, researched: list[str], doctrine_state: list[dict], defs: dict) -> tuple[list, list]:
    """All sub-unit bonuses of a country: researched technologies + grand doctrines, subdoctrines and their unlocked
    rewards (doctrine_state from game memory, defs = doctrines.definitions)."""
    mods, mults = [], []

    def take(key):
        m, b = tabs["doctrines"].get(key) or tabs["techs"].get(key) or ([], [])
        mods.extend(m)
        mults.extend(b)

    for t in researched:
        m, b = tabs["techs"].get(t) or ([], [])
        mods.extend(m)
        mults.extend(b)
    for folder in doctrine_state:
        grand = doctrines_mod.resolve(folder.get("grand"), defs, "grand")
        if grand:
            m, b = tabs["doctrines"].get(grand["id"]) or ([], [])
            mods.extend(m)
            mults.extend(b)
        for i, track in enumerate(folder.get("tracks") or []):
            track_id = grand["tracks"][i] if grand and i < len(grand["tracks"]) else None
            sub = doctrines_mod.resolve(track.get("sub"), defs, "subs", track_id)
            if not sub:
                continue
            m, b = tabs["doctrines"].get(sub["id"]) or ([], [])
            mods.extend(m)
            mults.extend(b)
            for reward in sub["rewards"][:track.get("rewards") or 0]:
                m, b = tabs["doctrines"].get(f"{sub['id']}/{reward['id']}") or ([], [])
                mods.extend(m)
                mults.extend(b)
    return mods, mults


def _sub_unit(unit: dict, equipment: dict[str, dict], mods: list, mults: list, adds: list) -> dict:
    base = unit["stats"]
    eq = dict.fromkeys(EQUIPMENT_STATS, 0.0)
    reliability, speed = [], None
    for archetype in unit["need"]:
        stats = equipment.get(archetype) or {}
        for k in EQUIPMENT_STATS:
            eq[k] += stats.get(k, 0.0)
        if stats.get("maximum_speed"):
            speed = min(speed, stats["maximum_speed"]) if speed else stats["maximum_speed"]
        if "reliability" in stats:
            reliability.append(stats["reliability"])
    s = {k: base.get(k, 0.0) for k in SUMS if k not in ATTACKS}
    s.update(max_organisation=base.get("max_organisation", 0.0), default_morale=base.get("default_morale", 0.0),
             supply_consumption=base.get("supply_consumption", 0.0), training_time=base.get("training_time", 0.0),
             supply_consumption_factor=base.get("supply_consumption_factor", 0.0),
             ap_attack=eq["ap_attack"], armor_value=eq["armor_value"], maximum_speed=speed or 0.0,
             reliability=sum(reliability) / len(reliability) if reliability else None)
    cats = unit["cats"]
    for target, stat, value in adds:   # battalion_mult with add = yes: before the factors
        if target in cats:
            s[stat] = s.get(stat, 0.0) + value
    total: dict[str, float] = {}
    for target, stat, value in mods + mults:
        if target in cats:
            total[stat] = total.get(stat, 0.0) + value
    for k in ATTACKS:
        s[k] = eq[k] * (1 + base.get(k, 0.0) + total.pop(k, 0.0))
    for stat, value in total.items():
        if stat in FACTORS:
            s[stat] = s.get(stat, 0.0) * (1 + value)
        elif stat == "reliability":
            s[stat] = (s[stat] or 0.0) + value if s[stat] is not None else None
        else:
            s[stat] = s.get(stat, 0.0) + value
    return s


FUEL_CAPACITY_HOURS = 96   # NDefines.NMilitary.FUEL_CAPACITY_DEFAULT_HOURS: a division holds 96 hours of its usage


def equipment_cost(template: dict, tabs: dict, equipment: dict[str, dict], costs: dict[str, list[float]]) -> dict | None:
    """The designer's "Equipment Cost" column beyond manpower and training time: {"equipment": {archetype: amount},
    "fuel_usage", "fuel_capacity", "cost_min", "cost_max"} - amounts from the sub-units' need, fuel from the designs used
    (x own_equipment_fuel_consumption_mult), the cost range over the country's cheapest and dearest design of each
    equipment (`costs` = {archetype: [build cost of every design]}). None when a sub-unit is unknown."""
    ids = list(template["battalions"]) + list(template["support"]) + list(template["regimental"])
    units = tabs["units"]
    if not ids or any(u not in units for u in ids):
        return None
    need: dict[str, float] = {}
    fuel = 0.0
    for u in ids:
        mult = units[u]["stats"].get("own_equipment_fuel_consumption_mult", 1.0)
        for archetype, amount in units[u]["need"].items():
            need[archetype] = need.get(archetype, 0.0) + amount
            fuel += (equipment.get(archetype) or {}).get("fuel_consumption", 0.0) * mult
    known = [a for a in need if costs.get(a)]
    return {"equipment": need, "fuel_usage": round(fuel, 4), "fuel_capacity": round(fuel * FUEL_CAPACITY_HOURS, 2),
            "cost_min": round(sum(need[a] * min(costs[a]) for a in known), 2),
            "cost_max": round(sum(need[a] * max(costs[a]) for a in known), 2),
            "no_design": sorted(a for a in need if not costs.get(a))}


def template_stats(template: dict, tabs: dict, equipment: dict[str, dict], mods: list, mults: list) -> dict | None:
    """Designer stats of a template ({"battalions", "support", "regimental": [sub-unit ids]}). `equipment` =
    {archetype: stats of the design used}. None when a sub-unit is unknown."""
    ids = list(template["battalions"]) + list(template["support"]) + list(template["regimental"])
    units = tabs["units"]
    if not ids or any(u not in units for u in ids):
        return None
    present = set().union(*(units[u]["cats"] for u in ids))
    factor, adds = [], []
    for u in ids:   # a sub-unit's own battalion_mult
        for cat, stat, value, add in units[u]["mult"]:
            (adds if add else factor).append((cat, stat, value))
    for holder, cat, stat, value, add in mults:   # technology / doctrine blocks of a support company in the division
        if holder in present:
            (adds if add else factor).append((cat, stat, value))
    subs = [_sub_unit(units[u], equipment, mods, factor, adds) for u in ids]
    n = len(subs)
    out = {k: sum(s.get(k, 0.0) for s in subs) for k in SUMS}
    out["supply_consumption"] = sum(s["supply_consumption"] for s in subs) * (
        1 + sum(s["supply_consumption_factor"] for s in subs))
    out["max_organisation"] = sum(s["max_organisation"] for s in subs) / n
    out["default_morale"] = sum(s["default_morale"] for s in subs) / n
    out["armor_value"] = 0.3 * max(s["armor_value"] for s in subs) + 0.7 * sum(s["armor_value"] for s in subs) / n
    out["ap_attack"] = 0.4 * max(s["ap_attack"] for s in subs) + 0.6 * sum(s["ap_attack"] for s in subs) / n
    speeds = [s["maximum_speed"] for u, s in zip(ids, subs) if units[u]["affects_speed"] and s["maximum_speed"]]
    out["maximum_speed"] = min(speeds) if speeds else None
    out["training_time"] = max(s["training_time"] for s in subs)
    rel = [min(s["reliability"], 1.0) for s in subs if s["reliability"] is not None]
    out["reliability"] = sum(rel) / len(rel) if rel else None
    missing = sorted({a for u in ids for a in units[u]["need"] if a not in equipment})
    return {"stats": out, "missing_equipment": missing}
