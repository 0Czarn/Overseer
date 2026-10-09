"""Interface between the debugger service and whatever reads the game."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class GameIntegration(Protocol):
    def detect(self) -> dict:
        """Return a detection snapshot.

        Shape: {"process": dict | None, "install": dict | None,
                "userdata": dict | None, "session": dict | None,
                "warnings": list[str]}
        """
        ...

    def game_log(self, name: str, lines: int) -> dict | None:
        """Tail of one of the game's own log files, or None if unavailable."""
        ...

    def game_log_names(self) -> list[str]:
        ...

    def saves_dir(self) -> Path | None:
        """The game's "save games" folder, if found."""
        ...


class NullIntegration:
    """Integration that never finds the game. Used in tests and as a safe fallback."""

    def __init__(self, reason: str = "Game integration disabled") -> None:
        self.reason = reason

    def detect(self) -> dict:
        return {"process": None, "install": None, "userdata": None, "session": None,
                "warnings": [self.reason]}

    def game_log(self, name: str, lines: int) -> dict | None:
        return None

    def game_log_names(self) -> list[str]:
        return []

    def saves_dir(self) -> Path | None:
        return None
