# Rashed-Step 15.G-09-18-2026-start
"""
Step 15.G unit tests: scheduler/RRC integration (rrc_state==CONNECTED
gating of GnbLicensedNR's DL/UL scheduler, NR-U Gnb's downlink
destination selection, and NrUE's own autonomous uplink data path),
plus ran/protocol/rrc.py's new compute_connection_setup_stats().

Same style/harness as test_rrc.py/test_nr_uplink.py/test_nru_uplink.py:
plain assert-based pytest-discovered functions, no simulation.py/
simulation_nr.py involved.
"""

import random
import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import simpy

from channel.channel import Channel
from ran.protocol.rrc import RrcState, compute_connection_setup_stats

from nru.nru import Gnb, Config_NR
from nru.ue import NrUE

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


# ---------------------------------------------------------------------
# GnbLicensedNR: DL scheduler filtering by rrc_state == CONNECTED.
# Default sr_to_grant_delay_us=4000.0, setup_processing_delay_us=
# 2000.0 -> full attach takes exactly 10000.0us (see test_rrc.py's own
# deterministic-timing test). A short run (until < 4000) always catches
# an rrc_enabled UE still in CONNECTING (RRCSetupRequest's own SR-delay
# uplink wait hasn't even elapsed yet).
# ---------------------------------------------------------------------

def _make_two_ue_licensed_gnb(cfg=None, ue2_uplink_enabled=True):
    env = simpy.Environment()
    channel = _make_channel(env)
    cfg = cfg if cfg is not None else Config_NRL(tdd_enabled=True)
    ue1 = NrUeLicensed(
        name="UE 1-1", pos=(10.0, 0.0), gnb_name="G1",
        env=env, config=cfg, uplink_enabled=True,
    )
    ue2 = NrUeLicensed(
        name="UE 1-2", pos=(10.0, 0.0), gnb_name="G1",
        env=env, config=cfg, uplink_enabled=ue2_uplink_enabled, rrc_enabled=True,
    )
    gnb = GnbLicensedNR(env, "G1", channel, (0.0, 0.0), [ue1, ue2], cfg)
    return env, channel, gnb, ue1, ue2


def test_dl_scheduler_excludes_ue_still_connecting():
    env, channel, gnb, ue1, ue2 = _make_two_ue_licensed_gnb()
    env.run(until=3900)  # < 4000: ue2's RRCSetupRequest uplink wait hasn't finished
    assert ue2.rrc_state is RrcState.CONNECTING

    assert len(gnb.packet_log) > 0  # several DL slots ran in 3900us
    assert all(p.destination != "UE 1-2" for p in gnb.packet_log)
    assert any(p.destination == "UE 1-1" for p in gnb.packet_log)


def test_dl_scheduler_includes_ue_once_connected():
    env, channel, gnb, ue1, ue2 = _make_two_ue_licensed_gnb()
    env.run(until=15000)  # > 10000: ue2 fully CONNECTED by now
    assert ue2.rrc_state is RrcState.CONNECTED
    assert any(p.destination == "UE 1-2" for p in gnb.packet_log)


def test_ul_scheduler_excludes_ue_still_connecting_even_though_ul_ready():
    """The key distinguishing case: at t=7000, ue2.ul_ready is already
    True (its OWN independent SR timer, config.sr_to_grant_delay_us=
    4000, completed at t=4000) but ue2.rrc_state is still CONNECTING
    (RRCSetupComplete's own uplink wait runs from t=6000 to t=10000) -
    proving the NEW rrc_state filter in _run_ul_slot() is doing real
    work, not just re-checking what ul_ready already covered."""
    env, channel, gnb, ue1, ue2 = _make_two_ue_licensed_gnb()
    env.run(until=7000)
    assert ue2.ul_ready is True
    assert ue2.rrc_state is RrcState.CONNECTING

    ul_sources = {p.source for p in gnb.packet_log if p.source == "UE 1-2"}
    assert ul_sources == set()
    assert any(p.source == "UE 1-1" for p in gnb.packet_log)


def test_ul_scheduler_includes_ue_once_connected():
    env, channel, gnb, ue1, ue2 = _make_two_ue_licensed_gnb()
    env.run(until=20000)
    assert ue2.rrc_state is RrcState.CONNECTED
    assert any(p.source == "UE 1-2" and p.status == "DELIVERED" for p in gnb.packet_log)


def test_dl_round_robin_and_pf_direct_calls_still_unaffected():
    """15.G's own extraction (allocate_dl_for()) must not have broken
    the pre-existing, directly-unit-tested zero-arg allocate() path -
    same safety property 15.E's own extraction preserved."""
    env = simpy.Environment()
    channel = _make_channel(env)
    ues = [NrUeLicensed(name=f"UE{i}", pos=(10.0 * i, 0.0), gnb_name="G1") for i in range(3)]
    gnb = GnbLicensedNR(env, "G1", channel, (0.0, 0.0), ues, Config_NRL())
    alloc_rr = gnb._round_robin_allocation()
    assert set(alloc_rr.keys()) == {"UE0", "UE1", "UE2"}
    alloc_pf = gnb._proportional_fair_allocation()
    assert len(alloc_pf) == 1


# ---------------------------------------------------------------------
# NR-U Gnb: downlink destination (rx_ue) selection filtered by
# rrc_state == CONNECTED. gen_new_transmission() is a plain (non-
# generator) method, so it can be called directly without env.run() -
# right after construction, ue2.rrc_state is RrcState.IDLE (set in its
# own __post_init__, before the attach process the gNB starts has had
# any chance to run).
# ---------------------------------------------------------------------

