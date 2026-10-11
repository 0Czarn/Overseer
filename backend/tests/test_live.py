import ctypes
import logging
import os
import struct
import sys
import time
import unittest
from contextlib import contextmanager
from unittest import mock
from pathlib import Path

from hoi4dbg.integration import memory
from hoi4dbg.integration.memory import ENCODINGS, needles_for, scan
from hoi4dbg.live import console, layout, pointers
from hoi4dbg.live.calibration import CalibrationError, FieldCalibration
from hoi4dbg.live.service import LiveError, LiveService

from helpers import TempDirMixin

BASE = 0x10_0000


class FakeMemory:
    """Two regions of fake process memory; supports the read-only interface used by the scanner."""

    def __init__(self, size=0x4000):
        self.regions_data = {BASE: bytearray(size), BASE + 0x10_0000: bytearray(size)}
        self.readable = True

    def regions(self):
        return [(b, len(d)) for b, d in self.regions_data.items()]

    def read(self, address, size):
        if not self.readable:
            return None
        for base, data in self.regions_data.items():
            if base <= address and address + size <= base + len(data):
                return bytes(data[address - base:address - base + size])
        return None

    def put(self, address, fmt, value):
        for base, data in self.regions_data.items():
            if base <= address < base + len(data):
                struct.pack_into("<" + fmt, data, address - base, value)
                return
        raise AssertionError("address outside fake memory")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


def fixed(v):
    return round(v * 1000)


class MemoryModuleTests(unittest.TestCase):
    def test_module_never_requests_write_access(self):
        source = Path(memory.__file__).read_text(encoding="utf-8")
        for forbidden in ("WriteProcessMemory", "VirtualProtectEx", "PROCESS_VM_WRITE", "PROCESS_VM_OPERATION",
                          "PROCESS_ALL_ACCESS", "CreateRemoteThread"):
            self.assertNotIn(forbidden, source)
        self.assertEqual(memory.ACCESS_RIGHTS, 0x0400 | 0x0010)

    def test_encodings_round_trip(self):
        for enc in ENCODINGS.values():
            if enc.scale == 1:
                continue
            packed = enc.pack(12.324)
            self.assertAlmostEqual(enc.unpack(packed), 12.324, places=4)
        self.assertEqual(ENCODINGS["fixed32_1000"].pack(12.324), struct.pack("<i", 12324))
        self.assertIsNone(ENCODINGS["fixed32_1000"].pack(1e12))  # does not fit: no needle, no crash

    def test_tolerance_needles(self):
        """Regression: fuel (save 304092.84835, a double in memory) and manpower (plain integer) were never found."""
        mem = FakeMemory()
        mem.put(BASE + 0x10, "d", 304092.848351234)   # more precision than the save prints
        mem.put(BASE + 0x40, "d", 304092.8484)        # outside +-0.000005
        mem.put(BASE + 0x80, "i", 119692338)
        hits = scan(mem, needles_for(304092.84835, tolerance=0.000005))
        self.assertEqual({k: v for k, v in hits.items() if v}, {"float64": [BASE + 0x10]})
        self.assertNotIn("fixed64_1000", hits)  # x1000 cannot hold 5 decimals -> not searched at all
        # x32768 (binary-save type of fuel/experience): the save truncates to 5 decimals, memory holds raw/32768
        mem.put(BASE + 0x200, "q", 9964514455)  # 304092.848358...
        hits = scan(mem, needles_for(304092.84835, tolerance=0.00001))
        self.assertEqual(hits["fixed64_32768"], [BASE + 0x200])
        hits = scan(mem, needles_for(119692338.0, tolerance=0.0005))
        self.assertEqual(hits["int32"], [BASE + 0x80])
        self.assertNotIn("int32", needles_for(12.324, tolerance=0.0005))  # not an integer -> not an int field
        mem.put(BASE + 0x100, "f", 119707338.0)  # float32 stores 119707336: outside +-0.0005, still the field
        hits = scan(mem, needles_for(119707338.0, tolerance=0.0005))
        self.assertEqual(hits["float32"], [BASE + 0x100])

    def test_zero_has_no_needles(self):
        self.assertEqual(needles_for(0.0), {})

    def test_scan_finds_aligned_hits_across_chunks_only(self):
        mem = FakeMemory()
        mem.put(BASE + 0x0ffc, "i", 12324)          # straddles a 4 KiB chunk border
        mem.put(BASE + 0x2001, "i", 12324)          # unaligned -> ignored
        mem.put(BASE + 0x10_0000 + 8, "i", 12324)   # second region
        hits = scan(mem, {"x": (struct.pack("<i", 12324), 4)}, chunk=0x1000)
        self.assertEqual(hits["x"], [BASE + 0x0ffc, BASE + 0x10_0000 + 8])

    @unittest.skipUnless(sys.platform == "win32", "WinAPI")
    def test_reads_own_process_memory(self):
        marker = ctypes.create_string_buffer(b"HOI4DBG-SELFTEST-" + os.urandom(8).hex().encode())
        with memory.ProcessMemory(os.getpid()) as mem:
            self.assertEqual(mem.read(ctypes.addressof(marker), len(marker.raw)), marker.raw)
            self.assertIsNone(mem.read(0, 16))
            self.assertIsNone(mem.read(ctypes.addressof(marker), memory.MAX_READ + 1))

    @unittest.skipUnless(sys.platform == "win32", "WinAPI")
    def test_open_missing_process_fails_cleanly(self):
        with self.assertRaises(memory.MemoryAccessError):
            memory.ProcessMemory(0xFFFFFFF0)


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.mem = FakeMemory()
        self.real = BASE + 0x100
        self.mem.put(self.real, "i", fixed(12.324))
        self.mem.put(BASE + 0x800, "i", fixed(12.324))     # decoy that never changes
        self.mem.put(BASE + 0x900, "q", fixed(12.324))     # decoy in another encoding
        self.cal = FieldCalibration("political_power", "GER", 1, "t")

    def change(self, value):
        self.mem.put(self.real, "i", fixed(value))

    def test_confirms_only_after_three_distinct_values(self):
        self.cal.start(self.mem, 12.324, "save")
        self.assertEqual(self.cal.state, "candidates")
        self.change(13.324)
        self.cal.refine(self.mem, 13.324, "pp 1")
        self.assertEqual(self.cal.state, "candidates")  # one survivor, but only two values seen
        self.change(18.324)
        self.cal.refine(self.mem, 18.324, "pp 5")
        self.assertEqual(self.cal.state, "confirmed")
        self.assertEqual(self.cal.encoding, "fixed32_1000")
        self.assertEqual(self.cal.candidates["fixed32_1000"], [self.real])
        self.change(19.5)
        self.assertEqual(self.cal.read(self.mem)["value"], 19.5)

    def test_negative_value_separates_32_from_64_bit(self):
        self.cal.start(self.mem, 12.324, "save")
        self.change(13.324)
        self.cal.refine(self.mem, 13.324, "pp 1")
        self.assertIsNotNone(self.cal.width_note)
        self.change(-1.0)  # int32 write leaves the upper 4 bytes at zero
        self.cal.refine(self.mem, -1.0, "pp -14.324")
        self.assertEqual(list(self.cal.candidates), ["fixed32_1000"])
        self.assertIsNone(self.cal.width_note)
        self.assertEqual(self.cal.state, "confirmed")

    def test_same_value_twice_is_not_evidence(self):
        self.cal.start(self.mem, 12.324, "save")
        for _ in range(3):
            self.cal.refine(self.mem, 12.324, "save again")
        self.assertEqual(self.cal.state, "candidates")

    def test_refine_accepts_save_rounding_but_nothing_more(self):
        """Regression: memory holds PP with 5 decimals (fixed64_100000), saves round to 3; an exact byte
        comparison would reject the true location once game days pass."""
        mem = FakeMemory()
        real, decoy = BASE + 0x100, BASE + 0x300
        for a in (real, decoy):
            mem.put(a, "q", 70032400)
        cal = FieldCalibration("political_power", "GER", 1, "t")
        cal.start(mem, 700.324, "save")
        mem.put(real, "q", 71232412)    # 712.32412 in memory, save says 712.324
        mem.put(decoy, "q", 71232600)   # 712.326: outside the save's precision
        cal.refine(mem, 712.324, "save")
        self.assertEqual(cal.candidates, {"fixed64_100000": [real]})

    def test_fails_when_value_moved_elsewhere(self):
        self.cal.start(self.mem, 12.324, "save")
        self.cal.refine(self.mem, 99.0, "wrong expectation")
        self.assertEqual(self.cal.state, "failed")

    def test_read_detects_inconsistent_copies_and_lost_memory(self):
        second = BASE + 0x200
        self.mem.put(second, "i", fixed(12.324))
        self.cal.start(self.mem, 12.324, "save")
        for v in (13.324, 14.324):
            self.change(v)
            self.mem.put(second, "i", fixed(v))
            self.cal.refine(self.mem, v, "cmd")
        self.assertEqual(self.cal.state, "confirmed")
        self.assertEqual(self.cal.read(self.mem)["copies"], 2)
        self.mem.put(second, "i", 1)
        with self.assertRaises(CalibrationError) as ctx:
            self.cal.read(self.mem)
        self.assertEqual(ctx.exception.code, "inconsistent")
        self.mem.readable = False
        with self.assertRaises(CalibrationError) as ctx:
            self.cal.read(self.mem)
        self.assertEqual(ctx.exception.code, "unreadable")

    def test_store_round_trip(self):
        self.cal.start(self.mem, 12.324, "save")
        self.cal.history_mark = (5.0, 3)
        restored = FieldCalibration.from_store(self.cal.to_store())
        self.assertEqual(restored.candidates, self.cal.candidates)
        self.assertEqual(restored.history_mark, (5.0, 3))
        self.assertEqual(restored.state, "candidates")


