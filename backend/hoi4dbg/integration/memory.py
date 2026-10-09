"""Read-only access to another process's memory (WinAPI ReadProcessMemory via ctypes).

Safety rules enforced here:
- the process is opened with PROCESS_QUERY_INFORMATION | PROCESS_VM_READ only. No write, no
  VM_OPERATION, no thread or handle rights. This module has no code path that writes memory;
- only committed, writable, non-guard private pages are scanned (where game state lives);
- every read is bounded (MAX_READ) and failures return None instead of raising.

Value encodings are hypotheses to be confirmed by calibration (see hoi4dbg/live/calibration.py), never assumed.
"""

from __future__ import annotations

import math
import struct
import sys
from dataclasses import dataclass
from typing import Callable, Iterator

IS_WINDOWS = sys.platform == "win32"

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
ACCESS_RIGHTS = PROCESS_QUERY_INFORMATION | PROCESS_VM_READ
MEM_COMMIT = 0x1000
MEM_PRIVATE = 0x20000
MEM_IMAGE = 0x1000000
PAGE_GUARD = 0x100
WRITABLE_PROTECT = {0x04, 0x08, 0x40, 0x80}  # READWRITE, WRITECOPY, EXECUTE_READWRITE, EXECUTE_WRITECOPY
MAX_READ = 64 << 20
USER_SPACE_END = 0x7FFF_FFFF_FFFF

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class MEMORY_BASIC_INFORMATION(ctypes.Structure):
        _fields_ = [("BaseAddress", ctypes.c_uint64), ("AllocationBase", ctypes.c_uint64),
                    ("AllocationProtect", wintypes.DWORD), ("PartitionId", wintypes.WORD), ("_pad1", wintypes.WORD),
                    ("RegionSize", ctypes.c_uint64), ("State", wintypes.DWORD), ("Protect", wintypes.DWORD),
                    ("Type", wintypes.DWORD), ("_pad2", wintypes.DWORD)]

    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.CloseHandle.restype = wintypes.BOOL
    _k32.VirtualQueryEx.argtypes = [wintypes.HANDLE, ctypes.c_uint64, ctypes.POINTER(MEMORY_BASIC_INFORMATION),
                                    ctypes.c_size_t]
    _k32.VirtualQueryEx.restype = ctypes.c_size_t
    _k32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_size_t,
                                       ctypes.POINTER(ctypes.c_size_t)]
    _k32.ReadProcessMemory.restype = wintypes.BOOL
    _k32.K32GetMappedFileNameW.argtypes = [wintypes.HANDLE, ctypes.c_uint64, wintypes.LPWSTR, wintypes.DWORD]
    _k32.K32GetMappedFileNameW.restype = wintypes.DWORD


class MemoryAccessError(OSError):
    pass


@dataclass(frozen=True)
class Needle:
    """Bytes to search for. The value itself starts `offset` bytes before the match; when lo/hi are set,
    every match is checked by decoding the whole value (prefix needles for tolerance searches)."""
    data: bytes
    align: int
    offset: int = 0
    size: int = 0
    encoding: "Encoding | None" = None
    lo: float | None = None
    hi: float | None = None

    def accepts(self, raw: bytes) -> bool:
        if self.encoding is None or self.lo is None:
            return True
        value = self.encoding.unpack(raw)
        return self.lo <= value <= self.hi


@dataclass(frozen=True)
class Encoding:
    """How a decimal game value might be stored. `pack` returns the exact bytes for a value."""
    name: str
    fmt: str
    scale: int | None  # fixed-point scale (1 = plain integer); None = IEEE float

    @property
    def size(self) -> int:
        return struct.calcsize("<" + self.fmt)

    def pack(self, value: float) -> bytes | None:
        try:
            if self.scale is None:
                return struct.pack("<" + self.fmt, value)
            return struct.pack("<" + self.fmt, round(value * self.scale))
        except (struct.error, OverflowError):
            return None

    def unpack(self, data: bytes) -> float:
        raw = struct.unpack("<" + self.fmt, data)[0]
        return raw if self.scale is None else raw / self.scale

    def needle(self, value: float, tolerance: float = 0.0) -> Needle | None:
        """Search pattern for a value known to +-tolerance (e.g. a save value printed with N decimals).

        Fixed point: only if the value is representable at this scale (else this cannot be the encoding).
        Float: the high-order bytes shared by value-tolerance and value+tolerance, verified on each match.
        Zero / unrepresentable / too unspecific (< 3 bytes) -> None."""
        lo, hi = value - tolerance, value + tolerance
        if self.scale is not None:
            # The stored integer must lie in [lo, hi] * scale. One integer there -> that one (e.g. x32768 from a
            # value printed with 5 decimals); several -> the printed value is exact at this scale; none -> not this encoding.
            first, last = math.ceil(lo * self.scale - 1e-9), math.floor(hi * self.scale + 1e-9)
            if first > last:
                return None
            try:
                exact = struct.pack("<" + self.fmt, first if first == last else round(value * self.scale))
            except struct.error:
                return None
            if not exact.strip(b"\0"):
                return None
            return Needle(exact, self.size, 0, self.size, self, lo, hi)
        nearest = self.pack(value)
        if nearest is None:
            return None
        # A float field holds the nearest representable value, which may lie outside the save's precision
        # (float32 at 1.2e8 has a step of 8): widen the window to include it.
        near = self.unpack(nearest)
        lo, hi = min(lo, near), max(hi, near)
        a, b = self.pack(lo), self.pack(hi)
        if a is None or b is None:
            return None
        common = 0
        while common < self.size and a[self.size - 1 - common] == b[self.size - 1 - common]:
            common += 1
        if common < 3 or not a[self.size - common:].strip(b"\0"):
            return None
        return Needle(a[self.size - common:], self.size, self.size - common, self.size, self, lo, hi)


