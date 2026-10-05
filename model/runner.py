# Rashed-Step pre_11.C-08-13-2026-start
"""
Runs a real singleRun.py scenario in-process and parses its printed
stats back into a dict, so model/compare.py always checks the analytical
models against an ACTUAL simulator run rather than a hand-copied number.

WHY IN-PROCESS INSTEAD OF A SUBPROCESS: singleRun.py's per-event log()
calls (common/common.py) write one line to log/*.log for every single
backoff/gap/transmission event - fine for a short run, but this is what
made a 16,000s scenario take 3+ hours of real wall-clock time earlier in
this project (see Project details/Step pre_11.txt). run_scenario() below
disables the logging module's output BEFORE exec'ing singleRun.py's own
top-level code (logging.disable(logging.CRITICAL) - a process-wide
suppression that make every log() call a cheap no-op instead of a disk
write), which gave a measured 14.6x speedup with byte-identical results
in this session's own testing. This is exactly the same technique used
ad hoc throughout this chat session's convergence/DTMC verification work,
now formalized here.

NOTE: logging.disable() is process-wide and NOT undone by this function
(matching how it was used throughout this session) - if a caller needs
normal per-event logging again in the same Python process afterward, call
logging.disable(logging.NOTSET) themselves.
"""
import contextlib
import io
import logging
import os
import re
import sys
from typing import Dict, List, Optional


_SINGLE_RUN_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "singleRun.py")

_PATTERNS = {
    "wifi_occ": r"Wifi occupancy \(Normalized\): ([\d.]+)",
    "gnb_occ": r"Gnb occupancy \(Normalized\): ([\d.]+)",
    "wifi_eff": r"Wifi efficieny \(Normalized\): ([\d.]+)",
    "gnb_eff": r"Gnb efficieny \(Normalized\): ([\d.]+)",
    "all_occ": r"All occupancy: ([\d.]+)",
    "all_eff": r"All efficieny: ([\d.]+)",
    "fairness": r"fairness: ([\d.]+)",
    "joint": r"joint: ([\d.]+)",
    # Rashed-Step 14.A-08-28-2026-start
    # Matches simulation.py's new per-technology throughput/delay lines
    # (see that file's Step 14.A block) - avg_latency_us can print as
    # "None" when a technology delivered zero packets, so these patterns
    # accept either a float or the literal word None; _post-process below
    # converts "None" text to a real None instead of leaving it as a
    # string (every other key in this dict is float-or-None already).
    "wifi_throughput_mbps": r"Wifi packet throughput \(Mbps\): ([\d.]+)",
    "wifi_avg_latency_us": r"Wifi packet avg latency \(us\): ([\d.]+|None)",
    "nru_throughput_mbps": r"NRU packet throughput \(Mbps\): ([\d.]+)",
    "nru_avg_latency_us": r"NRU packet avg latency \(us\): ([\d.]+|None)",
    # Rashed-Step 14.A-08-28-2026-end
    # Rashed-Step 17.G-10-05-2026-start
    # NR-U uplink block (17.G part 1, only printed with
    # --nru-ue-uplink-enabled) and the NR-U RRC block (15.G, only with
    # --nru-rrc-enabled) - None when the block isn't in the output.
    "nru_ul_throughput_mbps": r"NRU uplink packet throughput \(Mbps\): ([\d.]+)",
    "nru_ul_delivered": r"NRU uplink packets delivered: (\d+)",
    "nru_ul_failed_attempts": r"NRU uplink attempts ok/failed: \d+/(\d+)",
    "nru_rrc_latency_us": r"NRU RRC mean connection setup latency \(us\): ([\d.]+|None)",
    # Rashed-Step 17.G-10-05-2026-end
}
_SUCC_FAIL_WIFI = r"succ WiFi: (\d+) fail WiFi: (\d+)"
_SUCC_FAIL_NRU = r"succ NRU: (\d+) fail NRU: (\d+)"
_PCOLL_WIFI = r"N_stations:=\d+\s+CW_MIN = \d+ CW_MAX = \d+\s+PCOLL: ([\d.]+)"
_PCOLL_GNB = r"N_gnbs=\d+\s+CW_MIN = \d+ CW_MAX = \d+\s+PCOLL: ([\d.]+)"


