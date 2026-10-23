"""IC history of a campaign, like HOI4-IC-Graphs (github.com/otti086-Org/HOI4-IC-Graphs) but from game memory instead
of a DLL injected into the game: once per game day, every existing country's IC a day on military production (MIL),
naval production (NAV) and construction (CIV) - live/pointers.read_ic - and its civilian factories, military factories
and dockyards as the game shows them (live/pointers.read_factories); the IC wasted by factories left without a
production or construction line (wasted_ic); and the IC of equipment lost in combat, to attrition and destroyed of the
enemy (live/pointers.read_combat_log - the game keeps it only for the player's country unless the combat log patch is
on, live/code_patch.py; a country without one gets as combat losses its equipment destroyed by the countries with one).

One file per campaign in <data dir>/ic-history/<id>.jsonl: a "meta" line, then one line per recorded day
{"t": day number (365-day years), "d": "1941.11.02", "c": {tag: [STORED values]}, "f": {tag: faction} (every
FACTION_EVERY days), "p": {tag: {"n": player name, "s": [subject tags]}} (the human players, every day; rows recorded
before 2026-10-16 have none)}; rows recorded before a value existed are shorter (the value is None). Days skipped at high game speed are filled when graphing (the value holds until the next sample).
A campaign continues while the player's country stays the same and the date moves on (also in a later session, up to a
month after its last day); loading an earlier save during the session cuts the days after that date (the timeline was
replayed); another country or a jump back of more than a month starts a new file, and files of earlier sessions are
never cut. History only exists for days the app was running.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from . import actions as actions_mod

POLL_SECONDS = 0.25
MAX_STEP = 30   # days between two polls that still count as the game running (more = a save was loaded)
FACTION_EVERY = 7
UNITS_FULL_EVERY = 30   # days between full rows of division positions (and of railways and buildings)
INFRA_EVERY = 3         # days between readings of railways and buildings (0.3 s; they change slowly)
FRAME_HOURS = 6         # game hours between readings of divisions, moves and battles within a day
# Fast game (2026-10-23, user's question "why is the map recorded after 1 day, sometimes after 8 or 15"): the full
# day's reading takes ~1-1.5 s, at high speed several game days pass meanwhile, so the map jumped by them. When a game
# day passes faster than the full reading takes (and that is at least FAST_MIN_COST), the full day is read every
# FAST_FULL_EVERY game days and the days between get the light reading: the map, divisions, moves and battles
# (live.frame_snapshot with_map, ~0.4 s); no readings within a day then.
FAST_FULL_EVERY = 14
FAST_MIN_COST = 0.2     # seconds
SPEED_SMOOTHING = 0.3   # weight of the newest measurement of the real seconds a game day takes
DELTA_KINDS = ("units", "infra", "front", "divs", "tmpl")
NEW_CAMPAIGN_GAP = 31   # days back that still count as a reload of the same campaign
MONTH_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)   # the game has no leap years
SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


def row_time(row: dict) -> float:
    """Time of a campaign map row in days: its day and game hour ("h", readings within a day)."""
    return row["t"] + row.get("h", 0) / 24


def day_number(date: dict) -> int:
    return date["year"] * 365 + date["day"]


def date_text(t: int) -> str:
    year, day = divmod(t, 365)
    month = 0
    while day >= MONTH_DAYS[month]:
        day -= MONTH_DAYS[month]
        month += 1
    return f"{year}.{month + 1:02d}.{day + 1:02d}"


STORED = ("mil", "nav", "civ", "fciv", "fmil", "fdock",   # order of the values in a file row
          "wmil", "wnav", "wciv",                        # IC a day wasted by idle military / naval / civilian factories
          "lcom", "latt", "lenemy",                      # IC of equipment lost in combat / to attrition / of the enemy
          "amil", "anav", "aciv",                        # factories on military / naval production lines, construction
          *("pp", "stab", "ws", "cp", "fuel",            # from 2026-10-21 (EXTRA, live/service._campaign_day)
            "divs", "bat", "cover", "sown", "sctl", "vp", "tech", "mpf", "mpa", "mpt"),
          "mpl", "mpk")                                  # from 2026-10-23: manpower lost / enemy manpower lost a day
# values recorded from 2026-10-21 (user's request): political power, stability %, war support %, command power, fuel,
# divisions, battalions, equipment coverage % of the divisions, owned / controlled states, victory points controlled,
# researched technologies, free manpower, manpower in the field, in training
EXTRA = STORED[15:30]
# manpower lost in wars a day and manpower the country's enemies lost in its wars (the game's war casualties of each
# pair of countries at war, live/pointers.read_wars) - recorded from 2026-10-23
CASUALTIES = STORED[30:]
SUMS = {"fall": ("fciv", "fmil", "fdock"), "wall": ("wmil", "wnav", "wciv"), "lall": ("lcom", "latt"),
        "mpall": ("mpf", "mpa", "mpt"), "icall": ("mil", "nav", "civ")}
# IC a day per factory working on a line (2026-10-20, user's request): IC / assigned factories - the line's efficiency,
# factory / dockyard output and construction speed bonuses, resource shortages. Groups: their IC / their factories.
# Days recorded before the assigned factories were stored (before 2026-10-20): military and naval from the wasted IC
# (wasted = idle x IC / assigned and idle = factories - assigned, so assigned = factories x IC / (IC + wasted));
# civilian ones stay unknown (free civilian factories were not stored).
RATIOS = {"pmil": ("mil", "amil", "fmil", "wmil"), "pnav": ("nav", "anav", "fdock", "wnav"), "pciv": ("civ", "aciv", None, None)}
# equipment destroyed of the enemy per equipment lost, both summed from the first known day (IC; a group: its sums)
CUM_RATIOS = {"kd": ("lenemy", "lall")}
METRICS = STORED + tuple(SUMS) + tuple(RATIOS) + tuple(CUM_RATIOS)
LEVEL_METRICS = ("fciv", "fmil", "fdock", "fall", *RATIOS, *EXTRA, "mpall", *CUM_RATIOS)   # states of a day, not flows
AVERAGES = ("stab", "ws", "cover")   # a group's value: the mean of its countries with one
LOSS_METRICS = ("lcom", "latt", "lenemy", "lall")   # only countries with a combat log have them
NO_FACTION = "Non-aligned"

# IC a day of one factory without any line to compare with (common/defines NProduction, 1.19.3): BASE_FACTORY_SPEED_MIL,
# BASE_FACTORY_SPEED_NAV, BASE_FACTORY_SPEED (construction)
BASE_SPEED = {"mil": 3.5, "nav": 2.0, "civ": 4.0}


LAUNCH_LINE = re.compile(r"\[\[ Launching ([A-Z]+)-game \]\]")


def scan_game_log(lines, state: dict | None = None) -> dict:
    """In-game state from logs/game.log lines (read in parts: pass the state back). The game writes
    "[[ Launching SINGLEPLAYER-game ]]" when a game starts from the menu (a new one or a loaded save) and
    "End RestoreDeviceObjects" when its map is shown; "Resetting game" when it goes back to the menu.
    {"n": launches seen, "pending": launched, map not shown yet, "in_game": number of the game being played or None}."""
    state = dict(state or {"n": 0, "pending": False, "in_game": None})
    for line in lines:
        if LAUNCH_LINE.search(line):
            state["n"] += 1
            state["pending"] = True
        elif "End RestoreDeviceObjects" in line and state["pending"]:
            state["pending"], state["in_game"] = False, state["n"]
        elif "Resetting game" in line:   # also "Resetting gamestate"
            state["pending"], state["in_game"] = False, None
    return state


def wasted_ic(ic: dict, idle: dict) -> dict:
    """{"wmil", "wnav", "wciv"}: IC a day the idle factories (`idle` = {"mil", "nav", "civ"} factories without a line)
    would add at the country's own average output per assigned factory that day (its efficiency and bonuses); the
    game's base factory speed when no factory of the kind is assigned."""
    out = {}
    for kind in ("mil", "nav", "civ"):
        assigned = ic["a" + kind]
        per = ic[kind] / assigned if assigned else BASE_SPEED[kind]
        out["w" + kind] = round(max(0, idle[kind]) * per, 3)
    return out


