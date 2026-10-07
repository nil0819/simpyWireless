# Rashed-Step 18.F-10-06-2026-start
"""
Step 18.F tests: PDCP + RLC (ran/protocol/l2.py) - headers, segmentation
overhead, RLC AM ARQ, PDCP in-order delivery - and their wiring into
licensed NR and NR-U "slots".
"""

import contextlib
import io
import logging
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from click.testing import CliRunner

from common.error_model import ErrorModelConfig
from common.packet import Packet, TrafficConfig
from nr.nr import Config_NRL
from nru.nru import Config_NR
from ran.protocol.buffer import ByteBuffer
from ran.protocol.harq import HarqConfig
from ran.protocol.l2 import L2Buffer, L2Config, l2_config_from_cli, make_buffer
from simulation_nr import run_simulation_licensed_nr
from singleRun import single_run
from singleRunNR import single_run_nr


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
# headers
# ---------------------------------------------------------------------

def test_header_sizes():
    um, am, am18 = L2Config("um"), L2Config("am"), L2Config("am", sn_bits=18)
    assert (um.pdcp_header_bytes, am18.pdcp_header_bytes) == (2, 3)
    assert um.rlc_header_bytes(True, True) == 1          # UM whole SDU
    assert um.rlc_header_bytes(False, True) == 2         # UM first segment
    assert um.rlc_header_bytes(False, False) == 4        # + segment offset
    assert am.rlc_header_bytes(True, True) == 2 and am18.rlc_header_bytes(True, True) == 3
    assert am.rlc_header_bytes(False, False) == 4 and am18.rlc_header_bytes(False, False) == 5
    assert L2Config.mac_subheader_bytes(255) == 2 and L2Config.mac_subheader_bytes(256) == 3


def test_pdcp_header_added_and_whole_sdu_overhead():
    b = L2Buffer(l2=L2Config("um"))
    b.enqueue(_pkt(0, 100))
    assert b.backlog_bytes == 102                         # + 2-byte PDCP header
    # A whole SDU: 102 + 1 (UM) + 2 (MAC) = 105 bytes of TB.
    assert b.take(104, now=0.0) != [] and b.backlog_bytes > 0   # 104 too small: segmented
    b2 = L2Buffer(l2=L2Config("um"))
    b2.enqueue(_pkt(0, 100))
    segs = b2.take(105, now=0.0)
    assert segs == [(segs[0][0], 102, True)] and b2.stats["l2_overhead_bytes"] == 3


def test_segmentation_headers_count_against_the_tb():
    b = L2Buffer(l2=L2Config("am"))
    b.enqueue(_pkt(0, 998))                               # 1000 bytes with PDCP
    s1 = b.take(500, now=0.0)                             # first segment: 2 RLC + 3 MAC
    s2 = b.take(600, now=0.0)                             # rest: 4 RLC (SO) + 3 MAC
    assert s1[0][1] == 495 and s2[0][1] == 505
    assert b.stats["l2_overhead_bytes"] == 5 + 7


def test_make_buffer():
    assert type(make_buffer(None)) is ByteBuffer
    assert isinstance(make_buffer(None, l2=L2Config()), L2Buffer)


# ---------------------------------------------------------------------
# RLC AM ARQ / UM loss
# ---------------------------------------------------------------------

def test_um_loss_drops_the_packet():
    b = L2Buffer(l2=L2Config("um"))
    b.enqueue(_pkt(0, 100))
    b.drop(b.take(1000, now=0.0), now=0.0)
    assert [p.status for p in b.drain_finished()] == ["DROPPED"]


def test_am_retransmits_lost_bytes_after_the_status_delay():
    b = L2Buffer(l2=L2Config("am", am_status_delay_us=5000.0))
    b.enqueue(_pkt(0, 100))
    b.enqueue(_pkt(1, 100))
    lost = b.take(108, now=0.0)                           # p0 whole (102 + 2 + 2)... and a bit of p1
    b.drop(lost, now=0.0)
    assert b.drain_finished() == []                       # not dropped: queued again
    assert not b.has_ready(4999.0) or b.new_bytes > 0
    first = b.take(10_000, now=1000.0)                    # before the STATUS: only new data
    assert all(seg[0].packet_id == "p1" for seg in first)
    again = b.take(10_000, now=5000.0)                    # retransmission goes first
    assert again[0][0].packet_id == "p0"
    b.ack(first, now=5100.0)
    b.ack(again, now=5200.0)
    done = b.drain_finished()
    assert [p.packet_id for p in done] == ["p0", "p1"]    # in order
    assert all(p.status == "DELIVERED" for p in done)
    assert b.stats["am_retx_segments"] >= 1


def test_am_gives_up_after_max_retx():
    b = L2Buffer(l2=L2Config("am", am_max_retx=1, am_status_delay_us=0.0))
    b.enqueue(_pkt(0, 100))
    b.drop(b.take(1000, now=0.0), now=0.0)
    b.drop(b.take(1000, now=0.0), now=0.0)
    out = b.drain_finished()
    assert [p.status for p in out] == ["DROPPED"] and b.stats["dropped_max_retx"] == 1
    assert b.backlog_bytes == 0


