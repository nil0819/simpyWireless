# Rashed-Step pre_20.A-10-08-2026-start
"""
LAA / NR-U fairness study (Step pre_20): the 3GPP replacement test
(TR 38.889 7.2.1 / TR 36.889 8.2): "NR-U should not impact Wi-Fi more
than an additional Wi-Fi network on the same carrier".

Network A - Wi-Fi AP 1 at (0, 0) with its STA, Poisson load load_a_pps.
Network B - at (d, 0), carrying Poisson downlink load load_b_pps with the
same packet size, either
    "wifi": a second Wi-Fi AP (+ STA), or
    "nru":  an NR-U gNB (+ UE), "slots" COT model.
The verdict is network A's throughput and latency next to NR-U compared
with next to Wi-Fi (ratios over the same seeds). Wi-Fi uses 802.11
preamble detection (-82 dBm for Wi-Fi frames, -62 dBm energy detection
for anything else) - the asymmetry the study is about.

Network B as standalone NR-U downlink is exactly the unlicensed side of
LAA when the SCell carries the data (the licensed PCell never touches the
5 GHz channel - Step 19.E.4).

Run from the repo root: `python -m analysis.laa_fairness` (prints the
baseline table and writes analysis/generated/laa_fairness_baseline.csv).
"""
import contextlib
import csv
import io
import logging
import os
import statistics
import sys
from dataclasses import replace
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import simulation
from common.packet import TrafficConfig
from nru.nru import Config_NR
from wifi.wifi import Config

PACKET_BYTES = 1472           # Wi-Fi's MSDU size; NR-U carries the same packets
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated")


def run_case(network_b: str, load_a_pps: float, load_b_pps: float, distance_m: float, seed: int,
             sim_time_s: float = 1.0, wifi_config: Optional[Config] = None,
             nru_config: Optional[Config_NR] = None, wifi_preamble_detect: bool = True) -> Dict:
    """One run; returns network A / B throughput and latency plus the
    run's fairness dict."""
    assert network_b in ("wifi", "nru")
    wifi = wifi_config or Config()
    if wifi_preamble_detect:
        wifi = replace(wifi, preamble_detect_dbm=-82.0)
    nru = nru_config or Config_NR(cot_model="slots")
    ta = TrafficConfig(mode="poisson", arrival_rate_pps=load_a_pps, packet_size_bytes=PACKET_BYTES)
    tb = TrafficConfig(mode="poisson", arrival_rate_pps=load_b_pps, packet_size_bytes=PACKET_BYTES)
    n_ap = 2 if network_b == "wifi" else 1
    n_gnb = 1 if network_b == "nru" else 0
    backoffs = {k: {n_ap: 0} for k in range(max(wifi.cw_max, 1023) + 1)}
    kw = dict(area_w=max(50.0, distance_m + 20), area_h=50.0, sta_radius=5.0, ue_radius=5.0,
              ap_positions=[(0.0, 0.0), (distance_m, 0.0)][:n_ap], gnb_positions=[(distance_m, 0.0)],
              wifi_traffic_config=ta, nru_traffic_config=tb, fairness_report=True)
    if network_b == "wifi":
        kw["wifi_ap_traffic_configs"] = [ta, tb]
    logging.disable(logging.CRITICAL)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            fair = simulation.run_simulation(n_ap, n_gnb, seed, sim_time_s, wifi, nru, backoffs,
                                             {}, {}, {}, {}, False, **kw)
    finally:
        logging.disable(logging.NOTSET)
    nodes = fair["nodes"]
    b_name = "AP 2" if network_b == "wifi" else "Gnb 1"
    return {"a": nodes["AP 1"], "b": nodes[b_name], "fairness": fair}


def replacement_test(load_a_pps: float, load_b_pps: float, distance_m: float, seeds: List[int],
                     sim_time_s: float = 1.0, **case_kw) -> Dict:
    """Both cases over the same seeds; network A's mean throughput/latency
    and the NR-U / Wi-Fi ratios."""
    res = {}
    for b in ("wifi", "nru"):
        runs = [run_case(b, load_a_pps, load_b_pps, distance_m, s, sim_time_s, **case_kw) for s in seeds]
        lat = [r["a"]["avg_latency_us"] for r in runs if r["a"]["avg_latency_us"] is not None]
        res[b] = {
            "a_mbps": statistics.mean(r["a"]["throughput_mbps"] for r in runs),
            "a_latency_ms": (statistics.mean(lat) / 1000.0) if lat else None,
            "b_mbps": statistics.mean(r["b"]["throughput_mbps"] for r in runs),
            "a_fail_ratio": statistics.mean(r["fairness"]["tech"]["WiFi"]["failure_ratio"] for r in runs),
        }
    w, n = res["wifi"], res["nru"]
    res["throughput_ratio"] = (n["a_mbps"] / w["a_mbps"]) if w["a_mbps"] else None
    res["latency_ratio"] = (n["a_latency_ms"] / w["a_latency_ms"]) if (w["a_latency_ms"] and n["a_latency_ms"]) else None
    return res


BASELINE = {
    "load_a_pps": 1000.0,                      # ~12 Mbps for network A
    "loads_b_pps": [250.0, 1000.0, 2500.0],    # ~3, ~12, ~29 Mbps for network B
    "distances_m": [10.0, 40.0],               # both hear each other / NR-U below Wi-Fi's -62 dBm ED
    "seeds": [1, 2, 3, 4, 5],
    "sim_time_s": 1.0,
}


def main():
    rows = []
    print("3GPP replacement test - network A (Wi-Fi) next to network B = Wi-Fi vs NR-U")
    print(f"{'d (m)':>6} {'B load':>7} | {'A Mbps (B=WiFi)':>15} {'A Mbps (B=NR-U)':>15} {'ratio':>6} | "
          f"{'A ms (WiFi)':>11} {'A ms (NR-U)':>11} | {'A fail (WiFi)':>13} {'A fail (NR-U)':>13}")
    for d in BASELINE["distances_m"]:
        for lb in BASELINE["loads_b_pps"]:
            r = replacement_test(BASELINE["load_a_pps"], lb, d, BASELINE["seeds"], BASELINE["sim_time_s"])
            w, n = r["wifi"], r["nru"]
            print(f"{d:>6.0f} {lb:>7.0f} | {w['a_mbps']:>15.2f} {n['a_mbps']:>15.2f} {r['throughput_ratio']:>6.2f} | "
                  f"{w['a_latency_ms']:>11.2f} {n['a_latency_ms']:>11.2f} | {w['a_fail_ratio']:>13.3f} {n['a_fail_ratio']:>13.3f}")
            rows.append({"distance_m": d, "load_b_pps": lb, **{f"wifi_{k}": v for k, v in w.items()},
                         **{f"nru_{k}": v for k, v in n.items()},
                         "throughput_ratio": r["throughput_ratio"], "latency_ratio": r["latency_ratio"]})
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "laa_fairness_baseline.csv")
    with open(path, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
# Rashed-Step pre_20.A-10-08-2026-end
