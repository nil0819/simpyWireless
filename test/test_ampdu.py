# Rashed-Step pre_20.B-10-08-2026-start
"""
Step pre_20.B tests: Wi-Fi A-MPDU aggregation (Config.ampdu_max_mpdus,
AP downlink on the DCF path).
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
from nru.nru import Config_NR
from singleRun import single_run
from wifi.wifi import Config


def _run(wifi_cfg, n_gnb=0, gnb_at=40.0, traffic=None, t=0.5, seed=1):
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
            fair = simulation.run_simulation(1, n_gnb, seed, t, wifi_cfg, Config_NR(), backoffs, {}, {}, {}, {}, False,
                                             ap_positions=[(0.0, 0.0)], gnb_positions=[(gnb_at, 0.0)], sta_radius=5.0,
                                             wifi_traffic_config=traffic, fairness_report=True)
    finally:
        simulation.WiFi = orig
        logging.disable(logging.NOTSET)
    return aps[0], fair


def test_ppdu_is_capped_by_the_max_ppdu_time():
    ap, fair = _run(Config(ampdu_max_mpdus=64))
    st = ap.ampdu_stats
    # 1472-byte MSDUs at MCS 7: ~225 us each -> 24 fit in 5.484 ms.
    assert st["mpdus"] / st["ppdus"] == 24
    header_us, per_mpdu = ap._ampdu_times()
    assert header_us + 24 * per_mpdu(1472) <= 5484 < header_us + 25 * per_mpdu(1472)


def test_aggregation_raises_saturated_throughput():
    single = _run(Config())[1]["tech"]["WiFi"]["throughput_mbps"]
    agg_ap, agg = _run(Config(ampdu_max_mpdus=32))
    assert agg["tech"]["WiFi"]["throughput_mbps"] > 1.5 * single
    assert agg_ap.ampdu_stats["mpdus_ok"] == agg_ap.ampdu_stats["mpdus"]   # nothing else on the air


def test_partial_losses_are_retried_per_mpdu():
    # An NR-U gNB 40 m away that Wi-Fi can't hear: some MPDUs (or whole
    # PPDUs) are hit, the rest of each PPDU still gets through.
    ap, _ = _run(Config(ampdu_max_mpdus=32), n_gnb=1, t=1.0)
    st = ap.ampdu_stats
    assert 0 < st["mpdus_ok"] < st["mpdus"]
    assert any(p.status == "DELIVERED" and p.retry_count > 0 for p in ap.packet_log)


def test_queued_traffic_aggregates_what_is_waiting():
    ap, fair = _run(Config(ampdu_max_mpdus=32), traffic=TrafficConfig(mode="poisson", arrival_rate_pps=3000.0))
    st = ap.ampdu_stats
    assert 1 < st["mpdus"] / st["ppdus"] < 24
    delivered = sum(1 for p in ap.packet_log if p.status == "DELIVERED")
    assert delivered > 0.95 * 3000 * 0.5 * 0.97          # ~all offered (bar the last PPDU)


def test_cli_default_unchanged_and_block_when_on():
    base = ["--ap-number", "1", "--gnb-number", "0", "--seed", "1", "-t", "0.05", "-r", "1"]
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("log", exist_ok=True)
        off = runner.invoke(single_run, base)
        on = runner.invoke(single_run, base + ["--wifi-ampdu", "16"])
    assert off.exit_code == 0 and on.exit_code == 0, (off.output[-300:], on.output[-300:])
    assert "A-MPDU" not in off.output and "=== Wi-Fi A-MPDU ===" in on.output
# Rashed-Step pre_20.B-10-08-2026-end
