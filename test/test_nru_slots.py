# Rashed-Step 18.C-10-06-2026-start
"""
Step 18.C tests: NR-U COT made of slots (Config_NR.cot_model="slots",
singleRun.py --nru-cot-model slots), the channel's per-window SINR, and
NR-U per-UE downlink buffers.
"""

import contextlib
import io
import logging
import os
import re
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import simpy
from click.testing import CliRunner

import simulation
from channel.channel import ActiveTx, Channel
from common.packet import Packet, TrafficConfig
from nr.nr import NR_MCS_TABLE
from nru.nru import Config_NR, NruUplinkAccessMode
from ran.protocol.buffer import ByteBuffer
from singleRun import single_run
from wifi.wifi import Config


def _expect_value_error(fn, needle):
    try:
        fn()
    except ValueError as e:
        assert needle in str(e)
    else:
        assert False, "expected ValueError"


# ---------------------------------------------------------------------
# building blocks
# ---------------------------------------------------------------------

def _channel():
    env = simpy.Environment()
    return Channel(simpy.PriorityResource(env, capacity=1), simpy.Resource(env, capacity=1),
                   0, 1, {}, {}, {}, {}, {})


def _tx(name, pos, start, end, tech="NRU"):
    return ActiveTx(tx_id=name, tx_pos=pos, tx_start=start, rx_pos=(0.0, 0.0), tx_power_dbm=20.0,
                    f_hz=5.18e9, pl_exp=3.0, t_end=end, tech=tech, bandwidth_mhz=20.0)


def test_sinr_window_only_counts_interference_inside_it():
    ch = _channel()
    burst = _tx("gnb", (10.0, 0.0), 0, 3000)
    hit = _tx("ap", (12.0, 0.0), 1000, 1500, tech="WiFi")  # covers slot 2 (1000-1500) only
    ch.register_tx(burst)
    ch.register_tx(hit)
    clean = ch.sinr_db(burst, window=(0, 500))
    hit_slot = ch.sinr_db(burst, window=(1000, 1500))
    half = ch.sinr_db(burst, window=(1250, 1750))
    assert hit_slot < clean - 20          # the slot the frame landed on
    assert hit_slot < half < clean        # half-covered window: in between
    # No window = the whole burst, unchanged rule (1/6 of it covered).
    assert ch.sinr_db(burst) == ch.sinr_db(burst, window=(0, 3000))


def test_buffer_on_enqueue_callback():
    calls = []
    b = ByteBuffer(limit_bytes=1500, on_enqueue=lambda: calls.append(1))
    p = lambda i: Packet(packet_id=str(i), source="g", destination="u", payload_bytes=1000, header_bytes=0)
    b.enqueue(p(0))
    b.enqueue(p(1))  # over the limit: dropped, no callback
    assert calls == [1]


def test_config_validation():
    _expect_value_error(lambda: Config_NR(cot_model="frames"), "cot_model must be one of")
    _expect_value_error(lambda: Config_NR(cot_model="slots", numerology=7), "numerology must be one of")
    assert Config_NR().cot_model == "burst"


# ---------------------------------------------------------------------
# whole runs
# ---------------------------------------------------------------------

def _run(n_ap=0, n_gnb=1, seed=1, t=0.5, cfg_nr=None, traffic=None, ues=1, **kw):
    """run_simulation with a spy on the gNBs; returns (gnbs, channel)."""
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
            backoffs = {k: {n_ap: 0} for k in range(wifi.cw_max + 1)}  # as singleRun.py builds it
            simulation.run_simulation(n_ap, n_gnb, seed, t, wifi, cfg_nr or Config_NR(cot_model="slots"),
                                      backoffs, {}, {}, {}, {}, False, nru_traffic_config=traffic,
                                      nr_ues_per_gnb=ues, **kw)
    finally:
        simulation.Gnb = orig
        logging.disable(logging.NOTSET)
    return gnbs


