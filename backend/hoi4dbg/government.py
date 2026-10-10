"""Laws & Government, Research & Production and Military Staff of a country, laid out like the game's politics screen.

Laws are ideas of the law categories, design companies and industrial concerns are ideas of their own categories
(all in the country's idea list of the save); advisors are the save's appointed advisors (characters).
Ideology colours (common/ideologies) and faction templates (common/factions/templates) serve the country overview.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from .saves import text

LAWS = [("mobilization_laws", "Conscription Law"), ("trade_laws", "Trade Law"), ("economy", "Economy Law")]
COMPANIES = [("tank_manufacturer", "Tank Designer"), ("naval_manufacturer", "Ship Designer"),
             ("aircraft_manufacturer", "Aircraft Designer"), ("materiel_manufacturer", "Materiel Designer"),
             ("industrial_concern", "Industrial Concern")]
ADVISOR_SLOTS = {"political_advisor": ("Political Advisor", 3), "theorist": ("Theorist", 1),
                 "army_chief": ("Chief of Army", 1), "navy_chief": ("Chief of Navy", 1),
                 "air_chief": ("Chief of Air Force", 1), "high_command": ("Military High Command", 3)}
PORTRAIT_KIND = {"army_chief": "army", "high_command": "army", "air_chief": "army", "navy_chief": "navy"}


@lru_cache(maxsize=2)
def ideologies(roots: tuple[str, ...]) -> dict:
    """{"colors": {ideology: (r, g, b)}, "parent": {sub-ideology: ideology}, "factions": {template: {name, icon}}}."""
    colors, parent, factions = {}, {}, {}
    for root in map(Path, roots):
        for path in sorted((root / "common" / "ideologies").glob("*.txt")):
            try:
                items = text.parse(_strip(path))
            except Exception:
                continue
            for _key, block in (i for i in items if isinstance(i, tuple)):
                for ideology, body in (i for i in block if isinstance(i, tuple)) if isinstance(block, list) else []:
                    if not isinstance(body, list):
                        continue
                    color = text.get(body, "color")
                    if isinstance(color, list) and len(color) >= 3:
                        try:
                            colors[ideology] = tuple(int(float(c)) for c in color[:3])
                        except ValueError:
                            pass
                    for sub, _ in (i for i in (text.get(body, "types") or []) if isinstance(i, tuple)):
                        parent[sub] = ideology
        for path in sorted((root / "common" / "factions" / "templates").glob("*.txt")):
            try:
                items = text.parse(_strip(path))
            except Exception:
                continue
            for name, body in (i for i in items if isinstance(i, tuple)):
                if isinstance(body, list):
                    factions[name] = {"name": text.get(body, "name"), "icon": text.get(body, "icon")}
    return {"colors": colors, "parent": parent, "factions": factions}


def _strip(path: Path) -> str:
    return re.sub(r"#[^\n]*", "", path.read_text(encoding="utf-8-sig", errors="replace"))


def _sum(trait_defs: dict, traits: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for t in traits:
        for k, v in trait_defs.get(t, {}).items():
            out[k] = round(out.get(k, 0.0) + v, 6)
    return out


def _empty(slot: str, label: str) -> dict:
    return {"slot": slot, "slot_label": label, "kind": "empty", "id": None, "name_key": None, "icon": None,
            "modifiers": {}, "traits": [], "tooltips": []}


def _idea(slot: str, label: str, kind: str, idea: str, defs: dict) -> dict:
    meta = defs["idea_meta"].get(idea) or {}
    traits = meta.get("traits") or []
    mods = {**_sum(defs["traits"], traits)}
    for k, v in defs["ideas"].get(idea, {}).items():
        mods[k] = round(mods.get(k, 0.0) + v, 6)
    return {"slot": slot, "slot_label": label, "kind": kind, "id": idea, "name_key": defs["idea_names"].get(idea, idea),
            "icon": f"GFX_idea_{meta.get('picture') or idea}", "modifiers": mods, "traits": traits,
            "tooltips": meta.get("tooltips") or []}


def _portrait(ch: dict, slot: str) -> str | None:
    portraits = ch.get("portraits") or {}
    for kind in (PORTRAIT_KIND.get(slot, "civilian"), "civilian", "army", "navy"):
        for size in ("small", "large"):
            sprite = (portraits.get(kind) or {}).get(size)
            if sprite:
                return sprite
    return None


def sections(state: dict, defs: dict) -> dict[str, list[dict]]:
    """{"laws": [...], "research": [...], "military": [...]}: one entry per slot, in the game's order."""
    by_category: dict[str, list[str]] = {}
    for idea in state.get("ideas") or []:
        cat = (defs["idea_meta"].get(idea) or {}).get("category")
        if cat:
            by_category.setdefault(cat, []).append(idea)

    laws = []
    for cat, label in LAWS:
        ideas = by_category.get(cat) or []
        laws.append(_idea(cat, label, "law", ideas[0], defs) if ideas else _empty(cat, label))
    known = {c for c, _ in LAWS}
    for idea in state.get("ideas") or []:   # other law categories (mods, special laws)
        meta = defs["idea_meta"].get(idea) or {}
        if meta.get("law") and meta.get("category") not in known:
            laws.append(_idea(meta["category"], meta["category"].replace("_", " ").title(), "law", idea, defs))

    chars = state.get("characters") or {}
    appointed: dict[str, list[dict]] = {}
    for adv in state.get("advisors") or []:
        ch = chars.get(adv.get("id") or "")
        role = next((r for r in (ch or {}).get("advisors", []) if r["slot"] == adv.get("slot")), None)
        if not ch or not role:
            continue
        mods = _sum(defs["traits"], role["traits"])
        for k, v in defs["ideas"].get(role["idea_token"] or "", {}).items():
            mods[k] = round(mods.get(k, 0.0) + v, 6)
        appointed.setdefault(adv["slot"], []).append({
            "slot": adv["slot"], "slot_label": ADVISOR_SLOTS.get(adv["slot"], (adv["slot"], 1))[0], "kind": "advisor",
            "id": role["idea_token"] or ch["token"], "name_key": ch["name"] or ch["token"],
            "alt_name_key": ch["token"], "icon": _portrait(ch, adv["slot"]), "modifiers": mods,
            "traits": role["traits"], "tooltips": []})

    def advisors(slot: str) -> list[dict]:
        label, count = ADVISOR_SLOTS[slot]
        filled = appointed.get(slot, [])
        return filled + [_empty(slot, label) for _ in range(max(0, count - len(filled)))]

    research = []
    for cat, label in COMPANIES:
        ideas = by_category.get(cat) or []
        research.extend(_idea(cat, label, "company", i, defs) for i in ideas)
        if not ideas:
            research.append(_empty(cat, label))
    return {
        "laws": laws + advisors("political_advisor"),
        "research": research + advisors("theorist"),
        "military": advisors("army_chief") + advisors("navy_chief") + advisors("air_chief") + advisors("high_command"),
    }
