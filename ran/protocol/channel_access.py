# Rashed-Step 15.A-09-18-2026-start
"""
ChannelAccessStrategy: a shared abstraction over the two channel-access
mechanisms this simulator already implements - NR-U's Cat-4 LBT
(nru/nru.py's Gnb.wait_back_off_gap_after()) and licensed NR's
slot-by-slot RR/PF scheduler (nr/nr.py's GnbLicensedNR._allocate_rbs()).

Project details/Step pre_15.txt's Phase 1 (sub-step 15.A) asked for
this to be a PURE REFACTOR - the exact existing behavior of each
technology, extracted behind one shared interface, not a redesign.
Concretely:

  - LbtChannelAccess.wait() is a parametrized move of Gnb.wait_back_
    off_gap_after()'s body - same reads (config timing fields,
    channel.is_busy(), current position, sync-slot boundary), same
    yields in the same order, so the exact same simulated events
    happen at the exact same simulated times as before this refactor.
    nru.py's Gnb now just delegates to it (see Gnb.__init__/
    wait_back_off_gap_after()).

  - SlotScheduledAccess.allocate() is a thin delegator to
    GnbLicensedNR's own (UNMOVED) _round_robin_allocation()/
    _proportional_fair_allocation() methods, via the same if/else
    _allocate_rbs() already used. Those two methods were deliberately
    NOT relocated out of nr/nr.py - test/test_nr_licensed.py calls them
    directly on the gNB instance (e.g. gnb._round_robin_allocation())
    and must keep working completely unmodified.

REAL-WORLD SCOPE FOUND WHILE BUILDING THIS (2026-09-18): nru.py
actually has THREE backoff/gap-related methods on Gnb, not one -
wait_back_off_gap() and wait_back_off() are BOTH dead code today.
common.common.gap is a hardcoded module-level constant (gap = True,
never toggled by any CLI flag or config anywhere in this repo), and
Gnb.start() only ever calls wait_back_off_gap_after() (the `if gap:`
branch) - wait_back_off_gap() (a DIFFERENT method despite the similar
name) has its own call site commented out in start() ("#self.process =
... wait_back_off_gap()"), and Gnb.wait_back_off() (the `else`
branch) is unreachable since gap is never False anywhere in this repo.
Both are left completely untouched here - deleting genuinely dead code
is a separate, smaller Phase-0-style cleanup item, out of scope for
this refactor, which is scoped tightly to "extract what's actually
live" to keep it minimal and easy to verify byte-identical.
wait_back_off_gap_after() is the ONLY live NR-U backoff/gap
implementation as of this step, and is what LbtChannelAccess below
actually extracts.

Future sub-steps build on this shared shape: 15.C gives NrUE its own
real LBT transmit path by using LbtChannelAccess the same way Gnb does
(both duck-type against the same attributes: env, channel,
current_pos(), name, a Cat-4-LBT-shaped config, failed_transmissions_
in_row, next_sync_slot_boundry, cw_min/cw_max). 15.E gives licensed NR
real uplink scheduling by adding a UL-side counterpart alongside
SlotScheduledAccess's existing DL delegation.
"""
import random
from typing import Any, Dict

from common.common import log


# Rashed-Step pre_20.D.1-10-08-2026-start
# 3GPP TS 37.213 channel access priority classes (CAPC) p -> (m_p,
# CW_min,p, CW_max,p, T_mcot,p in ms). Defer Td = 16us + m_p x 9us; the
# backoff N is drawn from [0, CW_p], CW_p stepping (CW_min+1) x 2^k - 1
# up to CW_max (generate_backoff_slots below). Downlink: Table 4.1.1-1
# (T_mcot 8 ms for p = 3, 4 - 10 ms only if no other technology can
# share the carrier). Uplink: Table 4.2.1-1 (6 ms for p = 3, 4).
CAPC_DL = {1: (1, 3, 7, 2), 2: (1, 7, 15, 3), 3: (3, 15, 63, 8), 4: (7, 15, 1023, 8)}
CAPC_UL = {1: (2, 3, 7, 2), 2: (2, 7, 15, 4), 3: (3, 15, 1023, 6), 4: (7, 15, 1023, 6)}

# Rashed-Step pre_20.D.1-10-08-2026-end

