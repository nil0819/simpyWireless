# Rashed-Step 19.B.2-10-07-2026-start
"""
Radio link monitoring, radio link failure (RLF) and RRC re-establishment
(Step 19.B.2; TS 38.331 5.3.10 / 5.3.7, TS 38.133 8.1), shared by
licensed NR and NR-U like rrc.py.

Once a UE is RRC CONNECTED, every period_us it measures its downlink
SINR from the serving gNB (gnb.dl_sinr_estimate(ue)). Out-of-sync is
judged on the mean over the last eval_out_us (200 ms), in-sync over the
last eval_in_us (100 ms):
  - n310 out-of-sync indications in a row (mean < qout_db) start T310;
  - n311 in-sync indications in a row (mean >= qin_db) stop it again;
  - T310 expiring is a radio link failure: the UE is no longer
    scheduled (state CONNECTING) and starts re-establishment.
Re-establishment: for up to t311_us the UE looks for a usable cell (SINR
>= qin_db, checked every period_us; the serving cell - no other cells
until handover in 19.D). Once found: random access if the cell runs it,
then RRCReestablishmentRequest (uplink) -> RRCReestablishment (after
the gNB's setup processing) -> RRCReestablishmentComplete (uplink),
and the UE is CONNECTED again (no Core signaling - its context and PDU
session are kept). T311 expiring, or random access failing, sends the
UE to IDLE and monitoring stops.

Simplifications: SINR measured on a probe of the gNB's downlink, not on
SSB/CSI-RS; Qout/Qin as SINR thresholds (the standard maps them to a
hypothetical PDCCH BLER of 10% / 2%); no beam failure recovery.
"""
import math
from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class RlmConfig:
    period_us: float = 10_000.0
    qout_db: float = -8.0
    qin_db: float = -6.0
    eval_out_us: float = 200_000.0
    eval_in_us: float = 100_000.0
    n310: int = 1
    n311: int = 1
    t310_us: float = 1_000_000.0
    t311_us: float = 1_000_000.0

    def __post_init__(self):
        if not self.period_us > 0:
            raise ValueError(f"RLM period_us must be > 0 (got {self.period_us})")
        if self.n310 < 1 or self.n311 < 1:
            raise ValueError("RLM n310 / n311 must be >= 1")
        if self.t310_us < 0 or self.t311_us < 0:
            raise ValueError("RLM t310_us / t311_us must be >= 0")
        if self.qin_db < self.qout_db:
            raise ValueError(f"RLM qin_db ({self.qin_db}) must be >= qout_db ({self.qout_db})")


def _mean_db(samples, since: float) -> float:
    vals = [v for t, v in samples if t > since]
    if not vals:
        return -math.inf
    m = sum(vals) / len(vals)
    return 10.0 * math.log10(m) if m > 0 else -math.inf


def radio_link_monitor(gnb: Any, ue: Any, cfg: RlmConfig, rrc_layer: Any):
    """SimPy process, started when the UE becomes CONNECTED."""
    from ran.protocol.rrc import RrcState
    env = gnb.env
    ue.rlm_t310_starts = getattr(ue, "rlm_t310_starts", 0)
    ue.rlm_recoveries = getattr(ue, "rlm_recoveries", 0)
    ue.rlf_count = getattr(ue, "rlf_count", 0)
    ue.reestablishments = getattr(ue, "reestablishments", 0)
    ue.rlm_outage_us = getattr(ue, "rlm_outage_us", 0.0)
    samples = deque()
    oos = ins = 0
    t310_started = None
    keep_us = max(cfg.eval_out_us, cfg.eval_in_us)
    while True:
        yield env.timeout(cfg.period_us)
        now = env.now
        # Rashed-Step 19.B.3-10-07-2026-start
        # Radio link monitoring is a CONNECTED-state procedure: nothing
        # while the UE is INACTIVE (19.B.3) or resuming.
        if ue.rrc_state is not RrcState.CONNECTED:
            if ue.rrc_state is RrcState.IDLE:
                return
            samples.clear()
            oos = ins = 0
            t310_started = None
            continue
        # Rashed-Step 19.B.3-10-07-2026-end
        # Rashed-Step 19.D.1-10-07-2026-start
        gnb = getattr(ue, "gnb", None) or gnb  # the serving cell, after handovers too
        # Rashed-Step 19.D.1-10-07-2026-end
        sinr_db = gnb.dl_sinr_estimate(ue)
        samples.append((now, 10.0 ** (sinr_db / 10.0)))
        while samples and samples[0][0] <= now - keep_us:
            samples.popleft()
        if t310_started is None:
            oos = oos + 1 if _mean_db(samples, now - cfg.eval_out_us) < cfg.qout_db else 0
            if oos >= cfg.n310:
                t310_started = now
                ins = 0
                ue.rlm_t310_starts += 1
            continue
        ins = ins + 1 if _mean_db(samples, now - cfg.eval_in_us) >= cfg.qin_db else 0
        if ins >= cfg.n311:
            t310_started = None
            oos = 0
            ue.rlm_recoveries += 1
            continue
        if now - t310_started < cfg.t310_us:
            continue
        # Radio link failure.
        ue.rlf_count += 1
        ue.rlf_at = now
        ue.rrc_state = RrcState.CONNECTING
        ok = yield from reestablish(gnb, ue, cfg, rrc_layer)
        ue.rlm_outage_us += env.now - now
        if not ok:
            ue.rrc_state = RrcState.IDLE
            ue.rlf_to_idle_at = env.now
            return
        ue.reestablishments += 1
        ue.rrc_state = RrcState.CONNECTED
        samples.clear()
        oos = ins = 0
        t310_started = None


