"""Military Industrial Organisations (MIO, Arms Against Tyranny): definitions from the game files, state from the save.

Definitions (common/military_industrial_organization/organizations): a MIO `include`s a template (usually
generic_*_organization) and changes its trait tree with add_trait / override_trait / remove_trait. A trait gives
equipment_bonus (to the equipment the MIO designs), production_bonus (to its production lines) and
organization_modifier (to the MIO itself). Policies (…/policies) give the same kinds of bonuses.
Save (country production.industrial_organisations): size (= level), funds, unlocked traits, active policy.
Trait tree (2026-10-20, user's request: the MIO window's tree drawn by the app): trait position { x y } in the grid
(plus the position of relative_position_id), parents (parent / any_parent / all_parents), mutually_exclusive,
tree_header_text { text x } over the columns; files may use @variables (GER: position = { x=@tank_hoesch_X }).
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
DEFAULT_RESEARCH_BONUS = 0.05   # defines DESIGN_TEAM_RESEARCH_BONUS (a MIO without research_bonus)
RESEARCH_BONUS = "military_industrial_organization_research_bonus"


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


def _scoped(block) -> dict[str, dict[str, float]]:
    """Bonuses for one equipment type inside a bonus block (policies: equipment_bonus = { heavy_tank_chassis = {..} })."""
    if not isinstance(block, list):
        return {}
    return {k: _numbers(v) for k, v in (e for e in block if isinstance(e, tuple))
            if isinstance(k, str) and isinstance(v, list) and _numbers(v)}


def _tokens(block) -> list[str]:
    return [t for t in block if isinstance(t, str)] if isinstance(block, list) else []


def _number(value, variables: dict) -> float | None:
    value = variables.get(value, value) if isinstance(value, str) else value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _string(body: list, key: str) -> str | None:
    value = text.get(body, key)
    return value if isinstance(value, str) else None


def _trait(body: list, variables: dict | None = None) -> dict:
    """The parts of a trait block that are present (an override_trait changes only those)."""
    variables = variables or {}
    out: dict = {key: _string(body, key) for key in ("token", "name", "icon") if _string(body, key)}
    for kind in BONUS_KINDS:
        block = text.get(body, kind)
        if isinstance(block, list):
            out[kind] = _numbers(block)
            if _scoped(block):
                out[f"{kind}_scoped"] = _scoped(block)
    if _string(body, "special_trait_background"):
        out["special"] = _string(body, "special_trait_background") == "yes"
    position = text.get(body, "position")
    if isinstance(position, list):
        out["x"] = _number(text.get(position, "x"), variables) or 0.0
        out["y"] = _number(text.get(position, "y"), variables) or 0.0
    if _string(body, "relative_position_id"):
        out["relative_to"] = _string(body, "relative_position_id")
    parent = text.get(body, "parent")
    if isinstance(parent, list):
        out["parents"] = _tokens(text.get(parent, "traits"))
        out["parents_needed"] = int(_number(text.get(parent, "num_parents_needed"), variables) or 1)
    elif isinstance(text.get(body, "any_parent"), list):
        out["parents"], out["parents_needed"] = _tokens(text.get(body, "any_parent")), 1
    elif isinstance(text.get(body, "all_parents"), list):
        out["parents"] = _tokens(text.get(body, "all_parents"))
        out["parents_needed"] = len(out["parents"])
    for key, field in (("mutually_exclusive", "exclusive"), ("limit_to_equipment_type", "limit_to"),
                       ("delete_included_values", "delete")):
        if isinstance(text.get(body, key), list):
            out[field] = _tokens(text.get(body, key))
    return out


# delete_included_values names -> the keys of a trait dict they clear
_DELETABLE = {**{kind: (kind, f"{kind}_scoped") for kind in BONUS_KINDS},
              "relative_position_id": ("relative_to",), "position": ("x", "y"), "icon": ("icon",), "name": ("name",),
              "parent": ("parents", "parents_needed"), "any_parent": ("parents", "parents_needed"),
              "all_parents": ("parents", "parents_needed"), "mutually_exclusive": ("exclusive",),
              "special_trait_background": ("special",), "limit_to_equipment_type": ("limit_to",)}


def _merge(base: dict, override: dict) -> dict:
    out = {**base, **{k: v for k, v in override.items() if k != "delete"}}
    for name in override.get("delete") or []:
        for key in _DELETABLE.get(name, ()):
            out.pop(key, None)
    return out


def _headers(body: list) -> list[dict]:
    return [{"text": text.get(b, "text"), "x": _number(text.get(b, "x"), {}) or 0.0}
            for k, b in (e for e in body if isinstance(e, tuple))
            if k == "tree_header_text" and isinstance(b, list) and isinstance(text.get(b, "text"), str)]


@lru_cache(maxsize=2)
def definitions(roots: tuple[str, ...]) -> dict:
    """{"organizations": {id: raw definition}, "policies": {id: {kind: {stat: v}, kind_scoped, "icon", "name"}}};
    later roots override."""
    orgs: dict[str, dict] = {}
    policies: dict[str, dict] = {}
    for root in map(Path, roots):
        base = root / "common" / "military_industrial_organization"
        for path in sorted((base / "organizations").glob("*.txt")):
            entries = [e for e in _parse(path) if isinstance(e, tuple)]
            variables = {k: v for k, v in entries if isinstance(k, str) and k.startswith("@") and isinstance(v, str)}
            for name, body in entries:
                if not isinstance(body, list):
                    continue
                initial = text.get(body, "initial_trait")
                traits = [(k, _trait(b, variables)) for k, b in (e for e in body if isinstance(e, tuple))
                          if k in ("trait", "add_trait", "override_trait") and isinstance(b, list)]
                orgs[name] = {
                    "include": _string(body, "include"), "name": _string(body, "name"), "icon": _string(body, "icon"),
                    "background": _string(body, "background"),
                    "equipment_type": _tokens(text.get(body, "equipment_type")),
                    "research_bonus": _number(text.get(body, "research_bonus"), variables),
                    "headers": _headers(body),
                    "initial_trait": _trait(initial, variables) if isinstance(initial, list) else None,
                    **{kind: [t for k, t in traits if k == kind] for kind in ("trait", "add_trait", "override_trait")},
                    "remove_trait": [t for k, b in body if k == "remove_trait" and isinstance(b, list)
                                     for t in b if isinstance(t, str)],
                }
        for path in sorted((base / "policies").glob("*.txt")):
            for name, body in (e for e in _parse(path) if isinstance(e, tuple)):
                if isinstance(body, list):
                    policies[name] = {**{kind: _numbers(text.get(body, kind)) for kind in BONUS_KINDS},
                                      **{f"{kind}_scoped": _scoped(text.get(body, kind)) for kind in BONUS_KINDS},
                                      "icon": _string(body, "icon"), "name": _string(body, "name")}
    return {"organizations": orgs, "policies": policies}


def resolve(defs: dict, mio: str, depth: int = 6) -> dict | None:
    """Effective definition: traits {token: trait} (the tree's order), initial trait, equipment types, category,
    template chain, research bonus, column headers and background of the trait tree."""
    d = defs["organizations"].get(mio)
    if d is None:
        return None
    parent = (resolve(defs, d["include"], depth - 1) if d["include"] and depth > 0 else None) or {}
    traits = dict(parent.get("traits") or {})
    for t in d["trait"] + d["add_trait"]:
        if t.get("token"):
            traits[t["token"]] = t
    for t in d["override_trait"]:   # only the parts it names change
        if t.get("token"):
            traits[t["token"]] = _merge(traits.get(t["token"]) or {}, t)
    for token in d["remove_trait"]:
        traits.pop(token, None)
    initial = d["initial_trait"]
    if initial and parent.get("initial_trait"):
        initial = _merge(parent["initial_trait"], initial)
    equipment = d["equipment_type"] or parent.get("equipment_type") or []
    chain = [mio] + (parent.get("chain") or [])
    return {"traits": traits, "initial_trait": initial or parent.get("initial_trait"),
            "equipment_type": equipment, "icon": d["icon"] or parent.get("icon"),
            "background": d["background"] or parent.get("background"),
            "headers": d["headers"] or parent.get("headers") or [],
            "research_bonus": d["research_bonus"] if d["research_bonus"] is not None else parent.get("research_bonus"),
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


def positions(traits: dict) -> dict[str, tuple[float, float]]:
    """{token: (x, y)} in the tree grid: position, plus the position of relative_position_id (chains followed)."""
    out: dict[str, tuple[float, float]] = {}

    def place(token: str, seen: tuple = ()) -> tuple[float, float]:
        if token in out:
            return out[token]
        t = traits.get(token) or {}
        x, y = t.get("x", 0.0), t.get("y", 0.0)
        rel = t.get("relative_to")
        if rel and rel in traits and rel not in seen and rel != token:
            rx, ry = place(rel, seen + (token,))
            x, y = x + rx, y + ry
        out[token] = (x, y)
        return out[token]
    for token in traits:
        place(token)
    return out


def tree(defs: dict, mio: str, unlocked: list[str] | None = None) -> dict | None:
    """The trait tree of a MIO as the game's MIO window draws it: {"headers": [{text, x}], "background", "traits":
    [{token, name, icon, x, y, parents, parents_needed, exclusive, special, kinds, unlocked, bonuses}], "width",
    "height"} - parents and exclusive only to traits of the tree."""
    d = resolve(defs, mio)
    if d is None:
        return None
    done = set(unlocked or [])
    where = positions(d["traits"])
    traits = []
    for token, t in d["traits"].items():
        x, y = where[token]
        traits.append({**{k: v for k, v in t.items() if k not in ("x", "y", "relative_to", "delete")},
                       "token": token, "x": x, "y": y,
                       "parents": [p for p in t.get("parents") or [] if p in d["traits"]],
                       "parents_needed": t.get("parents_needed", 1),
                       "exclusive": [e for e in t.get("exclusive") or [] if e in d["traits"]],
                       "special": bool(t.get("special")),
                       "kinds": [k for k in BONUS_KINDS if t.get(k) or t.get(f"{k}_scoped")],
                       "unlocked": token in done})
    return {"id": mio, "headers": d["headers"], "background": d["background"], "category": d["category"],
            "initial_trait": d["initial_trait"], "traits": traits,
            "width": max((t["x"] for t in traits), default=0) + 1, "height": max((t["y"] for t in traits), default=0) + 1}


def summary(state: dict, defs: dict) -> dict | None:
    """One MIO of the save with its current bonuses: {id, category, size, funds, research_bonus, policy,
    traits: [trait dicts], bonuses: {kind: {stat: total}}}. Research bonus: the MIO's own (or the define's) plus
    what its traits and policy add."""
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
    base = state.get("research_bonus")   # the MIO's own (save / game memory: effects may have raised it)
    if base is None:
        base = d["research_bonus"] if d["research_bonus"] is not None else DEFAULT_RESEARCH_BONUS
    return {"id": state["id"], "category": d["category"], "size": state.get("size"), "funds": state.get("funds"),
            "research_bonus": round(base + bonuses["organization_modifier"].get(RESEARCH_BONUS, 0.0), 6),
            "policy": state.get("policy"), "icon": state.get("icon") or d["icon"], "name_key": d["name"],
            "assign_cost": state.get("assign_cost"), "funds_factor": state.get("funds_factor"),
            "traits": unlocked, "initial_trait": d["initial_trait"], "bonuses": bonuses,
            "policy_scoped": {kind: policy.get(f"{kind}_scoped") or {} for kind in BONUS_KINDS} if policy else {}}