def run_scenario(argv: List[str], suppress_logging: bool = True) -> Dict[str, Optional[float]]:
    """
    Runs singleRun.py's CLI (as if invoked `python singleRun.py <argv...>`)
    in-process and returns a dict of every stat this module knows how to
    parse from its stdout. Values not found in the output are None.

    argv: list of CLI arguments, e.g.
      ["--ap-number", "1", "--gnb-number", "1", "-t", "30", "--seed", "1", ...]
      (do NOT include "singleRun.py" itself - added automatically).

    Only supports -r/--runs 1 (a single run) - if you pass a larger
    --runs, only the LAST run's printed block is parsed (matches how the
    regexes above just find the last match in the whole captured output).
    """
    if suppress_logging:
        logging.disable(logging.CRITICAL)

    with open(_SINGLE_RUN_PATH) as f:
        script_src = f.read()

    old_argv = sys.argv
    old_path0 = sys.path[0] if sys.path else None
    repo_dir = os.path.dirname(_SINGLE_RUN_PATH)
    old_cwd = os.getcwd()
    try:
        os.chdir(repo_dir)
        if repo_dir not in sys.path:
            sys.path.insert(0, repo_dir)
        sys.argv = ["singleRun.py"] + list(argv)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                exec(compile(script_src, "singleRun.py", "exec"), {"__name__": "__main__"})
            except SystemExit:
                pass
        output = buf.getvalue()
    finally:
        sys.argv = old_argv
        os.chdir(old_cwd)

    result: Dict[str, Optional[float]] = {}
    for key, pattern in _PATTERNS.items():
        matches = re.findall(pattern, output)
        # Rashed-Step 14.A-08-28-2026-start
        # wifi_avg_latency_us/nru_avg_latency_us can legitimately match the
        # literal text "None" (a technology delivered zero packets this
        # run - see compute_packet_stats()'s own avg_latency_us=None case).
        # Every other existing key's pattern only ever matches digits, so
        # this check is a no-op for them.
        if matches and matches[-1] == "None":
            result[key] = None
        # Rashed-Step 14.A-08-28-2026-end
        else:
            result[key] = float(matches[-1]) if matches else None

    m = re.findall(_SUCC_FAIL_WIFI, output)
    if m:
        result["wifi_succ"], result["wifi_fail"] = int(m[-1][0]), int(m[-1][1])
    else:
        result["wifi_succ"] = result["wifi_fail"] = None

    m = re.findall(_SUCC_FAIL_NRU, output)
    if m:
        result["nru_succ"], result["nru_fail"] = int(m[-1][0]), int(m[-1][1])
    else:
        result["nru_succ"] = result["nru_fail"] = None

    m = re.findall(_PCOLL_WIFI, output)
    result["pcoll_wifi"] = float(m[-1]) if m else None
    m = re.findall(_PCOLL_GNB, output)
    result["pcoll_gnb"] = float(m[-1]) if m else None

    result["_raw_stdout"] = output
    return result


if __name__ == "__main__":
    # Smoke test / usage example: reproduces one of this session's runs.
    stats = run_scenario([
        "--ap-number", "1", "--gnb-number", "1", "-t", "10", "-r", "1", "--seed", "1",
        "--wifi-traffic-model", "saturated", "--nru-traffic-model", "saturated",
        "--area-w", "20", "--area-h", "20", "--ap-pos", "0,0", "--gnb-pos", "10,0",
        "--sta-radius", "3", "--ue-radius", "3",
    ])
    for k, v in stats.items():
        if k != "_raw_stdout":
            print(f"{k}: {v}")
# Rashed-Step pre_11.C-08-13-2026-end
