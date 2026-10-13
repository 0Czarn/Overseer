"""Debugger service: combines the game integration layer, DEMO data and reports
into the payloads served by the API. Contains no HTTP and no UI code."""

from __future__ import annotations

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
from . import mio as mio_mod
from . import focus as focus_mod
from . import techtree
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
    {"id": "debug_overlay", "name": "Debug visibility preview", "scope": "local", "status": "planned",
     "description": "Shows extra information inside the debugger only. Never changes what other players see."},
    {"id": "value_edit", "name": "Shared value change", "scope": "shared", "status": "planned",
     "description": "Changing country/state/equipment values. Requires a game-compatible sync method, "
                    "verified on two clients before it is offered in multiplayer."},
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
PLANE_STAT_LABELS = {"range": "Range", "air_defence": "Air Defense", "air_attack": "Air Attack", "air_agility": "Agility",
                     "air_superiority": "Air Superiority", "naval_strike_attack": "Naval Attack",
                     "naval_strike_targetting": "Naval Targeting", "maximum_speed": "Max Speed",
                     "reliability": "Reliability", "weight": "Weight", "thrust": "Thrust", "fuel_consumption": "Fuel Usage",
                     "build_cost_ic": "Production Cost"}


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
        tags = gamefiles.tag_order(install) if install else []
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

    def states(self, owner: str | None = None) -> dict:
        """States of the newest save (snapshot) with names and provinces from the game files; DEMO without them."""
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
                             "date": live.get("date")}
            except Exception:  # game not running, main menu, other version: the save is the fallback
                state = None
        if state is None:
            picked = self._pick_save(None)
            if picked is None:
                return None
            state = {**self.saves.focus_state(picked[0], tag), "source": "save"}
        userdata = (self.detect().get("userdata") or {}).get("path")
        folders = focus_mod.focus_folders(install, gamefiles.enabled_mods(Path(userdata)) if userdata else [])
        focuses = focus_mod.statuses(focus_mod.tree(folders, state["tree"]), state) if state["tree"] else []
        names = focus_mod.loc_names(install, {f["id"] for f in focuses})
        for f in focuses:
            name = names.get(f["id"])
            # scripted names ([GetSomething]) are resolved by the game at runtime - show a readable id instead
            f["name"] = name if name and "[" not in name else f["id"].split("_", 1)[-1].replace("_", " ").capitalize()
        return state, focuses

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
        descs = focus_mod.loc_names(install, {f"{f['id']}_desc" for f in focuses})
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

    def focus(self, tag: str) -> dict:
        """Focus tree of `tag` (game/mod files) laid out like the game's focus screen, with statuses from game
        memory while the game runs (else the newest save); the queue is a plan."""
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
        data = {
            "tag": tag, "tree": state["tree"], "current": state["current"], "progress_days": state["progress"],
            "paused": state["paused"], "completed": len(state["completed"]), "focuses": focuses,
            "queue": focus_mod.validate_queue(focuses, state, queue), "queue_supported": False,
            "focus_source": state["source"], "game_date": state.get("date"), "layout": focus_mod.layout(focuses),
            **self._focus_graphics(focuses)}
        if state["source"] == "live":
            return envelope(LIVE, data, f"Focus tree {state['tree']} from the game files; state of {tag} from game memory.")
        analysis = state["analysis"]
        header = analysis.get("header") or {}
        data.update(file=analysis["file"], in_game_date=header.get("date"),
                    freshness=save_freshness(analysis["file"]["mtime"], self.detect()))
        return envelope(SAVE, data, f"Focus tree {state['tree']} from the game files; state of {tag} from "
                                    f"{analysis['file']['name']} ({(header.get('date') or {}).get('text') or '?'}). "
                                    "Snapshot - not live.")

    def focus_state(self, tag: str) -> dict:
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
        by_id = {f["id"]: f for f in focuses}
        nxt = next((q for q in queue if q["ok"]), None)
        return envelope(LIVE if state["source"] == "live" else SAVE, {
            "tag": tag, "tree": state["tree"], "current": state["current"], "progress_days": state["progress"],
            "focus_source": state["source"], "queue": queue, "game_date": state.get("date"),
            "statuses": {f["id"]: {"status": f["status"], "progress": f["progress"], "missing": f["missing"]} for f in focuses},
            "next": {"id": nxt["id"], "name": by_id[nxt["id"]]["name"], "days": by_id[nxt["id"]]["days"]} if nxt else None,
        }, "Focus state from game memory." if state["source"] == "live" else "Focus state from the newest save.")

    def focus_autostart(self, apply: bool) -> dict:
        """Next focus of the PLAYER's plan, started in game memory when no focus is selected (apply=True; LOCAL write,
        single player). Focuses with start conditions the app cannot check or with effects on picking are left to
        the player ("manual"). state: busy (a focus runs), empty (no valid focus in the plan), manual, ready
        (preview), started."""
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
        if f.get("start_conditions") or f.get("select_effect"):
            why = " and ".join(w for w, on in (("conditions the app cannot check", f.get("start_conditions")),
                                               ("effects when it is picked", f.get("select_effect"))) if on)
            return {**out, "state": "manual", "reason": f"has {why} - start it in the game"}
        if not apply:
            return {**out, "state": "ready"}
        self.live.start_focus(f["id"])
        return {**out, "state": "started"}

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

    def live_stockpile(self, tag: str | None = None) -> dict:
        """Live stockpile (game memory) with archetype / equipment type from the newest save's variant table."""
        if self.live is None:
            raise NotFound("Live game access is disabled")
        live = self.live.stockpile(tag)
        install = self._install_path()
        picked = self._pick_save(None)
        variants, names, archetypes = {}, {}, {}
        if install and picked is not None:
            try:
                variants = self.saves.equipment(picked[0], live["tag"])["variants"]
            except SaveFormatError:
                variants = {}
            names = gamefiles.equipment_names(install)
            archetypes = deficit.tables(install)[1]
        entries = []
        for e in live["entries"]:
            v = variants.get(e["id"]) or {}
            eq_type = v.get("type")
            entries.append({**e, "type": eq_type, "type_name": names.get(eq_type, eq_type) if eq_type else None,
                            "archetype": deficit.archetype_of(eq_type, archetypes) if eq_type else None,
                            "name": e["name"] or v.get("name")})
        return {"data": {"tag": live["tag"], "entries": entries, "read_at": live["read_at"]}}

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
                names = gamefiles.equipment_names(install)
                items = save_equipment.rows(data, names)
                balance = deficit.compute(data, needs, archetypes)
                groups: dict[str, dict] = {}
                for item in items:
                    if item["pool"] != "stockpile":
                        continue
                    a = deficit.archetype_of(item["archetype"], archetypes)
                    g = groups.setdefault(a, {"archetype": a, "name": names.get(a, a.replace("_", " ").capitalize()),
                                              "variants": []})
                    g["variants"].append(item)
                for a, b in balance.items():
                    if b["need"] or b["stockpile"]:
                        groups.setdefault(a, {"archetype": a, "name": names.get(a, a.replace("_", " ").capitalize()),
                                              "variants": []})
                for a, g in groups.items():
                    g.update({k: balance.get(a, {}).get(k, 0.0) for k in ("need", "held", "missing", "shortfall")})
                    g["stockpile"] = sum(v["amount"] for v in g["variants"])
                ordered = sorted(groups.values(), key=lambda g: (-g["shortfall"], g["name"]))
                return envelope(SAVE, {
                    "tag": tag, "items": items, "groups": ordered,
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
        roots = self._game_roots(install)
        defs = modifiers.definitions(roots)
        groups = government_mod.sections(state, defs)
        flat = [it for items in groups.values() for it in items]
        shown = iter(self._present(flat, install, roots))
        data = {name: [next(shown) for _ in items] for name, items in groups.items()}
        data["mios"] = self._mios(state, tag, install, roots)
        return envelope(SAVE, {"tag": tag, **data, "ideas_source": "live" if live else "save",
                               "advisors_source": "live" if live_advisors else "save", "file": analysis["file"],
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
        names = focus_mod.loc_names(install, {f"PRODUCTION_MATERIALS_{k.upper()}" for k in keys})
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
        names = focus_mod.loc_names(install, keys)
        names.update(focus_mod.loc_names(install, {r for v in names.values() for r in LOC_REF.findall(v)} - set(names)))
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
        names = focus_mod.loc_names(install, {line["building"] for line in lines} | {f"VICTORY_POINTS_{p}" for p in ends})
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
        return envelope(LIVE, {"tag": tag, "lines": out, "factories": factories, "construction_source": "live",
                               "game_date": found.get("date")},
                        "Construction queue from game memory.")

    def construction_sort(self, apply: bool) -> dict:
        """Player's construction queue with civilian factories closest to completion first (live/service.py
        sort_construction); moved lines named by their state like the construction tab."""
        if self.live is None:
            from .live.service import LiveError   # live is optional (--no-game): imported only here
            raise LiveError("disabled", "Live game access is disabled (--no-game)")
        res = self.live.sort_construction(apply)
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
        loc = focus_mod.loc_names(install, {f"PRODUCTION_MATERIALS_{r.upper()}" for r in trade_mod.RESOURCES})
        for row in advice["resources"]:
            row["name"] = loc.get(f"PRODUCTION_MATERIALS_{row['resource'].upper()}", row["resource"].capitalize())
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
        names = focus_mod.loc_names(install, keys)
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
        ids = {u for t in army["templates"] for k in ("battalions", "support", "regimental") for u in t[k]}
        ids |= {sh["type"] for sh in navy["ships"]} | {g["role"] for g in air}
        stat_keys = {k for g in air + reserve for k in (g["stats"] or {})}
        names = focus_mod.loc_names(install, ids | {f"{i}_short" for i in ids} | {f"STAT_{k.upper()}" for k in stat_keys}
                                    | {f"EQUIPMENT_STAT_{k.upper()}" for k in stat_keys} | set(stat_keys))
        loc = lambda k: clean_loc(names[k], names) if names.get(k) else None  # noqa: E731
        label = lambda i: loc(i) or i.replace("_", " ").capitalize()  # noqa: E731

        def grouped(units):
            out = {}
            for u in units:
                out[u] = out.get(u, 0) + 1
            return [{"id": u, "name": label(u), "count": n} for u, n in out.items()]
        for t in army["templates"]:
            for k in ("battalions", "support", "regimental"):
                t[k] = grouped(t[k])
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
        return envelope(LIVE, {
            "tag": tag, "military_source": "live",
            "army": army, "navy": navy_out,
            "air": {"planes": sum(g["planes"] for g in air), "wings": air, "reserve": reserve, "stat_labels": stat_label},
        }, "Army, air force and navy from game memory.")

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
        names = focus_mod.loc_names(install, {t["id"] for t in tabs})
        names.update(focus_mod.loc_names(install, {r for v in names.values() for r in LOC_REF.findall(v)} - set(names)))
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
        names = focus_mod.loc_names(install, {lb["text"] for lb in layout["labels"]})
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
        names = focus_mod.loc_names(install, ids | {b["name"] for b in bonuses if b["name"]}
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
        names = focus_mod.loc_names(install, names_needed)
        refs = {r for v in names.values() for r in LOC_REF.findall(v)}
        names.update(focus_mod.loc_names(install, refs - set(names)))
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
            labels = focus_mod.loc_names(install, {f"MODIFIER_{m['key'].upper()}" for t in leader_out["traits"]
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

    def _mios(self, state: dict, tag: str, install: Path, roots: tuple[str, ...]) -> dict[str, list[dict]]:
        """{design slot: [MIO for display]} - level, funds, policy, unlocked traits and current bonuses."""
        defs = mio_mod.definitions(roots)
        items = [s for s in (mio_mod.summary(m, defs) for m in state.get("mios") or []) if s]
        def name_keys(it):
            n = it["name_key"]
            return [k for k in (f"{tag}_{n}" if n else None, n, f"{tag}_{it['id']}", it["id"]) if k]
        def trait_keys(it, t):
            n = t.get("name")
            return [k for k in (f"{tag}_{n}" if n else None, n, f"{tag}_{it['id']}_{t['token']}",
                                f"{it['id']}_{t['token']}", t["token"]) if k]
        stat_keys = lambda kind, stat: (  # noqa: E731
            [f"STAT_{p}_{stat.upper()}" for p in ("ARMY", "COMMON", "NAVY", "AIR")] if kind == "equipment_bonus"
            else [f"BONUS_{stat.upper()}"] if kind == "production_bonus" else [f"MODIFIER_{stat.upper()}"])
        keys = {"MODIFIER_MIO_RESEARCH_BONUS"}
        for it in items:
            keys.update(name_keys(it))
            keys.update(k for t in it["traits"] + ([it["initial_trait"]] if it["initial_trait"] else []) for k in trait_keys(it, t))
            keys.add(it["policy"] or "")
            keys.update(k for kind, stats in it["bonuses"].items() for s in stats for k in stat_keys(kind, s))
        names = focus_mod.loc_names(install, keys)
        refs = {r for v in names.values() for r in LOC_REF.findall(v)}
        names.update(focus_mod.loc_names(install, refs - set(names)))
        def loc(cands, fallback):
            for k in cands:
                v = clean_loc(names[k], names).rstrip(": ").strip() if k in names else ""
                if v and "$" not in v:
                    return v
            return fallback.replace("_", " ").capitalize()
        sprites = gfx.sprites(roots)
        groups = {"equipment_bonus": "Equipment", "production_bonus": "Production", "organization_modifier": "Organization"}
        out: dict[str, list[dict]] = {c: [] for c in mio_mod.CATEGORIES}
        for it in sorted(items, key=lambda i: (-(i["size"] or 0), i["id"])):
            texture = sprites.get(it["icon"] or "")
            out[it["category"]].append({
                "id": it["id"], "name": loc(name_keys(it), it["id"].removesuffix("_organization")),
                "icon": gfx.icon_data_uri(texture) if texture else None, "size": it["size"], "funds": it["funds"],
                "research_bonus": it["research_bonus"],
                "policy": loc([it["policy"]], it["policy"]) if it["policy"] else None,
                "initial_trait": loc(trait_keys(it, it["initial_trait"]), it["initial_trait"]["token"] or "initial trait")
                if it["initial_trait"] else None,
                "traits": [loc(trait_keys(it, t), t["token"]) for t in it["traits"]],
                "bonuses": [{"group": groups[kind], "entries": [
                    {"key": stat, "label": "Research bonus" if stat == "military_industrial_organization_research_bonus"
                     else loc(stat_keys(kind, stat), stat), "value": v} for stat, v in stats.items() if v]}
                    for kind, stats in it["bonuses"].items() if any(stats.values())],
            })
        return out

    def _present(self, items: list[dict], install: Path, roots: tuple[str, ...]) -> list[dict]:
        """Localised names, descriptions, modifier labels, trait names and icons (data: URIs) for display."""
        keys = set()
        for it in items:
            keys.update(filter(None, [it["name_key"], it.get("alt_name_key"), it.get("slot"),
                                      f"{it['name_key']}_desc", f"{it['id']}_desc", *it["tooltips"], *it.get("traits", [])]))
            keys.update(k for m in it["modifiers"] for k in (f"MODIFIER_{m.upper()}", m))
        names = focus_mod.loc_names(install, keys)
        refs = {r for v in names.values() for r in LOC_REF.findall(v)}
        names.update(focus_mod.loc_names(install, refs - set(names)))
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
        names =focus_mod.loc_names(install, modifiers.loc_keys(state, defs))
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
