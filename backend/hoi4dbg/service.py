"""Debugger service: combines the game integration layer, DEMO data and reports
into the payloads served by the API. Contains no HTTP and no UI code."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
import logging
import platform
import sys
import time

from . import __version__, demo
from .applog import RingBufferHandler
from .integration import GameIntegration, NullIntegration
from .reports import ReportStore
from .saves import fields as save_fields
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
                               "command power, fuel, army XP. Manpower/convoys not mapped. No write method."},
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
                 logger: logging.Logger, data_dir: str = "", saves: SaveAnalyzer | None = None) -> None:
        self.saves = saves
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

    # -- game data (DEMO until Stage 3) ---------------------------------------------------
    def countries(self) -> dict:
        return envelope(DEMO, demo.countries(), DEMO_NOTE)

    def country(self, tag: str) -> dict:
        data = demo.country(tag)
        if data is None:
            raise NotFound(f"Unknown country tag: {tag}")
        return envelope(DEMO, {**data, "fields": demo.COUNTRY_FIELDS, "editable": False}, DEMO_NOTE)

    def states(self, owner: str | None = None) -> dict:
        items = demo.states()
        if owner:
            owner = owner.upper()
            items = [s for s in items if owner in (s["owner"], s["controller"])]
        return envelope(DEMO, items, DEMO_NOTE)

    def focus(self, tag: str) -> dict:
        return envelope(DEMO, {"tag": tag.upper(), "focuses": demo.focuses(tag), "queue_supported": False},
                        DEMO_NOTE)

    def equipment(self, tag: str) -> dict:
        return envelope(DEMO, {"tag": tag.upper(), "items": demo.equipment(tag), "editable": False}, DEMO_NOTE)

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
