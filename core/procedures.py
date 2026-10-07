# Rashed-Step 16.C-10-02-2026-start
"""
Step 16.C: 5G Core procedures as simpy sub-processes - starting with
NAS Registration (Project details/Step 16.txt). PDU session
establishment (16.D) chains onto the end of the same per-UE process.

Same split as ran/protocol/rrc.py: these generators own the TIMING and
call core/network.py's instantaneous state methods (Amf.register(),
...) at the right simulated instant. Technology-agnostic: works for
nru.ue.NrUE and nr.ue.NrUeLicensed alike, reading only ue.name /
ue.rrc_state and gnb.name / gnb.env.

FLOW (per UE, started by CoreNetwork.start_ue(gnb, ue)):
  1. Wait for RRC CONNECTED. A UE that never opted into RRC has no
     rrc_state and counts as already connected - the same
     getattr(ue, "rrc_state", RrcState.CONNECTED) contract Step 15.G's
     scheduler gating uses.
  2. Registration Request -> (core.config.registration_delay_us) ->
     Registration Accept: AMF records the UE and its serving gNB, and
     ue.reg_state becomes REGISTERED.

SCOPE (first cut, Step 16.txt open decision 3): always succeeds after
the configured delay - no reject, no retry, no T3510-style timer. The
delay is one lumped value (measured end to end on a real testbed, see
core/network.py's TIMING DEFAULTS), not a per-message NAS/NGAP model.

Backward-compat contract (same as rrc_state's): a UE that was never
passed to start_ue() has NO reg_state attribute at all. Code that gates
on registration must use
`getattr(ue, "reg_state", RegistrationState.REGISTERED)`.
"""
from typing import Any, Dict, List

from ran.protocol.rrc import RrcState
from core.network import RegistrationState
# Rashed-Step 16.D-10-02-2026-start
from core.network import PduSessionState
# Rashed-Step 16.D-10-02-2026-end


def wait_rrc_connected(ue: Any):
    """Generator - returns as soon as the UE's RRC state is CONNECTED
    (immediately for a UE without RRC). Reuses the _rrc_connected_event
    hook RrcLayer.attach() already fires (Step 15.G); NrUE creates that
    event itself, NrUeLicensed doesn't, so create it here when missing.
    attach() looks it up only when it completes, so an event created
    any time before that is still fired."""
    if getattr(ue, "rrc_state", RrcState.CONNECTED) is RrcState.CONNECTED:
        return
    event = getattr(ue, "_rrc_connected_event", None)
    if event is None:
        event = ue.env.event() if getattr(ue, "env", None) is not None else None
    if event is None:
        raise ValueError(f"{ue.name}: has rrc_state but no env to wait on.")
    ue._rrc_connected_event = event
    yield event


def registration(core: Any, gnb: Any, ue: Any):
    """Generator - NAS Registration for one UE that is already RRC
    CONNECTED. Sets reg_requested_at / registered_at timestamps."""
    env = core.env
    ue.reg_requested_at = env.now
    # Rashed-Step 19.D.2-10-07-2026-start
    # Rejects + retries and AMF capacity (19.D.2); with the defaults this
    # is one plain wait, as before. Returns False when the UE gives up.
    attempts = 0
    while True:
        attempts += 1
        yield from _core_procedure(core, getattr(core, "amf_slots", None),
                                   core.config.registration_delay_us, ue, "amf_wait_us")
        if core.config.registration_reject_prob > 0 and core.rng.random() < core.config.registration_reject_prob:
            ue.reg_rejects = getattr(ue, "reg_rejects", 0) + 1
            if attempts >= core.config.max_attempts:
                ue.reg_failed_at = env.now
                return False
            yield env.timeout(core.config.retry_us)
            continue
        break
    # Rashed-Step 19.D.2-10-07-2026-end
    core.amf.register(ue.name, gnb.name)
    ue.reg_state = RegistrationState.REGISTERED
    ue.registered_at = env.now
    # Rashed-Step 19.D.2-10-07-2026-start
    return True
    # Rashed-Step 19.D.2-10-07-2026-end


