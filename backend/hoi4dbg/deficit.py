"""Equipment needed by fielded divisions vs. what they hold and the stockpile (estimate from a save).

Game files: common/units/*.txt `sub_units = { <type> = { need = { <archetype> = N } } }` and
common/units/equipment/*.txt `equipments = { <key> = { archetype = <archetype> } }` (archetypes map to themselves).
Save: each division's template (regiments + support) and the equipment it holds; the country stockpile.
missing in divisions = need - held (per archetype, never below 0 per division); shortfall = missing - stockpile.
The game's own deficit view also counts divisions in training and production; this is an estimate.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from .saves import text


def _parse(path: Path) -> list:
    try:
        return text.parse(re.sub(r"#[^\n]*", "", path.read_text(encoding="utf-8-sig", errors="replace")))
    except Exception:  # a broken (mod) file must not break the whole table
        return []


@lru_cache(maxsize=4)
def _load(folders: tuple[str, ...]) -> tuple[dict, dict]:
    needs: dict[str, dict[str, float]] = {}
    archetype: dict[str, str] = {}
    for folder in folders:
        units = Path(folder) / "common" / "units"
        for path in sorted(units.glob("*.txt")):
            for key, value in _parse(path):
                if key == "sub_units" and isinstance(value, list):
                    for unit, body in value:
                        need = text.get(body, "need") if isinstance(body, list) else None
                        if isinstance(need, list):
                            needs[unit] = {k: float(v) for k, v in need if _num(v)}
        for path in sorted((units / "equipment").glob("*.txt")):
            for key, value in _parse(path):
                if key == "equipments" and isinstance(value, list):
                    for eq, body in value:
                        if isinstance(body, list):
                            archetype[eq] = text.get(body, "archetype") or eq
    return needs, archetype


def _num(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def tables(install: Path, mods: list[Path] | None = None) -> tuple[dict, dict]:
    return _load(tuple(str(p) for p in [install] + list(mods or [])))


def archetype_of(key: str, archetypes: dict[str, str]) -> str:
    return archetypes.get(key) or re.sub(r"_\d+$", "", key)


def compute(data: dict, needs: dict, archetypes: dict) -> dict[str, dict]:
    """{archetype: {"need", "held", "missing", "stockpile", "shortfall"}} for archetypes needed or stocked."""
    out: dict[str, dict] = {}

    def row(a: str) -> dict:
        return out.setdefault(a, {"need": 0.0, "held": 0.0, "missing": 0.0, "stockpile": 0.0, "shortfall": 0.0})

    def arch(eq_id: str) -> str:
        return archetype_of((data["variants"].get(eq_id) or {}).get("type") or eq_id, archetypes)

    for div in data.get("divisions") or []:
        need: dict[str, float] = {}
        for unit in data.get("templates", {}).get(str(div["template"]), []):
            for a, n in needs.get(unit, {}).items():
                need[a] = need.get(a, 0) + n
        held: dict[str, float] = {}
        for eq_id, n in div["equipment"].items():
            held[arch(eq_id)] = held.get(arch(eq_id), 0) + n
        for a in set(need) | set(held):
            r = row(a)
            r["need"] += need.get(a, 0)
            r["held"] += held.get(a, 0)
            r["missing"] += max(0.0, need.get(a, 0) - held.get(a, 0))
    for eq_id, n in data["stockpile"].items():
        row(arch(eq_id))["stockpile"] += n
    for r in out.values():
        r["shortfall"] = max(0.0, r["missing"] - r["stockpile"])
    return out
