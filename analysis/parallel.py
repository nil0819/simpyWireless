# Rashed-Step 23.D-10-17-2026-start
"""
Seed sweeps with confidence intervals, run in parallel (Step 23.D).

  mean_ci(values)            mean and 95 % confidence half-width (Student
                             t, so small seed counts aren't overconfident)
  run_parallel(fn, jobs)     fn(**job) for every job dict on a process
                             pool, results in job order (fn and the job
                             values must be picklable - module-level
                             functions, dataclass configs). processes=1
                             runs them in this process.
  sweep_seeds(fn, seeds, metrics, **kw)
                             fn(seed=s, **kw) for every seed, in parallel,
                             then {metric: (mean, ci)} with
                             metric(result) -> number.

Each seed is an independent replication: its own placement / user drop
(layouts are seeded from the run seed), shadowing and fading draws, and
traffic. Results are the same whatever the process count - every run is
fully determined by its seed.
"""
import math
import os
import statistics
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from scipy import stats as _st


def mean_ci(values: Sequence[float], confidence: float = 0.95) -> Tuple[float, float]:
    vals = [float(v) for v in values if v is not None and not math.isnan(v)]
    if not vals:
        return float("nan"), float("nan")
    m = statistics.mean(vals)
    if len(vals) < 2:
        return m, 0.0
    half = _st.t.ppf(0.5 + confidence / 2.0, len(vals) - 1) * statistics.stdev(vals) / math.sqrt(len(vals))
    return m, float(half)


def _call(args):
    fn, kw = args
    return fn(**kw)


def default_processes() -> int:
    """Half the logical CPUs, at most 8. On Windows every worker is a new
    interpreter that re-imports the simulator (~7 s), and per-run time
    rises once all cores are busy: measured on 16 logical CPUs, 48 one-
    second runs took 36.9 s with 8 processes (serial ~168 s), 60.7 s with
    6, 84.7 s with 4 - but 16 runs on 15 processes (one run per worker)
    took 102 s, slower than serial. Worth it when each worker gets several
    runs."""
    return max(1, min(8, (os.cpu_count() or 2) // 2))


def run_parallel(fn: Callable[..., Any], jobs: Iterable[Dict[str, Any]], processes: Optional[int] = None) -> List[Any]:
    jobs = list(jobs)
    processes = default_processes() if processes is None else processes
    if processes <= 1 or len(jobs) <= 1:
        return [fn(**kw) for kw in jobs]
    with ProcessPoolExecutor(max_workers=min(processes, len(jobs))) as pool:
        return list(pool.map(_call, [(fn, kw) for kw in jobs]))


def sweep_seeds(fn: Callable[..., Any], seeds: Sequence[int], metrics: Dict[str, Callable[[Any], float]],
                processes: Optional[int] = None, **kw) -> Dict[str, Tuple[float, float]]:
    results = run_parallel(fn, [dict(kw, seed=s) for s in seeds], processes)
    return {name: mean_ci([get(r) for r in results]) for name, get in metrics.items()}
# Rashed-Step 23.D-10-17-2026-end
