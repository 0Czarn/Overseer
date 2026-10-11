"""Debugger service: combines the game integration layer, DEMO data and reports
into the payloads served by the API. Contains no HTTP and no UI code."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import logging
import functools
import platform
import re
import sys
import threading
import time

from . import __version__, deficit, demo, equipment_changes, gamefiles, gfx, modifiers
from . import government as government_mod
from . import mio as mio_mod
from . import focus as focus_mod
from .applog import RingBufferHandler
from .integration import GameIntegration, NullIntegration
from .reports import ReportError, ReportStore
from .saves import equipment as save_equipment
from .saves import fields as save_fields
from .saves import states as save_states
from .saves import text as text_mod
from .saves.binary import SaveFormatError
from .saves.reader import SaveAnalyzer, list_saves

LIVE, DEMO, UNAVAILABLE, SAVE = "live", "demo", "unavailable", "save"

DEMO_NOTE = "DEMO data - not read from the game."
SAVE_NOTE = ("Read from a save file (copy). A save is a snapshot from the moment it was written, "
             "never the live state of the game.")
WRITE_NOTE = "Editing is disabled: no write method exists yet (planned Stage 4, singleplayer first)."

# Which data domains are live vs DEMO right now. Single source of truth for the UI badges.
CAPABILITIES: dict[str, dict] = {
    "detection": {"source": LIVE, "write": False, "note": "Process, install and version detection."},
    "game_logs": {"source": LIVE, "write": False, "note": "Read-only tail of the game's own log files."},
    "countries": {"source": DEMO, "write": False, "note": DEMO_NOTE},
    "players": {"source": SAVE, "write": False, "note": "Player -> country assignment from the newest save. " + SAVE_NOTE},
    "save_header": {"source": SAVE, "write": False,
                    "note": "Save header: country, in-game date, version, difficulty, ideology, mods."},
    "country_values": {"source": SAVE, "write": False,
                       "note": "From text saves (-force_text_save): political power, stability, war support, "
                               "command power, fuel, army XP, manpower, convoys. No write method."},
    "states": {"source": DEMO, "write": False, "note": WRITE_NOTE},
    "focus": {"source": DEMO, "write": False, "note": "Read-only preview. Queueing is not implemented."},
    "equipment": {"source": DEMO, "write": False, "note": WRITE_NOTE},
    "intel": {"source": DEMO, "write": False, "note": DEMO_NOTE},
}

# Game Tools catalogue. scope: "local" = only this app / this client; "shared" = would change the
# common game state and therefore needs a sync mechanism that works in multiplayer.
TOOLS: list[dict] = [
    {"id": "always_on_top", "name": "Always on top", "scope": "local", "status": "available",
     "description": "Keeps the debugger window above the game window. Affects only this app."},
    {"id": "compact_mode", "name": "Compact mode", "scope": "local", "status": "available",
     "description": "Denser layout for a small window next to the game. Affects only this app."},
    {"id": "redetect", "name": "Re-detect game", "scope": "local", "status": "available",
     "description": "Runs process/version detection again. Read-only."},
    {"id": "open_logs", "name": "Open HOI4 logs folder", "scope": "local", "status": "available",
     "description": "Opens the game's log folder in Explorer. Read-only."},
    {"id": "save_inspector", "name": "Save inspector", "scope": "local", "status": "available",
     "description": "Reads a copy of any save file (header, players, mods, structure check). Never modifies saves."},
    {"id": "debug_overlay", "name": "Debug visibility preview", "scope": "local", "status": "planned",
     "description": "Shows extra information inside the debugger only. Never changes what other players see."},
    {"id": "value_edit", "name": "Shared value change", "scope": "shared", "status": "planned",
     "description": "Changing country/state/equipment values. Requires a game-compatible sync method, "
                    "verified on two clients before it is offered in multiplayer."},
]


def envelope(source: str, data, note: str | None = None) -> dict:
    return {"source": source, "note": note, "data": data}


class NotFound(LookupError):
    pass


def version_core(version: str | None) -> str | None:
    """'Operation Postern v1.19.3.0.c01a (ff0e)' -> 'Operation Postern v1.19.3.0.c01a'.
    The suffix in parentheses differs between saves of the same build, so it is not compared."""
    if not version:
        return None
    return version.split(" (")[0].strip()


def save_freshness(save_mtime: float, game: dict, now: float | None = None) -> dict:
    """How a save relates to the game that is running right now. A save is never live."""
    now = time.time() if now is None else now
    age_s = max(0, int(now - save_mtime))
    process = game.get("process")
    started = process.get("started") if process else None
    if process is None:
        category, label = "game_not_running", "Game not running - this is the last saved state, not a live game"
    elif started is None:
        category, label = "unknown_session", "Game running, but its start time is unknown - cannot tell if this save is current"
    elif save_mtime >= dt.datetime.fromisoformat(started).timestamp():
        category, label = "current_session", "Snapshot written during the current game session - the game has moved on since"
    else:
        category, label = "previous_session", "From an EARLIER session - NOT the current game state"
    return {"category": category, "label": label, "age_s": age_s, "is_live": False}


@functools.lru_cache(maxsize=2)
def resource_order(roots: tuple[str, ...]) -> dict[str, dict]:
    """{resource: {"frame": icon_frame}} from common/resources (later roots override)."""
    out: dict[str, dict] = {}
    for root in map(Path, roots):
        for path in sorted((root / "common" / "resources").glob("*.txt")):
            try:
                items = text_mod.parse(re.sub(r"#[^\n]*", "", path.read_text(encoding="utf-8-sig", errors="replace")))
            except Exception:
                continue
            for _k, block in (i for i in items if isinstance(i, tuple)):
                for name, body in (i for i in block if isinstance(i, tuple)) if isinstance(block, list) else []:
                    frame = text_mod.get(body, "icon_frame") if isinstance(body, list) else None
                    if frame is not None:
                        out[name] = {"frame": int(float(frame))}
    return out


LOC_REF = re.compile(r"\$([A-Za-z0-9_.]+)(?:\|[^$]*)?\$")


def clean_loc(value: str, names: dict[str, str], depth: int = 3) -> str:
    """Game localisation -> plain text: $KEY$ references resolved, colour codes (§X ... §!), icons (£x)
    and scripted expressions ([Root.GetName]) removed; \\n kept as line breaks."""
    for _ in range(depth):
        value = LOC_REF.sub(lambda m: names.get(m.group(1), ""), value)
    value = re.sub(r"§[A-Za-z!]", "", value)
    value = re.sub(r"£[A-Za-z0-9_|]+", "", value)
    value = re.sub(r"\[[^\]]*\]", "", value)
    return re.sub(r"[ \t]+", " ", value.replace("\\n", "\n")).strip()


class DebuggerService:
    def __init__(self, integration: GameIntegration, reports: ReportStore, ring: RingBufferHandler,
                 logger: logging.Logger, data_dir: str = "", saves: SaveAnalyzer | None = None,
                 live=None) -> None:
        self.saves = saves
        self.live = live  # live.service.LiveService (process memory, read-only) or None
        self.integration = integration
        self.reports = reports
        self.ring = ring
        self.log = logger
        self.data_dir = data_dir
        self._last_detected: bool | None = None

    # -- status ---------------------------------------------------------------------------
    def detect(self) -> dict:
        snapshot = self.integration.detect()
        detected = snapshot.get("process") is not None
        if detected != self._last_detected:
            if detected:
                proc = snapshot["process"]
                self.log.info("HOI4 process detected: pid=%s path=%s", proc.get("pid"), proc.get("path"))
            elif self._last_detected is not None:
                self.log.info("HOI4 process no longer running")
            else:
                self.log.info("HOI4 process not running")
            self._last_detected = detected
        return {**snapshot, "detected": detected}

    def status(self) -> dict:
        return {
            "app": {
                "version": __version__,
                "python": sys.version.split()[0],
                "platform": platform.platform(),
                "data_dir": self.data_dir,
            },
            "game": self.detect(),
            "capabilities": self.capabilities(),
        }

    def capabilities(self) -> dict:
        caps = {key: dict(value) for key, value in CAPABILITIES.items()}
        if isinstance(self.integration, NullIntegration):
            for key in ("detection", "game_logs"):
                caps[key].update(source=UNAVAILABLE, note=self.integration.reason)
        return caps

    # -- countries (game files + newest save) -----------------------------------------------
    def _install_path(self) -> Path | None:
        path = (self.detect().get("install") or {}).get("path")
        return Path(path) if path and (Path(path) / "common" / "country_tags").is_dir() else None

    def countries(self) -> dict:
        """Tags from the game files, names from its localisation; existence, ideology and players from the
        newest save (countries owning at least one state). DEMO only when neither is available."""
        install = self._install_path()
        tags = gamefiles.tag_order(install) if install else []
        names = gamefiles.country_names(install) if install else {}
        summary, note = None, None
        picked = self._pick_save(None)
        if picked is not None:
            try:
                summary = self.saves.country_list(picked[0])
            except SaveFormatError as exc:
                note = f"Country list not read from {picked[0].name}: {exc}"
        if not tags and summary is None:
            return envelope(DEMO, demo.countries(), DEMO_NOTE)
        owners = (summary or {}).get("owners") or {}
        ruling = (summary or {}).get("ruling") or {}
        header = ((summary or {}).get("analysis") or {}).get("header") or {}
        players: dict[str, str] = {}
        for p in header.get("players") or []:  # co-op: several players can share one country
            if p.get("tag"):
                players[p["tag"]] = ", ".join(filter(None, [players.get(p["tag"]), p.get("name") or "unknown"]))
        items = []
        for tag in tags or sorted(owners):
            party = ruling.get(tag)
            items.append({
                "tag": tag, "name": names.get(f"{tag}_{party}") or names.get(tag) or tag,
                "exists": (tag in owners) if summary else None, "states": owners.get(tag, 0),
                "ruling_party": party, "player": players.get(tag),
                "is_player_country": tag == header.get("player_tag"), "is_ai": tag not in players,
            })
        if summary:
            items = [i for i in items if i["exists"]] + [i for i in items if not i["exists"]]
            analysis = summary["analysis"]
            note = (f"{len(owners)} countries own states in {analysis['file']['name']} "
                    f"({(header.get('date') or {}).get('text') or 'date unknown'}); names from the game localisation.")
        return envelope(SAVE if summary else LIVE, items, note or "Tags and names from the game files; "
                        "no readable save for existence and players.")

    def country(self, tag: str) -> dict:
        tag = tag.upper()
        listing = self.countries()
        if listing["source"] == DEMO:
            data = demo.country(tag)
            if data is None:
                raise NotFound(f"Unknown country tag: {tag}")
            return envelope(DEMO, {**data, "fields": demo.COUNTRY_FIELDS, "editable": False}, DEMO_NOTE)
        found = next((c for c in listing["data"] if c["tag"] == tag), None)
        if found is None:
            raise NotFound(f"Unknown country tag: {tag}")
        return envelope(SAVE, {**found, "values": {}, "fields": demo.COUNTRY_FIELDS,
                               "editable": False}, "Country identity from game files and the newest save; "
                        "values come from /save-values and live memory.")

    def states(self, owner: str | None = None) -> dict:
        """States of the newest save (snapshot) with names and provinces from the game files; DEMO without them."""
        install = self._install_path()
        picked = self._pick_save(None)
        items, note, source = None, None, DEMO
        if install and picked is not None:
            try:
                data = self.saves.states(picked[0])
            except SaveFormatError as exc:
                note = f"States not read from {picked[0].name}: {exc}"
            else:
                items = save_states.assemble(data, gamefiles.state_definitions(install), gamefiles.state_names(install))
                header = data["analysis"].get("header") or {}
                source = SAVE
                note = (f"{len(items)} states from {picked[0].name} ({(header.get('date') or {}).get('text') or 'date unknown'})"
                        "; names and provinces from the game files. Snapshot - not live.")
        if items is None:
            items = demo.states()
            note = f"{note} {DEMO_NOTE}" if note else DEMO_NOTE
        if owner:
            owner = owner.upper()
            items = [s for s in items if owner in (s["owner"], s["controller"])]
        return envelope(source, items, note)

    def _focus_context(self, tag: str):
        """(state from the newest save, focuses of its tree with statuses) or None."""
        install = self._install_path()
        picked = self._pick_save(None)
        if install is None or picked is None:
            return None
        state = self.saves.focus_state(picked[0], tag)
        userdata = (self.detect().get("userdata") or {}).get("path")
        folders = focus_mod.focus_folders(install, gamefiles.enabled_mods(Path(userdata)) if userdata else [])
        focuses = focus_mod.statuses(focus_mod.tree(folders, state["tree"]), state) if state["tree"] else []
        names = focus_mod.loc_names(install, {f["id"] for f in focuses})
        for f in focuses:
            name = names.get(f["id"])
            # scripted names ([GetSomething]) are resolved by the game at runtime - show a readable id instead
            f["name"] = name if name and "[" not in name else f["id"].split("_", 1)[-1].replace("_", " ").capitalize()
        return state, focuses

    def focus(self, tag: str) -> dict:
        """Focus tree of `tag` (game/mod files) with statuses from the newest save; the queue is a plan."""
        tag = tag.upper()
        try:
            ctx = self._focus_context(tag)
        except SaveFormatError as exc:
            ctx, note = None, f"Focus state not read: {exc}"
        else:
            note = None
        if ctx is None:
            return envelope(DEMO, {"tag": tag, "focuses": demo.focuses(tag), "queue_supported": False},
                            f"{note} {DEMO_NOTE}" if note else DEMO_NOTE)
        state, focuses = ctx
        analysis = state["analysis"]
        header = analysis.get("header") or {}
        queue = self._focus_queues().get(f"{tag}:{state['tree']}", [])
        return envelope(SAVE, {
            "tag": tag, "tree": state["tree"], "current": state["current"], "progress_days": state["progress"],
            "paused": state["paused"], "completed": len(state["completed"]), "focuses": focuses,
            "queue": focus_mod.validate_queue(focuses, state, queue), "queue_supported": False,
            "file": analysis["file"], "in_game_date": header.get("date"),
            "freshness": save_freshness(analysis["file"]["mtime"], self.detect()),
        }, f"Focus tree {state['tree']} from the game files; state of {tag} from {analysis['file']['name']} "
           f"({(header.get('date') or {}).get('text') or '?'}). Snapshot - not live.")

    def _focus_context_cached(self, tag: str, wait: bool = True):
        """_focus_context() cached per newest save (parsing a binary save takes seconds). With wait=False a
        missing context is built in the background and None is returned meanwhile ("loading")."""
        picked = self._pick_save(None)
        key = (tag, picked[0].name if picked else None, picked[0].stat().st_mtime if picked else None)
        cache = getattr(self, "_focus_cache", None)
        if cache is not None and cache[0] == key:
            return cache[1]
        if wait:
            self._focus_cache = (key, self._focus_context(tag))
            return self._focus_cache[1]
        if getattr(self, "_focus_loading", None) != key:
            self._focus_loading = key

            def build() -> None:
                try:
                    self._focus_cache = (key, self._focus_context(tag))
                except (SaveFormatError, OSError, ValueError) as exc:
                    self.log.warning("Focus tree for %s not read: %s", tag, exc)
            threading.Thread(target=build, daemon=True).start()
        return None

    def live_focus(self, tag: str | None = None) -> dict:
        """Live current focus of `tag` (default: player) + the next focus of the planned queue.

        Completed focuses come from game memory (the country's completed list), so the queue moves on without
        a new save; a focus newly in that list is reported once as `event`. `idle` = no focus selected: the
        moment to start the next one (the app notifies; the game has no command to start a focus)."""
        if self.live is None:
            raise NotFound("Live game access is disabled")
        live = self.live.focus(tag)
        tag = live["tag"]
        ctx = self._focus_context_cached(tag, wait=False)
        if ctx is None:  # tree still being read: report the live focus without queue information
            return {"data": {"tag": tag, "tree": None, "current": live["current"], "current_name": live["current"],
                             "progress_days": live["progress_days"], "days": None, "idle": live["current"] is None,
                             "next": None, "completed_since_save": [], "event": None, "loading": True,
                             "read_at": live["read_at"]}}
        state, focuses = ctx
        by_id = {f["id"]: f for f in focuses}
        tracks = getattr(self, "_focus_tracks", None)
        if tracks is None:
            tracks = self._focus_tracks = {}
        track = tracks.setdefault((tag, state["tree"]), {"seen": None, "event": None})
        if track["seen"] is not None:
            new = [f for f in live["completed"] if f not in track["seen"]]
            if new:
                # kept (not consumed): several pollers (watcher, focus view) must all see it; clients de-duplicate by id
                track["event"] = {"id": f"{tag}:{new[-1]}:{len(live['completed'])}", "completed": new[-1],
                                  "name": (by_id.get(new[-1]) or {}).get("name", new[-1]), "all": new,
                                  "at": live["read_at"]}
                self.log.info("Focus completed (live) %s: %s", tag, ", ".join(new))
        track["seen"] = set(live["completed"])
        event = track["event"] if track["event"] and live["read_at"] - track["event"]["at"] < 600 else None
        done = list(dict.fromkeys(state["completed"] + live["completed"]))
        now = {"completed": done, "current": live["current"], "progress": live["progress_days"]}
        queue = focus_mod.validate_queue(focuses, now, self._focus_queues().get(f"{tag}:{state['tree']}", []))
        nxt = next((q for q in queue if q["ok"]), None)
        cur = by_id.get(live["current"] or "")
        return {"data": {
            "tag": tag, "tree": state["tree"], "current": live["current"],
            "current_name": cur["name"] if cur else None, "progress_days": live["progress_days"],
            "days": cur["days"] if cur else None, "idle": live["current"] is None,
            "next": {"id": nxt["id"], "name": by_id[nxt["id"]]["name"], "days": by_id[nxt["id"]]["days"]} if nxt else None,
            "completed_since_save": [f for f in live["completed"] if f not in state["completed"]],
            "event": event, "read_at": live["read_at"],
        }}

    def live_session(self) -> dict:
        """Countries that exist in the running game (own at least one state, game memory) and its players.

        Players: the local player's country from memory; the account name from the newest save that lists it.
        Other players of a multiplayer session are not read from memory yet (not verified in multiplayer)."""
        if self.live is None:
            raise NotFound("Live game access is disabled")
        live = self.live.session()
        # names as in the country list (ideology-specific from the newest save's ruling party)
        names = {c["tag"]: c["name"] for c in self.countries()["data"]}
        account = None
        picked = self._pick_save(None)
        if picked is not None:
            try:
                header = self.saves.analyse(picked[0]).get("header") or {}
            except SaveFormatError:
                header = {}
            account = next((p.get("name") for p in header.get("players") or []
                            if p.get("tag") == header.get("player_tag")), None)
        players = [{"tag": tag, "name": account, "local": True, "name_source": "save" if account else None}
                   for tag in live["players"][:1]]
        countries = [{"tag": tag, "name": names.get(tag, tag), "states": n,
                      "player": account if live["players"][:1] == [tag] else None}
                     for tag, n in live["states"].items() if n > 0]
        countries.sort(key=lambda c: -c["states"])
        mode = live["game_mode"]
        note = (f"{len(countries)} countries own states in the running game (game memory, "
                f"{(live['process'] or {}).get('version')}).")
        return envelope(LIVE, {"game_mode": mode, "players": players, "countries": countries,
                               "other_players_readable": False, "read_at": live["read_at"]}, note)

    def live_stockpile(self, tag: str | None = None) -> dict:
        """Live stockpile (game memory) with archetype / equipment type from the newest save's variant table."""
        if self.live is None:
            raise NotFound("Live game access is disabled")
        live = self.live.stockpile(tag)
        install = self._install_path()
        picked = self._pick_save(None)
        variants, names, archetypes = {}, {}, {}
        if install and picked is not None:
            try:
                variants = self.saves.equipment(picked[0], live["tag"])["variants"]
            except SaveFormatError:
                variants = {}
            names = gamefiles.equipment_names(install)
            archetypes = deficit.tables(install)[1]
        entries = []
        for e in live["entries"]:
            v = variants.get(e["id"]) or {}
            eq_type = v.get("type")
            entries.append({**e, "type": eq_type, "type_name": names.get(eq_type, eq_type) if eq_type else None,
                            "archetype": deficit.archetype_of(eq_type, archetypes) if eq_type else None,
                            "name": e["name"] or v.get("name")})
        return {"data": {"tag": live["tag"], "entries": entries, "read_at": live["read_at"]}}

    def _focus_queue_file(self) -> Path:
        return Path(self.data_dir) / "focus-queues.json"

    def _focus_queues(self) -> dict:
        try:
            data = json.loads(self._focus_queue_file().read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def set_focus_queue(self, tag: str, queue: list) -> dict:
        """Stores the planned order of focuses for `tag` (its current tree) and returns it validated."""
        tag = tag.upper()
        if not isinstance(queue, list) or len(queue) > 200 or not all(isinstance(q, str) and len(q) < 200 for q in queue):
            raise ReportError("queue must be a list of up to 200 focus ids")
        ctx = self._focus_context(tag)
        if ctx is None:
            raise NotFound("No game installation or save to read the focus tree from")
        state, focuses = ctx
        queues = self._focus_queues()
        queues[f"{tag}:{state['tree']}"] = queue
        self._focus_queue_file().write_text(json.dumps(queues, indent=1), encoding="utf-8")
        self.log.info("Focus queue %s (%s): %s", tag, state["tree"], ", ".join(queue) or "empty")
        return {"data": focus_mod.validate_queue(focuses, state, queue)}

    def equipment(self, tag: str) -> dict:
        """Stockpile and convoys of `tag` from the newest save, names from the game files; DEMO without them."""
        tag = tag.upper()
        install = self._install_path()
        picked = self._pick_save(None)
        if install and picked is not None:
            try:
                data = self.saves.equipment(picked[0], tag)
            except SaveFormatError as exc:
                note = f"Equipment not read from {picked[0].name}: {exc}"
            else:
                analysis = data["analysis"]
                header = analysis.get("header") or {}
                userdata = (self.detect().get("userdata") or {}).get("path")
                mods = gamefiles.enabled_mods(Path(userdata)) if userdata else []
                needs, archetypes = deficit.tables(install, mods)
                names = gamefiles.equipment_names(install)
                items = save_equipment.rows(data, names)
                balance = deficit.compute(data, needs, archetypes)
                groups: dict[str, dict] = {}
                for item in items:
                    if item["pool"] != "stockpile":
                        continue
                    a = deficit.archetype_of(item["archetype"], archetypes)
                    g = groups.setdefault(a, {"archetype": a, "name": names.get(a, a.replace("_", " ").capitalize()),
                                              "variants": []})
                    g["variants"].append(item)
                for a, b in balance.items():
                    if b["need"] or b["stockpile"]:
                        groups.setdefault(a, {"archetype": a, "name": names.get(a, a.replace("_", " ").capitalize()),
                                              "variants": []})
                for a, g in groups.items():
                    g.update({k: balance.get(a, {}).get(k, 0.0) for k in ("need", "held", "missing", "shortfall")})
                    g["stockpile"] = sum(v["amount"] for v in g["variants"])
                ordered = sorted(groups.values(), key=lambda g: (-g["shortfall"], g["name"]))
                return envelope(SAVE, {
                    "tag": tag, "items": items, "groups": ordered,
                    "designs": equipment_changes.designs(data, tag),
                    "editable": False, "file": analysis["file"], "in_game_date": header.get("date"),
                    "player_tag": header.get("player_tag"),
                    "freshness": save_freshness(analysis["file"]["mtime"], self.detect()),
                }, f"Stockpile of {tag} from {picked[0].name} ({(header.get('date') or {}).get('text') or '?'}). "
                   "Snapshot - not live.")
        else:
            note = None
        return envelope(DEMO, {"tag": tag, "items": demo.equipment(tag), "editable": False},
                        f"{note} {DEMO_NOTE}" if note else DEMO_NOTE)

    def intel(self, observer: str, target: str) -> dict:
        target_country = demo.country(target)
        if target_country is None or demo.country(observer) is None:
            raise NotFound("Unknown country tag")
        levels = demo.intel(observer, target) or {"civilian": 0.0, "army": 0.0, "navy": 0.0, "airforce": 0.0}
        return envelope(DEMO, {
            "observer": observer.upper(),
            "target": target.upper(),
            "intel_levels": levels,
            # "actual" is what the debugger can see; "visible" is what the observer would see in game.
            "actual": target_country["values"],
            "visible_rule": "DEMO rule: a value is shown to the observer when civilian intel >= 30%.",
            "visible": target_country["values"] if levels["civilian"] >= 0.30 else None,
        }, DEMO_NOTE)

    # -- save files ---------------------------------------------------------------------
    def saves_list(self) -> dict:
        directory = self.integration.saves_dir()
        if directory is None:
            return envelope(UNAVAILABLE, [], "Save folder not found")
        game = self.detect()
        items = list_saves(directory)
        for item in items:
            item["freshness"] = save_freshness(item["mtime"], game)
        return envelope(SAVE, {"directory": str(directory), "saves": items}, SAVE_NOTE)

    def save_analysis(self, name: str | None) -> dict:
        directory = self.integration.saves_dir()
        if directory is None or self.saves is None:
            return envelope(UNAVAILABLE, None, "Save folder not found")
        items = list_saves(directory)
        if not items:
            return envelope(UNAVAILABLE, None, "No save files found")
        if name:
            match = next((i for i in items if i["name"] == name), None)  # only names that exist in the folder
            if match is None:
                raise NotFound(f"Unknown save: {name}")
        else:
            match = items[0]
        result = self.saves.analyse(directory / match["name"])
        game = self.detect()
        result["freshness"] = save_freshness(result["file"]["mtime"], game)
        result["is_latest"] = match["name"] == items[0]["name"]
        running = ((game.get("install") or {}).get("version") or {}).get("display") if game.get("process") else None
        saved = (result.get("header") or {}).get("version")
        result["version_check"] = {
            "running": running, "save": saved,
            "match": None if not (running and saved) else version_core(running) == version_core(saved),
        }
        return envelope(SAVE, result, SAVE_NOTE)

    def _pick_save(self, name: str | None) -> tuple[Path, dict] | None:
        directory = self.integration.saves_dir()
        if directory is None or self.saves is None:
            return None
        items = list_saves(directory)
        if not items:
            return None
        if name:
            match = next((i for i in items if i["name"] == name), None)
            if match is None:
                raise NotFound(f"Unknown save: {name}")
        else:
            match = items[0]
        return directory / match["name"], {"is_latest": match["name"] == items[0]["name"]}

    def _controlled_buildings(self, path: Path, install: Path, tag: str) -> list[str]:
        """Province buildings in provinces `tag` controls (province controller, else the state owner)."""
        try:
            save = self.saves.states(path)
        except SaveFormatError:
            return []
        state_of = {prov: sid for sid, d in gamefiles.state_definitions(install).items() for prov in d["provinces"]}
        out = []
        for prov, info in save["provinces"].items():
            owner = (save["states"].get(state_of.get(int(prov))) or {}).get("owner")
            if (info.get("controller") or owner) == tag:
                out.extend(b for b, level in (info.get("buildings") or {}).items() if level)
        return sorted(set(out))

    def _game_roots(self, install: Path) -> tuple[str, ...]:
        userdata = (self.detect().get("userdata") or {}).get("path")
        mods = gamefiles.enabled_mods(Path(userdata)) if userdata else []
        return tuple(str(r) for r in [install, *mods])

    def spirits(self, tag: str) -> dict:
        """National spirits of `tag` (newest save) with icon, name, description and every modifier."""
        tag = tag.upper()
        install = self._install_path()
        picked = self._pick_save(None)
        if install is None or picked is None:
            return envelope(UNAVAILABLE, None, "Needs the game installation and a save")
        try:
            state = self.saves.politics(picked[0], tag)
        except SaveFormatError as exc:
            return envelope(UNAVAILABLE, None, str(exc))
        analysis = state.pop("analysis")
        state.pop("_all", None)
        live = self._live_ideas(tag, state)
        roots = self._game_roots(install)
        defs = modifiers.definitions(roots)
        out = self._present(modifiers.spirits(state, defs), install, roots)
        return envelope(SAVE, {"tag": tag, "spirits": out, "ideas_source": "live" if live else "save",
                               "file": analysis["file"],
                               "in_game_date": (analysis.get("header") or {}).get("date")},
                        f"National spirits from {analysis['file']['name']}; icons and texts from the game files.")

    def government(self, tag: str) -> dict:
        """Laws & Government, Research & Production, Military Staff of `tag` (newest save), one entry per slot."""
        tag = tag.upper()
        install = self._install_path()
        picked = self._pick_save(None)
        if install is None or picked is None:
            return envelope(UNAVAILABLE, None, "Needs the game installation and a save")
        try:
            state = self.saves.politics(picked[0], tag)
        except SaveFormatError as exc:
            return envelope(UNAVAILABLE, None, str(exc))
        analysis = state.pop("analysis")
        state.pop("_all", None)
        live = self._live_ideas(tag, state)
        roots = self._game_roots(install)
        defs = modifiers.definitions(roots)
        groups = government_mod.sections(state, defs)
        flat = [it for items in groups.values() for it in items]
        shown = iter(self._present(flat, install, roots))
        data = {name: [next(shown) for _ in items] for name, items in groups.items()}
        data["mios"] = self._mios(state, tag, install, roots)
        return envelope(SAVE, {"tag": tag, **data, "ideas_source": "live" if live else "save", "file": analysis["file"],
                               "in_game_date": (analysis.get("header") or {}).get("date")},
                        f"Laws, companies and advisors from {analysis['file']['name']}.")

    def resources(self, tag: str) -> dict:
        """Resources of `tag` (newest save): produced, to market, sold, imported (with the selling countries),
        available at home and used by production, per resource; icons from the game's resource strip."""
        tag = tag.upper()
        install = self._install_path()
        picked = self._pick_save(None)
        if install is None or picked is None:
            return envelope(UNAVAILABLE, None, "Needs the game installation and a save")
        try:
            state = self.saves.politics(picked[0], tag)
        except SaveFormatError as exc:
            return envelope(UNAVAILABLE, None, str(exc))
        analysis = state.pop("analysis")
        everyone = state.pop("_all", {})
        res = state["resources"]
        roots = self._game_roots(install)
        order = resource_order(roots)
        sellers: dict[str, list] = {}
        live = self._live_resources(tag, list(order))
        if live:
            res = {**{k: live[k] for k in ("produced", "to_market", "exported", "imported", "available", "used")},
                   "exports": [{"receiver": d["buyer"], "resource": d["resource"], "amount": d["amount"]}
                               for d in live["exports"]]}
            for deal in live["imports"]:
                if deal["amount"] and deal["seller"]:
                    sellers.setdefault(deal["resource"], []).append({"country": deal["seller"], "amount": deal["amount"]})
        else:
            for other, st in everyone.items():
                for deal in (st.get("resources") or {}).get("exports", []):
                    if deal["receiver"] == tag and deal["amount"]:
                        sellers.setdefault(deal["resource"], []).append({"country": other, "amount": deal["amount"]})
        keys = set(order) | set().union(*[set(v) for k, v in res.items() if isinstance(v, dict)])
        names = focus_mod.loc_names(install, {f"PRODUCTION_MATERIALS_{k.upper()}" for k in keys})
        rows = []
        for k in sorted(keys, key=lambda k: (order.get(k, {}).get("frame", 99), k)):
            get = lambda part: round(res[part].get(k, 0.0), 3)  # noqa: E731
            rows.append({"resource": k, "name": names.get(f"PRODUCTION_MATERIALS_{k.upper()}", k.capitalize()),
                         "frame": order.get(k, {}).get("frame"), "produced": get("produced"),
                         "to_market": get("to_market"), "exported": get("exported"), "imported": get("imported"),
                         "available": get("available"), "used": get("used"),
                         "balance": round(get("available") - get("used"), 3),
                         "buyers": sorted(({"country": d["receiver"], "amount": d["amount"]} for d in res["exports"]
                                           if d["resource"] == k and d["amount"]), key=lambda d: -d["amount"]),
                         "sellers": sorted(sellers.get(k, []), key=lambda d: -d["amount"])})
        sprites = gfx.sprites(roots)
        strip = sprites.get("GFX_resources_strip")
        return envelope(SAVE, {"tag": tag, "resources": rows, "icons": gfx.icon_data_uri(strip) if strip else None,
                               "icon_frames": max([v["frame"] for v in order.values()] or [0]),
                               "resources_source": "live" if live else "save",
                               "file": analysis["file"], "in_game_date": (analysis.get("header") or {}).get("date")},
                        "Resources per day from game memory." if live
                        else f"Resources per day from {analysis['file']['name']}.")

    def _live_ideas(self, tag: str, state: dict) -> bool:
        """Replaces state["ideas"] with the live ideas of `tag`; False when the game cannot be read."""
        if self.live is None:
            return False
        try:
            state["ideas"] = self.live.ideas(tag)["ideas"]
        except Exception:  # live data is optional: the save values stay
            return False
        return True

    def _live_resources(self, tag: str, order: list[str]) -> dict | None:
        """Live resources and trade deals of `tag`, or None (game not running, other version, ...)."""
        if self.live is None:
            return None
        try:
            return self.live.resources(tag, order)
        except Exception:  # live data is optional: the save values stay
            return None

    def _live_parties(self, tag: str, roots: tuple[str, ...]) -> dict | None:
        """Live popularity / ruling party, or None (game not running, other version, ...)."""
        if self.live is None:
            return None
        try:
            return self.live.parties(tag, list(government_mod.ideologies(roots)["colors"]))
        except Exception:  # live data is optional: the save values stay
            return None

    def overview(self, tag: str) -> dict:
        """Who rules `tag`: leader (portrait, sub-ideology, traits), ruling party, faction, party popularities."""
        tag = tag.upper()
        install = self._install_path()
        picked = self._pick_save(None)
        if install is None or picked is None:
            return envelope(UNAVAILABLE, None, "Needs the game installation and a save")
        try:
            state = self.saves.politics(picked[0], tag)
        except SaveFormatError as exc:
            return envelope(UNAVAILABLE, None, str(exc))
        analysis = state.pop("analysis")
        state.pop("_all", None)
        roots = self._game_roots(install)
        defs = modifiers.definitions(roots)
        ideo = government_mod.ideologies(roots)
        live_parties = self._live_parties(tag, roots)
        if live_parties:
            state["popularity"] = live_parties["popularity"]
            state["ruling_party"] = live_parties["ruling"] or state.get("ruling_party")
        parties = state.get("party_names") or {}
        names_needed = set(parties) | {f"{i}_noun" for i in parties} | {state.get("leader_ideology") or ""}
        for ideology, p in parties.items():
            names_needed.update(filter(None, [p["name"], p["long_name"], f"{tag}_{ideology}_party",
                                              f"{tag}_{ideology}_party_long"]))
        faction = state.get("faction")
        template = (ideo["factions"].get((faction or {}).get("template") or "") or {})
        names_needed.update(filter(None, [(faction or {}).get("name"), template.get("name")]))
        leader = (state.get("characters") or {}).get(state.get("leader") or "")
        names_needed.update(filter(None, [leader and leader["name"], leader and leader["token"],
                                          *((leader or {}).get("leader_traits") or [])]))
        names = focus_mod.loc_names(install, names_needed)
        refs = {r for v in names.values() for r in LOC_REF.findall(v)}
        names.update(focus_mod.loc_names(install, refs - set(names)))
        loc = lambda *keys: next((clean_loc(names[k], names) for k in keys if k and names.get(k)), None)  # noqa: E731
        sprites = gfx.sprites(roots)
        icon = lambda sprite: gfx.icon_data_uri(sprites[sprite]) if sprite and sprite in sprites else None  # noqa: E731
        party_list = []
        for ideology, popularity in sorted((state.get("popularity") or {}).items(), key=lambda x: -x[1]):
            p = parties.get(ideology) or {}
            party_list.append({
                "ideology": ideology, "ideology_name": loc(f"{ideology}_noun", ideology) or ideology,
                "name": loc(p.get("name"), f"{tag}_{ideology}_party", ideology) or ideology,
                "long_name": loc(p.get("long_name"), f"{tag}_{ideology}_party_long"),
                "popularity": popularity, "ruling": ideology == state.get("ruling_party"),
                "color": "#%02x%02x%02x" % ideo["colors"].get(ideology, (128, 128, 128))})
        leader_out = None
        if leader:
            portrait = next((leader["portraits"].get(k, {}).get(s) for k in ("civilian", "army", "navy")
                             for s in ("large", "small") if leader["portraits"].get(k, {}).get(s)), None)
            leader_out = {
                "name": loc(leader["name"], leader["token"]) or leader["name"], "portrait": icon(portrait),
                "ideology": state.get("leader_ideology"), "ideology_name": loc(state.get("leader_ideology")),
                "traits": [{"name": loc(t) or t, "modifiers": [
                    {"key": k, "label": k.replace("_", " ").capitalize(), "value": v}
                    for k, v in defs["traits"].get(t, {}).items()]} for t in leader["leader_traits"]]}
            # proper modifier labels
            labels = focus_mod.loc_names(install, {f"MODIFIER_{m['key'].upper()}" for t in leader_out["traits"]
                                                   for m in t["modifiers"]})
            for t in leader_out["traits"]:
                for m in t["modifiers"]:
                    m["label"] = clean_loc(labels.get(f"MODIFIER_{m['key'].upper()}", ""), names) or m["label"]
        faction_out = None
        if faction:
            faction_out = {"name": loc(faction.get("name"), template.get("name")) or template.get("name") or "Faction",
                           "icon": icon(faction.get("icon") or template.get("icon")), "members": faction["members"],
                           "leader": faction["members"][0] if faction["members"] else None}
        return envelope(SAVE, {"tag": tag, "leader": leader_out, "parties": party_list, "faction": faction_out,
                               "ruling_party": state.get("ruling_party"), "parties_source": "live" if live_parties else "save",
                               "file": analysis["file"],
                               "in_game_date": (analysis.get("header") or {}).get("date")},
                        f"Government from {analysis['file']['name']}.")

    def _mios(self, state: dict, tag: str, install: Path, roots: tuple[str, ...]) -> dict[str, list[dict]]:
        """{design slot: [MIO for display]} - level, funds, policy, unlocked traits and current bonuses."""
        defs = mio_mod.definitions(roots)
        items = [s for s in (mio_mod.summary(m, defs) for m in state.get("mios") or []) if s]
        def name_keys(it):
            n = it["name_key"]
            return [k for k in (f"{tag}_{n}" if n else None, n, f"{tag}_{it['id']}", it["id"]) if k]
        def trait_keys(it, t):
            n = t.get("name")
            return [k for k in (f"{tag}_{n}" if n else None, n, f"{tag}_{it['id']}_{t['token']}",
                                f"{it['id']}_{t['token']}", t["token"]) if k]
        stat_keys = lambda kind, stat: (  # noqa: E731
            [f"STAT_{p}_{stat.upper()}" for p in ("ARMY", "COMMON", "NAVY", "AIR")] if kind == "equipment_bonus"
            else [f"BONUS_{stat.upper()}"] if kind == "production_bonus" else [f"MODIFIER_{stat.upper()}"])
        keys = {"MODIFIER_MIO_RESEARCH_BONUS"}
        for it in items:
            keys.update(name_keys(it))
            keys.update(k for t in it["traits"] + ([it["initial_trait"]] if it["initial_trait"] else []) for k in trait_keys(it, t))
            keys.add(it["policy"] or "")
            keys.update(k for kind, stats in it["bonuses"].items() for s in stats for k in stat_keys(kind, s))
        names = focus_mod.loc_names(install, keys)
        refs = {r for v in names.values() for r in LOC_REF.findall(v)}
        names.update(focus_mod.loc_names(install, refs - set(names)))
        def loc(cands, fallback):
            for k in cands:
                v = clean_loc(names[k], names).rstrip(": ").strip() if k in names else ""
                if v and "$" not in v:
                    return v
            return fallback.replace("_", " ").capitalize()
        sprites = gfx.sprites(roots)
        groups = {"equipment_bonus": "Equipment", "production_bonus": "Production", "organization_modifier": "Organization"}
        out: dict[str, list[dict]] = {c: [] for c in mio_mod.CATEGORIES}
        for it in sorted(items, key=lambda i: (-(i["size"] or 0), i["id"])):
            texture = sprites.get(it["icon"] or "")
            out[it["category"]].append({
                "id": it["id"], "name": loc(name_keys(it), it["id"].removesuffix("_organization")),
                "icon": gfx.icon_data_uri(texture) if texture else None, "size": it["size"], "funds": it["funds"],
                "research_bonus": it["research_bonus"],
                "policy": loc([it["policy"]], it["policy"]) if it["policy"] else None,
                "initial_trait": loc(trait_keys(it, it["initial_trait"]), it["initial_trait"]["token"] or "initial trait")
                if it["initial_trait"] else None,
                "traits": [loc(trait_keys(it, t), t["token"]) for t in it["traits"]],
                "bonuses": [{"group": groups[kind], "entries": [
                    {"key": stat, "label": "Research bonus" if stat == "military_industrial_organization_research_bonus"
                     else loc(stat_keys(kind, stat), stat), "value": v} for stat, v in stats.items() if v]}
                    for kind, stats in it["bonuses"].items() if any(stats.values())],
            })
        return out

    def _present(self, items: list[dict], install: Path, roots: tuple[str, ...]) -> list[dict]:
        """Localised names, descriptions, modifier labels, trait names and icons (data: URIs) for display."""
        keys = set()
        for it in items:
            keys.update(filter(None, [it["name_key"], it.get("alt_name_key"), it.get("slot"),
                                      f"{it['name_key']}_desc", f"{it['id']}_desc", *it["tooltips"], *it.get("traits", [])]))
            keys.update(k for m in it["modifiers"] for k in (f"MODIFIER_{m.upper()}", m))
        names = focus_mod.loc_names(install, keys)
        refs = {r for v in names.values() for r in LOC_REF.findall(v)}
        names.update(focus_mod.loc_names(install, refs - set(names)))
        clean = lambda value: clean_loc(value, names) if value else value  # noqa: E731
        sprites = gfx.sprites(roots)
        out = []
        for it in items:
            texture = sprites.get(it["icon"] or "")
            if texture is None and it["icon"] and it["icon"].lower().endswith((".dds", ".png")):
                texture = next((str(Path(r) / it["icon"]) for r in reversed(roots) if (Path(r) / it["icon"]).exists()), None)
            name = clean(names.get(it["name_key"] or "") or names.get(it.get("alt_name_key") or ""))
            out.append({
                "kind": it["kind"], "id": it["id"], "slot": it.get("slot"), "slot_label": it.get("slot_label"),
                "name": name or (it["name_key"] or "").split("_", 1)[-1].replace("_", " ").title() or None,
                "traits": [clean(names.get(t)) or t for t in it.get("traits", [])],
                "description": clean(names.get(f"{it['name_key']}_desc") or names.get(f"{it['id']}_desc"))
                if it["name_key"] else None,
                "icon": gfx.icon_data_uri(texture) if texture else None,
                "modifiers": [{"key": k, "label": clean(names.get(f"MODIFIER_{k.upper()}") or names.get(k))
                               or k.replace("_", " ").capitalize(), "value": v} for k, v in it["modifiers"].items()],
                "tooltips": [clean(names.get(t)) or t for t in it["tooltips"]],
            })
        return out

    def stability(self, tag: str) -> dict:
        """Stability and war support as the game shows them: base + every modifier with its source.

        Modifiers come from the newest save (ideas, party popularity, leader, advisors, dynamic modifiers) and the
        game files; the base value from game memory when the game runs (it changes instantly), else from the save."""
        tag = tag.upper()
        install = self._install_path()
        picked = self._pick_save(None)
        if install is None or picked is None:
            return envelope(UNAVAILABLE, None, "Needs the game installation and a save")
        path = picked[0]
        try:
            state = self.saves.politics(path, tag)
        except SaveFormatError as exc:
            return envelope(UNAVAILABLE, {"file": path.name, "error": {"code": exc.code, "message": str(exc)}},
                            str(exc))
        analysis = state.pop("analysis")
        state.pop("_all", None)
        state["buildings"] = self._controlled_buildings(path, install, tag)
        live_ideas = self._live_ideas(tag, state)
        userdata = (self.detect().get("userdata") or {}).get("path")
        mods = gamefiles.enabled_mods(Path(userdata)) if userdata else []
        defs = modifiers.definitions(tuple(str(r) for r in [install, *mods]))
        names = focus_mod.loc_names(install, modifiers.loc_keys(state, defs))
        live_parties = self._live_parties(tag, tuple(str(r) for r in [install, *mods]))
        if live_parties:
            state["popularity"] = live_parties["popularity"]
            state["ruling_party"] = live_parties["ruling"] or state.get("ruling_party")
        base_source = {}
        for field in modifiers.KEYS:
            base_source[field] = "save"
            if self.live is not None:
                try:
                    state[field] = self.live.read(field, tag)["value"]
                    base_source[field] = "live"
                except Exception:  # game not running / other version: the save value stays
                    pass
        result = modifiers.breakdown(state, defs, names)
        for field in modifiers.KEYS:
            result[field]["base_source"] = base_source[field]
        game = self.detect()
        return envelope(SAVE, {
            "tag": tag, **result, "ideas_source": "live" if live_ideas else "save", "file": analysis["file"],
            "in_game_date": (analysis.get("header") or {}).get("date"),
            "freshness": save_freshness(analysis["file"]["mtime"], game),
            "not_read": ["core coastal states protection", "at war", "foreign propaganda", "occupation resistance",
                         "bombing / casualties / sunk convoys"] + [f"faction rule {r} (condition)"
                                                                  for r in result["unchecked_rules"]],
        }, f"Modifiers from {analysis['file']['name']} and the game files.")

    def country_save_values(self, tag: str, name: str | None) -> dict:
        """Real Country Editor values read from a save (snapshot). Never presented as live."""
        tag = tag.upper()
        picked = self._pick_save(name)
        if picked is None:
            return envelope(UNAVAILABLE, None, "No save file available")
        path, extra = picked
        read_at = dt.datetime.now().isoformat(timespec="seconds")
        try:
            out = self.saves.country_values(path, tag)
        except SaveFormatError as exc:
            return envelope(UNAVAILABLE, {"file": path.name, "error": {"code": exc.code, "message": str(exc)}},
                            str(exc))
        except ValueError as exc:
            raise NotFound(str(exc)) from exc
        analysis = out["analysis"]
        game = self.detect()
        return envelope(SAVE, {
            "tag": tag,
            "values": out["values"],
            "file": analysis["file"],
            "in_game_date": (analysis.get("header") or {}).get("date"),
            "save_version": (analysis.get("header") or {}).get("version"),
            "player_tag": (analysis.get("header") or {}).get("player_tag"),
            "freshness": save_freshness(analysis["file"]["mtime"], game),
            "read_at": read_at,
            **extra,
        }, SAVE_NOTE)

    def player_save_values(self) -> dict:
        """Values of the player country of the newest save (evidence source for live calibration)."""
        analysis = self.save_analysis(None)
        data = analysis.get("data") or {}
        tag = (data.get("header") or {}).get("player_tag")
        if analysis["source"] != SAVE or not tag:
            error = data.get("error") or {}
            note = (f"{error['message']} [{error.get('code')}]" if error.get("message")
                    else analysis.get("note") if analysis["source"] != SAVE else "Newest save has no player country")
            return envelope(UNAVAILABLE, {"error": error} if error else None, note)
        return self.country_save_values(tag, None)

    def save_fields(self) -> dict:
        return envelope(LIVE, save_fields.field_catalog())

    def tools(self) -> dict:
        return envelope(LIVE, TOOLS)

    # -- logs & reports -------------------------------------------------------------------
    def app_log(self, limit: int, level: str, after: int) -> dict:
        return envelope(LIVE, self.ring.entries(limit=limit, min_level=level, after_seq=after))

    def client_log(self, payload: dict) -> dict:
        level = str(payload.get("level", "info")).lower()
        message = str(payload.get("message", ""))[:2000]
        log_fn = {"debug": self.log.debug, "warning": self.log.warning, "error": self.log.error}.get(level, self.log.info)
        log_fn("%s", message, extra={"origin": "ui"})
        return {"ok": True}

    def game_log_names(self) -> dict:
        names = self.integration.game_log_names()
        return envelope(LIVE if names else UNAVAILABLE, names)

    def game_log(self, name: str, lines: int) -> dict:
        data = self.integration.game_log(name, lines)
        if data is None:
            return envelope(UNAVAILABLE, None, f"Log '{name}' is not available")
        return envelope(LIVE, data)

    def list_reports(self) -> dict:
        return envelope(LIVE, self.reports.list())

    def get_report(self, report_id: str) -> dict:
        report = self.reports.get(report_id)
        if report is None:
            raise NotFound(f"Unknown report: {report_id}")
        return envelope(LIVE, report)

    def create_report(self, payload: dict) -> dict:
        status = self.status()
        environment = {"app": status["app"], "game": {k: status["game"].get(k) for k in
                                                       ("detected", "process", "install", "session")}}
        report = self.reports.create(payload, environment)
        self.log.info("Test report saved: %s", report["id"])
        return envelope(LIVE, report)
