import datetime as dt
import hashlib
import os
import shutil
import time
import unittest
from pathlib import Path

from hoi4dbg import applog
from hoi4dbg.saves import binary, reader, text
from hoi4dbg.service import NotFound

from helpers import TempDirMixin, make_service
from savebuilder import realistic_save
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
        values = text.country_values(text.country_block(TEXT_SAVE.encode(), "GER"))
        self.assertEqual(values["political_power"]["value"], 2.324)
        self.assertEqual(values["political_power"]["path"], "politics.political_power")
        self.assertEqual(values["stability"]["value"], 0.7)
        self.assertEqual(values["war_support"]["value"], 0.3)
        self.assertEqual(values["command_power"]["value"], 0.286)
        self.assertEqual(values["fuel"]["value"], 297201.86508)
        self.assertEqual(values["army_experience"]["value"], 30.0)
        self.assertEqual(values["air_experience"]["status"], "absent")
        self.assertEqual(values["manpower"]["status"], "unmapped")
        self.assertEqual(values["convoys"]["status"], "unmapped")

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

    def test_binary_save_is_reported_as_unmapped(self):
        self.write("GER.hoi4", realistic_save())
        payload = self.service().country_save_values("GER", None)
        self.assertEqual(payload["source"], "unavailable")
        self.assertEqual(payload["data"]["error"]["code"], "binary_values_unmapped")
        self.assertIn("-force_text_save", payload["note"])

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


if __name__ == "__main__":
    unittest.main()
