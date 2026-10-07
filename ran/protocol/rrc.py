# Rashed-Step 15.F-09-18-2026-start
"""
Generic RRC (Radio Resource Control) attach procedure - Step pre_15.txt
Section 3's 15.F SCOPE RESOLVED decision (Rashed, 2026-09-18): written
ONCE here and composed into BOTH licensed NR (nr/nr.py's
GnbLicensedNR) and NR-U (nru/nru.py's Gnb), so STANDALONE_MULTIFIRE
(15.D's confirmed default) gets a real, working rrc_state/connection-
setup metric too, not just licensed NR - and so Phase 7's later
promise ("the same RRC/Core/QoS scaffolding built for licensed NR
governs an NR-U SCell too") holds without retrofitting this module.
Lands in ran/protocol/ alongside channel_access.py exactly where
Section 8's intended module structure said it eventually would.

Models a minimal, 3-message attach exchange - RRCSetupRequest (UE ->
gNB) -> RRCSetup (gNB -> UE) -> RRCSetupComplete (UE -> gNB) - as
scheduled SimPy events with configurable timing. The sub-step's own
description frames this as "replacing 'UE exists in gnb.ue_list at
construction' with a real, time-consuming attach procedure" - that
means every opted-in UE now genuinely HAS an rrc_state that starts at
IDLE and takes real simulated time to reach CONNECTED; whether the
DL/UL SCHEDULER actually filters by it is Step 15.G's job, not this
one. 15.F is purely additive (a real state machine + timing exists
alongside everything else) and does not itself change any existing
scheduling decision.

SCOPE (first cut):
  - Opt-in via a UE's own rrc_enabled field (requires uplink_enabled=
    True too - RRC attach genuinely needs real uplink capability to
    send RRCSetupRequest/RRCSetupComplete; it does not invent a
    second, separate minimal-state uplink pathway just for RRC
    signaling). Every existing NrUE(...)/NrUeLicensed(...) call site
    is unaffected either way - see those classes' own docstrings.
  - Always eventually succeeds, deterministically, after the modeled
    delay - no attach-failure/retry-limit/timeout concept yet. Real
    "setup success/failure rate" tracking (Step 15.G's own stated
    scope) will need a genuine failure mode added first; until then
    that metric would trivially read 0% failure - honestly documented
    here rather than silently implied to be more complete than it is.
  - A UE that never opts into rrc_enabled has NO rrc_state attribute
    at all (not even IDLE) - by design, so any future code (15.G) that
    filters ue_list by rrc_state must use
    `getattr(ue, "rrc_state", RrcState.CONNECTED) is RrcState.CONNECTED`,
    treating "never opted into RRC" as "always connected" - the
    CURRENT (pre-15.F) behavior for every UE, and it must stay that
    way for anything not explicitly using this feature.
"""
from enum import Enum
from typing import Any, Dict, List, Optional


class RrcState(Enum):
    IDLE = "idle"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    # Rashed-Step 19.B.3-10-07-2026-start
    # Released with suspend (19.B.3): context kept, not scheduled.
    INACTIVE = "inactive"
    # Rashed-Step 19.B.3-10-07-2026-end


