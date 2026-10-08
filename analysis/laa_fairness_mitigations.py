# Rashed-Step pre_20.D.1-10-08-2026-start
"""
LAA / NR-U fairness study, mitigations (Step pre_20.D). Each mitigation
is scored with the 3GPP replacement test (analysis/laa_fairness.py) at
the three regimes pre_20.C found (crossovers 18.9 / 32.3 / 69.6 m):
  10 m  both sides hear each other by energy detection
  25 m  one-sided: NR-U hears Wi-Fi, Wi-Fi does not hear NR-U
  40 m  neither hears the other by energy detection, NR-U still strong
        enough to break Wi-Fi frames (where NR-U failed the test)
Network A = Wi-Fi at 1500 pkt/s, neighbor B = 2500 pkt/s (as in
pre_20.C), 5 seeds x 1 s. "Pass" = network A's mean latency next to
NR-U is no worse than next to a Wi-Fi neighbor (10% + CI slack).

D.1 TS 37.213 channel access priority classes (Config_NR.priority_class).
D.2 energy-detection threshold: TS 37.213 clause 4.1.5 (power-dependent,
    Config_NR.ed_threshold_mode="ts37213") and fixed lower thresholds.
D.3 making COTs visible to Wi-Fi (Config_NR.wifi_reservation: an
    802.11-decodable preamble, or a CTS-to-self whose NAV covers the
    COT), alone and combined with a -82 dBm NR-U ED.

Run from the repo root: `python -m analysis.laa_fairness_mitigations
[capc|ed ...]` (default: all).
"""
import csv
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.laa_fairness import run_case, OUT_DIR
from analysis.plot_utils import save_bar_figure, BASELINE_COLOR, WIFI_COLOR, NRU_COLOR
from nru.nru import Config_NR

SEEDS = [1, 2, 3, 4, 5]
SIM_TIME_S = 1.0
LOAD_A = 1500.0
LOAD_B = 2500.0
DISTANCES = [10.0, 25.0, 40.0]


def _ci(vals):
    return 1.96 * statistics.stdev(vals) / len(vals) ** 0.5 if len(vals) > 1 else 0.0


def measure(network_b, d, **case_kw):
    """Network A latency / failures and B throughput, mean over SEEDS."""
    runs = [run_case(network_b, LOAD_A, LOAD_B, d, s, SIM_TIME_S, **case_kw) for s in SEEDS]
    lat = [r["a"]["avg_latency_us"] / 1000.0 for r in runs]
    return {"a_latency_ms": statistics.mean(lat), "a_latency_ci": _ci(lat),
            "a_fail_pct": statistics.mean(100.0 * r["fairness"]["tech"]["WiFi"]["failure_ratio"] for r in runs),
            "a_mbps": statistics.mean(r["a"]["throughput_mbps"] for r in runs),
            "b_mbps": statistics.mean(r["b"]["throughput_mbps"] for r in runs)}


def passes(nru, wifi_ref):
    return nru["a_latency_ms"] <= 1.1 * wifi_ref["a_latency_ms"] + wifi_ref["a_latency_ci"]


def score(variants, distances=DISTANCES, reference_kw=None):
    """variants: [(label, run_case kwargs for the NR-U case)]. The Wi-Fi
    reference (B = Wi-Fi) is run once per distance with reference_kw."""
    rows = []
    for d in distances:
        ref = measure("wifi", d, **(reference_kw or {}))
        rows.append({"distance_m": d, "variant": "Wi-Fi neighbor (reference)", **ref, "passes": ""})
        for label, kw in variants:
            m = measure("nru", d, **kw)
            rows.append({"distance_m": d, "variant": label, **m, "passes": passes(m, ref)})
    return rows


