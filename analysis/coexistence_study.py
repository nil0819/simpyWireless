# Rashed-Step 23.F-10-17-2026-start
"""
Coexistence with the Step 23 fidelity fixes (Step 23.F).

Runs in parallel (analysis/parallel.py); every figure is a mean over
independent seeds with a 95 % confidence interval.

Studies (python -m analysis.coexistence_study [tr38889] [distance] [dtmc]):

  tr38889   The 3GPP replacement test as TR 38.889 / TR 36.889 define it:
            the indoor layout (120 x 80 m, two operators x 3 cells, 5 users
            per cell re-dropped below -82 dBm serving power), FTP Model 3
            (0.5 MB files) on every cell, InH-Office + shadowing + fading,
            the 6 us collision window (23.A), Wi-Fi preamble detection, rate
            adaptation, 23 dBm cells, NR-U slots model. Operator B (Wi-Fi)
            next to operator A = Wi-Fi / NR-U / NR-U with ED -82 dBm + 20 dBm
            CTS-to-self. Metric: operator B's user-perceived throughput
            (UPT) and file transfer time, pooled over its cells' files.
  distance  The two-network test against distance (analysis/laa_fairness:
            A 1500 / B 2500 pkt/s, frame exchange) on InH + shadowing +
            fading + collision window, with enough seeds for a CI on the
            latency ratio.
  dtmc      The CCNC DTMC comparison (fixed CW, 5.4 ms frames, w = 1..6)
            under the defaults - must equal the pre_22.C numbers (Step 23's
            options are all off by default; pre_23.B doesn't touch saturated
            channel access).
"""
import contextlib
import csv
import io
import logging
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import simulation
from analysis.laa_fairness import run_case, OUT_DIR
from analysis.parallel import mean_ci, run_parallel
from analysis.plot_utils import save_line_figure, SERIES_STYLE, BASELINE_COLOR, WIFI_COLOR, NRU_COLOR
from channel.propagation import PathLossSpec
from common.layouts import build_layout, serving_rule
from common.packet import TrafficConfig
from nru.nru import Config_NR
from wifi.wifi import Config

CCA_US = 6.0
CHANNEL = dict(pathloss=PathLossSpec("inh-office-mixed", shadowing=True), fading=(None, None), cca_detect_us=CCA_US)

TR_SEEDS = list(range(1, 21))
TR_SIM_TIME_S = 10.0
TR_LOADS_FPS = [0.25, 0.5, 1.0]      # files/s per cell (0.5 MB): 1 / 2 / 4 Mbps offered per cell (low, medium, high)
TR_CASES = [
    ("Next to Wi-Fi", "wifi", {}),
    ("Next to NR-U", "nru", {}),
    ("Next to NR-U, ED -82 + CTS 20 dBm", "nru", dict(ed_threshold_dbm=-82.0, wifi_reservation="cts_to_self",
                                                      cts_power_dbm=20.0)),
]

D_SEEDS = list(range(1, 21))
D_SIM_TIME_S = 1.0
LOAD_A, LOAD_B = 1500.0, 2500.0
DISTANCES = [5, 10, 20, 30, 35, 40, 50, 60, 80]

DTMC_SEEDS = [1, 2, 3]
PRE22_ORIG = {  # pre_22.C, original stack (3 seeds x 10 s): Cw, Cn
    1: (0.718, 0.257), 2: (0.809, 0.156), 3: (0.831, 0.117), 4: (0.831, 0.098), 5: (0.816, 0.081), 6: (0.804, 0.075)}


def _write(rows, name):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, name), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


