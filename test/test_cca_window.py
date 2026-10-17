# Rashed-Step 23.A-10-17-2026-start
"""
Step 23.A tests: the collision window (Channel.cca_detect_us,
--cca-detect-us) - a transmission is invisible to channel sensing for its
first N us, so nodes starting within N us of each other collide.
"""
import os
import re
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import simpy
from click.testing import CliRunner

from channel.channel import ActiveTx, Channel


def _channel(env, **kw):
    return Channel(simpy.PriorityResource(env, capacity=1), simpy.Resource(env, capacity=1), 1, 1, {}, {}, {}, {}, {},
                   **kw)


def _tx(env):
    return ActiveTx(tx_id="AP 1", tx_pos=(0.0, 0.0), tx_start=env.now, rx_pos=(5.0, 0.0), tx_power_dbm=20.0,
                    f_hz=5.18e9, pl_exp=3.0, t_end=env.now + 100.0, tech="WiFi")


def test_detectable_only_after_the_window():
    seen = {}

    def probe(env, ch, label):
        yield env.timeout(10.0)
        ch.register_tx(_tx(env))
        for t in (0.0, 3.0, 5.9, 6.0, 50.0):
            yield env.timeout(10.0 + t - env.now)
            seen[(label, t)] = ch.is_busy((1.0, 0.0), -62.0)

    for label, kw in (("instant", {}), ("window", {"cca_detect_us": 6.0})):
        env = simpy.Environment()
        env.process(probe(env, _channel(env, **kw), label))
        env.run()
    assert all(seen[("instant", t)] for t in (0.0, 3.0, 5.9, 6.0, 50.0))
    assert not seen[("window", 0.0)] and not seen[("window", 3.0)] and not seen[("window", 5.9)]
    assert seen[("window", 6.0)] and seen[("window", 50.0)]


def test_waiting_nodes_are_woken_when_it_becomes_detectable():
    env = simpy.Environment()
    ch = _channel(env, cca_detect_us=6.0)
    woke = []

    def waiter():
        while not ch.is_busy((1.0, 0.0), -62.0):
            yield ch.state_changed
            woke.append(env.now)

    def sender():
        yield env.timeout(20.0)
        ch.register_tx(_tx(env))

    env.process(waiter())
    env.process(sender())
    env.run(until=100)
    assert woke and woke[-1] == 26.0                        # registered at 20, busy from 26


def test_cli_wifi_nru_collisions_appear():
    from singleRun import single_run
    base = ["--ap-number", "1", "--gnb-number", "1", "--seed", "1", "-t", "3", "-r", "1", "--ap-pos", "2,0",
            "--gnb-pos", "10,0", "--wifi_cw_min", "31", "--wifi_cw_max", "31", "--nru_cw_min", "31",
            "--nru_cw_max", "31", "--mcot", "6", "--wifi-packet-size-bytes", "36286"]
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("log", exist_ok=True)
        instant = runner.invoke(single_run, base)
        window = runner.invoke(single_run, base + ["--cca-detect-us", "6"])
        bad = runner.invoke(single_run, base + ["--cca-detect-us", "0"])
    fails = lambda r: int(re.search(r"N_stations:=1 .*FAILED_TRANSMISSIONS: (\d+)", r.output).group(1))
    assert instant.exit_code == 0 and window.exit_code == 0, window.output[-300:]
    assert fails(window) > fails(instant)                   # Wi-Fi/NR-U starts within 6 us now collide
    assert bad.exit_code != 0
# Rashed-Step 23.A-10-17-2026-end
