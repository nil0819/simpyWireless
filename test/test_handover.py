# Rashed-Step 19.D.1-10-07-2026-start
"""
Step 19.D.1 tests: measurements, event A3 and handover
(ran/protocol/handover.py), context transfer in licensed NR, and
re-establishment to the best cell.
"""

import contextlib
import io
import logging
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import simpy
from click.testing import CliRunner

from common.packet import Packet, TrafficConfig
from nr.nr import Config_NRL
from ran.protocol.handover import (HandoverConfig, compute_handover_stats, handover_config_from_cli,
                                   measurement_process)
from ran.protocol.rrc import RrcLayer, RrcState
from simulation_nr import run_simulation_licensed_nr
from singleRunNR import single_run_nr


def _expect_value_error(fn, needle):
    try:
        fn()
    except ValueError as e:
        assert needle in str(e)
    else:
        assert False, "expected ValueError"


class _Cell:
    """Fake gNB whose RSRP at the UE follows a script of (until_us, dBm)."""

    def __init__(self, env, name, script):
        self.env, self.name, self.script = env, name, script
        self.neighbors, self.slot_us, self.ue_list = [], 500.0, []

    def rsrp_dbm(self, ue):
        for until, v in self.script:
            if self.env.now < until:
                return v
        return self.script[-1][1]

    def rrc_uplink_delay(self, ue):
        yield self.env.timeout(1000.0)

    def release_ue_context(self, ue):
        self.ue_list.remove(ue)
        return {"dl": None}

    def admit_ue_context(self, ue, ctx):
        self.ue_list.append(ue)
        ue.gnb = self


class _Ue:
    name = "ue"


def _setup(script_a, script_b, cfg=None):
    env = simpy.Environment()
    a, b = _Cell(env, "A", script_a), _Cell(env, "B", script_b)
    a.neighbors, b.neighbors = [b], [a]
    ue = _Ue()
    ue.gnb, ue.rrc_state = a, RrcState.CONNECTED
    a.ue_list.append(ue)
    env.process(measurement_process(ue, cfg or HandoverConfig()))
    return env, a, b, ue


def test_a3_with_time_to_trigger_hands_over():
    # B becomes 10 dB stronger at 1 s and stays.
    env, a, b, ue = _setup([(1e12, -90.0)], [(1e6, -100.0), (1e12, -80.0)])
    env.run(until=3e6)
    assert ue.gnb is b and ue in b.ue_list and ue not in a.ue_list
    assert ue.handovers == 1 and ue.ho_reports == 1 and ue.rrc_state is RrcState.CONNECTED
    # Interruption: source slot 0.5 ms + execution 20 ms + Complete 1 ms.
    assert ue.ho_interruptions_us == [21_500.0]


def test_short_dip_does_not_trigger():
    # B is better for only 80 ms (< 160 ms TTT, after L3 filtering).
    env, a, b, ue = _setup([(1e12, -90.0)], [(1e6, -100.0), (1.08e6, -60.0), (1e12, -100.0)])
    env.run(until=3e6)
    assert ue.gnb is a and ue.handovers == 0


def test_ping_pong_is_counted():
    # B strong from 1.0 s, A strong again from 1.6 s: A -> B -> A, the second
    # handover back to A well within the 1 s ping-pong window.
    env, a, b, ue = _setup([(1e6, -90.0), (1.6e6, -110.0), (1e12, -70.0)],
                           [(1e6, -100.0), (1.6e6, -80.0), (1e12, -100.0)])
    env.run(until=4e6)
    assert ue.handovers == 2 and ue.ho_ping_pongs == 1 and ue.gnb is a


def test_config_and_cli_mapping():
    _expect_value_error(lambda: HandoverConfig(meas_period_us=0), "must be > 0")
    assert handover_config_from_cli(False, None, None) is None
    c = handover_config_from_cli(True, 2.0, 320.0)
    assert (c.a3_offset_db, c.ttt_us) == (2.0, 320_000.0)
    _expect_value_error(lambda: handover_config_from_cli(False, 2.0, None), "require --handover")


# ---------------------------------------------------------------------
# licensed NR
# ---------------------------------------------------------------------

def _gnbs_of(run_kwargs, cfg):
    import simulation_nr
    gnbs = []
    orig = simulation_nr.GnbLicensedNR

    class Spy(orig):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            gnbs.append(self)

    simulation_nr.GnbLicensedNR = Spy
    logging.disable(logging.CRITICAL)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            res = simulation_nr.run_simulation_licensed_nr(config=cfg, **run_kwargs)
    finally:
        simulation_nr.GnbLicensedNR = orig
        logging.disable(logging.NOTSET)
    return gnbs, res


def test_licensed_context_transfer_moves_buffer_and_resets_harq():
    from ran.protocol.harq import HarqConfig, HarqTb
    cfg = Config_NRL(dl_traffic=TrafficConfig(mode="cbr", arrival_rate_pps=10.0), harq=HarqConfig())
    gnbs, _ = _gnbs_of(dict(number_of_gnb=2, seed=1, simulation_time=0.01, nr_ues_per_gnb=1), cfg)
    a, b = gnbs
    ue = a.ue_list[0]
    buf = a.dl_buffers[ue.name]
    buf.enqueue(Packet(packet_id="x", source=a.name, destination=ue.name, payload_bytes=500, header_bytes=0))
    segs = buf.take(200, a.env.now)
    ent = a._harq_for(buf)
    tb = HarqTb(segs, 0, 1, 200)
    ent.attempt(tb, -50.0, 0.0, None, outcome=False)
    ent.failed(tb, a.env.now, 1000.0)
    from ran.protocol.handover import move_ue
    move_ue(a, b, ue)
    assert ue.gnb is b and ue in b.ue_list and ue not in a.ue_list
    assert b.dl_buffers[ue.name] is buf and ue.name not in a.dl_buffers
    assert id(buf) not in a._harq_entities                # HARQ reset
    assert any(p.packet_id == "x" and p.status == "DROPPED" for p in a.packet_log)


def test_cli_mobility_run_hands_over():
    runner = CliRunner()
    args = ["--gnb-number", "2", "--ues-per-gnb", "4", "--gnb-pos", "300,500", "--gnb-pos", "900,500",
            "--area-w", "1200", "--area-h", "1000", "--ue-radius", "150", "--ue-mobility-speed-mps", "20",
            "--seed", "3", "-t", "30", "--tdd-enabled", "--ue-uplink-enabled", "--rrc-enabled",
            "--dl-traffic", "poisson", "--dl-arrival-rate-pps", "50", "--handover"]
    with runner.isolated_filesystem():
        r = runner.invoke(single_run_nr, args)
        assert r.exit_code == 0, (r.output[-500:], r.exception)
        assert "=== Licensed 5G NR Handover ===" in r.output
        n = int(next(l for l in r.output.splitlines() if l.startswith("NR handovers:")).split(":")[1])
        assert n >= 1
        bad = runner.invoke(single_run_nr, ["--gnb-number", "2", "-t", "0.05", "--handover"])
        assert bad.exit_code != 0 and "--handover requires --rrc-enabled" in bad.output
# Rashed-Step 19.D.1-10-07-2026-end
