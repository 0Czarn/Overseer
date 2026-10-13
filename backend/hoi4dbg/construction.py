"""Construction queue as the game's construction screen shows it: building definitions from common/buildings
(icon frame in interface GFX_buildings_strip, state or province building) and the rows of a country's queue."""

from __future__ import annotations

import math
import re
from functools import lru_cache
from pathlib import Path

from .saves import text

STRIP_SPRITE = "GFX_buildings_strip"
STRIP_RE = re.compile(r'name\s*=\s*"?' + STRIP_SPRITE + r'"?\s*texturefile\s*=\s*"([^"]+)"\s*noOfFrames\s*=\s*(\d+)', re.I)


def _strip(path: Path) -> str:
    return re.sub(r"#[^\n]*", "", path.read_text(encoding="utf-8-sig", errors="replace"))


@lru_cache(maxsize=2)
def buildings(roots: tuple[str, ...]) -> dict[str, dict]:
    """{building id: {"icon_frame": int or None, "provincial": bool (level cap per province)}}; later roots (mods)
    override."""
    out: dict[str, dict] = {}
    for root in map(Path, roots):
        for path in sorted((Path(root) / "common" / "buildings").glob("*.txt")):
            try:
                items = text.parse(_strip(path))
            except Exception:  # a broken mod file must not break the whole list
                continue
            for key, block in items:
                if key != "buildings" or not isinstance(block, list):
                    continue
                for name, body in block:
                    if not isinstance(body, list):
                        continue
                    values = dict(i for i in body if isinstance(i, tuple))
                    frame = values.get("icon_frame")
                    cap = values.get("level_cap")
                    provincial = isinstance(cap, list) and any(isinstance(i, tuple) and i[0] == "province_max" for i in cap)
                    out[name] = {"icon_frame": int(frame) if isinstance(frame, str) and frame.isdigit() else None,
                                 "provincial": provincial}
    return out


@lru_cache(maxsize=2)
def icon_strip(roots: tuple[str, ...]) -> tuple[str, int] | None:
    """(texture path, number of frames) of the building icon strip; later roots (mods) override."""
    found = None
    for root in map(Path, roots):
        for path in sorted((root / "interface").rglob("*.gfx")):
            m = STRIP_RE.search(path.read_text(encoding="utf-8-sig", errors="replace"))
            if m:
                found = (str(root / m.group(1).replace("\\", "/")), int(m.group(2)))
    return found


@lru_cache(maxsize=2)
def max_factories(roots: tuple[str, ...]) -> int:
    """Factories one construction line can use (defines MAX_CIV_FACTORIES_PER_LINE, 15 in 1.19.3)."""
    value = 15
    for root in map(Path, roots):
        for path in sorted((root / "common" / "defines").glob("*.lua")):
            m = re.search(r"^\s*MAX_CIV_FACTORIES_PER_LINE\s*=\s*([0-9]+)", _strip_lua(path), re.M)
            if m:
                value = int(m.group(1))
    return value


def _strip_lua(path: Path) -> str:
    return re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8-sig", errors="replace"))


MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")
MONTH_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)   # the game has no leap years


def game_date_after(today: dict, days: int) -> dict:
    """{"year", "month", "day", "text"} `days` after `today` ({"year", "day": 0-based day of the year})."""
    year, day = divmod(today["day"] + days, 365)
    year += today["year"]
    month = 0
    while day >= MONTH_DAYS[month]:
        day -= MONTH_DAYS[month]
        month += 1
    return {"year": year, "month": month + 1, "day": day + 1, "text": f"{day + 1} {MONTHS[month][:3]}, {year}"}


def action(line: dict) -> str:
    """"build", "repair" (damaged levels only, the save's amount=0 / to_repair) or "build_repair" (both)."""
    if line.get("repair") and line.get("levels"):
        return "build_repair"
    return "repair" if line.get("repair") else "build"


def rows(lines: list[dict], names: dict[str, str], state_names: dict[str, str], max_factories: int,
         today: dict | None = None, defs: dict | None = None, province_states: dict[int, int] | None = None,
         province_names: dict[int, str] | None = None) -> list[dict]:
    """Queue lines -> rows of the construction screen: building and state names (state of the province for province
    buildings and railways), build or repair, progress of the current level and when it completes at today's speed
    (the game's "Next complete": days rounded up; SOV 27 Sep 1941, 890.21 points left at 183.75 a day -> 2 Oct 1941
    as the game tooltip). A railway is named after its end provinces like the game ("Bizerte - Tunis"), a province
    without a name by its state ("Tunis - Tunisia")."""
    defs, province_states, province_names = defs or {}, province_states or {}, province_names or {}
    state_of = lambda sid: state_names.get(f"STATE_{sid}") if sid is not None else None  # noqa: E731
    out = []
    for i, line in enumerate(lines, start=1):
        location, path = line.get("location"), line.get("path") or []
        province = None
        if path:
            province = path[0]
            state = province_states.get(path[0])
        elif (defs.get(line["building"]) or {}).get("provincial"):
            province, state = location, province_states.get(location)
        else:
            state = location
        end_state = province_states.get(path[-1]) if path else None
        ends = ([province_names.get(p) or state_of(province_states.get(p)) or f"Province {p}" for p in (path[0], path[-1])]
                if path else None)
        speed = line.get("speed") or 0
        days = math.ceil((line["cost"] - line["produced"]) / speed) if speed > 0 else None
        out.append({**line, "position": i, "action": action(line),
                    "name": names.get(line["building"]) or line["building"],
                    "state": state, "province": province,
                    "state_name": state_of(state),
                    "end_state_name": state_of(end_state) if end_state != state else None,
                    "place": " - ".join(ends) if ends else None,
                    "progress": line["produced"] / line["cost"] if line["cost"] else None,
                    "max_factories": max_factories, "days_left": days,
                    "next_complete": game_date_after(today, days) if today and days is not None else None})
    return out
