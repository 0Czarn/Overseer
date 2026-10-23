"""Debugger service: combines the game integration layer, DEMO data and reports
into the payloads served by the API. Contains no HTTP and no UI code."""

from __future__ import annotations

import base64
import datetime as dt
import json
from pathlib import Path
import logging
import math
import functools
import platform
import re
import sys
import threading
import time

from . import __version__, construction as construction_mod, doctrines as doctrines_mod, geography, trade as trade_mod, deficit, demo, equipment_changes, gamefiles, gfx, modifiers
from . import government as government_mod
from . import campaign_map
from . import game_tools
from . import mio as mio_mod
from . import divisions as divisions_mod
from . import ic_history as ic_history_mod
from .ic_history import IcHistory
from .backgrounds import BackgroundError, Backgrounds
from . import focus as focus_mod
from . import techtree
from . import triggers as triggers_mod
from .applog import RingBufferHandler
from .integration import GameIntegration, NullIntegration
from .reports import ReportError, ReportStore
from .saves import equipment as save_equipment
from .saves import fields as save_fields
from .saves import states as save_states
from .saves import text as text_mod
from .saves.binary import SaveFormatError
from .saves.reader import SaveAnalyzer, list_saves

LIVE, DEMO, UNAVAILABLE, SAVE = "live", "demo", "unavailable", "save"

DEMO_NOTE = "DEMO data - not read from the game."
SAVE_NOTE = ("Read from a save file (copy). A save is a snapshot from the moment it was written, "
             "never the live state of the game.")
WRITE_NOTE = "Editing is disabled: no write method exists yet (planned Stage 4, singleplayer first)."

# Which data domains are live vs DEMO right now. Single source of truth for the UI badges.
CAPABILITIES: dict[str, dict] = {
    "detection": {"source": LIVE, "write": False, "note": "Process, install and version detection."},
    "game_logs": {"source": LIVE, "write": False, "note": "Read-only tail of the game's own log files."},
    "countries": {"source": DEMO, "write": False, "note": DEMO_NOTE},
    "players": {"source": SAVE, "write": False, "note": "Player -> country assignment from the newest save. " + SAVE_NOTE},
    "save_header": {"source": SAVE, "write": False,
                    "note": "Save header: country, in-game date, version, difficulty, ideology, mods."},
    "country_values": {"source": SAVE, "write": False,
                       "note": "From text saves (-force_text_save): political power, stability, war support, "
                               "command power, fuel, army XP, manpower, convoys. No write method."},
    "states": {"source": DEMO, "write": False, "note": WRITE_NOTE},
    "focus": {"source": DEMO, "write": False, "note": "Read-only preview. Queueing is not implemented."},
    "equipment": {"source": DEMO, "write": False, "note": WRITE_NOTE},
}

# Game Tools catalogue. scope: "local" = only this app / this client; "shared" = would change the
# common game state and therefore needs a sync mechanism that works in multiplayer.
TOOLS: list[dict] = [
    {"id": "always_on_top", "name": "Always on top", "scope": "local", "status": "available",
     "description": "Keeps the debugger window above the game window. Affects only this app."},
    {"id": "compact_mode", "name": "Compact mode", "scope": "local", "status": "available",
     "description": "Denser layout for a small window next to the game. Affects only this app."},
    {"id": "redetect", "name": "Re-detect game", "scope": "local", "status": "available",
     "description": "Runs process/version detection again. Read-only."},
    {"id": "open_logs", "name": "Open HOI4 logs folder", "scope": "local", "status": "available",
     "description": "Opens the game's log folder in Explorer. Read-only."},
    {"id": "save_inspector", "name": "Save inspector", "scope": "local", "status": "available",
     "description": "Reads a copy of any save file (header, players, mods, structure check). Never modifies saves."},
    {"id": "fog_of_war", "name": "Fog of war", "scope": "local", "status": "available",
     "description": "Turns the fog of war of your own client off and on, like the console command fow. In "
                    "multiplayer only when allowed in Options - it shows you what the other players cannot see."},
    {"id": "checkpoints", "name": "Campaign checkpoints", "scope": "local", "status": "available",
     "description": "Your saves with game date, country and a note of your own (kept by the app). Saves are only read."},
    {"id": "live_check", "name": "Live memory check", "scope": "local", "status": "available",
     "description": "Runs every game-memory reader once and shows which work - after a game or mod update. Read-only."},
]


def envelope(source: str, data, note: str | None = None) -> dict:
    return {"source": source, "note": note, "data": data}


class NotFound(LookupError):
    pass


def version_core(version: str | None) -> str | None:
    """'Operation Postern v1.19.3.0.c01a (ff0e)' -> 'Operation Postern v1.19.3.0.c01a'.
    The suffix in parentheses differs between saves of the same build, so it is not compared."""
    if not version:
        return None
    return version.split(" (")[0].strip()


def save_freshness(save_mtime: float, game: dict, now: float | None = None) -> dict:
    """How a save relates to the game that is running right now. A save is never live."""
    now = time.time() if now is None else now
    age_s = max(0, int(now - save_mtime))
    process = game.get("process")
    started = process.get("started") if process else None
    if process is None:
        category, label = "game_not_running", "Game not running - this is the last saved state, not a live game"
    elif started is None:
        category, label = "unknown_session", "Game running, but its start time is unknown - cannot tell if this save is current"
    elif save_mtime >= dt.datetime.fromisoformat(started).timestamp():
        category, label = "current_session", "Snapshot written during the current game session - the game has moved on since"
    else:
        category, label = "previous_session", "From an EARLIER session - NOT the current game state"
    return {"category": category, "label": label, "age_s": age_s, "is_live": False}


# plane design stats as the game's design tooltip names them (Air.png)
MAX_ACTIONS = 3000   # newest events sent to the Players actions tab
PLANE_STAT_LABELS = {"range": "Range", "air_defence": "Air Defense", "air_attack": "Air Attack", "air_agility": "Agility",
                     "air_superiority": "Air Superiority", "naval_strike_attack": "Naval Attack",
                     "naval_strike_targetting": "Naval Targeting", "maximum_speed": "Max Speed",
                     "reliability": "Reliability", "weight": "Weight", "thrust": "Thrust", "fuel_consumption": "Fuel Usage",
                     "build_cost_ic": "Production Cost", "surface_detection": "Surface Detection",
                     "sub_detection": "Sub Detection"}


@functools.lru_cache(maxsize=2)
def resource_order(roots: tuple[str, ...]) -> dict[str, dict]:
    """{resource: {"frame": icon_frame, "cic": civilian factories per unit traded}} from common/resources (later
    roots override)."""
    out: dict[str, dict] = {}
    for root in map(Path, roots):
        for path in sorted((root / "common" / "resources").glob("*.txt")):
            try:
                items = text_mod.parse(re.sub(r"#[^\n]*", "", path.read_text(encoding="utf-8-sig", errors="replace")))
            except Exception:
                continue
            for _k, block in (i for i in items if isinstance(i, tuple)):
                for name, body in (i for i in block if isinstance(i, tuple)) if isinstance(block, list) else []:
                    frame = text_mod.get(body, "icon_frame") if isinstance(body, list) else None
                    if frame is not None:
                        cic = text_mod.get(body, "cic")
                        out[name] = {"frame": int(float(frame)), "cic": float(cic) if cic is not None else 0.125}
    return out


def usable_for(bonus: dict, techs: dict, researched: set[str], in_progress: set[str]) -> list[str]:
    """Technologies a one-time bonus can be used on now: in one of its categories, not researched nor in progress,
    every dependency and at least one technology leading to it researched (none = a root), no XOR one researched,
    in a tree folder and without an `allow` condition (country-only or hidden technologies). Sorted by start year,
    then id."""
    cats = set(bonus.get("categories") or [])   # "*" in both = any category (tech tree state)
    out = []
    for tid, t in techs.items():
        if tid in researched or tid in in_progress or not t.get("in_tree") or not cats & set(t.get("categories") or []):
            continue
        if t.get("parents") and not researched & set(t["parents"]):
            continue
        if not set(t.get("needs") or []) <= researched or researched & set(t.get("excludes") or []):
            continue
        out.append(tid)
    return sorted(out, key=lambda tid: (techs[tid].get("start_year") or 0, tid))


# Breakdown parts the game adds to stability / war support outside its summed country modifiers (2026-10-13, SOV
# 1941 tooltips): the ruling party term, world tension, at war, offensive / defensive war, bombing and casualty
# penalties. "War Support" (war_support_during_war) is inside the sum.
OUTSIDE_GAME_SUM = {"tension", "at_war", "offensive_war", "defensive_war", "bombing_penalty", "casualties_penalty"}
MONTH_START = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)   # the game has no leap years


def save_mismatch(save_date: dict | None, game_date: dict | None) -> str | None:
    """Message when the save is not from the running game: dated after it, or more than 31 days before it (e.g. a
    save of another campaign), else None."""
    if not save_date or not game_date or not save_date.get("year"):
        return None
    saved = save_date["year"] * 365 + MONTH_START[(save_date.get("month") or 1) - 1] + (save_date.get("day") or 1) - 1
    running = game_date["year"] * 365 + game_date["day"]
    if 0 <= running - saved <= 31:
        return None
    return (f"The newest save ({save_date.get('text') or save_date['year']}) is not from the running game "
            f"({game_date['year']}, day {game_date['day'] + 1}): save the game to read wars and other modifiers")


def _tech_xy(position, consts: dict) -> tuple[float, float]:
    """(x, y) of folder.position = { x = 0 y = @1936 } with the file's @ constants."""
    def num(v):
        v = consts.get(v, v) if isinstance(v, str) else v
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0
    return (num(text_mod.get(position, "x")), num(text_mod.get(position, "y"))) if isinstance(position, list) else (0.0, 0.0)


def ahead_years(tech: dict | None, today: float | None) -> float:
    """Years a technology is researched before its start year (0 when not ahead or unknown)."""
    if not tech or not tech.get("start_year") or today is None:
        return 0.0
    return max(0.0, tech["start_year"] - today)


def research_progress(slot: dict, tech: dict | None, defines: dict, today: float | None,
                      country_speed: float | None = None) -> dict:
    """{"cost", "progress" (0..1), "days_left", "ahead_years", "base_speed", "estimate"} of a research slot.

    Checked against the game (2026-10-11): cost = BASE_TECH_COST x research_cost (220 excavation1, 165
    interwar_artillery, 110 antiair1 - no ahead-of-time increase); researching ahead of time divides the daily
    points instead: speed = base / (1 + BASE_YEAR_AHEAD_PENALTY_FACTOR x years ahead). The slot speed read keeps
    the penalty of the day the research started (0.20327 for antiair1 both on day 263 and day 281), so the base is
    `country_speed` = the speed of a slot researching without penalty. The game's estimate lets the penalty shrink
    day by day, evaluated 2 days ahead: 401 and 383 days for antiair1 on days 263 and 281.5, both equal to the game.
    Without a penalty (cost - points) / (speed + technology bonus), rounded up (146, 111).
    `today` = game date in years (1936.72 = day 263 of 1936)."""
    empty = {"cost": None, "progress": None, "days_left": None, "ahead_years": None, "base_speed": slot.get("speed"),
             "estimate": False}
    if not slot.get("technology") or not tech or tech.get("cost") is None:
        return empty
    factor = defines["BASE_YEAR_AHEAD_PENALTY_FACTOR"]
    ahead = ahead_years(tech, today)
    speed, bonus = slot.get("speed"), slot.get("bonus")
    guessed = ahead > 0 and not country_speed
    if not ahead:
        base = speed
    else:   # without a penalty-free slot to compare with: today's penalty (the start day's is not known)
        base = country_speed or (speed * (1 + factor * ahead) if speed is not None else None)
    cost = defines["BASE_TECH_COST"] * tech["cost"]
    out = {**empty, "cost": cost, "ahead_years": ahead or None, "base_speed": base,
           # from a save the technology's own daily bonus is not known
           "estimate": guessed or bonus is None}
    points = slot.get("points")
    if points is None or base is None or cost <= 0:
        return out
    out["progress"] = min(1.0, points / cost)
    daily = base + (bonus or 0)
    if daily <= 0:
        return out
    if not ahead:
        out["days_left"] = math.ceil(round(max(0.0, cost - points) / daily, 6))
        return out
    days, done = 0, points
    while done < cost and days < 36500:
        done += daily / (1 + factor * max(0.0, ahead - (days + 2) / 365))
        days += 1
    out["days_left"] = days
    return out


LOC_REF = re.compile(r"\$([A-Za-z0-9_.]+)(?:\|[^$]*)?\$")
SCRIPTED_LOC = re.compile(r"\[(?:[A-Za-z]+\.)*Get([A-Z][A-Za-z]*?)(?:Names?)?\]")   # [GetAutobahnName] -> Autobahn
SCRIPTED_KEEP = {"Name", "NameDef", "NameDefCap", "Adjective", "AdjectiveCap", "Leader", "RulingParty"}  # country texts


def clean_loc(value: str, names: dict[str, str], depth: int = 3) -> str:
    """Game localisation -> plain text: $KEY$ references resolved, colour codes (§X ... §!), icons (£x)
    and scripted expressions ([Root.GetName]) removed; \\n kept as line breaks."""
    for _ in range(depth):
        value = LOC_REF.sub(lambda m: names.get(m.group(1), ""), value)
    value = re.sub(r"§[A-Za-z!]", "", value)
    value = re.sub(r"£[A-Za-z0-9_|]+", "", value)
    value = re.sub(r"\[[^\]]*\]", "", value)
    return re.sub(r"[ \t]+", " ", value.replace("\\n", "\n")).strip()


