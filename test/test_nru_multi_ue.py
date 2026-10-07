# Rashed-Step 18.D-10-06-2026-start
"""
Step 18.D tests: NR-U "slots" COTs shared by several UEs - downlink RBs
split max-min fair per slot, uplink windows on interlaces with Type 2A
run by all granted UEs before any transmits, per-UE uplink buffers.
"""

import contextlib
import io
import logging
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from click.testing import CliRunner

import simulation
from common.packet import TrafficConfig
from nru.nru import Config_NR, Gnb, NruUplinkAccessMode
from singleRun import single_run
from wifi.wifi import Config


def _run(n_ap=0, seed=1, t=0.5, cfg_nr=None, traffic=None, ues=1, **kw):
    logging.disable(logging.CRITICAL)
    gnbs = []
    orig = simulation.Gnb

    class Spy(orig):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            gnbs.append(self)

    simulation.Gnb = Spy
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            wifi = Config()
            backoffs = {k: {n_ap: 0} for k in range(wifi.cw_max + 1)}
            simulation.run_simulation(n_ap, 1, seed, t, wifi, cfg_nr or Config_NR(cot_model="slots"),
                                      backoffs, {}, {}, {}, {}, False, nru_traffic_config=traffic,
                                      nr_ues_per_gnb=ues, ue_radius=30.0, **kw)
    finally:
        simulation.Gnb = orig
        logging.disable(logging.NOTSET)
    return gnbs[0]


# ---------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------

def test_maxmin_rbs():
    assert Gnb._maxmin_rbs(51, {"a": 51, "b": 51, "c": 51}) == {"a": 17, "b": 17, "c": 17}
    assert Gnb._maxmin_rbs(51, {"a": 5, "b": 51, "c": 51}) == {"a": 5, "b": 23, "c": 23}
    assert Gnb._maxmin_rbs(51, {"a": 5, "b": 6}) == {"a": 5, "b": 6}
    assert sum(Gnb._maxmin_rbs(51, {"a": 100, "b": 100}).values()) == 51


def test_interlace_rbs_cover_the_carrier():
    g = _run(t=0.01)
    assert g.n_interlaces == 5
    assert [g._interlace_rbs([m]) for m in range(5)] == [11, 10, 10, 10, 10]
    assert g._interlace_rbs(list(range(5))) == g.total_rbs


# ---------------------------------------------------------------------
# downlink sharing
# ---------------------------------------------------------------------

def test_saturated_downlink_is_shared_by_every_ue_in_every_slot():
    g = _run(ues=3)
    ss = g.slot_stats
    per_ue = {ue.name: b.stats["delivered_bytes"] for ue, b in zip(g.ue_list, g.dl_buffers.values())}
    assert all(v > 0 for v in per_ue.values())
    # 3 TBs per slot.
    n_tb = ss["dl_tbs_ok"] + ss["dl_tbs_failed"]
    assert n_tb > 0 and n_tb % 3 == 0
    # Total close to one UE alone (same carrier, close-in UEs at top MCS);
    # integer RB split (17 x 3) uses the whole carrier.
    alone = _run(ues=1).slot_stats["dl_bits"]
    assert 0.9 * alone < ss["dl_bits"] <= alone * 1.01


def test_buffered_downlink_serves_small_and_large_queues_together():
    g = _run(ues=2, traffic=TrafficConfig(mode="cbr", arrival_rate_pps=2000.0))
    for b in g.dl_buffers.values():
        assert b.stats["enqueued_packets"] == 499
        assert b.stats["delivered_packets"] >= 497


# ---------------------------------------------------------------------
# uplink on interlaces
# ---------------------------------------------------------------------

def _ul_cfg(**kw):
    return Config_NR(cot_model="slots", ul_access_mode=NruUplinkAccessMode.COT_SHARING, **kw)


def test_two_uplink_ues_send_together_without_blocking_each_other():
    g = _run(ues=2, cfg_nr=_ul_cfg(), nru_ue_uplink_enabled=True)
    ss = g.slot_stats
    assert ss["ul_type2a_skips"] == 0
    assert ss["ul_tbs_failed"] == 0  # same-cell UEs don't interfere
    assert all(w["granted"] and len(w["granted"]) == 2 for w in g.ul_windows)
    for ue in g.ue_list:
        assert ue.ul_buffer.stats["delivered_bytes"] > 0
        assert any(p.status == "DELIVERED" for p in ue.packet_log)


def test_at_most_n_interlaces_ues_per_window_round_robin():
    g = _run(ues=7, cfg_nr=_ul_cfg(), nru_ue_uplink_enabled=True, t=0.2)
    assert all(len(w["granted"]) == 5 for w in g.ul_windows)
    w0, w1 = g.ul_windows[0]["granted"], g.ul_windows[1]["granted"]
    assert w0 == ["UE 1-1", "UE 1-2", "UE 1-3", "UE 1-4", "UE 1-5"]
    assert w1 == ["UE 1-6", "UE 1-7", "UE 1-1", "UE 1-2", "UE 1-3"]
    assert all(ue.ul_buffer.stats["delivered_bytes"] > 0 for ue in g.ue_list)


def test_buffered_uplink_and_downlink():
    cfg = _ul_cfg(ul_traffic=TrafficConfig(mode="cbr", arrival_rate_pps=200.0))
    g = _run(ues=2, cfg_nr=cfg, traffic=TrafficConfig(mode="cbr", arrival_rate_pps=400.0),
             nru_ue_uplink_enabled=True)
    for ue in g.ue_list:
        assert ue.ul_buffer.stats["enqueued_packets"] == 99
        assert ue.ul_buffer.stats["delivered_packets"] >= 97
        assert g.dl_buffers[ue.name].stats["delivered_packets"] >= 97


def test_idle_uplink_ues_get_no_window():
    cfg = _ul_cfg(ul_traffic=TrafficConfig(mode="cbr", arrival_rate_pps=4.0))  # one arrival, at 250 ms
    g = _run(ues=1, cfg_nr=cfg, traffic=TrafficConfig(mode="cbr", arrival_rate_pps=100.0),
             nru_ue_uplink_enabled=True)
    assert len(g.ul_windows) == 1


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------

BASE = ["--ap-number", "0", "--gnb-number", "1", "--seed", "1", "-r", "1", "-t", "0.1"]


def _cli(args):
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("log", exist_ok=True)
        return runner.invoke(single_run, args)


def test_cli_uplink_slot_lines_and_validation():
    r = _cli(BASE + ["--nru-cot-model", "slots", "--nru-ue-uplink-enabled",
                     "--nru-ul-traffic-model", "cbr", "--nru-ul-arrival-rate-pps", "300"])
    assert r.exit_code == 0, (r.output, r.exception)
    assert "NRU UL TBs ok/failed:" in r.output and "NRU UL grants:" in r.output
    r = _cli(BASE + ["--nru-ul-traffic-model", "cbr", "--nru-ue-uplink-enabled"])
    assert r.exit_code != 0 and "requires --nru-cot-model slots" in r.output
    r = _cli(BASE + ["--nru-cot-model", "slots", "--nru-ul-traffic-model", "cbr"])
    assert r.exit_code != 0 and "requires --nru-ue-uplink-enabled" in r.output
    r = _cli(BASE + ["--nru-cot-model", "slots", "--nru-ul-arrival-rate-pps", "5"])
    assert r.exit_code != 0 and "requires --nru-ul-traffic-model poisson or cbr" in r.output
# Rashed-Step 18.D-10-06-2026-end