def print_rows(rows):
    print(f"{'d (m)':>6} {'variant':<30} {'A lat ms':>9} {'A fail %':>9} {'A Mbps':>7} {'B Mbps':>7}  pass")
    for r in rows:
        print(f"{r['distance_m']:>6.0f} {r['variant']:<30} {r['a_latency_ms']:>9.2f} {r['a_fail_pct']:>9.2f} "
              f"{r['a_mbps']:>7.2f} {r['b_mbps']:>7.2f}  {r['passes']}")


def write_csv(rows, name):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, name), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def bar_figure(rows, labels, stem, colors=None):
    """Network A latency per distance (x groups), one bar per variant."""
    cats = [f"{d:.0f} m" for d in DISTANCES]
    series = {lab: [next(r["a_latency_ms"] for r in rows if r["distance_m"] == d and r["variant"] == lab)
                    for d in DISTANCES] for lab in labels}
    return save_bar_figure(cats, series, "Distance between the networks", "Network A latency (ms)", stem,
                           bar_colors=colors)


def capc_variants():
    return [("NR-U, default (class 3, 6 ms)", dict(nru_config=Config_NR(cot_model="slots")))] + [
        (f"NR-U, CAPC p={p}", dict(nru_config=Config_NR(cot_model="slots", priority_class=p))) for p in (1, 2, 3, 4)]


def study_capc():
    rows = score(capc_variants())
    print_rows(rows)
    write_csv(rows, "laa_fairness_capc.csv")
    labels = ["Wi-Fi neighbor (reference)", "NR-U, default (class 3, 6 ms)"] + [f"NR-U, CAPC p={p}" for p in (1, 2, 3, 4)]
    greens = ["#a9c4a6", "#7fa37b", "#4b7248", "#2e4a2c"]
    colors = dict(zip(labels, [WIFI_COLOR, BASELINE_COLOR] + greens))
    bar_figure(rows, labels, "laa_fairness_capc", colors)
# Rashed-Step pre_20.D.1-10-08-2026-end


# Rashed-Step pre_20.D.2-10-08-2026-start
ED_VARIANTS = [
    # (label, Config_NR kwargs)
    ("NR-U, default (-72 dBm, 23 dBm)", {}),
    ("NR-U, TS 37.213 at 18 dBm (-67)", dict(tx_power_dbm=18.0, ed_threshold_mode="ts37213")),
    ("NR-U, TS 37.213 at 13 dBm (-62)", dict(tx_power_dbm=13.0, ed_threshold_mode="ts37213")),
    ("NR-U, ED -77 dBm (23 dBm)", dict(ed_threshold_dbm=-77.0)),
    ("NR-U, ED -82 dBm (23 dBm)", dict(ed_threshold_dbm=-82.0)),
]


def ed_variants():
    return [(lab, dict(nru_config=Config_NR(cot_model="slots", **kw))) for lab, kw in ED_VARIANTS]


def study_ed():
    rows = score(ed_variants())
    print_rows(rows)
    write_csv(rows, "laa_fairness_ed.csv")
    labels = ["Wi-Fi neighbor (reference)"] + [lab for lab, _ in ED_VARIANTS]
    colors = dict(zip(labels, [WIFI_COLOR, BASELINE_COLOR, "#a9c4a6", "#7fa37b", "#4b7248", "#2e4a2c"]))
    bar_figure(rows, labels, "laa_fairness_ed", colors)


CURVE_DISTANCES = [5, 10, 15, 20, 25, 30, 35, 40, 50, 60, 70, 80]