# ---------------------------------------------------------------------
# PDCP in-order delivery
# ---------------------------------------------------------------------

def test_in_order_delivery_holds_later_packets():
    b = L2Buffer(l2=L2Config("am"))
    b.enqueue(_pkt(0, 100))
    b.enqueue(_pkt(1, 100))
    t0, t1 = b.take(106, now=0.0), b.take(106, now=0.0)   # one whole SDU each
    b.ack(t1, now=10.0)
    assert b.drain_finished() == []                       # p1 waits for p0
    b.ack(t0, now=30.0)
    done = b.drain_finished()
    assert [p.packet_id for p in done] == ["p0", "p1"]
    assert done[1].delivered_at == 30.0
    assert b.stats["reordered_packets"] == 1 and b.stats["reorder_wait_us_sum"] == 20.0


def test_a_lost_packet_releases_the_ones_behind_it():
    b = L2Buffer(l2=L2Config("um"))
    b.enqueue(_pkt(0, 100))
    b.enqueue(_pkt(1, 100))
    t0, t1 = b.take(105, now=0.0), b.take(105, now=0.0)
    b.ack(t1, now=10.0)
    b.drop(t0, now=20.0)
    assert [(p.packet_id, p.status) for p in b.drain_finished()] == [("p0", "DROPPED"), ("p1", "DELIVERED")]


# ---------------------------------------------------------------------
# config / CLI mapping
# ---------------------------------------------------------------------

def test_config_and_cli_mapping():
    _expect_value_error(lambda: L2Config("tm"), "RLC mode must be one of")
    _expect_value_error(lambda: L2Config(sn_bits=16), "12 or 18")
    assert l2_config_from_cli("none", None, None, None) is None
    assert l2_config_from_cli("am", 18, 8, 5.0) == L2Config("am", 18, 8, 5000.0)
    _expect_value_error(lambda: l2_config_from_cli("none", 12, None, None), "require --rlc-mode um or am")
    _expect_value_error(lambda: l2_config_from_cli("um", None, 3, None), "require --rlc-mode am")
    _expect_value_error(lambda: Config_NR(l2=L2Config()), "needs cot_model")


# ---------------------------------------------------------------------
# licensed NR end to end
# ---------------------------------------------------------------------

def _nr(**cfg):
    c = Config_NRL(dl_traffic=TrafficConfig(mode="poisson", arrival_rate_pps=3000.0), **cfg)
    logging.disable(logging.CRITICAL)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            return run_simulation_licensed_nr(2, 2, 0.3, c, nr_ues_per_gnb=4,
                                              error_model_config=ErrorModelConfig())["traffic_stats"]["dl"]
    finally:
        logging.disable(logging.NOTSET)


def test_licensed_nr_am_with_harq_loses_nothing():
    plain = _nr()
    um = _nr(l2=L2Config("um"))
    am = _nr(l2=L2Config("am"), harq=HarqConfig())
    assert plain["dropped_tb_error"] > 100
    assert um["dropped_tb_error"] > 100 and um["l2"]["l2_overhead_bytes"] > 0
    assert am["dropped_tb_error"] == 0
    assert am["delivered_packets"] > plain["delivered_packets"]


def test_licensed_nr_l2_needs_buffered_traffic():
    with contextlib.redirect_stdout(io.StringIO()):
        _expect_value_error(lambda: run_simulation_licensed_nr(1, 1, 0.01, Config_NRL(l2=L2Config())),
                            "needs buffered traffic")


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
    r = _cli(single_run_nr, nr + ["--dl-traffic", "cbr", "--rlc-mode", "am", "--pdcp-sn-bits", "18"])
    assert r.exit_code == 0, (r.output, r.exception)
    assert "=== Licensed 5G NR DL PDCP/RLC ===" in r.output and "SN 18 bit, PDCP header 3 B" in r.output
    r = _cli(single_run_nr, nr + ["--rlc-mode", "um"])
    assert r.exit_code != 0 and "needs --dl-traffic or --ul-traffic" in r.output
    r = _cli(single_run_nr, nr + ["--rlc-am-max-retx", "2"])
    assert r.exit_code != 0 and "require --rlc-mode" in r.output
    nru = ["--ap-number", "0", "--gnb-number", "1", "--seed", "1", "-r", "1", "-t", "0.05"]
    r = _cli(single_run, nru + ["--rlc-mode", "um"])
    assert r.exit_code != 0 and "needs --nru-cot-model slots" in r.output
    r = _cli(single_run, nru + ["--nru-cot-model", "slots", "--rlc-mode", "um"])
    assert r.exit_code == 0, (r.output, r.exception)
    assert "=== NR-U DL PDCP/RLC ===" in r.output
# Rashed-Step 18.F-10-06-2026-end
