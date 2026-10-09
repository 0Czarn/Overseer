import datetime as dt
import hashlib
import os
import shutil
import time
import unittest
from pathlib import Path

from hoi4dbg import applog
from hoi4dbg.saves import binary, binvalues, reader, text
from hoi4dbg.saves import binary as b
from hoi4dbg.saves import fields as f
from hoi4dbg.service import NotFound

from helpers import TempDirMixin, make_service
from savebuilder import Builder, realistic_save
from test_saves import FakeSaveIntegration, real_saves_dir

# Shape copied from the real 1.19.3 text save PROJEKT-OVERSEER.hoi4 (values shortened).
TEXT_SAVE = """HOI4txt
player="GER"
ideology=fascism
date="1936.1.1.12"
difficulty="normal"
version="Operation Postern v1.19.3.0.c01a (5468)"
tutorial=no
player_countries={
\tGER={
\t\tuser="Czarny"
\t\tcountry_leader=yes
\t\tid=1
\t}
}
save_version=33
mods={
\t"Toolpack+"
\t"FPS Map"
}
session=24
speed=0
equipments={
\tconvoy_1={
\t\tid={ id=1 type=70 }
\t\tcreator="GER"
\t}
\tinfantry_equipment_1={
\t\tid={ id=7 type=70 }
\t\tcreator="GER"
\t}
}
countries={
\tGER={
\t\tinstances_counter=0
\t\tcommand_power=0.286
\t\tfuel_status={
\t\t\tfuel=297201.86508
\t\t\tmax_fuel=371500.00000
\t\t}
\t\texperience_status={
\t\t\tarmy_experience=30.00000
\t\t\tarmy_experience_daily=1.20001
\t\t}
\t\tpolitics={
\t\t\truling_party=fascism
\t\t\tlast_election="1933.3.5.1"
\t\t\tpolitical_power=2.324
\t\t}
\t\tconvoys={
\t\t\tequipment={
\t\t\t\tequipment={
\t\t\t\t\tid={ id=1 type=70 }
\t\t\t\t\tamount=15
\t\t\t\t}
\t\t\t\tallow_zero_entries=no
\t\t\t}
\t\t}
\t\tmanpower={
\t\t\tcurrent=201692736
\t\t\tratio=250000
\t\t}
\t\tstability=0.7
\t\twar_support=0.3
\t\tcosmetic_tag="{weird} name"
\t}
\tSOV={
\t\tcommand_power=0.326
\t\tpolitics={
\t\t\tpolitical_power=1.5856
\t\t}
\t\tstability=0.5
\t\twar_support=0.3
\t}
}
"""


class TextParserTests(unittest.TestCase):
    def test_parse_nested_and_quoted(self):
        items = text.parse('a=1 b={ c="x y" d={ 1 2 } } e="q\\"q"')
        self.assertEqual(text.get(items, "a"), "1")
        self.assertEqual(text.get(items, "b", "c"), "x y")
        self.assertEqual(text.get(items, "b", "d"), ["1", "2"])
        self.assertEqual(text.get(items, "e"), 'q"q')
        self.assertIsNone(text.get(items, "b", "zzz"))

    def test_header(self):
        result = text.analyse_header(TEXT_SAVE.encode())
        header = result["header"]
        self.assertEqual(result["format"], "text")
        self.assertEqual(header["player_tag"], "GER")
        self.assertEqual(header["date"]["text"], "1936.1.1.12")
        self.assertEqual(header["players"][0]["name"], "Czarny")
        self.assertTrue(header["players"][0]["country_leader"])
        self.assertEqual(header["mods"], ["Toolpack+", "FPS Map"])
        self.assertEqual(result["missing_fields"], [])

    def test_country_values_for_editor(self):
        data = TEXT_SAVE.encode()
        values = text.country_values(text.country_block(data, "GER"), text.equipment_names(data))
        self.assertEqual(values["political_power"]["value"], 2.324)
        self.assertEqual(values["political_power"]["path"], "politics.political_power")
        self.assertEqual(values["stability"]["value"], 0.7)
        self.assertEqual(values["war_support"]["value"], 0.3)
        self.assertEqual(values["command_power"]["value"], 0.286)
        self.assertEqual(values["fuel"]["value"], 297201.86508)
        self.assertEqual(values["army_experience"]["value"], 30.0)
        self.assertEqual(values["air_experience"]["status"], "absent")
        self.assertEqual(values["manpower"]["value"], 201692736)
        self.assertEqual(values["manpower"]["path"], "manpower.current")
        self.assertEqual(values["convoys"]["value"], 15)
        self.assertEqual(values["convoys"]["raw"], "convoy_1#1=15")

    def test_crlf_saves(self):
        # Real saves use CRLF line endings.
        data = TEXT_SAVE.replace("\n", "\r\n").encode()
        self.assertEqual(text.equipment_names(data), {"1": "convoy_1", "7": "infantry_equipment_1"})
        values = text.country_values(text.country_block(data, "GER"), text.equipment_names(data))
        self.assertEqual((values["manpower"]["value"], values["convoys"]["value"]), (201692736, 15))
        self.assertEqual(text.analyse_header(data)["header"]["player_tag"], "GER")

    def test_convoys_ignore_other_equipment_and_flag_unknown_ids(self):
        block = text.parse("convoys={ equipment={ equipment={ id={ id=1 type=70 } amount=15 } "
                           "equipment={ id={ id=7 type=70 } amount=99 } } }")
        names = {"1": "convoy_1", "7": "infantry_equipment_1"}
        self.assertEqual(text.convoys(block, names)["value"], 15)
        self.assertEqual(text.convoys(block, {"7": "x"})["status"], "unmapped")
        self.assertEqual(text.convoys([], names)["status"], "absent")

    def test_country_block_is_bounded_to_that_country(self):
        sov = text.country_values(text.country_block(TEXT_SAVE.encode(), "SOV"))
        self.assertEqual(sov["political_power"]["value"], 1.5856)
        self.assertEqual(sov["fuel"]["status"], "absent")

    def test_missing_and_invalid_tags(self):
        self.assertIsNone(text.country_block(TEXT_SAVE.encode(), "ENG"))
        with self.assertRaises(ValueError):
            text.country_block(TEXT_SAVE.encode(), "../x")

    def test_damaged_text_saves(self):
        cut = TEXT_SAVE[:TEXT_SAVE.index("\t\tstability=0.7")].encode()
        with self.assertRaises(binary.SaveFormatError) as ctx:
            text.country_block(cut, "GER")
        self.assertEqual(ctx.exception.code, "truncated")
        no_countries = TEXT_SAVE[:TEXT_SAVE.index("countries={")].encode()
        with self.assertRaises(binary.SaveFormatError) as ctx:
            text.country_block(no_countries, "GER")
        self.assertEqual(ctx.exception.code, "unsupported")


