"""Stability / war support as the game shows them: base value + every modifier, with the source of each part.

Sources (game files + enabled mods, later folders override):
- national spirits and laws: common/ideas (`modifier = { ... }`)
- country leader and advisor traits: common/country_leader (keys directly in the trait or in `modifier`)
- dynamic modifiers: common/dynamic_modifiers; the save stores their evaluated values in the order of the
  modifier keys of the definition (`enable`, `icon`, `remove_trigger`, blocks are not modifiers)
- ruling party popularity: defines BASE_STABILITY_PARTY_POPULARITY_FACTOR x popularity
- world tension (war support): defines WAR_SUPPORT_TENSION_IMPACT x tension (2026-10-10: 0.4 x 4.815 % = the
  +1.92 % the game showed for SOV)
- faction rules of the country's faction: common/factions/rules (`modifier`, applied when `trigger` holds;
  e.g. war_declaration_rule_major_only "Declaring Country is Considered Major" -5 % / -5 % for SOV)
- static modifiers the save marks: pride_of_the_fleet_country (common/modifiers)
The total is clamped to 0..100 % like the game (MIN/MAX_STABILITY, MIN/MAX_WAR_SUPPORT).
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from .saves import text

KEYS = {"stability": "stability_factor", "war_support": "war_support_factor"}
NOT_MODIFIERS = {"enable", "icon", "remove_trigger", "attacker_modifier", "valid_relation_trigger", "allowed",
                 "visible", "available", "cancel", "on_add", "on_remove", "ai_will_do", "random", "sprite",
                 "ideology", "type", "picture", "name", "cost", "removal_cost", "level", "allowed_civil_war",
                 "allowed_to_remove", "default", "law", "use_list_view", "is_default", "ledger", "slot",
                 "can_be_fired", "triggered_modifier", "targeted_modifier", "equipment_bonus", "research_bonus",
                 "rule", "traits", "do_effect", "mutually_exclusive", "non_shared_modifier", "gui_order",
                 "specialist_advisor_trait", "expert_advisor_trait", "genius_advisor_trait", "parent", "command_cap",
                 "power_balance_modifier"}
DEFINE_RE = r"^\s*{}\s*=\s*(-?[0-9.]+)"


def _strip(path: Path) -> str:
    return re.sub(r"#[^\n]*", "", path.read_text(encoding="utf-8-sig", errors="replace"))


def _numbers(block) -> dict[str, float]:
    out = {}
    for item in block if isinstance(block, list) else []:
        if isinstance(item, tuple) and isinstance(item[0], str) and isinstance(item[1], str):
            try:
                out[item[0]] = float(item[1])
            except ValueError:
                pass
    return out


def _parse(path: Path) -> list:
    try:
        return text.parse(_strip(path))
    except Exception:  # a broken mod file must not break the whole list
        return []


@lru_cache(maxsize=2)
def definitions(roots: tuple[str, ...]) -> dict:
    """{"ideas": {id: {key: v}}, "traits": {id: {key: v}}, "dynamic": {id: [keys in order]}, "defines": {...}}."""
    ideas: dict[str, dict] = {}
    idea_names: dict[str, str] = {}   # idea -> localisation key (`name = ...`, else the idea id)
    traits: dict[str, dict] = {}
    dynamic: dict[str, list] = {}
    static: dict[str, dict] = {}
    rules: dict[str, dict] = {}       # faction rule -> {"mods", "trigger"}
    defines: dict[str, float] = {}
    for root in map(Path, roots):
        for path in sorted((root / "common" / "ideas").glob("*.txt")):
            for key, groups in _parse(path):
                if key != "ideas" or not isinstance(groups, list):
                    continue
                for _cat, entries in (g for g in groups if isinstance(g, tuple)):
                    for idea, body in (e for e in entries if isinstance(e, tuple)) if isinstance(entries, list) else []:
                        if isinstance(body, list):
                            ideas[idea] = _numbers(text.get(body, "modifier"))
                            idea_names[idea] = text.get(body, "name") if isinstance(text.get(body, "name"), str) else idea
        for path in sorted((root / "common" / "country_leader").glob("*.txt")):
            for key, entries in _parse(path):
                if key != "leader_traits" or not isinstance(entries, list):
                    continue
                for trait, body in (e for e in entries if isinstance(e, tuple)):
                    if isinstance(body, list):
                        traits[trait] = {**{k: v for k, v in _numbers(body).items() if k not in NOT_MODIFIERS},
                                         **_numbers(text.get(body, "modifier"))}
        for path in sorted((root / "common" / "dynamic_modifiers").glob("*.txt")):
            for name, body in (e for e in _parse(path) if isinstance(e, tuple)):
                if isinstance(body, list):
                    dynamic[name] = [k for k, v in (i for i in body if isinstance(i, tuple))
                                     if isinstance(k, str) and isinstance(v, str) and k not in NOT_MODIFIERS]
        for path in sorted((root / "common" / "modifiers").glob("*.txt")):
            for name, body in (e for e in _parse(path) if isinstance(e, tuple)):
                if isinstance(body, list):
                    static[name] = _numbers(body)
        for path in sorted((root / "common" / "factions" / "rules").glob("*.txt")):
            for name, body in (e for e in _parse(path) if isinstance(e, tuple)):
                if isinstance(body, list):
                    rules[name] = {"mods": _numbers(text.get(body, "modifier")), "trigger": text.get(body, "trigger")}
        for path in sorted((root / "common" / "defines").glob("*.lua")):
            src = path.read_text(encoding="utf-8-sig", errors="replace")
            for name in ("BASE_STABILITY_PARTY_POPULARITY_FACTOR", "MIN_STABILITY", "MAX_STABILITY",
                         "MIN_WAR_SUPPORT", "MAX_WAR_SUPPORT", "WAR_SUPPORT_TENSION_IMPACT"):
                m = re.search(DEFINE_RE.format(name), src, re.M)
                if m:
                    defines[name] = float(m.group(1))
    return {"ideas": ideas, "idea_names": idea_names, "traits": traits, "dynamic": dynamic, "static": static,
            "rules": rules, "defines": defines}


def trigger_holds(trigger, state: dict) -> bool | None:
    """The few conditions faction rules use; None = a condition this app does not evaluate."""
    if trigger is None:
        return True
    results = []
    for item in trigger if isinstance(trigger, list) else []:
        key, value = item if isinstance(item, tuple) else (None, None)
        if key == "is_major":
            results.append(state.get("major") == (value == "yes"))
        elif key == "is_faction_leader":
            results.append(bool((state.get("faction") or {}).get("leader")) == (value == "yes"))
        elif key in ("original_tag", "tag"):
            results.append(state.get("tag") == value)
        elif key == "OR":
            inner = [trigger_holds([i], state) for i in value]
            results.append(None if None in inner and True not in inner else True in inner)
        elif key in ("custom_trigger_tooltip", "AND"):
            results.append(trigger_holds([i for i in value if not (isinstance(i, tuple) and i[0] == "tooltip")], state))
        else:
            results.append(None)
    if False in results:
        return False
    return None if None in results else True


def loc_keys(state: dict, defs: dict) -> set[str]:
    """Localisation keys needed to label breakdown() of `state`."""
    keys = {defs["idea_names"].get(i, i) for i in state.get("ideas") or []}
    for ch in (state.get("characters") or {}).values():
        keys.update(filter(None, [ch["name"], ch["token"], *ch["leader_traits"]]))
        for role in ch["advisors"]:
            keys.update(filter(None, [role["slot"], role["idea_token"], *role["traits"]]))
    keys.update(d["id"] for d in state.get("dynamic_modifiers") or [])
    keys.update((state.get("faction") or {}).get("rules", []))
    keys.add("pride_of_the_fleet_country")
    return keys


def breakdown(state: dict, defs: dict, names: dict[str, str] | None = None) -> dict:
    """{field: {"base", "parts": [{kind, id, name, value}], "modifiers", "total", "clamped"}} for
    stability and war support. `state` = saves.politics.summary(); `names` = localisation."""
    names = names or {}
    chars = state.get("characters") or {}
    sources: list[tuple[str, str, str, dict]] = []   # (kind, id, label, {key: value})

    popularity = (state.get("popularity") or {}).get(state.get("ruling_party"))
    factor = defs["defines"].get("BASE_STABILITY_PARTY_POPULARITY_FACTOR", 0.15)
    if popularity:
        sources.append(("party", state["ruling_party"], f"Ruling party popularity ({popularity:g}%)",
                        {KEYS["stability"]: factor * popularity / 100}))
    for idea in state.get("ideas") or []:
        key = defs["idea_names"].get(idea, idea)
        sources.append(("idea", idea, names.get(key, names.get(idea, idea)), defs["ideas"].get(idea, {})))
    leader = chars.get(state.get("leader") or "")
    if leader:
        who = names.get(leader["name"] or "", names.get(leader["token"] or "", leader["name"] or leader["token"]))
        for trait in leader["leader_traits"]:
            sources.append(("leader", trait, f"{who}: {names.get(trait, trait)}", defs["traits"].get(trait, {})))
    for adv in state.get("advisors") or []:
        ch = chars.get(adv.get("id") or "")
        if not ch:
            continue
        who = names.get(ch["name"] or "", names.get(ch["token"] or "", ch["name"] or ch["token"]))
        for role in ch["advisors"]:
            if role["slot"] != adv.get("slot"):
                continue
            mods = {}
            for trait in role["traits"]:
                for k, v in defs["traits"].get(trait, {}).items():
                    mods[k] = mods.get(k, 0) + v
            sources.append(("advisor", role["idea_token"] or ch["token"], f"{who} ({names.get(role['slot'], role['slot'])})",
                            {**mods, **defs["ideas"].get(role["idea_token"] or "", {})}))
    for dm in state.get("dynamic_modifiers") or []:
        if not dm.get("enabled"):
            continue
        keys = defs["dynamic"].get(dm["id"])
        if keys is None:
            continue
        mods = {}
        for k, v in zip(keys, dm["values"]):
            try:
                mods[k] = float(v)
            except ValueError:
                pass
        sources.append(("dynamic", dm["id"], names.get(dm["id"], dm["id"]), mods))

    tension = state.get("tension")
    impact = defs["defines"].get("WAR_SUPPORT_TENSION_IMPACT", 0.4)
    if tension:
        sources.append(("world", "tension", f"World tension ({tension:.2f}%)", {KEYS["war_support"]: impact * tension / 100}))
    if state.get("pride_of_the_fleet"):
        sources.append(("static", "pride_of_the_fleet_country",
                        names.get("pride_of_the_fleet_country", "Has Pride of The Fleet"),
                        defs["static"].get("pride_of_the_fleet_country", {})))
    unchecked = []
    for rule in (state.get("faction") or {}).get("rules", []):
        d = defs["rules"].get(rule)
        if not d or not any(d["mods"].get(k) for k in KEYS.values()):
            continue
        holds = trigger_holds(d["trigger"], state)
        if holds:
            sources.append(("faction", rule, names.get(rule, rule), d["mods"]))
        elif holds is None:
            unchecked.append(names.get(rule, rule))

    out = {"unchecked_rules": unchecked}
    for field, key in KEYS.items():
        base = state.get(field)
        parts = [{"kind": kind, "id": sid, "name": label, "value": round(mods[key], 6)}
                 for kind, sid, label, mods in sources if mods.get(key)]
        total_mods = round(sum(p["value"] for p in parts), 6)
        lo = defs["defines"].get(f"MIN_{field.upper()}", 0.0)
        hi = defs["defines"].get(f"MAX_{field.upper()}", 1.0)
        raw = None if base is None else base + total_mods
        out[field] = {"base": base, "parts": parts, "modifiers": total_mods,
                      "total": None if raw is None else min(hi, max(lo, raw)),
                      "clamped": raw is not None and not lo <= raw <= hi}
    return out
