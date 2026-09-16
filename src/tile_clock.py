"""
tile_clock.py â€” TileClock diagnostic only (read-only, no side effects).

Isolation: no jobs, no BUY, no prio. Called from main.py only if TILE_CLOCK_ENABLED.
Fertilize is opportunity window (optional), not mandatory alert.
Multi-harvest: partial vs final distinction (strawberry 10,12,14 partial vs 16 final).
"""

from typing import Dict, List, Optional
from src.config import CROP_CONFIG

# Optional flag â€” OFF by default for diagnosis only
TILE_CLOCK_ENABLED = True

def _harvest_schedule(crop: str, planted_day: int) -> List[dict]:
    """Return list of harvest points with type partial/final."""
    cfg = CROP_CONFIG.get(crop)
    if not cfg:
        return []
    is_ongoing = cfg.get("is_ongoing", False)
    first = cfg["first_yield_day"]
    max_day = cfg["max_yield_day"]
    max_yield = cfg["max_yield"]
    if not is_ongoing:
        # one-time: single harvest at max
        return [{"day": planted_day + max_day, "type": "final", "label": f"{crop} harvest final"}]
    # ongoing: 4 harvests
    if crop == "STRAWBERRY":
        # 10,12,14,16
        days = [planted_day + 10, planted_day + 12, planted_day + 14, planted_day + 16]
        out = []
        for i, d in enumerate(days):
            typ = "final" if i == len(days)-1 else "partial"
            out.append({"day": d, "type": typ, "label": f"{crop} harvest {typ} {d}"})
        return out
    if crop == "TOMATO":
        days = [planted_day + 8, planted_day + 9, planted_day + 10, planted_day + 11]
        out = []
        for i, d in enumerate(days):
            typ = "final" if i == len(days)-1 else "partial"
            out.append({"day": d, "type": typ, "label": f"{crop} harvest {typ} {d}"})
        return out
    # generic ongoing: every 1 day x4
    days = [planted_day + first + i for i in range(4)]
    out = []
    for i, d in enumerate(days):
        typ = "final" if i == len(days)-1 else "partial"
        out.append({"day": d, "type": typ, "label": f"{crop} harvest {typ} {d}"})
    return out

def tile_clock_for_tile(tile: dict, x: int, y: int, day: int) -> Dict:
    """Read-only clock for single tile. No mutation."""
    pos = f"({x},{y})"
    if tile is None:
        # empty â€” weed risk + sow opportunity
        return {
            "pos": pos,
            "state": "empty",
            "sow": {"window": f"day {day}â†’{day+2}", "type": "mandatory", "note": "plant within 2 days or weed 0.005"},
            "weed": {"due": f"day {day+1} EOD", "type": "mandatory", "note": "spawn 0.005 if stays empty"},
            "water": None, "harvest": None, "replant": None, "fertilize": None, "feed": None,
        }
    if isinstance(tile, str) and tile == "WEED":
        return {"pos": pos, "state": "WEED", "weed": {"due": "now", "type": "mandatory", "note": "DIG required"}, "sow": None, "water": None, "harvest": None, "replant": None, "fertilize": None, "feed": None}
    if isinstance(tile, dict) and tile.get("kind") == "WEED":
        return {"pos": pos, "state": "WEED", "weed": {"due": "now", "type": "mandatory", "note": "DIG required"}, "sow": None, "water": None, "harvest": None, "replant": None, "fertilize": None, "feed": None}
    if isinstance(tile, dict) and "animal" in tile:
        # animal â€” feed mandatory, harvest periodic
        animal = tile.get("animal")
        fed = tile.get("fed_today", False)
        consec = tile.get("consecutive_unfed", 0)
        feed_due = "now" if not fed else f"day {day+1}"
        feed_type = "mandatory"
        feed_note = f"consecutive_unfed {consec}â†’2 escapes" if not fed else "fed today"
        # harvest schedule for animals (goose 4, cow 8, sheep 6) â€” simplified
        placed = tile.get("placed_day", day)
        return {
            "pos": pos, "state": f"{tile.get('kind')} {animal}",
            "feed": {"due": feed_due, "type": feed_type, "note": feed_note},
            "harvest": {"schedule": "periodic", "type": "mandatory", "note": f"{animal} periodic yield"},
            "water": None, "sow": None, "replant": None, "weed": None,
            "fertilize": {"window": "collect daily", "type": "opportunity", "note": "COLLECT_FERTILIZER optional"},
        }
    if isinstance(tile, dict) and tile.get("kind") == "PLANT":
        crop = tile.get("crop")
        planted = tile.get("planted_day", day)
        watered = tile.get("watered_today", False)
        consec_w = tile.get("consecutive_unwatered", 0)
        cfg = CROP_CONFIG.get(crop, {})
        # water
        if not watered:
            water_due = f"day {day} EOD"
            water_type = "mandatory"
            water_note = f"consecutive {consec_w}â†’2 weed" if consec_w >=1 else "water today"
        else:
            water_due = f"day {day+1}"
            water_type = "mandatory"
            water_note = "watered today, next due tomorrow"
        # harvest schedule
        harvest_sched = _harvest_schedule(crop, planted)
        # fertilize opportunity window: 3 days from any harvest
        fertilize = None
        if crop in ("STRAWBERRY",):
            # window around harvest days
            fertilize = {"window": f"{planted+10}â†’{planted+13} (3 days)", "type": "opportunity", "note": "double yield if watered+fertilized, optional"}
        # replant only after final harvest
        replant = None
        # find final harvest day
        final_day = None
        for h in harvest_sched:
            if h["type"] == "final":
                final_day = h["day"]
        if final_day is not None:
            replant = {"due": f"day {final_day+1}", "type": "mandatory", "note": "tile empty after final, sow within 2 days"}
        return {
            "pos": pos, "state": f"PLANT {crop} age {day-planted}",
            "water": {"due": water_due, "type": water_type, "note": water_note},
            "harvest": {"schedule": harvest_sched, "type": "mandatory", "note": "partial vs final distinguished"},
            "fertilize": fertilize,
            "replant": replant,
            "sow": None, "weed": None, "feed": None,
        }
    return {"pos": pos, "state": "unknown", "sow": None, "water": None, "harvest": None, "replant": None, "weed": None, "fertilize": None, "feed": None}

def build_clock(tiles, day: int) -> Dict[str, Dict]:
    """Build full clock for board â€” read-only."""
    out = {}
    for y,row in enumerate(tiles):
        for x,t in enumerate(row):
            if t == "LOCKED":
                continue
            out[f"({x},{y})"] = tile_clock_for_tile(t, x, y, day)
    return out
