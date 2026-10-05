# Rashed-Step pre_18.A-10-04-2026-start
"""
Step pre_18.A tests: channel.sinr_db() hybrid interference rule
(Wi-Fi targets: any overlap at full power; others: time-averaged).

Before: only transmissions still on the air when SINR was evaluated (at
the target's end) counted, at full power - an interferer that ended
first was ignored. Now every transmission that overlapped the target at
any point counts, weighted by the fraction of the target it covered.
Each test compares against a hand-computed expected SINR.
"""

import math
import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import simpy

from channel.channel import Channel, ActiveTx, TxSnapshot
from common.common_phy import dbm_to_mw, thermal_noise_dbm

F = 5.18e9


def _channel():
    env = simpy.Environment()
    return env, Channel(
        tx_queue=simpy.PriorityResource(env, capacity=1),
        tx_lock=simpy.Resource(env, capacity=1),
        n_of_stations=0, n_of_gNB=0, backoffs={},
        airtime_data={}, airtime_control={},
        airtime_data_NR={}, airtime_control_NR={},
    )


def _tx(tx_id, start, end, pos, rx_pos=(0.0, 0.0), power=20.0, tech="NRU", bw=20.0):
    return ActiveTx(tx_id=tx_id, tx_pos=pos, tx_start=start, rx_pos=rx_pos,
                    tx_power_dbm=power, f_hz=F, pl_exp=3.0, t_end=end, tech=tech,
                    bandwidth_mhz=bw)


def _expected_sinr(channel, target, interferers_with_weights):
    s = dbm_to_mw(channel._rx_pwr_dbm(target, target.rx_pos))
    i = sum(dbm_to_mw(channel._rx_pwr_dbm(o, target.rx_pos)) * w for o, w in interferers_with_weights)
    n = dbm_to_mw(thermal_noise_dbm(target.bandwidth_mhz, target.noise_figure_db))
    return 10 * math.log10(s / (i + n))


def test_interferer_that_ended_first_now_counts_weighted():
    env, ch = _channel()
    target = _tx("gNB", 0, 1000, (10.0, 0.0))
    ch.register_tx(target)
    blip = _tx("AP", 100, 350, (3.0, 0.0), tech="WiFi")   # 25% of the target
    ch.register_tx(blip)
    ch.unregister_tx(blip)                                  # gone before target ends
    assert blip not in ch.active_txs
    got = ch.sinr_db(target)
    assert math.isclose(got, _expected_sinr(ch, target, [(blip, 0.25)]), rel_tol=1e-12)
    no_interference = _expected_sinr(ch, target, [])
    assert got < no_interference  # it used to be exactly this


def test_full_overlap_counts_at_full_power_as_before():
    env, ch = _channel()
    target = _tx("UE", 100, 900, (10.0, 0.0))
    cover = _tx("AP", 0, 1000, (5.0, 0.0), tech="WiFi")
    ch.register_tx(cover)
    ch.register_tx(target)
    assert ch.sinr_db(target) == _expected_sinr(ch, target, [(cover, 1.0)])


def test_late_starting_interferer_still_on_air_is_now_partial():
    """The 17.G trace case: a Wi-Fi frame starting near the end of a
    2975us NR-U uplink used to count at full power."""
    env, ch = _channel()
    target = _tx("UE", 0, 2975, (10.0, 0.0))
    ch.register_tx(target)
    late = _tx("AP", 2800, 3042, (3.0, 0.0), tech="WiFi")
    ch.register_tx(late)
    w = 175 / 2975
    assert math.isclose(ch.sinr_db(target), _expected_sinr(ch, target, [(late, w)]), rel_tol=1e-12)


def test_several_interferers_each_weighted():
    env, ch = _channel()
    target = _tx("gNB", 0, 6000, (10.0, 0.0))
    ch.register_tx(target)
    frames = []
    for k, start in enumerate((500, 2000, 4000)):
        f = _tx(f"AP{k}", start, start + 242, (4.0 + k, 0.0), tech="WiFi")
        ch.register_tx(f)
        ch.unregister_tx(f)
        frames.append((f, 242 / 6000))
    assert math.isclose(ch.sinr_db(target), _expected_sinr(ch, target, frames), rel_tol=1e-12)