class DebuggerService:
    def __init__(self, integration: GameIntegration, reports: ReportStore, ring: RingBufferHandler,
                 logger: logging.Logger, data_dir: str = "", saves: SaveAnalyzer | None = None,
                 live=None) -> None:
        self.saves = saves
        self.live = live  # live.service.LiveService (process memory, read-only) or None
        self.integration = integration
        self.reports = reports
        self.ring = ring
        self.log = logger
        self.data_dir = data_dir
        self._last_detected: bool | None = None
        self.ic_history = IcHistory(Path(data_dir or ".") / "ic-history")
        self._where_cache: tuple | None = None   # (game roots, {province: state name})   # recorded campaigns (Game summary)
        self.backgrounds = Backgrounds(Path(data_dir or ".") / "backgrounds")   # the user's images (Options)
        self._checkpoints = game_tools.Checkpoints(Path(data_dir or ".") / "checkpoints.json")   # notes on saves
        self.ic_recorder = None   # ic_history.IcRecorder when live access is on (started in __main__)

    # -- status ---------------------------------------------------------------------------
    def detect(self) -> dict:
        snapshot = self.integration.detect()
        detected = snapshot.get("process") is not None
        if detected != self._last_detected:
            if detected:
                proc = snapshot["process"]
                self.log.info("HOI4 process detected: pid=%s path=%s", proc.get("pid"), proc.get("path"))
            elif self._last_detected is not None:
                self.log.info("HOI4 process no longer running")
            else:
                self.log.info("HOI4 process not running")
            self._last_detected = detected
        return {**snapshot, "detected": detected}

    def status(self) -> dict:
        return {
            "app": {
                "version": __version__,
                "python": sys.version.split()[0],
                "platform": platform.platform(),
                "data_dir": self.data_dir,
            },
            "game": self.detect(),
            "capabilities": self.capabilities(),
        }

    def capabilities(self) -> dict:
        caps = {key: dict(value) for key, value in CAPABILITIES.items()}
        if isinstance(self.integration, NullIntegration):
            for key in ("detection", "game_logs"):
                caps[key].update(source=UNAVAILABLE, note=self.integration.reason)
        return caps

    # -- countries (game files + newest save) -----------------------------------------------
    def _install_path(self) -> Path | None:
        path = (self.detect().get("install") or {}).get("path")
        return Path(path) if path and (Path(path) / "common" / "country_tags").is_dir() else None

    def countries(self) -> dict:
        """Tags from the game files, names from its localisation; existence, ideology and players from the
        newest save (countries owning at least one state). DEMO only when neither is available."""
        install = self._install_path()
        tags = gamefiles.tag_order(install, self._game_roots(install)[1:]) if install else []
        names = gamefiles.country_names(install) if install else {}
        summary, note = None, None
        picked = self._pick_save(None)
        if picked is not None:
            try:
                summary = self.saves.country_list(picked[0])
            except SaveFormatError as exc:
                note = f"Country list not read from {picked[0].name}: {exc}"
        if not tags and summary is None:
            return envelope(DEMO, demo.countries(), DEMO_NOTE)
        owners = (summary or {}).get("owners") or {}
        ruling = (summary or {}).get("ruling") or {}
        header = ((summary or {}).get("analysis") or {}).get("header") or {}
        players: dict[str, str] = {}
        for p in header.get("players") or []:  # co-op: several players can share one country
            if p.get("tag"):
                players[p["tag"]] = ", ".join(filter(None, [players.get(p["tag"]), p.get("name") or "unknown"]))
        items = []
        for tag in tags or sorted(owners):
            party = ruling.get(tag)
            items.append({
                "tag": tag, "name": names.get(f"{tag}_{party}") or names.get(tag) or tag,
                "exists": (tag in owners) if summary else None, "states": owners.get(tag, 0),
                "ruling_party": party, "player": players.get(tag),
                "is_player_country": tag == header.get("player_tag"), "is_ai": tag not in players,
            })
        if summary:
            items = [i for i in items if i["exists"]] + [i for i in items if not i["exists"]]
            analysis = summary["analysis"]
            note = (f"{len(owners)} countries own states in {analysis['file']['name']} "
                    f"({(header.get('date') or {}).get('text') or 'date unknown'}); names from the game localisation.")
        return envelope(SAVE if summary else LIVE, items, note or "Tags and names from the game files; "
                        "no readable save for existence and players.")

    def country(self, tag: str) -> dict:
        tag = tag.upper()
        listing = self.countries()
        if listing["source"] == DEMO:
            data = demo.country(tag)
            if data is None:
                raise NotFound(f"Unknown country tag: {tag}")
            return envelope(DEMO, {**data, "fields": demo.COUNTRY_FIELDS, "editable": False}, DEMO_NOTE)
        found = next((c for c in listing["data"] if c["tag"] == tag), None)
        if found is None:
            raise NotFound(f"Unknown country tag: {tag}")
        return envelope(SAVE, {**found, "values": {}, "fields": demo.COUNTRY_FIELDS,
                               "editable": False}, "Country identity from game files and the newest save; "
                        "values come from /save-values and live memory.")

    def states(self, owner: str | None = None, source: str = "save") -> dict:
        """States of the newest save (snapshot) with names and provinces from the game files; DEMO without them.
        source="live": from game memory instead (live/service.states) - province buildings and the controllers of
        single provinces are not read live."""
        if source == "live":
            return self._states_live(owner)
        install = self._install_path()
        picked = self._pick_save(None)
        items, note, source = None, None, DEMO
        if install and picked is not None:
            try:
                data = self.saves.states(picked[0])
            except SaveFormatError as exc:
                note = f"States not read from {picked[0].name}: {exc}"
            else:
                items = save_states.assemble(data, gamefiles.state_definitions(install), gamefiles.state_names(install))
                header = data["analysis"].get("header") or {}
                source = SAVE
                note = (f"{len(items)} states from {picked[0].name} ({(header.get('date') or {}).get('text') or 'date unknown'})"
                        "; names and provinces from the game files. Snapshot - not live.")
        if items is None:
            items = demo.states()
            note = f"{note} {DEMO_NOTE}" if note else DEMO_NOTE
        if owner:
            owner = owner.upper()
            items = [s for s in items if owner in (s["owner"], s["controller"])]
        return envelope(source, items, note)

    def _states_live(self, owner: str | None) -> dict:
        install = self._install_path()
        if install is None or self.live is None:
            return envelope(UNAVAILABLE, [], "Needs the game installation and live game access")
        roots = self._game_roots(install)
        try:
            res = self.live.states(list(construction_mod.buildings(roots)), list(resource_order(roots)))
        except Exception as exc:  # game not running, main menu, loading, another version
            return envelope(UNAVAILABLE, [], f"Live states not readable: {exc}")
        definitions, names = gamefiles.state_definitions(install), gamefiles.state_names(install)
        items = []
        for st in res["states"]:
            definition = definitions.get(st["id"]) or {}
            if not definition and not st["owner"]:
                continue   # an unused slot of the state table
            key = definition.get("name_key") or ""
            items.append({**st, "name": names.get(key, key or f"State {st['id']}"),
                          "controllers": {st["controller"]: len(definition.get("provinces") or [])} if st["controller"] else {},
                          "provinces": len(definition.get("provinces") or []), "province_buildings": None})
        if owner:
            owner = owner.upper()
            items = [s for s in items if owner in (s["owner"], s["controller"])]
        return envelope(LIVE, items, f"{len(items)} states from game memory ({res.get('date') or 'date unknown'}); "
                                     "province buildings only in the save view.")

    def _focus_context(self, tag: str, live_first: bool = False):
        """(state, focuses of its tree with statuses) or None. State from the newest save, or with `live_first`
        from game memory (tree, completed, current focus - no save needed) when the game runs."""
        install = self._install_path()
        if install is None:
            return None
        state = None
        if live_first and self.live is not None:
            try:
                live = self.live.focus(tag)
                if live.get("tree"):
                    state = {"tree": live["tree"], "completed": live["completed"], "current": live["current"],
                             "progress": live["progress_days"], "paused": False, "analysis": None, "source": "live",
                             "date": live.get("date"), "members": live.get("members")}
            except Exception:  # game not running, main menu, other version: the save is the fallback
                state = None
        if state is None:
            picked = self._pick_save(None)
            if picked is None:
                return None
            state = {**self.saves.focus_state(picked[0], tag), "source": "save"}
        roots = self._game_roots(install)
        files = focus_mod.focus_files(install, [Path(r) for r in roots[1:]])
        focuses = focus_mod.statuses(self._focus_shape(tag, state, files, roots), state) if state["tree"] else []
        names = self._loc_names(install, {f["id"] for f in focuses})
        for f in focuses:
            # scripted names ([GetAutobahnName]) are resolved by the game at runtime: "Autobahn", else a readable id
            name = SCRIPTED_LOC.sub(lambda m: m.group(0) if m.group(1) in SCRIPTED_KEEP
                                    else re.sub(r"(?<=[a-z])(?=[A-Z])", " ", m.group(1)), names.get(f["id"]) or "")
            f["name"] = name if name and "[" not in name else f["id"].split("_", 1)[-1].replace("_", " ").capitalize()
        return state, focuses

    def _focus_shape(self, tag: str, state: dict, files: tuple[str, ...], roots: tuple[str, ...]) -> list[dict]:
        """The tree as the game shows it to the country: its focuses (the game's list from memory when it runs),
        moved by the offsets whose trigger holds; "hidden" = allow_branch false or reachable only through hidden
        focuses. Triggers are checked on game memory, else on the save (completed focuses, DLCs, game rules)."""
        base = focus_mod.tree(files, state["tree"], members=state.get("members"))
        scripts = triggers_mod.focus_scripts(files)
        blocks = {}
        for f in base:
            sc = scripts.get(f["id"]) or {}
            if sc.get("allow_branch") is not None:
                blocks[("branch", f["id"], 0)] = sc["allow_branch"]
            for i, (_dx, _dy, trig) in enumerate(sc.get("offsets") or []):
                blocks[("offset", f["id"], i)] = trig
        found = self._evaluate_blocks(tag, blocks, state, roots) if blocks else {}
        shifts: dict[str, tuple[float, float]] = {}
        for (kind, fid, i), (ok, _unknown) in found.items():
            if kind == "offset" and ok is True:
                dx, dy, _t = scripts[fid]["offsets"][i]
                x, y = shifts.get(fid, (0, 0))
                shifts[fid] = (x + dx, y + dy)
        focuses = focus_mod.tree(files, state["tree"], shifts, state.get("members")) if shifts else base
        branch = {fid: ok for (kind, fid, _i), (ok, _u) in found.items() if kind == "branch"}
        gone = focus_mod.hidden(focuses, branch, set(state.get("completed") or []) | {state.get("current")})
        for f in focuses:
            f["hidden"] = f["id"] in gone
        return focuses

    def _evaluate_blocks(self, tag: str, blocks: dict, state: dict, roots: tuple[str, ...]) -> dict:
        """{key: (True / False / None, [unknown triggers])} of trigger blocks for `tag`: on game memory with live
        state, else on what the save gives (triggers.SavedWorld)."""
        install = Path(roots[0])
        userdata = (self.detect().get("userdata") or {}).get("path")
        dlcs = techtree.owned_dlcs(install, Path(userdata) if userdata else None)
        rules = self._game_rules(roots, live=state.get("source") == "live")
        scripted = triggers_mod.scripted_triggers(roots)
        if state.get("source") == "live" and self.live is not None:
            flags = self._live_save_flags(tag)
            try:
                return self.live.check_conditions(tag, blocks, list(government_mod.ideologies(roots)["colors"]),
                                                  dlcs, scripted, rules, {tag: flags} if flags is not None else None)
            except Exception as exc:   # game closed meanwhile: decided on the save's facts below
                self.log.debug("Focus tree triggers not checked in memory: %s", exc)
        world = triggers_mod.SavedWorld(tag, state.get("completed") or [], dlcs, rules,
                                        gamefiles.tag_order(install, roots[1:]), state.get("flags"))
        out = {}
        for key, block in blocks.items():
            ctx = triggers_mod.Context(world, tag, scripted)
            out[key] = (triggers_mod.evaluate(block, ctx), sorted(ctx.unknown))
        return out

    def _this_game_save(self) -> Path | None:
        """The newest save when the running game process wrote it (a save of an earlier game may belong to another
        campaign), else None."""
        started = ((self.detect().get("process") or {}).get("started"))
        picked = self._pick_save(None)
        try:
            if started and picked and picked[0].stat().st_mtime >= dt.datetime.fromisoformat(started).timestamp():
                return picked[0]
        except (OSError, ValueError):
            pass
        return None

    def _live_save_flags(self, tag: str) -> dict | None:
        """Country flags of `tag` for the running game: from the save this game process wrote (flags are not read
        from memory yet - 2026-10-20: the game's flag name registry is global, the country's own flag store was not
        found). None = not known (has_country_flag stays undecided)."""
        path = self._this_game_save()
        try:
            return self.saves.focus_state(path, tag).get("flags") if path else None
        except SaveFormatError as exc:
            self.log.debug("Country flags not read from the save: %s", exc)
            return None

    def _game_rules(self, roots: tuple[str, ...], live: bool = True) -> dict[str, str]:
        """Game rules {rule: option} for has_game_rule: the defaults of common/game_rules (game + mods) with the
        rules changed in the save (the save keeps only those; 2026-10-20 Po zmianach.hoi4: GER_focus_tree_selection
        = STANDARD_TREE). `live`: the save this game process wrote, else the newest save."""
        rules = dict(triggers_mod.game_rule_defaults(tuple(str(f) for f in gamefiles.merged_files(roots, "common/game_rules"))))
        path = self._this_game_save() if live else (self._pick_save(None) or [None])[0]
        if path is not None and self.saves is not None:
            try:
                rules.update(self.saves.game_rules(path))
            except SaveFormatError as exc:
                self.log.debug("Game rules not read from the save: %s", exc)
        return rules

    def _loc_names(self, install: Path, ids: set[str]) -> dict[str, str]:
        """Localised texts of the game and the mods it runs with."""
        return focus_mod.loc_names(install, ids, mods=self._game_roots(install)[1:])

    def _focus_graphics(self, focuses: list[dict]) -> dict:
        """Icons (by sprite), name plate backgrounds (by status) and the exclusive link of the game's focus screen,
        plus each focus's description; sets f["icon_key"] and f["desc"]."""
        install = self._install_path()
        roots = self._game_roots(install)
        sprites = gfx.sprites(roots)
        icons = {}
        for f in focuses:
            sprite = f.get("icon") if f.get("icon") in sprites else "GFX_goal_unknown"
            if sprite not in icons and sprite in sprites:
                icons[sprite] = gfx.icon_data_uri(sprites[sprite])
            f["icon_key"] = sprite if icons.get(sprite) else None
        descs = self._loc_names(install, {f"{f['id']}_desc" for f in focuses})
        for f in focuses:
            d = descs.get(f"{f['id']}_desc")
            f["desc"] = clean_loc(d, descs) if d and "[" not in d else None
        plate = {"completed": "GFX_focus_completed", "in_progress": "GFX_focus_can_start",
                 "available": "GFX_focus_can_start", "blocked": "GFX_focus_unavailable",
                 "excluded": "GFX_focus_unavailable"}
        link = sprites.get("GFX_focus_link_exclusive")
        return {"icons": icons,
                "plates": {k: gfx.icon_data_uri(sprites[v]) if sprites.get(v) else None for k, v in plate.items()},
                "exclusive_icon": gfx.frame_data_uri(link, 1, 3) if link else None}

    @staticmethod
    def _focus_shown(state: dict, focuses: list[dict], show_hidden: bool) -> tuple[list[dict], dict]:
        """(focuses to draw, {"hidden": count, "shape": key of positions and visibility, "missing": focuses of the
        game's tree not found in the files}) - hidden branches only with `show_hidden`."""
        shown = focuses if show_hidden else [f for f in focuses if not f.get("hidden")]
        known = {f["id"] for f in focuses}
        shape = "|".join(f"{f['id']}:{f['x']:g}:{f['y']:g}:{int(bool(f.get('hidden')))}" for f in shown)
        return shown, {"hidden": sum(1 for f in focuses if f.get("hidden")), "shape": str(hash((state["tree"], shape))),
                       "missing": [m for m in state.get("members") or [] if m not in known]}

    def focus(self, tag: str, show_hidden: bool = False) -> dict:
        """Focus tree of `tag` (game/mod files) laid out like the game's focus screen, with statuses from game
        memory while the game runs (else the newest save); the queue is a plan. Hidden branches (allow_branch) only
        with `show_hidden`."""
        tag = tag.upper()
        try:
            ctx = self._focus_context(tag, live_first=True)
        except SaveFormatError as exc:
            ctx, note = None, f"Focus state not read: {exc}"
        else:
            note = None
        if ctx is None:
            return envelope(DEMO, {"tag": tag, "focuses": demo.focuses(tag), "queue_supported": False},
                            f"{note} {DEMO_NOTE}" if note else DEMO_NOTE)
        state, focuses = ctx
        queue = self._focus_queues().get(f"{tag}:{state['tree']}", [])
        shown, info = self._focus_shown(state, focuses, show_hidden)
        data = {
            "tag": tag, "tree": state["tree"], "current": state["current"], "progress_days": state["progress"],
            "paused": state["paused"], "completed": len(state["completed"]), "focuses": shown,
            "queue": self._with_conditions(tag, focus_mod.validate_queue(focuses, state, queue), focuses, state),
            "queue_supported": False, "hidden_count": info["hidden"], "shape": info["shape"],
            "show_hidden": show_hidden, "missing_in_files": info["missing"][:20], "missing_count": len(info["missing"]),
            "tree_source": "memory" if state.get("members") else "files",
            "focus_source": state["source"], "game_date": state.get("date"), "layout": focus_mod.layout(shown),
            **self._focus_graphics(shown)}
        if state["source"] == "live":
            return envelope(LIVE, data, f"Focus tree {state['tree']} from the game files; state of {tag} from game memory.")
        analysis = state["analysis"]
        header = analysis.get("header") or {}
        data.update(file=analysis["file"], in_game_date=header.get("date"),
                    freshness=save_freshness(analysis["file"]["mtime"], self.detect()))
        return envelope(SAVE, data, f"Focus tree {state['tree']} from the game files; state of {tag} from "
                                    f"{analysis['file']['name']} ({(header.get('date') or {}).get('text') or '?'}). "
                                    "Snapshot - not live.")

    def focus_state(self, tag: str, show_hidden: bool = False) -> dict:
        """State of `tag`'s focus tree without the graphics (for Live / On refresh updates of the tree): tree id,
        current focus and progress, each focus's status and progress, the checked plan and its next focus."""
        tag = tag.upper()
        try:
            ctx = self._focus_context(tag, live_first=True)
        except SaveFormatError as exc:
            return envelope(UNAVAILABLE, None, f"Focus state not read: {exc}")
        if ctx is None:
            return envelope(UNAVAILABLE, None, "Needs the running game or a save")
        state, focuses = ctx
        queue = focus_mod.validate_queue(focuses, state, self._focus_queues().get(f"{tag}:{state['tree']}", []))
        queue = self._with_conditions(tag, queue, focuses, state)
        by_id = {f["id"]: f for f in focuses}
        nxt = next((q for q in queue if q["ok"]), None)
        shown, info = self._focus_shown(state, focuses, show_hidden)
        return envelope(LIVE if state["source"] == "live" else SAVE, {
            "tag": tag, "tree": state["tree"], "current": state["current"], "progress_days": state["progress"],
            "focus_source": state["source"], "queue": queue, "game_date": state.get("date"), "shape": info["shape"],
            "statuses": {f["id"]: {"status": f["status"], "progress": f["progress"], "missing": f["missing"]} for f in shown},
            "next": {"id": nxt["id"], "name": by_id[nxt["id"]]["name"], "days": by_id[nxt["id"]]["days"]} if nxt else None,
        }, "Focus state from game memory." if state["source"] == "live" else "Focus state from the newest save.")

    def focus_autostart(self, apply: bool) -> dict:
        """Next focus of the PLAYER's plan, started in game memory when no focus is selected (apply=True; LOCAL write,
        single player, or multiplayer when allowed). The focus's `available` conditions are checked on game memory
        (triggers.py): not met -> "waiting"; ones the app cannot check and effects on picking are left to the player
        ("manual"). state: busy (a focus runs), empty (no valid focus in the plan), waiting, manual, ready (preview),
        started."""
        if self.live is None:
            raise NotFound("Live game access is disabled")
        live = self.live.focus(None)
        tag = live["tag"]
        base = {"tag": tag, "current": live["current"], "focus": None, "name": None, "reason": None}
        if live["current"]:
            return {**base, "state": "busy"}
        ctx = self._focus_context(tag, live_first=True)
        if ctx is None:
            return {**base, "state": "empty", "reason": "focus tree not readable"}
        state, focuses = ctx
        by_id = {f["id"]: f for f in focuses}
        queue = focus_mod.validate_queue(focuses, state, self._focus_queues().get(f"{tag}:{state['tree']}", []))
        nxt = next((q for q in queue if q["ok"]), None)
        if nxt is None:
            return {**base, "state": "empty"}
        f = by_id[nxt["id"]]
        out = {**base, "focus": f["id"], "name": f["name"], "days": f["days"]}
        if f.get("select_effect"):
            return {**out, "state": "manual", "reason": "has effects when it is picked - start it in the game"}
        if f.get("start_conditions"):
            met, unknown = self._focus_available(tag, [f["id"]])[f["id"]]
            if met is False:
                return {**out, "state": "waiting", "reason": "its conditions (available) are not met yet"}
            if met is None:
                return {**out, "state": "manual", "reason": "has conditions the app cannot check"
                        + (f" ({', '.join(unknown[:4])})" if unknown else "") + " - start it in the game"}
        if not apply:
            return {**out, "state": "ready"}
        if self.live.game_mode() != "SINGLEPLAYER":
            # a focus written into memory is not sent to the other players: tested 2026-10-16, it desyncs the game
            return {**out, "state": "manual", "reason": "multiplayer - pick it in the game (a focus started by the app "
                                                        "desyncs a multiplayer game)"}
        self.live.start_focus(f["id"])
        return {**out, "state": "started"}

    def _with_conditions(self, tag: str, queue: list[dict], focuses: list[dict], state: dict) -> list[dict]:
        """Queue entries with "conditions": True / False / None (`available` of the focus in the running game; None =
        the app cannot tell, "unknown" names the triggers) - only with live state, only for focuses that have one."""
        by_id = {f["id"]: f for f in focuses}
        ids = [q["id"] for q in queue if q["ok"] and by_id.get(q["id"], {}).get("start_conditions")]
        if state.get("source") != "live" or not ids:
            return queue
        try:
            found = self._focus_available(tag, ids)
        except Exception as exc:   # game closed meanwhile, unreadable memory: the plan is shown without them
            self.log.debug("Focus conditions not checked: %s", exc)
            return queue
        return [{**q, "conditions": found[q["id"]][0], "unknown": found[q["id"]][1]} if q["id"] in found else q
                for q in queue]

    def _focus_available(self, tag: str, focus_ids: list[str]) -> dict[str, tuple]:
        """{id: (True / False / None, [unknown triggers])} of the focuses' `available` blocks in the running game."""
        install = self._install_path()
        if install is None:
            return {fid: (None, []) for fid in focus_ids}
        roots = self._game_roots(install)
        userdata = (self.detect().get("userdata") or {}).get("path")
        conditions = triggers_mod.focus_conditions(focus_mod.focus_files(install, [Path(r) for r in roots[1:]]))
        blocks = {fid: conditions.get(fid) or [] for fid in focus_ids}
        dlcs = techtree.owned_dlcs(install, Path(userdata) if userdata else None)
        return self.live.check_conditions(tag, blocks, list(government_mod.ideologies(roots)["colors"]),
                                          dlcs, triggers_mod.scripted_triggers(roots), self._game_rules(roots))

    def _focus_context_cached(self, tag: str, wait: bool = True):
        """_focus_context() cached per newest save (parsing a binary save takes seconds). With wait=False a
        missing context is built in the background and None is returned meanwhile ("loading")."""
        picked = self._pick_save(None)
        key = (tag, picked[0].name if picked else None, picked[0].stat().st_mtime if picked else None)
        cache = getattr(self, "_focus_cache", None)
        if cache is not None and cache[0] == key:
            return cache[1]
        if wait:
            self._focus_cache = (key, self._focus_context(tag))
            return self._focus_cache[1]
        if getattr(self, "_focus_loading", None) != key:
            self._focus_loading = key

            def build() -> None:
                try:
                    self._focus_cache = (key, self._focus_context(tag))
                except (SaveFormatError, OSError, ValueError) as exc:
                    self.log.warning("Focus tree for %s not read: %s", tag, exc)
            threading.Thread(target=build, daemon=True).start()
        return None

    def live_date(self) -> dict:
        """The player's country and the game date from game memory (the monthly trade advice watches the month)."""
        if self.live is None:
            raise NotFound("Live game access is disabled")
        live = self.live.focus(None)
        return {"data": {"tag": live["tag"], "date": live.get("date")}}

    def live_focus(self, tag: str | None = None) -> dict:
        """Live current focus of `tag` (default: player) + the next focus of the planned queue.

        Completed focuses come from game memory (the country's completed list), so the queue moves on without
        a new save; a focus newly in that list is reported once as `event`. `idle` = no focus selected: the
        moment to start the next one (the app notifies; the game has no command to start a focus)."""
        if self.live is None:
            raise NotFound("Live game access is disabled")
        live = self.live.focus(tag)
        tag = live["tag"]
        ctx = self._focus_context_cached(tag, wait=False)
        if ctx is None:  # tree still being read: report the live focus without queue information
            return {"data": {"tag": tag, "tree": None, "current": live["current"], "current_name": live["current"],
                             "progress_days": live["progress_days"], "days": None, "idle": live["current"] is None,
                             "next": None, "completed_since_save": [], "event": None, "loading": True,
                             "read_at": live["read_at"]}}
        state, focuses = ctx
        by_id = {f["id"]: f for f in focuses}
        tracks = getattr(self, "_focus_tracks", None)
        if tracks is None:
            tracks = self._focus_tracks = {}
        track = tracks.setdefault((tag, state["tree"]), {"seen": None, "event": None})
        if track["seen"] is not None:
            new = [f for f in live["completed"] if f not in track["seen"]]
            if new:
                # kept (not consumed): several pollers (watcher, focus view) must all see it; clients de-duplicate by id
                track["event"] = {"id": f"{tag}:{new[-1]}:{len(live['completed'])}", "completed": new[-1],
                                  "name": (by_id.get(new[-1]) or {}).get("name", new[-1]), "all": new,
                                  "at": live["read_at"]}
                self.log.info("Focus completed (live) %s: %s", tag, ", ".join(new))
        track["seen"] = set(live["completed"])
        event = track["event"] if track["event"] and live["read_at"] - track["event"]["at"] < 600 else None
        done = list(dict.fromkeys(state["completed"] + live["completed"]))
        now = {"completed": done, "current": live["current"], "progress": live["progress_days"]}
        queue = focus_mod.validate_queue(focuses, now, self._focus_queues().get(f"{tag}:{state['tree']}", []))
        nxt = next((q for q in queue if q["ok"]), None)
        cur = by_id.get(live["current"] or "")
        return {"data": {
            "tag": tag, "tree": state["tree"], "current": live["current"],
            "current_name": cur["name"] if cur else None, "progress_days": live["progress_days"],
            "days": cur["days"] if cur else None, "idle": live["current"] is None,
            "next": {"id": nxt["id"], "name": by_id[nxt["id"]]["name"], "days": by_id[nxt["id"]]["days"]} if nxt else None,
            "completed_since_save": [f for f in live["completed"] if f not in state["completed"]],
            "event": event, "read_at": live["read_at"],
        }}

    def live_session(self) -> dict:
        """Countries that exist in the running game (own at least one state, game memory) and its players.

        Players: the local player's country from memory; the account name from the newest save that lists it.
        Other players of a multiplayer session are not read from memory yet (not verified in multiplayer)."""
        if self.live is None:
            raise NotFound("Live game access is disabled")
        live = self.live.session()
        # names as in the country list (ideology-specific from the newest save's ruling party)
        names = {c["tag"]: c["name"] for c in self.countries()["data"]}
        account = None
        picked = self._pick_save(None)
        if picked is not None:
            try:
                header = self.saves.analyse(picked[0]).get("header") or {}
            except SaveFormatError:
                header = {}
            account = next((p.get("name") for p in header.get("players") or []
                            if p.get("tag") == header.get("player_tag")), None)
        players = [{"tag": tag, "name": account, "local": True, "name_source": "save" if account else None}
                   for tag in live["players"][:1]]
        countries = [{"tag": tag, "name": names.get(tag, tag), "states": n,
                      "player": account if live["players"][:1] == [tag] else None}
                     for tag, n in live["states"].items() if n > 0]
        countries.sort(key=lambda c: -c["states"])
        mode = live["game_mode"]
        note = (f"{len(countries)} countries own states in the running game (game memory, "
                f"{(live['process'] or {}).get('version')}).")
        return envelope(LIVE, {"game_mode": mode, "players": players, "countries": countries,
                               "other_players_readable": False, "read_at": live["read_at"]}, note)

    def live_equipment_needs(self, tag: str) -> dict:
        """Needs of the divisions of `tag` LIVE (game memory): per archetype needed / in divisions / stockpile /
        missing / shortfall like the save-based table (equipment()), the stockpile's variants and produced a day."""
        if self.live is None:
            raise NotFound("Live game access is disabled")
        tag = tag.upper()
        status = self.live.equipment_status(tag)
        stock = self.live_stockpile(tag)["data"]["entries"]
        install = self._install_path()
        rows = status["equipment"]
        names = self._equipment_names(install, set(rows)) if install else {}
        variants: dict[str, list] = {}
        for e in stock:
            a = e.get("archetype") or e.get("type") or f"#{e['id']}"
            variants.setdefault(a, []).append({"id": e["id"], "archetype": e.get("type") or a, "archetype_name": e.get("type_name") or a,
                                               "variant": e.get("name") or None, "amount": e["amount"], "pool": "stockpile"})
        groups = []
        for a in set(rows) | set(variants):
            need, held, stockpile, produced = rows.get(a, [0, 0, 0, 0])
            missing = max(0.0, need - held)
            groups.append({"archetype": a, "name": names.get(a) or a.replace("_", " ").capitalize(), "need": need, "held": held,
                           "stockpile": stockpile, "produced": produced, "missing": missing,
                           "shortfall": max(0.0, missing - stockpile), "variants": variants.get(a, [])})
        groups = [g for g in groups if g["need"] or g["held"] or g["stockpile"] or g["variants"]]
        groups.sort(key=lambda g: (-g["shortfall"], g["name"]))
        return envelope(LIVE, {"tag": tag, "groups": groups, "read_at": status["read_at"],
                               "icons": self._equipment_icons(install, tag, [g["archetype"] for g in groups]) if install else {}},
                        f"Needs of the divisions of {tag} from game memory.")

    def live_stockpile(self, tag: str | None = None) -> dict:
        """Live stockpile (game memory) with archetype / equipment type from the newest save's variant table."""
        if self.live is None:
            raise NotFound("Live game access is disabled")
        live = self.live.stockpile(tag)
        install = self._install_path()
        picked = self._pick_save(None)
        variants, names, archetypes = {}, {}, {}
        if install:
            if picked is not None and not all(e.get("type") for e in live["entries"]):
                try:   # the type of a variant not read from memory: the newest save's variant table
                    variants = self.saves.equipment(picked[0], live["tag"])["variants"]
                except SaveFormatError:
                    variants = {}
            archetypes = deficit.tables(install, [Path(r) for r in self._game_roots(install)[1:]])[1]
        types = {e.get("type") or (variants.get(e["id"]) or {}).get("type") for e in live["entries"]} - {None}
        if install:
            names = self._equipment_names(install, types | {deficit.archetype_of(t, archetypes) for t in types})
        entries = []
        for e in live["entries"]:
            v = variants.get(e["id"]) or {}
            eq_type = e.get("type") or v.get("type")
            entries.append({**e, "type": eq_type, "type_name": names.get(eq_type, eq_type) if eq_type else None,
                            "archetype": deficit.archetype_of(eq_type, archetypes) if eq_type else None,
                            "name": e["name"] or v.get("name")})
        return {"data": {"tag": live["tag"], "entries": entries, "read_at": live["read_at"]}}

    def _equipment_names(self, install: Path, keys: set[str]) -> dict[str, str]:
        """Names of equipment keys (types and archetypes) from the localisation of the game and the mods it runs with;
        the game's equipment_l_<lang>.yml for keys none of them names."""
        names = dict(gamefiles.equipment_names(install))
        loc = self._loc_names(install, set(keys))
        loc.update(self._loc_names(install, {r for v in loc.values() for r in LOC_REF.findall(v)} - set(loc)))
        names.update({k: clean_loc(loc[k], loc) for k in keys if loc.get(k) and "[" not in loc[k]})
        return names

    def _focus_queue_file(self) -> Path:
        return Path(self.data_dir) / "focus-queues.json"

    def _focus_queues(self) -> dict:
        try:
            data = json.loads(self._focus_queue_file().read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def set_focus_queue(self, tag: str, queue: list) -> dict:
        """Stores the planned order of focuses for `tag` (its current tree) and returns it validated."""
        tag = tag.upper()
        if not isinstance(queue, list) or len(queue) > 200 or not all(isinstance(q, str) and len(q) < 200 for q in queue):
            raise ReportError("queue must be a list of up to 200 focus ids")
        ctx = self._focus_context(tag, live_first=True)   # checked against the running game, like the tree shows it
        if ctx is None:
            raise NotFound("No game installation or save to read the focus tree from")
        state, focuses = ctx
        queues = self._focus_queues()
        queues[f"{tag}:{state['tree']}"] = queue
        self._focus_queue_file().write_text(json.dumps(queues, indent=1), encoding="utf-8")
        self.log.info("Focus queue %s (%s): %s", tag, state["tree"], ", ".join(queue) or "empty")
        return {"data": focus_mod.validate_queue(focuses, state, queue)}

    def equipment(self, tag: str) -> dict:
        """Stockpile and convoys of `tag` from the newest save, names from the game files; DEMO without them."""
        tag = tag.upper()
        install = self._install_path()
        picked = self._pick_save(None)
        if install and picked is not None:
            try:
                data = self.saves.equipment(picked[0], tag)
            except SaveFormatError as exc:
                note = f"Equipment not read from {picked[0].name}: {exc}"
            else:
                analysis = data["analysis"]
                header = analysis.get("header") or {}
                userdata = (self.detect().get("userdata") or {}).get("path")
                mods = gamefiles.enabled_mods(Path(userdata)) if userdata else []
                needs, archetypes = deficit.tables(install, mods)
                types = {v.get("type") for v in data["variants"].values()} - {None}
                names = self._equipment_names(install, types | {deficit.archetype_of(t, archetypes) for t in types}
                                              | set(archetypes.values()))
                items = save_equipment.rows(data, names)
                balance = deficit.compute(data, needs, archetypes)
                groups: dict[str, dict] = {}
                for item in items:
                    if item["pool"] != "stockpile":
                        continue
                    a = deficit.archetype_of(item["archetype"], archetypes)
                    g = groups.setdefault(a, {"archetype": a, "name": names.get(a) or a.replace("_", " ").capitalize(),
                                              "variants": []})
                    g["variants"].append(item)
                for a, b in balance.items():
                    if b["need"] or b["stockpile"]:
                        groups.setdefault(a, {"archetype": a, "name": names.get(a) or a.replace("_", " ").capitalize(),
                                              "variants": []})
                for a, g in groups.items():
                    g.update({k: balance.get(a, {}).get(k, 0.0) for k in ("need", "held", "missing", "shortfall")})
                    g["stockpile"] = sum(v["amount"] for v in g["variants"])
                ordered = sorted(groups.values(), key=lambda g: (-g["shortfall"], g["name"]))
                return envelope(SAVE, {
                    "tag": tag, "items": items, "groups": ordered,
                    "icons": self._equipment_icons(install, tag, [g["archetype"] for g in ordered]),
                    "designs": equipment_changes.designs(data, tag),
                    "editable": False, "file": analysis["file"], "in_game_date": header.get("date"),
                    "player_tag": header.get("player_tag"),
                    "freshness": save_freshness(analysis["file"]["mtime"], self.detect()),
                }, f"Stockpile of {tag} from {picked[0].name} ({(header.get('date') or {}).get('text') or '?'}). "
                   "Snapshot - not live.")
        else:
            note = None
        return envelope(DEMO, {"tag": tag, "items": demo.equipment(tag), "editable": False},
                        f"{note} {DEMO_NOTE}" if note else DEMO_NOTE)

    def _equipment_icons(self, install: Path, tag: str, archetypes: list[str]) -> dict[str, str]:
        """{archetype: data URI} - the game's equipment icon: the country's own (GFX_<TAG>_<archetype>_medium), else the
        generic one (GFX_archetype_<archetype>_medium); archetypes without an icon are left out."""
        roots = self._game_roots(install)
        sprites = gfx.sprites(roots)
        out = {}
        for a in archetypes[:200]:
            # designer archetypes (tank chassis, plane airframes) show the icon of the equipment they replace
            base = re.sub(r"^cv_", "", a)
            alias = {"small_plane_airframe": "fighter_equipment", "small_plane_cas_airframe": "CAS_equipment",
                     "small_plane_naval_bomber_airframe": "CAS_equipment", "medium_plane_airframe": "heavy_fighter_equipment",
                     "medium_plane_fighter_airframe": "heavy_fighter_equipment", "large_plane_airframe": "strat_bomber_equipment",
                     "train_equipment": "train"}.get(base) or re.sub(r"_chassis$", "_equipment", base)
            plain = re.sub(r"_(?:destroyer|aa|artillery|flame|amphibious)(?=_equipment$)", "", alias)   # tank variants
            name = next((n for n in (f"GFX_{tag}_{a}_medium", f"GFX_archetype_{a}_medium", f"GFX_archetype_{alias}_medium",
                                     f"GFX_{a}_medium", f"GFX_archetype_{plain}_medium") if n in sprites), None)
            uri = gfx.sprite_uri(roots, name) if name else None
            if uri:
                out[a] = uri
        return out

    # -- save files ---------------------------------------------------------------------
    def saves_list(self) -> dict:
        directory = self.integration.saves_dir()
        if directory is None:
            return envelope(UNAVAILABLE, [], "Save folder not found")
        game = self.detect()
        items = list_saves(directory)
        for item in items:
            item["freshness"] = save_freshness(item["mtime"], game)
        return envelope(SAVE, {"directory": str(directory), "saves": items}, SAVE_NOTE)

    def save_analysis(self, name: str | None) -> dict:
        directory = self.integration.saves_dir()
        if directory is None or self.saves is None:
            return envelope(UNAVAILABLE, None, "Save folder not found")
        items = list_saves(directory)
        if not items:
            return envelope(UNAVAILABLE, None, "No save files found")
        if name:
            match = next((i for i in items if i["name"] == name), None)  # only names that exist in the folder
            if match is None:
                raise NotFound(f"Unknown save: {name}")
        else:
            match = items[0]
        result = self.saves.analyse(directory / match["name"])
        game = self.detect()
        result["freshness"] = save_freshness(result["file"]["mtime"], game)
        result["is_latest"] = match["name"] == items[0]["name"]
        running = ((game.get("install") or {}).get("version") or {}).get("display") if game.get("process") else None
        saved = (result.get("header") or {}).get("version")
        result["version_check"] = {
            "running": running, "save": saved,
            "match": None if not (running and saved) else version_core(running) == version_core(saved),
        }
        return envelope(SAVE, result, SAVE_NOTE)

    def _pick_save(self, name: str | None) -> tuple[Path, dict] | None:
        directory = self.integration.saves_dir()
        if directory is None or self.saves is None:
            return None
        items = list_saves(directory)
        if not items:
            return None
        if name:
            match = next((i for i in items if i["name"] == name), None)
            if match is None:
                raise NotFound(f"Unknown save: {name}")
        else:
            match = items[0]
        return directory / match["name"], {"is_latest": match["name"] == items[0]["name"]}

    def _controlled_buildings(self, path: Path, install: Path, tag: str) -> list[str]:
        """Province buildings in provinces `tag` controls (province controller, else the state owner)."""
        try:
            save = self.saves.states(path)
        except SaveFormatError:
            return []
        state_of = {prov: sid for sid, d in gamefiles.state_definitions(install).items() for prov in d["provinces"]}
        out = []
        for prov, info in save["provinces"].items():
            owner = (save["states"].get(state_of.get(int(prov))) or {}).get("owner")
            if (info.get("controller") or owner) == tag:
                out.extend(b for b, level in (info.get("buildings") or {}).items() if level)
        return sorted(set(out))

    def _game_roots(self, install: Path) -> tuple[str, ...]:
        userdata = (self.detect().get("userdata") or {}).get("path")
        mods = gamefiles.enabled_mods(Path(userdata)) if userdata else []
        return tuple(str(r) for r in [install, *mods])

    def spirits(self, tag: str) -> dict:
        """National spirits of `tag` (newest save) with icon, name, description and every modifier."""
        tag = tag.upper()
        install = self._install_path()
        picked = self._pick_save(None)
        if install is None or picked is None:
            return envelope(UNAVAILABLE, None, "Needs the game installation and a save")
        try:
            state = self.saves.politics(picked[0], tag)
        except SaveFormatError as exc:
            return envelope(UNAVAILABLE, None, str(exc))
        analysis = state.pop("analysis")
        state.pop("_all", None)
        live = self._live_ideas(tag, state)
        roots = self._game_roots(install)
        defs = modifiers.definitions(roots)
        out = self._present(modifiers.spirits(state, defs), install, roots)
        return envelope(SAVE, {"tag": tag, "spirits": out, "ideas_source": "live" if live else "save",
                               "file": analysis["file"],
                               "in_game_date": (analysis.get("header") or {}).get("date")},
                        f"National spirits from {analysis['file']['name']}; icons and texts from the game files.")

    def government(self, tag: str) -> dict:
        """Laws & Government, Research & Production, Military Staff of `tag` (newest save), one entry per slot."""
        tag = tag.upper()
        install = self._install_path()
        picked = self._pick_save(None)
        if install is None or picked is None:
            return envelope(UNAVAILABLE, None, "Needs the game installation and a save")
        try:
            state = self.saves.politics(picked[0], tag)
        except SaveFormatError as exc:
            return envelope(UNAVAILABLE, None, str(exc))
        analysis = state.pop("analysis")
        state.pop("_all", None)
        live = self._live_ideas(tag, state)
        live_advisors = self._live_advisors(tag, state)
        live_mios = self._live_mios(tag, state)
        roots = self._game_roots(install)
        defs = modifiers.definitions(roots)
        groups = government_mod.sections(state, defs)
        flat = [it for items in groups.values() for it in items]
        shown = iter(self._present(flat, install, roots))
        data = {name: [next(shown) for _ in items] for name, items in groups.items()}
        data["mios"] = self._mios(state, tag, install, roots)
        return envelope(SAVE, {"tag": tag, **data, "ideas_source": "live" if live else "save",
                               "advisors_source": "live" if live_advisors else "save", 
                               "mios_source": "live" if live_mios else "save", "file": analysis["file"],
                               "in_game_date": (analysis.get("header") or {}).get("date")},
                        f"Laws, companies and advisors from {analysis['file']['name']}.")

    def resources(self, tag: str) -> dict:
        """Resources of `tag` (newest save): produced, to market, sold, imported (with the selling countries),
        available at home and used by production, per resource; icons from the game's resource strip."""
        tag = tag.upper()
        install = self._install_path()
        picked = self._pick_save(None)
        if install is None or picked is None:
            return envelope(UNAVAILABLE, None, "Needs the game installation and a save")
        try:
            state = self.saves.politics(picked[0], tag)
        except SaveFormatError as exc:
            return envelope(UNAVAILABLE, None, str(exc))
        analysis = state.pop("analysis")
        everyone = state.pop("_all", {})
        res = state["resources"]
        roots = self._game_roots(install)
        order = resource_order(roots)
        sellers: dict[str, list] = {}
        live = self._live_resources(tag, list(order))
        if live:
            res = {**{k: live[k] for k in ("produced", "to_market", "exported", "imported", "available", "used")},
                   "exports": [{"receiver": d["buyer"], "resource": d["resource"], "amount": d["amount"]}
                               for d in live["exports"]]}
            for deal in live["imports"]:
                if deal["amount"] and deal["seller"]:
                    sellers.setdefault(deal["resource"], []).append({"country": deal["seller"], "amount": deal["amount"]})
        else:
            for other, st in everyone.items():
                for deal in (st.get("resources") or {}).get("exports", []):
                    if deal["receiver"] == tag and deal["amount"]:
                        sellers.setdefault(deal["resource"], []).append({"country": other, "amount": deal["amount"]})
        keys = set(order) | set().union(*[set(v) for k, v in res.items() if isinstance(v, dict)])
        names = self._loc_names(install, {f"PRODUCTION_MATERIALS_{k.upper()}" for k in keys})
        rows = []
        for k in sorted(keys, key=lambda k: (order.get(k, {}).get("frame", 99), k)):
            get = lambda part: round(res[part].get(k, 0.0), 3)  # noqa: E731
            rows.append({"resource": k, "name": names.get(f"PRODUCTION_MATERIALS_{k.upper()}", k.capitalize()),
                         "frame": order.get(k, {}).get("frame"), "produced": get("produced"),
                         "to_market": get("to_market"), "exported": get("exported"), "imported": get("imported"),
                         "available": get("available"), "used": get("used"),
                         "balance": round(get("available") - get("used"), 3),
                         "buyers": sorted(({"country": d["receiver"], "amount": d["amount"]} for d in res["exports"]
                                           if d["resource"] == k and d["amount"]), key=lambda d: -d["amount"]),
                         "sellers": sorted(sellers.get(k, []), key=lambda d: -d["amount"])})
        sprites = gfx.sprites(roots)
        strip = sprites.get("GFX_resources_strip")
        return envelope(SAVE, {"tag": tag, "resources": rows, "icons": gfx.icon_data_uri(strip) if strip else None,
                               "icon_frames": max([v["frame"] for v in order.values()] or [0]),
                               "resources_source": "live" if live else "save",
                               "file": analysis["file"], "in_game_date": (analysis.get("header") or {}).get("date")},
                        "Resources per day from game memory." if live
                        else f"Resources per day from {analysis['file']['name']}.")

    def _live_ideas(self, tag: str, state: dict) -> bool:
        """Replaces state["ideas"] and state["dynamic_modifiers"] with the live ones of `tag`; False when the game
        cannot be read."""
        if self.live is None:
            return False
        try:
            live = self.live.ideas(tag)
        except Exception:  # live data is optional: the save values stay
            return False
        state["ideas"], state["dynamic_modifiers"] = live["ideas"], live["dynamic_modifiers"]
        return True

    def _live_advisors(self, tag: str, state: dict) -> bool:
        """Replaces state["advisors"] with the live hired advisors of `tag` (characters stay from the save)."""
        if self.live is None:
            return False
        try:
            state["advisors"] = self.live.advisors(tag)["advisors"]
        except Exception:  # live data is optional: the save values stay
            return False
        return True

    @staticmethod
    @functools.lru_cache(maxsize=2)
    def _technologies(roots: tuple[str, ...]) -> tuple[dict, dict]:
        """({id: {"cost", "start_year", "categories", "parents", "needs", "excludes"}}, defines) from
        common/technologies and the defines. parents = technologies whose path leads here, needs = dependencies,
        excludes = XOR."""
        techs: dict[str, dict] = {}
        defines = {"BASE_TECH_COST": 110.0, "BASE_YEAR_AHEAD_PENALTY_FACTOR": 2.0}
        for root in map(Path, roots):
            for path in sorted((root / "common" / "technologies").glob("*.txt")):
                try:
                    items = text_mod.parse(re.sub(r"#[^\n]*", "", path.read_text(encoding="utf-8-sig", errors="replace")))
                except Exception:
                    continue
                for block in (v for k, v in (i for i in items if isinstance(i, tuple)) if k == "technologies"):
                    # @1936 = 2 at the start of the file: constants used in folder positions
                    consts = {k: v for k, v in (i for i in block if isinstance(i, tuple)) if k.startswith("@")} \
                        if isinstance(block, list) else {}
                    for tid, body in (i for i in block if isinstance(i, tuple)) if isinstance(block, list) else []:
                        if not isinstance(body, list):
                            continue
                        cost = text_mod.get(body, "research_cost")
                        year = text_mod.get(body, "start_year")
                        cats = text_mod.get(body, "categories")
                        deps = text_mod.get(body, "dependencies")
                        xor = text_mod.get(body, "XOR")
                        try:
                            techs[tid] = {
                                "cost": float(cost) if cost is not None else None,
                                "start_year": int(float(year)) if year is not None else None,
                                "categories": [c for c in cats if isinstance(c, str)] if isinstance(cats, list) else [],
                                "leads_to": [text_mod.get(p, "leads_to_tech") for k, p in body
                                             if k == "path" and isinstance(p, list)
                                             and isinstance(text_mod.get(p, "leads_to_tech"), str)],
                                "needs": [k for k, _v in deps if isinstance(k, str)] if isinstance(deps, list) else [],
                                "excludes": [x for x in xor if isinstance(x, str)] if isinstance(xor, list) else [],
                                # shown in a tree folder and not limited to some countries by a script condition
                                "in_tree": text_mod.get(body, "folder") is not None
                                and text_mod.get(body, "allow") is None,
                                # a technology can sit in several tabs (one folder block each)
                                "folders": [text_mod.get(f, "name") for k, f in body
                                            if k == "folder" and isinstance(f, list)
                                            and isinstance(text_mod.get(f, "name"), str)],
                                "positions": {text_mod.get(f, "name"): _tech_xy(text_mod.get(f, "position"), consts)
                                              for k, f in body if k == "folder" and isinstance(f, list)
                                              and isinstance(text_mod.get(f, "name"), str)},
                                # equipment technologies are the big items of the tree
                                "big": text_mod.get(body, "enable_equipments") is not None,
                                # the game names a technology without its own text after its first equipment
                                "equipment": next((e for e in text_mod.get(body, "enable_equipments") or []
                                                   if isinstance(e, str)), None)
                                if isinstance(text_mod.get(body, "enable_equipments"), list) else None}
                        except (TypeError, ValueError):
                            continue
            for path in sorted((root / "common" / "defines").glob("*.lua")):
                src = path.read_text(encoding="utf-8-sig", errors="replace")
                for name in defines:
                    m = re.search(rf"^\s*{name}\s*=\s*(-?[0-9.]+)", src, re.M)
                    if m:
                        defines[name] = float(m.group(1))
        for tid, t in techs.items():
            t.setdefault("parents", [])
            for child in t["leads_to"]:
                if child in techs:
                    techs[child].setdefault("parents", []).append(tid)
        return techs, defines

    def _tech_names(self, install: Path, ids: set[str], techs: dict) -> dict[str, str]:
        """{technology id: name as the game shows it}: its own text, else the text of its first equipment
        (infantry_weapons1 -> infantry_equipment_1 "Infantry Equipment I"), else the id made readable."""
        keys = set(ids) | {techs[t]["equipment"] for t in ids if techs.get(t, {}).get("equipment")}
        names = self._loc_names(install, keys)
        names.update(self._loc_names(install, {r for v in names.values() for r in LOC_REF.findall(v)} - set(names)))
        out = {}
        for t in ids:
            key = t if names.get(t) else techs.get(t, {}).get("equipment")
            text = clean_loc(names[key], names) if key and names.get(key) else None
            out[t] = text or t.replace("_", " ").capitalize()
        return out

    def construction(self, tag: str) -> dict:
        """Construction queue of `tag` as the game's construction screen shows it (game memory): building, state,
        levels, factories assigned and progress of the current level; names and icons from the game files."""
        tag = tag.upper()
        install = self._install_path()
        if install is None:
            return envelope(UNAVAILABLE, None, "Needs the game installation")
        if self.live is None:
            return envelope(UNAVAILABLE, None, "Needs the running game")
        try:
            found = self.live.construction(tag)
        except Exception as exc:  # game not running, main menu, other version
            return envelope(UNAVAILABLE, None, f"Needs the running game: {exc}")
        roots = self._game_roots(install)
        defs = construction_mod.buildings(roots)
        strip = construction_mod.icon_strip(roots)
        lines = found["lines"]
        ends = {p for line in lines for p in (line["path"][:1] + line["path"][-1:])}
        names = self._loc_names(install, {line["building"] for line in lines} | {f"VICTORY_POINTS_{p}" for p in ends})
        provinces = {p: sid for sid, d in gamefiles.state_definitions(install).items() for p in d["provinces"]}
        out = construction_mod.rows(lines, {k: clean_loc(v, names) for k, v in names.items()},
                                    gamefiles.state_names(install), construction_mod.max_factories(roots),
                                    found.get("date"), defs, provinces,
                                    {p: names[f"VICTORY_POINTS_{p}"] for p in ends if f"VICTORY_POINTS_{p}" in names})
        for row in out:
            frame = (defs.get(row["building"]) or {}).get("icon_frame")
            row["icon"] = gfx.frame_data_uri(strip[0], frame, strip[1]) if strip and frame else None
        factories = found.get("factories")
        if factories:
            sprites = gfx.sprites(roots)
            icons = {task: gfx.icon_data_uri(sprites[name]) if sprites.get(name) else None
                     for task, name in construction_mod.TASK_SPRITES.items()}
            factories = {**factories, "assigned": sum(row["factories"] for row in out), "icons": icons}
        forecast = self._construction_forecast(tag, out, factories, roots, found.get("date"))
        return envelope(LIVE, {"tag": tag, "lines": out, "factories": factories, "construction_source": "live",
                               "game_date": found.get("date"), "forecast": forecast},
                        "Construction queue from game memory.")

    def _construction_forecast(self, tag: str, lines: list[dict], civil: dict | None, roots, today: dict | None) -> dict | None:
        """The queue played forward (construction.forecast): each row gets "finish_days" / "finish" (when its last
        level is done); {"now", 90, 180, 365: {"civ", "mil", "dock"}} factories, None without the factory counts."""
        if not civil or not today:
            return None
        try:
            fac = self.live.factories(tag)
        except Exception:  # the queue is still shown
            return None
        counts = {"civ": fac["civilian"]["total"], "mil": fac["military"]["total"], "dock": fac["dockyards"]["total"]}
        share = civil["consumer_goods"] / civil["total"] if civil.get("total") else 0.0
        result = construction_mod.forecast(lines, civil["free"], counts, share, construction_mod.max_factories(roots))
        for row, days in zip(lines, result["lines"]):
            row["finish_days"] = days
            row["finish"] = construction_mod.game_date_after(today, days) if days else None
        return {"now": counts, **{str(k): v for k, v in result["factories"].items()},
                "dates": {str(k): construction_mod.game_date_after(today, k)["text"] for k in construction_mod.FORECAST_MARKS}}

    def construction_advice(self, tag: str) -> dict:
        """Where `tag` can build factories (construction.where_to_build): its owned and controlled states with free
        building slots (live states, state categories of the game and mods, levels already queued there)."""
        tag = tag.upper()
        install = self._install_path()
        if install is None or self.live is None:
            return envelope(UNAVAILABLE, None, "Needs the game installation and the running game")
        states = self._states_live(None)
        if not states["data"]:
            return envelope(UNAVAILABLE, None, states["note"])
        roots = self._game_roots(install)
        defs = construction_mod.buildings(roots)
        queued: dict[int, int] = {}
        try:
            for line in self.live.construction(tag)["lines"]:
                if (defs.get(line["building"]) or {}).get("shares_slots") and line.get("levels"):
                    queued[line.get("location")] = queued.get(line.get("location"), 0) + line["levels"]
        except Exception:  # without the queue the slots are still known
            pass
        rows = construction_mod.where_to_build(states["data"], tag, construction_mod.state_slots(roots), defs, queued)
        return envelope(LIVE, {"tag": tag, "states": rows[:40], "total": len(rows),
                               "free": sum(r["free"] for r in rows)},
                        "Free building slots of the state categories; slots added by technologies or state modifiers "
                        "are not counted.")

    def construction_sort(self, apply: bool, kind: str = "civ") -> dict:
        """Player's construction queue with civilian ("civ") or military ("mil") factories closest to completion first
        (live/service.py sort_construction); moved lines named by their state like the construction tab."""
        if kind not in construction_mod.SORT_BUILDINGS:
            raise ReportError("kind must be civ or mil")
        if self.live is None:
            from .live.service import LiveError   # live is optional (--no-game): imported only here
            raise LiveError("disabled", "Live game access is disabled (--no-game)")
        res = self.live.sort_construction(apply, kind)
        install = self._install_path()
        if install is not None:
            names = gamefiles.state_names(install)
            provinces = {p: sid for sid, d in gamefiles.state_definitions(install).items() for p in d["provinces"]}
            defs = construction_mod.buildings(self._game_roots(install))
            for m in res["moved"]:
                loc = m["location"]
                state = provinces.get(loc) if (defs.get(m["building"]) or {}).get("provincial") else loc
                m["state_name"] = names.get(f"STATE_{state}") if state is not None else None
        return res

    def trade_advice(self, tag: str, mode: str = "surplus", limit: float = trade_mod.DEFAULT_LIMIT) -> dict:
        """Trade advisor for `tag` (trade.py): deals that cover its shortages and deals no longer needed, sellers
        ranked by the player's rules, within the factory limit (game memory)."""
        tag = tag.upper()
        install = self._install_path()
        if install is None:
            return envelope(UNAVAILABLE, None, "Needs the game installation")
        if self.live is None:
            return envelope(UNAVAILABLE, None, "Needs the running game")
        roots = self._game_roots(install)
        order = resource_order(roots)
        try:
            market = self.live.trade_market(tag, list(order), list(government_mod.ideologies(roots)["colors"]))
        except Exception as exc:  # game not running, main menu, other version
            return envelope(UNAVAILABLE, None, f"Needs the running game: {exc}")
        geo_note = self._trade_geography(install, tag, market["sellers"])
        advice = trade_mod.plan(market["player"], market["sellers"], {k: v["cic"] for k, v in order.items()},
                                mode, limit)
        if geo_note:
            advice["unchecked"].insert(0, geo_note)
        tags = {d["seller"] for row in advice["resources"] for d in row["buy"] + row["cancel"] + row["candidates"]}
        names = gamefiles.country_names(install)
        loc = self._loc_names(install, {f"PRODUCTION_MATERIALS_{r.upper()}" for r in trade_mod.RESOURCES})
        loc.update(self._loc_names(install, {r for v in loc.values() for r in LOC_REF.findall(v)} - set(loc)))
        for row in advice["resources"]:
            name = loc.get(f"PRODUCTION_MATERIALS_{row['resource'].upper()}")
            row["name"] = clean_loc(name, loc) if name else row["resource"].capitalize()   # "$rubber$" -> Rubber
            row["frame"] = order.get(row["resource"], {}).get("frame")
        sprites = gfx.sprites(roots)
        strip = sprites.get("GFX_resources_strip")
        return envelope(LIVE, {"tag": tag, **advice, "country_names": {t: names.get(t, t) for t in tags},
                               "icons": gfx.icon_data_uri(strip) if strip else None,
                               "icon_frames": max([v["frame"] for v in order.values()] or [0]),
                               "trade_source": "live"}, "Trade advice from game memory.")

    def _trade_geography(self, install: Path, tag: str, sellers: dict) -> str | None:
        """Sets "border" and "continent" of each seller (provinces of the newest save's state owners, map files);
        returns why they could not be set, else None."""
        picked = self._pick_save(None)
        if picked is None:
            return "shared border and same continent (no save to read the state owners from)"
        try:
            states = self.saves.states(picked[0])["states"]
            definitions = gamefiles.state_definitions(install)
            owned: dict[str, list[int]] = {}
            for sid, st in states.items():
                if st.get("owner") and int(sid) in definitions:
                    owned.setdefault(st["owner"], []).extend(definitions[int(sid)]["provinces"])
            neighbours = geography.province_neighbours(str(install), str(Path(self.data_dir) / "cache") if self.data_dir else "")
            continents = geography.province_continents(str(install))
        except (SaveFormatError, OSError, ValueError, KeyError) as exc:
            return f"shared border and same continent ({exc})"
        touching = geography.countries_touching(owned, neighbours, tag)
        home = geography.main_continent(owned.get(tag, []), continents)
        for t, info in sellers.items():
            info["border"] = t in touching
            info["continent"] = home is not None and geography.main_continent(owned.get(t, []), continents) == home
        return None

    def factories(self, tag: str) -> dict:
        """Factories of `tag` like the game's factory tooltip (game memory): military, dockyards, civilian - total
        and owned / occupation / subject relations / trade / damaged - and energy; building icons from the game."""
        tag = tag.upper()
        install = self._install_path()
        if install is None:
            return envelope(UNAVAILABLE, None, "Needs the game installation")
        if self.live is None:
            return envelope(UNAVAILABLE, None, "Needs the running game")
        try:
            found = self.live.factories(tag)
        except Exception as exc:  # game not running, main menu, other version
            return envelope(UNAVAILABLE, None, f"Needs the running game: {exc}")
        roots = self._game_roots(install)
        defs = construction_mod.buildings(roots)
        strip = construction_mod.icon_strip(roots)
        icons = {}
        for kind, building in (("military", "arms_factory"), ("dockyards", "dockyard"), ("civilian", "industrial_complex")):
            frame = (defs.get(building) or {}).get("icon_frame")
            icons[kind] = gfx.frame_data_uri(strip[0], frame, strip[1]) if strip and frame else None
        data = {k: found[k] for k in ("military", "dockyards", "civilian", "energy")}
        return envelope(LIVE, {"tag": tag, **data, "icons": icons, "factories_source": "live"},
                        "Factories from game memory.")

    def doctrines(self, tag: str) -> dict:
        """Doctrines of `tag` like the game's doctrine screen (game memory): per folder the grand doctrine, each
        track's subdoctrine, mastery, banked mastery, daily gain and rewards (unlocked or not, with their effects);
        the other grand doctrines and subdoctrines that could be chosen; names, texts and icons from the game files."""
        tag = tag.upper()
        install = self._install_path()
        if install is None:
            return envelope(UNAVAILABLE, None, "Needs the game installation")
        if self.live is None:
            return envelope(UNAVAILABLE, None, "Needs the running game")
        try:
            state = self.live.doctrine_state(tag)["folders"]
        except Exception as exc:  # game not running, main menu, other version
            return envelope(UNAVAILABLE, None, f"Needs the running game: {exc}")
        roots = self._game_roots(install)
        defs = doctrines_mod.definitions(roots)
        keys: set[str] = set()

        def want(d):
            if d:
                keys.update(filter(None, [d.get("name"), d.get("desc")]))
                for m in [d.get("modifiers") or {}] + [r["modifiers"] for r in d.get("rewards", [])] \
                        + [ms["modifiers"] for ms in d.get("milestones", [])]:
                    for k in m:
                        stat, _, unit = k.partition("@")
                        keys.update(filter(None, [f"MODIFIER_{stat.upper()}", stat, f"STAT_{stat.upper()}", unit]))
                for t in (d.get("tactics") or []) + [t for r in d.get("rewards", []) for t in r["tactics"]] \
                        + [t for ms in d.get("milestones", []) for t in ms["tactics"]]:
                    keys.add(t)
                for r in d.get("rewards", []):
                    keys.add(f"{d['id']}_{r['id']}")
        for f in defs["folders"]:
            keys.add(f["name"] or "")
        for t in defs["tracks"].values():
            keys.add(t["name"] or "")
        for d in list(defs["grand"].values()) + list(defs["subs"].values()):
            want(d)
        names = self._loc_names(install, keys)
        loc = lambda k: (clean_loc(names[k], names) if k and names.get(k) else None)  # noqa: E731
        sprites = gfx.sprites(roots)
        icon = lambda sprite: gfx.icon_data_uri(sprites[sprite]) if sprite and sprites.get(sprite) else None  # noqa: E731

        def mods(m: dict) -> list[dict]:
            out = []
            for k, v in m.items():
                stat, _, unit = k.partition("@")
                label = loc(f"MODIFIER_{stat.upper()}") or loc(f"STAT_{stat.upper()}") or loc(stat) \
                    or stat.replace("_", " ").capitalize()
                if unit:
                    label = f"{label} ({loc(unit) or unit.replace('category_', '').replace('_', ' ')})"
                out.append({"key": stat, "label": label, "value": v})
            return out

        def card(d, selected=False):
            if not d:
                return None
            return {"id": d["id"], "name": loc(d["name"]) or d["id"].replace("_", " ").title(),
                    "desc": loc(d["desc"]), "icon": icon(d["icon"]), "selected": selected,
                    "modifiers": mods(d["modifiers"]), "tactics": [loc(t) or t for t in d["tactics"]]}

        folders = []
        for i, fdef in enumerate(defs["folders"]):
            st = state[i] if i < len(state) else {"grand": None, "tracks": []}
            g = doctrines_mod.resolve(st["grand"], defs, "grand")
            track_ids = g["tracks"] if g else []
            tracks = []
            for j, t in enumerate(st["tracks"]):
                tid = track_ids[j] if j < len(track_ids) else None
                sub = doctrines_mod.resolve(t["sub"], defs, "subs", tid)
                rewards = [{"name": loc(f"{sub['id']}_{r['id']}") or r["id"].replace("_", " ").capitalize(),
                            "threshold": r["threshold"], "unlocked": k < t["rewards"],
                            "modifiers": mods(r["modifiers"]), "tactics": [loc(x) or x for x in r["tactics"]]}
                           for k, r in enumerate(sub["rewards"])] if sub else []
                milestone = g["milestones"][j] if g and j < len(g["milestones"]) else None
                tracks.append({
                    "id": tid, "name": loc((defs["tracks"].get(tid) or {}).get("name")) or (tid or "").replace("_", " ").title(),
                    "icon": icon((defs["tracks"].get(tid) or {}).get("icon")),
                    "sub": {**card(sub, True), "rewards": rewards} if sub else None,
                    "mastery": t["mastery"], "bank": t["bank"], "daily": t["daily"], "rewards_unlocked": t["rewards"],
                    "max_mastery": rewards[-1]["threshold"] if rewards else None,
                    "milestone": {"modifiers": mods(milestone["modifiers"]), "tactics": [loc(x) or x for x in milestone["tactics"]]}
                    if milestone else None,
                    "options": [card(o) for o in defs["subs"].values() if o["track"] == tid and (not sub or o["id"] != sub["id"])],
                })
            folders.append({
                "id": fdef["id"], "name": loc(fdef["name"]) or fdef["id"].replace("_", " ").title(), "icon": icon(fdef["icon"]),
                "grand": card(g, True), "tracks": tracks,
                "grand_options": [card(o) for o in defs["grand"].values() if o["folder"] == fdef["id"] and (not g or o["id"] != g["id"])],
            })
        return envelope(LIVE, {"tag": tag, "folders": folders, "doctrine_source": "live"},
                        "Doctrines from game memory; names, texts and icons from the game files.")

    def military(self, tag: str) -> dict:
        """Army, air force and navy of `tag` like the game's military overview (game memory): divisions per template
        with what they are made of and manpower in the field; planes per role and design with the design stats and
        planes in the stockpile; fleets, task forces and ships per type and class. Names from the game files."""
        tag = tag.upper()
        install = self._install_path()
        if install is None:
            return envelope(UNAVAILABLE, None, "Needs the game installation")
        if self.live is None:
            return envelope(UNAVAILABLE, None, "Needs the running game")
        try:
            found = self.live.military(tag)
        except Exception as exc:  # game not running, main menu, other version
            return envelope(UNAVAILABLE, None, f"Needs the running game: {exc}")
        army, navy, air, reserve = found["army"], found["navy"], found["air"], found["air_reserve"]
        self._division_stats(install, army["templates"], found)
        ids = {u for t in army["templates"] for k in ("battalions", "support", "regimental") for u in t[k]}
        ids |= {sh["type"] for sh in navy["ships"]} | {g["role"] for g in air}
        eq_ids = {a for t in army["templates"] for a in ((t.get("designer") or {}).get("cost") or {}).get("equipment", {})}
        ids |= eq_ids | {f"{a}_short" for a in eq_ids}
        planes = found.get("plane_designs") or []
        tanks = found.get("tank_designs") or []
        ids |= {d["type"] for d in planes + tanks} | {s["module"] for d in planes + tanks for s in d.get("slots", []) if s["module"]}
        stat_keys = {k for g in air + reserve for k in (g["stats"] or {})}
        names = self._loc_names(install, ids | {f"{i}_short" for i in ids} | {f"STAT_{k.upper()}" for k in stat_keys}
                                    | {f"EQUIPMENT_STAT_{k.upper()}" for k in stat_keys} | set(stat_keys))
        loc = lambda k: clean_loc(names[k], names) if names.get(k) else None  # noqa: E731
        label = lambda i: loc(i) or i.replace("_", " ").capitalize()  # noqa: E731

        def grouped(units):
            out = {}
            for u in units:
                out[u] = out.get(u, 0) + 1
            return [{"id": u, "name": label(u), "count": n} for u, n in out.items()]
        try:
            units = divisions_mod.tables(self._game_roots(install))["units"]
        except Exception:  # broken game files: no automatic icon
            units = {}
        priority = lambda u: (units.get(u) or {}).get("stats", {}).get("priority", 0)  # noqa: E731
        for t in army["templates"]:
            cost = (t.get("designer") or {}).get("cost")
            if cost:   # "Infantry Eq." as the designer
                cost["names"] = {a: loc(f"{a}_short") or loc(a) or a.replace("_", " ") for a in cost["equipment"]}
            # the template's icon: the player's choice, else the battalion type the game puts first (highest priority)
            first = max(t["battalions"], key=lambda u: (priority(u), t["battalions"].count(u)), default=None)
            t["icon"] = {"template": t["icon"]} if t["icon"] >= 0 else {"unit": first}
            for k in ("battalions", "support", "regimental"):
                t[k] = grouped(t[k])
        army["unit_names"] = {u: label(u) for t in army["templates"] for k in ("battalions", "support", "regimental")
                              for u in t["grid"][k] if u}
        army["templates"].sort(key=lambda t: -t["count"])
        stat_label = {k: PLANE_STAT_LABELS.get(k) or (loc(f"STAT_{k.upper()}") or loc(k) or k.replace("_", " ")).rstrip(":")
                      for k in stat_keys}
        for g in air:
            g["role_name"] = label(g["role"])
        types: dict[str, dict] = {}
        for sh in navy["ships"]:
            ty = types.setdefault(sh["type"], {"type": sh["type"], "name": label(sh["type"]), "count": 0, "classes": []})
            ty["count"] += sh["count"]
            ty["classes"].append({"name": sh["class"] or "?", "count": sh["count"]})
        navy_out = {"fleets": navy["fleets"], "task_forces": navy["task_forces"],
                    "ships": sum(t["count"] for t in types.values()),
                    "types": sorted(types.values(), key=lambda t: -t["count"])}
        stat_label.update({k: PLANE_STAT_LABELS.get(k) or k.replace("_", " ") for d in planes for k in d["stats"]
                           if k not in stat_label})
        return envelope(LIVE, {
            "tag": tag, "military_source": "live",
            "army": {**army, "tank_designs": self._plane_designs(tag, self._with_country_bonuses(install, tanks, found), label)},
            "navy": navy_out, "mios": self._design_mios(install, tag, found.get("mios") or {}, planes + tanks),
            "air": {"planes": sum(g["planes"] for g in air), "wings": air, "reserve": reserve, "stat_labels": stat_label,
                    "designs": self._plane_designs(tag, self._with_country_bonuses(install, planes, found), label)},
        }, "Army, air force and navy from game memory.")

    def _with_country_bonuses(self, install: Path, designs: list[dict], found: dict) -> list[dict]:
        """Plane and tank designs with the country's equipment bonuses the designer adds to a design (2026-10-20, user's
        FW 190 B: air attack 56.7 in the design, 59.5 in the designer = x 1.05 from the doctrine reward "loose formation"
        of Airspace Dominance: category_fighter { air_attack = 0.05 air_agility = 0.05 }): every technology and unlocked
        doctrine bonus for the air sub-unit that flies the design's equipment type (fighter needs small_plane_airframe) or
        its categories, stat x (1 + sum). "base_stats" keeps the design's own values, "bonuses" what was added."""
        roots = self._game_roots(install)
        try:
            tabs = divisions_mod.tables(roots)
            mods, _mults = divisions_mod.bonuses(tabs, found.get("researched") or [], found.get("doctrine_state") or [],
                                                 doctrines_mod.definitions(roots))
        except Exception as exc:  # broken game files: the design's own stats
            self.log.debug("Plane bonuses not computed: %s", exc)
            return designs
        out = []
        for d in designs:
            unit, stats, add = divisions_mod.design_with_bonuses(tabs["units"], mods, d.get("type") or "", d["stats"])
            out.append({**d, "stats": stats, "base_stats": d["stats"], "bonuses": add, "role": unit})
        return out

    def _design_mios(self, install: Path, tag: str, mios: dict, designs: list[dict]) -> dict:
        """{MIO id: {"key", "name", "icon" (data URI)}} of the MIOs the designs use: key from the game files by the
        organisation's icon (the country's own MIO first), name from its own name or the key's localisation."""
        used = {d.get("mio") for d in designs} - {None}
        if not used:
            return {}
        roots = self._game_roots(install)
        defs = mio_mod.definitions(roots)
        by_icon: dict[str, list[str]] = {}
        for key in defs["organizations"]:
            icon = (mio_mod.resolve(defs, key) or {}).get("icon")
            if icon:
                by_icon.setdefault(icon, []).append(key)
        out = {}
        for mid in used:
            m = mios.get(mid) or mios.get(str(mid)) or {}
            keys = by_icon.get(m.get("icon") or "", [])
            key = next((k for k in keys if k.startswith(f"{tag}_")), keys[0] if keys else None)
            name_key = m.get("name") or ((defs["organizations"].get(key) or {}).get("name") if key else None) or key
            out[mid] = {"key": key, "name_key": name_key, "icon": gfx.sprite_uri(roots, m["icon"]) if m.get("icon") else None}
        names = self._loc_names(install, {v["name_key"] for v in out.values() if v["name_key"]})
        for _ in range(2):   # "$messerschmitt$" -> Messerschmitt (references inside references too)
            names.update(self._loc_names(install, {r for v in names.values() for r in LOC_REF.findall(v)} - set(names)))
        for v in out.values():
            k = v.pop("name_key")
            v["name"] = clean_loc(names[k], names) if k in names else (k or "").replace("_organization", "").replace("_", " ").title() or None
        return out

    def _plane_designs(self, tag: str, planes: list[dict], label) -> list[dict]:
        """Plane designs of `tag` like the production screen: name (a base airframe: its type), type, outdated, stats,
        the design it was made from, and the game day the IC recorder first saw it ("seen", "seen_before": it existed
        already when the recording began - the game keeps no creation date)."""
        seen = self.ic_history.designs(self.ic_history.active).get(tag, {})
        out = []
        for d in planes:
            day = seen.get(str(d["id"]))
            slots = [{**s, "module_name": label(s["module"]) if s["module"] else None} for s in d.get("slots", [])]
            out.append({**d, "slots": slots, "type_name": label(d["type"]), "name": d["name"] or label(d["type"]),
                        "seen": ic_history_mod.date_text(day[0]) if day else None, "seen_before": bool(day and day[1])})
        return out

    def military_icons(self, units: list[str], templates: list[int], modules: list[str] | None = None,
                       blueprints: list[str] | None = None, tanks: list[str] | None = None, tag: str = "") -> dict:
        """Icons of the designers: {"units": {sub-unit id: data URI}, "templates": {icon number: data URI}, "modules":
        {plane module id: data URI}, "blueprints": {plane type: data URI}, "designer": {"background", "locked"}}
        (GFX_unit_<id>_icon_medium, GFX_div_templ_<n>_large, GFX_EMI_<id>, GFX_TC_<type>); fetched once by the Army
        and Air Force tiles, not on every refresh."""
        install = self._install_path()
        if install is None:
            return {"data": {"units": {}, "templates": {}}}
        roots = self._game_roots(install)
        return {"data": {
            "units": {u: gfx.sprite_uri(roots, f"GFX_unit_{u}_icon_medium") for u in units[:200] if re.fullmatch(r"\w{1,80}", u)},
            "templates": {str(n): gfx.sprite_uri(roots, f"GFX_div_templ_{n}_large") for n in templates[:200]},
            "modules": {m: gfx.sprite_uri(roots, f"GFX_EMI_{m}") for m in (modules or [])[:200] if re.fullmatch(r"\w{1,80}", m)},
            # the plane designer: the airframe's blueprint (GFX_TC_<type>), its background and the locked slot
            "blueprints": {b: gfx.sprite_uri(roots, f"GFX_TC_{b}") for b in (blueprints or [])[:100] if re.fullmatch(r"\w{1,80}", b)},
            "designer": {"background": gfx.sprite_uri(roots, "GFX_generic_plane_blueprint_background"),
                         "locked": gfx.sprite_uri(roots, "GFX_EMSI_locked")} if blueprints else {},
            # the tank designer: the chassis drawing of the country (GFX_TC_light_tank_chassis_sov), else the generic one
            "tanks": {t: self._tank_blueprint(roots, t, tag) for t in (tanks or [])[:100] if re.fullmatch(r"\w{1,80}", t)},
            "tank_designer": {"background": gfx.sprite_uri(roots, "GFX_tank_blueprint_background"),
                              "locked": gfx.sprite_uri(roots, "GFX_EMSI_locked")} if tanks else {}}}

    @staticmethod
    def _tank_blueprint(roots: tuple[str, ...], type_id: str, tag: str) -> str | None:
        base = re.sub(r"_\d+$", "", type_id)   # light_tank_chassis_2 -> light_tank_chassis
        # a variant without a drawing of its own (flame, amphibious) shows the plain chassis of its class
        plain = re.sub(r"_(?:flame|amphibious)(?=_chassis$)", "", base)
        if plain == "amphibious_tank_chassis":
            plain = "light_tank_chassis"
        sprites = gfx.sprites(roots)
        names = [f"GFX_TC_{b}_{tag.lower()}" for b in (base, plain)] + [f"GFX_TC_{base}", f"GFX_TC_generic_{base}", f"GFX_TC_{plain}"]
        name = next((n for n in names if n in sprites), None)
        return gfx.sprite_uri(roots, name) if name else None

    def _division_stats(self, install: Path, templates: list[dict], found: dict) -> None:
        """Adds "designer" (stats like the game's division designer, divisions.py) to each template; an estimate when
        a needed equipment type has several current designs (tanks)."""
        roots = self._game_roots(install)
        try:
            tabs = divisions_mod.tables(roots)
            archetypes = deficit.tables(install, [Path(r) for r in roots[1:]])[1]
            mods, mults = divisions_mod.bonuses(tabs, found.get("researched") or [], found.get("doctrine_state") or [],
                                                doctrines_mod.definitions(roots))
        except Exception as exc:  # broken game files must not hide the army
            self.log.warning("Division designer stats unavailable: %s", exc)
            return
        equipment: dict[str, dict] = {}
        several: set[str] = set()
        for d in found.get("designs") or []:
            arch = deficit.archetype_of(d["type"], archetypes)
            if arch in equipment:
                several.add(arch)
            else:
                equipment[arch] = {**d["stats"], "design": d["name"]}
        costs: dict[str, list[float]] = {}
        for d in found.get("design_costs") or []:   # every design, outdated ones too: the cost range
            costs.setdefault(deficit.archetype_of(d["type"], archetypes), []).append(d["cost"])
        for t in templates:
            res = divisions_mod.template_stats(t, tabs, equipment, mods, mults)
            if res is None:
                continue
            needs = {a for u in t["battalions"] + t["support"] + t["regimental"]
                     for a in tabs["units"].get(u, {}).get("need", {})}
            res["estimate"] = sorted(needs & several)
            res["designs"] = {a: equipment[a]["design"] for a in sorted(needs) if equipment.get(a, {}).get("design")}
            res["cost"] = divisions_mod.equipment_cost(t, tabs, equipment, costs)
            t["designer"] = res

    def summary_games(self) -> dict:
        """Recorded campaigns (IC history, ic_history.py) and what the recorder is doing."""
        recorder = self.ic_recorder.status() if self.ic_recorder else {"recording": None, "last": None,
                                                                        "error": "Live game access is disabled"}
        games = self.ic_history.games()
        running = self.live.running_game() if self.live is not None else None
        if running:   # the recorded campaigns of the running game (by its campaign id)
            running["known"] = [g["id"] for g in games if running["campaign"] and g["campaign"] == running["campaign"]]
        return {"data": {"games": games, "recorder": recorder, "running": running}}

    def summary_recording(self, data) -> dict:
        """The user's override of the recorder for the next game day: {"action": "new"} starts a new campaign file,
        {"action": "continue", "game": id} appends to a recorded one, {"action": "cancel"} drops the request."""
        data = data if isinstance(data, dict) else {}
        action, gid = data.get("action"), data.get("game")
        try:
            if action == "new":
                self.ic_history.request(None)
            elif action == "continue" and isinstance(gid, str):
                self.ic_history.request(gid)
            elif action == "cancel":
                self.ic_history.cancel_request()
            else:
                raise ReportError("action must be new, continue (with game) or cancel")
        except FileNotFoundError:
            raise NotFound(f"No recorded campaign {gid}") from None
        except ValueError as exc:
            raise ReportError(str(exc)) from None
        self.log.info("Game summary: recording request %s%s", action, f" {gid}" if action == "continue" else "")
        return self.summary_games()

    def summary_game(self, gid: str, metric: str = "mil", tags: list[str] | None = None, by_faction: bool = False,
                     groups_from: str | None = None, by_player: bool = False, subjects: bool = True) -> dict:
        """IC history of one campaign for the Game summary tab: the countries (latest MIL / NAV / CIV IC a day,
        faction, name) and the day series of `metric` for `tags`, per faction or per player with or without the
        player's subjects (ic_history.view), with the user's grouping of this campaign - or of `groups_from` (the
        campaign it is compared with)."""
        try:
            game = self.ic_history.game(gid)
            out = ic_history_mod.view(game, metric, tags, by_faction, self.ic_history.groups(groups_from or gid),
                                      by_player, subjects)
        except FileNotFoundError:
            raise NotFound(f"No recorded campaign {gid}") from None
        except ValueError as exc:
            raise ReportError(str(exc)) from None
        install = self._install_path()
        names = gamefiles.country_names(install) if install else {}
        for c in out["countries"]:
            c["name"] = names.get(c["tag"], c["tag"])
        for p in out["players"]:
            p["country"] = names.get(p["tag"], p["tag"])
        return {"data": {"id": gid, "player": game["player"], "metric": metric, "by_faction": by_faction,
                         "by_player": by_player, "subjects": subjects, **out}}

    # -- Players actions (actions.py) ---------------------------------------------------------------
    def action_snapshot(self, tags: list[str]) -> dict[str, dict]:
        """Snapshots of `tags` for the IC recorder (live/service.action_snapshot with the game's resource order)."""
        install = self._install_path()
        if install is None or self.live is None:
            return {}
        return self.live.action_snapshot(tags, list(resource_order(self._game_roots(install))))

    def players_actions(self, gid: str | None = None) -> dict:
        """The Players actions log of a campaign (the one being recorded, else the newest): events with names from the
        game files and the newest save, the watched countries."""
        games = self.ic_history.games()
        if gid is None or not any(g["id"] == gid for g in games):
            gid = self.ic_history.active or (games[0]["id"] if games else None)
        game = next((g for g in games if g["id"] == gid), None)
        events = self.ic_history.actions(gid)[-MAX_ACTIONS:]
        install = self._install_path()
        keys = {e["id"] for e in events if e["kind"] in ("focus", "research", "researched", "ideas") and e.get("id")}
        keys |= {str(e.get("detail") or "").split("@")[0] for e in events if e["kind"] == "construction"}
        names = self._loc_names(install, keys) if install else {}
        names.update({k: clean_loc(v, names) for k, v in names.items()})
        countries = gamefiles.country_names(install) if install else {}
        chars = self._character_names(install, {e["tag"] for e in events if e["kind"] in ("advisors", "leader")})
        out = []
        for e in events:
            out.append({**e, "date": ic_history_mod.date_text(e["t"]),
                        "name": self._action_name(e, names, countries, chars.get(e["tag"], {}))})
        return {"data": {"game": gid, "games": [{"id": g["id"], "player": g["player"], "first": g["first"], "last": g["last"],
                                                 "created": g["created"], "active": g["active"]} for g in games],
                         "player": game and game["player"], "watched": self.ic_history.watched(),
                         "countries": countries, "events": out, "limit": MAX_ACTIONS}}

    def players_actions_watch(self, data) -> dict:
        try:
            tags = self.ic_history.set_watched((data or {}).get("tags"))
        except ValueError as exc:
            raise ReportError(str(exc)) from None
        self.log.info("Players actions: watching %s", ", ".join(tags) or "the player only")
        return {"data": {"watched": tags}}

    def _character_names(self, install: Path | None, tags: set[str]) -> dict[str, dict[str, str]]:
        """{tag: {character id: name}} from the newest save (advisors and leaders are characters)."""
        picked = self._pick_save(None) if install and tags else None
        out: dict[str, dict[str, str]] = {}
        if not picked:
            return out
        for tag in tags:
            try:
                chars = (self.saves.politics(picked[0], tag).get("characters") or {})
            except Exception:  # an old or broken save: ids stay
                continue
            loc = self._loc_names(install, {c["name"] or c["token"] for c in chars.values() if c.get("name") or c.get("token")})
            out[tag] = {cid: loc.get(c["name"] or "") or loc.get(c["token"] or "") or c["token"] or cid for cid, c in chars.items()}
        return out

    @staticmethod
    def _action_name(e: dict, names: dict, countries: dict, chars: dict) -> str:
        """What the event is about, readable: a focus / technology / idea name, a country, a character, a design."""
        kind, i, detail = e["kind"], str(e.get("id") or ""), e.get("detail")
        if kind in ("focus", "research", "researched", "ideas"):
            return names.get(i) or i.replace("_", " ")
        if kind in ("wars", "justifications"):
            return countries.get(i) or i
        if kind in ("advisors", "leader"):
            return chars.get(i) or f"character {i}"
        if kind == "designs":
            return str(detail or i)
        if kind == "construction":
            building, _, state = str(detail or "").partition("@")
            return f"{names.get(building) or building.replace('_', ' ')} (state {state})"
        if kind == "trade":
            seller, _, resource = i.partition(" ")
            return f"{resource} from {countries.get(seller) or seller}: {detail}"
        return i

    def summary_equipment(self, gid: str, tags: list[str], archetype: str | None) -> dict:
        """Equipment chart of the Game summary: needed / in divisions / stockpile / produced a day of one equipment
        archetype for the chosen countries (summed) of a recorded campaign, with names and icons of the archetypes."""
        if not tags or not all(re.fullmatch(r"[A-Z][A-Z0-9]{2}", t) for t in tags):
            raise ReportError("tag must be one or more country tags")
        try:
            out = self.ic_history.equipment(gid, tags, archetype)
        except ValueError as exc:
            raise NotFound(f"No recorded campaign {gid}") from exc
        install = self._install_path()
        keys = list(out["archetypes"])
        names = self._equipment_names(install, set(keys)) if install else {}
        icons = self._equipment_icons(install, tags[0], keys) if install else {}
        out["archetypes"] = [{"key": a, "name": names.get(a) or a.replace("_", " ").capitalize(), "icon": icons.get(a)}
                             for a in keys]
        return {"data": {"id": gid, "tags": tags, **out}}

    def summary_delete(self, gid: str) -> dict:
        """Deletes a recorded campaign (not the one being recorded)."""
        try:
            self.ic_history.delete(gid)
        except FileNotFoundError:
            raise NotFound(f"No recorded campaign {gid}") from None
        except ValueError as exc:
            raise ReportError(str(exc)) from None
        self.log.info("Game summary: campaign %s deleted", gid)
        return {"data": {"deleted": gid}}

    def summary_groups(self, gid: str, data=None) -> dict:
        """The user's grouping of a campaign: {"custom": [names], "assign": {tag: group}}; saved when `data` is given."""
        try:
            groups = self.ic_history.groups(gid) if data is None else self.ic_history.set_groups(gid, data)
        except FileNotFoundError:
            raise NotFound(f"No recorded campaign {gid}") from None
        except ValueError as exc:
            raise ReportError(str(exc)) from None
        if data is not None:
            self.log.info("Game summary groups of %s: %d custom, %d moved", gid, len(groups["custom"]), len(groups["assign"]))
        return {"data": groups}

    def game_map(self, raster: bool = False) -> dict:
        """The game's province map (campaign_map.py) for the Game summary and the State Editor: country colours and
        names, state names and victory points of the game and the mods it runs with, the map's key - and with `raster`
        the map itself (PNG data URI, kept by the renderer by key) and the state of each province."""
        install = self._install_path()
        if install is None:
            raise ReportError("The game installation was not found - the map comes from its files")
        roots = self._game_roots(install)
        try:
            image = campaign_map.raster(roots, Path(self.data_dir or ".") / "cache")
        except (OSError, ValueError, ImportError) as exc:
            raise ReportError(f"The game's map could not be read: {exc}") from None
        loc = campaign_map.state_names(roots)
        found = campaign_map.states(roots)
        states = {sid: {"name": loc.get(s["name_key"] or "") or s["name_key"] or f"State {sid}", "vp": s["vp"]}
                  for sid, s in found.items()}
        vps = {p: v for s in found.values() for p, v in s["vps"].items() if v > 0}
        names = self._loc_names(install, {f"VICTORY_POINTS_{p}" for p in vps})
        # [province id, victory points, name] of the cities (victory point provinces with a name), the largest first
        cities = sorted(([p, v, clean_loc(names[f"VICTORY_POINTS_{p}"], names)] for p, v in vps.items()
                         if names.get(f"VICTORY_POINTS_{p}")), key=lambda c: -c[1])
        out = {"colors": campaign_map.country_colors(roots), "names": gamefiles.country_names(install), "states": states,
               "cities": cities,
               "map": {"key": image["key"], "width": image["width"], "height": image["height"]}}
        if raster:
            out["map"]["png"] = "data:image/png;base64," + base64.b64encode(image["png"]).decode("ascii")
            out["map"]["province_state"] = image["province_state"]
            out["map"]["terrain_types"] = image["terrain_types"]   # province terrain (definition.csv): names
            out["map"]["province_terrain"] = image["province_terrain"]
        return {"data": out}

    def game_borders(self) -> dict:
        """The province outlines of the game's map (campaign_map.borders, base64) - the sharp borders of the map when
        zoomed in."""
        install = self._install_path()
        if install is None:
            raise ReportError("The game installation was not found - the map comes from its files")
        try:
            out = campaign_map.borders(self._game_roots(install), Path(self.data_dir or ".") / "cache")
        except (OSError, ValueError, ImportError) as exc:
            raise ReportError(f"The game's map could not be read: {exc}") from None
        return {"data": {"key": out["key"], "borders": base64.b64encode(out["data"]).decode("ascii")}}

    def game_terrain(self) -> dict:
        """Relief and rivers of the game's map (campaign_map.terrain) - the terrain under the colours of the map."""
        install = self._install_path()
        if install is None:
            raise ReportError("The game installation was not found - the map comes from its files")
        try:
            return {"data": campaign_map.terrain(self._game_roots(install), Path(self.data_dir or ".") / "cache")}
        except (OSError, ValueError, ImportError) as exc:
            raise ReportError(f"The game's terrain could not be read: {exc}") from None

    def summary_map(self, gid: str, raster: bool = False) -> dict:
        """Campaign map of the Game summary: the recorded owner / controller rows of `gid` (changes per day,
        ic_history.add_map) and the game's map (game_map)."""
        try:
            rows = self.ic_history.map_rows(gid)
            game = self.ic_history.game(gid)
            factions = self.ic_history.faction_rows(gid)
        except (FileNotFoundError, ValueError):
            raise NotFound(f"No recorded campaign {gid}") from None
        players, last = [], None   # the player lists of the days they changed on
        for t, p in zip(game["t"], game["players"]):
            if p != last:
                players.append([t, p])
                last = p
        return {"data": {"id": gid, "rows": rows, "t": game["t"], "dates": game["dates"], "factions": factions,
                         "players": players, "groups": self.ic_history.groups(gid), **self.game_map(raster)["data"]}}

    def summary_units(self, gid: str) -> dict:
        """Division positions of a recorded campaign (ic_history.add_units rows) for the campaign map."""
        try:
            return {"data": {"id": gid, "rows": self.ic_history.units_rows(gid)}}
        except ValueError:
            raise NotFound(f"No recorded campaign {gid}") from None

    def summary_unit_kinds(self, gid: str) -> dict:
        """{"<tag>|<template>": kind (divisions.KINDS)} of every template recorded in a campaign (its newest line
        battalions) - the division counters of the campaign map."""
        try:
            rows = self.ic_history.delta_rows("tmpl", gid)
        except ValueError:
            raise NotFound(f"No recorded campaign {gid}") from None
        kinds: dict[str, str] = {}
        for r in rows:
            for key, tpl in (r.get("u") or {}).items():
                kind = divisions_mod.unit_kind(tpl.get("b") or []) if tpl else None
                if kind:
                    kinds[key] = kind
        return {"data": {"id": gid, "kinds": kinds}}

    def summary_infra(self, gid: str, kind: str = "infra") -> dict:
        """Railways and province buildings ("infra") or moves and battles ("front") of a recorded campaign
        (ic_history rows) for the campaign map."""
        try:
            return {"data": {"id": gid, "rows": self.ic_history.delta_rows(kind, gid)}}
        except ValueError:
            raise NotFound(f"No recorded campaign {gid}") from None

    def summary_moment(self, gid: str, t: float) -> dict:
        """The Time machine's game state: every country's recorded values (ic_history.METRICS) on the last recorded
        day on or before `t` (days), the factions and players of that day, the country names."""
        try:
            game = self.ic_history.game(gid)
        except FileNotFoundError:
            raise NotFound(f"No recorded campaign {gid}") from None
        i = max(0, sum(1 for d in game["t"] if d <= t) - 1)
        countries = {tag: {k: v[i] for k, v in s.items() if i < len(v)} for tag, s in game["countries"].items()}
        install = self._install_path()
        factions = ic_history_mod.IcHistory.faction_rows(self.ic_history, gid)
        faction = next((f for d, f in reversed(factions) if d <= t), {})
        players = game.get("players") or []
        return {"data": {"id": gid, "day": game["t"][i], "countries": countries, "factions": faction,
                         "players": players[i] if i < len(players) else {},
                         "names": gamefiles.country_names(install) if install else {}}}

    def summary_divisions(self, gid: str, t: float) -> dict:
        """Every division of a recorded campaign at time `t` (days; ic_history.delta_at): [{"id", "tag", "name",
        "template", "pid", "to", "s": stats or None}] - the map's names and the Time machine's list."""
        try:
            state = self.ic_history.delta_at("divs", gid, t)
        except ValueError:
            raise NotFound(f"No recorded campaign {gid}") from None
        where = self._province_states()
        out = []
        for key, v in state.items():
            if key[0] != "n":
                continue
            k = key[1:]
            pos = state.get(f"p{k}") or [0, 0]
            out.append({"id": int(k), "tag": v[0], "name": v[1], "template": v[2], "pid": pos[0], "to": pos[1],
                        "army": v[3] if len(v) > 3 else None, "leader": v[4] if len(v) > 4 else None,
                        "where": where.get(pos[0]), "s": state.get(f"s{k}")})
        return {"data": {"id": gid, "t": t, "divisions": out}}

    def _province_states(self) -> dict[int, str]:
        """{province id: name of its state} of the game and its mods (the Time machine's division locations)."""
        install = self._install_path()
        if install is None:
            return {}
        roots = self._game_roots(install)
        if self._where_cache and self._where_cache[0] == roots:
            return self._where_cache[1]
        try:
            loc = campaign_map.state_names(roots)
            out = {p: loc.get(s["name_key"] or "") or s["name_key"] or f"State {sid}"
                   for sid, s in campaign_map.states(roots).items() for p in s["provinces"]}
        except OSError:
            out = {}
        self._where_cache = (roots, out)
        return out

    def summary_division(self, gid: str, did: int) -> dict:
        """One division of a recorded campaign: "history" [[time (days), "n" | "p" | "s" | "e", value]] (its rows),
        its templates over time ({"<tag>|<name>": [[time, definition]]}), equipment needed and manpower of the
        template's sub-units (game files), the designer's stats of the template when it is in the running game now,
        the battles where it stood or attacked ([time, province, battle])."""
        try:
            hist = self.ic_history.key_history("divs", gid, [f"{p}{did}" for p in "npse"])
            front = self.ic_history.delta_rows("front", gid)
            tmpl_rows = self.ic_history.delta_rows("tmpl", gid)
        except ValueError:
            raise NotFound(f"No recorded campaign {gid}") from None
        if not hist:
            raise NotFound(f"No division {did} recorded in {gid}")
        names = {v[0]: v[1] for _t, k, v in hist if k == "n" and v}
        keys = {f"{v[0]}|{v[2]}" for _t, k, v in hist if k == "n" and v}
        templates = {key: [[ic_history_mod.row_time(r), r["u"][key]] for r in tmpl_rows if key in r["u"]] for key in keys}
        place: list = []   # (time, province, attacking into)
        for t, k, v in hist:
            if k == "p":
                place.append((t, v[0] if v else None, v[1] if v else None))
        battles = []
        for r in front:
            when = ic_history_mod.row_time(r)
            at = next((p for p in reversed(place) if p[0] <= when), None)
            if not at or at[1] is None:
                continue
            for key, b in r["u"].items():
                if key[0] == "c" and b and int(key[1:]) in (at[1], at[2]):
                    battles.append([when, int(key[1:]), b])
        out = {"id": did, "history": hist, "templates": templates, "battles": battles}
        install = self._install_path()
        if install is not None:
            try:
                tabs = divisions_mod.tables(self._game_roots(install))["units"]
                out["units"] = {u: {"need": tabs[u]["need"], "manpower": tabs[u]["stats"].get("manpower", 0)}
                                for key in keys for _t, d in templates[key] for u in (d["b"] or []) + (d["s"] or [])
                                + (d["r"] or []) if u in tabs}
            except Exception as exc:  # broken game files: the division without its needs
                self.log.info("Unit tables unavailable: %s", exc)
            held = {t for _t, k, v in hist if k == "e" and v for t in v}
            try:
                archetypes = deficit.tables(install, [Path(r) for r in self._game_roots(install)[1:]])[1]
            except Exception:  # noqa: BLE001 - the types stay as they are
                archetypes = {}
            out["archetype"] = {t: deficit.archetype_of(t, archetypes) for t in held}
            ids = set(out.get("units", {})) | set(out["archetype"].values())
            loc = self._loc_names(install, ids | {f"{i}_short" for i in ids})
            out["labels"] = {i: clean_loc(loc[i], loc) for i in ids if loc.get(i)}
            out["designer"] = self._live_designer(names, keys)
        return {"data": out}

    def _live_designer(self, names: dict, keys: set) -> dict:
        """{"<tag>|<template>": designer stats} of the templates the running game has now (military)."""
        out = {}
        for tag in {k.split("|")[0] for k in keys}:
            try:
                found = self.military(tag)
            except Exception:  # noqa: BLE001 - the game not running
                continue
            for t in ((found.get("data") or {}).get("army") or {}).get("templates") or []:
                key = f"{tag}|{t['name']}"
                if key in keys and t.get("designer"):
                    out[key] = t["designer"]
        return out

    def summary_notes(self, gid: str, data=None) -> dict:
        """The user's notes on a campaign's timeline; with `data` {"t", "text", "id"?} one is added, changed or (an
        empty text) deleted."""
        try:
            if data is None:
                notes = self.ic_history.notes(gid)
            else:
                nid = data.get("id")
                notes = self.ic_history.set_note(gid, data.get("t"), data.get("text", ""),
                                                 nid if isinstance(nid, int) else None)
        except FileNotFoundError:
            raise NotFound(f"No recorded campaign {gid} or note") from None
        except ValueError as exc:
            raise ReportError(str(exc)) from None
        return {"data": [{**n, "date": ic_history_mod.date_text(n["t"])} for n in notes]}

    def summary_sessions(self, gid: str) -> dict:
        """Play sessions and the players' time of a campaign (ic_history.sessions)."""
        try:
            game = self.ic_history.game(gid)
        except (FileNotFoundError, ValueError):
            raise NotFound(f"No recorded campaign {gid}") from None
        return {"data": {"id": gid, **ic_history_mod.sessions(game)}}

    def summary_ranking(self, gid: str, subjects: bool = True) -> dict:
        """The human players ranked by category (ic_history.ranking)."""
        try:
            game = self.ic_history.game(gid)
        except (FileNotFoundError, ValueError):
            raise NotFound(f"No recorded campaign {gid}") from None
        return {"data": {"id": gid, "subjects": subjects, **ic_history_mod.ranking(game, subjects)}}

    def research_tabs(self) -> dict:
        """Tabs of the research screen (technology folders) for the installed game, enabled mods and owned DLCs,
        with the number of technologies in each tab."""
        install = self._install_path()
        if install is None:
            return envelope(UNAVAILABLE, None, "Needs the game installation")
        userdata = (self.detect().get("userdata") or {}).get("path")
        roots = tuple(str(r) for r in self._game_roots(install))
        dlcs = techtree.owned_dlcs(install, Path(userdata) if userdata else None)
        techs, _defines = self._technologies(roots)
        counts: dict[str, int] = {}
        for t in techs.values():
            for folder in t.get("folders") or []:
                counts[folder] = counts.get(folder, 0) + 1
        tabs = techtree.research_tabs(roots, dlcs, counts)
        names = self._loc_names(install, {t["id"] for t in tabs})
        names.update(self._loc_names(install, {r for v in names.values() for r in LOC_REF.findall(v)} - set(names)))
        sprites = gfx.sprites(roots)
        for t in tabs:
            t["name"] = clean_loc(names[t["id"]], names) if names.get(t["id"]) else t["id"]
            t.pop("x", None)
            texture = sprites.get(t.pop("sprite") or "")
            t["image"] = gfx.icon_data_uri(texture) if texture else None
        return envelope(SAVE, {"tabs": tabs, "dlcs": sorted(dlcs), "mods": len(roots) - 1},
                        f"{len(tabs)} research tabs from the game files, {len(roots) - 1} mod(s), {len(dlcs)} DLC(s).")

    def research_tree(self, tag: str, folder: str = "") -> dict:
        """Research tabs plus the technologies of one tab (default: the first) laid out like the game
        (interface/countrytechtreeview.gui) with the state of each one for `tag`: researched, researching
        (+ progress), available (ahead of time marked), excluded (XOR technology researched), unavailable; lines
        from each technology to the ones it leads to, routed around the other items."""
        tag = tag.upper()
        install = self._install_path()
        if install is None:
            return envelope(UNAVAILABLE, None, "Needs the game installation")
        tabs_res = self.research_tabs()
        tabs = (tabs_res.get("data") or {}).get("tabs") or []
        if tabs and folder not in {t["id"] for t in tabs}:
            folder = tabs[0]["id"]
        roots = tuple(str(r) for r in self._game_roots(install))
        layout = techtree.folder_layout(roots, folder)
        if layout is None:
            return envelope(UNAVAILABLE, None, f"The game has no tech tree window for {folder}")
        research = self.research(tag)
        rdata = research.get("data") or {}
        techs, _defines = self._technologies(roots)
        researched = set(rdata.get("researched") or [])
        slots = {s["technology"]: s for s in rdata.get("slots") or [] if s.get("technology")}
        year = rdata.get("game_year")
        in_tab = {tid: t for tid, t in techs.items() if folder in (t.get("positions") or {})}
        names = self._loc_names(install, {lb["text"] for lb in layout["labels"]})
        loc = lambda key: (clean_loc(names[key], names) if names.get(key) else None) or key  # noqa: E731
        tech_names = self._tech_names(install, set(in_tab), techs)
        sprites = gfx.sprites(roots)

        def sprite(name):
            texture = sprites.get(name)
            return gfx.icon_data_uri(texture) if texture else None

        def background(size, state):
            small = "small_" if size == "small" else ""
            for name in (f"GFX_technology_{folder}_{small}{state}_item_bg", f"GFX_technology_{small}{state}_item_bg",
                         f"GFX_technology_{state}_item_bg"):
                uri = sprite(name)
                if uri:
                    return uri
            return None
        items = []
        for tid, t in in_tab.items():
            grid = techtree.branch_grid(tid, techs, folder, layout["grids"])
            if grid is None:
                continue
            x, y = techtree.place(t["positions"][folder], grid)
            size = "big" if t.get("big") else "small"
            box = layout[size]
            excluded_by = [x for x in t.get("excludes") or [] if x in researched]
            if tid in researched:
                state = "researched"
            elif tid in slots:
                state = "researching"
            elif excluded_by:
                state = "excluded"
            elif researched and usable_for({"categories": ["*"]}, {tid: {**t, "categories": ["*"]}}, researched, set()):
                state = "available"
            else:
                state = "unavailable"
            slot = slots.get(tid) or {}
            items.append({"id": tid, "name": tech_names[tid], "x": x + box["dx"], "y": y + box["dy"], "w": box["w"],
                          "h": box["h"], "size": size, "state": state, "start_year": t.get("start_year"),
                          "ahead": bool(year and t.get("start_year") and t["start_year"] > year),
                          "progress": slot.get("progress"), "days_left": slot.get("days_left"),
                          "excludes": list(t.get("excludes") or []), "excluded_by": excluded_by,
                          "icon": sprite(f"GFX_{tid}_medium")})
        # big items sit 56 px left of their slot: shift the whole tab when one would start outside
        dx = max(0.0, 10 - min([i["x"] for i in items] + [10]))
        dy = max(0.0, 10 - min([i["y"] for i in items] + [10]))
        for i in items:
            i["x"] += dx
            i["y"] += dy
        layout = {**layout, "labels": [{**lb, "x": lb["x"] + dx, "y": lb["y"] + dy} for lb in layout["labels"]]}
        placed = {i["id"]: i for i in items}
        lines = [{"from": tid, "to": child} for tid in placed for child in techs[tid].get("leads_to") or []
                 if child in placed]
        # routes depend on the layout only (not on the country): computed once per tab and layout
        geometry = (folder, tuple((i["id"], i["x"], i["y"], i["w"], i["h"]) for i in items),
                    tuple((ln["from"], ln["to"]) for ln in lines))
        cache = self.__dict__.setdefault("_route_cache", {})
        if geometry not in cache:
            cache[geometry] = techtree.route_lines(items, lines)
        for ln, points in zip(lines, cache[geometry]):
            ln["points"] = [[round(x, 1), round(y, 1)] for x, y in points]
        # mutually exclusive pairs of this tab (names for the tooltips)
        names_of = {i["id"]: i["name"] for i in items}
        for i in items:
            i["excludes"] = [{"id": x, "name": names_of.get(x) or x} for x in i["excludes"]]
            i["excluded_by"] = [names_of.get(x) or x for x in i["excluded_by"]]
        width = max([i["x"] + i["w"] for i in items] + [lb["x"] + 200 for lb in layout["labels"]] + [400]) + 20
        height = max([i["y"] + i["h"] for i in items] + [lb["y"] + 60 for lb in layout["labels"]] + [300]) + 20
        backgrounds = {f"{size}_{state}": background(size, "currently_researching" if state == "researching" else state)
                       for size in ("big", "small") for state in ("researched", "researching", "available", "unavailable")}
        for size in ("big", "small"):
            backgrounds[f"{size}_excluded"] = backgrounds[f"{size}_unavailable"]
        data = {"tag": tag, "folder": folder, "tabs": tabs, "width": width, "height": height, "items": items,
                "lines": lines,
                "labels": [{**lb, "text": loc(lb["text"])} for lb in layout["labels"]],
                "backgrounds": backgrounds, "research_source": rdata.get("research_source"),
                "file": rdata.get("file"), "in_game_date": rdata.get("in_game_date")}
        return envelope(SAVE, data, f"{len(items)} technologies of {folder}.")

    def research(self, tag: str) -> dict:
        """Research slots of `tag` and what each one researches: game memory while the game runs, else the newest
        save; names and icons from the game files."""
        tag = tag.upper()
        install = self._install_path()
        picked = self._pick_save(None)
        if install is None:
            return envelope(UNAVAILABLE, None, "Needs the game installation")
        slots, analysis, live, live_date, bonuses, researched = None, None, False, None, None, None
        if self.live is not None:
            try:
                found = self.live.research(tag)
                slots, live_date, live = found["slots"], found.get("date"), True
                bonuses, researched = found.get("bonuses"), found.get("researched")
            except Exception:  # live data is optional: the save is the fallback
                slots = None
        if picked is not None:
            try:
                state = self.saves.politics(picked[0], tag)
                analysis = state.pop("analysis")
                if slots is None:
                    slots = state.get("research") or []
                    bonuses = state.get("research_bonuses") or []
                if researched is None:
                    researched = state.get("researched")
            except SaveFormatError as exc:
                if slots is None:
                    return envelope(UNAVAILABLE, None, str(exc))
        if slots is None:
            return envelope(UNAVAILABLE, None, "Needs the running game or a save")
        roots = self._game_roots(install)
        techs, defines = self._technologies(tuple(str(r) for r in roots))
        date = (analysis.get("header") or {}).get("date") if analysis else None
        today = None
        if live_date:
            today = live_date["year"] + live_date["day"] / 365
        elif isinstance(date, dict) and date.get("year"):
            today = date["year"] + (MONTH_START[(date.get("month") or 1) - 1] + (date.get("day") or 1) - 1) / 365
        ids = {s["technology"] for s in slots if s["technology"]}
        # research speed of the country: a slot researching without ahead-of-time penalty shows it
        plain = [s["speed"] for s in slots if s["technology"] and s.get("speed")
                 and not ahead_years(techs.get(s["technology"]), today)]
        country_speed = max(plain) if plain else None
        # used up (0 uses left) bonuses stay in game memory and the save - the game no longer offers them
        bonuses = [b for b in bonuses or [] if (b.get("uses") or 0) > 0]
        names = self._loc_names(install, ids | {b["name"] for b in bonuses if b["name"]}
                                    | {k for b in bonuses for c in b["categories"] for k in (c, f"{c}_research")})
        sprites = gfx.sprites(roots)
        usable = {b["id"]: usable_for(b, techs, set(researched or []), ids) for b in bonuses} if researched else {}
        tech_names = self._tech_names(install, ids | {t for u in usable.values() for t in u}, techs)
        out = []
        for s in slots:
            tech = s["technology"]
            sprite = sprites.get(f"GFX_{tech}_medium") if tech else None
            out.append({**s, "name": tech_names.get(tech) if tech else None,
                        "icon": gfx.icon_data_uri(sprite) if sprite else None,
                        **research_progress(s, techs.get(tech or ""), defines, today, country_speed)})
        loc = lambda key: (clean_loc(names[key], names) if key and names.get(key) else None) or key  # noqa: E731
        data = {"tag": tag, "slots": out, "research_source": "live" if live else "save",
                "researched": sorted(researched or []),
                "game_year": int(today) if today is not None else None,
                # categories as the game names research bonuses: "<category>_research" (Motorization Research Speed)
                "bonuses": [{**b, "label": loc(b["name"]),
                             "category_labels": [loc(f"{c}_research") if names.get(f"{c}_research") else loc(c)
                                                 for c in b["categories"]],
                             "usable": [{"id": t, "name": tech_names[t],
                                         "start_year": techs[t].get("start_year")}
                                        for t in usable.get(b["id"], [])]
                             if researched else None}
                            for b in sorted(bonuses, key=lambda b: b["id"])]}
        if analysis:
            data.update({"file": analysis["file"], "in_game_date": (analysis.get("header") or {}).get("date")})
        return envelope(SAVE, data, "Research from game memory." if live else "Research from the newest save.")

    def _live_resources(self, tag: str, order: list[str]) -> dict | None:
        """Live resources and trade deals of `tag`, or None (game not running, other version, ...)."""
        if self.live is None:
            return None
        try:
            return self.live.resources(tag, order)
        except Exception:  # live data is optional: the save values stay
            return None

    def _live_leadership(self, tag: str, roots: tuple[str, ...], state: dict) -> bool:
        """Replaces popularity, ruling party, leader and faction in `state` with the live ones of `tag`; the
        faction keeps the save's template and rules while its leader is the same. False when not readable."""
        live = self._live_parties(tag, roots)
        if not live:
            return False
        state["popularity"] = live["popularity"]
        state["ruling_party"] = live["ruling"] or state.get("ruling_party")
        if live.get("leader") and live["leader"]["id"] in (state.get("characters") or {}):
            state["leader"] = live["leader"]["id"]
            state["leader_ideology"] = live["leader"]["ideology"] or state.get("leader_ideology")
        if "faction" in live:
            saved, faction = state.get("faction") or {}, live["faction"]
            same = bool(faction and saved.get("members", [])[:1] == faction["members"][:1])
            state["faction"] = None if faction is None else {
                "members": faction["members"], "name": faction["name"], "icon": faction["icon"],
                "template": saved.get("template") if same else None, "rules": saved.get("rules", []) if same else [],
                "leader": faction["members"][0] == tag}
        return True

    def _live_penalties(self, tag: str, state: dict) -> bool:
        """Replaces the bombing / casualties war support penalties in `state` with the live ones of `tag`."""
        if self.live is None:
            return False
        try:
            live = self.live.penalties(tag)
            state.update({k: live[k] for k in ("bombing_penalty", "casualties_penalty")})
        except Exception:  # live data is optional: the save values stay
            return False
        return True

    def _game_totals(self, tag: str, result: dict) -> dict | None:
        """Adds the game's own modifier sums (memory) to `result`: the value the game shows on its top bar is base +
        those (+ the ruling party term for stability, which the game keeps apart), capped. What the app's known
        modifiers miss becomes an "UNKNOWN" part, so parts always add up to what the game shows."""
        if self.live is None:
            return None
        try:
            sums = self.live.modifier_sums(tag)
        except Exception:  # game not running / other version: the app's own sum stays
            return None
        for field, key in modifiers.KEYS.items():
            b = result[field]
            outside = sum(p["value"] for p in b["parts"] if p["kind"] == "party" or p["id"] in OUTSIDE_GAME_SUM)
            game = sums[key] + outside
            unknown = round(game - b["modifiers"], 6)
            if abs(unknown) >= 0.0005:
                b["parts"].append({"kind": "unknown", "id": "unknown", "name": "UNKNOWN", "value": unknown})
            b["modifiers"] = round(game, 6)
            b["modifiers_source"] = "live"
            raw = None if b["base"] is None else b["base"] + game
            b["total"] = None if raw is None else min(1.0, max(0.0, raw))
            b["clamped"] = raw is not None and not 0.0 <= raw <= 1.0
        return sums.get("date")

    def _live_war_stability(self, tag: str, state: dict) -> bool:
        """Sets state["war_stability_factor"] to the game's own sum (memory): "At war" uses it."""
        if self.live is None:
            return False
        try:
            state["war_stability_factor"] = self.live.modifier_sums(tag)["war_stability_factor"]
        except Exception:  # live data is optional: the app's known sources stay
            return False
        return True

    def _live_wars(self, tag: str, state: dict) -> bool:
        """Replaces state["wars"] with the live wars of `tag` (binary saves have none: tokens unknown)."""
        if self.live is None:
            return False
        try:
            state["wars"] = self.live.wars(tag)["wars"]
        except Exception:  # live data is optional: the save values stay
            return False
        return True

    def _live_doctrines(self, tag: str, state: dict, defs: dict, everyone: dict) -> bool:
        """Replaces state["doctrines"] with the live ones of `tag`. A name key shared by variants (e.g. x and
        x_no_lar) resolves to the variant this game uses in the save, else the first defined; unlocked rewards stay
        from the save for the same doctrine. False when not readable."""
        if self.live is None:
            return False
        try:
            keys = self.live.doctrines(tag)["names"]
        except Exception:  # live data is optional: the save values stay
            return False
        used = {d["id"] for st in everyone.values() for d in st.get("doctrines") or []}
        rewards = {d["id"]: d["rewards"] for d in state.get("doctrines") or []}
        out = []
        for key in keys:
            ids = defs["doctrine_names"].get(key) or [key]
            doctrine = next((i for i in ids if i in used), ids[0])
            out.append({"id": doctrine, "rewards": rewards.get(doctrine, 0)})
        state["doctrines"] = out
        return True

    def _live_parties(self, tag: str, roots: tuple[str, ...]) -> dict | None:
        """Live popularity / ruling party, or None (game not running, other version, ...)."""
        if self.live is None:
            return None
        try:
            return self.live.parties(tag, list(government_mod.ideologies(roots)["colors"]))
        except Exception:  # live data is optional: the save values stay
            return None

    def overview(self, tag: str) -> dict:
        """Who rules `tag`: leader (portrait, sub-ideology, traits), ruling party, faction, party popularities."""
        tag = tag.upper()
        install = self._install_path()
        picked = self._pick_save(None)
        if install is None or picked is None:
            return envelope(UNAVAILABLE, None, "Needs the game installation and a save")
        try:
            state = self.saves.politics(picked[0], tag)
        except SaveFormatError as exc:
            return envelope(UNAVAILABLE, None, str(exc))
        analysis = state.pop("analysis")
        state.pop("_all", None)
        roots = self._game_roots(install)
        defs = modifiers.definitions(roots)
        ideo = government_mod.ideologies(roots)
        live_parties = self._live_leadership(tag, roots, state)
        parties = state.get("party_names") or {}
        names_needed = set(parties) | {f"{i}_noun" for i in parties} | {state.get("leader_ideology") or ""}
        for ideology, p in parties.items():
            names_needed.update(filter(None, [p["name"], p["long_name"], f"{tag}_{ideology}_party",
                                              f"{tag}_{ideology}_party_long"]))
        faction = state.get("faction")
        template = (ideo["factions"].get((faction or {}).get("template") or "") or {})
        names_needed.update(filter(None, [(faction or {}).get("name"), template.get("name")]))
        leader = (state.get("characters") or {}).get(state.get("leader") or "")
        names_needed.update(filter(None, [leader and leader["name"], leader and leader["token"],
                                          *((leader or {}).get("leader_traits") or [])]))
        names = self._loc_names(install, names_needed)
        refs = {r for v in names.values() for r in LOC_REF.findall(v)}
        names.update(self._loc_names(install, refs - set(names)))
        loc = lambda *keys: next((clean_loc(names[k], names) for k in keys if k and names.get(k)), None)  # noqa: E731
        sprites = gfx.sprites(roots)
        icon = lambda sprite: gfx.icon_data_uri(sprites[sprite]) if sprite and sprite in sprites else None  # noqa: E731
        party_list = []
        for ideology, popularity in sorted((state.get("popularity") or {}).items(), key=lambda x: -x[1]):
            p = parties.get(ideology) or {}
            party_list.append({
                "ideology": ideology, "ideology_name": loc(f"{ideology}_noun", ideology) or ideology,
                "name": loc(p.get("name"), f"{tag}_{ideology}_party", ideology) or ideology,
                "long_name": loc(p.get("long_name"), f"{tag}_{ideology}_party_long"),
                "popularity": popularity, "ruling": ideology == state.get("ruling_party"),
                "color": "#%02x%02x%02x" % ideo["colors"].get(ideology, (128, 128, 128))})
        leader_out = None
        if leader:
            portrait = next((leader["portraits"].get(k, {}).get(s) for k in ("civilian", "army", "navy")
                             for s in ("large", "small") if leader["portraits"].get(k, {}).get(s)), None)
            leader_out = {
                "name": loc(leader["name"], leader["token"]) or leader["name"], "portrait": icon(portrait),
                "ideology": state.get("leader_ideology"), "ideology_name": loc(state.get("leader_ideology")),
                "traits": [{"name": loc(t) or t, "modifiers": [
                    {"key": k, "label": k.replace("_", " ").capitalize(), "value": v}
                    for k, v in defs["traits"].get(t, {}).items()]} for t in leader["leader_traits"]]}
            # proper modifier labels
            labels = self._loc_names(install, {f"MODIFIER_{m['key'].upper()}" for t in leader_out["traits"]
                                                   for m in t["modifiers"]})
            for t in leader_out["traits"]:
                for m in t["modifiers"]:
                    m["label"] = clean_loc(labels.get(f"MODIFIER_{m['key'].upper()}", ""), names) or m["label"]
        faction_out = None
        if faction:
            faction_out = {"name": loc(faction.get("name"), template.get("name")) or faction.get("name")
                           or template.get("name") or "Faction",
                           "icon": icon(faction.get("icon") or template.get("icon")), "members": faction["members"],
                           "leader": faction["members"][0] if faction["members"] else None}
        return envelope(SAVE, {"tag": tag, "leader": leader_out, "parties": party_list, "faction": faction_out,
                               "ruling_party": state.get("ruling_party"), "parties_source": "live" if live_parties else "save",
                               "file": analysis["file"],
                               "in_game_date": (analysis.get("header") or {}).get("date")},
                        f"Government from {analysis['file']['name']}.")

    # MIO window numbers (defines NIndustrialOrganisation): PP a day of an assigned design team, funds to the next level
    MIO_ASSIGN_COST = 0.1
    MIO_SIZE_UP = (700.0, 100.0, 1.8)   # FUNDS_FOR_SIZE_UP, _LEVEL_FACTOR, _LEVEL_POW

    @staticmethod
    def _mio_keys(tag: str, it: dict):
        """(name keys of a MIO, function trait -> its name keys, function (kind, stat) -> label keys)."""
        n = it.get("name_key")
        names = [k for k in (f"{tag}_{n}" if n else None, n, f"{tag}_{it['id']}", it["id"]) if k]
        def trait_keys(t):
            tn = t.get("name")
            return [k for k in (f"{tag}_{tn}" if tn else None, tn, f"{tag}_{it['id']}_{t.get('token')}",
                                f"{it['id']}_{t.get('token')}", t.get("token")) if k]
        def stat_keys(kind, stat):
            if kind == "equipment_bonus":
                return [f"STAT_{p}_{stat.upper()}" for p in ("ARMY", "COMMON", "NAVY", "AIR")] + [stat]
            return [f"BONUS_{stat.upper()}", stat] if kind == "production_bonus" else [f"MODIFIER_{stat.upper()}", stat]
        return names, trait_keys, stat_keys

    def _mio_loc(self, install: Path, keys: set[str]):
        """Function (candidate keys, fallback) -> the first localised text (references $x$ resolved)."""
        names = self._loc_names(install, keys)
        refs = {r for v in names.values() for r in LOC_REF.findall(v)}
        names.update(self._loc_names(install, refs - set(names)))
        def loc(cands, fallback):
            for k in cands:
                v = clean_loc(names[k], names).rstrip(": ").strip() if k in names else ""
                if v and "$" not in v:
                    return v
            return (fallback or "").replace("_", " ").capitalize()
        return loc

    def _live_mios(self, tag: str, state: dict) -> bool:
        """Replaces state["mios"] with the live level, funds, unlocked traits and policy of `tag`'s MIOs."""
        if self.live is None:
            return False
        try:
            state["mios"] = self.live.mios(tag)["mios"]
        except Exception:  # live data is optional: the save values stay
            return False
        return True

    @staticmethod
    def _country_mio_modifiers(state: dict, roots: tuple[str, ...]) -> dict[str, float]:
        """{military_industrial_organization_* modifier: total} of the country's ideas, leader, advisors and dynamic
        modifiers (GER 1940: +15% research bonus, +15% funds gain from its spirits)."""
        try:
            sources = modifiers.country_sources(state, modifiers.definitions(roots))
        except Exception:  # an unreadable modifier source must not hide the MIOs
            return {}
        out: dict[str, float] = {}
        for _kind, _id, _label, mods in sources:
            for k, v in mods.items():
                if k.startswith("military_industrial_organization_"):
                    out[k] = round(out.get(k, 0.0) + v, 6)
        return out

    def _mio_attributes(self, it: dict, country: dict[str, float]) -> dict:
        """Attributes of the MIO window: research bonus, design team assign cost a day, funds gain, size up progress."""
        org = (it.get("bonuses") or {}).get("organization_modifier") or {}
        total = lambda key: org.get(key, 0.0) + country.get(key, 0.0)  # noqa: E731
        base, factor, power = self.MIO_SIZE_UP
        size = it.get("size") or 0
        need = base + factor * size ** power
        assign = it.get("assign_cost") if it.get("assign_cost") is not None else self.MIO_ASSIGN_COST
        return {"research_bonus": round((it.get("research_bonus") or 0.0) + country.get(mio_mod.RESEARCH_BONUS, 0.0), 4),
                "assign_cost": round(assign * max(0.0, 1 + total("military_industrial_organization_design_team_assign_cost")), 4),
                "funds_gain": round((it.get("funds_factor") or 1.0) * (1 + total("military_industrial_organization_funds_gain")) - 1, 4),
                "funds_needed": round(need, 1),
                "progress": round(min(1.0, (it.get("funds") or 0.0) / need), 4) if need else None}

    def _mios(self, state: dict, tag: str, install: Path, roots: tuple[str, ...]) -> dict[str, list[dict]]:
        """{design slot: [MIO for display]} - level, funds, policy, unlocked traits and current bonuses."""
        defs = mio_mod.definitions(roots)
        items = [s for s in (mio_mod.summary(m, defs) for m in state.get("mios") or []) if s]
        country = self._country_mio_modifiers(state, roots)
        keys = {"MODIFIER_MIO_RESEARCH_BONUS"}
        for it in items:
            names, trait_keys, stat_keys = self._mio_keys(tag, it)
            keys.update(names)
            keys.update(k for t in it["traits"] + ([it["initial_trait"]] if it["initial_trait"] else []) for k in trait_keys(t))
            keys.add(it["policy"] or "")
            keys.update(k for kind, stats in it["bonuses"].items() for s in stats for k in stat_keys(kind, s))
        loc = self._mio_loc(install, keys)
        sprites = gfx.sprites(roots)
        groups = {"equipment_bonus": "Equipment", "production_bonus": "Production", "organization_modifier": "Organization"}
        out: dict[str, list[dict]] = {c: [] for c in mio_mod.CATEGORIES}
        for it in sorted(items, key=lambda i: (-(i["size"] or 0), i["id"])):
            names, trait_keys, stat_keys = self._mio_keys(tag, it)
            texture = sprites.get(it["icon"] or "")
            attributes = self._mio_attributes(it, country)
            out[it["category"]].append({
                "id": it["id"], "name": loc(names, it["id"].removesuffix("_organization")),
                "icon": gfx.icon_data_uri(texture) if texture else None, "size": it["size"], "funds": it["funds"],
                "research_bonus": attributes["research_bonus"], "attributes": attributes,
                "policy": loc([it["policy"]], it["policy"]) if it["policy"] else None,
                "initial_trait": loc(trait_keys(it["initial_trait"]), it["initial_trait"].get("token") or "initial trait")
                if it["initial_trait"] else None,
                "traits": [loc(trait_keys(t), t.get("token")) for t in it["traits"]],
                "bonuses": [{"group": groups[kind], "entries": [
                    {"key": stat, "label": "Research bonus" if stat == mio_mod.RESEARCH_BONUS
                     else loc(stat_keys(kind, stat), stat), "value": v} for stat, v in stats.items() if v]}
                    for kind, stats in it["bonuses"].items() if any(stats.values())],
            })
        return out

    def mio_tree(self, tag: str, mio_id: str) -> dict:
        """Trait tree of one MIO of `tag` as the game's MIO window: column headers, traits at their grid positions with
        icons, bonuses, parents and exclusions, which are unlocked (game memory when the game runs, else the newest
        save), level, funds, policy and attributes."""
        tag = tag.upper()
        install = self._install_path()
        picked = self._pick_save(None)
        if install is None:
            return envelope(UNAVAILABLE, None, "Needs the game installation")
        state: dict = {"mios": []}
        if picked is not None:
            try:
                state = self.saves.politics(picked[0], tag)
                state.pop("analysis", None)
                state.pop("_all", None)
            except SaveFormatError:
                state = {"mios": []}
        live = self._live_mios(tag, state)
        self._live_ideas(tag, state)
        self._live_advisors(tag, state)
        roots = self._game_roots(install)
        defs = mio_mod.definitions(roots)
        mine = next((m for m in state.get("mios") or [] if m.get("id") == mio_id), None) or {"id": mio_id}
        it = mio_mod.summary(mine, defs)
        tree = mio_mod.tree(defs, mio_id, mine.get("traits"))
        if it is None or tree is None:
            return envelope(UNAVAILABLE, None, f"{mio_id} is not a military industrial organisation of the game files")
        names, trait_keys, stat_keys = self._mio_keys(tag, it)
        policy = defs["policies"].get(it["policy"] or "") or {}
        bonus_sources = tree["traits"] + ([tree["initial_trait"]] if tree["initial_trait"] else []) + [policy]
        keys = set(names) | {h["text"] for h in tree["headers"]} | {it["policy"] or ""}
        keys.update(k for t in tree["traits"] + ([tree["initial_trait"]] if tree["initial_trait"] else []) for k in trait_keys(t))
        for src in bonus_sources:
            for kind in mio_mod.BONUS_KINDS:
                keys.update(k for stat in src.get(kind) or {} for k in stat_keys(kind, stat))
                for scope, stats in (src.get(f"{kind}_scoped") or {}).items():
                    keys.add(scope)
                    keys.update(k for stat in stats for k in stat_keys(kind, stat))
        keys.update(e for t in tree["traits"] for e in t.get("limit_to") or [])
        loc = self._mio_loc(install, keys)
        sprites = gfx.sprites(roots)
        icon = lambda name: gfx.icon_data_uri(sprites[name]) if name and name in sprites else None  # noqa: E731

        def bonuses(src: dict) -> list[dict]:
            out = []
            for kind in mio_mod.BONUS_KINDS:
                for stat, v in (src.get(kind) or {}).items():
                    if v:
                        out.append({"kind": kind, "key": stat, "scope": None, "value": v,
                                    "label": "Research bonus" if stat == mio_mod.RESEARCH_BONUS else loc(stat_keys(kind, stat), stat)})
                for scope, stats in (src.get(f"{kind}_scoped") or {}).items():
                    out.extend({"kind": kind, "key": stat, "scope": loc([scope], scope), "value": v,
                                "label": loc(stat_keys(kind, stat), stat)} for stat, v in stats.items() if v)
            return out

        def trait_icon(t: dict) -> str | None:
            for name in (t.get("icon"), f"GFX_{tag}_{it['id']}_{t['token']}", f"GFX_{it['id']}_{t['token']}"):
                if name and name in sprites:
                    return icon(name)
            return icon("GFX_industrial_org_trait_placeholder")

        frames = gfx.sprite_frames(roots)
        def strip(name: str) -> list[str | None]:
            texture, n = sprites.get(name), frames.get(name) or 1
            return [gfx.frame_data_uri(texture, i, n) for i in range(1, n + 1)] if texture else []

        traits = [{"token": t["token"], "name": loc(trait_keys(t), t["token"]), "icon": trait_icon(t), "x": t["x"], "y": t["y"],
                   "parents": t["parents"], "parents_needed": t["parents_needed"], "exclusive": t["exclusive"],
                   "special": t["special"], "kinds": t["kinds"], "unlocked": t["unlocked"],
                   "limit_to": [loc([e], e) for e in t.get("limit_to") or []], "bonuses": bonuses(t)}
                  for t in tree["traits"]]
        initial = tree["initial_trait"]
        texture = sprites.get(it["icon"] or "")
        attributes = self._mio_attributes(it, self._country_mio_modifiers(state, roots))
        return envelope(SAVE, {
            "tag": tag, "id": mio_id, "name": loc(names, mio_id.removesuffix("_organization")),
            "icon": gfx.icon_data_uri(texture) if texture else None, "category": it["category"],
            "size": it["size"], "funds": it["funds"], "attributes": attributes,
            "policy": {"name": loc([it["policy"]], it["policy"]), "icon": icon(policy.get("icon")), "bonuses": bonuses(policy)}
            if it["policy"] else None,
            "initial_trait": {"name": loc(trait_keys(initial), initial.get("token") or "initial trait"), "bonuses": bonuses(initial),
                              "limit_to": [loc([e], e) for e in initial.get("limit_to") or []]} if initial else None,
            "headers": [{"text": loc([h["text"]], h["text"]), "x": h["x"]} for h in tree["headers"]],
            "traits": traits, "width": tree["width"], "height": tree["height"],
            "unlocked_count": sum(t["unlocked"] for t in traits),
            "sprites": {"frame": strip("GFX_industrial_org_trait_button"), "special": strip("GFX_country_spefific_org_trait_button"),
                        "exclusive": strip("GFX_focus_link_exclusive"),
                        "equipment_bonus": icon("GFX_design_team_icon"), "production_bonus": icon("GFX_industrial_manufacturer_icon"),
                        "organization_modifier": icon("GFX_organization_modifier_icon")},
            "source": "live" if live else "save",
        }, "MIO state from game memory." if live else "MIO state from the newest save (the game is not read).")

    def _present(self, items: list[dict], install: Path, roots: tuple[str, ...]) -> list[dict]:
        """Localised names, descriptions, modifier labels, trait names and icons (data: URIs) for display."""
        keys = set()
        for it in items:
            keys.update(filter(None, [it["name_key"], it.get("alt_name_key"), it.get("slot"),
                                      f"{it['name_key']}_desc", f"{it['id']}_desc", *it["tooltips"], *it.get("traits", [])]))
            keys.update(k for m in it["modifiers"] for k in (f"MODIFIER_{m.upper()}", m))
        names = self._loc_names(install, keys)
        refs = {r for v in names.values() for r in LOC_REF.findall(v)}
        names.update(self._loc_names(install, refs - set(names)))
        clean = lambda value: clean_loc(value, names) if value else value  # noqa: E731
        sprites = gfx.sprites(roots)
        out = []
        for it in items:
            texture = sprites.get(it["icon"] or "")
            if texture is None and it["icon"] and it["icon"].lower().endswith((".dds", ".png")):
                texture = next((str(Path(r) / it["icon"]) for r in reversed(roots) if (Path(r) / it["icon"]).exists()), None)
            name = clean(names.get(it["name_key"] or "") or names.get(it.get("alt_name_key") or ""))
            out.append({
                "kind": it["kind"], "id": it["id"], "slot": it.get("slot"), "slot_label": it.get("slot_label"),
                "name": name or (it["name_key"] or "").split("_", 1)[-1].replace("_", " ").title() or None,
                "traits": [clean(names.get(t)) or t for t in it.get("traits", [])],
                "description": clean(names.get(f"{it['name_key']}_desc") or names.get(f"{it['id']}_desc"))
                if it["name_key"] else None,
                "icon": gfx.icon_data_uri(texture) if texture else None,
                "modifiers": [{"key": k, "label": clean(names.get(f"MODIFIER_{k.upper()}") or names.get(k))
                               or k.replace("_", " ").capitalize(), "value": v} for k, v in it["modifiers"].items()],
                "tooltips": [clean(names.get(t)) or t for t in it["tooltips"]],
            })
        return out

    def stability(self, tag: str) -> dict:
        """Stability and war support as the game shows them: base + every modifier with its source.

        Modifiers come from the newest save (ideas, party popularity, leader, advisors, dynamic modifiers) and the
        game files; the base value from game memory when the game runs (it changes instantly), else from the save."""
        tag = tag.upper()
        install = self._install_path()
        picked = self._pick_save(None)
        if install is None or picked is None:
            return envelope(UNAVAILABLE, None, "Needs the game installation and a save")
        path = picked[0]
        try:
            state = self.saves.politics(path, tag)
        except SaveFormatError as exc:
            return envelope(UNAVAILABLE, {"file": path.name, "error": {"code": exc.code, "message": str(exc)}},
                            str(exc))
        analysis = state.pop("analysis")
        everyone = state.pop("_all", {})
        state["buildings"] = self._controlled_buildings(path, install, tag)
        live_ideas = self._live_ideas(tag, state)
        live_advisors = self._live_advisors(tag, state)
        userdata = (self.detect().get("userdata") or {}).get("path")
        mods = gamefiles.enabled_mods(Path(userdata)) if userdata else []
        defs = modifiers.definitions(tuple(str(r) for r in [install, *mods]))
        self._live_leadership(tag, tuple(str(r) for r in [install, *mods]), state)
        live_doctrines = self._live_doctrines(tag, state, defs, everyone)
        live_penalties = self._live_penalties(tag, state)
        live_wars = self._live_wars(tag, state)
        self._live_war_stability(tag, state)
        names =self._loc_names(install, modifiers.loc_keys(state, defs))
        base_source = {}
        for field in modifiers.KEYS:
            base_source[field] = "save"
            if self.live is not None:
                try:
                    state[field] = self.live.read(field, tag)["value"]
                    base_source[field] = "live"
                except Exception:  # game not running / other version: the save value stays
                    pass
        result = modifiers.breakdown(state, defs, names)
        for field in modifiers.KEYS:
            result[field]["base_source"] = base_source[field]
        game_date = self._game_totals(tag, result)
        game = self.detect()
        header_date = (analysis.get("header") or {}).get("date")
        return envelope(SAVE, {
            "tag": tag, **result, "save_mismatch": save_mismatch(header_date, game_date), "ideas_source": "live" if live_ideas else "save",
            "advisors_source": "live" if live_advisors else "save",
            "doctrines_source": "live" if live_doctrines else "save",
            "penalties_source": "live" if live_penalties else "save", "wars_source": "live" if live_wars else "save", "file": analysis["file"],
            "in_game_date": (analysis.get("header") or {}).get("date"),
            "freshness": save_freshness(analysis["file"]["mtime"], game),
            "not_read": ["core coastal states protection", "foreign propaganda", "convoys raided", "attache sent",
                         "sunk Pride of the Fleet"] + [f"faction rule {r} (condition)"
                                                                  for r in result["unchecked_rules"]],
        }, f"Modifiers from {analysis['file']['name']} and the game files.")

    def country_save_values(self, tag: str, name: str | None) -> dict:
        """Real Country Editor values read from a save (snapshot). Never presented as live."""
        tag = tag.upper()
        picked = self._pick_save(name)
        if picked is None:
            return envelope(UNAVAILABLE, None, "No save file available")
        path, extra = picked
        read_at = dt.datetime.now().isoformat(timespec="seconds")
        try:
            out = self.saves.country_values(path, tag)
        except SaveFormatError as exc:
            return envelope(UNAVAILABLE, {"file": path.name, "error": {"code": exc.code, "message": str(exc)}},
                            str(exc))
        except ValueError as exc:
            raise NotFound(str(exc)) from exc
        analysis = out["analysis"]
        game = self.detect()
        return envelope(SAVE, {
            "tag": tag,
            "values": out["values"],
            "file": analysis["file"],
            "in_game_date": (analysis.get("header") or {}).get("date"),
            "save_version": (analysis.get("header") or {}).get("version"),
            "player_tag": (analysis.get("header") or {}).get("player_tag"),
            "freshness": save_freshness(analysis["file"]["mtime"], game),
            "read_at": read_at,
            **extra,
        }, SAVE_NOTE)

    def player_save_values(self) -> dict:
        """Values of the player country of the newest save (evidence source for live calibration)."""
        analysis = self.save_analysis(None)
        data = analysis.get("data") or {}
        tag = (data.get("header") or {}).get("player_tag")
        if analysis["source"] != SAVE or not tag:
            error = data.get("error") or {}
            note = (f"{error['message']} [{error.get('code')}]" if error.get("message")
                    else analysis.get("note") if analysis["source"] != SAVE else "Newest save has no player country")
            return envelope(UNAVAILABLE, {"error": error} if error else None, note)
        return self.country_save_values(tag, None)

    def save_fields(self) -> dict:
        return envelope(LIVE, save_fields.field_catalog())

    def tools(self) -> dict:
        return envelope(LIVE, TOOLS)

    def tool_changes(self) -> dict:
        """Every way the app changes the game, with its method and whether it is allowed now (game_tools.changes)."""
        mode, mp, running, supported = None, {}, False, False
        if self.live is not None:
            process = self.live.status().get("process")
            running = bool(process)
            if running:
                from .live import pointers   # live is optional (--no-game): imported only here
                supported = pointers.supported(process.get("version"))
                mp = self.live.multiplayer_writes()
                mode = mp.get("mode")
        return envelope(LIVE, {"mode": mode, "running": running, "version_supported": supported,
                               "multiplayer_writes": {"enabled": bool(mp.get("enabled")), "fog": bool(mp.get("fog"))},
                               "changes": game_tools.changes(mode, mp, running, supported)})

    def checkpoints(self, data=None) -> dict:
        """Campaign checkpoints: the saves with their header and the user's notes; with `data` {"name", "note"} the
        note on one save is set (an empty note removes it)."""
        directory = self.integration.saves_dir()
        if data is not None:
            try:
                self._checkpoints.set_note(directory, str(data.get("name", "")), str(data.get("note", "")))
            except LookupError as exc:
                raise NotFound(str(exc)) from None
            except ValueError as exc:
                raise ReportError(str(exc)) from None
        if directory is None:
            return envelope(UNAVAILABLE, {"directory": None, "saves": [], "total": 0, "orphan_notes": []},
                            "Save folder not found")
        return envelope(SAVE, self._checkpoints.list(directory))

    def live_check(self) -> dict:
        """Every live memory reader once (game_tools.live_check), read-only."""
        if self.live is None:
            return envelope(UNAVAILABLE, {"running": False, "checks": []}, "Live game access is disabled (--no-game)")
        return envelope(LIVE, game_tools.live_check(self.live))

    # -- Options: the app's data folder ------------------------------------------------------------------
    DATA_PARTS = {"ic-history": "Recorded campaigns (Game summary, Players actions)", "backgrounds": "Background images",
                  "logs": "Application log", "reports": "Test reports", "save-cache": "Copies of read saves",
                  "live": "Live reading settings"}

    def data_usage(self) -> dict:
        """Size of each part of the data folder and of each recorded campaign (all its files)."""
        root = Path(self.data_dir or ".")

        def size(path: Path) -> tuple[int, int]:
            files = [p for p in path.rglob("*") if p.is_file()] if path.is_dir() else []
            return sum(p.stat().st_size for p in files), len(files)
        parts = []
        for name, label in self.DATA_PARTS.items():
            total, count = size(root / name)
            parts.append({"name": name, "label": label, "size": total, "files": count})
        folder = root / "ic-history"
        campaigns = []
        for g in self.ic_history.games():
            total = sum(p.stat().st_size for p in folder.glob(f"{g['id']}.*") if p.is_file())
            campaigns.append({"id": g["id"], "player": g["player"], "first": g["first"], "last": g["last"],
                              "days": g["days"], "created": g["created"], "active": g["active"], "size": total})
        return {"data": {"path": str(root.resolve()), "parts": parts, "campaigns": campaigns,
                         "total": sum(p["size"] for p in parts)}}

    def data_cleanup(self, data) -> dict:
        """Automatic clean-up (Options): deletes recorded campaigns not recorded for more than `days` days, then the
        oldest ones while the data folder is above `limit_mb` MB. The campaign being recorded is never deleted."""
        data = data if isinstance(data, dict) else {}
        days, limit = data.get("days") or 0, data.get("limit_mb") or 0
        if not isinstance(days, (int, float)) or not isinstance(limit, (int, float)) or days < 0 or limit < 0:
            raise ReportError("days and limit_mb must be numbers >= 0")
        folder = Path(self.data_dir or ".") / "ic-history"

        def touched(gid: str) -> float:
            return max((p.stat().st_mtime for p in folder.glob(f"{gid}.*") if p.is_file()), default=0.0)
        deleted = []
        games = [g for g in self.ic_history.games() if not g["active"]]
        if days:
            cutoff = time.time() - days * 86400
            for g in games:
                if touched(g["id"]) < cutoff:
                    self.ic_history.delete(g["id"])
                    deleted.append(g["id"])
        if limit:
            left = sorted((g for g in games if g["id"] not in deleted), key=lambda g: touched(g["id"]))
            while left and self.data_usage()["data"]["total"] > limit * 1024 * 1024:
                gid = left.pop(0)["id"]
                self.ic_history.delete(gid)
                deleted.append(gid)
        if deleted:
            self.log.info("Options: clean-up deleted %d campaign(s): %s", len(deleted), ", ".join(deleted))
        return {"data": {"deleted": deleted, **self.data_usage()["data"]}}

    # -- Options: the user's background images (backgrounds.py) ----------------------------------------
    def backgrounds_list(self) -> dict:
        return {"data": self.backgrounds.list()}

    def background_add(self, data) -> dict:
        data = data if isinstance(data, dict) else {}
        try:
            item = self.backgrounds.add(data.get("name"), data.get("data"), time.strftime("%Y-%m-%d %H:%M:%S"))
        except BackgroundError as exc:
            raise ReportError(str(exc)) from None
        self.log.info("Options: background %s added (%s, %d bytes)", item["id"], item["name"], item["size"])
        return {"data": item}

    def background(self, bid: str) -> dict:
        try:
            return {"data": {"id": bid, "uri": self.backgrounds.get(bid)}}
        except (FileNotFoundError, BackgroundError):
            raise NotFound(f"No background {bid}") from None

    def background_delete(self, bid: str) -> dict:
        try:
            self.backgrounds.delete(bid)
        except (FileNotFoundError, BackgroundError):
            raise NotFound(f"No background {bid}") from None
        self.log.info("Options: background %s deleted", bid)
        return self.backgrounds_list()

    # -- logs & reports -------------------------------------------------------------------
    def app_log(self, limit: int, level: str, after: int) -> dict:
        return envelope(LIVE, self.ring.entries(limit=limit, min_level=level, after_seq=after))

    def client_log(self, payload: dict) -> dict:
        level = str(payload.get("level", "info")).lower()
        message = str(payload.get("message", ""))[:2000]
        log_fn = {"debug": self.log.debug, "warning": self.log.warning, "error": self.log.error}.get(level, self.log.info)
        log_fn("%s", message, extra={"origin": "ui"})
        return {"ok": True}

    def game_log_names(self) -> dict:
        names = self.integration.game_log_names()
        return envelope(LIVE if names else UNAVAILABLE, names)

    def game_log(self, name: str, lines: int) -> dict:
        data = self.integration.game_log(name, lines)
        if data is None:
            return envelope(UNAVAILABLE, None, f"Log '{name}' is not available")
        return envelope(LIVE, data)

    def list_reports(self) -> dict:
        return envelope(LIVE, self.reports.list())

    def get_report(self, report_id: str) -> dict:
        report = self.reports.get(report_id)
        if report is None:
            raise NotFound(f"Unknown report: {report_id}")
        return envelope(LIVE, report)

    def create_report(self, payload: dict) -> dict:
        status = self.status()
        environment = {"app": status["app"], "game": {k: status["game"].get(k) for k in
                                                       ("detected", "process", "install", "session")}}
        report = self.reports.create(payload, environment)
        self.log.info("Test report saved: %s", report["id"])
        return envelope(LIVE, report)
