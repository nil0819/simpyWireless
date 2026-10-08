# Rashed-Step pre_20.A-10-08-2026-start
"""
Coexistence fairness metrics (Step pre_20.A, the LAA fairness study).

Per technology on the shared channel:
  - airtime share: time its transmissions occupied, failed ones included,
    over the run (a technology that transmits into collisions still
    holds the channel), and the share of that airtime that succeeded;
  - transmissions and their failure ratio (collisions / interference);
  - delivered throughput and mean packet latency.
Jain's fairness index over the airtime shares of the technologies
present: (sum x)^2 / (n * sum x^2) - 1.0 when equal, 1/n when one takes
everything.

These describe one run. The study's verdict uses the 3GPP replacement
test (TR 38.889 / TR 36.889): see analysis/laa_fairness.py.
"""
from typing import Any, Dict, Tuple

TECH_LABELS = {"WiFi": "Wi-Fi", "NRU": "NR-U", "NR": "licensed NR"}


def jain_index(values) -> float:
    vals = [v for v in values]
    if not vals or sum(vals) == 0:
        return 1.0
    return (sum(vals) ** 2) / (len(vals) * sum(v * v for v in vals))


def compute_fairness(channel: Any, simulation_time_s: float,
                     per_tech: Dict[str, Tuple[float, dict]]) -> Dict[str, Any]:
    """per_tech: {tech: (throughput_mbps, packet_stats)} for the
    technologies to compare (Wi-Fi and NR-U on the shared band)."""
    t_us = simulation_time_s * 1e6
    out: Dict[str, Any] = {"tech": {}}
    for tech, (thr, ps) in per_tech.items():
        air = channel.tx_airtime_total_us.get(tech, 0.0)
        n = channel.tx_count.get(tech, 0)
        failed = channel.tx_failed.get(tech, 0)
        ok_air = {"WiFi": sum(channel.airtime_data.values()),
                  "NRU": sum(channel.airtime_data_NR.values())}.get(tech, 0.0)
        out["tech"][tech] = {
            "airtime_share": air / t_us if t_us else 0.0,
            "successful_airtime_share": ok_air / t_us if t_us else 0.0,
            "transmissions": n,
            "failed": failed,
            "failure_ratio": (failed / n) if n else 0.0,
            "throughput_mbps": thr,
            "avg_latency_us": ps.get("avg_latency_us"),
        }
    present = [v["airtime_share"] for v in out["tech"].values() if v["transmissions"] > 0]
    out["jain_airtime"] = jain_index(present) if len(present) > 1 else None
    out["idle_share"] = max(0.0, 1.0 - sum(v["airtime_share"] for v in out["tech"].values()))
    return out


def print_fairness(f: Dict[str, Any]) -> None:
    print("=== Coexistence Fairness ===")
    for tech, v in f["tech"].items():
        lbl = TECH_LABELS.get(tech, tech)
        print(f"{lbl} airtime share (failed included): {v['airtime_share']}")
        print(f"{lbl} successful airtime share: {v['successful_airtime_share']}")
        print(f"{lbl} transmissions: {v['transmissions']} (failed {v['failed']}, ratio {v['failure_ratio']})")
        print(f"{lbl} throughput (Mbps): {v['throughput_mbps']}, avg latency (us): {v['avg_latency_us']}")
    print(f"Channel idle (or overlapping) share: {f['idle_share']}")
    print(f"Jain's index over airtime shares: {f['jain_airtime']}")
# Rashed-Step pre_20.A-10-08-2026-end
