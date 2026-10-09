"""Country list: tags and names from game files, existence and ruling party from saves."""

import time
import os
import unittest

from hoi4dbg import applog, gamefiles
from hoi4dbg.saves import binary as b
from hoi4dbg.saves import binvalues, countries, reader

from helpers import TempDirMixin, make_service
from savebuilder import Builder
from test_saves import FakeSaveIntegration

# Shape of a real 1.19.3 text save: CRLF line ends, and lines the game writes without indentation
# inside nested blocks (given_resource_rights) - a column-0 '}' must not end the section.
TEXT_SAVE = (
    'HOI4txt\r\nplayer="ITA"\r\ndate="1936.2.1.3"\r\nversion="Operation Postern v1.19.3.0.c01a (5632)"\r\n'
    'player_countries={\r\n\tITA={\r\n\t\tuser="Czarny"\r\n\t}\r\n}\r\nsession=24\r\n'
    'states={\r\n\t1={\r\n\t\towner="FRA"\r\n\t}\r\n\t2={\r\n\t\towner="ITA"\r\n\t}\r\n\t3={\r\n\t\towner="FRA"\r\n\t}\r\n}\r\n'
    'countries={\r\n'
    '\tFRA={\r\n\t\tpolitics={\r\n\t\t\tparties={\r\n\t\t\t}\r\n\t\t\truling_party=democratic\r\n\t\t}\r\n'
    '\t\tgiven_resource_rights={\r\n\t\t\t{ oil "ENG"\r\n}\r\n { coal "ENG"\r\n}\r\n \t\t}\r\n\t}\r\n'
    '\tITA={\r\n\t\tpolitics={\r\n\t\t\truling_party=fascism\r\n\t\t}\r\n\t}\r\n'
    '\tKUR={\r\n\t\tpolitics={\r\n\t\t\truling_party=neutrality\r\n\t\t}\r\n\t}\r\n'
    '}\r\nsomething_else={\r\n\truling_party=wrong\r\n}\r\n')


def binary_save() -> bytes:
    bld = Builder(8)
    bld.key(0x2A4A).i32(5)  # an unrelated top-level field first
    bld.key(binvalues.TOKENS["countries"]).open()
    for tag, party in (("FRA", "democratic"), ("KUR", "neutrality")):
        bld.qstr(tag).tok(b.EQUALS).open()
        bld.key(0x1234).i32(1)
        bld.key(binvalues.TOKENS["politics"]).open().key(countries.RULING_PARTY).ustr(party).close()
        bld.close()
    bld.close()
    bld.key(countries.STATES).open()
    for sid, owner in ((1, "FRA"), (3, "FRA")):
        bld.i32(sid).tok(b.EQUALS).open().key(countries.OWNER).qstr(owner).close()
    bld.close()
    return bld.bytes()


class GameFilesTests(TempDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        tags = self.tmp / "common" / "country_tags"
        tags.mkdir(parents=True)
        (tags / "00_countries.txt").write_text('GER = "a"\n#SOV = "b"\nITA\t= "c"\n', encoding="utf-8")
        (tags / "zz_dynamic_countries.txt").write_text('D01 = "x"\nGER = "dup"\n', encoding="utf-8")
        loc = self.tmp / "localisation" / "english"
        loc.mkdir(parents=True)
        (loc / "countries_l_english.yml").write_text(
            '﻿l_english:\n GER:0 "Germany"\n GER_fascism:0 "German Reich"\n GER_DEF:0 "Germany"\n ITA: "Italy"\n',
            encoding="utf-8")

    def test_tag_order_and_names(self):
        self.assertEqual(gamefiles.tag_order(self.tmp), ["GER", "ITA", "D01"])
        names = gamefiles.country_names(self.tmp)
        self.assertEqual((names["GER"], names["GER_fascism"], names["ITA"]), ("Germany", "German Reich", "Italy"))
        self.assertNotIn("GER_DEF", names)


class SaveSummaryTests(unittest.TestCase):
    def test_text_save(self):
        res = countries.summary_text(TEXT_SAVE.encode())
        self.assertEqual(res["owners"], {"FRA": 2, "ITA": 1})
        self.assertEqual(res["ruling"], {"FRA": "democratic", "ITA": "fascism", "KUR": "neutrality"})

    def test_binary_save(self):
        res = countries.summary_binary(binary_save(), 8, "v1.19.3")
        self.assertEqual(res["owners"], {"FRA": 2})
        self.assertEqual(res["ruling"], {"FRA": "democratic"})  # KUR owns nothing: not parsed

    def test_binary_save_of_other_version_is_refused(self):
        with self.assertRaises(b.SaveFormatError) as ctx:
            countries.summary_binary(binary_save(), 8, "v1.17.0")
        self.assertEqual(ctx.exception.code, "binary_values_unmapped")


class InstallIntegration(FakeSaveIntegration):
    def __init__(self, saves_dir, install):
        super().__init__(saves_dir, None, "Operation Postern v1.19.3.0.c01a (5632)")
        self.install = install

    def detect(self):
        out = super().detect()
        out["install"]["path"] = str(self.install)
        return out


class CountriesServiceTests(GameFilesTests):
    def service(self):
        logger, _ = applog.setup(None)
        saves = self.tmp / "save games"
        saves.mkdir(exist_ok=True)
        svc = make_service(self.tmp, InstallIntegration(saves, self.tmp))
        svc.saves = reader.SaveAnalyzer(reader.SaveSnapshotter(self.tmp / "cache"), logger)
        return svc, saves

    def test_list_from_game_files_and_newest_save(self):
        svc, saves = self.service()
        path = saves / "italy.hoi4"
        path.write_text(TEXT_SAVE.replace("FRA", "GER"), encoding="utf-8", newline="")
        stamp = time.time() - 60
        os.utime(path, (stamp, stamp))
        res = svc.countries()
        self.assertEqual(res["source"], "save")
        by_tag = {c["tag"]: c for c in res["data"]}
        self.assertEqual([c["tag"] for c in res["data"]], ["GER", "ITA", "D01"])  # existing first, file order
        self.assertEqual((by_tag["GER"]["name"], by_tag["GER"]["states"], by_tag["GER"]["exists"]),
                         ("Germany", 2, True))  # GER_democratic not localised -> base name
        self.assertEqual((by_tag["ITA"]["player"], by_tag["ITA"]["is_player_country"], by_tag["ITA"]["is_ai"]),
                         ("Czarny", True, False))
        self.assertFalse(by_tag["D01"]["exists"])
        country = svc.country("ita")
        self.assertEqual((country["source"], country["data"]["ruling_party"], country["data"]["values"]),
                         ("save", "fascism", {}))

    def test_without_save_the_list_comes_from_game_files(self):
        svc, _ = self.service()
        res = svc.countries()
        self.assertEqual(res["source"], "live")
        self.assertEqual([c["exists"] for c in res["data"]], [None, None, None])
        self.assertEqual(svc.country("GER")["data"]["name"], "Germany")


if __name__ == "__main__":
    unittest.main()
