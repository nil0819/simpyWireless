# Rashed-Step 18.A-10-06-2026-start
"""
Step 18.A tests: the link error model (common/error_model.py) and its
wiring into licensed NR, NR-U and Wi-Fi via --error-model.

CLI runs go through click's CliRunner inside isolated_filesystem() so
singleRun.py's packet.log report lands in a temp dir, not the repo.
"""

import math
import os
import random
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from click.testing import CliRunner

from common.error_model import (
    BlerErrorModel,
    ErrorModelConfig,
    decode_ok,
    error_model_config_from_cli,
    make_error_model,
)
from nr.nr import Config_NRL, GnbLicensedNR, NR_MCS_TABLE
from simulation_nr import run_simulation_licensed_nr
from singleRun import single_run
from singleRunNR import single_run_nr


def _expect_value_error(fn, needle):
    try:
        fn()
    except ValueError as e:
        assert needle in str(e)
    else:
        assert False, "expected ValueError"


# ---------------------------------------------------------------------
# BLER curve
# ---------------------------------------------------------------------

def test_bler_hits_target_at_threshold_and_falls_with_sinr():
    m = BlerErrorModel(ErrorModelConfig(), seed=1)
    for req in (-6.0, 4.0, 25.0):
        assert math.isclose(m.bler(req, req), 0.1, rel_tol=1e-9)
        assert m.bler(req - 3, req) > m.bler(req - 1, req) > 0.1 > m.bler(req + 1, req) > m.bler(req + 3, req)
    # Default slope 2/dB: 10% -> ~1% about 1.2 dB above the threshold.
    assert 0.009 < m.bler(1.2, 0.0) < 0.011


def test_bler_extremes_do_not_overflow():
    m = BlerErrorModel(ErrorModelConfig(slope_per_db=50.0), seed=1)
    assert m.bler(1e4, 0.0) == 0.0
    assert m.bler(-1e4, 0.0) == 1.0


def test_steeper_slope_narrows_the_waterfall():
    gentle = BlerErrorModel(ErrorModelConfig(slope_per_db=1.0), seed=1)
    steep = BlerErrorModel(ErrorModelConfig(slope_per_db=5.0), seed=1)
    assert steep.bler(2.0, 0.0) < gentle.bler(2.0, 0.0)
    assert steep.bler(-2.0, 0.0) > gentle.bler(-2.0, 0.0)


# ---------------------------------------------------------------------
# decode_ok / random stream
# ---------------------------------------------------------------------

def test_decode_ok_without_model_is_the_threshold_rule():
    assert decode_ok(None, 5.0, 5.0) is True
    assert decode_ok(None, 4.999, 5.0) is False
    assert decode_ok(None, 30.0, 5.0) is True


def test_decode_rate_at_threshold_is_about_target():
    m = BlerErrorModel(ErrorModelConfig(), seed=7)
    n = 20000
    fails = sum(not m.decode(3.0, 3.0) for _ in range(n))
    assert 0.09 < fails / n < 0.11
    assert m.stats["decodes"] == n
    assert m.stats["failures"] == fails == m.stats["failures_above_threshold"]
    assert m.stats["successes_below_threshold"] == 0


def test_decode_counts_successes_below_threshold():
    m = BlerErrorModel(ErrorModelConfig(), seed=3)
    oks = sum(m.decode(-1.0, 0.0) for _ in range(2000))
    assert oks == m.stats["successes_below_threshold"] > 0


def test_model_uses_its_own_stream_not_the_global_one():
    random.seed(123)
    expected = [random.random() for _ in range(3)]
    random.seed(123)
    m = BlerErrorModel(ErrorModelConfig(), seed=1)
    for _ in range(100):
        m.decode(0.0, 0.0)
    assert [random.random() for _ in range(3)] == expected


def test_same_seed_same_draws():
    a = BlerErrorModel(ErrorModelConfig(), seed=5)
    b = BlerErrorModel(ErrorModelConfig(), seed=5)
    assert [a.decode(0.5, 0.0) for _ in range(200)] == [b.decode(0.5, 0.0) for _ in range(200)]


# ---------------------------------------------------------------------
# config / CLI mapping
# ---------------------------------------------------------------------

def test_config_validation():
    _expect_value_error(lambda: ErrorModelConfig(slope_per_db=0.0), "slope must be > 0")
    _expect_value_error(lambda: ErrorModelConfig(target_bler=1.0), "strictly between 0 and 1")


