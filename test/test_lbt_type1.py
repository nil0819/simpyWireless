# Rashed-Step pre_18.E-10-05-2026-start
"""
Step pre_18.E tests: ran/protocol/channel_access.py LbtChannelAccess -
NR-U Type 1 channel access (3GPP TS 37.213): a full defer period Td
(16 + 3 x 9 = 43us) sensed idle before the countdown AND again after
every busy period; event-driven sensing; then the gap to the next sync
boundary (freeze on busy, resume).

The backoff draw is pinned (monkeypatched generate_backoff_slots) and the
sync slot is 1us with the boundary in the past, so the gap is always
exactly 1us - each test checks the exact moment wait() returns.
"""

import sys
import os
from types import SimpleNamespace

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import simpy

import ran.protocol.channel_access as ca
from channel.channel import Channel, ActiveTx

F = 5.18e9
TD = 16 + 3 * 9   # 43
SLOT = 9
GAP = 1


def _channel():
    env = simpy.Environment()
    return env, Channel(
        tx_queue=simpy.PriorityResource(env, capacity=1),
        tx_lock=simpy.Resource(env, capacity=1),
        n_of_stations=0, n_of_gNB=0, backoffs={},
        airtime_data={}, airtime_control={},
        airtime_data_NR={}, airtime_control_NR={},
    )


def _node(env, channel):
    cfg = SimpleNamespace(deter_period=16, M=3, observation_slot_duration=SLOT,
                          ed_threshold_dbm=-72.0, f_ghz=F, bandwidth_mhz=20.0,
                          synchronization_slot_duration=1)
    return SimpleNamespace(env=env, channel=channel, name="Gnb 1", col="",
                           current_pos=lambda: (0.0, 0.0), config_nr=cfg,
                           failed_transmissions_in_row=0, cw_min=15, cw_max=63,
                           next_sync_slot_boundry=0)


def _occupy(env, channel, start, end, pos=(1.0, 0.0)):
    def proc():
        yield env.timeout(start)
        tx = ActiveTx(tx_id="AP 1", tx_pos=pos, tx_start=env.now, rx_pos=(2.0, 0.0),
                      tx_power_dbm=20.0, f_hz=F, pl_exp=3.0, t_end=end, tech="WiFi")
        channel.register_tx(tx)
        yield env.timeout(end - start)
        channel.unregister_tx(tx)
    env.process(proc())


def _run(n_slots, busy=(), monkeypatch=None, until=5000):
    monkeypatch.setattr(ca, "generate_backoff_slots", lambda *a: n_slots)
    env, ch = _channel()
    node = _node(env, ch)
    for start, end in busy:
        _occupy(env, ch, start, end)
    done = []

    def proc():
        yield from ca.LbtChannelAccess().wait(node)
        done.append(env.now)
    env.process(proc())
    env.run(until=until)
    return done


def test_idle_channel_defer_then_countdown_then_gap(monkeypatch):
    assert _run(5, monkeypatch=monkeypatch) == [TD + 5 * SLOT + GAP]   # 89


def test_busy_mid_countdown_freezes_and_redoes_full_defer(monkeypatch):
    """Countdown slots start at 43: 43-52 done, busy at 60 (mid-slot,
    noticed at once) -> 4 left. After the channel clears at 200: a full
    43us defer again, then 4 slots, then the 1us gap -> 280.
    (The old code resumed the leftover countdown with no new defer.)"""
    assert _run(5, busy=[(60, 200)], monkeypatch=monkeypatch) == [200 + TD + 4 * SLOT + GAP]


def test_busy_during_defer_restarts_it(monkeypatch):
    assert _run(2, busy=[(20, 100)], monkeypatch=monkeypatch) == [100 + TD + 2 * SLOT + GAP]


def test_busy_during_gap_pauses_and_resumes_remaining_gap(monkeypatch):
    """Gap semantics unchanged: busy pauses it, the rest resumes (no new
    defer). Sync slot 1000us, boundary at 1000: backoff ends at 61, gap
    939us; busy 500-700 -> 500 - 61 = 439 done, 500 left -> 700 + 500."""
    monkeypatch.setattr(ca, "generate_backoff_slots", lambda *a: 2)
    env, ch = _channel()
    node = _node(env, ch)
    node.config_nr.synchronization_slot_duration = 1000
    node.next_sync_slot_boundry = 1000
    _occupy(env, ch, 500, 700)
    done = []

    def proc():
        yield from ca.LbtChannelAccess().wait(node)
        done.append(env.now)
    env.process(proc())
    env.run(until=5000)
    assert done == [1200]


def test_far_transmission_ignored(monkeypatch):
    monkeypatch.setattr(ca, "generate_backoff_slots", lambda *a: 5)
    env, ch = _channel()
    node = _node(env, ch)
    _occupy(env, ch, 60, 200, pos=(5000.0, 0.0))
    done = []

    def proc():
        yield from ca.LbtChannelAccess().wait(node)
        done.append(env.now)
    env.process(proc())
    env.run(until=5000)
    assert done == [TD + 5 * SLOT + GAP]
# Rashed-Step pre_18.E-10-05-2026-end
