"""Evidence-based location of a game value in process memory (read-only).

No address or offset is guessed. A field is located by:
1. scanning the process for an EXACT value taken from an independent source (a fresh save or a
   value expected after a documented console command) in every candidate encoding;
2. re-reading the surviving candidates after the value has CHANGED in the game and keeping
   only those that now hold the new exact value;
3. declaring the location confirmed only after at least MIN_DISTINCT_VALUES different values
   were matched and the survivors are all in one encoding.

Addresses are only valid for the process instance (pid + start time) they were found in.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..integration.memory import ENCODINGS, needles_for, scan

SCAN_LIMIT = 200_000  # per field and encoding (memory.scan default)

MIN_DISTINCT_VALUES = 3     # initial value + at least two independent changes
MAX_CONFIRMED = 8           # more survivors than this = not specific enough
PAGE = 4096
# Saves write values with 3 decimals; memory may hold more (1.19.3 PP: 5 decimals). A refine step
# therefore matches within half of the save's last digit, never more.
EVIDENCE_TOLERANCE = 0.0005


class CalibrationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class Step:
    value: float
    source: str           # e.g. "save PROJEKT.hoi4 1936.1.1.12" or "expected after `pp 1`"
    at: float
    remaining: dict[str, int]

    def as_dict(self) -> dict:
        return {"value": self.value, "source": self.source, "at": self.at, "remaining": self.remaining}


@dataclass
class FieldCalibration:
    field: str
    tag: str
    pid: int
    process_started: str | None
    candidates: dict[str, list[int]] = field(default_factory=dict)
    steps: list[Step] = field(default_factory=list)
    state: str = "new"    # new | candidates | confirmed | failed
    message: str = ""
    save_mtime: float = 0.0  # newest save already used as evidence
    history_mark: tuple | None = None  # console history (mtime, lines) already used as evidence
    unit_evidence: list[dict] = field(default_factory=list)
    truncated: bool = False  # initial scan hit SCAN_LIMIT: the true location may be missing
    tolerance: float = EVIDENCE_TOLERANCE  # precision of the evidence (save digits)

    # -- evidence ------------------------------------------------------------------------
    def start(self, memory, value: float, source: str, progress=None) -> None:
        self.start_from_hits(scan(memory, needles_for(value, tolerance=self.tolerance), progress=progress),
                             value, source)

    def start_from_hits(self, hits: dict[str, list[int]], value: float, source: str) -> None:
        """Initial candidates from a scan for `value` ({encoding: addresses}); see scan_many()."""
        self.candidates = {k: v for k, v in hits.items() if v}
        self.truncated = any(len(v) >= SCAN_LIMIT for v in hits.values())
        self.steps = [Step(value, source, time.time(), {k: len(v) for k, v in self.candidates.items()})]
        self._update_state()

    def add_unit_evidence(self, command_args: float, observed_change: float, commands: list[str]) -> None:
        """Command argument vs observed save change, used to verify the unit of a console command."""
        self.unit_evidence.append({"args": command_args, "observed": round(observed_change, 6),
                                   "ratio": round(observed_change / command_args, 6) if command_args else None,
                                   "commands": commands, "at": time.time()})

    def refine(self, memory, value: float, source: str) -> None:
        if not self.steps:
            raise CalibrationError("not_started", "Calibration was not started")
        survivors: dict[str, list[int]] = {}
        for name, addrs in self.candidates.items():
            enc = ENCODINGS[name]
            packed = enc.pack(value)
            if packed is None:
                continue
            # the field can only hold the nearest representable value (float32 steps grow with magnitude)
            tol = max(self.tolerance, abs(enc.unpack(packed) - value)) + 1e-9
            keep = [a for a, data in _read_many(memory, addrs, enc.size)
                    if data is not None and abs(enc.unpack(data) - value) <= tol]
            if keep:
                survivors[name] = keep
        self.candidates = survivors
        self.steps.append(Step(value, source, time.time(), {k: len(v) for k, v in survivors.items()}))
        self._update_state()

    def _effective(self) -> dict[str, list[int]]:
        """32- and 64-bit fixed point at the SAME addresses are one location: for small positive values the
        upper 4 bytes are zero, so both readings match. A negative value would tell them apart."""
        c = self.candidates
        for narrow, wide in (("fixed32_1000", "fixed64_1000"), ("int32", "int64")):
            if set(c) == {narrow, wide} and c[narrow] == c[wide]:
                return {narrow: c[narrow]}
        return c

    @property
    def width_note(self) -> str | None:
        if self._effective() is not self.candidates:
            return ("32/64-bit width not distinguished yet (same address); reading the low 32 bits, "
                    "exact for |value| < 2,147,483.")
        return None

    def _update_state(self) -> None:
        distinct = len({round(s.value, 6) for s in self.steps})
        eff = self._effective()
        total = sum(len(v) for v in eff.values())
        if total == 0:
            self.state, self.message = "failed", ("No memory location holds the expected value. The game state may "
                                                  "have changed in between (unpaused?) - start again."
                                                  + (" The first scan was truncated (value too common)."
                                                     if self.truncated else ""))
        elif distinct >= MIN_DISTINCT_VALUES and len(eff) == 1 and total <= MAX_CONFIRMED:
            self.state = "confirmed"
            self.message = (f"Confirmed: {total} location(s), encoding {self.encoding}, matched "
                            f"{distinct} different values.")
        else:
            self.state = "candidates"
            need = max(0, MIN_DISTINCT_VALUES - distinct)
            self.message = (f"{total} candidate(s) in {len(eff)} encoding(s). "
                            + (f"Change the value in game {need} more time(s) and refine." if need
                               else "Still ambiguous - change the value again and refine."))

    # -- reading -------------------------------------------------------------------------
    @property
    def encoding(self) -> str | None:
        eff = self._effective()
        return next(iter(eff)) if len(eff) == 1 else None

    def read(self, memory) -> dict:
        """Live value from the confirmed locations; all copies must agree."""
        if self.state != "confirmed":
            raise CalibrationError("not_confirmed", f"{self.field} is not calibrated ({self.state})")
        enc = ENCODINGS[self.encoding]
        values = []
        for _, data in _read_many(memory, self.candidates[self.encoding], enc.size):
            if data is None:
                raise CalibrationError("unreadable", "A calibrated address is no longer readable "
                                                     "(save loaded or game restarted?) - calibrate again.")
            values.append(enc.unpack(data))
        distinct = sorted(set(values))
        if len(distinct) != 1:
            raise CalibrationError("inconsistent", f"Calibrated copies disagree: {distinct}. The game may have "
                                                   "reloaded the country - calibrate again.")
        return {"value": distinct[0], "encoding": self.encoding, "copies": len(values)}

    def as_dict(self) -> dict:
        total = sum(len(v) for v in self._effective().values())
        return {
            "field": self.field, "tag": self.tag, "pid": self.pid, "process_started": self.process_started,
            "state": self.state, "message": self.message, "encoding": self.encoding,
            "candidate_count": total, "width_note": self.width_note, "unit_evidence": self.unit_evidence,
            "addresses": [hex(a) for a in self.candidates.get(self.encoding or "", [])][:MAX_CONFIRMED]
            if self.state == "confirmed" else [],
            "steps": [s.as_dict() for s in self.steps],
        }

    def to_store(self) -> dict:
        return {**self.as_dict(), "save_mtime": self.save_mtime, "tolerance": self.tolerance,
                "history_mark": list(self.history_mark) if self.history_mark else None,
                "candidates": self.candidates if total_ok(self.candidates) else {}}

    @classmethod
    def from_store(cls, data: dict) -> "FieldCalibration":
        cal = cls(data["field"], data["tag"], data["pid"], data.get("process_started"),
                  {k: list(v) for k, v in (data.get("candidates") or {}).items()},
                  [Step(s["value"], s["source"], s["at"], s["remaining"]) for s in data.get("steps", [])],
                  save_mtime=data.get("save_mtime", 0.0),
                  history_mark=tuple(data["history_mark"]) if data.get("history_mark") else None,
                  unit_evidence=list(data.get("unit_evidence") or []),
                  tolerance=data.get("tolerance", EVIDENCE_TOLERANCE))
        cal._update_state()
        return cal


def total_ok(candidates: dict[str, list[int]], limit: int = 20000) -> bool:
    return sum(len(v) for v in candidates.values()) <= limit


def _read_many(memory, addrs: list[int], size: int):
    """Yields (addr, bytes | None), reading whole pages so thousands of candidates stay fast."""
    by_page: dict[int, list[int]] = {}
    for a in addrs:
        by_page.setdefault(a - a % PAGE, []).append(a)
    for page, items in by_page.items():
        end = max(items) + size
        data = memory.read(page, end - page)
        for a in items:
            yield a, (data[a - page:a - page + size] if data else memory.read(a, size))


def tolerance_for(raw: str | None) -> float:
    """One unit of the last printed digit, at least 3 decimals: text saves print x100000 values trimmed
    (`760.3` is exact) and x32768 values truncated to 5 decimals (`304092.84835` = 304092.848358...).
    Binary-save values are exact (full repr), which gives a negligible tolerance."""
    decimals = len(raw.split(".", 1)[1]) if raw and "." in raw else 0
    return 10.0 ** -max(decimals, 3)


def scan_many(memory, values: dict[str, tuple[float, float]], progress=None) -> dict[str, dict[str, list[int]]]:
    """One pass over memory for several fields: {field: (value, tolerance)} -> {field: {encoding: addresses}}."""
    needles = {}
    for name, (value, tol) in values.items():
        for enc, needle in needles_for(value, tolerance=tol).items():
            needles[f"{name}|{enc}"] = needle
    hits = scan(memory, needles, progress=progress, limit=SCAN_LIMIT) if needles else {}
    out: dict[str, dict[str, list[int]]] = {name: {} for name in values}
    for key, addrs in hits.items():
        name, enc = key.split("|", 1)
        out[name][enc] = addrs
    return out
