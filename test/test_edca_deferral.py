# Rashed-Step pre_21.B-10-11-2026-start
"""
Step pre_21.B tests: EDCA deferral - a fresh AIFS[AC] after every busy
period, backoff counted per slot on the global grid, residual backoff kept,
and agreement with Bianchi (EDCA with DCF parameters behaves like DCF).
"""

import contextlib
import io
import logging
import os
import statistics
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import simpy

import simulation
from channel.channel import ActiveTx, Channel
from common.packet import EdcaAcParams, QOS_TRAFFIC_CLASSES, TrafficConfig
from model import bianchi
from model.compare import _cluster_ap_positions
from nru.nru import Config_NR
from wifi.wifi import Config, WiFi


class _Idle(WiFi):
    def start(self):
        return
        yield

    def start_edca(self):
        return
        yield


class _Sta:
    name = "STA 1-1"

    def current_pos(self):
        return (1.0, 0.0)


def _ap(params, only="best_effort"):
    env = simpy.Environment()
    ch = Channel(simpy.PriorityResource(env, capacity=1), simpy.Resource(env, capacity=1), 1, 0, {}, {}, {}, {}, {})
    ap = _Idle(env, "AP 1", ch, (0.0, 0.0), [_Sta()], Config(qos_enabled=True, edca_params=params))
    ap._refresh_ac_frame(only)
    return env, ch, ap


def _blocker(ch, t0, t1):
    tx = ActiveTx(tx_id="X", tx_pos=(2.0, 0.0), rx_pos=(3.0, 0.0), tx_start=t0, tx_power_dbm=20.0, f_hz=5.18e9,
                  pl_exp=3.0, t_end=t1, tech="WiFi")
    ch.register_tx(tx)
    return tx


def _wait(env, ap):
    out = []

    def go():
        out.append((yield from ap.wait_back_off_edca()))
        out.append(env.now)
    env.process(go())
    return out


def test_fresh_aifs_after_a_busy_period_then_the_slot_grid():
    params = {ac: EdcaAcParams(cw_min=0, cw_max=0, aifsn=7) for ac in QOS_TRAFFIC_CLASSES}   # no backoff
    env, ch, ap = _ap(params)
    tx = _blocker(ch, 0.0, 1000.0)

    def end():
        yield env.timeout(1000.0)
        ch.unregister_tx(tx)
    env.process(end())
    out = _wait(env, ap)
    env.run(until=3000)
    # idle from 1000 us: AIFS[7] = 79 us -> 1079, next 9 us boundary 1080
    assert out == ["best_effort", 1080.0]


def test_residual_backoff_is_kept_across_a_busy_period():
    params = {ac: EdcaAcParams(cw_min=15, cw_max=15, aifsn=2) for ac in QOS_TRAFFIC_CLASSES}
    env, ch, ap = _ap(params)
    draws = []
    ap.generate_new_back_off_slots_edca = lambda ac: draws.append(ac) or 10
    out = _wait(env, ap)

    def interrupt():
        # idle from 0: AIFS 34 -> counting from 36; after 5 slots (81 us) busy for 500 us
        yield env.timeout(81.0)
        tx = _blocker(ch, 81.0, 581.0)
        yield env.timeout(500.0)
        ch.unregister_tx(tx)
    env.process(interrupt())
    env.run(until=3000)
    # idle again from 581: AIFS 34 -> 615, grid 621, the 5 remaining slots -> 666
    assert out == ["best_effort", 666.0] and draws == ["best_effort"]


def test_edca_with_dcf_parameters_matches_bianchi():
    logging.disable(logging.CRITICAL)
    dcf_like = {ac: EdcaAcParams(cw_min=15, cw_max=63, aifsn=2) for ac in QOS_TRAFFIC_CLASSES}
    ps = []
    for seed in (1, 2):
        aps = []
        orig = simulation.WiFi

        class Spy(orig):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                aps.append(self)
        simulation.WiFi = Spy
        try:
            pos = [tuple(map(float, p.split(","))) for p in _cluster_ap_positions("0,0", 3, 3.0)]
            with contextlib.redirect_stdout(io.StringIO()):
                backoffs = {k: {3: 0} for k in range(1024)}
                simulation.run_simulation(3, 0, seed, 1.0, Config(qos_enabled=True, edca_params=dcf_like,
                                                                  mac_exchange=True, preamble_detect_dbm=-82.0),
                                          Config_NR(), backoffs, {}, {}, {}, {}, False, ap_positions=pos,
                                          sta_radius=3.0,
                                          wifi_traffic_config=TrafficConfig(mode="poisson", arrival_rate_pps=6000.0,
                                                                            traffic_class_mix={"best_effort": 1.0}))
        finally:
            simulation.WiFi = orig
            logging.disable(logging.NOTSET)
        s = sum(a.succeeded_transmissions for a in aps)
        f = sum(a.failed_transmissions for a in aps)
        ps.append(f / (s + f))
    assert abs(statistics.mean(ps) - bianchi.collision_probability(3, 15, 63)) < 0.03
# Rashed-Step pre_21.B-10-11-2026-end
