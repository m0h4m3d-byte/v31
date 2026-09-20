"""
portfolio.py - Shop-driven adaptive herd (v1: animals only, crops fixed).

Reads the town shop draw and splits the 15-head pasture budget across
COW/SHEEP by product demand instead of the frozen 10/5 PLAN:

    YARN-heavy draw  -> sheep-heavy herd (sell what town drains)
    no-YARN draw     -> cow-heavy herd (don't feed wool into $1)
    egg-heavy draw   -> (reserved: GOOSE stays 0 until coop placement is
                        proven ladder-profitable; see goose diagnostics)

Recomputed only when the unlocked-shop SET changes (days 3/6/9...62008);
days 0-2 run the baseline plan (no information exists yet). Targets gate
FUTURE buys only (missing = target - have); nothing is ever force-sold.
"""

from collections import Counter

# Shop -> {product: drain weight}. 2.0 marks single-product shops, which
# consume double (town rule). Names match the engine shop table + replays.
SHOP_DEMAND = {
    "BAKERY": {"EGG": 1.0, "WHEAT": 1.0},
    "PIZZA_SHOP": {"MILK": 1.0, "TOMATO": 1.0, "WHEAT": 1.0},
    "BRUNCH_SPOT": {"EGG": 1.0, "WHEAT": 1.0, "STRAWBERRY": 1.0},
    "YARN_STORE": {"WOOL": 2.0},
    "ICE_CREAM_SHOP": {"STRAWBERRY": 1.0, "MILK": 1.0, "WHEAT": 1.0},
    "PET_CAFE": {"CARROT": 2.0},
    "SMOOTHIE_SHOP": {"STRAWBERRY": 1.0, "MILK": 1.0},
    "FARMERS_MARKET": {"WHEAT": 1.0, "CARROT": 1.0, "TOMATO": 1.0, "STRAWBERRY": 1.0},
}

# Town center trickle: 1 unit of every non-fertilizer product per day.
CENTER_PRODUCTS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY",
                   "MELON", "EGG", "MILK", "WOOL")

HERD_BUDGET = 15  # central pasture block size; never exceed it
# Wide clamps: no-YARN worlds must be able to reach ~13/2 (kill the wool
# flood at its root instead of capping it after), yarn worlds ~4/10.
COW_MIN, COW_MAX = 3, 13
SHEEP_MIN, SHEEP_MAX = 0, 10


def demand_scores(shops):
    """{product: expected drain weight} for the current shop set."""
    out = Counter()
    for p in CENTER_PRODUCTS:
        out[p] += 0.5
    for shop in shops or []:
        for product, weight in SHOP_DEMAND.get(shop, {}).items():
            out[product] += weight
    return out


def adapt_herd(day, shops, base_plan):
    """Return {COW, SHEEP, GOOSE} targets splitting HERD_BUDGET by the
    milk/wool/egg demand shares. Pre-shop days (<3) keep the base plan."""
    base = dict(base_plan)
    if day < 3 or not shops:
        return {"COW": base.get("COW", 10), "SHEEP": base.get("SHEEP", 5),
                "GOOSE": base.get("GOOSE", 0)}
    scores = demand_scores(shops)
    milk = scores.get("MILK", 0.0)
    wool = scores.get("WOOL", 0.0)
    total = milk + wool
    if total <= 0:
        return {"COW": base.get("COW", 10), "SHEEP": base.get("SHEEP", 5),
                "GOOSE": base.get("GOOSE", 0)}
    # Split the 15-head budget proportionally between milk and wool demand.
    cows = min(COW_MAX, max(COW_MIN, int(round(HERD_BUDGET * milk / total))))
    sheep = min(SHEEP_MAX, max(SHEEP_MIN, HERD_BUDGET - cows))
    # Keep the pasture block exactly full without exceeding it.
    if cows + sheep > HERD_BUDGET:
        sheep = HERD_BUDGET - cows
    return {"COW": cows, "SHEEP": sheep, "GOOSE": 0}


def shops_signature(shops):
    return tuple(sorted(shops or []))


# Strawberry shops: every instance demanding it (smoothie/brunch/farmers/
# ice-cream). Seed target steps with instance count: base 20, +4 per
# instance up to 28. Day>=3 only (need one real shop wave, not noise).
STRAWBERRY_SHOPS = ("SMOOTHIE_SHOP", "BRUNCH_SPOT", "FARMERS_MARKET",
                    "ICE_CREAM_SHOP")
STRAW_BASE, STRAW_STEP, STRAW_MAX = 20, 4, 28


def adapt_straw(day, shops, base):
    """Adaptive strawberry seed target for straw-heavy draws."""
    if day < 3 or not shops:
        return base.get("STRAWBERRY", STRAW_BASE)
    n = sum(1 for s in shops if s in STRAWBERRY_SHOPS)
    if n <= 1:
        return base.get("STRAWBERRY", STRAW_BASE)
    return min(STRAW_MAX, base.get("STRAWBERRY", STRAW_BASE) + STRAW_STEP * (n - 1))
