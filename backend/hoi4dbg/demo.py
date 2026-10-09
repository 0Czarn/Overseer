"""DEMO dataset.

Everything here is invented sample data used to build and test the UI before
real game reading exists. It must always be served with source="demo" and is
never presented as the state of a running game. Values are not taken from
HOI4 and are not guaranteed to match any real start date.
"""

from __future__ import annotations

import copy

COUNTRIES: list[dict] = [
    {"tag": "GER", "name": "Germany", "player": "DEMO Tester 1", "is_ai": False},
    {"tag": "SOV", "name": "Soviet Union", "player": "DEMO Tester 2", "is_ai": False},
    {"tag": "ENG", "name": "United Kingdom", "player": None, "is_ai": True},
    {"tag": "FRA", "name": "France", "player": None, "is_ai": True},
    {"tag": "ITA", "name": "Italy", "player": None, "is_ai": True},
    {"tag": "USA", "name": "United States", "player": None, "is_ai": True},
    {"tag": "JAP", "name": "Japan", "player": None, "is_ai": True},
    {"tag": "POL", "name": "Poland", "player": None, "is_ai": True},
]

# Field keys shared with the Country Editor UI. Units describe how the UI formats them.
COUNTRY_FIELDS: list[dict] = [
    {"key": "political_power", "label": "Political Power", "unit": "number"},
    {"key": "stability", "label": "Stability", "unit": "percent"},
    {"key": "war_support", "label": "War Support", "unit": "percent"},
    {"key": "manpower", "label": "Manpower", "unit": "integer"},
    {"key": "fuel", "label": "Fuel", "unit": "integer"},
    {"key": "convoys", "label": "Convoys", "unit": "integer"},
    {"key": "command_power", "label": "Command Power", "unit": "number"},
    {"key": "army_experience", "label": "Army Experience", "unit": "number"},
    {"key": "air_experience", "label": "Air Experience", "unit": "number"},
    {"key": "navy_experience", "label": "Navy Experience", "unit": "number"},
]

_COUNTRY_VALUES: dict[str, dict] = {
    "GER": dict(political_power=112.4, stability=0.62, war_support=0.41, manpower=1_250_000, fuel=48_000,
                convoys=40, command_power=31.0, army_experience=12.5, air_experience=8.0, navy_experience=3.2),
    "SOV": dict(political_power=87.0, stability=0.38, war_support=0.30, manpower=2_800_000, fuel=61_000,
                convoys=25, command_power=18.5, army_experience=5.0, air_experience=2.0, navy_experience=1.0),
    "ENG": dict(political_power=150.0, stability=0.70, war_support=0.15, manpower=420_000, fuel=90_000,
                convoys=500, command_power=40.0, army_experience=1.0, air_experience=4.0, navy_experience=20.0),
    "FRA": dict(political_power=60.0, stability=0.45, war_support=0.20, manpower=900_000, fuel=30_000,
                convoys=120, command_power=22.0, army_experience=3.0, air_experience=1.5, navy_experience=6.0),
    "ITA": dict(political_power=75.5, stability=0.55, war_support=0.50, manpower=650_000, fuel=12_000,
                convoys=90, command_power=25.0, army_experience=9.0, air_experience=6.0, navy_experience=7.5),
    "USA": dict(political_power=40.0, stability=0.80, war_support=0.05, manpower=380_000, fuel=200_000,
                convoys=300, command_power=10.0, army_experience=0.0, air_experience=0.0, navy_experience=2.0),
    "JAP": dict(political_power=95.0, stability=0.65, war_support=0.70, manpower=1_100_000, fuel=25_000,
                convoys=200, command_power=35.0, army_experience=15.0, air_experience=9.0, navy_experience=18.0),
    "POL": dict(political_power=30.0, stability=0.50, war_support=0.35, manpower=500_000, fuel=5_000,
                convoys=10, command_power=8.0, army_experience=0.5, air_experience=0.5, navy_experience=0.2),
}

