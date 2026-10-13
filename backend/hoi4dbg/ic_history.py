"""IC history of a campaign, like HOI4-IC-Graphs (github.com/otti086-Org/HOI4-IC-Graphs) but from game memory instead
of a DLL injected into the game: once per game day, every existing country's IC a day on military production (MIL),
naval production (NAV) and construction (CIV) - live/pointers.read_ic - and its civilian factories, military factories
and dockyards as the game shows them (live/pointers.read_factories).

One file per campaign in <data dir>/ic-history/<id>.jsonl: a "meta" line, then one line per recorded day
{"t": day number (365-day years), "d": "1941.11.02", "c": {tag: [mil, nav, civ, fciv, fmil, fdock]}, "f": {tag: faction} (every
FACTION_EVERY days)}. Days skipped at high game speed are filled when graphing (the value holds until the next sample).
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
from pathlib import Path

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


STORED = ("mil", "nav", "civ", "fciv", "fmil", "fdock")   # order of the values in a file row
METRICS = STORED + ("fall",)   # fall = all factories (civilian + military + dockyards)
NO_FACTION = "Non-aligned"


TAG = re.compile(r"^[A-Z0-9]{2,4}$")
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


def view(game: dict, metric: str, tags: list[str] | None, by_faction: bool, groups: dict | None = None) -> dict:
    """What the Game summary tab draws: the country list (latest IC a day, faction) and the day series of `metric`
    for the chosen countries, or one summed series per faction (current factions; others under NO_FACTION).
    `groups` (check_groups) moves countries between factions and adds the user's own groups."""
    if metric not in METRICS:
        raise ValueError(f"metric must be one of {', '.join(METRICS)}")
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
    if by_faction:
        sums: dict[str, list[float]] = {}
        for t, v in countries.items():
            name = factions.get(t) or NO_FACTION
            acc = sums.setdefault(name, [0.0] * len(game["t"]))
            for i, x in enumerate(v[metric]):
                acc[i] = None if x is None or acc[i] is None else acc[i] + x
        for name in groups["custom"]:   # an empty group of the user's still shows (as zero)
            sums.setdefault(name, [0.0] * len(game["t"]))
        order = sorted(sums, key=lambda n: (n == NO_FACTION, -(sums[n][-1] or 0) if sums[n] else 0))
        series = [{"key": n, "values": [None if x is None else round(x, 3) for x in sums[n]]} for n in order]
    else:
        series = [{"key": t, "values": countries[t][metric]} for t in tags or [] if t in countries]
    for c in listing:
        c["game_faction"] = game_factions.get(c["tag"])
    return {"t": game["t"], "dates": game["dates"], "countries": listing, "series": series,
            "factions": sorted({f for f in factions.values() if f} | set(groups["custom"])),
            "custom": groups["custom"]}


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
            rows = self._lines(path.stem)
            meta = next((r["meta"] for r in rows if "meta" in r), {})
            days = [r for r in rows if "t" in r]
            out.append({"id": path.stem, "player": meta.get("player"), "created": meta.get("created"),
                        "first": days[0]["d"] if days else None, "last": days[-1]["d"] if days else None,
                        "last_t": days[-1]["t"] if days else None, "days": len(days), "active": path.stem == self.active})
        return sorted(out, key=lambda g: g["created"] or "", reverse=True)

    def game(self, gid: str) -> dict:
        """{"id", "player", "t": [...], "dates": [...], "countries": {tag: {metric: [...]}}, "factions": {tag: faction}}
        - a missing country on a day is 0 (it did not exist); a value not recorded yet is None."""
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
                for k, v in zip(STORED, row):   # rows recorded before factories were counted have none (None)
                    series[tag][k].append(v)
                fac = row[3:6]
                series[tag]["fall"].append(None if None in fac else sum(fac))
            if "f" in r:
                factions = r["f"]
        return {"id": gid, "player": meta.get("player"), "t": [r["t"] for r in days], "dates": [r["d"] for r in days],
                "countries": series, "factions": factions}

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

    def _choose(self, player: str, t: int) -> str:
        """The campaign file a sample of `player` at day `t` belongs to (cutting replayed days)."""
        candidates = [g for g in self.games() if g["player"] == player and g["last_t"] is not None]
        if self.active:
            candidates.sort(key=lambda g: g["id"] != self.active)   # the current file first
        for g in candidates:
            if g["last_t"] < t <= g["last_t"] + NEW_CAMPAIGN_GAP:
                return g["id"]
            # only the file of this session is cut: an older campaign of the same country is never touched
            if g["id"] == self.active and t <= g["last_t"] and g["last_t"] - t <= NEW_CAMPAIGN_GAP:
                self._cut(g["id"], t)
                return g["id"]
        gid = f"{player}_{date_text(t).replace('.', '-')}_{time.strftime('%Y%m%d-%H%M%S')}"
        self.folder.mkdir(parents=True, exist_ok=True)
        meta = {"meta": {"player": player, "created": time.strftime("%Y-%m-%d %H:%M:%S"), "start": date_text(t)}}
        self._path(gid).write_text(json.dumps(meta) + "\n", encoding="utf-8")
        return gid

    def _cut(self, gid: str, t: int) -> None:
        rows = [r for r in self._lines(gid) if "t" not in r or r["t"] < t]
        self._path(gid).write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows), encoding="utf-8")

    def add(self, sample: dict) -> str:
        """Appends {"t", "player", "countries", "factions"?} and returns the campaign id."""
        with self._lock:
            if self.active is None or sample["t"] <= self._last_t or sample["player"] != self._player:
                self.active = self._choose(sample["player"], sample["t"])
            row = {"t": sample["t"], "d": date_text(sample["t"]), "c": sample["countries"]}
            if sample.get("factions") is not None:
                row["f"] = sample["factions"]
            with self._path(self.active).open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, separators=(",", ":")) + "\n")
            self._last_t, self._player = sample["t"], sample["player"]
            return self.active

    _last_t = -1
    _player: str | None = None


class IcRecorder:
    """Background thread: polls the game date and records a sample when a new day starts."""

    def __init__(self, live, history: IcHistory, log) -> None:
        self.live, self.history, self.log = live, history, log
        self.last_t: int | None = None   # last recorded day
        self.seen_t: int | None = None   # day of the previous poll
        self.error: str | None = None
        self._stop = threading.Event()
        self._last_faction_t = -FACTION_EVERY

    def start(self) -> None:
        threading.Thread(target=self._run, name="ic-recorder", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def status(self) -> dict:
        return {"recording": self.history.active, "last": date_text(self.last_t) if self.last_t is not None else None,
                "error": self.error}

    def step(self) -> bool:
        """One poll: records when a game day has passed; True when a sample was written. Only a date moving forward by
        1..MAX_STEP days counts: the main menu and the country selection screen hold a 1936.01.01 game state with the
        hovered country as player, and loading a save jumps the date - neither is a played day."""
        t = self.live.game_day()
        previous, self.seen_t = self.seen_t, t
        if t is None or previous is None or not 0 < t - previous <= MAX_STEP:
            return False
        with_factions = t - self._last_faction_t >= FACTION_EVERY or self.last_t is None or t < self.last_t
        sample = self.live.ic_snapshot(with_factions)
        if sample["t"] != t:   # the day moved on while reading: take it next time
            self.seen_t = previous
            return False
        if not any(any(v) for v in sample["countries"].values()):   # production not set up yet (loading)
            return False
        self.history.add(sample)
        if with_factions:
            self._last_faction_t = t
        self.last_t = t
        return True

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
