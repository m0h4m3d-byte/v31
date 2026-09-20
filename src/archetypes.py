"""
archetypes.py - Two HONEST sparring opponents (decision metric, not lab toys).

Unlike mirror clones (synchronized self-floods) or replay ghosts (crippled
bodies), these bots run INDEPENDENT, simple, fully functional policies with
their own production mix:

    WheatBot: wheat monoculture (the volume game ladder leaders play).
    DairyBot: 5-cow pasture dairy (milk + fertilizer economy).

Honesty contract: each bot actually farms its mix end-to-end every turn
(buy -> plant/build -> water/feed -> harvest -> sell). If a bot scores ~0
or errors, the DEVICE is broken, not the opponent (see quality proof in
run_arch() output). Movement/layout constants are shared board facts,
strategy is fully independent from src/planner.py and src/economy.py.

Usage:
    python -m src.archetypes            # quality proof + our margins
"""

import argparse

SHED_TILES = [(4, 4), (5, 4), (4, 5), (5, 5)]
PASTURES = [(4, 3), (3, 4), (4, 4), (3, 3), (4, 2)]
LAND_DAYS = [6, 9, 12]
LAND_COSTS = [1000, 2000, 4000]


def _step(pos, target):
    tx, ty = target
    fx, fy = pos
    if fx != tx:
        return ["EAST" if tx > fx else "WEST"]
    if fy != ty:
        return ["SOUTH" if ty > fy else "NORTH"]
    return ["PASS"]


def _nearest(pos, spots):
    return min(spots, key=lambda s: abs(s[0] - pos[0]) + abs(s[1] - pos[1]))


def _shed_near(pos):
    return _nearest(pos, SHED_TILES)


def _tiles_of(me):
    return me["tiles"]


def _each_unit(obs):
    me = obs["farms"][obs["player"]]
    yield 0, list(me["farmer"])
    for i, h in enumerate(me["hands"], start=1):
        yield i, list(h)


class WheatBot:
    """Wheat monoculture: buy seeds, plant everything, water, harvest, sell."""

    def __init__(self):
        self.day = -1

    def __call__(self, obs):
        day = obs["day"]
        me = obs["farms"][obs["player"]]
        private = obs["private"]
        money = me["money"]
        tiles = _tiles_of(me)
        shed = private["shed"]
        seeds = private["seeds"]
        invs = private["inventories"]
        market = []

        if seeds.get("WHEAT", 0) < 8 and money > 200:
            market.append(["BUY_SEED", "WHEAT", min(8, 8 - seeds.get("WHEAT", 0))])
        # Patient sales: ≤40/day protects our own marginal price (own floods
        # cratered it); frugality: NW tiles suffice, 2 hands max, no land.
        if shed.get("WHEAT", 0) > 0:
            market.append(["SELL", "WHEAT", min(40, shed["WHEAT"])])
        if len(me.get("hands", [])) < 2 and money > 500 and day >= 1:
            market.append(["HIRE"])

        field = []
        for u_idx, pos in _each_unit(obs):
            inv = invs[u_idx] if u_idx < len(invs) else {}
            t = tiles[pos[1]][pos[0]] if 0 <= pos[1] < 10 and 0 <= pos[0] < 10 else "LOCKED"
            if t == "LOCKED":
                field.append(_step(pos, [4, 4]))
                continue
            if isinstance(t, dict) and t.get("kind") == "WEED":
                field.append(["DIG"])
                continue
            acted = False
            if isinstance(t, dict) and t.get("kind") == "PLANT":
                # Wheat is one-time: harvest at max_yield_day (4), never early
                # (early harvest forfeits half the bonus-window yield).
                if t.get("yield_units", 0) > 0 and obs["day"] - t.get("planted_day", day) >= 4:
                    field.append(["HARVEST"])
                    acted = True
                elif not t.get("watered_today"):
                    field.append(["WATER"])
                    acted = True
                # else: growing crop needs nothing -> fall through to walk
            elif t is None and seeds.get("WHEAT", 0) > 0:
                field.append(["PLANT", "WHEAT"])
                seeds = dict(seeds)
                seeds["WHEAT"] -= 1
                acted = True
            if acted:
                continue
            # walk to nearest work anywhere (ready > thirsty > weeds > empty)
            ready, wet, weeds, empty = [], [], [], []
            for y in range(10):
                for x in range(10):
                    c = tiles[y][x]
                    if c == "LOCKED":
                        continue
                    if isinstance(c, dict) and c.get("kind") == "PLANT":
                        if c.get("yield_units", 0) > 0 and obs["day"] - c.get("planted_day", day) >= 4:
                            ready.append((x, y))
                        elif not c.get("watered_today"):
                            wet.append((x, y))
                    elif isinstance(c, dict) and c.get("kind") == "WEED":
                        weeds.append((x, y))
                    elif c is None and seeds.get("WHEAT", 0) > 0:
                        empty.append((x, y))
            target = None
            if ready:
                target = _nearest(pos, ready)
            elif wet:
                target = _nearest(pos, wet)
            elif weeds:
                target = _nearest(pos, weeds)
            elif empty:
                target = _nearest(pos, empty)
            field.append(_step(pos, list(target)) if target else ["PASS"])
        return {"farmer": field[0], "hands": field[1:], "market": market[:10]}


