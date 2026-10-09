# Rashed-Step 20.D-10-08-2026-start
"""
Step 20.D tests: 802.11 management plane (wifi/mgmt.py) - beacons,
passive scan + authentication/association with the strongest AP, data
only to/from associated STAs, roaming.
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
from click.testing import CliRunner

import simulation
from common.packet import TrafficConfig
from nru.nru import Config_NR
from singleRun import single_run
from wifi import mac
from wifi.mgmt import MgmtConfig
from wifi.wifi import Config


def _run(cfg, n_ap=1, positions=None, t=1.0, seed=1, uplink=False, mobility=0.0, area=(50.0, 50.0), **kw):
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
            backoffs = {k: {n_ap: 0} for k in range(1024)}
            simulation.run_simulation(n_ap, 0, seed, t, cfg, Config_NR(), backoffs, {}, {}, {}, {}, False,
                                      ap_positions=positions or [(0.0, 0.0)], sta_radius=3.0,
                                      wifi_sta_uplink_enabled=uplink, sta_mobility_speed_mps=mobility,
                                      area_w=area[0], area_h=area[1], **kw)
    finally:
        simulation.WiFi = orig
        logging.disable(logging.NOTSET)
    return aps


def test_off_by_default():
    assert Config().management is None
    aps = _run(Config(), t=0.05)
    assert aps[0]._mgmt is None


def test_beacons_every_interval():
    aps = _run(Config(management=MgmtConfig()), t=1.0)
    m = aps[0]._mgmt
    assert 9 <= m.stats["beacons"] <= 10                    # 1 s / 102.4 ms
    assert m.stats["beacon_airtime_us"] == m.stats["beacons"] * mac.ctrl_frame_us(250, 6) == m.stats["beacons"] * 360


def test_stas_join_the_strongest_ap_and_data_waits_for_it():
    aps = _run(Config(management=MgmtConfig()), n_ap=2, positions=[(0.0, 0.0), (20.0, 0.0)], t=1.0,
               wifi_traffic_config=TrafficConfig(mode="poisson", arrival_rate_pps=300.0))
    m = aps[0]._mgmt
    for st in m.sta_state.values():
        assert st.state == "associated"
        assert st.assoc_time_us >= MgmtConfig().scan_us                     # after the passive scan
        assert st.ap.name == max(st.rssi, key=lambda a: st.rssi[a][0])       # the strongest beacon
        assert st.sta in st.ap.associated and st.sta.ap is st.ap
    first_assoc = min(st.assoc_time_us for st in m.sta_state.values())
    delivered = [p for ap in aps for p in ap.packet_log if p.status == "DELIVERED"]
    assert delivered and min(p.delivered_at for p in delivered) > first_assoc
    assert m.stats["mgmt_frames"] >= 4 * len(m.sta_state)


def test_uplink_waits_for_association():
    aps = _run(Config(management=MgmtConfig()), t=0.5, uplink=True)
    st = next(iter(aps[0]._mgmt.sta_state.values()))
    ul = [p for p in st.sta.packet_log if p.status == "DELIVERED"]
    assert ul and min(p.delivered_at for p in ul) > st.assoc_time_us


def test_roaming_between_two_aps():
    cfg = Config(management=MgmtConfig(), mac_exchange=True, preamble_detect_dbm=-82.0)
    aps = _run(cfg, n_ap=2, positions=[(0.0, 10.0), (60.0, 10.0)], t=5.0, mobility=10.0, area=(60.0, 20.0),
               wifi_traffic_config=TrafficConfig(mode="poisson", arrival_rate_pps=500.0))
    m = aps[0]._mgmt
    s = m.summary(5e6)
    assert s["roams"] >= 1 and s["associated"] == s["stas"]
    assert 0 < s["mean_interruption_ms"] < 20          # reassociation only, the target is known from beacons


def test_cli():
    base = ["--ap-number", "2", "--gnb-number", "0", "--seed", "1", "-t", "0.3", "-r", "1"]
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("log", exist_ok=True)
        off = runner.invoke(single_run, base)
        on = runner.invoke(single_run, base + ["--wifi-management", "--wifi-beacon-interval-ms", "50"])
    assert off.exit_code == 0 and on.exit_code == 0, on.output[-400:]
    assert "Wi-Fi Management" not in off.output and "=== Wi-Fi Management ===" in on.output
    assert "Wifi STAs associated at end: 2/2" in on.output
# Rashed-Step 20.D-10-08-2026-end
