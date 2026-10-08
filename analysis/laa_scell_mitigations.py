# Rashed-Step pre_20.D.4-10-08-2026-start
"""
LAA fairness study, the original 19.F scenario (Step pre_20.D.4): one
Wi-Fi AP (saturated) + an NR-U gNB carrying an LAA SCell for a
co-located 20 MHz licensed cell (4 UEs, ~193 Mbps offered, HARQ), Wi-Fi
preamble detection on. Wi-Fi throughput and SCell throughput per
mitigation, mean over SEEDS (1 s each), via the singleRun CLI.

Reference: Wi-Fi alone ~30.8 Mbps; next to a saturated Wi-Fi neighbor it
would get about half.

Run from the repo root: `python -m analysis.laa_scell_mitigations`
(`--plot-only` redraws the figure from the CSV).
"""
import csv
import os
import re
import statistics
import subprocess
import sys
import textwrap

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.laa_fairness import OUT_DIR
from analysis.plot_utils import save_bar_figure, WIFI_COLOR, NRU_COLOR

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEEDS = [1, 2, 3]
BASE = ("--ap-number 1 --gnb-number 1 -t 1 -r 1 --nru-cot-model slots --nru-traffic-model poisson "
        "--nru-arrival-rate-pps 20 --nr-gnb-number 1 --nr-colocated --nr-bandwidth-mhz 20 --nr-dl-traffic poisson "
        "--nr-dl-arrival-rate-pps 4000 --nru-scell --harq --wifi-preamble-detect").split()
FIX = "--nru-ed-threshold-dbm -82 --nru-wifi-reservation cts_to_self".split()
VARIANTS = [
    ("Default", []),
    ("Ref. slot Z=0.1", "--nru-ref-nack-threshold 0.1".split()),
    ("Adaptive COT", ["--nru-adaptive-cot"]),
    ("Z=0.1 + adaptive COT", "--nru-ref-nack-threshold 0.1 --nru-adaptive-cot".split()),
    ("ED -82 + CTS", FIX),
    ("ED -82 + CTS + CAPC p1", FIX + "--nru-priority-class 1".split()),
    ("ED -82 + CTS + A-MPDU 32", FIX + "--wifi-ampdu 32".split()),
]


def run(extra, seed):
    out = subprocess.run([sys.executable, "singleRun.py", *BASE, "--seed", str(seed), *extra], cwd=REPO,
                         capture_output=True, text=True).stdout
    wifi = float(re.search(r"Wifi packet throughput \(Mbps\): ([0-9.]+)", out).group(1))
    scell = float(re.search(r"LAA DL throughput on the NR-U SCell \(Mbps\): ([0-9.]+)", out).group(1))
    cots, failed = map(int, re.search(r"NRU COTs: (\d+) \(reference slot failed: (\d+)", out).groups())
    return wifi, scell, cots, failed


def main():
    rows = []
    for label, extra in VARIANTS:
        res = [run(extra, s) for s in SEEDS]
        rows.append({"variant": label,
                     "wifi_mbps": statistics.mean(r[0] for r in res),
                     "scell_mbps": statistics.mean(r[1] for r in res),
                     "cots_per_s": statistics.mean(r[2] for r in res),
                     "ref_slot_failed_pct": 100.0 * sum(r[3] for r in res) / max(1, sum(r[2] for r in res))})
        r = rows[-1]
        print(f"{label:<28} Wi-Fi {r['wifi_mbps']:6.2f}  SCell {r['scell_mbps']:6.2f}  "
              f"COTs/s {r['cots_per_s']:6.1f}  ref fail {r['ref_slot_failed_pct']:5.1f} %")
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "laa_scell_mitigations.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    plot(rows)


def plot(rows):
    save_bar_figure([textwrap.fill(r["variant"], 12) for r in rows],
                    {"Wi-Fi": [float(r["wifi_mbps"]) for r in rows],
                     "NR-U SCell": [float(r["scell_mbps"]) for r in rows]},
                    "", "Throughput (Mbps)", "laa_scell_mitigations", figsize=(12.0, 5.5), value_fmt="{:.1f}",
                    bar_colors={"Wi-Fi": WIFI_COLOR, "NR-U SCell": NRU_COLOR})


if __name__ == "__main__":
    if "--plot-only" in sys.argv:
        with open(os.path.join(OUT_DIR, "laa_scell_mitigations.csv"), newline="") as f:
            plot(list(csv.DictReader(f)))
    else:
        main()
# Rashed-Step pre_20.D.4-10-08-2026-end