class ConsoleTests(TempDirMixin, unittest.TestCase):
    def test_build_and_parse_documented_command(self):
        self.assertEqual(console.build_command("political_power", 10), "pp 10")
        self.assertEqual(console.build_command("political_power", -3.0), "pp -3")
        for bad in (0, 1.5, 6000):
            with self.assertRaises(ValueError):
                console.build_command("political_power", bad)
        self.assertEqual(console.build_command("stability", 0.05), "add_stability 5")  # 1 unit = 0.01
        self.assertEqual(console.build_command("stability", -0.03), "add_stability -3")
        with self.assertRaises(ValueError):
            console.build_command("stability", 0.005)  # half a unit
        self.assertEqual(console.parse_command("  PP   10 "), [("political_power", 10.0, 10.0)])
        self.assertEqual(console.parse_command("political_power 2"), [("political_power", 2.0, 2.0)])  # alias
        self.assertEqual(console.parse_command("pp ten"), [])
        self.assertEqual(console.parse_command("ai"), [])
        self.assertEqual(console.parse_command("st -5"), [("stability", -5.0, -0.05)])

    def test_xp_changes_all_three_experience_fields(self):
        self.assertEqual(sorted(f for f, _, _ in console.parse_command("xp 10")),
                         ["air_experience", "army_experience", "navy_experience"])

    def test_history_detects_new_entries_only(self):
        path = self.tmp / console.HISTORY_FILE
        path.write_text("ai\r\npp 10\r\n", encoding="utf-8")
        hist = console.ConsoleHistory(path)
        mark = hist.mark()
        self.assertEqual(hist.new_entries(mark), [])
        self.assertFalse(hist.executed_since(mark, "pp 10"))  # old entry is not a new execution
        time.sleep(0.02)
        path.write_text("ai\r\npp 10\r\nfow\r\npp 5\r\n", encoding="utf-8")
        os.utime(path, (time.time() + 1, time.time() + 1))
        self.assertEqual(hist.new_entries(mark), ["fow", "pp 5"])
        self.assertTrue(hist.executed_since(mark, "PP 5"))
        self.assertIsNone(console.ConsoleHistory(self.tmp / "missing.txt").mark())


