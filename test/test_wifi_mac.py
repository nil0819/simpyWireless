# Rashed-Step 20.A-10-08-2026-start
"""
Step 20.A tests: 802.11 frame exchange on the air (Config.mac_exchange,
wifi/mac.py) - ACK / Block Ack transmissions, NAV, EIFS, RTS/CTS, the
ACK-lost duplicate bookkeeping, and agreement with Bianchi's model.
"""

import contextlib
import io
import logging
import os
import sys
from types import SimpleNamespace

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest
import simpy
from click.testing import CliRunner

import simulation
from channel.channel import ActiveTx, Channel
from common.common import Frame
from common.packet import Packet
from model import bianchi
from model.compare import _cluster_ap_positions
from model.runner import run_scenario
from nru.nru import Config_NR
from singleRun import single_run
from wifi import mac
from wifi.wifi import Config


def _run(cfg, n_ap=1, positions=None, t=0.3, seed=1):
    logging.disable(logging.CRITICAL)
    aps, chans = [], []
    orig_w, orig_c = simulation.WiFi, simulation.Channel

    class SpyW(orig_w):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            aps.append(self)

    class SpyC(orig_c):
        def __post_init__(self):
            super().__post_init__()
            chans.append(self)

    simulation.WiFi, simulation.Channel = SpyW, SpyC
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            backoffs = {k: {n_ap: 0} for k in range(1024)}
            simulation.run_simulation(n_ap, 0, seed, t, cfg, Config_NR(), backoffs, {}, {}, {}, {}, False,
                                      ap_positions=positions or [(0.0, 0.0)], sta_radius=3.0)
    finally:
        simulation.WiFi, simulation.Channel = orig_w, orig_c
        logging.disable(logging.NOTSET)
    return aps, chans[0]


def test_control_frame_durations():
    assert mac.ctrl_frame_us(14, 24) == 28          # ACK / CTS at 24 Mbps (the old fixed 44 = SIFS + 28)
    assert mac.ctrl_frame_us(14, 6) == 44           # ACK at 6 Mbps
    assert mac.ctrl_frame_us(20, 24) == 28 and mac.ctrl_frame_us(32, 24) == 32
    assert mac.EIFS_US == 16 + 44 + 34


def test_off_by_default_no_control_frames_on_the_air():
    assert Config().mac_exchange is False and Config().rts_threshold_bytes is None
    aps, ch = _run(Config())
    assert ch.tx_count["WiFi"] == aps[0].succeeded_transmissions + aps[0].failed_transmissions
    assert aps[0].mac_stats["exchanges"] == 0


def test_acks_go_on_the_air():
    aps, ch = _run(Config(mac_exchange=True))
    ap = aps[0]
    st = ap.mac_stats
    done = ap.succeeded_transmissions + ap.failed_transmissions
    assert done > 0 and st["exchanges"] - done in (0, 1)          # one may be in flight at the end
    assert st["acks"] - ap.succeeded_transmissions in (0, 1) and st["acks_lost"] == 0 and st["rts"] == 0
    # ACK airtime is on the channel: total Wi-Fi airtime = data frames + 28 us per ACK.
    data_us = ch.airtime_data[ap.name]
    assert ch.tx_airtime_total_us["WiFi"] == pytest.approx(data_us + 28 * st["acks"])


def test_rts_cts_above_the_threshold_only():
    aps, ch = _run(Config(mac_exchange=True, rts_threshold_bytes=0))
    st = aps[0].mac_stats
    assert st["rts"] == st["exchanges"] > 0 and st["rts_failed"] == 0
    aps, ch = _run(Config(mac_exchange=True, rts_threshold_bytes=2000))      # 1472-byte payloads
    assert aps[0].mac_stats["rts"] == 0


def _stub():
    env = simpy.Environment()
    ch = Channel(simpy.PriorityResource(env, capacity=1), simpy.Resource(env, capacity=1), 1, 0, {}, {}, {}, {}, {})
    return env, ch, SimpleNamespace(env=env, channel=ch, config=Config(), name="AP 1", mac_stats=mac.new_stats())


def test_decoded_frame_sets_a_nav_for_the_rest_of_the_exchange():
    env, ch, node = _stub()
    res = []

    def go():
        res.append((yield from mac.send_control(node, "AP 1", (0.0, 0.0), (5.0, 0.0), mac.RTS_BYTES, nav_after_us=500)))
    env.process(go())
    env.run(until=29)                                  # RTS is 28 us
    assert res == [True]
    assert ch.nav_busy((10.0, 0.0), -82.0)             # third party in range
    assert not ch.nav_busy((10.0, 0.0), -82.0, exclude_tx_id="AP 1")
    assert not ch.nav_busy((200.0, 0.0), -82.0)        # too far to decode
    env.run(until=600)
    assert not ch.nav_busy((10.0, 0.0), -82.0)         # expired


