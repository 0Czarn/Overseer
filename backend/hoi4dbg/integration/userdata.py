"""The game's user-data folder (Documents\\Paradox Interactive\\Hearts of Iron IV). Read-only."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

GAME_FOLDER = Path("Paradox Interactive") / "Hearts of Iron IV"
LOG_NAME_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}\.log")
TAIL_MAX_BYTES = 2 * 1024 * 1024


def documents_dir() -> Path:
    """The user's Documents folder, honouring folder redirection (e.g. OneDrive) on Windows."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                        ("Data4", ctypes.c_ubyte * 8)]

        # FOLDERID_Documents {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
        folder_id = GUID(0xFDD39AD0, 0x238F, 0x46AF, (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))
        out = ctypes.c_wchar_p()
        shell32 = ctypes.WinDLL("shell32")
        ole32 = ctypes.WinDLL("ole32")
        if shell32.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, None, ctypes.byref(out)) == 0:
            try:
                return Path(out.value)
            finally:
                ole32.CoTaskMemFree(out)
    return Path.home() / "Documents"


def resolve_user_dir(game_data_path: str | None = None) -> Path:
    """User dir from launcher-settings' gameDataPath ("%USER_DOCUMENTS%/...") or the default location."""
    docs = documents_dir()
    if game_data_path and "%USER_DOCUMENTS%" in game_data_path:
        return Path(game_data_path.replace("%USER_DOCUMENTS%", str(docs)))
    return docs / GAME_FOLDER


class UserData:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.logs_dir = root / "logs"

    def exists(self) -> bool:
        return self.root.is_dir()

    def summary(self) -> dict:
        return {
            "path": str(self.root),
            "logs_dir": str(self.logs_dir) if self.logs_dir.is_dir() else None,
            "saves_dir": str(self.root / "save games") if (self.root / "save games").is_dir() else None,
            "last_save": self.last_save(),
        }

    def last_save(self) -> dict | None:
        try:
            data = json.loads((self.root / "continue_game.json").read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return None
        return {"title": data.get("title"), "file": data.get("filename"),
                "date": (data.get("date") or "").strip() or None, "is_remote": data.get("is_remote")}

    def log_names(self) -> list[str]:
        if not self.logs_dir.is_dir():
            return []
        return sorted(p.name for p in self.logs_dir.iterdir() if p.is_file() and LOG_NAME_RE.fullmatch(p.name))

    def log_path(self, name: str) -> Path | None:
        if not LOG_NAME_RE.fullmatch(name or ""):
            return None
        path = self.logs_dir / name
        return path if path.is_file() else None

    def read_text(self, name: str) -> str | None:
        path = self.log_path(name)
        if path is None:
            return None
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def tail(self, name: str, lines: int) -> dict | None:
        path = self.log_path(name)
        if path is None:
            return None
        try:
            stat = path.stat()
            with path.open("rb") as handle:
                start = max(0, stat.st_size - TAIL_MAX_BYTES)
                handle.seek(start)
                chunk = handle.read()
        except OSError:
            return None
        text = chunk.decode("utf-8", errors="replace")
        all_lines = text.splitlines()
        if start > 0 and all_lines:
            all_lines = all_lines[1:]  # first line is probably cut in half
        return {
            "name": name,
            "path": str(path),
            "size": stat.st_size,
            "modified": dt.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            "mtime": stat.st_mtime,
            "lines": all_lines[-lines:] if lines > 0 else all_lines,
            "truncated": start > 0 or len(all_lines) > lines,
        }


def env_user_dir_override() -> Path | None:
    value = os.environ.get("HOI4DBG_GAME_USER_DIR")
    return Path(value) if value else None
