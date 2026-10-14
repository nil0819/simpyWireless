# Rashed-Step pre_22.B-10-13-2026-start
"""
LAA / NR-U fairness study re-validated on the Step 20-21 Wi-Fi stack
(Step pre_22.B). The pre_20 study ran with the original Wi-Fi model (ACK
time only waited out, legacy 802.11a, one frame per access). Here the same
3GPP replacement test (analysis/laa_fairness.py: Wi-Fi network A at (0,0),
neighbor B at (d,0) = Wi-Fi or NR-U, A 1500 / B 2500 pkt/s, 5 seeds x 1 s,
preamble detection on) runs with three Wi-Fi stacks:

  original   - as in pre_20 (byte-identical to its results)
  mac        - 802.11 frame exchange on the air (--wifi-mac-exchange:
               ACK / NAV / EIFS, Step 20.A)
  he_ampdu   - HE20 MCS 7 + A-MPDU 32 + frame exchange (Steps 20.A-C)

Studies (python -m analysis.laa_revalidation [distance] [mitigations]):
  distance    - replacement-test latency ratio (A next to NR-U / A next to
                Wi-Fi) and A's frame failures vs distance, per stack.
  mitigations - pass/fail at 10 / 25 / 40 m for the pre_20 mitigations
                (ED -82 dBm, CTS-to-self, both) on the new stacks.
"""
import csv
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.laa_fairness import run_case, OUT_DIR
from analysis.laa_fairness_sweeps import crossover_m
from analysis.plot_utils import save_line_figure, SERIES_STYLE, BASELINE_COLOR, WIFI_COLOR, NRU_COLOR
from nru.nru import Config_NR
from wifi.wifi import Config

SEEDS = [1, 2, 3, 4, 5]
SIM_TIME_S = 1.0
LOAD_A, LOAD_B = 1500.0, 2500.0
DISTANCES = [5, 10, 15, 20, 25, 30, 35, 40, 50, 60, 70, 80]
MIT_DISTANCES = [10.0, 25.0, 40.0]

STACKS = {
    "original": ("Original Wi-Fi (pre_20)", lambda: None),
    "mac": ("Frame exchange on the air", lambda: Config(mac_exchange=True)),
    "he_ampdu": ("HE20 + A-MPDU + frame exchange",
                 lambda: Config(phy="he", channel_width_mhz=20, mcs=7, ampdu_max_mpdus=32, mac_exchange=True)),
}
MITIGATIONS = [
    ("NR-U default", {}),
    ("ED -82 dBm", dict(ed_threshold_dbm=-82.0)),
    ("CTS-to-self", dict(wifi_reservation="cts_to_self")),
    ("ED -82 + CTS-to-self", dict(ed_threshold_dbm=-82.0, wifi_reservation="cts_to_self")),
]


def _mean_ci(v):
    m = statistics.mean(v)
    return m, (1.96 * statistics.stdev(v) / len(v) ** 0.5 if len(v) > 1 else 0.0)


def measure(stack, neighbor, d, nru_kw=None):
    wifi_cfg = STACKS[stack][1]
    runs = [run_case(neighbor, LOAD_A, LOAD_B, float(d), s, SIM_TIME_S, wifi_config=wifi_cfg(),
                     nru_config=Config_NR(cot_model="slots", **(nru_kw or {})))
            for s in SEEDS]
    lat = [r["a"]["avg_latency_us"] / 1000.0 for r in runs]
    return {"a_latency_ms": _mean_ci(lat)[0], "a_latency_ci": _mean_ci(lat)[1],
            "a_fail_pct": statistics.mean(100.0 * r["fairness"]["tech"]["WiFi"]["failure_ratio"] for r in runs),
            "a_mbps": statistics.mean(r["a"]["throughput_mbps"] for r in runs),
            "b_mbps": statistics.mean(r["b"]["throughput_mbps"] for r in runs)}


def passes(nru, ref):
    return nru["a_latency_ms"] <= 1.1 * ref["a_latency_ms"] + ref["a_latency_ci"]


def _write(rows, name):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, name), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def study_distance():
    rows, ratio = [], {}
    for key, (label, _) in STACKS.items():
        ratio[label] = []
        for d in DISTANCES:
            ref = measure(key, "wifi", d)
            nru = measure(key, "nru", d)
            ratio[label].append(nru["a_latency_ms"] / ref["a_latency_ms"])
            rows.append({"stack": key, "distance_m": d, "ref_latency_ms": ref["a_latency_ms"],
                         "nru_latency_ms": nru["a_latency_ms"], "ratio": ratio[label][-1],
                         "ref_fail_pct": ref["a_fail_pct"], "nru_fail_pct": nru["a_fail_pct"],
                         "passes": passes(nru, ref)})
            print(f"{key:9} {d:>3} m  ref {ref['a_latency_ms']:7.2f} ms ({ref['a_fail_pct']:5.1f}%)  "
                  f"NR-U {nru['a_latency_ms']:7.2f} ms ({nru['a_fail_pct']:5.1f}%)  ratio {ratio[label][-1]:6.2f}  "
                  f"{'pass' if passes(nru, ref) else 'FAIL'}")
    _write(rows, "laa_revalidation_distance.csv")
    styles = dict(zip([v[0] for v in STACKS.values()], [(BASELINE_COLOR, "o"), (WIFI_COLOR, "^"), (NRU_COLOR, "h")]))
    for lab, (c, m) in styles.items():
        SERIES_STYLE.setdefault(lab, dict(color=c, marker=m, linestyle="-"))
    v = [(round(crossover_m(23.0, -62.0), 1), "NR-U below Wi-Fi ED"),
         (round(crossover_m(20.0, -72.0), 1), "Wi-Fi below NR-U ED")]
    save_line_figure(DISTANCES, ratio, "Distance between the networks (m)",
                     "Latency next to NR-U / next to Wi-Fi", "", "laa_revalidation_latency_ratio",
                     vlines=v, hlines=[(1.0, "Replacement-test parity")])


def study_mitigations():
    rows = []
    for key in ("mac", "he_ampdu"):
        for d in MIT_DISTANCES:
            ref = measure(key, "wifi", d)
            for label, kw in MITIGATIONS:
                m = measure(key, "nru", d, kw)
                rows.append({"stack": key, "distance_m": d, "variant": label, "ref_latency_ms": ref["a_latency_ms"],
                             "nru_latency_ms": m["a_latency_ms"], "nru_fail_pct": m["a_fail_pct"],
                             "b_mbps": m["b_mbps"], "passes": passes(m, ref)})
                print(f"{key:9} {d:>4.0f} m  {label:22} ref {ref['a_latency_ms']:7.2f}  NR-U {m['a_latency_ms']:7.2f} ms "
                      f"({m['a_fail_pct']:5.1f}%)  B {m['b_mbps']:5.1f}  {'pass' if passes(m, ref) else 'FAIL'}")
    _write(rows, "laa_revalidation_mitigations.csv")


STUDIES = {"distance": study_distance, "mitigations": study_mitigations}

if __name__ == "__main__":
    for name in sys.argv[1:] or list(STUDIES):
        print(f"=== {name} ===")
        STUDIES[name]()
# Rashed-Step pre_22.B-10-13-2026-end
