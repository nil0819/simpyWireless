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
from typing import Any


class RrcState(Enum):
    IDLE = "idle"
    CONNECTING = "connecting"
    CONNECTED = "connected"


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
        Technology-specific by design: nru.nru.Gnb's version reuses
        REAL LBT contention delay (via the same
        ran.protocol.channel_access.LbtChannelAccess Step 15.C's NrUE
        uplink already uses - so an NR-U UE's RRCSetupRequest/
        RRCSetupComplete genuinely wait through real Cat-4 LBT
        contention, exactly as this sub-step's SCOPE RESOLVED note
        called for); nr.nr.GnbLicensedNR's version reuses Step 15.E's
        own SchedulingRequest -> grant-eligibility delay
        (config.sr_to_grant_delay_us) - the same real bootstrap cost
        every other uplink message on that UE would incur.

        `ue` must expose rrc_state, already set to RrcState.IDLE
        before this process starts running (see each UE class's own
        __post_init__ - NrUE/NrUeLicensed).
        """
        ue.rrc_state = RrcState.CONNECTING
        ue.rrc_attach_started_at = gnb.env.now
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
# Rashed-Step 15.F-09-18-2026-end
