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
from hoi4dbg.live import console
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


if __name__ == "__main__":
    unittest.main()
