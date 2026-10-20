"""Game triggers (focus `available` blocks) evaluated with three values: True, False, None = the app cannot tell.

Script syntax with comparison operators (`has_political_power > 50`), which saves.text does not keep: parse()
gives [(key, op, value)], value a string or a nested list. evaluate() walks the block like the game: the block and
AND are all-of, OR any-of, NOT none-of (the game's NOT is a NOR of its contents); if / else_if / else; scopes (TAG,
state number, ROOT / THIS / PREV, owner / controller / overlord) and the usual any_ / all_ iterators; scripted
triggers of common/scripted_triggers are expanded; has_game_rule asks world.game_rule(). A trigger the app has no data for (flags, civil war, variables,
continents, ...) is None and named in Context.unknown, so the caller can say why it did not decide.

The data comes from a world object (live/world.py: game memory) - see the methods used below.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

# a quoted string may hold escaped quotes (2026-10-20, Road to 56 germany.txt: division = "name = \"Volkssturm ...\""):
# read as one string, else its braces and the rest of the file were misread (837 of 909 German focuses lost)
TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|[<>!]?=|[<>]|[{}]|[^\s{}=<>!]+')
COMMENT = re.compile(r'("(?:[^"\\\n]|\\.)*")|#[^\n]*')   # a # inside a quoted string is not a comment
OPS = ("=", "<", ">", "<=", ">=", "!=")
TAG_RE = re.compile(r"[A-Z][A-Z0-9]{2}")


def parse(source: str) -> list:
    tokens = TOKEN.findall(COMMENT.sub(lambda m: m.group(1) or "", source))
    out, _ = _parse(tokens, 0)
    return out


def _parse(t: list[str], i: int) -> tuple[list, int]:
    out = []
    while i < len(t):
        x = t[i]
        if x == "}":
            return out, i + 1
        if i + 1 < len(t) and t[i + 1] in OPS:
            op = t[i + 1]
            if i + 2 < len(t) and t[i + 2] == "{":
                value, i = _parse(t, i + 3)
            else:
                value = t[i + 2].strip('"') if i + 2 < len(t) else None
                i += 3
            out.append((x, op, value))
        elif i + 1 < len(t) and t[i + 1] == "{" and x not in OPS:   # `key { ... }` without "=" (the game takes it)
            value, i = _parse(t, i + 2)
            out.append((x, "=", value))
        elif x == "{":
            value, i = _parse(t, i + 1)
            out.append((None, "", value))
        else:
            out.append((None, "", x))
            i += 1
    return out, i


@lru_cache(maxsize=4)
def focus_scripts(files: tuple[str, ...]) -> dict[str, dict]:
    """{focus id: {"available": block, "allow_branch": block or None, "offsets": [(x, y, trigger block)]}} of every
    focus in the files (focus.focus_files; later files override)."""
    out: dict[str, dict] = {}
    for path in files:
        try:
            items = parse(Path(path).read_text(encoding="utf-8-sig", errors="replace"))
        except Exception:
            continue
        blocks = []
        for key, _op, value in items:
            if key == "focus_tree" and isinstance(value, list):
                blocks += [v for k, _o, v in value if k == "focus" and isinstance(v, list)]
            elif key in ("shared_focus", "joint_focus") and isinstance(value, list):
                blocks.append(value)
        for block in blocks:
            fid = next((v for k, _o, v in block if k == "id" and isinstance(v, str)), None)
            if not fid:
                continue
            offsets = []
            for k, _o, v in block:
                if k == "offset" and isinstance(v, list):
                    try:
                        dx, dy = (float(next((x for kk, _oo, x in v if kk == axis), 0) or 0) for axis in ("x", "y"))
                    except (TypeError, ValueError):
                        continue
                    offsets.append((dx, dy, next((x for kk, _oo, x in v if kk == "trigger" and isinstance(x, list)), [])))
            out[fid] = {"available": next((v for k, _o, v in block if k == "available" and isinstance(v, list)), []),
                        "allow_branch": next((v for k, _o, v in block if k == "allow_branch" and isinstance(v, list)), None),
                        "offsets": offsets}
    return out


def focus_conditions(files: tuple[str, ...]) -> dict[str, list]:
    """{focus id: its `available` block}."""
    return {fid: s["available"] for fid, s in focus_scripts(files).items()}


@lru_cache(maxsize=4)
def game_rule_defaults(files: tuple[str, ...]) -> dict[str, str]:
    """{rule: default option} of common/game_rules (gamefiles.merged_files) - the rules of a game started without
    changing them."""
    out: dict[str, str] = {}
    for path in files:
        try:
            items = parse(Path(path).read_text(encoding="utf-8-sig", errors="replace"))
        except Exception:
            continue
        for key, _op, value in items:
            if key and isinstance(value, list):
                default = next((v for k, _o, v in value if k == "default" and isinstance(v, list)), None)
                name = next((v for k, _o, v in default or [] if k == "name" and isinstance(v, str)), None)
                if name:
                    out[key] = name
    return out


class Unknown(Exception):
    """Raised by a world that has no data for a trigger (SavedWorld) - the trigger is None."""


class SavedWorld:
    """A world from a save / the app's files only: the country's completed focuses and flags, owned DLCs and game
    rules. Everything else is unknown - enough for allow_branch and offsets, which mostly ask for those."""

    def __init__(self, tag: str, completed: list[str], dlcs: set[str] | None, rules: dict[str, str],
                 countries: list[str], flags: dict | None = None) -> None:
        self.tag, self._completed, self._dlcs, self.rules, self._countries = tag, set(completed), dlcs, rules, countries
        self._flags = flags

    def country_flags(self, tag: str) -> dict | None:
        return self._flags if tag == self.tag else None

    def countries(self) -> list[str]:
        return self._countries

    def dlcs(self) -> set[str] | None:
        return self._dlcs

    def game_rule(self, rule: str) -> str | None:
        return self.rules.get(rule)

    def completed(self, tag: str) -> set[str]:
        if tag != self.tag:
            raise Unknown(tag)
        return self._completed

    def __getattr__(self, name):
        def unknown(*_args, **_kwargs):
            raise Unknown(name)
        return unknown


@lru_cache(maxsize=4)
def scripted_triggers(roots: tuple[str, ...]) -> dict[str, list]:
    """{name: trigger block} of common/scripted_triggers (game first, mods override)."""
    out: dict[str, list] = {}
    for root in roots:
        for path in sorted((Path(root) / "common" / "scripted_triggers").glob("*.txt")):
            try:
                items = parse(path.read_text(encoding="utf-8-sig", errors="replace"))
            except Exception:
                continue
            out.update({k: v for k, _o, v in items if k and isinstance(v, list)})
    return out


class Context:
    def __init__(self, world, root: str, scripted: dict[str, list] | None = None) -> None:
        self.world = world
        self.root = root
        self.scripted = scripted or {}
        self.unknown: set[str] = set()
        self._depth = 0


# scope = ("country", tag) or ("state", id); a stack of them gives PREV
def evaluate(block: list, ctx: Context, scope: tuple | None = None) -> bool | None:
    scope = scope or ("country", ctx.root)
    return _all(block, ctx, [scope])


def _and(values) -> bool | None:
    out = True
    for v in values:
        if v is False:
            return False
        if v is None:
            out = None
    return out


def _or(values) -> bool | None:
    out = False
    for v in values:
        if v is True:
            return True
        if v is None:
            out = None
    return out


def _not(v: bool | None) -> bool | None:
    return None if v is None else not v


def _all(block: list, ctx: Context, stack: list) -> bool | None:
    results = []
    chain_done = False     # an if / else_if of the chain was taken (or undecided -> None)
    chain_state: bool | None = True
    for key, op, value in block:
        if key is None or key in ("tooltip", "text", "count"):
            continue
        if key in ("if", "IF", "else_if"):
            if key != "else_if":
                chain_done, chain_state = False, True
            if chain_done:
                continue
            limit = next((v for k, _o, v in value if k == "limit"), []) if isinstance(value, list) else []
            cond = _all(limit, ctx, stack)
            body = [x for x in value if x[0] != "limit"] if isinstance(value, list) else []
            if cond is True:
                results.append(_all(body, ctx, stack))
                chain_done = True
            elif cond is None:
                results.append(None)
                chain_done, chain_state = True, None
            continue
        if key in ("else", "ELSE"):
            if not chain_done and isinstance(value, list):
                results.append(_all(value, ctx, stack))
            chain_done = True
            continue
        try:
            results.append(_one(key, op, value, ctx, stack))
        except Unknown:
            ctx.unknown.add(key)
            results.append(None)
        if results[-1] is False:
            return False
    return _and(results)


def _resolve(value, ctx: Context, stack: list) -> tuple | None:
    """A scope named by a value: TAG, ROOT, THIS, PREV, a state number, owner/controller of a state scope."""
    if not isinstance(value, str):
        return None
    v = value
    if v in ("ROOT", "root"):
        return ("country", ctx.root)
    if v in ("THIS", "this"):
        return stack[-1]
    if v in ("PREV", "prev"):
        return stack[-2] if len(stack) > 1 else None
    if v.isdigit():
        return ("state", int(v))
    if v in ("owner", "OWNER", "controller", "CONTROLLER") and stack[-1][0] == "state":
        st = ctx.world.state(stack[-1][1])
        t = st and st.get("owner" if v.lower() == "owner" else "controller")
        return ("country", t) if t else None
    if v in ("overlord", "OVERLORD") and stack[-1][0] == "country":
        t = ctx.world.overlord(stack[-1][1])
        return ("country", t) if t else ("none", None)
    if TAG_RE.fullmatch(v):
        return ("country", v)
    return None


def _num(op: str, have: float, want) -> bool | None:
    try:
        w = float(want)
    except (TypeError, ValueError):
        return None
    return {"=": have == w, ">": have > w, "<": have < w, ">=": have >= w, "<=": have <= w, "!=": have != w}.get(op)


def _yes(value) -> bool | None:
    return True if value == "yes" else False if value == "no" else None


ITERATORS = {
    "any_country": ("country", "any", False), "all_country": ("country", "all", False),
    "any_other_country": ("country", "any", True), "all_other_country": ("country", "all", True),
    "any_owned_state": ("owned", "any", False), "all_owned_state": ("owned", "all", False),
    "any_controlled_state": ("controlled", "any", False), "all_controlled_state": ("controlled", "all", False),
    "any_core_state": ("core", "any", False), "all_core_state": ("core", "all", False),
    "any_state": ("state", "any", False), "all_state": ("state", "all", False),
    "any_allied_country": ("allied", "any", True), "all_allied_country": ("allied", "all", True),
    "any_enemy_country": ("enemy", "any", True), "all_enemy_country": ("enemy", "all", True),
    "any_subject_country": ("subject", "any", True), "all_subject_country": ("subject", "all", True),
    "any_country_with_original_tag": ("original", "any", False),
    "all_country_with_original_tag": ("original", "all", False),
}


def _iterate(kind: str, block: list, ctx: Context, stack: list) -> list[tuple] | None:
    w, cur = ctx.world, stack[-1]
    tag = cur[1] if cur[0] == "country" else None
    if kind == "country":
        return [("country", t) for t in w.countries()]
    if kind == "state":
        return [("state", s) for s in w.state_ids()]
    if kind == "original":
        want = next((v for k, _o, v in block if k == "original_tag_to_check"), None)
        return [("country", want)] if isinstance(want, str) and want in w.countries() else []
    if tag is None:
        return None
    if kind in ("owned", "controlled", "core"):
        return [("state", s) for s in w.state_ids()
                if (w.state(s) or {}).get({"owned": "owner", "controlled": "controller"}.get(kind, "")) == tag
                or (kind == "core" and tag in ((w.state(s) or {}).get("cores") or []))]
    if kind == "allied":
        return [("country", t) for t in (w.faction(tag) or [])]
    if kind == "enemy":
        return [("country", t) for t in w.wars(tag)]
    if kind == "subject":
        return [("country", t) for t in w.subjects(tag)]
    return None


def _one(key: str, op: str, value, ctx: Context, stack: list) -> bool | None:
    w, cur = ctx.world, stack[-1]
    if key in ("AND", "custom_trigger_tooltip", "hidden_trigger", "custom_override_tooltip"):
        return _all(value, ctx, stack) if isinstance(value, list) else None
    if key == "OR":
        return _or(_all([x], ctx, stack) for x in value if x[0]) if isinstance(value, list) else None
    if key == "NOT":
        return _not(_or(_all([x], ctx, stack) for x in value if x[0])) if isinstance(value, list) else None
    if key == "always":
        return _yes(value)
    if key == "has_game_rule" and isinstance(value, list):
        rule = next((v for k, _o, v in value if k == "rule"), None)
        option = next((v for k, _o, v in value if k == "option"), None)
        have = w.game_rule(rule) if isinstance(rule, str) else None
        if have is None or not isinstance(option, str):
            ctx.unknown.add(key)
            return None
        return have.upper() == option.upper()
    if key in ITERATORS and isinstance(value, list):
        kind, mode, other = ITERATORS[key]
        if any(k == "count" for k, _o, _v in value):
            ctx.unknown.add(key + " (count)")
            return None
        scopes = _iterate(kind, value, ctx, stack)
        if scopes is None:
            ctx.unknown.add(key)
            return None
        if other:
            scopes = [s for s in scopes if s != cur]
        body = [x for x in value if x[0] not in ("original_tag_to_check", "limit")]
        limit = next((v for k, _o, v in value if k == "limit"), None)
        results = []
        for s in scopes:
            if limit is not None:
                ok = _all(limit, ctx, stack + [s])
                if ok is False:
                    continue
                if ok is None:
                    results.append(None)
                    continue
            results.append(_all(body, ctx, stack + [s]))
        return _or(results) if mode == "any" else _and(results)
    if isinstance(value, list):     # a scope change: TAG = { ... }, 42 = { ... }, ROOT, owner, ...
        target = _resolve(key, ctx, stack)
        if target is not None and key not in ctx.scripted:
            if target[0] == "none":
                return False
            if target[0] == "country" and target[1] not in w.countries():
                # a country that does not exist: its triggers are false (`exists = no` is the only true one)
                return _all(value, ctx, stack + [target]) if any(k == "exists" for k, _o, _v in value) else False
            return _all(value, ctx, stack + [target])

    if key in ctx.scripted and _yes(value) is not None:
        if ctx._depth > 20:
            ctx.unknown.add(key)
            return None
        ctx._depth += 1
        try:
            res = _all(ctx.scripted[key], ctx, stack)
        finally:
            ctx._depth -= 1
        return res if _yes(value) else _not(res)

    if cur[0] == "state":
        return _state_trigger(key, op, value, ctx, stack)
    if cur[0] != "country":
        ctx.unknown.add(key)
        return None
    res = _country_trigger(key, op, value, ctx, stack, cur[1])
    if res is None:
        ctx.unknown.add(key)
    return res


def _other_tag(value, ctx: Context, stack: list) -> str | None:
    s = _resolve(value, ctx, stack)
    return s[1] if s and s[0] == "country" else None


def _country_trigger(key, op, value, ctx: Context, stack: list, tag: str) -> bool | None:
    w = ctx.world
    exists = tag in w.countries()
    if key == "exists":
        return _yes(value) == exists if _yes(value) is not None else None
    if key == "country_exists":
        t = _other_tag(value, ctx, stack)
        return (t in w.countries()) if t else None
    if key == "tag":
        t = _other_tag(value, ctx, stack)
        return tag == t if t else None
    if key == "original_tag":
        t = _other_tag(value, ctx, stack)
        if not t:
            return None
        if tag == t:
            return True
        return None if re.fullmatch(r"[A-Z]\d\d", tag) else False   # dynamic tags (civil war) keep the original
    if not exists:
        return False
    if key == "has_government":
        want = value
        t = _other_tag(value, ctx, stack) if isinstance(value, str) and value.isupper() else None
        if t:
            want = w.government(t)
        have = w.government(tag)
        return None if have is None or want is None else have == want
    if key == "is_subject":
        return _yes(value) == (w.overlord(tag) is not None) if _yes(value) is not None else None
    if key == "is_subject_of":
        t = _other_tag(value, ctx, stack)
        return w.overlord(tag) == t if t else None
    if key == "has_subject":
        t = _other_tag(value, ctx, stack)
        return t in w.subjects(tag) if t else None
    if key == "num_subjects":
        return _num(op, len(w.subjects(tag)), value)
    if key == "has_war":
        return _yes(value) == bool(w.wars(tag)) if _yes(value) is not None else None
    if key == "has_war_with":
        t = _other_tag(value, ctx, stack)
        return t in w.wars(tag) if t else None
    if key == "has_completed_focus":
        return value in w.completed(tag)
    if key == "has_country_flag":
        flags = w.country_flags(tag) if hasattr(w, "country_flags") else None   # {flag: value}, None = not known
        if flags is None:
            return None
        if isinstance(value, str):
            return value in flags
        name = next((v for k, _o, v in value if k == "flag"), None) if isinstance(value, list) else None
        cmp = next(((o, v) for k, o, v in value if k == "value"), None) if isinstance(value, list) else None
        if not isinstance(name, str) or any(k in ("days", "date") for k, _o, _v in value):
            return None
        if name not in flags:
            return False
        try:
            have = float(flags[name])
        except (TypeError, ValueError):
            return None
        return True if cmp is None else _num(cmp[0], have, cmp[1])
    if key == "has_idea":
        return value in w.ideas(tag)
    if key == "has_dynamic_modifier":
        mod = next((v for k, _o, v in value if k == "modifier"), None) if isinstance(value, list) else value
        return mod in w.dynamic_modifiers(tag) if isinstance(mod, str) else None
    if key == "has_tech":
        return value in w.techs(tag)
    if key == "is_in_faction":
        return _yes(value) == bool(w.faction(tag)) if _yes(value) is not None else None
    if key == "is_in_faction_with":
        t = _other_tag(value, ctx, stack)
        return bool(t and t != tag and t in (w.faction(tag) or []))
    if key == "is_faction_leader":
        members = w.faction(tag) or []
        return _yes(value) == bool(members and members[0] == tag) if _yes(value) is not None else None
    if key == "num_faction_members":
        return _num(op, len(w.faction(tag) or []), value)
    if key == "is_ally_with":
        t = _other_tag(value, ctx, stack)
        if not t:
            return None
        return (t in (w.faction(tag) or []) and t != tag) or w.overlord(tag) == t or w.overlord(t) == tag
    if key in ("controls_state", "has_full_control_of_state", "owns_state"):
        st = w.state(int(value)) if isinstance(value, str) and value.isdigit() else None
        return None if st is None else st.get("owner" if key == "owns_state" else "controller") == tag
    if key == "is_ai":
        return _yes(value) == (tag not in w.players()) if _yes(value) is not None else None
    if key == "has_dlc":
        dlcs = w.dlcs()
        return None if dlcs is None else value in dlcs
    if key in ("has_guaranteed", "is_guaranteed_by", "has_non_aggression_pact_with", "has_military_access_to",
               "gives_military_access_to"):
        t = _other_tag(value, ctx, stack)
        if not t:
            return None
        kind, first, second = {"has_guaranteed": ("guarantee", tag, t), "is_guaranteed_by": ("guarantee", t, tag),
                               "has_non_aggression_pact_with": ("non_aggression_pact", None, None),
                               "has_military_access_to": ("military_access", None, None),
                               "gives_military_access_to": ("military_access", None, None)}[key]
        links = w.links(tag)
        if links is None:
            return None
        if first is None:
            return any(k == kind and t in (a, b) for k, a, b in links)
        return any(k == kind and (a, b) == (first, second) for k, a, b in links)
    if key == "has_opinion" and isinstance(value, list):
        t = _other_tag(next((v for k, _o, v in value if k == "target"), None), ctx, stack)
        cmp = next(((o, v) for k, o, v in value if k == "value"), None)
        have = w.opinion(tag, t) if t else None
        return None if have is None or cmp is None else _num(cmp[0], have, cmp[1])
    if key == "is_justifying_wargoal_against":
        t = _other_tag(value, ctx, stack)
        have = w.justifying(tag)
        return None if not t or have is None else t in have
    if key == "has_political_power":
        have = w.political_power(tag)
        return None if have is None else _num(op, have, value)
    if key == "has_army_manpower" and isinstance(value, list):
        cmp = next(((o, v) for k, o, v in value if k == "size"), None)
        have = w.army_manpower(tag)
        return None if have is None or cmp is None else _num(cmp[0], have, cmp[1])
    if op in ("<", ">", "<=", ">=") and key in w.ideology_names():   # party popularity: fascism > 0.5
        have = w.popularity(tag, key)
        return None if have is None else _num(op, have, value)
    if key == "num_of_factories":
        have = w.factories(tag)
        return None if have is None else _num(op, have, value)
    return None


def _state_trigger(key, op, value, ctx: Context, stack: list) -> bool | None:
    st = ctx.world.state(stack[-1][1])
    if st is None:
        ctx.unknown.add(key)
        return None
    t = _other_tag(value, ctx, stack)
    if key == "state":
        return str(stack[-1][1]) == str(value)
    if key in ("is_fully_controlled_by", "is_controlled_by"):
        return st.get("controller") == t if t else None
    if key == "is_owned_by":
        return st.get("owner") == t if t else None
    if key == "is_owned_and_controlled_by":
        return st.get("owner") == t and st.get("controller") == t if t else None
    if key == "is_core_of":
        return t in (st.get("cores") or []) if t else None
    if key == "is_claimed_by":
        return t in (st.get("claims") or []) if t else None
    ctx.unknown.add(key)
    return None
