# Rashed-Step 22.C-10-15-2026-start
"""
Step 22.C tests: flat block fading (channel/fading.py) and its use in
Channel.rx_power_at() for sensing and decoding.
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
from scipy.special import j0

from channel.channel import ActiveTx, Channel
from channel.fading import Fading
from channel.propagation import PathLossSpec, Propagation

F = 5.18e9
A, B = (0.0, 0.0), (12.3, 4.1)


def test_rayleigh_statistics_and_rician_mean():
    p = np.array([abs(Fading(s).diffuse(A, B, 0.0, F)) ** 2 for s in range(1500)])
    assert 0.9 < p.mean() < 1.1
    assert abs((p < 0.1).mean() - (1 - math.exp(-0.1))) < 0.03       # Rayleigh deep-fade probability
    assert abs((p < 1.0).mean() - (1 - math.exp(-1.0))) < 0.05
    r = np.array([10 ** (Fading(s).gain_db(A, B, 0.0, F, k_db=7.0) / 10) for s in range(1500)])
    assert 0.9 < r.mean() < 1.1
    assert (r < 0.1).mean() < 0.3 * (p < 0.1).mean()                   # LOS component: far fewer deep fades


def test_reciprocal_block_constant_and_doppler_correlated():
    f = Fading(3)
    assert f.diffuse(A, B, 100.0, F) == f.diffuse(B, A, 100.0, F)
    blk = f.block_us(F)
    assert 6000 < blk < 8000                                            # ~7.3 ms at 5.18 GHz, 1.2 km/h
    assert f.diffuse(A, B, 1.0, F) == f.diffuse(A, B, blk - 1.0, F)     # held over the block
    h0, h1 = [], []
    for s in range(1500):
        g = Fading(s)
        h0.append(g.diffuse(A, B, 0.0, F))
        h1.append(g.diffuse(A, B, 5 * blk, F))
    h0, h1 = np.array(h0), np.array(h1)
    rho = abs(np.mean(h0 * np.conj(h1))) / math.sqrt(np.mean(abs(h0) ** 2) * np.mean(abs(h1) ** 2))
    fd = (1.2 / 3.6) * F / 3e8
    assert rho == pytest.approx(abs(j0(2 * math.pi * fd * 5 * blk * 1e-6)), abs=0.08)


def test_movement_decorrelates_within_a_wavelength():
    lam = 3e8 / F
    h0, h1 = [], []
    for s in range(1500):
        g = Fading(s)
        h0.append(g.diffuse(A, B, 0.0, F))
        h1.append(g.diffuse(A, (B[0] + 0.38 * lam, B[1]), 0.0, F))   # first zero of J0 at 0.38 lambda
    h0, h1 = np.array(h0), np.array(h1)
    assert abs(np.mean(h0 * np.conj(h1))) / np.mean(abs(h0) ** 2) < 0.15


def _channel(**kw):
    env = simpy.Environment()
    return Channel(simpy.PriorityResource(env, capacity=1), simpy.Resource(env, capacity=1), 1, 1, {}, {}, {}, {}, {},
                   **kw)


def _tx(tx_id="AP 1", pos=A, rx=B):
    return ActiveTx(tx_id=tx_id, tx_pos=pos, tx_start=0, rx_pos=rx, tx_power_dbm=20.0, f_hz=F, pl_exp=3.0,
                    t_end=1e9, tech="WiFi")


def test_channel_applies_the_same_gain_to_sensing_and_decoding():
    plain, faded = _channel(), _channel(fading=Fading(5))
    tx = _tx()
    g = faded.fading.gain_db(A, B, 0.0, F)
    assert faded.rx_power_at(tx, B) == pytest.approx(plain.rx_power_at(tx, B) + g)
    faded.register_tx(tx)
    assert faded.sensed_energy_dbm(B) == pytest.approx(faded.rx_power_at(tx, B))      # sensing sees the fade
    sinr = faded.sinr_db(tx, noise_dbm=-90.0)
    assert sinr == pytest.approx(faded.rx_power_at(tx, B) + 90.0, abs=1e-9)          # decoding too
    up = _tx("STA 1-1", B, A)
    assert faded.rx_power_at(up, A) == pytest.approx(faded.rx_power_at(tx, B))       # reciprocal (same power)


def test_rician_k_by_link_state():
    assert Propagation(PathLossSpec("inh-office-mixed", los_mode="los")).rician_k_db(A, B) == 7.0
    assert Propagation(PathLossSpec("umi", los_mode="los")).rician_k_db(A, B) == 9.0
    assert Propagation(PathLossSpec("inh-office-mixed", los_mode="nlos")).rician_k_db(A, B) is None
    tg = Propagation(PathLossSpec("tgax-enterprise"))
    assert tg.rician_k_db(A, (8.0, 0.0)) == 3.0 and tg.rician_k_db(A, (15.0, 0.0)) is None
    ch = _channel(propagation=Propagation(PathLossSpec("inh-office-mixed", los_mode="los")), fading=Fading(2))
    no_f = _channel(propagation=Propagation(PathLossSpec("inh-office-mixed", los_mode="los")))
    assert ch.rx_power_at(_tx(), B) == pytest.approx(no_f.rx_power_at(_tx(), B) + ch.fading.gain_db(A, B, 0.0, F, 7.0))


def test_cli():
    from singleRun import single_run
    from singleRunNR import single_run_nr
    base = ["--ap-number", "1", "--gnb-number", "1", "--seed", "1", "-t", "0.1", "-r", "1",
            "--ap-pos", "0,0", "--gnb-pos", "30,0"]
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("log", exist_ok=True)
        r1 = runner.invoke(single_run, base + ["--fading", "--fading-k-db", "3", "--fading-env-speed-mps", "1"])
        r2 = runner.invoke(single_run, base + ["--fading", "--fading-k-db", "3", "--fading-env-speed-mps", "1"])
        r3 = runner.invoke(single_run, base + ["--pathloss-model", "tgax-residential", "--fading"])
        nr = runner.invoke(single_run_nr, ["--gnb-number", "1", "--ues-per-gnb", "2", "--seed", "1", "-t", "0.05",
                                           "--pathloss-model", "uma", "--fading"])
        bad = [runner.invoke(single_run, base + extra) for extra in (
            ["--fading-k-db", "3"], ["--fading", "--fading-env-speed-mps", "0"],
            ["--pathloss-model", "umi", "--fading", "--fading-k-db", "3"])]
    for r in (r1, r3, nr):
        assert r.exit_code == 0, r.output[-300:]
    occ = lambda r: [l for l in r.output.splitlines() if "occupancy (Normalized)" in l]
    assert occ(r1) and occ(r1) == occ(r2)
    assert all(b.exit_code != 0 for b in bad)
# Rashed-Step 22.C-10-15-2026-end
