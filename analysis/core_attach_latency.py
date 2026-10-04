# Rashed-Step 16.G-10-04-2026-start
"""
Figure: full attach latency (RRC setup -> 5G Core registration -> PDU
session establishment) as stacked bars, one per scenario - Step 16.G
(Project details/Step 16.txt).

Same three scenarios, distance (10m), and seeds as analysis/
rrc_connection_setup_latency.py, so the two figures line up: that one
zooms into the RRC slice, this one shows it in context of the whole
attach. Every number comes from live runs through the real
RrcLayer/CoreNetwork machinery (CoreNetwork.start_ue() at t=0), not
hard-coded:

  Licensed NR (grant-based RRC), NR-U on an idle channel (gNB downlink
  silenced, isolated LBT), NR-U with the gNB's own saturated downlink
  (Step 15.C's self-collision case).

Per UE: RRC = rrc_connected_at - rrc_attach_started_at, registration =
registered_at - reg_requested_at, PDU session = activated_at -
requested_at. The three are back to back with no gaps (ue_attach chains
them on the same tick), which generate() asserts, so the bar height is
exactly the attach latency compute_pdu_session_stats() reports.

EXPECTED SHAPE: the Core stages are fixed configurable delays (90ms +
125ms, measured Open5GS testbed defaults - see core/network.py), so
they dominate and are identical across scenarios; only the RRC slice
differs (4ms licensed, ~5.6ms / ~14.6ms NR-U). That is the honest
picture at these defaults: radio access is a few percent of the attach
time, the Core is the rest.

Run standalone from the repo root: `python -m analysis.core_attach_latency`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import random
import statistics

import simpy

from channel.channel import Channel
from core.network import CoreNetwork, CoreConfig
from core.procedures import compute_pdu_session_stats

from nru.nru import Gnb, Config_NR
from nru.ue import NrUE

from nr.nr import GnbLicensedNR, Config_NRL
from nr.ue import NrUeLicensed

from analysis.plot_utils import save_stacked_bar_figure

SEEDS = list(range(1, 21))  # same as rrc_connection_setup_latency.py
UE_POS = (10.0, 0.0)
GNB_POS = (0.0, 0.0)
# Default attach is ~215ms + RRC (<= ~16ms here); leave headroom.
RUN_UNTIL_US = 400_000.0

SCENARIOS = [
    ("licensed", "Licensed NR\n(grant-based)"),
    ("nru_isolated", "NR-U\n(isolated LBT)"),
    ("nru_collision", "NR-U\n(gNB self-collision)"),
]


def _make_channel(env):
    return Channel(
        tx_queue=simpy.PriorityResource(env, capacity=1),
        tx_lock=simpy.Resource(env, capacity=1),
        n_of_stations=0, n_of_gNB=1, backoffs={},
        airtime_data={}, airtime_control={},
        airtime_data_NR={}, airtime_control_NR={},
    )


class _NoAutoStartGnb(Gnb):
    """Silences only the gNB's own downlink - same isolation technique as
    rrc_connection_setup_latency.py / test_nru_uplink.py."""
    def start(self):
        return
        yield  # pragma: no cover


def _stages_us(scenario: str, seed: int, core_config: CoreConfig = None):
    """(rrc, registration, pdu_session) in us for one UE, one seed."""
    random.seed(seed)
    env = simpy.Environment()
    channel = _make_channel(env)
    if scenario == "licensed":
        cfg = Config_NRL(tdd_enabled=True)
        ue = NrUeLicensed(name="UE 1-1", pos=UE_POS, gnb_name="G1",
                          env=env, config=cfg, uplink_enabled=True, rrc_enabled=True)
        gnb = GnbLicensedNR(env, "G1", channel, GNB_POS, [ue], cfg)
    else:
        cfg = Config_NR()
        ue = NrUE(name="UE 1-1", pos=UE_POS, gnb_name="G1",
                  env=env, channel=channel, config_nr=cfg,
                  uplink_enabled=True, rrc_enabled=True)
        gnb_cls = _NoAutoStartGnb if scenario == "nru_isolated" else Gnb
        gnb = gnb_cls(env, "G1", channel, GNB_POS, [ue], cfg)

    CoreNetwork(env, core_config).start_ue(gnb, ue)
    env.run(until=RUN_UNTIL_US)

    stats = compute_pdu_session_stats([ue])
    assert stats["active"] == 1, f"{scenario} seed {seed}: session not ACTIVE within {RUN_UNTIL_US}us"
    rrc = ue.rrc_connected_at - ue.rrc_attach_started_at
    reg = ue.registered_at - ue.reg_requested_at
    pdu = ue.pdu_session.activated_at - ue.pdu_session.requested_at
    # Back to back: the bar height must equal the reported attach latency.
    assert abs((rrc + reg + pdu) - stats["attach_latencies_us"][0]) < 1e-6, (scenario, seed)
    return rrc, reg, pdu


def generate(seeds=SEEDS, core_config: CoreConfig = None):
    results = {}
    for key, _ in SCENARIOS:
        rows = [_stages_us(key, s, core_config) for s in seeds]
        results[key] = {
            "rrc_us": [r[0] for r in rows],
            "registration_us": [r[1] for r in rows],
            "pdu_session_us": [r[2] for r in rows],
            "total_us": [sum(r) for r in rows],
        }

    def mean_ms(key, field):
        return statistics.mean(results[key][field]) / 1000.0

    paths = save_stacked_bar_figure(
        categories=[label for _, label in SCENARIOS],
        stacks={
            "RRC setup":    [mean_ms(k, "rrc_us") for k, _ in SCENARIOS],
            "Registration": [mean_ms(k, "registration_us") for k, _ in SCENARIOS],
            "PDU session":  [mean_ms(k, "pdu_session_us") for k, _ in SCENARIOS],
        },
        xlabel="Scenario",
        ylabel="Attach latency (ms)",
        output_stem="core_attach_latency",
    )
    return results, paths


if __name__ == "__main__":
    results, paths = generate()
    print(f"{'scenario':>28} | {'RRC (ms)':>9} {'reg (ms)':>9} {'PDU (ms)':>9} {'total (ms)':>11} {'RRC share':>10}")
    print("-" * 86)
    for key, label in SCENARIOS:
        r = results[key]
        rrc = statistics.mean(r["rrc_us"]) / 1000.0
        reg = statistics.mean(r["registration_us"]) / 1000.0
        pdu = statistics.mean(r["pdu_session_us"]) / 1000.0
        total = statistics.mean(r["total_us"]) / 1000.0
        print(f"{label.replace(chr(10), ' '):>28} | {rrc:>9.2f} {reg:>9.2f} {pdu:>9.2f} {total:>11.2f} {rrc / total:>9.1%}")
    print()
    print(f"Saved: {paths['pdf']}")
    print(f"Saved: {paths['jpg']}")
# Rashed-Step 16.G-10-04-2026-end