# ---- tr38889 -------------------------------------------------------------
def tr_ftp_run(op_a: str, seed: int, files_per_s: float, nru_kw: dict) -> dict:
    """One TR 38.889 run; operator B's per-file UPT / transfer times."""
    spec = CHANNEL["pathloss"]
    lay = build_layout("tr38889-indoor", seed,
                       serving_ok=serving_rule(-82.0, lambda site: 23.0, lambda site: 5.18e9, spec, seed))
    a_sites, b_sites = lay.operator_sites("A"), lay.operator_sites("B")
    aps = (a_sites if op_a == "wifi" else []) + b_sites
    gnbs = a_sites if op_a == "nru" else []
    wifi = Config(mac_exchange=True, preamble_detect_dbm=-82.0, rate_adapt_enabled=True, tx_power_dbm=23.0)
    nru = Config_NR(cot_model="slots", rate_adapt_enabled=True, **nru_kw)
    ftp = TrafficConfig(mode="ftp3", arrival_rate_pps=files_per_s, packet_size_bytes=1500, file_size_bytes=500_000)
    kw = dict(area_w=lay.area_w, area_h=lay.area_h,
              ap_positions=[s.pos for s in aps], gnb_positions=[s.pos for s in gnbs] or None,
              sta_positions=[list(s.users) for s in aps], ue_positions=[list(s.users) for s in gnbs] or None,
              wifi_traffic_config=ftp, nru_traffic_config=ftp, fairness_report=True, **CHANNEL)
    logging.disable(logging.CRITICAL)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            fair = simulation.run_simulation(len(aps), len(gnbs), seed, TR_SIM_TIME_S, wifi, nru,
                                             {k: {len(aps): 0} for k in range(1024)}, {}, {}, {}, {}, False, **kw)
    finally:
        logging.disable(logging.NOTSET)
    b_names = [f"AP {i + 1}" for i in range(len(aps) - len(b_sites), len(aps))]
    files = fair.get("files", {})
    upt = [v for n in b_names for v in files.get(n, {}).get("upt_mbps", [])]
    tms = [v for n in b_names for v in files.get(n, {}).get("transfer_ms", [])]
    seen = sum(files.get(n, {}).get("files_seen", 0) for n in b_names)
    return {"upt": upt, "transfer_ms": tms, "completed": len(upt), "seen": seen}


def study_tr38889(processes=None):
    rows = []
    for load in TR_LOADS_FPS:
        jobs, keys = [], []
        for label, op_a, nru_kw in TR_CASES:
            for s in TR_SEEDS:
                jobs.append(dict(op_a=op_a, seed=s, files_per_s=load, nru_kw=nru_kw))
                keys.append(label)
        res = run_parallel(tr_ftp_run, jobs, processes)
        ref = None
        for label, op_a, _ in TR_CASES:
            runs = [r for k, r in zip(keys, res) if k == label]
            # One value per seed (its mean UPT / transfer), so the CI is over
            # independent replications, not correlated files of one run.
            upt = mean_ci([statistics.mean(r["upt"]) for r in runs if r["upt"]])
            tms = mean_ci([statistics.mean(r["transfer_ms"]) for r in runs if r["transfer_ms"]])
            pooled = sorted(v for r in runs for v in r["upt"])
            p5 = pooled[int(0.05 * (len(pooled) - 1))] if pooled else float("nan")
            done = sum(r["completed"] for r in runs) / max(1, sum(r["seen"] for r in runs))
            if op_a == "wifi":
                ref = upt
            ok = "" if op_a == "wifi" else (upt[0] + upt[1] >= ref[0] - ref[1])   # not worse than next to Wi-Fi
            rows.append({"files_per_s_per_cell": load, "case": label, "b_upt_mbps": upt[0], "b_upt_ci": upt[1],
                         "b_upt_p5_mbps": p5, "b_transfer_ms": tms[0], "b_transfer_ci": tms[1],
                         "b_files_completed": done, "passes": ok})
            print(f"{load:4.2f} files/s  {label:36} B UPT {upt[0]:6.2f} +- {upt[1]:5.2f} Mbps (5th pct {p5:5.2f})  "
                  f"transfer {tms[0]:7.1f} +- {tms[1]:6.1f} ms  done {100 * done:5.1f}%  "
                  f"{'' if op_a == 'wifi' else ('pass' if ok else 'FAIL')}", flush=True)
    _write(rows, "coexistence_tr38889_ftp.csv")