# Rashed-Step 16.C-10-02-2026-end


# Rashed-Step 16.D-10-02-2026-start
def pdu_session_establishment(core: Any, ue: Any):
    """Generator - PDU Session Establishment for one REGISTERED UE.
    Request: the SMF creates a PENDING session and picks its UPF.
    Accept (core.config.pdu_session_delay_us later, 125ms default): the
    session becomes ACTIVE and the UPF anchors the UE, so
    core.user_plane_allows(ue.name) turns True from this instant.
    ue.pdu_session points at the SMF's own PduSession object (its
    requested_at / activated_at are the timestamps)."""
    env = core.env
    ue.pdu_session = core.smf.request_session(ue.name, now=env.now)
    # Rashed-Step 19.D.2-10-07-2026-start
    attempts = 0
    while True:
        attempts += 1
        yield from _core_procedure(core, getattr(core, "smf_slots", None),
                                   core.config.pdu_session_delay_us, ue, "smf_wait_us")
        if core.config.pdu_reject_prob > 0 and core.rng.random() < core.config.pdu_reject_prob:
            ue.pdu_rejects = getattr(ue, "pdu_rejects", 0) + 1
            core.smf.release_session(ue.name)
            if attempts >= core.config.max_attempts:
                ue.pdu_failed_at = env.now
                return
            yield env.timeout(core.config.retry_us)
            first = ue.pdu_session.requested_at
            ue.pdu_session = core.smf.request_session(ue.name, now=env.now)
            ue.pdu_session.requested_at = first  # latency counts from the first request
            continue
        break
    # Rashed-Step 19.D.2-10-07-2026-end
    # Rashed-Step 19.B.4-10-07-2026-start
    # With RRC reconfiguration on (the serving gNB's rrc_reconfig_us), the
    # gNB first sets up the UE's data radio bearer - RRCReconfiguration,
    # carrying the NAS accept, and its Complete - and only then does
    # the user plane open. ue.gnb: the back-reference every gNB sets.
    gnb = getattr(ue, "gnb", None)
    if gnb is not None and getattr(gnb, "rrc_reconfig_us", None) is not None:
        from ran.protocol.rrc import rrc_reconfiguration
        yield from rrc_reconfiguration(gnb, ue)
    # Rashed-Step 19.B.4-10-07-2026-end
    core.smf.activate_session(ue.name, now=env.now)
    # Rashed-Step 16.E-10-02-2026-start
    # Release anything waiting on the user plane (NR-U's uplink loop) on
    # the same tick the UPF opens. getattr: a UE driven through this
    # function without start_ue() simply has no event.
    event = getattr(ue, "_user_plane_event", None)
    if event is not None and not event.triggered:
        event.succeed()
    # Rashed-Step 16.E-10-02-2026-end
# Rashed-Step 16.D-10-02-2026-end


# Rashed-Step 16.C-10-02-2026-start
# Rashed-Step 19.D.2-10-07-2026-start
def _core_procedure(core: Any, slots: Any, delay_us: float, ue: Any, wait_attr: str):
    """One Core procedure's delay. With a capacity limit (slots), it first
    waits for a free AMF/SMF slot and holds it for service_us, which is
    part of delay_us; the queue wait adds to the latency."""
    env = core.env
    if slots is None:
        yield env.timeout(delay_us)
        return
    queued = env.now
    with slots.request() as req:
        yield req
        setattr(ue, wait_attr, getattr(ue, wait_attr, 0.0) + env.now - queued)
        yield env.timeout(core.config.service_us)
    yield env.timeout(delay_us - core.config.service_us)


