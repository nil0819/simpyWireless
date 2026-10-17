# Rashed-Step 23.D-10-17-2026-start
"""
Step 23.D tests: confidence intervals and parallel seed sweeps
(analysis/parallel.py).
"""
import math
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest

from analysis.laa_fairness import run_case
from analysis.parallel import mean_ci, run_parallel, sweep_seeds


def test_mean_ci():
    m, h = mean_ci([1.0, 2.0, 3.0, 4.0, 5.0])
    assert m == 3.0
    assert h == pytest.approx(2.776445 * math.sqrt(2.5) / math.sqrt(5), rel=1e-5)   # t(0.975, 4)
    assert mean_ci([7.0]) == (7.0, 0.0)
    assert mean_ci([2.0, None, float("nan"), 4.0])[0] == 3.0
    assert math.isnan(mean_ci([])[0])


def _thr(r):
    return r["a"]["throughput_mbps"]


def test_parallel_equals_serial():
    kw = dict(network_b="nru", load_a_pps=500.0, load_b_pps=500.0, distance_m=20.0, sim_time_s=0.1)
    jobs = [dict(kw, seed=s) for s in (1, 2, 3)]
    serial = [_thr(r) for r in run_parallel(run_case, jobs, processes=1)]
    par = [_thr(r) for r in run_parallel(run_case, jobs, processes=3)]
    assert serial == par                                          # every run fixed by its seed
    s = sweep_seeds(run_case, [1, 2, 3], {"thr": _thr}, processes=2, **kw)
    assert s["thr"] == mean_ci(serial)
# Rashed-Step 23.D-10-17-2026-end
