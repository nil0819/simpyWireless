# Rashed-Step 18.B-10-06-2026-start
"""
Step 18.B tests: per-UE byte buffers (ran/protocol/buffer.py) and
buffered traffic in licensed NR (Config_NRL.dl_traffic/ul_traffic,
singleRunNR.py --dl-traffic/--ul-traffic).
"""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import simpy
from click.testing import CliRunner

from common.packet import Packet, TrafficConfig
from nr.nr import Config_NRL
from ran.protocol.buffer import (
    ByteBuffer,
    arrival_process,
    traffic_configs_from_cli,
    validate_buffered_traffic,
)
from simulation_nr import run_simulation_licensed_nr
from singleRunNR import single_run_nr


def _pkt(i, size=1000, t=0.0):
    return Packet(packet_id=f"p{i}", source="g", destination="u", payload_bytes=size,
                  header_bytes=0, created_at=t)


def _expect_value_error(fn, needle):
    try:
        fn()
    except ValueError as e:
        assert needle in str(e)
    else:
        assert False, "expected ValueError"


# ---------------------------------------------------------------------
# ByteBuffer
# ---------------------------------------------------------------------

def test_segments_are_read_only_and_split_packets():
    b = ByteBuffer()
    for i in range(3):
        b.enqueue(_pkt(i))
    segs = b.segments(2500)
    assert [(p.packet_id, n, last) for p, n, last in segs] == [("p0", 1000, True), ("p1", 1000, True), ("p2", 500, False)]
    assert b.backlog_bytes == 3000 and len(b) == 3


def test_deliver_completes_packets_and_carries_partial_head():
    b = ByteBuffer()
    for i in range(3):
        b.enqueue(_pkt(i))
    assert b.deliver(b.segments(2500), now=10.0) == 2500
    assert b.backlog_bytes == 500 and len(b) == 1
    done = b.drain_finished()
    assert [p.packet_id for p in done] == ["p0", "p1"]
    assert all(p.status == "DELIVERED" and p.delivered_at == 10.0 for p in done)
    # The rest of p2 goes first in the next TB.
    segs = b.segments(4000)
    assert [(p.packet_id, n, last) for p, n, last in segs] == [("p2", 500, True)]
    b.deliver(segs, now=20.0)
    assert b.backlog_bytes == 0 and len(b) == 0
    assert b.stats["delivered_bytes"] == 3000 and b.stats["delivered_packets"] == 3


def test_lose_drops_every_packet_in_the_tb_including_a_partly_sent_head():
    b = ByteBuffer()
    for i in range(3):
        b.enqueue(_pkt(i))
    b.deliver(b.segments(400), now=1.0)  # 400 bytes of p0 got through
    assert b.backlog_bytes == 2600
    assert b.lose(b.segments(1200)) == 2  # rest of p0 + 600 of p1
    assert b.backlog_bytes == 1000 and b.head().packet_id == "p2"
    dropped = b.drain_finished()
    assert [p.packet_id for p in dropped] == ["p0", "p1"]
    assert all(p.status == "DROPPED" for p in dropped)
    assert b.stats["dropped_tb_error"] == 2
    # p2 starts from its first byte.
    assert b.segments(5000)[0][1] == 1000


def test_drop_tail_limit():
    b = ByteBuffer(limit_bytes=2500)
    assert b.enqueue(_pkt(0)) and b.enqueue(_pkt(1))
    assert not b.enqueue(_pkt(2))
    assert b.backlog_bytes == 2000 and b.stats["dropped_overflow"] == 1
    assert b.stats["max_backlog_bytes"] == 2000
    assert b.drain_finished()[0].status == "DROPPED"


def test_empty_buffer_segments():
    assert ByteBuffer().segments(1000) == []
    assert ByteBuffer().head() is None


# ---------------------------------------------------------------------
# arrivals / validation / CLI mapping
# ---------------------------------------------------------------------

def test_cbr_arrivals_are_evenly_spaced():
    env = simpy.Environment()
    b = ByteBuffer()
    seq = iter(range(1000))
    env.process(arrival_process(env, b, TrafficConfig(mode="cbr", arrival_rate_pps=1000.0),
                                lambda: _pkt(next(seq), t=env.now), lambda r: 1 / r))
    env.run(until=10_500)
    assert len(b) == 10
    assert [s[0].created_at for s in b.segments(10**9)][:3] == [1000.0, 2000.0, 3000.0]


def test_validate_buffered_traffic():
    _expect_value_error(lambda: validate_buffered_traffic(TrafficConfig(mode="saturated")), "must be one of")
    _expect_value_error(lambda: validate_buffered_traffic(TrafficConfig(mode="cbr", arrival_rate_pps=0)), "> 0 packets/s")
    _expect_value_error(lambda: validate_buffered_traffic(TrafficConfig(mode="cbr", packet_size_bytes=0)), "> 0 bytes")


