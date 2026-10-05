# Rashed-Step 16.F-10-02-2026-start
"""
Step 16.F tests: the 5G Core wired into both orchestrators and CLIs
(simulation_nr.py/singleRunNR.py --core-enabled, simulation.py/
singleRun.py --nru-core-enabled), plus core/procedures.py's
first-packet/combined stats and core/network.py's core_config_from_cli.

CLI runs go through click's CliRunner inside isolated_filesystem() so
singleRun.py's packet.log report lands in a temp dir, not the repo.
"""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from click.testing import CliRunner

from core.network import CoreConfig, core_config_from_cli
from core.procedures import compute_first_packet_stats
from common.packet import Packet
from singleRunNR import single_run_nr
from singleRun import single_run


def _expect_value_error(fn, needle):
    try:
        fn()
    except ValueError as e:
        assert needle in str(e)
    else:
        assert False, "expected ValueError"


# ---------------------------------------------------------------------
# core_config_from_cli
# ---------------------------------------------------------------------

def test_core_config_from_cli_off_returns_none():
    assert core_config_from_cli(False) is None


def test_core_config_from_cli_defaults_and_overrides():
    assert core_config_from_cli(True) == CoreConfig()
    cfg = core_config_from_cli(True, 1000.0, 2000.0)
    assert (cfg.registration_delay_us, cfg.pdu_session_delay_us) == (1000.0, 2000.0)
    assert core_config_from_cli(True, None, 5.0).registration_delay_us == 90_000.0


def test_core_config_from_cli_rejects_delays_without_core_and_negatives():
    _expect_value_error(lambda: core_config_from_cli(False, 1.0), "only apply with the 5G Core enabled")
    _expect_value_error(lambda: core_config_from_cli(False, None, 1.0), "only apply with the 5G Core enabled")
    _expect_value_error(lambda: core_config_from_cli(True, -1.0), "must be >= 0")


# ---------------------------------------------------------------------
# compute_first_packet_stats
# ---------------------------------------------------------------------

class _Ue:
    def __init__(self, name, started_at, rrc_started_at=None):
        self.name = name
        self.reg_state = object()  # "handed to the Core"
        self.core_started_at = started_at
        if rrc_started_at is not None:
            self.rrc_attach_started_at = rrc_started_at


def _pkt(src, dst, status="DELIVERED", delivered_at=None):
    p = Packet(packet_id="p", source=src, destination=dst, payload_bytes=1, header_bytes=0)
    p.status = status
    p.delivered_at = delivered_at
    return p


def test_first_packet_stats_earliest_delivered_either_direction():
    ue_a = _Ue("A", started_at=100.0)
    ue_b = _Ue("B", started_at=100.0, rrc_started_at=0.0)
    ue_c = _Ue("C", started_at=0.0)  # never gets a packet
    packets = [
        _pkt("G", "A", delivered_at=900.0),
        _pkt("A", "G", delivered_at=700.0),          # uplink, earlier -> wins
        _pkt("G", "A", status="DROPPED", delivered_at=None),
        _pkt("G", "B", delivered_at=5000.0),
        _pkt("G", "B", status="PENDING", delivered_at=None),
    ]
    stats = compute_first_packet_stats([ue_a, ue_b, ue_c], packets)
    assert stats["attempted"] == 3
    assert stats["with_packet"] == 2
    assert stats["latencies_us"] == [600.0, 5000.0]  # A from core start, B from RRC start
    assert stats["mean_latency_us"] == 2800.0
    assert compute_first_packet_stats([], [])["mean_latency_us"] is None


# ---------------------------------------------------------------------
# Licensed NR CLI
# ---------------------------------------------------------------------

def _run(cmd, args):
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cmd, args)
    assert result.exit_code == 0, (result.output, result.exception)
    return result.output


def _block(output, title):
    lines = output.splitlines()
    i = lines.index(f"=== {title} ===")
    out = {}
    for line in lines[i + 1:]:
        if line.startswith("==="):
            break
        if ": " in line:
            k, v = line.split(": ", 1)
            out[k] = v
    return out


NR_BASE = ["--gnb-number", "1", "--ues-per-gnb", "2", "--seed", "1"]


def test_nr_cli_without_core_prints_no_core_block():
    out = _run(single_run_nr, NR_BASE + ["-t", "0.01"])
    assert "5G Core" not in out


def test_nr_cli_core_with_rrc_full_numbers():
    out = _run(single_run_nr, NR_BASE + ["-t", "0.3", "--tdd-enabled", "--ue-uplink-enabled",
                                         "--rrc-enabled", "--core-enabled"])
    b = _block(out, "Licensed 5G NR 5G Core")
    assert b["NR Core UEs"] == "2"
    assert b["NR registered"] == "2"
    assert b["NR mean registration latency (us)"] == "90000.0"
    assert b["NR PDU sessions active"] == "2"
    assert b["NR mean PDU session latency (us)"] == "125000.0"
    assert b["NR mean attach latency, start -> session active (us)"] == "219000.0"
    assert b["NR UEs with a delivered packet"] == "2"
    # First data slot right after activation: +1 slot (500us at mu=1).
    assert b["NR mean attach-to-first-packet latency (us)"] == "219500.0"