def test_eifs_after_an_undecoded_frame_until_a_good_one():
    env, ch, node = _stub()
    mk = lambda tid, t_end: ActiveTx(tx_id=tid, tx_pos=(0.0, 0.0), rx_pos=(5.0, 0.0), tx_start=0.0,
                                     tx_power_dbm=20.0, f_hz=5.18e9, pl_exp=3.0, t_end=t_end, tech="WiFi")
    ch.note_wifi_frame(mk("AP 2", 100.0), False)
    assert ch.eifs_applies((10.0, 0.0), -82.0)
    assert not ch.eifs_applies((10.0, 0.0), -82.0, exclude_tx_id="AP 2")      # its own frame
    assert not ch.eifs_applies((500.0, 0.0), -82.0)                           # didn't hear it
    ch.note_wifi_frame(mk("AP 3", 150.0), True)
    assert not ch.eifs_applies((10.0, 0.0), -82.0)


def test_lost_ack_delivers_once_and_counts_the_duplicate():
    node = SimpleNamespace(mac_stats=mac.new_stats(), env=SimpleNamespace(now=500.0), packet_log=[],
                           channel=SimpleNamespace(bytes_sent=0))
    pkt = Packet(packet_id="p1", source="AP 1", destination="STA 1-1", payload_bytes=1472, header_bytes=40,
                 created_at=0.0)
    frame = Frame(250, "AP 1", "", 1472, 0.0)
    frame.packet = pkt
    calls = []

    def on_ok():                                        # like sent_completed
        pkt.status, pkt.delivered_at = "DELIVERED", node.env.now
        node.packet_log.append(pkt)
        calls.append("ok")

    assert mac.finish(node, frame, "ack_lost", 250.0, on_ok, lambda: calls.append("fail")) is False
    assert calls == ["fail"] and frame.rx_delivered_at == 250.0
    assert mac.finish(node, frame, "ok", 600.0, on_ok, lambda: None) is True
    assert pkt.delivered_at == 250.0 and node.mac_stats["duplicates"] == 1


def test_lost_ack_then_retry_limit_still_counts_delivered():
    node = SimpleNamespace(mac_stats=mac.new_stats(), env=SimpleNamespace(now=0.0), packet_log=[],
                           channel=SimpleNamespace(bytes_sent=0))
    pkt = Packet(packet_id="p1", source="AP 1", destination="STA 1-1", payload_bytes=1472, header_bytes=40,
                 created_at=0.0)
    frame = Frame(250, "AP 1", "", 1472, 0.0)
    frame.packet = pkt

    def drop():                                         # like sent_failed past r_limit
        pkt.status = "DROPPED"
        node.packet_log.append(pkt)
    mac.finish(node, frame, "ack_lost", 250.0, None, drop)
    assert pkt.status == "DELIVERED" and pkt.delivered_at == 250.0 and node.channel.bytes_sent == 1472


def test_collision_probability_matches_bianchi_with_acks_on_the_air():
    # 3 saturated APs on a 3 m circle (one collision domain).
    ps = []
    for seed in (1, 2):
        argv = ["--ap-number", "3", "--gnb-number", "0", "-t", "1", "-r", "1", "--seed", str(seed),
                "--wifi-traffic-model", "saturated", "--area-w", "20", "--area-h", "20", "--sta-radius", "3",
                "--wifi-mac-exchange", "--wifi-preamble-detect"]
        for pos in _cluster_ap_positions("0,0", 3, 3.0):
            argv += ["--ap-pos", pos]
        ps.append(run_scenario(argv)["pcoll_wifi"])
    assert abs(sum(ps) / len(ps) - bianchi.collision_probability(3, 15, 63)) < 0.03


def test_ampdu_block_ack_on_the_air():
    aps, ch = _run(Config(mac_exchange=True, ampdu_max_mpdus=8))
    ap = aps[0]
    assert ap.mac_stats["acks"] == ap.ampdu_stats["ppdus"] > 0
    assert ch.tx_airtime_total_us["WiFi"] == pytest.approx(ch.airtime_data[ap.name] + 32 * ap.mac_stats["acks"])
    delivered = [p for p in ap.packet_log if p.status == "DELIVERED"]
    assert len(delivered) == len({p.packet_id for p in delivered}) == ap.ampdu_stats["mpdus_ok"]


def test_cli():
    base = ["--ap-number", "2", "--gnb-number", "0", "--seed", "1", "-t", "0.05", "-r", "1"]
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("log", exist_ok=True)
        off = runner.invoke(single_run, base)
        on = runner.invoke(single_run, base + ["--wifi-mac-exchange", "--wifi-rts-threshold", "500"])
        bad = runner.invoke(single_run, base + ["--wifi-rts-threshold", "500"])
    assert off.exit_code == 0 and on.exit_code == 0, on.output[-400:]
    assert "Wi-Fi MAC" not in off.output and "=== Wi-Fi MAC ===" in on.output
    assert bad.exit_code != 0
# Rashed-Step 20.A-10-08-2026-end
