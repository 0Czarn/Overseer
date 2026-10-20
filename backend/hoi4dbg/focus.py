"""National focus trees (game files) and a country's focus state (save), plus queue validation.

Game files: common/national_focus/*.txt of the game and the mods it runs with, merged like the game loads them
(gamefiles.merged_files: a mod's file of the same name replaces the game's; replace_path) -
`focus_tree = { id = ... focus = {...} shared_focus = X }` and top-level `shared_focus = {...}` blocks (shared
branches). A focus: id, cost (x 7 days), x/y (relative to relative_position_id), prerequisite blocks (AND between
blocks, OR inside one), mutually_exclusive, allow_branch (false = hidden with what depends on it) and
offset = { x y trigger } (moved while the trigger holds) - their triggers are evaluated by the service
(triggers.py), positions and hiding are applied by tree() / hidden().
"available" here means "prerequisites met and not excluded"; the `available` triggers are checked separately.
Save: country `focus_tree` (id) and `focus = { completed=... progress=N current=... paused=no }`.
Starting a focus: the game documents NO console command or effect that starts one (only ones that complete it
instantly, which the spec forbids), so the queue is a plan the app validates; see docs/PROGRESS.md (step F).
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from . import gamefiles, triggers
from .saves import text

DAYS_PER_COST = 7
# branches outside a tree: shared_focus, and joint_focus (taken together by a faction; TFB abdacom_shared_branch.txt)
SHARED = ("shared_focus", "joint_focus")
LOC_LINE = re.compile(r'^\s*([A-Za-z0-9_.\-]+):\d*\s*"(.*)"\s*(?:#[^"\n]*)?$', re.M)


def _strip(path: Path) -> str:
    return triggers.COMMENT.sub(lambda m: m.group(1) or "", path.read_text(encoding="utf-8-sig", errors="replace"))


def _pairs(block: list) -> list:
    """`key = value` items of a parsed block, nested blocks too. The game also takes `key { ... }` without "=" (2026-10-16,
    mod 3506850939 soviet.txt: `mutually_exclusive { focus = ... }`), which saves.text gives as a bare word and a bare
    block: joined into (key, block). Other bare items (lists of values) are dropped."""
    out, i = [], 0
    while i < len(block):
        item = block[i]
        if isinstance(item, tuple) and len(item) == 2:
            out.append((item[0], _pairs(item[1]) if _is_block(item[1]) else item[1]))
        elif isinstance(item, str) and i + 1 < len(block) and isinstance(block[i + 1], list):
            out.append((item, _pairs(block[i + 1]) if _is_block(block[i + 1]) else block[i + 1]))
            i += 1
        i += 1
    return out


def _is_block(value) -> bool:
    """A block of `key = value` items (not a list of plain values such as colours)."""
    return isinstance(value, list) and any(isinstance(x, tuple) for x in value)


def _focus(block: list) -> dict:
    block = _pairs(block)
    prereqs = [[v for k, v in item if k == "focus"] for key, item in block
               if key == "prerequisite" and isinstance(item, list)]
    exclusive = [v for key, item in block if key == "mutually_exclusive" and isinstance(item, list)
                 for k, v in item if k == "focus"]
    try:
        cost = float(text.get(block, "cost") or 10)
    except ValueError:
        cost = 10.0  # cost given as a variable/expression
    def num(key):
        try:
            return float(text.get(block, key) or 0)
        except ValueError:
            return 0.0
    icon = text.get(block, "icon")
    if isinstance(icon, list):   # conditional icons: { key = GFX_... trigger = ... } - the first one is the default
        icon = next((v for k, v in icon if k == "key" and isinstance(v, str)), None)
    return {"id": text.get(block, "id"), "days": round(cost * DAYS_PER_COST), "x": num("x"), "y": num("y"),
            "local": (num("x"), num("y")),   # relative to relative_position_id, before offsets
            "icon": icon if isinstance(icon, str) and icon.startswith("GFX_") else None,
            "relative_to": text.get(block, "relative_position_id"), "prerequisites": [p for p in prereqs if p],
            "exclusive": exclusive, "has_conditions": any(k in ("available", "bypass") for k, _ in block),
            # conditions to start it that the app cannot check (an empty available = {} has none), effects run
            # when it is picked in the game: such focuses are started by the player, not by the app
            "start_conditions": any(k == "available" and v for k, v in block),
            "select_effect": any(k == "select_effect" for k, _ in block),
            "branch_condition": any(k == "allow_branch" for k, _ in block)}


@lru_cache(maxsize=4)
def _load(files: tuple[str, ...]) -> tuple[dict, dict]:
    """(trees {id: {"focuses": [...], "shared": [...]}}, focuses {id: {...}}) - later files override."""
    trees: dict[str, dict] = {}
    focuses: dict[str, dict] = {}
    for path in files:
        try:
            items = _pairs(text.parse(_strip(Path(path))))
        except Exception:  # a broken mod file must not break the whole list
            continue
        for key, value in items:
            if not isinstance(value, list):
                continue
            if key == "focus_tree":
                tid = text.get(value, "id")
                own = [_focus(v) for k, v in value if k == "focus" and isinstance(v, list)]
                for f in own:
                    if f["id"]:
                        focuses[f["id"]] = {**f, "tree": tid}
                trees[tid] = {"focuses": [f["id"] for f in own if f["id"]],
                              "shared": [v for k, v in value if k in SHARED and isinstance(v, str)]}
            elif key in SHARED:
                f = _focus(value)
                if f["id"]:
                    focuses[f["id"]] = {**f, "tree": None, "joint": key == "joint_focus"}
    return trees, focuses


def focus_files(install: Path, mods: list[Path] | None = None) -> tuple[str, ...]:
    """common/national_focus/*.txt as the game loads them with these mods (gamefiles.merged_files)."""
    return tuple(str(f) for f in gamefiles.merged_files([install, *(mods or [])], "common/national_focus"))


def tree(files: tuple[str, ...], tree_id: str, shifts: dict | None = None,
         members: list[str] | None = None) -> list[dict]:
    """All focuses of a tree incl. shared branches, with absolute positions. `members` = the tree's focuses as the
    game loaded them (game memory); without it shared focuses are chained by prerequisites. `shifts` = {id: (dx, dy)}
    of the offsets whose trigger holds - focuses placed relative to a moved one move along."""
    trees, focuses = _load(files)
    t = trees.get(tree_id)
    if members:
        ids = [m for m in dict.fromkeys(members) if m in focuses]
    elif t is None:
        return []
    else:
        ids = list(t["focuses"]) + [s for s in t["shared"] if s in focuses]
        included = set(ids)
        changed = True
        while changed:  # shared focuses that build on already included ones
            changed = False
            for fid, f in focuses.items():
                if f["tree"] is None and fid not in included and f["prerequisites"] and \
                        all(any(p in included for p in group) for group in f["prerequisites"]):
                    ids.append(fid)
                    included.add(fid)
                    changed = True
    shifts = shifts or {}
    pos: dict[str, tuple[float, float]] = {}

    def place(fid: str, depth: int = 0) -> tuple[float, float]:
        if fid in pos:
            return pos[fid]
        f = focuses[fid]
        dx, dy = shifts.get(fid, (0, 0))
        x, y = f["local"][0] + dx, f["local"][1] + dy
        rel = f["relative_to"]
        if rel and rel in focuses and depth < 50:
            rx, ry = place(rel, depth + 1)
            x, y = x + rx, y + ry
        pos[fid] = (x, y)
        return pos[fid]
    return [{**focuses[f], "x": place(f)[0], "y": place(f)[1]} for f in ids]


def hidden(focuses: list[dict], branch: dict[str, bool | None], keep: set[str] = frozenset()) -> set[str]:
    """Focuses the game does not show: allow_branch false (`branch`; None = the app cannot tell -> shown), and the
    ones that can never be taken because every focus of one of their prerequisite groups is hidden. `keep`
    (completed, in progress) always stay - also when the state comes from a game with other mods."""
    out = {fid for fid, ok in branch.items() if ok is False} - set(keep)
    in_tree = {f["id"] for f in focuses}
    changed = True
    while changed:
        changed = False
        for f in focuses:
            if f["id"] not in out and f["id"] not in keep and any(g and all(p in out for p in g)
                                          for g in ([p for p in g if p in in_tree] for g in f["prerequisites"])):
                out.add(f["id"])
                changed = True
    return out


def loc_names(install: Path, ids: set[str], lang: str = "english", mods: tuple = ()) -> dict[str, str]:
    """Localised names for the given keys from the game and the mods (cached by root set)."""
    names = _all_loc((str(install), *map(str, mods)), lang)
    return {i: names[i] for i in ids if i in names}


@lru_cache(maxsize=2)
def _all_loc(roots: tuple[str, ...], lang: str) -> dict[str, str]:
    """Like the game: every *_l_<lang>.yml under localisation/ of each root; a mod's file with the name of an
    earlier one replaces it; otherwise the first definition of a key wins (game before mods), and files in a
    `replace` folder override everything (later mods last)."""
    files: dict[tuple[bool, str], tuple[int, Path]] = {}
    for i, root in enumerate(roots):
        folder = Path(root) / "localisation"
        found = sorted(folder.rglob(f"*l_{lang}.yml")) if i else sorted((folder / lang).rglob("*.yml"))
        for path in found:
            is_replace = "replace" in (p.lower() for p in path.relative_to(folder).parts[:-1])
            files[(is_replace, path.name.lower())] = (i, path)
    out: dict[str, str] = {}
    replace: dict[str, str] = {}
    for (is_replace, _name), (_i, path) in sorted(files.items(), key=lambda kv: (kv[1][0], kv[0][1])):
        pairs = LOC_LINE.findall(path.read_text(encoding="utf-8-sig", errors="replace"))
        if is_replace:
            replace.update(pairs)
        else:
            for key, value in pairs:
                out.setdefault(key, value)
    out.update(replace)
    return out


def save_state(block: list) -> dict:
    """{"tree", "completed", "current", "progress", "paused"} from a (named) country block."""
    focus = text.get(block, "focus") or []
    completed = [v for k, v in focus if k == "completed"] if isinstance(focus, list) else []
    try:
        progress = float(text.get(focus, "progress")) if isinstance(focus, list) and text.get(focus, "progress") else 0.0
    except ValueError:
        progress = 0.0
    flags = text.get(block, "flags")
    flags = {k: (text.get(v, "value") if isinstance(v, list) else v) for k, v in flags
             if isinstance(k, str)} if isinstance(flags, list) else {}
    return {"tree": text.get(block, "focus_tree"), "completed": completed, "flags": flags,
            "current": text.get(focus, "current") if isinstance(focus, list) else None,
            "progress": progress, "paused": (text.get(focus, "paused") if isinstance(focus, list) else None) == "yes"}


def _met(f: dict, done: set[str]) -> bool:
    return all(any(p in done for p in group) for group in f["prerequisites"])


def statuses(focuses: list[dict], state: dict) -> list[dict]:
    done = set(state["completed"])
    excluded = {e for f in focuses if f["id"] in done | {state["current"]} for e in f["exclusive"]}
    out = []
    for f in focuses:
        if f["id"] in done:
            status = "completed"
        elif f["id"] == state["current"]:
            status = "in_progress"
        elif f["id"] in excluded:
            status = "excluded"
        elif _met(f, done):
            status = "available"
        else:
            status = "blocked"
        missing = [g for g in f["prerequisites"] if not any(p in done for p in g)]
        out.append({**f, "status": status, "missing": missing,
                    "progress": min(1.0, state["progress"] / f["days"]) if status == "in_progress" and f["days"] else None})
    return out


def validate_queue(focuses: list[dict], state: dict, queue: list[str]) -> list[dict]:
    """Each queued focus: ok, or why it cannot follow (unknown, done, excluded, prerequisites not before it)."""
    by_id = {f["id"]: f for f in focuses}
    done = set(state["completed"]) | ({state["current"]} if state["current"] else set())
    taken = set(done)
    excluded = {e for fid in done if fid in by_id for e in by_id[fid]["exclusive"]}
    result = []
    for fid in queue:
        f = by_id.get(fid)
        if f is None:
            result.append({"id": fid, "ok": False, "reason": "not in this country's focus tree"})
            continue
        if fid in taken:
            result.append({"id": fid, "ok": False, "reason": "already completed, in progress or queued earlier"})
            continue
        if fid in excluded:
            result.append({"id": fid, "ok": False, "reason": "mutually exclusive with a focus taken earlier"})
            continue
        if f.get("hidden"):
            result.append({"id": fid, "ok": False, "reason": "hidden in the game (allow_branch) - it cannot be taken"})
            continue
        missing = [g for g in f["prerequisites"] if not any(p in taken for p in g)]
        if missing:
            result.append({"id": fid, "ok": False, "reason": "needs " + " and ".join(" or ".join(g) for g in missing)})
            continue
        taken.add(fid)
        excluded |= set(f["exclusive"])
        result.append({"id": fid, "ok": True, "reason": None,
                       "conditions": f["has_conditions"]})
    return result


# Layout like the game's focus screen (interface/nationalfocusview.gui: focus_spacing x = 96, y = 130): each focus is
# an icon with its name plate below; prerequisite lines go down from the parent, across just above the child and down
# into it (dashed when the parent is one of several alternatives); mutually exclusive focuses are joined by the
# game's red exclusive link.
SPACING = (96, 130)
NODE = {"w": 92, "h": 118, "icon_h": 78, "plate_top": 80, "plate_h": 34}
PAD = 24


def layout(focuses: list[dict]) -> dict:
    """{"items": [{id, left, top}], "lines": [{from, to, points, alternative}], "exclusive": [{a, b, points, at}],
    "width", "height"} in pixels."""
    if not focuses:
        return {"items": [], "lines": [], "exclusive": [], "width": 0, "height": 0}
    min_x = min(f["x"] for f in focuses)
    pos = {f["id"]: (PAD + (f["x"] - min_x) * SPACING[0], PAD + f["y"] * SPACING[1]) for f in focuses}
    cx = lambda fid: pos[fid][0] + NODE["w"] / 2  # noqa: E731
    lines = []
    for f in focuses:
        for group in f["prerequisites"]:
            for p in group:
                if p not in pos:
                    continue
                x1, y1 = cx(p), pos[p][1] + NODE["plate_top"] + NODE["plate_h"]
                x2, y2 = cx(f["id"]), pos[f["id"]][1]
                mid = y2 - 10 if y2 - 10 > y1 else (y1 + y2) / 2
                pts = [[x1, y1], [x1, mid], [x2, mid], [x2, y2]] if x1 != x2 else [[x1, y1], [x2, y2]]
                lines.append({"from": p, "to": f["id"], "points": pts, "alternative": len(group) > 1})
    exclusive, seen = [], set()
    for f in focuses:
        for e in f["exclusive"]:
            pair = tuple(sorted((f["id"], e)))
            if e not in pos or pair in seen:
                continue
            seen.add(pair)
            a, b = sorted(pair, key=lambda i: pos[i][0])
            y_a = pos[a][1] + NODE["icon_h"] / 2
            y_b = pos[b][1] + NODE["icon_h"] / 2
            pts = [[pos[a][0] + NODE["w"] - 8, y_a], [pos[b][0] + 8, y_b]]
            exclusive.append({"a": a, "b": b, "points": pts,
                              "at": [(pts[0][0] + pts[1][0]) / 2, (pts[0][1] + pts[1][1]) / 2]})
    width = max(left for left, _ in pos.values()) + NODE["w"] + PAD
    height = max(top for _, top in pos.values()) + NODE["h"] + PAD
    return {"items": [{"id": fid, "left": left, "top": top} for fid, (left, top) in pos.items()],
            "lines": lines, "exclusive": exclusive, "width": width, "height": height, "node": NODE}
