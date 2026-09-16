"""
test_suite.py - Unified Test Suite for Kaggriculture Agent

Single source of truth for all agent testing.
Design: Dynamic, extensible, covers baseline metrics.

Principles:
- ONE test file only (no test_*.py proliferation)
- All metrics collected via registry pattern
- Easy to add new test scenarios without restructuring
- Baseline coverage: seed purchasing, planting, harvesting, market operations
"""

from collections import defaultdict
from datetime import datetime


# ============================================================
# Test Configuration
# ============================================================

CONFIG = {
    "episodes": 3,           # Number of episodes to average over
    "max_steps": 720,        # Season length (24 turns × 30 days)
    "debug_mode": False,     # Set True for verbose output per episode
    "export_csv": True,      # Export results to CSV after run
    "csv_path": "test_results.csv",
}


# ============================================================
# Metric Registry Pattern
# ============================================================
# All metrics are collected through this registry. New metrics
# can be added by registering a collector function without
# modifying the core test loop.

metric_registry = {}


def register_metric(name: str):
    """Decorator to register a new metric collector function."""
    def decorator(func):
        metric_registry[name] = func
        return func
    return decorator


# ============================================================
# Baseline Metric Collectors
# ============================================================

@register_metric("total_reward")
def collect_total_reward(obs, action, env):
    """Total cumulative reward per episode."""
    if env and hasattr(env, "steps") and env.steps:
        total = 0
        for s in env.steps:
            if isinstance(s, dict) and s.get("reward") is not None:
                try:
                    total += float(s["reward"])
                except (ValueError, TypeError):
                    pass
        return total
    return 0


@register_metric("market_orders")
def collect_market_orders(obs, action, env):
    """Count total market orders issued."""
    market = action.get("market", [])
    return len(market) if market else 0


@register_metric("seeds_purchased")
def collect_seeds_purchased(obs, action, env):
    """Count seed purchase orders."""
    market = action.get("market", [])
    count = 0
    for o in market:
        if o and o[0] == "BUY_SEED":
            count += 1
    return count


@register_metric("animals_bought")
def collect_animals_bought(obs, action, env):
    """Count animal purchase orders."""
    market = action.get("market", [])
    count = 0
    for o in market:
        if o and o[0] == "BUY_ANIMAL":
            count += 1
    return count


@register_metric("hands_hired")
def collect_hands_hired(obs, action, env):
    """Count hands hired this turn."""
    return action.get("hires_today", 0) if hasattr(action, "get") else 0


@register_metric("shed_capacity_usage")
def collect_shed_usage(obs, action, env):
    """Calculate shed usage percentage."""
    if obs and "private" in obs and "shed" in obs["private"]:
        shed = obs["private"]["shed"]
        total = sum(shed.values()) if shed else 0
        capacity = 100  # SHED_CAPACITY
        return min(total / capacity * 100, 100) if capacity > 0 else 0
    return 0


@register_metric("crops_planted")
def collect_crops_planted(obs, action, env):
    """Count total crops planted this episode."""
    if obs and "private" in obs and "seeds" in obs["private"]:
        seeds = obs["private"]["seeds"]
        return sum(1 for c in seeds if seeds[c] > 0) if seeds else 0
    return 0


# ============================================================
# Agent Wrapper for Metric Collection
# ============================================================

class MetricAgentWrapper:
    """
    Wrapper that collects metrics during env.run().
    Stores collected metrics per-turn, then provides averages.
    """
    def __init__(self, inner_agent, metric_names=None):
        self.inner_agent = inner_agent
        self.metric_names = metric_names or list(metric_registry.keys())
        self.episode_metrics = defaultdict(list)

    def __call__(self, obs):
        # Get action from inner agent
        action = self.inner_agent(obs)

# Collect all registered metrics for this step
        for name in self.metric_names:
            if name in metric_registry:
                try:
                    val = metric_registry[name](obs, action, env)  # Pass env, not None
                    self.episode_metrics[name].append(val)
                except Exception:
                    self.episode_metrics[name].append(None)

        return action


# ============================================================
# Baseline Test Runner
# ============================================================

