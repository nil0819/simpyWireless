# Rashed-Step 24.E-10-19-2026-start
"""
Benign-scenario validation of the CAD-paper DTMC (model/dtmc.py, pa = 0)
against the simulator under its defaults (Step 24.E).

Scenario (model/compare.compare_dtmc): w = 1..6 co-located Wi-Fi APs + one
NR-U gNB, saturated, fixed contention window 31 on both, 5.4 ms Wi-Fi
frames, MCOT 6 ms, ng = 55. The model's Wi-Fi occupancy is counted the
simulator's way (Step pre_22.G).

Studies (python -m analysis.dtmc_validation [seeds] [long]):
  seeds   100 independent seeds x 100 s per w (parallel): mean +- 95 % CI.
  long    one 10 000 s run per w (--compact-packet-log, 3 at a time - each
          ~1 GB): the literal long-run check.
"""
import contextlib
import csv
import io
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.laa_fairness import OUT_DIR
from analysis.parallel import mean_ci, run_parallel

W_VALUES = [1, 2, 3, 4, 5, 6]
SEEDS = list(range(1, 101))
SEED_TIME_S = 100.0
LONG_TIME_S = 10_000.0


def one(w: int, seed: int, sim_time_s: float, compact: bool = False) -> dict:
    from model.compare import compare_dtmc
    logging.disable(logging.CRITICAL)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            r = compare_dtmc(w=w, Wo=32, ng=55, Twp_us=5400.0, Tmcot_us=6000.0, sim_time_s=sim_time_s, seed=seed,
                             ap_cluster_radius=2.0, wifi_packet_size_bytes=36286,
                             extra_argv=["--compact-packet-log"] if compact else None)
    finally:
        logging.disable(logging.NOTSET)
    return r


def _report(rows_by_w, label, out_name):
    rows = []
    print(f"{label}")
    print(" w | model Cw | sim Cw              | dev   | model Cn | sim Cn              | dev   | Wi-Fi pcoll sim/model")
    for w, rs in rows_by_w.items():
        m = rs[0]
        cw, cn = mean_ci([r["measured_Cw"] for r in rs]), mean_ci([r["measured_Cn"] for r in rs])
        tw, tn = m["model_tau_w"], m["model_tau_n"]
        pc_model = 1 - (1 - tw) ** (w - 1) * (1 - tn)
        pc_sim = (sum(r["measured_wifi_fail"] for r in rs)
                  / max(1, sum(r["measured_wifi_fail"] + r["measured_wifi_succ"] for r in rs)))
        dw, dn = cw[0] - m["model_Cw"], cn[0] - m["model_Cn"]
        rows.append({"w": w, "runs": len(rs), "model_Cw": m["model_Cw"], "sim_Cw": cw[0], "sim_Cw_ci": cw[1],
                     "dev_Cw_points": 100 * dw, "model_Cn": m["model_Cn"], "sim_Cn": cn[0], "sim_Cn_ci": cn[1],
                     "dev_Cn_points": 100 * dn, "pcoll_sim": pc_sim, "pcoll_model": pc_model})
        print(f" {w} | {m['model_Cw']:.3f}    | {cw[0]:.4f} +- {cw[1]:.4f} | {100*dw:+5.2f} | {m['model_Cn']:.3f}    | "
              f"{cn[0]:.4f} +- {cn[1]:.4f} | {100*dn:+5.2f} | {pc_sim:.3f} / {pc_model:.3f}", flush=True)
    mw = sum(abs(r["dev_Cw_points"]) for r in rows) / len(rows)
    mn = sum(abs(r["dev_Cn_points"]) for r in rows) / len(rows)
    print(f" mean |dev|: Wi-Fi {mw:.2f} points, NR-U {mn:.2f} points", flush=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, out_name), "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)


def study_seeds(processes=None):
    t = time.time()
    jobs = [dict(w=w, seed=s, sim_time_s=SEED_TIME_S) for w in W_VALUES for s in SEEDS]
    res = run_parallel(one, jobs, processes)
    by_w = {w: [r for j, r in zip(jobs, res) if j["w"] == w] for w in W_VALUES}
    _report(by_w, f"{len(SEEDS)} seeds x {SEED_TIME_S:.0f} s per w ({time.time() - t:.0f} s wall)",
            "dtmc_validation_seeds.csv")


def study_long(processes=3):
    t = time.time()
    jobs = [dict(w=w, seed=1, sim_time_s=LONG_TIME_S, compact=True) for w in W_VALUES]
    res = run_parallel(one, jobs, processes)
    _report({j["w"]: [r] for j, r in zip(jobs, res)},
            f"1 run x {LONG_TIME_S:.0f} s per w ({time.time() - t:.0f} s wall; no CI from one run)",
            "dtmc_validation_long.csv")


STUDIES = {"seeds": study_seeds, "long": study_long}

if __name__ == "__main__":
    for name in sys.argv[1:] or list(STUDIES):
        print(f"=== {name} ===", flush=True)
        STUDIES[name]()
# Rashed-Step 24.E-10-19-2026-end
