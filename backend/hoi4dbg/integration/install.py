"""Locating the HOI4 installation and reading its version. Read-only file access."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HOI4_APP_ID = "394360"  # Steam app id (seen in libraryfolders.vdf / appmanifest_394360.acf)
HOI4_EXE = "hoi4.exe"


# --- Valve KeyValues (.vdf / .acf) ------------------------------------------------------
_TOKEN_RE = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])')


def parse_vdf(text: str) -> dict:
    """Minimal parser for Valve's text KeyValues format: "key" "value" and "key" { ... }."""
    root: dict = {}
    stack = [root]
    pending_key: str | None = None
    for match in _TOKEN_RE.finditer(text):
        string, brace = match.groups()
        if brace == "{":
            child: dict = {}
            stack[-1][pending_key if pending_key is not None else ""] = child
            stack.append(child)
            pending_key = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
            pending_key = None
        else:
            value = string.replace("\\\\", "\\").replace('\\"', '"')
            if pending_key is None:
                pending_key = value
            else:
                stack[-1][pending_key] = value
                pending_key = None
    return root


# --- Steam ------------------------------------------------------------------------------
def steam_path_from_registry() -> Path | None:
    if sys.platform != "win32":
        return None
    import winreg

    candidates = [
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
    ]
    for hive, key, value in candidates:
        try:
            with winreg.OpenKey(hive, key) as handle:
                path = Path(winreg.QueryValueEx(handle, value)[0])
        except OSError:
            continue
        if path.is_dir():
            return path
    return None


def steam_libraries(steam_path: Path) -> list[Path]:
    libraries = [steam_path]
    vdf = steam_path / "steamapps" / "libraryfolders.vdf"
    try:
        data = parse_vdf(vdf.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return libraries
    for entry in (data.get("libraryfolders") or data.get("LibraryFolders") or {}).values():
        raw = entry.get("path") if isinstance(entry, dict) else entry  # new vs. old file format
        if isinstance(raw, str) and raw:
            path = Path(raw)
            if path not in libraries:
                libraries.append(path)
    return libraries


def find_install_dir(libraries: list[Path]) -> tuple[Path, dict] | None:
    """Returns (install dir, appmanifest dict) for the first library that has HOI4 installed."""
    for library in libraries:
        steamapps = library / "steamapps"
        manifest_file = steamapps / f"appmanifest_{HOI4_APP_ID}.acf"
        manifest: dict = {}
        if manifest_file.is_file():
            manifest = parse_vdf(manifest_file.read_text(encoding="utf-8", errors="replace")).get("AppState", {})
        install_dir = steamapps / "common" / manifest.get("installdir", "Hearts of Iron IV")
        if (install_dir / HOI4_EXE).is_file():
            return install_dir, manifest
    return None


# --- Version ----------------------------------------------------------------------------
def read_version(install_dir: Path) -> dict | None:
    """Version as declared by the game's own launcher-settings.json."""
    try:
        data = json.loads((install_dir / "launcher-settings.json").read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    display = data.get("version")
    raw = data.get("rawVersion")
    suffix = None
    if display and raw:
        match = re.search(re.escape(raw) + r"\.([0-9a-fA-F]+)\b", display)
        suffix = match.group(1) if match else None
    return {"display": display, "raw": raw, "build_suffix": suffix,
            "game_data_path": data.get("gameDataPath"), "source": "launcher-settings.json"}


def read_install_revision(install_dir: Path) -> str | None:
    try:
        text = (install_dir / "hoi4_rev.txt").read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    return text if re.fullmatch(r"[0-9a-f]{7,64}", text) else None


def parse_code_revisions(text: str) -> dict:
    """Parses logs/code_revisions.log ("key: value" lines) written by the game at startup."""
    result = {}
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            result[key.strip()] = value.strip()
    return result
