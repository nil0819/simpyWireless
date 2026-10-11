# Rashed-Step 21.A-10-11-2026-start
"""
Step 21.A tests: single-user downlink to each packet's own STA (was:
every packet addressed to and decoded at sta_list[0]).
"""

import contextlib
import io
import logging
import os
import sys
from collections import Counter

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from click.testing import CliRunner

import simulation
from common.common_phy import dist
from common.packet import TrafficConfig
from nru.nru import Config_NR
from singleRun import single_run
from wifi import ampdu
from wifi.wifi import Config


def _run(cfg, n=4, traffic=None, t=0.3, regs=None):
    logging.disable(logging.CRITICAL)
    aps = []
    orig_w, orig_reg = simulation.WiFi, simulation.Channel.register_tx

    class Spy(orig_w):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            aps.append(self)

    def reg(ch, tx):
        regs.append(tx)
        return orig_reg(ch, tx)

    simulation.WiFi = Spy
    if regs is not None:
        simulation.Channel.register_tx = reg
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            backoffs = {k: {1: 0} for k in range(1024)}
            simulation.run_simulation(1, 0, 1, t, cfg, Config_NR(), backoffs, {}, {}, {}, {}, False,
                                      ap_positions=[(0.0, 0.0)], sta_radius=25.0, wifi_stas_per_ap=n,
                                      wifi_traffic_config=traffic)
    finally:
        simulation.WiFi = orig_w
        simulation.Channel.register_tx = orig_reg
        logging.disable(logging.NOTSET)
    return aps[0]


def test_one_sta_is_unchanged():
    ap = _run(Config(), n=1)
    assert {p.destination for p in ap.packet_log} == {ap.sta_list[0].name}


def test_packets_spread_over_the_stas_and_are_decoded_at_each():
    regs = []
    ap = _run(Config(), regs=regs)
    c = Counter(p.destination for p in ap.packet_log if p.status == "DELIVERED")
    assert set(c) == {s.name for s in ap.sta_list} and max(c.values()) - min(c.values()) <= 1
    by_name = {s.name: s for s in ap.sta_list}
    data = [t for t in regs if t.tx_id == ap.name and t.packet is not None]
    assert data and all(t.rx_pos == by_name[t.packet.destination].current_pos() for t in data)
    # the closer STA sees the higher SINR
    sinr = {n: [p.measured_sinr_db for p in ap.packet_log if p.destination == n] for n in by_name}
    near = min(by_name, key=lambda n: dist(by_name[n].current_pos(), ap.current_pos()))
    far = max(by_name, key=lambda n: dist(by_name[n].current_pos(), ap.current_pos()))
    assert sum(sinr[near]) / len(sinr[near]) > sum(sinr[far]) / len(sinr[far])


def test_rate_adaptation_per_sta():
    ap = _run(Config(rate_adapt_enabled=True))
    assert set(ap.link_rate_state) == {s.name for s in ap.sta_list}


def test_ack_comes_from_the_frames_sta():
    regs = []
    ap = _run(Config(mac_exchange=True), regs=regs)
    names = {s.name for s in ap.sta_list}
    pairs = 0
    for a, b in zip(regs, regs[1:]):
        if a.tx_id == ap.name and a.packet is not None and b.tx_id in names and b.t_end - b.tx_start == 28:
            assert b.tx_id == a.packet.destination
            pairs += 1
    assert pairs > 100


def test_ampdu_aggregates_one_receiver():
    seen = []
    orig = ampdu.send

    def spy(node, mpdus, *a, **k):
        seen.append({p.destination for p in mpdus})
        return (yield from orig(node, mpdus, *a, **k))
    ampdu.send = spy
    try:
        ap = _run(Config(ampdu_max_mpdus=16), traffic=TrafficConfig(mode="poisson", arrival_rate_pps=3000.0))
    finally:
        ampdu.send = orig
    assert seen and all(len(s) == 1 for s in seen)
    assert len({next(iter(s)) for s in seen}) == 4
    assert sum(1 for p in ap.packet_log if p.status == "DELIVERED") > 0.9 * 3000 * 0.3 * 0.9


def test_cli_stas_per_ap():
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("log", exist_ok=True)
        r = runner.invoke(single_run, ["--ap-number", "1", "--gnb-number", "0", "--seed", "1", "-t", "0.05", "-r", "1",
                                       "--wifi-stas-per-ap", "3"])
    assert r.exit_code == 0, r.output[-300:]
# Rashed-Step 21.A-10-11-2026-end
