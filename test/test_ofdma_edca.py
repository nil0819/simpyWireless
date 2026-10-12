# Rashed-Step 21.C-10-11-2026-start
"""
Step 21.C tests: OFDMA with EDCA access (per-AC contention, the winning
AC's packets on the RUs within its TXOP limit) and MU EDCA for STAs.
"""

import contextlib
import io
import logging
import os
import statistics
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from click.testing import CliRunner

import simulation
from common.packet import TrafficConfig
from nru.nru import Config_NR
from singleRun import single_run
from wifi import ofdma
from wifi.wifi import Config

HE = dict(phy="he", channel_width_mhz=20, mcs=7, ampdu_max_mpdus=16)


def _run(cfg, n=8, traffic=None, uplink=False, sta_traffic=None, t=0.5):
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
            simulation.run_simulation(1, 0, 1, t, cfg, Config_NR(), backoffs, {}, {}, {}, {}, False,
                                      ap_positions=[(0.0, 0.0)], sta_radius=10.0, wifi_stas_per_ap=n,
                                      wifi_traffic_config=traffic, wifi_sta_uplink_enabled=uplink,
                                      wifi_sta_traffic_config=sta_traffic)
    finally:
        simulation.WiFi = orig
        logging.disable(logging.NOTSET)
    return aps[0]


def _lat(ap, cls):
    d = [p for p in ap.packet_log if p.status == "DELIVERED" and p.traffic_class == cls]
    return statistics.mean(p.delivered_at - p.created_at for p in d)


def test_edca_access_gives_voice_priority_on_the_rus():
    tr = TrafficConfig(mode="poisson", arrival_rate_pps=4000.0, traffic_class_mix={"voice": 0.2, "best_effort": 0.8})
    dcf = _run(Config(**HE, ofdma=True), traffic=tr)
    edca = _run(Config(**HE, ofdma=True, qos_enabled=True), traffic=tr)
    assert abs(_lat(dcf, "voice") - _lat(dcf, "best_effort")) < 0.3 * _lat(dcf, "best_effort")
    assert _lat(edca, "voice") < 0.6 * _lat(edca, "best_effort")
    d = [p for p in edca.packet_log if p.status == "DELIVERED"]
    assert len(d) == len({p.packet_id for p in d}) and len(d) > 0.9 * 4000 * 0.5 * 0.9


def test_each_mu_ppdu_carries_one_access_category_within_its_txop():
    seen = []
    orig = ofdma._fill

    def spy(take, put_back, per, budget, max_mpdus, pending):
        mp, used = orig(take, put_back, per, budget, max_mpdus, pending)
        seen.append(({p.traffic_class for p in mp}, budget))
        return mp, used
    ofdma._fill = spy
    try:
        _run(Config(**HE, ofdma=True, qos_enabled=True), t=0.2)        # saturated: all ACs backlogged
    finally:
        ofdma._fill = orig
    classes = [c for c, _ in seen if c]
    assert classes and all(len(c) == 1 for c in classes)
    voice_budgets = {b for c, b in seen if c == {"voice"}}
    assert voice_budgets and max(voice_budgets) <= 1504.0


def test_mu_edca_lets_triggered_stas_contend_with_worse_parameters():
    base = dict(HE, ofdma=True, ul_ofdma=True, mac_exchange=True)
    kw = dict(traffic=TrafficConfig(mode="poisson", arrival_rate_pps=500.0), uplink=True,
              sta_traffic=TrafficConfig(mode="poisson", arrival_rate_pps=300.0))
    trig_only = _run(Config(**base), **kw)
    mu = _run(Config(**base, mu_edca=ofdma.MuEdcaParams()), **kw)
    assert all(s.succeeded_transmissions + s.failed_transmissions == 0 for s in trig_only.sta_list)
    own = sum(s.succeeded_transmissions + s.failed_transmissions for s in mu.sta_list)
    under_mu = sum(getattr(s, "mu_edca_accesses", 0) for s in mu.sta_list)
    assert own > 0 and 0 < under_mu <= own
    assert mu.ofdma_stats["ul_rounds"] > 0
    ul = [p for s in mu.sta_list for p in s.packet_log if p.status == "DELIVERED"]
    assert len(ul) == len({p.packet_id for p in ul}) > 0.9 * 8 * 300 * 0.5 * 0.9


def test_cli():
    base = ["--ap-number", "1", "--gnb-number", "0", "--seed", "1", "-t", "0.1", "-r", "1", "--wifi-phy", "he",
            "--wifi-ofdma", "--wifi-stas-per-ap", "4"]
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("log", exist_ok=True)
        on = runner.invoke(single_run, base + ["--wifi-edca", "--wifi-sta-uplink-enabled", "--wifi-ul-ofdma",
                                               "--wifi-mu-edca"])
        bad = runner.invoke(single_run, base + ["--wifi-mu-edca"])
    assert on.exit_code == 0, on.output[-400:]
    assert "Wifi MU EDCA: STA own-contention frames" in on.output
    assert bad.exit_code != 0
# Rashed-Step 21.C-10-11-2026-end
