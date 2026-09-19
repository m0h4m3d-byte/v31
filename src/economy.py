"""
economy.py - Economic engine for the Kaggriculture agent.
Contains the market order logic V15_FIXED production agent.

Parity guarantee: tests/test_market_parity.py replays the monolith agent and
asserts this engine produces IDENTICAL market orders at every step. Any
change to the numbers below must be reflected there or the test fails.
"""

from typing import Dict, List

# All tunables imported from single source of truth — src/config.py is the ONLY
# place that holds numbers. No os.environ / KAGG_* reads exist anywhere.
from src.config import (
    PLAN, FEED_RESERVE,
    ANIMAL_ADVISOR_ON, MILK_CRASH_PRICE, ANIMAL_ADVISOR_MIN_DAY, MILK_TREND_DROP,
    WOOL_CRASH_PRICE, WOOL_CRASH_MIN_DAY, WOOL_CRASH_DROP, WOOL_NO_YARN_CAP,
    PASTURE_BUFFER, HIRE_TARGET, HIRE_POOR_MONEY, HIRE_POOR_HANDS,
    RESERVE,
)

from src.config import (
    SHED_CAPACITY, SHED_DUMP_AT, SELL_HOLD_DAY, SELL_FLOOR_MIN, LIQUIDATE_DAY,
    FORCE_SLIDE_DROP, FORCE_PEAK_FLOOR,
    MELON_FLOOR_MIN,
    MILK_BULL_D12, MILK_BULL_HOLD_DAY, MILK_BAIL_FROM_DAY, MILK_BAIL_FACTOR,
    MELON_PANIC_DROP,
    STRAW_BULL_DAY, STRAW_BULL_PRICE, STRAW_BULL_HOLD_DAY,
    STRAW_BAIL_FROM_DAY, STRAW_BAIL_FACTOR,
    ANIMALS, SEED_COST,
    MARKET_AWARE_ON, MARKET_AWARE_CAPS,
)

from src.config import (
    LAND_COSTS, LAND_DAYS, LAND_BUY_BUFFER,
    CARROT_OPP_TARGET, CARROT_OPP_LAST_DAY, CARROT_OPP_CAP,
    TOMATO_OPP_TARGET, TOMATO_OPP_LAST_DAY, TOMATO_OPP_CAP,
    CROP_LINK_ON,
)


def _fib(n: int) -> int:
    """Fibonacci with _fib(0)=1, _fib(1)=1, _fib(2)=2..."""
    a, b = 1, 1
    for _ in range(n):
        a, b = b, a + b
    return a


