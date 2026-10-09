"""Reader for text saves ("HOI4txt", written when the game runs with -force_text_save).

Field names and locations below were confirmed on a real 1.19.3 text save
(PROJEKT-OVERSEER.hoi4, 2026-10-09). See docs/SAVE-FORMAT.md section 8.
Only the parts we need are parsed (header and single country blocks), not the whole 60 MB file.
"""

from __future__ import annotations

import re

from .binary import SaveFormatError

TOKEN_RE = re.compile(r'"(?:[^"\\]|\\.)*"|[{}=]|[^\s{}=]+')
HEADER_LIMIT = 64 * 1024

# Country Editor field -> path inside the country block. Confirmed on the real save.
COUNTRY_FIELDS: dict[str, tuple[str, ...]] = {
    "political_power": ("politics", "political_power"),
    "stability": ("stability",),
    "war_support": ("war_support",),
    "command_power": ("command_power",),
    "fuel": ("fuel_status", "fuel"),
    "army_experience": ("experience_status", "army_experience"),
    "air_experience": ("experience_status", "air_experience"),
    "navy_experience": ("experience_status", "navy_experience"),
    # Confirmed 2026-10-09: absent before, 201692736 after console `manpower 2000000` + `manpower 200000000`.
    "manpower": ("manpower", "current"),
}
# Fields whose location in the save is not confirmed yet (never guessed).
UNMAPPED_FIELDS: dict[str, str] = {}
EQUIPMENT_DEF_RE = re.compile(rb"\n\t([A-Za-z0-9_]+)=\{\r?\n\t\tid=\{ id=(\d+) type=(\d+) \}")  # real saves use CRLF
# Absent experience fields: the game omits some values from text saves (observed: only army_experience present).
OMITTED_NOTE = "Not present in the save (the game omits some values, likely when they are 0)."