class LiveServiceTests(TempDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.install = self.tmp / "game"
        self.install.mkdir()
        self.history = self.install / console.HISTORY_FILE
        self.history.write_text("ai\r\n", encoding="utf-8")
        self.mem = FakeMemory()
        self.addr = BASE + 0x40
        self.pp = 12.324
        self.mem.put(self.addr, "i", fixed(self.pp))
        self.stab_addr = BASE + 0x80
        self.stab = 0.7
        self.mem.put(self.stab_addr, "q", 70000)  # fixed64_100000
        self.process = {"pid": 7, "path": str(self.install / "hoi4.exe"), "started": "2026-10-09T12:00:00+00:00"}
        self.save_mtime = 100.0
        self.save_category = "current_session"
        self.clock = time.time()
        os.utime(self.history, (self.clock, self.clock))
        self.svc = self.make()

    def make(self):
        return LiveService(self.detect, self.save_values, self.tmp / "live", logging.getLogger("test"),
                           open_memory=lambda pid: self.mem, clock=lambda: self.clock)

    def detect(self):
        return {"process": self.process, "install": {"path": str(self.install)}}

    def save_values(self):
        return {"source": "save", "data": {
            "tag": "GER", "player_tag": "GER", "file": {"name": "s.hoi4", "mtime": self.save_mtime},
            "in_game_date": {"text": "1936.1.1.12"}, "freshness": {"category": self.save_category},
            "values": {"political_power": {"status": "read", "value": self.pp},
                       "stability": {"status": "read", "value": self.stab},
                       "navy_experience": {"status": "absent", "value": None}}}}

    def set_pp(self, value):
        self.pp = value
        self.mem.put(self.addr, "i", fixed(value))

    def type_command(self, cmd):
        with self.history.open("a", encoding="utf-8") as f:
            f.write(cmd + "\r\n")
        self.clock += 10
        os.utime(self.history, (self.clock, self.clock))

    def calibrate(self):
        self.svc.start_calibration("political_power", background=False)
        self.type_command("pp 1")
        self.set_pp(13.324)
        self.svc.refine_calibration("political_power", "command")
        self.clock += 10
        self.set_pp(14.5)  # e.g. a day passed
        self.save_mtime += 50
        self.svc.refine_calibration("political_power", "save")
        cal = self.svc.status()["calibrations"]["political_power"]
        self.assertEqual(cal["state"], "confirmed", cal)

    def test_refuses_stale_save_and_missing_game(self):
        self.save_category = "previous_session"
        with self.assertRaises(LiveError) as ctx:
            self.svc.start_calibration("political_power", background=False)
        self.assertEqual(ctx.exception.code, "stale_save")
        self.process = None
        with self.assertRaises(LiveError) as ctx:
            self.svc.read("political_power")
        self.assertEqual(ctx.exception.code, "game_not_running")

    def test_full_calibration_then_verified_change(self):
        self.calibrate()
        self.assertEqual(self.svc.read("political_power")["value"], 14.5)
        op = self.svc.create_operation("political_power", "target", 20.5)
        self.assertEqual((op["command"], op["expected"]), ("pp 6", 20.5))
        self.assertEqual(self.svc.poll_operation(op["id"])["state"], "waiting_for_command")
        self.type_command("pp 6")
        self.set_pp(20.5)
        done = self.svc.poll_operation(op["id"])
        self.assertEqual(done["state"], "confirmed", done)
        self.assertEqual(done["actual"], 20.5)

    def test_change_not_applied_is_reported(self):
        self.calibrate()
        op = self.svc.create_operation("political_power", "delta", 5)
        self.type_command("pp 5")
        self.assertEqual(self.svc.poll_operation(op["id"])["state"], "executed")  # grace period
        self.clock += 10
        res = self.svc.poll_operation(op["id"])
        self.assertEqual(res["state"], "mismatch")
        self.assertIn("did not change", res["message"])

    def test_target_must_be_whole_number_away_and_command_must_appear(self):
        self.calibrate()
        with self.assertRaises(LiveError) as ctx:
            self.svc.create_operation("political_power", "target", 20)
        self.assertEqual(ctx.exception.code, "not_integer")
        op = self.svc.create_operation("political_power", "delta", 2)
        self.type_command("pp 3")  # a different command is not this operation
        self.assertEqual(self.svc.poll_operation(op["id"])["state"], "waiting_for_command")
        self.clock += 700
        self.assertEqual(self.svc.poll_operation(op["id"])["state"], "expired")

    def test_calibration_is_bound_to_process_and_persisted(self):
        self.calibrate()
        again = self.make()
        self.assertEqual(again.read("political_power")["value"], 14.5)
        self.process = {**self.process, "pid": 8}
        with self.assertRaises(LiveError) as ctx:
            again.read("political_power")
        self.assertEqual(ctx.exception.code, "process_changed")
        # Regression: the confirmed address was lost with the discarded calibration; the layout keeps it
        rec = self.make().layouts.records()[-1]
        self.assertEqual((rec["pid"], rec["tag"], rec["fields"]["political_power"]),
                         (7, "GER", {"encoding": "fixed32_1000", "address": self.addr}))

    def test_calibration_of_other_process_is_discarded_on_disk(self):
        """Regression: a calibration from an earlier PID stayed stored and was offered as 'candidates'."""
        self.svc.start_calibration("political_power", background=False)
        self.process = {**self.process, "pid": 9, "started": "2026-10-09T14:32:57+00:00"}
        st = self.make().status()
        self.assertEqual(st["calibrations"], {})
        self.assertEqual(st["invalidated"]["political_power"]["pid"], 7)
        self.assertEqual(self.make().calibrations, {})  # gone from calibrations.json too
        values = self.make().values()["political_power"]
        self.assertEqual((values["status"], values["code"]), ("unavailable", "not_calibrated"))

    def test_calibration_is_discarded_when_game_exits(self):
        self.calibrate()
        self.process = None
        st = self.svc.status()
        self.assertEqual((st["error"]["code"], st["calibrations"]), ("game_not_running", {}))
        self.assertIn("ended", st["invalidated"]["political_power"]["message"])

    def test_restart_with_same_pid_is_detected(self):
        self.calibrate()
        self.process = {**self.process, "started": "2026-10-09T15:00:00+00:00"}
        with self.assertRaises(LiveError) as ctx:
            self.svc.read("political_power")
        self.assertEqual(ctx.exception.code, "process_changed")

    def test_unconfirmed_location_is_never_read(self):
        self.svc.start_calibration("political_power", background=False)
        values = self.svc.values()["political_power"]
        self.assertEqual((values["status"], values["code"]), ("unavailable", "unverified"))
        self.assertNotIn("value", values)

    def test_one_scan_calibrates_several_fields_and_records_command_units(self):
        # behave as before the unit of add_stability was verified
        with mock.patch.dict(console.COMMANDS, {"stability": {**console.COMMANDS["stability"], "factor": None}}):
            self._calibrate_with_unverified_unit()
        # with the verified unit (1 = 0.01) the app can prepare and verify a stability change
        op = self.svc.create_operation("stability", "target", 0.73)
        self.assertEqual((op["command"], op["expected"]), ("add_stability 5", 0.73))
        self.type_command("add_stability 5")
        self.mem.put(self.stab_addr, "q", 73000)
        self.assertEqual(self.svc.poll_operation(op["id"])["state"], "confirmed")

    def _calibrate_with_unverified_unit(self):
        self.svc.start_calibrations(["political_power", "stability", "navy_experience"], background=False)
        st = self.svc.status()
        self.assertEqual(sorted(st["calibrations"]), ["political_power", "stability"])
        self.assertIn("navy_experience", st["job"]["skipped"])
        # unit of add_stability unknown: command evidence is refused, save evidence records the ratio
        self.type_command("add_stability -5")
        self.stab = 0.65
        self.mem.put(self.stab_addr, "q", 65000)
        with self.assertRaises(LiveError) as ctx:
            self.svc.refine_calibration("stability", "command")
        self.assertEqual(ctx.exception.code, "unit_unverified")
        self.save_mtime += 10
        res = self.svc.refine_calibration("stability", "save")
        self.assertEqual(res["unit_evidence"][0]["ratio"], 0.01)
        self.assertEqual(res["unit_evidence"][0]["commands"], ["add_stability -5"])
        self.type_command("st 3")
        self.stab = 0.68
        self.mem.put(self.stab_addr, "q", 68000)
        self.save_mtime += 10
        res = self.svc.refine_calibration("stability", "save")
        self.assertEqual(res["state"], "confirmed", res)
        self.assertEqual(self.svc.read("stability")["value"], 0.68)
        with self.assertRaises(LiveError) as ctx:
            self.svc.create_operation("stability", "delta", 0.05)
        self.assertEqual(ctx.exception.code, "unit_unverified")

    def test_confirmed_location_is_not_refined_by_stale_evidence(self):
        """Regression: a confirmed PP location was refined with old console commands against an old
        baseline after game days passed, and ended up 'failed'."""
        self.calibrate()
        self.clock += 100
        self.set_pp(40.0)          # days passed
        self.type_command("pp 3")  # entered later, applied to a different baseline
        self.set_pp(43.0)
        with self.assertRaises(LiveError) as ctx:
            self.svc.refine_calibration("political_power", "command")
        self.assertEqual(ctx.exception.code, "already_confirmed")
        self.assertEqual(self.svc.read("political_power")["value"], 43.0)

    def test_save_being_written_has_its_own_code(self):
        self.save_values = lambda: {"source": "unavailable", "note": "still writing [in_progress]",
                                    "data": {"error": {"code": "in_progress", "message": "still writing"}}}
        with self.assertRaises(LiveError) as ctx:
            self.make().start_calibration("political_power", background=False)
        self.assertEqual(ctx.exception.code, "save_in_progress")

    def test_refine_command_requires_new_pp_entry(self):
        self.svc.start_calibration("political_power", background=False)
        with self.assertRaises(LiveError) as ctx:
            self.svc.refine_calibration("political_power", "command")
        self.assertEqual(ctx.exception.code, "no_command")


class LayoutTests(TempDirMixin, unittest.TestCase):
    """Calibration of a new game process from the layout confirmed in an earlier one."""

    FIELDS = {"political_power": ("fixed64_100000", 0x40, 772.3), "stability": ("fixed64_100000", 0x80, 0.71),
              "command_power": ("fixed64_100000", 0x1000, 72.682), "fuel": ("fixed64_32768", 0x2000, 305592.8483581543)}

    def setUp(self):
        super().setUp()
        self.install = self.tmp / "game"
        self.install.mkdir()
        (self.install / console.HISTORY_FILE).write_text("", encoding="utf-8")
        self.mem = FakeMemory(0x8000)
        self.process = {"pid": 7, "path": str(self.install / "hoi4.exe"), "started": "a"}
        self.values = {f: v for f, (_, _, v) in self.FIELDS.items()}
        self.svc = self.make()

    def make(self):
        return LiveService(self.detect, self.save_values, self.tmp / "live", logging.getLogger("test"),
                           open_memory=lambda pid: self.mem)

    def detect(self):
        return {"process": self.process, "install": {"path": str(self.install), "version": {"display": "v1.19.3"}}}

    def save_values(self):
        return {"source": "save", "data": {
            "player_tag": "GER", "file": {"name": "s.hoi4", "mtime": 100.0}, "in_game_date": {"text": "1936.1.30.1"},
            "freshness": {"category": "current_session"},
            "values": {f: {"status": "read", "value": v} for f, v in self.values.items()}}}

    def put(self, base, fields=None):
        for f, (enc, off, value) in (fields or self.FIELDS).items():
            self.mem.put(base + off, "q", round(value * ENCODINGS[enc].scale))

    def record_earlier_process(self, base=BASE):
        self.svc.layouts.record({"pid": 3, "started": "x", "version": "v1.19.3"}, "GER",
                                {f: (enc, base + off) for f, (enc, off, _) in self.FIELDS.items()})

    def test_new_process_is_calibrated_from_recorded_distances(self):
        self.record_earlier_process(BASE)
        self.put(BASE + 0x100)                      # new process: same object, other heap address
        self.mem.put(BASE + 0x3000, "q", 71000)     # stray copies of common values elsewhere
        self.mem.put(BASE + 0x10_0000 + 0x80, "q", 71000)
        res = self.svc.calibrate_from_layout()
        self.assertEqual(res["layout"]["found"], sorted(self.FIELDS))
        for f, (_, off, value) in self.FIELDS.items():
            cal = res["calibrations"][f]
            self.assertEqual((cal["state"], cal["addresses"]), ("confirmed", [hex(BASE + 0x100 + off)]), f)
            self.assertAlmostEqual(self.svc.read(f)["value"], value, places=5)
        self.assertEqual(self.svc.status()["calibrations"]["stability"]["confirmed_by"], "process 3")
        # the new process is recorded too and becomes the reference for the next one
        self.assertEqual(self.svc.layouts.records()[-1]["pid"], 7)

    def test_field_off_the_recorded_distance_falls_back_to_normal_calibration(self):
        self.record_earlier_process(BASE)
        moved = dict(self.FIELDS, fuel=("fixed64_32768", 0x3800, self.FIELDS["fuel"][2]))
        self.put(BASE + 0x100, moved)
        res = self.svc.calibrate_from_layout()
        self.assertEqual(res["layout"]["not_aligned"], ["fuel"])
        fuel = res["calibrations"]["fuel"]
        self.assertEqual((fuel["state"], fuel["candidate_count"]), ("candidates", 1))
        self.assertEqual(res["calibrations"]["command_power"]["state"], "confirmed")
        with self.assertRaises(LiveError) as ctx:
            self.svc.read("fuel")
        self.assertEqual(ctx.exception.code, "unverified")

    def test_two_identical_clusters_are_ambiguous(self):
        self.record_earlier_process(BASE)
        self.put(BASE + 0x100)
        self.put(BASE + 0x10_0000 + 0x100)          # e.g. a copy of the country object
        res = self.svc.calibrate_from_layout()
        self.assertEqual(res["layout"]["found"], [])
        self.assertEqual(res["layout"]["ambiguous"], sorted(self.FIELDS))
        self.assertTrue(all(c["state"] != "confirmed" for c in res["calibrations"].values()))

    def test_too_few_aligned_fields_is_not_evidence(self):
        self.record_earlier_process(BASE)
        self.put(BASE + 0x100, {f: self.FIELDS[f] for f in ("political_power", "stability")})
        self.put(BASE + 0x500, {f: self.FIELDS[f] for f in ("command_power", "fuel")})
        res = self.svc.calibrate_from_layout()
        self.assertEqual(res["layout"]["found"], [])

    def test_layout_of_other_version_country_or_same_process_is_not_used(self):
        self.svc.layouts.record({"pid": 3, "started": "x", "version": "v1.18"}, "GER",
                                {f: (enc, BASE + off) for f, (enc, off, _) in self.FIELDS.items()})
        self.svc.layouts.record({"pid": 4, "started": "x", "version": "v1.19.3"}, "SOV",
                                {f: (enc, BASE + off) for f, (enc, off, _) in self.FIELDS.items()})
        self.svc.layouts.record({**self.process, "version": "v1.19.3"}, "GER",
                                {f: (enc, BASE + off) for f, (enc, off, _) in self.FIELDS.items()})
        with self.assertRaises(LiveError) as ctx:
            self.svc.calibrate_from_layout()
        self.assertEqual(ctx.exception.code, "no_layout")


class CountryTableTests(TempDirMixin, unittest.TestCase):
    """Reads through the game's country table (pointers.py) - no calibration needed."""

    MODULE = BASE + 0x10_0000  # fake hoi4.exe base (second fake region)

    def setUp(self):
        super().setUp()
        self.install = self.tmp / "game"
        (self.install / "common" / "country_tags").mkdir(parents=True)
        (self.install / "common" / "country_tags" / "00_countries.txt").write_text(
            'GER\t= "countries/Germany.txt"\n# ITA = commented out\nENG = "countries/United Kingdom.txt"\n'
            'ITA = "countries/Italy.txt"\n', encoding="utf-8")
        (self.install / "common" / "country_tags" / "zz_dynamic_countries.txt").write_text('D01 = "x"\n')
        (self.install / console.HISTORY_FILE).write_text("", encoding="utf-8")
        self.mem = FakeMemory(0x8000)
        self.mem.modules = lambda: {"hoi4.exe": (self.MODULE, self.MODULE + 0x8000)}
        self.version = "Operation Postern v1.19.3.0.c01a (5632)"
        self.save_player = "GER"   # stale save: the player switched to ITA since
        self.process = {"pid": 7, "path": str(self.install / "hoi4.exe"), "started": "2026-10-09T10:00:00+00:00"}
        self.logs = self.tmp / "logs"
        self.game_log("SINGLEPLAYER")
        # hoi4.exe+rva -> table object; +0x310 -> array; slot i -> country objects
        rva, slot = pointers.COUNTRY_TABLE
        self.mem.regions_data[self.MODULE] = bytearray(max(0x8000, rva + 8))
        table, array = BASE + 0x100, BASE + 0x200
        self.mem.put(self.MODULE + rva, "Q", table)
        self.mem.put(table + slot, "Q", array)
        self.countries = {"GER": BASE + 0x1000, "ITA": BASE + 0x3000}
        for i, tag in enumerate(["GER", "ENG", "ITA"], start=1):
            if tag in self.countries:
                self.mem.put(array + 8 * i, "Q", self.countries[tag])
        self.put_country("GER", stability=0.71, pp=772.3, ai=1)
        self.put_country("ITA", stability=0.6, pp=31.1972, ai=0)
        self.svc = LiveService(self.detect, self.save_values, self.tmp / "live", logging.getLogger("test"),
                               open_memory=lambda pid: self.mem)

    def put_country(self, tag, stability, pp, ai=1):
        c = self.countries[tag]
        self.mem.put(c + pointers.PLAYER_FLAG[0], "Q", c + 0x1C00)  # visibility sub-object (0 = visible)
        self.mem.regions_data[BASE][c - BASE + 0x1C00 + pointers.PLAYER_FLAG[1]] = ai
        self.mem.put(c + 0x10D0, "q", round(stability * 100000))
        self.mem.put(c + 0xF90, "Q", c + 0x1800)           # politics object
        self.mem.put(c + 0x1800 + 0xE0, "q", round(pp * 100000))

    def detect(self):
        return {"process": self.process, "install": {"path": str(self.install), "version": {"display": self.version}},
                "userdata": {"logs_dir": str(self.logs)}}

    def game_log(self, mode):
        self.logs.mkdir(exist_ok=True)
        (self.logs / "game.log").write_text(f"[19:59:34][1936.02.01.03][frontend.cpp:682]: \n\n\t\t[[ Launching {mode}-game ]]\n"
                                            "\tStart-date: 1936.2.1.3\n", encoding="utf-8")

    def save_values(self):
        return {"source": "save", "data": {"player_tag": self.save_player, "file": {"name": "s.hoi4", "mtime": 1.0},
                                           "freshness": {"category": "current_session"}, "values": {}}}

    def test_tag_order_follows_files_and_lines(self):
        self.assertEqual(pointers.tag_order(self.install), ["GER", "ENG", "ITA", "D01"])  # gamefiles.tag_order

    def test_player_and_any_country_without_calibration(self):
        res = self.svc.read("stability")
        self.assertEqual((res["value"], res["tag"], res["method"]), (0.6, "ITA", "country_table"))
        self.assertEqual(self.svc.read("political_power", "GER")["value"], 772.3)
        values = self.svc.values("GER")
        self.assertEqual(values["stability"]["value"], 0.71)
        self.assertEqual(values["manpower"]["status"], "unavailable")   # not in the country table map

    def test_player_comes_from_the_ai_flag_not_the_stale_save(self):
        self.assertEqual(self.svc.players(), ["ITA"])          # ENG has no object (slot empty)
        self.assertEqual(self.svc.status()["players"], ["ITA"])
        self.assertEqual(self.svc.read("stability")["tag"], "ITA")

    def test_session_lists_countries_owning_states(self):
        self.mem.put(self.countries["GER"] + pointers.OWNED_STATES, "i", 12)
        self.mem.put(self.countries["ITA"] + pointers.OWNED_STATES, "i", 0)   # annexed
        res = self.svc.session()
        self.assertEqual(res["states"], {"GER": 12, "ITA": 0})               # ENG: empty slot
        self.assertEqual((res["game_mode"], res["players"]), ("SINGLEPLAYER", ["ITA"]))

    def test_session_rejects_implausible_state_counts(self):
        self.mem.put(self.countries["GER"] + pointers.OWNED_STATES, "i", -5)
        with self.assertRaises(LiveError) as ctx:
            self.svc.session()
        self.assertEqual(ctx.exception.code, "no_country_table")

    def test_player_falls_back_to_the_save_when_the_flag_is_unreadable(self):
        for c in self.countries.values():
            self.mem.put(c + pointers.PLAYER_FLAG[0], "Q", 0)
        self.assertEqual(self.svc.players(), [])
        self.assertEqual(self.svc.read("stability")["tag"], "GER")

    def put_string(self, at, text, heap):
        """MSVC std::string at `at`: short strings inline, longer ones in a heap buffer at `heap`."""
        raw = text.encode()
        if len(raw) < 16:
            self.mem.regions_data[BASE][at - BASE:at - BASE + len(raw)] = raw
            cap = 15
        else:
            self.mem.regions_data[BASE][heap - BASE:heap - BASE + len(raw)] = raw
            self.mem.put(at, "Q", heap)
            cap = len(raw)
        self.mem.put(at + 16, "Q", len(raw))
        self.mem.put(at + 24, "Q", cap)

    def test_focus_current_progress_and_completed(self):
        c = self.countries["ITA"]
        state, cur_def, done_def, array = BASE + 0x2000, BASE + 0x2100, BASE + 0x2200, BASE + 0x2300
        self.mem.put(c + pointers.FOCUS["state"], "Q", state)
        self.mem.put(state + pointers.FOCUS["definition"], "Q", cur_def)
        self.mem.put(state + pointers.FOCUS["progress"], "q", 23 * 100000)
        self.put_string(cur_def + pointers.FOCUS["id"], "ITA_preservation_of_independence", BASE + 0x2800)
        self.mem.put(state + pointers.FOCUS["completed"], "Q", array)
        self.mem.put(state + pointers.FOCUS["completed_count"], "I", 1)
        self.mem.put(array, "Q", done_def)
        self.put_string(done_def + pointers.FOCUS["id"], "ITA_army", BASE + 0x2900)  # short: inline
        self.assertEqual(self.svc.focus()["current"], "ITA_preservation_of_independence")
        res = self.svc.focus("ITA")
        self.assertEqual((res["progress_days"], res["completed"]), (23.0, ["ITA_army"]))
        self.mem.put(state + pointers.FOCUS["definition"], "Q", 0)        # nothing selected
        self.assertIsNone(self.svc.focus("ITA")["current"])

    def writer(self):
        """The fake memory doubles as the writer; it records writes."""
        self.writes = []

        def write(address, data):
            self.writes.append((address, data))
            for base, region in self.mem.regions_data.items():
                if base <= address < base + len(region):
                    region[address - base:address - base + len(data)] = data
        self.mem.write = write
        self.svc._open_writer = lambda pid: self.mem

    def test_local_write_sets_the_value_and_reads_it_back(self):
        self.writer()
        res = self.svc.write_value("stability", 0.8, expected_before=0.6)        # player ITA
        self.assertEqual((res["tag"], res["before"], res["after"], res["scope"]), ("ITA", 0.6, 0.8, "local"))
        self.assertEqual(self.writes, [(self.countries["ITA"] + 0x10D0, struct.pack("<q", 80000))])
        self.assertEqual(self.svc.read("stability")["value"], 0.8)
        res = self.svc.write_value("political_power", 500, tag="GER")             # behind a pointer, any country
        self.assertEqual(res["after"], 500.0)

    def test_local_write_is_refused_in_multiplayer_out_of_range_or_when_the_value_moved(self):
        self.writer()
        for kwargs, code in ((dict(field="stability", value=1.5), "out_of_range"),
                             (dict(field="manpower", value=5), "unsupported_field"),
                             (dict(field="stability", value=0.5, expected_before=0.7), "value_changed")):
            with self.assertRaises(LiveError) as ctx:
                self.svc.write_value(**kwargs)
            self.assertEqual(ctx.exception.code, code, kwargs)
        self.game_log("MULTIPLAYER")
        with self.assertRaises(LiveError) as ctx:
            self.svc.write_value("stability", 0.5)
        self.assertEqual(ctx.exception.code, "multiplayer")
        (self.logs / "game.log").write_text("[19:59:10][no_game_date][gamestate.cpp:2844]: Loaded 13414 provinces.\n")
        with self.assertRaises(LiveError) as ctx:                                 # no launch line: unknown
            self.svc.write_value("stability", 0.5)
        self.assertEqual(ctx.exception.code, "mode_unknown")
        self.assertEqual(self.writes, [])

    def test_player_with_fog_of_war_off_keeps_the_last_unambiguous_result(self):
        """Correction: the flag is fog-of-war visibility - after `fow` every existing country is visible."""
        self.assertEqual(self.svc.read("stability")["tag"], "ITA")              # only ITA visible
        self.svc._player = None
        self.put_country("GER", stability=0.71, pp=772.3, ai=0)                   # `fow`: GER visible too
        self.assertEqual(self.svc.players(), ["GER", "ITA"])
        self.assertEqual(self.svc.read("stability")["tag"], "ITA")

    def put_stockpile(self, tag, items):
        """items: [(equipment id, amount)] -> production object, entry array and variant objects."""
        c = self.countries[tag]
        prod, array, variants = c + 0x1E00, BASE + 0x6000, BASE + 0x6800
        self.mem.put(c + pointers.STOCKPILE["production"], "Q", prod)
        self.mem.put(prod + pointers.STOCKPILE["array"], "Q", array)
        self.mem.put(prod + pointers.STOCKPILE["count"], "i", len(items))
        for i, (eq_id, amount) in enumerate(items):
            v = variants + 0x80 * i
            self.mem.put(v + pointers.VARIANT["id"], "i", eq_id)
            self.mem.put(array + 16 * i, "Q", v)
            self.mem.put(array + 16 * i + 8, "q", round(amount * 100000))

    def test_stockpile_read_and_local_write(self):
        self.put_stockpile("ITA", [(1785, 394), (1820, 205), (1817, 0)])
        res = self.svc.stockpile()
        self.assertEqual(res["tag"], "ITA")
        self.assertEqual([(e["id"], e["amount"]) for e in res["entries"]], [("1785", 394.0), ("1820", 205.0), ("1817", 0.0)])
        self.writer()
        done = self.svc.write_stockpile("1817", 500, expected_before=0)
        self.assertEqual((done["before"], done["after"], done["scope"]), (0.0, 500.0, "local"))
        self.assertEqual(self.svc.stockpile()["entries"][2]["amount"], 500.0)
        for args, code in ((("9999", 5), "not_in_stockpile"), (("1785", -5), "out_of_range"), (("1785", 2.5), "out_of_range")):
            with self.assertRaises(LiveError) as ctx:
                self.svc.write_stockpile(*args)
            self.assertEqual(ctx.exception.code, code, args)
        with self.assertRaises(LiveError) as ctx:
            self.svc.write_stockpile("1785", 10, expected_before=1)                # value moved
        self.assertEqual(ctx.exception.code, "value_changed")
        self.game_log("MULTIPLAYER")
        with self.assertRaises(LiveError) as ctx:
            self.svc.write_stockpile("1785", 10)
        self.assertEqual(ctx.exception.code, "multiplayer")

    def test_writer_module_requests_only_the_rights_it_needs(self):
        from hoi4dbg.integration import memory_write
        self.assertEqual(memory_write.WRITE_ACCESS_RIGHTS, 0x0400 | 0x0010 | 0x0020 | 0x0008)
        source = Path(memory_write.__file__).read_text(encoding="utf-8")
        for forbidden in ("VirtualProtectEx(", "PROCESS_ALL_ACCESS =", "CreateRemoteThread("):
            self.assertNotIn(forbidden, source)

    def test_missing_country_and_unknown_tag(self):
        with self.assertRaises(LiveError) as ctx:
            self.svc.read("stability", "ENG")    # slot empty
        self.assertEqual(ctx.exception.code, "country_missing")
        with self.assertRaises(LiveError) as ctx:
            self.svc.read("stability", "XXX")
        self.assertEqual(ctx.exception.code, "unknown_tag")

    def test_implausible_layout_is_refused(self):
        self.mem.put(self.countries["ITA"] + 0x10D0, "q", 12_345_678)
        with self.assertRaises(LiveError) as ctx:
            self.svc.read("stability")
        self.assertEqual(ctx.exception.code, "implausible")

    def test_other_game_version_does_not_use_the_table(self):
        self.version = "Operation Postern v1.19.4.0.abcd (6000)"
        with self.assertRaises(LiveError) as ctx:
            self.svc.read("stability")
        self.assertEqual(ctx.exception.code, "not_calibrated")


if __name__ == "__main__":
    unittest.main()


class PartyPointerTests(unittest.TestCase):
    def test_read_parties(self):
        mem = FakeMemory(0x4000)
        country, pol, array = BASE + 0x100, BASE + 0x1000, BASE + 0x2000
        parties = [BASE + 0x2400 + 0x100 * i for i in range(4)]
        mem.put(country + pointers.POLITICS, "Q", pol)
        mem.put(pol + pointers.PARTIES, "Q", array)
        for i, (p, pop) in enumerate(zip(parties, (10.0, 88.0, 2.0, 0.0))):
            mem.put(array + 8 * i, "Q", p)
            mem.put(p + pointers.PARTY_POPULARITY, "q", round(pop * 100000))
        mem.put(pol + pointers.RULING_PARTY, "Q", parties[1])
        out = pointers.read_parties(mem, country, ["democratic", "communism", "fascism", "neutrality"])
        self.assertEqual(out, {"popularity": {"democratic": 10.0, "communism": 88.0, "fascism": 2.0, "neutrality": 0.0},
                               "ruling": "communism"})
        mem.put(parties[2] + pointers.PARTY_POPULARITY, "q", 500 * 100000)   # not a percentage: wrong layout
        with self.assertRaises(pointers.PointerError):
            pointers.read_parties(mem, country, ["democratic", "communism", "fascism", "neutrality"])


class ResourcePointerTests(unittest.TestCase):
    NAMES = ["oil", "aluminium", "rubber"]
    TOKENS = [0x4E37, 0x4E1F, 0x3E05]

    def _pools(self, mem, cr, values):
        for part, pool in pointers.RESOURCE_POOLS.items():
            for k, (token, v) in enumerate(zip(self.TOKENS, values.get(part, [0, 0, 0]))):
                mem.put(cr + pool + pointers.POOL_SLOTS + 16 * k, "q", round(v * 100000))
                mem.put(cr + pool + pointers.POOL_SLOTS + 16 * k + 8, "I", token)

    def test_read_resources_and_imports(self):
        mem = FakeMemory(0x4000)
        cr, seller_cr, array, deal, res = BASE + 0x100, BASE + 0x900, BASE + 0x1000, BASE + 0x1100, BASE + 0x1300
        self._pools(mem, cr, {"produced": [191, 130, 2], "used": [0, -19, -8], "imported": [24, 0, 0]})
        out = pointers.read_resources(mem, cr, self.NAMES)
        self.assertEqual(out["produced"], {"oil": 191.0, "aluminium": 130.0, "rubber": 2.0})
        self.assertEqual(out["used"], {"oil": 0.0, "aluminium": 19.0, "rubber": 8.0})   # stored negative
        self.assertEqual(out["_tokens"], dict(zip(self.TOKENS, self.NAMES)))
        mem.put(cr + pointers.IMPORTS, "Q", array)
        mem.put(cr + pointers.IMPORTS + 8, "i", 1)    # capacity
        mem.put(cr + pointers.IMPORTS + 12, "i", 1)   # size
        mem.put(array, "Q", deal)
        mem.put(deal + pointers.EXCHANGE["seller_resources"], "Q", seller_cr)
        mem.put(deal + pointers.EXCHANGE["resource"], "Q", res)
        mem.put(deal + pointers.EXCHANGE["amount"], "q", 24 * 100000)
        mem.put(res + pointers.RESOURCE_TOKEN, "I", 0x4E37)
        self.assertEqual(pointers.read_imports(mem, cr, out["_tokens"], {seller_cr: "USA"}),
                         [{"seller": "USA", "resource": "oil", "amount": 24.0}])

    def test_wrong_layout_is_refused(self):
        mem = FakeMemory(0x4000)
        cr = BASE + 0x100
        self._pools(mem, cr, {})
        mem.put(cr + pointers.RESOURCE_POOLS["exported"] + pointers.POOL_SLOTS + 8, "I", 0x1234)   # other token
        with self.assertRaises(pointers.PointerError):
            pointers.read_resources(mem, cr, self.NAMES)
        self._pools(mem, cr, {"produced": [5e7, 0, 0]})   # not an amount per day
        with self.assertRaises(pointers.PointerError):
            pointers.read_resources(mem, cr, self.NAMES)


class IdeaPointerTests(unittest.TestCase):
    def _string(self, mem, address, text):
        raw = text.encode()
        if len(raw) < 16:   # MSVC small string: inline buffer, size, capacity 15
            mem.regions_data[BASE][address - BASE:address - BASE + len(raw)] = raw
        else:
            heap = address + 0x200
            mem.regions_data[BASE][heap - BASE:heap - BASE + len(raw)] = raw
            mem.put(address, "Q", heap)
        mem.put(address + 16, "Q", len(raw))
        mem.put(address + 24, "Q", max(15, len(raw)))

    def test_read_ideas_uses_size_not_capacity(self):
        mem = FakeMemory(0x4000)
        country, pol, array = BASE + 0x100, BASE + 0x1000, BASE + 0x1100
        ideas = [BASE + 0x2000 + 0x400 * i for i in range(3)]
        mem.put(country + pointers.POLITICS, "Q", pol)
        mem.put(pol + pointers.IDEAS, "Q", array)
        mem.put(pol + pointers.IDEAS + 8, "i", 3)    # capacity
        mem.put(pol + pointers.IDEAS + 12, "i", 2)   # size: the 3rd slot is stale
        for i, (idea, name) in enumerate(zip(ideas, ("civilian_economy", "export_focus", "stale_idea"))):
            mem.put(array + 8 * i, "Q", idea)
            self._string(mem, idea + pointers.IDEA_NAME, name)
        self.assertEqual(pointers.read_ideas(mem, country), ["civilian_economy", "export_focus"])
        mem.put(pol + pointers.IDEAS + 12, "i", 9)   # more than the capacity: wrong layout
        with self.assertRaises(pointers.PointerError):
            pointers.read_ideas(mem, country)

    def test_read_advisors(self):
        mem = FakeMemory(0x4000)
        country, chars, array, adv, ch = BASE + 0x100, BASE + 0x400, BASE + 0x600, BASE + 0x1000, BASE + 0x1800
        mem.put(country + pointers.COUNTRY_CHARACTERS, "Q", chars)
        mem.put(chars + pointers.HIRED_ADVISORS, "Q", array)
        mem.put(chars + pointers.HIRED_ADVISORS + 8, "i", 2)    # capacity
        mem.put(chars + pointers.HIRED_ADVISORS + 12, "i", 1)   # size
        mem.put(array, "Q", adv)
        mem.put(adv + pointers.ADVISOR_CHARACTER, "Q", ch)
        self._string(mem, adv + pointers.ADVISOR_SLOT, "political_advisor")
        mem.put(ch + pointers.CHARACTER_ID, "i", 4432)
        self.assertEqual(pointers.read_advisors(mem, country), [{"slot": "political_advisor", "id": "4432"}])
        self._string(mem, adv + pointers.ADVISOR_SLOT, "\x01\x02garbage")
        with self.assertRaises(pointers.PointerError):
            pointers.read_advisors(mem, country)

    def test_read_dynamic_modifiers(self):
        mem = FakeMemory(0x4000)
        country, array, definition, values = BASE + 0x100, BASE + 0x1000, BASE + 0x1400, BASE + 0x1800
        mem.put(country + pointers.DYNAMIC_MODIFIERS, "Q", array)
        mem.put(country + pointers.DYNAMIC_MODIFIERS + 8, "i", 1)
        mem.put(country + pointers.DYNAMIC_MODIFIERS + 12, "i", 1)
        mem.put(array + pointers.DYNAMIC["definition"], "Q", definition)
        mem.put(array + pointers.DYNAMIC["enabled"], "q", 1)
        mem.put(array + pointers.DYNAMIC["values"], "Q", values)
        mem.put(array + pointers.DYNAMIC["values"] + 12, "i", 4)   # size
        self._string(mem, definition + pointers.DYNAMIC_NAME, "SOV_second_five_year_plan_dynamic_modifier")
        for i, v in enumerate((-15000, 5000, 10000, 5000)):
            mem.put(values + 8 * i, "q", v)
        self.assertEqual(pointers.read_dynamic_modifiers(mem, country),
                         [{"id": "SOV_second_five_year_plan_dynamic_modifier", "values": [-0.15, 0.05, 0.1, 0.05],
                           "enabled": True}])
        mem.put(country + pointers.DYNAMIC_MODIFIERS + 12, "i", 5)   # more than the capacity: wrong layout
        with self.assertRaises(pointers.PointerError):
            pointers.read_dynamic_modifiers(mem, country)

    def test_read_leader(self):
        mem = FakeMemory(0x4000)
        country, pol, party, array, leader, ch, ideo = (BASE + 0x100, BASE + 0x400, BASE + 0x600, BASE + 0x800,
                                                       BASE + 0x1000, BASE + 0x1400, BASE + 0x1800)
        mem.put(country + pointers.POLITICS, "Q", pol)
        mem.put(pol + pointers.RULING_PARTY, "Q", party)
        mem.put(party + pointers.PARTY_LEADERS, "Q", array)
        mem.put(party + pointers.PARTY_LEADERS + 8, "i", 1)
        mem.put(party + pointers.PARTY_LEADERS + 12, "i", 1)
        mem.put(array, "Q", leader)
        mem.put(leader + pointers.LEADER_CHARACTER, "Q", ch)
        mem.put(ch + pointers.CHARACTER_ID, "i", 4352)
        mem.put(leader + pointers.LEADER_IDEOLOGY, "Q", ideo)
        self._string(mem, ideo + pointers.IDEOLOGY_NAME, "stalinism")
        self.assertEqual(pointers.read_leader(mem, country), {"id": "4352", "ideology": "stalinism"})
        mem.put(party + pointers.PARTY_LEADERS + 12, "i", 0)   # party without a leader
        self.assertIsNone(pointers.read_leader(mem, country))

    def test_read_faction(self):
        mem = FakeMemory(0x4000)
        country, dip, faction, array = BASE + 0x100, BASE + 0x400, BASE + 0x1000, BASE + 0x2000
        eng, can = BASE + 0x3000, BASE + 0x3100
        mem.put(country + pointers.DIPLOMACY, "Q", dip)
        self.assertIsNone(pointers.read_faction(mem, country, {}))   # not in a faction
        mem.put(dip + pointers.FACTION, "Q", faction)
        self._string(mem, faction + pointers.FACTION_FIELDS["name"], "Allies")
        self._string(mem, faction + pointers.FACTION_FIELDS["icon"], "GFX_faction_icon_allies")
        mem.put(faction + pointers.FACTION_FIELDS["members"], "Q", array)
        mem.put(faction + pointers.FACTION_FIELDS["members"] + 8, "i", 2)
        mem.put(faction + pointers.FACTION_FIELDS["members"] + 12, "i", 2)
        mem.put(array, "Q", eng)
        mem.put(array + 8, "Q", can)
        self.assertEqual(pointers.read_faction(mem, country, {eng: "ENG", can: "CAN"}),
                         {"name": "Allies", "icon": "GFX_faction_icon_allies", "members": ["ENG", "CAN"]})
        with self.assertRaises(pointers.PointerError):   # a member that is no country: wrong layout
            pointers.read_faction(mem, country, {eng: "ENG"})

    def test_read_doctrines(self):
        mem = FakeMemory(0x4000)
        static = 0x400_0000
        mem.regions_data[static] = bytearray(0x100)
        module_base = static - pointers.COUNTRY_TABLE[0]
        tags = ["GER", "ENG", "SOV"]
        root, system, array = BASE + 0x100, BASE + 0x600, BASE + 0x800
        folders, tracks, grand, sub = BASE + 0xC00, BASE + 0x1000, BASE + 0x2000, BASE + 0x2400
        mem.put(static, "Q", root)
        mem.put(root + pointers.DOCTRINE_SYSTEM, "Q", system)
        mem.put(system + pointers.DOCTRINE_COUNTRIES, "Q", array)
        entry = array + pointers.DOCTRINE_ENTRY * 3    # SOV: slot 3 of the country table
        mem.put(entry + 8, "Q", 3)
        mem.put(entry + pointers.DOCTRINE_FOLDERS, "Q", folders)
        mem.put(entry + pointers.DOCTRINE_FOLDERS + 12, "i", 2)           # land and naval folder
        mem.put(folders + pointers.FOLDER_GRAND, "Q", grand)
        mem.put(folders + pointers.FOLDER_TRACKS, "Q", tracks)
        mem.put(folders + pointers.FOLDER_TRACKS + 12, "i", 2)             # 2 tracks, the 2nd empty
        mem.put(tracks + pointers.TRACK_SUB, "Q", sub)
        self._string(mem, grand + pointers.TEMPLATE_NAME, "GRAND_DOCTRINE_MASS_ASSAULT")
        self._string(mem, sub + pointers.TEMPLATE_NAME, "SUBDOCTRINE_HUMAN_WAVES")
        self.assertEqual(pointers.read_doctrines(mem, module_base, tags, "SOV"),
                         ["GRAND_DOCTRINE_MASS_ASSAULT", "SUBDOCTRINE_HUMAN_WAVES"])
        with self.assertRaises(pointers.PointerError):   # entry of another slot: wrong layout
            pointers.read_doctrines(mem, module_base, tags, "ENG")

    def test_read_penalties(self):
        mem = FakeMemory(0x4000)
        country = BASE + 0x100
        mem.put(country + pointers.PENALTIES["bombing_penalty"], "q", -2676)     # 'po pauzie 2': -0.08166 in the save
        mem.put(country + pointers.PENALTIES["casualties_penalty"], "q", -973)   # -0.02969
        out = pointers.read_penalties(mem, country)
        self.assertAlmostEqual(out["bombing_penalty"], -0.08166, delta=1e-5)   # the save cuts to 5 decimals
        self.assertAlmostEqual(out["casualties_penalty"], -0.02969, delta=1e-5)
        mem.put(country + pointers.PENALTIES["bombing_penalty"], "q", 5 * 32768)   # +500 %: wrong layout
        with self.assertRaises(pointers.PointerError):
            pointers.read_penalties(mem, country)

    def test_read_research(self):
        mem = FakeMemory(0x4000)
        country, status, array = BASE + 0x100, BASE + 0x400, BASE + 0x600
        slots, tech, template = [BASE + 0x800, BASE + 0x900], BASE + 0x1000, BASE + 0x1400
        mem.put(country + pointers.TECHNOLOGY_STATUS, "Q", status)
        mem.put(status + pointers.RESEARCH_SLOTS, "Q", array)
        mem.put(status + pointers.RESEARCH_SLOTS + 8, "i", 2)
        mem.put(status + pointers.RESEARCH_SLOTS + 12, "i", 2)
        for i, s in enumerate(slots):
            mem.put(array + 8 * i, "Q", s)
        mem.put(slots[0] + pointers.SLOT_TECHNOLOGY, "Q", tech)
        mem.put(slots[0] + pointers.SLOT_SPEED, "q", 113000)
        mem.put(slots[1] + pointers.SLOT_SPEED, "q", 100000)
        mem.put(tech + pointers.TECHNOLOGY_TEMPLATE, "Q", template)
        mem.put(tech + pointers.TECHNOLOGY_POINTS, "q", 4128000)   # 41.28 points, as in the user's save
        mem.put(tech + pointers.TECHNOLOGY_BONUS, "q", 10000)      # +0.1 per day
        self._string(mem, template + pointers.TEMPLATE_ID, "excavation1")
        self.assertEqual(pointers.read_research(mem, country), [
            {"slot": 1, "technology": "excavation1", "speed": 1.13, "points": 41.28, "bonus": 0.1},
            {"slot": 2, "technology": None, "speed": 1.0, "points": None, "bonus": None}])
        mem.put(slots[1] + pointers.SLOT_SPEED, "q", -5 * 100000)   # negative speed: wrong layout
        with self.assertRaises(pointers.PointerError):
            pointers.read_research(mem, country)

    def test_read_date(self):
        mem = FakeMemory(0x4000)
        static = 0x400_0000
        mem.regions_data[static] = bytearray(0x100)
        module_base = static - pointers.COUNTRY_TABLE[0]
        root = BASE + 0x100
        mem.put(static, "Q", root)
        mem.put(root + pointers.GAME_DATE, "i", (5000 + 1936) * 8760 + 263 * 24)   # 1936.9.21 in the user's game
        self.assertEqual(pointers.read_date(mem, module_base), {"year": 1936, "day": 263, "hour": 0})
        mem.put(root + pointers.GAME_DATE, "i", 12345)
        with self.assertRaises(pointers.PointerError):
            pointers.read_date(mem, module_base)

    def test_read_limited_bonuses(self):
        mem = FakeMemory(0x4000)
        country, status, array, bonus, cats, cat = (BASE + 0x100, BASE + 0x400, BASE + 0x600, BASE + 0x800,
                                                    BASE + 0xA00, BASE + 0xC00)
        mem.put(country + pointers.TECHNOLOGY_STATUS, "Q", status)
        for at, data, n in ((status + pointers.LIMITED_BONUSES, array, 1), (bonus + pointers.BONUS["categories"], cats, 1)):
            mem.put(at, "Q", data)
            mem.put(at + 8, "i", n)
            mem.put(at + 12, "i", n)
        mem.put(array, "Q", bonus)
        mem.put(cats, "Q", cat)
        mem.put(bonus + pointers.BONUS["uses"], "i", 1)
        mem.put(bonus + pointers.BONUS["id"], "i", 1)
        mem.put(bonus + pointers.BONUS["bonus"], "q", 50000)
        self._string(mem, bonus + pointers.BONUS["name"], "SUBDOCTRINE_MOBILE_INFANTRY")
        self._string(mem, cat, "motorized_equipment")
        self.assertEqual(pointers.read_limited_bonuses(mem, country), [
            {"id": 1, "name": "SUBDOCTRINE_MOBILE_INFANTRY", "bonus": 0.5, "uses": 1, "categories": ["motorized_equipment"]}])
        mem.put(bonus + pointers.BONUS["uses"], "i", -3)   # negative uses: wrong layout
        with self.assertRaises(pointers.PointerError):
            pointers.read_limited_bonuses(mem, country)
