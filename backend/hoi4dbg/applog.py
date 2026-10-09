"""Application log: rotating file on disk + in-memory ring buffer for the UI."""

from __future__ import annotations

import collections
import datetime as dt
import logging
import logging.handlers
import threading
from pathlib import Path

LOGGER_NAME = "hoi4dbg"

LEVELS = {"debug": logging.DEBUG, "info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR}


class RingBufferHandler(logging.Handler):
    """Keeps the most recent log records as plain dicts."""

    def __init__(self, capacity: int = 2000) -> None:
        super().__init__()
        self._records: collections.deque[dict] = collections.deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._seq = 0

    def emit(self, record: logging.LogRecord) -> None:
        with self._lock:
            self._seq += 1
            self._records.append(
                {
                    "seq": self._seq,
                    "time": dt.datetime.fromtimestamp(record.created).isoformat(timespec="seconds"),
                    "level": record.levelname.lower(),
                    "origin": getattr(record, "origin", "backend"),
                    "message": record.getMessage(),
                }
            )

    def entries(self, limit: int = 200, min_level: str = "debug", after_seq: int = 0) -> list[dict]:
        threshold = LEVELS.get(min_level, logging.DEBUG)
        with self._lock:
            items = [
                r for r in self._records
                if r["seq"] > after_seq and LEVELS.get(r["level"], logging.INFO) >= threshold
            ]
        return items[-limit:] if limit > 0 else items


def setup(log_dir: Path | None, capacity: int = 2000) -> tuple[logging.Logger, RingBufferHandler]:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    ring = RingBufferHandler(capacity)
    logger.addHandler(ring)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(file_handler)
    return logger, ring
