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

        Generator - same yield sequence/order as the original
        Gnb.wait_back_off_gap_after(), so callers see byte-identical
        simulated timing (and, since node.name/node.col are read the
        same way, byte-identical log output too).
        """
        config = node.config_nr
        pp = config.deter_period + config.M * config.observation_slot_duration
        backoff_slots = generate_backoff_slots(node.failed_transmissions_in_row, node.cw_min, node.cw_max)
        backoff_time = pp + backoff_slots * config.observation_slot_duration

        remaining = backoff_time
        while remaining > 0:
            if node.channel.is_busy(node.current_pos(), config.ed_threshold_dbm, exclude_tx_id=node.name,
                                     sense_f_hz=config.f_ghz, sense_bw_mhz=config.bandwidth_mhz):
                log(node, f"Channel busy during backoff, pausing backoff with {remaining} us remaining")
                yield node.channel.state_changed
                continue
            step = min(config.observation_slot_duration, remaining)
            yield node.env.timeout(step)
            remaining -= step

        time_to_next_sync_slot = node.next_sync_slot_boundry - node.env.now
        while time_to_next_sync_slot <= 0:
            time_to_next_sync_slot += config.synchronization_slot_duration
            log(node, f'Backoff finished but next sync slot was in the past, new time to next possible sync = {time_to_next_sync_slot}')

        gap_remaining = time_to_next_sync_slot
        log(node, f"Starting gap period of : {gap_remaining} us")
        while gap_remaining > 0:
            if node.channel.is_busy(node.current_pos(), config.ed_threshold_dbm, exclude_tx_id=node.name,
                                     sense_f_hz=config.f_ghz, sense_bw_mhz=config.bandwidth_mhz):
                log(node, f"Channel busy during gap, pausing gap with {gap_remaining} us remaining")
                yield node.channel.state_changed
                continue
            step = min(config.observation_slot_duration, gap_remaining)
            yield node.env.timeout(step)
            gap_remaining -= step

        log(node, "Finished GAP-after-backoff (reached sync boundary)")
        return


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
# Rashed-Step 15.A-09-18-2026-end
