"""Command-line driver for live calibration (same data dir as the app; read-only memory access).

python -m hoi4dbg.live status
python -m hoi4dbg.live start political_power
python -m hoi4dbg.live refine political_power save|command
python -m hoi4dbg.live read political_power [seconds]
python -m hoi4dbg.live change political_power delta|target N
python -m hoi4dbg.live reset political_power
python -m hoi4dbg.live auto political_power [seconds]
python -m hoi4dbg.live check political_power [seconds]
"""

from __future__ import annotations

import json
import sys
import time

from .. import applog, paths
from ..integration.hoi4 import Hoi4Integration
from ..reports import ReportStore
from ..saves.reader import SaveAnalyzer, SaveSnapshotter
from ..service import DebuggerService
from .service import LiveError, LiveService


def build() -> LiveService:
    data_dir = paths.data_dir()
    logger, ring = applog.setup(data_dir / "logs")
    saves = SaveAnalyzer(SaveSnapshotter(data_dir / "save-cache"), logger)
    svc = DebuggerService(Hoi4Integration(), ReportStore(data_dir / "reports"), ring, logger, str(data_dir), saves=saves)
    return LiveService(svc.detect, svc.player_save_values, data_dir / "live", logger)


def show(obj) -> None:
    print(json.dumps(obj, indent=1, default=str))


def stamp(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def auto(live: LiveService, field: str, duration: float) -> None:
    """Calibrates from the evidence the tester produces in game: a fresh save starts the scan,
    each documented console command and each newer save refines it. Once confirmed, every further
    command/save is used as an independent check of the live value."""
    end = time.time() + duration
    started_at = time.time()
    last_live = None
    last_error = None
    while time.time() < end:
        st = live.status()
        cal = st["calibrations"].get(field)
        try:
            if cal is None or not cal["current_process"] or cal["state"] == "failed":
                save = live._fresh_save(live._process())
                if save["file"]["mtime"] > started_at:
                    stamp(f"fresh save {save['file']['name']} -> scanning memory")
                    t = time.time()
                    res = live.start_calibration(field, background=False)
                    c = res["calibrations"].get(field) or {}
                    stamp(f"scan done in {time.time() - t:.0f}s: {c.get('message') or res['job']}")
                    print("SCAN_DONE", flush=True)
            else:
                for source in ("command", "save"):
                    try:
                        before = last_live
                        res = live.refine_calibration(field, source)
                        stamp(f"refine {source}: {res['steps'][-1]['source']} -> {res['message']}")
                        if res["state"] == "confirmed":
                            now = live.read(field)
                            stamp(f"LIVE {field} = {now['value']} ({now['encoding']}, {now['copies']} copies)"
                                  + (f"; previous live {before}" if before is not None else ""))
                            last_live = now["value"]
                    except LiveError as exc:
                        if exc.code not in ("no_command", "no_new_save", "stale_save", "save_in_progress"):
                            stamp(f"refine {source}: {exc.code}: {exc}")
                if cal["state"] == "confirmed":
                    v = live.read(field)["value"]
                    if v != last_live:
                        stamp(f"LIVE {field} changed: {last_live} -> {v}")
                        last_live = v
        except LiveError as exc:
            if exc.code not in ("stale_save", "save_in_progress") and str(exc) != last_error:
                stamp(f"{exc.code}: {exc}")
            last_error = str(exc)
            time.sleep(4)
        time.sleep(1)


def check(live: LiveService, field: str, duration: float) -> None:
    """Independent check of a confirmed location: for every new save of the running game, compares the
    save value with the memory value read right after the save appeared (game paused). Read-only."""
    end = time.time() + duration
    seen = time.time()
    last_error = None
    while time.time() < end:
        try:
            save = live._fresh_save(live._process())
            if save["file"]["mtime"] > seen:
                seen = save["file"]["mtime"]
                entry = save["values"].get(field) or {}
                now = live.read(field)
                diff = now["value"] - entry.get("value", float("nan"))
                verdict = "PASS" if abs(diff) <= 0.0005 else "FAIL"
                stamp(f"{verdict} {save['file']['name']} ({(save.get('in_game_date') or {}).get('text')}): "
                      f"save {entry.get('value')} / memory {now['value']} (diff {diff:+.5f})")
            last_error = None
        except LiveError as exc:
            if exc.code not in ("stale_save", "save_in_progress") and str(exc) != last_error:
                stamp(f"{exc.code}: {exc}")
            last_error = str(exc)
        time.sleep(1)


def main(argv: list[str]) -> int:
    live = build()
    cmd, args = argv[0], argv[1:]
    try:
        if cmd == "status":
            show(live.status())
        elif cmd == "start":
            t = time.time()
            show(live.start_calibration(args[0], background=False)["calibrations"][args[0]])
            print(f"scan took {time.time() - t:.1f}s")
        elif cmd == "refine":
            show(live.refine_calibration(args[0], args[1]))
        elif cmd == "reset":
            show(live.reset_calibration(args[0]))
        elif cmd == "read":
            end = time.time() + (float(args[1]) if len(args) > 1 else 0)
            while True:
                show(live.read(args[0]))
                if time.time() >= end:
                    break
                time.sleep(1)
        elif cmd == "change":
            op = live.create_operation(args[0], args[1], float(args[2]))
            show(op)
            while op["state"] in ("waiting_for_command", "executed"):
                time.sleep(0.5)
                op = live.poll_operation(op["id"])
            show(op)
        elif cmd == "check":
            check(live, args[0], float(args[1]) if len(args) > 1 else 1800)
        elif cmd == "auto":
            auto(live, args[0], float(args[1]) if len(args) > 1 else 1800)
        else:
            print(__doc__)
            return 2
    except LiveError as exc:
        print(f"ERROR {exc.code}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
