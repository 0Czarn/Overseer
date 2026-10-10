"""Military Industrial Organisations (MIO, Arms Against Tyranny): definitions from the game files, state from the save.

Definitions (common/military_industrial_organization/organizations): a MIO `include`s a template (usually
generic_*_organization) and changes its trait tree with add_trait / override_trait / remove_trait. A trait gives
equipment_bonus (to the equipment the MIO designs), production_bonus (to its production lines) and
organization_modifier (to the MIO itself). Policies (…/policies) give the same kinds of bonuses.
Save (country production.industrial_organisations): size (= level), funds, unlocked traits, active policy.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from .saves import text

BONUS_KINDS = ("equipment_bonus", "production_bonus", "organization_modifier")
CATEGORIES = ("tank_manufacturer", "naval_manufacturer", "aircraft_manufacturer", "materiel_manufacturer")
NAVAL = re.compile(r"ship|submarine|convoy|carrier|cruiser|destroyer|battleship|fleet|naval_(?!bomber)")
AIR = re.compile(r"plane|airframe|fighter|bomber|cas\b|^cas|helicopter|aircraft|maritime_patrol")
TANK = re.compile(r"tank|armor|armored_car|assault_gun|chassis")
MATERIEL = {"infantry_equipment", "support_equipment", "artillery_equipment", "motorized_equipment", "train_equipment"}


def _strip(path: Path) -> str:
    return re.sub(r"#[^\n]*", "", path.read_text(encoding="utf-8-sig", errors="replace"))


def _parse(path: Path) -> list:
    try:
        return text.parse(_strip(path))
    except Exception:  # a broken mod file must not break the whole list
        return []


def _numbers(block) -> dict[str, float]:
    out = {}
    for item in block if isinstance(block, list) else []:
        if isinstance(item, tuple) and isinstance(item[0], str) and isinstance(item[1], str):
            try:
                out[item[0]] = float(item[1])
            except ValueError:
                pass
    return out


def _trait(body: list) -> dict:
    return {"token": text.get(body, "token"), "name": text.get(body, "name"),
            **{kind: _numbers(text.get(body, kind)) for kind in BONUS_KINDS}}


@lru_cache(maxsize=2)
def definitions(roots: tuple[str, ...]) -> dict:
    """{"organizations": {id: raw definition}, "policies": {id: {kind: {stat: v}}}}; later roots override."""
    orgs: dict[str, dict] = {}
    policies: dict[str, dict] = {}
    for root in map(Path, roots):
        base = root / "common" / "military_industrial_organization"
        for path in sorted((base / "organizations").glob("*.txt")):
            for name, body in (e for e in _parse(path) if isinstance(e, tuple)):
                if not isinstance(body, list):
                    continue
                initial = text.get(body, "initial_trait")
                orgs[name] = {
                    "include": text.get(body, "include") if isinstance(text.get(body, "include"), str) else None,
                    "name": text.get(body, "name") if isinstance(text.get(body, "name"), str) else None,
                    "icon": text.get(body, "icon") if isinstance(text.get(body, "icon"), str) else None,
                    "equipment_type": [e for e in (text.get(body, "equipment_type") or []) if isinstance(e, str)]
                    if isinstance(text.get(body, "equipment_type"), list) else [],
                    "initial_trait": _trait(initial) if isinstance(initial, list) else None,
                    "trait": [_trait(b) for k, b in body if k == "trait" and isinstance(b, list)],
                    "add_trait": [_trait(b) for k, b in body if k == "add_trait" and isinstance(b, list)],
                    "override_trait": [_trait(b) for k, b in body if k == "override_trait" and isinstance(b, list)],
                    "remove_trait": [t for k, b in body if k == "remove_trait" and isinstance(b, list)
                                     for t in b if isinstance(t, str)],
                }
        for path in sorted((base / "policies").glob("*.txt")):
            for name, body in (e for e in _parse(path) if isinstance(e, tuple)):
                if isinstance(body, list):
                    policies[name] = {kind: _numbers(text.get(body, kind)) for kind in BONUS_KINDS}
    return {"organizations": orgs, "policies": policies}


def resolve(defs: dict, mio: str, depth: int = 6) -> dict | None:
    """Effective definition: traits {token: trait}, initial trait, equipment types, category, template chain."""
    d = defs["organizations"].get(mio)
    if d is None:
        return None
    parent = resolve(defs, d["include"], depth - 1) if d["include"] and depth > 0 else None
    traits = dict((parent or {}).get("traits") or {})
    for t in d["trait"] + d["add_trait"] + d["override_trait"]:
        if t["token"]:
            traits[t["token"]] = t
    for token in d["remove_trait"]:
        traits.pop(token, None)
    equipment = d["equipment_type"] or (parent or {}).get("equipment_type") or []
    chain = [mio] + ((parent or {}).get("chain") or [])
    return {"traits": traits, "initial_trait": d["initial_trait"] or (parent or {}).get("initial_trait"),
            "equipment_type": equipment, "icon": d["icon"] or (parent or {}).get("icon"),
            "name": d["name"], "chain": chain, "category": category(equipment, chain)}


def category(equipment: list[str], chain: list[str]) -> str:
    """Design slot of the politics screen the MIO belongs to: by its first equipment type, else its templates.
    Tanks are tested first ("tank_destroyer_chassis" is not a ship)."""
    for probe in equipment[:1] + chain[1:] + chain[:1] + equipment[1:]:
        if TANK.search(probe):
            return "tank_manufacturer"
        if NAVAL.search(probe):
            return "naval_manufacturer"
        if AIR.search(probe):
            return "aircraft_manufacturer"
        if probe in MATERIEL or "equipment" in probe and probe == (equipment[:1] or [None])[0]:
            return "materiel_manufacturer"
    return "materiel_manufacturer"


def summary(state: dict, defs: dict) -> dict | None:
    """One MIO of the save with its current bonuses: {id, category, size, funds, research_bonus, policy,
    traits: [trait dicts], bonuses: {kind: {stat: total}}}."""
    d = resolve(defs, state["id"])
    if d is None:
        return None
    unlocked = [d["traits"][t] for t in state.get("traits") or [] if t in d["traits"]]
    sources = ([d["initial_trait"]] if d["initial_trait"] else []) + unlocked
    policy = defs["policies"].get(state.get("policy") or "")
    bonuses: dict[str, dict[str, float]] = {kind: {} for kind in BONUS_KINDS}
    for src in sources + ([policy] if policy else []):
        for kind in BONUS_KINDS:
            for stat, v in (src.get(kind) or {}).items():
                bonuses[kind][stat] = round(bonuses[kind].get(stat, 0.0) + v, 6)
    return {"id": state["id"], "category": d["category"], "size": state.get("size"), "funds": state.get("funds"),
            "research_bonus": state.get("research_bonus"), "policy": state.get("policy"),
            "icon": state.get("icon") or d["icon"], "name_key": d["name"],
            "traits": unlocked, "initial_trait": d["initial_trait"], "bonuses": bonuses}
