# Rashed-Step 20.E-10-09-2026-start
"""
Step 20.E tests: 802.11ax OFDMA (wifi/ofdma.py) - RU plans and rates,
validation, downlink MU PPDUs on resource units, trigger-based uplink,
OFDMA with association (20.D), CLI.
"""

import contextlib
import io
import logging
import math
import os
import statistics
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest
from click.testing import CliRunner

import simulation
from common.packet import TrafficConfig
from nru.nru import Config_NR
from singleRun import single_run
from wifi import ofdma
from wifi.mgmt import MgmtConfig
from wifi.wifi import Config

HE = dict(phy="he", channel_width_mhz=20, mcs=7, ampdu_max_mpdus=16)


def _run(cfg, n_sta, traffic=None, uplink=False, sta_traffic=None, t=0.5, seed=1, spy_channel=None):
    logging.disable(logging.CRITICAL)
    aps, regs = [], []
    orig_w, orig_reg = simulation.WiFi, simulation.Channel.register_tx

    class Spy(orig_w):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            aps.append(self)

    def reg(ch, tx):
        regs.append(tx)
        return orig_reg(ch, tx)

    simulation.WiFi = Spy
    if spy_channel:
        simulation.Channel.register_tx = reg
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            backoffs = {k: {1: 0} for k in range(1024)}
            simulation.run_simulation(1, 0, seed, t, cfg, Config_NR(), backoffs, {}, {}, {}, {}, False,
                                      ap_positions=[(0.0, 0.0)], sta_radius=10.0, wifi_stas_per_ap=n_sta,
                                      wifi_traffic_config=traffic, wifi_sta_uplink_enabled=uplink,
                                      wifi_sta_traffic_config=sta_traffic)
    finally:
        simulation.WiFi = orig_w
        simulation.Channel.register_tx = orig_reg
        logging.disable(logging.NOTSET)
    return aps[0], regs


def test_ru_plan_and_rates():
    assert [t for t, _, _ in ofdma.ru_plan(20, 1)] == [242]
    assert [t for t, _, _ in ofdma.ru_plan(20, 2)] == [106, 106]
    assert [t for t, _, _ in ofdma.ru_plan(20, 4)] == [52] * 4
    assert [t for t, _, _ in ofdma.ru_plan(20, 9)] == [26] * 9
    assert [t for t, _, _ in ofdma.ru_plan(80, 3)] == [242] * 3
    for width in (20, 40, 80):
        for n in (1, 2, 5, 9):
            plan = ofdma.ru_plan(width, n)
            edges = sorted((off - bw * 1e6 / 2, off + bw * 1e6 / 2) for _, off, bw in plan)
            assert edges[0][0] >= -width * 1e6 / 2 and edges[-1][1] <= width * 1e6 / 2      # inside the channel
            assert all(a[1] <= b[0] for a, b in zip(edges, edges[1:]))                     # no overlap
    assert ofdma.ru_rate_mbps(242, 11, 800) == pytest.approx(143.4, abs=0.1)              # = HE20 MCS 11
    assert ofdma.ru_rate_mbps(26, 0, 800) == pytest.approx(24 * 0.5 / 13.6)


def test_validation():
    with pytest.raises(ValueError):
        Config(ofdma=True)                                  # needs HE
    with pytest.raises(ValueError):
        Config(**HE, ul_ofdma=True)                          # needs ofdma
    with pytest.raises(ValueError):
        Config(**HE, ofdma=True, qos_enabled=True)
    assert Config().ofdma is False


def test_saturated_downlink_serves_all_users_on_rus():
    ap, regs = _run(Config(**HE, ofdma=True, ofdma_max_users=9), 9, t=0.2, spy_channel=True)
    st = ap.ofdma_stats
    assert st["dl_ppdus"] > 0 and st["dl_users"] == 9 * st["dl_ppdus"]
    assert set(st["ru_tones"]) == {26} and st["dl_mpdus_ok"] == st["dl_mpdus"]       # users don't interfere
    dests = {p.destination for p in ap.packet_log if p.status == "DELIVERED"}
    assert dests == {s.name for s in ap.sta_list}
    ru_txs = [t for t in regs if t.tx_id == ap.name and t.bandwidth_mhz < 3.0]
    assert ru_txs and all(t.tx_power_dbm == pytest.approx(20.0 + 10 * math.log10(26 / 242)) for t in ru_txs)
    assert len({t.f_hz for t in ru_txs}) == 9


def test_poisson_downlink_delivers_the_offered_load():
    ap, _ = _run(Config(**HE, ofdma=True), 6, traffic=TrafficConfig(mode="poisson", arrival_rate_pps=1500.0))
    delivered = [p for p in ap.packet_log if p.status == "DELIVERED"]
    assert len(delivered) > 0.9 * 1500 * 0.5 * 0.95
    assert len(delivered) == len({p.packet_id for p in delivered})


def test_trigger_based_uplink_replaces_contention():
    def ul(cfg):
        ap, _ = _run(cfg, 9, traffic=TrafficConfig(mode="poisson", arrival_rate_pps=50.0, packet_size_bytes=300),
                     uplink=True, sta_traffic=TrafficConfig(mode="poisson", arrival_rate_pps=1500.0, packet_size_bytes=300))
        d = [p for s in ap.sta_list for p in s.packet_log if p.status == "DELIVERED"]
        return ap, len(d), statistics.mean(p.delivered_at - p.created_at for p in d)
    base = dict(HE, mac_exchange=True)
    ap_su, n_su, lat_su = ul(Config(**base))
    ap_mu, n_mu, lat_mu = ul(Config(**base, ofdma=True, ul_ofdma=True, ofdma_max_users=9))
    assert sum(s.failed_transmissions for s in ap_su.sta_list) > 100          # contention collisions
    assert all(s.succeeded_transmissions == s.failed_transmissions == 0 for s in ap_mu.sta_list)   # never contend
    assert ap_mu.ofdma_stats["ul_rounds"] > 0 and ap_mu.ofdma_stats["ul_mpdus_ok"] == ap_mu.ofdma_stats["ul_mpdus"]
    assert n_mu >= 0.95 * n_su and lat_mu < 0.7 * lat_su


def test_ofdma_with_association():
    ap, _ = _run(Config(**HE, ofdma=True, management=MgmtConfig()), 4,
                 traffic=TrafficConfig(mode="poisson", arrival_rate_pps=800.0), t=0.6)
    m = ap._mgmt
    first = min(st.assoc_time_us for st in m.sta_state.values())
    d = [p for p in ap.packet_log if p.status == "DELIVERED"]
    assert d and min(p.delivered_at for p in d) > first
    assert {p.destination for p in d} <= {s.name for s in ap.associated}


def test_cli():
    base = ["--ap-number", "1", "--gnb-number", "0", "--seed", "1", "-t", "0.05", "-r", "1"]
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("log", exist_ok=True)
        on = runner.invoke(single_run, base + ["--wifi-phy", "he", "--wifi-ofdma", "--wifi-ampdu", "8",
                                               "--wifi-sta-uplink-enabled", "--wifi-ul-ofdma"])
        bad1 = runner.invoke(single_run, base + ["--wifi-ofdma"])
        bad2 = runner.invoke(single_run, base + ["--wifi-phy", "he", "--wifi-ul-ofdma"])
    assert on.exit_code == 0, on.output[-400:]
    assert "=== Wi-Fi OFDMA ===" in on.output
    assert bad1.exit_code != 0 and bad2.exit_code != 0
# Rashed-Step 20.E-10-09-2026-end
