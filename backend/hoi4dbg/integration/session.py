"""Session hints from logs/game.log.

game.log is rewritten when the game starts and only receives lines on certain events,
so this is a weak, possibly stale signal - never a substitute for live game state.
Line format observed in 1.19.3: "[HH:MM:SS][<game date or no_game_date>][source.cpp:line]: text".
"""

from __future__ import annotations

import re

LINE_RE = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]\[([^\]]+)\]\[[^\]]*\]: ?(.*)$")
GAME_DATE_RE = re.compile(r"^\d{1,4}\.\d{2}\.\d{2}\.\d{1,2}$")
LAUNCH_RE = re.compile(r"\[\[\s*Launching\s+(\S+?)-game\s*\]\]")
START_DATE_RE = re.compile(r"^\s*Start-date:\s*(\S+)")


def parse_game_log(text: str) -> dict:
    result = {"launch_type": None, "start_date": None, "last_game_date": None, "last_log_time": None,
              "launches": 0}
    for line in text.splitlines():
        match = LINE_RE.match(line)
        if match:
            time, date, _ = match.groups()
            result["last_log_time"] = time
            if GAME_DATE_RE.match(date):
                result["last_game_date"] = date
        launch = LAUNCH_RE.search(line)
        if launch:
            result["launch_type"] = launch.group(1)
            result["launches"] += 1
        start = START_DATE_RE.match(line)
        if start:
            result["start_date"] = start.group(1)
    return result
