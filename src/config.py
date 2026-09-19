"""
config.py — Single source of truth for ALL decision numbers
Effective values as actually used on main a2debda (v26, mean 90225)
AFTER cleanup: NO os.environ / KAGG_* toggles — every value is explicit.

Principle: any KAGG_* that was ON/OFF is now frozen as a plain constant.
To change a value, edit it HERE ONLY. No hidden env var can override it.
"""

# ============================================================
# Core economy — frozen effective values (were KAGG_* defaults)
# ============================================================
PLAN = {"COW": 10, "SHEEP": 5, "GOOSE": 0, "MELON": 12, "STRAWBERRY": 20, "WHEAT": 15}

LAND_COSTS = [1000, 2000, 4000]
LAND_DAYS = [6, 9, 12]
# Liquidity gate: cash that must remain AFTER paying land cost.
# Blocks NE-with-$115 / SW-with-$25 buys; neutral once rich.
LAND_BUY_BUFFER = 300

HIRE_TARGET = 12
# Flexible hiring, one degree at a time: while poor (money below threshold),
# skip ONLY the single priciest hire of the day (13th hand = $233 fib tail).
# Smaller than the rejected cap-8 experiment; workforce impact minimal.
HIRE_POOR_MONEY = 1500
HIRE_POOR_HANDS = 12
PASTURE_BUFFER = 2
RESERVE = 15
SHED_CAPACITY = 100
# Overflow force-dump trips at 95 (near-full): drain as 5-unit samples per
# product (no flood) to rotate stock instead of discarding overflow.
SHED_DUMP_AT = 95
# Force drain fires ONLY when both hold: (1) shed full AND premium prices
# sliding, (2) incoming harvest exceeds free room. Otherwise healthy-full
# sheds drain at normal caps, crashed-full sheds wait for recovery.
FORCE_SLIDE_DROP = 0.25
FORCE_PEAK_FLOOR = 100

SELL_HOLD_DAY = {"MILK": 0, "WOOL": 0, "EGG": 0, "STRAWBERRY": 0}
# Floor guard: never SELL below this live price, except overflow force-dump
# (shed>=SHED_DUMP_AT) or final liquidation (day>=LIQUIDATE_DAY). Selling at
# $1-5 wastes harvest/haul labor for ~zero revenue; waiting is cheaper.
SELL_FLOOR_MIN = 10
# Melon floor sits ABOVE seed cost (80/6 = 13.3$/unit) with margin: below
# 25 a melon sale cannot repay seed+labor. Other goods keep the general
# floor (wheat seed is ~3$/unit; fertilizer must always flow).
MELON_FLOOR_MIN = 25
# Melon: no waiting for peaks (ladder rivals skim them early). Sell first
# flushes immediately; PANIC-dump everything at the first 20% slide off the
# running peak instead of riding to $1.
MELON_PANIC_DROP = 0.20
# Strawberry early exit (BULL/BAIL template): 4 flushes on days 10/12/14/16;
# classify at 12 on the advisor-trusted 190; bulls hold through the last
# flush (16), bailouts release at the first -20% slide inside 13-15.
STRAW_BULL_DAY = 12
STRAW_BULL_PRICE = 190
STRAW_BULL_HOLD_DAY = 16
STRAW_BAIL_FROM_DAY = 13
STRAW_BAIL_FACTOR = 0.80
MILK_BULL_D12 = 180
MILK_BULL_HOLD_DAY = 20
MILK_BAIL_FROM_DAY = 16
MILK_BAIL_FACTOR = 0.85

MARKET_AWARE_ON = True  # was KAGG_MARKET_AWARE=1 default ON
MARKET_AWARE_CAPS = {
    # Tranches, not floods: halved premium caps spread flush-day dumps over
    # several days at higher average prices (caps bind on flushes, rarely on
    # daily production). Staples keep full flow (they absorb gluts).
    "MELON": 12,
    "WOOL": 15,
    "MILK": 20,
    "STRAWBERRY": 25,
    "EGG": 80,
    "WHEAT": 150,
    "FERTILIZER": 80,
    "CARROT": 60,
    "TOMATO": 40,
}

ANIMALS = {
    "COW": {"cost": 400, "struct": "PASTURE", "product": "MILK"},
    "SHEEP": {"cost": 500, "struct": "PASTURE", "product": "WOOL"},
    "GOOSE": {"cost": 300, "struct": "COOP", "product": "EGG"},
}
SEED_COST = {"WHEAT": 10, "CARROT": 20, "TOMATO": 50, "STRAWBERRY": 100, "MELON": 80}

FEED_RESERVE = 4