def test_error_model_config_from_cli():
    assert error_model_config_from_cli("threshold", None) is None
    assert error_model_config_from_cli("bler", None) == ErrorModelConfig()
    assert error_model_config_from_cli("bler", 3.5).slope_per_db == 3.5
    _expect_value_error(lambda: error_model_config_from_cli("threshold", 2.0), "requires --error-model bler")
    _expect_value_error(lambda: error_model_config_from_cli("bler", -1.0), "slope must be > 0")
    _expect_value_error(lambda: error_model_config_from_cli("magic", None), "must be one of")


def test_make_error_model():
    assert make_error_model(None, 1) is None
    assert isinstance(make_error_model(ErrorModelConfig(), 1), BlerErrorModel)


# ---------------------------------------------------------------------
# licensed NR: _decode_mcs
# ---------------------------------------------------------------------

class _FixedModel:
    """Stands in for BlerErrorModel; records what it was asked."""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def decode(self, sinr_db, required_db):
        self.calls.append((sinr_db, required_db))
        return self.result


def _bare_gnb(error_model):
    g = GnbLicensedNR.__new__(GnbLicensedNR)
    g.config = Config_NRL(error_model=error_model)
    return g


def test_decode_mcs_without_model_passes_the_pick_through():
    g = _bare_gnb(None)
    assert g._decode_mcs(9.0, 4) == 4
    assert g._decode_mcs(-9.0, None) is None


def test_decode_mcs_with_model_draws_at_the_pick_or_mcs0():
    ok = _FixedModel(True)
    g = _bare_gnb(ok)
    assert g._decode_mcs(9.0, 4) == 4
    assert g._decode_mcs(-9.0, None) == 0
    assert ok.calls == [(9.0, NR_MCS_TABLE[4][0]), (-9.0, NR_MCS_TABLE[0][0])]
    assert _bare_gnb(_FixedModel(False))._decode_mcs(9.0, 4) is None


# ---------------------------------------------------------------------
# orchestrators / CLIs
# ---------------------------------------------------------------------

def test_licensed_nr_run_reports_stats_and_leaves_caller_config_alone():
    cfg = Config_NRL()
    off = run_simulation_licensed_nr(1, 1, 0.01, cfg, nr_ues_per_gnb=2)
    on = run_simulation_licensed_nr(1, 1, 0.01, cfg, nr_ues_per_gnb=2,
                                    error_model_config=ErrorModelConfig())
    assert off["error_model_stats"] is None
    assert on["error_model_stats"]["decodes"] > 0
    assert cfg.error_model is None


def _run(cmd, args):
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cmd, args)
    return result


NR_BASE = ["--gnb-number", "1", "--ues-per-gnb", "2", "--seed", "1", "-t", "0.01"]
NRU_BASE = ["--ap-number", "1", "--gnb-number", "1", "--seed", "1", "-r", "1", "-t", "0.05"]


def test_nr_cli_default_has_no_error_model_block():
    r = _run(single_run_nr, NR_BASE)
    assert r.exit_code == 0, (r.output, r.exception)
    assert "=== Error Model ===" not in r.output


def test_nr_cli_bler_prints_block():
    r = _run(single_run_nr, NR_BASE + ["--error-model", "bler", "--bler-slope-db", "3"])
    assert r.exit_code == 0, (r.output, r.exception)
    assert "=== Error Model ===" in r.output
    assert "slope 3.0 per dB" in r.output


def test_cli_rejects_slope_without_bler():
    r = _run(single_run_nr, NR_BASE + ["--bler-slope-db", "3"])
    assert r.exit_code != 0
    assert "requires --error-model bler" in r.output
    r = _run(single_run, NRU_BASE + ["--bler-slope-db", "3"])
    assert r.exit_code != 0
    assert "requires --error-model bler" in r.output


def test_coexistence_cli_bler_covers_wifi_and_nru():
    r = _run(single_run, NRU_BASE + ["--error-model", "bler", "--wifi-sta-uplink-enabled",
                                     "--nru-ue-uplink-enabled"])
    assert r.exit_code == 0, (r.output, r.exception)
    assert "=== Error Model ===" in r.output
    decodes = int(next(l for l in r.output.splitlines() if l.startswith("Error model decodes:")).split(":")[1])
    assert decodes > 0
# Rashed-Step 18.A-10-06-2026-end
