# Rashed-Step 6.B-07-31-2026-start
# Licensed 5G NR UE (as opposed to nru.ue.NrUE, which belongs to the
# unlicensed NR-U path). Same shape as NrUE - kept as a separate class
# rather than reusing NrUE so the two technologies stay decoupled (a
# licensed-NR run never accidentally shares UE objects/state with an
# NR-U run), matching how wifi/nru already have their own independent
# device classes.

from dataclasses import dataclass
from common.common import Pos
from typing import Optional, Any

# Rashed-Step 15.F-09-18-2026-start
from ran.protocol.rrc import RrcState
# Rashed-Step 15.F-09-18-2026-end


@dataclass
class NrUeLicensed:
    name: str
    pos: Pos  # initial/static position - if mobility is set, use current_pos() instead
    gnb_name: str  # associated gNB
    mobility: Optional[Any] = None

    def current_pos(self) -> Pos:
        return self.mobility.pos_now() if self.mobility is not None else self.pos

    """
    Step 15.E: opt-in uplink eligibility for NrUeLicensed - the
    licensed-NR counterpart of wifi.sta.WiFiSTA (15.B) and nru.ue.NrUE
    (15.C), but architecturally different from both on purpose:
    licensed NR's uplink is GRANT-BASED (the gNB's scheduler decides
    who transmits and when - see nr.nr.GnbLicensedNR._run_ul_slot()),
    not contention-based. This class therefore does NOT run its own
    active transmit process the way WiFiSTA/NrUE do - it stays a
    mostly-passive object (env.process() below only runs a short,
    ONE-TIME SchedulingRequest timer, never a per-slot transmit loop).
    GnbLicensedNR drives the entire uplink transmission centrally,
    exactly like it already does for downlink.

    SCOPE (first cut, same discipline as 15.B/15.C): opt-in via
    uplink_enabled (default False) - every existing NrUeLicensed(...)
    call site (simulation_nr.py, every test/test_nr_licensed.py
    scenario) is unaffected. Saturated traffic only (once
    ul_ready=True, this UE is simply a standing UL candidate every
    'U' slot - see GnbLicensedNR._run_ul_slot() - mirroring real
    Configured Grant / semi-persistent scheduling, which real
    deployments use to avoid re-running SchedulingRequest for every
    packet of ongoing saturated traffic). No ahead-of-time rate
    adaptation for UL yet (always the oracle/post-hoc MCS pick, same
    as DL's rate_adapt_enabled=False path).

    Unlike WiFiSTA.ap/NrUE.gnb, this class's own `gnb` back-reference
    (set automatically by GnbLicensedNR.__init__, mirroring both of
    those) is NOT actually read by 15.E's own mechanism - wired anyway
    for consistency and because 15.F's RRC layer will need it.
    """

    # Rashed-Step 15.E-09-18-2026-start
    # Opt-in uplink fields - all Optional/False-defaulted so every
    # existing NrUeLicensed(...) call site is unaffected. `config` is
    # duck-typed against nr.nr.Config_NRL's shape (only
    # sr_to_grant_delay_us is actually read by this class itself -
    # GnbLicensedNR reads the rest directly off its own config when it
    # drives this UE's actual uplink transmission).
    env: Optional[Any] = None
    config: Optional[Any] = None
    # Set automatically by GnbLicensedNR.__init__ - see this class's
    # own docstring. Not read by 15.E's own mechanism (see docstring)
    # but not meant to be passed by callers either way.
    gnb: Optional[Any] = None
    uplink_enabled: bool = False
    # Rashed-Step 15.F-09-18-2026-start
    # Opt-in RRC attach - mirrors nru.ue.NrUE's identical field/
    # dependency contract (see ran/protocol/rrc.py's module docstring).
    # Requires uplink_enabled=True too - RRC attach genuinely needs
    # real uplink capability (RRCSetupRequest/RRCSetupComplete ride the
    # same SR->grant delay every other uplink message on this UE
    # would incur - see GnbLicensedNR.rrc_uplink_delay()).
    rrc_enabled: bool = False
    # Rashed-Step 15.F-09-18-2026-end

    def __post_init__(self):
        # Rashed-Step 15.F-09-18-2026-start
        if self.rrc_enabled and not self.uplink_enabled:
            raise ValueError(
                "NrUeLicensed: rrc_enabled=True requires uplink_enabled"
                "=True too - RRC attach genuinely needs real uplink "
                "capability to send RRCSetupRequest/RRCSetupComplete "
                "(see ran/protocol/rrc.py's module docstring)."
            )
        # Rashed-Step 15.F-09-18-2026-end
        if not self.uplink_enabled:
            return
        if self.env is None or self.config is None:
            raise ValueError(
                "NrUeLicensed: uplink_enabled=True requires env and "
                "config to be supplied (the gNB reference is wired in "
                "automatically by GnbLicensedNR.__init__ once this UE "
                "is placed in a gNB's ue_list, so it does not need to "
                "be passed here - see this class's own docstring)."
            )
        self.ul_ready = False
        self.sr_sent_at: Optional[float] = None
        self.first_grant_at: Optional[float] = None
        # Rashed-Step 15.F-09-18-2026-start
        if self.rrc_enabled:
            self.rrc_state = RrcState.IDLE
        # Rashed-Step 15.F-09-18-2026-end
        self.env.process(self._send_scheduling_request())

    def _send_scheduling_request(self):
        """
        One-time SchedulingRequest -> grant-eligibility timer - see
        Config_NRL.sr_to_grant_delay_us's own docstring for why this is
        charged once, not per packet. A real, timed SimPy event (not an
        instant flag flip) specifically so there's something genuine
        for a future connection-setup-latency metric (Step 15.G) to
        measure - self.sr_sent_at/self.first_grant_at are timestamps
        exactly for that purpose.
        """
        self.sr_sent_at = self.env.now
        yield self.env.timeout(self.config.sr_to_grant_delay_us)
        self.ul_ready = True
        self.first_grant_at = self.env.now
    # Rashed-Step 15.E-09-18-2026-end
# Rashed-Step 6.B-07-31-2026-end
