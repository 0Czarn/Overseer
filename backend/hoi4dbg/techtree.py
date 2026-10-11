"""Research screen tabs ("technology folders") from the game files and enabled mods.

common/technology_tags/*.txt: technology_folders = { infantry_folder = { ledger = army available = { has_dlc = .. } }
... } - the order in the file is the order of the tabs. A folder is shown when its `available` trigger holds; the
triggers of the game (1.19.3) only use has_dlc with NOT / OR / AND. Owned DLCs = the game's dlc/*/*.dlc files
(name = "No Step Back") minus the ones disabled in the launcher (dlc_load.json "disabled_dlcs"). Doctrine folders
(doctrine = yes) have their own screen since 1.19 and `ledger = hidden` ones are not shown, so both are left out.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from .saves import text

LEDGER_ORDER = ("army", "navy", "air", "civilian")


def _parse(path: Path) -> list:
    try:
        return text.parse(re.sub(r"#[^\n]*", "", path.read_text(encoding="utf-8-sig", errors="replace")))
    except Exception:
        return []


def owned_dlcs(install: Path, userdata: Path | None) -> set[str]:
    """Names of the installed and enabled DLCs ("Man the Guns", ...)."""
    names: set[str] = set()
    for path in (install / "dlc").glob("*/*.dlc"):
        found = re.search(r'^\s*name\s*=\s*"([^"]+)"', path.read_text(encoding="utf-8", errors="replace"), re.M)
        if found:
            names.add(found.group(1))
    disabled: set[str] = set()
    try:
        load = json.loads((userdata / "dlc_load.json").read_text(encoding="utf-8")) if userdata else {}
        disabled = {Path(d).stem for d in load.get("disabled_dlcs", [])}
    except (OSError, ValueError):
        pass
    if disabled:   # entries are dlc/<folder>/<file>.dlc paths: drop the names of those files
        for path in (install / "dlc").glob("*/*.dlc"):
            if path.stem in disabled:
                found = re.search(r'^\s*name\s*=\s*"([^"]+)"', path.read_text(encoding="utf-8", errors="replace"), re.M)
                if found:
                    names.discard(found.group(1))
    return names


def trigger(block, dlcs: set[str]) -> bool | None:
    """Value of an `available` trigger (AND of its entries); None when it uses anything but has_dlc / NOT / OR /
    AND / always."""
    if not isinstance(block, list):
        return None
    results = []
    for key, value in (e for e in block if isinstance(e, tuple)):
        k = key.lower()
        if k == "has_dlc":
            results.append(value in dlcs)
        elif k == "always":
            results.append(value == "yes")
        elif k in ("not", "or", "and"):
            inner = [trigger([e], dlcs) for e in value if isinstance(e, tuple)] if isinstance(value, list) else [None]
            if None in inner:
                return None
            results.append(not all(inner) if k == "not" else any(inner) if k == "or" else all(inner))
        else:
            return None
    return all(results)


@lru_cache(maxsize=4)
def folders(roots: tuple[str, ...]) -> list[dict]:
    """[{"id", "ledger", "doctrine", "available": trigger block or None}] in file order; later roots override."""
    out: dict[str, dict] = {}
    for root in map(Path, roots):
        for path in sorted((root / "common" / "technology_tags").glob("*.txt")):
            for key, block in (e for e in _parse(path) if isinstance(e, tuple)):
                if key != "technology_folders" or not isinstance(block, list):
                    continue
                for fid, body in (e for e in block if isinstance(e, tuple)):
                    if isinstance(body, list):
                        out[fid] = {"id": fid, "ledger": text.get(body, "ledger"),
                                    "doctrine": text.get(body, "doctrine") == "yes",
                                    "available": text.get(body, "available")}
    return list(out.values())


# a buttonType block with one level of nested braces (position = { x = 22 y = 0 })
TAB_BUTTON = re.compile(r"buttonType\s*=\s*\{((?:[^{}]|\{[^{}]*\})*)\}", re.S)
TAB_NAME = re.compile(r'\bname\s*=\s*"?(\w+?)_tab"?')
TAB_SPRITE = re.compile(r'quadTextureSprite\s*=\s*"?(\w+)"?')
TAB_X = re.compile(r"position\s*=\s*\{\s*x\s*=\s*(-?\d+)")


@lru_cache(maxsize=4)
def tab_buttons(roots: tuple[str, ...]) -> dict[str, dict]:
    """{folder id: {"sprite", "x"}} of the tab buttons in interface/*.gui (countrytechtreeview.gui: buttonType
    name = "infantry_folder_tab" position = { x = 22 y = 0 } quadTextureSprite = "GFX_infantry_folder_tab"); the
    game orders the tabs by x (22 infantry ... 378 naval, 556 air, 645 engineering, 734 industry). Later roots
    override. The sprites are 2 frames side by side: selected (raised), normal - techtree_infantry_tab.dds is 182 x 61."""
    out: dict[str, dict] = {}
    for root in map(Path, roots):
        for path in sorted((root / "interface").glob("*.gui")):
            try:
                src = path.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                continue
            if "_tab" not in src:
                continue
            for block in TAB_BUTTON.findall(re.sub(r"#[^\n]*", "", src)):
                name, sprite = TAB_NAME.search(block), TAB_SPRITE.search(block)
                if name and sprite:
                    x = TAB_X.search(block)
                    out[name.group(1)] = {"sprite": sprite.group(1), "x": int(x.group(1)) if x else None}
    return out


def research_tabs(roots: tuple[str, ...], dlcs: set[str], tech_counts: dict[str, int]) -> list[dict]:
    """Tabs of the research screen: [{"id", "ledger", "technologies", "condition"}] where condition is "always",
    "dlc" (decided by the owned DLCs) or "unknown" (a mod trigger the app cannot evaluate - shown anyway)."""
    tabs = []
    for f in folders(roots):
        if f["doctrine"] or f["ledger"] == "hidden":
            continue
        held = True if f["available"] is None else trigger(f["available"], dlcs)
        if held is False:
            continue
        tabs.append({"id": f["id"], "ledger": f["ledger"], "technologies": tech_counts.get(f["id"], 0),
                     "condition": "always" if f["available"] is None else "dlc" if held else "unknown",
                     "sprite": (tab_buttons(roots).get(f["id"]) or {}).get("sprite"),
                     "x": (tab_buttons(roots).get(f["id"]) or {}).get("x")})
    # the game's left-to-right order; tabs without a known button (mods) keep the file order at the end
    return sorted(tabs, key=lambda t: (t["x"] is None, t["x"] or 0))