def _unquote(token: str) -> str:
    if len(token) >= 2 and token[0] == '"' and token[-1] == '"':
        return token[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return token


def parse(text: str) -> list:
    """Parses Clausewitz text into nested lists of (key, value) pairs and bare values."""
    tokens = TOKEN_RE.findall(text)
    pos = 0

    def block() -> list:
        nonlocal pos
        items: list = []
        while pos < len(tokens):
            tok = tokens[pos]
            pos += 1
            if tok == "}":
                return items
            value = block() if tok == "{" else _unquote(tok)
            if pos < len(tokens) and tokens[pos] == "=":
                pos += 1
                if pos >= len(tokens):
                    raise SaveFormatError("truncated", "Text save ends after '='")
                nxt = tokens[pos]
                pos += 1
                items.append((value, block() if nxt == "{" else _unquote(nxt)))
            else:
                items.append(value)
        return items

    return block()


def get(items: list, *path: str):
    """First value at a key path, or None."""
    current = items
    for key in path:
        if not isinstance(current, list):
            return None
        current = next((v for k_v in current if isinstance(k_v, tuple) and k_v[0] == key
                        for v in [k_v[1]]), None)
        if current is None:
            return None
    return current


def _number(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def analyse_header(data: bytes) -> dict:
    head = data[:HEADER_LIMIT].decode("utf-8", errors="replace")
    if not head.startswith("HOI4txt"):
        raise SaveFormatError("unknown_format", "Not a text save")
    cut = head.find("\nsession=")
    if cut < 0:
        raise SaveFormatError("unsupported", "Text save header end not found where expected")
    items = parse(head[len("HOI4txt"):cut])
    date_text = get(items, "date")
    date = None
    if isinstance(date_text, str) and re.fullmatch(r"\d+\.\d+\.\d+\.\d+", date_text):
        y, m, d, h = (int(x) for x in date_text.split("."))
        date = {"year": y, "month": m, "day": d, "hour": h, "text": date_text}
    players = []
    for entry in get(items, "player_countries") or []:
        if isinstance(entry, tuple) and isinstance(entry[1], list):
            players.append({"tag": entry[0], "name": get(entry[1], "user"),
                            "unidentified_fields": {},
                            "country_leader": get(entry[1], "country_leader") == "yes",
                            "id": get(entry[1], "id")})
    mods = get(items, "mods")
    header = {
        "player_tag": get(items, "player"),
        "date": date,
        "version": get(items, "version"),
        "ideology": get(items, "ideology"),
        "difficulty": get(items, "difficulty"),
        "players": players,
        "mods": [m for m in mods if isinstance(m, str)] if isinstance(mods, list) else None,
    }
    missing = [k for k in ("player_tag", "date", "version") if not header[k]]
    return {"format": "text", "float_width": None, "header": header, "missing_fields": missing}


def country_block(data: bytes, tag: str) -> list | None:
    """Parsed block of one country from the top-level `countries={...}`; None if absent."""
    if not re.fullmatch(r"[A-Z][A-Z0-9]{2}", tag or ""):
        raise ValueError(f"Invalid country tag: {tag!r}")
    start = data.find(b"\ncountries={")
    if start < 0:
        raise SaveFormatError("unsupported", "No 'countries' block in this text save")
    marker = f"\n\t{tag}={{".encode()
    pos = data.find(marker, start)
    if pos < 0:
        return None
    # Find the matching closing brace of this block (strings in saves never contain raw braces here,
    # but quoted strings are skipped anyway to be safe).
    i = pos + len(marker)
    depth = 1
    in_string = False
    while i < len(data) and depth:
        c = data[i]
        if in_string:
            if c == 0x5C:  # backslash
                i += 1
            elif c == 0x22:
                in_string = False
        elif c == 0x22:
            in_string = True
        elif c == 0x7B:
            depth += 1
        elif c == 0x7D:
            depth -= 1
        i += 1
    if depth:
        raise SaveFormatError("truncated", f"Country block {tag} is not closed")
    return parse(data[pos + len(marker):i - 1].decode("utf-8", errors="replace"))


def equipment_names(data: bytes) -> dict[str, str]:
    """Equipment id -> type name from the top-level `equipments={...}` table (e.g. "1" -> "convoy_1")."""
    start = data.find(b"\nequipments={")
    if start < 0:
        return {}
    end = data.find(b"\n}", start)
    return {m.group(2).decode(): m.group(1).decode() for m in EQUIPMENT_DEF_RE.finditer(data, start, end)}


def convoys(block: list, names: dict[str, str]) -> dict:
    """Convoys = sum of convoys.equipment entries whose equipment type name starts with "convoy"."""
    entries = get(block, "convoys", "equipment")
    if entries is None:
        return {"value": None, "path": "convoys.equipment", "status": "absent", "note": OMITTED_NOTE}
    total = 0.0
    parts = []
    unknown = []
    for item in entries:
        if not (isinstance(item, tuple) and item[0] == "equipment" and isinstance(item[1], list)):
            continue
        eq_id = get(item[1], "id", "id")
        amount = _number(get(item[1], "amount"))
        name = names.get(eq_id)
        if name is None:
            unknown.append(eq_id)
        elif name.startswith("convoy") and amount is not None:
            total += amount
            parts.append(f"{name}#{eq_id}={amount:g}")
    if unknown:
        return {"value": None, "path": "convoys.equipment", "status": "unmapped",
                "note": f"Equipment id(s) {', '.join(map(str, unknown))} not found in the equipments table"}
    return {"value": total, "path": "convoys.equipment", "status": "read", "raw": " + ".join(parts) or "0"}


def country_values(block: list, names: dict[str, str] | None = None) -> dict:
    """Country Editor values with per-field provenance."""
    values = {}
    for field, path in COUNTRY_FIELDS.items():
        raw = get(block, *path)
        number = _number(raw)
        if number is None:
            values[field] = {"value": None, "path": ".".join(path), "status": "absent", "note": OMITTED_NOTE}
        else:
            values[field] = {"value": number, "path": ".".join(path), "status": "read", "raw": raw}
    values["convoys"] = convoys(block, names or {})
    for field, note in UNMAPPED_FIELDS.items():
        values[field] = {"value": None, "path": None, "status": "unmapped", "note": note}
    return values
