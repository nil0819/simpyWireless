# Rashed-Step pre_21.E-10-11-2026-start
"""
Step pre_21.E: an OFDMA PPDU's airtime counts once - channel totals on its
primary RU, per-node successful airtime split over the RUs that got
through (was: once per resource unit, so shares above 1.0).
"""

import contextlib
import io
import logging
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest

import simulation
from common.packet import TrafficConfig
from nru.nru import Config_NR
from wifi.wifi import Config

HE = dict(phy="he", channel_width_mhz=20, mcs=7, ampdu_max_mpdus=16, ofdma=True, ofdma_max_users=8)


def _run(cfg, uplink=False, t=0.3):
    logging.disable(logging.CRITICAL)
    aps, chans = [], []
    orig_w, orig_c = simulation.WiFi, simulation.Channel

    class SpyW(orig_w):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            aps.append(self)

    class SpyC(orig_c):
        def __post_init__(self):
            super().__post_init__()
            chans.append(self)
    simulation.WiFi, simulation.Channel = SpyW, SpyC
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            fair = simulation.run_simulation(
                1, 0, 1, t, cfg, Config_NR(), {k: {1: 0} for k in range(1024)}, {}, {}, {}, {}, False,
                ap_positions=[(0.0, 0.0)], sta_radius=8.0, wifi_stas_per_ap=8, fairness_report=True,
                wifi_sta_uplink_enabled=uplink,
                wifi_sta_traffic_config=TrafficConfig(mode="saturated") if uplink else None)
    finally:
        simulation.WiFi, simulation.Channel = orig_w, orig_c
        logging.disable(logging.NOTSET)
    return aps[0], chans[0], fair


def test_downlink_ppdu_counted_once():
    ap, ch, fair = _run(Config(**HE))
    st = ap.ofdma_stats
    assert st["dl_users"] == 8 * st["dl_ppdus"] and st["dl_mpdus_ok"] == st["dl_mpdus"]   # 8 successful RUs each
    w = fair["tech"]["WiFi"]
    assert 0.5 < w["airtime_share"] <= 1.0                   # was ~8x with every RU counted
    assert ch.tx_count["WiFi"] == st["dl_ppdus"]
    assert ch.airtime_data[ap.name] == pytest.approx(ch.tx_airtime_total_us["WiFi"], rel=0.01)


def test_uplink_tb_ppdus_counted_once_and_split_per_sta():
    ap, ch, fair = _run(Config(**HE, ul_ofdma=True), uplink=True)
    assert ap.ofdma_stats["ul_rounds"] > 0
    assert 0.5 < fair["tech"]["WiFi"]["airtime_share"] <= 1.0
    sta_air = [ch.airtime_data.get(s.name, 0) for s in ap.sta_list]
    assert all(a > 0 for a in sta_air)                         # every STA credited for its own RU
    assert sum(sta_air) + ch.airtime_data[ap.name] <= ch.tx_airtime_total_us["WiFi"] * 1.01
# Rashed-Step pre_21.E-10-11-2026-end
