# Rashed-Step 18.E-10-06-2026-start
"""
Step 18.E tests: HARQ (ran/protocol/harq.py), the buffer's take/ack/drop
path, and HARQ in licensed NR (buffered) and NR-U "slots".
"""

import contextlib
import io
import logging
import math
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from click.testing import CliRunner

import simulation
from common.error_model import ErrorModelConfig
from common.packet import Packet, TrafficConfig
from nr.nr import Config_NRL
from nru.nru import Config_NR, NruUplinkAccessMode
from ran.protocol.buffer import ByteBuffer
from ran.protocol.harq import HarqConfig, HarqEntity, HarqTb, harq_config_from_cli
from simulation_nr import run_simulation_licensed_nr
from singleRun import single_run
from singleRunNR import single_run_nr
from wifi.wifi import Config


def _expect_value_error(fn, needle):
    try:
        fn()
    except ValueError as e:
        assert needle in str(e)
    else:
        assert False, "expected ValueError"


def _pkt(i, size=1000):
    return Packet(packet_id=f"p{i}", source="g", destination="u", payload_bytes=size, header_bytes=0)


# ---------------------------------------------------------------------
# HarqEntity
# ---------------------------------------------------------------------

def test_chase_combining_adds_linear_sinr():
    e = HarqEntity(HarqConfig())
    tb = HarqTb([], mcs=4, rbs=10, tb_bytes=100)
    # 2 dB short of a 5 dB threshold: fails alone...
    assert not e.attempt(tb, 3.0, 5.0, None)
    assert e.failed(tb, now=0.0, rtt_us=2000.0)
    # ...but two copies at 3 dB combine to 3 + 10*log10(2) = 6.01 dB.
    assert e.next_retx(1999.0) is None
    tb2 = e.next_retx(2000.0)
    assert tb2 is tb
    assert e.attempt(tb, 3.0, 5.0, None)
    assert math.isclose(10 * math.log10(tb.sinr_lin_sum), 3.0 + 10 * math.log10(2))
    assert e.stats == {"new_tbs": 1, "retx": 1, "ok_first": 0, "ok_retx": 1, "dropped": 0}


def test_gives_up_after_max_tx():
    e = HarqEntity(HarqConfig(max_tx=2))
    tb = HarqTb([], 0, 1, 10)
    assert not e.attempt(tb, -50.0, 0.0, None)
    assert e.failed(tb, 0.0, 0.0)
    assert not e.attempt(e.next_retx(0.0), -50.0, 0.0, None)
    assert not e.failed(tb, 0.0, 0.0)  # 2nd attempt was the last
    assert e.stats["dropped"] == 1 and e.pending() == 0


def test_process_limit_blocks_new_data():
    e = HarqEntity(HarqConfig(n_processes=2))
    for _ in range(2):
        tb = HarqTb([], 0, 1, 10)
        e.attempt(tb, -50.0, 0.0, None)
        e.failed(tb, 0.0, 1000.0)
    assert not e.can_send_new()


def test_config_and_cli():
    _expect_value_error(lambda: HarqConfig(max_tx=0), "max_tx must be >= 1")
    assert harq_config_from_cli(False, None, None) is None
    assert harq_config_from_cli(True, None, None) == HarqConfig()
    assert harq_config_from_cli(True, 2, 8) == HarqConfig(max_tx=2, rtt_slots=8)
    _expect_value_error(lambda: harq_config_from_cli(False, 3, None), "require --harq")


# ---------------------------------------------------------------------
# ByteBuffer take / ack / drop
# ---------------------------------------------------------------------

def test_take_removes_bytes_and_ack_completes_split_packets_out_of_order():
    b = ByteBuffer()
    b.enqueue(_pkt(0))
    b.enqueue(_pkt(1))
    tb1 = b.take(600)   # p0[0:600]
    tb2 = b.take(900)   # p0[600:1000] + p1[0:500]
    assert b.backlog_bytes == 500
    b.ack(tb2, now=5.0)
    assert b.drain_finished() == []      # p0 still has bytes in flight
    b.ack(tb1, now=7.0)
    done = b.drain_finished()
    assert [p.packet_id for p in done] == ["p0"] and done[0].delivered_at == 7.0
    b.ack(b.take(500), now=9.0)
    assert b.drain_finished()[0].packet_id == "p1"
    assert b.stats["delivered_packets"] == 2 and b.stats["delivered_bytes"] == 2000


def test_drop_loses_the_packet_and_its_queued_remainder():
    b = ByteBuffer()
    b.enqueue(_pkt(0))
    b.enqueue(_pkt(1))
    tb = b.take(400)   # first 400 bytes of p0
    b.drop(tb)
    assert b.backlog_bytes == 1000 and b.head().packet_id == "p1"
    dropped = b.drain_finished()
    assert [p.packet_id for p in dropped] == ["p0"] and dropped[0].status == "DROPPED"


