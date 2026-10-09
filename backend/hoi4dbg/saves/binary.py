"""Lexer / validator / partial parser for the HOI4 binary save format ("HOI4bin").

Format as verified on real saves 1.16.10 - 1.19.3 (docs/SAVE-FORMAT.md):
- 7-byte magic "HOI4bin", then a stream of little-endian u16 tokens.
- Control tokens: 0x0001 "=", 0x0003 "{", 0x0004 "}".
- Typed values (token followed by payload):
    0x000c i32 (4)      0x0014 u32 (4)      0x000e bool (1)
    0x000f quoted string, 0x0017 unquoted string (u16 length + bytes)
    0x0167 8 bytes      0x029c u64 (8)      0x0317 8 bytes
    0x000d 4 bytes in 1.16.x, 8 bytes in 1.17.0+ (see detect_float_width)
- Every other u16 is a field-name token. Paradox does not publish the id -> name map;
  meanings we rely on are listed in fields.py together with the evidence.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field

MAGIC_BINARY = b"HOI4bin"
MAGIC_TEXT = b"HOI4txt"
ZIP_MAGIC = b"PK\x03\x04"

EQUALS, OPEN, CLOSE = 0x0001, 0x0003, 0x0004
I32, F32, BOOL, QUOTED, U32, UNQUOTED, F64, U64, I64 = 0x000C, 0x000D, 0x000E, 0x000F, 0x0014, 0x0017, 0x0167, 0x029C, 0x0317
FIXED_SIZES = {I32: 4, U32: 4, BOOL: 1, F64: 8, U64: 8, I64: 8}


class SaveFormatError(Exception):
    """Raised for files we cannot read. `code` is stable and shown in the UI."""

    def __init__(self, code: str, message: str, offset: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.offset = offset


def sniff(prefix: bytes) -> str:
    """'binary' | 'text' | 'compressed' | 'empty' | 'unknown'."""
    if not prefix:
        return "empty"
    if prefix.startswith(MAGIC_BINARY):
        return "binary"
    if prefix.startswith(MAGIC_TEXT):
        return "text"
    if prefix.startswith(ZIP_MAGIC):
        return "compressed"
    return "unknown"


# --- full-file structural validation -------------------------------------------------------
@dataclass
class ScanResult:
    ok: bool
    float_width: int
    tokens: int = 0
    max_depth: int = 0
    end_depth: int = 0
    error: str | None = None
    error_offset: int | None = None


def scan(data: bytes | memoryview, float_width: int, start: int = len(MAGIC_BINARY)) -> ScanResult:
    """Walks every token and checks the grammar. A wrong payload size for any token type
    desynchronises the stream, which this check is designed to catch:
    file must end exactly on a token boundary with balanced braces, "=" must follow a key
    and be followed by a value."""
    sizes = dict(FIXED_SIZES)
    sizes[F32] = float_width
    n = len(data)
    pos = start
    depth = max_depth = tokens = 0
    prev = OPEN  # treat start like the inside of an object
    while pos < n:
        if pos + 2 > n:
            return ScanResult(False, float_width, tokens, max_depth, depth, "truncated token", pos)
        tok = data[pos] | (data[pos + 1] << 8)
        tok_pos = pos
        pos += 2
        tokens += 1
        if tok == EQUALS:
            if prev in (EQUALS, OPEN, CLOSE):
                return ScanResult(False, float_width, tokens, max_depth, depth, "'=' without a key", tok_pos)
        elif tok == OPEN:
            depth += 1
            if depth > max_depth:
                max_depth = depth
        elif tok == CLOSE:
            if prev == EQUALS:
                return ScanResult(False, float_width, tokens, max_depth, depth, "'}' after '='", tok_pos)
            depth -= 1
            if depth < 0:
                return ScanResult(False, float_width, tokens, max_depth, depth, "unbalanced '}'", tok_pos)
        elif tok == QUOTED or tok == UNQUOTED:
            if pos + 2 > n:
                return ScanResult(False, float_width, tokens, max_depth, depth, "truncated string", tok_pos)
            pos += 2 + (data[pos] | (data[pos + 1] << 8))
        else:
            size = sizes.get(tok)
            if size:
                pos += size
        prev = tok
    if pos != n:
        return ScanResult(False, float_width, tokens, max_depth, depth, "value runs past end of file", n)
    if depth != 0:
        return ScanResult(False, float_width, tokens, max_depth, depth,
                          f"{depth} unclosed '{{' at end of file", n)
    return ScanResult(True, float_width, tokens, max_depth, 0)


VERSION_RE = re.compile(r"v(\d+)\.(\d+)")


def expected_float_width(version: str | None) -> int | None:
    """Width of token 0x000d suggested by the game version string (observed: 4 in 1.16, 8 from 1.17.0)."""
    match = VERSION_RE.search(version or "")
    if not match:
        return None
    major, minor = int(match.group(1)), int(match.group(2))
    return 8 if (major, minor) >= (1, 17) else 4


@dataclass
class Validation:
    status: str  # "complete" | "ambiguous" | "invalid"
    float_width: int | None
    message: str
    results: list[ScanResult] = field(default_factory=list)


def validate(data: bytes | memoryview, version: str | None) -> Validation:
    """Picks the 0x000d width that yields a structurally valid file.

    The width suggested by the game version is tried first and accepted if the whole file
    validates with it. Otherwise (or without a version) both widths are tried; some saves
    validate with both, so a single passing width is required to decide without a version."""
    expected = expected_float_width(version)
    if expected is not None:
        first = scan(data, expected)
        if first.ok:
            return Validation("complete", expected,
                              f"Structure valid, value width {expected} (matches game version)", [first])
        results = [first, scan(data, 12 - expected)]
    else:
        results = [scan(data, 8), scan(data, 4)]
    passing = [r for r in results if r.ok]
    if len(passing) == 1:
        width = passing[0].float_width
        note = "" if expected in (None, width) else f" (unexpected for {version})"
        return Validation("complete", width, f"Structure valid, value width {width}{note}", results)
    if len(passing) == 2:
        if expected is not None:
            return Validation("complete", expected, f"Structure valid; width {expected} chosen by game version", results)
        return Validation("ambiguous", None, "Structure valid with both value widths and version unknown", results)
    worst = max(results, key=lambda r: r.error_offset or 0)
    return Validation("invalid", None,
                      f"Structure invalid ({worst.error} at offset {worst.error_offset}); file is damaged, "
                      "incomplete or uses an unsupported format", results)


# --- partial tree parser (header) ----------------------------------------------------------
@dataclass
class Token:
    """A field-name token whose meaning is not known (kept as its numeric id)."""
    id: int

    def __repr__(self) -> str:
        return f"#{self.id:04x}"


@dataclass
class Raw:
    """A typed value whose numeric scale has not been verified; kept as raw bytes."""
    type: int
    data: bytes


class Parser:
    def __init__(self, data: bytes | memoryview, float_width: int, start: int = len(MAGIC_BINARY)) -> None:
        self.data = data
        self.pos = start
        self.sizes = dict(FIXED_SIZES)
        self.sizes[F32] = float_width

    def _need(self, count: int) -> None:
        if self.pos + count > len(self.data):
            raise SaveFormatError("truncated", "File ends in the middle of a value", self.pos)

    def _u16(self) -> int:
        self._need(2)
        value = self.data[self.pos] | (self.data[self.pos + 1] << 8)
        self.pos += 2
        return value

    def peek(self) -> int | None:
        if self.pos + 2 > len(self.data):
            return None
        return self.data[self.pos] | (self.data[self.pos + 1] << 8)

    def scalar(self, tok: int):
        if tok in (QUOTED, UNQUOTED):
            length = self._u16()
            self._need(length)
            raw = bytes(self.data[self.pos:self.pos + length])
            self.pos += length
            return raw.decode("utf-8", errors="replace")
        size = self.sizes.get(tok)
        if size:
            self._need(size)
            raw = bytes(self.data[self.pos:self.pos + size])
            self.pos += size
            if tok == I32:
                return struct.unpack("<i", raw)[0]
            if tok == U32:
                return struct.unpack("<I", raw)[0]
            if tok == BOOL:
                return raw[0] != 0
            if tok == U64:
                return struct.unpack("<Q", raw)[0]
            return Raw(tok, raw)  # 0x000d / 0x0167 / 0x0317: scale not verified
        if tok in (EQUALS, OPEN, CLOSE):
            raise SaveFormatError("corrupt", f"Unexpected control token 0x{tok:04x}", self.pos - 2)
        return Token(tok)

    def value(self, budget: list[int]):
        tok = self._u16()
        if tok == OPEN:
            return self.block(budget)
        return self.scalar(tok)

    def block(self, budget: list[int]) -> list:
        """Contents of { ... } as a list of (key, value) pairs or bare values."""
        items: list = []
        while True:
            budget[0] -= 1
            if budget[0] < 0:
                raise SaveFormatError("unsupported", "Header block larger than expected", self.pos)
            tok = self._u16()
            if tok == CLOSE:
                return items
            item = self.block(budget) if tok == OPEN else self.scalar(tok)
            if self.peek() == EQUALS:
                self.pos += 2
                items.append((item, self.value(budget)))
            else:
                items.append(item)

    def skip_value(self) -> None:
        """Skips one value (scalar or whole block) without building it."""
        tok = self._u16()
        if tok != OPEN:
            self.scalar(tok)
            return
        depth = 1
        while depth:
            tok = self._u16()
            if tok == OPEN:
                depth += 1
            elif tok == CLOSE:
                depth -= 1
            elif tok in (QUOTED, UNQUOTED):
                length = self._u16()
                self._need(length)
                self.pos += length
            else:
                size = self.sizes.get(tok)
                if size:
                    self._need(size)
                    self.pos += size

    def top_level(self, wanted: set[int], max_entries: int = 400, block_budget: int = 20000) -> dict[int, object]:
        """Reads top-level `key = value` entries until all `wanted` keys were seen.
        Blocks for unwanted keys are skipped; wanted ones are parsed (bounded by block_budget tokens)."""
        found: dict[int, object] = {}
        for _ in range(max_entries):
            if wanted <= found.keys() or self.peek() is None:
                break
            key = self._u16()
            if key in (EQUALS, OPEN, CLOSE) or key in self.sizes or key in (QUOTED, UNQUOTED):
                raise SaveFormatError("corrupt", f"Expected a field name at top level, got 0x{key:04x}", self.pos - 2)
            if self._u16() != EQUALS:
                raise SaveFormatError("corrupt", "Expected '=' after a top-level field", self.pos - 2)
            if key in wanted:
                found[key] = self.value([block_budget])
            else:
                self.skip_value()
        return found
