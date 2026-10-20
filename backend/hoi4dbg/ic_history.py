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
NEW_CAMPAIGN_GAP = 31   # days back that still count as a reload of the same campaign
MONTH_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)   # the game has no leap years
SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


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
          "amil", "anav", "aciv")                        # factories on military / naval production lines, construction
SUMS = {"fall": ("fciv", "fmil", "fdock"), "wall": ("wmil", "wnav", "wciv"), "lall": ("lcom", "latt")}
# IC a day per factory working on a line (2026-10-20, user's request): IC / assigned factories - the line's efficiency,
# factory / dockyard output and construction speed bonuses, resource shortages. Groups: their IC / their factories.
# Days recorded before the assigned factories were stored (before 2026-10-20): military and naval from the wasted IC
# (wasted = idle x IC / assigned and idle = factories - assigned, so assigned = factories x IC / (IC + wasted));
# civilian ones stay unknown (free civilian factories were not stored).
RATIOS = {"pmil": ("mil", "amil", "fmil", "wmil"), "pnav": ("nav", "anav", "fdock", "wnav"), "pciv": ("civ", "aciv", None, None)}
METRICS = STORED + tuple(SUMS) + tuple(RATIOS)
LEVEL_METRICS = ("fciv", "fmil", "fdock", "fall", *RATIOS)   # states of a day, not flows: no cumulative chart
LOSS_METRICS = ("lcom", "latt", "lenemy", "lall")   # only countries with a combat log have them
NO_FACTION = "Non-aligned"

# IC a day of one factory without any line to compare with (common/defines NProduction, 1.19.3): BASE_FACTORY_SPEED_MIL,
# BASE_FACTORY_SPEED_NAV, BASE_FACTORY_SPEED (construction)
BASE_SPEED = {"mil": 3.5, "nav": 2.0, "civ": 4.0}


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
    if by_player:
        skip_unknown = metric in LOSS_METRICS
        sums: dict[str, list] = {}
        for i, day in enumerate(days):
            for t, p in day.items():
                acc = sums.setdefault(player_key(t, p), [None if skip_unknown else 0.0] * len(game["t"]))
                for member in [t, *(p.get("s") or [] if subjects else [])]:
                    x = countries.get(member, {}).get(metric, [None] * len(game["t"]))[i]
                    if skip_unknown:
                        acc[i] = acc[i] if x is None else (acc[i] or 0.0) + x
                    else:
                        acc[i] = None if x is None or acc[i] is None else acc[i] + x
        order = sorted(sums, key=lambda n: -(sums[n][-1] or 0))
        series = [{"key": n, "values": [None if x is None else round(x, 3) for x in sums[n]]} for n in order]
        if subjects:   # the subjects' own value counts in the listing too
            for p in players:
                vals = [last(countries.get(m, {}), metric) for m in [p["tag"], *p["subjects"]]]
                p["value"] = None if all(v is None for v in vals) else round(sum(v or 0 for v in vals), 3)
    elif by_faction:
        sums: dict[str, list[float]] = {}
        skip_unknown = metric in LOSS_METRICS   # most countries have no combat log: sum the known ones
        for t, v in countries.items():
            name = factions.get(t) or NO_FACTION
            acc = sums.setdefault(name, [None if skip_unknown else 0.0] * len(game["t"]))
            for i, x in enumerate(v[metric]):
                if skip_unknown:
                    acc[i] = acc[i] if x is None else (acc[i] or 0.0) + x
                else:
                    acc[i] = None if x is None or acc[i] is None else acc[i] + x
        for name in groups["custom"]:   # an empty group of the user's still shows (as zero)
            sums.setdefault(name, [None if skip_unknown else 0.0] * len(game["t"]))
        if skip_unknown:   # groups without any combat log are not drawn
            sums = {n: v for n, v in sums.items() if any(x is not None for x in v) or n in groups["custom"]}
        order = sorted(sums, key=lambda n: (n == NO_FACTION, -(sums[n][-1] or 0) if sums[n] else 0))
        series = [{"key": n, "values": [None if x is None else round(x, 3) for x in sums[n]]} for n in order]
    else:
        series = [{"key": t, "values": countries[t][metric]} for t in tags or [] if t in countries]
    for c in listing:
        c["game_faction"] = game_factions.get(c["tag"])
    return {"t": game["t"], "dates": game["dates"], "countries": listing, "series": series,
            "factions": sorted({f for f in factions.values() if f} | set(groups["custom"])),
            "custom": groups["custom"], "players": players}


class IcHistory:
    """Campaign files: reading, choosing the file a new sample belongs to, appending."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.active: str | None = None
        self._lock = threading.Lock()

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
        for r in days:
            for tag in tags:
                values = r["c"].get(tag)
                row = list(values) + [None] * (len(STORED) - len(values)) if values else [0] * len(STORED)
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
        known = [r.get("p") for r in days]
        first = next((p for p in known if p), None) or (
            {meta["player"]: {"n": None, "s": []}} if meta.get("player") else {})
        players, current = [], first
        for p in known:
            current = p or current
            players.append(current)
        return {"id": gid, "player": meta.get("player"), "t": [r["t"] for r in days], "dates": [r["d"] for r in days],
                "countries": series, "factions": factions, "players": players}

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
        seen = self.designs(gid)   # designs first seen on a replayed day: the game may give their ids to new ones
        kept = {tag: {i: v for i, v in ids.items() if v[1] or v[0] < t} for tag, ids in seen.items()}
        if kept != seen:
            self._designs_path(gid).write_text(json.dumps(kept, separators=(",", ":")), encoding="utf-8")

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
        self.actions = actions             # tags -> {tag: snapshot} (Players actions), None = off
        self._snaps: dict[str, dict] = {}  # last snapshot per watched country
        self._snaps_gid: str | None = None
        self._chosen: tuple | None = None   # (file, how it was chosen) last logged

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
        hovered country as player, and loading a save jumps the date - neither is a played day."""
        t = self.live.game_day()
        previous, self.seen_t = self.seen_t, t
        if t is not None and t != previous:   # a game started since the user turned it on gets it too
            self.live.ensure_combat_log_patch()
        if t is None or previous is None or not 0 < t - previous <= MAX_STEP:
            if t != previous:   # another game state: its combat log and snapshots do not continue the last ones
                self._losses = None
                self._snaps = {}
            return False
        with_factions = t - self._last_faction_t >= FACTION_EVERY or self.last_t is None or t < self.last_t
        sample = self.live.ic_snapshot(with_factions)
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
        for tag, values in sample["countries"].items():   # after the losses (None when not read): assigned factories
            values.extend([None] * (12 - len(values)))
            values.extend(assigned.get(tag) or [None, None, None])
        designs = sample.pop("designs", None)
        gid = self.history.add(sample)
        if (gid, self.history.how) != self._chosen:
            self._chosen = (gid, self.history.how)
            self.log.info("IC recorder: %s (game id %s) - %s", gid, sample.get("campaign") or "not readable",
                          self.history.how)
        if designs is not None:
            self.history.note_designs(gid, t, designs)
        if self.actions is not None:
            self._record_actions(gid, t, sample.get("player"))
        if with_factions:
            self._last_faction_t = t
        self.last_t = t
        return True

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