def test_late_ack_after_drop_keeps_packet_dropped():
    b = ByteBuffer()
    b.enqueue(_pkt(0))
    tb1, tb2 = b.take(500), b.take(500)
    b.drop(tb1)
    b.ack(tb2, now=1.0)
    out = b.drain_finished()
    assert len(out) == 1 and out[0].status == "DROPPED"
    assert b.stats["dropped_tb_error"] == 1 and b.stats["delivered_packets"] == 0


# ---------------------------------------------------------------------
# licensed NR
# ---------------------------------------------------------------------

def _nr(harq, **kw):
    cfg = Config_NRL(dl_traffic=TrafficConfig(mode="poisson", arrival_rate_pps=3000.0), harq=harq)
    with contextlib.redirect_stdout(io.StringIO()):
        logging.disable(logging.CRITICAL)
        try:
            return run_simulation_licensed_nr(2, 2, 0.3, cfg, nr_ues_per_gnb=4,
                                              error_model_config=ErrorModelConfig(), **kw)
        finally:
            logging.disable(logging.NOTSET)


def test_licensed_nr_harq_recovers_block_errors():
    off = _nr(None)["traffic_stats"]["dl"]
    on = _nr(HarqConfig())["traffic_stats"]["dl"]
    assert on["dropped_tb_error"] < 0.05 * off["dropped_tb_error"]
    assert on["delivered_bytes"] > off["delivered_bytes"]
    h = on["harq"]
    assert h["ok_retx"] > 0 and h["retx"] >= h["ok_retx"]
    # Every TB is decoded, dropped, waiting - or a retransmission claimed in
    # the last slot when the run ended (at most one per UE).
    in_flight = h["new_tbs"] - (h["ok_first"] + h["ok_retx"] + h["dropped"] + h["pending"])
    assert 0 <= in_flight <= 8


def test_licensed_nr_harq_needs_buffered_traffic():
    with contextlib.redirect_stdout(io.StringIO()):
        _expect_value_error(lambda: run_simulation_licensed_nr(1, 1, 0.01, Config_NRL(harq=HarqConfig())),
                            "needs buffered traffic")


# ---------------------------------------------------------------------
# NR-U slots
# ---------------------------------------------------------------------

def _nru(harq, seed=4):
    logging.disable(logging.CRITICAL)
    gnbs = []
    orig = simulation.Gnb

    class Spy(orig):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            gnbs.append(self)

    simulation.Gnb = Spy
    cfg = Config_NR(cot_model="slots", ul_access_mode=NruUplinkAccessMode.COT_SHARING, harq=harq,
                    ul_traffic=TrafficConfig(mode="poisson", arrival_rate_pps=500.0))
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            wifi = Config()
            backoffs = {k: {1: 0} for k in range(wifi.cw_max + 1)}
            simulation.run_simulation(1, 1, seed, 0.5, wifi, cfg, backoffs, {}, {}, {}, {}, False,
                                      nru_traffic_config=TrafficConfig(mode="poisson", arrival_rate_pps=1500.0),
                                      nru_ue_uplink_enabled=True)
    finally:
        simulation.Gnb = orig
        logging.disable(logging.NOTSET)
    return gnbs[0]


def test_nru_harq_recovers_both_directions():
    off, on = _nru(None), _nru(HarqConfig())
    dl = lambda g: sum(b.stats["dropped_tb_error"] for b in g.dl_buffers.values())
    ul = lambda g: sum(ue.ul_buffer.stats["dropped_tb_error"] for ue in g.ue_list)
    assert dl(off) > 20 and dl(on) < 0.2 * dl(off)
    assert ul(off) > 20 and ul(on) < 0.5 * ul(off)
    assert sum(e.stats["ok_retx"] for e in on.harq_entities(False)) > 0
    assert sum(e.stats["ok_retx"] for e in on.harq_entities(True)) > 0


def test_nru_harq_needs_slots():
    _expect_value_error(lambda: Config_NR(harq=HarqConfig()), "needs cot_model")


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------

def _cli(cmd, args):
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("log", exist_ok=True)
        return runner.invoke(cmd, args)


def test_cli():
    nr = ["--gnb-number", "1", "--ues-per-gnb", "2", "--seed", "1", "-t", "0.05"]
    r = _cli(single_run_nr, nr + ["--dl-traffic", "cbr", "--harq"])
    assert r.exit_code == 0, (r.output, r.exception)
    assert "=== Licensed 5G NR DL HARQ ===" in r.output
    r = _cli(single_run_nr, nr + ["--harq"])
    assert r.exit_code != 0 and "needs --dl-traffic or --ul-traffic" in r.output
    r = _cli(single_run_nr, nr + ["--harq-max-tx", "2"])
    assert r.exit_code != 0 and "require --harq" in r.output
    nru = ["--ap-number", "0", "--gnb-number", "1", "--seed", "1", "-r", "1", "-t", "0.05"]
    r = _cli(single_run, nru + ["--harq"])
    assert r.exit_code != 0 and "needs --nru-cot-model slots" in r.output
    r = _cli(single_run, nru + ["--nru-cot-model", "slots", "--harq"])
    assert r.exit_code == 0, (r.output, r.exception)
    assert "=== NR-U DL HARQ ===" in r.output
# Rashed-Step 18.E-10-06-2026-end