class DairyBot:
    """5-cow dairy: central pastures, daily feed/care/harvest, sell milk+fert."""

    NCOWS = 5

    def __call__(self, obs):
        day = obs["day"]
        me = obs["farms"][obs["player"]]
        private = obs["private"]
        money = me["money"]
        tiles = _tiles_of(me)
        shed = private["shed"]
        invs = private["inventories"]
        market = []

        cows = sum(1 for row in tiles for t in row
                   if isinstance(t, dict) and t.get("animal") == "COW")
        unplaced = shed.get("COW", 0) + sum(i.get("COW", 0) for i in invs)
        if cows + unplaced < self.NCOWS and money > 600 and day <= 21:
            market.append(["BUY_ANIMAL", "COW", 1])
        wheat_stock = shed.get("WHEAT", 0)
        if wheat_stock < 8:
            market.append(["BUY_PRODUCT", "WHEAT", min(8 - wheat_stock, 8)])
        if shed.get("MILK", 0) > 0:
            market.append(["SELL", "MILK", shed["MILK"]])
        if shed.get("FERTILIZER", 0) > 2:
            market.append(["SELL", "FERTILIZER", shed["FERTILIZER"] - 2])
        if len(me.get("hands", [])) < 4 and money > 500 and day >= 1:
            market.append(["HIRE"])
        unlocked = len(me.get("unlocked_quadrants", []))
        if 0 < unlocked <= 3 and day >= LAND_DAYS[unlocked - 1] and money > LAND_COSTS[unlocked - 1] + 1000:
            market.append(["BUY_LAND"])

        # herd-level flags recomputed from live tiles
        cow_tiles = [(x, y) for y in range(10) for x in range(10)
                     if isinstance(tiles[y][x], dict) and tiles[y][x].get("animal") == "COW"]
        unfed = [(x, y) for (x, y) in cow_tiles if not tiles[y][x].get("fed_today")]
        built = sum(1 for row in tiles for c in row
                    if isinstance(c, dict) and c.get("kind") == "PASTURE")

        field = []
        for u_idx, pos in _each_unit(obs):
            inv = invs[u_idx] if u_idx < len(invs) else {}
            # 1. feed round: carrier goes to unfed cow, empty carrier refills
            if unfed and inv.get("WHEAT", 0) > 0:
                tgt = _nearest(pos, unfed)
                t = tiles[pos[1]][pos[0]]
                if pos == list(tgt) and isinstance(t, dict) and not t.get("fed_today"):
                    field.append(["FEED"])
                    unfed.remove(tgt)
                else:
                    field.append(_step(pos, list(tgt)))
                continue
            if unfed and inv.get("WHEAT", 0) <= 0 and shed.get("WHEAT", 0) > 0:
                near = _shed_near(pos)
                if pos == list(near):
                    field.append(["PICKUP", "WHEAT", 6])
                    shed = dict(shed)
                    shed["WHEAT"] = max(0, shed.get("WHEAT", 0) - 6)
                    invs[u_idx] = dict(inv)
                    invs[u_idx]["WHEAT"] = invs[u_idx].get("WHEAT", 0) + 6
                else:
                    field.append(_step(pos, list(near)))
                continue
            t = tiles[pos[1]][pos[0]] if 0 <= pos[1] < 10 and 0 <= pos[0] < 10 else "LOCKED"
            if t == "LOCKED":
                field.append(_step(pos, [4, 4]))
                continue
            # 2. harvest / collect / care on occupied tile
            if isinstance(t, dict) and "animal" in t and t.get("animal") == "COW":
                if t.get("yield_units", 0) > 0:
                    field.append(["HARVEST"])
                    continue
                if t.get("fertilizer_available"):
                    field.append(["COLLECT_FERTILIZER"])
                    continue
                if not t.get("cared_today"):
                    field.append(["CARE"])
                    continue
            # 3. carry a cow to an empty pasture
            if inv.get("COW", 0) > 0:
                empt = [p for p in PASTURES
                        if isinstance(tiles[p[1]][p[0]], dict)
                        and tiles[p[1]][p[0]].get("kind") == "PASTURE"
                        and "animal" not in tiles[p[1]][p[0]]]
                if empt:
                    tgt = _nearest(pos, empt)
                    field.append(_step(pos, list(tgt)) if pos != list(tgt) else ["PLACE", "COW"])
                    continue
            # 4. fetch cow from shed
            if shed.get("COW", 0) > 0 and inv.get("COW", 0) <= 0:
                near = _shed_near(pos)
                field.append(_step(pos, list(near)) if pos != list(near) else ["PICKUP", "COW", 1])
                continue
            # 5. build pastures first (free) so placements never wait
            if built < self.NCOWS:
                for p in PASTURES:
                    if tiles[p[1]][p[0]] is None:
                        field.append(_step(pos, list(p)) if pos != list(p) else ["BUILD_PASTURE"])
                        break
                else:
                    field.append(["PASS"])
                continue
            if isinstance(t, dict) and t.get("kind") == "WEED":
                field.append(["DIG"])
                continue
            # 6. walk to remaining work: harvestable, collectable, weed
            work_h, work_c, weeds = [], [], []
            for y in range(10):
                for x in range(10):
                    c = tiles[y][x]
                    if not (isinstance(c, dict) and "animal" in c):
                        if isinstance(c, dict) and c.get("kind") == "WEED":
                            weeds.append((x, y))
                        continue
                    if c.get("animal") != "COW":
                        continue
                    if c.get("yield_units", 0) > 0:
                        work_h.append((x, y))
                    elif c.get("fertilizer_available"):
                        work_c.append((x, y))
            tgt = None
            if work_h:
                tgt = _nearest(pos, work_h)
            elif work_c:
                tgt = _nearest(pos, work_c)
            elif weeds:
                tgt = _nearest(pos, weeds)
            field.append(_step(pos, list(tgt)) if tgt else ["PASS"])
        return {"farmer": field[0], "hands": field[1:], "market": market[:10]}