class CountrySaveValuesServiceTests(TempDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.saves = self.tmp / "save games"
        self.saves.mkdir()

    def write(self, name, data, age_s=3600):
        path = self.saves / name
        path.write_bytes(data)
        stamp = time.time() - age_s
        os.utime(path, (stamp, stamp))
        return path

    def service(self, started=None):
        logger, _ = applog.setup(None)
        svc = make_service(self.tmp, FakeSaveIntegration(self.saves, started, "Operation Postern v1.19.3.0.c01a (5632)"))
        svc.saves = reader.SaveAnalyzer(reader.SaveSnapshotter(self.tmp / "cache"), logger)
        return svc

    def test_values_from_newest_text_save_are_a_snapshot(self):
        self.write("PROJEKT-OVERSEER.hoi4", TEXT_SAVE.encode(), age_s=60)
        started = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=30)
        payload = self.service(started).country_save_values("ger", None)
        self.assertEqual(payload["source"], "save")
        data = payload["data"]
        self.assertEqual(data["tag"], "GER")
        self.assertEqual(data["values"]["political_power"]["value"], 2.324)
        self.assertEqual(data["in_game_date"]["text"], "1936.1.1.12")
        self.assertEqual(data["freshness"]["category"], "current_session")
        self.assertFalse(data["freshness"]["is_live"])
        self.assertTrue(data["is_latest"])
        self.assertTrue(data["read_at"])

    def test_binary_save_of_other_version_is_reported_as_unmapped(self):
        self.write("GER.hoi4", realistic_save(version="Gotterdammerung v1.17.0.0 (abcd)"))
        payload = self.service().country_save_values("GER", None)
        self.assertEqual(payload["source"], "unavailable")
        self.assertEqual(payload["data"]["error"]["code"], "binary_values_unmapped")
        self.assertIn("-force_text_save", payload["note"])

    def test_binary_1_19_3_country_values(self):
        """Token ids and value types verified on a real text/binary pair (saves/binvalues.py)."""
        T = binvalues.TOKENS
        bld = Builder(8)
        bld.key(f.VERSION).qstr("Operation Postern v1.19.3.0.c01a (5468)")
        bld.key(T["countries"]).open().qstr("ENG").tok(b.EQUALS).open().key(T["stability"]).f(50000).close()
        bld.qstr("GER").tok(b.EQUALS).open()
        bld.key(T["politics"]).open().key(T["political_power"]).f(76630000).close()
        bld.key(T["stability"]).f(73000).key(0x1234).i32(5)
        bld.key(T["fuel_status"]).open().key(T["fuel"]).tok(b.F64)
        bld.out += (9964514455).to_bytes(8, "little", signed=True)
        bld.close()
        bld.key(T["manpower"]).open().key(T["current"]).i32(119692338).close()
        bld.close().close()
        self.write("GER_bin.hoi4", bld.bytes())
        payload = self.service().country_save_values("GER", None)
        self.assertEqual(payload["source"], "save", payload)
        values = payload["data"]["values"]
        self.assertEqual(values["political_power"]["value"], 766.3)
        self.assertEqual(values["stability"]["value"], 0.73)
        self.assertAlmostEqual(values["fuel"]["value"], 304092.848358, places=5)
        self.assertEqual(values["manpower"]["value"], 119692338)
        self.assertEqual(values["command_power"]["status"], "absent")

    def test_missing_country_and_bad_tag(self):
        self.write("t.hoi4", TEXT_SAVE.encode())
        svc = self.service()
        self.assertEqual(svc.country_save_values("ENG", None)["data"]["error"]["code"], "country_missing")
        with self.assertRaises(NotFound):
            svc.country_save_values("G/R", None)
        with self.assertRaises(NotFound):
            svc.country_save_values("GER", "missing.hoi4")

    def test_no_saves(self):
        self.assertEqual(self.service().country_save_values("GER", None)["source"], "unavailable")