def casualty_deltas(before: dict | None, now: dict) -> dict[str, list[int]] | None:
    """{tag: [manpower lost, enemy manpower lost]} since `before` (live ic_snapshot "casualties": {tag: {enemy: (lost,
    killed)}} of the countries at war); None without an earlier reading. The game counts per war, from its start: a war
    not in `before` counts whole (it began since), a war that ended is gone; counts only grow."""
    if before is None:
        return None
    out = {}
    for tag, wars in now.items():
        old = before.get(tag, {})
        sums = [0, 0]
        for enemy, values in wars.items():
            for i, v in enumerate(values):
                sums[i] += max(0, (v or 0) - (old.get(enemy, (0, 0))[i] or 0))
        out[tag] = sums
    return out


def loss_deltas(before: dict | None, now: dict) -> dict[str, list[float | None]] | None:
    """{tag: [IC lost in combat, IC lost to attrition, IC of enemy equipment destroyed]} since `before`
    (pointers.read_combat_log: {tag: {(group, kind, record date, variant id): (units, IC of one unit, creator)}});
    None without an earlier reading (the first day after the app started or a save was loaded is unknown). Entries
    only grow; new ones (a new battle, a new country at war) count whole, ones the game dropped (older than 12 months)
    are ignored. A country without a log of its own gets [the IC of its equipment the countries with a log destroyed
    (by the creator of the equipment), None, None] - only its losses against them."""
    if before is None:
        return None
    out = {}
    inflicted: dict[str, float] = {}
    for tag, entries in now.items():
        old = before.get(tag, {})
        sums = {"combat": 0.0, "attrition": 0.0, "enemy": 0.0}
        for key, (units, cost, *creator) in entries.items():
            ic = max(0.0, units - old.get(key, (0.0,))[0]) * cost
            sums[key[1]] += ic
            if key[1] == "enemy" and creator and creator[0] and ic:
                inflicted[creator[0]] = inflicted.get(creator[0], 0.0) + ic
        out[tag] = [round(sums[k], 3) for k in ("combat", "attrition", "enemy")]
    for tag, ic in inflicted.items():
        if tag not in now:
            out[tag] = [round(ic, 3), None, None]
    return out


TAG = re.compile(r"^[A-Z0-9]{2,4}$")
MAX_WATCHED = 20
MAX_GROUPS = 30


def check_groups(data) -> dict:
    """Validated user grouping {"custom": [group names], "assign": {tag: group name or "" (non-aligned)}}."""
    if not isinstance(data, dict):
        raise ValueError("groups must be an object")
    custom = data.get("custom") or []
    assign = data.get("assign") or {}
    if not isinstance(custom, list) or not isinstance(assign, dict) or len(custom) > MAX_GROUPS or len(assign) > 2000:
        raise ValueError("groups: custom must be a list (up to 30) and assign an object")
    names = []
    for name in custom:
        if not isinstance(name, str) or not 0 < len(name.strip()) <= 40 or name.strip() == NO_FACTION:
            raise ValueError("a group name must be 1-40 characters (not 'Non-aligned')")
        if name.strip() not in names:
            names.append(name.strip())
    out = {}
    for tag, group in assign.items():
        if not isinstance(tag, str) or not TAG.match(tag) or not isinstance(group, str) or len(group) > 40:
            raise ValueError(f"bad assignment {tag!r}")
        out[tag] = group.strip()
    return {"custom": names, "assign": out}


def player_key(tag: str, info: dict) -> str:
    """A player's series name: the account name, else the country (campaigns recorded before player names)."""
    return info.get("n") or tag


def per_factory(ic, factories) -> float | None:
    """IC a day per factory on a line; None when unknown or no factory works on one."""
    return None if ic is None or not factories else round(ic / factories, 3)


def combine(values: list, metric: str) -> float | None:
    """A group's value of a day from its countries' values: the sum (unknown when one is unknown); the losses sum the
    countries with a combat log (most have none); stability, war support and coverage are the mean of the known ones."""
    known = [v for v in values if v is not None]
    if metric in AVERAGES:
        return round(sum(known) / len(known), 3) if known else None
    if metric in LOSS_METRICS:
        return round(sum(known), 3) if known else None
    return None if len(known) < len(values) else round(sum(known), 3)


def cum_ratio(t: list[int], num: list, den: list) -> list[float | None]:
    """Running sum of `num` / running sum of `den` (each day's value counts for the days until the next sample, as the
    cumulative chart); None until both are known and the denominator is above zero."""
    out, a, b = [], None, None
    for i in range(len(t)):
        w = 1 if i == 0 else t[i] - t[i - 1]
        x = num[i] if i < len(num) else None
        y = den[i] if i < len(den) else None
        if x is not None:
            a = (a or 0.0) + x * w
        if y is not None:
            b = (b or 0.0) + y * w
        out.append(round(a / b, 3) if a is not None and b else None)
    return out


def view(game: dict, metric: str, tags: list[str] | None, by_faction: bool, groups: dict | None = None,
         by_player: bool = False, subjects: bool = True) -> dict:
    """What the Game summary tab draws: the country list (latest IC a day, faction) and the day series of `metric`
    for the chosen countries, or one summed series per faction (current factions; others under NO_FACTION), or with
    `by_player` one series per human player: the player's country of that day, plus its subjects of that day when
    `subjects`. `groups` (check_groups) moves countries between factions and adds the user's own groups."""
    if metric not in METRICS:
        raise ValueError(f"metric must be one of {', '.join(METRICS)}")
    if metric in RATIOS and (by_player or by_faction):   # a group's IC per factory: its IC / its factories
        ic, assigned, _t, _w = RATIOS[metric]
        num = view(game, ic, tags, by_faction, groups, by_player, subjects)
        den = view(game, assigned, tags, by_faction, groups, by_player, subjects)
        dens = {s["key"]: s["values"] for s in den["series"]}
        for s in num["series"]:
            s["values"] = [per_factory(a, b) for a, b in zip(s["values"], dens.get(s["key"], []))]
        dvals = {p["name"]: p["value"] for p in den["players"]}
        for p in num["players"]:
            p["value"] = per_factory(p["value"], dvals.get(p["name"]))
        listing = view(game, metric, tags, False, groups)["countries"]
        num["series"].sort(key=lambda s: -(s["values"][-1] or 0) if s["values"] else 0)
        return {**num, "countries": listing}
    if metric in CUM_RATIOS and (by_player or by_faction):   # a group's ratio: its sums
        a, b = CUM_RATIOS[metric]
        num = view(game, a, tags, by_faction, groups, by_player, subjects)
        dens = {s["key"]: s["values"] for s in view(game, b, tags, by_faction, groups, by_player, subjects)["series"]}
        for s in num["series"]:
            s["values"] = cum_ratio(game["t"], s["values"], dens.get(s["key"], []))
        lasts = {s["key"]: next((v for v in reversed(s["values"]) if v is not None), None) for s in num["series"]}
        for p in num["players"]:
            p["value"] = lasts.get(p["name"])
        num["series"].sort(key=lambda s: -(lasts[s["key"]] or 0))
        return {**num, "countries": view(game, metric, tags, False, groups)["countries"]}
    countries = game["countries"]
    game_factions = game.get("factions") or {}
    groups = groups or {"custom": [], "assign": {}}
    factions = dict(game_factions)
    for tag, group in groups["assign"].items():
        if group:
            factions[tag] = group
        else:
            factions.pop(tag, None)
    last = lambda v, k: (v.get(k) or [None])[-1]  # noqa: E731
    listing = sorted(({"tag": t, "faction": factions.get(t), **{k: last(v, k) for k in METRICS}}
                      for t, v in countries.items() if any(last(v, k) for k in METRICS)),
                     key=lambda c: -(c[metric] or 0))
    series = []
    days = game.get("players") or [{} for _ in game["t"]]
    latest = days[-1] if days else {}
    players = [{"name": player_key(t, p), "tag": t, "subjects": p.get("s") or [],
                "value": last(countries.get(t, {}), metric)} for t, p in latest.items()]
    n = len(game["t"])
    column = lambda tag: countries.get(tag, {}).get(metric) or [None] * n  # noqa: E731
    if by_player:
        sums: dict[str, list] = {}
        for i, day in enumerate(days):
            members: dict[str, list] = {}
            for t, p in day.items():
                members.setdefault(player_key(t, p), []).extend([t, *(p.get("s") or [] if subjects else [])])
            for name, tags_ in members.items():
                sums.setdefault(name, [None] * n)[i] = combine([column(m)[i] for m in tags_], metric)
        order = sorted(sums, key=lambda k: -(sums[k][-1] or 0))
        series = [{"key": k, "values": sums[k]} for k in order]
        if subjects:   # the subjects' own value counts in the listing too
            for p in players:
                p["value"] = combine([last(countries.get(m, {}), metric) for m in [p["tag"], *p["subjects"]]], metric)
    elif by_faction:
        members: dict[str, list[str]] = {}
        for t in countries:
            members.setdefault(factions.get(t) or NO_FACTION, []).append(t)
        for name in groups["custom"]:   # an empty group of the user's still shows (as zero)
            members.setdefault(name, [])
        sums = {name: [combine([column(m)[i] for m in tags_], metric) if tags_ else
                       (None if metric in LOSS_METRICS or metric in AVERAGES else 0.0) for i in range(n)]
                for name, tags_ in members.items()}
        if metric in LOSS_METRICS:   # groups without any combat log are not drawn
            sums = {k: v for k, v in sums.items() if any(x is not None for x in v) or k in groups["custom"]}
        order = sorted(sums, key=lambda k: (k == NO_FACTION, -(sums[k][-1] or 0) if sums[k] else 0))
        series = [{"key": k, "values": sums[k]} for k in order]
    else:
        series = [{"key": t, "values": countries[t][metric]} for t in tags or [] if t in countries]
    for c in listing:
        c["game_faction"] = game_factions.get(c["tag"])
    return {"t": game["t"], "dates": game["dates"], "countries": listing, "series": series,
            "factions": sorted({f for f in factions.values() if f} | set(groups["custom"])),
            "custom": groups["custom"], "players": players}


