"""Patches of the game's code in memory - LOCAL ONLY (single player), opt-in, asked for by the user 2026-10-15
(combat log for every country, hoi4dbg/live/code_patch.py).

Kept apart from memory_write.py, whose field writes never change page protection. Code pages are read-only, so this
module alone uses VirtualProtectEx. Safety rules enforced here:
- a patch replaces bytes only when the current bytes are exactly the expected ones (the original, or the patch when
  undoing it) - another game version or another tool's change is left alone;
- at most MAX_PATCH bytes, the page protection is restored right after the write, the instruction cache flushed and
  the result read back;
- nothing is written to the files of the game: the patch lives until the game closes.
"""

from __future__ import annotations

from .memory import IS_WINDOWS, MemoryAccessError, ProcessMemory
from .memory_write import WRITE_ACCESS_RIGHTS

MAX_PATCH = 16
PAGE_EXECUTE_READWRITE = 0x40

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_size_t,
                                        ctypes.POINTER(ctypes.c_size_t)]
    _k32.WriteProcessMemory.restype = wintypes.BOOL
    _k32.VirtualProtectEx.argtypes = [wintypes.HANDLE, ctypes.c_uint64, ctypes.c_size_t, wintypes.DWORD,
                                      ctypes.POINTER(wintypes.DWORD)]
    _k32.VirtualProtectEx.restype = wintypes.BOOL
    _k32.FlushInstructionCache.argtypes = [wintypes.HANDLE, ctypes.c_uint64, ctypes.c_size_t]
    _k32.FlushInstructionCache.restype = wintypes.BOOL


class ProcessCodePatcher(ProcessMemory):
    """Handle for replacing a few known bytes of code. Use as a context manager."""

    def __init__(self, pid: int) -> None:  # noqa: D107 - opens with write rights, unlike ProcessMemory
        if not IS_WINDOWS:
            raise MemoryAccessError("Process memory access is only implemented on Windows")
        self.pid = pid
        self._handle = _k32.OpenProcess(WRITE_ACCESS_RIGHTS, False, pid)
        if not self._handle:
            err = ctypes.get_last_error()
            hint = " (access denied: the game may run elevated)" if err == 5 else ""
            raise MemoryAccessError(err, f"OpenProcess(pid={pid}, VM_WRITE) failed{hint}")

    def replace(self, address: int, expected: bytes, new: bytes) -> None:
        """Writes `new` over `expected` at address; refuses when the current bytes differ."""
        if not 0 < len(new) == len(expected) <= MAX_PATCH or address <= 0:
            raise MemoryAccessError(f"Refusing a code patch of {len(new)} bytes")
        if self.read(address, len(new)) != expected:
            raise MemoryAccessError(f"Code at {address:#x} is not the expected one - not patched")
        old = wintypes.DWORD()
        if not _k32.VirtualProtectEx(self._handle, address, len(new), PAGE_EXECUTE_READWRITE, ctypes.byref(old)):
            raise MemoryAccessError(ctypes.get_last_error(), f"VirtualProtectEx at {address:#x} failed")
        try:
            buf = ctypes.create_string_buffer(new, len(new))
            done = ctypes.c_size_t()
            ok = _k32.WriteProcessMemory(self._handle, address, buf, len(new), ctypes.byref(done))
            err = ctypes.get_last_error()
        finally:
            _k32.VirtualProtectEx(self._handle, address, len(new), old.value, ctypes.byref(wintypes.DWORD()))
            _k32.FlushInstructionCache(self._handle, address, len(new))
        if not ok or done.value != len(new):
            raise MemoryAccessError(err, f"WriteProcessMemory at {address:#x} failed")
        if self.read(address, len(new)) != new:
            raise MemoryAccessError(f"Code at {address:#x} did not hold the patch")
