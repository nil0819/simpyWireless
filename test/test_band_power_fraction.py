# Rashed-Step pre_20.C0-10-08-2026-start
"""
Step pre_20.C0: interference and sensed energy are scaled by the share of
the TRANSMITTER's power that falls in the receiver's band
(common_phy.power_fraction_in_band), not by the share of the receiver's
band that is covered (spectral_overlap_fraction) - the two only agree when
the bandwidths are equal.
"""

import math
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest
import simpy

from channel.channel import ActiveTx, Channel
from common.common_phy import power_fraction_in_band, spectral_overlap_fraction, thermal_noise_dbm

F = 5.18e9


def test_power_fraction_values():
    assert power_fraction_in_band(F, 20.0, F, 20.0) == 1.0 == spectral_overlap_fraction(F, 20.0, F, 20.0)
    assert power_fraction_in_band(F, 80.0, F, 20.0) == 1.0          # narrow interferer inside a wide receiver
    assert power_fraction_in_band(F, 20.0, F, 80.0) == 0.25         # wide interferer, narrow receiver
    assert power_fraction_in_band(F, 20.0, F + 10e6, 20.0) == pytest.approx(0.5)
    assert power_fraction_in_band(F, 20.0, F + 20e6, 20.0) == 0.0
    assert power_fraction_in_band(F, 20.0, F, 0.0) == 0.0


def _ch():
    env = simpy.Environment()
    return Channel(simpy.PriorityResource(env, capacity=1), simpy.Resource(env, capacity=1), 1, 1, {}, {}, {}, {}, {})


def _tx(tid, pos, rx, bw, power=20.0):
    return ActiveTx(tx_id=tid, tx_pos=pos, rx_pos=rx, tx_start=0.0, tx_power_dbm=power, f_hz=F, pl_exp=3.0,
                    t_end=100.0, tech="WiFi", bandwidth_mhz=bw)


def _interference_dbm(victim_bw, interferer_bw):
    ch = _ch()
    victim = _tx("A", (0.0, 0.0), (5.0, 0.0), victim_bw)
    ch.register_tx(victim)
    ch.register_tx(_tx("B", (40.0, 0.0), (45.0, 0.0), interferer_bw))
    s = ch._rx_pwr_dbm(victim, victim.rx_pos)
    sinr = ch.sinr_db(victim)
    n = 10 ** (thermal_noise_dbm(victim_bw, victim.noise_figure_db) / 10)
    return 10 * math.log10(10 ** ((s - sinr) / 10) - n)


def test_sinr_counts_the_interferers_power_in_band():
    full = _interference_dbm(20.0, 20.0)
    assert _interference_dbm(80.0, 20.0) == pytest.approx(full, abs=0.01)                  # all of it
    assert _interference_dbm(20.0, 80.0) == pytest.approx(full - 10 * math.log10(4), abs=0.01)   # a quarter


def test_sensed_energy_counts_the_power_in_band():
    ch = _ch()
    ch.register_tx(_tx("B", (40.0, 0.0), (45.0, 0.0), 80.0))
    e80 = ch.sensed_energy_dbm((0.0, 0.0), sense_f_hz=F, sense_bw_mhz=80.0)
    e20 = ch.sensed_energy_dbm((0.0, 0.0), sense_f_hz=F, sense_bw_mhz=20.0)
    assert e80 - e20 == pytest.approx(10 * math.log10(4), abs=0.01)
# Rashed-Step pre_20.C0-10-08-2026-end