STOP_AFTER = 3.0    # real seconds the game hour stands still before the time counts as stopped (paused, waiting)
SESSION_GAP = 900   # real seconds between two recorded days that start a new session (the game or the app was closed)
RANKING = (("icall", "IC a day", False), ("fall", "Factories", False), ("divs", "Divisions", False),
           ("mpall", "Manpower", False), ("tech", "Technologies", False), ("vp", "Victory points", False),
           ("sctl", "States controlled", False), ("lenemy", "Enemy equipment destroyed (IC)", True),
           ("kd", "Destroyed / lost", False))
RANK_BACK = 30   # game days back the ranking is compared with


def _last_known(values: list, upto: int | None = None):
    for v in reversed(values[:None if upto is None else upto + 1]):
        if v is not None:
            return v
    return None


def ranking(game: dict, subjects: bool = True) -> dict:
    """The human players ranked in each RANKING category (with their subjects when `subjects`): the last recorded day
    and RANK_BACK game days before - {"date", "since", "categories": [{"key", "label", "rows": [{"name", "tag",
    "value", "before", "rank", "rank_before"}]}]}; a cumulative category sums the days recorded."""
    t = game["t"]
    if not t:
        return {"date": None, "since": None, "categories": []}
    back = max((i for i, x in enumerate(t) if x <= t[-1] - RANK_BACK), default=0)   # else the first day
    tags = {player_key(tag, p): tag for tag, p in (game["players"][-1] if game["players"] else {}).items()}
    out = []
    for key, label, cumulated in RANKING:
        v = view(game, key, None, False, None, True, subjects)
        rows = []
        for s in v["series"]:
            values = s["values"]
            if cumulated:
                sums, acc = [], None
                for i, x in enumerate(values):
                    if x is not None:
                        acc = (acc or 0.0) + x * (1 if i == 0 else t[i] - t[i - 1])
                    sums.append(None if acc is None else round(acc, 1))
                values = sums
            rows.append({"name": s["key"], "tag": tags.get(s["key"]), "value": _last_known(values),
                         "before": _last_known(values, back) if back < len(t) - 1 else None})
        for field, rank in (("value", "rank"), ("before", "rank_before")):
            ordered = sorted((r for r in rows if r[field] is not None), key=lambda r: -r[field])
            for i, r in enumerate(ordered):
                r[rank] = i + 1
            for r in rows:
                r.setdefault(rank, None)
        out.append({"key": key, "label": label, "rows": sorted(rows, key=lambda r: r["rank"] or 999)})
    return {"date": date_text(t[-1]), "since": date_text(t[back]) if back < len(t) - 1 else None, "categories": out}


def sessions(game: dict) -> dict:
    """Play sessions of a campaign from the real time of each recorded day (days recorded from 2026-10-21): a new
    session after SESSION_GAP seconds without a day or when the date goes back (a save loaded). Per session: real
    start and end, game days, game days an hour, time stopped (the game hour stood still over STOP_AFTER seconds: paused
    or waiting), the players and who joined or left; per player: sessions, minutes present, countries."""
    rows = [(i, w) for i, w in enumerate(game.get("wall") or []) if w is not None]
    out, players = [], {}
    current = None
    for i, w in rows:
        day = game["t"][i]
        names = {player_key(tag, p): tag for tag, p in (game["players"][i] or {}).items()}
        if current is None or w - current["_w"] > SESSION_GAP or day < current["_t"]:
            current = {"start": w, "end": w, "first": game["dates"][i], "last": game["dates"][i], "days": 0,
                       "stopped": 0.0, "players": dict(names), "joined": [], "left": [], "_w": w, "_t": day,
                       "_names": dict(names)}
            out.append(current)
        else:
            span = w - current["_w"]
            for n in set(names) & set(current["_names"]):   # present on both days: the time in between counts
                players.setdefault(n, {"name": n, "sessions": set(), "seconds": 0.0, "countries": set()})["seconds"] += span
            for n in sorted(set(names) - set(current["_names"])):
                current["joined"].append({"name": n, "tag": names[n], "date": game["dates"][i], "at": w})
            for n in sorted(set(current["_names"]) - set(names)):
                current["left"].append({"name": n, "tag": current["_names"][n], "date": game["dates"][i], "at": w})
            current["players"].update(names)
            current["days"] += day - current["_t"]
            current["stopped"] += (game.get("still") or [0] * len(game["t"]))[i] or 0
            current.update(end=w, last=game["dates"][i], _w=w, _t=day, _names=names)
        for n, tag in names.items():
            entry = players.setdefault(n, {"name": n, "sessions": set(), "seconds": 0.0, "countries": set()})
            entry["sessions"].add(len(out))
            entry["countries"].add(tag)
    for sess in out:
        hours = (sess["end"] - sess["start"]) / 3600
        sess["minutes"] = round(hours * 60, 1)
        sess["days_per_hour"] = round(sess["days"] / hours, 1) if hours > 0 else None
        sess["stopped_minutes"] = round(sess.pop("stopped") / 60, 1)
        sess["players"] = [{"name": n, "tag": t} for n, t in sorted(sess["players"].items())]
        for k in ("_w", "_t", "_names"):
            sess.pop(k)
    summary = [{"name": p["name"], "sessions": len(p["sessions"]), "minutes": round(p["seconds"] / 60, 1),
                "countries": sorted(p["countries"])} for p in players.values()]
    return {"sessions": out, "players": sorted(summary, key=lambda p: -p["minutes"]),
            "recorded": len(rows), "days": len(game["t"])}


