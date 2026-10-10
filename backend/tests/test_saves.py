import datetime as dt
import hashlib
import os
import shutil
import time
import unittest
from pathlib import Path

from hoi4dbg import applog
from hoi4dbg.integration.userdata import documents_dir
from hoi4dbg.saves import binary, fields, reader
from hoi4dbg.service import NotFound, save_freshness, version_core

from helpers import TempDirMixin, make_service
from savebuilder import Builder, encode_date, realistic_save

FUTURE = lambda: time.time() + 3600  # noqa: E731 - clock where every file is "settled"


def sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


class DateTests(unittest.TestCase):
    def test_real_values(self):
        # Values read from real saves: autosave "German Reich 1937.3.1.2" and AUS_1943_02_01_01.hoi4
        self.assertEqual(fields.decode_date(60769537)["text"], "1937.3.1.2")
        self.assertEqual(fields.decode_date(60821424)["text"], "1943.2.1.1")

    def test_roundtrip_month_edges(self):
        for date in [(1936, 1, 1, 1), (1936, 1, 1, 24), (1939, 2, 28, 12), (1944, 12, 31, 24), (2277, 1, 12, 7)]:
            decoded = fields.decode_date(encode_date(*date))
            self.assertEqual((decoded["year"], decoded["month"], decoded["day"], decoded["hour"]), date)


