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

    # -- evidence ------------------------------------------------------------------------
    def start(self, memory, value: float, source: str, progress=None) -> None:
        hits = scan(memory, needles_for(value), progress=progress)
        self.candidates = {k: v for k, v in hits.items() if v}
        self.steps = [Step(value, source, time.time(), {k: len(v) for k, v in self.candidates.items()})]
        self._update_state()

    def refine(self, memory, value: float, source: str) -> None:
        if not self.steps:
            raise CalibrationError("not_started", "Calibration was not started")
        survivors: dict[str, list[int]] = {}
        for name, addrs in self.candidates.items():
            enc = ENCODINGS[name]
            keep = [a for a, data in _read_many(memory, addrs, enc.size)
                    if data is not None and abs(enc.unpack(data) - value) <= EVIDENCE_TOLERANCE]
            if keep:
                survivors[name] = keep
        self.candidates = survivors
        self.steps.append(Step(value, source, time.time(), {k: len(v) for k, v in survivors.items()}))
        self._update_state()

    def _effective(self) -> dict[str, list[int]]:
        """32- and 64-bit fixed point at the SAME addresses are one location: for small positive values the
        upper 4 bytes are zero, so both readings match. A negative value would tell them apart."""
        c = self.candidates
        if set(c) == {"fixed32_1000", "fixed64_1000"} and c["fixed32_1000"] == c["fixed64_1000"]:
            return {"fixed32_1000": c["fixed32_1000"]}
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
                                                  "have changed in between (unpaused?) - start again.")
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
            "candidate_count": total, "width_note": self.width_note,
            "addresses": [hex(a) for a in self.candidates.get(self.encoding or "", [])][:MAX_CONFIRMED]
            if self.state == "confirmed" else [],
            "steps": [s.as_dict() for s in self.steps],
        }

    def to_store(self) -> dict:
        return {**self.as_dict(), "save_mtime": self.save_mtime,
                "history_mark": list(self.history_mark) if self.history_mark else None,
                "candidates": self.candidates if total_ok(self.candidates) else {}}

    @classmethod
    def from_store(cls, data: dict) -> "FieldCalibration":
        cal = cls(data["field"], data["tag"], data["pid"], data.get("process_started"),
                  {k: list(v) for k, v in (data.get("candidates") or {}).items()},
                  [Step(s["value"], s["source"], s["at"], s["remaining"]) for s in data.get("steps", [])],
                  save_mtime=data.get("save_mtime", 0.0),
                  history_mark=tuple(data["history_mark"]) if data.get("history_mark") else None)
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
