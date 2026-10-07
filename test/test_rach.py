# Rashed-Step 19.A-10-07-2026-start
"""
Step 19.A tests: 4-step random access (ran/protocol/rach.py) before RRC,
for licensed NR and NR-U.
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
from nr.nr import Config_NRL
from nru.nru import Config_NR
from ran.protocol.rach import RachCell, RachConfig, rach_config_from_cli
from simulation_nr import run_simulation_licensed_nr
from singleRun import single_run
from singleRunNR import single_run_nr
from wifi.wifi import Config


def _expect_value_error(fn, needle):
    try:
        fn()
    except ValueError as e:
        assert needle in str(e)
    else:
        assert False, "expected ValueError"


def test_config_and_cli():
    _expect_value_error(lambda: RachConfig(prach_period_us=0), "prach_period_us must be > 0")
    _expect_value_error(lambda: RachConfig(n_preambles=0), "must be >= 1")
    assert rach_config_from_cli(False, None, None, None) is None
    assert rach_config_from_cli(True, None, None, None) == RachConfig()
    c = rach_config_from_cli(True, 5.0, 20.0, 40.0)
    assert (c.prach_period_us, c.backoff_us, c.rar_window_us) == (5000.0, 20000.0, 40000.0)
    _expect_value_error(lambda: rach_config_from_cli(False, 5.0, None, None), "require --rach")


def test_occasions_are_on_a_shared_grid():
    cell = RachCell.__new__(RachCell)
    cell.config = RachConfig(prach_period_us=10_000.0)
    assert cell._next_occasion(0.0) == 10_000.0
    assert cell._next_occasion(9_999.0) == 10_000.0
    assert cell._next_occasion(10_000.0) == 20_000.0


# ---------------------------------------------------------------------
# licensed NR
# ---------------------------------------------------------------------

def _nr(rach, ues=1, radius=50.0, t=0.5, seed=2):
    cfg = Config_NRL(tdd_enabled=True, rach=rach)
    logging.disable(logging.CRITICAL)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            return run_simulation_licensed_nr(1, seed, t, cfg, nr_ues_per_gnb=ues, ue_radius=radius,
                                              nr_ue_uplink_enabled=True, nr_rrc_enabled=True)
    finally:
        logging.disable(logging.NOTSET)


def test_single_ue_timing():
    res = _nr(RachConfig())
    r = res["rach_stats"]
    # Next occasion at 10 ms + 1 ms RAR; then RRC's 4 ms.
    assert r["succeeded"] == 1 and r["latencies_us"] == [11_000.0]
    assert r["mean_preambles"] == 1.0 and r["collisions"] == 0
    assert res["rrc_stats"]["latencies_us"] == [15_000.0]
    assert res["rrc_stats"]["failed"] == 0


def test_without_rach_nothing_changes():
    res = _nr(None)
    assert res["rach_stats"] is None
    assert res["rrc_stats"]["latencies_us"] == [4_000.0]


def test_crowded_cell_collides_but_everyone_gets_in():
    r = _nr(RachConfig(), ues=40)["rach_stats"]
    assert r["succeeded"] == 40 and r["failed"] == 0
    assert r["collisions"] > 5
    # A collision costs the contention timer (64 ms) before the retry.
    assert r["mean_latency_us"] > 11_000.0


def test_one_preamble_two_ues_both_fail():
    res = _nr(RachConfig(n_preambles=1, preamble_trans_max=3), ues=2)
    r, rrc = res["rach_stats"], res["rrc_stats"]
    assert r["failed"] == 2 and r["succeeded"] == 0 and r["collisions"] == 6
    assert rrc["connected"] == 0 and rrc["failed"] == 2 and rrc["success_rate"] == 0.0


def test_power_ramping_gets_a_weak_preamble_through():
    # Target 15 dB below the noise over the PRACH band: below the -10 dB
    # detection threshold until a few 2 dB ramps.
    r = _nr(RachConfig(target_rx_power_dbm=-118.0))["rach_stats"]
    assert r["succeeded"] == 1 and r["mean_preambles"] > 1 and r["no_rar"] >= 1


def test_out_of_reach_ue_fails_after_preamble_max():
    res = _nr(RachConfig(preamble_trans_max=4), radius=3000.0, seed=5)
    r = res["rach_stats"]
    assert r["failed"] == 1 and r["no_rar"] == 4
    assert res["rrc_stats"]["failed"] == 1


# ---------------------------------------------------------------------
# NR-U
# ---------------------------------------------------------------------

def _nru(n_ap, seed=4, **cfg):
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
            wifi = Config()
            backoffs = {k: {n_ap: 0} for k in range(wifi.cw_max + 1)}
            simulation.run_simulation(n_ap, 1, seed, 0.5, wifi, Config_NR(rach=RachConfig(), **cfg),
                                      backoffs, {}, {}, {}, {}, False,
                                      nru_ue_uplink_enabled=True, nru_rrc_enabled=True)
    finally:
        simulation.Gnb = orig
        logging.disable(logging.NOTSET)
    return gnbs[0].ue_list[0]


def test_nru_own_gnb_does_not_block_prach():
    ue = _nru(0)
    assert ue.rach_lbt_failures == 0
    assert ue.rach_done_at is not None and ue.rrc_state.name == "CONNECTED"


def test_nru_rar_waits_for_a_cot():
    ue = _nru(0, cot_model="slots")
    # Preamble at 10 ms; the RAR needs a gNB COT after the 1 ms processing.
    assert ue.rach_done_at >= 11_000.0
    assert ue.rrc_state.name == "CONNECTED"


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------

def _cli(cmd, args):
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("log", exist_ok=True)
        return runner.invoke(cmd, args)


def test_cli():
    nr = ["--gnb-number", "1", "--ues-per-gnb", "2", "--seed", "1", "-t", "0.05"]
    r = _cli(single_run_nr, nr + ["--tdd-enabled", "--ue-uplink-enabled", "--rrc-enabled", "--rach"])
    assert r.exit_code == 0, (r.output, r.exception)
    assert "=== Licensed 5G NR Random Access ===" in r.output and "NR RRC failed (random access): 0" in r.output
    r = _cli(single_run_nr, nr + ["--rach"])
    assert r.exit_code != 0 and "--rach requires --rrc-enabled" in r.output
    r = _cli(single_run_nr, nr + ["--prach-period-ms", "5"])
    assert r.exit_code != 0 and "require --rach" in r.output
    nru = ["--ap-number", "1", "--gnb-number", "1", "--seed", "1", "-r", "1", "-t", "0.1"]
    r = _cli(single_run, nru + ["--nru-ue-uplink-enabled", "--nru-rrc-enabled", "--rach"])
    assert r.exit_code == 0, (r.output, r.exception)
    assert "=== NR-U Random Access ===" in r.output
    r = _cli(single_run, nru + ["--rach"])
    assert r.exit_code != 0 and "--rach requires --nru-rrc-enabled" in r.output
# Rashed-Step 19.A-10-07-2026-end
