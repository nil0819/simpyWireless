# Rashed-Step 25.A-10-20-2026-start
"""
Step 25.A tests: 802.11ax spatial reuse - BSS colour + OBSS-PD in
Channel.is_busy_wifi, the transmit-power restriction, and the CLI.
"""
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest
import simpy
from click.testing import CliRunner

from channel.channel import ActiveTx, Channel


def _setup():
    env = simpy.Environment()
    ch = Channel(simpy.PriorityResource(env, capacity=1), simpy.Resource(env, capacity=1), 2, 0, {}, {}, {}, {}, {})
    ch.bss_color_of.update({"AP 1": 1, "STA 1-1": 1, "AP 2": 2, "STA 2-1": 2})
    return env, ch


def _tx(env, tx_id, pos, power=20.0, tech="WiFi", t_end=1000.0, **kw):
    return ActiveTx(tx_id=tx_id, tx_pos=pos, tx_start=env.now, rx_pos=(pos[0] + 1, pos[1]), tx_power_dbm=power,
                    f_hz=5.18e9, pl_exp=3.0, t_end=t_end, tech=tech, **kw)


def _busy(ch, obss=None):
    return ch.is_busy_wifi((0.0, 0.0), -62.0, -82.0, exclude_tx_id="AP 1", obss_pd_dbm=obss)


def test_inter_bss_below_level_is_ignored_and_caps_power():
    env, ch = _setup()
    t = _tx(env, "AP 2", (40.0, 0.0))                 # 20 dBm at 40 m, n=3: ~ -74.8 dBm at AP 1
    ch.register_tx(t)
    assert t.bss_color == 2
    assert _busy(ch) is True                            # preamble detection (-82) without OBSS-PD
    assert _busy(ch, obss=-82.0) is True                # level below the signal: still busy
    assert _busy(ch, obss=-72.0) is False               # below -72: ignored
    until, cap = ch.sr_cap["AP 1"]
    assert until == t.t_end and cap == pytest.approx(21.0 - (-72.0 + 82.0))
    mine = _tx(env, "AP 1", (0.0, 0.0), power=20.0)
    ch.register_tx(mine)
    assert mine.tx_power_dbm == pytest.approx(11.0) and ch.sr_stats["capped_tx"] == 1


def test_intra_bss_strong_and_non_wifi_still_block():
    env, ch = _setup()
    ch.register_tx(_tx(env, "STA 1-1", (40.0, 0.0)))   # same colour: never ignored
    assert _busy(ch, obss=-62.0) is True
    env2, ch2 = _setup()
    ch2.register_tx(_tx(env2, "AP 2", (5.0, 0.0)))     # ~ -54 dBm > -62: energy detection
    assert ch2.is_busy_wifi((0.0, 0.0), -62.0, -82.0, exclude_tx_id="AP 1", obss_pd_dbm=-62.0) is True
    env3, ch3 = _setup()
    cts = _tx(env3, "Gnb 1", (40.0, 0.0), tech="NRU", wifi_preamble=True)   # NR-U CTS-to-self: no colour
    ch3.register_tx(cts)
    assert cts.bss_color is None and _busy(ch3, obss=-62.0) is True


def test_power_cap_expires():
    env, ch = _setup()
    ch.register_tx(_tx(env, "AP 2", (40.0, 0.0), t_end=50.0))
    assert _busy(ch, obss=-72.0) is False

    def later():
        yield env.timeout(60.0)
        mine = _tx(env, "AP 1", (0.0, 0.0), power=20.0, t_end=200.0)
        ch.register_tx(mine)
        out["p"] = mine.tx_power_dbm
    out = {}
    env.process(later())
    env.run(until=100)
    assert out["p"] == 20.0                             # the ignored frame ended at 50 us


def test_cli():
    from singleRun import single_run
    base = ["--seed", "1", "-t", "0.2", "-r", "1", "--layout", "tgax-residential", "--layout-cols", "3",
            "--wifi-phy", "he", "--wifi-preamble-detect"]
    runner = CliRunner()
    with runner.isolated_filesystem():
        fixed = runner.invoke(single_run, base + ["--wifi-obss-pd-dbm", "-72"])
        auto = runner.invoke(single_run, base + ["--wifi-obss-pd-dbm", "auto", "--wifi-obss-pd-margin-db", "15"])
        bad = [runner.invoke(single_run, a) for a in (
            base + ["--wifi-obss-pd-dbm", "-50"],
            base[:-3] + ["--wifi-obss-pd-dbm", "-72"],                     # no HE / preamble detection
            base + ["--wifi-obss-pd-dbm", "loud"],
            base + ["--wifi-obss-pd-margin-db", "10"])]
    assert fixed.exit_code == 0 and auto.exit_code == 0, (fixed.output + auto.output)[-400:]
    assert "=== Wi-Fi Spatial Reuse (OBSS-PD) ===" in fixed.output
    assert "OBSS-PD -72.0 dBm, TX power cap when reusing 11.0 dBm" in fixed.output
    assert all(b.exit_code != 0 for b in bad)
# Rashed-Step 25.A-10-20-2026-end
