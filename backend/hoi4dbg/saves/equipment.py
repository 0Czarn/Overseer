"""Equipment of a save: the variant table and each country's stockpile and convoys.

Save layout (1.19.3; binary tokens from aligning the text/binary pair 11.hoi4 / 2-1.hoi4):
- top-level `equipments` (0x2f5a): archetype key -> {id={id (0x000b) type (0x00e1)}, name (0x001b) for named
  variants, creator (0x306d), obsolete (0x306c)}; the key repeats, the numeric id is unique;
- country `production` (0x2fb4) -> `equipments` -> `equipment` (0x2f4e) {id={id type}, amount (0x01a1)} = stockpile;
- country `convoys` (0x3062) -> `equipment` -> `equipment` entries, same shape.
"""

from __future__ import annotations

from . import binary, binvalues, countries, text
from .states import _normalise as _states_normalise
from .states import NAMES as STATE_NAMES

T = {"equipments": 0x2F5A, "production": 0x2FB4, "equipment": 0x2F4E, "id": 0x000B, "type": 0x00E1,
     "amount": 0x01A1, "convoys": 0x3062, "name": 0x001B, "creator": 0x306D, "obsolete": 0x306C}
for _name, _tok in T.items():
    STATE_NAMES.setdefault(_tok, _name)


def _entries(block) -> dict[str, float]:
    """`equipment` entries of a stockpile block -> {equipment id: amount}."""
    out: dict[str, float] = {}
    for item in block if isinstance(block, list) else []:
        if isinstance(item, tuple) and item[0] == "equipment" and isinstance(item[1], list):
            eq_id = text.get(item[1], "id", "id")
            try:
                amount = float(text.get(item[1], "amount"))
            except (TypeError, ValueError):
                continue
            if eq_id is not None:
                out[str(eq_id)] = out.get(str(eq_id), 0) + amount
    return out


def _variants(items: list) -> dict[str, dict]:
    out = {}
    for item in items:
        if isinstance(item, tuple) and isinstance(item[1], list):
            eq_id = text.get(item[1], "id", "id")
            if eq_id is not None:
                out[str(eq_id)] = {"type": str(item[0]), "name": text.get(item[1], "name"),
                                   "creator": text.get(item[1], "creator"),
                                   "obsolete": text.get(item[1], "obsolete") == "yes"}
    return out


def _country(block: list) -> dict:
    return {"stockpile": _entries(text.get(block, "production", "equipments")),
            "convoys": _entries(text.get(block, "convoys", "equipment"))}


def read(data: bytes, fmt: str, float_width: int | None, version: str | None, tag: str) -> dict:
    """{"variants": {id: {...}}, "stockpile": {id: amount}, "convoys": {id: amount}} for one country."""
    if fmt == "text":
        section = countries._section(data, b"equipments")
        variants = _variants(text.parse(section.decode("utf-8", "replace"))[0][1]) if section else {}
        block = text.country_block(data, tag)
        if block is None:
            raise binary.SaveFormatError("country_missing", f"Country {tag} does not exist in this save")
        return {"variants": variants, **_country(block)}
    if not binvalues.VERIFIED_VERSION.search(version or "") or float_width != 8:
        raise binary.SaveFormatError("binary_values_unmapped", f"Binary equipment is only mapped for 1.19.3 "
                                     f"(this save: {version or 'unknown'}). Use a text save (-force_text_save).")
    p = binary.Parser(data, float_width)
    variants, country = {}, None
    while p.peek() is not None:
        key = p._u16()
        if p._u16() != binary.EQUALS:
            raise binary.SaveFormatError("corrupt", "Expected '=' after a top-level field", p.pos - 2)
        if key == T["equipments"] and p.peek() == binary.OPEN:
            p._u16()
            variants = _variants(_states_normalise(p.block([200_000_000])))
        elif key == binvalues.TOKENS["countries"] and p.peek() == binary.OPEN:
            p._u16()
            while p.peek() not in (None, binary.CLOSE):
                name = p.scalar(p._u16())
                p._u16()
                if name == tag and p.peek() == binary.OPEN:
                    p._u16()
                    country = _country(_states_normalise(p.block([50_000_000])))
                else:
                    p.skip_value()
            p._u16()
        else:
            p.skip_value()
    if country is None:
        raise binary.SaveFormatError("country_missing", f"Country {tag} does not exist in this save")
    return {"variants": variants, **country}


def rows(data: dict, names: dict[str, str]) -> list[dict]:
    """Stockpile rows with archetype names from the game localisation and variant names from the save."""
    out = []
    for kind, amounts in (("stockpile", data["stockpile"]), ("convoys", data["convoys"])):
        for eq_id, amount in amounts.items():
            v = data["variants"].get(eq_id) or {}
            archetype = v.get("type") or f"#{eq_id}"
            out.append({"id": eq_id, "archetype": archetype, "archetype_name": names.get(archetype, archetype),
                        "variant": v.get("name"), "creator": v.get("creator"), "obsolete": v.get("obsolete", False),
                        "amount": amount, "pool": kind})
    return sorted(out, key=lambda r: (r["pool"] != "stockpile", r["archetype_name"], r["variant"] or ""))
