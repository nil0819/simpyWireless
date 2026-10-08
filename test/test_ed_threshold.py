# Rashed-Step pre_20.D.2-10-08-2026-start
"""
Step pre_20.D.2 tests: NR-U energy-detection threshold - TS 37.213
clause 4.1.5 (Config_NR.ed_threshold_mode="ts37213") and the CLI
override.
"""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest
from click.testing import CliRunner

from analysis.laa_fairness import run_case
from nru.nru import Config_NR
from ran.protocol.channel_access import ts37213_ed_threshold_dbm as ed
from singleRun import single_run


def test_formula_values():
    # 20 MHz: T_max = -75 + 13.01 = -61.99 dBm; -72 floor.
    assert ed(23.0) == pytest.approx(-72.0, abs=0.02)
    assert ed(18.0) == pytest.approx(-67.0, abs=0.02)
    assert ed(13.0) == pytest.approx(-62.0, abs=0.02)
    assert ed(5.0) == pytest.approx(-62.0, abs=0.02)      # capped at T_max
    assert ed(30.0) == pytest.approx(-72.0, abs=0.02)     # never below -72
    assert ed(23.0, bandwidth_mhz=40.0) == pytest.approx(-66.0, abs=0.05)
    assert ed(23.0, t_a_db=5.0) == pytest.approx(-67.0, abs=0.02)   # discovery-only bursts


def test_config_mode():
    assert Config_NR().ed_threshold_dbm == -72.0
    assert Config_NR(ed_threshold_mode="ts37213", tx_power_dbm=18.0).ed_threshold_dbm == pytest.approx(-67.0, abs=0.02)
    with pytest.raises(ValueError):
        Config_NR(ed_threshold_mode="etsi")


def test_lower_ed_makes_nru_defer_to_wifi_at_40_m():
    # 40 m: Wi-Fi reaches the gNB at ~-75 dBm - below -72, above -77.
    def a_latency(**kw):
        r = run_case("nru", 1500.0, 2500.0, 40.0, seed=1, sim_time_s=0.5,
                     nru_config=Config_NR(cot_model="slots", **kw))
        return r["a"]["avg_latency_us"] / 1000.0
    assert a_latency(ed_threshold_dbm=-77.0) < 0.5 * a_latency()


def test_cli_flags():
    base = ["--ap-number", "1", "--gnb-number", "1", "--seed", "1", "-t", "0.05", "-r", "1"]
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("log", exist_ok=True)
        off = runner.invoke(single_run, base)
        thr = runner.invoke(single_run, base + ["--nru-ed-threshold-dbm", "-82"])
        mode = runner.invoke(single_run, base + ["--nru-ed-mode", "ts37213", "--nru-tx-power-dbm", "13"])
    for r in (off, thr, mode):
        assert r.exit_code == 0, r.output[-300:]
# Rashed-Step pre_20.D.2-10-08-2026-end
