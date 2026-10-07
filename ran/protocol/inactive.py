# Rashed-Step 19.B.3-10-07-2026-start
"""
RRC_INACTIVE with resume (Step 19.B.3; TS 38.331 5.3.8 suspend, 5.3.13
resume), shared by licensed NR and NR-U like rrc.py.

A CONNECTED UE with nothing queued in either direction (and no HARQ
retransmission waiting) for inactivity_timer_us is released to
RRC_INACTIVE: the RAN and the Core keep its context and PDU session, it
is not scheduled. New data brings it back:
  - uplink data (arrives in the UE's buffer): the UE resumes at once;
  - downlink data (arrives in the gNB's buffer for it): the gNB pages it
    (RAN paging); the UE hears the page at its next paging occasion,
    every paging_cycle_us, then resumes.
Resume = random access if the cell runs it, then RRCResumeRequest
(uplink) -> RRCResume (after the gNB's setup processing) ->
RRCResumeComplete (uplink). No Core signaling - the difference from
IDLE, which would need a full setup and service request.

`gnb` must expose env, rrc_uplink_delay(ue), ue_has_pending(ue) and
ue_buffers(ue) (the UE's downlink and uplink buffers).

Simplifications: idleness is checked every check_period_us (a release
can come up to that much late); paging occasions are the same for every
UE; no RNA updates (no mobility between cells yet).
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class InactiveConfig:
    inactivity_timer_us: float = 100_000.0
    paging_cycle_us: float = 320_000.0
    check_period_us: float = 10_000.0

    def __post_init__(self):
        for name in ("inactivity_timer_us", "paging_cycle_us", "check_period_us"):
            if not getattr(self, name) > 0:
                raise ValueError(f"INACTIVE {name} must be > 0 (got {getattr(self, name)})")


def inactivity_manager(gnb: Any, ue: Any, cfg: InactiveConfig, rrc_layer: Any):
    """SimPy process, started when the UE first becomes CONNECTED."""
    from ran.protocol.rrc import RrcState
    env = gnb.env
    ue.rrc_releases = getattr(ue, "rrc_releases", 0)
    ue.rrc_resumes = getattr(ue, "rrc_resumes", 0)
    ue.rrc_resume_latencies_us = getattr(ue, "rrc_resume_latencies_us", [])
    ue.rrc_inactive_us = getattr(ue, "rrc_inactive_us", 0.0)
    trigger = {"event": env.event(), "dl": False}

    def on_data(dl: bool):
        def hook():
            if ue.rrc_state is RrcState.INACTIVE and not trigger["event"].triggered:
                trigger["dl"] = dl
                trigger["event"].succeed()
        return hook

    dl_buf, ul_buf = gnb.ue_buffers(ue)
    for buf, dl in ((dl_buf, True), (ul_buf, False)):
        if buf is None:
            continue
        prev = buf.on_enqueue
        hook = on_data(dl)
        buf.on_enqueue = hook if prev is None else (lambda p=prev, h=hook: (p(), h()))

    last_active = env.now
    while True:
        if ue.rrc_state is not RrcState.CONNECTED:
            # RLF / re-establishment owns the UE right now; or it's gone.
            if ue.rrc_state is RrcState.IDLE:
                return
            last_active = env.now
            yield env.timeout(cfg.check_period_us)
            continue
        # Rashed-Step 19.D.1-10-07-2026-start
        gnb = getattr(ue, "gnb", None) or gnb  # serving cell, after handovers too
        # Rashed-Step 19.D.1-10-07-2026-end
        if gnb.ue_has_pending(ue):
            last_active = env.now
        if env.now - last_active < cfg.inactivity_timer_us:
            yield env.timeout(cfg.check_period_us)
            continue
        # RRCRelease with suspend: CONNECTED -> INACTIVE.
        ue.rrc_state = RrcState.INACTIVE
        ue.rrc_releases += 1
        released_at = env.now
        trigger["event"] = env.event()
        yield trigger["event"]
        woke_at = env.now
        if trigger["dl"]:
            cycle = cfg.paging_cycle_us
            k = int(env.now // cycle) + 1
            yield env.timeout(k * cycle - env.now)
        ue.rrc_state = RrcState.CONNECTING
        rach = getattr(gnb, "rach_cell", None)
        if rach is not None and not (yield from rach.access(ue)):
            ue.rrc_state = RrcState.IDLE
            ue.rrc_failed_at = env.now
            return
        yield from gnb.rrc_uplink_delay(ue)                       # RRCResumeRequest
        yield env.timeout(rrc_layer.setup_processing_delay_us)   # RRCResume
        yield from gnb.rrc_uplink_delay(ue)                       # RRCResumeComplete
        ue.rrc_state = RrcState.CONNECTED
        ue.rrc_resumes += 1
        ue.rrc_resume_latencies_us.append(env.now - woke_at)
        ue.rrc_inactive_us += woke_at - released_at
        last_active = env.now


def compute_inactive_stats(ue_list: List[Any]) -> Dict[str, Any]:
    mon = [ue for ue in ue_list if hasattr(ue, "rrc_releases")]
    lat = [x for ue in mon for x in ue.rrc_resume_latencies_us]
    return {
        "ues": len(mon),
        "releases": sum(ue.rrc_releases for ue in mon),
        "resumes": sum(ue.rrc_resumes for ue in mon),
        "mean_resume_latency_us": (sum(lat) / len(lat)) if lat else None,
        "inactive_us": sum(ue.rrc_inactive_us for ue in mon),
        "inactive_now": sum(1 for ue in mon if ue.rrc_state.name == "INACTIVE"),
    }


def print_inactive_stats(title: str, label: str, s: Dict[str, Any]) -> None:
    print(f"=== {title} ===")
    print(f"{label} RRC releases to INACTIVE: {s['releases']}")
    print(f"{label} RRC resumes: {s['resumes']}")
    print(f"{label} RRC mean resume latency, data -> CONNECTED (us): {s['mean_resume_latency_us']}")
    print(f"{label} time spent INACTIVE (us, completed periods): {s['inactive_us']}")
    print(f"{label} UEs INACTIVE at the end: {s['inactive_now']}")


def inactive_config_from_cli(enabled: bool, timer_ms: Optional[float], paging_ms: Optional[float]) -> Optional[InactiveConfig]:
    if not enabled:
        if timer_ms is not None or paging_ms is not None:
            raise ValueError("--inactivity-timer-ms / --paging-cycle-ms require --rrc-inactive.")
        return None
    kw = {}
    if timer_ms is not None:
        kw["inactivity_timer_us"] = timer_ms * 1000.0
    if paging_ms is not None:
        kw["paging_cycle_us"] = paging_ms * 1000.0
    return InactiveConfig(**kw)
# Rashed-Step 19.B.3-10-07-2026-end
