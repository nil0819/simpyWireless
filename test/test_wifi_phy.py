# Rashed-Step 20.C-10-08-2026-start
"""
Step 20.C tests: 802.11n/ac/ax PHY (wifi/phy.py) - rate tables, PPDU
durations, validation, the legacy path untouched, wider channels' noise,
aggregation efficiency, rate adaptation over the HE MCS range, CLI.
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
from nru.nru import Config_NR
from singleRun import single_run
from Times import Times
from wifi import phy
from wifi.wifi import Config


def _run(cfg, t=0.3, seed=1):
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
            fair = simulation.run_simulation(1, 0, seed, t, cfg, Config_NR(), backoffs, {}, {}, {}, {}, False,
                                             ap_positions=[(0.0, 0.0)], sta_radius=3.0, fairness_report=True)
    finally:
        simulation.WiFi = orig
        logging.disable(logging.NOTSET)
    return aps[0], fair["tech"]["WiFi"]["throughput_mbps"]


def test_rates_match_the_standard_tables():
    r = phy.rate_mbps
    assert r("ht", 20, 7, 800) == pytest.approx(65.0)
    assert r("ht", 40, 7, 400) == pytest.approx(150.0)
    assert r("vht", 80, 9, 400) == pytest.approx(433.3, abs=0.1)
    assert r("vht", 160, 9, 400) == pytest.approx(866.7, abs=0.1)
    assert r("he", 20, 0, 3200) == pytest.approx(7.3, abs=0.05)
    assert r("he", 80, 11, 800) == pytest.approx(600.5, abs=0.1)
    assert r("he", 160, 11, 800) == pytest.approx(1201.0, abs=0.1)


def test_ppdu_duration():
    t = phy.PhyTimes(1472, 7, "ht", 20, 800)
    # 36 us preamble + ceil((16 + 320 + 11776 + 6) / 260) = 47 symbols x 4 us
    assert t.get_ppdu_frame_time(1472) == 36 + 47 * 4
    assert t.data_rate == pytest.approx(65.0)
    he = phy.PhyTimes(1472, 11, "he", 80, 800)
    assert he.get_ppdu_frame_time(1472) == 72        # ceil(44 + 2 symbols x 13.6 us)


def test_validation_and_bandwidth():
    for bad in [("ht", 80, 7, 800), ("ht", 20, 8, 800), ("vht", 20, 9, 800), ("he", 20, 11, 400), ("xx", 20, 0, 800)]:
        with pytest.raises(ValueError):
            phy.validate(*bad)
    c = Config(phy="vht", channel_width_mhz=80, mcs=9, guard_interval_ns=400)
    assert c.bandwidth_mhz == 80.0
    with pytest.raises(ValueError):
        Config(phy="ht", mcs=9)


def test_legacy_is_the_original_times():
    c = Config()
    t = phy.make_times(c, 1472, 7)
    assert type(t) is Times and c.bandwidth_mhz == 20.0
    assert phy.sinr_table(c) is __import__("Times").WIFI_MCS_SINR_THRESHOLDS_DB
    assert [phy.ctrl_rate_mbps(c, m) for m in range(8)] == [6, 6, 12, 12, 24, 24, 24, 24]


def test_control_rate_follows_the_modulation():
    c = Config(phy="he", mcs=0)
    assert [phy.ctrl_rate_mbps(c, m) for m in (0, 1, 2, 3, 7, 11)] == [6, 12, 12, 24, 24, 24]


def test_wider_channel_has_more_noise():
    ap20, _ = _run(Config(phy="vht", channel_width_mhz=20, mcs=0), t=0.05)
    ap80, _ = _run(Config(phy="vht", channel_width_mhz=80, mcs=0), t=0.05)
    s20 = [p.measured_sinr_db for p in ap20.packet_log if p.measured_sinr_db is not None]
    s80 = [p.measured_sinr_db for p in ap80.packet_log if p.measured_sinr_db is not None]
    assert sum(s20) / len(s20) - sum(s80) / len(s80) == pytest.approx(6.02, abs=0.05)   # 4x the noise


def test_aggregation_is_what_makes_a_fast_phy_pay_off():
    _, ht = _run(Config(phy="ht", mcs=7))
    _, vht = _run(Config(phy="vht", channel_width_mhz=80, mcs=9, guard_interval_ns=400))
    _, vht_agg = _run(Config(phy="vht", channel_width_mhz=80, mcs=9, guard_interval_ns=400, ampdu_max_mpdus=64))
    assert vht < 2 * ht                     # 6.7x the PHY rate, < 2x the throughput: per-access overhead
    assert vht_agg > 5 * vht                # aggregation recovers it


def test_rate_adaptation_uses_the_he_mcs_range():
    ap, _ = _run(Config(phy="he", mcs=0, rate_adapt_enabled=True), t=0.5)
    states = list(ap.link_rate_state.values())
    assert states and max(s["mcs"] for s in states) > 7   # climbs past the legacy/HT range at close range


def test_cli():
    base = ["--ap-number", "1", "--gnb-number", "0", "--seed", "1", "-t", "0.05", "-r", "1"]
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("log", exist_ok=True)
        off = runner.invoke(single_run, base)
        on = runner.invoke(single_run, base + ["--wifi-phy", "he", "--wifi-channel-width", "40", "-m", "9", "--wifi-gi", "1600"])
        bad1 = runner.invoke(single_run, base + ["--wifi-channel-width", "40"])
        bad2 = runner.invoke(single_run, base + ["--wifi-phy", "ht", "--wifi-channel-width", "80"])
    assert off.exit_code == 0 and on.exit_code == 0, on.output[-300:]
    assert "Wi-Fi PHY" not in off.output and "Wifi PHY: HE 40 MHz, MCS 9, GI 1600 ns" in on.output
    assert bad1.exit_code != 0 and bad2.exit_code != 0
# Rashed-Step 20.C-10-08-2026-end
