"""Debugger service: combines the game integration layer, DEMO data and reports
into the payloads served by the API. Contains no HTTP and no UI code."""

from __future__ import annotations

import logging
import platform
import sys

from . import __version__, demo
from .applog import RingBufferHandler
from .integration import GameIntegration, NullIntegration
from .reports import ReportStore

LIVE, DEMO, UNAVAILABLE = "live", "demo", "unavailable"

DEMO_NOTE = "DEMO data - not read from the game. Live reading is planned for Stage 3."
WRITE_NOTE = "Editing is disabled: no write method exists yet (planned Stage 4, singleplayer first)."

# Which data domains are live vs DEMO right now. Single source of truth for the UI badges.
CAPABILITIES: dict[str, dict] = {
    "detection": {"source": LIVE, "write": False, "note": "Process, install and version detection."},
    "game_logs": {"source": LIVE, "write": False, "note": "Read-only tail of the game's own log files."},
    "countries": {"source": DEMO, "write": False, "note": DEMO_NOTE},
    "players": {"source": DEMO, "write": False, "note": DEMO_NOTE},
    "country_values": {"source": DEMO, "write": False, "note": WRITE_NOTE},
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


class DebuggerService:
    def __init__(self, integration: GameIntegration, reports: ReportStore, ring: RingBufferHandler,
                 logger: logging.Logger, data_dir: str = "") -> None:
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
