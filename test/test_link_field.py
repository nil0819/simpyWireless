# Rashed-Step 22.B-10-15-2026-start
"""
Step 22.B tests: reciprocal, spatially correlated shadowing and LOS state
(channel/link_field.py, Propagation with shadowing, --shadowing-correlated).
"""
import math
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import numpy as np
import pytest
import simpy
from click.testing import CliRunner

from channel.channel import ActiveTx, Channel
from channel.link_field import LinkField
from channel.propagation import PathLossSpec, Propagation, path_loss_db

F = 5.18e9


def test_reciprocal_and_deterministic():
    f = LinkField(7, 1, 10.0)
    a, b = (1.0, 2.0), (31.5, -4.0)
    assert f.value(a, b) == f.value(b, a)
    assert LinkField(7, 1, 10.0).value(a, b) == f.value(a, b)          # same seed/stream -> same field
    assert LinkField(8, 1, 10.0).value(a, b) != f.value(a, b)
    assert LinkField(7, 2, 10.0).value(a, b) != f.value(a, b)
    assert 0.0 < f.uniform(a, b) < 1.0


def test_unit_variance_and_exponential_correlation():
    d = 10.0
    a, b = (0.0, 0.0), (30.0, 7.0)
    base, near, at_d = [], [], []
    for s in range(300):
        f = LinkField(s, 1, d)
        base.append(f.value(a, b))
        near.append(f.value(a, (32.0, 7.0)))       # moved 2 m: exp(-0.2) = 0.82
        at_d.append(f.value(a, (40.0, 7.0)))       # moved d: exp(-1) = 0.37
    base = np.array(base)
    assert abs(base.mean()) < 0.15 and 0.8 < base.var() < 1.25
    assert np.corrcoef(base, near)[0, 1] > 0.7
    assert 0.2 < np.corrcoef(base, at_d)[0, 1] < 0.55


def test_model_shadowing_sigma_by_los_state():
    a, b = (0.0, 0.0), (12.0, 5.0)
    d2d = math.hypot(12, 5)
    for los_mode, sigma in (("los", 3.0), ("nlos", 8.03)):
        plain = Propagation(PathLossSpec("inh-office-mixed", los_mode=los_mode), seed=3)
        shad = Propagation(PathLossSpec("inh-office-mixed", los_mode=los_mode, shadowing=True), seed=3)
        delta = shad.loss_db(a, b, F, True, False) - plain.loss_db(a, b, F, True, False)
        fld = shad._shadow[0 if los_mode == "los" else 1][1]
        assert delta == pytest.approx(sigma * fld.value(a, b))
        assert shad.loss_db(b, a, F, False, True) == shad.loss_db(a, b, F, True, False)
    assert path_loss_db("inh-office-mixed", d2d, 3.0, 1.5, F, True) == \
        Propagation(PathLossSpec("inh-office-mixed", los_mode="los")).loss_db(a, b, F, True, False)


def test_los_state_is_spatially_consistent():
    # Walking 10 -> 60 m in 0.25 m steps: independent draws (22.A) would
    # flip the LOS state ~90 times; the 10 m-correlated field far fewer
    # (exponential correlation is rough at small scales, so a crossing of
    # the LOS probability can flicker briefly).
    from channel.propagation import los_probability
    xs = np.arange(10.0, 60.0, 0.25)
    p_los = [los_probability("inh-office-open", x) for x in xs]
    independent = sum(p_los[i] * (1 - p_los[i - 1]) + p_los[i - 1] * (1 - p_los[i]) for i in range(1, len(xs)))
    flips = []
    for seed in range(20):
        p = Propagation(PathLossSpec("inh-office-open"), seed=seed)
        states = [p.is_los((0.0, 0.0), (x, 0.0), x) for x in xs]
        flips.append(sum(1 for i in range(1, len(states)) if states[i] != states[i - 1]))
    assert independent > 80
    assert np.mean(flips) < 0.25 * independent


def _channel(**kw):
    env = simpy.Environment()
    return Channel(simpy.PriorityResource(env, capacity=1), simpy.Resource(env, capacity=1), 1, 1, {}, {}, {}, {}, {},
                   **kw)


def _tx(tx_id, pos):
    return ActiveTx(tx_id=tx_id, tx_pos=pos, tx_start=0, rx_pos=(0.0, 0.0), tx_power_dbm=20.0, f_hz=F, pl_exp=3.0,
                    t_end=10, tech="WiFi")


def test_correlated_legacy_shadowing_is_reciprocal():
    a, b = (0.0, 0.0), (17.0, 3.0)
    old = _channel(shadowing_sigma_db=6.0)
    assert old.rx_power_at(_tx("AP 1", a), b) != old.rx_power_at(_tx("STA 1-1", b), a)   # independent draws
    new = _channel(shadowing_sigma_db=6.0, shadow_field=LinkField(1, 4, 10.0))
    ab = new.rx_power_at(_tx("AP 1", a), b)
    assert ab == new.rx_power_at(_tx("STA 1-1", b), a)
    plain = _channel().rx_power_at(_tx("AP 1", a), b)
    assert plain - ab == pytest.approx(6.0 * new.shadow_field.value(a, b))


def test_cli():
    from singleRun import single_run
    from singleRunNR import single_run_nr
    base = ["--ap-number", "1", "--gnb-number", "1", "--seed", "1", "-t", "0.1", "-r", "1",
            "--ap-pos", "0,0", "--gnb-pos", "30,0"]
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("log", exist_ok=True)
        r1 = runner.invoke(single_run, base + ["--pathloss-model", "umi", "--pathloss-shadowing"])
        r2 = runner.invoke(single_run, base + ["--shadowing-sigma-db", "6", "--shadowing-correlated",
                                               "--shadowing-decorr-m", "5"])
        r3 = runner.invoke(single_run, base + ["--shadowing-sigma-db", "6", "--shadowing-correlated",
                                               "--shadowing-decorr-m", "5"])
        nr = runner.invoke(single_run_nr, ["--gnb-number", "1", "--ues-per-gnb", "2", "--seed", "1", "-t", "0.05",
                                           "--pathloss-model", "uma", "--pathloss-shadowing"])
        bad = [runner.invoke(single_run, base + extra) for extra in (
            ["--pathloss-shadowing"],
            ["--shadowing-correlated"],
            ["--shadowing-sigma-db", "6", "--shadowing-decorr-m", "5"],
            ["--pathloss-model", "umi", "--pathloss-shadowing", "--shadowing-sigma-db", "4"])]
    for r in (r1, r2, nr):
        assert r.exit_code == 0, r.output[-300:]
    occ = lambda r: [l for l in r.output.splitlines() if "occupancy (Normalized)" in l]
    assert occ(r2) and occ(r2) == occ(r3)
    assert all(b.exit_code != 0 for b in bad)
# Rashed-Step 22.B-10-15-2026-end
