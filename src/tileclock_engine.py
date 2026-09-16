"""
tileclock_engine.py — Full routing engine using TileClock (7 timings) + smart priority.
Runs in parallel with old planner for shadow testing, no replacement yet.
FIX: PLANT/HARVEST now use real seeds + season + cap + last playable day.
Geography 15 and snake preserved.
"""

from typing import Dict, List, Tuple
from src.tile_clock import build_clock
from src.config import CROP_CONFIG, PASTURE_LOCATIONS, PLAN, MELON_LAST_DAY, STRAWBERRY_LAST_DAY, LAST_PLAYABLE_DAY, CROP_ADVISOR_ON, STRAW_LEAD_THRESHOLD, ADVISOR_MIN_DAY
from src.constants import SHED_TILES
from src.economy import MarketEngine

PRIORITY = {
    "FEED": 0,
    "WATER": 1,
    "HARVEST_FINAL": 2,
    "DIG": 3,
    "BUILD_PASTURE": 4,
    "BUILD_COOP": 4,
    "PLACE": 4,
    "HARVEST_PARTIAL": 5,
    "PLANT": 6,
    "CARE": 7,
    "COLLECT_FERTILIZER": 8,
    "FERTILIZE": 9,
    "DEPOSIT": 10,
}

DEFAULT_CROP_ORDER = ("STRAWBERRY", "MELON", "WHEAT")
MELON_CAP = 28

def _is_melon_season(day:int)->bool: return day <= MELON_LAST_DAY
def _is_straw_season(day:int)->bool: return day <= STRAWBERRY_LAST_DAY
def _crop_active(crop, day):
    if crop=="STRAWBERRY": return _is_straw_season(day)
    if crop=="MELON": return _is_melon_season(day)
    return True

def _advisor_crop_order(day, market_ctx):
    try:
        from src.decision_engine import project_harvest_prices
        proj = project_harvest_prices(market_ctx) if market_ctx else {}
    except Exception:
        proj={}
    straw_active=_is_straw_season(day)
    straw_ok=(straw_active and (day < ADVISOR_MIN_DAY or proj.get("STRAWBERRY") is None or proj.get("STRAWBERRY",0) >= STRAW_LEAD_THRESHOLD))
    order=[]
    if straw_ok: order.append("STRAWBERRY")
    for c in DEFAULT_CROP_ORDER:
        if c=="STRAWBERRY": continue
        if _crop_active(c, day): order.append(c)
    if straw_active and not straw_ok: order.append("STRAWBERRY")
    return order or list(DEFAULT_CROP_ORDER)

def _choose_crop_for_plant(day, tiles, seeds, market_ctx):
    """Return best crop to plant now using real seeds, season, cap, LAST_PLAYABLE_DAY."""
    if CROP_ADVISOR_ON and market_ctx:
        crop_order=_advisor_crop_order(day, market_ctx)
    else:
        crop_order=list(DEFAULT_CROP_ORDER)
    melon_on_field=sum(1 for row in tiles for t in row if isinstance(t, dict) and t.get("kind")=="PLANT" and t.get("crop")=="MELON")
    for crop in crop_order:
        if not _crop_active(crop, day): continue
        if seeds.get(crop,0) <=0: continue
        if crop=="MELON" and melon_on_field >= MELON_CAP: continue
        if day + CROP_CONFIG[crop]["first_yield_day"] > LAST_PLAYABLE_DAY: continue
        return crop
    return None

def _is_harvest_ready(tile, day):
    if not isinstance(tile, dict) or tile.get("kind")!="PLANT": return False
    crop=tile.get("crop")
    cfg=CROP_CONFIG.get(crop, {})
    age=day - tile.get("planted_day", day)
    y_units=tile.get("yield_units",0)
    if y_units<=0: return False
    if cfg.get("is_ongoing"): return True
    return age >= cfg.get("first_yield_day", 999)