class RrcLayer:
    """
    Stateless (holds no per-UE data of its own - every value it reads/
    writes lives on the `ue`/`gnb` arguments, same convention as
    LbtChannelAccess/SlotScheduledAccess in channel_access.py), so one
    shared instance can safely drive every UE's attach procedure.
    """

    def __init__(self, setup_processing_delay_us: float = 2000.0):
        # gNB-side RRCSetup message processing/DL-signaling delay - a
        # representative, not conformance-tested, first-cut value (real
        # 3GPP RRC procedure timers are considerably more involved -
        # this models "the gNB needed some real time to process the
        # request and signal the response", not a literal spec figure).
        self.setup_processing_delay_us = setup_processing_delay_us

    def attach(self, gnb: Any, ue: Any):
        """
        Generator - drives one UE's full IDLE -> CONNECTING ->
        CONNECTED attach procedure.

        `gnb` must expose: env (simpy.Environment), and
        rrc_uplink_delay(ue) - a generator modeling how long this UE
        must wait before it can actually send an uplink RRC message.
        Technology-specific by design (Step 16.A: both first pay
        their config's rrc_ul_grant_delay_us, so the description
        below is what each adds on top of / instead of that):
        nru.nru.Gnb's version reuses
        REAL LBT contention delay (via the same
        ran.protocol.channel_access.LbtChannelAccess Step 15.C's NrUE
        uplink already uses - so an NR-U UE's RRCSetupRequest/
        RRCSetupComplete genuinely wait through real Cat-4 LBT
        contention, exactly as this sub-step's SCOPE RESOLVED note
        called for); nr.nr.GnbLicensedNR's version is the grant delay
        alone (config.rrc_ul_grant_delay_us - before Step 16.A it
        reused 15.E's data-plane sr_to_grant_delay_us instead).

        `ue` must expose rrc_state, already set to RrcState.IDLE
        before this process starts running (see each UE class's own
        __post_init__ - NrUE/NrUeLicensed).
        """
        ue.rrc_state = RrcState.CONNECTING
        ue.rrc_attach_started_at = gnb.env.now
        # Rashed-Step 19.A-10-07-2026-start
        # Random access first (ran/protocol/rach.py) when the cell runs it;
        # Msg3/Msg4 are the RRCSetupRequest/RRCSetup below. A failed random
        # access abandons the attach: the UE goes back to IDLE.
        rach = getattr(gnb, "rach_cell", None)
        if rach is not None:
            if not (yield from rach.access(ue)):
                ue.rrc_state = RrcState.IDLE
                ue.rrc_failed_at = gnb.env.now
                return
        # Rashed-Step 19.A-10-07-2026-end
        # RRCSetupRequest (UE -> gNB)
        yield from gnb.rrc_uplink_delay(ue)
        ue.rrc_setup_request_sent_at = gnb.env.now
        # RRCSetup (gNB -> UE)
        yield gnb.env.timeout(self.setup_processing_delay_us)
        ue.rrc_setup_received_at = gnb.env.now
        # RRCSetupComplete (UE -> gNB)
        yield from gnb.rrc_uplink_delay(ue)
        ue.rrc_setup_complete_sent_at = gnb.env.now
        ue.rrc_state = RrcState.CONNECTED
        ue.rrc_connected_at = gnb.env.now
        # Rashed-Step 15.G-09-18-2026-start
        # Optional coordination hook for Step 15.G's uplink gating: a UE
        # class that wants its own autonomous transmit loop to block
        # until RRC is CONNECTED (nru.ue.NrUE's start_uplink() does -
        # see that method's own comment) prepares a plain simpy.Event
        # named _rrc_connected_event in its own __post_init__ (only
        # when rrc_enabled=True). Fired here, the instant rrc_state
        # actually becomes CONNECTED, so any waiter resumes on the
        # exact same tick as rrc_connected_at above - no polling, no
        # separate timing model to keep in sync with this one.
        # getattr(...)-based and purely optional so RrcLayer itself
        # stays generic/UE-shape-agnostic (NrUeLicensed has no
        # autonomous loop to gate this way at all - see Step 15.G's own
        # note in nr/nr.py's _run_ul_slot()/_run_dl_slot(), which gate
        # by polling ue.rrc_state every slot instead, needing no event).
        connected_event = getattr(ue, "_rrc_connected_event", None)
        if connected_event is not None and not connected_event.triggered:
            connected_event.succeed()
        # Rashed-Step 19.B.2-10-07-2026-start
        # Radio link monitoring from now on, when the cell runs it
        # (ran/protocol/rlm.py).
        rlm_cfg = getattr(gnb, "rlm_config", None)
        if rlm_cfg is not None:
            from ran.protocol.rlm import radio_link_monitor
            gnb.env.process(radio_link_monitor(gnb, ue, rlm_cfg, self))
        # Rashed-Step 19.B.3-10-07-2026-start
        inactive_cfg = getattr(gnb, "inactive_config", None)
        if inactive_cfg is not None:
            from ran.protocol.inactive import inactivity_manager
            gnb.env.process(inactivity_manager(gnb, ue, inactive_cfg, self))
        # Rashed-Step 19.D.1-10-07-2026-start
        ho_cfg = getattr(gnb, "ho_config", None)
        if ho_cfg is not None:
            from ran.protocol.handover import measurement_process
            gnb.env.process(measurement_process(ue, ho_cfg))
        # Rashed-Step 19.D.1-10-07-2026-end
        # Rashed-Step 19.B.3-10-07-2026-end
        # Rashed-Step 19.B.2-10-07-2026-end
        # Rashed-Step 15.G-09-18-2026-end
# Rashed-Step 15.F-09-18-2026-end