def real_text_save() -> Path | None:
    directory = real_saves_dir()
    if directory is None:
        return None
    for item in reader.list_saves(directory):
        with open(directory / item["name"], "rb") as handle:
            if handle.read(7) == binary.MAGIC_TEXT:
                return directory / item["name"]
    return None


@unittest.skipUnless(real_text_save(), "no real text save (start HOI4 with -force_text_save and save)")
class RealTextSaveTests(TempDirMixin, unittest.TestCase):
    """Reads Country Editor values from a COPY of the newest real text save; the original must not change."""

    def test_real_country_values(self):
        original = real_text_save()
        digest = hashlib.sha1(original.read_bytes()).hexdigest()
        staged = Path(shutil.copy2(original, self.tmp / original.name))
        logger, _ = applog.setup(None)
        analyzer = reader.SaveAnalyzer(reader.SaveSnapshotter(self.tmp / "cache"), logger)
        header = analyzer.analyse(staged)["header"]
        out = analyzer.country_values(staged, header["player_tag"])
        values = out["values"]
        for field in ("political_power", "stability", "war_support", "command_power"):
            self.assertEqual(values[field]["status"], "read", field)
        self.assertTrue(0.0 <= values["stability"]["value"] <= 1.0)
        self.assertTrue(0.0 <= values["war_support"]["value"] <= 1.0)
        self.assertEqual(hashlib.sha1(original.read_bytes()).hexdigest(), digest)


def pp_test_pair() -> tuple[Path, Path] | None:
    directory = real_saves_dir()
    if directory is None:
        return None
    before, after = directory / "PROJEKT-OVERSEER.hoi4", directory / "pp save 2.hoi4"
    return (before, after) if before.is_file() and after.is_file() else None


@unittest.skipUnless(pp_test_pair(), "PP in-game test saves not present")
class RealPpChangeTests(TempDirMixin, unittest.TestCase):
    """In-game test 2026-10-09: GER paused at 1936.1.1.12, console `pp 10`, then `savegame`.
    Both saves are read from copies; the change must be exactly +10 and nothing else may change."""

    def test_pp_plus_10_verified_from_saves(self):
        logger, _ = applog.setup(None)
        analyzer = reader.SaveAnalyzer(reader.SaveSnapshotter(self.tmp / "cache"), logger)
        results = []
        for original in pp_test_pair():
            staged = Path(shutil.copy2(original, self.tmp / original.name))
            out = analyzer.country_values(staged, "GER")
            results.append((out["analysis"]["header"]["date"]["text"], out["values"]))
        (date_before, before), (date_after, after) = results
        self.assertEqual(date_before, date_after)
        self.assertAlmostEqual(after["political_power"]["value"] - before["political_power"]["value"], 10.0, places=3)
        for field in ("stability", "war_support", "command_power", "fuel", "army_experience"):
            self.assertEqual(before[field]["value"], after[field]["value"], field)


def manpower_test_pair() -> tuple[Path, Path] | None:
    directory = real_saves_dir()
    if directory is None:
        return None
    before, after = directory / "pp save 2.hoi4", directory / "Manpower 203.3, convoy 10.hoi4"
    return (before, after) if before.is_file() and after.is_file() else None


@unittest.skipUnless(manpower_test_pair(), "manpower/convoy in-game test saves not present")
class RealManpowerConvoyTests(TempDirMixin, unittest.TestCase):
    """In-game test 2026-10-09 (GER, 1936.1.1.12): console `manpower 2000000`, `manpower 200000000`,
    `add_latest_equipment 999`, `add_latest_equipment 10`, then savegame. Read from copies."""

    def test_values_change_as_observed(self):
        logger, _ = applog.setup(None)
        analyzer = reader.SaveAnalyzer(reader.SaveSnapshotter(self.tmp / "cache"), logger)
        before, after = (analyzer.country_values(Path(shutil.copy2(p, self.tmp / p.name)), "GER")["values"]
                         for p in manpower_test_pair())
        # manpower = available pool of owned states + manpower.current (console additions); the second save is
        # named after the game's top bar: "Manpower 203.3" (M)
        self.assertEqual(before["manpower"]["value"], 1332620)
        self.assertEqual(after["manpower"]["value"], 1639884 + 201692736)
        self.assertEqual(int(after["manpower"]["value"] / 100000) / 10, 203.3)
        self.assertEqual((before["convoys"]["value"], after["convoys"]["value"]), (200, 15))
        self.assertEqual(before["political_power"]["value"], after["political_power"]["value"])


if __name__ == "__main__":
    unittest.main()
