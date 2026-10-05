# Rashed-Step 17.G-10-05-2026-start
"""
Figures: NR-U uplink access, autonomous (Step 15.C - every UE runs its own
Cat-4 LBT) vs COT sharing (Step 17 - the gNB grants its UEs the uplink
part of its own channel occupancy time; UEs send after a 25us Type 2A
check). Project details/Step 17.txt, 17.G.

Three scenarios, each run through singleRun.py's real CLI in-process
(model.runner.run_scenario) with NR-U uplink and RRC on, both access
modes, 10 seeds x 1s:
  1 cell          - 1 gNB + its UE, no Wi-Fi (the self-collision case:
                    autonomous mode delivers nothing in either direction)
  2 cells         - 2 gNBs + UEs in a 20x20m area (they hear each other)
  1 cell + Wi-Fi  - 1 gNB + UE coexisting with 1 Wi-Fi AP + STA
Three figures (grouped bars, means over seeds; 95% CI half-widths in the
printed table):
  nru_ul_access_uplink_throughput   - NR-U uplink goodput (Mbps)
  nru_ul_access_downlink_throughput - NR-U downlink goodput (Mbps)
  nru_ul_access_rrc_latency         - NR-U RRC connection setup (ms)
Autonomous is drawn in the baseline gray, COT sharing in the NR-U green.

Run standalone from the repo root:
`python -m analysis.nru_ul_access_comparison`.
"""
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model.runner import run_scenario
from analysis.plot_utils import save_bar_figure, BASELINE_COLOR, NRU_COLOR

SEEDS = list(range(1, 11))
SIM_TIME_S = 1.0
SCENARIOS = [
    ("1 cell", ["--ap-number", "0", "--gnb-number", "1"]),
    ("2 cells", ["--ap-number", "0", "--gnb-number", "2", "--area-w", "20", "--area-h", "20"]),
    ("1 cell + Wi-Fi", ["--ap-number", "1", "--gnb-number", "1"]),
]
MODES = [
    ("Autonomous (Cat-4)", "autonomous"),
    ("COT sharing", "cot_sharing"),
]
BAR_COLORS = {"Autonomous (Cat-4)": BASELINE_COLOR, "COT sharing": NRU_COLOR}


def _ci95(values):
    if len(values) < 2:
        return 0.0
    return 1.96 * statistics.stdev(values) / len(values) ** 0.5


def _run(scenario_argv, mode, seed):
    argv = scenario_argv + ["-t", str(SIM_TIME_S), "-r", "1", "--seed", str(seed),
                            "--nru-ue-uplink-enabled", "--nru-rrc-enabled",
                            "--nru-ul-access-mode", mode]
    r = run_scenario(argv)
    rrc = r.get("nru_rrc_latency_us")
    return {
        "ul_mbps": r.get("nru_ul_throughput_mbps") or 0.0,
        "dl_mbps": r.get("nru_throughput_mbps") or 0.0,
        "rrc_ms": rrc / 1000.0 if rrc is not None else None,
    }


def generate(seeds=SEEDS):
    results = {}
    for s_label, s_argv in SCENARIOS:
        for m_label, mode in MODES:
            rows = [_run(s_argv, mode, seed) for seed in seeds]
            results[(s_label, m_label)] = {
                k: [row[k] for row in rows if row[k] is not None] for k in ("ul_mbps", "dl_mbps", "rrc_ms")
            }

    categories = [label for label, _ in SCENARIOS]

    def series(metric):
        return {m_label: [statistics.mean(results[(s, m_label)][metric]) if results[(s, m_label)][metric] else 0.0
                          for s in categories]
                for m_label, _ in MODES}

    paths = {
        "uplink": save_bar_figure(categories, series("ul_mbps"), "Scenario", "NR-U uplink throughput (Mbps)",
                                  "nru_ul_access_uplink_throughput", value_fmt="{:.2f}", bar_colors=BAR_COLORS),
        "downlink": save_bar_figure(categories, series("dl_mbps"), "Scenario", "NR-U downlink throughput (Mbps)",
                                    "nru_ul_access_downlink_throughput", value_fmt="{:.2f}", bar_colors=BAR_COLORS),
        "rrc": save_bar_figure(categories, series("rrc_ms"), "Scenario", "RRC connection setup (ms)",
                               "nru_ul_access_rrc_latency", value_fmt="{:.1f}", bar_colors=BAR_COLORS),
    }
    return results, paths


if __name__ == "__main__":
    results, paths = generate()
    print(f"{'scenario':<16} {'mode':<20} | {'UL Mbps':>14} | {'DL Mbps':>14} | {'RRC ms':>14}   "
          f"(mean +/- 95% CI, {len(SEEDS)} seeds x {SIM_TIME_S}s)")
    print("-" * 92)
    for s_label, _ in SCENARIOS:
        for m_label, _ in MODES:
            r = results[(s_label, m_label)]
            cells = []
            for k in ("ul_mbps", "dl_mbps", "rrc_ms"):
                v = r[k]
                cells.append(f"{statistics.mean(v):7.3f} +/-{_ci95(v):5.3f}" if v else f"{'n/a':>14}")
            print(f"{s_label:<16} {m_label:<20} | {cells[0]} | {cells[1]} | {cells[2]}")
    print()
    for p in paths.values():
        print(f"Saved: {p['pdf']}")
        print(f"Saved: {p['jpg']}")
# Rashed-Step 17.G-10-05-2026-end