# Rashed-Step pre_20.D.2-10-08-2026-start
def ts37213_ed_threshold_dbm(tx_power_dbm: float, bandwidth_mhz: float = 20.0, t_a_db: float = 10.0,
                             p_h_dbm: float = 23.0) -> float:
    """
    Maximum energy-detection threshold of 3GPP TS 37.213 clause 4.1.5,
    for when the absence of any other technology on the carrier cannot
    be guaranteed (the coexistence case):
      X = max{ -72 + 10 log10(BW/20),
               min{ T_max, T_max - T_A + (P_H + 10 log10(BW/20) - P_TX) } }
    T_max = 10 log10(3.16228e-8 mW/MHz x BW) = -75 dBm/MHz + 10 log10(BW);
    T_A = 10 dB for transmissions with PDSCH (5 dB discovery-only);
    P_H = 23 dBm; P_TX = the node's maximum output power. At 20 MHz and
    23 dBm this is -72 dBm (the long-standing default); lower power
    raises it 1 dB per dB up to T_max (-62 dBm); it never goes below
    -72 dBm (+ bandwidth term).
    """
    import math
    bw_db = 10.0 * math.log10(bandwidth_mhz / 20.0)
    t_max = -75.0 + 10.0 * math.log10(bandwidth_mhz)
    return max(-72.0 + bw_db, min(t_max, t_max - t_a_db + (p_h_dbm + bw_db - tx_power_dbm)))

# Rashed-Step pre_20.D.2-10-08-2026-end

def generate_backoff_slots(failed_transmissions_in_row: int, cw_min: int, cw_max: int) -> int:
    """
    Pure Cat-4 LBT backoff-slot draw (3GPP-style binary-exponential
    contention window) - extracted verbatim from nru.py's Gnb.
    generate_backoff_slots(): same formula, same single random.randint()
    draw, just parametrized on cw_min/cw_max instead of reading them
    off self. Gnb.generate_backoff_slots() itself is UNCHANGED (still a
    real method, kept for anything that calls it directly) but its body
    now delegates here - see nru/nru.py.
    """
    upper_limit = pow(2, failed_transmissions_in_row) * (cw_min + 1) - 1
    upper_limit = upper_limit if upper_limit <= cw_max else cw_max
    return random.randint(0, upper_limit)


# Rashed-Step pre_18.E-10-05-2026-start
def sense_idle_for(node: Any, duration: float, busy):
    """
    Generator -> True if the channel stays idle (busy() False) from now
    until now + duration, False as soon as it turns busy before that.
    Event-driven: wakes on every node.channel.state_changed, so a
    transmission that starts at any instant is noticed at once - not
    only at the next fixed sensing step. Something that starts EXACTLY
    at the end counts as idle (the same-slot rule: both sides go ahead
    and collide, whatever order the simulator processes them in).
    Shared by DcfChannelAccess (Wi-Fi, pre_18.D) and LbtChannelAccess
    (NR-U, pre_18.E).
    """
    env = node.env
    end = env.now + duration
    if duration <= 0:
        return True
    if busy():
        return False
    while True:
        yield env.timeout(end - env.now) | node.channel.state_changed
        if env.now >= end:
            return True
        if busy():
            return False
# Rashed-Step pre_18.E-10-05-2026-end