def test_unregistered_trial_estimate_uses_what_is_on_air():
    """Licensed NR's scheduler estimates SINR on a never-registered trial
    transmission - it must still see current transmissions."""
    env, ch = _channel()
    other = _tx("gNB2", 0, 500, (8.0, 0.0), tech="NR")
    ch.register_tx(other)
    trial = _tx("gNB1", 0, 500, (10.0, 0.0), tech="NR")
    assert trial.overlap_history == []
    assert ch.sinr_db(trial) == _expected_sinr(ch, trial, [(other, 1.0)])


def test_interferer_on_air_and_in_history_counted_once():
    env, ch = _channel()
    target = _tx("gNB", 0, 1000, (10.0, 0.0))
    ch.register_tx(target)
    other = _tx("AP", 0, 1000, (4.0, 0.0), tech="WiFi")
    ch.register_tx(other)
    assert len(target.overlap_history) == 1 and other in ch.active_txs
    assert ch.sinr_db(target) == _expected_sinr(ch, target, [(other, 1.0)])


def test_history_holds_plain_snapshots_not_live_objects():
    env, ch = _channel()
    a = _tx("A", 0, 1000, (10.0, 0.0))
    b = _tx("B", 500, 1500, (12.0, 0.0))
    ch.register_tx(a)
    ch.register_tx(b)
    assert a.overlap_history == [TxSnapshot.of(b)] and b.overlap_history == [TxSnapshot.of(a)]
    assert all(isinstance(x, TxSnapshot) for x in a.overlap_history + b.overlap_history)


def test_non_overlapping_and_same_id_transmissions_ignored():
    env, ch = _channel()
    before = _tx("AP", 0, 100, (4.0, 0.0), tech="WiFi")
    ch.register_tx(before)
    target = _tx("gNB", 100, 1000, (10.0, 0.0))   # starts exactly as `before` ends
    ch.register_tx(target)
    own_previous = _tx("gNB", 0, 1000, (10.0, 0.0))
    ch.register_tx(own_previous)
    assert target.overlap_history == []
    assert ch.sinr_db(target) == _expected_sinr(ch, target, [])

def test_same_named_allocations_in_one_slot_each_count():
    """Licensed NR registers one ActiveTx per UE allocation, all named
    after the gNB with the same slot timing - they are different
    transmissions and must not be merged (found by the pre_18.B
    before/after run: 2-gNB PF throughput changed until fixed)."""
    env, ch = _channel()
    target = _tx("GnbNR 1", 0, 500, (10.0, 0.0), tech="NR")
    a = _tx("GnbNR 2", 0, 500, (8.0, 0.0), tech="NR")
    b = _tx("GnbNR 2", 0, 500, (8.0, 0.0), tech="NR")
    for t in (target, a, b):
        ch.register_tx(t)
    assert ch.sinr_db(target) == _expected_sinr(ch, target, [(a, 1.0), (b, 1.0)])


def test_wifi_target_counts_any_overlap_at_full_power():
    """Hybrid rule: a Wi-Fi frame is one decode unit - an interferer that
    covered only part of it (even one that already ended) counts fully."""
    env, ch = _channel()
    frame = _tx("AP 1", 0, 242, (10.0, 0.0), tech="WiFi")
    ch.register_tx(frame)
    hit = _tx("AP 2", 150, 392, (4.0, 0.0), tech="WiFi")   # covers 38% of the frame
    early = _tx("gNB", -100, 60, (6.0, 0.0), tech="NRU")    # ended after 25%
    ch.register_tx(hit)
    ch.register_tx(early)
    ch.unregister_tx(early)
    assert ch.sinr_db(frame) == _expected_sinr(ch, frame, [(hit, 1.0), (early, 1.0)])


def test_nru_target_hit_by_wifi_frame_is_time_averaged():
    """...while an NR-U burst hit by the same kind of frame only takes the
    covered fraction."""
    env, ch = _channel()
    burst = _tx("gNB", 0, 6000, (10.0, 0.0), tech="NRU")
    ch.register_tx(burst)
    frame = _tx("AP 1", 3000, 3242, (4.0, 0.0), tech="WiFi")
    ch.register_tx(frame)
    ch.unregister_tx(frame)
    assert math.isclose(ch.sinr_db(burst), _expected_sinr(ch, burst, [(frame, 242 / 6000)]), rel_tol=1e-12)
# Rashed-Step pre_18.A-10-04-2026-end
