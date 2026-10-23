"""Game Tools (Krok G, 2026-10-23): what the app can change and how, campaign checkpoints, live memory check.

Changes: every way the app changes the game, with the method and whether it is allowed in the running game. The
rules repeat the live service's guards (live/service.py: _require_single_player, fog_of_war, _apply_patch) so the
tab shows what a click would do - the guards themselves stay the only enforcement.

Checkpoints: the save files with their header (game date, player, multiplayer, version - from the first bytes, see
HEADER_BYTES) and the user's note on each, kept in <data>/checkpoints.json. Saves are only read, never changed.

Live check: every live reader once for the player's country, with its time and error - read-only, for a game update
or a mod that moves something in memory.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from .saves import binary, reader

HEADER_BYTES = 1 << 18   # the header of a binary or text save ends well within the first 256 KB (1.19.3 saves)
MAX_NOTE = 2000
MAX_CHECKPOINTS = 300    # newest saves listed

CONSOLE, MEMORY, MEMORY_SP, CODE_PATCH, VIEW = "console", "memory", "memory_sp", "code_patch", "view"
METHODS = {
    CONSOLE: "Console command you type in the game; the app prepares it and checks the result",
    MEMORY: "Direct write into game memory (this client)",
    MEMORY_SP: "Direct write into game memory (this client), single player only",
    CODE_PATCH: "Change of the game's code in memory (this client), single player only",
    VIEW: "Changes only what this client shows",
}
# id, name, tab (view id), tab label, method, scope: shared = changes the common game state
CHANGES = [
    ("console_values", "Political power, stability, war support, command power, fuel, manpower, experience",
     "country-editor", "Country Editor", CONSOLE, "shared"),
    ("add_equipment", "Add equipment (archetype or design name)", "equipment", "Equipment Manager", CONSOLE, "shared"),
    ("write_values", "Set a country value directly", "country-editor", "Country Editor", MEMORY, "shared"),
    ("write_stockpile", "Set a stockpile amount", "equipment", "Equipment Manager", MEMORY, "shared"),
    ("construction_sort", "Sort the construction queue (factories by progress)", "construction", "Construction",
     MEMORY, "shared"),
    ("focus_start", "Start the next focus of the plan", "focus", "National Focus Manager", MEMORY_SP, "shared"),
    ("combat_log", "Combat log for every country", "summary", "Game summary", CODE_PATCH, "local"),
    ("fog_of_war", "Map without fog of war", "tools", "Game Tools", VIEW, "local"),
]


def change_status(method: str, mode: str | None, mp: dict, running: bool, supported: bool) -> tuple[str, str]:
    """(allowed | blocked | untested | unknown, reason) of a change by `method` in the running game."""
    if not running:
        return "unknown", "Game not running"
    if method == CONSOLE:   # the game's own command: no memory layout involved
        if mode == "SINGLEPLAYER":
            return "allowed", "Single player"
        if mode == "MULTIPLAYER":
            return "untested", "Multiplayer: whether the command syncs from every player is not tested yet (Krok H)"
        return "unknown", "Single player not confirmed from game.log"
    if not supported:
        return "blocked", "Game version not verified for memory access"
    if mode == "SINGLEPLAYER":
        return "allowed", "Single player"
    if method == VIEW:
        if mode is not None and mp.get("fog"):
            return "allowed", "Multiplayer, allowed in Options (you see what the others cannot)"
        return "blocked", ("Multiplayer - allow it in Options > Multiplayer" if mode else "Single player not confirmed")
    if method == MEMORY and mp.get("enabled"):
        return "allowed", "Allowed in Options: this client only - may desynchronise a multiplayer game"
    if method in (MEMORY_SP, CODE_PATCH):
        return "blocked", "Single player only (desyncs a multiplayer game)" if mode else "Single player not confirmed"
    return "blocked", "Multiplayer: this client only - allow it in Options > Multiplayer" if mode else \
        "Single player not confirmed from game.log"


def changes(mode: str | None, mp: dict, running: bool, supported: bool) -> list[dict]:
    out = []
    for cid, name, view, tab, method, scope in CHANGES:
        status, reason = change_status(method, mode, mp, running, supported)
        out.append({"id": cid, "name": name, "view": view, "tab": tab, "method": method, "method_text": METHODS[method],
                    "scope": scope, "status": status, "reason": reason})
    return out


def quick_header(path: Path) -> dict:
    """{"date", "player_tag", "multiplayer", "players", "version", "mods"} from the first HEADER_BYTES of a save,
    or {"error"}."""
    try:
        with open(path, "rb") as f:
            data = f.read(HEADER_BYTES)
        h = reader.analyse_bytes(data)["header"]
    except (OSError, binary.SaveFormatError, ValueError, KeyError, IndexError) as exc:
        return {"error": str(exc) or type(exc).__name__}
    return {"date": (h.get("date") or {}).get("text"), "player_tag": h.get("player_tag"),
            "multiplayer": bool(h.get("multiplayer")), "players": [p.get("tag") for p in h.get("players") or []],
            "version": h.get("version"), "mods": len(h.get("mods") or [])}


class Checkpoints:
    """Save files with their header and the user's notes (keyed by file name)."""

    def __init__(self, notes_file: Path) -> None:
        self.file = notes_file
        self._lock = threading.Lock()
        self._headers: dict[tuple, dict] = {}   # (name, size, mtime) -> quick_header

    def _notes(self) -> dict:
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def list(self, saves_dir: Path | None) -> dict:
        items = reader.list_saves(saves_dir)
        notes = self._notes()
        out = []
        for item in items[:MAX_CHECKPOINTS]:
            key = (item["name"], item["size"], item["mtime"])
            if key not in self._headers:
                self._headers[key] = quick_header(Path(saves_dir) / item["name"])
            note = notes.get(item["name"]) or {}
            out.append({**item, **self._headers[key], "note": note.get("text", ""),
                        "note_changed": note.get("mtime") is not None and abs(note["mtime"] - item["mtime"]) > 1,
                        "note_at": note.get("at")})
        return {"directory": str(saves_dir) if saves_dir else None, "saves": out, "total": len(items),
                "orphan_notes": sorted(set(notes) - {i["name"] for i in items})}

    def set_note(self, saves_dir: Path | None, name: str, text: str) -> dict:
        """The note on save `name` (a file in the folder); an empty text removes it."""
        text = (text or "").strip()
        if len(text) > MAX_NOTE:
            raise ValueError(f"A note can have at most {MAX_NOTE} characters")
        match = next((i for i in reader.list_saves(saves_dir) if i["name"] == name), None)
        with self._lock:
            notes = self._notes()
            if not text:
                notes.pop(name, None)
            elif match is None:
                raise LookupError(f"Unknown save: {name}")
            else:
                notes[name] = {"text": text, "mtime": match["mtime"], "at": time.time()}
            self.file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.file.with_suffix(".part")
            tmp.write_text(json.dumps(notes, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.file)
        return {"name": name, "note": notes.get(name, {}).get("text", "")}


def live_check(live, clock=time.perf_counter) -> dict:
    """Every live reader once for the player's country: {"running", "version", "tag", "checks": [{"id", "name",
    "ok", "ms", "detail" | "error"}]}."""
    status = live.status()
    process = status.get("process")
    if not process:
        return {"running": False, "version": None, "tag": None, "error": (status.get("error") or {}).get("message"),
                "checks": []}
    tag, tag_error = None, None
    try:
        tag = live.player_tag(process)
    except Exception as exc:   # noqa: BLE001 - reported, the checks that need no country still run
        tag_error = str(exc)

    def count(key):
        return lambda r: f"{len(r.get(key) or [])} {key}"
    checks = [
        ("date", "Game date", live.running_game, lambda r: (r or {}).get("date") or "not readable"),
        ("session", "Session (mode, countries)", live.session,
         lambda r: f"{r.get('game_mode') or 'mode unknown'}, {len(r.get('states') or {})} countries with states"),
        ("values", "Country values", lambda: live.values(tag),
         lambda r: f"{sum(v.get('status') == 'live' for v in r.values())} of {len(r)} fields live"),
        ("focus", "National focus", lambda: live.focus(tag), lambda r: r.get("current") or "no focus selected"),
        ("research", "Research slots", lambda: live.research(tag), count("slots")),
        ("factories", "Factories", lambda: live.factories(tag), lambda r: "read"),
        ("construction", "Construction queue", lambda: live.construction(tag), count("lines")),
        ("stockpile", "Equipment stockpile", lambda: live.stockpile(tag), count("entries")),
        ("military", "Army, navy, air force", lambda: live.military(tag), lambda r: "read"),
        ("ideas", "Spirits, laws, advisors", lambda: live.ideas(tag), lambda r: "read"),
        ("wars", "Wars", lambda: live.wars(tag), lambda r: "read"),
        ("fog", "Fog of war flag", live.fog_of_war, lambda r: "fog on" if r.get("fog") else "fog off"),
        ("combat_log", "Combat log patch", live.combat_log_patch,
         lambda r: r.get("error") or f"patch {r.get('state') or 'unknown'}"),
    ]
    needs_tag = {"values", "focus", "research", "factories", "construction", "stockpile", "military", "ideas", "wars"}
    out = []
    for cid, name, read, detail in checks:
        t = clock()
        try:
            if tag is None and cid in needs_tag:
                raise LookupError(f"Player country not readable: {tag_error}")
            ok, text = True, detail(read())
        except Exception as exc:   # noqa: BLE001 - a failing reader is the result of the check
            ok, text = False, f"{getattr(exc, 'code', type(exc).__name__)}: {exc}"
        out.append({"id": cid, "name": name, "ok": ok, "ms": round((clock() - t) * 1000, 1),
                    ("detail" if ok else "error"): text})
    return {"running": True, "version": process.get("version"), "tag": tag, "checks": out}
