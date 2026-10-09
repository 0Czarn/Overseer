"""Hoi4Integration: non-invasive detection of the running game.

Sources (all read-only): process list + process metadata (WinAPI), Steam registry and
library files, the game's launcher-settings.json / hoi4_rev.txt, and the user-data
folder (logs, continue_game.json). No memory access, no writes.
"""

from __future__ import annotations

import datetime as dt
import time
from pathlib import Path
from typing import Callable

from . import install as inst
from . import session as sess
from . import winproc
from .userdata import UserData, env_user_dir_override, resolve_user_dir


class Hoi4Integration:
    def __init__(
        self,
        process_finder: Callable[[str], list[dict]] = winproc.find_processes,
        steam_path_finder: Callable[[], Path | None] = inst.steam_path_from_registry,
        user_dir: Path | None = None,
        install_cache_s: float = 30.0,
    ) -> None:
        self._find_processes = process_finder
        self._steam_path_finder = steam_path_finder
        self._user_dir_override = user_dir or env_user_dir_override()
        self._install_cache_s = install_cache_s
        self._install_cache: tuple[float, tuple[Path, dict, Path] | None] | None = None

    # -- install lookup ------------------------------------------------------------------
    def _steam_install(self) -> tuple[Path, dict, Path] | None:
        now = time.monotonic()
        if self._install_cache and now - self._install_cache[0] < self._install_cache_s:
            return self._install_cache[1]
        found = None
        steam = self._steam_path_finder()
        if steam is not None:
            hit = inst.find_install_dir(inst.steam_libraries(steam))
            if hit:
                found = (hit[0], hit[1], steam)
        self._install_cache = (now, found)
        return found

    def _install(self, process: dict | None, warnings: list[str]) -> dict | None:
        steam_hit = self._steam_install()
        install_dir: Path | None = None
        source = None
        if process and process.get("path"):
            install_dir = Path(process["path"]).parent
            source = "running process"
        elif steam_hit:
            install_dir = steam_hit[0]
            source = "Steam library"
        if install_dir is None:
            return None

        manifest = steam_hit[1] if steam_hit and steam_hit[0] == install_dir else {}
        if steam_hit and process and process.get("path") and steam_hit[0] != install_dir:
            warnings.append(f"Running game is not the Steam install ({steam_hit[0]})")
        return {
            "path": str(install_dir),
            "source": source,
            "version": inst.read_version(install_dir),
            "steam": {"app_id": inst.HOI4_APP_ID, "build_id": manifest.get("buildid"),
                      "steam_path": str(steam_hit[2]) if steam_hit else None} if manifest else None,
            "revision": {"install_hash": inst.read_install_revision(install_dir)},
        }

    def _user_data(self, install: dict | None) -> UserData:
        if self._user_dir_override:
            return UserData(self._user_dir_override)
        game_data_path = ((install or {}).get("version") or {}).get("game_data_path")
        return UserData(resolve_user_dir(game_data_path))

    # -- GameIntegration -----------------------------------------------------------------
    def detect(self) -> dict:
        warnings: list[str] = []
        try:
            processes = self._find_processes(inst.HOI4_EXE)
        except OSError as exc:
            processes = []
            warnings.append(f"Process enumeration failed: {exc}")
        process = processes[0] if processes else None
        if len(processes) > 1:
            warnings.append(f"{len(processes)} {inst.HOI4_EXE} processes running; showing PID {process['pid']}")
        if process and process.get("path") is None:
            warnings.append("Could not query the game process (access denied?) - path and start time unknown")

        install = self._install(process, warnings)
        if install is None:
            warnings.append("HOI4 installation not found (Steam registry / library folders)")
        elif install["version"] is None:
            warnings.append("launcher-settings.json missing or unreadable - version unknown")

        userdata = self._user_data(install)
        session = None
        if userdata.exists():
            session = self._session(userdata, process, install, warnings)
        else:
            warnings.append(f"Game user folder not found: {userdata.root}")

        return {
            "process": process,
            "install": install,
            "userdata": userdata.summary() if userdata.exists() else None,
            "session": session,
            "warnings": warnings,
        }

    def _session(self, userdata: UserData, process: dict | None, install: dict | None,
                 warnings: list[str]) -> dict | None:
        started = None
        if process and process.get("started"):
            started = dt.datetime.fromisoformat(process["started"]).timestamp()

        def current(name: str) -> bool | None:
            """Whether a log file was written by the currently running game process."""
            path = userdata.log_path(name)
            if path is None or started is None:
                return None
            return path.stat().st_mtime >= started - 5

        revisions_text = userdata.read_text("code_revisions.log")
        if install and revisions_text:
            revisions = inst.parse_code_revisions(revisions_text)
            rev = install["revision"]
            rev.update(running_hash=revisions.get("game_hash_long"), hash_short=revisions.get("game_hash_short"),
                       timestamp=revisions.get("game_timestamp"), from_current_run=current("code_revisions.log"))
            if (rev["from_current_run"] and rev["install_hash"] and rev["running_hash"]
                    and rev["install_hash"] != rev["running_hash"]):
                warnings.append("Running build differs from the installed build (game updated while running?)")

        game_log = userdata.read_text("game.log")
        if game_log is None or process is None:
            return None
        hints = sess.parse_game_log(game_log)
        hints["from_current_run"] = current("game.log")
        hints["source"] = "game.log"
        if hints["from_current_run"] is False:
            warnings.append("game.log is older than the running process - session hints ignored")
            return None
        return hints

    def game_log_names(self) -> list[str]:
        return self._user_data(self._install(None, [])).log_names()

    def game_log(self, name: str, lines: int) -> dict | None:
        return self._user_data(self._install(None, [])).tail(name, lines)
