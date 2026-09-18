# Rashed-Step pre_11.C-08-13-2026-start
"""
Sweep helper built on top of compare.py's compare_dtmc() - runs a range of
w (coexisting Wi-Fi AP count, gNB count fixed at 1) and reports model-vs-
simulator deviation for each, in one table.

Grew out of an ad hoc scratch script written during this project's Step
pre_11.C model-validation work (Rashed asked for "iterative comparison...
no of coexisting wifi = {1,2,3,4,5,6}, keep gNB no to be 1"). That first
sweep (no ap_cluster_radius) exposed a real bug/limitation: at w=5 and 6,
random AP placement across the full area_w x area_h box let some AP pairs
fall outside each other's sensing range (spatial reuse/hidden-terminal
effect), producing measured occupancy sums >1.0 - not comparable to the
DTMC's single-collision-domain assumption at all. compare_dtmc()'s
ap_cluster_radius parameter (added the same session) fixes this by
clustering all w APs within mutual sensing range - see compare.py's
_cluster_ap_positions()/compare_dtmc() docstrings and Project details/
Step pre_11.txt for the full story.

Standalone toolkit - not imported by the simulator's own runtime, not
wired into singleRun.py's CLI (same convention as bianchi.py/dtmc.py/
compare.py).
"""
from typing import Dict, List, Optional

from model.compare import compare_dtmc


def sweep_dtmc_by_w(w_values: List[int], Wo: int, ng: int, Twp_us: float, Tmcot_us: float,
                     sim_time_s: float, seed: int = 1, ap_cluster_radius: Optional[float] = 2.0,
                     wifi_packet_size_bytes: Optional[int] = None, **kwargs) -> List[Dict]:
    """
    Runs compare_dtmc() once per value in w_values (gnb-number is always 1,
    fixed by compare_dtmc() itself), returning the list of result dicts in
    the same order. Defaults ap_cluster_radius=2.0 (unlike compare_dtmc()'s
    own default of None) since a sweep across w is exactly the case where
    random placement is most likely to break the single-collision-domain
    comparison at higher w - pass ap_cluster_radius=None explicitly to
    restore the old random-placement behavior for comparison.
    """
    results = []
    for w in w_values:
        r = compare_dtmc(w=w, Wo=Wo, ng=ng, Twp_us=Twp_us, Tmcot_us=Tmcot_us,
                          sim_time_s=sim_time_s, seed=seed, ap_cluster_radius=ap_cluster_radius,
                          wifi_packet_size_bytes=wifi_packet_size_bytes, **kwargs)
        results.append(r)
    return results


# Rashed-Step 14.L-08-31-2026-start
def sweep_dtmc_by_w_multiseed(w_values: List[int], seeds: List[int], Wo: int, ng: int,
                               Twp_us: float, Tmcot_us: float, sim_time_s: float,
                               ap_cluster_radius: Optional[float] = 2.0,
                               wifi_packet_size_bytes: Optional[int] = None,
                               **kwargs) -> List[Dict]:
    """
    Rashed asked whether the DTMC-validation figure (occupancy_model_vs_
    sim.py) could show confidence intervals - it couldn't, because
    sweep_dtmc_by_w() above only ever runs ONE simulator seed per w value,
    so there was no variability to report. This is the multi-seed sibling:
    runs compare_dtmc() once per (w, seed) pair - keeping the model's
    analytical prediction (deterministic, identical across seeds for a
    given w) and aggregating the simulator's measured occupancy across
    seeds into a mean + 95% CI half-width per w, per technology.

    Returns one dict per w with keys: w, model_Cw, model_Cn (unchanged,
    single analytical value), mean_measured_Cw, ci95_measured_Cw,
    mean_measured_Cn, ci95_measured_Cn, n_seeds, plus the raw
    measured_Cw_samples/measured_Cn_samples lists (in case a caller wants
    the raw per-seed values instead of just mean+CI).
    """
    import numpy as np
    from scipy import stats

    results = []
    for w in w_values:
        cw_samples: List[float] = []
        cn_samples: List[float] = []
        model_Cw = model_Cn = None
        for seed in seeds:
            r = compare_dtmc(w=w, Wo=Wo, ng=ng, Twp_us=Twp_us, Tmcot_us=Tmcot_us,
                              sim_time_s=sim_time_s, seed=seed, ap_cluster_radius=ap_cluster_radius,
                              wifi_packet_size_bytes=wifi_packet_size_bytes, **kwargs)
            cw_samples.append(r["measured_Cw"])
            cn_samples.append(r["measured_Cn"])
            model_Cw, model_Cn = r["model_Cw"], r["model_Cn"]  # deterministic - same every seed

        n = len(seeds)
        cw_arr, cn_arr = np.array(cw_samples), np.array(cn_samples)
        # 95% CI half-width via Student's t (not a fixed 1.96 z-value) -
        # more honest for the small seed counts (n~10) this sweep uses.
        t_crit = stats.t.ppf(0.975, df=n - 1) if n > 1 else 0.0
        cw_sem = cw_arr.std(ddof=1) / np.sqrt(n) if n > 1 else 0.0
        cn_sem = cn_arr.std(ddof=1) / np.sqrt(n) if n > 1 else 0.0

        results.append({
            "w": w,
            "model_Cw": model_Cw, "model_Cn": model_Cn,
            "mean_measured_Cw": float(cw_arr.mean()), "ci95_measured_Cw": float(t_crit * cw_sem),
            "mean_measured_Cn": float(cn_arr.mean()), "ci95_measured_Cn": float(t_crit * cn_sem),
            "n_seeds": n,
            "measured_Cw_samples": cw_samples, "measured_Cn_samples": cn_samples,
        })
    return results
# Rashed-Step 14.L-08-31-2026-end


def print_sweep_report(results: List[Dict]) -> None:
    """Pretty-prints the list returned by sweep_dtmc_by_w() as one table."""
    print(f"{'w':>2} | {'model Cn':>9} {'meas Cn':>9} {'dev Cn':>8} | "
          f"{'model Cw':>9} {'meas Cw':>9} {'dev Cw':>8}")
    print("-" * 70)
    for r in results:
        devn = r["deviation_Cn"] * 100 if r["deviation_Cn"] is not None else float("nan")
        devw = r["deviation_Cw"] * 100 if r["deviation_Cw"] is not None else float("nan")
        mcn = r["measured_Cn"] if r["measured_Cn"] is not None else float("nan")
        mcw = r["measured_Cw"] if r["measured_Cw"] is not None else float("nan")
        print(f"{r['w']:>2} | {r['model_Cn']:>9.4f} {mcn:>9.4f} {devn:>7.1f}% | "
              f"{r['model_Cw']:>9.4f} {mcw:>9.4f} {devw:>7.1f}%")


if __name__ == "__main__":
    # This session's reference sweep: w=1..6 coexisting Wi-Fi APs, gNB=1,
    # Wo=32/ng=55 (fixed CW, matches the DTMC's own assumption), Twp=5400us
    # (36286-byte Wi-Fi frame - see compare.py's own __main__ for how that
    # byte count was derived), Tmcot=6000us, 30s runs, clustered placement.
    results = sweep_dtmc_by_w(
        w_values=list(range(1, 7)), Wo=32, ng=55, Twp_us=5400.0, Tmcot_us=6000.0,
        sim_time_s=30.0, seed=1, ap_cluster_radius=2.0, wifi_packet_size_bytes=36286,
    )
    print_sweep_report(results)
# Rashed-Step pre_11.C-08-13-2026-end
