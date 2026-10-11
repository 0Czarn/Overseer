import unittest

from hoi4dbg.saves import politics, text

# Shape of the SOV 1936 country block (values from SOV_1936_03_12_01.hoi4)
BLOCK = """resources={
    produced={ oil=223 rubber=2 steel=593 }
    imported={ rubber=8 }
    to_use={ { oil=112 rubber=9 steel=297 } { } { rubber=-8 steel=-59 } }
    to_export={ oil=111 rubber=1 steel=296 }
    exported={ oil=111 steel=24 }
    export={ receiver="CHI" resource="oil" delivered=15 }
    export={ receiver="SIK" resource="steel" delivered=8 }
}"""


class ResourceTests(unittest.TestCase):
    def test_resources_of(self):
        r = politics.resources_of(text.parse(BLOCK))
        self.assertEqual(r["produced"]["steel"], 593.0)
        self.assertEqual((r["to_market"]["steel"], r["exported"]["steel"]), (296.0, 24.0))
        self.assertEqual((r["imported"]["rubber"], r["available"]["rubber"], r["used"]["rubber"]), (8.0, 9.0, 8.0))
        self.assertEqual(r["exports"], [{"receiver": "CHI", "resource": "oil", "amount": 15.0},
                                        {"receiver": "SIK", "resource": "steel", "amount": 8.0}])

    def test_missing_block(self):
        r = politics.resources_of([])
        self.assertEqual((r["produced"], r["used"], r["exports"]), ({}, {}, []))


if __name__ == "__main__":
    unittest.main()
