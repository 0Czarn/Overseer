import unittest

from hoi4dbg import trade

CIC = {r: 0.125 for r in trade.RESOURCES}


def player(**balance):
    used = {r: 10.0 for r in trade.RESOURCES}
    # balance +5 (above every target) unless given
    return {"resources": {"available": {r: 10.0 + balance.get(r, 5.0) for r in trade.RESOURCES}, "used": used},
            "factories": {"total": 154, "traded_goods": 0, "free": 47},
            "wars": [{"enemy": "GER", "offensive": False}], "ideology": "democratic",
            "faction": {"members": ["USA", "PHI"]}, "imports": [], "tag": "USA"}


def seller(free, ideology="neutrality", faction=(), **extra):
    return {"market": {r: free for r in trade.RESOURCES}, "ideology": ideology, "faction": list(faction), **extra}


class TradePlanTest(unittest.TestCase):
    def test_buys_from_the_best_seller(self):
        # USA 1936: chromium -4, rubber -1; ally PHI with 13 free beats a bigger democratic seller
        p = player(chromium=-4, rubber=-1)
        sellers = {"PHI": seller(13, "democratic"), "SAF": seller(98, "democratic"), "ITA": seller(500, "fascism"),
                   "GER": seller(900, "fascism"), "SMALL": seller(7, "democratic")}
        advice = trade.plan(p, sellers, CIC)
        rows = {r["resource"]: r for r in advice["resources"]}
        self.assertEqual(rows["chromium"]["buy"], [{"seller": "PHI", "amount": 8.0, "factories": 1, "score": 48,
                                                    "reasons": ["ally (same faction)", "same ideology (democratic)"]}])
        self.assertEqual(rows["oil"]["action"], "ok")
        sellers_seen = {c["seller"] for c in rows["rubber"]["candidates"]}
        self.assertNotIn("GER", sellers_seen)     # at war with the player
        self.assertNotIn("SMALL", sellers_seen)   # less than one factory's worth on the market
        self.assertEqual(advice["factories"]["budget"], 38)   # 25 % of 154
        self.assertEqual(advice["factories"]["planned"], 2)

    def test_rules_in_the_users_order(self):
        # each rule outweighs all the ones after it; overlord, enemy faction at the bottom; embargo excluded
        p = player(rubber=-1)
        sellers = {
            "PUP": seller(10, links={"subject": ["USA", "PUP"]}),
            "IDEO": seller(500, "democratic", opinion=50, border=True, continent=True,
                           links={"non_aggression_pact": ["IDEO", "USA"]}),
            "NEAR": seller(500, opinion=30, border=True, continent=True, links={"non_aggression_pact": ["NEAR", "USA"]}),
            "FAR": seller(900),
            "LORD": seller(900, "democratic", links={"subject": ["LORD", "USA"]}),
            "EMB": seller(900, "democratic", links={"embargo": ["EMB", "USA"]}),
        }
        rubber = next(r for r in trade.plan(p, sellers, CIC)["resources"] if r["resource"] == "rubber")
        self.assertEqual([c["seller"] for c in rubber["candidates"]], ["PUP", "IDEO", "NEAR", "FAR", "LORD"])
        self.assertEqual(rubber["buy"][0]["seller"], "PUP")
        self.assertIn("your overlord", rubber["candidates"][-1]["reasons"])

    def test_current_seller_breaks_ties_only(self):
        p = player(rubber=-1)
        p["imports"] = [{"seller": "B", "resource": "rubber", "amount": 8.0}]
        sellers = {"A": seller(400), "B": seller(10), "C": seller(10, "democratic")}
        order = [c["seller"] for c in next(r for r in trade.plan(p, sellers, CIC)["resources"]
                                           if r["resource"] == "rubber")["candidates"]]
        self.assertEqual(order, ["C", "B", "A"])   # B beats the bigger A by the bonus, not the same-ideology C

    def test_targets_and_limit(self):
        p = player(steel=-1)
        sellers = {"SWE": seller(92, "democratic")}
        steel = lambda a: next(r for r in a["resources"] if r["resource"] == "steel")  # noqa: E731
        self.assertEqual(steel(trade.plan(p, sellers, CIC, "tolerate"))["action"], "ok")    # -1 tolerated (-2)
        self.assertEqual(steel(trade.plan(p, sellers, CIC, "exact"))["buy"][0]["amount"], 8.0)
        p["factories"]["traded_goods"] = 38   # factory limit used up
        self.assertEqual(steel(trade.plan(p, sellers, CIC))["action"], "short")

    def test_cancels_deals_not_needed(self):
        p = player(oil=30)
        p["imports"] = [{"seller": "ROM", "resource": "oil", "amount": 16.0}, {"seller": "VEN", "resource": "oil", "amount": 24.0}]
        oil = trade.plan(p, {"ROM": seller(0), "VEN": seller(0, "democratic")}, CIC)["resources"][0]
        # 30 above the target of +2 = 28 spare: the worse seller ROM (16) can go, VEN (24) would drop below the target
        self.assertEqual(oil["cancel"], [{"seller": "ROM", "amount": 16.0, "factories": 2}])


if __name__ == "__main__":
    unittest.main()