def decide_for_worker(pos: List[int], tiles, day: int, hour: int, shed: Dict, seeds: Dict, inv: Dict, animals_ordered: Dict, market_ctx=None) -> List[str]:
    clock = build_clock(tiles, day)
    best = None
    best_score = None
    best_op = None
    best_target = None
    fx, fy = pos
    melon_on_field = sum(1 for row in tiles for t in row if isinstance(t, dict) and t.get("kind")=="PLANT" and t.get("crop")=="MELON")
    for key, info in clock.items():
        try:
            x_str, y_str = key.strip("()").split(",")
            x, y = int(x_str), int(y_str)
        except Exception:
            continue
        t_direct = tiles[y][x] if 0 <= y < len(tiles) and 0 <= x < len(tiles[0]) else None
        if t_direct is None and (x,y) in PASTURE_LOCATIONS:
            pastures = sum(1 for row in tiles for t in row if isinstance(t, dict) and t.get("kind")=="PASTURE")
            if day <= 2: target = 5
            else: target = min(PLAN["COW"]+PLAN["SHEEP"], sum(animals_ordered.get(k,0) for k in ("COW","SHEEP"))+2)
            if pastures < target:
                op = "BUILD_PASTURE"
                prio = PRIORITY["BUILD_PASTURE"]
                dist = abs(x-fx) + abs(y-fy)
                score = prio*10 + dist*0.3
                if best is None or score < best_score:
                    best = (x,y); best_score = score; best_op = op; best_target = (x,y)
                continue
        if isinstance(t_direct, dict) and t_direct.get("kind")=="PASTURE" and not t_direct.get("animal"):
            if any(MarketEngine._unplaced_animal(inv, shed, a) >0 for a in ("COW","SHEEP")):
                op = "PLACE"; prio = PRIORITY["PLACE"]
                dist = abs(x-fx) + abs(y-fy)
                score = prio*10 + dist*0.3
                if best is None or score < best_score:
                    best = (x,y); best_score = score; best_op = op; best_target = (x,y)
                continue
        op = None; prio = None
        if info.get("state") == "WEED":
            op = "DIG"; prio = PRIORITY["DIG"]
        elif info.get("feed") and info["feed"]["type"] == "mandatory" and "now" in info["feed"]["due"]:
            if inv.get("WHEAT",0)>0 or shed.get("WHEAT",0)>0:
                op = "FEED"; prio = PRIORITY["FEED"]
        elif info.get("harvest"):
            t = tiles[y][x] if 0 <= y < len(tiles) and 0 <= x < len(tiles[0]) else None
            if _is_harvest_ready(t, day):
                sched = info["harvest"].get("schedule") if isinstance(info["harvest"].get("schedule"), list) else []
                is_final = any(h.get("day")==day and h.get("type")=="final" for h in sched) if sched else False
                # also final if ongoing last harvest or day>=27
                if is_final or day >= 27:
                    op = "HARVEST"; prio = PRIORITY["HARVEST_FINAL"]
                else:
                    op = "HARVEST"; prio = PRIORITY["HARVEST_PARTIAL"]
        elif info.get("water") and info["water"]["type"] == "mandatory" and "EOD" in info["water"]["due"]:
            t = tiles[y][x] if 0 <= y < len(tiles) and 0 <= x < len(tiles[0]) else None
            if isinstance(t, dict) and t.get("kind")=="PLANT" and not t.get("watered_today"):
                op = "WATER"; prio = PRIORITY["WATER"]
        elif info.get("state") == "empty" and info.get("sow"):
            chosen = _choose_crop_for_plant(day, tiles, seeds, market_ctx)
            if chosen is not None:
                op = "PLANT"; prio = PRIORITY["PLANT"]
        elif info.get("state","").startswith("COOP") or info.get("state","").startswith("PASTURE"):
            t = tiles[y][x] if 0 <= y < len(tiles) and 0 <= x < len(tiles[0]) else None
            if isinstance(t, dict) and "animal" in t:
                if not t.get("cared_today"):
                    op = "CARE"; prio = PRIORITY["CARE"]
                elif t.get("fertilizer_available"):
                    op = "COLLECT_FERTILIZER"; prio = PRIORITY["COLLECT_FERTILIZER"]
        if op is None: continue
        dist = abs(x-fx) + abs(y-fy)
        score = prio*10 + dist*0.3
        if best is None or score < best_score:
            best = (x,y); best_score = score; best_op = op; best_target = (x,y)
    if best is None: return ["PASS"]
    if best_op == "DIG":
        if pos != list(best_target):
            tx,ty=best_target
            if pos[0]!=tx: return ["EAST" if tx>pos[0] else "WEST"]
            if pos[1]!=ty: return ["SOUTH" if ty>pos[1] else "NORTH"]
        return ["DIG"]
    if best_op == "FEED":
        if inv.get("WHEAT",0) <=0:
            if shed.get("WHEAT",0) >0:
                near = min(SHED_TILES, key=lambda s: abs(s[0]-pos[0])+abs(s[1]-pos[1]))
                if pos != list(near):
                    tx,ty=near
                    if pos[0]!=tx: return ["EAST" if tx>pos[0] else "WEST"]
                    if pos[1]!=ty: return ["SOUTH" if ty>pos[1] else "NORTH"]
                return ["PICKUP", "WHEAT", min(6, shed.get("WHEAT",0))]
            return ["PASS"]
        if pos != list(best_target):
            tx,ty=best_target
            if pos[0]!=tx: return ["EAST" if tx>pos[0] else "WEST"]
            if pos[1]!=ty: return ["SOUTH" if ty>pos[1] else "NORTH"]
        return ["FEED"]
    if best_op == "WATER":
        if pos != list(best_target):
            tx,ty=best_target
            if pos[0]!=tx: return ["EAST" if tx>pos[0] else "WEST"]
            if pos[1]!=ty: return ["SOUTH" if ty>pos[1] else "NORTH"]
        return ["WATER"]
    if best_op == "HARVEST":
        if pos != list(best_target):
            tx,ty=best_target
            if pos[0]!=tx: return ["EAST" if tx>pos[0] else "WEST"]
            if pos[1]!=ty: return ["SOUTH" if ty>pos[1] else "NORTH"]
        return ["HARVEST"]
    if best_op == "PLANT":
        if pos != list(best_target):
            tx,ty=best_target
            if pos[0]!=tx: return ["EAST" if tx>pos[0] else "WEST"]
            if pos[1]!=ty: return ["SOUTH" if ty>pos[1] else "NORTH"]
        chosen = _choose_crop_for_plant(day, tiles, seeds, market_ctx)
        if chosen: return ["PLANT", chosen]
        return ["PASS"]
    if best_op == "BUILD_PASTURE":
        if pos != list(best_target):
            tx,ty=best_target
            if pos[0]!=tx: return ["EAST" if tx>pos[0] else "WEST"]
            if pos[1]!=ty: return ["SOUTH" if ty>pos[1] else "NORTH"]
        return ["BUILD_PASTURE"]
    if best_op == "BUILD_COOP":
        if pos != list(best_target):
            tx,ty=best_target
            if pos[0]!=tx: return ["EAST" if tx>pos[0] else "WEST"]
            if pos[1]!=ty: return ["SOUTH" if ty>pos[1] else "NORTH"]
        return ["BUILD_COOP"]
    if best_op == "PLACE":
        chosen = None
        for a in ("COW","SHEEP"):
            if MarketEngine._unplaced_animal(inv, shed, a) > 0:
                if inv.get(a,0) > 0:
                    chosen = a; break
                elif shed.get(a,0) > 0:
                    near = min(SHED_TILES, key=lambda s: abs(s[0]-pos[0])+abs(s[1]-pos[1]))
                    if pos != list(near):
                        tx,ty=near
                        if pos[0]!=tx: return ["EAST" if tx>pos[0] else "WEST"]
                        if pos[1]!=ty: return ["SOUTH" if ty>pos[1] else "NORTH"]
                    return ["PICKUP", a, 1]
        if chosen:
            if pos != list(best_target):
                tx,ty=best_target
                if pos[0]!=tx: return ["EAST" if tx>pos[0] else "WEST"]
                if pos[1]!=ty: return ["SOUTH" if ty>pos[1] else "NORTH"]
            return ["PLACE", chosen]
        return ["PASS"]
    if best_op in ("CARE","COLLECT_FERTILIZER"):
        if pos != list(best_target):
            tx,ty=best_target
            if pos[0]!=tx: return ["EAST" if tx>pos[0] else "WEST"]
            if pos[1]!=ty: return ["SOUTH" if ty>pos[1] else "NORTH"]
        return [best_op]
    return ["PASS"]