# Rashed-Step 19.D.2-10-07-2026-end
def ue_attach(core: Any, gnb: Any, ue: Any):
    """Generator - the whole per-UE Core procedure chain: RRC CONNECTED
    -> Registration (16.C) -> PDU session establishment (16.D)."""
    yield from wait_rrc_connected(ue)
    # Rashed-Step 19.D.2-10-07-2026-start
    if not (yield from registration(core, gnb, ue)):
        return  # gave up after max_attempts rejects
    # Rashed-Step 19.D.2-10-07-2026-end
    # Rashed-Step 16.D-10-02-2026-start
    yield from pdu_session_establishment(core, ue)
    # Rashed-Step 16.D-10-02-2026-end


def compute_registration_stats(ue_list: List[Any]) -> Dict[str, Any]:
    """Same shape as ran.protocol.rrc.compute_connection_setup_stats():
    counts only UEs handed to the Core (they have reg_state at all).
    Latency = registered_at - reg_requested_at, i.e. the registration
    procedure alone, not including the RRC wait before it. Same
    "success_rate is really 'finished so far'" caveat as RRC's, since
    registration cannot fail yet."""
    opted = [ue for ue in ue_list if getattr(ue, "reg_state", None) is not None]
    done = [ue for ue in opted if ue.reg_state is RegistrationState.REGISTERED]
    latencies_us = [ue.registered_at - ue.reg_requested_at for ue in done]
    return {
        "attempted": len(opted),
        "registered": len(done),
        "success_rate": (len(done) / len(opted)) if opted else None,
        "latencies_us": latencies_us,
        "mean_latency_us": (sum(latencies_us) / len(latencies_us)) if latencies_us else None,
    }
# Rashed-Step 16.C-10-02-2026-end


# Rashed-Step 16.D-10-02-2026-start
def compute_pdu_session_stats(ue_list: List[Any]) -> Dict[str, Any]:
    """Same shape as compute_registration_stats(). Counts UEs handed to
    the Core (they have reg_state at all).
      latencies_us: activated_at - requested_at (the PDU session step
        alone).
      attach_latencies_us: activated_at - the moment the UE started
        attaching - rrc_attach_started_at if it went through RRC, else
        core_started_at (when CoreNetwork.start_ue() was called). This
        is the full "radio + Core" time before the UE may carry data.
    Same "success_rate is really 'finished so far'" caveat as the RRC
    and registration stats - nothing can fail yet."""
    opted = [ue for ue in ue_list if getattr(ue, "reg_state", None) is not None]
    active = [
        ue for ue in opted
        if getattr(ue, "pdu_session", None) is not None
        and ue.pdu_session.state is PduSessionState.ACTIVE
    ]
    latencies_us = [ue.pdu_session.activated_at - ue.pdu_session.requested_at for ue in active]
    attach_latencies_us = [
        ue.pdu_session.activated_at - getattr(ue, "rrc_attach_started_at", ue.core_started_at)
        for ue in active
    ]
    return {
        "attempted": len(opted),
        "active": len(active),
        "success_rate": (len(active) / len(opted)) if opted else None,
        "latencies_us": latencies_us,
        "mean_latency_us": (sum(latencies_us) / len(latencies_us)) if latencies_us else None,
        "attach_latencies_us": attach_latencies_us,
        "mean_attach_latency_us": (
            sum(attach_latencies_us) / len(attach_latencies_us) if attach_latencies_us else None
        ),
    }
# Rashed-Step 16.D-10-02-2026-end