def run_baseline_test(agent_factory, episodes: int = None):
    """
    Run baseline tests and collect averaged metrics.

    agent_factory: callable that returns a new agent function per episode.
                   The agent function should accept (obs) and return action dict.

    Returns:
        dict: Averaged metrics including episode stats and registered metrics.
    """
    import kaggle_environments as kg

    episodes = episodes or CONFIG["episodes"]
    all_results = []

    env = kg.make("kaggriculture", configuration={"episodeSteps": CONFIG["max_steps"]}, debug=CONFIG["debug_mode"])

    for ep in range(episodes):
        print("Episode %d/%d..." % (ep + 1, episodes))

        # Create wrapper agent for metric collection
        base_agent = agent_factory()
        wrapper = MetricAgentWrapper(inner_agent=base_agent,
                                     metric_names=list(metric_registry.keys()))

        # Reset and run environment with metric collection
        env.reset()
        env.run([wrapper, "random"])

        # Gather final results for this episode
        episode_data = {
            "episode": ep + 1,
        }

        # Collect total reward from wrapper metrics
        if "total_reward" in wrapper.episode_metrics:
            vals = wrapper.episode_metrics["total_reward"]
            episode_data["total_reward"] = sum(v for v in vals if v is not None) if vals else 0
        else:
            episode_data["total_reward"] = 0

        # Collect each metric average for this episode
        for name in metric_registry:
            vals = wrapper.episode_metrics.get(name, [])
            if vals and any(v is not None for v in vals):
                episode_data["avg_%s" % name] = sum(v for v in vals if v is not None) / len([v for v in vals if v is not None])
            else:
                episode_data["avg_%s" % name] = 0

        all_results.append(episode_data)
        print("  Completed - steps collected: %d" % len(wrapper.episode_metrics.get("total_reward", [])))

    # No explicit close needed for kaggle_environments
    # Environment resources are managed internally

    # Compute overall averages across episodes
    if not all_results:
        return {}

    num_episodes = len(all_results)
    avg_results = {
        "episodes": num_episodes,
        "avg_reward": sum(r.get("total_reward", 0) for r in all_results) / num_episodes,
    }

    # Add averages for each registered metric
    for name in metric_registry:
        all_vals = [r.get("avg_%s" % name, 0) for r in all_results]
        avg_results["avg_%s" % name] = sum(all_vals) / len(all_vals) if all_vals else 0

    # Export to CSV if configured
    if CONFIG["export_csv"]:
        try:
            import csv
            with open(CONFIG["csv_path"], "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["episode"] + ["avg_%s" % n for n in metric_registry] + ["avg_reward", "episodes"])
                if f.tell() == 0:  # Write header if new file
                    writer.writeheader()
                row = {"episodes": num_episodes, "avg_reward": avg_results.get("avg_reward", 0)}
                for name in metric_registry:
                    row["avg_%s" % name] = avg_results.get("avg_%s" % name, 0)
                writer.writerow(row)
            print("Results exported to %s" % CONFIG["csv_path"])
        except Exception as e:
            print("CSV export failed: %s" % e)

    return avg_results


# ============================================================
# Example Baseline Agent (Minimal Wheat Loop)
# ============================================================

def wheat_loop_agent_factory():
    """
    Factory that returns a wheat loop baseline agent.
    The agent function accepts (obs) and returns action dict.
    """
    def wheat_loop_agent(obs):
        """
        Minimal wheat loop baseline agent.
        Purchases wheat seed if none owned and has money,
        plants when possible, harvests at first yield.
        """
        player = obs.get("player", 0)
        me = obs["farms"][player]
        private = obs["private"]
        market = obs["market"]

        market_orders = []

        # Buy wheat seed on first turn if affordable
        if obs.get("step", 0) == 0 and me["money"] >= 10:
            if private["seeds"].get("WHEAT", 0) == 0:
                market_orders.append(["BUY_SEED", "WHEAT", 1])

        # Sell wheat from shed
        wheat_in_shed = private["shed"].get("WHEAT", 0)
        if wheat_in_shed > 0:
            market_orders.append(["SELL", "WHEAT", wheat_in_shed])

        # Get farmer position
        fx, fy = me["farmer"]
        tile = me["tiles"][fy][fx]

        # Plant if empty tile has wheat seed
        if tile is None and private["seeds"].get("WHEAT", 0) > 0:
            market_orders.append(["PLANT", "WHEAT"])

        # Harvest if plant is ready (age >= 2 for wheat)
        if isinstance(tile, dict) and tile.get("kind") == "PLANT":
            crop_age = obs.get("day", 0) - tile.get("planted_day", 0)
            if crop_age >= 2:  # WHEAT first_yield_day = 2
                market_orders.append(["HARVEST"])

        # Return minimal action dict
        return {"farmer": [["PASS"]], "hands": [], "market": market_orders}

    return wheat_loop_agent


# ============================================================
# Main Execution
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Test Suite Kaggriculture")
    print("   Started: %s" % datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    print("=" * 60)

    # Display registered metrics
    print("\nRegistered metrics (%d):" % len(metric_registry))
    for name in sorted(metric_registry.keys()):
        print("   - %s" % name)

    # Run baseline test with wheat loop agent
    print("\nRunning baseline test with wheat_loop_agent...")
    results = run_baseline_test(wheat_loop_agent_factory, episodes=CONFIG["episodes"])

    # Print summary
    print("\nBaseline Results Summary")
    print("=" * 60)
    for key, value in sorted(results.items()):
        if not key.startswith("avg_"):  # Skip averaged metrics in main output
            print("   %s: %s" % (key, value))
    print("\nAveraged metrics:")
    for key, value in sorted(results.items()):
        if key.startswith("avg_"):
            print("   %s: %.2f" % (key, value))

    print("\n" + "=" * 60)
    print("Test Suite Complete")
    print("   Finished: %s" % datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    print("=" * 60)

    # Provide guidance for adding new metrics
    print("\nAdding New Metrics:")
    print("   1. Define a collector function with @register_metric('new_name')")
    print("      Example:")
    print("      @register_metric('my_custom_metric')")
    print("      def my_collector(obs, action, env):")
    print("          return some_value")
    print("   2. The function signature: collector(obs, action, env) -> numeric|dict")
    print("   3. Results will auto-appear in baseline summaries")
    print("=" * 60)