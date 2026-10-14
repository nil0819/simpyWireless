# Rashed-Step pre_22.D-10-13-2026-start
"""
Step pre_22.D tests: NR-U reservation signal instead of the sync-slot gap
(Config_NR.reservation_signal) and the CTS-to-self power
(Config_NR.cts_power_dbm).
"""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest
from click.testing import CliRunner

from analysis.laa_fairness import run_case
from channel.channel import Channel
from nru.nru import Config_NR
from singleRun import single_run
from wifi.wifi import Config


def test_config():
    c = Config_NR()
    assert c.reservation_signal is False and c.cts_power_dbm is None
    with pytest.raises(ValueError):
        Config_NR(reservation_signal=True)                  # burst model


def _laa(rs):
    # Saturated Wi-Fi with 5.4 ms A-MPDUs next to an NR-U gNB 10 m away:
    # in the gap NR-U keeps losing the channel to Wi-Fi.
    return run_case("nru", None, 6000.0, 10.0, seed=1, sim_time_s=0.5, wifi_config=Config(ampdu_max_mpdus=32),
                    nru_config=Config_NR(cot_model="slots", reservation_signal=rs))


def test_reservation_signal_wins_nru_more_channel_accesses():
    gap, rs = _laa(False), _laa(True)
    assert rs["fairness"]["tech"]["NRU"]["transmissions"] > 1.5 * gap["fairness"]["tech"]["NRU"]["transmissions"]
    assert rs["b"]["throughput_mbps"] > gap["b"]["throughput_mbps"]
    assert rs["a"]["throughput_mbps"] < gap["a"]["throughput_mbps"]


def test_cts_and_its_nav_use_the_cts_power():
    seen = []
    orig = Channel.set_nav

    def spy(self, r):
        seen.append(r.tx_power_dbm)
        return orig(self, r)
    Channel.set_nav = spy
    try:
        run_case("nru", 500.0, 1000.0, 20.0, seed=1, sim_time_s=0.1,
                 nru_config=Config_NR(cot_model="slots", wifi_reservation="cts_to_self", cts_power_dbm=20.0))
    finally:
        Channel.set_nav = orig
    assert seen and set(seen) == {20.0}                     # not the 23 dBm data power


def test_cli():
    base = ["--ap-number", "1", "--gnb-number", "1", "--seed", "1", "-t", "0.05", "-r", "1"]
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("log", exist_ok=True)
        ok = runner.invoke(single_run, base + ["--nru-cot-model", "slots", "--nru-reservation-signal",
                                               "--wifi-preamble-detect", "--nru-wifi-reservation", "cts_to_self",
                                               "--nru-cts-power-dbm", "20"])
        bad = runner.invoke(single_run, base + ["--nru-reservation-signal"])
    assert ok.exit_code == 0, ok.output[-300:]
    assert bad.exit_code != 0
# Rashed-Step pre_22.D-10-13-2026-end
