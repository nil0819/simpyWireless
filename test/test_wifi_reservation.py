# Rashed-Step pre_20.D.3-10-08-2026-start
"""
Step pre_20.D.3 tests: making NR-U COTs visible to Wi-Fi -
Config_NR.wifi_reservation ("preamble" / "cts_to_self"), the channel's
NAV reservations.
"""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest
import simpy
from click.testing import CliRunner

from analysis.laa_fairness import run_case
from channel.channel import ActiveTx, Channel
from nru.nru import Config_NR, CTS_TO_SELF_US
from singleRun import single_run


def _channel():
    env = simpy.Environment()
    return env, Channel(simpy.PriorityResource(env, capacity=1), simpy.Resource(env, capacity=1), 1, 1, {}, {}, {}, {}, {})


def test_nav_is_honoured_in_range_and_expires():
    env, ch = _channel()
    # NR-U gNB at (0,0), 23 dBm: -82 dBm reached at ~87.6 m (n=3, 5.18 GHz).
    ch.set_nav(ActiveTx(tx_id="Gnb 1", tx_pos=(0.0, 0.0), rx_pos=(0.0, 0.0), tx_start=0.0, tx_power_dbm=23.0,
                        f_hz=5.18e9, pl_exp=3.0, t_end=1000.0, tech="NRU"))
    assert ch.is_busy_wifi((30.0, 0.0), -62.0, -82.0)          # nothing on the air, NAV only
    assert not ch.is_busy_wifi((120.0, 0.0), -62.0, -82.0)     # out of decoding range
    assert not ch.is_busy_wifi((30.0, 0.0), -62.0, -82.0, exclude_tx_id="Gnb 1")
    woke = []

    def waiter():
        while ch.is_busy_wifi((30.0, 0.0), -62.0, -82.0):
            yield ch.state_changed
        woke.append(env.now)
    env.process(waiter())
    env.run()
    assert woke == [1000.0]                                      # the expiry wakes waiting nodes


def test_config_validation():
    assert Config_NR().wifi_reservation is None
    Config_NR(wifi_reservation="preamble")                       # any COT model
    with pytest.raises(ValueError):
        Config_NR(wifi_reservation="cts_to_self")                # burst model
    with pytest.raises(ValueError):
        Config_NR(cot_model="slots", wifi_reservation="rts")


def _case(mode, d=25.0, seed=1, **kw):
    return run_case("nru", 1500.0, 2500.0, d, seed, 0.5,
                    nru_config=Config_NR(cot_model="slots", wifi_reservation=mode, **kw))


def test_wifi_defers_to_visible_cots_where_it_cannot_hear_nru():
    # 25 m: NR-U is below Wi-Fi's -62 dBm ED -> ~25-30% Wi-Fi failures;
    # with a preamble or a CTS-to-self Wi-Fi defers and they vanish.
    base = _case(None)["fairness"]["tech"]["WiFi"]["failure_ratio"]
    assert base > 0.15
    for mode in ("preamble", "cts_to_self"):
        assert _case(mode)["fairness"]["tech"]["WiFi"]["failure_ratio"] < 0.02


def test_cts_costs_airtime_but_not_cots():
    r = _case("cts_to_self", d=200.0)
    plain = _case(None, d=200.0)
    nru, nru0 = r["fairness"]["tech"]["NRU"], plain["fairness"]["tech"]["NRU"]
    # One CTS per COT, not counted as a transmission of its own; its
    # 44 us count as NR-U airtime.
    assert nru["transmissions"] == pytest.approx(nru0["transmissions"], rel=0.1)
    assert nru["airtime_share"] > nru0["airtime_share"]
    assert CTS_TO_SELF_US == 44.0


def test_cli():
    base = ["--ap-number", "1", "--gnb-number", "1", "--seed", "1", "-t", "0.05", "-r", "1",
            "--nru-cot-model", "slots"]
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("log", exist_ok=True)
        off = runner.invoke(single_run, base)
        on = runner.invoke(single_run, base + ["--wifi-preamble-detect", "--nru-wifi-reservation", "cts_to_self"])
        pre = runner.invoke(single_run, base + ["--wifi-preamble-detect", "--nru-wifi-reservation", "preamble"])
        bad = runner.invoke(single_run, base + ["--nru-wifi-reservation", "preamble"])
    assert off.exit_code == 0 and on.exit_code == 0 and pre.exit_code == 0, (on.output[-300:], pre.output[-300:])
    assert "CTS-to-self" not in off.output and "NRU CTS-to-self frames=" in on.output
    assert bad.exit_code != 0
# Rashed-Step pre_20.D.3-10-08-2026-end