# Rashed-Step 16.F-10-02-2026-start
def compute_first_packet_stats(ue_list: List[Any], packets: List[Any]) -> Dict[str, Any]:
    """Attach-to-first-packet: for each UE handed to the Core, the first
    DELIVERED data packet to or from it (Packet.destination or .source
    == ue.name) in `packets`, measured from the same attach start as
    compute_pdu_session_stats' attach latency (rrc_attach_started_at, or
    core_started_at without RRC). The caller decides which packet logs
    count - see simulation.py's NR-U note on why it passes uplink logs
    only. UEs with no delivered packet yet are counted in "attempted"
    but not in "with_packet"."""
    opted = [ue for ue in ue_list if getattr(ue, "reg_state", None) is not None]
    first_at: Dict[str, float] = {}
    for p in packets:
        if p.status != "DELIVERED" or p.delivered_at is None:
            continue
        for name in (p.destination, p.source):
            if name not in first_at or p.delivered_at < first_at[name]:
                first_at[name] = p.delivered_at
    latencies_us = [
        first_at[ue.name] - getattr(ue, "rrc_attach_started_at", ue.core_started_at)
        for ue in opted if ue.name in first_at
    ]
    return {
        "attempted": len(opted),
        "with_packet": len(latencies_us),
        "latencies_us": latencies_us,
        "mean_latency_us": (sum(latencies_us) / len(latencies_us)) if latencies_us else None,
    }


def compute_core_stats(ue_list: List[Any], packets: List[Any]) -> Dict[str, Any]:
    """Registration + PDU session + first-packet stats in one dict, the
    shape both orchestrators return under "core_stats"."""
    return {
        "registration": compute_registration_stats(ue_list),
        "pdu_session": compute_pdu_session_stats(ue_list),
        "first_packet": compute_first_packet_stats(ue_list, packets),
    }


# Rashed-Step 19.D.2-10-07-2026-start
def compute_core_failure_stats(ue_list: List[Any]) -> Dict[str, Any]:
    """Rejects, give-ups and AMF/SMF queue waits (19.D.2)."""
    opted = [ue for ue in ue_list if getattr(ue, "reg_state", None) is not None]
    n = len(opted)
    return {
        "registration_rejects": sum(getattr(ue, "reg_rejects", 0) for ue in opted),
        "registration_failed": sum(1 for ue in opted if getattr(ue, "reg_failed_at", None) is not None),
        "pdu_rejects": sum(getattr(ue, "pdu_rejects", 0) for ue in opted),
        "pdu_failed": sum(1 for ue in opted if getattr(ue, "pdu_failed_at", None) is not None),
        "mean_amf_wait_us": (sum(getattr(ue, "amf_wait_us", 0.0) for ue in opted) / n) if n else None,
        "mean_smf_wait_us": (sum(getattr(ue, "smf_wait_us", 0.0) for ue in opted) / n) if n else None,
    }


def print_core_failure_stats(prefix: str, s: Dict[str, Any]) -> None:
    print(f'{prefix} registration rejects: {s["registration_rejects"]} (gave up: {s["registration_failed"]})')
    print(f'{prefix} PDU session rejects: {s["pdu_rejects"]} (gave up: {s["pdu_failed"]})')
    print(f'{prefix} mean AMF queue wait (us): {s["mean_amf_wait_us"]}')
    print(f'{prefix} mean SMF queue wait (us): {s["mean_smf_wait_us"]}')


# Rashed-Step 19.D.2-10-07-2026-end
def print_core_stats(title: str, prefix: str, stats: Dict[str, Any], first_packet_label: str) -> None:
    """Stdout block for a run with the Core enabled - same "label: value"
    style as the RRC Connection Setup block."""
    reg, pdu, first = stats["registration"], stats["pdu_session"], stats["first_packet"]
    print(f"=== {title} ===")
    print(f'{prefix} Core UEs: {reg["attempted"]}')
    print(f'{prefix} registered: {reg["registered"]}')
    print(f'{prefix} mean registration latency (us): {reg["mean_latency_us"]}')
    print(f'{prefix} PDU sessions active: {pdu["active"]}')
    print(f'{prefix} mean PDU session latency (us): {pdu["mean_latency_us"]}')
    print(f'{prefix} mean attach latency, start -> session active (us): {pdu["mean_attach_latency_us"]}')
    print(f'{prefix} UEs with a delivered {first_packet_label}: {first["with_packet"]}')
    print(f'{prefix} mean attach-to-first-{first_packet_label} latency (us): {first["mean_latency_us"]}')
# Rashed-Step 16.F-10-02-2026-end
