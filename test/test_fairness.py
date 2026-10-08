# Rashed-Step pre_20.A-10-08-2026-start
"""
Step pre_20.A tests: fairness metrics (common/fairness.py), the channel's
per-technology airtime counters, 802.11 preamble detection, per-AP
traffic, and the 3GPP replacement-test harness (analysis/laa_fairness.py).
"""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import simpy
from click.testing import CliRunner

from analysis.laa_fairness import run_case
from channel.channel import ActiveTx, Channel
from common.fairness import jain_index
from ran.protocol.channel_access import DcfChannelAccess
from singleRun import single_run
from wifi.wifi import Config


def _ch():
    env = simpy.Environment()
    return Channel(simpy.PriorityResource(env, capacity=1), simpy.Resource(env, capacity=1), 1, 1, {}, {}, {}, {}, {})


def _tx(name, x, tech, power=20.0, **kw):
    return ActiveTx(tx_id=name, tx_pos=(x, 0.0), tx_start=0, rx_pos=(0.0, 0.0), tx_power_dbm=power,
                    f_hz=5.18e9, pl_exp=3.0, t_end=1000, tech=tech, bandwidth_mhz=20.0, **kw)


def test_jain_index():
    assert jain_index([0.5, 0.5]) == 1.0
    assert jain_index([1.0, 0.0]) == 0.5
    assert abs(jain_index([0.6, 0.2]) - (0.8 ** 2) / (2 * 0.40)) < 1e-12


def test_channel_counts_all_airtime_failed_included():
    ch = _ch()
    a, b = _tx("ap", 5, "WiFi"), _tx("g", 5, "NRU")
    ch.register_tx(a)
    ch.register_tx(b)
    ch.unregister_tx(a, success=True)
    ch.unregister_tx(b, success=False)
    assert ch.tx_airtime_total_us == {"WiFi": 1000, "NRU": 1000}
    assert ch.tx_count == {"WiFi": 1, "NRU": 1} and ch.tx_failed == {"NRU": 1}
    assert ch.airtime_data == {"ap": 1000} and ch.airtime_data_NR == {}   # successful only, as before


def test_preamble_detection_hears_wifi_not_nru_between_minus82_and_minus62():
    ch = _ch()
    # 40 m away at 20 dBm: about -71 dBm at the sensing point - between -82 and -62.
    ch.register_tx(_tx("ap2", 40, "WiFi"))
    assert not ch.is_busy((0, 0), -62.0, sense_f_hz=5.18e9, sense_bw_mhz=20.0)
    assert ch.is_busy_wifi((0, 0), -62.0, -82.0, sense_f_hz=5.18e9, sense_bw_mhz=20.0)
    ch2 = _ch()
    ch2.register_tx(_tx("g", 40, "NRU"))
    assert not ch2.is_busy_wifi((0, 0), -62.0, -82.0, sense_f_hz=5.18e9, sense_bw_mhz=20.0)
    ch3 = _ch()
    ch3.register_tx(_tx("g", 40, "NRU", wifi_preamble=True))       # NR-U sending a Wi-Fi preamble
    assert ch3.is_busy_wifi((0, 0), -62.0, -82.0, sense_f_hz=5.18e9, sense_bw_mhz=20.0)


def test_dcf_uses_preamble_detection_only_when_configured():
    class Node:
        name = "ap1"

        def __init__(self, channel, cfg):
            self.channel, self.config = channel, cfg

        def current_pos(self):
            return (0.0, 0.0)

    ch = _ch()
    ch.register_tx(_tx("ap2", 40, "WiFi"))
    assert not DcfChannelAccess._busy(Node(ch, Config()))
    assert DcfChannelAccess._busy(Node(ch, Config(preamble_detect_dbm=-82.0)))


def test_replacement_harness_runs_both_cases_with_per_ap_load():
    w = run_case("wifi", 200.0, 600.0, 10.0, seed=1, sim_time_s=0.2)
    n = run_case("nru", 200.0, 600.0, 10.0, seed=1, sim_time_s=0.2)
    # Network B carries ~3x network A's load in both cases.
    assert w["b"]["delivered"] > 2 * w["a"]["delivered"]
    assert n["b"]["delivered"] > 2 * n["a"]["delivered"]
    assert set(w["fairness"]["nodes"]) == {"AP 1", "AP 2"}
    assert set(n["fairness"]["nodes"]) == {"AP 1", "Gnb 1"}


def test_cli_fairness_block_only_when_asked():
    base = ["--ap-number", "1", "--gnb-number", "1", "--seed", "1", "-t", "0.1", "-r", "1"]
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("log", exist_ok=True)
        off = runner.invoke(single_run, base)
        on = runner.invoke(single_run, base + ["--fairness-report", "--wifi-preamble-detect"])
    assert off.exit_code == 0 and on.exit_code == 0, (off.output[-300:], on.output[-300:])
    assert "Coexistence Fairness" not in off.output
    assert "=== Coexistence Fairness ===" in on.output and "Jain's index over airtime shares" in on.output
# Rashed-Step pre_20.A-10-08-2026-end
