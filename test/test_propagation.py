# Rashed-Step 22.A-10-15-2026-start
"""
Step 22.A tests: path-loss models (channel/propagation.py) and the single
Channel.rx_power_at() hook.
"""
import math
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest
import simpy
from click.testing import CliRunner

from channel.channel import ActiveTx, Channel
from channel.propagation import (PathLossSpec, Propagation, is_infrastructure, los_probability, path_loss_db,
                                 pathloss_spec_from_cli, walls_between)
from common.common_phy import rx_power_dbm

F = 5.18e9


def _channel(spec=None, seed=1):
    env = simpy.Environment()
    return Channel(simpy.PriorityResource(env, capacity=1), simpy.Resource(env, capacity=1), 1, 1, {}, {}, {}, {}, {},
                   propagation=Propagation(spec, seed) if spec else None)


def _tx(tx_id="AP 1", pos=(0.0, 0.0), rx=(10.0, 0.0), power=20.0):
    return ActiveTx(tx_id=tx_id, tx_pos=pos, tx_start=0, rx_pos=rx, tx_power_dbm=power, f_hz=F, pl_exp=3.0,
                    t_end=100, tech="WiFi")


def test_no_model_is_the_old_log_distance():
    ch = _channel()
    tx = _tx()
    assert ch.rx_power_at(tx, (10.0, 0.0)) == rx_power_dbm(20.0, 10.0, F, n=3.0, shadow_db=0.0)
    assert ch.link_rx_power_dbm("AP 1", (0.0, 0.0), (7.0, 3.0), 20.0, F, 3.0) == \
        rx_power_dbm(20.0, math.hypot(7, 3), F, n=3.0)


def test_inh_office_values():
    d3d = math.hypot(10.0, 1.5)
    los = 32.4 + 17.3 * math.log10(d3d) + 20 * math.log10(5.18)
    nlos = 38.3 * math.log10(d3d) + 17.30 + 24.9 * math.log10(5.18)
    assert path_loss_db("inh-office-mixed", 10.0, 3.0, 1.5, F, True) == pytest.approx(los)
    assert path_loss_db("inh-office-mixed", 10.0, 3.0, 1.5, F, False) == pytest.approx(max(los, nlos))
    assert los == pytest.approx(64.07, abs=0.01)


def test_umi_uma_continuous_at_breakpoint_and_nlos_above_los():
    for model, h_bs in (("umi", 10.0), ("uma", 25.0)):
        d_bp = 4 * (h_bs - 1) * 0.5 * 3.5e9 / 3e8
        below = path_loss_db(model, d_bp, h_bs, 1.5, 3.5e9, True)
        above = path_loss_db(model, d_bp + 1e-6, h_bs, 1.5, 3.5e9, True)
        assert above == pytest.approx(below, abs=0.05)     # 38.901 PL1 = PL2 at d'BP
        for d in (20.0, 100.0, 500.0):
            assert path_loss_db(model, d, h_bs, 1.5, 3.5e9, False) >= path_loss_db(model, d, h_bs, 1.5, 3.5e9, True)


def test_tgax_breakpoint_and_walls():
    d3d = math.hypot(20.0, 1.5)
    exp = 40.05 + 20 * math.log10(5.18 / 2.4) + 20 * math.log10(10.0) + 35 * math.log10(d3d / 10.0) + 7 * 2
    assert path_loss_db("tgax-enterprise", 20.0, 3.0, 1.5, F, True, walls=2) == pytest.approx(exp)
    assert walls_between((1.0, 1.0), (25.0, 1.0), 10.0) == 2
    assert walls_between((1.0, 1.0), (9.0, 9.0), 10.0) == 0
    p = Propagation(PathLossSpec("tgax-residential"))
    one_room = p.loss_db((1.0, 1.0), (9.0, 1.0), F, True, False)
    next_room = p.loss_db((1.0, 1.0), (11.0, 1.0), F, True, False)
    assert next_room - one_room > 5.0                      # a 5 dB wall plus distance


def test_los_probability():
    assert los_probability("inh-office-mixed", 1.0) == 1.0
    assert los_probability("inh-office-mixed", 10.0) == pytest.approx(0.32 * math.exp(-3.5 / 32.6))
    assert los_probability("inh-office-open", 30.0) == pytest.approx(math.exp(-25 / 70.8))
    assert los_probability("umi", 18.0) == 1.0
    assert los_probability("uma", 100.0) == pytest.approx(0.18 + math.exp(-100 / 63) * 0.82)


