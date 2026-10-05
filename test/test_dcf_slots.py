# Rashed-Step pre_18.D-10-05-2026-start
"""
Step pre_18.D tests: ran/protocol/channel_access.py DcfChannelAccess -
Wi-Fi DCF (DIFS + backoff) on a shared global slot grid, with
event-driven sensing.

Small fake stations on a real Channel: each one waits DcfChannelAccess,
then "transmits" by registering an ActiveTx for a fixed duration. All
stations sit within a few metres, so each hears the others.
"""

import sys
import os
from types import SimpleNamespace

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import simpy

from channel.channel import Channel, ActiveTx
from ran.protocol.channel_access import DcfChannelAccess
from Times import Times

SLOT = Times.t_slot      # 9
DIFS = Times.t_difs      # 34
F = 5.18e9
DCF = DcfChannelAccess(SLOT, DIFS)


def _channel():
    env = simpy.Environment()
    return env, Channel(
        tx_queue=simpy.PriorityResource(env, capacity=1),
        tx_lock=simpy.Resource(env, capacity=1),
        n_of_stations=0, n_of_gNB=0, backoffs={},
        airtime_data={}, airtime_control={},
        airtime_data_NR={}, airtime_control_NR={},
    )


class _Station:
    def __init__(self, env, channel, name, pos):
        self.env, self.channel, self.name, self.pos = env, channel, name, pos
        self.config = SimpleNamespace(ed_threshold_dbm=-62.0, f_ghz=F, bandwidth_mhz=20.0)
        self.col = ""
        self.starts = []

    def current_pos(self):
        return self.pos

    def run(self, backoff_slots, frame_us=242, start_at=0):
        if start_at:
            yield self.env.timeout(start_at)
        yield from DCF.wait(self, backoff_slots)
        self.starts.append(self.env.now)
        tx = ActiveTx(tx_id=self.name, tx_pos=self.pos, tx_start=self.env.now, rx_pos=(0.0, 0.0),
                      tx_power_dbm=20.0, f_hz=F, pl_exp=3.0, t_end=self.env.now + frame_us, tech="WiFi")
        self.channel.register_tx(tx)
        yield self.env.timeout(frame_us)
        self.channel.unregister_tx(tx)


def _occupy(env, channel, start, end, pos=(1.0, 1.0), name="X"):
    def proc():
        yield env.timeout(start)
        tx = ActiveTx(tx_id=name, tx_pos=pos, tx_start=env.now, rx_pos=(0.0, 0.0),
                      tx_power_dbm=20.0, f_hz=F, pl_exp=3.0, t_end=end, tech="WiFi")
        channel.register_tx(tx)
        yield env.timeout(end - start)
        channel.unregister_tx(tx)
    env.process(proc())


def test_transmits_on_global_slot_grid_after_difs():
    """Idle channel, start at t=5: DIFS ends at 39, next global boundary 45,
    then 3 slots -> transmit at 72 (a multiple of 9)."""
    env, ch = _channel()
    a = _Station(env, ch, "A", (0.0, 0.0))
    env.process(a.run(3, start_at=5))
    env.run(until=1000)
    assert a.starts == [5 + DIFS + 6 + 3 * SLOT] == [72]
    assert a.starts[0] % SLOT == 0


def test_same_slot_means_same_instant_collision():
    """Two stations whose backoff ends on the same global boundary both
    transmit at that exact instant and collide - even though they
    arrived at different times: A at t=1 (DIFS ends 35 -> boundary 36,
    4 slots -> 72), B at t=3 (DIFS ends 37 -> boundary 45, 3 slots ->
    72). Neither can sense the other before then."""
    env, ch = _channel()
    a = _Station(env, ch, "A", (0.0, 0.0))
    b = _Station(env, ch, "B", (2.0, 0.0))
    env.process(a.run(4, start_at=1))
    env.process(b.run(3, start_at=3))
    env.run(until=2000)
    assert a.starts == b.starts == [72]


def test_later_slot_freezes_and_never_overlaps():
    """B's backoff ends one slot after A's: B senses A and defers, then
    does a fresh DIFS after A's frame - no overlap."""
    env, ch = _channel()
    a = _Station(env, ch, "A", (0.0, 0.0))
    b = _Station(env, ch, "B", (2.0, 0.0))
    env.process(a.run(2, frame_us=242))
    env.process(b.run(3, frame_us=242))
    env.run(until=5000)
    (ta,), (tb,) = a.starts, b.starts
    assert tb >= ta + 242 + DIFS      # waited out A's frame plus a fresh DIFS
    assert tb % SLOT == 0
    # remaining backoff after the freeze was 1 slot
    a_end = ta + 242
    first_boundary = a_end + DIFS + ((SLOT - (a_end + DIFS) % SLOT) % SLOT)
    assert tb == first_boundary + 1 * SLOT


def test_transmission_starting_mid_slot_is_noticed_immediately():
    """Old behaviour checked only at slot starts; now a transmission that
    starts 3us into a slot freezes the station straight away, and it
    resumes only after a fresh DIFS once the channel clears."""
    env, ch = _channel()
    a = _Station(env, ch, "A", (0.0, 0.0))
    env.process(a.run(5))                 # grid: DIFS to 34 -> boundary 36, slots 36..81
    _occupy(env, ch, 48, 300)             # starts 3us into the slot 45-54
    env.run(until=3000)
    (ta,) = a.starts
    # Slots done before the busy period: 36-45 only -> 4 left, fresh DIFS after 300.
    boundary = 300 + DIFS + ((SLOT - (300 + DIFS) % SLOT) % SLOT)
    assert ta == boundary + 4 * SLOT


def test_busy_during_difs_restarts_difs():
    env, ch = _channel()
    a = _Station(env, ch, "A", (0.0, 0.0))
    env.process(a.run(0))
    _occupy(env, ch, 20, 100)             # interrupts the first DIFS
    env.run(until=1000)
    (ta,) = a.starts
    assert ta >= 100 + DIFS and ta % SLOT == 0


def test_far_away_transmission_below_threshold_is_ignored():
    env, ch = _channel()
    a = _Station(env, ch, "A", (0.0, 0.0))
    env.process(a.run(3, start_at=5))
    _occupy(env, ch, 40, 400, pos=(5000.0, 0.0))   # far below -62 dBm
    env.run(until=1000)
    assert a.starts == [72]   # same as on an idle channel
# Rashed-Step pre_18.D-10-05-2026-end