# Candidate encodings. Clausewitz games store most values as fixed point; which one a field
# uses in 1.19.3 is decided by calibration evidence, not by this list.
ENCODINGS: dict[str, Encoding] = {e.name: e for e in (
    Encoding("int32", "i", 1),
    Encoding("int64", "q", 1),
    Encoding("fixed32_1000", "i", 1000),
    Encoding("fixed64_1000", "q", 1000),
    Encoding("fixed64_100000", "q", 100000),
    # binary saves store fuel/experience as int64 / 32768 (see hoi4dbg/saves/binvalues.py)
    Encoding("fixed64_32768", "q", 32768),
    Encoding("float32", "f", None),
    Encoding("float64", "d", None),
)}


class ProcessMemory:
    """Read-only handle to a process. Use as a context manager."""

    def __init__(self, pid: int) -> None:
        if not IS_WINDOWS:
            raise MemoryAccessError("Process memory access is only implemented on Windows")
        self.pid = pid
        self._handle = _k32.OpenProcess(ACCESS_RIGHTS, False, pid)
        if not self._handle:
            err = ctypes.get_last_error()
            hint = " (access denied: the game may run elevated or under another user)" if err == 5 else ""
            raise MemoryAccessError(err, f"OpenProcess(pid={pid}, QUERY_INFORMATION|VM_READ) failed{hint}")

    def close(self) -> None:
        if self._handle:
            _k32.CloseHandle(self._handle)
            self._handle = None

    def __enter__(self) -> "ProcessMemory":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def regions(self, image: bool = False) -> Iterator[tuple[int, int]]:
        """(base, size) of committed, writable, private regions (+ writable module data with `image`)."""
        for base, size, _, _ in self._query(MEM_PRIVATE | (MEM_IMAGE if image else 0)):
            yield base, size

    def modules(self) -> dict[str, tuple[int, int]]:
        """Loaded images: lower-case file name -> (allocation base, end of the last region)."""
        out: dict[str, tuple[int, int]] = {}
        names: dict[int, str] = {}
        buf = ctypes.create_unicode_buffer(1024)
        for base, size, alloc, _ in self._query(MEM_IMAGE, writable_only=False):
            if alloc not in names:
                n = _k32.K32GetMappedFileNameW(self._handle, alloc, buf, len(buf))
                names[alloc] = buf.value[:n].rsplit("\\", 1)[-1].lower() if n else hex(alloc)
            lo, hi = out.get(names[alloc], (alloc, alloc))
            out[names[alloc]] = (lo, max(hi, base + size))
        return out

    def _query(self, types: int, writable_only: bool = True) -> Iterator[tuple[int, int, int, int]]:
        addr, mbi = 0, MEMORY_BASIC_INFORMATION()
        while addr < USER_SPACE_END and _k32.VirtualQueryEx(self._handle, addr, ctypes.byref(mbi), ctypes.sizeof(mbi)):
            if (mbi.State == MEM_COMMIT and mbi.Type & types and not mbi.Protect & PAGE_GUARD
                    and (not writable_only or (mbi.Protect & 0xFF) in WRITABLE_PROTECT)):
                yield mbi.BaseAddress, mbi.RegionSize, mbi.AllocationBase, mbi.Type
            next_addr = mbi.BaseAddress + mbi.RegionSize
            if next_addr <= addr:
                break
            addr = next_addr

    def read(self, address: int, size: int) -> bytes | None:
        if size <= 0 or size > MAX_READ or address <= 0:
            return None
        buf = ctypes.create_string_buffer(size)
        done = ctypes.c_size_t()
        if not _k32.ReadProcessMemory(self._handle, address, buf, size, ctypes.byref(done)) or done.value != size:
            return None
        return buf.raw


def scan(memory, needles: dict[str, "Needle | tuple[bytes, int]"], chunk: int = 32 << 20,
         progress: Callable[[int, int], None] | None = None, limit: int = 200_000) -> dict[str, list[int]]:
    """Finds every aligned value matching each needle in the scannable regions -> {key: [value address]}.

    `memory` needs regions() and read(); chunks overlap so values on chunk borders are found once.
    A plain (bytes, alignment) tuple is an exact needle.
    """
    needles = {k: (v if isinstance(v, Needle) else Needle(v[0], v[1], 0, len(v[0]))) for k, v in needles.items()}
    regions = list(memory.regions())
    total = sum(size for _, size in regions) or 1
    done = 0
    overlap = max((max(n.size, len(n.data) + n.offset) for n in needles.values()), default=1)
    hits: dict[str, list[int]] = {key: [] for key in needles}
    for base, size in regions:
        offset = 0
        while offset < size:
            n = min(chunk, size - offset)
            data = memory.read(base + offset, min(n + overlap, size - offset))
            if data:
                for key, nd in needles.items():
                    found = hits[key]
                    i = data.find(nd.data)
                    while i != -1 and len(found) < limit:
                        start = i - nd.offset
                        if start >= n:
                            break
                        if start >= 0 and (base + offset + start) % nd.align == 0                                 and nd.accepts(data[start:start + nd.size]):
                            found.append(base + offset + start)
                        i = data.find(nd.data, i + 1)
            offset += n
            done += n
            if progress:
                progress(done, total)
    return hits


def needles_for(value: float, encodings: dict[str, Encoding] = ENCODINGS, tolerance: float = 0.0) -> dict[str, Needle]:
    out = {}
    for name, enc in encodings.items():
        nd = enc.needle(value, tolerance)
        if nd is not None:
            out[name] = nd
    return out
