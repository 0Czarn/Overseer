"""Country values from BINARY saves (HOI4bin), using a token map verified for one game version.

Evidence (2026-10-09, 1.19.3): a text save and a binary save of the same paused game
(`11.hoi4` / `2-1.hoi4`, differing only by one `manpower 10000`) were walked side by side:
- all 82 top-level keys align 1:1 (no conflicts); country tags are quoted strings;
- inside GER, token ids map to the field names below;
- value types: 0x000d (8 B) = int64 / 100000 (26 635 of 26 688 samples equal; the rest are
  dynamic values that differ between the two moments, e.g. resources.produced 153 vs 131),
  0x0167 = int64 / 32768 (1 696 / 1 696; text saves truncate it to 5 decimals),
  0x0317 = int64 (1 / 1).
Other game versions are refused (token ids are not guaranteed to be stable across versions).
"""

from __future__ import annotations

import re
import struct

from . import binary, text

VERIFIED_VERSION = re.compile(r"v1\.19\.3\b")

# field name -> token id (1.19.3)
TOKENS = {
    "countries": 0x2D49, "politics": 0x2FFA, "political_power": 0x301E, "stability": 0x2883,
    "war_support": 0x37FD, "command_power": 0x3883, "fuel_status": 0x3B10, "fuel": 0x2EE3,
    "experience_status": 0x418D, "army_experience": 0x3392, "air_experience": 0x3394,
    "navy_experience": 0x3393, "manpower": 0x283C, "current": 0x2B75,
}
NAMES = {v: k for k, v in TOKENS.items()}


def decode(value: binary.Raw) -> str:
    raw = struct.unpack("<q", value.data)[0] if len(value.data) == 8 else None
    if raw is None:
        return value.data.hex()
    if value.type == binary.F32:
        return repr(raw / 100000)
    if value.type == binary.F64:
        return repr(raw / 32768)
    if value.type == binary.I64:
        return str(raw)
    return value.data.hex()


def _named(items: list) -> list:
    """Binary block -> the shape text.parse() produces (names for known tokens, decoded numbers)."""
    out = []
    for item in items:
        if isinstance(item, tuple):
            key, val = item
            out.append((_scalar(key), _named(val) if isinstance(val, list) else _scalar(val)))
        else:
            out.append(_named(item) if isinstance(item, list) else _scalar(item))
    return out


def _scalar(v):
    if isinstance(v, binary.Token):
        return NAMES.get(v.id, repr(v))
    if isinstance(v, binary.Raw):
        return decode(v)
    if isinstance(v, bool):
        return "yes" if v else "no"
    return str(v)


def country_block(data: bytes, tag: str, float_width: int, version: str | None) -> list | None:
    if not re.fullmatch(r"[A-Z][A-Z0-9]{2}", tag or ""):
        raise ValueError(f"Invalid country tag: {tag!r}")
    return country_blocks(data, {tag}, float_width, version).get(tag)


def country_blocks(data: bytes, tags: set[str], float_width: int, version: str | None) -> dict[str, list]:
    """Named blocks of the wanted countries, in one pass over the save."""
    if not VERIFIED_VERSION.search(version or ""):
        raise binary.SaveFormatError("binary_values_unmapped", f"Binary country values are only mapped for 1.19.3 "
                                     f"(this save: {version or 'unknown'}). Use a text save (-force_text_save).")
    if float_width != 8:
        raise binary.SaveFormatError("binary_values_unmapped", "Unexpected value width in this binary save")
    out: dict[str, list] = {}
    p = binary.Parser(data, float_width)
    while p.peek() is not None:
        key = p._u16()
        if p._u16() != binary.EQUALS:
            raise binary.SaveFormatError("corrupt", "Expected '=' after a top-level field", p.pos - 2)
        if key != TOKENS["countries"]:
            p.skip_value()
            continue
        if p._u16() != binary.OPEN:
            raise binary.SaveFormatError("corrupt", "'countries' is not a block", p.pos - 2)
        while p.peek() not in (None, binary.CLOSE) and len(out) < len(tags):
            name = p.scalar(p._u16())
            if p._u16() != binary.EQUALS:
                raise binary.SaveFormatError("corrupt", "Expected '=' after a country tag", p.pos - 2)
            if name in tags:
                if p._u16() != binary.OPEN:
                    raise binary.SaveFormatError("corrupt", f"Country {name} is not a block", p.pos - 2)
                out[name] = _named(p.block([50_000_000]))
            else:
                p.skip_value()
        return out
    raise binary.SaveFormatError("unsupported", "No 'countries' block in this binary save")


def country_values(data: bytes, tag: str, float_width: int, version: str | None) -> dict | None:
    block = country_block(data, tag, float_width, version)
    if block is None:
        return None
    values = text.country_values(block, {})
    for entry in values.values():
        if entry.get("status") == "read":
            entry["source"] = "binary token map 1.19.3"
    return values
