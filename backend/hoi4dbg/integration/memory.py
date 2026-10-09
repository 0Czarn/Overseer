"""Read-only access to another process's memory (WinAPI ReadProcessMemory via ctypes).

Safety rules enforced here:
- the process is opened with PROCESS_QUERY_INFORMATION | PROCESS_VM_READ only. No write, no
  VM_OPERATION, no thread or handle rights. This module has no code path that writes memory;
- only committed, writable, non-guard private pages are scanned (where game state lives);
- every read is bounded (MAX_READ) and failures return None instead of raising.

Value encodings are hypotheses to be confirmed by calibration (see hoi4dbg/live/calibration.py), never assumed.
"""

from __future__ import annotations

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


class MemoryAccessError(OSError):
    pass


@dataclass(frozen=True)
class Encoding:
    """How a decimal game value might be stored. `pack` returns the exact bytes for a value."""
    name: str
    fmt: str
    scale: int | None  # fixed-point scale; None = IEEE float

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


# Candidate encodings. Clausewitz games store most values as fixed point; which one a field
# uses in 1.19.3 is decided by calibration evidence, not by this list.
ENCODINGS: dict[str, Encoding] = {e.name: e for e in (
    Encoding("fixed32_1000", "i", 1000),
    Encoding("fixed64_1000", "q", 1000),
    Encoding("fixed64_100000", "q", 100000),
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

    def regions(self) -> Iterator[tuple[int, int]]:
        """(base, size) of committed, writable, private regions."""
        addr, mbi = 0, MEMORY_BASIC_INFORMATION()
        while addr < USER_SPACE_END and _k32.VirtualQueryEx(self._handle, addr, ctypes.byref(mbi), ctypes.sizeof(mbi)):
            if (mbi.State == MEM_COMMIT and mbi.Type == MEM_PRIVATE and (mbi.Protect & 0xFF) in WRITABLE_PROTECT
                    and not mbi.Protect & PAGE_GUARD):
                yield mbi.BaseAddress, mbi.RegionSize
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


def scan(memory, needles: dict[str, tuple[bytes, int]], chunk: int = 32 << 20,
         progress: Callable[[int, int], None] | None = None, limit: int = 200_000) -> dict[str, list[int]]:
    """Finds every aligned occurrence of each needle {key: (bytes, alignment)} in the scannable regions.

    `memory` needs regions() and read(); chunks overlap so values on chunk borders are found.
    """
    regions = list(memory.regions())
    total = sum(size for _, size in regions) or 1
    done = 0
    overlap = max((len(n) for n, _ in needles.values()), default=1) - 1
    hits: dict[str, list[int]] = {key: [] for key in needles}
    for base, size in regions:
        offset = 0
        while offset < size:
            n = min(chunk, size - offset)
            data = memory.read(base + offset, min(n + overlap, size - offset))
            if data:
                for key, (needle, align) in needles.items():
                    found = hits[key]
                    i = data.find(needle)
                    while i != -1 and i < n and len(found) < limit:
                        if (base + offset + i) % align == 0:
                            found.append(base + offset + i)
                        i = data.find(needle, i + 1)
            offset += n
            done += n
            if progress:
                progress(done, total)
    return hits


def needles_for(value: float, encodings: dict[str, Encoding] = ENCODINGS) -> dict[str, tuple[bytes, int]]:
    out = {}
    for name, enc in encodings.items():
        packed = enc.pack(value)
        if packed is not None and packed.strip(b"\0"):  # zero would match everywhere
            out[name] = (packed, enc.size)
    return out