# Rashed-Step 15.G-09-18-2026-start
# Rashed-Step 19.B.4-10-07-2026-start
def rrc_reconfiguration(gnb: Any, ue: Any):
    """Generator - one RRCReconfiguration exchange (TS 38.331 5.3.5):
    the gNB sends RRCReconfiguration (e.g. the data radio bearer for a
    new PDU session, with the NAS accept inside), the UE applies it -
    gnb.rrc_reconfig_us, 10 ms by default, the UE processing time TS
    38.331 clause 12 allows for it - and answers with
    RRCReconfigurationComplete on the normal RRC uplink path."""
    env = gnb.env
    started = env.now
    yield env.timeout(gnb.rrc_reconfig_us)
    yield from gnb.rrc_uplink_delay(ue)
    ue.rrc_reconfig_latencies_us = getattr(ue, "rrc_reconfig_latencies_us", []) + [env.now - started]


def compute_reconfig_stats(ue_list: List[Any]) -> Dict[str, Any]:
    lat = [x for ue in ue_list for x in getattr(ue, "rrc_reconfig_latencies_us", [])]
    return {"reconfigurations": len(lat),
            "mean_latency_us": (sum(lat) / len(lat)) if lat else None}
# Rashed-Step 19.B.4-10-07-2026-end


def compute_connection_setup_stats(ue_list: List[Any]) -> Dict[str, Any]:
    """
    Aggregate RRC connection-setup metrics across every UE in ue_list
    that opted into RRC (rrc_enabled=True, i.e. it has an rrc_state
    attribute at all - see this module's own backward-compat contract
    above). Technology-agnostic: reads only ue.rrc_state/
    ue.rrc_attach_started_at/ue.rrc_connected_at, which both nru.ue.NrUE
    and nr.ue.NrUeLicensed populate identically via RrcLayer.attach()
    (that's the whole point of 15.F's generic design) - this function
    works unmodified for either technology's ue_list, or a mixed one.

    UEs that never opted into RRC are excluded entirely from every
    count here (not treated as "connected" the way the scheduler-
    filtering getattr(..., RrcState.CONNECTED) default does - that
    default exists to keep OLD code paths behaviorally unchanged, not
    to imply those UEs meaningfully went through a setup procedure this
    metric should describe).

    Returns:
        {
          "attempted": int - UEs with rrc_enabled=True,
          "connected": int - of those, how many are currently
              RrcState.CONNECTED (mid-run, some may still be IDLE/
              CONNECTING - see "success_rate"'s own note below),
          "success_rate": float | None - connected / attempted, or
              None if attempted == 0 (nothing to divide by),
          "latencies_us": List[float] - rrc_connected_at -
              rrc_attach_started_at, one entry per CONNECTED UE,
          "mean_latency_us": float | None - mean of latencies_us, or
              None if empty,
        }

    KNOWN LIMITATION (see ran/protocol/rrc.py's own module docstring's
    SCOPE note): RrcLayer.attach() has no failure mode yet - every UE
    that opts in eventually reaches CONNECTED given enough simulated
    time, so "success_rate" is not a real setup-failure metric today;
    a UE counted as "not yet connected" here is simply still mid-
    attach at the moment this function was called (IDLE/CONNECTING),
    not a UE whose attach failed. A genuine failure/retry-limit/
    timeout mode (Step 15.G's own roadmap note flagged this as
    naturally belonging to a future sub-step) would need to exist
    before this number means "reliability" rather than just "how many
    have finished so far."
    """
    opted = [ue for ue in ue_list if getattr(ue, "rrc_state", None) is not None]
    connected = [ue for ue in opted if ue.rrc_state is RrcState.CONNECTED]
    latencies_us = [
        ue.rrc_connected_at - ue.rrc_attach_started_at
        for ue in connected
    ]
    return {
        "attempted": len(opted),
        "connected": len(connected),
        "success_rate": (len(connected) / len(opted)) if opted else None,
        "latencies_us": latencies_us,
        "mean_latency_us": (sum(latencies_us) / len(latencies_us)) if latencies_us else None,
        # Rashed-Step 19.A-10-07-2026-start
        # Attaches abandoned because random access failed.
        "failed": sum(1 for ue in opted if getattr(ue, "rrc_failed_at", None) is not None),
        # Rashed-Step 19.A-10-07-2026-end
    }
# Rashed-Step 15.G-09-18-2026-end
