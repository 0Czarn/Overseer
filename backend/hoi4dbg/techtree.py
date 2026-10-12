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


# ---- tree layout of one tab (interface/countrytechtreeview.gui, 1.19.3) ----
# A folder is a containerWindowType named like the folder (infantry_folder). Inside it every branch has a gridbox
# "<root technology>_tree" with a pixel position, a slot size (70 x 70) and a format: "LEFT" = the branch grows to
# the right (a technology's y from common/technologies is the column, x the row; infantry: y = @1936), "UP" /
# "UPPER_LEFT" = x column, y row. Nested containers add their positions. The items are the templates
# techtree_<folder>_item (big, 183 x 84 at -56/-7 of the slot) and techtree_<folder>_small_item (72 x 72).

def _num(v) -> float:
    try:
        return float(str(v).replace("%", ""))
    except (TypeError, ValueError):
        return 0.0


def _xy(block) -> tuple[float, float]:
    pos = text.get(block, "position") if isinstance(block, list) else None
    return (_num(text.get(pos, "x")), _num(text.get(pos, "y"))) if isinstance(pos, list) else (0.0, 0.0)


@lru_cache(maxsize=4)
def _gui(roots: tuple[str, ...]) -> dict[str, list]:
    """{window name: block} of every top-level and nested window of interface/*.gui (later roots override)."""
    named: dict[str, list] = {}

    def walk(block):
        for e in block:
            if isinstance(e, tuple) and isinstance(e[1], list):
                name = text.get(e[1], "name")
                if isinstance(name, str) and e[0].lower() in ("containerwindowtype", "windowtype"):
                    named[name] = e[1]
                walk(e[1])
    for root in map(Path, roots):
        for path in sorted((root / "interface").glob("*.gui")):
            try:
                src = path.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                continue
            if "gridbox" not in src.lower() and "techtree_" not in src:
                continue
            try:
                walk(text.parse(re.sub(r"#[^\n]*", "", src).replace("%%", "")))
            except Exception:
                continue
    return named


def folder_layout(roots: tuple[str, ...], folder: str) -> dict | None:
    """{"grids": {name: {x, y, w, h, format}}, "labels": [{text, x, y, size}], "big": {dx, dy, w, h},
    "small": {...}} of a research tab, or None when the game has no window for it."""
    windows = _gui(roots)
    win = windows.get(folder)
    if win is None:
        return None
    grids, labels = {}, []

    def walk(block, ox, oy):
        for key, value in (e for e in block if isinstance(e, tuple)):
            if not isinstance(value, list):
                continue
            k = key.lower()
            x, y = _xy(value)
            if k == "gridboxtype":
                slot = text.get(value, "slotsize") or []
                grids[text.get(value, "name")] = {"x": ox + x, "y": oy + y, "w": _num(text.get(slot, "width")) or 70,
                                                   "h": _num(text.get(slot, "height")) or 70,
                                                   "format": str(text.get(value, "format") or "UP").upper()}
            elif k == "instanttextboxtype" and isinstance(text.get(value, "text"), str) and text.get(value, "text"):
                font = str(text.get(value, "font") or "")
                size = re.search(r"(\d+)", font)
                labels.append({"text": text.get(value, "text"), "x": ox + x, "y": oy + y,
                               "size": int(size.group(1)) if size else 16})
            elif k in ("containerwindowtype", "windowtype"):
                walk(value, ox + x, oy + y)
    walk(win, 0.0, 0.0)

    def item(name, default):
        t = windows.get(name)
        if t is None:
            return default
        x, y = _xy(t)
        size = text.get(t, "size") or []
        return {"dx": x, "dy": y, "w": _num(text.get(size, "width")) or default["w"],
                "h": _num(text.get(size, "height")) or default["h"]}
    return {"grids": grids, "labels": labels,
            "big": item(f"techtree_{folder}_item", {"dx": -56, "dy": -7, "w": 183, "h": 84}),
            "small": item(f"techtree_{folder}_small_item", {"dx": 0, "dy": 0, "w": 72, "h": 72})}


