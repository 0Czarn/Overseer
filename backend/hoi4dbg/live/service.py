"""Live game values (process memory, read-only) and verified value changes.

Change method: a documented console command, entered in the game console (the app copies it;
it never types into the game). Execution is detected in console_history.txt, and the result is
verified independently by re-reading the calibrated memory location (and, optionally, a save).
"""

from __future__ import annotations

import datetime as dt
import itertools
import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Callable

from ..integration.memory import ENCODINGS, MemoryAccessError, ProcessMemory, needles_for, scan
from ..integration.memory_write import ProcessMemoryWriter
from .. import construction as construction_mod
from .. import ic_history
from . import console, layout, pointers
from .calibration import SCAN_LIMIT, CalibrationError, FieldCalibration, holds, scan_many, tolerance_for

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
                 clock: Callable[[], float] = time.time,
                 open_writer: Callable[[int], object] = ProcessMemoryWriter) -> None:
        self._detect = detect
        self._save_values = save_values      # newest save's values for its player country (envelope)
        self._open_memory = open_memory
        self._open_writer = open_writer
        self._clock = clock
        self.log = logger
        self.store = store_dir / "calibrations.json"
        self.layouts = layout.LayoutStore(store_dir / "layouts.json")
        self._lock = threading.RLock()
        self._job: dict | None = None
        self._ops: dict[str, dict] = {}
        self._ids = itertools.count(1)
        self.calibrations: dict[str, FieldCalibration] = self._load()
        self.invalidated: dict[str, dict] = {}  # field -> why its calibration was dropped
        self._module_base: dict[tuple, int] = {}   # (pid, started) -> hoi4.exe base
        self._tags: dict[str, list[str]] = {}      # install path -> tag order
        self._player: tuple[float, tuple, str] | None = None  # (read at, process key, tag)

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

    def _record_layout(self, process: dict) -> None:
        """Keeps the addresses of confirmed single locations beyond this process (see layout.py)."""
        by_tag: dict[str, dict] = {}
        for field, cal in self.calibrations.items():
            addrs = cal.candidates.get(cal.encoding or "", [])
            if cal.state == "confirmed" and len(addrs) == 1:
                by_tag.setdefault(cal.tag, {})[field] = (cal.encoding, addrs[0])
        for tag, fields in by_tag.items():
            self.layouts.record(process, tag, fields)

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
            players = self.players(process) if process else []
            return {"process": process, "error": error, "calibrations": cals, "job": dict(self._job or {}),
                    "players": players,
                    "invalidated": dict(self.invalidated),
                    "commands": {k: {"doc": v["doc"], "verified": v["factor"] is not None}
                                 for k, v in console.COMMANDS.items()}}

    # -- calibration -----------------------------------------------------------------------
    def start_calibration(self, field: str, background: bool = True) -> dict:
        return self.start_calibrations([field], background)

    def start_calibrations(self, fields: list[str], background: bool = True) -> dict:
        """One memory scan for several fields, each for its exact value in a fresh save of the running game."""
        unknown = [f for f in fields if f not in console.COMMANDS]
        if unknown or not fields:
            raise LiveError("unsupported_field", f"Calibration is not available for {', '.join(unknown) or 'nothing'}")
        process = self._process()
        save = self._fresh_save(process)
        values, skipped = {}, {}
        for field in fields:
            entry = save["values"].get(field) or {}
            if entry.get("status") != "read":
                skipped[field] = f"not present in {save['file']['name']}"
            elif not entry.get("value"):
                skipped[field] = "value is 0 (matches everywhere) - change it in game first"
            else:
                values[field] = (entry["value"], tolerance_for(entry.get("raw")))
        if not values:
            raise LiveError("no_value", "Nothing to calibrate: " + "; ".join(f"{k} {v}" for k, v in skipped.items()))
        tag = save.get("player_tag") or save.get("tag")
        source = f"save {save['file']['name']} ({(save.get('in_game_date') or {}).get('text')})"
        mark = _mark_tuple(self._history(process))
        with self._lock:
            if self._job and self._job.get("state") == "running":
                raise LiveError("busy", "A memory scan is already running")
            self._job = {"field": ",".join(values), "fields": list(values), "skipped": skipped,
                         "state": "running", "progress": 0.0, "started": self._clock()}

        def run() -> None:
            try:
                with self._open_memory(process["pid"]) as mem:
                    hits = scan_many(mem, values, progress=self._progress)
                cals = {}
                for field, value in values.items():
                    cal = FieldCalibration(field, tag, process["pid"], process.get("started"))
                    cal.save_mtime, cal.history_mark = save["file"]["mtime"], mark
                    cal.tolerance = value[1]
                    cal.start_from_hits(hits[field], value[0], source)
                    cals[field] = cal
                with self._lock:
                    self.calibrations.update(cals)
                    for field in cals:
                        self.invalidated.pop(field, None)
                    self._save()
                    self._job.update(state="done", progress=1.0, result={f: c.as_dict() for f, c in cals.items()})
                for field, cal in cals.items():
                    self.log.info("Live calibration %s: scan of %s = %s -> %s", field, tag, values[field][0], cal.message)
            except (MemoryAccessError, OSError) as exc:
                with self._lock:
                    self._job.update(state="error", error=str(exc))
                self.log.warning("Live calibration %s failed: %s", ",".join(values), exc)

        if background:
            threading.Thread(target=run, daemon=True).start()
        else:
            run()
        return self.status()

    def calibrate_from_layout(self, fields: list[str] | None = None) -> dict:
        """Locates fields in a new game process from the layout recorded in an earlier one (same version and
        country): one scan for each field's exact save value in its recorded encoding, then the candidates
        that line up at the recorded distances (layout.clusters). Fields that do not line up start the normal
        calibration from these candidates (encoding as recorded), so no second scan is needed."""
        process = self._process()
        save = self._fresh_save(process)
        tag = save.get("player_tag") or save.get("tag")
        ref = self.layouts.reference(process, tag)
        if ref is None:
            raise LiveError("no_layout", f"No layout recorded for {tag} in an earlier game process of this version - "
                                         "run the full calibration once.")
        values, skipped = {}, {}
        for field in fields or list(console.COMMANDS):
            entry = save["values"].get(field) or {}
            if field not in ref["fields"]:
                skipped[field] = "not in the recorded layout"
            elif entry.get("status") != "read" or not entry.get("value"):
                skipped[field] = f"no usable value in {save['file']['name']}"
            else:
                values[field] = (entry["value"], tolerance_for(entry.get("raw")))
        needles = {}
        for field, (value, tol) in values.items():
            enc = ref["fields"][field]["encoding"]
            nd = needles_for(value, {enc: ENCODINGS[enc]}, tolerance=tol).get(enc)
            if nd is None:
                skipped[field] = f"value {value} not representable in {enc}"
            else:
                needles[field] = nd
        if len(needles) < layout.MIN_CLUSTER:
            raise LiveError("no_value", "Too few fields to match the layout: "
                            + "; ".join(f"{k} {v}" for k, v in skipped.items()))
        source = f"save {save['file']['name']} ({(save.get('in_game_date') or {}).get('text')})"
        reference = f"process {ref['pid']}"
        mark = _mark_tuple(self._history(process))
        with self._lock:
            if self._job and self._job.get("state") == "running":
                raise LiveError("busy", "A memory scan is already running")
            self._job = {"field": ",".join(needles), "fields": list(needles), "skipped": skipped, "method": "layout",
                         "state": "running", "progress": 0.0, "started": self._clock()}
        try:
            with self._open_memory(process["pid"]) as mem:
                hits = scan(mem, needles, progress=self._progress, limit=SCAN_LIMIT)
                found, ambiguous = layout.clusters(ref, hits)
                # re-read: the cluster must still hold the exact save values (game paused)
                found = {f: a for f, a in found.items()
                         if holds(ref["fields"][f]["encoding"], mem.read(a, ENCODINGS[ref["fields"][f]["encoding"]].size),
                                  *values[f])}
        except (MemoryAccessError, OSError) as exc:
            with self._lock:
                self._job.update(state="error", error=str(exc))
            raise LiveError("memory_error", str(exc)) from exc
        cals = {}
        for field in needles:
            enc = ref["fields"][field]["encoding"]
            cal = FieldCalibration(field, tag, process["pid"], process.get("started"))
            cal.save_mtime, cal.history_mark, cal.tolerance = save["file"]["mtime"], mark, values[field][1]
            if field in found:
                cal.start_from_layout(enc, found[field], values[field][0], source, reference)
            else:
                cal.start_from_hits({enc: hits[field]}, values[field][0], source)
            cals[field] = cal
        with self._lock:
            self.calibrations.update(cals)
            for field in cals:
                self.invalidated.pop(field, None)
            self._save()
            self._record_layout(process)
            result = {"found": sorted(found), "ambiguous": ambiguous, "skipped": skipped,
                      "not_aligned": sorted(set(needles) - set(found)), "reference": reference}
            self._job.update(state="done", progress=1.0, result=result)
        self.log.info("Live layout calibration of %s from %s: found %s, not aligned %s", tag, reference,
                      ", ".join(result["found"]) or "-", ", ".join(result["not_aligned"]) or "-")
        return {**self.status(), "layout": result}

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
            if cal.state == "confirmed":
                # Further "evidence" can only be stale (game time moved since the last step) and must never
                # destroy a verified location. Checks of a confirmed value go through read()/operations.
                raise LiveError("already_confirmed", f"{field} is already confirmed")
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
                if cal.history_mark is not None:
                    entries = self._history(process).new_entries(console.HistoryMark(*cal.history_mark))
                    used = [(e, arg) for e in entries for f, arg, _ in console.parse_command(e) if f == field]
                    if used:
                        cal.add_unit_evidence(sum(a for _, a in used), value - last.value, [e for e, _ in used])
            elif source == "command":
                if not console.verified(field):
                    raise LiveError("unit_unverified", f"The unit of `{console.COMMANDS[field]['command']}` is not "
                                                       "verified yet - refine from a save instead")
                history = self._history(process)
                if cal.history_mark is None:
                    raise LiveError("no_history", "Console history position unknown - start the calibration again")
                entries = history.new_entries(console.HistoryMark(*cal.history_mark))
                deltas = [change for e in entries for f, _, change in console.parse_command(e) if f == field]
                if not deltas:
                    raise LiveError("no_command", f"No {field} console command entered since the previous step "
                                                  f"(new entries: {entries})")
                value = round(last.value + sum(deltas), 6)
                label = f"expected after {', '.join(f'`{e.strip()}`' for e in entries)} ({last.value} + {sum(deltas):g})"
            else:
                raise LiveError("bad_source", "source must be 'save' or 'command'")
            with self._open_memory(process["pid"]) as mem:
                cal.refine(mem, value, label)
            cal.history_mark = _mark_tuple(self._history(process))
            self._save()
            if cal.state == "confirmed":
                self._record_layout(process)
            self.log.info("Live calibration %s refine (%s = %s): %s", field, source, value, cal.message)
            return cal.as_dict()

    def reset_calibration(self, field: str) -> dict:
        with self._lock:
            self.calibrations.pop(field, None)
            self._save()
        return self.status()

    # -- live values -----------------------------------------------------------------------
    def player_tag(self, process: dict) -> str:
        """Player country: the game state's player slot (verified version, follows `tag`); else the only country not
        hidden by fog of war; else the last unambiguous result of this game process; else the newest save."""
        key = (process["pid"], process.get("started"))
        now = self._clock()
        if self._player and self._player[1] == key and now - self._player[0] < 5:
            return self._player[2]
        tag = None
        if pointers.supported(process.get("version")):
            tag = self._player_from_state(process)
        if tag is None and pointers.supported(process.get("version")):
            visible = self.players(process)
            if len(visible) == 1:
                tag = visible[0]
                self._last_unique_player = (key, tag)
            elif getattr(self, "_last_unique_player", (None, None))[0] == key:
                tag = self._last_unique_player[1]
        if tag is None:
            save = self._fresh_save(process)
            tag = save.get("player_tag") or save.get("tag")
        if not tag:
            raise LiveError("player_unknown", "The newest save has no player country")
        self._player = (now, key, tag)
        return tag

    def _player_from_state(self, process: dict) -> str | None:
        """Player's country from the game state (pointers.player_country), None when not readable."""
        key = (process["pid"], process.get("started"))
        install = process.get("install") or ""
        if install not in self._tags:
            self._tags[install] = pointers.tag_order(Path(install))
        try:
            with self._open_memory(process["pid"]) as mem:
                if key not in self._module_base:
                    module = mem.modules().get(pointers.MODULE)
                    if not module:
                        return None
                    self._module_base[key] = module[0]
                return pointers.player_country(mem, self._module_base[key], self._tags[install])
        except (MemoryAccessError, OSError, pointers.PointerError):
            return None

    def players(self, process: dict | None = None) -> list[str]:
        """Human-controlled countries read from game memory ([] if unavailable)."""
        process = process or self._process()
        if not pointers.supported(process.get("version")):
            return []
        key = (process["pid"], process.get("started"))
        install = process.get("install") or ""
        if install not in self._tags:
            self._tags[install] = pointers.tag_order(Path(install))
        try:
            with self._open_memory(process["pid"]) as mem:
                if key not in self._module_base:
                    module = mem.modules().get(pointers.MODULE)
                    if not module:
                        return []
                    self._module_base[key] = module[0]
                return pointers.player_tags(mem, self._module_base[key], self._tags[install])
        except (MemoryAccessError, OSError):
            return []

    def _read_pointer(self, process: dict, field: str, tag: str | None) -> dict:
        tag = tag or self.player_tag(process)
        key = (process["pid"], process.get("started"))
        install = process.get("install") or ""
        if install not in self._tags:
            self._tags[install] = pointers.tag_order(Path(install))
        try:
            with self._open_memory(process["pid"]) as mem:
                if key not in self._module_base:
                    module = mem.modules().get(pointers.MODULE)
                    if not module:
                        raise LiveError("no_module", f"{pointers.MODULE} is not loaded in the game process")
                    self._module_base[key] = module[0]
                country = pointers.country_object(mem, self._module_base[key], self._tags[install], tag)
                value = pointers.read_field(mem, country, field)
        except pointers.PointerError as exc:
            raise LiveError(exc.code, str(exc)) from exc
        return {"value": value, "encoding": pointers.FIELDS[field][1], "copies": 1, "method": "country_table",
                "field": field, "tag": tag, "read_at": self._clock()}

    def focus(self, tag: str | None = None) -> dict:
        """Current national focus and its progress (days) of `tag` (default: the player), from game memory."""
        process = self._process()
        if not pointers.supported(process.get("version")):
            raise LiveError("unsupported_version", "Live focus reading is only verified for 1.19.3.0.c01a")
        tag = tag or self.player_tag(process)
        key = (process["pid"], process.get("started"))
        install = process.get("install") or ""
        if install not in self._tags:
            self._tags[install] = pointers.tag_order(Path(install))
        try:
            with self._open_memory(process["pid"]) as mem:
                if key not in self._module_base:
                    module = mem.modules().get(pointers.MODULE)
                    if not module:
                        raise LiveError("no_module", f"{pointers.MODULE} is not loaded in the game process")
                    self._module_base[key] = module[0]
                country = pointers.country_object(mem, self._module_base[key], self._tags[install], tag)
                out = pointers.read_focus(mem, country)
                try:
                    out["date"] = pointers.read_date(mem, self._module_base[key])
                except pointers.PointerError:
                    out["date"] = None
        except pointers.PointerError as exc:
            raise LiveError(exc.code, str(exc)) from exc
        except (MemoryAccessError, OSError) as exc:
            raise LiveError("memory_error", str(exc)) from exc
        return {**out, "tag": tag, "read_at": self._clock()}

    def game_mode(self) -> str | None:
        """SINGLEPLAYER / MULTIPLAYER from the newest `[[ Launching X-game ]]` line of logs/game.log, written by
        the running game (log modified after the process started). None when unknown."""
        game = self._detect()
        logs = (game.get("userdata") or {}).get("logs_dir")
        process = game.get("process") or {}
        if not logs:
            return None
        path = Path(logs) / "game.log"
        try:
            stat = path.stat()
            if stat.st_size > 50 << 20:
                return None
            started = process.get("started")
            if started:
                if stat.st_mtime < dt.datetime.fromisoformat(started).timestamp() - 5:
                    return None  # log of an earlier game run
            found = re.findall(r"\[\[ Launching ([A-Z]+)-game \]\]", path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            return None
        return found[-1] if found else None

    def parties(self, tag: str, ideologies: list[str]) -> dict:
        """Live party popularity and ruling party of `tag`, its leader {"id", "ideology"} and faction
        {"name", "icon", "members"} or None (game memory)."""
        process = self._process()
        if not pointers.supported(process.get("version")):
            raise LiveError("unsupported_version", "Live party reading is only verified for 1.19.3.0.c01a")
        key = (process["pid"], process.get("started"))

        def read(mem, c):
            countries = pointers.country_objects(mem, self._module_base[key], self._tags[process.get("install") or ""])
            return {**pointers.read_parties(mem, c, ideologies), "leader": pointers.read_leader(mem, c),
                    "faction": pointers.read_faction(mem, c, {o: t for t, o in countries.items()})}
        return {**self._with_country(process, tag, read), "tag": tag, "read_at": self._clock()}

    def ideas(self, tag: str) -> dict:
        """Live ideas of `tag` (national spirits, laws, companies) in the game's order and its dynamic modifiers
        (game memory)."""
        process = self._process()
        if not pointers.supported(process.get("version")):
            raise LiveError("unsupported_version", "Live idea reading is only verified for 1.19.3.0.c01a")
        ideas, dynamic = self._with_country(process, tag, lambda mem, c: (pointers.read_ideas(mem, c),
                                                                           pointers.read_dynamic_modifiers(mem, c)))
        return {"ideas": ideas, "dynamic_modifiers": dynamic, "tag": tag, "read_at": self._clock()}

    def doctrines(self, tag: str) -> dict:
        """Live grand doctrines and subdoctrines of `tag` as name keys of common/doctrines (game memory)."""
        process = self._process()
        if not pointers.supported(process.get("version")):
            raise LiveError("unsupported_version", "Live doctrine reading is only verified for 1.19.3.0.c01a")
        key = (process["pid"], process.get("started"))
        names = self._with_country(process, tag, lambda mem, _c: pointers.read_doctrines(
            mem, self._module_base[key], self._tags[process.get("install") or ""], tag))
        return {"names": names, "tag": tag, "read_at": self._clock()}

    def penalties(self, tag: str) -> dict:
        """Live war support penalties of `tag` from enemy bombing and combat casualties (game memory)."""
        process = self._process()
        if not pointers.supported(process.get("version")):
            raise LiveError("unsupported_version", "Live penalty reading is only verified for 1.19.3.0.c01a")
        return {**self._with_country(process, tag, pointers.read_penalties), "tag": tag, "read_at": self._clock()}

    def modifier_sums(self, tag: str) -> dict:
        """Live sums of the stability / war support modifiers of `tag` as the game keeps them (game memory)."""
        process = self._process()
        if not pointers.supported(process.get("version")):
            raise LiveError("unsupported_version", "Live modifier reading is only verified for 1.19.3.0.c01a")
        key = (process["pid"], process.get("started"))
        sums, date = self._with_country(process, tag, lambda mem, c: (
            pointers.read_modifier_sums(mem, c), pointers.read_date(mem, self._module_base[key])))
        return {**sums, "date": date, "tag": tag, "read_at": self._clock()}

    def wars(self, tag: str) -> dict:
        """Live wars of `tag`: [{"enemy", "offensive"}] (game memory)."""
        process = self._process()
        if not pointers.supported(process.get("version")):
            raise LiveError("unsupported_version", "Live war reading is only verified for 1.19.3.0.c01a")
        return {"wars": self._with_country(process, tag, lambda mem, c: pointers.read_wars(
                    mem, c, self._tags[process.get("install") or ""], tag)),
                "tag": tag, "read_at": self._clock()}

    def research(self, tag: str) -> dict:
        """Live research slots of `tag`: [{"slot", "technology", "speed"}] (game memory)."""
        process = self._process()
        if not pointers.supported(process.get("version")):
            raise LiveError("unsupported_version", "Live research reading is only verified for 1.19.3.0.c01a")
        key = (process["pid"], process.get("started"))
        slots, date, bonuses, researched = self._with_country(process, tag, lambda mem, c: (
            pointers.read_research(mem, c), pointers.read_date(mem, self._module_base[key]),
            pointers.read_limited_bonuses(mem, c), pointers.read_researched(mem, c)))
        return {"slots": slots, "date": date, "bonuses": bonuses, "researched": researched, "tag": tag,
                "read_at": self._clock()}

    def construction(self, tag: str) -> dict:
        """Live construction queue of `tag` in queue order and its civilian factories by task (game memory)."""
        process = self._process()
        if not pointers.supported(process.get("version")):
            raise LiveError("unsupported_version", "Live construction reading is only verified for 1.19.3.0.c01a")
        key = (process["pid"], process.get("started"))
        lines, factories, date = self._with_country(process, tag, lambda mem, c: (
            pointers.read_construction(mem, c, self._module_base[key]), pointers.read_civilian_factories(mem, c),
            pointers.read_date(mem, self._module_base[key])))
        return {"lines": lines, "factories": factories, "date": date, "tag": tag, "read_at": self._clock()}

    def sort_construction(self, apply: bool) -> dict:
        """Civilian factories with the most progress first in the PLAYER's construction queue (see
        construction.civilian_first_order). apply=False only reports the new order; apply=True writes it into game
        memory (LOCAL write, single player only) and checks it by reading the queue again."""
        process = self._process()
        if not pointers.supported(process.get("version")):
            raise LiveError("unsupported_version", "Queue sorting is only available for the verified game version")
        if apply:
            self._require_single_player()
        tag = self.player_tag(process)
        key = (process["pid"], process.get("started"))

        def run(mem, country):
            lines = pointers.read_construction(mem, country, self._module_base[key])
            data, slots = pointers.construction_slots(mem, country)
            if len(slots) != len(lines):
                raise LiveError("queue_changed", "The construction queue changed while it was read - try again")
            order = construction_mod.civilian_first_order(lines)
            changed = 0
            if apply and order != list(range(len(lines))):
                changed = pointers.write_construction_order(mem, data, slots, order)
                if pointers.construction_slots(mem, country)[1] != [slots[k] for k in order]:
                    raise LiveError("not_held", "The construction queue did not hold the new order")
            return lines, order, changed
        lines, order, changed = self._with_country(process, tag, run, writer=apply)
        if changed:
            self.log.warning("LOCAL memory write %s construction queue: civilian factories by progress, %d slots moved",
                             tag, changed)
        moved = [{"from": k + 1, "to": i + 1, "building": lines[k]["building"], "location": lines[k]["location"],
                  "progress": lines[k]["produced"] / lines[k]["cost"] if lines[k]["cost"] else None}
                 for i, k in enumerate(order) if k != i]
        return {"tag": tag, "sorted": not moved or bool(changed), "applied": bool(changed), "moved": moved,
                "scope": "local" if changed else None, "read_at": self._clock()}

    def start_focus(self, focus_id: str) -> dict:
        """LOCAL write: makes `focus_id` the PLAYER's current focus (0 days, see pointers.write_focus_start); single
        player only, only while no focus is selected; checked by reading the focus again."""
        process = self._process()
        if not pointers.supported(process.get("version")):
            raise LiveError("unsupported_version", "Starting a focus is only available for the verified game version")
        self._require_single_player()
        tag = self.player_tag(process)

        def run(mem, country):
            definition = pointers.focus_definition(mem, country, focus_id)
            if definition is None:
                raise LiveError("not_in_tree", f"{focus_id} is not in {tag}'s focus tree")
            pointers.write_focus_start(mem, country, definition)
            return pointers.read_focus(mem, country)
        after = self._with_country(process, tag, run, writer=True)
        if after["current"] != focus_id:
            raise LiveError("not_held", f"The game did not keep {focus_id} as the current focus")
        self.log.warning("LOCAL memory write %s: focus %s started (0 days)", tag, focus_id)
        return {"tag": tag, "started": focus_id, "scope": "local", "written_at": self._clock()}

    def factories(self, tag: str) -> dict:
        """Live factories of `tag` by type with where they come from, and energy (game memory)."""
        process = self._process()
        if not pointers.supported(process.get("version")):
            raise LiveError("unsupported_version", "Live factory reading is only verified for 1.19.3.0.c01a")
        return {**self._with_country(process, tag, pointers.read_factories), "tag": tag, "read_at": self._clock()}

    def doctrine_state(self, tag: str) -> dict:
        """Live doctrines of `tag`: per folder the grand doctrine and each track's subdoctrine and mastery."""
        process = self._process()
        if not pointers.supported(process.get("version")):
            raise LiveError("unsupported_version", "Live doctrine reading is only verified for 1.19.3.0.c01a")
        key = (process["pid"], process.get("started"))
        folders = self._with_country(process, tag, lambda mem, _c: pointers.read_doctrine_state(
            mem, self._module_base[key], self._tags[process.get("install") or ""], tag))
        return {"folders": folders, "tag": tag, "read_at": self._clock()}

    def military(self, tag: str) -> dict:
        """Live army (divisions, templates, free manpower, manpower in the field and in training), navy (fleets, task
        forces, ships) and air force (wings by role and design, planes in the stockpile) of `tag` (game memory), with
        what the division designer needs: the newest equipment designs, researched technologies, doctrine state."""
        process = self._process()
        if not pointers.supported(process.get("version")):
            raise LiveError("unsupported_version", "Live military reading is only verified for 1.19.3.0.c01a")
        key = (process["pid"], process.get("started"))
        tags = self._tags.setdefault(process.get("install") or "", pointers.tag_order(Path(process.get("install") or "")))
        army, navy, air, reserve, free, designs, researched, doctrine_state = self._with_country(
            process, tag, lambda mem, c: (
                pointers.read_army(mem, c), pointers.read_navy(mem, c),
                pointers.read_air(mem, self._module_base[key], tags, tag), pointers.read_stockpile_planes(mem, c),
                pointers.read_free_manpower(mem, self._module_base[key], tags, tag), pointers.read_designs(mem, c),
                pointers.read_researched(mem, c), pointers.read_doctrine_state(mem, self._module_base[key], tags, tag)))
        army["manpower_free"] = free
        return {"army": army, "navy": navy, "air": air, "air_reserve": reserve, "designs": designs,
                "researched": researched, "doctrine_state": doctrine_state, "tag": tag, "read_at": self._clock()}

    def advisors(self, tag: str) -> dict:
        """Live hired advisors and staff of `tag`: [{"slot", "id": character id}] (game memory)."""
        process = self._process()
        if not pointers.supported(process.get("version")):
            raise LiveError("unsupported_version", "Live advisor reading is only verified for 1.19.3.0.c01a")
        return {"advisors": self._with_country(process, tag, pointers.read_advisors), "tag": tag,
                "read_at": self._clock()}

    def resources(self, tag: str, resources: list[str]) -> dict:
        """Live resources of `tag` (game memory): the six per-day parts of the save ({part: {resource: amount}})
        plus "imports" [{seller, resource, amount}] and "exports" [{buyer, resource, amount}] of its trade deals.
        `resources` = names in the order of common/resources."""
        process = self._process()
        if not pointers.supported(process.get("version")):
            raise LiveError("unsupported_version", "Live resource reading is only verified for 1.19.3.0.c01a")
        key = (process["pid"], process.get("started"))
        install = process.get("install") or ""
        if install not in self._tags:
            self._tags[install] = pointers.tag_order(Path(install))
        try:
            with self._open_memory(process["pid"]) as mem:
                if key not in self._module_base:
                    self._module_base[key] = mem.modules()[pointers.MODULE][0]
                countries = pointers.country_objects(mem, self._module_base[key], self._tags[install])
                if tag not in countries:
                    raise LiveError("country_missing", f"{tag} has no country object in the running game")
                cr_of = {t: pointers._ptr(mem, c + pointers.COUNTRY_RESOURCES) for t, c in countries.items()}
                sellers = {cr: t for t, cr in cr_of.items() if cr}
                out = pointers.read_resources(mem, pointers.resources_object(mem, countries[tag]), resources)
                tokens = out.pop("_tokens")
                out["imports"] = pointers.read_imports(mem, cr_of[tag], tokens, sellers)
                out["exports"] = []
                for t, cr in cr_of.items():
                    if not cr or t == tag:
                        continue
                    try:  # tags without a country (released later, ...) may hold no import array
                        deals = pointers.read_imports(mem, cr, tokens, sellers)
                    except pointers.PointerError:
                        continue
                    out["exports"] += [{"buyer": t, "resource": d["resource"], "amount": d["amount"]}
                                       for d in deals if d["seller"] == tag]
        except pointers.PointerError as exc:
            raise LiveError(exc.code, str(exc)) from exc
        except (MemoryAccessError, OSError, KeyError) as exc:
            raise LiveError("memory_error", f"Game memory access failed: {exc}") from exc
        return {**out, "tag": tag, "read_at": self._clock()}

    def trade_market(self, tag: str, resources: list[str], ideologies: list[str]) -> dict:
        """What the trade advisor needs, read in one pass (game memory): `tag`'s resources, import deals, civilian
        factories, wars and faction, and for every other country with resources on the market and not sold yet
        ({resource: amount}): ruling ideology, faction members, opinion of `tag` and the links between them
        ({kind: [first tag, second tag]}: subject = [overlord, subject], non_aggression_pact, embargo, ...)."""
        process = self._process()
        if not pointers.supported(process.get("version")):
            raise LiveError("unsupported_version", "Live trade reading is only verified for 1.19.3.0.c01a")
        key = (process["pid"], process.get("started"))
        install = process.get("install") or ""
        if install not in self._tags:
            self._tags[install] = pointers.tag_order(Path(install))
        order = self._tags[install]
        try:
            with self._open_memory(process["pid"]) as mem:
                if key not in self._module_base:
                    self._module_base[key] = mem.modules()[pointers.MODULE][0]
                countries = pointers.country_objects(mem, self._module_base[key], order)
                if tag not in countries:
                    raise LiveError("country_missing", f"{tag} has no country object in the running game")
                by_object = {c: t for t, c in countries.items()}
                cr_of = {t: pointers._ptr(mem, c + pointers.COUNTRY_RESOURCES) for t, c in countries.items()}
                own = pointers.read_resources(mem, cr_of[tag], resources)
                tokens = own.pop("_tokens")
                player = {"tag": tag, "resources": own,
                          "imports": pointers.read_imports(mem, cr_of[tag], tokens, {cr: t for t, cr in cr_of.items() if cr}),
                          "factories": pointers.read_civilian_factories(mem, countries[tag]),
                          "wars": pointers.read_wars(mem, countries[tag], order, tag),
                          "faction": pointers.read_faction(mem, countries[tag], by_object)}
                sellers = {}
                for t, cr in cr_of.items():
                    if t == tag or not cr:
                        continue
                    try:
                        pools = pointers.read_resources(mem, cr, resources)
                    except pointers.PointerError:   # tags without a country (released later, ...)
                        continue
                    free = {r: round(pools["to_market"][r] - pools["exported"][r], 3) for r in resources}
                    if not any(v > 0 for v in free.values()):
                        continue
                    c = countries[t]
                    try:
                        ruling = pointers.read_parties(mem, c, ideologies)["ruling"]
                        faction = pointers.read_faction(mem, c, by_object)
                    except pointers.PointerError:
                        ruling, faction = None, None
                    try:   # the seller's view of the player: its opinion and their pacts, subject link, embargo
                        relation = pointers.read_relation(mem, c, order.index(tag) + 1, self._module_base[key])
                    except pointers.PointerError:
                        relation = {"opinion": None, "links": {}}
                    links = {k: [order[s - 1] if 0 < s <= len(order) else None for s in v]
                             for k, v in relation["links"].items()}
                    sellers[t] = {"market": free, "ideology": ruling, "faction": faction["members"] if faction else [],
                                  "opinion": relation["opinion"], "links": links}
                player["ideology"] = pointers.read_parties(mem, countries[tag], ideologies)["ruling"]
                # who prepares war against whom (every country), the player's puppets (its relations)
                slot_tag = lambda s: order[s - 1] if 0 < s <= len(order) else None  # noqa: E731
                justifying = []
                for t, c in countries.items():
                    try:
                        justifying += [[slot_tag(a), slot_tag(b)] for a, b in pointers.read_justifications(mem, c)]
                    except pointers.PointerError:   # tags without a country
                        continue
                player["justifications"] = justifying
                own_slot = order.index(tag) + 1
                puppets = []
                for t in countries:
                    if t == tag:
                        continue
                    try:
                        sub = pointers.read_relation(mem, countries[tag], order.index(t) + 1,
                                                     self._module_base[key])["links"].get("subject")
                    except pointers.PointerError:
                        continue
                    if sub and sub[0] == own_slot:
                        puppets.append(t)
                player["puppets"] = puppets
        except pointers.PointerError as exc:
            raise LiveError(exc.code, str(exc)) from exc
        except (MemoryAccessError, OSError, KeyError) as exc:
            raise LiveError("memory_error", f"Game memory access failed: {exc}") from exc
        return {"tag": tag, "player": player, "sellers": sellers, "read_at": self._clock()}

    def session(self) -> dict:
        """Running game: mode (game.log), local player country and states owned by every country (memory)."""
        process = self._process()
        if not pointers.supported(process.get("version")):
            raise LiveError("unsupported_version", "Live country reading is only verified for 1.19.3.0.c01a")
        key = (process["pid"], process.get("started"))
        install = process.get("install") or ""
        if install not in self._tags:
            self._tags[install] = pointers.tag_order(Path(install))
        try:
            with self._open_memory(process["pid"]) as mem:
                if key not in self._module_base:
                    module = mem.modules().get(pointers.MODULE)
                    if not module:
                        raise LiveError("no_module", f"{pointers.MODULE} is not loaded in the game process")
                    self._module_base[key] = module[0]
                states = pointers.owned_states(mem, self._module_base[key], self._tags[install])
        except (MemoryAccessError, OSError) as exc:
            raise LiveError("memory_error", str(exc)) from exc
        if not states:
            raise LiveError("no_country_table", "The country table is not readable (main menu or loading)")
        return {"process": process, "game_mode": self.game_mode(), "players": self.players(process),
                "states": states, "read_at": self._clock()}

    def _with_country(self, process: dict, tag: str, fn, writer: bool = False):
        """Runs fn(memory, country object) for `tag` in the running game (country table)."""
        key = (process["pid"], process.get("started"))
        install = process.get("install") or ""
        if install not in self._tags:
            self._tags[install] = pointers.tag_order(Path(install))
        try:
            with (self._open_writer if writer else self._open_memory)(process["pid"]) as mem:
                if key not in self._module_base:
                    self._module_base[key] = mem.modules()[pointers.MODULE][0]
                return fn(mem, pointers.country_object(mem, self._module_base[key], self._tags[install], tag))
        except pointers.PointerError as exc:
            raise LiveError(exc.code, str(exc)) from exc
        except (MemoryAccessError, OSError, KeyError) as exc:
            raise LiveError("memory_error", f"Game memory access failed: {exc}") from exc

    def _game_memory(self, fn):
        """Runs fn(memory, module base, tag order) in the running game (verified version only)."""
        process = self._process()
        if not pointers.supported(process.get("version")):
            raise LiveError("unsupported_version", "Live reading is only verified for 1.19.3.0.c01a")
        key = (process["pid"], process.get("started"))
        install = process.get("install") or ""
        if install not in self._tags:
            self._tags[install] = pointers.tag_order(Path(install))
        try:
            with self._open_memory(process["pid"]) as mem:
                if key not in self._module_base:
                    self._module_base[key] = mem.modules()[pointers.MODULE][0]
                return fn(mem, self._module_base[key], self._tags[install], process)
        except pointers.PointerError as exc:
            raise LiveError(exc.code, str(exc)) from exc
        except (MemoryAccessError, OSError, KeyError) as exc:
            raise LiveError("memory_error", f"Game memory access failed: {exc}") from exc

    def game_day(self) -> int | None:
        """Day number of the running game (365-day years), None when it is not readable (menu, loading)."""
        try:
            return self._game_memory(lambda mem, base, _tags, _p: ic_history.day_number(pointers.read_date(mem, base)))
        except LiveError:
            return None

    def ic_snapshot(self, with_factions: bool = False) -> dict:
        """{"t", "player", "countries": {tag: [mil, nav, civ, civilian factories, military factories, dockyards]},
        "factions": {tag: faction name} or None} - IC a day (pointers.read_ic) and factories as the game shows them
        (pointers.read_factories) of every existing country."""
        def read(mem, base, tags, process):
            t = ic_history.day_number(pointers.read_date(mem, base))
            countries = pointers.country_objects(mem, base, tags)
            owned = pointers.owned_states(mem, base, tags)
            out = {}
            for tag, c in countries.items():
                if owned.get(tag, 0) <= 0:
                    continue
                try:
                    ic = pointers.read_ic(mem, c)
                    fac = pointers.read_factories(mem, c)
                except pointers.PointerError:   # a country being created or annexed right now
                    continue
                out[tag] = [ic["mil"], ic["nav"], ic["civ"],
                            fac["civilian"]["total"], fac["military"]["total"], fac["dockyards"]["total"]]
            factions = None
            if with_factions:
                by_object = {c: t for t, c in countries.items()}
                factions = {}
                for tag in out:
                    try:
                        f = pointers.read_faction(mem, countries[tag], by_object)
                    except pointers.PointerError:
                        f = None
                    if f and f.get("name"):
                        factions[tag] = f["name"]
            player = pointers.player_country(mem, base, tags) or self.player_tag(process)
            return {"t": t, "player": player, "countries": out, "factions": factions}
        return self._game_memory(read)

    def stockpile(self, tag: str | None = None) -> dict:
        """Live equipment stockpile of `tag` (default: player): {"tag", "entries": [{id, name, amount}]}."""
        process = self._process()
        if not pointers.supported(process.get("version")):
            raise LiveError("unsupported_version", "Live stockpile reading is only verified for 1.19.3.0.c01a")
        tag = tag or self.player_tag(process)
        entries = self._with_country(process, tag, pointers.read_stockpile)
        return {"tag": tag, "entries": [{k: e[k] for k in ("id", "name", "amount")} for e in entries],
                "read_at": self._clock()}

    def write_stockpile(self, equipment_id: str, amount: float, tag: str | None = None,
                        expected_before: float | None = None) -> dict:
        """LOCAL write of one stockpile entry (existing entries only; single player only, like write_value)."""
        process = self._process()
        if not pointers.supported(process.get("version")):
            raise LiveError("unsupported_version", "Direct writes are only available for the verified game version")
        lo, hi = pointers.STOCKPILE_RANGE
        if not isinstance(amount, (int, float)) or amount != amount or not lo <= amount <= hi or amount != int(amount):
            raise LiveError("out_of_range", f"Amount must be a whole number between {lo:g} and {hi:g}")
        self._require_single_player()
        tag = tag or self.player_tag(process)
        packed = ENCODINGS["fixed64_100000"].pack(amount)

        def write(mem, country):
            entries = [e for e in pointers.read_stockpile(mem, country) if e["id"] == str(equipment_id)]
            if not entries:
                raise LiveError("not_in_stockpile", f"Equipment {equipment_id} has no stockpile entry for {tag} - add "
                                                    "it once with the console command, then it can be edited")
            entry = entries[0]
            if expected_before is not None and abs(sum(e["amount"] for e in entries) - expected_before) > 1e-6:
                raise LiveError("value_changed", f"Stockpile of {equipment_id} is {entry['amount']:g} now, not "
                                                 f"{expected_before:g} - check the value and try again")
            before = entry["amount"]
            mem.write(entry["address"], packed)
            after = next(e["amount"] for e in pointers.read_stockpile(mem, country) if e["address"] == entry["address"])
            return before, after, entry["name"]
        before, after, name = self._with_country(process, tag, write, writer=True)
        self.log.warning("LOCAL memory write %s stockpile %s (%s): %s -> %s", tag, equipment_id, name, before, after)
        return {"tag": tag, "id": str(equipment_id), "name": name, "before": before, "after": after,
                "scope": "local", "written_at": self._clock()}

    def _require_single_player(self) -> None:
        mode = self.game_mode()
        if mode != "SINGLEPLAYER":
            raise LiveError("multiplayer" if mode else "mode_unknown",
                            (f"The running game is {mode}" if mode else "Single player could not be confirmed from "
                             "game.log") + ": a memory write would change this client only and desynchronise a "
                             "multiplayer game - use the console command instead")

    def write_value(self, field: str, value: float, tag: str | None = None,
                    expected_before: float | None = None) -> dict:
        """LOCAL direct write of one country field into game memory (opt-in, single player only).

        Refused in multiplayer (more than one human player): the change would exist on this client only.
        `expected_before` (the value the user saw) guards against overwriting a value that moved meanwhile."""
        if field not in pointers.WRITE_RANGES:
            raise LiveError("unsupported_field", f"Direct writes are not available for {field}")
        process = self._process()
        if not pointers.supported(process.get("version")):
            raise LiveError("unsupported_version", "Direct writes are only available for the verified game version")
        lo, hi = pointers.WRITE_RANGES[field]
        if not isinstance(value, (int, float)) or value != value or not lo <= value <= hi:
            raise LiveError("out_of_range", f"{field} must be between {lo:g} and {hi:g}")
        self._require_single_player()
        humans = []
        tag = tag or self.player_tag(process)
        key = (process["pid"], process.get("started"))
        install = process.get("install") or ""
        if install not in self._tags:
            self._tags[install] = pointers.tag_order(Path(install))
        enc = ENCODINGS[pointers.FIELDS[field][1]]
        packed = enc.pack(value)
        if packed is None:
            raise LiveError("out_of_range", f"{value} cannot be stored as {enc.name}")
        try:
            with self._open_writer(process["pid"]) as mem:
                if key not in self._module_base:
                    self._module_base[key] = mem.modules()[pointers.MODULE][0]
                country = pointers.country_object(mem, self._module_base[key], self._tags[install], tag)
                before = pointers.read_field(mem, country, field)
                if expected_before is not None and abs(before - expected_before) > 1e-6:
                    raise LiveError("value_changed", f"{field} is {before:g} now, not {expected_before:g} - "
                                                     "check the value and try again")
                mem.write(pointers.field_address(mem, country, field), packed)
                after = pointers.read_field(mem, country, field)
        except pointers.PointerError as exc:
            raise LiveError(exc.code, str(exc)) from exc
        except (MemoryAccessError, OSError, KeyError) as exc:
            raise LiveError("memory_error", f"Memory write failed: {exc}") from exc
        self.log.warning("LOCAL memory write %s %s: %s -> %s (requested %s)", tag, field, before, after, value)
        return {"field": field, "tag": tag, "before": before, "after": after, "requested": value,
                "scope": "local", "players": humans, "written_at": self._clock()}

    def read(self, field: str, tag: str | None = None) -> dict:
        """Live value: through the game's country table (verified game version), else a calibrated location."""
        process = self._process()
        pointer_error = None
        if field in pointers.FIELDS and pointers.supported(process.get("version")):
            try:
                return self._read_pointer(process, field, tag)
            except (LiveError, MemoryAccessError, OSError) as exc:
                pointer_error = exc
        with self._lock:
            cal = self._calibration(field, process)
            if cal is not None and tag and tag != cal.tag:
                cal = None
            if cal is None:
                if isinstance(pointer_error, LiveError):
                    raise pointer_error
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
        return {**out, "method": "calibration", "field": field, "tag": cal.tag, "read_at": self._clock()}

    def values(self, tag: str | None = None) -> dict:
        out = {}
        for field in sorted(set(self.calibrations) | set(self.invalidated) | set(console.COMMANDS)):
            try:
                out[field] = {"status": "live", **self.read(field, tag)}
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
        if spec["factor"] is None:
            raise LiveError("unit_unverified", f"The unit of `{spec['command']}` is not verified in game yet")
        if spec["integer_only"] and round(delta / spec["factor"], 6) != int(round(delta / spec["factor"], 6)):
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