def test_traffic_configs_from_cli():
    assert traffic_configs_from_cli("full_buffer", None, "full_buffer", None, None, None, False) == (None, None)
    dl, ul = traffic_configs_from_cli("poisson", 50.0, "cbr", None, 200, 10_000, True)
    assert (dl.mode, dl.arrival_rate_pps, dl.packet_size_bytes) == ("poisson", 50.0, 200)
    assert (ul.mode, ul.arrival_rate_pps) == ("cbr", 100.0)
    _expect_value_error(lambda: traffic_configs_from_cli("full_buffer", 5.0, "full_buffer", None, None, None, False),
                        "--dl-arrival-rate-pps requires")
    _expect_value_error(lambda: traffic_configs_from_cli("full_buffer", None, "cbr", None, None, None, False),
                        "requires --ue-uplink-enabled")
    _expect_value_error(lambda: traffic_configs_from_cli("full_buffer", None, "full_buffer", None, 100, None, False),
                        "require --dl-traffic or --ul-traffic")
    _expect_value_error(lambda: traffic_configs_from_cli("cbr", None, "full_buffer", None, None, 0, False),
                        "must be > 0")


# ---------------------------------------------------------------------
# licensed NR integration
# ---------------------------------------------------------------------

def _run(cfg, t=0.2, **kw):
    return run_simulation_licensed_nr(1, 2, t, cfg, nr_ues_per_gnb=4, ue_radius=60.0, **kw)


def test_light_load_delivers_everything_offered():
    cfg = Config_NRL(dl_traffic=TrafficConfig(mode="cbr", arrival_rate_pps=500.0))
    st = _run(cfg)["traffic_stats"]["dl"]
    # 4 UEs x 99 arrivals (every 2 ms from t=2 ms; the one at 200 ms is past
    # the end); all but the last slot's get through.
    assert st["enqueued_packets"] == 396
    assert st["delivered_packets"] >= 392
    assert st["dropped_tb_error"] == st["dropped_overflow"] == 0
    assert abs(st["delivered_mbps"] - st["offered_mbps"]) < 0.1 * st["offered_mbps"]
    # Underloaded: latency is about a slot, not a queue build-up.
    assert st["packet_stats"]["avg_latency_us"] < 2_000


def test_throughput_counts_delivered_bytes_not_capacity():
    full = _run(Config_NRL())
    light = _run(Config_NRL(dl_traffic=TrafficConfig(mode="cbr", arrival_rate_pps=100.0)))
    assert light["throughput_mbps"] < 0.1 * full["throughput_mbps"]
    assert abs(light["throughput_mbps"] - light["traffic_stats"]["dl"]["delivered_mbps"]) < 1e-9


def test_overload_is_capped_by_capacity_and_drop_tail():
    full_mbps = _run(Config_NRL())["throughput_mbps"]
    cfg = Config_NRL(dl_traffic=TrafficConfig(mode="cbr", arrival_rate_pps=100_000.0), buffer_limit_bytes=200_000)
    res = _run(cfg)
    st = res["traffic_stats"]["dl"]
    assert st["offered_mbps"] > full_mbps
    assert st["delivered_mbps"] <= full_mbps * 1.01
    assert st["dropped_overflow"] > 0
    assert st["max_backlog_bytes"] <= 200_000


def test_full_buffer_default_has_no_buffers():
    res = _run(Config_NRL())
    assert res["traffic_stats"] == {}


def test_buffered_uplink():
    cfg = Config_NRL(tdd_enabled=True, ul_traffic=TrafficConfig(mode="cbr", arrival_rate_pps=200.0))
    # One UE: two UEs in the same UL slot currently interfere with each
    # other despite separate RBs (pre-existing channel issue found in
    # 18.B, tracked separately).
    res = run_simulation_licensed_nr(1, 2, 0.2, cfg, nr_ues_per_gnb=1, ue_radius=40.0, nr_ue_uplink_enabled=True)
    st = res["traffic_stats"]["ul"]
    assert "dl" not in res["traffic_stats"]
    assert st["enqueued_packets"] == 39  # every 5 ms from 5 ms
    assert st["delivered_packets"] >= 37
    assert st["dropped_tb_error"] == 0


def _cli(args):
    runner = CliRunner()
    with runner.isolated_filesystem():
        return runner.invoke(single_run_nr, args)


NR_BASE = ["--gnb-number", "1", "--ues-per-gnb", "2", "--seed", "1", "-t", "0.05"]


def test_cli_blocks_only_when_buffered():
    r = _cli(NR_BASE)
    assert r.exit_code == 0, (r.output, r.exception)
    assert "Traffic ===" not in r.output
    r = _cli(NR_BASE + ["--dl-traffic", "poisson", "--dl-arrival-rate-pps", "200"])
    assert r.exit_code == 0, (r.output, r.exception)
    assert "=== Licensed 5G NR DL Traffic ===" in r.output
    assert "=== Licensed 5G NR UL Traffic ===" not in r.output


def test_cli_rejects_ul_traffic_without_uplink():
    r = _cli(NR_BASE + ["--ul-traffic", "cbr"])
    assert r.exit_code != 0
    assert "requires --ue-uplink-enabled" in r.output
# Rashed-Step 18.B-10-06-2026-end