class MarketEngine:
    """
    Builds the market orders (sell / hire / land / feed / seeds / animals).

    Ported verbatim from Agent._market_orders + Agent._sell in src/main.py (baseline).
    Accepts the same raw observation slices the monolith passes around,
    so the port is a line-for-line move with no number changes.

    State kept here mirrors the monolith's Agent attributes:
        ordered_today: per-day BUY dedupe (reset on day change / new game)
        sold_today:    per-day SELL dedupe (reset on day change / new game)
        animals_ordered: cumulative animal purchases (reset only per game)
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.day = -1
        self.ordered_today = {}
        self.sold_today = {}
        self.animals_ordered = {"COW": 0, "SHEEP": 0, "GOOSE": 0}
        self.milk_bull = None
        self.milk_d12_price = None
        self.bail_fires = 0
        self.melon_peak = 0.0
        self.force_peak = {}
        self.straw_bull = None
        self.straw_d12_price = None
        self.wool_season_max = None
        self.milk_peak = 0.0
        self.milk_crash_active = False
        self.milk_history: list[float] = []

    def _on_day(self, day: int):
        """Roll over day-trackers; a fresh game looks like a day reset."""
        if day == self.day:
            return
        if day == 0 or day < self.day:
            self.reset()
            self.day = 0
        else:
            self.day = day
            self.ordered_today = {}
            self.sold_today = {}

    @staticmethod
    def _animal_counts(me):
        animal_tiles = []
        for row in me["tiles"]:
            for t in row:
                if isinstance(t, dict) and "animal" in t:
                    animal_tiles.append(t)
        cows = sum(1 for t in animal_tiles if t["animal"] == "COW")
        sheep = sum(1 for t in animal_tiles if t["animal"] == "SHEEP")
        geese = sum(1 for t in animal_tiles if t["animal"] == "GOOSE")
        return len(animal_tiles), cows, sheep, geese

    @staticmethod
    def _unplaced_animal(invs, shed, animal):
        total = shed.get(animal, 0)
        for inv in invs:
            total += inv.get(animal, 0)
        return total

    def build_orders(self, day: int, hour: int, me, shed, seeds, prices, money, invs,
                     unlocked_shops=None, market_inventory=None, incoming=0) -> List[list]:
        """Return the market orders list. Mirrors Agent._market_orders exactly.

        unlocked_shops: obs.town.unlocked_shops (P5 signal); None/absent on
        the OFF path so behaviour stays bit-identical to GOLDEN_BASELINE.
        market_inventory: shared market supply; enables the linked ROI crop
        order (None => legacy behavior, no CTE seeds).
        incoming: unharvested field yield + carried inventories (units about
        to enter the shed); gates the overflow force-dump with free room.
        """
        self._on_day(day)
        orders = []
        pending = 0
        animals_now, cows, sheep, geese = self._animal_counts(me)

        def can(cost):
            return money - pending - cost >= RESERVE

        def buy(key, cap, cost, order, floor=RESERVE, units=1):
            nonlocal pending
            if self.ordered_today.get(key, 0) + units > cap:
                return False
            if money - pending - cost < floor:
                return False
            if len(orders) >= 10:
                return False
            self.ordered_today[key] = self.ordered_today.get(key, 0) + units
            orders.append(order)
            pending += cost
            return True

        self._sell(orders, shed, prices, day, animals_now,
                   unlocked_shops=unlocked_shops, incoming=incoming)

        if day < 30:
            hired = me.get("hires_today", 0)
            unlocked = len(me.get("unlocked_quadrants", []))
            # Requested: 5 day0, +5 at NE, +5+1 at SW (extra worker)
            geo_target = unlocked * 5 + (1 if unlocked == 3 else 0)
            target = min(HIRE_TARGET + 2, geo_target)  # allow 16 total (farmer+15) if needed
            target_hands = max(0, target - 1)
            if money < HIRE_POOR_MONEY:
                target_hands = min(target_hands, HIRE_POOR_HANDS)
            if hired < target_hands:
                need = target_hands - hired
                if day == 0 and hour == 0:
                    step = min(4, 10 - len(orders), 24 - hour)
                elif need >= 4:
                    step = min(5, 10 - len(orders), 24 - hour)
                else:
                    step = min(2, 10 - len(orders), 24 - hour)
                planned = 0
                while hired + planned < target_hands and planned < step:
                    cost = _fib(hired + planned)
                    if money - pending - cost < 5:
                        break
                    orders.append(["HIRE"])
                    pending += cost
                    planned += 1

        # no-4th-land experiment: stop at 3 quarters (75 tiles) like leaders — 4th land $4k is fixed rule with ~75% usage, ROI negative late
        unlocked = len(me.get("unlocked_quadrants", []))
        # was: 0 < unlocked < len(LAND_COSTS)+1 (allows 4th at day12); now cap at 3 quadrants
        if 0 < unlocked < len(LAND_COSTS) and day >= LAND_DAYS[unlocked - 1]:
            # Liquidity gate: keep operating buffer after paying (blocks
            # NE-with-$115 / SW-with-$25 buys; neutral once rich).
            buy("land", 1, LAND_COSTS[unlocked - 1], ["BUY_LAND"],
                floor=LAND_BUY_BUFFER)

        wheat_price = prices.get("WHEAT", 25)
        need_reserve = 4 if wheat_price <= 35 else 0
        feed_need = animals_now + need_reserve
        if shed.get("WHEAT", 0) < feed_need and wheat_price <= 70:
            q = min(feed_need - shed.get("WHEAT", 0), 6)
            if q > 0 and q * wheat_price <= money - pending:
                feed_cap = 4 if animals_now <= 2 else 2 if animals_now < 8 else 3
                buy("feed", feed_cap, q * wheat_price, ["BUY_PRODUCT", "WHEAT", q], floor=0)

        # User plan: WHEAT 15 MELON 5 (2825$) — cap melon 5 day0
        seed_plan = {"WHEAT": (15, 24, 8, 0), "MELON": (5, 10, 5 if day == 0 else 6, 0),
                     "STRAWBERRY": (PLAN["STRAWBERRY"], 14, 10, 3)}
        # Linked ROI gate (single source with planner): CTE seeds join ONLY
        # when the shared ranking admits them (beating wheat x margin).
        if CROP_LINK_ON and market_inventory is not None and day >= 3:
            try:
                from src.decision_engine import linked_crop_order
                _linked = linked_crop_order(day, {
                    "day": day,
                    "inventory": dict(market_inventory),
                    "shops": list(unlocked_shops or []),
                })
            except Exception:
                _linked = None
            if _linked:
                if "CARROT" in _linked:
                    seed_plan["CARROT"] = (CARROT_OPP_TARGET, CARROT_OPP_LAST_DAY,
                                           CARROT_OPP_CAP, 3)
                if "TOMATO" in _linked:
                    seed_plan["TOMATO"] = (TOMATO_OPP_TARGET, TOMATO_OPP_LAST_DAY,
                                           TOMATO_OPP_CAP, 3)
        for crop, (target, last_day, cap, start_day) in seed_plan.items():
            if day > last_day or day < start_day:
                continue
            have = seeds.get(crop, 0)
            if have < target:
                q = min(target - have, cap)
                if q > 0:
                    buy("seed_" + crop, cap, q * SEED_COST[crop], ["BUY_SEED", crop, q], units=q, floor=0)

        # no-waste-buying: per-animal last day to guarantee at least one yield before day29
        # GOOSE 4d -> 25 (25+4=29), SHEEP 6d -> 23 (23+6=29), COW 8d -> 21 (21+8=29); GOOSE not bought (PLAN 0) but keep for completeness
        _ANIMAL_LAST_DAY = {"GOOSE": 25, "SHEEP": 23, "COW": 21}
        if day <= 25:  # max cutoff
            day0_n = {"SHEEP": 2, "COW": 3}
            # Sheep target is the plan, full stop. (The retired P4 family of
            # YARN-gated cap arms evaluated to a no-op here: min(PLAN 5,
            # floor 8) == PLAN, all other arms OFF. Removed, not disabled.)
            sheep_target = PLAN["SHEEP"]
            # Phase 15 (v17 ladder autopsies): milk-crash worlds killed the
            # cow-heavy build. ep 99812812: P(MILK) $185 -> $1 while wool held
            # $240; we kept pouring $400/cow into a dead market. When the
            # realized milk price collapses, freeze the cow herd and point
            # the remaining pen budget at sheep (wool was $200+ throughout).
            # Phase 16: trend detection — a >25% slide off the running peak
            # fires BEFORE the absolute floor does (ep 99840272 bought cows
            # at $185 that were worth $1 a week later). Peak is tracked
            # per-game from day 3 on; reset() clears it.
            milk_now = prices.get("MILK", 160)
            if day >= 3:
                if milk_now > self.milk_peak:
                    self.milk_peak = milk_now
            # Early indicator: rate of change over last 3-4 days (not absolute value)
            self.milk_history.append(float(milk_now))
            if len(self.milk_history) > 4:
                self.milk_history.pop(0)
            early_slowdown = False
            if len(self.milk_history) >= 3 and day >= ANIMAL_ADVISOR_MIN_DAY:
                d1 = self.milk_history[-1] - self.milk_history[-2]
                d2 = self.milk_history[-2] - self.milk_history[-3]
                # Only fire early if price is already softening below $150 —
                # avoids false positives when price is $180+ and dips slightly
                # but will recover (healthy worlds).
                if milk_now < 150:
                    if d2 > 5 and d1 < d2 * 0.5:
                        early_slowdown = True
                    if d1 < 0 and d1 < d2:
                        early_slowdown = True
            cow_target = PLAN["COW"]
            crash_fired = False
            if ANIMAL_ADVISOR_ON and day >= ANIMAL_ADVISOR_MIN_DAY:
                trend_broken = (self.milk_peak >= 100
                                and milk_now < MILK_TREND_DROP * self.milk_peak)
                if milk_now < MILK_CRASH_PRICE or trend_broken or early_slowdown:
                    crash_fired = True
                    cow_frozen = cows + self._unplaced_animal(invs, shed, "COW")
                    cow_target = cow_frozen
                    # Wool guard: never redirect the pen budget into sheep
                    # when wool itself is crashing in a no-YARN world.
                    wool_now_g = prices.get("WOOL", 200)
                    wool_crash_g = (
                        unlocked_shops is not None
                        and "YARN_STORE" not in unlocked_shops
                        and day >= WOOL_CRASH_MIN_DAY
                        and (wool_now_g < WOOL_CRASH_PRICE
                             or (self.wool_season_max is not None
                                 and self.wool_season_max >= 100
                                 and wool_now_g < WOOL_CRASH_DROP * self.wool_season_max)))
                    if not wool_crash_g:
                        sheep_target = max(sheep_target,
                                           PLAN["COW"] + PLAN["SHEEP"] - cow_frozen)
            self.milk_crash_active = crash_fired
            # Wool crash breaker: no-YARN + collapsed wool => hard sheep
            # cap. Tightens the V2A floor (8, ineffective vs PLAN 5) down
            # to WOOL_NO_YARN_CAP only when wool is actually weak, so
            # healthy no-YARN worlds keep PLAN behavior (neutral).
            if (ANIMAL_ADVISOR_ON and unlocked_shops is not None
                    and day >= WOOL_CRASH_MIN_DAY
                    and "YARN_STORE" not in unlocked_shops):
                wool_now = prices.get("WOOL", 200)
                wool_peak = self.wool_season_max if self.wool_season_max else wool_now
                if (wool_now < WOOL_CRASH_PRICE
                        or (wool_peak >= 100 and wool_now < WOOL_CRASH_DROP * wool_peak)):
                    sheep_target = min(sheep_target, WOOL_NO_YARN_CAP)
            for animal, target in (("SHEEP", sheep_target), ("COW", cow_target)):
                # no-waste-buying: skip if beyond last viable day for this animal
                if day > _ANIMAL_LAST_DAY.get(animal, 24):
                    continue
                have = (cows if animal == "COW" else sheep if animal == "SHEEP" else geese) \
                    + self._unplaced_animal(invs, shed, animal)
                missing = target - have
                if missing <= 0:
                    continue
                n = min(missing, day0_n.get(animal, 1) if day == 0 else 1)
                if self._unplaced_animal(invs, shed, animal) >= 10:
                    n = 0
                cost = ANIMALS[animal]["cost"]
                if n > 0 and buy("animal_" + animal, n, n * cost, ["BUY_ANIMAL", animal, n], units=n, floor=0):
                    self.animals_ordered[animal] = self.animals_ordered.get(animal, 0) + n

        # (Retired fertilizer working-stock buyer removed: OFF since
        # inception; expansion capital keeps first claim unconditionally.)

        return orders

    def _sell(self, orders, shed, prices, day, animals_now, unlocked_shops=None,
              incoming=0):
        sold = self.sold_today

        def sell_capped(item, amount, cap):
            # Overflow drain is samples, not floods: 5 units per product per
            # day (day-27 liquidation keeps full caps to empty everything).
            if force_dump and day < LIQUIDATE_DAY:
                cap = min(cap, 5)
            amount = min(amount, cap - sold.get(item, 0))
            if amount > 0 and len(orders) < 10:
                sold[item] = sold.get(item, 0) + amount
                orders.append(["SELL", item, amount])

        # Phase 3: overflow guard with TWO joint conditions (both must hold):
        # (1) shed near-full AND some premium sliding 25%+ off its peak,
        # (2) incoming harvest exceeds free room. Healthy-full sheds drain at
        # normal caps; crashed-full sheds with nothing incoming wait instead
        # of dumping into the crash (discards risk accepted over fire-sale).
        sellable = ("MILK", "WOOL", "EGG", "FERTILIZER", "MELON",
                    "STRAWBERRY", "WHEAT", "CARROT", "TOMATO")
        shed_load = sum(shed.get(p, 0) for p in sellable)
        for _fp in ("MILK", "WOOL", "MELON", "STRAWBERRY"):
            _fv = prices.get(_fp)
            if _fv is not None and _fv > self.force_peak.get(_fp, 0):
                self.force_peak[_fp] = float(_fv)
        prices_low = any(
            self.force_peak.get(_fp, 0) >= FORCE_PEAK_FLOOR
            and prices.get(_fp, 0) < (1.0 - FORCE_SLIDE_DROP) * self.force_peak[_fp]
            for _fp in ("MILK", "WOOL", "MELON", "STRAWBERRY")
        )
        force_dump = (shed_load >= SHED_DUMP_AT and prices_low
                      and incoming > SHED_CAPACITY - shed_load)

        # Phase 10: adaptive milk hold - classify the market once on d12
        # (prices are constant per day, so the hour-0 snapshot is exact).
        if day == 12 and self.milk_bull is None:
            self.milk_bull = prices.get("MILK", 160) >= MILK_BULL_D12
            self.milk_d12_price = prices.get("MILK", 160)
        milk_gate = MILK_BULL_HOLD_DAY if self.milk_bull else SELL_HOLD_DAY["MILK"]
        # Phase 11: late-game bail - bulls that start sliding at d16+ (the
        # d12 check cannot see a d21-29 collapse) dump at the visible
        # -15% level instead of riding the hold to crash prices.
        if (self.milk_bull and self.milk_d12_price
                and MILK_BAIL_FROM_DAY <= day < MILK_BULL_HOLD_DAY
                and prices.get("MILK", 160) < MILK_BAIL_FACTOR * self.milk_d12_price):
            milk_gate = day
            self.bail_fires += 1
        # BATCH-3 (P5): regime-adaptive wool tranche. Track season max
        # price every day (harmless state when OFF).
        # FIX: initialize wool_gate BEFORE conditional to prevent
        # UnboundLocalError on subsequent calls when price <= season max.
        wool_gate = SELL_HOLD_DAY["WOOL"]
        if prices.get("WOOL") is not None:
            w = prices["WOOL"]
            if self.wool_season_max is None or w > self.wool_season_max:
                self.wool_season_max = w
        # (Retired P5/P7 wool-timing arms removed: both OFF since inception,
        # default path kept verbatim.)
        for p, gate in (("MILK", milk_gate), ("WOOL", wool_gate),
                        ("EGG", SELL_HOLD_DAY["EGG"])):
            amt = shed.get(p, 0)
            # Floor guard: below SELL_FLOOR_MIN, hold for recovery unless
            # overflow forces it out. (Day>=27 liquidation below sells
            # everything separately, so no liquidation clause here.)
            if amt > 0 and (force_dump
                            or (day >= gate and prices.get(p, 0) >= SELL_FLOOR_MIN)):
                cap = MARKET_AWARE_CAPS.get(p, 80) if MARKET_AWARE_ON else 80
                sell_capped(p, amt, cap)

        fert = shed.get("FERTILIZER", 0)
        # Phase 12: no fertilizer price floor - sell everything above the
        # reserve every day. The >=40 floor was a real-ladder bug: in
        # crash games fert falls to 4-27, the stock never sells, the shed
        # clogs and the cascade force-dumps milk/strawberry/wheat at
        # cratered prices (leader-1 of the real ladder sells ~1970 fert
        # at ~$50 avg = their single biggest revenue line). Locally the
        # price rarely drops below 40, so this is behavior-neutral in the
        # starter benchmark (shed stays ~2 units either way).
        # Fertilizer reserve is a plain 2 (the retired stock-buyer path that
        # raised it is gone).
        fert_reserve = 2
        if fert > fert_reserve:
            cap = MARKET_AWARE_CAPS["FERTILIZER"] if MARKET_AWARE_ON else 80
            sell_capped("FERTILIZER", fert - fert_reserve, cap)

        melon = shed.get("MELON", 0)
        # Melon: sell first flushes IMMEDIATELY at healthy prices (legacy
        # tranches, no waiting for peaks). PANIC permission covers the gaps
        # legacy misses: days 10-11 and sub-30 slides, always at tranche pace
        # (never floods) and never below the 30 floor (never at a loss).
        _mp = prices.get("MELON", 250)
        if _mp > self.melon_peak:
            self.melon_peak = float(_mp)
        melon_panic = (day >= 10 and self.melon_peak >= 100
                       and _mp < (1.0 - MELON_PANIC_DROP) * self.melon_peak)
        if melon_panic:
            self.bail_fires += 1
        if melon > 0 and (force_dump
                          or (melon_panic and _mp >= MELON_FLOOR_MIN)
                          or ((prices.get("MELON", 250) >= 30 or day >= 12)
                              and prices.get("MELON", 250) >= MELON_FLOOR_MIN)):
            cap = MARKET_AWARE_CAPS["MELON"] if MARKET_AWARE_ON else 80
            sell_capped("MELON", melon, cap)

        strawberry = shed.get("STRAWBERRY", 0)
        # Strawberry early exit (BULL/BAIL template): classify at first-flush
        # age on the advisor-trusted 190; bulls hold through the last flush
        # (16), bailouts release at the first -20% slide inside 13-15.
        # NOTE: the legacy day>=0 clause always passed, so the bull hold
        # only binds by suspending it (same fix as melon price>=30).
        if day == STRAW_BULL_DAY and self.straw_bull is None:
            self.straw_bull = prices.get("STRAWBERRY", 120) >= STRAW_BULL_PRICE
            self.straw_d12_price = prices.get("STRAWBERRY", 120)
        straw_gate = STRAW_BULL_HOLD_DAY if self.straw_bull else SELL_HOLD_DAY["STRAWBERRY"]
        if (self.straw_bull and self.straw_d12_price
                and STRAW_BAIL_FROM_DAY <= day < STRAW_BULL_HOLD_DAY
                and prices.get("STRAWBERRY", 120) < STRAW_BAIL_FACTOR * self.straw_d12_price):
            straw_gate = day
            self.bail_fires += 1
        straw_hold = bool(self.straw_bull) and day < straw_gate
        if strawberry > 0 and (force_dump
                               or (not straw_hold
                                   and (prices.get("STRAWBERRY", 120) >= 30
                                        or day >= max(straw_gate, SELL_HOLD_DAY["STRAWBERRY"]))
                                   and prices.get("STRAWBERRY", 120) >= SELL_FLOOR_MIN)):
            cap = MARKET_AWARE_CAPS["STRAWBERRY"] if MARKET_AWARE_ON else 80
            sell_capped("STRAWBERRY", strawberry, cap)

        wheat = shed.get("WHEAT", 0)
        sell_wheat_min = 0 if force_dump else animals_now + FEED_RESERVE
        if wheat > sell_wheat_min and (force_dump
                                       or (prices.get("WHEAT", 25) >= 25
                                           and prices.get("WHEAT", 25) >= SELL_FLOOR_MIN)):
            cap = MARKET_AWARE_CAPS["WHEAT"] if MARKET_AWARE_ON else 150
            sell_capped("WHEAT", wheat - sell_wheat_min, cap)

        for p in ("CARROT", "TOMATO"):
            if shed.get(p, 0) > 0 and (force_dump
                                       or prices.get(p, 0) >= SELL_FLOOR_MIN):
                cap = MARKET_AWARE_CAPS.get(p, 40) if MARKET_AWARE_ON else 40
                sell_capped(p, shed[p], cap)

        if day >= 27:
            for p, q in list(shed.items()):
                if p not in ("COW", "SHEEP", "GOOSE") and q > 0:
                    sell_capped(p, q, 999)


# Global instance
market = MarketEngine()