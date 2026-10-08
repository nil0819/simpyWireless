# Rashed-Step 15.B-09-18-2026-start
"""
Step 15.B unit tests: WiFiSTA's new opt-in real uplink transmit/
contention path (env/channel/config/uplink_enabled fields,
WiFi.__init__'s automatic sta.ap back-reference, and the
wait_back_off()/send_frame()/sent_completed()/sent_failed() generator
methods themselves).

Same style/harness as test_packet.py/test_phy_unit.py: plain
assert-based pytest-discovered functions, no simulation.py involved.
"""

import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import simpy

from channel.channel import Channel
from wifi.wifi import WiFi, Config
from wifi.sta import WiFiSTA
from common.packet import TrafficConfig


def _make_channel(env, n_of_stations=1):
    return Channel(
        tx_queue=simpy.PriorityResource(env, capacity=1),
        tx_lock=simpy.Resource(env, capacity=1),
        n_of_stations=n_of_stations,
        n_of_gNB=0,
        backoffs={key: {n_of_stations: 0} for key in range(Config().cw_max + 1)},
        airtime_data={},
        airtime_control={},
        airtime_data_NR={},
        airtime_control_NR={},
    )


def _make_ap_with_uplink_sta(config=None, sta_pos=(1.0, 0.0), ap_pos=(0.0, 0.0)):
    """Real (non-fake) WiFi AP + a single uplink_enabled=True WiFiSTA,
    wired together exactly the way simulation.py's own construction
    order does it (STA built first, then the AP that owns it - see
    WiFiSTA's class docstring's WIRING section and WiFi.__init__'s
    back-reference loop)."""
    env = simpy.Environment()
    channel = _make_channel(env)
    cfg = config if config is not None else Config()
    sta = WiFiSTA(
        name="STA 1-1", pos=sta_pos, ap_name="AP 1",
        env=env, channel=channel, config=cfg, uplink_enabled=True,
    )
    ap = WiFi(env, "AP 1", channel, ap_pos, [sta], cfg)
    return env, channel, ap, sta


# ---------------------------------------------------------------------
# Backward compatibility: every pre-15.B WiFiSTA(...) call site passes
# none of the new fields - must stay a no-op.
# ---------------------------------------------------------------------

def test_default_construction_is_untouched():
    sta = WiFiSTA(name="STA 1-1", pos=(0.0, 0.0), ap_name="AP 1")
    assert sta.uplink_enabled is False
    assert sta.env is None
    assert sta.channel is None
    assert sta.config is None
    assert sta.ap is None
    # __post_init__ returns immediately when uplink_enabled is False -
    # none of the uplink-only state should exist at all.
    assert not hasattr(sta, "times")
    assert not hasattr(sta, "frame_to_send")


def test_wifi_init_back_references_every_sta_even_when_uplink_unused():
    """WiFi.__init__'s new back-reference loop (see wifi.py) runs
    unconditionally - must be a safe no-op for STAs that never use
    uplink at all."""
    env = simpy.Environment()
    channel = _make_channel(env)
    sta = WiFiSTA(name="STA 1-1", pos=(1.0, 0.0), ap_name="AP 1")
    ap = WiFi(env, "AP 1", channel, (0.0, 0.0), [sta], Config())
    assert sta.ap is ap
    assert sta.uplink_enabled is False


# ---------------------------------------------------------------------
# Fail-fast validation (mirrors WiFi's own qos_enabled=True EDCA gate).
# ---------------------------------------------------------------------

def test_uplink_enabled_requires_env_channel_config():
    try:
        WiFiSTA(name="S", pos=(0.0, 0.0), ap_name="AP 1", uplink_enabled=True)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "requires env, channel, and config" in str(e)


# Rashed-Step 20.B-10-08-2026-start
# Poisson/CBR uplink is supported since Step 20.B (this used to assert a
# "saturated only" ValueError); an unknown mode is still rejected.
def test_uplink_accepts_poisson_and_rejects_unknown_traffic():
    env = simpy.Environment()
    channel = _make_channel(env)
    sta = WiFiSTA(
        name="S", pos=(0.0, 0.0), ap_name="AP 1", uplink_enabled=True,
        env=env, channel=channel, config=Config(),
        traffic_config=TrafficConfig(mode="poisson", arrival_rate_pps=10.0),
    )
    assert sta.packet_queue is not None
    try:
        WiFiSTA(
            name="S2", pos=(0.0, 0.0), ap_name="AP 1", uplink_enabled=True,
            env=env, channel=channel, config=Config(),
            traffic_config=TrafficConfig(mode="bursty"),
        )
        assert False, "expected ValueError"
    except ValueError as e:
        assert "unknown traffic_config.mode" in str(e)
# Rashed-Step 20.B-10-08-2026-end


def test_uplink_process_raises_runtime_error_if_never_wired_to_an_ap():
    """A STA constructed with uplink_enabled=True but never placed in a
    WiFi AP's sta_list (so WiFi.__init__ never set sta.ap) must fail
    loudly the moment its process actually runs, not silently no-op or
    raise a confusing AttributeError deep inside packet construction."""
    env = simpy.Environment()
    channel = _make_channel(env)
    sta = WiFiSTA(
        name="Orphan STA", pos=(0.0, 0.0), ap_name="AP 1",
        env=env, channel=channel, config=Config(), uplink_enabled=True,
    )
    assert sta.ap is None
    try:
        env.run(until=10)
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "no AP reference was wired in" in str(e)