# ---- distance --------------------------------------------------------------
def _ab_latency(network_b, distance_m, seed):
    r = run_case(network_b, LOAD_A, LOAD_B, float(distance_m), seed, D_SIM_TIME_S, wifi_config=Config(mac_exchange=True),
                 nru_config=Config_NR(cot_model="slots"), sim_kw=CHANNEL)
    return r["a"]["avg_latency_us"] / 1000.0


def study_distance(processes=None):
    jobs = [dict(network_b=nb, distance_m=d, seed=s) for d in DISTANCES for nb in ("wifi", "nru") for s in D_SEEDS]
    res = run_parallel(_ab_latency, jobs, processes)
    lat = {}
    for j, v in zip(jobs, res):
        lat.setdefault((j["distance_m"], j["network_b"]), []).append(v)
    rows, ratio, lo, hi = [], [], [], []
    for d in DISTANCES:
        ref, nru = mean_ci(lat[(d, "wifi")]), mean_ci(lat[(d, "nru")])
        r = nru[0] / ref[0]
        # CI of the ratio of two independent means (delta method).
        rel = ((nru[1] / nru[0]) ** 2 + (ref[1] / ref[0]) ** 2) ** 0.5 if nru[0] and ref[0] else 0.0
        ratio.append(r)
        ok = nru[0] <= 1.1 * ref[0] + ref[1]
        rows.append({"distance_m": d, "ref_latency_ms": ref[0], "ref_ci": ref[1], "nru_latency_ms": nru[0],
                     "nru_ci": nru[1], "ratio": r, "ratio_ci": r * rel, "passes": ok})
        print(f"{d:>3} m  next to Wi-Fi {ref[0]:7.2f} +- {ref[1]:6.2f} ms  next to NR-U {nru[0]:7.2f} +- {nru[1]:6.2f} ms  "
              f"ratio {r:5.2f} +- {r * rel:4.2f}  {'pass' if ok else 'FAIL'}", flush=True)
    _write(rows, "coexistence_distance.csv")
    label = "InH + shadowing + fading + collision window"
    SERIES_STYLE.setdefault(label, dict(color=NRU_COLOR, marker="h", linestyle="-"))
    save_line_figure(DISTANCES, {label: ratio}, "Distance between the networks (m)",
                     "Latency next to NR-U / next to Wi-Fi", "", "coexistence_latency_ratio_ci",
                     hlines=[(1.0, "Replacement-test parity")], yerr={label: [row["ratio_ci"] for row in rows]})


# ---- dtmc ------------------------------------------------------------------
def _dtmc(w, seed):
    from model.compare import compare_dtmc
    logging.disable(logging.CRITICAL)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            r = compare_dtmc(w=w, Wo=32, ng=55, Twp_us=5400.0, Tmcot_us=6000.0, sim_time_s=10.0, seed=seed,
                             ap_cluster_radius=2.0, wifi_packet_size_bytes=36286)
    finally:
        logging.disable(logging.NOTSET)
    return r["measured_Cw"], r["measured_Cn"]


def study_dtmc(processes=None):
    jobs = [dict(w=w, seed=s) for w in PRE22_ORIG for s in DTMC_SEEDS]
    res = run_parallel(_dtmc, jobs, processes)
    same = True
    for w, (cw0, cn0) in PRE22_ORIG.items():
        v = [r for j, r in zip(jobs, res) if j["w"] == w]
        cw, cn = statistics.mean(x[0] for x in v), statistics.mean(x[1] for x in v)
        eq = round(cw, 3) == cw0 and round(cn, 3) == cn0
        same &= eq
        print(f"w={w}: Cw {cw:.3f} (pre_22.C {cw0:.3f})  Cn {cn:.3f} (pre_22.C {cn0:.3f})  {'same' if eq else 'DIFFERENT'}",
              flush=True)
    print("DTMC comparison unchanged under the defaults" if same else "DTMC comparison CHANGED", flush=True)


STUDIES = {"tr38889": study_tr38889, "distance": study_distance, "dtmc": study_dtmc}

if __name__ == "__main__":
    for name in sys.argv[1:] or list(STUDIES):
        print(f"=== {name} ===", flush=True)
        STUDIES[name]()
# Rashed-Step 23.F-10-17-2026-end
