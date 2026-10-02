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
    yield env.timeout(core.config.registration_delay_us)
    core.amf.register(ue.name, gnb.name)
    ue.reg_state = RegistrationState.REGISTERED
    ue.registered_at = env.now


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
    yield env.timeout(core.config.pdu_session_delay_us)
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
def ue_attach(core: Any, gnb: Any, ue: Any):
    """Generator - the whole per-UE Core procedure chain: RRC CONNECTED
    -> Registration (16.C) -> PDU session establishment (16.D)."""
    yield from wait_rrc_connected(ue)
    yield from registration(core, gnb, ue)
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
