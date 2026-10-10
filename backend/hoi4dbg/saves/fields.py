"""Meaning of the binary field tokens we use, with the evidence for each.

Only tokens listed here are interpreted. Everything else stays an anonymous token id.
status:
  verified - meaning confirmed against an independent source (file name, installed mods, ...)
  inferred - meaning follows from a consistent value domain across many saves, but was not
             confirmed against an independent source
Evidence collected 2026-10-09 on 158 real saves, versions 1.16.10 - 1.19.3 (docs/SAVE-FORMAT.md).
"""

from __future__ import annotations

from dataclasses import dataclass

from .binary import Raw, Token


@dataclass(frozen=True)
class FieldInfo:
    key: str
    label: str
    status: str
    evidence: str


PLAYER_TAG = 0x2A35
IDEOLOGY = 0x2E3E
DATE = 0x284A
DIFFICULTY = 0x299F
VERSION = 0x00EE
PLAYERS = 0x3567
PLAYER_NAME = 0x00E2
COUNTRY_LEADER = 0x3035
MODS = 0x3769
MULTIPLAYER = 0x365C

FIELDS: dict[int, FieldInfo] = {
    PLAYER_TAG: FieldInfo("player_tag", "Saving player's country", "verified",
                          "Equals the TAG prefix of the file name in 121/121 named saves."),
    DATE: FieldInfo("date", "In-game date", "verified",
                    "Decoded date equals the file-name date in 121/121 saves (hour 0-6 h later: game ticks "
                    "before writing). Encoding: hours since 1 Jan 5000 BC, 365-day years, hour = value % 24 + 1."),
    VERSION: FieldInfo("version", "Game version that wrote the save", "verified",
                       "Value is the full version string, e.g. 'Operation Postern v1.19.3.0.c01a (ff0e)'."),
    PLAYERS: FieldInfo("players", "Players and their countries", "verified",
                       "Keys are country tags, each holding the player's account name (0x00e2); "
                       "multiplayer saves list one entry per human player."),
    PLAYER_NAME: FieldInfo("player_name", "Player account name", "verified",
                           "Strings are account names; the saving player's tag is always among the keys."),
    MODS: FieldInfo("mods", "Enabled mods", "verified",
                    "All 14 names in the newest save equal 'name=' of installed .mod files."),
    MULTIPLAYER: FieldInfo("multiplayer", "Saved during a multiplayer session", "inferred",
                           "Present (true) in 79 of 179 binary saves (1.16.10 - 1.19.2, 2026-10-10), every one listing "
                           "2-31 players; absent in all 87 saves listing one player. 13 saves list several players "
                           "without it (an earlier multiplayer game continued in single player, presumably)."),
    IDEOLOGY: FieldInfo("ideology", "Ruling ideology of the saving player's country", "inferred",
                        "Values across 158 saves are ideology names (fascism, communism, democratic, "
                        "neutrality, plus mod ideologies)."),
    DIFFICULTY: FieldInfo("difficulty", "Difficulty", "inferred",
                          "Values across 158 saves: easy, normal, hard, very_hard."),
}

HEADER_KEYS = {PLAYER_TAG, IDEOLOGY, DATE, DIFFICULTY, VERSION, PLAYERS, MODS, MULTIPLAYER}
HEADER_END = MODS  # last header field; MULTIPLAYER is absent in single-player saves


def decode_date(value: int) -> dict:
    """Binary date (i32) -> {"year", "month", "day", "hour", "text"}."""
    days, hour = divmod(int(value), 24)
    year, day_of_year = divmod(days, 365)
    year -= 5000
    month = 1
    for length in (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31):
        if day_of_year < length:
            break
        day_of_year -= length
        month += 1
    day = day_of_year + 1
    return {"year": year, "month": month, "day": day, "hour": hour + 1, "text": f"{year}.{month}.{day}.{hour + 1}"}


def _plain(value):
    """JSON-friendly form of a parsed value; unknown pieces are labelled as such."""
    if isinstance(value, Token):
        return f"#{value.id:04x}"
    if isinstance(value, Raw):
        return {"raw_type": f"0x{value.type:04x}", "hex": value.data.hex()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, tuple):
        return [_plain(v) for v in value]
    return value


def extract_players(block) -> list[dict]:
    players = []
    if not isinstance(block, list):
        return players
    for entry in block:
        if not (isinstance(entry, tuple) and isinstance(entry[0], str) and isinstance(entry[1], list)):
            continue
        tag, body = entry
        name, leader = None, None
        other = {}
        for item in body:
            if isinstance(item, tuple) and isinstance(item[0], Token):
                if item[0].id == PLAYER_NAME and isinstance(item[1], str):
                    name = item[1]
                elif item[0].id == COUNTRY_LEADER and isinstance(item[1], bool):
                    leader = item[1]
                else:
                    other[f"#{item[0].id:04x}"] = _plain(item[1])
        players.append({"tag": tag, "name": name, "country_leader": leader, "unidentified_fields": other})
    return players


def extract_header(found: dict[int, object]) -> dict:
    """Maps parsed top-level values to named header fields. Missing fields stay None."""
    date_value = found.get(DATE)
    mods = found.get(MODS)
    return {
        "player_tag": found.get(PLAYER_TAG) if isinstance(found.get(PLAYER_TAG), str) else None,
        "date": decode_date(date_value) if isinstance(date_value, int) else None,
        "version": found.get(VERSION) if isinstance(found.get(VERSION), str) else None,
        "ideology": found.get(IDEOLOGY) if isinstance(found.get(IDEOLOGY), str) else None,
        "difficulty": found.get(DIFFICULTY) if isinstance(found.get(DIFFICULTY), str) else None,
        "players": extract_players(found.get(PLAYERS)),
        "multiplayer": found.get(MULTIPLAYER) is True, "multiplayer_basis": "flag",
        "mods": [m for m in mods if isinstance(m, str)] if isinstance(mods, list) else None,
    }


def field_catalog() -> list[dict]:
    return [{"token": f"0x{token:04x}", **info.__dict__} for token, info in FIELDS.items()]
