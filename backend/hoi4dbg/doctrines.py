"""Doctrines from the game files (common/doctrines, 1.19): folders (land, naval, air, special forces), tracks, grand
doctrines (folder, tracks, effects, one milestone per track) and subdoctrines (track, effects, rewards). A reward
needs DEFAULT_REWARD_MASTERY (100) mastery unless it sets its own `mastery`; the thresholds add up (100, 200, ...).
The game's memory gives each country's grand doctrine and subdoctrines by their name keys (live/pointers.py)."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from .saves import text

DEFAULT_REWARD_MASTERY = 100.0
SKIP = {"available", "visible", "ai_will_do", "allowed", "effect", "logistics_company", "mastery", "on_add",
        "on_remove", "can_be_shared", "battalion_mult"}


def _strip(path: Path) -> str:
    return re.sub(r"#[^\n]*", "", path.read_text(encoding="utf-8-sig", errors="replace"))


def _parse(path: Path) -> list:
    try:
        return text.parse(_strip(path))
    except Exception:  # a broken mod file must not break the whole list
        return []


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def effects(block: list) -> tuple[dict[str, float], list[str]]:
    """({modifier: value}, [tactics enabled]) of a doctrine / reward block. Unit stats nested in a unit or category
    block become "<stat>@<unit>" (e.g. reliability@category_light_infantry)."""
    mods: dict[str, float] = {}
    tactics: list[str] = []
    for item in block if isinstance(block, list) else []:
        if not isinstance(item, tuple) or len(item) != 2:
            continue
        k, v = item
        if k in SKIP:
            continue
        if k == "enable_tactic" and isinstance(v, str):
            tactics.append(v)
        elif isinstance(v, str) and _num(v) is not None:
            mods[k] = mods.get(k, 0.0) + float(v)
        elif isinstance(v, list):   # unit / category stats
            for sub in v:
                if isinstance(sub, tuple) and len(sub) == 2 and isinstance(sub[1], str) and _num(sub[1]) is not None:
                    key = f"{sub[0]}@{k}"
                    mods[key] = mods.get(key, 0.0) + float(sub[1])
    return mods, tactics


@lru_cache(maxsize=2)
def definitions(roots: tuple[str, ...]) -> dict:
    """{"folders": [{id, name, icon}] in game order, "tracks": {id: {name, icon}}, "grand": {id: {...}},
    "subs": {id: {...}}, "by_key": {name key: id}} - later roots (mods) override."""
    folders: dict[str, dict] = {}
    tracks: dict[str, dict] = {}
    grand: dict[str, dict] = {}
    subs: dict[str, dict] = {}
    for root in map(Path, roots):
        base = root / "common" / "doctrines"
        for path in sorted((base / "folders").glob("*.txt")):
            for fid, body in _parse(path):
                if isinstance(body, list):
                    folders[fid] = {"id": fid, "name": text.get(body, "name"), "icon": text.get(body, "ledger_gfx")}
        for path in sorted((base / "tracks").glob("*.txt")):
            for tid, body in _parse(path):
                if isinstance(body, list):
                    tracks[tid] = {"id": tid, "name": text.get(body, "name"), "icon": text.get(body, "icon")}
        for path in sorted((base / "grand_doctrines").glob("*.txt")):
            for gid, body in _parse(path):
                if not isinstance(body, list):
                    continue
                mods, tactics = effects(body)
                track_ids = [v for v in (text.get(body, "tracks") or []) if isinstance(v, str)]
                milestones = [effects(m) for m in (text.get(body, "milestones") or []) if isinstance(m, list)]
                for key in ("tracks", "milestones", "folder", "name", "description", "icon", "xp_cost", "xp_type"):
                    mods.pop(key, None)
                grand[gid] = {"id": gid, "folder": text.get(body, "folder"), "name": text.get(body, "name"),
                              "desc": text.get(body, "description"), "icon": text.get(body, "icon"),
                              "xp_cost": _num(text.get(body, "xp_cost")), "tracks": track_ids,
                              "modifiers": mods, "tactics": tactics,
                              "milestones": [{"modifiers": m, "tactics": t} for m, t in milestones]}
        for path in sorted((base / "subdoctrines").rglob("*.txt")):
            for sid, body in _parse(path):
                if not isinstance(body, list):
                    continue
                mods, tactics = effects(body)
                for key in ("rewards", "track", "name", "description", "icon", "xp_cost", "xp_type"):
                    mods.pop(key, None)
                rewards, at = [], 0.0
                for rid, rbody in text.get(body, "rewards") or []:
                    if not isinstance(rbody, list):
                        continue
                    at += _num(text.get(rbody, "mastery")) or DEFAULT_REWARD_MASTERY
                    rmods, rtactics = effects(rbody)
                    rewards.append({"id": rid, "threshold": at, "modifiers": rmods, "tactics": rtactics})
                subs[sid] = {"id": sid, "track": text.get(body, "track"), "name": text.get(body, "name"),
                             "desc": text.get(body, "description"), "icon": text.get(body, "icon"),
                             "xp_cost": _num(text.get(body, "xp_cost")), "modifiers": mods, "tactics": tactics,
                             "rewards": rewards}
    by_key: dict[str, str] = {}
    for d in list(grand.values()) + list(subs.values()):
        if d["name"]:
            by_key.setdefault(d["name"], d["id"])   # variants (x and x_no_lar) share a name: the first is used
    return {"folders": list(folders.values()), "tracks": tracks, "grand": grand, "subs": subs, "by_key": by_key}


def resolve(key: str | None, defs: dict, kind: str, track: str | None = None) -> dict | None:
    """Definition of a grand doctrine / subdoctrine by the name key from game memory (a subdoctrine of `track`
    preferred when several share the name)."""
    if not key:
        return None
    pool = defs[kind]
    same = [d for d in pool.values() if d["name"] == key]
    if track:
        same = [d for d in same if d.get("track") == track] or same
    return same[0] if same else None
