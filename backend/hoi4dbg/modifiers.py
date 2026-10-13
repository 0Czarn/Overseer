"""Stability / war support as the game shows them: base value + every modifier, with the source of each part.

Sources (game files + enabled mods, later folders override):
- national spirits and laws: common/ideas (`modifier = { ... }`)
- country leader and advisor traits: common/country_leader (keys directly in the trait or in `modifier`)
- dynamic modifiers: common/dynamic_modifiers; the save stores their evaluated values in the order of the
  modifier keys of the definition (`enable`, `icon`, `remove_trigger`, blocks are not modifiers)
- ruling party popularity: popularity x (defines BASE_STABILITY_PARTY_POPULARITY_FACTOR + every
  party_popularity_stability_factor of the other sources)
- doctrines: grand doctrine and subdoctrine modifiers + the first `rewards` rewards of each slotted subdoctrine
  (common/doctrines; the save keeps sub_doctrine and the number of unlocked rewards per track)
- world tension (war support): defines WAR_SUPPORT_TENSION_IMPACT x tension (2026-10-10: 0.4 x 4.815 % = the
  +1.92 % the game showed for SOV)
- faction rules of the country's faction: common/factions/rules (`modifier`, applied when `trigger` holds;
  e.g. war_declaration_rule_major_only "Declaring Country is Considered Major" -5 % / -5 % for SOV)
- static modifiers the save marks: pride_of_the_fleet_country (common/modifiers)
- buildings with country modifiers (landmarks, common/buildings `country_modifiers`): for the controller of the
  province holding them, if listed in `enable_for_controllers` (e.g. Taj Mahal: RAJ +5 % stability)
- balance of power: the range of common/bop that holds the save's value (e.g. FIN -0.48 -> FIN_low_trust_range
  -0.6..-0.1: -5 % / -5 %) and the balance's active modifier (common/modifiers)
The total is clamped to 0..100 % like the game (MIN/MAX_STABILITY, MIN/MAX_WAR_SUPPORT).
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from .saves import text

KEYS = {"stability": "stability_factor", "war_support": "war_support_factor"}
# raises the ruling-party term: popularity x (BASE_STABILITY_PARTY_POPULARITY_FACTOR + sum of this modifier)
# (GER: 40 % x (0.15 + 0.10 from an advisor) = the +10 % the game showed)
POPULARITY_KEY = "party_popularity_stability_factor"
NOT_MODIFIERS = {"enable", "icon", "remove_trigger", "attacker_modifier", "valid_relation_trigger", "allowed",
                 "visible", "available", "cancel", "on_add", "on_remove", "ai_will_do", "random", "sprite",
                 "ideology", "type", "picture", "name", "cost", "removal_cost", "level", "allowed_civil_war",
                 "allowed_to_remove", "default", "law", "use_list_view", "is_default", "ledger", "slot",
                 "can_be_fired", "triggered_modifier", "targeted_modifier", "equipment_bonus", "research_bonus",
                 "rule", "traits", "do_effect", "mutually_exclusive", "non_shared_modifier", "gui_order",
                 "specialist_advisor_trait", "expert_advisor_trait", "genius_advisor_trait", "parent", "command_cap",
                 "power_balance_modifier", "custom_modifier_tooltip", "hidden_modifier"}
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
    idea_meta: dict[str, dict] = {}   # idea -> {"category", "law", "picture", "tooltips"}
    dynamic_icons: dict[str, str] = {}
    traits: dict[str, dict] = {}
    dynamic: dict[str, list] = {}
    static: dict[str, dict] = {}
    rules: dict[str, dict] = {}       # faction rule -> {"mods", "trigger"}
    bop: dict[str, list] = {}         # balance of power -> [{"id", "min", "max", "mods", "side"}]
    buildings: dict[str, dict] = {}   # building -> {"controllers": [tags] or None (any), "mods"}
    doctrines: dict[str, dict] = {}   # grand doctrine / subdoctrine -> {"mods", "rewards": [(name, mods)]}
    doctrine_names: dict[str, list[str]] = {}   # name key -> ids in definition order (game memory holds the key)
    defines: dict[str, float] = {}
    for root in map(Path, roots):
        for path in sorted((root / "common" / "ideas").glob("*.txt")):
            for key, groups in _parse(path):
                if key != "ideas" or not isinstance(groups, list):
                    continue
                for cat, entries in (g for g in groups if isinstance(g, tuple)):
                    law = isinstance(entries, list) and text.get(entries, "law") == "yes"
                    for idea, body in (e for e in entries if isinstance(e, tuple)) if isinstance(entries, list) else []:
                        if isinstance(body, list):
                            mod = text.get(body, "modifier")
                            ideas[idea] = _numbers(mod)
                            picture = text.get(body, "picture")
                            idea_meta[idea] = {
                                "category": cat, "law": law, "picture": picture if isinstance(picture, str) else None,
                                "traits": [t for t in (text.get(body, "traits") or []) if isinstance(t, str)]
                                if isinstance(text.get(body, "traits"), list) else [],
                                "tooltips": [v for k, v in (mod if isinstance(mod, list) else [])
                                             if k == "custom_modifier_tooltip" and isinstance(v, str)]}
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
                    if isinstance(text.get(body, "icon"), str):
                        dynamic_icons[name] = text.get(body, "icon")
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
        for path in sorted((root / "common" / "buildings").glob("*.txt")):
            for key, entries in _parse(path):
                if key != "buildings" or not isinstance(entries, list):
                    continue
                for name, body in (e for e in entries if isinstance(e, tuple)):
                    cm = text.get(body, "country_modifiers") if isinstance(body, list) else None
                    if isinstance(cm, list):
                        tags = text.get(cm, "enable_for_controllers")
                        buildings[name] = {"controllers": [t for t in tags if isinstance(t, str)] if isinstance(tags, list) else None,
                                           "mods": _numbers(text.get(cm, "modifiers"))}
        for path in sorted((root / "common" / "doctrines").rglob("*.txt")):
            for name, body in (e for e in _parse(path) if isinstance(e, tuple)):
                if isinstance(body, list):
                    rewards = text.get(body, "rewards")
                    if isinstance(text.get(body, "name"), str):
                        ids = doctrine_names.setdefault(text.get(body, "name"), [])
                        if name not in ids:
                            ids.append(name)
                    doctrines[name] = {
                        "mods": {k: v for k, v in _numbers(body).items() if k not in NOT_MODIFIERS},
                        "rewards": [(r, _numbers(m)) for r, m in (i for i in rewards or [] if isinstance(i, tuple))]
                        if isinstance(rewards, list) else []}
        for path in sorted((root / "common" / "bop").glob("*.txt")):
            for name, body in (e for e in _parse(path) if isinstance(e, tuple)):
                if isinstance(body, list):
                    bop[name] = _bop_ranges(body)
        for path in sorted((root / "common" / "defines").glob("*.lua")):
            src = path.read_text(encoding="utf-8-sig", errors="replace")
            for name in ("BASE_STABILITY_PARTY_POPULARITY_FACTOR", "MIN_STABILITY", "MAX_STABILITY",
                         "MIN_WAR_SUPPORT", "MAX_WAR_SUPPORT", "WAR_SUPPORT_TENSION_IMPACT",
                         "BASE_STABILITY_WAR_FACTOR", "WAR_SUPPORT_OFFNSIVE_WAR", "WAR_SUPPORT_DEFENSIVE_WAR"):
                m = re.search(DEFINE_RE.format(name), src, re.M)
                if m:
                    defines[name] = float(m.group(1))
    return {"ideas": ideas, "idea_names": idea_names, "idea_meta": idea_meta, "dynamic_icons": dynamic_icons, "traits": traits, "dynamic": dynamic, "static": static,
            "rules": rules, "bop": bop, "buildings": buildings, "doctrines": doctrines,
            "doctrine_names": doctrine_names, "defines": defines}


def _bop_ranges(body: list) -> list[dict]:
    """Ranges of a balance of power: the central `range`s and the `range`s inside each `side`."""
    out = []
    def add(block, side):
        for key, r in (i for i in block if isinstance(i, tuple)):
            if key == "range" and isinstance(r, list):
                lo, hi = _numbers(r).get("min"), _numbers(r).get("max")
                if lo is not None and hi is not None:
                    out.append({"id": text.get(r, "id"), "min": lo, "max": hi, "side": side,
                                "mods": _numbers(text.get(r, "modifier"))})
    add(body, None)
    for key, side in (i for i in body if isinstance(i, tuple)):
        if key == "side" and isinstance(side, list):
            add(side, text.get(side, "id"))
    return out


def bop_range(ranges: list[dict], value: float) -> dict | None:
    """Active range: the one strictly containing the value, else (on a border) the first one including it."""
    inside = [r for r in ranges if r["min"] < value < r["max"]]
    border = [r for r in ranges if r["min"] <= value <= r["max"]]
    return (inside or border or [None])[0]


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
    keys.update(state.get("buildings") or [])
    for d in state.get("doctrines") or []:
        keys.update(filter(None, [d["id"], *[r for r, _ in (defs["doctrines"].get(d["id"]) or {}).get("rewards", [])]]))
    for b in state.get("power_balances") or []:
        keys.update(filter(None, [b["id"], b.get("modifier")]))
        keys.update(r["id"] for r in defs["bop"].get(b["id"], []) if r["id"])
    return keys


def breakdown(state: dict, defs: dict, names: dict[str, str] | None = None) -> dict:
    """{field: {"base", "parts": [{kind, id, name, value}], "modifiers", "total", "clamped"}} for
    stability and war support. `state` = saves.politics.summary(); `names` = localisation."""
    names = names or {}
    chars = state.get("characters") or {}
    sources: list[tuple[str, str, str, dict]] = []   # (kind, id, label, {key: value})

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
    for building in state.get("buildings") or []:
        d = defs["buildings"].get(building)
        if d and (d["controllers"] is None or state.get("tag") in d["controllers"]):
            sources.append(("building", building, names.get(building, building), d["mods"]))
    for b in state.get("power_balances") or []:
        r = bop_range(defs["bop"].get(b["id"], []), b["value"]) if b["value"] is not None else None
        title = names.get(b["id"], b["id"])
        if r:
            sources.append(("bop", r["id"], f"{names.get(r['id'], r['id'])} (balance of power {b['value']:+.2f})", r["mods"]))
        if b.get("modifier"):
            sources.append(("bop", b["modifier"], f"{names.get(b['modifier'], b['modifier'])} ({title})",
                            defs["static"].get(b["modifier"], {})))
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

    for d in state.get("doctrines") or []:
        definition = defs["doctrines"].get(d["id"])
        if not definition:
            continue
        label = names.get(d["id"], d["id"])
        if definition["mods"]:
            sources.append(("doctrine", d["id"], label, definition["mods"]))
        for reward, mods in definition["rewards"][:d.get("rewards") or 0]:
            sources.append(("doctrine", reward, f"{label}: {names.get(reward, reward)}", mods))

    # war (2026-10-11, SOV at war with POL, checked against the game tooltip): offensive / defensive war support
    # from the defines; "At war" = BASE_STABILITY_WAR_FACTOR + war_stability_factor (2026-10-13, SOV 1941: game sum
    # 0.02195 -> -17.80 % as the game shows, unchanged a month later; with POL 0.0025 -> -19.75 %), the game's own sum
    # in state["war_stability_factor"] when read from memory, else the app's known sources; penalties that build up
    # weekly from the save
    wars = state.get("wars") or []
    if wars:
        factor = state.get("war_stability_factor")
        if factor is None:
            factor = sum(mods.get("war_stability_factor", 0) for *_rest, mods in sources)
        sources.append(("war", "at_war", "At war",
                        {KEYS["stability"]: defs["defines"].get("BASE_STABILITY_WAR_FACTOR", -0.2) + factor}))
        if any(w["offensive"] for w in wars):
            sources.append(("war", "offensive_war", "Offensive war",
                            {KEYS["war_support"]: defs["defines"].get("WAR_SUPPORT_OFFNSIVE_WAR", -0.2)}))
        if any(not w["offensive"] for w in wars):
            sources.append(("war", "defensive_war", "Defensive war",
                            {KEYS["war_support"]: defs["defines"].get("WAR_SUPPORT_DEFENSIVE_WAR", 0.2)}))
    for key, label in (("bombing_penalty", "Enemy bombing"), ("casualties_penalty", "Combat Casualties")):
        if state.get(key):
            sources.append(("war", key, label, {KEYS["war_support"]: state[key]}))

    popularity = (state.get("popularity") or {}).get(state.get("ruling_party"))
    if popularity:
        base_factor = defs["defines"].get("BASE_STABILITY_PARTY_POPULARITY_FACTOR", 0.15)
        extra = [(label, mods[POPULARITY_KEY]) for _k, _i, label, mods in sources if mods.get(POPULARITY_KEY)]
        factor = base_factor + sum(v for _, v in extra)
        detail = "".join(f", {v * 100:+g}% from {label}" for label, v in extra)
        sources.insert(0, ("party", state["ruling_party"],
                           f"Ruling party popularity ({popularity:g}% x {factor * 100:g}%{detail})",
                           {KEYS["stability"]: factor * popularity / 100}))

    out = {"unchecked_rules": unchecked}
    fields = list(KEYS.items())
    fields.sort(key=lambda fk: fk[0] != "war_support")   # war support first: stability at war depends on it
    for field, key in fields:
        if field == "stability" and wars and out.get("war_support", {}).get("total") is not None:
            # static modifier war_support_during_war: stability_factor -0.3, scaled by how much war support is missing
            scale = defs["static"].get("war_support_during_war", {}).get(key, -0.3)
            sources.append(("war", "war_support_during_war", "War Support",
                            {key: scale * (1 - out["war_support"]["total"])}))
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


# The game's "National Spirits" list: ideas of this category (laws, advisors, companies and military spirits have
# their own categories and panels) + dynamic modifiers.
SPIRIT_CATEGORY = "country"


def spirits(state: dict, defs: dict) -> list[dict]:
    """National spirits as the game lists them: ideas of the `country` category and dynamic modifiers.
    [{kind, id, name_key, icon (sprite), modifiers: {key: value}, tooltips: [loc keys]}]"""
    out = []
    for idea in state.get("ideas") or []:
        meta = defs["idea_meta"].get(idea) or {}
        if meta.get("category") != SPIRIT_CATEGORY:
            continue
        out.append({"kind": "idea", "id": idea, "name_key": defs["idea_names"].get(idea, idea),
                    "icon": f"GFX_idea_{meta.get('picture') or idea}",
                    "modifiers": defs["ideas"].get(idea, {}), "tooltips": meta.get("tooltips", [])})
    for dm in state.get("dynamic_modifiers") or []:
        if not dm.get("enabled") or dm["id"] not in defs["dynamic"]:
            continue
        mods = {}
        for k, v in zip(defs["dynamic"][dm["id"]], dm["values"]):
            try:
                if float(v):
                    mods[k] = float(v)
            except ValueError:
                pass
        out.append({"kind": "dynamic", "id": dm["id"], "name_key": dm["id"], "icon": defs["dynamic_icons"].get(dm["id"]),
                    "modifiers": mods, "tooltips": []})
    return out
