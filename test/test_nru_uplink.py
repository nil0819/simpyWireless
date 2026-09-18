# Rashed-Step 15.C-09-18-2026-start
"""
Step 15.C/15.D unit tests: NrUE's new opt-in real uplink LBT transmit
path (env/channel/config_nr/uplink_enabled fields, Gnb.__init__'s
automatic ue.gnb back-reference, the wait_back_off()/
send_transmission()/sent_completed()/sent_failed() generator methods),
plus 15.D's NruDeploymentMode guard.

Same style/harness as test_wifi_uplink.py/test_packet.py: plain
assert-based pytest-discovered functions, no simulation.py involved.
"""

import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import simpy

from channel.channel import Channel
from nru.nru import Gnb, Config_NR, NruDeploymentMode
from nru.ue import NrUE
from common.packet import TrafficConfig


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


class _NoAutoStartGnb(Gnb):
    """Same isolation technique test_packet.py already uses (Step
    10.B/8.F) - Gnb.__init__ unconditionally starts its own downlink
    process (env.process(self.start())), which would otherwise contend
    against the UE's uplink on the same channel and make a plain
    success/failure test non-deterministic. Silences ONLY the gNB's own
    downlink so a test can drive/observe the UE's uplink path in
    isolation; sync_slot_counter() (which the UE's uplink still needs,
    via its next_sync_slot_boundry property reading the gNB's live
    value) is untouched and keeps running."""
    def start(self):
        return
        yield  # pragma: no cover - never reached, makes this a generator


def _make_gnb_with_uplink_ue(config_nr=None, ue_pos=(1.0, 0.0), gnb_pos=(0.0, 0.0),
                              silence_gnb_downlink=True):
    """Real (non-fake) Gnb + a single uplink_enabled=True NrUE, wired
    together exactly the way simulation.py's own construction order
    does it (UE built first, then the gNB that owns it - see NrUE's
    class docstring's WIRING section and Gnb.__init__'s back-reference
    loop)."""
    env = simpy.Environment()
    channel = _make_channel(env)
    cfg = config_nr if config_nr is not None else Config_NR()
    ue = NrUE(
        name="UE 1-1", pos=ue_pos, gnb_name="Gnb 1",
        env=env, channel=channel, config_nr=cfg, uplink_enabled=True,
    )
    gnb_cls = _NoAutoStartGnb if silence_gnb_downlink else Gnb
    gnb = gnb_cls(env, "Gnb 1", channel, gnb_pos, [ue], cfg)
    return env, channel, gnb, ue


# ---------------------------------------------------------------------
# Backward compatibility: every pre-15.C NrUE(...) call site passes
# none of the new fields - must stay a no-op.
# ---------------------------------------------------------------------

def test_default_construction_is_untouched():
    ue = NrUE(name="UE 1-1", pos=(0.0, 0.0), gnb_name="Gnb 1")
    assert ue.uplink_enabled is False
    assert ue.env is None
    assert ue.channel is None
    assert ue.config_nr is None
    assert ue.gnb is None
    assert not hasattr(ue, "transmission_to_send")
    assert not hasattr(ue, "_channel_access")


def test_gnb_init_back_references_every_ue_even_when_uplink_unused():
    """Gnb.__init__'s new back-reference loop (see nru.py) runs
    unconditionally - must be a safe no-op for UEs that never use
    uplink at all."""
    env = simpy.Environment()
    channel = _make_channel(env)
    ue = NrUE(name="UE 1-1", pos=(1.0, 0.0), gnb_name="Gnb 1")
    gnb = Gnb(env, "Gnb 1", channel, (0.0, 0.0), [ue], Config_NR())
    assert ue.gnb is gnb
    assert ue.uplink_enabled is False
    assert gnb.deployment_mode == NruDeploymentMode.STANDALONE_MULTIFIRE


def test_default_deployment_mode_is_standalone_multifire():
    assert Config_NR().deployment_mode == NruDeploymentMode.STANDALONE_MULTIFIRE


# ---------------------------------------------------------------------
# Fail-fast validation (mirrors WiFiSTA's own uplink_enabled gate).
# ---------------------------------------------------------------------

def test_uplink_enabled_requires_env_channel_config():
    try:
        NrUE(name="U", pos=(0.0, 0.0), gnb_name="Gnb 1", uplink_enabled=True)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "requires env, channel, and config_nr" in str(e)


def test_uplink_enabled_rejects_non_saturated_traffic():
    env = simpy.Environment()
    channel = _make_channel(env)
    try:
        NrUE(
            name="U", pos=(0.0, 0.0), gnb_name="Gnb 1", uplink_enabled=True,
            env=env, channel=channel, config_nr=Config_NR(),
            traffic_config=TrafficConfig(mode="poisson"),
        )
        assert False, "expected ValueError"
    except ValueError as e:
        assert "only supports traffic_config.mode='saturated'" in str(e)