class FormatTests(unittest.TestCase):
    def test_sniff(self):
        self.assertEqual(binary.sniff(b""), "empty")
        self.assertEqual(binary.sniff(b"HOI4bin\x35\x2a"), "binary")
        self.assertEqual(binary.sniff(b"HOI4txt\n"), "text")
        self.assertEqual(binary.sniff(b"PK\x03\x04xx"), "compressed")
        self.assertEqual(binary.sniff(b"EU4bin"), "unknown")

    def test_expected_width_by_version(self):
        self.assertEqual(binary.expected_float_width("Countenance v1.16.10.5638 (71f2)"), 4)
        self.assertEqual(binary.expected_float_width("Musketeer v1.17.0.5e61 (e664)"), 8)
        self.assertEqual(binary.expected_float_width("Operation Postern v1.19.3.0.c01a (ff0e)"), 8)
        self.assertIsNone(binary.expected_float_width("garbage"))

    def test_header_of_realistic_save(self):
        data = realistic_save(players=[("GER", "Czarny"), ("SOV", "Tester Two")], mods=["Toolpack+", "FPS Map"])
        result = reader.analyse_bytes(data)
        header = result["header"]
        self.assertEqual(result["missing_fields"], [])
        self.assertEqual(header["player_tag"], "GER")
        self.assertEqual(header["date"]["text"], "1937.3.1.2")
        self.assertEqual(header["version"], "Operation Postern v1.19.3.0.c01a (ff0e)")
        self.assertEqual((header["ideology"], header["difficulty"]), ("fascism", "normal"))
        self.assertEqual([(p["tag"], p["name"]) for p in header["players"]], [("GER", "Czarny"), ("SOV", "Tester Two")])
        self.assertEqual(header["players"][1]["unidentified_fields"], {"#000b": 2})
        self.assertEqual(header["mods"], ["Toolpack+", "FPS Map"])
        self.assertEqual(header["players"][0]["country_leader"], True)
        self.assertEqual((header["multiplayer"], header["multiplayer_basis"]), (False, "flag"))

    def test_multiplayer_flag_and_header_end(self):
        data = realistic_save(players=[("GER", "Czarny"), ("ITA", "Two")], multiplayer=True)
        self.assertTrue(reader.analyse_bytes(data)["header"]["multiplayer"])
        # without the flag the header parse stops at the mods (last header field), not in the body
        parser = binary.Parser(realistic_save(), 8)
        found = parser.top_level(fields.HEADER_KEYS, until=fields.HEADER_END)
        self.assertNotIn(fields.MULTIPLAYER, found)
        self.assertIn(fields.MODS, found)
        self.assertEqual(parser.peek(), 0x2D49)  # positioned at the first body field

    def test_validation_picks_width_by_structure(self):
        new = realistic_save(float_width=8)
        old = realistic_save(version="Countenance v1.16.10.5638 (71f2)", float_width=4)
        self.assertEqual((binary.validate(new, "x v1.19.3").status, binary.validate(new, "x v1.19.3").float_width),
                         ("complete", 8))
        self.assertEqual(binary.validate(old, "x v1.16.10").float_width, 4)
        # A wrong version hint is overruled by the structure:
        wrong = binary.validate(new, "x v1.16.10")
        self.assertEqual((wrong.status, wrong.float_width), ("complete", 8))
        self.assertIn("unexpected", wrong.message)
        self.assertFalse(binary.scan(new, 4).ok)

    def test_ambiguous_without_version(self):
        data = realistic_save(body_values=0)  # no 0x000d values -> both widths parse
        self.assertEqual(binary.validate(data, None).status, "ambiguous")
        self.assertEqual(binary.validate(data, "x v1.19.3").status, "complete")

    def test_grammar_errors_are_detected(self):
        cases = {
            "unbalanced": Builder().key(0x1111).open().i32(1).bytes(),
            "close_first": Builder().close().bytes(),
            "equals_without_key": Builder().open().tok(binary.EQUALS).i32(1).close().bytes(),
            "close_after_equals": Builder().key(0x1111).close().bytes(),
            "string_past_end": Builder().key(0x1111).bytes() + b"\x0f\x00\xff\x00ab",
            "odd_trailing_byte": Builder().key(0x1111).i32(1).bytes() + b"\x01",
        }
        for name, data in cases.items():
            with self.subTest(name):
                result = binary.validate(data, "x v1.19.3")
                self.assertEqual(result.status, "invalid")
                self.assertIn("Structure invalid", result.message)

    def test_unreadable_files_raise_coded_errors(self):
        full = realistic_save()
        cases = {
            b"": "empty",
            b"PK\x03\x04rest": "compressed",
            b"HOI4txt\nplayer=\"GER\"\n": "unsupported",  # text header without its expected end
            b"\x00\x01garbage": "unknown_format",
            full[:40]: "truncated",  # cut inside the header
            Builder().key(0x1111).i32(1).bytes(): "unsupported",  # binary, but no version string
        }
        for data, code in cases.items():
            with self.subTest(code):
                with self.assertRaises(binary.SaveFormatError) as ctx:
                    reader.analyse_bytes(data)
                self.assertEqual(ctx.exception.code, code)

    def test_header_parse_rejects_control_token_as_key(self):
        data = Builder().tok(binary.OPEN).bytes()
        with self.assertRaises(binary.SaveFormatError) as ctx:
            binary.Parser(data, 8).top_level({fields.VERSION})
        self.assertEqual(ctx.exception.code, "corrupt")

    def test_oversized_header_block_is_bounded(self):
        bld = Builder().key(fields.VERSION).qstr("x v1.19.3").key(fields.PLAYERS).open()
        for i in range(30000):
            bld.i32(i)
        data = bld.close().bytes()
        with self.assertRaises(binary.SaveFormatError) as ctx:
            reader.analyse_bytes(data)
        self.assertEqual(ctx.exception.code, "unsupported")

    def test_field_catalog_has_evidence(self):
        for entry in fields.field_catalog():
            self.assertIn(entry["status"], ("verified", "inferred"))
            self.assertTrue(entry["evidence"])


class SavesDirMixin(TempDirMixin):
    def setUp(self):
        super().setUp()
        self.saves = self.tmp / "save games"
        self.saves.mkdir()
        self.cache = self.tmp / "cache"

    def write(self, name: str, data: bytes, age_s: float = 3600) -> Path:
        path = self.saves / name
        path.write_bytes(data)
        stamp = time.time() - age_s
        os.utime(path, (stamp, stamp))
        return path


