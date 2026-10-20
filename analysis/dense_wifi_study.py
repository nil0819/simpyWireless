# Rashed-Step 25.E-10-20-2026-start
"""
Dense Wi-Fi (802.11ax) studies (Step 25.E): what the Step 25 features do
in a dense deployment and next to NR-U.

python -m analysis.dense_wifi_study [ladder] [sr] [coex]

  ladder  TGax residential (2 x 10 apartments, one AP + 5 STAs each, HE
          20 MHz, preamble detection, saturated downlink), 5 seeds x 1 s,
          features added one at a time: ARF -> Minstrel (25.B) -> + 2
          spatial streams (25.C) -> + OFDMA, equal RUs -> + demand RU plan
          (25.D) -> + MU-MIMO 2 users (25.C, 4 users per round, vs the same
          without MU-MIMO); and ARF / Minstrel + OBSS-PD
          -72 dBm (25.A). Aggregate Wi-Fi throughput, 5th-percentile user,
          Jain over users, collision / failure ratio.
  sr      Same layout (2 STAs per apartment): OBSS-PD level -82 ... -62 dBm
          and per-AP auto vs no spatial reuse, with ARF and with Minstrel.
  coex    TR 38.889 indoor (operator A 3 cells, operator B 3 Wi-Fi APs, 5
          users each, Poisson 300 pkt/s per cell), 5 seeds x 2 s: operator
          B's throughput next to Wi-Fi vs next to NR-U (slots), with ARF,
          Minstrel + 2 spatial streams, and ARF + OBSS-PD -72 (operator A's
          Wi-Fi gets the same features). OBSS-PD only
          ignores Wi-Fi frames of another BSS colour - NR-U frames carry
          no colour - so spatial reuse can't open up the channel next to
          NR-U the way it does next to Wi-Fi.

Each run is one singleRun.py call (results parsed from its Cell Report /
summary lines); runs go in parallel (analysis/parallel.py). CSVs and
figures go to analysis/generated/dense_wifi_*.
"""
import csv
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from analysis.parallel import mean_ci, run_parallel
from analysis.plot_utils import GENERATED_DIR, save_bar_figure, save_line_figure, SERIES_STYLE, WIFI_COLOR, NRU_COLOR

SEEDS = [1, 2, 3, 4, 5]
HE = ["--wifi-phy", "he", "--wifi-preamble-detect"]
RES = ["--layout", "tgax-residential"]
RA, MIN = ["--wifi-rate-adapt"], ["--wifi-rate-adapt", "--wifi-rate-algo", "minstrel"]

LADDER = [
    ("ARF", RA),
    ("Minstrel", MIN),
    ("+ 2 SS", MIN + ["--wifi-spatial-streams", "2"]),
    ("+ OFDMA", MIN + ["--wifi-spatial-streams", "2", "--wifi-ofdma"]),
    ("+ demand RUs", MIN + ["--wifi-spatial-streams", "2", "--wifi-ofdma", "--wifi-ofdma-ru-alloc", "demand"]),
    # MU-MIMO needs RUs of >= 106 tones: 5 users in 20 MHz don't fit in two 2-user groups (then plain OFDMA),
    # so this step serves 4 users per round (two groups of two on the 106-tone RUs)
    ("+ MU-MIMO 2", MIN + ["--wifi-spatial-streams", "2", "--wifi-ofdma", "--wifi-ofdma-ru-alloc", "demand",
                           "--wifi-mu-mimo-users", "2", "--wifi-ofdma-max-users", "4"]),
    ("OFDMA, 4 users/round", MIN + ["--wifi-spatial-streams", "2", "--wifi-ofdma", "--wifi-ofdma-ru-alloc", "demand",
                                    "--wifi-ofdma-max-users", "4"]),
    ("ARF + OBSS-PD", RA + ["--wifi-obss-pd-dbm", "-72"]),
    ("Minstrel + OBSS-PD", MIN + ["--wifi-obss-pd-dbm", "-72"]),
]
SR_LEVELS = [None, -82, -77, -72, -67, -62, "auto"]
COEX_LOAD = ["--wifi-traffic-model", "poisson", "--wifi-arrival-rate-pps", "300",
             "--nru-traffic-model", "poisson", "--nru-arrival-rate-pps", "300", "--nru-cot-model", "slots"]
