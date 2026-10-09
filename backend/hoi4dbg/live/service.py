"""Live game values (process memory, read-only) and verified value changes.

Change method: a documented console command, entered in the game console (the app copies it;
it never types into the game). Execution is detected in console_history.txt, and the result is
verified independently by re-reading the calibrated memory location (and, optionally, a save).
"""

from __future__ import annotations

import itertools
import json
import logging
import threading
import time
from pathlib import Path
from typing import Callable

from ..integration.memory import MemoryAccessError, ProcessMemory
from . import console
from .calibration import CalibrationError, FieldCalibration

TOLERANCE = 0.0005           # values are fixed point with 3 decimals
OP_TIMEOUT_S = 600
APPLY_GRACE_S = 5.0          # command seen in history, value not changed yet -> wait this long


def _mark_tuple(history: console.ConsoleHistory) -> tuple | None:
    mark = history.mark()
    return (mark.mtime, mark.lines) if mark else None


class LiveError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class LiveService:
    def __init__(self, detect: Callable[[], dict], save_values: Callable[[], dict], store_dir: Path,
                 logger: logging.Logger, open_memory: Callable[[int], object] = ProcessMemory,
                 clock: Callable[[], float] = time.time) -> None:
        self._detect = detect
        self._save_values = save_values      # newest save's values for its player country (envelope)
        self._open_memory = open_memory
        self._clock = clock
        self.log = logger
        self.store = store_dir / "calibrations.json"
        self._lock = threading.RLock()
        self._job: dict | None = None
        self._ops: dict[str, dict] = {}
        self._ids = itertools.count(1)
        self.calibrations: dict[str, FieldCalibration] = self._load()
        self.invalidated: dict[str, dict] = {}  # field -> why its calibration was dropped

    # -- persistence -----------------------------------------------------------------------
    def _load(self) -> dict[str, FieldCalibration]:
        try:
            data = json.loads(self.store.read_text(encoding="utf-8"))
            return {d["field"]: FieldCalibration.from_store(d) for d in data}
        except (OSError, ValueError, KeyError, TypeError):
            return {}

    def _save(self) -> None:
        self.store.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.store.with_suffix(".tmp")
        tmp.write_text(json.dumps([c.to_store() for c in self.calibrations.values()]), encoding="utf-8")
        tmp.replace(self.store)

    # -- environment -----------------------------------------------------------------------
    def _process(self) -> dict:
        game = self._detect()
        process = game.get("process")
        if not process:
            raise LiveError("game_not_running", "HOI4 is not running")
        if process.get("path") is None:
            raise LiveError("no_access", "Cannot query the game process (access denied?)")
        install = game.get("install") or {}
        return {**process, "install": install.get("path"), "version": (install.get("version") or {}).get("display")}

    def _history(self, process: dict) -> console.ConsoleHistory:
        return console.ConsoleHistory(Path(process["install"]) / console.HISTORY_FILE)

    def _calibration(self, field: str, process: dict) -> FieldCalibration | None:
        self._invalidate_stale(process)
        return self.calibrations.get(field)

    def _invalidate_stale(self, process: dict | None) -> None:
        """Addresses are only valid in the process they were found in: drop calibrations of any other
        game process (restart, crash, other PID; or no game at all) so no stale address is ever read."""
        with self._lock:
            stale = [f for f, c in self.calibrations.items() if process is None
                     or c.pid != process["pid"] or c.process_started != process.get("started")]
            for field in stale:
                cal = self.calibrations.pop(field)
                self.invalidated[field] = {
                    "pid": cal.pid, "process_started": cal.process_started, "state": cal.state,
                    "at": self._clock(), "message": f"Calibration from game process {cal.pid} "
                    f"(started {cal.process_started}) discarded: "
                    + (f"the game now runs as PID {process['pid']}." if process else "that game process has ended.")
                    + " Calibrate again."}
                self.log.warning("Live calibration %s discarded: process %s -> %s", field, cal.pid,
                                 process["pid"] if process else "none")
            if stale:
                self._save()

    def _fresh_save(self, process: dict) -> dict:
        res = self._save_values()
        data = res.get("data") or {}
        if res.get("source") != "save":
            if ((data.get("error") or {}).get("code")) == "in_progress":
                raise LiveError("save_in_progress", f"The newest save is still being written: {res.get('note')}")
            raise LiveError("no_save", f"No readable text save: {res.get('note')}")
        if (data.get("freshness") or {}).get("category") != "current_session":
            raise LiveError("stale_save", "The newest save is not from the running game. Type `savegame` in the "
                                          "console (game paused), then try again.")
        return data

    # -- status ----------------------------------------------------------------------------
    def status(self) -> dict:
        try:
            process = self._process()
            error = None
        except LiveError as exc:
            process, error = None, {"code": exc.code, "message": str(exc)}
        with self._lock:
            if process or (error and error["code"] == "game_not_running"):
                self._invalidate_stale(process)
            cals = {}
            for field, cal in self.calibrations.items():
                info = cal.as_dict()
                info["current_process"] = bool(process)
                cals[field] = info
            return {"process": process, "error": error, "calibrations": cals, "job": dict(self._job or {}),
                    "invalidated": dict(self.invalidated),
                    "commands": {k: v["doc"] for k, v in console.COMMANDS.items()}}

    # -- calibration -----------------------------------------------------------------------
    def start_calibration(self, field: str, background: bool = True) -> dict:
        if field not in console.COMMANDS:
            raise LiveError("unsupported_field", f"Calibration is not available for {field}")
        process = self._process()
        save = self._fresh_save(process)
        entry = save["values"].get(field) or {}
        if entry.get("status") != "read":
            raise LiveError("no_value", f"{field} is not present in {save['file']['name']}")
        tag = save.get("player_tag") or save.get("tag")
        source = f"save {save['file']['name']} ({(save.get('in_game_date') or {}).get('text')})"
        with self._lock:
            if self._job and self._job.get("state") == "running":
                raise LiveError("busy", "A memory scan is already running")
            self._job = {"field": field, "state": "running", "progress": 0.0, "started": self._clock()}
        cal = FieldCalibration(field, tag, process["pid"], process.get("started"))
        cal.save_mtime = save["file"]["mtime"]
        cal.history_mark = _mark_tuple(self._history(process))

        def run() -> None:
            try:
                with self._open_memory(process["pid"]) as mem:
                    cal.start(mem, entry["value"], source, progress=self._progress)
                with self._lock:
                    self.calibrations[field] = cal
                    self._save()
                    self._job.update(state="done", progress=1.0, result=cal.as_dict())
                    self.invalidated.pop(field, None)
                self.log.info("Live calibration %s: scan of %s = %s -> %s", field, tag, entry["value"], cal.message)
            except (MemoryAccessError, OSError) as exc:
                with self._lock:
                    self._job.update(state="error", error=str(exc))
                self.log.warning("Live calibration %s failed: %s", field, exc)

        if background:
            threading.Thread(target=run, daemon=True).start()
        else:
            run()
        return self.status()

    def _progress(self, done: int, total: int) -> None:
        with self._lock:
            if self._job:
                self._job["progress"] = round(done / total, 3)

    def refine_calibration(self, field: str, source: str) -> dict:
        process = self._process()
        with self._lock:
            cal = self._calibration(field, process)
            if cal is None or not cal.steps:
                raise LiveError("not_started", "Start the calibration first (needs a fresh save)")
            if cal.state == "failed":
                raise LiveError("failed", cal.message)
            last = cal.steps[-1]
            if source == "save":
                save = self._fresh_save(process)
                if save["file"]["mtime"] <= cal.save_mtime:
                    raise LiveError("no_new_save", "No save newer than the previous step. Type `savegame` first.")
                entry = save["values"].get(field) or {}
                if entry.get("status") != "read":
                    raise LiveError("no_value", f"{field} missing in {save['file']['name']}")
                value = entry["value"]
                label = f"save {save['file']['name']} ({(save.get('in_game_date') or {}).get('text')})"
                cal.save_mtime = save["file"]["mtime"]
            elif source == "command":
                history = self._history(process)
                if cal.history_mark is None:
                    raise LiveError("no_history", "Console history position unknown - start the calibration again")
                entries = history.new_entries(console.HistoryMark(*cal.history_mark))
                deltas = [p[1] for p in map(console.parse_command, entries) if p and p[0] == field]
                if not deltas:
                    raise LiveError("no_command", f"No {field} console command entered since the previous step "
                                                  f"(new entries: {entries})")
                value = round(last.value + sum(deltas), 3)
                label = f"expected after {', '.join(f'`{e.strip()}`' for e in entries)} ({last.value} + {sum(deltas):g})"
            else:
                raise LiveError("bad_source", "source must be 'save' or 'command'")
            with self._open_memory(process["pid"]) as mem:
                cal.refine(mem, value, label)
            cal.history_mark = _mark_tuple(self._history(process))
            self._save()
            self.log.info("Live calibration %s refine (%s = %s): %s", field, source, value, cal.message)
            return cal.as_dict()

    def reset_calibration(self, field: str) -> dict:
        with self._lock:
            self.calibrations.pop(field, None)
            self._save()
        return self.status()

    # -- live values -----------------------------------------------------------------------
    def read(self, field: str) -> dict:
        process = self._process()
        with self._lock:
            cal = self._calibration(field, process)
            if cal is None:
                if field in self.invalidated:
                    raise LiveError("process_changed", self.invalidated[field]["message"])
                raise LiveError("not_calibrated", f"{field} is not calibrated for this game process")
            if cal.state != "confirmed":
                raise LiveError("unverified", f"{field}: location not verified yet ({cal.message})")
            try:
                with self._open_memory(process["pid"]) as mem:
                    out = cal.read(mem)
            except CalibrationError as exc:
                raise LiveError(exc.code, str(exc)) from exc
        return {**out, "field": field, "tag": cal.tag, "read_at": self._clock()}

    def values(self) -> dict:
        out = {}
        for field in sorted(set(self.calibrations) | set(self.invalidated) | set(console.COMMANDS)):
            try:
                out[field] = {"status": "live", **self.read(field)}
            except LiveError as exc:
                out[field] = {"status": "unavailable", "code": exc.code, "message": str(exc)}
        return out

    # -- verified change -------------------------------------------------------------------
    def create_operation(self, field: str, mode: str, amount: float) -> dict:
        if field not in console.COMMANDS:
            raise LiveError("unsupported_field", f"No verified change method for {field}")
        before = self.read(field)
        if mode == "target":
            delta = round(amount - before["value"], 3)
        elif mode == "delta":
            delta = amount
        else:
            raise LiveError("bad_mode", "mode must be 'target' or 'delta'")
        spec = console.COMMANDS[field]
        if spec["integer_only"] and delta != int(delta):
            raise LiveError("not_integer", f"`{spec['command']}` takes whole numbers; change would be {delta:g}. "
                                           f"Pick a target that differs by a whole number "
                                           f"(e.g. {before['value'] + round(delta):g}).")
        try:
            command = console.build_command(field, delta)
        except ValueError as exc:
            raise LiveError("bad_amount", str(exc)) from exc
        process = self._process()
        op = {
            "id": f"op-{next(self._ids)}", "field": field, "tag": before["tag"], "command": command,
            "before": before["value"], "expected": round(before["value"] + delta, 3), "delta": delta,
            "state": "waiting_for_command", "created": self._clock(), "message":
                f"Enter `{command}` in the game console ({before['tag']} must be the player country).",
            "mark": self._history(process).mark(), "pid": process["pid"],
        }
        with self._lock:
            self._ops[op["id"]] = op
        self.log.info("Live change %s: %s %s -> expected %s via `%s`", op["id"], field, op["before"], op["expected"], command)
        return self._public(op)

    def poll_operation(self, op_id: str) -> dict:
        with self._lock:
            op = self._ops.get(op_id)
        if op is None:
            raise LiveError("unknown_operation", f"Unknown operation {op_id}")
        if op["state"] in ("confirmed", "mismatch", "expired", "error", "cancelled"):
            return self._public(op)
        now = self._clock()
        try:
            process = self._process()
            if process["pid"] != op["pid"]:
                return self._finish(op, "error", "The game process changed during the operation")
            if op["state"] == "waiting_for_command":
                if self._history(process).executed_since(op["mark"], op["command"]):
                    op.update(state="executed", executed_at=now)
                elif now - op["created"] > OP_TIMEOUT_S:
                    return self._finish(op, "expired", "Command was not entered within 10 minutes")
                else:
                    return self._public(op)
            value = self.read(op["field"])["value"]
            op["actual"] = value
            if abs(value - op["expected"]) <= TOLERANCE:
                return self._finish(op, "confirmed", f"Verified in memory: {op['before']:g} -> {value:g} "
                                                     f"(expected {op['expected']:g}).")
            if now - op["executed_at"] < APPLY_GRACE_S:
                op["message"] = "Command entered; waiting for the game to apply it…"
                return self._public(op)
            hint = " Game time seems to have moved (unpaused?)." if abs(value - op["expected"]) < 5 else ""
            if abs(value - op["before"]) <= TOLERANCE:
                return self._finish(op, "mismatch", f"Command was entered but the value did not change "
                                                    f"({value:g}). Was the console open in the right country?")
            return self._finish(op, "mismatch", f"Expected {op['expected']:g}, memory shows {value:g}.{hint}")
        except LiveError as exc:
            return self._finish(op, "error", f"{exc.code}: {exc}")

    def cancel_operation(self, op_id: str) -> dict:
        with self._lock:
            op = self._ops.get(op_id)
        if op is None:
            raise LiveError("unknown_operation", f"Unknown operation {op_id}")
        if op["state"] == "waiting_for_command":
            self._finish(op, "cancelled", "Cancelled before the command was entered")
        return self._public(op)

    def _finish(self, op: dict, state: str, message: str) -> dict:
        op.update(state=state, message=message, finished=self._clock())
        level = logging.INFO if state == "confirmed" else logging.WARNING
        self.log.log(level, "Live change %s %s: %s", op["id"], state, message)
        return self._public(op)

    @staticmethod
    def _public(op: dict) -> dict:
        return {k: v for k, v in op.items() if k not in ("mark",)}
