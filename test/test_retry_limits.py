# Rashed-Step 21.D-10-11-2026-start
"""
Step 21.D tests: 802.11 short/long retry counters (wifi/mac.retry_exhausted)
and control responses at the rate-adapted data MCS.
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

from click.testing import CliRunner

import simulation
from common.common import Frame
from common.packet import Packet
from nru.nru import Config_NR
from singleRun import single_run
from wifi import mac
from wifi.wifi import Config


def _frame(payload=1472):
    f = Frame(250, "AP 1", "", payload, 0.0)
    f.packet = Packet(packet_id="p", source="AP 1", destination="STA 1-1", payload_bytes=payload, header_bytes=40,
                      created_at=0.0)
    return f


def _fail(cfg, f, res):
    """One failed exchange the way finish() + sent_failed() handle it."""
    node = SimpleNamespace(config=cfg, mac_stats=mac.new_stats(), env=SimpleNamespace(now=0.0), packet_log=[],
                           channel=SimpleNamespace(bytes_sent=0))
    out = []

    def on_fail():
        f.number_of_retransmissions += 1
        out.append(mac.retry_exhausted(cfg, f))
    mac.finish(node, f, res, 100.0, None, on_fail)
    return out[0]


def test_default_is_the_single_retry_limit():
    cfg = Config(r_limit=7)
    f = _frame()
    results = [_fail(cfg, f, "data_fail") for _ in range(8)]
    assert results == [False] * 7 + [True]


def test_short_counter_for_frames_without_rts():
    cfg = Config(mac_exchange=True, short_retry_limit=7, long_retry_limit=4, rts_threshold_bytes=2000)
    f = _frame(1472)                                   # below the threshold: no RTS, short counter
    assert [_fail(cfg, f, "data_fail") for _ in range(8)] == [False] * 7 + [True]


def test_long_counter_after_a_cts_and_short_counter_for_rts_failures():
    cfg = Config(mac_exchange=True, short_retry_limit=7, long_retry_limit=4, rts_threshold_bytes=500)
    f = _frame(1472)                                   # above the threshold: RTS/CTS first
    assert [_fail(cfg, f, "data_fail") for _ in range(5)] == [False] * 4 + [True]     # CTS came back: long
    g = _frame(1472)
    assert [_fail(cfg, g, "rts_fail") for _ in range(8)] == [False] * 7 + [True]      # no CTS: short
    h = _frame(1472)
    for _ in range(6):
        _fail(cfg, h, "rts_fail")                        # SRC 6 ...
    assert _fail(cfg, h, "data_fail") is False and h._src == 0   # ... reset by the CTS, LRC 1


def test_forced_data_failures_drop_after_the_long_limit():
    logging.disable(logging.CRITICAL)
    aps = []
    orig = simulation.WiFi

    class Spy(orig):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            aps.append(self)
    simulation.WiFi = Spy
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            cfg = Config(mac_exchange=True, rts_threshold_bytes=0, short_retry_limit=7, long_retry_limit=4,
                         wifi_sinr_thr_db_override=200.0)       # data never decodes; RTS/CTS do
            simulation.run_simulation(1, 0, 1, 0.2, cfg, Config_NR(), {k: {1: 0} for k in range(1024)},
                                      {}, {}, {}, {}, False, ap_positions=[(0.0, 0.0)], sta_radius=3.0)
    finally:
        simulation.WiFi = orig
        logging.disable(logging.NOTSET)
    dropped = [p for p in aps[0].packet_log if p.status == "DROPPED"]
    assert dropped and {p.retry_count for p in dropped} == {5}         # 1 + 4 long retries


def test_control_rate_follows_rate_adaptation():
    cfg = Config(mcs=7, rate_adapt_enabled=True)
    node = SimpleNamespace(config=cfg, current_mcs_for_link=lambda k: 1, rate_adapt_link_key=lambda: "STA 1-1")
    assert mac.ctrl_rate(node) == 6                    # MCS 1 (9 Mbps) -> 6 Mbps basic rate
    assert mac.ctrl_rate(SimpleNamespace(config=Config(mcs=7))) == 24


def test_cli():
    base = ["--ap-number", "1", "--gnb-number", "0", "--seed", "1", "-t", "0.05", "-r", "1", "--wifi-mac-exchange",
            "--wifi-rts-threshold", "500"]
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("log", exist_ok=True)
        r = runner.invoke(single_run, base + ["--wifi-short-retry-limit", "7", "--wifi-long-retry-limit", "4"])
    assert r.exit_code == 0, r.output[-300:]
# Rashed-Step 21.D-10-11-2026-end