def test_nr_cli_core_without_rrc_and_custom_delays():
    out = _run(single_run_nr, NR_BASE + ["-t", "0.05", "--core-enabled",
                                         "--core-registration-delay-us", "10000",
                                         "--core-pdu-session-delay-us", "20000"])
    b = _block(out, "Licensed 5G NR 5G Core")
    assert b["NR mean attach latency, start -> session active (us)"] == "30000.0"
    assert b["NR mean attach-to-first-packet latency (us)"] == "30500.0"


def test_nr_cli_core_gates_throughput_before_session():
    """A run shorter than the attach time carries no data at all."""
    out = _run(single_run_nr, NR_BASE + ["-t", "0.1", "--core-enabled"])
    assert "TOTAL: slots_ok=0 " in out
    b = _block(out, "Licensed 5G NR 5G Core")
    assert b["NR PDU sessions active"] == "0"
    assert b["NR mean attach-to-first-packet latency (us)"] == "None"


def test_nr_cli_delay_flag_without_core_fails_fast():
    runner = CliRunner()
    result = runner.invoke(single_run_nr, NR_BASE + ["-t", "0.01", "--core-pdu-session-delay-us", "5"])
    assert result.exit_code != 0
    assert "only apply with the 5G Core enabled" in result.output


# ---------------------------------------------------------------------
# NR-U CLI (singleRun.py)
# ---------------------------------------------------------------------

NRU_BASE = ["--ap-number", "1", "--gnb-number", "1", "--seed", "1", "-r", "1"]


def test_nru_cli_without_core_prints_no_core_block():
    out = _run(single_run, NRU_BASE + ["-t", "0.01"])
    assert "5G Core" not in out


def test_nru_cli_core_without_rrc_numbers():
    out = _run(single_run, NRU_BASE + ["-t", "0.3", "--nru-core-enabled"])
    b = _block(out, "NR-U 5G Core")
    assert b["NRU Core UEs"] == "1"
    assert b["NRU registered"] == "1"
    assert b["NRU PDU sessions active"] == "1"
    assert b["NRU mean attach latency, start -> session active (us)"] == "215000.0"
    # Rashed-Step pre_17.A-10-04-2026-start
    # Was "uplink only -> 0 / None" (16.F). Since the NR-U destination
    # fix, downlink counts too: the first downlink to the UE lands after
    # its session activates (215ms), never before.
    assert b["NRU UEs with a delivered packet"] == "1"
    first = float(b["NRU mean attach-to-first-packet latency (us)"])
    assert 215_000.0 < first < 300_000.0
    # Rashed-Step pre_17.A-10-04-2026-end


def test_nru_cli_core_with_rrc_attach_includes_rrc_time():
    out = _run(single_run, ["--ap-number", "0", "--gnb-number", "1", "--seed", "1", "-r", "1",
                            "-t", "0.3", "--nru-ue-uplink-enabled", "--nru-rrc-enabled",
                            "--nru-core-enabled"])
    rrc = float(_block(out, "NR-U RRC Connection Setup")["NRU RRC mean connection setup latency (us)"])
    b = _block(out, "NR-U 5G Core")
    assert float(b["NRU mean attach latency, start -> session active (us)"]) == rrc + 215_000.0


def test_nru_cli_delay_flag_without_core_fails_fast():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(single_run, NRU_BASE + ["-t", "0.01", "--core-registration-delay-us", "5"])
    assert result.exit_code != 0
    assert "only apply with the 5G Core enabled" in result.output
# Rashed-Step 16.F-10-02-2026-end


# Rashed-Step 16.G-10-04-2026-start
# ---------------------------------------------------------------------
# 16.G: analysis/core_attach_latency.py stages + the stacked-bar helper.
# Never calls generate() (it would overwrite the committed figure with a
# few-seed version); the helper is pointed at pytest's tmp_path instead.
# ---------------------------------------------------------------------

from analysis import core_attach_latency as cal
from analysis import plot_utils


def test_attach_stages_licensed_nr_exact():
    assert cal._stages_us("licensed", seed=1) == (4000.0, 90_000.0, 125_000.0)


def test_attach_stages_nru_rrc_slower_than_licensed_core_stages_identical():
    for scenario in ("nru_cot", "nru_autonomous"):  # Rashed-Step 17.G-10-05-2026: revised scenarios
        rrc, reg, pdu = cal._stages_us(scenario, seed=1)
        assert rrc > 4000.0
        assert (reg, pdu) == (90_000.0, 125_000.0)
    assert cal._stages_us("nru_autonomous", 1)[0] > cal._stages_us("nru_cot", 1)[0]


def test_attach_stages_follow_custom_core_config():
    cfg = CoreConfig(registration_delay_us=1000.0, pdu_session_delay_us=2000.0)
    assert cal._stages_us("licensed", seed=1, core_config=cfg) == (4000.0, 1000.0, 2000.0)


def test_stacked_bar_helper_writes_pdf_and_jpg(tmp_path, monkeypatch):
    monkeypatch.setattr(plot_utils, "GENERATED_DIR", str(tmp_path))
    paths = plot_utils.save_stacked_bar_figure(
        categories=["A", "B"],
        stacks={"RRC setup": [1.0, 2.0], "Registration": [3.0, 4.0], "PDU session": [5.0, 6.0]},
        xlabel="x", ylabel="y", output_stem="stack_test",
    )
    for p in paths.values():
        assert os.path.dirname(p) == str(tmp_path)
        assert os.path.getsize(p) > 0
# Rashed-Step 16.G-10-04-2026-end
