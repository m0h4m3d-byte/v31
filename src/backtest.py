"""
backtest.py - Replay-backed evaluation: our agent vs RECORDED ladder opponents.

Instead of imaginary archetypes or synchronized clones, we replay the exact
per-turn market+field actions of a real ladder opponent (from a replay JSON)
and play our CURRENT agent against them in the real engine:

    python -m src.backtest --replays replays/my_agent_replays

Answers: "what would THIS code have scored in THAT real match?"
Validity note: the recorded opponent does not react (fixed actions); the
market/engine reacts normally. Engine no-ops invalid replayed actions.

Sanity: backtesting code identical to the recorded version should land in
the same ballpark as the recorded score (not exact: see note above).
"""

import argparse
import glob
import json
import os

from src.simulator import Simulator


def find_us(replay):
    teams = replay.get("info", {}).get("TeamNames", [])
    for i, n in enumerate(teams):
        if "m0h4m3d" in n.lower():
            return i
    return None


def run_backtest(agent_factory, replay_path, copy_obs=False, mode="verbatim"):
    """Play one episode: fresh agent vs recorded opponent actions.

    mode="verbatim": replay every opponent action as-is (field + market).
    mode="market": live competent field (own planner) + RECORDED market
      orders (real sell timing/volumes/pressure, clipped to availability by
      the engine). Use "market": verbatim field actions misfire once state
      diverges (7/8 flattering wins vs 0/8 recorded), market-only transfers.
    """
    import copy as _copy

    with open(replay_path, encoding="utf-8") as f:
        replay = json.load(f)
    steps = replay["steps"]
    us_idx = find_us(replay)
    assert us_idx is not None, f"us not found in {replay_path}"
    opp_idx = 1 - us_idx
    seed = replay.get("info", {}).get("seed")

    sim = Simulator(seed=seed)
    sim.reset()
    views = sim.step(None)
    agent = agent_factory()
    opp_inner = None
    if mode == "market":
        from main import Agent as _ProdAgent

        opp_inner = _ProdAgent()
    n_turns = 0
    while not sim.done and n_turns < len(steps):
        obs = _copy.deepcopy(views[us_idx]) if copy_obs else views[us_idx]
        ours = agent(obs)
        rec = steps[n_turns][opp_idx].get("action") or {}
        if mode == "market":
            live = opp_inner(views[opp_idx])
            opp_act = {
                "farmer": live.get("farmer", ["PASS"]),
                "hands": live.get("hands", []),
                "market": [list(o) for o in rec.get("market", [])],
            }
        else:
            opp_act = {
                "farmer": list(rec.get("farmer", ["PASS"])),
                "hands": [list(h) for h in rec.get("hands", [])],
                "market": [list(o) for o in rec.get("market", [])],
            }
        pair = [None, None]
        pair[us_idx] = ours
        pair[opp_idx] = opp_act
        views = sim.step(pair)
        n_turns += 1
    money = [float(f["money"]) for f in sim.state[0].observation.farms]
    rec_money = replay.get("rewards") or [None, None]
    return {
        "file": os.path.basename(replay_path),
        "seed": seed,
        "us_idx": us_idx,
        "money": money[us_idx],
        "opp_money": money[opp_idx],
        "recorded_us": rec_money[us_idx],
        "recorded_opp": rec_money[opp_idx],
        "turns": n_turns,
    }


def main():
    ap = argparse.ArgumentParser(description="Replay backtest harness")
    ap.add_argument("--replays", default="replays/my_agent_replays")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--mode", choices=["verbatim", "market"], default="market")
    args = ap.parse_args()

    from main import Agent

    files = sorted(glob.glob(os.path.join(args.replays, "*.json")))
    if args.limit:
        files = files[: args.limit]
    rows = []
    for fp in files:
        try:
            r = run_backtest(Agent, fp, mode=args.mode)
        except Exception as e:  # noqa: BLE001 - report per-file, keep going
            print(f"{os.path.basename(fp)}: ERROR {type(e).__name__}: {e}")
            continue
        rows.append(r)
        print(f"{r['file']}: backtest us=${r['money']:,.0f} opp=${r['opp_money']:,.0f} "
              f"| recorded us=${r['recorded_us']:,.0f} opp=${r['recorded_opp']:,.0f}")
    if rows:
        import statistics

        gaps = [r["money"] - r["opp_money"] for r in rows]
        print(f"\nbacktest margins: mean={statistics.mean(gaps):+,.0f} "
              f"wins={sum(1 for g in gaps if g > 0)}/{len(gaps)}")


if __name__ == "__main__":
    main()