class SnapshotTests(SavesDirMixin, unittest.TestCase):
    def test_copy_leaves_original_untouched(self):
        original = self.write("GER_1937_03_01_02.hoi4", realistic_save())
        before = (sha1(original), original.stat().st_mtime_ns)
        copy = reader.SaveSnapshotter(self.cache).copy(original)
        self.assertNotEqual(copy.parent, original.parent)
        self.assertEqual(sha1(copy), before[0])
        self.assertEqual((sha1(original), original.stat().st_mtime_ns), before)

    def test_recent_file_is_treated_as_in_progress(self):
        original = self.write("autosave.hoi4", realistic_save(), age_s=0)
        with self.assertRaises(binary.SaveFormatError) as ctx:
            reader.SaveSnapshotter(self.cache, settle_s=3).copy(original)
        self.assertEqual(ctx.exception.code, "in_progress")

    def test_prune_keeps_recent_copies(self):
        snap = reader.SaveSnapshotter(self.cache, keep=2)
        for i in range(4):
            snap.copy(self.write(f"s{i}.hoi4", realistic_save(players=[(f"T{i:02d}", "x")])))
        self.assertEqual(len(list(self.cache.glob("*.hoi4"))), 2)

    def test_list_saves_newest_first(self):
        self.write("old.hoi4", b"x", age_s=500)
        self.write("new.hoi4", b"x", age_s=10)
        (self.saves / "notes.txt").write_text("x", encoding="utf-8")
        self.assertEqual([s["name"] for s in reader.list_saves(self.saves)], ["new.hoi4", "old.hoi4"])
        self.assertEqual(reader.list_saves(self.tmp / "missing"), [])

    def analyzer(self):
        logger, _ = applog.setup(None)
        return reader.SaveAnalyzer(reader.SaveSnapshotter(self.cache), logger)

    def test_analyzer_validates_in_background_and_caches(self):
        analyzer = self.analyzer()
        path = self.write("GER.hoi4", realistic_save())
        first = analyzer.analyse(path)
        self.assertIn(first["validation"]["status"], ("pending", "complete"))
        analyzer.wait_idle()
        done = analyzer.analyse(path)
        self.assertEqual(done["validation"]["status"], "complete")
        self.assertIsNone(done["error"])
        done["header"]["player_tag"] = "XXX"  # callers get copies, not the cached object
        self.assertEqual(analyzer.analyse(path)["header"]["player_tag"], "GER")

    def test_analyzer_reports_damaged_body(self):
        analyzer = self.analyzer()
        data = realistic_save()[:-2]  # last '}' missing: header readable, file incomplete
        path = self.write("broken.hoi4", data)
        analyzer.analyse(path)
        analyzer.wait_idle()
        result = analyzer.analyse(path)
        self.assertEqual(result["header"]["player_tag"], "GER")
        self.assertEqual(result["validation"]["status"], "invalid")
        self.assertEqual(result["error"]["code"], "corrupt")

    def test_analyzer_reports_unreadable_file(self):
        result = self.analyzer().analyse(self.write("empty.hoi4", b""))
        self.assertEqual(result["error"]["code"], "empty")
        self.assertIsNone(result["header"])


class FakeSaveIntegration:
    def __init__(self, saves_dir: Path, started: dt.datetime | None, version: str | None) -> None:
        self._dir = saves_dir
        self.started = started
        self.version = version

    def detect(self) -> dict:
        process = None
        if self.started:
            process = {"pid": 1, "name": "hoi4.exe", "path": "x", "started": self.started.isoformat(), "uptime_s": 1}
        return {"process": process, "install": {"version": {"display": self.version}}, "userdata": None,
                "session": None, "warnings": []}

    def saves_dir(self):
        return self._dir

    def game_log_names(self):
        return []

    def game_log(self, name, lines):
        return None


