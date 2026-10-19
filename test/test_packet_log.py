# Rashed-Step 24.B-10-19-2026-start
"""
Step 24.B tests: Packet __slots__, the compact packet log
(common/packet_log.py, --compact-packet-log) and the one-pass statistics.
"""
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest
from click.testing import CliRunner

from common.packet import Packet, compute_packet_stats, compute_packet_stats_by_class
from common.packet_log import CompactPacketLog, PacketView, new_packet_log, set_compact_packet_log


def _pkts():
    out = []
    for i in range(40):
        p = Packet(packet_id=f"AP 1-{i:06d}" if i % 7 else f"odd id {i}", source="AP 1",
                   destination=f"STA 1-{i % 3 + 1}", payload_bytes=1500 + i, header_bytes=34,
                   created_at=10.0 * i, retry_count=i % 4, traffic_class=("voice", "best_effort")[i % 2])
        if i % 5:
            p.status, p.delivered_at, p.measured_sinr_db = "DELIVERED", 10.0 * i + 3.5 + (i % 3), 20.0 + i / 7
        elif i % 10 == 0:
            p.status = "DROPPED"
        if i % 6 == 0:
            p.file_id, p.file_packets, p.file_bytes, p.file_arrival = f"AP 1-F{i}", 3, 4500, 10.0 * i
        if i % 9 == 0:
            p.tb_bits, p._dup = 1234.5, True
        out.append(p)
    return out


def test_slots():
    p = Packet("a", "b", "c", 1, 0)
    assert not hasattr(p, "__dict__")
    with pytest.raises(AttributeError):
        p.not_a_field = 1


def test_round_trip_and_order():
    pk = _pkts()
    log = CompactPacketLog(live=0)
    log.extend(pk[:10])
    for p in pk[10:]:
        log.append(p)
    assert len(log) == 40
    assert list(log) == pk                                    # every field back, same order
    assert len(log._sparse) < 40                              # sparse fields only where set


def test_recent_entries_stay_live():
    log = CompactPacketLog(live=5)
    pk = _pkts()
    log.extend(pk)
    tail = list(log)[-5:]
    assert all(a is b for a, b in zip(tail, pk[-5:]))         # same objects: later changes still seen
    pk[-1].status = "DROPPED"
    assert list(log)[-1].status == "DROPPED"


def test_many_distinct_strings_do_not_overflow_codes():
    log = CompactPacketLog(live=0)
    for i in range(70_000):
        log.append(Packet(f"x{i}y", f"src{i}", "d", 1, 0, status="DELIVERED", delivered_at=1.0))
    last = list(log)[-1]
    assert (last.packet_id, last.source, last.status) == ("x69999y", "src69999", "DELIVERED")


def test_one_pass_stats_match_lists():
    pk = _pkts()
    log = CompactPacketLog(live=3)
    log.extend(pk)
    assert compute_packet_stats(PacketView([log])) == compute_packet_stats(pk)
    assert compute_packet_stats_by_class(PacketView([log])) == compute_packet_stats_by_class(pk)
    s = compute_packet_stats(pk)
    lat = sorted(p.delivered_at - p.created_at for p in pk if p.status == "DELIVERED")
    assert s["delivered"] == len(lat) and s["min_latency_us"] == lat[0] and s["max_latency_us"] == lat[-1]


def test_factory_and_cli_same_output():
    set_compact_packet_log(True)
    assert isinstance(new_packet_log(), CompactPacketLog)
    set_compact_packet_log(False)
    assert new_packet_log() == []
    from singleRun import single_run
    args = ["--ap-number", "2", "--gnb-number", "1", "--seed", "2", "-t", "0.5", "-r", "1",
            "--wifi-traffic-model", "poisson", "--wifi-arrival-rate-pps", "800", "--fairness-report"]
    old = CompactPacketLog.LIVE
    CompactPacketLog.LIVE = 5
    try:
        runner = CliRunner()
        with runner.isolated_filesystem():
            a = runner.invoke(single_run, args)
            b = runner.invoke(single_run, args + ["--compact-packet-log"])
            c = runner.invoke(single_run, args)                 # flag doesn't leak into the next run
    finally:
        CompactPacketLog.LIVE = old
        set_compact_packet_log(False)
    assert a.exit_code == 0 and b.exit_code == 0, b.output[-300:]
    assert a.output == b.output == c.output
# Rashed-Step 24.B-10-19-2026-end