COEX_FEATURES = [("ARF", RA),
                 ("Minstrel + 2 SS", MIN + ["--wifi-spatial-streams", "2"]),
                 ("ARF + OBSS-PD -72", RA + ["--wifi-obss-pd-dbm", "-72"])]

_WIFI_LINE = re.compile(r"^Wi-Fi: (\d+) cells, ([\d.]+) Mbps, Jain over cells ([\d.]+); (\d+) users: mean ([\d.]+), "
                        r"median ([\d.]+), 5th percentile ([\d.]+) Mbps, Jain over users ([\d.]+)", re.M)
_AP_LINE = re.compile(r"^AP (\d+): Wi-Fi [\d.]+ GHz, \d+ users, throughput ([\d.]+) Mbps", re.M)


def run_cli(args, seed, time_s):
    """One singleRun.py run; the parsed Wi-Fi numbers."""
    cmd = [sys.executable, os.path.join(ROOT, "singleRun.py"), "--seed", str(seed), "-t", str(time_s), "-r", "1",
           "--cell-report"] + list(args)
    out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True).stdout
    m = _WIFI_LINE.search(out)
    if m is None:
        raise RuntimeError("no Wi-Fi summary in output of " + " ".join(cmd) + "\n" + out[-800:])
    pcol = re.search(r"WiFi pcol:=([\d.]+)|PCOLL: ([\d.]+) THR", out)
    aps = {int(a): float(t) for a, t in _AP_LINE.findall(out)}
    return {"tput": float(m.group(2)), "p5": float(m.group(7)), "jain": float(m.group(8)),
            "pcol": float(next(g for g in pcol.groups() if g)) if pcol else float("nan"), "aps": aps}


def _sweep(cases, time_s):
    """cases: [(name, args)] -> {name: [result per seed]}, all runs in parallel."""
    jobs = [dict(args=a, seed=s, time_s=time_s) for _, a in cases for s in SEEDS]
    res = run_parallel(run_cli, jobs)
    return {name: res[i * len(SEEDS):(i + 1) * len(SEEDS)] for i, (name, _) in enumerate(cases)}


