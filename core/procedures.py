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


def ue_attach(core: Any, gnb: Any, ue: Any):
    """Generator - the whole per-UE Core procedure chain: RRC CONNECTED
    -> Registration (16.C). 16.D appends PDU session establishment."""
    yield from wait_rrc_connected(ue)
    yield from registration(core, gnb, ue)


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
