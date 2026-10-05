# Rashed-Step 15.G-09-18-2026-start
"""
Figure: RRC connection-setup latency, three scenarios.

Directly exercises Step 15.F's generic RrcLayer/RrcState machinery and
Step 15.G's compute_connection_setup_stats() metric against REAL,
live simulator runs (not hard-coded numbers, unlike analysis/
ml_pdr_comparison.py's own documented precedent) - constructed
directly in Python (bypassing singleRun.py/singleRunNR.py's click CLI
entirely, the same way analysis/nru_sensing_region_impact.py calls
model.runner.run_scenario() directly), because as of Step 15.G neither
CLI's opt-in RRC/uplink flags existed anywhere but singleRun.py/
singleRunNR.py themselves - this script constructs Gnb/GnbLicensedNR/
NrUE/NrUeLicensed objects directly, exactly like simulation.py/
simulation_nr.py do internally.

Three scenarios, same distance (10m) and default PHY parameters
throughout so only the ATTACH MECHANISM itself differs between bars:

  Licensed NR: grant-based RRC uplink delay (config.rrc_ul_grant_
    delay_us=1000.0 by default since Step 16.A; before that it reused
    15.E's sr_to_grant_delay_us=4000.0) - exactly deterministic, no
    contention of any kind possible. Expected: every seed reads
    identically 2*1000.0 + setup_processing_delay_us(2000.0) = 4000.0us,
    zero variance.

  Step 16.A note: both NR-U bars below now also pay the same
  rrc_ul_grant_delay_us before each LBT wait, so NR-U is never faster
  than licensed NR. Measured after 16.A (20 seeds): licensed 4000.0us,
  NR-U isolated 5629.6us mean, NR-U self-collision 14629.5us mean
  (was 10000.0 / 3629.6 / 7629.6 before 16.A).

  NR-U (isolated UE): a single UE attaching to a gNB whose OWN
    downlink is silenced (see _NoAutoStartGnb below, the same
    isolation technique test/test_nru_uplink.py's own functional tests
    already use) - the UE's RRCSetupRequest/RRCSetupComplete uplink
    messages still genuinely contend via real Cat-4 LBT (Step 15.C's
    LbtChannelAccess), but against an otherwise-idle channel. Models
    "how long does real LBT contention alone add, with nothing else on
    the channel."

  NR-U (gNB self-collision): the REALISTIC single-cell case - the
    gNB's own downlink is saturated and actively transmitting too,
    exactly the scenario Step 15.C's own REALISM FINDING documented
    (a gNB and its own UE, run as independent LBT contenders sharing
    the same next_sync_slot_boundry, collide on EVERY attempt when
    both are saturated - see Project details/Step pre_15.txt's STEP 15
    - 15.C/15.D DONE section). This bar is expected to be visibly
    slower/more variable than the isolated case - not a bug, a genuine
    consequence of that already-documented architectural limitation,
    now visible in a NEW metric (RRC attach latency) this sub-step
    added, not just the pre-existing succ/fail transmission counters.

Run standalone: `python -m analysis.rrc_connection_setup_latency` from
the repo root, or `python analysis/rrc_connection_setup_latency.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import random
import statistics

import simpy

from channel.channel import Channel
from ran.protocol.rrc import RrcState, compute_connection_setup_stats

from nru.nru import Gnb, Config_NR
# Rashed-Step 17.F-10-04-2026-start
from nru.nru import NruUplinkAccessMode
# Rashed-Step 17.F-10-04-2026-end
from nru.ue import NrUE

from nr.nr import GnbLicensedNR, Config_NRL
from nr.ue import NrUeLicensed

from analysis.plot_utils import save_bar_figure

SEEDS = list(range(1, 21))  # 20 seeds per scenario
UE_POS = (10.0, 0.0)   # matches every other analysis/ script's default gNB-UE distance
GNB_POS = (0.0, 0.0)
# Generous enough for NR-U's gNB-self-collision case (the slowest of
# the three) to reliably finish attach within this budget across every
# seed - see module docstring's own empirical range during dev testing
# (roughly 5000-10000us observed for that scenario at this distance;
# ~14000-15000us since Step 16.A's added RRC grant delay).
RUN_UNTIL_US = 200_000.0


def _make_channel(env, n_of_gnb=1):
    return Channel(
        tx_queue=simpy.PriorityResource(env, capacity=1),
        tx_lock=simpy.Resource(env, capacity=1),
        n_of_stations=0,
        n_of_gNB=n_of_gnb,
        backoffs={},
        airtime_data={},
        airtime_control={},
        airtime_data_NR={},
        airtime_control_NR={},
    )


class _NoAutoStartGnb(Gnb):
    """Same isolation technique test/test_nru_uplink.py's own functional
    tests already use (itself following test_packet.py's Step 8.F/10.B
    precedent) - silences ONLY this gNB's own downlink transmit process
    so the "isolated UE" scenario measures real LBT contention against
    an otherwise-idle channel, not this gNB's own competing traffic.
    sync_slot_counter() (which the UE's uplink/RRC timing still needs)
    is untouched and keeps running."""
    def start(self):
        return
        yield  # pragma: no cover - never reached, makes this a generator


def _licensed_nr_latency_us(seed: int) -> float:
    random.seed(seed)
    env = simpy.Environment()
    channel = _make_channel(env)
    cfg = Config_NRL(tdd_enabled=True)
    ue = NrUeLicensed(
        name="UE 1-1", pos=UE_POS, gnb_name="G1",
        env=env, config=cfg, uplink_enabled=True, rrc_enabled=True,
    )
    GnbLicensedNR(env, "G1", channel, GNB_POS, [ue], cfg)
    env.run(until=RUN_UNTIL_US)
    stats = compute_connection_setup_stats([ue])
    assert stats["connected"] == 1, f"seed {seed}: licensed-NR UE never connected within {RUN_UNTIL_US}us"
    return stats["latencies_us"][0]


def _nru_latency_us(seed: int, isolated: bool) -> float:
    random.seed(seed)
    env = simpy.Environment()
    channel = _make_channel(env)
    # Rashed-Step 17.F-10-04-2026: pinned to the autonomous (Cat-4) RRC
    # path these scenarios were defined with, so this figure is unchanged
    # until 17.G revises the scenarios for COT sharing.
    cfg = Config_NR(ul_access_mode=NruUplinkAccessMode.AUTONOMOUS)
    ue = NrUE(
        name="UE 1-1", pos=UE_POS, gnb_name="G1",
        env=env, channel=channel, config_nr=cfg, uplink_enabled=True, rrc_enabled=True,
    )
    gnb_cls = _NoAutoStartGnb if isolated else Gnb
    gnb_cls(env, "G1", channel, GNB_POS, [ue], cfg)
    env.run(until=RUN_UNTIL_US)
    stats = compute_connection_setup_stats([ue])
    scenario = "isolated" if isolated else "gNB self-collision"
    assert stats["connected"] == 1, f"seed {seed}: NR-U ({scenario}) UE never connected within {RUN_UNTIL_US}us"
    return stats["latencies_us"][0]


def generate(seeds=SEEDS):
    licensed_nr = [_licensed_nr_latency_us(s) for s in seeds]
    nru_isolated = [_nru_latency_us(s, isolated=True) for s in seeds]
    nru_collision = [_nru_latency_us(s, isolated=False) for s in seeds]

    categories = ["Licensed NR\n(grant-based)", "NR-U\n(isolated LBT)", "NR-U\n(gNB self-collision)"]
    means = [statistics.mean(licensed_nr), statistics.mean(nru_isolated), statistics.mean(nru_collision)]

    paths = save_bar_figure(
        categories=categories,
        series={"Mean connection setup latency (us)": means},
        xlabel="Scenario",
        ylabel="Connection setup latency (us)",
        output_stem="rrc_connection_setup_latency",
        value_fmt="{:.0f}",
        bar_colors={"Mean connection setup latency (us)": "#4b7248"},
    )

    return {
        "categories": categories,
        "licensed_nr_us": licensed_nr,
        "nru_isolated_us": nru_isolated,
        "nru_collision_us": nru_collision,
        "means_us": means,
    }, paths


if __name__ == "__main__":
    results, paths = generate()
    print(f"{'scenario':>28} | {'mean (us)':>10} {'stdev (us)':>11} {'min (us)':>9} {'max (us)':>9}")
    print("-" * 78)
    for label, values in (
        ("Licensed NR (grant-based)", results["licensed_nr_us"]),
        ("NR-U (isolated LBT)", results["nru_isolated_us"]),
        ("NR-U (gNB self-collision)", results["nru_collision_us"]),
    ):
        mean = statistics.mean(values)
        stdev = statistics.stdev(values) if len(values) > 1 else 0.0
        print(f"{label:>28} | {mean:>10.1f} {stdev:>11.1f} {min(values):>9.1f} {max(values):>9.1f}")
    print()
    print(f"Saved: {paths['pdf']}")
    print(f"Saved: {paths['jpg']}")
# Rashed-Step 15.G-09-18-2026-end