def _write(rows, name):
    os.makedirs(GENERATED_DIR, exist_ok=True)
    with open(os.path.join(GENERATED_DIR, name), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _row(name, runs, **extra):
    row = dict(extra, case=name)
    for k in ("tput", "p5", "jain", "pcol"):
        m, ci = mean_ci([r[k] for r in runs])
        row[k], row[k + "_ci"] = round(m, 3), round(ci, 3)
    return row


def study_ladder():
    res = _sweep([(n, HE + RES + ["--layout-users-per-cell", "5"] + a) for n, a in LADDER], 1.0)
    rows = [_row(n, r) for n, r in res.items()]
    for r in rows:
        print(f"{r['case']:20} {r['tput']:7.2f} +- {r['tput_ci']:5.2f} Mbps  5th pct {r['p5']:5.2f}  "
              f"Jain {r['jain']:.3f}  fail {r['pcol']:.3f}", flush=True)
    _write(rows, "dense_wifi_ladder.csv")
    short = {"+ 2 SS": "+ 2 SS",
              "+ OFDMA": "+ OFDMA",
              "+ demand RUs": "+ demand\nRUs",
              "+ MU-MIMO 2": "+ MU-MIMO\n2 users",
              "OFDMA, 4 users/round": "OFDMA,\n4/round",
              "ARF + OBSS-PD": "ARF +\nOBSS-PD",
              "Minstrel + OBSS-PD": "Minstrel +\nOBSS-PD"}
    names = [short.get(r["case"], r["case"]) for r in rows]
    save_bar_figure(names, {"Aggregate (Mbps)": [r["tput"] for r in rows]}, "", "Wi-Fi throughput (Mbps)",
                    "dense_wifi_ladder_tput", figsize=(12.0, 5.5), value_fmt="{:.1f}",
                    bar_colors={"Aggregate (Mbps)": WIFI_COLOR})
    save_bar_figure(names, {"5th percentile user (Mbps)": [r["p5"] for r in rows]}, "",
                    "5th-percentile user (Mbps)", "dense_wifi_ladder_p5", figsize=(12.0, 5.5),
                    bar_colors={"5th percentile user (Mbps)": WIFI_COLOR})


def study_sr():
    cases = []
    for algo, a in (("ARF", RA), ("Minstrel", MIN)):
        for lv in SR_LEVELS:
            sr = [] if lv is None else ["--wifi-obss-pd-dbm", str(lv)]
            cases.append((f"{algo}|{lv}", HE + RES + a + sr))
    res = _sweep(cases, 1.0)
    rows = []
    for name, runs in res.items():
        algo, lv = name.split("|")
        rows.append(_row(name, runs, algo=algo, obss_pd=lv))
        print(f"{algo:8} OBSS-PD {lv:>5}  {rows[-1]['tput']:7.2f} Mbps  5th pct {rows[-1]['p5']:5.2f}  "
              f"Jain {rows[-1]['jain']:.3f}  fail {rows[-1]['pcol']:.3f}", flush=True)
    _write(rows, "dense_wifi_sr.csv")
    levels = [lv for lv in SR_LEVELS if isinstance(lv, int)]
    for metric, ylabel, stem in (("tput", "Wi-Fi throughput (Mbps)", "dense_wifi_sr_tput"),
                                 ("p5", "5th-percentile user (Mbps)", "dense_wifi_sr_p5")):
        series = {}
        for algo, (c, mk) in (("ARF", (WIFI_COLOR, "^")), ("Minstrel", ("#b05a1e", "s"))):
            lab, base = f"{algo}, OBSS-PD", f"{algo}, no SR"
            SERIES_STYLE.setdefault(lab, dict(color=c, marker=mk, linestyle="-"))
            SERIES_STYLE.setdefault(base, dict(color=c, marker="", linestyle="--"))     # flat reference in the same colour
            series[lab] = [next(r[metric] for r in rows if r["algo"] == algo and r["obss_pd"] == str(lv)) for lv in levels]
            series[base] = [next(r[metric] for r in rows if r["algo"] == algo and r["obss_pd"] == "None")] * len(levels)
        save_line_figure(levels, series, "OBSS-PD level (dBm)", ylabel, "", stem)


def study_coex():
    cases = []
    for feat, a in COEX_FEATURES:
        for nb in ("wifi", "nru"):
            cases.append((f"{feat}|{nb}", HE + a + COEX_LOAD + ["--layout", "tr38889-indoor", "--layout-tech", nb]))
    res = _sweep(cases, 2.0)
    rows = []
    for name, runs in res.items():
        feat, nb = name.split("|")
        # operator B = the last 3 APs (after operator A's when it is Wi-Fi)
        b = [sum(t for ap, t in sorted(r["aps"].items())[-3:]) for r in runs]
        m, ci = mean_ci(b)
        rows.append({"features": feat, "neighbor": nb, "op_b_tput": round(m, 3), "op_b_tput_ci": round(ci, 3)})
        print(f"{feat:20} next to {nb:4}: operator B {m:6.2f} +- {ci:4.2f} Mbps", flush=True)
    _write(rows, "dense_wifi_coex.csv")
    feats = [f for f, _ in COEX_FEATURES]
    save_bar_figure(feats,
                    {"Next to Wi-Fi": [next(r["op_b_tput"] for r in rows if r["features"] == f and r["neighbor"] == "wifi") for f in feats],
                     "Next to NR-U": [next(r["op_b_tput"] for r in rows if r["features"] == f and r["neighbor"] == "nru") for f in feats]},
                    "", "Operator B throughput (Mbps)", "dense_wifi_coex", figsize=(10.0, 5.5),
                    bar_colors={"Next to Wi-Fi": WIFI_COLOR, "Next to NR-U": NRU_COLOR})


if __name__ == "__main__":
    which = sys.argv[1:] or ["ladder", "sr", "coex"]
    for w in which:
        print(f"=== {w} ===", flush=True)
        {"ladder": study_ladder, "sr": study_sr, "coex": study_coex}[w]()
# Rashed-Step 25.E-10-20-2026-end
