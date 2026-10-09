"""Save discovery, safe copying and analysis.

The original save is never opened for writing and never parsed in place: it is first
copied into the debugger's cache directory (after checking that the game is not still
writing it), and all parsing happens on that copy.
"""

from __future__ import annotations

import copy as copy_module
import datetime as dt
import hashlib
import logging
import shutil
import threading
import time
from pathlib import Path
from typing import Callable

from . import binary, fields, text

SAVE_SUFFIX = ".hoi4"
SNIFF_BYTES = 16


def list_saves(saves_dir: Path | None) -> list[dict]:
    if saves_dir is None or not saves_dir.is_dir():
        return []
    items = []
    for path in saves_dir.iterdir():
        if path.suffix.lower() != SAVE_SUFFIX or not path.is_file():
            continue
        stat = path.stat()
        items.append({"name": path.name, "size": stat.st_size, "mtime": stat.st_mtime,
                      "modified": dt.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")})
    items.sort(key=lambda s: s["mtime"], reverse=True)
    return items


def analyse_bytes(data: bytes) -> dict:
    """Header analysis of a complete save already in memory. Raises SaveFormatError."""
    kind = binary.sniff(data[:SNIFF_BYTES])
    if kind == "empty":
        raise binary.SaveFormatError("empty", "The save file is empty")
    if kind == "compressed":
        raise binary.SaveFormatError("compressed", "Compressed (zip) saves are not supported yet")
    if kind == "text":
        return text.analyse_header(data)
    if kind != "binary":
        raise binary.SaveFormatError("unknown_format", f"Not a HOI4 save (starts with {data[:8]!r})")

    # The version string precedes every 0x000d value, so it can be read before the width is known.
    version = binary.Parser(data, 8).top_level({fields.VERSION}, max_entries=32).get(fields.VERSION)
    if not isinstance(version, str):
        raise binary.SaveFormatError("unsupported", "Version string not found where expected in the header")
    width = binary.expected_float_width(version) or 8
    return header_with_width(data, width)


def header_with_width(data: bytes, width: int) -> dict:
    found = binary.Parser(data, width).top_level(fields.HEADER_KEYS)
    header = fields.extract_header(found)
    missing = [fields.FIELDS[k].key for k in fields.HEADER_KEYS if k not in found]
    return {"format": "binary", "float_width": width, "header": header, "missing_fields": sorted(missing)}


class SaveSnapshotter:
    """Copies a save into the cache once it is stable (not being written)."""

    def __init__(self, cache_dir: Path, settle_s: float = 3.0, keep: int = 3,
                 clock: Callable[[], float] = time.time) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.settle_s = settle_s
        self.keep = keep
        self.clock = clock

    def copy(self, source: Path) -> Path:
        before = source.stat()
        if self.clock() - before.st_mtime < self.settle_s:
            raise binary.SaveFormatError("in_progress", "The game may still be writing this save; try again shortly")
        digest = hashlib.sha1(f"{source.name}|{before.st_size}|{before.st_mtime_ns}".encode()).hexdigest()[:12]
        target = self.cache_dir / f"{digest}{SAVE_SUFFIX}"
        if not (target.exists() and target.stat().st_size == before.st_size):
            tmp = target.with_suffix(".part")
            shutil.copyfile(source, tmp)
            after = source.stat()
            if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
                tmp.unlink(missing_ok=True)
                raise binary.SaveFormatError("in_progress", "The save changed while it was being copied")
            tmp.replace(target)
        self._prune(keep=target)
        return target

    def _prune(self, keep: Path) -> None:
        copies = sorted(self.cache_dir.glob(f"*{SAVE_SUFFIX}"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in [p for p in copies if p != keep][self.keep - 1:]:
            old.unlink(missing_ok=True)


class SaveAnalyzer:
    """Header analysis on demand plus full structural validation in a background thread.
    Results are cached per (name, size, mtime)."""

    def __init__(self, snapshotter: SaveSnapshotter, logger: logging.Logger) -> None:
        self.snapshotter = snapshotter
        self.log = logger
        self._lock = threading.Lock()
        self._results: dict[tuple, dict] = {}

    def analyse(self, path: Path) -> dict:
        stat = path.stat()
        key = (path.name, stat.st_size, stat.st_mtime_ns)
        with self._lock:
            cached = self._results.get(key)
            if cached is not None:
                return copy_module.deepcopy(cached)
        result: dict = {
            "file": {"name": path.name, "size": stat.st_size, "mtime": stat.st_mtime,
                     "modified": dt.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")},
            "copy": None, "format": None, "header": None, "missing_fields": [], "error": None,
            "validation": {"status": "not_run", "message": None},
        }
        try:
            snapshot = self.snapshotter.copy(path)
            result["copy"] = str(snapshot)
            data = snapshot.read_bytes()
            result.update(analyse_bytes(data))
            if result["format"] == "binary":
                result["validation"] = {"status": "pending", "message": "Checking the whole file…"}
                threading.Thread(target=self._validate, args=(key, data, result), daemon=True).start()
            else:
                result["validation"] = {"status": "not_applicable",
                                        "message": "Text save: header and requested country blocks are parsed on demand"}
        except binary.SaveFormatError as exc:
            result["error"] = {"code": exc.code, "message": str(exc), "offset": exc.offset}
            self.log.warning("Save %s not readable: %s (%s)", path.name, exc, exc.code)
            if exc.code == "in_progress":
                return result  # do not cache: retry later
        except OSError as exc:
            result["error"] = {"code": "io_error", "message": f"Could not copy/read the save: {exc}", "offset": None}
            return result
        with self._lock:
            self._results[key] = result
            if len(self._results) > 20:
                self._results.pop(next(iter(self._results)))
            return copy_module.deepcopy(result)

    def _validate(self, key: tuple, data: bytes, result: dict) -> None:
        started = time.perf_counter()
        changes: dict = {}
        try:
            version = (result.get("header") or {}).get("version")
            validation = binary.validate(data, version)
            update = {"status": validation.status, "message": validation.message,
                      "float_width": validation.float_width, "seconds": round(time.perf_counter() - started, 1)}
            if validation.status == "complete" and validation.float_width != result.get("float_width"):
                update["header_reparsed"] = True
                changes.update(header_with_width(data, validation.float_width))
            if validation.status == "invalid":
                changes["error"] = {"code": "corrupt", "message": validation.message,
                                    "offset": max((r.error_offset or 0) for r in validation.results)}
        except Exception as exc:  # never kill the thread silently
            update = {"status": "error", "message": f"Validation crashed: {exc}"}
            self.log.exception("Save validation failed for %s", key[0])
        with self._lock:
            result.update(changes)
            result["validation"] = update
        self.log.info("Save %s validated: %s (%s)", key[0], update["status"], update.get("message"))

    def country_values(self, path: Path, tag: str) -> dict:
        """Country Editor values for `tag` from the cached copy of a text save."""
        result = self.analyse(path)
        if result["error"]:
            raise binary.SaveFormatError(result["error"]["code"], result["error"]["message"])
        if result["format"] != "text":
            raise binary.SaveFormatError(
                "binary_values_unmapped", "This save is binary. Country values are only mapped for text saves - "
                "start the game with -force_text_save and save again.")
        data = Path(result["copy"]).read_bytes()
        block = text.country_block(data, tag)
        if block is None:
            raise binary.SaveFormatError("country_missing", f"Country {tag} does not exist in this save")
        return {"analysis": result, "values": text.country_values(block)}

    def wait_idle(self, timeout: float = 60.0) -> None:
        """Test helper: wait until no validation is pending."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if not any(r["validation"]["status"] == "pending" for r in self._results.values()):
                    return
            time.sleep(0.05)
        raise TimeoutError("save validation still pending")
