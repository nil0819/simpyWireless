# Rashed-Step 22.D-10-15-2026-start
"""
Per-cell report for multi-cell runs (Step 22.D, --cell-report).

For every cell (AP / gNB): technology, channel, users, delivered
throughput (downlink + uplink, Mbps); per technology: Jain's index over
the cells' throughputs and over the users' throughputs, and the mean,
median and 5th-percentile ("cell-edge") user throughput. A user's
throughput counts the delivered packets addressed to it (downlink) and
sent by it (uplink); a user with nothing delivered counts as 0. Licensed
NR full-buffer slots count their transport block (packet.tb_bits).
"""
from typing import Any, Dict, List, Tuple

import numpy as np

from common.fairness import TECH_LABELS, jain_index


def compute_cell_report(cells: List[Tuple[str, str, float, List[str], list]], simulation_time_s: float) -> Dict[str, Any]:
    """cells: (cell name, tech, centre frequency Hz, user names, packets)."""
    to_mbps = 8.0 / (simulation_time_s * 1e6)
    out: Dict[str, Any] = {"cells": [], "tech": {}}
    for name, tech, f_hz, users, packets in cells:
        per_user = {u: 0 for u in users}
        seen = set()
        total = 0
        for p in packets:
            if id(p) in seen or p.status != "DELIVERED":
                continue
            seen.add(id(p))
            # Licensed NR full buffer logs one placeholder packet per slot;
            # its delivered amount is the slot's transport block (tb_bits).
            tb = getattr(p, "tb_bits", None)
            b = tb / 8.0 if tb is not None else p.total_bytes()
            total += b
            for end in (p.destination, p.source):
                if end in per_user:
                    per_user[end] += b
                    break
        out["cells"].append({"cell": name, "tech": tech, "f_ghz": f_hz / 1e9, "users": len(users),
                             "throughput_mbps": total * to_mbps,
                             "user_mbps": {u: b * to_mbps for u, b in per_user.items()}})
    for tech in sorted({c["tech"] for c in out["cells"]}):
        cs = [c for c in out["cells"] if c["tech"] == tech]
        cell_thr = [c["throughput_mbps"] for c in cs]
        user_thr = [v for c in cs for v in c["user_mbps"].values()]
        out["tech"][tech] = {
            "cells": len(cs), "users": len(user_thr),
            "throughput_mbps": sum(cell_thr),
            "jain_cells": jain_index(cell_thr),
            "jain_users": jain_index(user_thr) if user_thr else None,
            "user_mean_mbps": float(np.mean(user_thr)) if user_thr else None,
            "user_p50_mbps": float(np.percentile(user_thr, 50)) if user_thr else None,
            "user_p5_mbps": float(np.percentile(user_thr, 5)) if user_thr else None,
        }
    return out


def print_cell_report(r: Dict[str, Any]) -> None:
    print("=== Cell Report ===")
    for c in r["cells"]:
        print(f"{c['cell']}: {TECH_LABELS.get(c['tech'], c['tech'])} {c['f_ghz']:.2f} GHz, "
              f"{c['users']} users, throughput {c['throughput_mbps']:.2f} Mbps")
    for tech, t in r["tech"].items():
        line = (f"{TECH_LABELS.get(tech, tech)}: {t['cells']} cells, {t['throughput_mbps']:.2f} Mbps, "
                f"Jain over cells {t['jain_cells']:.3f}")
        if t["users"]:
            line += (f"; {t['users']} users: mean {t['user_mean_mbps']:.2f}, median {t['user_p50_mbps']:.2f}, "
                     f"5th percentile {t['user_p5_mbps']:.2f} Mbps, Jain over users {t['jain_users']:.3f}")
        print(line)
# Rashed-Step 22.D-10-15-2026-end
