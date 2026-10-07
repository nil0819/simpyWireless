# Rashed-Step 19.D.1-10-07-2026-start
"""
Measurements and handover between gNBs (Step 19.D.1; TS 38.331 5.5
measurements / event A3, TS 38.300 9.2.3 Xn handover). Licensed NR
(several gNBs per run); NR-U handover waits for the unified
orchestrator (19.E).

Measurement (every meas_period_us while CONNECTED): RSRP of the serving
cell and every neighbor (gnb.rsrp_dbm(ue)), L3-filtered
F = (1 - a) F + a M with a = 1 / 2^(k/4) (TS 38.331 5.5.3.2).
Event A3: a neighbor's F exceeds the serving cell's by a3_offset_db +
hysteresis_db continuously for ttt_us -> measurement report.
Handover:
  1. MeasurementReport on the uplink (serving gNB's RRC uplink path);
  2. Xn handover preparation (prep_us);
  3. HO command (RRCReconfiguration with sync): the UE stops being
     scheduled; once the source's current slot is over, its context
     moves - the downlink buffer is forwarded to the target, HARQ is
     reset (RLC AM / PDCP recover what was in flight);
  4. HO execution (exec_us: the UE retunes and syncs to the target);
  5. random access to the target when the target runs it;
  6. RRCReconfigurationComplete on the target's uplink -> CONNECTED.
The interruption is measured from 3 to 6. A handover back to the cell
the UE left less than ping_pong_us earlier counts as a ping-pong.
Random access failing at the target is a handover failure: IDLE.

`gnb` must expose env, name, neighbors (list of gNBs), slot_us,
rsrp_dbm(ue), rrc_uplink_delay(ue), release_ue_context(ue) -> ctx and
admit_ue_context(ue, ctx).
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class HandoverConfig:
    meas_period_us: float = 40_000.0
    l3_filter_k: int = 4
    a3_offset_db: float = 3.0
    hysteresis_db: float = 1.0
    ttt_us: float = 160_000.0
    prep_us: float = 10_000.0
    exec_us: float = 20_000.0
    ping_pong_us: float = 1_000_000.0

    def __post_init__(self):
        if not self.meas_period_us > 0:
            raise ValueError(f"handover meas_period_us must be > 0 (got {self.meas_period_us})")
        for name in ("ttt_us", "prep_us", "exec_us", "ping_pong_us", "hysteresis_db"):
            if getattr(self, name) < 0:
                raise ValueError(f"handover {name} must be >= 0 (got {getattr(self, name)})")
        if self.l3_filter_k < 0:
            raise ValueError("handover l3_filter_k must be >= 0")


def move_ue(source: Any, target: Any, ue: Any) -> None:
    """Hand the UE's context from source to target (lists, back-references,
    forwarded downlink buffer)."""
    ctx = source.release_ue_context(ue)
    target.admit_ue_context(ue, ctx)


def measurement_process(ue: Any, cfg: HandoverConfig):
    """SimPy process, started when the UE first becomes CONNECTED."""
    from ran.protocol.rrc import RrcState
    env = ue.gnb.env
    a = 1.0 / (2.0 ** (cfg.l3_filter_k / 4.0))
    filt: Dict[str, float] = {}
    entered = None
    ue.ho_reports = getattr(ue, "ho_reports", 0)
    ue.handovers = getattr(ue, "handovers", 0)
    ue.ho_failures = getattr(ue, "ho_failures", 0)
    ue.ho_ping_pongs = getattr(ue, "ho_ping_pongs", 0)
    ue.ho_interruptions_us = getattr(ue, "ho_interruptions_us", [])
    while True:
        yield env.timeout(cfg.meas_period_us)
        if ue.rrc_state is RrcState.IDLE:
            return
        if ue.rrc_state is not RrcState.CONNECTED:
            entered = None
            continue
        serving = ue.gnb
        cells = [serving] + list(getattr(serving, "neighbors", []))
        for c in cells:
            m = c.rsrp_dbm(ue)
            filt[c.name] = m if c.name not in filt else (1 - a) * filt[c.name] + a * m
        neighbors = [c for c in cells[1:]]
        if not neighbors:
            continue
        best = max(neighbors, key=lambda c: filt[c.name])
        if filt[best.name] > filt[serving.name] + cfg.a3_offset_db + cfg.hysteresis_db:
            if entered is None or entered[0] is not best:
                entered = (best, env.now)
            if env.now - entered[1] >= cfg.ttt_us:
                entered = None
                yield from handover(serving, best, ue, cfg)
                if ue.rrc_state is RrcState.IDLE:
                    return
        else:
            entered = None


def handover(source: Any, target: Any, ue: Any, cfg: HandoverConfig):
    from ran.protocol.rrc import RrcState
    env = source.env
    ue.ho_reports += 1
    yield from source.rrc_uplink_delay(ue)       # MeasurementReport
    yield env.timeout(cfg.prep_us)               # Xn HO request / ack
    # HO command: the source stops scheduling the UE, finishes its slot.
    ue.rrc_state = RrcState.CONNECTING
    started = env.now
    yield env.timeout(getattr(source, "slot_us", 0.0))
    move_ue(source, target, ue)
    yield env.timeout(cfg.exec_us)
    rach = getattr(target, "rach_cell", None)
    if rach is not None and not (yield from rach.access(ue)):
        ue.ho_failures += 1
        ue.rrc_state = RrcState.IDLE
        ue.rrc_failed_at = env.now
        return
    yield from target.rrc_uplink_delay(ue)       # RRCReconfigurationComplete
    ue.rrc_state = RrcState.CONNECTED
    ue.handovers += 1
    ue.ho_interruptions_us.append(env.now - started)
    last = getattr(ue, "_ho_last", None)
    if last is not None and last[0] is target and env.now - last[1] < cfg.ping_pong_us:
        ue.ho_ping_pongs += 1
    ue._ho_last = (source, env.now)


def compute_handover_stats(ue_list: List[Any]) -> Dict[str, Any]:
    mon = [ue for ue in ue_list if hasattr(ue, "handovers")]
    ints = [x for ue in mon for x in ue.ho_interruptions_us]
    return {
        "ues": len(mon),
        "reports": sum(ue.ho_reports for ue in mon),
        "handovers": sum(ue.handovers for ue in mon),
        "failures": sum(ue.ho_failures for ue in mon),
        "ping_pongs": sum(ue.ho_ping_pongs for ue in mon),
        "mean_interruption_us": (sum(ints) / len(ints)) if ints else None,
    }


def print_handover_stats(title: str, label: str, s: Dict[str, Any]) -> None:
    print(f"=== {title} ===")
    print(f"{label} measurement reports (A3): {s['reports']}")
    print(f"{label} handovers: {s['handovers']}")
    print(f"{label} handover failures: {s['failures']}")
    print(f"{label} ping-pong handovers: {s['ping_pongs']}")
    print(f"{label} mean handover interruption (us): {s['mean_interruption_us']}")


def handover_config_from_cli(enabled: bool, a3_offset_db: Optional[float], ttt_ms: Optional[float]) -> Optional[HandoverConfig]:
    if not enabled:
        if a3_offset_db is not None or ttt_ms is not None:
            raise ValueError("--a3-offset-db / --ttt-ms require --handover.")
        return None
    kw = {}
    if a3_offset_db is not None:
        kw["a3_offset_db"] = a3_offset_db
    if ttt_ms is not None:
        kw["ttt_us"] = ttt_ms * 1000.0
    return HandoverConfig(**kw)
# Rashed-Step 19.D.1-10-07-2026-end