def test_uplink_enabled_rejects_laa_anchored_deployment_mode():
    """Step 15.D's guard: LAA_ANCHORED is a recognized enum value but
    NrUE's LBT-based uplink is STANDALONE_MULTIFIRE only - selecting
    LAA_ANCHORED with uplink_enabled=True must fail loudly, not
    silently give LAA-labeled traffic MultiFire-shaped behavior."""
    env = simpy.Environment()
    channel = _make_channel(env)
    cfg = Config_NR(deployment_mode=NruDeploymentMode.LAA_ANCHORED)
    try:
        NrUE(
            name="U", pos=(0.0, 0.0), gnb_name="Gnb 1", uplink_enabled=True,
            env=env, channel=channel, config_nr=cfg,
        )
        assert False, "expected NotImplementedError"
    except NotImplementedError as e:
        assert "LAA_ANCHORED" in str(e)


def test_uplink_process_raises_runtime_error_if_never_wired_to_a_gnb():
    """A UE constructed with uplink_enabled=True but never placed in a
    Gnb's ue_list (so Gnb.__init__ never set ue.gnb) must fail loudly
    the moment its process actually runs."""
    env = simpy.Environment()
    channel = _make_channel(env)
    ue = NrUE(
        name="Orphan UE", pos=(0.0, 0.0), gnb_name="Gnb 1",
        env=env, channel=channel, config_nr=Config_NR(), uplink_enabled=True,
    )
    assert ue.gnb is None
    try:
        env.run(until=10)
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "no gNB reference was wired in" in str(e)


# ---------------------------------------------------------------------
# Functional: a real, close-range UE<->gNB link actually exchanges
# uplink transmissions and updates the same shared channel state every
# other technology in this simulator already uses. The gNB's own
# downlink is silenced (_NoAutoStartGnb) so these tests isolate the
# UPLINK path itself - see the separate "known limitation" test below
# for what happens with both directions saturated on the same cell.
# ---------------------------------------------------------------------

def test_uplink_transmits_and_succeeds_at_close_range():
    env, channel, gnb, ue = _make_gnb_with_uplink_ue()
    env.run(until=50000)  # 50 ms

    assert ue.succeeded_transmissions + ue.failed_transmissions > 0
    assert ue.succeeded_transmissions > 0
    assert channel.succeeded_transmissions_NR == ue.succeeded_transmissions
    assert channel.failed_transmissions_NR == ue.failed_transmissions
    assert channel.airtime_data_NR.get("UE 1-1", 0) > 0


def test_uplink_delivered_packet_has_correct_direction_and_sinr():
    env, channel, gnb, ue = _make_gnb_with_uplink_ue()
    env.run(until=50000)

    delivered = [p for p in ue.packet_log if p.status == "DELIVERED"]
    assert len(delivered) > 0
    for p in delivered:
        assert p.source == "UE 1-1"
        assert p.destination == "Gnb 1"
        assert p.measured_sinr_db is not None
        assert p.delivered_at is not None


def test_uplink_retry_and_drop_under_forced_failure():
    """Force every uplink attempt to fail (impossible SINR threshold),
    with a small r_limit so a drop is reached quickly, mirroring
    Gnb.sent_failed()'s own retry-count/DROP bookkeeping exactly."""
    cfg = Config_NR(nru_sinr_thr_db_override=1000.0, r_limit=2)
    env, channel, gnb, ue = _make_gnb_with_uplink_ue(config_nr=cfg)
    env.run(until=60000)

    assert ue.succeeded_transmissions == 0
    assert ue.failed_transmissions > 0

    dropped = [p for p in ue.packet_log if p.status == "DROPPED"]
    assert len(dropped) > 0
    for p in dropped:
        assert p.retry_count == cfg.r_limit + 1
        assert p.source == "UE 1-1"


# ---------------------------------------------------------------------
# Known limitation (documented in "Project details/Step pre_15.txt"'s
# STEP 15 - 15.C/15.D DONE section): a gNB and its OWN UE currently
# contend as fully independent LBT participants, with no coordination
# between the cell's downlink and its uplink. Both align to the SAME
# next_sync_slot_boundry (the UE reads it live off its serving gNB -
# see NrUE.next_sync_slot_boundry) and, at saturated traffic with
# identical mcot-based durations, land on the exact same transmission
# start time essentially every cycle - a systematic near-total self-
# collision, not a partial/probabilistic one. This test captures that
# finding so it's a visible, tracked regression rather than a silent
# surprise if a future scheduler/coordination sub-step changes it.
# ---------------------------------------------------------------------

def test_known_limitation_gnb_and_own_ue_collide_when_both_saturated():
    env, channel, gnb, ue = _make_gnb_with_uplink_ue(silence_gnb_downlink=False)
    env.run(until=30000)  # 30 ms - several contention cycles

    assert ue.failed_transmissions + gnb.failed_transmissions > 0
    assert ue.succeeded_transmissions == 0
    assert gnb.succeeded_transmissions == 0
# Rashed-Step 15.C-09-18-2026-end
