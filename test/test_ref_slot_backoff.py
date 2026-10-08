# Rashed-Step pre_20.D.4-10-08-2026-start
"""
Step pre_20.D.4 tests: reference-slot feedback - the NACK threshold Z
(Config_NR.ref_slot_nack_threshold) and the adaptive COT cap
(Config_NR.adaptive_cot).
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
from wifi.wifi import Config


def _gnb(nru_cfg, seed=1, t=0.5):
    """1 saturated Wi-Fi AP (0,0) + 1 NR-U gNB 30 m away whose UEs are hit by
    Wi-Fi it can't always hear; 4 UEs spread to 40 m, so a slot can lose
    some UEs' blocks and not others."""
    logging.disable(logging.CRITICAL)
    gnbs = []
    orig = simulation.Gnb

    class Spy(orig):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            gnbs.append(self)

    simulation.Gnb = Spy
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            backoffs = {k: {1: 0} for k in range(1024)}
            simulation.run_simulation(1, 1, seed, t, Config(), nru_cfg, backoffs, {}, {}, {}, {}, False,
                                      ap_positions=[(0.0, 0.0)], gnb_positions=[(30.0, 0.0)], sta_radius=5.0,
                                      ue_radius=40.0, nr_ues_per_gnb=4,
                                      nru_traffic_config=TrafficConfig(mode="poisson", arrival_rate_pps=4000.0))
    finally:
        simulation.Gnb = orig
        logging.disable(logging.NOTSET)
    return gnbs[0]


def test_config_defaults_and_validation():
    c = Config_NR()
    assert c.ref_slot_nack_threshold == 0.8 and c.adaptive_cot is False
    with pytest.raises(ValueError):
        Config_NR(cot_model="slots", ref_slot_nack_threshold=0.0)
    with pytest.raises(ValueError):
        Config_NR(adaptive_cot=True)                        # burst model


def test_smaller_z_counts_more_reference_slots_as_failed():
    z80 = _gnb(Config_NR(cot_model="slots")).slot_stats
    z01 = _gnb(Config_NR(cot_model="slots", ref_slot_nack_threshold=0.01)).slot_stats
    assert z80["cots_failed"] > 0
    assert z01["cots_failed"] / z01["cots"] > z80["cots_failed"] / z80["cots"]


def test_adaptive_cot_shrinks_the_cap_after_failures():
    g = _gnb(Config_NR(cot_model="slots", adaptive_cot=True, ref_slot_nack_threshold=0.01))
    st = g.slot_stats
    mean_cap = st["cot_cap_us_sum"] / st["cots"]
    assert g.slot_us <= mean_cap < g.config_nr.mcot * 1000
    assert g.slot_us <= g._cot_cap_us <= g.config_nr.mcot * 1000
    plain = _gnb(Config_NR(cot_model="slots")).slot_stats
    assert plain["cot_cap_us_sum"] == 0.0                   # off: never touched


def test_cli():
    base = ["--ap-number", "1", "--gnb-number", "1", "--seed", "1", "-t", "0.05", "-r", "1",
            "--nru-cot-model", "slots"]
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("log", exist_ok=True)
        off = runner.invoke(single_run, base)
        on = runner.invoke(single_run, base + ["--nru-adaptive-cot", "--nru-ref-nack-threshold", "0.5"])
        bad = runner.invoke(single_run, ["--ap-number", "1", "--gnb-number", "1", "-t", "0.05", "--nru-adaptive-cot"])
    assert off.exit_code == 0 and on.exit_code == 0, on.output[-300:]
    assert "adaptive COT" not in off.output and "NRU adaptive COT: mean COT cap" in on.output
    assert bad.exit_code != 0
# Rashed-Step pre_20.D.4-10-08-2026-end