class LbtChannelAccess:
    """
    NR-U's Cat-4 LBT channel-access wait: a prioritization period
    (deterministic period + M observation slots) plus a Cat-4 backoff,
    sensed with freeze-on-busy/resume-on-idle semantics, followed by
    waiting out the remaining time to the next NR-U synchronization
    slot boundary (also freeze-on-busy) before the caller is allowed to
    transmit. Extracted from nru.py's Gnb.wait_back_off_gap_after() -
    see this module's own docstring for why that's the only live NR-U
    backoff/gap method as of Step 15.A.

    Stateless (holds no per-node data of its own - every value it reads
    lives on the `node` argument, exactly as it did before this
    refactor when it was a bound method), so one shared instance can
    safely serve every node using this strategy.
    """

    def wait(self, node: Any):
        """
        `node` must expose: env (simpy.Environment), channel
        (channel.Channel), current_pos() -> Pos, name: str,
        failed_transmissions_in_row: int, next_sync_slot_boundry:
        float, cw_min/cw_max: int, and a config object exposing
        deter_period/M/observation_slot_duration/ed_threshold_dbm/
        f_ghz/bandwidth_mhz/synchronization_slot_duration (Config_NR's
        shape) as `node.config_nr`. nru.py's Gnb satisfies this today;
        15.C gives NrUE the same shape so it can reuse this unchanged.

        Generator. (Until pre_18.E this was a byte-identical move of the
        original Gnb.wait_back_off_gap_after(); see below for what
        pre_18.E changed.)

        Rashed-Step pre_18.E (2026-10-05) - 3GPP TS 37.213 Type 1 channel
        access. The defer period Td = deter_period + M x slot (16 + 3x9 =
        43us, priority class 3) must be sensed idle in full before the
        countdown starts AND again after every busy period; the backoff
        then counts down one observation slot at a time, freezing as soon
        as the channel turns busy (event-driven sensing - sense_idle_for).
        Before, Td was just the first part of one countdown that resumed
        after a busy period without re-sensing Td, and the channel was
        only checked at the start of each 9us step - the same shortcut
        the old Wi-Fi loop had (fixed in pre_18.D). Once Wi-Fi did a fresh
        DIFS after every busy period and NR-U did not, NR-U regained the
        channel about one defer period earlier after every Wi-Fi
        transmission (DTMC validation: NR-U 2-5 points above the model).
        The model charges a defer after every busy period on both sides.
        Same backoff draw (generate_backoff_slots) as before.
        """
        config = node.config_nr

        # Rashed-Step pre_18.E-10-05-2026-start
        def busy():
            return node.channel.is_busy(node.current_pos(), config.ed_threshold_dbm, exclude_tx_id=node.name,
                                        sense_f_hz=config.f_ghz, sense_bw_mhz=config.bandwidth_mhz)

        # Rashed-Step pre_20.D.1-10-08-2026-start
        # A node with its own m_p (a UE on the uplink CAPC table) sets lbt_m;
        # everyone else uses config.M as before.
        m_p = getattr(node, "lbt_m", None)
        m_p = config.M if m_p is None else m_p
        # Rashed-Step pre_20.D.1-10-08-2026-end
        defer_us = config.deter_period + m_p * config.observation_slot_duration
        backoff_slots = generate_backoff_slots(node.failed_transmissions_in_row, node.cw_min, node.cw_max)
        while True:
            while busy():
                yield node.channel.state_changed
            if not (yield from sense_idle_for(node, defer_us, busy)):
                continue
            while backoff_slots > 0:
                if not (yield from sense_idle_for(node, config.observation_slot_duration, busy)):
                    log(node, f"Channel busy during backoff, frozen with {backoff_slots} slots left - fresh defer period next")
                    break
                backoff_slots -= 1
            else:
                break
        # Rashed-Step pre_18.E-10-05-2026-end

        time_to_next_sync_slot = node.next_sync_slot_boundry - node.env.now
        while time_to_next_sync_slot <= 0:
            time_to_next_sync_slot += config.synchronization_slot_duration
            log(node, f'Backoff finished but next sync slot was in the past, new time to next possible sync = {time_to_next_sync_slot}')

        gap_remaining = time_to_next_sync_slot
        log(node, f"Starting gap period of : {gap_remaining} us")
        # Rashed-Step pre_18.E-10-05-2026-start
        # Same meaning as before (freeze on busy, resume the remaining gap
        # - the DTMC gap states self-loop with pg, no re-defer), but
        # event-driven: a transmission starting mid-step is noticed at
        # once instead of at the next 9us check.
        while gap_remaining > 0:
            while busy():
                log(node, f"Channel busy during gap, pausing gap with {gap_remaining} us remaining")
                yield node.channel.state_changed
            started = node.env.now
            idle = yield from sense_idle_for(node, gap_remaining, busy)
            gap_remaining = 0 if idle else gap_remaining - (node.env.now - started)
        # Rashed-Step pre_18.E-10-05-2026-end

        log(node, "Finished GAP-after-backoff (reached sync boundary)")
        return


