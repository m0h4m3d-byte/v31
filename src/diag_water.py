"""diag water causes - like PASS analysis"""
from src.simulator import Simulator
from main import Agent
from collections import Counter

# monkey patch planner to count
from src.planner import FarmPlanner
orig_collect = FarmPlanner.collect_jobs
orig_action = FarmPlanner.unit_action

counters = Counter()
total_unwatered = 0
total_water_jobs = 0

def patched_collect(day, tiles, shed, seeds, invs, animals_ordered, market_ctx=None):
    jobs = orig_collect(planner, day, tiles, shed, seeds, invs, animals_ordered, market_ctx)
    # count water jobs
    global total_water_jobs
    total_water_jobs += sum(1 for j in jobs if j[1]=="WATER")
    return jobs

# We'll just run evaluation style and count in unit_action
planner = FarmPlanner()
# patch
import types

# Instead, run simulation and count reasons for each unwatered plant not being watered
# Trace per turn: for each plant with watered_today False, check if WATER job exists and why not picked

from src.evaluation import run_single_game
import src.evaluation as ev

# Patch run_single_game to collect water causes
orig_run = ev.run_single_game

def counting_run(seed):
    sim=Simulator(seed=seed)
    sim.reset()
    views=sim.step(None)
    agent=Agent()
    # reset counters per game
    local = Counter()
    total = 0
    while not sim.done:
        obs=views[0]
        me=obs["farms"][0]
        tiles=me["tiles"]
        # count unwatered plants at start of turn
        unwatered = []
        for y,row in enumerate(tiles):
            for x,t in enumerate(row):
                if isinstance(t, dict) and t.get("kind")=="PLANT" and not t.get("watered_today"):
                    unwatered.append((x,y))
                    total_unwatered_local = 1
        # get jobs
        # we need to call planner collect to see jobs
        # Use agent's planner
        jobs = agent.planner.collect_jobs(obs["day"], tiles, obs["private"]["shed"], obs["private"]["seeds"], obs["private"]["inventories"], agent.market.animals_ordered, {"day":obs["day"],"hour":obs["hour"],"prices":obs["market"]["prices"],"inventory":obs["market"]["inventory"],"shops":obs.get("town",{}).get("unlocked_shops",[]), "milk_crash": getattr(agent.market, "milk_crash_active", False)})
        # for each unwatered, check why not in jobs or not picked
        # Simplified: check if WATER job exists for that pos
        water_jobs_pos = set(j[0] for j in jobs if j[1]=="WATER")
        for (x,y) in unwatered:
            nonlocal_total = 0
            # we need to count per plant
            # This is per turn, need to aggregate
            pass
        act=agent(obs)
        views=sim.step([act, {"farmer":["PASS"],"hands":[],"market":[]}])
    return

# Simpler: just run with instrumentation in planner
# Add counters inside planner
import src.planner as pl
orig_unit = pl.FarmPlanner.unit_action
cnt = Counter()
cnt_total_water_opportunities = 0
cnt_water_picked = 0

def patched_unit(self, pos, u_idx, jobs, used_jobs, inv, shed):
    global cnt, cnt_total_water_opportunities, cnt_water_picked
    # count water opportunities
    water_jobs = [j for j in jobs if j[1]=="WATER"]
    cnt_total_water_opportunities += len(water_jobs)
    # call original and see what is picked
    res = orig_unit(self, pos, u_idx, jobs, used_jobs, inv, shed)
    # res is action, check if WATER
    if res and res[0]=="WATER":
        cnt_water_picked+=1
        cnt["water_picked"]+=1
    else:
        # if there was water job but not picked, count reason
        # check if any water job was available but not picked due to used_jobs or prio
        # Check if water job exists for this worker's nearest
        if water_jobs:
            # check if any water job was in used_jobs
            if any(j[0] in used_jobs for j in water_jobs):
                cnt["congestion_used_jobs"]+=1
            elif any(j[2]==0 for j in water_jobs): # FEED prio0 exists
                cnt["higher_prio_FEED"]+=1
            elif any(j[2]==1 for j in water_jobs):
                # water prio2 vs harvest prio1 etc - check if harvest exists with prio1
                harvest_exists = any(j[1]=="HARVEST" and j[2]==1 for j in jobs)
                if harvest_exists:
                    cnt["higher_prio_HARVEST"]+=1
                else:
                    cnt["worker_busy_or_distance"]+=1
            else:
                cnt["other"]+=1
    return res

pl.FarmPlanner.unit_action = patched_unit

# run 8 seeds
for seed in range(8):
    # reset
    sim=Simulator(seed=seed)
    sim.reset()
    views=sim.step(None)
    agent=Agent()
    # need to reset planner counters
    cnt.clear()
    # run game
    while not sim.done:
        obs=views[0]
        act=agent(obs)
        views=sim.step([act, {"farmer":["PASS"],"hands":[],"market":[]}])
    print(f"seed {seed} water jobs {cnt_total_water_opportunities} picked {cnt_water_picked} breakdown {dict(cnt)}")
    # reset for next seed
    cnt_total_water_opportunities=0
    cnt_water_picked=0