def place(position: tuple[float, float], grid: dict) -> tuple[float, float]:
    """Pixel position of a technology slot in its branch gridbox."""
    px, py = position
    if grid["format"] == "LEFT":
        return grid["x"] + py * grid["w"], grid["y"] + px * grid["h"]
    return grid["x"] + px * grid["w"], grid["y"] + py * grid["h"]


def branch_grid(tech: str, techs: dict, folder: str, grids: dict) -> dict | None:
    """Gridbox of the branch of `tech`: "<tech>_tree", else the one of a predecessor in the same tab."""
    seen, todo = set(), [tech]
    while todo:
        t = todo.pop(0)
        if t in seen:
            continue
        seen.add(t)
        if f"{t}_tree" in grids:
            return grids[f"{t}_tree"]
        todo += [p for p in techs.get(t, {}).get("parents", []) if folder in (techs.get(p, {}).get("positions") or {})]
    return None


# ---- lines between technologies that do not run through other items ----
# Every line is an orthogonal polyline from the side of the parent that faces the child to the facing side of the
# child. Candidates: 3 segments with the middle one in a free channel, or 5 segments (out into a channel, along a
# channel, back towards the child). Cost: running through another item (huge), crossing / running along a line of
# another parent, length. Lines of one parent may share their first part (a trunk, as in the game).
MARGIN = 3


def _box_hit(seg, box) -> bool:
    (x1, y1), (x2, y2) = seg
    left, top, right, bottom = box["x"] + MARGIN, box["y"] + MARGIN, box["x"] + box["w"] - MARGIN, box["y"] + box["h"] - MARGIN
    if x1 == x2:
        return left < x1 < right and min(y1, y2) < bottom and max(y1, y2) > top
    return top < y1 < bottom and min(x1, x2) < right and max(x1, x2) > left


def _segments(points):
    return [(points[i], points[i + 1]) for i in range(len(points) - 1)
            if points[i] != points[i + 1]]


def _seg_cost(a, b) -> float:
    """Crossing (10) or running along the same channel (length) of two axis-aligned segments."""
    (ax1, ay1), (ax2, ay2) = a
    (bx1, by1), (bx2, by2) = b
    a_vertical, b_vertical = ax1 == ax2, bx1 == bx2
    if a_vertical == b_vertical:
        if a_vertical and abs(ax1 - bx1) < 4:
            overlap = min(max(ay1, ay2), max(by1, by2)) - max(min(ay1, ay2), min(by1, by2))
            return max(0.0, overlap)
        if not a_vertical and abs(ay1 - by1) < 4:
            overlap = min(max(ax1, ax2), max(bx1, bx2)) - max(min(ax1, ax2), min(bx1, bx2))
            return max(0.0, overlap)
        return 0.0
    v, hz = (a, b) if a_vertical else (b, a)
    vx, (vy1, vy2) = v[0][0], sorted((v[0][1], v[1][1]))
    hy, (hx1, hx2) = hz[0][1], sorted((hz[0][0], hz[1][0]))
    return 10.0 if hx1 < vx < hx2 and vy1 < hy < vy2 else 0.0


