"""Construction queue as the game's construction screen shows it: building definitions from common/buildings
(icon frame in interface GFX_buildings_strip, state or province building) and the rows of a country's queue."""

from __future__ import annotations

import math
import re
from functools import lru_cache
from pathlib import Path

from .saves import text

STRIP_SPRITE = "GFX_buildings_strip"
# icons of the civilian factory tasks on the game's construction screen (interface/countryconstructionsview.gfx)
TASK_SPRITES = {"consumer_goods": "GFX_consumer_goods_icon", "market_contracts": "GFX_ongoing_market_contract_icon",
                "national_projects": "GFX_special_project_icon", "traded_goods": "GFX_traded_factories_icon"}
STRIP_RE = re.compile(r'name\s*=\s*"?' + STRIP_SPRITE + r'"?\s*texturefile\s*=\s*"([^"]+)"\s*noOfFrames\s*=\s*(\d+)', re.I)


def _strip(path: Path) -> str:
    return re.sub(r"#[^\n]*", "", path.read_text(encoding="utf-8-sig", errors="replace"))


@lru_cache(maxsize=2)
def buildings(roots: tuple[str, ...]) -> dict[str, dict]:
    """{building id: {"icon_frame": int or None, "provincial": bool (level cap per province), "shares_slots": bool (takes
    one of the state's building slots: factories, dockyards, refineries...)}}; later roots (mods) override."""
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
                    shares = isinstance(cap, list) and any(i == ("shares_slots", "yes") for i in cap if isinstance(i, tuple))
                    out[name] = {"icon_frame": int(frame) if isinstance(frame, str) and frame.isdigit() else None,
                                 "provincial": provincial, "shares_slots": shares}
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


SORT_BUILDINGS = {"civ": "industrial_complex", "mil": "arms_factory"}   # auto-sort kinds (Construction tab)


def factory_first_order(lines: list[dict], kind: str = "civ") -> list[int]:
    """New queue order (indices into `lines`): factories of `kind` ("civ" civilian, "mil" military) being built on top,
    the one closest to completion first (it gets the factories and finishes soonest), the rest below in its own order.
    Repairs and other buildings keep their relative order; equal progress keeps the current order."""
    building = SORT_BUILDINGS[kind]

    def wanted(line: dict) -> bool:
        return line["kind"] == "building" and line["building"] == building and line["levels"] > 0
    top = sorted((i for i, line in enumerate(lines) if wanted(line)),
                 key=lambda i: -(lines[i]["produced"] / lines[i]["cost"] if lines[i]["cost"] else 0))
    picked = set(top)
    return top + [i for i in range(len(lines)) if i not in picked]


def civilian_first_order(lines: list[dict]) -> list[int]:
    return factory_first_order(lines, "civ")


# -- forecast of the queue and where to build (2026-10-22, user's request) --------------------------------------
FORECAST_DAYS = 730
FORECAST_MARKS = (90, 180, 365)
FACTORY_KINDS = {"industrial_complex": "civ", "arms_factory": "mil", "dockyard": "dock"}
BASE_SPEED = 5.0   # construction points a day of one factory when no line shows the country's own speed


