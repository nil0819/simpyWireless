# Rashed-Step pre_20.D.3a-10-08-2026-start
"""
Step pre_20.D.3a: a Wi-Fi frame's SINR (full-power rule) counts one
interfering transmitter's back-to-back transmissions at its peak
instantaneous power, not their sum.
"""

import math
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import simpy

from channel.channel import ActiveTx, Channel


def _setup():
    env = simpy.Environment()
    ch = Channel(simpy.PriorityResource(env, capacity=1), simpy.Resource(env, capacity=1), 1, 1, {}, {}, {}, {}, {})
    wifi = ActiveTx(tx_id="AP 1", tx_pos=(0.0, 0.0), rx_pos=(5.0, 0.0), tx_start=0.0, tx_power_dbm=20.0,
                    f_hz=5.18e9, pl_exp=3.0, t_end=250.0, tech="WiFi")
    ch.register_tx(wifi)
    return ch, wifi


def _nru(tx_id, start, end, power=23.0):
    return ActiveTx(tx_id=tx_id, tx_pos=(50.0, 0.0), rx_pos=(50.0, 0.0), tx_start=start, tx_power_dbm=power,
                    f_hz=5.18e9, pl_exp=3.0, t_end=end, tech="NRU")


def test_back_to_back_frames_of_one_transmitter_count_once():
    ch, wifi = _setup()
    ch.register_tx(_nru("Gnb 1", 0.0, 100.0))
    one = ch.sinr_db(wifi)
    ch.register_tx(_nru("Gnb 1", 160.0, 6000.0))       # same gNB, after a gap: CTS then COT
    assert math.isclose(ch.sinr_db(wifi), one)


def test_different_transmitters_and_overlapping_frames_still_add():
    ch, wifi = _setup()
    ch.register_tx(_nru("Gnb 1", 0.0, 100.0))
    one = ch.sinr_db(wifi)
    ch.register_tx(_nru("Gnb 2", 160.0, 6000.0))       # another gNB: +3 dB interference
    assert math.isclose(ch.sinr_db(wifi), one - 10 * math.log10(2), abs_tol=0.05)
    ch2, wifi2 = _setup()
    ch2.register_tx(_nru("Gnb 1", 0.0, 200.0, power=20.0))
    ch2.register_tx(_nru("Gnb 1", 100.0, 300.0, power=20.0))   # on the air together: they add
    ch3, wifi3 = _setup()
    ch3.register_tx(_nru("Gnb 1", 0.0, 200.0, power=23.0))
    assert math.isclose(ch2.sinr_db(wifi2), ch3.sinr_db(wifi3), abs_tol=0.05)
# Rashed-Step pre_20.D.3a-10-08-2026-end
