import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from hoi4dbg import campaign_map


def bmp(width, height, pixels):
    """A bottom-up 24-bit BMP of `pixels` (rows top to bottom of (r, g, b))."""
    stride = (width * 3 + 3) & ~3
    data = b""
    for row in reversed(pixels):
        line = b"".join(bytes((b, g, r)) for r, g, b in row)
        data += line + b"\0" * (stride - len(line))
    head = struct.pack("<2sIHHI", b"BM", 54 + len(data), 0, 0, 54)
    info = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0, len(data), 0, 0, 0, 0)
    return head + info + data


def decode(png):
    width, height = struct.unpack(">II", png[16:24])
    i, idat = 8, b""
    while i < len(png):
        n = struct.unpack(">I", png[i:i + 4])[0]
        if png[i + 4:i + 8] == b"IDAT":
            idat += png[i + 8:i + 8 + n]
        i += 12 + n
    raw = zlib.decompress(idat)
    rows = [raw[y * (width * 3 + 1) + 1:(y + 1) * (width * 3 + 1)] for y in range(height)]
    return [[tuple(r[3 * x:3 * x + 3]) for x in range(width)] for r in rows]


class CampaignMapTest(unittest.TestCase):
    def setUp(self):
        base = Path(tempfile.mkdtemp())
        self.game, self.mod = base / "game", base / "mod"
        red, blue, sea = (255, 0, 0), (0, 0, 255), (0, 255, 0)
        (self.game / "map").mkdir(parents=True)
        (self.game / "map" / "provinces.bmp").write_bytes(bmp(4, 2, [[sea, sea, sea, sea], [red, red, blue, blue]]))
        (self.game / "map" / "definition.csv").write_text(
            "0;0;0;0;land;false;unknown;0\n1;255;0;0;land;false;plains;1\n2;0;0;255;land;false;plains;1\n"
            "3;0;255;0;sea;false;ocean;0\n", encoding="utf-8")
        states = self.game / "history" / "states"
        states.mkdir(parents=True)
        (states / "1-A.txt").write_text('state = { id = 1 name = "STATE_1" provinces = { 1 } '
                                        'history = { victory_points = { 1 10 } victory_points = { 1 2.5 } } }')
        (states / "2-B.txt").write_text('state = { id = 2 name = "STATE_2" provinces = { 2 } }')
        (self.game / "common" / "country_tags").mkdir(parents=True)
        (self.game / "common" / "country_tags" / "00_countries.txt").write_text('GER = "countries/Germany.txt"\n')
        (self.game / "common" / "countries").mkdir(parents=True)
        (self.game / "common" / "countries" / "Germany.txt").write_text("color = { 10 20 30 }\n")

    def test_states_victory_points_and_colours(self):
        s = campaign_map.states([self.game])
        self.assertEqual((s[1]["vp"], s[1]["provinces"], s[2]["vp"]), (12.5, [1], 0))
        self.assertEqual(campaign_map.country_colors([self.game]), {"GER": "#0a141e"})
        (self.mod / "common" / "countries").mkdir(parents=True)   # a mod's colors.txt wins (what the map shows)
        (self.mod / "common" / "countries" / "colors.txt").write_text("GER = { color = rgb { 255 0 0 } }\n")
        self.assertEqual(campaign_map.country_colors([self.game, self.mod])["GER"], "#ff0000")

    def test_raster_holds_the_state_of_each_pixel(self):
        out = campaign_map.raster([self.game])
        self.assertEqual((out["width"], out["height"]), (2, 1))   # STEP 2: the lower right pixel of each 2 x 2 block
        self.assertEqual(decode(out["png"]), [[(0, 1, campaign_map.LAND), (0, 2, campaign_map.LAND)]])

    def test_a_mod_map_replaces_the_game_map(self):
        (self.mod / "map").mkdir(parents=True)
        (self.mod / "map" / "provinces.bmp").write_bytes(bmp(2, 2, [[(0, 0, 255)] * 2, [(0, 255, 0)] * 2]))
        cache = Path(tempfile.mkdtemp())
        out = campaign_map.raster([self.game, self.mod], cache)
        self.assertEqual(decode(out["png"]), [[(0, 0, campaign_map.SEA)]])
        self.assertEqual(len(list(cache.glob("campaign_map_*.png"))), 1)
        self.assertEqual(campaign_map.raster([self.game, self.mod], cache)["png"], out["png"])   # from the cache


if __name__ == "__main__":
    unittest.main()
