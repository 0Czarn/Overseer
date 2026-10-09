"""Read-only Windows process enumeration via WinAPI (ctypes).

Uses only process *metadata* APIs (Toolhelp snapshot, QueryFullProcessImageNameW,
GetProcessTimes) with PROCESS_QUERY_LIMITED_INFORMATION access. It does not open
the process for memory reading (no PROCESS_VM_READ) and never writes anything.
"""

from __future__ import annotations

import datetime as dt
import sys

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    TH32CS_SNAPPROCESS = 0x00000002
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
    MAX_PATH_CHARS = 32768

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    _kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    _kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    _kernel32.Process32FirstW.restype = wintypes.BOOL
    _kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    _kernel32.Process32NextW.restype = wintypes.BOOL
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                     ctypes.POINTER(wintypes.DWORD)]
    _kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    _kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    _kernel32.GetProcessTimes.restype = wintypes.BOOL


def _filetime_to_datetime(ft) -> dt.datetime:
    ticks = (ft.dwHighDateTime << 32) | ft.dwLowDateTime  # 100 ns since 1601-01-01 UTC
    return dt.datetime(1601, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(microseconds=ticks // 10)


def list_processes() -> list[tuple[int, str]]:
    """(pid, exe name) for every process visible to the current user."""
    if not IS_WINDOWS:
        return []
    snapshot = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        raise OSError(ctypes.get_last_error(), "CreateToolhelp32Snapshot failed")
    result = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = _kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            result.append((int(entry.th32ProcessID), entry.szExeFile))
            ok = _kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(snapshot)
    return result


def process_details(pid: int) -> dict:
    """Executable path and start time. Fields are None when access is denied."""
    details: dict = {"path": None, "started": None, "uptime_s": None}
    if not IS_WINDOWS:
        return details
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        details["access_error"] = ctypes.get_last_error()
        return details
    try:
        buf = ctypes.create_unicode_buffer(MAX_PATH_CHARS)
        size = wintypes.DWORD(MAX_PATH_CHARS)
        if _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            details["path"] = buf.value
        created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if _kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                     ctypes.byref(kernel), ctypes.byref(user)):
            started = _filetime_to_datetime(created)
            details["started"] = started.isoformat(timespec="seconds")
            details["uptime_s"] = max(0, int((dt.datetime.now(dt.timezone.utc) - started).total_seconds()))
    finally:
        _kernel32.CloseHandle(handle)
    return details


def find_processes(exe_name: str, lister=list_processes, details=process_details) -> list[dict]:
    """All running processes whose executable name matches exe_name (case-insensitive)."""
    wanted = exe_name.lower()
    return [{"pid": pid, "name": name, **details(pid)} for pid, name in lister() if name.lower() == wanted]