def forecast(lines: list[dict], free: float, counts: dict[str, int], consumer_share: float = 0.0,
             max_factories: int = 15, days: int = FORECAST_DAYS) -> dict:
    """The queue played forward day by day at today's speeds: the free civilian factories go to the lines in queue
    order (up to `max_factories` each), a line's speed per factory is its own today (else the mean of the working lines
    for the same building, else of all), a finished level of a civilian factory adds a factory less its consumer goods
    share, levels finish in turn and a finished line hands its factories to the next. Returns {"lines": [days until the
    line is done or None], "levels": [[day of each level]], "factories": {mark: {"civ", "mil", "dock"}}} - a forecast:
    new bonuses, consumer goods changes, trade and the player's changes of the queue are not known."""
    per = [(l["speed"] / l["factories"]) if l.get("factories") and l.get("speed") else None for l in lines]
    by_building: dict[str, list[float]] = {}
    for l, v in zip(lines, per):
        if v:
            by_building.setdefault(l["building"], []).append(v)
    known = [v for v in per if v]
    mean = sum(known) / len(known) if known else BASE_SPEED
    speed = [v or (sum(by_building[l["building"]]) / len(by_building[l["building"]]) if l["building"] in by_building else mean)
             for l, v in zip(lines, per)]
    left = [(l.get("levels") or 0) + (l.get("repair") or 0) for l in lines]
    done = [l.get("produced") or 0.0 for l in lines]
    finished = [0 if n <= 0 else None for n in left]
    levels: list[list[int]] = [[] for _ in lines]
    counts = dict(counts)
    marks = {}
    for day in range(1, days + 1):
        pool = free
        for i, l in enumerate(lines):
            if left[i] <= 0 or pool < 1:
                continue
            n = min(max_factories, int(pool))
            pool -= n
            done[i] += n * speed[i]
            while left[i] > 0 and l["cost"] and done[i] >= l["cost"]:
                done[i] -= l["cost"]
                left[i] -= 1
                levels[i].append(day)
                kind = FACTORY_KINDS.get(l["building"])
                if kind and (l.get("levels") or 0) >= len(levels[i]) - (l.get("repair") or 0) > 0:
                    counts[kind] = counts.get(kind, 0) + 1
                    if kind == "civ":
                        free += 1 - consumer_share
            if left[i] <= 0:
                finished[i] = day
                done[i] = 0.0
        if day in FORECAST_MARKS:
            marks[day] = dict(counts)
        if all(n <= 0 for n in left) and day >= max(FORECAST_MARKS):
            break
    for m in FORECAST_MARKS:   # an empty queue: nothing changes
        marks.setdefault(m, dict(counts))
    return {"lines": finished, "levels": levels, "factories": marks}


def state_slots(roots) -> dict[str, int]:
    """{state category: building slots} of common/state_category (game and mods, a later root wins)."""
    out: dict[str, int] = {}
    for root in map(Path, roots):
        for path in sorted((root / "common" / "state_category").glob("*.txt")):
            try:
                items = text.parse(_strip(path))
            except Exception:  # a broken mod file
                continue
            for key, block in items:
                if key != "state_categories" or not isinstance(block, list):
                    continue
                for name, body in block:
                    values = dict(i for i in body if isinstance(i, tuple)) if isinstance(body, list) else {}
                    slots = values.get("local_building_slots")
                    if isinstance(slots, str) and slots.lstrip("-").isdigit():
                        out[name] = int(slots)
    return out


def where_to_build(states: list[dict], tag: str, slots: dict[str, int], defs: dict[str, dict],
                   queued: dict[int, int] | None = None) -> list[dict]:
    """States of `tag` where a factory can go, best first: owned and controlled, free building slots = the category's
    slots - buildings sharing slots - levels already queued there (techs and state modifiers that add slots are not
    counted), then higher infrastructure (faster construction of factories), cores before other states."""
    queued = queued or {}
    out = []
    for st in states:
        if st.get("owner") != tag or st.get("controller") != tag:
            continue
        total = slots.get(st.get("category") or "")
        if total is None:
            continue
        used = sum(v for b, v in (st.get("buildings") or {}).items() if (defs.get(b) or {}).get("shares_slots"))
        free = total - used - queued.get(st["id"], 0)
        if free <= 0:
            continue
        out.append({"id": st["id"], "name": st.get("name"), "category": st.get("category"), "slots": total, "used": used,
                    "queued": queued.get(st["id"], 0), "free": free,
                    "infrastructure": (st.get("buildings") or {}).get("infrastructure", 0),
                    "core": tag in (st.get("cores") or []), "resources": st.get("resources") or {}})
    return sorted(out, key=lambda s: (-s["free"], -s["infrastructure"], not s["core"], s["id"]))
