# Rashed-Step 19.C-10-07-2026-start
"""
5G QoS (Step 19.C): QoS flows identified by their 5QI, with the
standardized characteristics of TS 23.501 Table 5.7.4-1, and the
mapping that ties the simulator's traffic classes to them - and to the
Wi-Fi EDCA access categories - so both technologies are compared on the
same footing.

    traffic class   5QI  type     priority  PDB     PER    Wi-Fi AC
    voice             1  GBR         20     100 ms  1e-2   AC_VO
    video             2  GBR         40     150 ms  1e-3   AC_VI
    best_effort       8  non-GBR     80     300 ms  1e-6   AC_BE
    background        9  non-GBR     90     300 ms  1e-6   AC_BK

5QI 8 and 9 have the same characteristics apart from priority; using
both keeps best effort above background, as AC_BE is above AC_BK.
Lower priority level = served first. GBR bit rates (GFBR/MFBR) are not
enforced - only priority and the delay budget are used.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class FiveQi:
    value: int
    resource_type: str        # "GBR" or "non-GBR"
    priority_level: int
    pdb_ms: float             # packet delay budget
    per: float                # packet error rate
    example: str


FIVE_QI_TABLE: Dict[int, FiveQi] = {
    1: FiveQi(1, "GBR", 20, 100.0, 1e-2, "conversational voice"),
    2: FiveQi(2, "GBR", 40, 150.0, 1e-3, "conversational video"),
    8: FiveQi(8, "non-GBR", 80, 300.0, 1e-6, "TCP-based (premium)"),
    9: FiveQi(9, "non-GBR", 90, 300.0, 1e-6, "TCP-based (default)"),
}

TRAFFIC_CLASS_TO_5QI: Dict[str, int] = {"voice": 1, "video": 2, "best_effort": 8, "background": 9}
FIVE_QI_TO_WIFI_AC: Dict[int, str] = {1: "AC_VO", 2: "AC_VI", 8: "AC_BE", 9: "AC_BK"}
DEFAULT_5QI = 9


def five_qi_for(traffic_class: str) -> int:
    """5QI of a packet's traffic class; unknown labels -> the default bearer."""
    return TRAFFIC_CLASS_TO_5QI.get(traffic_class, DEFAULT_5QI)


def compute_qos_flow_stats(packets: List[Any], queued: Optional[List[Any]] = None,
                           now: Optional[float] = None) -> Dict[int, Dict[str, Any]]:
    """Per-5QI delivery and delay-budget stats. `packets` = finished ones;
    `queued` = still waiting at `now` (end of run) - a starved flow keeps
    its packets queued, so those already older than the delay budget
    count as misses too."""
    from common.packet import _percentile
    queued = queued or []
    out: Dict[int, Dict[str, Any]] = {}
    for q in sorted({five_qi_for(p.traffic_class) for p in list(packets) + queued},
                    key=lambda v: FIVE_QI_TABLE.get(v, FIVE_QI_TABLE[DEFAULT_5QI]).priority_level):
        mine = [p for p in packets if five_qi_for(p.traffic_class) == q]
        ok = [p for p in mine if p.status == "DELIVERED"]
        lat = sorted(p.delivered_at - p.created_at for p in ok)
        pdb_us = FIVE_QI_TABLE.get(q, FIVE_QI_TABLE[DEFAULT_5QI]).pdb_ms * 1000.0
        on_time = sum(1 for x in lat if x <= pdb_us)
        done = len(ok) + sum(1 for p in mine if p.status == "DROPPED")
        waiting = [p for p in queued if five_qi_for(p.traffic_class) == q]
        late_waiting = sum(1 for p in waiting if now is not None and now - p.created_at > pdb_us)
        out[q] = {
            "delivered": len(ok),
            "dropped": done - len(ok),
            "mean_latency_us": (sum(lat) / len(lat)) if lat else None,
            "p95_latency_us": _percentile(lat, 95) if lat else None,
            "pdb_us": pdb_us,
            "queued": len(waiting),
            "queued_past_pdb": late_waiting,
            # Delivered within the delay budget, out of finished packets plus
            # those still queued past it (drops and late ones are misses).
            "within_pdb": (on_time / (done + late_waiting)) if (done + late_waiting) else None,
        }
    return out


def print_qos_flow_stats(title: str, label: str, stats: Dict[int, Dict[str, Any]]) -> None:
    print(f"=== {title} ===")
    for q, s in stats.items():
        fq = FIVE_QI_TABLE.get(q)
        name = f"5QI {q}" + (f" ({fq.resource_type}, priority {fq.priority_level}, {FIVE_QI_TO_WIFI_AC[q]})" if fq else "")
        print(f"{label} {name}: delivered {s['delivered']}, dropped {s['dropped']}, "
              f"mean latency (us) {s['mean_latency_us']}, p95 (us) {s['p95_latency_us']}, "
              f"queued at end {s['queued']} ({s['queued_past_pdb']} past PDB), "
              f"within PDB {s['pdb_us'] / 1000:.0f} ms: {s['within_pdb']}")
# Rashed-Step 19.C-10-07-2026-end
