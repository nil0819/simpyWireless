# Rashed-Step 15.E-09-18-2026-start
"""
Step 15.E unit tests: licensed NR's new opt-in TDD uplink (grant-based
SchedulingRequest -> eligibility -> RR/PF-scheduled UL transmission),
plus the pure-refactor extraction of _round_robin_allocation()/
_proportional_fair_allocation() into candidate-set-parametrized
_for() helpers that both DL (unchanged callers) and UL (new caller,
via SlotScheduledAccess.allocate_ul()) now share.

Same style/harness as test_nr_licensed.py/test_wifi_uplink.py/
test_nru_uplink.py: plain assert-based pytest-discovered functions, no
simulation_nr.py involved.
"""

import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import simpy

from channel.channel import Channel
from nr.nr import GnbLicensedNR, Config_NRL
from nr.ue import NrUeLicensed


def _make_channel(env, n_of_gnb=1):
    return Channel(
        tx_queue=simpy.PriorityResource(env, capacity=1),
        tx_lock=simpy.Resource(env, capacity=1),
        n_of_stations=0,
        n_of_gNB=n_of_gnb,
        backoffs={},
        airtime_data={},
        airtime_control={},
        airtime_data_NR={},
        airtime_control_NR={},
    )


def _make_gnb_with_uplink_ue(config=None, ue_pos=(10.0, 0.0), gnb_pos=(0.0, 0.0),
                              extra_ues=None):
    """Real (non-fake) GnbLicensedNR + one uplink_enabled=True
    NrUeLicensed (plus any extra_ues), wired the way simulation_nr.py's
    own construction order does it (UEs built first, then the gNB that
    owns them - see NrUeLicensed's class docstring's WIRING note and
    GnbLicensedNR.__init__'s back-reference loop)."""
    env = simpy.Environment()
    channel = _make_channel(env)
    cfg = config if config is not None else Config_NRL(tdd_enabled=True)
    ue = NrUeLicensed(
        name="UE 1-1", pos=ue_pos, gnb_name="G1",
        env=env, config=cfg, uplink_enabled=True,
    )
    ue_list = [ue] + (extra_ues or [])
    gnb = GnbLicensedNR(env, "G1", channel, gnb_pos, ue_list, cfg)
    return env, channel, gnb, ue


# ---------------------------------------------------------------------
# Backward compatibility: every pre-15.E NrUeLicensed(...)/Config_NRL()
# call site is unaffected.
# ---------------------------------------------------------------------

def test_default_ue_construction_is_untouched():
    ue = NrUeLicensed(name="U", pos=(0.0, 0.0), gnb_name="G1")
    assert ue.uplink_enabled is False
    assert ue.env is None
    assert ue.config is None
    assert ue.gnb is None
    assert not hasattr(ue, "ul_ready")
    assert not hasattr(ue, "sr_sent_at")


def test_default_config_has_tdd_disabled():
    cfg = Config_NRL()
    assert cfg.tdd_enabled is False
    assert cfg.tdd_pattern == "DDDU"


def test_gnb_init_back_references_every_ue_even_when_uplink_unused():
    env = simpy.Environment()
    channel = _make_channel(env)
    ue = NrUeLicensed(name="U", pos=(10.0, 0.0), gnb_name="G1")
    gnb = GnbLicensedNR(env, "G1", channel, (0.0, 0.0), [ue], Config_NRL())
    assert ue.gnb is gnb
    assert ue.uplink_enabled is False


def test_round_robin_and_pf_direct_calls_unaffected_by_extraction():
    """test_nr_licensed.py's own direct gnb._round_robin_allocation()/
    _proportional_fair_allocation() calls (no args) must still work
    exactly as before Step 15.E's pure-refactor extraction - this is
    the same safety property 15.A's own extraction preserved for
    nru.py's generate_backoff_slots()."""
    env = simpy.Environment()
    channel = _make_channel(env)
    ues = [NrUeLicensed(name=f"UE{i}", pos=(10.0 * i, 0.0), gnb_name="G1") for i in range(3)]
    gnb = GnbLicensedNR(env, "G1", channel, (0.0, 0.0), ues, Config_NRL())
    alloc_rr = gnb._round_robin_allocation()
    assert set(alloc_rr.keys()) == {"UE0", "UE1", "UE2"}
    alloc_pf = gnb._proportional_fair_allocation()
    assert len(alloc_pf) == 1  # single-winner-per-slot, unchanged


# ---------------------------------------------------------------------
# Fail-fast validation.
# ---------------------------------------------------------------------

def test_uplink_enabled_requires_env_and_config():
    try:
        NrUeLicensed(name="U", pos=(0.0, 0.0), gnb_name="G1", uplink_enabled=True)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "requires env and config" in str(e)


# ---------------------------------------------------------------------
# Functional: SchedulingRequest -> grant-eligibility -> real TDD-slotted
# uplink transmission, round-robin scheduler (the Config_NRL default).
# ---------------------------------------------------------------------

