"""Debugger service: combines the game integration layer, DEMO data and reports
into the payloads served by the API. Contains no HTTP and no UI code."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import logging
import platform
import sys
import threading
import time

from . import __version__, deficit, demo, equipment_changes, gamefiles
from . import focus as focus_mod
from .applog import RingBufferHandler
from .integration import GameIntegration, NullIntegration
from .reports import ReportError, ReportStore
from .saves import equipment as save_equipment
from .saves import fields as save_fields
from .saves import states as save_states
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
    "intel": {"source": DEMO, "write": False, "note": DEMO_NOTE},
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
        players = {p["tag"]: p.get("name") for p in header.get("players") or [] if p.get("tag")}
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

    def _focus_context(self, tag: str):
        """(state from the newest save, focuses of its tree with statuses) or None."""
        install = self._install_path()
        picked = self._pick_save(None)
        if install is None or picked is None:
            return None
        state = self.saves.focus_state(picked[0], tag)
        userdata = (self.detect().get("userdata") or {}).get("path")
        folders = focus_mod.focus_folders(install, gamefiles.enabled_mods(Path(userdata)) if userdata else [])
        focuses = focus_mod.statuses(focus_mod.tree(folders, state["tree"]), state) if state["tree"] else []
        names = focus_mod.loc_names(install, {f["id"] for f in focuses})
        for f in focuses:
            name = names.get(f["id"])
            # scripted names ([GetSomething]) are resolved by the game at runtime - show a readable id instead
            f["name"] = name if name and "[" not in name else f["id"].split("_", 1)[-1].replace("_", " ").capitalize()
        return state, focuses

    def focus(self, tag: str) -> dict:
        """Focus tree of `tag` (game/mod files) with statuses from the newest save; the queue is a plan."""
        tag = tag.upper()
        try:
            ctx = self._focus_context(tag)
        except SaveFormatError as exc:
            ctx, note = None, f"Focus state not read: {exc}"
        else:
            note = None
        if ctx is None:
            return envelope(DEMO, {"tag": tag, "focuses": demo.focuses(tag), "queue_supported": False},
                            f"{note} {DEMO_NOTE}" if note else DEMO_NOTE)
        state, focuses = ctx
        analysis = state["analysis"]
        header = analysis.get("header") or {}
        queue = self._focus_queues().get(f"{tag}:{state['tree']}", [])
        return envelope(SAVE, {
            "tag": tag, "tree": state["tree"], "current": state["current"], "progress_days": state["progress"],
            "paused": state["paused"], "completed": len(state["completed"]), "focuses": focuses,
            "queue": focus_mod.validate_queue(focuses, state, queue), "queue_supported": False,
            "file": analysis["file"], "in_game_date": header.get("date"),
            "freshness": save_freshness(analysis["file"]["mtime"], self.detect()),
        }, f"Focus tree {state['tree']} from the game files; state of {tag} from {analysis['file']['name']} "
           f"({(header.get('date') or {}).get('text') or '?'}). Snapshot - not live.")

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
        ctx = self._focus_context(tag)
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

    def intel(self, observer: str, target: str) -> dict:
        target_country = demo.country(target)
        if target_country is None or demo.country(observer) is None:
            raise NotFound("Unknown country tag")
        levels = demo.intel(observer, target) or {"civilian": 0.0, "army": 0.0, "navy": 0.0, "airforce": 0.0}
        return envelope(DEMO, {
            "observer": observer.upper(),
            "target": target.upper(),
            "intel_levels": levels,
            # "actual" is what the debugger can see; "visible" is what the observer would see in game.
            "actual": target_country["values"],
            "visible_rule": "DEMO rule: a value is shown to the observer when civilian intel >= 30%.",
            "visible": target_country["values"] if levels["civilian"] >= 0.30 else None,
        }, DEMO_NOTE)

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
