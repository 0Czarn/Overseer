"""Documented console commands used as the change method, and detection of their execution.

The game appends every entered console command to `console_history.txt` in the install folder
(observed on 1.19.3: the file listed `pp 10`, `manpower 2000000` ... right after they were typed).
The debugger only READS that file. Commands come from the game's own documentation
(documentation/console_commands_documentation.md); none are invented here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

HISTORY_FILE = "console_history.txt"
MAX_HISTORY_BYTES = 1 << 20

# field -> documented command. `pp`: "Gives political power to player" (argument: PP amount).
COMMANDS: dict[str, dict] = {
    "political_power": {"command": "pp", "doc": "pp - Gives political power to player (argument: PP amount)",
                        "integer_only": True, "max_abs": 5000},
}


def normalise(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip()).lower()


def build_command(field: str, delta: float) -> str:
    spec = COMMANDS.get(field)
    if spec is None:
        raise ValueError(f"No documented console command for {field}")
    if delta == 0:
        raise ValueError("Change must not be zero")
    if spec["integer_only"] and delta != int(delta):
        raise ValueError(f"`{spec['command']}` takes whole numbers")
    if abs(delta) > spec["max_abs"]:
        raise ValueError(f"Change limited to ±{spec['max_abs']} per operation")
    return f"{spec['command']} {int(delta) if spec['integer_only'] else delta}"


def parse_command(command: str) -> tuple[str, float] | None:
    """`pp 10` -> ("political_power", 10.0). Only documented commands are recognised."""
    parts = normalise(command).split(" ")
    if len(parts) != 2:
        return None
    for field, spec in COMMANDS.items():
        if parts[0] == spec["command"]:
            try:
                return field, float(parts[1])
            except ValueError:
                return None
    return None


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
