# Rashed-Step 22.E-10-15-2026-start
"""
LAA / NR-U coexistence on a realistic channel (Step 22.E, Phase D).

The pre_20 / pre_22 replacement-test results used the log-distance path
loss (exponent 3) with no shadowing or fading. Here the same 3GPP test runs
on the Step 22 channel models.

Studies (python -m analysis.realism_study [distance] [tr38889]):

  distance  Two networks (analysis/laa_fairness.py: Wi-Fi network A at
            (0,0), neighbor B at (d,0) = Wi-Fi or NR-U, A 1500 / B 2500
            pkt/s, frame exchange on the air, preamble detection on, NR-U
            slots), 5 seeds x 1 s, on four channels:
              log-distance (as before), 38.901 InH-Office (mixed),
              InH + its shadowing (22.B), InH + shadowing + fading (22.C).
            Latency ratio (A next to NR-U / next to Wi-Fi) vs distance.
  tr38889   The test on its own layout (TR 38.889 indoor, 22.D): operator
            B = 3 Wi-Fi APs, operator A = 3 Wi-Fi APs or 3 NR-U gNBs, 5
            users per cell (re-dropped below -82 dBm serving power, as
            A.1.1), InH + shadowing + fading, preamble detection,
            rate adaptation, 23 dBm cells, Poisson load per cell; operator
            B's mean latency / throughput next to Wi-Fi vs next to NR-U
            (NR-U default, and ED -82 dBm + 20 dBm CTS-to-self). 5 seeds x 2 s.
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
from analysis.plot_utils import save_line_figure, SERIES_STYLE, BASELINE_COLOR, WIFI_COLOR, NRU_COLOR
from channel.propagation import PathLossSpec
from common.layouts import build_layout, serving_rule
from nru.nru import Config_NR
from common.packet import TrafficConfig
from wifi.wifi import Config

SEEDS = [1, 2, 3, 4, 5]
SIM_TIME_S = 1.0
LOAD_A, LOAD_B = 1500.0, 2500.0
DISTANCES = [5, 10, 20, 30, 35, 40, 50, 60, 80]

CHANNELS = {
    "logdist": ("Log-distance (pre_20 / pre_22)", {}),
    "inh": ("38.901 InH-Office", {"pathloss": PathLossSpec("inh-office-mixed")}),
    "inh_sh": ("InH + shadowing", {"pathloss": PathLossSpec("inh-office-mixed", shadowing=True)}),
    "inh_sh_f": ("InH + shadowing + fading",
                 {"pathloss": PathLossSpec("inh-office-mixed", shadowing=True), "fading": (None, None)}),
}

TR_SEEDS = [1, 2, 3, 4, 5]
TR_SIM_TIME_S = 2.0
TR_LOADS_PPS = [50.0, 100.0]           # per cell, 1500 B packets: 0.6 / 1.2 Mbps (one 20 MHz channel for 6 cells)
TR_CASES = [
    ("Next to Wi-Fi", "wifi", {}),
    ("Next to NR-U", "nru", {}),
    ("Next to NR-U, ED -82 + CTS 20 dBm", "nru", dict(ed_threshold_dbm=-82.0, wifi_reservation="cts_to_self",
                                                      cts_power_dbm=20.0)),
]


def _mean_ci(v):
    m = statistics.mean(v)
    return m, (1.96 * statistics.stdev(v) / len(v) ** 0.5 if len(v) > 1 else 0.0)


def _write(rows, name):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, name), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def measure(channel, neighbor, d):
    runs = [run_case(neighbor, LOAD_A, LOAD_B, float(d), s, SIM_TIME_S, wifi_config=Config(mac_exchange=True),
                     nru_config=Config_NR(cot_model="slots"), sim_kw=CHANNELS[channel][1])
            for s in SEEDS]
    lat = [r["a"]["avg_latency_us"] / 1000.0 for r in runs]
    return {"a_latency_ms": _mean_ci(lat)[0], "a_latency_ci": _mean_ci(lat)[1],
            "a_fail_pct": statistics.mean(100.0 * r["fairness"]["tech"]["WiFi"]["failure_ratio"] for r in runs)}


def passes(nru, ref):
    return nru["a_latency_ms"] <= 1.1 * ref["a_latency_ms"] + ref["a_latency_ci"]


def study_distance():
    rows, ratio = [], {}
    for key, (label, _) in CHANNELS.items():
        ratio[label] = []
        for d in DISTANCES:
            ref = measure(key, "wifi", d)
            nru = measure(key, "nru", d)
            ratio[label].append(nru["a_latency_ms"] / ref["a_latency_ms"])
            rows.append({"channel": key, "distance_m": d, "ref_latency_ms": ref["a_latency_ms"],
                         "nru_latency_ms": nru["a_latency_ms"], "ratio": ratio[label][-1],
                         "ref_fail_pct": ref["a_fail_pct"], "nru_fail_pct": nru["a_fail_pct"],
                         "passes": passes(nru, ref)})
            print(f"{key:9} {d:>3} m  ref {ref['a_latency_ms']:7.2f} ms ({ref['a_fail_pct']:5.1f}%)  "
                  f"NR-U {nru['a_latency_ms']:7.2f} ms ({nru['a_fail_pct']:5.1f}%)  ratio {ratio[label][-1]:6.2f}  "
                  f"{'pass' if passes(nru, ref) else 'FAIL'}", flush=True)
    _write(rows, "realism_distance.csv")
    styles = [(BASELINE_COLOR, "o"), (WIFI_COLOR, "^"), (NRU_COLOR, "h"), ("#b05a1e", "s")]
    for (lab, _), (c, m) in zip(CHANNELS.values(), styles):
        SERIES_STYLE.setdefault(lab, dict(color=c, marker=m, linestyle="-"))
    save_line_figure(DISTANCES, ratio, "Distance between the networks (m)",
                     "Latency next to NR-U / next to Wi-Fi", "", "realism_latency_ratio",
                     hlines=[(1.0, "Replacement-test parity")])


def tr_run(op_a, seed, load_pps, nru_kw):
    """One TR 38.889 indoor run; operator B's per-AP node stats."""
    spec = PathLossSpec("inh-office-mixed", shadowing=True)
    # TR 38.889 A.1.1: a user whose serving cell reaches it below -82 dBm is
    # dropped again (cells at 23 dBm on 5.18 GHz, InH + shadowing as the run).
    lay = build_layout("tr38889-indoor", seed,
                       serving_ok=serving_rule(-82.0, lambda site: 23.0, lambda site: 5.18e9, spec, seed))
    a_sites, b_sites = lay.operator_sites("A"), lay.operator_sites("B")
    aps = (a_sites if op_a == "wifi" else []) + b_sites
    gnbs = a_sites if op_a == "nru" else []
    wifi = Config(mac_exchange=True, preamble_detect_dbm=-82.0, rate_adapt_enabled=True, tx_power_dbm=23.0)
    nru = Config_NR(cot_model="slots", rate_adapt_enabled=True, **nru_kw)
    load = TrafficConfig(mode="poisson", arrival_rate_pps=load_pps, packet_size_bytes=1500)
    backoffs = {k: {len(aps): 0} for k in range(1024)}
    kw = dict(area_w=lay.area_w, area_h=lay.area_h,
              ap_positions=[s.pos for s in aps], gnb_positions=[s.pos for s in gnbs] or None,
              sta_positions=[list(s.users) for s in aps], ue_positions=[list(s.users) for s in gnbs] or None,
              wifi_traffic_config=load, nru_traffic_config=load, fairness_report=True,
              pathloss=spec, fading=(None, None))
    logging.disable(logging.CRITICAL)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            fair = simulation.run_simulation(len(aps), len(gnbs), seed, TR_SIM_TIME_S, wifi, nru, backoffs,
                                             {}, {}, {}, {}, False, **kw)
    finally:
        logging.disable(logging.NOTSET)
    b_names = [f"AP {i + 1}" for i in range(len(aps) - len(b_sites), len(aps))]
    return [fair["nodes"][n] for n in b_names]