class FlooderBot:
    """Crops-only volume spammer (Yash mechanism, no husbandry): rotate
    wheat/carrot/melon/strawberry across every tile, SELL every unit every
    turn (no floors), 8 hands/day, land when rich.

    Models the ladder flooders whose shared-market volume collapses prices
    and strangles price-waiting agents. Honesty bar: solo >= 15k (volume at
    rising solo prices must pay); margin vs it is the flood-response gate.
    Test device only, never submitted."""

    CROPS = ["WHEAT", "CARROT", "MELON", "STRAWBERRY"]
    FIRST = {"WHEAT": 4, "CARROT": 3, "MELON": 10, "STRAWBERRY": 0}

    def __call__(self, obs):
        day = obs["day"]
        me = obs["farms"][obs["player"]]
        private = obs["private"]
        money = me["money"]
        tiles = _tiles_of(me)
        shed = dict(private["shed"])
        seeds = dict(private["seeds"])
        invs = private["inventories"]
        market = []

        if day == 0 and money > 1500:
            # opening stock: cheap staples bulk, premium toe-hold
            market.append(["BUY_SEED", "WHEAT", 12])
            market.append(["BUY_SEED", "CARROT", 8])
            market.append(["BUY_SEED", "MELON", 2])
        for c in self.CROPS:
            if seeds.get(c, 0) < 3 and money > 500 and day <= 19:
                market.append(["BUY_SEED", c, 3])
        # dump EVERYTHING, every turn, no floors
        for item, n in shed.items():
            if n > 0:
                market.append(["SELL", item, n])
        if me.get("hires_today", 0) < 8 and money > 100:
            market.append(["HIRE"])
        unlocked = len(me.get("unlocked_quadrants", []))
        if 0 < unlocked <= 3 and day >= LAND_DAYS[unlocked - 1] \
                and money > LAND_COSTS[unlocked - 1] + 500:
            market.append(["BUY_LAND"])

        field = []
        for u_idx, pos in _each_unit(obs):
            t = tiles[pos[1]][pos[0]] if 0 <= pos[1] < 10 and 0 <= pos[0] < 10 else "LOCKED"
            if t == "LOCKED":
                field.append(_step(pos, [4, 4]))
                continue
            if isinstance(t, dict) and t.get("kind") == "WEED":
                field.append(["DIG"])
                continue
            if isinstance(t, dict) and t.get("kind") == "PLANT":
                age = day - t.get("planted_day", day)
                if t.get("yield_units", 0) > 0 and age >= self.FIRST[t.get("crop", "WHEAT")]:
                    field.append(["HARVEST"])
                    continue
                if not t.get("watered_today"):
                    field.append(["WATER"])
                    continue
            if t is None:
                c = self.CROPS[(pos[0] + pos[1]) % 4]
                if seeds.get(c, 0) > 0 and day <= 19:
                    field.append(["PLANT", c])
                    seeds[c] -= 1
                    continue
            thirsty, ready, empty = [], [], []
            for y in range(10):
                for x in range(10):
                    c = tiles[y][x]
                    if c == "LOCKED":
                        continue
                    if isinstance(c, dict) and c.get("kind") == "PLANT":
                        age = day - c.get("planted_day", day)
                        if c.get("yield_units", 0) > 0 and age >= self.FIRST[c.get("crop", "WHEAT")]:
                            ready.append((x, y))
                        elif not c.get("watered_today"):
                            thirsty.append((x, y))
                    elif c is None and day <= 19:
                        empty.append((x, y))
            tgt = (ready or thirsty or empty)
            tgt = _nearest(pos, tgt) if tgt else None
            field.append(_step(pos, list(tgt)) if tgt else ["PASS"])
        return {"farmer": field[0], "hands": field[1:], "market": market[:10]}


def run_arch(seeds):
    from src.simulator import Simulator
    from main import Agent

    for name, factory in (("wheat", WheatBot), ("dairy", DairyBot),
                          ("flooder", FlooderBot)):
        solo, margin = [], []
        ok = True
        for s in seeds:
            try:
                r1 = Simulator(seed=s).run([factory(), "pass"])
                r2 = Simulator(seed=s).run([Agent(), factory()])
            except Exception as e:  # noqa: BLE001
                print(f"{name} seed {s}: ERROR {type(e).__name__}: {e}")
                ok = False
                break
            solo.append(r1["money"][0])
            margin.append(r2["money"][0] - r2["money"][1])
        if solo:
            print(f"[{name}] solo mean=${sum(solo)/len(solo):,.0f} "
                  f"({'HONEST' if sum(solo)/len(solo) > 20000 else 'BROKEN?'}) | "
                  f"our margin mean=${sum(margin)/len(margin):+,.0f} "
                  f"wins={sum(1 for m in margin if m > 0)}/{len(margin)} | device_ok={ok}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Archetype honesty + margins")
    ap.add_argument("--seeds", type=int, default=8)
    args = ap.parse_args()
    run_arch(list(range(args.seeds)))
