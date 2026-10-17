# Rashed-Step pre_23.B-10-17-2026-start
"""
Step pre_23.B tests: an NR-U burst-model COT carries what its MCS and data
time hold (head packet + queued / new packets that fit), not one 1500 B
placeholder; channel access is unchanged.
"""
import os
import re
import sys
from collections import Counter
from types import SimpleNamespace

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest
from click.testing import CliRunner

from nr.nr import NR_MCS_TABLE, NUMEROLOGY_SCS_KHZ, resource_block_count
from nru.nru import Config_NR, Gnb, NRU_MCS_SINR_THRESHOLDS_DB


def _cap(mcs, data_us, cfg=None):
    cfg = cfg or Config_NR()
    stub = SimpleNamespace(config_nr=cfg, current_mcs_for_link=lambda key: mcs, rate_adapt_link_key=lambda: None)
    return Gnb._burst_capacity_bytes(stub, data_us)


def test_capacity_mapping():
    effs = [1.18, 1.48, 1.91, 2.73, 3.32, 4.52, 5.12, 5.89]
    cfg = Config_NR()
    scs = NUMEROLOGY_SCS_KHZ[cfg.numerology]
    hz = resource_block_count(cfg.bandwidth_mhz, scs) * 12 * scs * 1000.0
    for mcs, eff in enumerate(effs):
        assert NRU_MCS_SINR_THRESHOLDS_DB[mcs] >= max(r for r, e in NR_MCS_TABLE.values() if e == eff)
        assert _cap(mcs, 6000.0) == int(eff * hz * 6000e-6 // 8)
    assert _cap(3, 0.0) == 0


def _run(extra):
    from singleRun import single_run
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("log", exist_ok=True)
        csv_path = os.path.abspath("p.csv")
        r = runner.invoke(single_run, ["--ap-number", "1", "--gnb-number", "1", "--seed", "1", "-t", "0.5", "-r", "1",
                                       "--ap-pos", "0,0", "--gnb-pos", "10,0", "--export-packets-csv", csv_path] + extra)
        rows = open(csv_path).read().splitlines() if os.path.exists(csv_path) else []
    assert r.exit_code == 0, r.output[-400:]
    return r.output, rows


def test_saturated_cot_carries_its_capacity():
    out, _ = _run([])
    cots = int(re.search(r"N_gnbs=1 .*SUCCEEDED_TRANSMISSION (\d+)", out).group(1))
    thr = float(re.search(r"NRU packet throughput \(Mbps\): ([\d.]+)", out).group(1))
    per_cot_bytes = thr * 1e6 / 8 * 0.5 / cots
    cap = _cap(Config_NR().mcs, Config_NR().mcot * 1000)
    assert cap - 1500 < per_cot_bytes <= cap                 # filled up to the last whole packet
    assert thr > 10.0                                        # was 1500 B per COT (~1.5 Mbps)


def test_queued_packets_conserved_and_delivered():
    # 2000 pkt/s x 1500 B = 24 Mbps offered, well inside a COT's capacity:
    # (nearly) everything arrives, each packet once. (Channel access being
    # unchanged is checked by the regression runs: only NR-U throughput /
    # latency lines change, not occupancy or transmission counts.)
    out, rows = _run(["--nru-traffic-model", "poisson", "--nru-arrival-rate-pps", "2000"])
    hdr = rows[0].split(",")
    i_tech, i_id, i_status = hdr.index("technology"), hdr.index("packet_id"), hdr.index("status")
    nru = [r.split(",") for r in rows[1:] if r.split(",")[i_tech].upper().startswith("NR")]
    ids = Counter(r[i_id] for r in nru)
    assert nru and max(ids.values()) == 1                    # no packet delivered / logged twice
    delivered = sum(1 for r in nru if r[i_status] == "DELIVERED")
    assert delivered > 0.9 * 2000 * 0.5                      # was one packet per COT (~65 in 0.5 s)
    thr = float(re.search(r"NRU packet throughput \(Mbps\): ([\d.]+)", out).group(1))
    assert thr == pytest.approx(delivered * 1500 * 8 / 0.5e6, rel=1e-6)
# Rashed-Step pre_23.B-10-17-2026-end
