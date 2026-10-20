import unittest

from hoi4dbg import triggers


class FakeWorld:
    def __init__(self):
        self.gov = {"GER": "fascism", "CZE": "democratic", "ENG": "democratic", "AST": "democratic", "SOV": "communism"}
        self.pop = {"CZE": {"fascism": 0.04, "democratic": 0.8}}
        self.states = {42: {"owner": "GER", "controller": "GER", "cores": ["GER"]},
                       51: {"owner": "GER", "controller": "FRA", "cores": ["GER"]}}
        self.subject = [("subject", "ENG", "AST")]

    def countries(self): return ["GER", "CZE", "ENG", "AST", "SOV", "FRA"]
    def players(self): return {"GER"}
    def dlcs(self): return {"La Resistance"}
    def government(self, t): return self.gov.get(t)
    def ideology_names(self): return ["democratic", "fascism", "communism", "neutrality"]
    def popularity(self, t, i): return self.pop.get(t, {}).get(i)
    def army_manpower(self, t): return 330200 if t == "GER" else 0
    def links(self, t): return [x for x in self.subject if t in x[1:]]
    def overlord(self, t): return next((a for k, a, b in self.links(t) if b == t), None)
    def subjects(self, t): return [b for k, a, b in self.links(t) if a == t]
    def wars(self, t): return {"GER": [], "SOV": []}.get(t, [])
    def faction(self, t): return ["SOV"] if t == "SOV" else None
    def completed(self, t): return ["GER_rearmament"] if t == "GER" else []
    def ideas(self, t): return []
    def dynamic_modifiers(self, t): return []
    def techs(self, t): return ["basic_machine_tools"] if t == "GER" else []
    def state(self, sid): return self.states.get(sid)
    def state_ids(self): return list(self.states)
    def opinion(self, t, o): return 10
    def justifying(self, t): return set()
    def political_power(self, t): return 75.0
    def factories(self, t): return 40


def ev(source, scripted=None, root="GER"):
    ctx = triggers.Context(FakeWorld(), root, scripted)
    return triggers.evaluate(triggers.parse(source), ctx), sorted(ctx.unknown)


class TriggerTests(unittest.TestCase):
    def test_parse_keeps_comparison_operators(self):
        self.assertEqual(triggers.parse("has_political_power > 50 CZE = { fascism < 0.5 } # x"),
                         [("has_political_power", ">", "50"), ("CZE", "=", [("fascism", "<", "0.5")])])

    def test_key_and_block_without_equals(self):
        self.assertEqual(triggers.parse("mutually_exclusive { focus = A }"), [("mutually_exclusive", "=", [("focus", "=", "A")])])
        from hoi4dbg import focus
        f = focus._focus([("id", "X"), "mutually_exclusive", [("focus", "A")], ("cost", "5")])
        self.assertEqual((f["id"], f["exclusive"], f["days"]), ("X", ["A"], 35))

    def test_rhineland_like_block(self):
        src = "is_subject = no has_government = fascism 42 = { is_fully_controlled_by = ROOT }"
        self.assertEqual(ev(src), (True, []))
        self.assertEqual(ev(src + " 51 = { is_fully_controlled_by = ROOT }")[0], False)

    def test_not_is_a_nor_and_or_any_of(self):
        self.assertEqual(ev("NOT = { has_war = yes is_subject = yes }")[0], True)
        self.assertEqual(ev("NOT = { has_war = no is_subject = yes }")[0], False)
        self.assertEqual(ev("OR = { has_war = yes has_tech = basic_machine_tools }")[0], True)

    def test_unknown_triggers_are_none_and_named_but_decided_branches_win(self):
        self.assertEqual(ev("has_country_flag = x"), (None, ["has_country_flag"]))
        self.assertEqual(ev("has_country_flag = x has_war = yes")[0], False)                 # AND with a false
        self.assertEqual(ev("OR = { has_country_flag = x has_war = no }")[0], True)          # OR with a true

    def test_scopes_iterators_popularity_and_subjects(self):
        self.assertEqual(ev("CZE = { OR = { has_government = fascism fascism > 0.5 } }")[0], False)
        self.assertEqual(ev("ENG = { has_subject = AST } AST = { is_subject_of = ENG }")[0], True)
        self.assertEqual(ev("any_other_country = { has_government = communism is_faction_leader = yes }")[0], True)
        self.assertEqual(ev("has_army_manpower = { size > 749999 }")[0], False)
        self.assertEqual(ev("SPA = { has_government = fascism }")[0], False)                 # does not exist
        self.assertEqual(ev("SPA = { exists = no }")[0], True)

    def test_if_else_and_scripted_triggers(self):
        src = 'if = { limit = { has_dlc = "La Resistance" } has_war = yes } else = { always = yes }'
        self.assertEqual(ev(src)[0], False)
        self.assertEqual(ev('if = { limit = { has_dlc = "Nope" } has_war = yes } else = { always = yes }')[0], True)
        self.assertEqual(ev("my_trigger = yes", {"my_trigger": [("has_war", "=", "no")]})[0], True)
        self.assertEqual(ev("my_trigger = no", {"my_trigger": [("has_war", "=", "no")]})[0], False)


if __name__ == "__main__":
    unittest.main()