STATES: list[dict] = [
    {"id": "demo-1", "name": "DEMO Northland", "owner": "GER", "controller": "GER",
     "buildings": {"infrastructure": 4, "industrial_complex": 6, "arms_factory": 3, "air_base": 2},
     "resources": {"steel": 12, "aluminium": 4}, "cores": ["GER"], "claims": []},
    {"id": "demo-2", "name": "DEMO Eastmark", "owner": "POL", "controller": "GER",
     "buildings": {"infrastructure": 3, "industrial_complex": 2},
     "resources": {"tungsten": 2}, "cores": ["POL"], "claims": ["GER"]},
    {"id": "demo-3", "name": "DEMO Steppe", "owner": "SOV", "controller": "SOV",
     "buildings": {"infrastructure": 2, "arms_factory": 5},
     "resources": {"oil": 20, "chromium": 6}, "cores": ["SOV"], "claims": []},
    {"id": "demo-4", "name": "DEMO Harbour", "owner": "ENG", "controller": "ENG",
     "buildings": {"infrastructure": 5, "dockyard": 4, "naval_base": 6},
     "resources": {"rubber": 3}, "cores": ["ENG"], "claims": []},
    {"id": "demo-5", "name": "DEMO Riviera", "owner": "FRA", "controller": "ITA",
     "buildings": {"infrastructure": 4, "industrial_complex": 3},
     "resources": {}, "cores": ["FRA"], "claims": ["ITA"]},
]

# status: completed | in_progress | available | blocked
FOCUSES: dict[str, list[dict]] = {
    "GER": [
        {"id": "DEMO_focus_industry", "name": "DEMO Industrial Effort", "status": "completed", "days": 70},
        {"id": "DEMO_focus_army", "name": "DEMO Army Reform", "status": "in_progress", "days": 70, "progress": 0.4},
        {"id": "DEMO_focus_air", "name": "DEMO Air Doctrine", "status": "available", "days": 70},
        {"id": "DEMO_focus_navy", "name": "DEMO Naval Plans", "status": "available", "days": 35},
        {"id": "DEMO_focus_alliance", "name": "DEMO Alliance Talks", "status": "blocked", "days": 70,
         "blocked_by": "DEMO_focus_army"},
    ],
}

EQUIPMENT: dict[str, list[dict]] = {
    "GER": [
        {"type": "infantry_equipment", "variant": "DEMO Rifle Mk1", "stockpile": 42_000, "required": 38_000},
        {"type": "support_equipment", "variant": "DEMO Support Kit", "stockpile": 3_100, "required": 2_400},
        {"type": "artillery_equipment", "variant": "DEMO Field Gun", "stockpile": 1_800, "required": 2_200},
        {"type": "fighter", "variant": "DEMO Fighter A", "stockpile": 320, "required": 0},
    ],
}

# Intelligence categories as presented in the UI. Values are DEMO percentages.
INTEL: dict[tuple[str, str], dict] = {
    ("GER", "SOV"): {"civilian": 0.35, "army": 0.20, "navy": 0.10, "airforce": 0.15},
    ("SOV", "GER"): {"civilian": 0.25, "army": 0.30, "navy": 0.05, "airforce": 0.10},
}


def countries() -> list[dict]:
    return copy.deepcopy(COUNTRIES)


def country(tag: str) -> dict | None:
    tag = tag.upper()
    base = next((c for c in COUNTRIES if c["tag"] == tag), None)
    if base is None:
        return None
    return {**copy.deepcopy(base), "values": dict(_COUNTRY_VALUES.get(tag, {}))}


def states() -> list[dict]:
    return copy.deepcopy(STATES)


def focuses(tag: str) -> list[dict]:
    return copy.deepcopy(FOCUSES.get(tag.upper(), []))


def equipment(tag: str) -> list[dict]:
    return copy.deepcopy(EQUIPMENT.get(tag.upper(), []))


def intel(observer: str, target: str) -> dict | None:
    levels = INTEL.get((observer.upper(), target.upper()))
    return dict(levels) if levels else None
