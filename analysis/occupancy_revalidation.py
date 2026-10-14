# Rashed-Step pre_22.C-10-13-2026-start
"""
CCNC model validation re-run on the Step 20 Wi-Fi stack (Step pre_22.C):
the DTMC channel-occupancy comparison of analysis/occupancy_model_vs_sim
(w = 1..6 co-located Wi-Fi APs + 1 NR-U gNB, saturated, fixed CW = Wo-1 =
31, 5.4 ms Wi-Fi PPDUs, 6 ms MCOT) with the original Wi-Fi model and with
the 802.11 frame exchange on the air (--wifi-mac-exchange). Mean over
SEEDS; prints the deviation from the model per w and writes a figure.

Run from the repo root: `python -m analysis.occupancy_revalidation`.
"""
import csv
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.laa_fairness import OUT_DIR
from analysis.plot_utils import save_line_figure, SERIES_STYLE, WIFI_COLOR, NRU_COLOR
from model.sweep import sweep_dtmc_by_w

W_VALUES = list(range(1, 7))
SEEDS = [1, 2, 3]
SIM_TIME_S = 10.0
STACKS = {"original": [], "mac": ["--wifi-mac-exchange", "--wifi-preamble-detect"]}


def run():
    out = {}
    for key, extra in STACKS.items():
        per_seed = [sweep_dtmc_by_w(W_VALUES, Wo=32, ng=55, Twp_us=5400.0, Tmcot_us=6000.0, sim_time_s=SIM_TIME_S,
                                    seed=s, ap_cluster_radius=2.0, wifi_packet_size_bytes=36286, extra_argv=extra)
                    for s in SEEDS]
        out[key] = [{"w": w,
                     "model_Cw": per_seed[0][i]["model_Cw"], "model_Cn": per_seed[0][i]["model_Cn"],
                     "Cw": statistics.mean(r[i]["measured_Cw"] for r in per_seed),
                     "Cn": statistics.mean(r[i]["measured_Cn"] for r in per_seed)}
                    for i, w in enumerate(W_VALUES)]
    return out


def main():
    out = run()
    rows = []
    print(f"{'w':>2}  {'model Cw':>8} {'orig Cw':>8} {'mac Cw':>8}   {'model Cn':>8} {'orig Cn':>8} {'mac Cn':>8}")
    for i, w in enumerate(W_VALUES):
        o, m = out["original"][i], out["mac"][i]
        print(f"{w:>2}  {o['model_Cw']:8.3f} {o['Cw']:8.3f} {m['Cw']:8.3f}   {o['model_Cn']:8.3f} {o['Cn']:8.3f} {m['Cn']:8.3f}")
        rows.append({"w": w, "model_Cw": o["model_Cw"], "orig_Cw": o["Cw"], "mac_Cw": m["Cw"],
                     "model_Cn": o["model_Cn"], "orig_Cn": o["Cn"], "mac_Cn": m["Cn"]})
    for key in ("orig", "mac"):
        dw = statistics.mean(abs(r[f"{key}_Cw"] - r["model_Cw"]) for r in rows)
        dn = statistics.mean(abs(r[f"{key}_Cn"] - r["model_Cn"]) for r in rows)
        print(f"mean |deviation| {key:4}: Wi-Fi {100 * dw:.2f} points, NR-U {100 * dn:.2f} points")
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "occupancy_revalidation.csv"), "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    SERIES_STYLE.setdefault("Wi-Fi (Simulated, frame exchange)", dict(color=WIFI_COLOR, marker="^", linestyle=":"))
    SERIES_STYLE.setdefault("NR-U (Simulated, frame exchange)", dict(color=NRU_COLOR, marker="h", linestyle=":"))
    series = {
        "Wi-Fi (Model)": [r["model_Cw"] for r in rows],
        "Wi-Fi (Simulated)": [r["orig_Cw"] for r in rows],
        "Wi-Fi (Simulated, frame exchange)": [r["mac_Cw"] for r in rows],
        "NR-U (Model)": [r["model_Cn"] for r in rows],
        "NR-U (Simulated)": [r["orig_Cn"] for r in rows],
        "NR-U (Simulated, frame exchange)": [r["mac_Cn"] for r in rows],
    }
    save_line_figure(W_VALUES, series, "Number of coexisting Wi-Fi APs (w)", "Normalized channel occupancy", "",
                     "occupancy_revalidation")


if __name__ == "__main__":
    main()
# Rashed-Step pre_22.C-10-13-2026-end
