# Rashed-Step 23.C-10-17-2026-start
"""
FTP Model 3 file statistics (Step 23.C, 3GPP TR 36.889 A.1.1).

With TrafficConfig mode "ftp3" every packet carries its file (file_id,
file_packets, file_bytes, file_arrival). A file is complete when all its
packets were delivered; its transfer time runs from its arrival to the
last packet's delivery, and its user-perceived throughput (UPT) is
file_bytes x 8 / transfer time - the metric TR 36.889's replacement test
reports. Files still in flight at the end of the run (or with a dropped
packet) count as incomplete and are left out of the UPT statistics.
"""
from typing import Any, Dict, Iterable

import numpy as np


def compute_file_stats(packets: Iterable) -> Dict[str, Any]:
    files: Dict[str, Dict[str, Any]] = {}
    for p in packets:
        fid = getattr(p, "file_id", None)
        if fid is None:
            continue
        f = files.setdefault(fid, {"n": p.file_packets, "bytes": p.file_bytes, "arrival": p.file_arrival,
                                   "delivered": 0, "last": None, "dropped": False})
        if p.status == "DELIVERED":
            f["delivered"] += 1
            f["last"] = p.delivered_at if f["last"] is None else max(f["last"], p.delivered_at)
        elif p.status == "DROPPED":
            f["dropped"] = True
    done = [f for f in files.values() if not f["dropped"] and f["delivered"] >= f["n"] and f["last"] is not None]
    t_ms = [(f["last"] - f["arrival"]) / 1000.0 for f in done]
    upt = [f["bytes"] * 8 / max(1e-9, (f["last"] - f["arrival"])) for f in done]   # bits/us = Mbps
    out = {"files_seen": len(files), "files_completed": len(done)}
    if done:
        out.update(upt_mean_mbps=float(np.mean(upt)), upt_median_mbps=float(np.median(upt)),
                   upt_p5_mbps=float(np.percentile(upt, 5)), transfer_mean_ms=float(np.mean(t_ms)),
                   transfer_p95_ms=float(np.percentile(t_ms, 95)))
    return out


def print_file_stats(label: str, s: Dict[str, Any]) -> None:
    line = f"{label}: files completed {s['files_completed']} of {s['files_seen']} seen"
    if s["files_completed"]:
        line += (f"; UPT mean {s['upt_mean_mbps']:.2f}, median {s['upt_median_mbps']:.2f}, "
                 f"5th percentile {s['upt_p5_mbps']:.2f} Mbps; transfer mean {s['transfer_mean_ms']:.1f} ms, "
                 f"95th percentile {s['transfer_p95_ms']:.1f} ms")
    print(line)
# Rashed-Step 23.C-10-17-2026-end
