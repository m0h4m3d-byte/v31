"""main.py - Clean-rebuild agent v2: proven engine, winner strategy.

Tactics (HOW): legacy field/market machinery (src/economy, src/planner,
src/decision_engine) - audited at 122k solo. It compounds because it spends
aggressively on day 0, buys land the moment affordable, and runs 10+ hands.

Strategy (WHAT): the reverse-engineered winner recipe (src/config.py PLAN =
8 cows / 4 sheep / 30 strawberry / 8 melon / 12 wheat, hire target 10).
NO per-shop adaptation: v6's adaptive herd won mirror (+16.8%) but lost
ladder (610.9 -> 565.7). Fixed winner plan only.
"""

from src.economy import MarketEngine
from src.planner import FarmPlanner
from src.decision_engine import SellAdvisor
from src.constants import CROP_CONFIG
from src.config import LAST_PLAYABLE_DAY, CROP_MAX_PLANT_DAY


class Agent:
    # Sell threshold: min_hold_edge multiplier for SellAdvisor (legacy 5%).
    SELL_THRESHOLD = 1.05

    def __init__(self):
        self.reset()

    def reset(self):
        self.day = 0
        self.hour = 0
        self.market = MarketEngine()
        self.planner = FarmPlanner()

    @property
    def ordered_today(self):
        return self.market.ordered_today

    @property
    def sold_today(self):
        return self.market.sold_today

    @property
    def animals_ordered(self):
        return self.market.animals_ordered

    @property
    def unit_task(self):
        return self.planner.unit_task

    def __call__(self, obs):
        if obs.get("step", 0) == 0:
            self.reset()

        day = obs.get("day", 0)
        self.day = day
        self.hour = obs.get("hour", 0)
        player = obs["player"]
        me = obs["farms"][player]
        private = obs["private"]
        market = obs["market"]
        money = me["money"]
        prices = market.get("prices", {})
        shed = private["shed"]
        seeds = private["seeds"]
        tiles = me["tiles"]
        units = [list(me["farmer"])] + [list(h) for h in me["hands"]]
        invs = private["inventories"]

        incoming = 0
        for _row in tiles:
            for _t in _row:
                if isinstance(_t, dict):
                    incoming += _t.get("yield_units", 0) or 0
        for _inv in invs:
            for _v in _inv.values():
                incoming += _v or 0

        # Step 1: market orders (fixed winner plan inside MarketEngine).
        orders = self.market.build_orders(
            day, self.hour, me, shed, seeds, prices, money, invs,
            unlocked_shops=list((obs.get("town") or {}).get("unlocked_shops") or []),
            market_inventory=market.get("inventory", {}),
            incoming=incoming,
        )

        # Step 1.5: price-projective sell filter (legacy Solution A).
        if shed:
            advisory_obs = {
                "day": day,
                "hour": self.hour,
                "town": {"unlocked_shops": list((obs.get("town") or {}).get("unlocked_shops") or [])},
                "market": {"prices": prices, "inventory": market.get("inventory", {})},
                "private": {"shed": shed},
            }
            sa = SellAdvisor(min_hold_edge=self.SELL_THRESHOLD)
            sell_plan = sa.advise(advisory_obs)
            filtered_orders = []
            for o in orders:
                if o and o[0] == "SELL" and len(o) >= 2:
                    item = o[1]
                    available = shed.get(item, 0)
                    if item in sell_plan:
                        verdict, n = sell_plan[item]
                        if verdict == "SELL":
                            sell_n = min(n, available)
                            if sell_n > 0:
                                filtered_orders.append(["SELL", item, sell_n])
                        elif verdict == "HOLD":
                            filtered_orders.append(o)
                        else:
                            filtered_orders.append(o)
                    else:
                        filtered_orders.append(o)
                else:
                    filtered_orders.append(o)
            orders = filtered_orders

        # Step 2: farm job queue.
        market_ctx = {
            "day": day,
            "hour": self.hour,
            "prices": prices,
            "inventory": market.get("inventory", {}),
            "shops": list((obs.get("town") or {}).get("unlocked_shops") or []),
            "milk_crash": getattr(self.market, "milk_crash_active", False),
        }
        self.planner.on_day(day)
        jobs = self.planner.collect_jobs(
            day, tiles, shed, seeds, invs,
            self.market.animals_ordered,
            market_ctx=market_ctx
        )

        # Step 3: crop-specific planting windows (legacy Solution B).
        filtered_jobs = self._filter_late_planting_jobs(jobs, day, seeds)

        actions = []
        used_jobs = set()
        for u_idx, pos in enumerate(units):
            inv = invs[u_idx] if u_idx < len(invs) else {}
            actions.append(self.planner.unit_action(
                pos, u_idx, filtered_jobs, used_jobs, inv, shed
            ))
        return {"farmer": actions[0], "hands": actions[1:], "market": orders}

    def _filter_late_planting_jobs(self, jobs, day, seeds):
        plantable_crops = set()
        for crop in CROP_CONFIG:
            if seeds.get(crop, 0) <= 0:
                continue
            max_plant = CROP_MAX_PLANT_DAY.get(crop, 29)
            if day > max_plant:
                continue
            first_yield = CROP_CONFIG[crop]["first_yield_day"]
            if max_plant + first_yield <= LAST_PLAYABLE_DAY:
                plantable_crops.add(crop)

        filtered = []
        for job in jobs:
            if job[1] == "PLANT" and len(job) >= 4:
                crop = job[3]
                if crop not in plantable_crops:
                    job_pos = job[0]
                    new_job = (job_pos, "PASS", 0)
                    filtered.append(new_job)
                else:
                    filtered.append(job)
            else:
                filtered.append(job)
        return filtered


agent = Agent()


def agent_function(obs):
    return agent(obs)
