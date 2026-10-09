"""Documented console commands used as the change method, and detection of their execution.

The game appends every entered console command to `console_history.txt` in the install folder
(observed on 1.19.3: the file listed `pp 10`, `manpower 2000000` ... right after they were typed).
The debugger only READS that file. Commands come from the game's own documentation
(documentation/console_commands_documentation.md); none are invented here.

`factor` converts the command argument into the change of the save/memory value. It is None until
verified in game: the documentation does not state units (e.g. `add_stability`: "unity amount").
A field whose factor is unverified can be calibrated from saves only and cannot be changed by the app.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

HISTORY_FILE = "console_history.txt"
MAX_HISTORY_BYTES = 1 << 20

# field -> documented command (names and aliases from console_commands_documentation.md, 1.19.3).
COMMANDS: dict[str, dict] = {
    # factor 1 verified 2026-10-09: `pp 7`/`pp 5`/`pp 3`/`pp 6` changed memory and saves by exactly that much.
    "political_power": {"command": "pp", "aliases": ("political_power",), "factor": 1.0,
                        "doc": "pp - Gives political power to player (argument: PP amount)",
                        "integer_only": True, "max_abs": 5000},
    # Units verified 2026-10-09 from save pairs (game paused): `add_stability -5` -> -0.05, `add_stability 3` -> +0.03;
    # same for add_war_support; `cp -5` -> -5, `cp 3` -> +3; `manpower 10000` -> +10000, `manpower 5000` -> +5000;
    # `xp 10` -> +10 army, navy and air experience (one observation); `xp 10`, `xp 5` confirmed again in a new process.
    # `fuel 1000` -> +1000, `fuel 500` -> +500 (saves runda 1 / runda 2, PID 24536).
    "stability": {"command": "add_stability", "aliases": ("st",), "factor": 0.01,
                  "doc": "add_stability (st) - Gives/removes stability from player (argument: unity amount)",
                  "integer_only": True, "max_abs": 100},
    "war_support": {"command": "add_war_support", "aliases": ("ws",), "factor": 0.01,
                    "doc": "add_war_support (ws) - Gives/removes war support from player (argument: unity amount)",
                    "integer_only": True, "max_abs": 100},
    "command_power": {"command": "cp", "aliases": (), "factor": 1.0,
                      "doc": "cp - Gives command power to player (argument: CP amount)",
                      "integer_only": True, "max_abs": 1000},
    "fuel": {"command": "fuel", "aliases": ("army_juice",), "factor": 1.0,
             "doc": "fuel (army_juice) - Adds/removes fuel to the player (argument: Fuel amount)",
             "integer_only": True, "max_abs": 10_000_000},
    "manpower": {"command": "manpower", "aliases": (), "factor": 1.0,
                 "doc": "manpower - Adds manpower to player (argument: Amount)",
                 "integer_only": True, "max_abs": 100_000_000},
    # One command changes all three experience values.
    "army_experience": {"command": "xp", "aliases": (), "factor": 1.0, "shared_with": ("navy_experience", "air_experience"),
                        "doc": "xp - Gives Army, navy and air experience to player (argument: XP amount)",
                        "integer_only": True, "max_abs": 10_000},
    "navy_experience": {"command": "xp", "aliases": (), "factor": 1.0, "shared_with": ("army_experience", "air_experience"),
                        "doc": "xp - Gives Army, navy and air experience to player (argument: XP amount)",
                        "integer_only": True, "max_abs": 10_000},
    "air_experience": {"command": "xp", "aliases": (), "factor": 1.0, "shared_with": ("army_experience", "navy_experience"),
                       "doc": "xp - Gives Army, navy and air experience to player (argument: XP amount)",
                       "integer_only": True, "max_abs": 10_000},
}


def normalise(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip()).lower()


def verified(field: str) -> bool:
    spec = COMMANDS.get(field)
    return bool(spec) and spec["factor"] is not None


def build_command(field: str, delta: float) -> str:
    """Command that changes `field` by `delta` (in save/memory units). Only for verified units."""
    spec = COMMANDS.get(field)
    if spec is None:
        raise ValueError(f"No documented console command for {field}")
    if spec["factor"] is None:
        raise ValueError(f"The unit of `{spec['command']}` is not verified in game yet")
    if delta == 0:
        raise ValueError("Change must not be zero")
    arg = round(delta / spec["factor"], 6)
    if spec["integer_only"] and arg != int(arg):
        raise ValueError(f"`{spec['command']}` takes whole numbers")
    if abs(arg) > spec["max_abs"]:
        raise ValueError(f"Change limited to ±{spec['max_abs']} per operation")
    return f"{spec['command']} {int(arg) if spec['integer_only'] else arg}"


def parse_command(command: str) -> list[tuple[str, float, float | None]]:
    """`xp 10` -> [(army_experience, 10.0, None), (navy_experience, ...), ...]: (field, argument, change)
    where change = argument * factor, or None while the unit is unverified. Unknown commands -> []."""
    parts = normalise(command).split(" ")
    if len(parts) != 2:
        return []
    try:
        arg = float(parts[1])
    except ValueError:
        return []
    return [(field, arg, arg * spec["factor"] if spec["factor"] is not None else None)
            for field, spec in COMMANDS.items() if parts[0] in (spec["command"], *spec["aliases"])]


@dataclass(frozen=True)
class HistoryMark:
    mtime: float
    lines: int


class ConsoleHistory:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _lines(self) -> list[str] | None:
        try:
            if self.path.stat().st_size > MAX_HISTORY_BYTES:
                return None
            text = self.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        return [line for line in text.splitlines() if line.strip()]

    def mark(self) -> HistoryMark | None:
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return None
        lines = self._lines()
        return HistoryMark(mtime, len(lines) if lines is not None else 0)

    def new_entries(self, mark: HistoryMark | None) -> list[str]:
        """Commands entered after `mark`. If the file stopped growing (history cap), only the newest
        entry can be attributed to the change."""
        current = self.mark()
        if current is None or (mark is not None and current.mtime <= mark.mtime):
            return []
        lines = self._lines() or []
        if mark is not None and len(lines) > mark.lines:
            return lines[mark.lines:]
        return lines[-1:]

    def executed_since(self, mark: HistoryMark | None, command: str) -> bool:
        return any(normalise(line) == normalise(command) for line in self.new_entries(mark))

    def last(self, n: int = 10) -> list[str]:
        return (self._lines() or [])[-n:]
