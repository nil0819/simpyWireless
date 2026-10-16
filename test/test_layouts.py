# Rashed-Step 22.D-10-15-2026-start
"""
Step 22.D tests: multi-cell layouts (common/layouts.py), per-cell channels,
the per-cell report (common/cell_report.py) and the singleRun.py options.
"""
import math
import os
import re
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest
from click.testing import CliRunner

from common.cell_report import compute_cell_report
from common.layouts import assign_channels, build_layout, hex_sites
from common.packet import Packet


def _d(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def test_tr38889_indoor():
    L = build_layout("tr38889-indoor", 1)
    assert (L.area_w, L.area_h) == (120.0, 80.0)
    assert [s.pos for s in L.operator_sites("A")] == [(20.0, 20.0), (60.0, 20.0), (100.0, 20.0)]
    assert [s.pos for s in L.operator_sites("B")] == [(20.0, 60.0), (60.0, 60.0), (100.0, 60.0)]
    for op in ("A", "B"):
        own = L.operator_sites(op)
        for s in own:
            assert len(s.users) == 5
            for u in s.users:                                   # kept by the nearest cell of its operator
                assert 0 <= u[0] <= 120 and 0 <= u[1] <= 80
                assert _d(u, s.pos) == min(_d(u, o.pos) for o in own)


def test_tgax_layouts():
    R = build_layout("tgax-residential", 2, rows=2, cols=3, users_per_cell=3)
    assert len(R.sites) == 6 and (R.area_w, R.area_h) == (30.0, 20.0) and R.room_size_m == 10.0
    for s in R.sites:                                           # AP and its STAs in the same apartment
        room = (math.floor(s.pos[0] / 10), math.floor(s.pos[1] / 10))
        assert all((math.floor(u[0] / 10), math.floor(u[1] / 10)) == room for u in s.users) and len(s.users) == 3
    E = build_layout("tgax-enterprise", 2)
    assert len(E.sites) == 32 and (E.area_w, E.area_h) == (80.0, 40.0) and E.room_size_m == 20.0
    assert all(_d(u, s.pos) <= 5 * math.sqrt(2) + 1e-9 for s in E.sites for u in s.users)


def test_hex_layout():
    assert len(hex_sites(1, 100.0)) == 7 and len(hex_sites(2, 100.0)) == 19
    H = build_layout("hex", 3, hex_rings=1, hex_isd_m=100.0)
    ds =sorted(_d(a.pos, b.pos) for i, a in enumerate(H.sites) for b in H.sites[i + 1:])
    assert ds[0] == pytest.approx(100.0)                        # nearest neighbours one ISD apart
    for s in H.sites:
        assert len(s.users) == 5
        assert all(_d(u, s.pos) == min(_d(u, o.pos) for o in H.sites) for u in s.users)
    with pytest.raises(ValueError):
        build_layout("hex", 1, hex_rings=3)


def test_layout_reproducible_per_seed():
    a, b, c = (build_layout("tgax-residential", s) for s in (5, 5, 6))
    assert [x.users for x in a.sites] == [x.users for x in b.sites]
    assert [x.users for x in a.sites] != [x.users for x in c.sites]


def test_channel_reuse():
    grid = [(0, 0), (10, 0), (0, 10), (10, 10)]
    assert set(assign_channels(grid, 1)) == {5.18e9}
    assert len(set(assign_channels(grid, 4))) == 4
    line = [(10.0 * i, 0.0) for i in range(9)]
    ch = assign_channels(line, 3)
    assert all(ch[i] != ch[i + 1] for i in range(8))           # neighbours never share a channel
    with pytest.raises(ValueError):
        assign_channels(grid, 9)


def _pkt(src, dst, size, ok=True):
    p = Packet(packet_id=f"{src}-{dst}-{size}", source=src, destination=dst, payload_bytes=size, header_bytes=0)
    p.status = "DELIVERED" if ok else "DROPPED"
    return p


def test_cell_report():
    cells = [("AP 1", "WiFi", 5.18e9, ["STA 1-1", "STA 1-2"],
              [_pkt("AP 1", "STA 1-1", 1000), _pkt("STA 1-1", "AP 1", 500), _pkt("AP 1", "STA 1-2", 9999, ok=False)]),
             ("AP 2", "WiFi", 5.20e9, ["STA 2-1"], [_pkt("AP 2", "STA 2-1", 1500)])]
    r = compute_cell_report(cells, 1.0)
    c1 = r["cells"][0]
    assert c1["f_ghz"] == pytest.approx(5.18) and c1["throughput_mbps"] == pytest.approx(1500 * 8 / 1e6)
    assert c1["user_mbps"] == {"STA 1-1": pytest.approx(1500 * 8 / 1e6), "STA 1-2": 0.0}
    t = r["tech"]["WiFi"]
    assert t["cells"] == 2 and t["users"] == 3
    assert t["jain_cells"] == pytest.approx(1.0)                # 0.012 and 0.012 Mbps
    assert t["user_p5_mbps"] < t["user_p50_mbps"]


def test_cli():
    from singleRun import single_run
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("log", exist_ok=True)
        lay = runner.invoke(single_run, ["--seed", "1", "-t", "0.1", "-r", "1", "--layout", "tr38889-indoor",
                                         "--pathloss-model", "inh-office-mixed", "--cell-report"])
        reuse = runner.invoke(single_run, ["--seed", "1", "-t", "0.1", "-r", "1", "--layout", "tgax-residential",
                                           "--layout-cols", "3", "--channel-reuse", "3", "--cell-report"])
        explicit = runner.invoke(single_run, ["--ap-number", "2", "--gnb-number", "1", "--seed", "1", "-t", "0.1",
                                              "-r", "1", "--wifi-ap-freq-ghz", "5.18", "--wifi-ap-freq-ghz", "5.24",
                                              "--wifi-stas-per-ap", "2", "--cell-report"])
        bad = [runner.invoke(single_run, a) for a in (
            ["--layout", "hex", "--ap-number", "3"],
            ["--ap-number", "1", "--gnb-number", "1", "--hex-isd-m", "50"],
            ["--gnb-number", "1"],
            ["--ap-number", "2", "--gnb-number", "0", "--channel-reuse", "2"],          # random positions
            ["--ap-number", "1", "--gnb-number", "0", "--wifi-ap-freq-ghz", "5.18", "--wifi-ap-freq-ghz", "5.2"])]
    assert lay.exit_code == 0, lay.output[-400:]
    assert "AP 1 (20.0, 60.0)" in lay.output and "Gnb 1 (20.0, 20.0)" in lay.output
    assert re.search(r"NR-U: 3 cells, .* 15 users", lay.output) and re.search(r"Wi-Fi: 3 cells, .* 15 users", lay.output)
    assert reuse.exit_code == 0, reuse.output[-400:]
    chans = re.findall(r"AP \d+: Wi-Fi ([\d.]+) GHz, 2 users", reuse.output)
    assert len(chans) == 6 and len(set(chans)) == 3
    assert explicit.exit_code == 0, explicit.output[-400:]
    assert "AP 1: Wi-Fi 5.18 GHz, 2 users" in explicit.output and "AP 2: Wi-Fi 5.24 GHz, 2 users" in explicit.output
    assert all(b.exit_code != 0 for b in bad), [b.output[-200:] for b in bad]
# Rashed-Step 22.D-10-15-2026-end
