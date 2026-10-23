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


def bmp8(width, height, rows):
    """A bottom-up 8-bit BMP of palette indexes `rows` (top to bottom), a grey palette."""
    stride = (width + 3) & ~3
    data = b"".join(bytes(r) + b"\0" * (stride - width) for r in reversed(rows))
    palette = b"".join(bytes((i, i, i, 0)) for i in range(256))
    head = struct.pack("<2sIHHI", b"BM", 54 + 1024 + len(data), 0, 0, 54 + 1024)
    info = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 8, 0, len(data), 0, 0, 256, 0)
    return head + info + palette + data


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
        self.assertEqual((s[1]["vps"], s[2]["vps"]), ({1: 2.5}, {}))   # per province: the last one in the file
        self.assertEqual(campaign_map.country_colors([self.game]), {"GER": "#0a141e"})
        (self.mod / "common" / "countries").mkdir(parents=True)   # a mod's colors.txt wins (what the map shows)
        (self.mod / "common" / "countries" / "colors.txt").write_text("GER = { color = rgb { 255 0 0 } }\n")
        self.assertEqual(campaign_map.country_colors([self.game, self.mod])["GER"], "#ff0000")

    def test_raster_holds_the_state_of_each_pixel(self):
        out = campaign_map.raster([self.game])
        self.assertEqual((out["width"], out["height"]), (4, 2))   # STEP 1: the whole map
        land = [(0, 1, campaign_map.LAND)] * 2 + [(0, 2, campaign_map.LAND)] * 2   # provinces 1, 2
        self.assertEqual(decode(out["png"]), [[(0, 3, campaign_map.SEA)] * 4, land])
        self.assertEqual(out["province_state"], [0, 1, 2, 0])   # province 3 is sea
        self.assertEqual((out["terrain_types"], out["province_terrain"]), (["", "plains"], [0, 1, 1]))   # 3: sea

    def test_outlines_of_the_provinces(self):
        cache = Path(tempfile.mkdtemp())
        out = campaign_map.borders([self.game], cache)
        magic, width, height, n_arcs, n_points, n_words = struct.unpack_from("<4s5I", out["data"])
        self.assertEqual((magic, width, height), (b"OVB1", 4, 2))
        self.assertEqual(len(out["data"]), 24 + 4 * (n_arcs + 1) + 4 * n_arcs + 4 * n_points + 4 * n_words)
        self.assertEqual(len(list(cache.glob("campaign_borders_*.bin"))), 1)
        ids = [[3] * 4, [1, 1, 2, 2]]
        import numpy as np
        arcs, rings = campaign_map.trace(np.array(ids, dtype=np.int32), campaign_map._kind_of(
            {1: "land", 2: "land", 3: "sea"}, 3))
        self.assertIn((1, 2, [(4, 2), (4, 4)]), arcs)   # x = 2 from y 1 to 2 (half pixels), province 1 west of it
        self.assertTrue(all(p in (1, 2) or q in (1, 2) for p, q, _ in arcs))   # no sea-only border
        self.assertEqual(sorted(rings), [1, 2])   # land and lakes only
        for pid in (1, 2):   # one ring each, the province on the same side: a positive area near its 2 pixels
            pts = []
            for ref in rings[pid][0]:
                line = arcs[ref][2] if ref >= 0 else arcs[~ref][2][::-1]
                pts += line if not pts else line[1:]
            area = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1])) / 8
            self.assertEqual(len(rings[pid]), 1)
            self.assertGreater(area, 1.5)
            self.assertLessEqual(area, 2)

    def test_relief_and_rivers(self):
        import numpy as np
        heights = np.zeros((4, 8), dtype=np.uint8)
        heights[:, 4:] = 200   # a slope up to the east: lit side faces west -> darker (light from the north-west)
        land = np.ones((4, 8), dtype=bool)
        land[:, :2] = False
        w, h, grey = campaign_map.relief(heights, land)
        self.assertEqual((w, h), (4, 2))
        rows = [list(grey[i * w:(i + 1) * w]) for i in range(h)]
        self.assertEqual(rows[0][0], 128)   # off land: flat
        self.assertLess(rows[0][1], 128)    # the slope rising to the south-east
        self.assertEqual(rows[0][3], 128)   # flat top
        px = np.full((5, 6), 255, dtype=np.uint8)   # an L-shaped narrow river (3) joining a wide one (11)
        px[0, 1] = 0                                  # its source
        px[1:4, 1] = 3
        px[3, 2:6] = 11
        lines = campaign_map.rivers(px)
        narrow = [l for l in lines if l[0] == 3]
        self.assertEqual(len(narrow), 1)
        self.assertEqual(sorted([narrow[0][1:3], narrow[0][-2:]]), [[1.5, 0.5], [1.5, 3.5]])   # source to the corner
        wide = sorted(sorted([l[1:3], l[-2:]]) for l in lines if l[0] == 11)   # the join takes the wider class
        self.assertEqual(wide, [[[1.5, 3.5], [2.5, 3.5]], [[2.5, 3.5], [5.5, 3.5]]])
        self.assertTrue(all(len(l) == 5 for l in lines if l[0] == 11))   # straight: the two ends only
        (self.game / "map" / "heightmap.bmp").write_bytes(bmp8(4, 2, [[0] * 4, [0, 0, 50, 50]]))
        (self.game / "map" / "rivers.bmp").write_bytes(bmp8(4, 2, [[255] * 4, [3, 3, 255, 255]]))
        cache = Path(tempfile.mkdtemp())
        out = campaign_map.terrain([self.game], cache)
        self.assertEqual((out["relief"]["width"], out["relief"]["height"]), (2, 1))
        self.assertEqual(out["rivers"], [[3, 0.5, 1.5, 1.5, 1.5]])
        self.assertEqual(campaign_map.terrain([self.game], cache), out)   # from the cache

    def test_building_types_in_the_games_order(self):
        folder = self.game / "common" / "buildings"
        folder.mkdir(parents=True)
        (folder / "00_buildings.txt").write_text(
            "buildings = {\n\tinfrastructure = {\n\t\tlevel_cap = { province_max = 5 }\n\t}\n"
            "\trail_way = { show_on_map = 1 }\n}\nspawn_points = {\n\tnaval_base_spawn = { type = naval_base }\n}\n")
        (folder / "01_landmarks.txt").write_text("buildings = { landmark_big_ben = { } }\n")
        self.assertEqual(campaign_map.building_types([self.game]), ["infrastructure", "rail_way", "landmark_big_ben"])

    def test_a_mod_map_replaces_the_game_map(self):
        (self.mod / "map").mkdir(parents=True)
        (self.mod / "map" / "provinces.bmp").write_bytes(bmp(2, 2, [[(0, 0, 255)] * 2, [(0, 255, 0)] * 2]))
        cache = Path(tempfile.mkdtemp())
        out = campaign_map.raster([self.game, self.mod], cache)
        self.assertEqual(decode(out["png"]), [[(0, 2, campaign_map.LAND)] * 2, [(0, 3, campaign_map.SEA)] * 2])
        self.assertEqual(len(list(cache.glob("campaign_map_*.png"))), 1)
        self.assertEqual(campaign_map.raster([self.game, self.mod], cache)["png"], out["png"])   # from the cache


if __name__ == "__main__":
    unittest.main()
