"""Builds synthetic HOI4bin files for tests, mirroring the structure of real saves."""

from __future__ import annotations

import struct

from hoi4dbg.saves import binary as b
from hoi4dbg.saves import fields as f


class Builder:
    def __init__(self, float_width: int = 8) -> None:
        self.out = bytearray(b.MAGIC_BINARY)
        self.float_width = float_width

    def tok(self, value: int) -> "Builder":
        self.out += struct.pack("<H", value)
        return self

    def key(self, token: int) -> "Builder":
        return self.tok(token).tok(b.EQUALS)

    def qstr(self, text: str) -> "Builder":
        raw = text.encode("utf-8")
        self.tok(b.QUOTED).out += struct.pack("<H", len(raw)) + raw
        return self

    def ustr(self, text: str) -> "Builder":
        raw = text.encode("utf-8")
        self.tok(b.UNQUOTED).out += struct.pack("<H", len(raw)) + raw
        return self

    def i32(self, value: int) -> "Builder":
        self.tok(b.I32).out += struct.pack("<i", value)
        return self

    def u32(self, value: int) -> "Builder":
        self.tok(b.U32).out += struct.pack("<I", value)
        return self

    def boolean(self, value: bool) -> "Builder":
        self.tok(b.BOOL).out += bytes([1 if value else 0])
        return self

    def f(self, raw: int = 0) -> "Builder":
        """A 0x000d value with this builder's width."""
        self.tok(b.F32).out += raw.to_bytes(self.float_width, "little", signed=True)
        return self

    def open(self) -> "Builder":
        return self.tok(b.OPEN)

    def close(self) -> "Builder":
        return self.tok(b.CLOSE)

    def bytes(self) -> bytes:
        return bytes(self.out)


def encode_date(year: int, month: int, day: int, hour: int) -> int:
    days_before = sum((31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)[:month - 1])
    return ((year + 5000) * 365 + days_before + day - 1) * 24 + hour - 1


def realistic_save(version: str = "Operation Postern v1.19.3.0.c01a (ff0e)", float_width: int = 8,
                   players: list[tuple[str, str]] = (("GER", "Czarny"),), mods: list[str] = ("Toolpack+",),
                   body_values: int = 3) -> bytes:
    """Same top-level order as a real 1.19.3 save, followed by a body that uses 0x000d values
    (the token whose width changed between versions)."""
    bld = Builder(float_width)
    bld.key(f.PLAYER_TAG).qstr(players[0][0])
    bld.key(f.IDEOLOGY).ustr("fascism")
    bld.key(f.DATE).i32(encode_date(1937, 3, 1, 2))
    bld.key(f.DIFFICULTY).qstr("normal")
    bld.key(f.VERSION).qstr(version)
    bld.key(0x2DF8).boolean(False)
    bld.key(f.PLAYERS).open()
    for index, (tag, name) in enumerate(players, start=1):
        bld.qstr(tag).tok(b.EQUALS).open()
        bld.key(f.PLAYER_NAME).qstr(name).key(0x3035).boolean(True).key(0x000B).i32(index)
        bld.close()
    bld.close()
    bld.key(0x349D).i32(33)
    bld.key(0x2D1A).u32(257535)
    bld.key(f.MODS).open()
    for mod in mods:
        bld.qstr(mod)
    bld.close()
    # Body: a block of 0x000d values similar to the region where width detection matters.
    # The raw value 3 << 32 makes a 4-byte reader see a CLOSE token (0x0004) mid-value.
    bld.key(0x2D49).open().key(0x00F0).open()
    for _ in range(body_values):
        bld.f(0).f(3 << 32 if float_width == 8 else 0)
    bld.close().close()
    return bld.bytes()