# Rashed-Step pre_18.D-10-05-2026-start
class DcfChannelAccess:
    """
    Wi-Fi legacy DCF channel-access wait (DIFS + backoff) on a SHARED slot
    grid - Step pre_18.D (Project details/Step pre_18.txt).

    Why: 802.11 DCF, and the DTMC/Bianchi models, assume all stations count
    backoff slots on the same grid, so two stations can only collide when
    they finish in the same slot (they start at the same instant); a
    station whose slot ends later has already sensed the earlier one and
    frozen. The old wifi.py/sta.py wait_back_off() counted slots on each
    station's own grid, checked the channel only at the start of each of
    its slots, and transmitted after the last one without re-checking -
    so it missed a neighbour that started a few microseconds earlier
    (measured: ~3/4 of Wi-Fi/Wi-Fi collisions started 1-9us apart, ~2x
    the model's collision rate).

    How: (1) wait until the channel is idle; (2) DIFS with the channel
    continuously idle; (3) wait for the next GLOBAL slot boundary (t a
    multiple of Times.t_slot) - the DTMC's own slotted time; (4) count the
    backoff down one global slot at a time. Sensing is event-driven
    (wakes on every channel.state_changed), so a transmission that starts
    any time inside a slot is noticed at once; the station freezes, and
    after the channel clears it does a fresh DIFS (802.11 behaviour - the
    old code resumed without one). A transmission starting EXACTLY on the
    boundary where this station's slot ends is the same-slot case: both
    transmit and collide, whatever order the simulator processes them in.

    Why a global grid rather than one anchored at "idle + DIFS": in this
    simulator the sender waits for its ACK (44us) without the ACK being on
    the channel, so other stations would anchor 44us earlier than the
    sender - 44 is not a multiple of 9, the grids would drift again.
    A global grid sidesteps that and is exactly the model's assumption.
    Cost: up to t_slot-1 us of extra waiting after DIFS.

    Stateless; node must expose env, channel, current_pos(), name and
    config.ed_threshold_dbm / f_ghz / bandwidth_mhz (wifi.WiFi and
    wifi.sta.WiFiSTA both do).
    """

    def __init__(self, t_slot_us: float, t_difs_us: float):
        self.t_slot_us = t_slot_us
        self.t_difs_us = t_difs_us

    @staticmethod
    def _busy(node: Any) -> bool:
        cfg = node.config
        # Rashed-Step pre_20.A-10-08-2026-start
        pd = getattr(cfg, "preamble_detect_dbm", None)
        if pd is not None:
            return node.channel.is_busy_wifi(node.current_pos(), cfg.ed_threshold_dbm, pd, exclude_tx_id=node.name,
                                             sense_f_hz=cfg.f_ghz, sense_bw_mhz=cfg.bandwidth_mhz)
        # Rashed-Step pre_20.A-10-08-2026-end
        # Rashed-Step 20.A-10-08-2026-start
        # MAC exchange without preamble detection: still honour NAVs
        # (decodable from -82 dBm).
        if getattr(cfg, "mac_exchange", False) and node.channel.nav_busy(
                node.current_pos(), -82.0, node.name, cfg.f_ghz, cfg.bandwidth_mhz):
            return True
        # Rashed-Step 20.A-10-08-2026-end
        return node.channel.is_busy(node.current_pos(), cfg.ed_threshold_dbm, exclude_tx_id=node.name,
                                    sense_f_hz=cfg.f_ghz, sense_bw_mhz=cfg.bandwidth_mhz)

    def _idle_for(self, node: Any, duration: float):
        """See sense_idle_for() (shared with LbtChannelAccess since pre_18.E)."""
        return (yield from sense_idle_for(node, duration, lambda: self._busy(node)))

    def wait(self, node: Any, backoff_slots: int):
        """Generator - returns when `node` may transmit (see class doc)."""
        env = node.env
        while True:
            while self._busy(node):
                yield node.channel.state_changed
            # Rashed-Step 20.A-10-08-2026-start
            ifs = self.t_difs_us
            if getattr(node.config, "mac_exchange", False):
                from wifi.mac import EIFS_US
                pd = getattr(node.config, "preamble_detect_dbm", None)
                if node.channel.eifs_applies(node.current_pos(), -82.0 if pd is None else pd, node.name):
                    ifs = EIFS_US
                    node.mac_stats["eifs"] += 1
            # Rashed-Step 20.A-10-08-2026-end
            if not (yield from self._idle_for(node, ifs)):  # 20.A: EIFS or DIFS
                continue
            to_grid = (self.t_slot_us - env.now % self.t_slot_us) % self.t_slot_us
            if not (yield from self._idle_for(node, to_grid)):
                continue
            while backoff_slots > 0:
                if not (yield from self._idle_for(node, self.t_slot_us)):
                    break
                backoff_slots -= 1
            else:
                return
            log(node, f"Channel busy during backoff, frozen with {backoff_slots} slots left")
# Rashed-Step pre_18.D-10-05-2026-end


