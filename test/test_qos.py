# Rashed-Step 19.C-10-07-2026-start
"""
Step 19.C tests: QoS flows / 5QI (common/qos.py), one DRB per flow with
logical channel prioritization (ran/protocol/drb.py), and their wiring
into licensed NR and NR-U.
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

from common.packet import Packet, TrafficConfig
from common.qos import FIVE_QI_TABLE, FIVE_QI_TO_WIFI_AC, compute_qos_flow_stats, five_qi_for
from nr.nr import Config_NRL
from nru.nru import Config_NR
from ran.protocol.drb import QosBuffer
from ran.protocol.l2 import L2Config, make_buffer
from simulation_nr import run_simulation_licensed_nr
from singleRun import single_run
from singleRunNR import single_run_nr


def _pkt(i, cls, size=1000, t=0.0):
    return Packet(packet_id=f"{cls}{i}", source="g", destination="u", payload_bytes=size,
                  header_bytes=0, created_at=t, traffic_class=cls)


def _expect_value_error(fn, needle):
    try:
        fn()
    except ValueError as e:
        assert needle in str(e)
    else:
        assert False, "expected ValueError"


def test_5qi_table_and_mapping():
    assert [five_qi_for(c) for c in ("voice", "video", "best_effort", "background", "weird")] == [1, 2, 8, 9, 9]
    assert FIVE_QI_TABLE[1].pdb_ms == 100.0 and FIVE_QI_TABLE[1].resource_type == "GBR"
    levels = [FIVE_QI_TABLE[q].priority_level for q in (1, 2, 8, 9)]
    assert levels == sorted(levels)
    assert [FIVE_QI_TO_WIFI_AC[q] for q in (1, 2, 8, 9)] == ["AC_VO", "AC_VI", "AC_BE", "AC_BK"]


def test_tb_is_filled_in_5qi_priority_order():
    b = make_buffer(None, qos=True)
    assert isinstance(b, QosBuffer)
    b.enqueue(_pkt(0, "background"))
    b.enqueue(_pkt(0, "best_effort"))
    b.enqueue(_pkt(0, "voice"))           # arrives last, goes first
    segs = b.segments(2500)
    assert [(p.traffic_class, n) for p, n, _l in segs] == [("voice", 1000), ("best_effort", 1000), ("background", 500)]
    assert b.deliver(segs, now=5.0) == 2500
    done = b.drain_finished()
    assert sorted(p.traffic_class for p in done) == ["best_effort", "voice"]
    assert b.backlog_bytes == 500 and len(b) == 1 and b.head().traffic_class == "background"
    assert set(b.drbs) == {1, 8, 9}


def test_take_ack_drop_dispatch_per_drb():
    calls = []
    b = make_buffer(None, on_enqueue=lambda: calls.append(1), qos=True)
    b.enqueue(_pkt(0, "video"))
    b.enqueue(_pkt(1, "best_effort"))
    assert calls == [1, 1]
    tb = b.take(1500, now=0.0)
    b.drop([s for s in tb if s[0].traffic_class == "best_effort"], now=0.0)
    b.ack([s for s in tb if s[0].traffic_class == "video"], now=1.0)
    out = {p.traffic_class: p.status for p in b.drain_finished()}
    assert out == {"video": "DELIVERED", "best_effort": "DROPPED"}
    st = b.stats
    assert st["delivered_packets"] == 1 and st["dropped_tb_error"] == 1 and st["enqueued_packets"] == 2


def test_each_drb_has_its_own_pdcp_with_l2():
    b = make_buffer(None, l2=L2Config("am"), qos=True)
    b.enqueue(_pkt(0, "voice", 100))
    b.enqueue(_pkt(0, "best_effort", 100))
    assert b.backlog_bytes == 2 * 102                  # PDCP header on each
    segs = b.take(10_000, now=0.0)
    assert [p.traffic_class for p, _n, _l in segs] == ["voice", "best_effort"]
    assert b.stats["l2_overhead_bytes"] == 2 * (2 + 2)  # AM header + MAC subheader each


def test_flow_stats_count_starved_packets_as_misses():
    done = [_pkt(0, "voice", t=0.0)]
    done[0].status, done[0].delivered_at = "DELIVERED", 50_000.0
    waiting = [_pkt(1, "background", t=0.0), _pkt(2, "background", t=900_000.0)]
    s = compute_qos_flow_stats(done, waiting, now=1_000_000.0)
    assert s[1]["within_pdb"] == 1.0 and s[1]["mean_latency_us"] == 50_000.0
    assert s[9]["queued"] == 2 and s[9]["queued_past_pdb"] == 1 and s[9]["within_pdb"] == 0.0


def _nr(qos, seed=2):
    tc = TrafficConfig(mode="poisson", arrival_rate_pps=8000.0,
                       traffic_class_mix={"voice": 0.1, "best_effort": 0.9})
    cfg = Config_NRL(dl_traffic=tc, buffer_limit_bytes=2_000_000, qos_flows=qos)
    logging.disable(logging.CRITICAL)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            return run_simulation_licensed_nr(1, seed, 0.5, cfg, nr_ues_per_gnb=4)["traffic_stats"]["dl"]
    finally:
        logging.disable(logging.NOTSET)


def test_licensed_overload_voice_stays_fast_only_with_qos_flows():
    on = _nr(True)["qos"]
    assert on[1]["within_pdb"] == 1.0 and on[1]["mean_latency_us"] < 5_000
    assert on[8]["mean_latency_us"] > 10 * on[1]["mean_latency_us"]
    assert "qos" not in _nr(False)


def test_config_and_cli_validation():
    _expect_value_error(lambda: Config_NR(qos_flows=True), "needs cot_model")
    with contextlib.redirect_stdout(io.StringIO()):
        _expect_value_error(lambda: run_simulation_licensed_nr(1, 1, 0.01, Config_NRL(qos_flows=True)),
                            "needs buffered traffic")
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("log", exist_ok=True)
        nr = ["--gnb-number", "1", "--ues-per-gnb", "2", "-t", "0.05"]
        r = runner.invoke(single_run_nr, nr + ["--qos-flows"])
        assert r.exit_code != 0 and "need --dl-traffic or --ul-traffic" in r.output
        r = runner.invoke(single_run_nr, nr + ["--dl-traffic", "cbr", "--qos-flows",
                                               "--traffic-class-mix", "voice=1"])
        assert r.exit_code == 0, (r.output, r.exception)
        assert "=== Licensed 5G NR DL QoS Flows ===" in r.output and "NR DL 5QI 1" in r.output
        r = runner.invoke(single_run, ["--ap-number", "0", "--gnb-number", "1", "-t", "0.05", "-r", "1", "--qos-flows"])
        assert r.exit_code != 0 and "--nru-cot-model slots" in r.output
# Rashed-Step 19.C-10-07-2026-end