def test_nru_downlink_excludes_ue_before_rrc_connects():
    env = simpy.Environment()
    channel = _make_channel(env)
    cfg = Config_NR()
    ue1 = NrUE(name="UE 1-1", pos=(10.0, 0.0), gnb_name="G1")
    ue2 = NrUE(
        name="UE 1-2", pos=(10.0, 0.0), gnb_name="G1",
        env=env, channel=channel, config_nr=cfg, uplink_enabled=True, rrc_enabled=True,
    )
    gnb = Gnb(env, "G1", channel, (0.0, 0.0), [ue1, ue2], cfg)

    assert ue2.rrc_state is RrcState.IDLE  # attach process hasn't run yet - env.run() never called
    random.seed(1)
    picks = [gnb.gen_new_transmission().rx_ue for _ in range(10)]
    assert all(rx is ue1 for rx in picks)


def test_nru_downlink_includes_ue_once_connected():
    env = simpy.Environment()
    channel = _make_channel(env)
    cfg = Config_NR()
    ue1 = NrUE(name="UE 1-1", pos=(10.0, 0.0), gnb_name="G1")
    ue2 = NrUE(
        name="UE 1-2", pos=(10.0, 0.0), gnb_name="G1",
        env=env, channel=channel, config_nr=cfg, uplink_enabled=True, rrc_enabled=True,
    )
    gnb = Gnb(env, "G1", channel, (0.0, 0.0), [ue1, ue2], cfg)
    env.run(until=200_000)  # generous window for real LBT contention to finish attach
    assert ue2.rrc_state is RrcState.CONNECTED

    random.seed(1)
    picks = {gnb.gen_new_transmission().rx_ue.name for _ in range(20)}
    assert picks == {"UE 1-1", "UE 1-2"}


# ---------------------------------------------------------------------
# NrUE: its own autonomous uplink DATA path is gated on rrc_state ==
# CONNECTED (transmission_to_send only gets assigned inside start_
# uplink()'s while-True loop, which is itself gated behind yielding on
# self._rrc_connected_event when rrc_enabled=True).
# ---------------------------------------------------------------------

def test_nru_ue_own_uplink_data_path_blocked_until_rrc_connects():
    env = simpy.Environment()
    channel = _make_channel(env)
    cfg = Config_NR()
    ue = NrUE(
        name="UE 1-1", pos=(10.0, 0.0), gnb_name="G1",
        env=env, channel=channel, config_nr=cfg, uplink_enabled=True, rrc_enabled=True,
    )
    gnb = Gnb(env, "G1", channel, (0.0, 0.0), [ue], cfg)

    env.run(until=1)  # far too early for attach to have finished
    assert ue.rrc_state is not RrcState.CONNECTED
    assert ue.transmission_to_send is None  # start_uplink()'s real loop hasn't started

    env.run(until=200_000)
    assert ue.rrc_state is RrcState.CONNECTED
    assert ue.transmission_to_send is not None  # now genuinely contending


def test_nru_ue_uplink_data_path_unaffected_when_rrc_disabled():
    """Control: the pre-15.F/15.G default - uplink_enabled=True alone
    (rrc_enabled=False, the class default) starts contending for real
    data immediately, no gate at all."""
    env = simpy.Environment()
    channel = _make_channel(env)
    cfg = Config_NR()
    ue = NrUE(
        name="UE 1-1", pos=(10.0, 0.0), gnb_name="G1",
        env=env, channel=channel, config_nr=cfg, uplink_enabled=True,
    )
    gnb = Gnb(env, "G1", channel, (0.0, 0.0), [ue], cfg)

    env.run(until=1)
    assert not hasattr(ue, "rrc_state")
    assert ue.transmission_to_send is not None


# ---------------------------------------------------------------------
# compute_connection_setup_stats()
# ---------------------------------------------------------------------

def test_compute_connection_setup_stats_empty_list():
    stats = compute_connection_setup_stats([])
    assert stats == {
        "attempted": 0, "connected": 0, "success_rate": None,
        "latencies_us": [], "mean_latency_us": None,
    }


def test_compute_connection_setup_stats_no_ue_opted_in():
    class _Ue:
        pass
    stats = compute_connection_setup_stats([_Ue(), _Ue()])
    assert stats["attempted"] == 0
    assert stats["success_rate"] is None


def test_compute_connection_setup_stats_mixed():
    class _Ue:
        def __init__(self, state, started_at=None, connected_at=None):
            self.rrc_state = state
            if started_at is not None:
                self.rrc_attach_started_at = started_at
            if connected_at is not None:
                self.rrc_connected_at = connected_at

    class _NotOptedIn:
        pass

    connected1 = _Ue(RrcState.CONNECTED, started_at=0.0, connected_at=10000.0)
    connected2 = _Ue(RrcState.CONNECTED, started_at=0.0, connected_at=8000.0)
    still_connecting = _Ue(RrcState.CONNECTING, started_at=0.0)
    not_opted = _NotOptedIn()

    stats = compute_connection_setup_stats([connected1, connected2, still_connecting, not_opted])
    assert stats["attempted"] == 3
    assert stats["connected"] == 2
    assert stats["success_rate"] == 2 / 3
    assert sorted(stats["latencies_us"]) == [8000.0, 10000.0]
    assert stats["mean_latency_us"] == 9000.0


def test_compute_connection_setup_stats_from_real_gnb():
    """End-to-end sanity check against a real GnbLicensedNR/NrUeLicensed
    run, not hand-built fakes."""
    env, channel, gnb, ue1, ue2 = _make_two_ue_licensed_gnb()
    env.run(until=15000)
    stats = compute_connection_setup_stats(gnb.ue_list)
    assert stats["attempted"] == 1  # only ue2 has rrc_enabled=True
    assert stats["connected"] == 1
    assert stats["success_rate"] == 1.0
    assert stats["latencies_us"] == [10000.0]
# Rashed-Step 15.G-09-18-2026-end
