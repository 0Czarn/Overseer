"""Which countries exist in a save (own at least one state) and their ruling party (for the displayed name).

Every country tag has a block in `countries` (also tags that do not exist yet), so existence is taken from
state ownership: top-level `states` -> each state's `owner`.
Binary token ids verified 2026-10-09 on the text/binary pair 11.hoi4 / 2-1.hoi4 (1.19.3): states 0x2e3b,
state owner 0x283e (quoted tag), politics.ruling_party 0x3008 (ideology name).
"""

from __future__ import annotations

import bisect
import re

from . import binary, binvalues

STATES, OWNER, RULING_PARTY = 0x2E3B, 0x283E, 0x3008
BRACE_OR_STRING = re.compile(rb'"(?:[^"\\]|\\.)*"|[{}]')


def _section(data: bytes, name: bytes) -> bytes:
    """Top-level block `name={...}` by brace matching (the game does not indent every line consistently)."""
    start = data.find(b"\n" + name + b"={")
    if start < 0:
        return b""
    depth = 0
    for m in BRACE_OR_STRING.finditer(data, start + len(name) + 2):
        tok = m.group()
        if tok == b"{":
            depth += 1
        elif tok == b"}":
            depth -= 1
            if depth == 0:
                return data[start:m.end()]
    return data[start:]


def summary_text(data: bytes) -> dict:
    states = _section(data, b"states")
    owners: dict[str, int] = {}
    for tag in re.findall(rb'\n\t\towner="([A-Z][A-Z0-9]{2})"', states):
        owners[tag.decode()] = owners.get(tag.decode(), 0) + 1
    countries = _section(data, b"countries")
    heads = [(m.start(), m.group(1).decode()) for m in re.finditer(rb"\n\t([A-Z][A-Z0-9]{2})=\{", countries)]
    starts = [p for p, _ in heads]
    ruling = {}
    for m in re.finditer(rb"\n\t\t\truling_party=([a-z_]+)", countries):  # depth 3: only inside politics={}
        i = bisect.bisect_right(starts, m.start()) - 1
        if i >= 0:
            ruling.setdefault(heads[i][1], m.group(1).decode())
    return {"owners": owners, "ruling": ruling}


def summary_binary(data: bytes, float_width: int, version: str | None) -> dict:
    if not binvalues.VERIFIED_VERSION.search(version or "") or float_width != 8:
        raise binary.SaveFormatError("binary_values_unmapped", f"Binary country list is only mapped for 1.19.3 "
                                     f"(this save: {version or 'unknown'}). Use a text save (-force_text_save).")
    owners: dict[str, int] = {}
    positions: dict[int, int] = {}
    p = binary.Parser(data, float_width)
    while p.peek() is not None:
        key = p._u16()
        if p._u16() != binary.EQUALS:
            raise binary.SaveFormatError("corrupt", "Expected '=' after a top-level field", p.pos - 2)
        if key in (STATES, binvalues.TOKENS["countries"]):
            positions[key] = p.pos
        p.skip_value()
    if STATES in positions:
        p.pos = positions[STATES]
        if p._u16() == binary.OPEN:
            while p.peek() not in (None, binary.CLOSE):
                p.scalar(p._u16())
                if p._u16() != binary.EQUALS or p._u16() != binary.OPEN:
                    raise binary.SaveFormatError("corrupt", "A state is not a block", p.pos - 2)
                for k, v in p.block([1_000_000]):
                    if isinstance(k, binary.Token) and k.id == OWNER and isinstance(v, str):
                        owners[v] = owners.get(v, 0) + 1
    ruling = {}
    if binvalues.TOKENS["countries"] in positions:
        p.pos = positions[binvalues.TOKENS["countries"]]
        if p._u16() == binary.OPEN:
            while p.peek() not in (None, binary.CLOSE):
                tag = p.scalar(p._u16())
                if p._u16() != binary.EQUALS:
                    raise binary.SaveFormatError("corrupt", "Expected '=' after a country tag", p.pos - 2)
                if tag not in owners or p.peek() != binary.OPEN:
                    p.skip_value()
                    continue
                p._u16()
                party = _ruling_party(p)
                if party:
                    ruling[tag] = party
    return {"owners": owners, "ruling": ruling}


def focus_states_binary(data: bytes, float_width: int, version: str | None) -> dict[str, list]:
    """{tag: [("focus_tree", id), ("focus", [...])]} for every country, in one pass (other keys skipped)."""
    if not binvalues.VERIFIED_VERSION.search(version or "") or float_width != 8:
        raise binary.SaveFormatError("binary_values_unmapped", f"Binary focus state is only mapped for 1.19.3 "
                                     f"(this save: {version or 'unknown'}). Use a text save (-force_text_save).")
    wanted = {binvalues.TOKENS["focus_tree"], binvalues.TOKENS["focus"]}
    out: dict[str, list] = {}
    p = binary.Parser(data, float_width)
    while p.peek() is not None:
        key = p._u16()
        if p._u16() != binary.EQUALS:
            raise binary.SaveFormatError("corrupt", "Expected '=' after a top-level field", p.pos - 2)
        if key != binvalues.TOKENS["countries"] or p.peek() != binary.OPEN:
            p.skip_value()
            continue
        p._u16()
        while p.peek() not in (None, binary.CLOSE):
            tag = p.scalar(p._u16())
            p._u16()
            if p.peek() != binary.OPEN:
                p.skip_value()
                continue
            p._u16()
            items = []
            while p.peek() not in (None, binary.CLOSE):
                if p.peek() == binary.OPEN:
                    p.skip_value()
                    continue
                k = p.scalar(p._u16())
                if p.peek() != binary.EQUALS:
                    continue
                p._u16()
                if isinstance(k, binary.Token) and k.id in wanted:
                    items.append((k, p.value([1_000_000])))
                else:
                    p.skip_value()
            p._u16()
            out[tag] = binvalues._named(items)
        break
    return out


def _ruling_party(p: binary.Parser) -> str | None:
    """Reads one country block (cursor after its '{'), returning politics.ruling_party; skips everything else."""
    party = None
    while p.peek() not in (None, binary.CLOSE):
        if p.peek() == binary.OPEN:
            p.skip_value()  # bare block inside the country block
            continue
        key = p.scalar(p._u16())
        if p.peek() != binary.EQUALS:
            continue  # bare value
        p._u16()
        if isinstance(key, binary.Token) and key.id == binvalues.TOKENS["politics"] and p.peek() == binary.OPEN:
            p._u16()
            for k, v in p.block([1_000_000]):
                if isinstance(k, binary.Token) and k.id == RULING_PARTY and isinstance(v, str):
                    party = v
        else:
            p.skip_value()
    p._u16()  # '}'
    return party