def study_tr38889():
    rows = []
    for load in TR_LOADS_PPS:
        ref = None
        for label, op_a, nru_kw in TR_CASES:
            lat, thr = [], []
            for s in TR_SEEDS:
                b = tr_run(op_a, s, load, nru_kw)
                lat.append(statistics.mean(n["avg_latency_us"] / 1000.0 for n in b if n["avg_latency_us"] is not None))
                thr.append(sum(n["throughput_mbps"] for n in b))
            m_lat, ci = _mean_ci(lat)
            m_thr = statistics.mean(thr)
            if op_a == "wifi":
                ref = (m_lat, ci)
            ok = ref is not None and m_lat <= 1.1 * ref[0] + ref[1]
            rows.append({"load_pps_per_cell": load, "case": label, "b_latency_ms": m_lat, "b_latency_ci": ci,
                         "b_throughput_mbps": m_thr, "passes": ok if op_a == "nru" else ""})
            print(f"{load:>5.0f} pkt/s  {label:36} B latency {m_lat:7.2f} +- {ci:5.2f} ms  B {m_thr:6.2f} Mbps  "
                  f"{'' if op_a == 'wifi' else ('pass' if ok else 'FAIL')}", flush=True)
    _write(rows, "realism_tr38889.csv")


STUDIES = {"distance": study_distance, "tr38889": study_tr38889}

if __name__ == "__main__":
    for name in sys.argv[1:] or list(STUDIES):
        print(f"=== {name} ===")
        STUDIES[name]()
# Rashed-Step 22.E-10-15-2026-end