# AnimalAdvisor — was KAGG_ANIMAL_ADVISOR=1 default ON
ANIMAL_ADVISOR_ON = True
MILK_CRASH_PRICE = 120
ANIMAL_ADVISOR_MIN_DAY = 10
MILK_TREND_DROP = 0.75
# Wool crash breaker (mirror of milk logic): no-YARN worlds where wool
# collapses need a sheep freeze, otherwise the milk-crash redirect below
# pours the pen budget into the crashing good. Neutral with YARN present.
WOOL_CRASH_PRICE = 100
WOOL_CRASH_MIN_DAY = 10
WOOL_CRASH_DROP = 0.60
WOOL_NO_YARN_CAP = 2

# ============================================================
# Board layout — single source for pastures — 15 central contiguous (5 per quad)
# NW(5) NE(5) SW(5) all 1-2 steps from shed, no plant gap inside block
# ============================================================
SHED_TILES = [(4, 4), (5, 4), (4, 5), (5, 5)]
# Central contiguous clusters:
# NW: (4,2)-(3,3)-(4,3)-(3,4)-(4,4)  NE: (5,2)-(5,3)-(6,3)-(5,4)-(6,4)  SW: (2,5)-(3,5)-(4,5)-(3,6)-(4,6)
PASTURE_LOCATIONS = [
    (4, 3), (3, 4), (4, 4), (3, 3), (4, 2),  # NW 5 - closest to shed first
    (5, 4), (5, 3), (6, 4), (6, 3), (5, 2),  # NE 5
    (4, 5), (3, 5), (3, 6), (4, 6), (2, 5),  # SW 5
]
COOP_POS = [(0, 0)]

CROP_CONFIG = {
    "WHEAT": {"seed_cost": 10, "base_price": 25, "first_yield_day": 2, "max_yield_day": 4, "max_yield": 6, "max_yield_no_fertilizer": 4, "is_ongoing": False},
    "CARROT": {"seed_cost": 20, "base_price": 35, "first_yield_day": 2, "max_yield_day": 3, "max_yield": 4, "max_yield_no_fertilizer": 3, "is_ongoing": False},
    "TOMATO": {"seed_cost": 50, "base_price": 60, "first_yield_day": 8, "max_yield_day": 8, "max_yield": 4, "max_yield_no_fertilizer": 4, "is_ongoing": True},
    "STRAWBERRY": {"seed_cost": 100, "base_price": 120, "first_yield_day": 10, "max_yield_day": 10, "max_yield": 4, "max_yield_no_fertilizer": 4, "is_ongoing": True},
    "MELON": {"seed_cost": 80, "base_price": 250, "first_yield_day": 10, "max_yield_day": 12, "max_yield": 6, "max_yield_no_fertilizer": 6, "is_ongoing": False},
}

# ============================================================
# Planner / strategy — day gates (were in src/strategy.py)
# ============================================================
# Day gates ported verbatim from main.py baseline
MELON_LAST_DAY = 13
STRAWBERRY_LAST_DAY = 22
LIQUIDATE_DAY = 27

PLANT_TARGET_FULL = 60
PLANT_TARGET_LATE = 30
LAST_PLAYABLE_DAY = 29
STRAW_LEAD_THRESHOLD = 190
ADVISOR_MIN_DAY = 12
WEED_PRIORITY_THRESHOLD = 15
WEED_PRIORITY_PRIO = 1

# CropAdvisor — was KAGG_CROP_ADVISOR=1 default ON
CROP_ADVISOR_ON = True

# ============================================================
# Planting windows / animal timing — single source of truth
# (moved here from main.py to avoid date conflicts)
# Latest day to plant each crop for reliable maturation (day + first_yield <= 29).
# ============================================================
CROP_MAX_PLANT_DAY = {
    "WHEAT": 27,       # first_yield=2, 27+2=29
    "CARROT": 27,      # first_yield=2
    "TOMATO": 21,      # first_yield=8
    "STRAWBERRY": 19,  # first_yield=10
    "MELON": 19,       # first_yield=10
}

# (Dead timing tables removed: per-animal buy days and product schedules
# from the deleted Solution C were never wired to any decision.)
# Linked crop order (ROI gate): ONE ranking drives both seed buying
# (economy) and planting (planner). CTE joins only by CLEARLY beating the
# staple (margin filters noise-level edges like d0 CARROT 27 vs WHEAT 26;
# real hinge explosions like drained CARROT 3629 pass easily).
# CTE joins only on true hinge explosions (e.g. drained CARROT 3629);
# noise-level edges stay out.
# Linked ROI gate v2: admit CTE only on CLEAR wins (1.5x wheat) with TWO
# shop waves of evidence (day>=6). v1 (2.0/day>=3) proved dormant; noise
# needs info, real hinge explosions (100s-1000s ROI) clear 1.5x easily.
CROP_LINK_ON = True
CROP_LINK_MARGIN = 1.5
CTE_START_DAY = 6
# CTE trial caps (used only when the linked order admits them).
CARROT_OPP_TARGET = 6
CARROT_OPP_LAST_DAY = 24
CARROT_OPP_CAP = 3
TOMATO_OPP_TARGET = 4
TOMATO_OPP_LAST_DAY = 21
TOMATO_OPP_CAP = 2


