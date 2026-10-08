# Rashed-Step pre_20.C-10-08-2026-start
"""
LAA / NR-U fairness study, diagnosis sweeps (Step pre_20.C). Every point
is the 3GPP replacement test (analysis/laa_fairness.py): Wi-Fi network A
at (0, 0) next to neighbor network B at (d, 0) - a second Wi-Fi network
or an NR-U network with the same load - Wi-Fi preamble detection on,
mean over SEEDS with 95% CI error bars.

Figures (analysis/generated/, PDF + JPG):
  laa_fairness_latency_vs_distance    - network A mean packet latency
  laa_fairness_failures_vs_distance   - network A frame failure ratio
  laa_fairness_throughput_vs_distance - network A throughput, A saturated
  laa_fairness_latency_vs_load        - A latency vs neighbor load, 40 m
  laa_fairness_ampdu                  - A latency, single frames vs A-MPDU
Reference lines on the distance figures (this simulator's log-distance
path loss, exponent 3.0, FSPL at 1 m, 5.18 GHz, no shadowing):
  ~18.9 m  NR-U (23 dBm) drops below Wi-Fi's -62 dBm energy detection
  ~32.4 m  Wi-Fi (20 dBm) drops below NR-U's -72 dBm energy detection
  ~69.6 m  Wi-Fi drops below Wi-Fi's -82 dBm preamble detection
So 18.9-32.4 m is the asymmetric region (NR-U hears Wi-Fi, Wi-Fi does not
hear NR-U); from 32.4 m on neither hears the other by energy detection
while a second Wi-Fi network is still heard through its preamble.

Run from the repo root: `python -m analysis.laa_fairness_sweeps`.
"""
import csv
import math
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.laa_fairness import run_case, OUT_DIR
from analysis.plot_utils import save_bar_figure, save_line_figure, WIFI_COLOR, NRU_COLOR
from wifi.wifi import Config

SEEDS = [1, 2, 3, 4, 5]
SIM_TIME_S = 1.0
LOAD_A = 1500.0            # ~18 Mbps
LOAD_B = 2500.0            # ~29 Mbps
DISTANCES = [5, 10, 15, 20, 25, 30, 35, 40, 50, 60, 70, 80]
LOADS_B = [250, 500, 1000, 1500, 2500, 4000]
LABEL = {"wifi": "Neighbor: Wi-Fi", "nru": "Neighbor: NR-U"}


def crossover_m(tx_dbm: float, threshold_dbm: float, f_hz: float = 5.18e9, n: float = 3.0) -> float:
    """Distance where tx_dbm falls to threshold_dbm (log-distance, 1 m ref)."""
    fspl_1m = 20 * math.log10(4 * math.pi * f_hz / 3e8)
    return 10 ** ((tx_dbm - fspl_1m - threshold_dbm) / (10 * n))


def _ci(vals):
    return 1.96 * statistics.stdev(vals) / len(vals) ** 0.5 if len(vals) > 1 else 0.0


def sweep(points, make_args):
    """{b: {"lat": [(mean, ci)], "fail": [...], "thr": [...]}} over points."""
    out = {b: {"lat": [], "fail": [], "thr": []} for b in ("wifi", "nru")}
    rows = []
    for x in points:
        for b in ("wifi", "nru"):
            runs = [run_case(b, seed=s, sim_time_s=SIM_TIME_S, **make_args(x)) for s in SEEDS]
            lat = [r["a"]["avg_latency_us"] / 1000.0 for r in runs]
            fail = [100.0 * r["fairness"]["tech"]["WiFi"]["failure_ratio"] for r in runs]
            thr = [r["a"]["throughput_mbps"] for r in runs]
            for k, v in (("lat", lat), ("fail", fail), ("thr", thr)):
                out[b][k].append((statistics.mean(v), _ci(v)))
            rows.append({"x": x, "neighbor": b, "a_latency_ms": statistics.mean(lat),
                         "a_fail_pct": statistics.mean(fail), "a_mbps": statistics.mean(thr),
                         "b_mbps": statistics.mean(r["b"]["throughput_mbps"] for r in runs)})
    return out, rows


def _line(points, out, key, ylabel, stem, xlabel, vlines=None):
    series = {LABEL[b]: [m for m, _ in out[b][key]] for b in out}
    yerr = {LABEL[b]: [c for _, c in out[b][key]] for b in out}
    return save_line_figure(points, series, xlabel, ylabel, "", stem, vlines=vlines, yerr=yerr)


def _write(rows, name):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, name), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main():
    v = [(round(crossover_m(23.0, -62.0), 1), "NR-U below Wi-Fi ED (-62 dBm)"),
         (round(crossover_m(20.0, -72.0), 1), "Wi-Fi below NR-U ED (-72 dBm)"),
         (round(crossover_m(20.0, -82.0), 1), "Wi-Fi below preamble detection (-82 dBm)")]
    print("crossovers (m):", v)

    out, rows = sweep(DISTANCES, lambda d: dict(load_a_pps=LOAD_A, load_b_pps=LOAD_B, distance_m=float(d)))
    _write(rows, "laa_fairness_distance.csv")
    _line(DISTANCES, out, "lat", "Network A latency (ms)", "laa_fairness_latency_vs_distance",
          "Distance between the networks (m)", vlines=v)
    _line(DISTANCES, out, "fail", "Network A frame failures (%)", "laa_fairness_failures_vs_distance",
          "Distance between the networks (m)", vlines=v)
    for r in rows:
        print("dist", r)

    out_s, rows_s = sweep(DISTANCES, lambda d: dict(load_a_pps=None, load_b_pps=LOAD_B, distance_m=float(d)))
    _write(rows_s, "laa_fairness_distance_saturated.csv")
    _line(DISTANCES, out_s, "thr", "Network A throughput (Mbps)", "laa_fairness_throughput_vs_distance",
          "Distance between the networks (m)", vlines=v)
    for r in rows_s:
        print("sat", r)

    out_l, rows_l = sweep(LOADS_B, lambda lb: dict(load_a_pps=LOAD_A, load_b_pps=float(lb), distance_m=40.0))
    _write(rows_l, "laa_fairness_load.csv")
    _line(LOADS_B, out_l, "lat", "Network A latency (ms)", "laa_fairness_latency_vs_load",
          "Neighbor load (packets/s)")
    for r in rows_l:
        print("load", r)

    cats, lat = ["1 frame / access", "A-MPDU (32)"], {"wifi": [], "nru": []}
    rows_a = []
    for cat, agg in zip(cats, (1, 32)):
        for b in ("wifi", "nru"):
            runs = [run_case(b, LOAD_A, LOAD_B, 40.0, s, SIM_TIME_S, wifi_config=Config(ampdu_max_mpdus=agg))
                    for s in SEEDS]
            m = statistics.mean(r["a"]["avg_latency_us"] / 1000.0 for r in runs)
            lat[b].append(m)
            rows_a.append({"wifi_tx": cat, "neighbor": b, "a_latency_ms": m,
                           "a_fail_pct": statistics.mean(100 * r["fairness"]["tech"]["WiFi"]["failure_ratio"] for r in runs)})
    _write(rows_a, "laa_fairness_ampdu.csv")
    save_bar_figure(cats, {LABEL[b]: lat[b] for b in lat}, "Wi-Fi transmission", "Network A latency (ms)",
                    "laa_fairness_ampdu", bar_colors={LABEL["wifi"]: WIFI_COLOR, LABEL["nru"]: NRU_COLOR})
    for r in rows_a:
        print("ampdu", r)


if __name__ == "__main__":
    main()
# Rashed-Step pre_20.C-10-08-2026-end
