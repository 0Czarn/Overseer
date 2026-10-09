"""Command-line driver for live calibration (same data dir as the app; read-only memory access).

python -m hoi4dbg.live status
python -m hoi4dbg.live start political_power
python -m hoi4dbg.live refine political_power save|command
python -m hoi4dbg.live read political_power [seconds]
python -m hoi4dbg.live change political_power delta|target N
python -m hoi4dbg.live reset political_power
python -m hoi4dbg.live auto all|field[,field...] [seconds] [--use-newest]
python -m hoi4dbg.live check political_power [seconds]
python -m hoi4dbg.live layout [field,field...]      (calibrate from the layout of an earlier game process)
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
from . import console
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


QUIET = ("already_confirmed", "no_command", "no_new_save", "stale_save", "save_in_progress", "unit_unverified")


def auto(live: LiveService, fields: list[str], duration: float, use_newest: bool = False) -> None:
    """Calibrates from the evidence the tester produces in game: a fresh save starts one scan for all
    fields, each documented console command (verified units only) and each newer save refines them.
    Once confirmed, every further step is an independent check of the live value."""
    end = time.time() + duration
    # Only saves written after start trigger a scan, unless the newest save of the running game may be used
    # (the tester confirms the game stayed paused since it was written).
    scanned_save = 0.0 if use_newest else time.time()
    last_live: dict[str, float] = {}
    last_error = None
    try_layout = True
    while time.time() < end:
        try:
            cals = live.status()["calibrations"]
            for field in fields:
                cal = cals.get(field)
                if cal is None or cal["state"] == "failed":
                    continue
                for source in ("command", "save"):
                    try:
                        res = live.refine_calibration(field, source)
                        stamp(f"{field} refine {source}: {res['steps'][-1]['source']} -> {res['message']}")
                        if source == "save" and res.get("unit_evidence"):
                            stamp(f"  {field} unit evidence: {res['unit_evidence'][-1]}")
                    except LiveError as exc:
                        if exc.code not in QUIET:
                            stamp(f"{field} refine {source}: {exc.code}: {exc}")
                if live.status()["calibrations"].get(field, {}).get("state") == "confirmed":
                    v = live.read(field)["value"]
                    if v != last_live.get(field):
                        stamp(f"LIVE {field}: {last_live.get(field)} -> {v}")
                        last_live[field] = v
            # Fields without a usable calibration: one scan per new save of the running game.
            cals = live.status()["calibrations"]
            pending = [f for f in fields if f not in cals or cals[f]["state"] == "failed"]
            if pending:
                save = live._fresh_save(live._process())
                if save["file"]["mtime"] > scanned_save and try_layout:
                    try_layout = False
                    stamp(f"fresh save {save['file']['name']} -> layout of an earlier process for {', '.join(pending)}")
                    t = time.time()
                    try:
                        res = live.calibrate_from_layout(pending)["layout"]
                    except LiveError as exc:
                        stamp(f"layout skipped: {exc.code}: {exc}")
                    else:
                        stamp(f"layout done in {time.time() - t:.0f}s ({res['reference']}): found {res['found']}, "
                              f"not aligned {res['not_aligned']}, skipped {res['skipped']}")
                        scanned_save = save["file"]["mtime"]
                        print("SCAN_DONE", flush=True)
                        continue
                if save["file"]["mtime"] > scanned_save:
                    scanned_save = save["file"]["mtime"]
                    stamp(f"fresh save {save['file']['name']} -> scanning memory for {', '.join(pending)}")
                    t = time.time()
                    try:
                        res = live.start_calibrations(pending, background=False)
                    except LiveError as exc:
                        stamp(f"scan skipped: {exc.code}: {exc}")
                    else:
                        stamp(f"scan done in {time.time() - t:.0f}s; skipped: {res['job'].get('skipped')}")
                        for f in pending:
                            if f in res["calibrations"]:
                                stamp(f"  {f}: {res['calibrations'][f]['message']}")
                        print("SCAN_DONE", flush=True)
            last_error = None
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
        elif cmd == "layout":
            t = time.time()
            res = live.calibrate_from_layout(args[0].split(",") if args else None)
            show(res["layout"])
            for f, c in res["calibrations"].items():
                print(f"{f:16} {c['state']:10} {c['message']}")
            print(f"took {time.time() - t:.1f}s")
        elif cmd == "check":
            check(live, args[0], float(args[1]) if len(args) > 1 else 1800)
        elif cmd == "auto":
            fields = list(console.COMMANDS) if args[0] == "all" else args[0].split(",")
            rest = [a for a in args[1:] if a != "--use-newest"]
            auto(live, fields, float(rest[0]) if rest else 1800, use_newest="--use-newest" in args)
        else:
            print(__doc__)
            return 2
    except LiveError as exc:
        print(f"ERROR {exc.code}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