def distance_curves(variants, stem, colors, markers):
    """A latency vs distance: the Wi-Fi reference plus each NR-U variant."""
    from analysis.plot_utils import save_line_figure, SERIES_STYLE
    from analysis.laa_fairness_sweeps import crossover_m
    series, rows = {}, []
    for label, b, kw in [("Wi-Fi neighbor (reference)", "wifi", {})] + [(l, "nru", k) for l, k in variants]:
        SERIES_STYLE.setdefault(label, dict(color=colors[label], marker=markers[label], linestyle="-"))
        series[label] = []
        for d in CURVE_DISTANCES:
            m = measure(b, float(d), **kw)
            series[label].append(m["a_latency_ms"])
            rows.append({"distance_m": d, "variant": label, **m})
    v = [(round(crossover_m(23.0, -62.0), 1), "NR-U (23 dBm) below Wi-Fi ED"),
         (round(crossover_m(20.0, -72.0), 1), "Wi-Fi below NR-U ED (-72 dBm)")]
    save_line_figure(CURVE_DISTANCES, series, "Distance between the networks (m)", "Network A latency (ms)", "",
                     stem, vlines=v)
    return rows


def study_ed_distance():
    keep = ["NR-U, default (-72 dBm, 23 dBm)", "NR-U, TS 37.213 at 18 dBm (-67)",
            "NR-U, TS 37.213 at 13 dBm (-62)", "NR-U, ED -82 dBm (23 dBm)"]
    variants = [(lab, kw) for lab, kw in ed_variants() if lab in keep]
    colors = dict(zip(["Wi-Fi neighbor (reference)"] + keep, [WIFI_COLOR, BASELINE_COLOR, "#a9c4a6", "#7fa37b", NRU_COLOR]))
    markers = dict(zip(["Wi-Fi neighbor (reference)"] + keep, ["^", "o", "s", "D", "h"]))
    rows = distance_curves(variants, "laa_fairness_ed_vs_distance", colors, markers)
    write_csv(rows, "laa_fairness_ed_distance.csv")
    for r in rows:
        print(f"{r['distance_m']:>4} {r['variant']:<34} {r['a_latency_ms']:>8.2f} ms {r['a_fail_pct']:>6.2f} %  B {r['b_mbps']:.1f}")


# Rashed-Step pre_20.D.2-10-08-2026-end


# Rashed-Step pre_20.D.3-10-08-2026-start
RESERVATION_VARIANTS = [
    ("NR-U, default", {}),
    ("NR-U, Wi-Fi preamble", dict(wifi_reservation="preamble")),
    ("NR-U, CTS-to-self", dict(wifi_reservation="cts_to_self")),
    ("NR-U, ED -82 dBm", dict(ed_threshold_dbm=-82.0)),
    ("NR-U, ED -82 dBm + CTS-to-self", dict(ed_threshold_dbm=-82.0, wifi_reservation="cts_to_self")),
]


def study_reservation():
    variants = [(lab, dict(nru_config=Config_NR(cot_model="slots", **kw))) for lab, kw in RESERVATION_VARIANTS]
    labels = ["Wi-Fi neighbor (reference)"] + [lab for lab, _ in RESERVATION_VARIANTS]
    colors = dict(zip(labels, [WIFI_COLOR, BASELINE_COLOR, "#a9c4a6", "#7fa37b", "#2e4a2c", NRU_COLOR]))
    markers = dict(zip(labels, ["^", "o", "s", "D", "v", "h"]))
    rows = distance_curves(variants, "laa_fairness_reservation_vs_distance", colors, markers)
    ref = {r["distance_m"]: r for r in rows if r["variant"] == labels[0]}
    for r in rows:
        r["passes"] = "" if r["variant"] == labels[0] else passes(r, ref[r["distance_m"]])
    write_csv(rows, "laa_fairness_reservation.csv")
    for r in rows:
        print(f"{r['distance_m']:>4} {r['variant']:<34} {r['a_latency_ms']:>8.2f} ms {r['a_fail_pct']:>6.2f} %  "
              f"B {r['b_mbps']:.1f}  {r['passes']}")


STUDIES = {"capc": study_capc, "ed": study_ed, "ed_distance": study_ed_distance, "reservation": study_reservation}


def main(names=None):
    for name in names or list(STUDIES):
        print(f"=== {name} ===")
        STUDIES[name]()


if __name__ == "__main__":
    main(sys.argv[1:])
# Rashed-Step pre_20.D.3-10-08-2026-end