def _candidates(a: dict, b: dict, xs: list[float], ys: list[float]):
    acx, acy, bcx, bcy = a["x"] + a["w"] / 2, a["y"] + a["h"] / 2, b["x"] + b["w"] / 2, b["y"] + b["h"] / 2
    horizontal = abs(bcx - acx) >= abs(bcy - acy)
    if horizontal:
        sx = a["x"] + a["w"] if bcx > acx else a["x"]
        ex = b["x"] if bcx > acx else b["x"] + b["w"]
        start, end = (sx, acy), (ex, bcy)
        lo, hi = sorted((sx, ex))
        if abs(acy - bcy) < 1:
            yield [start, end]
        for x in [x for x in xs if lo <= x <= hi]:
            yield [start, (x, acy), (x, bcy), end]
        for x1 in [x for x in xs if lo <= x <= hi][:12]:
            for y in ys:
                for x2 in [x for x in xs if lo <= x <= hi and (x >= x1 if ex >= sx else x <= x1)][-12:]:
                    yield [start, (x1, acy), (x1, y), (x2, y), (x2, bcy), end]
    else:
        sy = a["y"] + a["h"] if bcy > acy else a["y"]
        ey = b["y"] if bcy > acy else b["y"] + b["h"]
        start, end = (acx, sy), (bcx, ey)
        lo, hi = sorted((sy, ey))
        if abs(acx - bcx) < 1:
            yield [start, end]
        for y in [y for y in ys if lo <= y <= hi]:
            yield [start, (acx, y), (bcx, y), end]
        for y1 in [y for y in ys if lo <= y <= hi][:12]:
            for x in xs:
                for y2 in [y for y in ys if lo <= y <= hi and (y >= y1 if ey >= sy else y <= y1)][-12:]:
                    yield [start, (acx, y1), (x, y1), (x, y2), (bcx, y2), end]


def route_lines(items: list[dict], lines: list[dict]) -> list[list[tuple[float, float]]]:
    """Polyline (points) for every line {"from", "to"} between items {"id", "x", "y", "w", "h"}."""
    by_id = {i["id"]: i for i in items}
    # free channels: just outside every item and half way between neighbours
    xs = sorted({round(v, 1) for i in items for v in (i["x"] - 7, i["x"] + i["w"] + 7)})
    ys = sorted({round(v, 1) for i in items for v in (i["y"] - 7, i["y"] + i["h"] + 7)})
    xs = [x for x in xs if not any(_box_hit(((x, -1e6), (x, 1e6)), {**i, "y": i["y"], "h": 0}) for i in [])] or xs
    placed: list[tuple[str, tuple]] = []   # (parent id, segment)
    out = []
    # short lines first: they have the fewest ways around
    order = sorted(range(len(lines)), key=lambda k: abs(by_id[lines[k]["from"]]["x"] - by_id[lines[k]["to"]]["x"])
                   + abs(by_id[lines[k]["from"]]["y"] - by_id[lines[k]["to"]]["y"]))
    result: dict[int, list] = {}
    for k in order:
        line = lines[k]
        a, b = by_id[line["from"]], by_id[line["to"]]
        others = [i for i in items if i["id"] not in (a["id"], b["id"])]
        best, best_cost = None, None
        for points in _candidates(a, b, xs, ys):
            segs = _segments(points)
            cost = 0.0
            for seg in segs:
                if any(_box_hit(seg, i) for i in others):
                    cost += 100000
                cost += sum(_seg_cost(seg, other) for parent, other in placed if parent != line["from"])
                cost += (abs(seg[0][0] - seg[1][0]) + abs(seg[0][1] - seg[1][1])) * 0.01
            cost += len(segs) * 2
            if best_cost is None or cost < best_cost:
                best, best_cost = points, cost
                if cost < 1e-9:
                    break
        best = best or [(a["x"] + a["w"] / 2, a["y"] + a["h"] / 2), (b["x"] + b["w"] / 2, b["y"] + b["h"] / 2)]
        placed += [(line["from"], seg) for seg in _segments(best)]
        result[k] = best
    for k in range(len(lines)):
        out.append(result[k])
    return out


def line_report(items: list[dict], lines: list[dict], routes: list[list]) -> dict:
    """{"through_items", "crossings"}: lines running through other items / crossings of lines of different parents."""
    by_id = {i["id"]: i for i in items}
    through, crossings = 0, 0
    segs = []
    for line, points in zip(lines, routes):
        others = [i for i in items if i["id"] not in (line["from"], line["to"])]
        for seg in _segments(points):
            if any(_box_hit(seg, i) for i in others):
                through += 1
            segs.append((line["from"], seg))
    for n, (pa, a) in enumerate(segs):
        for pb, b in segs[n + 1:]:
            if pa != pb and _seg_cost(a, b) == 10.0:
                crossings += 1
    return {"through_items": through, "crossings": crossings, "lines": len(lines)}