def test_saturated_alone_matches_the_capacity_formula_and_burst_footprint():
    g = _run()[0]
    ss = g.slot_stats
    assert g.total_rbs == 51 and g.slot_us == 500.0
    assert ss["dl_tbs_failed"] == 0 and ss["cots_failed"] == 0
    # Every COT is 6 ms = 12 slots of downlink (no uplink sharing here).
    # (the run can end inside the last COT)
    assert 12 * (ss["cots"] - 1) < ss["dl_tbs_ok"] <= 12 * ss["cots"]
    assert ss["dl_mcs_sum"] / ss["dl_tbs_ok"] == 15  # 7 m link: top MCS
    per_slot_bits = (NR_MCS_TABLE[15][1] * 51 * 12 * 30e3 * 500e-6) // 8 * 8
    assert ss["dl_bits"] == per_slot_bits * ss["dl_tbs_ok"]
    burst = _run(cfg_nr=Config_NR())[0]
    # Same channel occupancy as the burst model.
    assert g.channel.airtime_data_NR[g.name] == burst.channel.airtime_data_NR[burst.name]


def test_light_buffered_load_shortens_cots_and_delivers_everything():
    g = _run(traffic=TrafficConfig(mode="cbr", arrival_rate_pps=200.0))[0]
    st = g.dl_buffers[g.ue_list[0].name].stats
    assert st["enqueued_packets"] == 99
    assert st["delivered_packets"] >= 98
    # One packet per COT needs one slot, not 12.
    assert g.slot_stats["dl_tbs_ok"] + g.slot_stats["dl_tbs_failed"] <= g.slot_stats["cots"] + 1
    assert g.channel.airtime_data_NR[g.name] < 0.1 * 0.5e6


def test_idle_gnb_does_not_contend():
    g = _run(traffic=TrafficConfig(mode="cbr", arrival_rate_pps=4.0))[0]  # one arrival at 250 ms
    assert g.slot_stats["cots"] == 1


def test_arrival_rate_is_a_per_gnb_total_split_over_ues():
    g = _run(traffic=TrafficConfig(mode="cbr", arrival_rate_pps=400.0), ues=2)[0]
    per_ue = [b.stats["enqueued_packets"] for b in g.dl_buffers.values()]
    assert per_ue == [99, 99]  # 200 pkt/s each
    assert all(b.stats["delivered_packets"] >= 97 for b in g.dl_buffers.values())


def test_wifi_interference_fails_individual_slots_not_whole_cots():
    g = _run(n_ap=1, seed=1, t=1.0)[0]
    ss = g.slot_stats
    assert ss["dl_tbs_failed"] > 0
    assert ss["dl_tbs_ok"] > 5 * ss["dl_tbs_failed"]
    # Failed COTs are exactly the ones whose first (reference) slot failed.
    assert g.channel.failed_transmissions_NR == ss["cots_failed"]


def test_rrc_and_cot_sharing_complete_with_buffered_traffic():
    cfg = Config_NR(cot_model="slots", ul_access_mode=NruUplinkAccessMode.COT_SHARING)
    g = _run(t=0.3, cfg_nr=cfg, traffic=TrafficConfig(mode="cbr", arrival_rate_pps=100.0),
             nru_ue_uplink_enabled=True, nru_rrc_enabled=True)[0]
    ue = g.ue_list[0]
    assert ue.rrc_state.name == "CONNECTED"
    assert g.dl_buffers[ue.name].stats["delivered_packets"] > 0


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------

BASE = ["--ap-number", "1", "--gnb-number", "1", "--seed", "1", "-r", "1", "-t", "0.1"]


def _cli(args):
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("log", exist_ok=True)
        return runner.invoke(single_run, args)


def test_cli_slots_block_only_with_slots():
    r = _cli(BASE)
    assert r.exit_code == 0, (r.output, r.exception)
    assert "=== NR-U Slots ===" not in r.output
    r = _cli(BASE + ["--nru-cot-model", "slots", "--nru-traffic-model", "poisson", "--nru-arrival-rate-pps", "500"])
    assert r.exit_code == 0, (r.output, r.exception)
    assert "=== NR-U Slots ===" in r.output and "=== NR-U DL Traffic ===" in r.output
    assert re.search(r"RBs=51 in 20.0 MHz", r.output)


def test_cli_rejects_slot_flags_without_slots():
    r = _cli(BASE + ["--nru-numerology", "0"])
    assert r.exit_code != 0 and "require --nru-cot-model slots" in r.output
    r = _cli(BASE + ["--nru-cot-model", "slots", "--nru-numerology", "0"])
    assert r.exit_code == 0, (r.output, r.exception)
    assert "slot=1000.0 us" in r.output
# Rashed-Step 18.C-10-06-2026-end