class ServiceSaveTests(SavesDirMixin, unittest.TestCase):
    def service(self, started=None, version="Operation Postern v1.19.3.0.c01a (5632)"):
        logger, _ = applog.setup(None)
        svc = make_service(self.tmp, FakeSaveIntegration(self.saves, started, version))
        svc.saves = reader.SaveAnalyzer(reader.SaveSnapshotter(self.cache), logger)
        return svc

    def test_freshness_categories(self):
        now = time.time()
        started = dt.datetime.fromtimestamp(now - 600, dt.timezone.utc)
        game = {"process": {"started": started.isoformat()}}
        self.assertEqual(save_freshness(now - 60, game, now)["category"], "current_session")
        self.assertEqual(save_freshness(now - 6000, game, now)["category"], "previous_session")
        self.assertEqual(save_freshness(now, {"process": None}, now)["category"], "game_not_running")
        self.assertEqual(save_freshness(now, {"process": {"started": None}}, now)["category"], "unknown_session")
        self.assertFalse(save_freshness(now, game, now)["is_live"])

    def test_latest_save_from_previous_session_is_flagged(self):
        self.write("old.hoi4", realistic_save(players=[("SOV", "a")]), age_s=7200)
        self.write("GER_1937_03_01_02.hoi4", realistic_save(), age_s=3600)
        svc = self.service(started=dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5))
        payload = svc.save_analysis(None)
        self.assertEqual(payload["source"], "save")
        data = payload["data"]
        self.assertEqual(data["file"]["name"], "GER_1937_03_01_02.hoi4")
        self.assertTrue(data["is_latest"])
        self.assertEqual(data["freshness"]["category"], "previous_session")
        self.assertTrue(data["version_check"]["match"])  # suffix in parentheses ignored

    def test_named_save_and_version_mismatch(self):
        self.write("old.hoi4", realistic_save(version="Countenance v1.16.10.5638 (71f2)", float_width=4), age_s=7200)
        self.write("new.hoi4", realistic_save(), age_s=3600)
        data = self.service(started=dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=3)).save_analysis("old.hoi4")["data"]
        self.assertFalse(data["is_latest"])
        self.assertEqual(data["freshness"]["category"], "current_session")
        self.assertFalse(data["version_check"]["match"])

    def test_unknown_or_traversal_names_rejected(self):
        self.write("a.hoi4", realistic_save())
        svc = self.service()
        for name in ("nope.hoi4", "../a.hoi4", "..\\a.hoi4", "C:\\Windows\\win.ini"):
            with self.subTest(name), self.assertRaises(NotFound):
                svc.save_analysis(name)

    def test_saves_list_has_freshness(self):
        self.write("a.hoi4", realistic_save())
        payload = self.service().saves_list()
        self.assertEqual(payload["data"]["saves"][0]["freshness"]["category"], "game_not_running")

    def test_version_core(self):
        self.assertEqual(version_core("Operation Postern v1.19.3.0.c01a (ff0e)"), "Operation Postern v1.19.3.0.c01a")
        self.assertIsNone(version_core(None))


def real_saves_dir() -> Path | None:
    override = os.environ.get("HOI4DBG_REAL_SAVES")
    path = Path(override) if override else documents_dir() / "Paradox Interactive" / "Hearts of Iron IV" / "save games"
    return path if path.is_dir() and any(path.glob("*.hoi4")) else None


@unittest.skipUnless(real_saves_dir(), "no real HOI4 saves on this machine")
class RealSaveTests(TempDirMixin, unittest.TestCase):
    """Runs the full pipeline on a COPY of the newest real save and checks the original is untouched."""

    def test_newest_real_save(self):
        newest = reader.list_saves(real_saves_dir())[0]
        original = real_saves_dir() / newest["name"]
        before = (original.stat().st_size, original.stat().st_mtime_ns, sha1(original))
        staging = self.tmp / "copy"
        staging.mkdir()
        staged = Path(shutil.copy2(original, staging / newest["name"]))

        logger, _ = applog.setup(None)
        analyzer = reader.SaveAnalyzer(reader.SaveSnapshotter(self.tmp / "cache"), logger)
        analyzer.analyse(staged)
        analyzer.wait_idle(timeout=120)
        result = analyzer.analyse(staged)

        self.assertIsNone(result["error"], result["error"])
        expected = "complete" if result["format"] == "binary" else "not_applicable"
        self.assertEqual(result["validation"]["status"], expected, result["validation"])
        header = result["header"]
        self.assertRegex(header["player_tag"], r"^[A-Z][A-Z0-9]{2}$")
        self.assertIn(header["player_tag"], [p["tag"] for p in header["players"]])
        self.assertRegex(header["version"], r"v\d+\.\d+")
        self.assertGreaterEqual(header["date"]["year"], 1936)
        self.assertEqual((original.stat().st_size, original.stat().st_mtime_ns, sha1(original)), before)


if __name__ == "__main__":
    unittest.main()
