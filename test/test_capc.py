# Rashed-Step pre_20.D.1-10-08-2026-start
"""
Step pre_20.D.1 tests: 3GPP TS 37.213 channel access priority classes
(Config_NR.priority_class, CAPC_DL / CAPC_UL, NrUE uplink table).
"""

import os
import sys
from types import SimpleNamespace

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest
import simpy
from click.testing import CliRunner

from analysis.laa_fairness import run_case
from nru.nru import Config_NR
from nru.ue import NrUE
from ran.protocol.channel_access import CAPC_DL, CAPC_UL, LbtChannelAccess
from singleRun import single_run


def test_class_sets_the_ts_37213_downlink_values():
    assert CAPC_DL == {1: (1, 3, 7, 2), 2: (1, 7, 15, 3), 3: (3, 15, 63, 8), 4: (7, 15, 1023, 8)}
    for p, (m, cmin, cmax, mcot) in CAPC_DL.items():
        c = Config_NR(cw_min=99, cw_max=99, mcot=1, priority_class=p)    # the class wins
        assert (c.M, c.cw_min, c.cw_max, c.mcot) == (m, cmin, cmax, mcot)
    d = Config_NR()
    assert (d.M, d.cw_min, d.cw_max, d.mcot, d.priority_class) == (3, 15, 63, 6, None)
    with pytest.raises(ValueError):
        Config_NR(priority_class=5)


def test_ue_type1_lbt_uses_the_uplink_table():
    env = simpy.Environment()
    ue = NrUE("UE 1", (0.0, 0.0), "Gnb 1", uplink_enabled=True, env=env, channel=SimpleNamespace(airtime_data_NR={}, airtime_control_NR={}),
              config_nr=Config_NR(priority_class=2))
    assert (ue.lbt_m, ue.cw_min, ue.cw_max, ue.ul_mcot_ms) == CAPC_UL[2] == (2, 7, 15, 4)
    plain = NrUE("UE 2", (0.0, 0.0), "Gnb 1", uplink_enabled=True, env=env, channel=SimpleNamespace(airtime_data_NR={}, airtime_control_NR={}), config_nr=Config_NR())
    assert plain.lbt_m is None and (plain.cw_min, plain.cw_max, plain.ul_mcot_ms) == (15, 63, 6)


def _defer_time(lbt_m, M=3):
    env = simpy.Environment()
    ch = SimpleNamespace(is_busy=lambda *a, **k: False, state_changed=env.event())
    cfg = SimpleNamespace(deter_period=16, M=M, observation_slot_duration=9, ed_threshold_dbm=-72.0,
                          f_ghz=5.18e9, bandwidth_mhz=20.0, synchronization_slot_duration=1)
    node = SimpleNamespace(env=env, channel=ch, current_pos=lambda: (0.0, 0.0), name="n", col="",
                           failed_transmissions_in_row=0, cw_min=0, cw_max=0,      # no backoff slots
                           next_sync_slot_boundry=0, config_nr=cfg, lbt_m=lbt_m)
    env.process(LbtChannelAccess().wait(node))
    env.run()
    return env.now


def test_defer_period_follows_m_p():
    assert 43 <= _defer_time(None) <= 44              # config.M = 3: 16 + 3 x 9
    assert 25 <= _defer_time(1) <= 26                 # node's own m_p = 1: 16 + 9
    assert 79 <= _defer_time(7) <= 80                 # m_p = 7: 16 + 63


def test_mcot_caps_the_cot_length():
    # NR-U overloaded (50k pkt/s), Wi-Fi network far away: COTs run to
    # the class's MCOT - 2 ms for p=1, 3 ms for p=2, 8 ms for p=4.
    def mean_cot_us(p):
        r = run_case("nru", 10.0, 50000.0, 200.0, seed=1, sim_time_s=0.3,
                     nru_config=Config_NR(cot_model="slots", priority_class=p))
        t = r["fairness"]["tech"]["NRU"]
        return t["airtime_share"] * 0.3e6 / t["transmissions"]
    assert 1900.0 < mean_cot_us(1) <= 2000.0
    assert 2900.0 < mean_cot_us(2) <= 3000.0
    assert 6000.0 < mean_cot_us(4) <= 8000.0


def test_cli_flag():
    base = ["--ap-number", "1", "--gnb-number", "1", "--seed", "1", "-t", "0.05", "-r", "1"]
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("log", exist_ok=True)
        off = runner.invoke(single_run, base)
        on = runner.invoke(single_run, base + ["--nru-priority-class", "1"])
        bad = runner.invoke(single_run, base + ["--nru-priority-class", "5"])
    assert off.exit_code == 0 and on.exit_code == 0, (off.output[-300:], on.output[-300:])
    assert "N_gnbs=1 CW_MIN = 15 CW_MAX = 63" in off.output and "N_gnbs=1 CW_MIN = 3 CW_MAX = 7" in on.output
    assert bad.exit_code != 0
# Rashed-Step pre_20.D.1-10-08-2026-end
