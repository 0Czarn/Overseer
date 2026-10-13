"""Trade advisor (Trading_opt.txt): which import deals cover the player's shortages of oil, aluminium, rubber,
tungsten, steel and chromium, from which seller, and which deals are no longer needed. The app only advises - the
player makes and cancels deals in the game (no console command or script effect cancels an import deal).

Rules (user's description): buy only where trade is possible - not from a country at war with the player, not with
an embargo either way, not when the seller's unsold surplus is below one factory's worth, not without free civilian
factories; within a factory limit (10-100 % of civilian factories, default 25 %); keep each balance at a target
(+2, exactly 0, or tolerate -2). Sellers ranked in the user's order - the player's puppets, allies (same faction),
the same ideology, a good opinion of the player, a non-aggression pact, a shared border, the same continent - each
rule outweighing all the ones after it; at the bottom the player's overlord and a seller whose faction is at war
with the player. A tie goes to the bigger surplus; the current seller gets a small bonus so deals do not jump
between nearly equal countries every month. Rules that need data the app cannot read yet are listed in UNCHECKED.
"""

from __future__ import annotations

import math

RESOURCES = ("oil", "aluminium", "rubber", "tungsten", "steel", "chromium")
BALANCE_TARGETS = {"surplus": 2.0, "exact": 0.0, "tolerate": -2.0}
DEFAULT_LIMIT = 0.25
# points of a seller (higher = better): each rule outweighs every rule below it; the current seller bonus only
# breaks ties between otherwise equal sellers
SCORE = {"puppet": 64, "ally": 32, "ideology": 16, "opinion": 8, "non_aggression_pact": 4, "border": 2,
         "continent": 1, "current": 0.5, "overlord": -200, "enemy_faction": -200}
GOOD_OPINION = 1   # opinion of the player from this value up counts as good
UNCHECKED = ("countries preparing war (wargoals)", "volunteers", "convoys for sea routes")


def seller_score(seller: str, info: dict, player: dict, resource: str) -> tuple[int, list[str]]:
    """(points, reasons) of one seller for the player."""
    points, reasons = 0, []
    links, tag = info.get("links") or {}, player.get("tag")
    overlord, subject = (links.get("subject") or [None, None])[:2]
    if subject == seller and overlord == tag:
        points += SCORE["puppet"]
        reasons.append("your puppet")
    if seller in (player.get("faction") or {}).get("members", []):
        points += SCORE["ally"]
        reasons.append("ally (same faction)")
    if info.get("ideology") and info["ideology"] == player.get("ideology"):
        points += SCORE["ideology"]
        reasons.append(f"same ideology ({info['ideology']})")
    if info.get("opinion") is not None and info["opinion"] >= GOOD_OPINION:
        points += SCORE["opinion"]
        reasons.append(f"good opinion of you ({info['opinion']:+d})")
    if "non_aggression_pact" in links:
        points += SCORE["non_aggression_pact"]
        reasons.append("non-aggression pact")
    if info.get("border"):
        points += SCORE["border"]
        reasons.append("shared border")
    if info.get("continent"):
        points += SCORE["continent"]
        reasons.append("same continent")
    if overlord == seller and subject == tag:
        points += SCORE["overlord"]
        reasons.append("your overlord")
    enemies = {w["enemy"] for w in player.get("wars") or []}
    if enemies & set(info.get("faction") or []):
        points += SCORE["enemy_faction"]
        reasons.append("its faction is at war with you")
    if any(d["seller"] == seller and d["resource"] == resource for d in player.get("imports") or []):
        points += SCORE["current"]
        reasons.append("current seller")
    return points, reasons


def plan(player: dict, sellers: dict[str, dict], cic: dict[str, float], mode: str = "surplus",
         limit: float = DEFAULT_LIMIT) -> dict:
    """Advice for the player: per resource the balance, target, deals to make (seller, amount, factories) and deals
    no longer needed; the factory budget. `cic` = civilian factories per unit of each resource (common/resources)."""
    target = BALANCE_TARGETS.get(mode, BALANCE_TARGETS["surplus"])
    limit = min(1.0, max(0.1, limit))
    res, f = player["resources"], player["factories"]
    enemies = {w["enemy"] for w in player.get("wars") or []}
    budget = max(0, math.floor(f["total"] * limit) - f["traded_goods"])
    budget = min(budget, f["free"])
    left = budget
    rows = []
    for r in RESOURCES:
        unit = 1 / cic.get(r, 0.125)   # units of one factory's worth (8)
        balance = round(res["available"].get(r, 0.0) - res["used"].get(r, 0.0), 3)
        row = {"resource": r, "balance": balance, "target": target, "buy": [], "cancel": [], "candidates": [],
               "missing": 0.0}
        candidates = []
        for t, info in sellers.items():
            free = info["market"].get(r, 0.0)
            if t in enemies or free < unit or "embargo" in (info.get("links") or {}):
                continue
            points, reasons = seller_score(t, info, player, r)
            candidates.append({"seller": t, "free": free, "score": points, "reasons": reasons})
        candidates.sort(key=lambda c: (-c["score"], -c["free"], c["seller"]))
        row["candidates"] = candidates[:5]
        need = target - balance
        if need > 1e-9:
            for c in candidates:
                if need <= 1e-9 or left <= 0:
                    break
                amount = min(unit * math.ceil(need / unit), unit * math.floor(c["free"] / unit), unit * left)
                if amount <= 0:
                    continue
                factories = math.ceil(amount * cic.get(r, 0.125) - 1e-9)
                row["buy"].append({"seller": c["seller"], "amount": amount, "factories": factories,
                                   "score": c["score"], "reasons": c["reasons"]})
                left -= factories
                need -= amount
            row["missing"] = round(max(0.0, need), 3)
        else:
            # deals beyond the target: drop the worst sellers first while the balance stays at the target
            spare = -need
            deals = [d for d in player.get("imports") or [] if d["resource"] == r and d["amount"]]
            score = {d["seller"]: seller_score(d["seller"], sellers.get(d["seller"], {}), player, r)[0] for d in deals}
            for d in sorted(deals, key=lambda d: (score[d["seller"]], d["amount"])):
                if d["amount"] <= spare + 1e-9:
                    row["cancel"].append({"seller": d["seller"], "amount": d["amount"],
                                          "factories": math.ceil(d["amount"] * cic.get(r, 0.125) - 1e-9)})
                    spare -= d["amount"]
        row["action"] = "buy" if row["buy"] else "cancel" if row["cancel"] else "short" if row["missing"] else "ok"
        rows.append(row)
    return {"mode": mode, "target": target, "limit": limit, "resources": rows, "unchecked": list(UNCHECKED),
            "factories": {"total": f["total"], "limit": math.floor(f["total"] * limit), "trade_now": f["traded_goods"],
                          "free": f["free"], "budget": budget, "planned": budget - left}}
