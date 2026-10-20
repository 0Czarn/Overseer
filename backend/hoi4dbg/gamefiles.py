"""Read-only data from the game installation: country tags (in load order) and their localised names."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

MAX_TAGS = 2000
TAG_LINE = re.compile(r"^\s*([A-Z][A-Z0-9]{2})\s*=", re.M)
NAME_LINE = re.compile(r'^\s*([A-Z][A-Z0-9]{2}(?:_[a-z]+)?):\d*\s*"(.*)"\s*(?:#.*)?$', re.M)
NAME_FILES = ("countries_l_{lang}.yml", "countries_cosmetic_l_{lang}.yml")


def tag_order(install: Path, mods=()) -> list[str]:
    """Tags in the order the game loads them (files of common/country_tags by name, lines in order) - with the mods
    the game runs with: a mod's 00_countries.txt replaces the game's (2026-10-20, TFB: other order, 140 tags; with
    the game's order SOV's slot was read as another country)."""
    return list(_tag_order(str(install), tuple(map(str, mods))))


@lru_cache(maxsize=4)
def _tag_order(install: str, mods: tuple[str, ...] = ()) -> tuple[str, ...]:
    tags: list[str] = []
    for path in merged_files([install, *mods], "common/country_tags"):
        text = re.sub(r"#[^\n]*", "", path.read_text(encoding="utf-8-sig", errors="replace"))
        tags += [t for t in TAG_LINE.findall(text) if t not in tags]
    return tuple(tags[:MAX_TAGS])


def country_names(install: Path, lang: str = "english") -> dict[str, str]:
    """Localised names: TAG -> base name, TAG_ideology -> name under that ruling party (GER_fascism -> German Reich)."""
    return dict(_country_names(str(install), lang))


@lru_cache(maxsize=4)
def _country_names(install: str, lang: str) -> tuple[tuple[str, str], ...]:
    names: dict[str, str] = {}
    folder = Path(install) / "localisation" / lang
    for pattern in NAME_FILES:
        path = folder / pattern.format(lang=lang)
        if path.is_file():
            for tag, name in NAME_LINE.findall(path.read_text(encoding="utf-8-sig", errors="replace")):
                names.setdefault(tag, name)
    return tuple(names.items())


STATE_ID = re.compile(r"\bid\s*=\s*(\d+)")
STATE_NAME = re.compile(r'\bname\s*=\s*"([^"]+)"')
STATE_PROVINCES = re.compile(r"\bprovinces\s*=\s*\{([^}]*)\}")
STATE_NAME_LINE = re.compile(r'^\s*(STATE_\d+):\d*\s*"(.*)"', re.M)


def state_definitions(install: Path) -> dict[int, dict]:
    """State id -> {"name_key", "provinces"} from history/states/*.txt."""
    return dict(_state_definitions(str(install)))


@lru_cache(maxsize=2)
def _state_definitions(install: str) -> tuple:
    out = {}
    for path in sorted((Path(install) / "history" / "states").glob("*.txt")):
        text = re.sub(r"#[^\n]*", "", path.read_text(encoding="utf-8-sig", errors="replace"))
        sid, name, provs = STATE_ID.search(text), STATE_NAME.search(text), STATE_PROVINCES.search(text)
        if sid:
            out[int(sid.group(1))] = {"name_key": name.group(1) if name else None,
                                     "provinces": [int(x) for x in provs.group(1).split() if x.isdigit()] if provs else []}
    return tuple(out.items())


def state_names(install: Path, lang: str = "english") -> dict[str, str]:
    path = Path(install) / "localisation" / lang / f"state_names_l_{lang}.yml"
    if not path.is_file():
        return {}
    return dict(STATE_NAME_LINE.findall(path.read_text(encoding="utf-8-sig", errors="replace")))


EQUIPMENT_NAME_LINE = re.compile(r'^\s*([a-z][a-z0-9_]*):\d*\s*"(.*)"', re.M)


def equipment_names(install: Path, lang: str = "english") -> dict[str, str]:
    """Equipment archetype key -> localised name (infantry_equipment_1 -> Infantry Equipment I)."""
    return dict(_equipment_names(str(install), lang))


@lru_cache(maxsize=2)
def _equipment_names(install: str, lang: str) -> tuple:
    path = Path(install) / "localisation" / lang / f"equipment_l_{lang}.yml"
    if not path.is_file():
        return ()
    return tuple(EQUIPMENT_NAME_LINE.findall(path.read_text(encoding="utf-8-sig", errors="replace")))


ACTIVE_MOD_LINE = re.compile(r"\]: Active Mod: (.*?)\s*$", re.M)


def enabled_mods(userdata: Path) -> list[Path]:
    """Folders of the mods the game runs with, in load order (descriptor *.mod -> path=...). The game's own list
    comes first: logs/system.log of the last start ("Active Mod Count: N", "Active Mod: <name>"); dlc_load.json (the
    launcher's playset, written before the start) gives the order, and is the list when the log has none. 2026-10-20:
    the user played with the TFB playset while the app read another one."""
    userdata = Path(userdata)
    key = []
    for f in (userdata / "dlc_load.json", userdata / "logs" / "system.log", userdata / "mod"):
        try:
            key.append(f.stat().st_mtime_ns)
        except OSError:
            key.append(None)
    return list(_enabled_mods(str(userdata), tuple(key)))


@lru_cache(maxsize=4)
def _enabled_mods(userdata: str, _mtimes: tuple) -> tuple[Path, ...]:
    import json
    userdata = Path(userdata)
    try:
        enabled = json.loads((userdata / "dlc_load.json").read_text(encoding="utf-8")).get("enabled_mods") or []
    except (OSError, ValueError):
        enabled = []
    try:
        log = (userdata / "logs" / "system.log").read_text(encoding="utf-8", errors="replace")
    except OSError:
        log = ""
    descriptors = {}
    for rel in list(enabled) + sorted(f"mod/{p.name}" for p in (userdata / "mod").glob("*.mod")):
        if rel in descriptors:
            continue
        try:
            descriptors[rel] = (userdata / rel).read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
    if "Active Mod Count:" in log:
        active = [n.strip() for n in ACTIVE_MOD_LINE.findall(log)]
        name_of = {rel: (re.search(r'^\s*name\s*=\s*"([^"]*)"', d, re.M) or [None, ""])[1].strip()
                   for rel, d in descriptors.items()}
        chosen = [rel for rel in enabled if name_of.get(rel) in active]
        for name in active:   # mods not in the launcher's list (another playset): any descriptor of that name
            if not any(name_of.get(rel) == name for rel in chosen):
                chosen += [rel for rel in descriptors if name_of[rel] == name][:1]
    else:
        chosen = [rel for rel in enabled if rel in descriptors]
    out = []
    for rel in chosen:
        m = re.search(r'^\s*path\s*=\s*"([^"]+)"', descriptors[rel], re.M)
        if m and Path(m.group(1)).is_dir():
            out.append(Path(m.group(1)))
    return tuple(out)


def replaced_paths(mod: Path) -> list[str]:
    """`replace_path` folders of a mod (its descriptor.mod): the game ignores those folders of everything loaded
    before the mod."""
    try:
        descriptor = (Path(mod) / "descriptor.mod").read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []
    found = re.findall(r'^\s*replace_path\s*=\s*"([^"]+)"', descriptor, re.M)
    return [p.replace("\\", "/").strip("/").lower() for p in found]


def merged_files(roots, folder: str, pattern: str = "*.txt") -> list[Path]:
    """Files of `folder` (e.g. common/national_focus) as the game loads them: a later root's file with the same name
    replaces the earlier one, a mod's replace_path drops the folder of the roots before it; sorted by name."""
    files: dict[str, Path] = {}
    for i, root in enumerate(roots):
        root = Path(root)
        if i and folder.lower() in replaced_paths(root):
            files = {}
        for path in (root / folder).glob(pattern):
            files[path.name.lower()] = path
    return [files[k] for k in sorted(files)]