class IcHistory:
    """Campaign files: reading, choosing the file a new sample belongs to, appending."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.active: str | None = None
        self._lock = threading.Lock()
        self._equipment_cache: dict[str, tuple[int, list]] = {}
        self._delta_cache: dict[tuple[str, str], tuple] = {}   # (campaign, kind) -> (file stamp, rows)

    def _path(self, gid: str) -> Path:
        if not SAFE_ID.match(gid):
            raise ValueError("bad campaign id")
        return self.folder / f"{gid}.jsonl"

    def _lines(self, gid: str) -> list[dict]:
        try:
            text = self._path(gid).read_text(encoding="utf-8")
        except OSError:
            return []
        out = []
        for line in text.splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:   # a line cut by a crash
                continue
        return out

    def games(self) -> list[dict]:
        """[{"id", "player", "first", "last", "days", "active"}], newest first."""
        out = []
        for path in sorted(self.folder.glob("*.jsonl")) if self.folder.exists() else []:
            if "." in path.stem:   # <id>.actions.jsonl: a campaign's Players actions, not a campaign
                continue
            rows = self._lines(path.stem)
            meta = next((r["meta"] for r in rows if "meta" in r), {})
            days = [r for r in rows if "t" in r]
            out.append({"id": path.stem, "player": meta.get("player"), "created": meta.get("created"),
                        "campaign": meta.get("campaign"), "linked": meta.get("linked"),
                        "first": days[0]["d"] if days else None, "last": days[-1]["d"] if days else None,
                        "last_t": days[-1]["t"] if days else None, "days": len(days), "active": path.stem == self.active})
        return sorted(out, key=lambda g: g["created"] or "", reverse=True)

    def game(self, gid: str) -> dict:
        """{"id", "player", "t": [...], "dates": [...], "countries": {tag: {metric: [...]}}, "factions": {tag: faction},
        "players": [{tag: {"n", "s"}} per day]} - a missing country on a day is 0 (it did not exist); a value not
        recorded yet is None. Days without a player list take the next known one (the first days of a campaign) or the
        last one; a campaign recorded without any is the campaign's player alone."""
        rows = self._lines(gid)
        if not rows:
            raise FileNotFoundError(gid)
        meta = next((r["meta"] for r in rows if "meta" in r), {})
        days = [r for r in rows if "t" in r]
        tags = sorted({tag for r in days for tag in r["c"]})
        series = {tag: {k: [] for k in METRICS} for tag in tags}
        factions: dict[str, str] = {}
        MISSING = [None if k in AVERAGES else 0 for k in STORED]   # a country that did not exist that day
        for r in days:
            for tag in tags:
                values = r["c"].get(tag)
                row = list(values) + [None] * (len(STORED) - len(values)) if values else MISSING
                for k, v in zip(STORED, row):   # rows recorded before a value was counted have none (None)
                    series[tag][k].append(v)
                for k, parts in SUMS.items():
                    vals = [series[tag][p][-1] for p in parts]
                    series[tag][k].append(None if None in vals else round(sum(vals), 3))
                for k, (ic, assigned, total, wasted) in RATIOS.items():
                    s = series[tag]
                    older = s[assigned][-1] is None and total and None not in (s[ic][-1], s[total][-1], s[wasted][-1])
                    if older and s[ic][-1] + s[wasted][-1] > 0:   # an older day: assigned factories from the wasted IC
                        s[assigned][-1] = round(s[total][-1] * s[ic][-1] / (s[ic][-1] + s[wasted][-1]), 3)
                    s[k].append(per_factory(s[ic][-1], s[assigned][-1]))
            if "f" in r:
                factions = r["f"]
        t = [r["t"] for r in days]
        for tag in tags:
            for k, (a, b) in CUM_RATIOS.items():
                series[tag][k] = cum_ratio(t, series[tag][a], series[tag][b])
        known = [r.get("p") for r in days]
        first = next((p for p in known if p), None) or (
            {meta["player"]: {"n": None, "s": []}} if meta.get("player") else {})
        players, current = [], first
        for p in known:
            current = p or current
            players.append(current)
        return {"id": gid, "player": meta.get("player"), "t": [r["t"] for r in days], "dates": [r["d"] for r in days],
                "countries": series, "factions": factions, "players": players,
                "wall": [r.get("w") for r in days], "still": [r.get("s") for r in days]}

    def groups(self, gid: str) -> dict:
        """The user's grouping of a campaign (check_groups), empty when none was saved."""
        try:
            return check_groups(json.loads((self.folder / f"{gid}.groups.json").read_text(encoding="utf-8")))                 if SAFE_ID.match(gid) else {"custom": [], "assign": {}}
        except (OSError, ValueError):
            return {"custom": [], "assign": {}}

    def set_groups(self, gid: str, data) -> dict:
        if not self._path(gid).exists():
            raise FileNotFoundError(gid)
        groups = check_groups(data)
        (self.folder / f"{gid}.groups.json").write_text(json.dumps(groups, indent=1), encoding="utf-8")
        return groups

    def delete(self, gid: str) -> None:
        """Removes a campaign and its grouping; the one being recorded stays (the recorder appends to it)."""
        with self._lock:
            path = self._path(gid)
            if not path.exists():
                raise FileNotFoundError(gid)
            if gid == self.active:
                raise ValueError("This campaign is being recorded now - it can be deleted once another game runs")
            path.unlink()
            (self.folder / f"{gid}.groups.json").unlink(missing_ok=True)
            (self.folder / f"{gid}.designs.json").unlink(missing_ok=True)
            (self.folder / f"{gid}.actions.jsonl").unlink(missing_ok=True)
            (self.folder / f"{gid}.equipment.jsonl").unlink(missing_ok=True)
            (self.folder / f"{gid}.map.jsonl").unlink(missing_ok=True)
            for kind in DELTA_KINDS:
                (self.folder / f"{gid}.{kind}.jsonl").unlink(missing_ok=True)
            (self.folder / f"{gid}.notes.json").unlink(missing_ok=True)

    def _choose(self, player: str, t: int, campaign: str | None = None) -> str:
        """The campaign file a sample of `player` at day `t` of the game's campaign id `campaign` belongs to (cutting
        replayed days). With the id every save of a campaign is recognised, however far its date; without it (another
        game version) a date at most NEW_CAMPAIGN_GAP days from the last recorded one of the same country is guessed
        to continue it. The user's request (request()) goes first."""
        pending, self.pending = self.pending, None
        if pending:
            gid = pending.get("continue")
            if gid and self._path(gid).exists():
                self._continue(gid, t, player=player, campaign=campaign, linked=datetime.now().isoformat(" ", "microseconds"))
                self.how = "chosen manually"
                return gid
            return self._new(player, t, campaign, "new recording started manually")
        games = [g for g in self.games() if g["player"] == player]
        if campaign:
            same = sorted((g for g in games if g["campaign"] == campaign),   # the current file, else the newest one
                          key=lambda g: (g["id"] == self.active, max(g["created"] or "", g["linked"] or "")), reverse=True)
            if same:
                self._continue(same[0]["id"], t)
                self.how = "recognised by the campaign id"
                return same[0]["id"]
            games = [g for g in games if g["id"] == self.active and not g["campaign"]]   # recorded before the id was read
        candidates = [g for g in games if g["last_t"] is not None and not (campaign and g["campaign"])]
        if self.active:
            candidates.sort(key=lambda g: g["id"] != self.active)   # the current file first
        for g in candidates:
            # only the file of this session is cut: an older campaign of the same country is never touched
            if g["last_t"] < t <= g["last_t"] + NEW_CAMPAIGN_GAP or (
                    g["id"] == self.active and t <= g["last_t"] and g["last_t"] - t <= NEW_CAMPAIGN_GAP):
                self._continue(g["id"], t, campaign=campaign)
                self.how = "continued by the date (no campaign id)"
                return g["id"]
        return self._new(player, t, campaign, "new campaign" if campaign else "new campaign (no campaign id)")

    def _new(self, player: str, t: int, campaign: str | None, how: str) -> str:
        gid = base = f"{player}_{date_text(t).replace('.', '-')}_{time.strftime('%Y%m%d-%H%M%S')}"
        n = 1
        while self._path(gid).exists():   # two new files within a second
            n += 1
            gid = f"{base}-{n}"
        self.folder.mkdir(parents=True, exist_ok=True)
        meta = {"player": player, "created": time.strftime("%Y-%m-%d %H:%M:%S"), "start": date_text(t),
                "linked": datetime.now().isoformat(" ", "microseconds")}   # the order of the files of one campaign
        if campaign:
            meta["campaign"] = campaign
        self._path(gid).write_text(json.dumps({"meta": meta}) + "\n", encoding="utf-8")
        self.how = how
        return gid

    def _continue(self, gid: str, t: int, **meta) -> None:
        """Appending to `gid` from day `t` on: later recorded days are cut, `meta` values (if not None) noted."""
        rows = self._lines(gid)
        if any("t" in r and r["t"] >= t for r in rows):
            self._cut(gid, t)
            rows = self._lines(gid)
        meta = {k: v for k, v in meta.items() if v is not None}
        head = next((r["meta"] for r in rows if "meta" in r), None)
        if meta and head is not None and any(head.get(k) != v for k, v in meta.items()):
            head.update(meta)
            self._path(gid).write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows),
                                       encoding="utf-8")

    def request(self, gid: str | None) -> None:
        """The user's choice for the next recorded day: None = a new campaign file, else continue `gid` (the days
        recorded from that day on are cut, the campaign id is noted so that the game is recognised later)."""
        if gid is not None and not self._path(gid).exists():
            raise FileNotFoundError(gid)
        with self._lock:
            self.pending = {"continue": gid}

    def cancel_request(self) -> None:
        with self._lock:
            self.pending = None

    def _cut(self, gid: str, t: int) -> None:
        rows = [r for r in self._lines(gid) if "t" not in r or r["t"] < t]
        self._path(gid).write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows), encoding="utf-8")
        events = self.actions(gid)   # actions of replayed days did not happen in this timeline
        if any(e["t"] >= t for e in events):
            self._actions_path(gid).write_text("".join(json.dumps(e, separators=(",", ":")) + "\n" for e in events
                                                       if e["t"] < t), encoding="utf-8")
        lines = self._equipment_lines(gid)   # equipment of replayed days
        if any(r["t"] >= t for r in lines):
            self._equipment_path(gid).write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in lines
                                                         if r["t"] < t), encoding="utf-8")
        lines = self.map_rows(gid)   # states of replayed days (the rows before stay valid: each holds the changes)
        if any(r["t"] >= t for r in lines):
            self._map_path(gid).write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in lines
                                                   if r["t"] < t), encoding="utf-8")
        for kind in DELTA_KINDS:   # division positions, railways of replayed days (the recorder starts a full row next)
            lines = self.delta_rows(kind, gid)
            if any(r["t"] >= t for r in lines):
                self._delta_path(gid, kind).write_text("".join(json.dumps(r, separators=(",", ":")) + "\n"
                                                               for r in lines if r["t"] < t), encoding="utf-8")
        seen = self.designs(gid)   # designs first seen on a replayed day: the game may give their ids to new ones
        kept = {tag: {i: v for i, v in ids.items() if v[1] or v[0] < t} for tag, ids in seen.items()}
        if kept != seen:
            self._designs_path(gid).write_text(json.dumps(kept, separators=(",", ":")), encoding="utf-8")

    # -- equipment of every country by day (Game summary equipment chart): <id>.equipment.jsonl, one line a day
    # {"t": day, "e": {tag: {archetype: [needed, in divisions, stockpile, produced a day]}}} (live/service._equipment_day)
    def _equipment_path(self, gid: str) -> Path:
        self._path(gid)   # checks the id
        return self.folder / f"{gid}.equipment.jsonl"

    def add_equipment(self, gid: str, t: int, data: dict) -> None:
        with self._equipment_path(gid).open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": t, "e": data}, separators=(",", ":")) + "\n")

    def _equipment_lines(self, gid: str) -> list[dict]:
        """The days of the equipment file, read once and then only the lines appended since (a cut file is re-read)."""
        path = self._equipment_path(gid)
        try:
            size = path.stat().st_size
        except OSError:
            return []
        cache = self._equipment_cache.get(gid)
        if cache is None or size < cache[0]:
            cache = (0, [])
        offset, rows = cache
        if size > offset:
            with path.open("rb") as f:
                f.seek(offset)
                chunk = f.read(size - offset)
            end = chunk.rfind(b"\n") + 1    # a line being written stays for the next reading
            for line in chunk[:end].splitlines():
                try:
                    rows.append(json.loads(line))
                except ValueError:   # a line cut by a crash
                    continue
            offset += end
        self._equipment_cache[gid] = (offset, rows)
        return rows

    def equipment(self, gid: str, tags: list[str], archetype: str | None) -> dict:
        """{"t", "dates", "archetypes": {archetype: last needed + in divisions + stockpile of the chosen countries},
        "series": {"needed", "held", "stockpile", "produced": [...]}} - the chosen countries summed, `archetype` (default:
        the one with the most of it); a day without the file's line for a country counts 0."""
        rows = self._equipment_lines(gid)
        totals: dict[str, float] = {}
        for r in rows[-1:]:
            for tag in tags:
                for a, v in (r["e"].get(tag) or {}).items():
                    totals[a] = totals.get(a, 0) + v[0] + v[1] + v[2]
        for r in rows:   # archetypes that existed earlier only
            for tag in tags:
                for a in r["e"].get(tag) or {}:
                    totals.setdefault(a, 0)
        chosen = archetype if archetype in totals else max(totals, key=lambda a: totals[a], default=None)
        series = {k: [] for k in ("needed", "held", "stockpile", "produced")}
        for r in rows:
            sums = [0.0, 0.0, 0.0, 0.0]
            for tag in tags:
                v = (r["e"].get(tag) or {}).get(chosen)
                if v:
                    sums = [a + b for a, b in zip(sums, v)]
            for k, x in zip(series, sums):
                series[k].append(round(x, 2))
        last: dict[str, list[float]] = {}   # every archetype on the last day: the production forecast
        for r in rows[-1:]:
            for tag in tags:
                for a, v in (r["e"].get(tag) or {}).items():
                    last[a] = [round(x + y, 2) for x, y in zip(last.get(a, [0.0, 0.0, 0.0, 0.0]), v)]
        return {"t": [r["t"] for r in rows], "dates": [date_text(r["t"]) for r in rows], "archetype": chosen,
                "archetypes": dict(sorted(totals.items(), key=lambda kv: -kv[1])), "series": series, "last": last}

    # -- campaign map (2026-10-21): <id>.map.jsonl, one line a day {"t", "s": {state id: [owner, controller]}} with the
    # states changed since the line before; "full": 1 = every state (the first day the recorder writes into the file)
    def _map_path(self, gid: str) -> Path:
        self._path(gid)   # checks the id
        return self.folder / f"{gid}.map.jsonl"

    def add_map(self, gid: str, t: int, states: dict, full: bool, provinces: dict | None = None) -> None:
        """A map row {"t", "s": {state: [owner, controller]} (all or the changes), "full": 1 for all, "x": {province:
        controller} all provinces off their state's controller - only when they changed}."""
        row = {"t": t, "s": {str(k): v for k, v in states.items()}}
        if full:
            row["full"] = 1
        if provinces is not None:
            row["x"] = {str(k): v for k, v in provinces.items()}
        with self._map_path(gid).open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")

    # -- campaign map, <id>.<kind>.jsonl rows {"t", "full": 1 | absent, "u": {key: value or null}} - every key in a full
    # row, else the keys that changed (null: gone); "h": the game hour when not the day's first reading (FRAME_HOURS).
    # "units": division positions {province: {tag: [divisions, mean organisation, mean strength, {template:
    # divisions}]}}; "infra" (2026-10-23): {"r<a>-<b>": railway level, "b<province>": [supply hub, naval base, land
    # fort, coastal fort levels]}; "front" (2026-10-23): {"m<from>-<to>": {tag: divisions moving / attacking},
    # "c<province>": [attacker, defender, attacking divisions, defending divisions, attacker share in %]}; "divs"
    # (2026-10-23): each division (live division_rows: n name, p position, s stats, e equipment - positions every
    # FRAME_HOURS, the rest daily); "tmpl": {"<tag>|<template>": {"b", "s", "r" sub-units, "g" designer grid, "i"
    # icon}} of the templates in use
    def _delta_path(self, gid: str, kind: str) -> Path:
        self._path(gid)   # checks the id
        if kind not in DELTA_KINDS:
            raise ValueError(f"Unknown campaign map file {kind}")
        return self.folder / f"{gid}.{kind}.jsonl"

    def add_delta(self, kind: str, gid: str, t: int, values: dict, full: bool, hour: int = 0) -> None:
        row = {"t": t, "u": values}
        if hour:
            row["h"] = hour
        if full:
            row["full"] = 1
        with self._delta_path(gid, kind).open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")

    def add_units(self, gid: str, t: int, units: dict, full: bool, hour: int = 0) -> None:
        self.add_delta("units", gid, t, units, full, hour)

    def units_rows(self, gid: str) -> list[dict]:
        return self.delta_rows("units", gid)

    def delta_rows(self, kind: str, gid: str) -> list[dict]:
        """The rows of a campaign map file (read again only when the file changed; the list is shared - not to be
        changed)."""
        path = self._delta_path(gid, kind)
        try:
            st = path.stat()
        except OSError:
            return []
        stamp = (st.st_mtime_ns, st.st_size)
        cached = self._delta_cache.get((gid, kind))
        if cached and cached[0] == stamp:
            return cached[1]
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return []
        out = []
        for line in text.splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:   # a line cut by a crash
                continue
        if len(self._delta_cache) > 8:
            self._delta_cache.clear()
        self._delta_cache[(gid, kind)] = (stamp, out)
        return out

    def delta_at(self, kind: str, gid: str, t: float) -> dict:
        """{key: value} of a campaign map file at time `t` (days, row_time): the last full row on or before it and the
        changes after it (null: gone)."""
        rows = self.delta_rows(kind, gid)
        last = -1
        for i, r in enumerate(rows):
            if row_time(r) > t:
                break
            last = i
        start = next((i for i in range(last, -1, -1) if rows[i].get("full")), 0)
        out: dict = {}
        for r in rows[start:last + 1]:
            for k, v in r["u"].items():
                if v is None:
                    out.pop(k, None)
                else:
                    out[k] = v
        return out

    def key_history(self, kind: str, gid: str, keys: list[str]) -> list[list]:
        """[[time, key's first letter, value or None]] of `keys` in a campaign map file, each change once (full rows
        repeat what did not change)."""
        out, last = [], {}
        for r in self.delta_rows(kind, gid):
            u = r["u"]
            for k in keys:
                if k in u:
                    v = u[k]
                elif r.get("full") and k in last and last[k] is not None:
                    v = None   # a full row without it: gone
                else:
                    continue
                if last.get(k, "missing") != v:
                    out.append([row_time(r), k[0], v])
                    last[k] = v
        return out

    def faction_rows(self, gid: str) -> list[list]:
        """[[day, {tag: faction}]] of the days the factions were recorded on (every FACTION_EVERY days)."""
        return [[r["t"], r["f"]] for r in self._lines(gid) if "t" in r and r.get("f") is not None]

    def map_rows(self, gid: str) -> list[dict]:
        try:
            text = self._map_path(gid).read_text(encoding="utf-8")
        except OSError:
            return []
        out = []
        for line in text.splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:   # a line cut by a crash
                continue
        return out

    def map_states(self, gid: str, t: int | None = None) -> dict[str, list]:
        """{state id: [owner, controller]} on day `t` (default: the last recorded one)."""
        states: dict[str, list] = {}
        for r in self.map_rows(gid):
            if t is not None and r["t"] > t:
                break
            if r.get("full"):
                states = {}
            states.update(r["s"])
        return states

    # -- the user's notes on the timeline (2026-10-21): <id>.notes.json = [{"id", "t", "text", "created"}]
    def _notes_path(self, gid: str) -> Path:
        self._path(gid)   # checks the id
        return self.folder / f"{gid}.notes.json"

    def notes(self, gid: str) -> list[dict]:
        try:
            data = json.loads(self._notes_path(gid).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return sorted((n for n in data if isinstance(n, dict) and isinstance(n.get("t"), int)), key=lambda n: (n["t"], n["id"]))

    def set_note(self, gid: str, t: int, text: str, nid: int | None = None) -> list[dict]:
        """Adds a note (nid None) or changes note `nid`; an empty text deletes it."""
        if not self._path(gid).exists():
            raise FileNotFoundError(gid)
        if not isinstance(t, int) or not 0 <= t < 10_000 * 365 or not isinstance(text, str) or len(text) > 2000:
            raise ValueError("a note needs a game day and a text of at most 2000 characters")
        with self._lock:
            notes = self.notes(gid)
            text = text.strip()
            if nid is None:
                if not text:
                    raise ValueError("the note is empty")
                if len(notes) >= 500:
                    raise ValueError("at most 500 notes a campaign")
                notes.append({"id": max((n["id"] for n in notes), default=0) + 1, "t": t, "text": text,
                              "created": time.strftime("%Y-%m-%d %H:%M:%S")})
            else:
                note = next((n for n in notes if n["id"] == nid), None)
                if note is None:
                    raise FileNotFoundError(f"note {nid}")
                if text:
                    note.update(t=t, text=text)
                else:
                    notes.remove(note)
            self._notes_path(gid).write_text(json.dumps(notes, indent=1), encoding="utf-8")
            return self.notes(gid)

    # -- Players actions (actions.py): the watched countries and the events of each campaign --
    def _actions_path(self, gid: str) -> Path:
        self._path(gid)   # checks the id
        return self.folder / f"{gid}.actions.jsonl"

    def actions(self, gid: str | None) -> list[dict]:
        """Events of a campaign in the order they were recorded."""
        try:
            text = self._actions_path(gid).read_text(encoding="utf-8") if gid else ""
        except OSError:
            return []
        out = []
        for line in text.splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:   # a line cut by a crash
                continue
        return out

    def add_actions(self, gid: str, events: list[dict]) -> None:
        with self._actions_path(gid).open("a", encoding="utf-8") as f:
            f.write("".join(json.dumps(e, separators=(",", ":")) + "\n" for e in events))

    def watched(self) -> list[str]:
        """Countries watched for Players actions besides the player (all campaigns)."""
        try:
            tags = json.loads((self.folder / "actions-watch.json").read_text(encoding="utf-8")).get("tags", [])
        except (OSError, ValueError, AttributeError):
            return []
        return [t for t in tags if isinstance(t, str) and TAG.match(t)][:MAX_WATCHED]

    def set_watched(self, tags) -> list[str]:
        if not isinstance(tags, list) or not all(isinstance(t, str) and TAG.match(t) for t in tags):
            raise ValueError("tags must be a list of country tags")
        tags = sorted(set(tags))[:MAX_WATCHED]
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / "actions-watch.json").write_text(json.dumps({"tags": tags}), encoding="utf-8")
        return tags

    # -- the day a plane design was first seen (the game keeps no creation date, live/pointers.read_plane_designs) --
    def _designs_path(self, gid: str) -> Path:
        self._path(gid)   # checks the id
        return self.folder / f"{gid}.designs.json"

    def designs(self, gid: str | None) -> dict[str, dict[str, list]]:
        """{tag: {equipment id: [day number, before]}} - before = it already existed when the recording began."""
        try:
            return json.loads(self._designs_path(gid).read_text(encoding="utf-8")) if gid else {}
        except (OSError, ValueError):
            return {}

    def note_designs(self, gid: str, t: int, ids: dict[str, list[int]]) -> None:
        """Notes the designs not seen before in the campaign; on its first reading all of them as existing before."""
        path = self._designs_path(gid)
        first = not path.exists()
        seen = self.designs(gid)
        changed = first
        for tag, vids in ids.items():
            known = seen.setdefault(tag, {})
            for vid in vids:
                if str(vid) not in known:
                    known[str(vid)] = [t, first]
                    changed = True
        if changed:
            path.write_text(json.dumps(seen, separators=(",", ":")), encoding="utf-8")

    def add(self, sample: dict) -> str:
        """Appends {"t", "player", "countries", "factions"?} and returns the campaign id."""
        with self._lock:
            campaign = sample.get("campaign")
            if (self.active is None or sample["t"] <= self._last_t or sample["player"] != self._player
                    or campaign != self._campaign or self.pending):
                self.active = self._choose(sample["player"], sample["t"], campaign)
                self.campaign = campaign
            row = {"t": sample["t"], "d": date_text(sample["t"]), "c": sample["countries"]}
            if sample.get("factions") is not None:
                row["f"] = sample["factions"]
            if sample.get("players"):
                row["p"] = sample["players"]
            if sample.get("wall") is not None:   # the real time of the day (session statistics, from 2026-10-21)
                row["w"] = sample["wall"]
                row["s"] = sample.get("still", 0)
            with self._path(self.active).open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, separators=(",", ":")) + "\n")
            self._last_t, self._player, self._campaign = sample["t"], sample["player"], campaign
            return self.active

    _last_t = -1
    _player: str | None = None
    _campaign: str | None = None
    campaign: str | None = None   # the game's campaign id of the file being recorded
    how: str | None = None        # how that file was chosen (_choose)
    pending: dict | None = None   # the user's request for the next day (request)