class SlotScheduledAccess:
    """
    Licensed NR's per-slot RB scheduler dispatch: round-robin or
    proportional-fair, selected by scheduler.config.scheduler. A thin
    delegator, deliberately - GnbLicensedNR._round_robin_allocation()/
    _proportional_fair_allocation() themselves are NOT moved here (see
    this module's own docstring for why: test/test_nr_licensed.py calls
    them directly on the gNB instance and must keep working
    unmodified). This class just formalizes _allocate_rbs()'s existing
    if/else dispatch behind the same ChannelAccessStrategy shape
    LbtChannelAccess above uses, so future UL scheduling (15.E) and
    NR-U SCell integration (Phase 7) have one consistent interface to
    add a second implementation against, instead of each reinventing
    its own ad hoc dispatch.
    """

    def allocate(self, scheduler: Any) -> Dict[str, int]:
        """
        `scheduler` must expose: config.scheduler ("round_robin" or
        "proportional_fair"), _round_robin_allocation(),
        _proportional_fair_allocation() - GnbLicensedNR satisfies this
        today.
        """
        if scheduler.config.scheduler == "proportional_fair":
            return scheduler._proportional_fair_allocation()
        return scheduler._round_robin_allocation()

    # Rashed-Step 15.E-09-18-2026-start
    def allocate_ul(self, scheduler: Any, candidate_ues: list) -> Dict[str, int]:
        """
        UL counterpart to allocate() above - this class's own docstring
        anticipated exactly this ("future UL scheduling (15.E) ...
        have one consistent interface to add a second implementation
        against"). Same round_robin/proportional_fair dispatch, but
        against a caller-supplied candidate set (UEs with a pending
        SchedulingRequest that's been granted eligibility - see
        GnbLicensedNR._run_ul_slot()/NrUeLicensed's SR timer - not the
        gNB's whole ue_list) and the gNB's own UL-specific scheduler
        state (scheduler._rr_pointer_ul / scheduler._pf_avg_rate_ul,
        kept separate from DL's scheduler._rr_pointer /
        scheduler._pf_avg_rate since DL and UL rounds happen on
        different slots and coupling their rotation/fairness state
        would be a confusing, unintended cross-direction interaction).

        Reuses scheduler._round_robin_allocation_for()/
        _proportional_fair_allocation_for() - the pure, parametrized
        cores Step 15.E extracted from _round_robin_allocation()/
        _proportional_fair_allocation() (themselves left as thin
        zero-arg wrappers around these same cores, so test/
        test_nr_licensed.py's direct DL-only calls are unaffected) -
        specifically so this reuses the real DL algorithm rather than
        reimplementing a parallel copy of it.

        `scheduler` must additionally expose: _rr_pointer_ul: int,
        _pf_avg_rate_ul: Dict[str, float], _trial_sinr_db_ul(ue) - all
        new on GnbLicensedNR as of Step 15.E.
        """
        if scheduler.config.scheduler == "proportional_fair":
            return scheduler._proportional_fair_allocation_for(
                candidate_ues, scheduler._pf_avg_rate_ul,
                trial_sinr_fn=scheduler._trial_sinr_db_ul,
            )
        rr_alloc, scheduler._rr_pointer_ul = scheduler._round_robin_allocation_for(
            candidate_ues, scheduler._rr_pointer_ul
        )
        return rr_alloc
    # Rashed-Step 15.E-09-18-2026-end

    # Rashed-Step 15.G-09-18-2026-start
    def allocate_dl_for(self, scheduler: Any, candidate_ues: list) -> Dict[str, int]:
        """
        DL counterpart to allocate_ul() above, added for Step 15.G's
        "GnbLicensedNR's scheduler starts filtering ue_list by
        rrc_state == CONNECTED" requirement. allocate() (the zero-arg
        dispatch, still used wherever no filtering is needed/wanted)
        is DELIBERATELY left untouched - it still reads
        scheduler.ue_list unconditionally via
        _round_robin_allocation()/_proportional_fair_allocation(),
        exactly as test/test_nr_licensed.py's existing direct calls
        require (see this module's own class docstring and 15.E's
        identical reasoning for not touching those two methods).

        Reuses the SAME _round_robin_allocation_for()/
        _proportional_fair_allocation_for() cores allocate_ul() already
        reuses, against scheduler's DL-side state (scheduler._rr_
        pointer / scheduler._pf_avg_rate / scheduler._trial_sinr_db -
        the pre-existing DL trackers, NOT the UL-specific _ul ones), so
        RRC-filtered DL scheduling is byte-identical to the unfiltered
        allocate() path whenever candidate_ues == scheduler.ue_list
        (i.e. whenever no UE in this gNB's cell has rrc_enabled=True -
        see GnbLicensedNR._run_dl_slot()'s own getattr(ue, "rrc_state",
        RrcState.CONNECTED) backward-compat filter).
        """
        if scheduler.config.scheduler == "proportional_fair":
            return scheduler._proportional_fair_allocation_for(
                candidate_ues, scheduler._pf_avg_rate,
                trial_sinr_fn=scheduler._trial_sinr_db,
            )
        rr_alloc, scheduler._rr_pointer = scheduler._round_robin_allocation_for(
            candidate_ues, scheduler._rr_pointer
        )
        return rr_alloc
    # Rashed-Step 15.G-09-18-2026-end
# Rashed-Step 15.A-09-18-2026-end
