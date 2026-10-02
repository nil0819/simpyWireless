# Rashed-Step 6.B-07-31-2026-start
# Licensed 5G NR (as opposed to nru.py, which is NR-U - unlicensed NR
# with Cat-4 LBT/energy-detection deferral). The defining realism
# difference: a licensed operator has exclusive rights to its carrier,
# so there is NO listen-before-talk here at all - Config_NRL has no
# ed_threshold_dbm field on purpose. Instead, a gNB runs a slot-by-slot
# scheduler (round-robin or proportional-fair) that allocates resource
# blocks across its associated UEs every slot, exactly like a real
# gNB MAC scheduler. Reuses the same channel.ActiveTx/register_tx/
# sinr_db machinery NR-U and WiFi already use (tech="NR"), so if two
# licensed gNBs from the SAME run happen to share spectrum without any
# inter-cell coordination, they DO interfere with each other - a
# realistic "co-channel same-operator interference" effect (real
# networks avoid this via frequency-reuse planning / X2-Xn scheduler
# coordination, neither of which is modeled here - noted as a
# simplification, see Step 6.txt).

import math
import random
from dataclasses import dataclass, field
from typing import Dict, Optional, Any, List, Tuple

from common.common import Pos, dist, log, colors
from channel.channel import ActiveTx
# Rashed-Step 13.E.3-08-23-2026-start
from common.packet import Packet
# Rashed-Step 13.E.3-08-23-2026-end

# Rashed-Step 15.A-09-18-2026-start
from ran.protocol.channel_access import SlotScheduledAccess
# Rashed-Step 15.A-09-18-2026-end
# Rashed-Step 15.F-09-18-2026-start
from ran.protocol.rrc import RrcLayer
# Rashed-Step 15.F-09-18-2026-end
# Rashed-Step 15.G-09-18-2026-start
from ran.protocol.rrc import RrcState
# Rashed-Step 15.G-09-18-2026-end


# ---------------------------------------------------------------------
# Numerology (3GPP TS 38.211): subcarrier spacing doubles, slot duration
# halves, per numerology index mu. FR1 (sub-6 GHz, which licensed 5G NR
# almost always is for a macro/small-cell deployment) commonly uses
# mu=0 or mu=1; mu=2/3 exist mostly for FR2 (mmWave) but are included
# here for completeness since nothing about the scheduler logic below
# depends on which one is picked.
# ---------------------------------------------------------------------
NUMEROLOGY_SCS_KHZ = {0: 15, 1: 30, 2: 60, 3: 120}


def slot_duration_us(mu: int) -> float:
    """Slot duration in microseconds for numerology index mu (3GPP: 1ms / 2^mu)."""
    return 1000.0 / (2 ** mu)


# ---------------------------------------------------------------------
# Resource-block count per (channel bandwidth, subcarrier spacing).
# Real values are standardized (3GPP TS 38.101-1 Table 5.3.2-1) - the
# table below reproduces the common FR1 entries exactly; anything not
# in the table falls back to a formula-based estimate (usable bandwidth
# ~= 90% of nominal, after guard bands, divided by RB width = 12 *
# SCS_khz*1000 Hz) so uncommon bandwidth/SCS combinations still get a
# sane RB count instead of failing.
# ---------------------------------------------------------------------
_RB_TABLE_KHZ15 = {5: 25, 10: 52, 15: 79, 20: 106, 25: 133, 30: 160, 40: 216, 50: 270}
_RB_TABLE_KHZ30 = {10: 24, 15: 38, 20: 51, 25: 65, 30: 78, 40: 106, 50: 133, 60: 162, 80: 217, 90: 245, 100: 273}
_RB_TABLE_KHZ60 = {10: 11, 20: 24, 30: 38, 40: 51, 50: 65, 60: 79, 80: 107, 90: 121, 100: 135}
_RB_TABLES = {15: _RB_TABLE_KHZ15, 30: _RB_TABLE_KHZ30, 60: _RB_TABLE_KHZ60}