class IcRecorder:
    """Background thread: polls the game date and records a sample when a new day starts."""

    def __init__(self, live, history: IcHistory, log, actions=None) -> None:
        self.live, self.history, self.log = live, history, log
        self.last_t: int | None = None   # last recorded day
        self.seen_t: int | None = None   # day of the previous poll
        self.error: str | None = None
        self._stop = threading.Event()
        self._last_faction_t = -FACTION_EVERY
        self._losses: dict | None = None   # combat log of the last recorded day (loss_deltas)
        self._casualties: dict | None = None   # war casualties of the last recorded day (casualty_deltas)
        self.actions = actions             # tags -> {tag: snapshot} (Players actions), None = off
        self._snaps: dict[str, dict] = {}  # last snapshot per watched country
        self._snaps_gid: str | None = None
        self._chosen: tuple | None = None   # (file, how it was chosen) last logged
        self._launch_done: str | None = None   # the game start (game.log) whose loaded day is recorded
        self._map_last: dict | None = None   # states of the last day written to the map file
        self._map_gid: str | None = None
        self._prov_last: dict | None = None   # provinces off their state's controller, last written
        self._units_last: dict | None = None  # division positions of the last day written (add_units)
        self._units_gid: str | None = None
        self._units_full_t = -UNITS_FULL_EVERY
        self._infra: dict = {"last": None, "gid": None, "full_t": -UNITS_FULL_EVERY}   # railways, buildings written
        self._last_infra_t = -INFRA_EVERY
        self._front: dict = {"last": None, "gid": None, "full_t": -UNITS_FULL_EVERY}   # moves and battles written
        self._divs: dict = {"last": None, "gid": None, "full_t": -UNITS_FULL_EVERY}    # each division written
        self._tmpl: dict = {"last": None, "gid": None, "full_t": -UNITS_FULL_EVERY}    # templates written
        self._frame: tuple | None = None   # (campaign, game hour) of the last reading of divisions
        self._hour: int | None = None        # game hour of the last poll and since when (real time) it stands
        self._hour_since: float | None = None
        self._still = 0.0                    # real seconds stopped since the last recorded day
        self._gid: str | None = None         # file of the last full day
        self._light_t: int | None = None     # day of the last light reading (fast game)
        self._full_cost: float | None = None   # real seconds the last full day's reading took
        self._day_seconds: float | None = None   # real seconds a game day takes (smoothed, while the game runs)
        self._speed_mark: tuple | None = None    # (game hour, real time) the hour last moved on
        self._fast_logged: bool | None = None
        self.wall = time.time
        self.monotonic = time.monotonic

    def start(self) -> None:
        threading.Thread(target=self._run, name="ic-recorder", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def status(self) -> dict:
        h = self.history
        return {"recording": h.active, "last": date_text(self.last_t) if self.last_t is not None else None,
                "error": self.error, "campaign": h.campaign, "how": h.how,
                "pending": None if h.pending is None else (h.pending.get("continue") or "new")}

    def step(self) -> bool:
        """One poll: records when a game day has passed; True when a sample was written. Only a date moving forward by
        1..MAX_STEP days counts: the main menu and the country selection screen hold a 1936.01.01 game state with the
        hovered country as player, and loading a save jumps the date - neither is a played day. Except the day a game
        starts on (2026-10-20, user's request): once game.log says the game left the menu (live.game_launch), that
        day is recorded right away, once per game start."""
        hours = self.live.game_hours() if hasattr(self.live, "game_hours") else None
        t = hours // 24 if hours is not None else self.live.game_day()
        self._track_stops(hours)
        self._track_speed(hours)
        previous, self.seen_t = self.seen_t, t
        if t is not None and t != previous:   # a game started since the user turned it on gets it too
            self.live.ensure_combat_log_patch()
        if t is not None and t == previous and t in (self.last_t, self._light_t) and hours is not None:
            if not self.fast():
                self._step_frame(hours)
            return False
        if (t is not None and previous is not None and 0 < t - previous <= MAX_STEP and self.fast()
                and self.last_t is not None and 0 < t - self.last_t < FAST_FULL_EVERY and self._light(t)):
            return False
        launch = None
        if t is None or previous is None or not 0 < t - previous <= MAX_STEP:
            if t != previous:   # another game state: its combat log and snapshots do not continue the last ones
                self._losses = None
                self._casualties = None
                self._snaps = {}
                self._map_last = None
                self._units_last = None
                self._infra["last"] = None
                self._front["last"] = None
                self._divs["last"] = None
                self._tmpl["last"] = None
                self._frame = None
                self._light_t = None
                self._last_infra_t = -INFRA_EVERY
            # a game just started on a country (game.log, not the menu's state): its first day is recorded at once
            launch = self._new_launch()
            if t is None or launch is None:
                return False
        with_factions = t - self._last_faction_t >= FACTION_EVERY or self.last_t is None or t < self.last_t
        with_infra = t - self._last_infra_t >= INFRA_EVERY or t < self._last_infra_t
        began = self.monotonic()
        sample = self.live.ic_snapshot(with_factions, with_infra)
        self._full_cost = self.monotonic() - began
        if sample["t"] != t:   # the day moved on while reading: take it next time
            self.seen_t = previous
            return False
        if not any(any(v) for v in sample["countries"].values()):   # production not set up yet (loading)
            return False
        losses = sample.pop("losses", None)
        assigned = sample.pop("assigned", None) or {}
        if losses is not None:
            deltas = loss_deltas(self._losses, losses)
            days = max(1, t - self.last_t) if self.last_t is not None else 1
            for tag, values in sample["countries"].items():   # a day's average over skipped days; None = not known
                if deltas and tag in deltas:
                    values.extend(None if v is None else round(v / days, 3) for v in deltas[tag])
                else:
                    values.extend([None, None, None])
            self._losses = losses
        extra = sample.pop("extra", None) or {}
        casualties = sample.pop("casualties", None)
        lost = casualty_deltas(self._casualties, casualties) if casualties is not None else None
        self._casualties = casualties
        days = max(1, t - self.last_t) if self.last_t is not None else 1
        for tag, values in sample["countries"].items():   # after the losses (None when not read): assigned factories
            values.extend([None] * (12 - len(values)))
            values.extend(assigned.get(tag) or [None, None, None])
            values.extend(extra.get(tag) or [None] * len(EXTRA))
            values.extend([None, None] if lost is None else [round(v / days, 1) for v in lost.get(tag, (0, 0))])
        control = sample.pop("map", None)
        units = sample.pop("units", None)
        infra = sample.pop("infra", None)
        front = sample.pop("front", None)
        divs = sample.pop("divs", None)
        templates = sample.pop("templates", None)
        hour = sample.pop("hour", 0) or 0
        sample["wall"], sample["still"] = int(self.wall()), round(self._still)
        self._still = 0.0
        designs = sample.pop("designs", None)
        equipment = sample.pop("equipment", None)
        gid = self.history.add(sample)
        self._gid = gid
        if (gid, self.history.how) != self._chosen:
            self._chosen = (gid, self.history.how)
            self.log.info("IC recorder: %s (game id %s) - %s", gid, sample.get("campaign") or "not readable",
                          self.history.how)
        if designs is not None:
            self.history.note_designs(gid, t, designs)
        if equipment:
            self.history.add_equipment(gid, t, equipment)
        if control:
            self._record_map(gid, t, control)
        if units is not None:
            self._record_units(gid, t, units, hour)
            self._frame = (gid, t * 24 + hour)
        if front is not None:
            self._record_delta("front", self._front, gid, t, front, hour)
        if divs is not None:
            self._record_delta("divs", self._divs, gid, t, divs, hour)
        if templates is not None:
            self._record_delta("tmpl", self._tmpl, gid, t, templates, hour)
        if infra is not None:
            flat = {f"r{k}": v for k, v in infra.get("r", {}).items()}
            flat.update({f"b{k}": v for k, v in infra.get("b", {}).items()})
            self._record_delta("infra", self._infra, gid, t, flat)
        if with_infra:
            self._last_infra_t = t
        if self.actions is not None:
            self._record_actions(gid, t, sample.get("player"))
        if with_factions:
            self._last_faction_t = t
        if launch is not None:
            self._launch_done = launch
        self.last_t = t
        return True

    def _track_stops(self, hours: int | None) -> None:
        """Real time the game hour stood still over STOP_AFTER seconds (paused or waiting for a player) - counted once
        the hour moves on; the menu (no readable date) does not count."""
        now = self.monotonic()
        if hours != self._hour:
            if self._hour is not None and hours is not None and self._hour_since is not None:
                stood = now - self._hour_since
                if stood > STOP_AFTER:
                    self._still += stood
            self._hour, self._hour_since = hours, now

    def _record_map(self, gid: str, t: int, control: dict) -> None:
        """Owner and controller of every state: all of them the first day written into a file, then the changes; the
        provinces held by another country than their state's controller (from 2026-10-23): all of them whenever they
        change (few - the fronts inside states)."""
        provinces = None
        if "states" in control:
            control, provinces = control["states"], control.get("provinces")
        control = {str(k): v for k, v in control.items()}
        provinces = None if provinces is None else {str(k): v for k, v in provinces.items()}
        full = gid != self._map_gid or self._map_last is None
        changed = control if full else {k: v for k, v in control.items() if self._map_last.get(k) != v}
        moved = provinces is not None and (full or provinces != self._prov_last)
        if full or changed or moved:
            self.history.add_map(gid, t, changed, full, provinces if moved else None)
        self._map_last, self._map_gid = control, gid
        if provinces is not None:
            self._prov_last = provinces

    def _step_frame(self, hours: int) -> None:
        """Within a recorded day: divisions, moves and battles again every FRAME_HOURS game hours."""
        if self._frame is None or hours - self._frame[1] < FRAME_HOURS or not hasattr(self.live, "frame_snapshot"):
            return
        gid = self._frame[0]
        try:
            frame = self.live.frame_snapshot()
        except Exception as exc:   # noqa: BLE001 - the daily rows go on without it
            self.log.info("Divisions not readable between days: %s", exc)
            self._frame = (gid, hours)
            return
        if frame["t"] != self.last_t:   # the day moved on: the daily reading takes it
            return
        self._record_frame(gid, frame)

    def _track_speed(self, hours: int | None) -> None:
        """Real seconds a game day takes, measured whenever the game hour moves on (a pause before it counts too -
        it only makes the game look slower, which reads the full day)."""
        now = self.monotonic()
        if hours is None:
            self._speed_mark = None
            return
        mark = self._speed_mark
        if mark is None or hours < mark[0] or hours - mark[0] > 24 * MAX_STEP:
            self._speed_mark = (hours, now)
        elif hours > mark[0]:
            seconds = (now - mark[1]) * 24 / (hours - mark[0])
            self._day_seconds = seconds if self._day_seconds is None else \
                SPEED_SMOOTHING * seconds + (1 - SPEED_SMOOTHING) * self._day_seconds
            self._speed_mark = (hours, now)

    def fast(self) -> bool:
        """A game day passes faster than the full day's reading takes (FAST_FULL_EVERY)."""
        fast = (self._full_cost is not None and self._full_cost >= FAST_MIN_COST and self._day_seconds is not None
                and self._day_seconds < self._full_cost)
        if fast != bool(self._fast_logged) and self._full_cost is not None and self._day_seconds is not None:
            self._fast_logged = fast
            self.log.info("IC recorder: %s (a game day in %.2f s, the full reading %.2f s)%s",
                          "fast game" if fast else "game slower than the reading", self._day_seconds, self._full_cost,
                          f" - full day every {FAST_FULL_EVERY} days, the map and divisions in between" if fast else "")
        return fast

    def _light(self, t: int) -> bool:
        """The light reading of a day between full ones (fast game): map, divisions, moves and battles. False when
        it cannot be done (no file yet, nothing readable) - the full day is read instead."""
        if self._gid is None or not hasattr(self.live, "frame_snapshot"):
            return False
        try:
            frame = self.live.frame_snapshot(with_map=True)
        except Exception as exc:   # noqa: BLE001 - the full reading takes the day
            self.log.info("Light reading not possible: %s", exc)
            return False
        if frame["t"] is None or frame["t"] <= self.last_t:
            return False
        if frame.get("map"):
            self._record_map(self._gid, frame["t"], frame["map"])
        self._record_frame(self._gid, frame)
        self._light_t = frame["t"]
        return True

    def _record_frame(self, gid: str, frame: dict) -> None:
        """Divisions, moves and battles of a reading between full days (frame_snapshot)."""
        if frame["units"] is not None:
            self._record_units(gid, frame["t"], frame["units"], frame["hour"])
        if frame["front"] is not None:
            self._record_delta("front", self._front, gid, frame["t"], frame["front"], frame["hour"])
        if frame.get("divs") is not None and self._divs["last"] is not None and self._divs["gid"] == gid:
            # positions and names now, stats and equipment as last read (daily); divisions gone lose them all
            here = {k[1:] for k in frame["divs"] if k[0] == "n"}
            kept = {k: v for k, v in self._divs["last"].items() if k[0] in "se" and k[1:] in here}
            self._record_delta("divs", self._divs, gid, frame["t"], {**kept, **frame["divs"]}, frame["hour"])
        self._frame = (gid, frame["t"] * 24 + frame["hour"])

    def _record_delta(self, kind: str, state: dict, gid: str, t: int, values: dict, hour: int = 0) -> None:
        """Like _record_units for another file (`state`: {"last", "gid", "full_t"} of what was written)."""
        full = gid != state["gid"] or state["last"] is None or t - state["full_t"] >= UNITS_FULL_EVERY \
            or t < state["full_t"]
        if full:
            changed = values
            state["full_t"] = t
        else:
            changed = {k: v for k, v in values.items() if state["last"].get(k) != v}
            changed.update({k: None for k in state["last"] if k not in values})
        if full or changed:
            self.history.add_delta(kind, gid, t, changed, full, hour)
        state["last"], state["gid"] = values, gid

    def _record_units(self, gid: str, t: int, units: dict, hour: int = 0) -> None:
        """Division positions: all of them the first day written into a file and every UNITS_FULL_EVERY days (playback
        starts from the last full row), else the provinces that changed (null: no division left there). Within a day
        (`hour`, FRAME_HOURS) only provinces whose divisions came or went - organisation and strength once a day."""
        units = {str(k): v for k, v in units.items()}
        full = gid != self._units_gid or self._units_last is None or t - self._units_full_t >= UNITS_FULL_EVERY \
            or t < self._units_full_t
        if full:
            changed = units
            self._units_full_t = t
        else:
            last = self._units_last
            same = lambda a, b: {g: (e[0], e[3]) for g, e in a.items()} == {g: (e[0], e[3]) for g, e in b.items()}  # noqa: E731
            changed = {k: v for k, v in units.items() if last.get(k) != v and not (hour and k in last and same(v, last[k]))}
            changed.update({k: None for k in last if k not in units})
        if full or changed:
            self.history.add_units(gid, t, changed, full, hour)
        if full or not hour:
            self._units_last = units
        else:   # what the file holds now: provinces with only other organisation / strength keep the written values
            kept = {k: v for k, v in self._units_last.items() if k in units}
            self._units_last = {**kept, **{k: v for k, v in changed.items() if v is not None}}
        self._units_gid = gid

    def _new_launch(self) -> str | None:
        """Id of the game being played (game.log) when its loaded day is not recorded yet, else None."""
        try:
            launch = self.live.game_launch()
        except Exception:  # the log is optional: the next played day is recorded anyway
            return None
        return launch if launch is not None and launch != self._launch_done else None

    def _record_actions(self, gid: str, t: int, player: str | None) -> None:
        """Snapshot of the player and the watched countries; what changed since the day before becomes events."""
        if gid != self._snaps_gid:   # another campaign: a new baseline
            self._snaps, self._snaps_gid = {}, gid
        tags = sorted({player, *self.history.watched()} - {None})
        try:
            snaps = self.actions(tags)
        except Exception as exc:  # the IC history is still worth recording
            self.log.info("Players actions not read: %s", exc)
            return
        events = []
        for tag, snap in snaps.items():
            events += [{"t": t, "tag": tag, **e} for e in actions_mod.diff(self._snaps.get(tag), snap)]
            self._snaps[tag] = snap
        if events:
            self.history.add_actions(gid, events)

    def _lock(self) -> bool:
        """Only one app instance records (a second one - e.g. the smoke test - stays passive): an OS lock on
        ic-history/.recorder.lock, released when the process ends."""
        try:
            self.history.folder.mkdir(parents=True, exist_ok=True)
            self._lock_file = open(self.history.folder / ".recorder.lock", "a+")
            if os.name == "nt":
                import msvcrt
                self._lock_file.seek(0)
                msvcrt.locking(self._lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            if getattr(self, "_lock_file", None):
                self._lock_file.close()
                self._lock_file = None
            return False

    def _run(self) -> None:
        while not self._lock():
            self.error = "another app instance is recording"
            if self._stop.wait(30):
                return
        self.error = None
        while not self._stop.is_set():
            try:
                self.step()
                self.error = None
            except Exception as exc:  # game closed, main menu, loading - try again later
                if str(exc) != self.error:
                    self.log.info("IC recorder waiting: %s", exc)
                self.error = str(exc)
                self._stop.wait(2.0)
            self._stop.wait(POLL_SECONDS)
