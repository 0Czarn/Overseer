"""Backend entry point: `python -m hoi4dbg [--port N] [--no-game] [--watch-stdin]`.

Prints one JSON line `{"event": "ready", "port": N}` to stdout once listening.
The API token is read from HOI4DBG_TOKEN (generated and printed when missing).
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import threading

from . import __version__, applog, paths
from .ic_history import IcHistory, IcRecorder
from .integration import NullIntegration
from .integration.hoi4 import Hoi4Integration
from .live.service import LiveService
from .reports import ReportStore
from .saves.reader import SaveAnalyzer, SaveSnapshotter
from .server import make_server
from .service import DebuggerService


def build_integration(disabled: bool):
    if disabled:
        return NullIntegration("Game integration disabled (--no-game)")
    return Hoi4Integration()


def wait_for_eof(fd: int) -> None:
    """Returns when the pipe `fd` is closed by the other side. On Windows without a blocking read: while one thread
    waits in a synchronous ReadFile on the pipe, loading a DLL in another thread waits for it (2026-10-21: the first
    `import numpy` for the campaign map hung the backend) - so the pipe is polled with PeekNamedPipe instead."""
    if os.name != "nt":
        while os.read(fd, 4096):
            pass
        return
    import ctypes
    import msvcrt
    import time
    from ctypes import wintypes
    handle = msvcrt.get_osfhandle(fd)
    peek = ctypes.windll.kernel32.PeekNamedPipe
    peek.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
                     ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    available = wintypes.DWORD()
    while peek(handle, None, 0, None, ctypes.byref(available), None):
        if available.value:   # nothing is sent over stdin; read it so the pipe never fills
            if not os.read(fd, available.value):
                return
        else:
            time.sleep(0.5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hoi4dbg", description="The OVERSEER backend")
    parser.add_argument("--port", type=int, default=0, help="TCP port on 127.0.0.1 (0 = random free port)")
    parser.add_argument("--no-game", action="store_true", help="never touch the game (tests / offline UI work)")
    parser.add_argument("--watch-stdin", action="store_true", help="exit when stdin is closed (parent died)")
    args = parser.parse_args(argv)

    token = os.environ.get("HOI4DBG_TOKEN") or secrets.token_urlsafe(24)
    data_dir = paths.data_dir()
    logger, ring = applog.setup(data_dir / "logs")
    logger.info("The OVERSEER backend %s starting (data dir: %s)", __version__, data_dir)

    saves = SaveAnalyzer(SaveSnapshotter(data_dir / "save-cache"), logger)
    service = DebuggerService(build_integration(args.no_game), ReportStore(data_dir / "reports"), ring,
                              logger, str(data_dir), saves=saves)
    if not args.no_game:
        service.live = LiveService(service.detect, service.player_save_values, data_dir / "live", logger)
        service.ic_recorder = IcRecorder(service.live, service.ic_history, logger, actions=service.action_snapshot)
        service.ic_recorder.start()
    server = make_server(service, token, args.port)
    port = server.server_address[1]

    if args.watch_stdin:
        def watch() -> None:
            wait_for_eof(sys.stdin.fileno())   # the parent process closed the pipe
            logger.info("Parent closed stdin - shutting down")
            server.shutdown()
        threading.Thread(target=watch, daemon=True).start()

    ready = {"event": "ready", "port": port}
    if "HOI4DBG_TOKEN" not in os.environ:
        ready["token"] = token  # manual runs only; Electron always supplies its own token
    print(json.dumps(ready), flush=True)
    logger.info("API listening on 127.0.0.1:%s", port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        logger.info("Backend stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
