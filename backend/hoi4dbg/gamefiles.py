"""Read-only data from the game installation: country tags (in load order) and their localised names."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

MAX_TAGS = 2000
TAG_LINE = re.compile(r"^\s*([A-Z][A-Z0-9]{2})\s*=", re.M)
NAME_LINE = re.compile(r'^\s*([A-Z][A-Z0-9]{2}(?:_[a-z]+)?):\d*\s*"(.*)"\s*(?:#.*)?$', re.M)
NAME_FILES = ("countries_l_{lang}.yml", "countries_cosmetic_l_{lang}.yml")


def tag_order(install: Path) -> list[str]:
    """Tags in the order the game loads them (files of common/country_tags by name, lines in order)."""
    return list(_tag_order(str(install)))


@lru_cache(maxsize=4)
def _tag_order(install: str) -> tuple[str, ...]:
    tags: list[str] = []
    for path in sorted((Path(install) / "common" / "country_tags").glob("*.txt"), key=lambda p: p.name.lower()):
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
