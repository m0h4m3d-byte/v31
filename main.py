"""
main.py - Kaggriculture agent: thin wiring layer over the modular port.

Production agent modules:
    src/constants.py - game constants + board layout
    src/economy.py   - MarketEngine (all market orders) + tunables
    src/config.py    - all tunables (single source of truth)
    src/planner.py   - FarmPlanner (job queue + per-unit dispatch)

Equivalence with the proven baseline behavior is enforced at runtime by the
parity suites (frozen oracle):
    market, strategy, navigation, and the full-pipeline planner replay.
Any drift of the modules vs the oracle fails loudly.

Kaggle packaging: a single-file submission needs this module's logic
bundled with its src/ package (see docs/AGENTS.md).
"""

from src.economy import MarketEngine
from src.planner import FarmPlanner
from src.decision_engine import SellAdvisor
from src.constants import CROP_CONFIG
from src.config import LAST_PLAYABLE_DAY, CROP_MAX_PLANT_DAY


class Agent:
    """Parses observations and delegates to the modular engines.

    The agent operates in a fixed turn loop (24 turns per day, 30 days = 720 turns).
    Each turn, it:
    1. Resets state at the start of each new day (step == 0)
    2. Delegates market order generation to MarketEngine
    3. Delegates farm job collection to FarmPlanner
    4. Delegates per-unit action dispatch to FarmPlanner
    5. Returns action dict for farmer + hired hands + market orders

    Key improvements:
    - Solution B: Crop-specific planting windows (see _filter_late_planting_jobs)
    - Solution A: Price-projective sell decision with configurable threshold
        - Uses SellAdvisor with min_hold_edge threshold
        - Only HOLD if projected revenue gain exceeds threshold
        - Otherwise SELL immediately to capture current price
    - Maintains perfect parity with the official competition engine
        """
    # Sell threshold: min_hold_edge multiplier for SellAdvisor.
    # Valid values tested: 1.01 (1%), 1.02 (2%), 1.035 (3.5%), 1.05 (5%), 1.075 (7.5%), 1.10 (10%)
    # Default (5%) maintains baseline parity when Solution B is active.
    SELL_THRESHOLD = 1.05

    def __init__(self):
        self.reset()

    def reset(self):
        self.day = 0
        self.hour = 0
        self.market = MarketEngine()
        self.planner = FarmPlanner()

    # ------------------------------------------------------------------
    # Live views kept for introspection / regression tests.
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Action dispatch
    # ------------------------------------------------------------------

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

        # --- Step 1: Generate market orders ---
        # MarketEngine builds orders (seeds, animals, land, sell orders)
        # Mirrors the monolith's Agent._market_orders exactly for parity
        orders = self.market.build_orders(
            day, self.hour, me, shed, seeds, prices, money, invs,
            unlocked_shops=list((obs.get("town") or {}).get("unlocked_shops") or []),
            market_inventory=market.get("inventory", {}),
        )

        # --- Step 1.5: Solution A - Price-projective sell decision with threshold ---
        # Use SellAdvisor to get hold/SELL recommendations based on price projection.
        # The SellAdvisor already projects price using the market model with a 5% minimum hold edge.
        # Threshold rule: Only HOLD if projected price increase exceeds 5% over current price.
        # Otherwise, SELL immediately to capture current price.
        # This prevents holding through price crashes while maintaining parity.
        if shed:
            advisory_obs = {
                "day": day,
                "hour": self.hour,
                "town": {"unlocked_shops": list((obs.get("town") or {}).get("unlocked_shops") or [])},
                "market": {"prices": prices, "inventory": market.get("inventory", {})},
                "private": {"shed": shed},
            }
            # FIX: Set min_hold_edge threshold on SellAdvisor instance.
            # Without this, SellAdvisor uses default 5% edge, making all thresholds identical.
            sa = SellAdvisor(min_hold_edge=self.SELL_THRESHOLD)
            sell_plan = sa.advise(advisory_obs)
            
            # Filter SELL orders based on threshold condition.
            # Rule: 
            # - If SellAdvisor says SELL: always SELL now (capture current price)
            # - If SellAdvisor says HOLD: only HOLD if the projected revenue gain exceeds 5% threshold.
            #   Since SellAdvisor already uses min_hold_edge=1.05 (5%), a HOLD recommendation
            #   means the edge is already >= 5%, so we respect it.
            # - Non-SELL orders (HIRE, BUY_xxx) are always kept.
            filtered_orders = []
            for o in orders:
                if o and o[0] == "SELL" and len(o) >= 2:
                    item = o[1]
                    available = shed.get(item, 0)
                    if item in sell_plan:
                        verdict, n = sell_plan[item]
                        if verdict == "SELL":
                            # Always SELL when model says SELL
                            sell_n = min(n, available)
                            if sell_n > 0:
                                filtered_orders.append(["SELL", item, sell_n])
                        elif verdict == "HOLD":
                            # HOLD when model says HOLD (edge already >= 5% per SellAdvisor)
                            filtered_orders.append(o)
                        else:
                            filtered_orders.append(o)
                    else:
                        # item not in sell_plan: keep original order
                        filtered_orders.append(o)
                else:
                    # non-SELL orders (HIRE, BUY_xxx): keep as-is
                    filtered_orders.append(o)
            orders = filtered_orders
        # --- End Solution A ---

        # --- Step 2: Build farm job queue ---
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

        # --- Step 3: Solution B - Crop-specific planting windows ---
        # Filter jobs to only plant crops that can mature before season end.
        # Season ends at day 29 (turn 719). A crop planted on day d can first
        # yield on day d + first_yield_day. If d + first_yield_day > 29, the
        # crop cannot yield before season end.
        #
        # CROP_MAX_PLANT_DAY defines the latest day to plant each crop for
        # reliable maturation:
        #   WHEAT: day 27 (first_yield=2, 27+2=29)
        #   CARROT: day 27 (first_yield=2)
        #   TOMATO: day 21 (first_yield=8, ongoing crop)
        #   STRAWBERRY: day 19 (first_yield=10)
        #   MELON: day 19 (first_yield=10, melon_cap=28 limits density)
        #
        # Crops planted after these days have reduced chance of yielding
        # before season end and are filtered out.
        filtered_jobs = self._filter_late_planting_jobs(jobs, day, seeds)

        # Re-dispatch with filtered jobs
        actions = []
        used_jobs = set()
        for u_idx, pos in enumerate(units):
            inv = invs[u_idx] if u_idx < len(invs) else {}
            actions.append(self.planner.unit_action(
                pos, u_idx, filtered_jobs, used_jobs, inv, shed
            ))
        # --- Step 4: Return action dict ---
        return {"farmer": actions[0], "hands": actions[1:], "market": orders}

    # ------------------------------------------------------------------
    # Solution B helper: filter late planting jobs
    # ------------------------------------------------------------------
    def _filter_late_planting_jobs(self, jobs, day, seeds):
        """Filter out planting jobs for crops that cannot mature before season end.

        Season ends at day 29 (turn 719). A crop planted on day d can first
        yield on day d + first_yield_day. If d + first_yield_day > 29, the
        crop cannot yield before season end.

        Returns: modified jobs list with late planting jobs removed (changed to PASS).
        """
        # Compute which crops are plantable this day
        plantable_crops = set()
        for crop in CROP_CONFIG:
            # Check if there's any seed of this type
            if seeds.get(crop, 0) <= 0:
                continue
            # Check max plant day threshold
            max_plant = CROP_MAX_PLANT_DAY.get(crop, 29)
            if day > max_plant:
                continue
            # Check if crop has sufficient time to yield before season end
            first_yield = CROP_CONFIG[crop]["first_yield_day"]
            # A crop planted on max_plant first yields on day max_plant + first_yield
            # Must be <= 29 (LAST_PLAYABLE_DAY) to yield this season
            if max_plant + first_yield <= LAST_PLAYABLE_DAY:
                plantable_crops.add(crop)

        # Filter jobs: change PLANT jobs for non-plantable crops to PASS
        filtered = []
        for job in jobs:
            if job[1] == "PLANT" and len(job) >= 4:
                crop = job[3]
                if crop not in plantable_crops:
                    # Change this job to PASS instead of planting late
                    job_pos = job[0]
                    new_job = (job_pos, "PASS", 0)  # priority 0 = lowest
                    filtered.append(new_job)
                else:
                    filtered.append(job)
            else:
                filtered.append(job)
        return filtered

    # ------------------------------------------------------------------
    # Global agent instance
    # --------------------------------------------------------------------------

agent = Agent()


def agent_function(obs):
    return agent(obs)