def reestablish(gnb: Any, ue: Any, cfg: RlmConfig, rrc_layer: Any):
    """Generator -> True once re-established, False if T311 expires or
    random access fails."""
    env = gnb.env
    deadline = env.now + cfg.t311_us
    # Rashed-Step 19.D.1-10-07-2026-start
    # Cell selection: the best of the serving cell and its neighbors
    # (19.D.1); re-establishing at another cell moves the UE's context.
    def best():
        cells = [gnb] + list(getattr(gnb, "neighbors", []))
        return max(cells, key=lambda c: c.dl_sinr_estimate(ue))
    cell = best()
    while cell.dl_sinr_estimate(ue) < cfg.qin_db:
        if env.now + cfg.period_us > deadline:
            return False
        yield env.timeout(cfg.period_us)
        cell = best()
    if cell is not gnb:
        from ran.protocol.handover import move_ue
        move_ue(gnb, cell, ue)
        ue.reestablished_elsewhere = getattr(ue, "reestablished_elsewhere", 0) + 1
        gnb = cell
    # Rashed-Step 19.D.1-10-07-2026-end
    rach = getattr(gnb, "rach_cell", None)
    if rach is not None and not (yield from rach.access(ue)):
        return False
    yield from gnb.rrc_uplink_delay(ue)               # RRCReestablishmentRequest
    yield env.timeout(rrc_layer.setup_processing_delay_us)  # RRCReestablishment
    yield from gnb.rrc_uplink_delay(ue)               # RRCReestablishmentComplete
    # Rashed-Step 19.B.4-10-07-2026-start
    # Then RRCReconfiguration resumes the data radio bearers (19.B.4).
    if getattr(gnb, "rrc_reconfig_us", None) is not None:
        from ran.protocol.rrc import rrc_reconfiguration
        yield from rrc_reconfiguration(gnb, ue)
    # Rashed-Step 19.B.4-10-07-2026-end
    return True


def compute_rlf_stats(ue_list: List[Any]) -> Dict[str, Any]:
    mon = [ue for ue in ue_list if hasattr(ue, "rlf_count")]
    return {
        "monitored": len(mon),
        "t310_starts": sum(ue.rlm_t310_starts for ue in mon),
        "recovered_before_rlf": sum(ue.rlm_recoveries for ue in mon),
        "rlf": sum(ue.rlf_count for ue in mon),
        "reestablished": sum(ue.reestablishments for ue in mon),
        "to_idle": sum(1 for ue in mon if getattr(ue, "rlf_to_idle_at", None) is not None),
        "outage_us": sum(ue.rlm_outage_us for ue in mon),
    }


def print_rlf_stats(title: str, label: str, s: Dict[str, Any]) -> None:
    print(f"=== {title} ===")
    print(f"{label} RLM UEs monitored: {s['monitored']}")
    print(f"{label} RLM T310 started: {s['t310_starts']} (recovered before failure: {s['recovered_before_rlf']})")
    print(f"{label} radio link failures: {s['rlf']}")
    print(f"{label} RRC re-establishments: {s['reestablished']}")
    print(f"{label} UEs dropped to IDLE after RLF: {s['to_idle']}")
    print(f"{label} time spent re-establishing (us): {s['outage_us']}")


def rlm_config_from_cli(enabled: bool, t310_ms: Optional[float], t311_ms: Optional[float]) -> Optional[RlmConfig]:
    if not enabled:
        if t310_ms is not None or t311_ms is not None:
            raise ValueError("--t310-ms / --t311-ms require --rlm.")
        return None
    kw = {}
    if t310_ms is not None:
        kw["t310_us"] = t310_ms * 1000.0
    if t311_ms is not None:
        kw["t311_us"] = t311_ms * 1000.0
    return RlmConfig(**kw)
# Rashed-Step 19.B.2-10-07-2026-end