def test_link_los_state_is_reciprocal_stable_and_seeded():
    p = Propagation(PathLossSpec("inh-office-mixed"), seed=4)
    a, b = (0.0, 0.0), (30.0, 5.0)
    first = p.loss_db(a, b, F, True, False)
    assert p.loss_db(b, a, F, False, True) == first        # same LOS state and heights both ways
    assert p.loss_db(a, b, F, True, False) == first
    states = [Propagation(PathLossSpec("inh-office-mixed"), seed=s).is_los(a, b, 30.4) for s in range(40)]
    assert 0 < sum(states) < 40                            # LOS probability ~0.25 at 30 m
    forced = Propagation(PathLossSpec("inh-office-mixed", los_mode="los"))
    assert forced.is_los(a, b, 30.4) is True


def test_heights_follow_node_role():
    assert is_infrastructure("AP 2") and is_infrastructure("Gnb 1") and is_infrastructure("GnbNR 3")
    assert not is_infrastructure("STA 1-1") and not is_infrastructure("UE 1-1") and not is_infrastructure(None)
    ch = _channel(PathLossSpec("inh-office-mixed", los_mode="los"))
    d = 10.0
    ap_sta = 20.0 - path_loss_db("inh-office-mixed", d, 3.0, 1.5, F, True)
    ap_ap = 20.0 - path_loss_db("inh-office-mixed", d, 3.0, 3.0, F, True)
    assert ch.rx_power_at(_tx(), (d, 0.0)) == pytest.approx(ap_sta)              # downlink: STA at 1.5 m
    assert ch.rx_power_at(_tx(), (d, 0.0), rx_infra=True) == pytest.approx(ap_ap)  # AP senses AP


def test_sinr_interference_at_the_targets_receiver():
    ch = _channel(PathLossSpec("inh-office-mixed", los_mode="los"))
    target = _tx("AP 1", (0.0, 0.0), (5.0, 0.0))
    other = _tx("STA 2-1", (20.0, 0.0), (25.0, 0.0))
    ch.register_tx(other)
    s = 20.0 - path_loss_db("inh-office-mixed", 5.0, 3.0, 1.5, F, True)
    i = 20.0 - path_loss_db("inh-office-mixed", 15.0, 1.5, 1.5, F, True)          # STA -> STA, both 1.5 m
    sinr = ch.sinr_db(target, noise_dbm=-200.0)
    assert sinr == pytest.approx(s - i, abs=1e-6)


def test_spec_validation_and_cli_helper():
    assert pathloss_spec_from_cli(None) is None and pathloss_spec_from_cli("log-distance") is None
    with pytest.raises(ValueError):
        pathloss_spec_from_cli("log-distance", "los")
    with pytest.raises(ValueError):
        PathLossSpec("inh-office-mixed", room_size_m=10.0)  # walls are TGax only
    with pytest.raises(ValueError):
        PathLossSpec("free-space")
    spec = pathloss_spec_from_cli("uma", "nlos", 30.0, 2.0)
    p = Propagation(spec)
    assert (p.h_bs, p.h_ut) == (30.0, 2.0)


def test_cli_runs_and_is_reproducible():
    from singleRun import single_run
    from singleRunNR import single_run_nr
    runner = CliRunner()
    base = ["--ap-number", "1", "--gnb-number", "1", "--seed", "1", "-t", "0.1", "-r", "1",
            "--ap-pos", "0,0", "--gnb-pos", "35,0"]
    with runner.isolated_filesystem():
        os.makedirs("log", exist_ok=True)
        a = runner.invoke(single_run, base + ["--pathloss-model", "tgax-residential", "--tgax-room-size-m", "8"])
        b = runner.invoke(single_run, base + ["--pathloss-model", "tgax-residential", "--tgax-room-size-m", "8"])
        nr = runner.invoke(single_run_nr, ["--gnb-number", "1", "--ues-per-gnb", "2", "--seed", "1", "-t", "0.05",
                                           "--pathloss-model", "uma"])
        bad = runner.invoke(single_run, base + ["--bs-height-m", "5"])
    assert a.exit_code == 0, a.output[-300:]
    occ = [l for l in a.output.splitlines() if "occupancy (Normalized)" in l]
    assert occ and occ == [l for l in b.output.splitlines() if "occupancy (Normalized)" in l]
    assert nr.exit_code == 0, nr.output[-300:]
    assert bad.exit_code != 0
# Rashed-Step 22.A-10-15-2026-end
