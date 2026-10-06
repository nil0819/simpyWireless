# Rashed-Step pre_18.F-10-06-2026-start
"""
Step pre_18.F tests: licensed NR uplink UEs of one cell, scheduled in the
same slot on different RBs (OFDMA), must not interfere with each other;
UEs of OTHER cells still do.
"""

import io
import contextlib
import logging
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import simpy

from channel.channel import ActiveTx, Channel, TxSnapshot
from nr.nr import Config_NRL
import simulation_nr


def _channel():
    env = simpy.Environment()
    return Channel(simpy.PriorityResource(env, capacity=1), simpy.Resource(env, capacity=1),
                   0, 1, {}, {}, {}, {}, {})


def _ul(name, pos, cell, gnb_pos=(0.0, 0.0)):
    return ActiveTx(tx_id=name, tx_pos=pos, tx_start=0, rx_pos=gnb_pos, tx_power_dbm=20.0,
                    f_hz=3.5e9, pl_exp=3.0, t_end=500, tech="NR", bandwidth_mhz=50.0,
                    ofdma_cell=cell)


def test_same_cell_uplink_ues_do_not_interfere():
    ch = _channel()
    near, far = _ul("ue1", (10.0, 0.0), "g1"), _ul("ue2", (60.0, 0.0), "g1")
    alone = _ul("ue2-alone", (60.0, 0.0), "g1")
    ch.register_tx(near)
    ch.register_tx(far)
    assert ch.sinr_db(far) == ch.sinr_db(alone)  # as if ue1 weren't there
    assert ch.sinr_db(far) > 0


def test_other_cell_uplink_still_interferes():
    ch = _channel()
    victim = _ul("ue2", (60.0, 0.0), "g1")
    ch.register_tx(victim)
    clean = ch.sinr_db(victim)
    ch.register_tx(_ul("ue9", (10.0, 0.0), "g2"))
    assert ch.sinr_db(victim) < clean - 10


def test_untagged_transmissions_are_unchanged():
    ch = _channel()
    a, b = _ul("a", (10.0, 0.0), None), _ul("b", (60.0, 0.0), None)
    ch.register_tx(a)
    ch.register_tx(b)
    assert ch.sinr_db(b) < 0  # full co-channel interference, as before


def test_snapshot_keeps_the_cell_so_ended_same_cell_tx_stays_ignored():
    tx = _ul("ue1", (10.0, 0.0), "g1")
    assert TxSnapshot.of(tx).ofdma_cell == "g1"


def test_two_ue_uplink_cell_delivers_both():
    logging.disable(logging.CRITICAL)
    gnbs = []
    orig = simulation_nr.GnbLicensedNR

    class Spy(orig):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            gnbs.append(self)

    simulation_nr.GnbLicensedNR = Spy
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            simulation_nr.run_simulation_licensed_nr(1, 2, 0.2, Config_NRL(tdd_enabled=True), nr_ues_per_gnb=2,
                                                     ue_radius=40.0, nr_ue_uplink_enabled=True)
    finally:
        simulation_nr.GnbLicensedNR = orig
        logging.disable(logging.NOTSET)
    g = gnbs[0]
    assert g.failed_transmissions_ul == 0
    ul = [p for p in g.packet_log if p.source != g.name]
    assert {p.source for p in ul if p.status == "DELIVERED"} == {ue.name for ue in g.ue_list}


def test_uplink_results_block_and_return_value():
    from click.testing import CliRunner
    from singleRunNR import single_run_nr
    base = ["--gnb-number", "1", "--ues-per-gnb", "2", "--seed", "1", "-t", "0.05", "--ue-radius", "40"]
    runner = CliRunner()
    with runner.isolated_filesystem():
        off = runner.invoke(single_run_nr, base)
        on = runner.invoke(single_run_nr, base + ["--tdd-enabled", "--ue-uplink-enabled"])
    assert off.exit_code == 0 and on.exit_code == 0, (off.output, on.output)
    assert "Uplink Results" not in off.output
    assert "=== Licensed 5G NR Uplink Results ===" in on.output
    assert "TOTAL UL: slots_ok=" in on.output
    with contextlib.redirect_stdout(io.StringIO()):
        res = simulation_nr.run_simulation_licensed_nr(1, 1, 0.05, Config_NRL(tdd_enabled=True),
                                                       nr_ues_per_gnb=2, ue_radius=40.0,
                                                       nr_ue_uplink_enabled=True)
        assert simulation_nr.run_simulation_licensed_nr(1, 1, 0.05, Config_NRL(), nr_ues_per_gnb=2,
                                                        ue_radius=40.0)["ul_throughput_mbps"] is None
    assert res["ul_throughput_mbps"] > 0
# Rashed-Step pre_18.F-10-06-2026-end
