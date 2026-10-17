# Rashed-Step 23.C-10-17-2026-start
"""
Step 23.C tests: FTP Model 3 traffic (TrafficConfig mode "ftp3") and its
file statistics (common/ftp.py).
"""
import os
import re
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest
import simpy
from click.testing import CliRunner

from common.ftp import compute_file_stats
from common.packet import Packet, TrafficConfig, ftp3_file
from ran.protocol.buffer import arrival_process, validate_buffered_traffic


def _maker(size=1500):
    seq = [0]

    def make():
        seq[0] += 1
        return Packet(packet_id=f"p{seq[0]}", source="AP 1", destination="STA 1-1", payload_bytes=size, header_bytes=0)
    return make


def test_file_split_and_tagged():
    tc = TrafficConfig(mode="ftp3", file_size_bytes=500_000)
    pkts = ftp3_file(_maker(1500), tc, "AP 1-F1", 42.0, "STA 1-2")
    assert len(pkts) == 334                                   # ceil(500000 / 1500)
    assert {p.file_id for p in pkts} == {"AP 1-F1"} and {p.destination for p in pkts} == {"STA 1-2"}
    assert all(p.file_packets == 334 and p.file_bytes == 500_000 and p.file_arrival == 42.0 for p in pkts)
    validate_buffered_traffic(tc)


def test_file_stats():
    tc = TrafficConfig(mode="ftp3", file_size_bytes=3000)
    a = ftp3_file(_maker(1500), tc, "A", 0.0)                 # 2 packets, done at 1000 us -> 24 Mbps
    b = ftp3_file(_maker(1500), tc, "B", 0.0)                 # one packet still pending
    c = ftp3_file(_maker(1500), tc, "C", 0.0)                 # one packet dropped
    for p, t in zip(a, (500.0, 1000.0)):
        p.status, p.delivered_at = "DELIVERED", t
    b[0].status, b[0].delivered_at = "DELIVERED", 100.0
    c[0].status, c[0].delivered_at = "DELIVERED", 100.0
    c[1].status = "DROPPED"
    s = compute_file_stats(a + [b[0]] + c)
    assert s["files_seen"] == 3 and s["files_completed"] == 1
    assert s["upt_mean_mbps"] == pytest.approx(3000 * 8 / 1000.0)
    assert s["transfer_mean_ms"] == pytest.approx(1.0)


def test_arrival_process_delivers_whole_files():
    class Buf:
        def __init__(self):
            self.got = []

        def enqueue(self, p):
            self.got.append(p)

    env = simpy.Environment()
    buf = Buf()
    tc = TrafficConfig(mode="ftp3", arrival_rate_pps=50.0, packet_size_bytes=1500, file_size_bytes=15_000)
    import random
    rng = random.Random(3)
    env.process(arrival_process(env, buf, tc, _maker(1500), rng.expovariate, "G1>UE 1-1"))
    env.run(until=1_000_000)
    ids = {}
    for p in buf.got:
        ids.setdefault(p.file_id, []).append(p)
    assert 30 < len(ids) < 80                                 # ~50 files in 1 s
    assert all(len(v) == 10 and len({p.file_arrival for p in v}) == 1 for v in ids.values())
    assert all(fid.startswith("G1>UE 1-1-F") for fid in ids)


def test_cli():
    from singleRun import single_run
    args = ["--ap-number", "1", "--gnb-number", "1", "--wifi-stas-per-ap", "2", "--seed", "1", "-t", "1", "-r", "1",
            "--ap-pos", "0,0", "--gnb-pos", "10,0", "--wifi-traffic-model", "ftp3", "--wifi-arrival-rate-pps", "4",
            "--nru-traffic-model", "ftp3", "--nru-arrival-rate-pps", "4", "--ftp-file-bytes", "200000"]
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("log", exist_ok=True)
        r1 = runner.invoke(single_run, args)
        r2 = runner.invoke(single_run, args + ["--nru-cot-model", "slots"])
        r3 = runner.invoke(single_run, args)
        bad = runner.invoke(single_run, args[:-2] + ["--ftp-file-bytes", "0"])
    for r in (r1, r2):
        assert r.exit_code == 0, r.output[-400:]
        assert "=== FTP Model 3 ===" in r.output
        assert re.search(r"Wi-Fi: files completed [1-9]\d* of", r.output)
        assert re.search(r"NR-U: files completed [1-9]\d* of", r.output)
    block = lambda r: r.output[r.output.index("=== FTP Model 3 ==="):].splitlines()[:3]
    assert block(r1) == block(r3)                              # reproducible
    assert bad.exit_code != 0
# Rashed-Step 23.C-10-17-2026-end
