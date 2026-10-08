# Rashed-Step pre_20.C-10-08-2026-start
"""
Step pre_20.C tests: the LAA fairness diagnosis sweeps
(analysis/laa_fairness_sweeps.py) and the saturated network A option of
analysis/laa_fairness.run_case.
"""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from analysis import laa_fairness_sweeps as sw
from analysis.laa_fairness import run_case


def test_crossover_distances_match_the_ed_thresholds():
    # NR-U 23 dBm vs Wi-Fi's -62 dBm ED; Wi-Fi 20 dBm vs NR-U's -72 dBm
    # ED and Wi-Fi's -82 dBm preamble detection (exponent 3, 5.18 GHz).
    from common.common_phy import rx_power_dbm
    for tx, th, lo, hi in ((23.0, -62.0, 18.5, 19.5), (20.0, -72.0, 32.0, 33.0), (20.0, -82.0, 69.0, 70.0)):
        d = sw.crossover_m(tx, th)
        assert lo < d < hi
        assert abs(rx_power_dbm(tx, d, 5.18e9, n=3.0) - th) < 1e-6   # same model as the channel


def test_saturated_network_a_fills_the_channel_alone_with_wifi_far_away():
    r = run_case("wifi", None, 10.0, 150.0, seed=1, sim_time_s=0.3)
    assert r["a"]["throughput_mbps"] > 25.0          # ~30 Mbps, one frame per access


def test_sweep_returns_mean_and_ci_per_neighbor(monkeypatch):
    monkeypatch.setattr(sw, "SEEDS", [1, 2])
    monkeypatch.setattr(sw, "SIM_TIME_S", 0.2)
    out, rows = sw.sweep([10], lambda d: dict(load_a_pps=500.0, load_b_pps=500.0, distance_m=float(d)))
    assert set(out) == {"wifi", "nru"} and len(rows) == 2
    for b in out:
        for key in ("lat", "fail", "thr"):
            (mean, ci), = out[b][key]
            assert mean >= 0.0 and ci >= 0.0
    assert {r["neighbor"] for r in rows} == {"wifi", "nru"}
# Rashed-Step pre_20.C-10-08-2026-end