def resource_block_count(bandwidth_mhz: float, scs_khz: int) -> int:
    table = _RB_TABLES.get(scs_khz)
    if table is not None:
        bw_int = int(round(bandwidth_mhz))
        if bw_int in table:
            return table[bw_int]
    # Fallback: usable bandwidth ~90% of nominal (guard bands), divided
    # by one RB's width (12 subcarriers * scs_khz).
    usable_hz = bandwidth_mhz * 1e6 * 0.90
    rb_width_hz = 12 * scs_khz * 1000.0
    return max(1, int(usable_hz // rb_width_hz))


# ---------------------------------------------------------------------
# MCS -> (required SINR dB, spectral efficiency bits/s/Hz). Loosely
# follows the shape of the real 3GPP CQI/MCS tables (TS 38.214 Table
# 5.2.2.1-2 / 38.213 CQI table) - QPSK at the low end through 64-QAM at
# the top - but, like WIFI_MCS_SINR_THRESHOLDS_DB and
# NRU_MCS_SINR_THRESHOLDS_DB elsewhere in this project, these are
# representative/typical values for a coexistence-simulator PHY
# abstraction, not vendor- or 3GPP-conformance-tested figures.
# ---------------------------------------------------------------------
NR_MCS_TABLE: Dict[int, Tuple[float, float]] = {
    0: (-6.0, 0.15),
    1: (-4.0, 0.23),
    2: (-2.0, 0.38),
    3: (0.0, 0.60),
    4: (2.0, 0.88),
    5: (4.0, 1.18),
    6: (6.0, 1.48),
    7: (8.0, 1.91),
    8: (10.0, 2.41),
    9: (12.0, 2.73),
    10: (14.0, 3.32),
    11: (16.0, 3.90),
    12: (18.0, 4.52),
    13: (20.0, 5.12),
    14: (22.0, 5.55),
    15: (24.0, 5.89),
}


def select_mcs_for_sinr(sinr_db: float, table: Dict[int, Tuple[float, float]] = NR_MCS_TABLE) -> Optional[int]:
    """
    Link adaptation: pick the highest MCS index whose required SINR is
    still met by the achieved sinr_db. Returns None if even MCS 0 can't
    be met (transmission fails outright this slot). Unlike WiFi/NR-U
    (which use one fixed, operator-configured MCS and a pass/fail gate),
    licensed NR here does real adaptive modulation and coding per slot,
    per UE - a deliberate scope difference matching the "full scheduler
    model" this step was asked to build.
    """
    best = None
    for mcs, (req_db, _eff) in table.items():
        if sinr_db >= req_db:
            if best is None or mcs > best:
                best = mcs
    return best


@dataclass()
class Config_NRL:
    # Frame/numerology
    numerology: int = 1  # mu; 30 kHz SCS by default (common FR1 mid-band choice)
    bandwidth_mhz: float = 100.0  # channel bandwidth used to derive RB count + noise floor

    # Scheduler
    scheduler: str = "round_robin"  # "round_robin" or "proportional_fair"
    pf_alpha: float = 0.2  # EMA weight for the proportional-fair average-rate tracker

    # RF / propagation - default frequency is 3.5 GHz (3GPP band n78),
    # the most common global mid-band licensed 5G NR carrier, deliberately
    # different from Wi-Fi/NR-U's 5.18 GHz U-NII default so a licensed-NR
    # run doesn't accidentally co-channel with the unlicensed scenario.
    tx_power_dbm: float = 30.0  # small-cell/macro downlink EIRP, licensed band
    f_ghz: float = 3.5e9
    pl_exp: float = 3.0

    noise_figure_db: float = 7.0

    # NOTE: intentionally no ed_threshold_dbm here - licensed spectrum
    # means no LBT/CCA deferral. See module docstring.

    # Rashed-Step 13.E.3-08-23-2026-start
    # Nominal per-slot payload size stamped on each synthesized Packet
    # (Step 13.E.3) - same "placeholder, nothing downstream reads it"
    # convention as nru.py's Config_NR default (1500 bytes): this
    # scheduler's slot duration/RB allocation is fixed regardless of
    # payload_bytes, so this is bookkeeping only, not a real traffic-
    # size model.
    packet_payload_bytes: int = 1500

    # Opt-in AHEAD-OF-TIME rate adaptation. False (default): EXACT
    # pre-13.E.3 behavior - MCS is chosen AFTER the slot's real SINR is
    # already known (select_mcs_for_sinr(sinr), a "genie-aided"/oracle
    # pick that can only fail if even MCS0's threshold isn't met - see
    # select_mcs_for_sinr()'s own docstring). True: MCS is instead
    # chosen BEFORE the slot's real SINR is known, from that UE's own
    # last-measured SINR (a real prediction under uncertainty, the same
    # "ahead-of-time, may guess wrong" shape as WiFi's ARF (Step 11.A)
    # and NR-U's CQI-style scheme (Step 11.B) - genuinely comparable to
    # them for the first time, unlike the oracle default, which no
    # heuristic or model could ever legitimately "beat" since it already
    # has perfect real-time channel knowledge). A wrong ahead-of-time
    # guess (chosen MCS's threshold not actually met this slot) is a
    # real failure (DROPPED) here, even if a lower MCS would have
    # worked - this is what makes rate_adapt_enabled=True a genuine,
    # fallible adaptation scheme instead of a strictly-better oracle.
    # See "Project details/Step 13.txt"'s 13.E.3 section for the full
    # design rationale (this was a real design fork found while
    # building this sub-step, not something anticipated when 13.E was
    # first planned).
    rate_adapt_enabled: bool = False
    # Only consulted when rate_adapt_enabled is True AND a UE's link
    # already has >= predictor.lag_k measurements - swaps "last
    # measured SINR" for the predictor's PREDICTED next SINR, same
    # duck-typed hook (.lag_k/.predict_next()) and same constant-link
    # safety guard (Step 13.D-fix/13.E.1-fix) as Config_NR.sinr_predictor
    # / wifi.Config.sinr_predictor.
    sinr_predictor: Any = None
    # Rashed-Step 13.E.3-08-23-2026-end

    # Rashed-Step 15.E-09-18-2026-start
    # Opt-in TDD uplink. False (default): every slot is scheduled as
    # downlink exactly as before this step - run_one_slot() delegates
    # unconditionally to _run_dl_slot() (a pure rename of this method's
    # entire pre-15.E body, zero logic change), so every existing
    # licensed-NR run (simulation_nr.py, singleRunNR.py, every test/
    # test_nr_licensed.py scenario) is byte-identical whether or not
    # any UE has its own uplink_enabled set. True: slots are scheduled
    # per tdd_pattern below instead - see _run_ul_slot() and
    # NrUeLicensed's own uplink_enabled field (nr/ue.py).
    tdd_enabled: bool = False
    # Only consulted when tdd_enabled is True. A string of 'D'/'U'
    # characters, cycled per slot index (slot i uses
    # tdd_pattern[i % len(tdd_pattern)]) - deliberately simplified vs.
    # real 3GPP TDD patterns (which also have 'S'/special/flexible
    # slots, e.g. "DDDSU") since this first cut only needs a clean UL/
    # DL split, not sub-slot flexible symbols. 3 DL : 1 UL is a
    # realistic-shaped, DL-heavy ratio (typical of real deployments,
    # which usually favor DL given asymmetric traffic demand) without
    # starving UL entirely.
    tdd_pattern: str = "DDDU"
    # Real UE max transmit EIRP is commonly ~23 dBm for FR1 handsets -
    # deliberately separate from tx_power_dbm above (the gNB's OWN
    # downlink power, 30 dBm default) since a UE is a much smaller,
    # battery-powered radio. Shared by every UE on this gNB (no
    # per-UE power config yet - same "one shared config for now" scope
    # simplification as every other technology's first uplink cut).
    ue_tx_power_dbm: float = 23.0
    # SchedulingRequest -> first-grant-eligibility delay, modeling a
    # real UE's initial random-access-like wait before a gNB scheduler
    # starts actually granting it UL resources (real 3GPP SR-to-grant
    # latency is commonly a few ms depending on SR periodicity/
    # processing timelines - 4000us is a representative, not
    # conformance-tested, first-cut value). Charged ONCE per UE (see
    # NrUeLicensed._send_scheduling_request()) - after that, a
    # saturated UE is simply a standing UL candidate every U-slot
    # (mirrors real Configured Grant / semi-persistent scheduling,
    # which real deployments use specifically to avoid re-running SR
    # for every single packet of ongoing saturated traffic).
    sr_to_grant_delay_us: float = 4000.0
    # Rashed-Step 15.E-09-18-2026-end

    # Rashed-Step 16.A-10-02-2026-start
    # Per-message uplink grant delay for RRC signaling (RRCSetupRequest
    # / RRCSetupComplete - see GnbLicensedNR.rrc_uplink_delay()). Before
    # 16.A, RRC reused sr_to_grant_delay_us above (4000us, a DATA-plane
    # Configured-Grant bootstrap cost) twice, which made licensed NR's
    # attach (10ms) slower than NR-U's (3.6-7.6ms) - the reverse of
    # real deployments, where LBT adds delay on top of scheduling.
    # 1000us = 2 slots at the default numerology (mu=1, 500us slots):
    # one slot for the grant, one for the UE's own transmission. With
    # RrcLayer's 2000us setup-processing delay, a full licensed-NR
    # attach takes 2*1000 + 2000 = 4000us, inside 3GPP TR 38.913's
    # 10ms control-plane latency target. NR-U's Config_NR has the same
    # field and pays it too, plus its LBT wait (nru/nru.py's
    # Gnb.rrc_uplink_delay()). Only read when a UE has
    # rrc_enabled=True.
    rrc_ul_grant_delay_us: float = 1000.0
    # Rashed-Step 16.A-10-02-2026-end


class GnbLicensedNR:
    def __init__(
            self,
            env,
            name: str,
            channel,
            pos: Pos,
            ue_list: list,
            config: Config_NRL,
            mobility: Optional[Any] = None,
    ):
        self.env = env
        self.name = name
        self.channel = channel
        self.pos = pos
        self.ue_list = ue_list
        self.config = config
        self.mobility = mobility
        self.col = random.choice(colors)

        self.scs_khz = NUMEROLOGY_SCS_KHZ[config.numerology]
        self.slot_us = slot_duration_us(config.numerology)
        self.total_rbs = resource_block_count(config.bandwidth_mhz, self.scs_khz)
        self.rb_bandwidth_hz = 12 * self.scs_khz * 1000.0

        # Stats
        self.succeeded_transmissions = 0
        self.failed_transmissions = 0
        self.bits_delivered = 0

        # Round-robin rotation pointer
        self._rr_pointer = 0
        # Proportional-fair per-UE average-rate tracker (bits/s), seeded
        # with a small epsilon so every UE can win at least once early on
        # instead of a first-slot tie going to whichever UE happens first
        # in ue_list every time.
        self._pf_avg_rate: Dict[str, float] = {ue.name: 1.0 for ue in ue_list}

        self.channel.airtime_data_NRL.setdefault(name, 0)
        self.channel.airtime_control_NRL.setdefault(name, 0)

        # Rashed-Step 15.A-09-18-2026-start
        # Shared, stateless slot-scheduler strategy (see ran/protocol/
        # channel_access.py) - _allocate_rbs() below now delegates to it
        # instead of dispatching inline. _round_robin_allocation()/
        # _proportional_fair_allocation() themselves are UNMOVED (still
        # directly unit-tested by test/test_nr_licensed.py) - zero
        # behavior change, just formalizes the existing dispatch behind
        # the same interface LbtChannelAccess uses.
        self._channel_access = SlotScheduledAccess()
        # Rashed-Step 15.A-09-18-2026-end

        # Rashed-Step 15.F-09-18-2026-start
        # Shared, stateless RRC attach driver - see
        # ran/protocol/rrc.py's module docstring. Same single-shared-
        # instance convention as self._channel_access above.
        self._rrc_layer = RrcLayer()
        # Rashed-Step 15.F-09-18-2026-end

        # Rashed-Step 15.E-09-18-2026-start
        # UL scheduler state - own rotation pointer/fairness tracker,
        # kept separate from DL's self._rr_pointer/self._pf_avg_rate
        # above (see SlotScheduledAccess.allocate_ul()'s own docstring
        # for why). Cheap to construct unconditionally even when
        # config.tdd_enabled is False (empty dict, pointer never
        # advanced) - same "unused costs nothing" convention as every
        # other opt-in field elsewhere in this project.
        self._rr_pointer_ul = 0
        self._pf_avg_rate_ul: Dict[str, float] = {}
        self._slot_index = 0
        self.succeeded_transmissions_ul = 0
        self.failed_transmissions_ul = 0
        self.bits_delivered_ul = 0
        # Back-reference each associated UE to this gNB object, mirroring
        # wifi.WiFi.__init__'s sta.ap = self (15.B) and nru.Gnb.__init__'s
        # ue.gnb = self (15.C). Not actually read by 15.E's own mechanism
        # (this gNB drives UL transmission centrally in _run_ul_slot(),
        # unlike WiFiSTA/NrUE's autonomous-contention uplinks - see
        # NrUeLicensed's class docstring) but wired anyway for
        # consistency and because 15.F's RRC layer will need it. No-op
        # for every UE that doesn't use uplink.
        for ue in self.ue_list:
            ue.gnb = self
            if getattr(ue, "uplink_enabled", False):
                self.channel.airtime_data_NRL.setdefault(ue.name, 0)
            # Rashed-Step 15.F-09-18-2026-start
            # Kick off RRC attach for any UE that opted in - see
            # ran/protocol/rrc.py's module docstring and
            # NrUeLicensed.__post_init__'s validation (requires
            # uplink_enabled=True too). Started here, not in
            # NrUeLicensed's own __post_init__, for the same reason as
            # nru.Gnb's identical loop (Step 15.F there): attach()
            # needs ue.gnb (just set above) and this gNB's own
            # rrc_uplink_delay(), neither of which exists yet at
            # UE-construction time.
            if getattr(ue, "rrc_enabled", False):
                env.process(self._rrc_layer.attach(self, ue))
            # Rashed-Step 15.F-09-18-2026-end
        # Rashed-Step 15.E-09-18-2026-end

        # Rashed-Step 13.E.3-08-23-2026-start
        self._packet_seq = 0
        # Every DATA packet this gNB has finished with (DELIVERED or
        # DROPPED - never PENDING), same convention as nru.Gnb's
        # packet_log (Step 8.G).
        self.packet_log: List[Packet] = []
        # Per-UE ahead-of-time rate-adaptation state (only populated/
        # consulted when config.rate_adapt_enabled is True - see
        # current_mcs_for_ue()/record_link_result()).
        self.link_state: Dict[str, Dict[str, Any]] = {}
        # Rashed-Step 13.E.3-08-23-2026-end

        env.process(self.start())

    def current_pos(self) -> Pos:
        return self.mobility.pos_now() if self.mobility is not None else self.pos

    def start(self):
        while True:
            yield self.env.process(self.run_one_slot())

    # -------------------------------------------------------------
    # Scheduling
    # -------------------------------------------------------------
    def _round_robin_allocation(self) -> Dict[str, int]:
        """Equal-share OFDMA: every associated UE gets a slice of the
        slot's resource blocks, rotating which UE(s) absorb the
        remainder so nobody is shorted every single slot."""
        # Rashed-Step 15.E-09-18-2026-start
        # UPGRADE (pure refactor, zero behavior change): body extracted
        # into _round_robin_allocation_for() below, parametrized on
        # candidate_ues/pointer instead of hardcoding self.ue_list/
        # self._rr_pointer, so 15.E's UL scheduler can reuse the exact
        # same algorithm against a different candidate set and its own
        # independent pointer - see SlotScheduledAccess.allocate_ul()'s
        # docstring. This method is now a one-line wrapper; test/
        # test_nr_licensed.py's direct gnb._round_robin_allocation()
        # calls are unaffected.
        alloc, self._rr_pointer = self._round_robin_allocation_for(self.ue_list, self._rr_pointer)
        return alloc

    def _round_robin_allocation_for(self, candidate_ues: list, pointer: int) -> Tuple[Dict[str, int], int]:
        n = len(candidate_ues)
        if n == 0 or self.total_rbs == 0:
            return {}, pointer
        base = self.total_rbs // n
        remainder = self.total_rbs % n
        alloc = {}
        for i, ue in enumerate(candidate_ues):
            rbs = base
            # Rotate who gets the +1 remainder RB so it averages out.
            if remainder > 0 and ((i - pointer) % n) < remainder:
                rbs += 1
            if rbs > 0:
                alloc[ue.name] = rbs
        return alloc, (pointer + 1) % n
        # Rashed-Step 15.E-09-18-2026-end

    def _trial_sinr_db(self, ue) -> float:
        """Estimate this UE's SINR *as if* it had the full carrier to
        itself right now, without registering anything - used purely to
        rank UEs for scheduling (both PF's priority metric and, if ever
        needed, admission checks). Reflects real current interference
        from any other already-registered transmitter (e.g. another
        licensed-NR gNB reusing the same channel with no coordination).
        """
        now = self.env.now
        trial = ActiveTx(
            tx_id=self.name,
            tx_pos=self.current_pos(),
            tx_start=now,
            rx_pos=ue.current_pos(),
            tx_power_dbm=self.config.tx_power_dbm,
            f_hz=self.config.f_ghz,
            pl_exp=self.config.pl_exp,
            t_end=now + self.slot_us,
            tech="NR",
            bandwidth_mhz=self.config.bandwidth_mhz,
            noise_figure_db=self.config.noise_figure_db,
        )
        return self.channel.sinr_db(trial)

    # Rashed-Step 15.E-09-18-2026-start
    def _trial_sinr_db_ul(self, ue) -> float:
        """UL counterpart to _trial_sinr_db() above - estimates this
        UE's UPLINK SINR (UE as transmitter, this gNB as receiver, at
        config.ue_tx_power_dbm) as if it had the whole carrier to
        itself right now. Used only to rank UL proportional-fair
        priority - see SlotScheduledAccess.allocate_ul()."""
        now = self.env.now
        trial = ActiveTx(
            tx_id=ue.name,
            tx_pos=ue.current_pos(),
            tx_start=now,
            rx_pos=self.current_pos(),
            tx_power_dbm=self.config.ue_tx_power_dbm,
            f_hz=self.config.f_ghz,
            pl_exp=self.config.pl_exp,
            t_end=now + self.slot_us,
            tech="NR",
            bandwidth_mhz=self.config.bandwidth_mhz,
            noise_figure_db=self.config.noise_figure_db,
        )
        return self.channel.sinr_db(trial)
    # Rashed-Step 15.E-09-18-2026-end

    # Rashed-Step 15.F-09-18-2026-start
    def rrc_uplink_delay(self, ue):
        """
        RRC attach's technology-specific uplink-access-delay hook (see
        ran/protocol/rrc.py's RrcLayer.attach()).
        """
        # Rashed-Step 16.A-10-02-2026-start
        # Was config.sr_to_grant_delay_us (15.F) - see
        # Config_NRL.rrc_ul_grant_delay_us for why RRC now has its own
        # grant delay.
        yield self.env.timeout(self.config.rrc_ul_grant_delay_us)
        # Rashed-Step 16.A-10-02-2026-end
    # Rashed-Step 15.F-09-18-2026-end

    def _proportional_fair_allocation(self) -> Dict[str, int]:
        """Classic PF: priority = instantaneous achievable rate / running
        average rate. The single highest-priority UE gets the whole
        slot's resource blocks (matches how PF is usually described/
        implemented - one winner per scheduling interval), then its
        average-rate tracker is updated via EMA; everyone else's tracker
        decays toward 0 for this slot (they got nothing)."""
        # Rashed-Step 15.E-09-18-2026-start
        # UPGRADE (pure refactor, zero behavior change): same extraction
        # as _round_robin_allocation() above - see that method's
        # comment. This method is now a one-line wrapper; test/
        # test_nr_licensed.py's direct calls are unaffected.
        return self._proportional_fair_allocation_for(self.ue_list, self._pf_avg_rate)

    def _proportional_fair_allocation_for(self, candidate_ues: list, avg_rate: Dict[str, float],
                                           trial_sinr_fn=None) -> Dict[str, int]:
        trial_sinr_fn = trial_sinr_fn if trial_sinr_fn is not None else self._trial_sinr_db
        if not candidate_ues or self.total_rbs == 0:
            return {}
        best_ue = None
        best_priority = -math.inf
        best_inst_rate = 0.0
        for ue in candidate_ues:
            sinr = trial_sinr_fn(ue)
            mcs = select_mcs_for_sinr(sinr)
            eff = NR_MCS_TABLE[mcs][1] if mcs is not None else 0.0
            inst_rate = eff * (self.total_rbs * self.rb_bandwidth_hz)
            avg = avg_rate.get(ue.name, 1.0)
            priority = inst_rate / avg if avg > 0 else inst_rate
            if priority > best_priority:
                best_priority = priority
                best_ue = ue
                best_inst_rate = inst_rate

        alpha = self.config.pf_alpha
        for ue in candidate_ues:
            achieved = best_inst_rate if ue is best_ue else 0.0
            prev = avg_rate.get(ue.name, 1.0)
            avg_rate[ue.name] = (1 - alpha) * prev + alpha * achieved

        return {best_ue.name: self.total_rbs} if best_ue is not None else {}
        # Rashed-Step 15.E-09-18-2026-end

    # Rashed-Step 15.A-09-18-2026-start
    # UPGRADE (pure refactor, zero behavior change): delegates to
    # ran.protocol.channel_access.SlotScheduledAccess.allocate(), which
    # runs the exact same if/else dispatch this method used to run
    # inline. Kept as a real method (not deleted) since run_one_slot()
    # and anything else already calling self._allocate_rbs() keeps
    # working unmodified.
    def _allocate_rbs(self) -> Dict[str, int]:
        return self._channel_access.allocate(self)
    # Rashed-Step 15.A-09-18-2026-end

    # Rashed-Step 13.E.3-08-23-2026-start
    def _make_packet(self, destination: str) -> Packet:
        """Synthesize a fresh Packet for one UE's slot allocation - same
        "standalone placeholder, nothing downstream reads payload_bytes"
        rationale as nru.Gnb._make_packet()."""
        self._packet_seq += 1
        return Packet(
            packet_id=f"{self.name}-{self._packet_seq:06d}",
            source=self.name,
            destination=destination,
            payload_bytes=self.config.packet_payload_bytes,
            header_bytes=0,
            created_at=self.env.now,
        )

    def current_mcs_for_ue(self, ue_name: str) -> Optional[int]:
        """
        The AHEAD-OF-TIME MCS to transmit this UE's next slot at, or
        None to signal "use the existing oracle/post-hoc pick instead"
        (rate_adapt_enabled=False, or this UE has no prior measurement
        yet - the natural bootstrap case, same "no measurement yet"
        fallback every other technology's rate adaptation already has).

        When config.sinr_predictor is set AND this UE's link already
        has >= predictor.lag_k measurements with genuine variation (the
        same constant-link safety guard as Config_NR.sinr_predictor /
        wifi.Config.sinr_predictor - Step 13.D-fix/13.E.1-fix), the pick
        is based on the predictor's PREDICTED next SINR instead of the
        raw last-measured value.
        """
        if not self.config.rate_adapt_enabled:
            return None
        state = self.link_state.get(ue_name)
        if state is None or state.get("last_sinr_db") is None:
            return None
        predictor = self.config.sinr_predictor
        if predictor is not None:
            history = state.get("sinr_history", [])
            if len(history) >= predictor.lag_k and len(set(history[-predictor.lag_k:])) > 1:
                predicted = predictor.predict_next(history, technology_is_wifi=0)
                return select_mcs_for_sinr(predicted)
        return select_mcs_for_sinr(state["last_sinr_db"])

    def record_link_result(self, ue_name: str, measured_sinr_db: float) -> None:
        """Update this UE's ahead-of-time rate-adaptation state. No-op
        when rate_adapt_enabled is False (keeps link_state empty in that
        case, not just unused)."""
        if not self.config.rate_adapt_enabled:
            return
        state = self.link_state.setdefault(ue_name, {"last_sinr_db": None, "sinr_history": []})
        state["last_sinr_db"] = measured_sinr_db
        history = state.setdefault("sinr_history", [])
        history.append(measured_sinr_db)
        del history[:-8]
    # Rashed-Step 13.E.3-08-23-2026-end

    # -------------------------------------------------------------
    # One slot: register a transmission per scheduled UE, wait out the
    # slot, then settle SINR/MCS/throughput for each - mirrors the
    # try/except BaseException pattern used in wifi.WiFi.send_frame()/
    # nru.Gnb.send_transmission() (Step 5.I/6.A) so a GeneratorExit at
    # simulation shutdown doesn't try to yield again mid-cleanup.
    # -------------------------------------------------------------
    def run_one_slot(self):
        # Rashed-Step 15.E-09-18-2026-start
        # UPGRADE (opt-in, byte-identical when off): this method's ENTIRE
        # pre-15.E body is now _run_dl_slot() below, a pure rename - see
        # that method's own comment. config.tdd_enabled=False (the
        # default) means every slot is scheduled as downlink exactly as
        # before this step, unconditionally - no TDD pattern, no UL, no
        # behavior change whatsoever for any existing licensed-NR run.
        if not self.config.tdd_enabled:
            yield from self._run_dl_slot()
            return
        direction = self.config.tdd_pattern[self._slot_index % len(self.config.tdd_pattern)]
        self._slot_index += 1
        if direction == "U":
            yield from self._run_ul_slot()
        else:
            yield from self._run_dl_slot()
        # Rashed-Step 15.E-09-18-2026-end

    def _run_dl_slot(self):
        # Rashed-Step 15.G-09-18-2026-start
        # Scheduler/RRC integration: only schedule UEs that are RRC-
        # CONNECTED (or never opted into RRC at all - getattr(...,
        # RrcState.CONNECTED) default preserves every pre-15.F/15.G
        # UE's existing "always eligible" behavior). Uses the new
        # allocate_dl_for() (candidate-set-parametrized, mirrors 15.E's
        # allocate_ul()) instead of _allocate_rbs()/allocate()'s zero-
        # arg dispatch, so the already directly-unit-tested
        # _round_robin_allocation()/_proportional_fair_allocation()
        # methods themselves stay completely untouched (test/
        # test_nr_licensed.py's direct calls keep working exactly as
        # before - see channel_access.py's allocate_dl_for() docstring
        # for the full reasoning). Byte-identical to the old
        # self._allocate_rbs() call whenever no UE in ue_list has
        # rrc_enabled=True (candidate_ues == self.ue_list in that case).
        candidate_ues = [
            ue for ue in self.ue_list
            if getattr(ue, "rrc_state", RrcState.CONNECTED) is RrcState.CONNECTED
        ]
        alloc = self._channel_access.allocate_dl_for(self, candidate_ues)
        # Rashed-Step 15.G-09-18-2026-end
        if not alloc:
            yield self.env.timeout(self.slot_us)
            return

        ue_by_name = {ue.name: ue for ue in self.ue_list}
        now = self.env.now
        # Rashed-Step 13.E.3-08-23-2026-start
        # (ActiveTx, rb_count, Packet, ahead-of-time chosen mcs or None)
        # - the chosen-mcs is decided HERE, before the slot's real SINR
        # is known, so it can be genuinely wrong (see current_mcs_for_ue()
        # docstring / Config_NRL.rate_adapt_enabled's comment).
        txs: List[Tuple[ActiveTx, int, Packet, Optional[int]]] = []
        # Rashed-Step 13.E.3-08-23-2026-end
        for ue_name, rb_count in alloc.items():
            ue = ue_by_name[ue_name]
            bw_mhz_this_ue = self.config.bandwidth_mhz * (rb_count / self.total_rbs)
            # Constant power-spectral-density split: this UE's tx power
            # scales down with its bandwidth share, same as a real gNB
            # splitting total transmit power across the RBs it's using
            # (so SINR is roughly independent of RB share - only the
            # number of RBs, and therefore throughput, changes).
            tx_power_dbm_this_ue = self.config.tx_power_dbm + 10.0 * math.log10(rb_count / self.total_rbs)
            # Rashed-Step 13.E.3-08-23-2026-start
            packet = self._make_packet(ue_name)
            chosen_mcs = self.current_mcs_for_ue(ue_name)
            # Rashed-Step 13.E.3-08-23-2026-end
            tx = ActiveTx(
                tx_id=self.name,
                tx_pos=self.current_pos(),
                tx_start=now,
                rx_pos=ue.current_pos(),
                tx_power_dbm=tx_power_dbm_this_ue,
                f_hz=self.config.f_ghz,
                pl_exp=self.config.pl_exp,
                t_end=now + self.slot_us,
                tech="NR",
                bandwidth_mhz=bw_mhz_this_ue,
                noise_figure_db=self.config.noise_figure_db,
                # Rashed-Step 13.E.3-08-23-2026-start
                packet=packet,
                # Rashed-Step 13.E.3-08-23-2026-end
            )
            self.channel.register_tx(tx)
            # Rashed-Step 13.E.3-08-23-2026-start
            txs.append((tx, rb_count, packet, chosen_mcs))
            # Rashed-Step 13.E.3-08-23-2026-end

        try:
            yield self.env.timeout(self.slot_us)
            for tx, rb_count, packet, chosen_mcs in txs:
                ue_name = packet.destination
                sinr = self.channel.sinr_db(tx)
                # Rashed-Step 13.E.3-08-23-2026-start
                # Log measured SINR on the packet itself, success or
                # failure alike - same convention as every other
                # technology's Step 13.A site. Update this UE's ahead-
                # of-time state for FUTURE slots regardless of how this
                # slot resolves (no-op when rate_adapt_enabled is False).
                packet.measured_sinr_db = sinr
                self.record_link_result(ue_name, sinr)

                if chosen_mcs is not None:
                    # Ahead-of-time pick was made (rate_adapt_enabled,
                    # and this UE already had prior history) - check
                    # whether the REAL measured SINR actually clears the
                    # CHOSEN mcs's threshold. A wrong guess is a genuine
                    # failure here, even if a lower mcs would have
                    # worked - this is what makes ahead-of-time
                    # adaptation fallible, unlike the oracle fallback
                    # below.
                    required_db = NR_MCS_TABLE[chosen_mcs][0]
                    if sinr >= required_db:
                        mcs = chosen_mcs
                    else:
                        mcs = None
                else:
                    # rate_adapt_enabled=False, or no history yet for
                    # this UE (bootstrap) - exact pre-13.E.3 oracle/
                    # post-hoc behavior, byte-identical when
                    # rate_adapt_enabled is False.
                    mcs = select_mcs_for_sinr(sinr)

                if mcs is not None:
                    eff = NR_MCS_TABLE[mcs][1]
                    bits = eff * (rb_count * self.rb_bandwidth_hz) * (self.slot_us / 1e6)
                    self.sent_completed(bits)
                    packet.status = "DELIVERED"
                    packet.delivered_at = self.env.now
                    log(self, f"UE {tx.rx_pos} slot OK: SINR={sinr:.2f} dB, MCS={mcs}, RBs={rb_count}, bits={bits:.0f}")
                else:
                    self.sent_failed()
                    packet.status = "DROPPED"
                    log(self, f"UE {tx.rx_pos} slot FAILED: SINR={sinr:.2f} dB below MCS0 threshold")
                self.packet_log.append(packet)
                self.channel.unregister_tx(tx, success=(mcs is not None))
                # Rashed-Step 13.E.3-08-23-2026-end
        except BaseException:
            for tx, _rb_count, _packet, _chosen_mcs in txs:
                self.channel.unregister_tx(tx, success=False)
            raise

    # Rashed-Step 15.E-09-18-2026-start
    def _run_ul_slot(self):
        """
        Grant-based uplink for one TDD 'U' slot. Unlike WiFiSTA/NrUE's
        autonomous-contention uplinks (Steps 15.B/15.C, each UE decides
        FOR ITSELF when to transmit via its own backoff/LBT process),
        licensed NR's uplink is grant-based - this gNB decides who
        transmits and with how many RBs, exactly like it already does
        for downlink in _run_dl_slot(). So the UE object stays passive
        here too (see NrUeLicensed's class docstring): this method
        drives the ENTIRE uplink transmission - registering each
        granted UE's ActiveTx (tx_id/tx_pos are the UE's, not this
        gNB's - the UE IS the transmitter here), waiting out the slot,
        then settling SINR/MCS/success exactly like the DL path does.

        Candidates: UEs with uplink_enabled=True whose one-time
        SchedulingRequest->grant-eligibility delay has already elapsed
        (ue.ul_ready - see NrUeLicensed._send_scheduling_request()).
        Not yet supported: ahead-of-time rate adaptation for UL (always
        uses the oracle/post-hoc select_mcs_for_sinr(), same as DL's
        rate_adapt_enabled=False path) - a deferred follow-up, mirroring
        every other uplink sub-step's own first-cut scope-out.
        """
        candidate_ues = [
            ue for ue in self.ue_list
            if getattr(ue, "uplink_enabled", False) and getattr(ue, "ul_ready", False)
            # Rashed-Step 15.G-09-18-2026-start
            # Same rrc_state==CONNECTED (or never-opted-in) filter as
            # _run_dl_slot() above - a granted, ul_ready UE still can't
            # actually be scheduled for real uplink data until its RRC
            # attach has finished (see this module's own class
            # docstring update for Step 15.G).
            and getattr(ue, "rrc_state", RrcState.CONNECTED) is RrcState.CONNECTED
            # Rashed-Step 15.G-09-18-2026-end
        ]
        if not candidate_ues:
            yield self.env.timeout(self.slot_us)
            return

        alloc = self._channel_access.allocate_ul(self, candidate_ues)
        if not alloc:
            yield self.env.timeout(self.slot_us)
            return

        ue_by_name = {ue.name: ue for ue in candidate_ues}
        now = self.env.now
        txs: List[Tuple[ActiveTx, int, Packet]] = []
        for ue_name, rb_count in alloc.items():
            ue = ue_by_name[ue_name]
            bw_mhz_this_ue = self.config.bandwidth_mhz * (rb_count / self.total_rbs)
            # Same constant-PSD power split as DL, off the UE's own
            # (smaller) max power - see Config_NRL.ue_tx_power_dbm.
            tx_power_dbm_this_ue = self.config.ue_tx_power_dbm + 10.0 * math.log10(rb_count / self.total_rbs)
            packet = self._make_packet_ul(ue_name)
            tx = ActiveTx(
                tx_id=ue_name,
                tx_pos=ue.current_pos(),
                tx_start=now,
                rx_pos=self.current_pos(),
                tx_power_dbm=tx_power_dbm_this_ue,
                f_hz=self.config.f_ghz,
                pl_exp=self.config.pl_exp,
                t_end=now + self.slot_us,
                tech="NR",
                bandwidth_mhz=bw_mhz_this_ue,
                noise_figure_db=self.config.noise_figure_db,
                packet=packet,
            )
            self.channel.register_tx(tx)
            txs.append((tx, rb_count, packet))

        try:
            yield self.env.timeout(self.slot_us)
            for tx, rb_count, packet in txs:
                sinr = self.channel.sinr_db(tx)
                packet.measured_sinr_db = sinr
                mcs = select_mcs_for_sinr(sinr)
                if mcs is not None:
                    eff = NR_MCS_TABLE[mcs][1]
                    bits = eff * (rb_count * self.rb_bandwidth_hz) * (self.slot_us / 1e6)
                    self.sent_completed_ul(bits)
                    packet.status = "DELIVERED"
                    packet.delivered_at = self.env.now
                    log(self, f"UL UE {tx.tx_id} slot OK: SINR={sinr:.2f} dB, MCS={mcs}, RBs={rb_count}, bits={bits:.0f}")
                else:
                    self.sent_failed_ul()
                    packet.status = "DROPPED"
                    log(self, f"UL UE {tx.tx_id} slot FAILED: SINR={sinr:.2f} dB below MCS0 threshold")
                self.packet_log.append(packet)
                self.channel.unregister_tx(tx, success=(mcs is not None))
        except BaseException:
            for tx, _rb_count, _packet in txs:
                self.channel.unregister_tx(tx, success=False)
            raise

    def _make_packet_ul(self, ue_name: str) -> Packet:
        """UL counterpart to _make_packet() - direction reversed (UE is
        source, this gNB is destination)."""
        self._packet_seq += 1
        return Packet(
            packet_id=f"{self.name}-UL-{self._packet_seq:06d}",
            source=ue_name,
            destination=self.name,
            payload_bytes=self.config.packet_payload_bytes,
            header_bytes=0,
            created_at=self.env.now,
        )

    def sent_completed_ul(self, bits: float):
        """UL counterpart to sent_completed() - shares the channel-level
        aggregate NRL counters (same convention as nru.py's Step 15.C:
        Gnb/NrUE share channel.succeeded_transmissions_NR) but keeps
        its own gNB-object-level counters (succeeded_transmissions_ul/
        failed_transmissions_ul/bits_delivered_ul) separate from DL's
        (succeeded_transmissions/failed_transmissions/bits_delivered),
        so direction is still distinguishable at the gNB-object level."""
        self.channel.succeeded_transmissions_NRL += 1
        self.succeeded_transmissions_ul += 1
        self.bits_delivered_ul += bits

    def sent_failed_ul(self):
        self.channel.failed_transmissions_NRL += 1
        self.failed_transmissions_ul += 1
    # Rashed-Step 15.E-09-18-2026-end

    def sent_completed(self, bits: float):
        self.channel.succeeded_transmissions_NRL += 1
        self.succeeded_transmissions += 1
        self.bits_delivered += bits

    def sent_failed(self):
        self.channel.failed_transmissions_NRL += 1
        self.failed_transmissions += 1
# Rashed-Step 6.B-07-31-2026-end
