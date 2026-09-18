"""
bench.py - Unified DeepSim benchmark (default = ladder realism).

Runs the agent under BOTH regimes so no improvement can hide behind solo optimism:

   solo   : vs pass (legacy metric)
   mirror : vs itself (2-player shared market, symmetric-flood stress bound)
   wheat/dairy: vs honest archetype sparring bots (decision metric)

    python -m src.bench --seeds 12
    python -m src.bench --seeds 30 --quick   # solo only, fast

The archetype margins are the GATE for any submission: they must not regress.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description="DeepSim unified bench")
    parser.add_argument("--seeds", type=int, default=12)
    parser.add_argument("--quick", action="store_true", help="solo only")
    args = parser.parse_args()
    seeds = list(range(args.seeds))

    from src.simulator import evaluate
    from main import Agent
    import src.economy as E

    print("=" * 60)
    print(f"DeepSim bench — {args.seeds} seeds — PLAN {E.PLAN['COW']}:{E.PLAN['SHEEP']} W{ E.PLAN['WHEAT']}")
    print("=" * 60)

    # 1. solo (legacy)
    st = evaluate(lambda: Agent(), seeds, opponent="pass")
    print(f"\n[solo vs pass] mean ${st['mean']:,.0f}  best ${st['best']:,.0f} worst ${st['worst']:,.0f}")

    if args.quick:
        return

    # 2. mirror (2-player shared market, symmetric-flood stress bound)
    from src.simulator import Simulator
    mres = []
    for s in seeds:
        mres.append(Simulator(seed=s).run([Agent(), Agent()])["money"][0])
    print(f"\n[mirror vs self] mean ${sum(mres)/len(mres):,.0f}  "
          f"best ${max(mres):,.0f} worst ${min(mres):,.0f}")

    # 3. archetype sparring (diverse honest opponents, decision metric)
    from src.archetypes import WheatBot, DairyBot
    for name, factory in (("wheat", WheatBot), ("dairy", DairyBot)):
        solo, margin = [], []
        for s in seeds:
            r1 = Simulator(seed=s).run([factory(), "pass"])
            r2 = Simulator(seed=s).run([Agent(), factory()])
            solo.append(r1["money"][0])
            margin.append(r2["money"][0] - r2["money"][1])
        tag = "HONEST" if sum(solo) / len(solo) > 12000 else "WEAK-PROBE?"
        print(f"\n[{name}] solo ${sum(solo)/len(solo):,.0f} [{tag}] | "
              f"our margin ${sum(margin)/len(margin):+,.0f} "
              f"wins={sum(1 for m in margin if m > 0)}/{len(margin)}")


if __name__ == "__main__":
    main()
