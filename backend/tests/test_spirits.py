import struct
import unittest
import zlib

from hoi4dbg import gfx, modifiers
from hoi4dbg.service import clean_loc


def dds(width, height, bgra_pixels):
    header = bytearray(128)
    header[:4] = b"DDS "
    struct.pack_into("<II", header, 12, height, width)
    struct.pack_into("<I4sIIIII", header, 80, 0x41, b"\0\0\0\0", 32, 0xFF0000, 0xFF00, 0xFF, 0xFF000000)
    return bytes(header) + bgra_pixels


class GfxTests(unittest.TestCase):
    def test_uncompressed_dds_to_png(self):
        png = gfx.dds_to_png(dds(2, 1, bytes([1, 2, 3, 255, 10, 20, 30, 128])))   # B G R A
        self.assertTrue(png.startswith(b"\x89PNG"))
        idat = png[png.index(b"IDAT") + 4:]
        raw = zlib.decompress(idat[:struct.unpack(">I", png[png.index(b"IDAT") - 4:png.index(b"IDAT")])[0]])
        self.assertEqual(raw, b"\x00" + bytes([3, 2, 1, 255, 30, 20, 10, 128]))      # filter byte + R G B A

    def test_compressed_or_broken_textures_are_skipped(self):
        compressed = bytearray(dds(4, 4, bytes(64)))
        struct.pack_into("<I4s", compressed, 80, 0x4, b"DXT5")
        self.assertIsNone(gfx.dds_to_png(bytes(compressed)))
        self.assertIsNone(gfx.dds_to_png(b"not a dds"))
        self.assertIsNone(gfx.dds_to_png(dds(64, 64, bytes(10))))                  # truncated pixels

    def test_sprite_index(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "interface").mkdir()
            (Path(tmp) / "interface" / "ideas.gfx").write_text(
                'spriteTypes = {\n\tSpriteType = {\n\t\tname = "GFX_idea_sisu"\n\t\ttexturefile = "gfx/interface/ideas/sisu.dds"\n\t}\n}\n')
            gfx.sprites.cache_clear()
            self.assertEqual(Path(gfx.sprites((tmp,))["GFX_idea_sisu"]), Path(tmp) / "gfx/interface/ideas/sisu.dds")


class LocTests(unittest.TestCase):
    def test_clean_loc(self):
        names = {"GER_mefo_bills": "MEFO Bills", "INNER": "$GER_mefo_bills$ x"}
        self.assertEqual(clean_loc("$GER_mefo_bills$", names), "MEFO Bills")
        self.assertEqual(clean_loc("$INNER$", names), "MEFO Bills x")                 # nested reference
        self.assertEqual(clean_loc("£prod_eff Production §YEfficiency§!", names), "Production Efficiency")
        self.assertEqual(clean_loc("[GER.GetNameDefCap] has a long\nhistory", names), "has a long\nhistory")


class SpiritListTests(unittest.TestCase):
    def test_only_country_ideas_and_enabled_dynamic_modifiers(self):
        defs = {"idea_meta": {"sisu": {"category": "country", "picture": "sisu_pic", "tooltips": ["tt"]},
                              "civilian_economy": {"category": "economy", "law": True},
                              "GER_philipp_holzmann": {"category": "industrial_concern"},
                              "bold_attack_spirit": {"category": "army_spirit"}},
                "idea_names": {"sisu": "FIN_sisu"}, "ideas": {"sisu": {"recovery_rate": 0.05}},
                "dynamic": {"plan": ["consumer_goods_factor", "stability_factor"]}, "dynamic_icons": {"plan": "GFX_plan"}}
        state = {"ideas": ["sisu", "civilian_economy", "GER_philipp_holzmann", "bold_attack_spirit"],
                 "dynamic_modifiers": [{"id": "plan", "values": ["0.1", "0"], "enabled": True},
                                       {"id": "plan", "values": ["0.2", "0"], "enabled": False}]}
        out = modifiers.spirits(state, defs)
        self.assertEqual([(s["id"], s["icon"]) for s in out], [("sisu", "GFX_idea_sisu_pic"), ("plan", "GFX_plan")])
        self.assertEqual(out[0]["name_key"], "FIN_sisu")
        self.assertEqual(out[1]["modifiers"], {"consumer_goods_factor": 0.1})          # zero values are not shown

    def test_custom_tooltips_do_not_shift_dynamic_values(self):
        self.assertIn("custom_modifier_tooltip", modifiers.NOT_MODIFIERS)


if __name__ == "__main__":
    unittest.main()


class Dds16Tests(unittest.TestCase):
    def test_x1r5g5b5_portrait(self):
        header = bytearray(128)
        header[:4] = b"DDS "
        struct.pack_into("<II", header, 12, 1, 1)
        struct.pack_into("<I4sIIIII", header, 80, 0x40, b"\0\0\0\0", 16, 0x7C00, 0x3E0, 0x1F, 0)
        png = gfx.dds_to_png(bytes(header) + struct.pack("<H", 0x7C00))   # pure red, no alpha
        idat = png.index(b"IDAT")
        raw = zlib.decompress(png[idat + 4:idat + 4 + struct.unpack(">I", png[idat - 4:idat])[0]])
        self.assertEqual(raw, b"\x00" + bytes([255, 0, 0, 255]))