def test_scheduling_request_then_uplink_succeeds():
    env, channel, gnb, ue = _make_gnb_with_uplink_ue()
    assert ue.ul_ready is False  # not eligible yet at construction

    env.run(until=20000)  # 20ms - several TDD cycles

    assert ue.sr_sent_at == 0
    assert ue.first_grant_at == ue.sr_sent_at + gnb.config.sr_to_grant_delay_us
    assert ue.ul_ready is True
    assert gnb.succeeded_transmissions_ul > 0
    assert gnb.failed_transmissions_ul == 0  # close range, strong link
    assert channel.succeeded_transmissions_NRL == gnb.succeeded_transmissions + gnb.succeeded_transmissions_ul


def test_uplink_delivered_packet_has_correct_direction_and_sinr():
    env, channel, gnb, ue = _make_gnb_with_uplink_ue()
    env.run(until=20000)

    ul_delivered = [p for p in gnb.packet_log if p.source == "UE 1-1" and p.status == "DELIVERED"]
    assert len(ul_delivered) > 0
    for p in ul_delivered:
        assert p.destination == "G1"
        assert p.measured_sinr_db is not None
        assert p.delivered_at is not None


def test_uplink_not_scheduled_before_grant_eligibility():
    """Before sr_to_grant_delay_us elapses, this UE must never appear
    as a UL transmitter, even though 'U' slots are already happening."""
    cfg = Config_NRL(tdd_enabled=True, sr_to_grant_delay_us=100_000.0)  # never elapses in this short run
    env, channel, gnb, ue = _make_gnb_with_uplink_ue(config=cfg)
    env.run(until=20000)

    assert ue.ul_ready is False
    assert gnb.succeeded_transmissions_ul == 0
    assert gnb.failed_transmissions_ul == 0
    ul_packets = [p for p in gnb.packet_log if p.source == "UE 1-1"]
    assert len(ul_packets) == 0


def test_pf_scheduler_ul_has_independent_state_from_dl():
    """PF's UL winner-selection must use its own average-rate tracker
    (_pf_avg_rate_ul), not share/corrupt DL's (_pf_avg_rate) - see
    SlotScheduledAccess.allocate_ul()'s docstring."""
    cfg = Config_NRL(tdd_enabled=True, scheduler="proportional_fair")
    ue2 = NrUeLicensed(name="UE 1-2", pos=(20.0, 0.0), gnb_name="G1")
    env, channel, gnb, ue = _make_gnb_with_uplink_ue(config=cfg, extra_ues=[ue2])
    env.run(until=20000)

    assert gnb.succeeded_transmissions_ul > 0
    assert "UE 1-1" in gnb._pf_avg_rate_ul
    # DL's own PF tracker is untouched by UL activity - still seeded
    # for both UEs from construction (DL considers every UE, not just
    # the uplink-eligible one).
    assert set(gnb._pf_avg_rate.keys()) == {"UE 1-1", "UE 1-2"}


def test_multiple_ul_ues_round_robin_share_the_pool():
    ue2 = NrUeLicensed(name="UE 1-2", pos=(12.0, 0.0), gnb_name="G1")
    cfg = Config_NRL(tdd_enabled=True)
    env, channel, gnb, ue = _make_gnb_with_uplink_ue(config=cfg, extra_ues=[ue2])
    # Give ue2 uplink too, after construction (mirrors how a caller
    # would build two identically-configured uplink UEs).
    ue2.env, ue2.config, ue2.uplink_enabled = gnb.env, cfg, True
    ue2.ul_ready = False
    ue2.sr_sent_at = None
    ue2.first_grant_at = None
    gnb.env.process(ue2._send_scheduling_request())

    env.run(until=30000)

    assert gnb.succeeded_transmissions_ul > 0
    ul_sources = {p.source for p in gnb.packet_log if p.status == "DELIVERED" and p.source in ("UE 1-1", "UE 1-2")}
    assert ul_sources == {"UE 1-1", "UE 1-2"}


# ---------------------------------------------------------------------
# TDD opt-in itself: disabled (default) must be byte-identical to
# every pre-15.E run - covered by the module-level git-stash-based
# regression check (see Project details/Step pre_15.txt's DONE
# section), but also asserted directly here: with tdd_enabled=False,
# an uplink_enabled UE is simply never scheduled, no matter how long
# the run goes.
# ---------------------------------------------------------------------

def test_tdd_disabled_means_no_uplink_ever_scheduled():
    cfg = Config_NRL(tdd_enabled=False)  # the default - UL mechanism inert
    env, channel, gnb, ue = _make_gnb_with_uplink_ue(config=cfg)
    env.run(until=20000)

    assert ue.ul_ready is True  # the SR timer itself is UE-side, independent of tdd_enabled
    assert gnb.succeeded_transmissions_ul == 0
    assert gnb.failed_transmissions_ul == 0
    assert all(p.source != "UE 1-1" for p in gnb.packet_log)
# Rashed-Step 15.E-09-18-2026-end
