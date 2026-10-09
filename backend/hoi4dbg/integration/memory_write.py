"""Direct writes to the game's memory - LOCAL ONLY (single player), opt-in, approved by the user 2026-10-09.

Kept apart from hoi4dbg/integration/memory.py, which stays strictly read-only. A memory write changes only this
client: in multiplayer the game state of the other players would diverge (desync), so callers must refuse
writes when more than one human player is present (hoi4dbg/live/service.py) and the UI marks the result as local.

Safety rules enforced here:
- the process is opened with exactly QUERY_INFORMATION | VM_READ | VM_WRITE | VM_OPERATION (no thread,
  handle or create rights; no VirtualProtectEx - only memory that is already writable is written);
- one write is at most 8 bytes (a single field) and is checked by reading it back.
"""

from __future__ import annotations

from .memory import IS_WINDOWS, MemoryAccessError, ProcessMemory

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_OPERATION = 0x0008
WRITE_ACCESS_RIGHTS = PROCESS_QUERY_INFORMATION | PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION
MAX_WRITE = 8

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_size_t,
                                        ctypes.POINTER(ctypes.c_size_t)]
    _k32.WriteProcessMemory.restype = wintypes.BOOL


class ProcessMemoryWriter(ProcessMemory):
    """Read/write handle for single small field writes. Use as a context manager."""

    def __init__(self, pid: int) -> None:  # noqa: D107 - opens with write rights, unlike ProcessMemory
        if not IS_WINDOWS:
            raise MemoryAccessError("Process memory access is only implemented on Windows")
        self.pid = pid
        self._handle = _k32.OpenProcess(WRITE_ACCESS_RIGHTS, False, pid)
        if not self._handle:
            err = ctypes.get_last_error()
            hint = " (access denied: the game may run elevated)" if err == 5 else ""
            raise MemoryAccessError(err, f"OpenProcess(pid={pid}, VM_WRITE) failed{hint}")

    def write(self, address: int, data: bytes) -> None:
        if not 0 < len(data) <= MAX_WRITE or address <= 0:
            raise MemoryAccessError(f"Refusing a write of {len(data)} bytes")
        buf = ctypes.create_string_buffer(data, len(data))
        done = ctypes.c_size_t()
        if not _k32.WriteProcessMemory(self._handle, address, buf, len(data), ctypes.byref(done)) \
                or done.value != len(data):
            raise MemoryAccessError(ctypes.get_last_error(), f"WriteProcessMemory at {address:#x} failed")
        if self.read(address, len(data)) != data:
            raise MemoryAccessError(f"Value at {address:#x} did not hold the written bytes")
