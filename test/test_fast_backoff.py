# Rashed-Step 24.C-10-19-2026-start
"""
Step 24.C tests: the batched backoff countdown (countdown_slots, used when
Channel.static_sensing) counts the same slots as the per-slot loop, and
run_simulation only enables it where sensing can't change between channel
events.
"""
import os
import sys
from types import SimpleNamespace

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest
import simpy

from channel.channel import ActiveTx, Channel
from ran.protocol.channel_access import countdown_slots, sense_idle_for

SLOT = 9.0


def _run(mode, slots, busy_at, start=100.0):
    env = simpy.Environment()
    ch = Channel(simpy.PriorityResource(env, capacity=1), simpy.Resource(env, capacity=1), 1, 1, {}, {}, {}, {}, {})
    node = SimpleNamespace(env=env, channel=ch, name="AP 1")
    busy = lambda: ch.is_busy((0.0, 0.0), -62.0, exclude_tx_id="AP 1")
    out = {}

    def counter():
        yield env.timeout(start)
        if mode == "batched":
            left = yield from countdown_slots(node, slots, SLOT, busy)
        else:
            left = slots
            while left > 0:
                if not (yield from sense_idle_for(node, SLOT, busy)):
                    break
                left -= 1
        out["left"], out["t"] = left, env.now

    def other():
        yield env.timeout(busy_at)
        ch.register_tx(ActiveTx(tx_id="AP 2", tx_pos=(1.0, 0.0), tx_start=env.now, rx_pos=(2.0, 0.0),
                                tx_power_dbm=20.0, f_hz=5.18e9, pl_exp=3.0, t_end=env.now + 500.0, tech="WiFi"))

    env.process(counter())
    env.process(other())
    env.run(until=start + slots * SLOT + 1000)
    return out["left"], out["t"]


@pytest.mark.parametrize("busy_at", [50.0, 100.0, 104.0, 109.0, 113.0, 136.0, 140.5, 145.0, 190.0, 300.0])
def test_same_slots_as_per_slot_loop(busy_at):
    # 10 slots from t=100: boundaries 109, 118, ..., 190 - busy before the
    # start, at it, inside a slot, exactly on a boundary, at the last
    # boundary and never (300).
    assert _run("batched", 10, busy_at) == _run("perslot", 10, busy_at)


def test_static_sensing_only_without_fading_mobility_ofdma():
    import simulation
    seen = []
    orig = Channel.__init__

    def spy(self, *a, **k):
        orig(self, *a, **k)
        seen.append(self)
    Channel.__init__ = spy
    from click.testing import CliRunner
    from singleRun import single_run
    base = ["--ap-number", "1", "--gnb-number", "1", "--seed", "1", "-t", "0.02", "-r", "1"]
    try:
        flags = []
        for extra in ([], ["--fading"], ["--sta-mobility-speed-mps", "1"], ["--wifi-phy", "he", "--wifi-ofdma"]):
            seen.clear()
            r = CliRunner().invoke(single_run, base + extra)
            assert r.exit_code == 0, r.output[-300:]
            flags.append(seen[-1].static_sensing)
    finally:
        Channel.__init__ = orig
    assert flags == [True, False, False, False]
# Rashed-Step 24.C-10-19-2026-end
