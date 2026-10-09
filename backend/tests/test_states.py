"""States from saves (text and binary 1.19.3) joined with the game's state files."""

import unittest

from hoi4dbg import gamefiles
from hoi4dbg.saves import binary as b
from hoi4dbg.saves import binvalues, states

from helpers import TempDirMixin
from savebuilder import Builder

T = states.T
TEXT_SAVE = (
    'HOI4txt\r\nsession=1\r\n'
    'provinces={\r\n\t11={\r\n\t\tcontroller="GER"\r\n\t}\r\n\t12={\r\n\t\tbuildings={\r\n\t\t\tnaval_base={\r\n'
    '\t\t\t\tlevel=3\r\n\t\t\t}\r\n\t\t}\r\n\t}\r\n}\r\n'
    'states={\r\n\t1={\r\n\t\tbuildings={\r\n\t\t\tinfrastructure={\r\n\t\t\t\tlevel=2\r\n\t\t\t}\r\n'
    '\t\t\tindustrial_complex={\r\n\t\t\t\tlevel=1\r\n\t\t\t}\r\n\t\t}\r\n\t\towner="FRA"\r\n'
    '\t\tmanpower_pool={\r\n\t\t\tavailable=1853\r\n\t\t\tlocked=317970\r\n\t\t\ttotal=323304\r\n\t\t}\r\n'
    '\t\tresources={\r\n\t\t\toil=10\r\n\t\t}\r\n\t\tstate_category=town\r\n\t}\r\n}\r\n'
    'countries={\r\n\tFRA={\r\n\t\tcores={ 1 2 }\r\n\t}\r\n\tGER={\r\n\t\tclaims={ 1 }\r\n\t}\r\n}\r\n')


def binary_save() -> bytes:
    bld = Builder(8)
    bld.key(T["provinces"]).open()
    bld.qstr("11").tok(b.EQUALS).open().key(T["controller"]).qstr("GER").close()
    bld.qstr("12").tok(b.EQUALS).open().key(T["buildings"]).open()
    bld.tok(0x31F6).tok(b.EQUALS).open().key(T["level"]).i32(3).close().close().close()
    bld.close()
    bld.key(T["states"]).open().i32(1).tok(b.EQUALS).open()
    bld.key(T["buildings"]).open()
    bld.tok(0x2FAB).tok(b.EQUALS).open().key(T["level"]).i32(2).close()
    bld.qstr("industrial_complex").tok(b.EQUALS).open().key(T["level"]).i32(1).close()
    bld.close()
    bld.key(T["owner"]).qstr("FRA")
    bld.key(T["manpower_pool"]).open().key(T["available"]).i32(1853).key(T["locked"]).i32(317970)
    bld.key(T["total"]).i32(323304).close()
    bld.key(T["resources"]).open().ustr("oil").tok(b.EQUALS).i32(10).close()
    bld.key(T["state_category"]).ustr("town")
    bld.close().close()
    bld.key(binvalues.TOKENS["countries"]).open()
    bld.qstr("FRA").tok(b.EQUALS).open().key(T["cores"]).open().i32(1).i32(2).close().close()
    bld.qstr("GER").tok(b.EQUALS).open().key(0x1234).i32(5).key(T["claims"]).open().i32(1).close().close()
    bld.close()
    return bld.bytes()


class StatesTests(TempDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        (self.tmp / "history" / "states").mkdir(parents=True)
        (self.tmp / "history" / "states" / "1-Corsica.txt").write_text(
            'state={\n\tid=1\n\tname="STATE_1" # comment\n\tprovinces={\n\t\t10 11 12\n\t}\n}\n', encoding="utf-8")
        (self.tmp / "localisation" / "english").mkdir(parents=True)
        (self.tmp / "localisation" / "english" / "state_names_l_english.yml").write_text(
            '﻿l_english:\n STATE_1:0 "Corsica"\n', encoding="utf-8")

    def check(self, data):
        rows = states.assemble(data, gamefiles.state_definitions(self.tmp), gamefiles.state_names(self.tmp))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["id"], row["name"], row["owner"], row["category"]), (1, "Corsica", "FRA", "town"))
        self.assertEqual(row["controllers"], {"FRA": 2, "GER": 1})   # province 11 occupied
        self.assertEqual(row["controller"], "FRA")
        self.assertEqual(row["buildings"], {"infrastructure": 2, "industrial_complex": 1})
        self.assertEqual(row["province_buildings"], {"naval_base": 3})
        self.assertEqual(row["resources"], {"oil": 10})
        self.assertEqual(row["manpower"], {"available": 1853, "locked": 317970, "total": 323304})
        self.assertEqual((row["cores"], row["claims"]), (["FRA"], ["GER"]))

    def test_text_save(self):
        self.check(states.read(TEXT_SAVE.encode(), "text", None, None))

    def test_binary_save(self):
        self.check(states.read(binary_save(), "binary", 8, "Operation Postern v1.19.3.0.c01a (5632)"))

    def test_binary_save_of_other_version_is_refused(self):
        with self.assertRaises(b.SaveFormatError):
            states.read(binary_save(), "binary", 8, "v1.17.0")


if __name__ == "__main__":
    unittest.main()
