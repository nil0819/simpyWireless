# Rashed-Step 20.B-10-08-2026-start
"""
Step 20.B tests: Wi-Fi STA uplink with poisson/cbr queues, EDCA with
arrival-driven per-AC queues, and A-MPDU on EDCA (per-AC TXOP limits) and
STA uplink (wifi/ampdu.py).
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
from common.packet import Packet, TrafficConfig
from nru.nru import Config_NR
from singleRun import single_run
from wifi import ampdu
from wifi.wifi import Config


def _run(cfg, traffic=None, sta_traffic=None, uplink=False, t=0.5, seed=1):
    logging.disable(logging.CRITICAL)
    aps = []
    orig = simulation.WiFi

    class Spy(orig):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            aps.append(self)

    simulation.WiFi = Spy
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            backoffs = {k: {1: 0} for k in range(1024)}
            simulation.run_simulation(1, 0, seed, t, cfg, Config_NR(), backoffs, {}, {}, {}, {}, False,
                                      ap_positions=[(0.0, 0.0)], sta_radius=3.0, wifi_traffic_config=traffic,
                                      wifi_sta_uplink_enabled=uplink, wifi_sta_traffic_config=sta_traffic)
    finally:
        simulation.WiFi = orig
        logging.disable(logging.NOTSET)
    return aps[0]


def _delivered(log):
    return [p for p in log if p.status == "DELIVERED"]


def test_sta_poisson_uplink_carries_the_offered_load():
    ap = _run(Config(), traffic=TrafficConfig(mode="poisson", arrival_rate_pps=200.0), uplink=True,
              sta_traffic=TrafficConfig(mode="poisson", arrival_rate_pps=400.0))
    sta = ap.sta_list[0]
    ul = _delivered(sta.packet_log)
    assert 0.8 * 400 * 0.5 < len(ul) <= 1.2 * 400 * 0.5            # ~200 offered in 0.5 s
    assert all(p.source == sta.name and p.destination == ap.name for p in ul)
    assert max(p.delivered_at - p.created_at for p in ul) < 20000   # light load: no backlog


def test_sta_poisson_retry_exhaustion_takes_the_next_queued_packet():
    # Every uplink frame fails (impossible SINR threshold): packets are
    # dropped after r_limit retries and the STA moves on to queued ones
    # instead of synthesizing new packets.
    ap = _run(Config(wifi_sinr_thr_db_override=200.0), uplink=True,
              sta_traffic=TrafficConfig(mode="cbr", arrival_rate_pps=100.0), t=0.5)
    sta = ap.sta_list[0]
    dropped = [p for p in sta.packet_log if p.status == "DROPPED"]
    assert dropped and len(dropped) <= 50                           # at most what arrived (cbr 100 pps x 0.5 s)
    assert all(p.retry_count > Config().r_limit for p in dropped)


def test_edca_queued_only_backlogged_acs_contend_and_voice_is_faster():
    mix = {"voice": 0.3, "best_effort": 0.7}
    ap = _run(Config(qos_enabled=True), traffic=TrafficConfig(mode="poisson", arrival_rate_pps=3500.0,
                                                               traffic_class_mix=mix))
    d = _delivered(ap.packet_log)
    by = {c: [p.delivered_at - p.created_at for p in d if p.traffic_class == c] for c in mix}
    assert by["voice"] and by["best_effort"]
    assert not any(p.traffic_class in ("video", "background") for p in ap.packet_log)
    assert sum(by["voice"]) / len(by["voice"]) < sum(by["best_effort"]) / len(by["best_effort"])
    assert ap.ac_frame_to_send["video"] is None and ap.ac_frame_to_send["background"] is None


def test_edca_light_load_delivers_everything():
    ap = _run(Config(qos_enabled=True), traffic=TrafficConfig(mode="poisson", arrival_rate_pps=300.0))
    queued = sum(len(q) for q in ap.ac_queue.values())
    assert len(_delivered(ap.packet_log)) + queued >= 0.8 * 300 * 0.5
    assert queued <= 2


def test_txop_limits_bound_the_ppdu():
    cfg = Config(ampdu_max_mpdus=64)
    node = type("N", (), {"config": cfg})()
    assert ampdu.ppdu_budget_us(node, "voice") == 1504.0
    assert ampdu.ppdu_budget_us(node, "video") == 3008.0
    assert ampdu.ppdu_budget_us(node, "best_effort") == 5484.0 == ampdu.ppdu_budget_us(node)
    per = lambda b: 225.0
    take = iter([Packet(packet_id=f"p{i}", source="a", destination="b", payload_bytes=1472, header_bytes=40,
                        created_at=0.0) for i in range(64)])
    mpdus = ampdu.build([], lambda: next(take, None), lambda p: None, 20.0, per, 64, 1504.0)
    assert len(mpdus) == 6                                           # 20 + 6 x 225 <= 1504 < 20 + 7 x 225


def test_edca_aggregates_per_access_category():
    ap = _run(Config(qos_enabled=True, ampdu_max_mpdus=32))
    st = ap.ampdu_stats
    assert st["ppdus"] > 0 and 1 < st["mpdus"] / st["ppdus"] < 24
    d = _delivered(ap.packet_log)
    assert {p.traffic_class for p in d} >= {"voice", "video"}
    assert len(d) == len({p.packet_id for p in d})


def test_sta_uplink_aggregates():
    ap = _run(Config(ampdu_max_mpdus=16), traffic=TrafficConfig(mode="poisson", arrival_rate_pps=200.0), uplink=True,
              sta_traffic=TrafficConfig(mode="poisson", arrival_rate_pps=3000.0))
    sta = ap.sta_list[0]
    assert sta.ampdu_stats["ppdus"] > 0 and sta.ampdu_stats["mpdus"] / sta.ampdu_stats["ppdus"] > 2
    assert len(_delivered(sta.packet_log)) > 0.9 * 3000 * 0.5 * 0.9


def test_cli():
    base = ["--ap-number", "1", "--gnb-number", "0", "--seed", "1", "-t", "0.05", "-r", "1"]
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("log", exist_ok=True)
        ok1 = runner.invoke(single_run, base + ["--wifi-edca", "--wifi-traffic-model", "poisson", "--wifi-arrival-rate-pps", "500"])
        ok2 = runner.invoke(single_run, base + ["--wifi-sta-uplink-enabled", "--wifi-sta-traffic-model", "cbr",
                                                "--wifi-sta-arrival-rate-pps", "200", "--wifi-ampdu", "8"])
        bad = runner.invoke(single_run, base + ["--wifi-sta-traffic-model", "poisson"])
    assert ok1.exit_code == 0 and ok2.exit_code == 0, (ok1.output[-300:], ok2.output[-300:])
    assert "Wifi uplink A-MPDU PPDUs:" in ok2.output
    assert bad.exit_code != 0
# Rashed-Step 20.B-10-08-2026-end