# ---------------------------------------------------------------------
# Functional: a real, close-range AP<->STA link actually exchanges
# uplink frames and updates the same shared channel state every other
# technology in this simulator already uses.
# ---------------------------------------------------------------------

def test_uplink_transmits_and_succeeds_at_close_range():
    env, channel, ap, sta = _make_ap_with_uplink_sta()
    env.run(until=50000)  # 50 ms

    assert sta.succeeded_transmissions + sta.failed_transmissions > 0
    assert sta.succeeded_transmissions > 0
    # channel-level aggregate counters must reflect both the AP's own
    # downlink and the STA's new uplink - the whole point of Step 15.B.
    assert channel.succeeded_transmissions == sta.succeeded_transmissions + ap.succeeded_transmissions
    assert channel.failed_transmissions == sta.failed_transmissions + ap.failed_transmissions

    # per-node airtime got populated for the STA specifically (it had no
    # pre-registered entry before this step - see WiFiSTA.__post_init__).
    assert channel.airtime_data.get("STA 1-1", 0) > 0
    assert channel.airtime_control.get("STA 1-1", 0) > 0


def test_uplink_delivered_packet_has_correct_direction_and_sinr():
    env, channel, ap, sta = _make_ap_with_uplink_sta()
    env.run(until=50000)

    delivered = [p for p in sta.packet_log if p.status == "DELIVERED"]
    assert len(delivered) > 0
    for p in delivered:
        assert p.source == "STA 1-1"
        assert p.destination == "AP 1"
        assert p.measured_sinr_db is not None
        assert p.delivered_at is not None


def test_uplink_retry_and_drop_under_forced_failure():
    """Force every uplink attempt to fail (impossible SINR threshold),
    with a small r_limit so a drop is reached quickly, and confirm
    sent_failed()'s retry-count/DROP bookkeeping mirrors WiFi's own
    downlink sent_failed() exactly."""
    cfg = Config(wifi_sinr_thr_db_override=1000.0, r_limit=2)
    env, channel, ap, sta = _make_ap_with_uplink_sta(config=cfg)
    env.run(until=20000)  # 20 ms - plenty of attempts at this CW

    assert sta.succeeded_transmissions == 0
    assert sta.failed_transmissions > 0

    dropped = [p for p in sta.packet_log if p.status == "DROPPED"]
    assert len(dropped) > 0
    for p in dropped:
        assert p.retry_count == cfg.r_limit + 1
        assert p.source == "STA 1-1"
# Rashed-Step 15.B-09-18-2026-end


# Rashed-Step pre_17.B-10-04-2026-start
# ---------------------------------------------------------------------
# pre_17.B: singleRun.py --wifi-sta-uplink-enabled. CLI runs use click's
# CliRunner inside isolated_filesystem() so packet.log / CSVs land in a
# temp dir, not the repo.
# ---------------------------------------------------------------------

import csv

from click.testing import CliRunner

from singleRun import single_run

_BASE = ["--ap-number", "1", "--gnb-number", "1", "--seed", "1", "-r", "1"]


def _invoke(args):
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(single_run, args)
        rows = []
        if os.path.exists("p.csv"):
            with open("p.csv", newline="") as f:
                rows = list(csv.DictReader(f))
    return result, rows


def _line_value(output, label):
    for line in output.splitlines():
        if line.startswith(label + ": "):
            return line.split(": ", 1)[1]
    raise AssertionError(f"{label!r} not in output")


def test_cli_default_has_no_wifi_uplink_and_no_sta_rows():
    result, rows = _invoke(_BASE + ["-t", "0.05", "--export-packets-csv", "p.csv"])
    assert result.exit_code == 0, result.output
    assert "Wi-Fi Uplink" not in result.output
    assert not any(r["node"].startswith("STA") for r in rows)


def test_cli_wifi_uplink_reports_and_exports_sta_packets():
    result, rows = _invoke(_BASE + ["-t", "0.2", "--wifi-sta-uplink-enabled", "--export-packets-csv", "p.csv"])
    assert result.exit_code == 0, (result.output, result.exception)
    assert "=== Wi-Fi Uplink ===" in result.output
    assert _line_value(result.output, "Wifi uplink STAs") == "1"
    delivered = int(_line_value(result.output, "Wifi uplink packets delivered"))
    assert delivered > 0
    assert float(_line_value(result.output, "Wifi uplink packet throughput (Mbps)")) > 0.0
    sta_rows = [r for r in rows if r["node"] == "STA 1-1"]
    assert sum(r["status"] == "DELIVERED" for r in sta_rows) == delivered
    assert all(r["technology"] == "WiFi" and r["source"] == "STA 1-1" and r["destination"] == "AP 1"
               for r in sta_rows)
    # The AP's downlink keeps running alongside.
    assert any(r["node"] == "AP 1" and r["status"] == "DELIVERED" for r in rows)


def test_cli_wifi_uplink_rejected_with_rogue_ap():
    result, _ = _invoke(["--ap-number", "1", "--gnb-number", "0", "-t", "0.01", "-r", "1",
                         "--rogue", "True", "--wifi-sta-uplink-enabled"])
    assert result.exit_code != 0
    assert "not supported with --rogue True" in result.output
# Rashed-Step pre_17.B-10-04-2026-end
