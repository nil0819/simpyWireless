# Rashed-Step 15.F-09-18-2026-start
"""
Step 15.F unit tests: generic RRC (Radio Resource Control) attach
procedure (ran/protocol/rrc.py's RrcState/RrcLayer), composed into
BOTH NR-U (nru.nru.Gnb) and licensed NR (nr.nr.GnbLicensedNR) via each
gNB's own rrc_uplink_delay(ue) hook.

Same style/harness as test_nr_uplink.py/test_nru_uplink.py: plain
assert-based pytest-discovered functions, no simulation_nr.py/
simulation.py involved.
"""

import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import simpy

from channel.channel import Channel
from ran.protocol.rrc import RrcState

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
# Backward compatibility: every pre-15.F NrUE(...)/NrUeLicensed(...)
# call site is unaffected - no rrc_state attribute at all unless
# rrc_enabled=True was explicitly passed. See ran/protocol/rrc.py's
# module docstring's SCOPE note on the getattr(...) backward-compat
# contract.
# ---------------------------------------------------------------------

def test_nru_default_construction_has_no_rrc_state():
    ue = NrUE(name="U", pos=(0.0, 0.0), gnb_name="G1")
    assert ue.rrc_enabled is False
    assert not hasattr(ue, "rrc_state")


def test_nr_licensed_default_construction_has_no_rrc_state():
    ue = NrUeLicensed(name="U", pos=(0.0, 0.0), gnb_name="G1")
    assert ue.rrc_enabled is False
    assert not hasattr(ue, "rrc_state")


def test_backward_compat_getattr_contract_treats_unopted_ue_as_connected():
    """The documented contract future code (15.G) must use: a UE that
    never opted into RRC reads as CONNECTED via getattr(..., default),
    matching pre-15.F behavior (every UE always eligible)."""
    ue = NrUE(name="U", pos=(0.0, 0.0), gnb_name="G1")
    assert getattr(ue, "rrc_state", RrcState.CONNECTED) is RrcState.CONNECTED


def test_nru_gnb_init_does_not_start_rrc_for_non_opted_ues():
    env = simpy.Environment()
    channel = _make_channel(env)
    ue = NrUE(name="U", pos=(10.0, 0.0), gnb_name="G1")
    gnb = Gnb(env, "G1", channel, (0.0, 0.0), [ue], Config_NR())
    env.run(until=5000)
    assert not hasattr(ue, "rrc_state")


def test_nr_licensed_gnb_init_does_not_start_rrc_for_non_opted_ues():
    env = simpy.Environment()
    channel = _make_channel(env)
    ue = NrUeLicensed(name="U", pos=(10.0, 0.0), gnb_name="G1")
    gnb = GnbLicensedNR(env, "G1", channel, (0.0, 0.0), [ue], Config_NRL())
    env.run(until=5000)
    assert not hasattr(ue, "rrc_state")


# ---------------------------------------------------------------------
# Fail-fast validation: rrc_enabled=True requires uplink_enabled=True,
# for both technologies (mirrors each class's __post_init__ check).
# ---------------------------------------------------------------------

def test_nru_rrc_enabled_requires_uplink_enabled():
    try:
        NrUE(name="U", pos=(0.0, 0.0), gnb_name="G1", rrc_enabled=True)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "requires uplink_enabled=True" in str(e)


def test_nr_licensed_rrc_enabled_requires_uplink_enabled():
    try:
        NrUeLicensed(name="U", pos=(0.0, 0.0), gnb_name="G1", rrc_enabled=True)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "requires uplink_enabled=True" in str(e)


def test_nru_rrc_enabled_with_uplink_enabled_but_no_env_still_fails_fast():
    """rrc_enabled=True implies uplink_enabled=True's own env/channel/
    config_nr requirement is still enforced (rrc validation runs before
    the pre-existing uplink validation, but both are checked)."""
    try:
        NrUE(name="U", pos=(0.0, 0.0), gnb_name="G1",
             uplink_enabled=True, rrc_enabled=True)
        assert False, "expected ValueError (missing env/channel/config_nr)"
    except ValueError:
        pass


# ---------------------------------------------------------------------
# Functional: full IDLE -> CONNECTING -> CONNECTED attach, both
# technologies, each incurring its own technology-specific uplink
# delay (real LBT contention for NR-U, SR->grant delay for licensed
# NR - see rrc_uplink_delay()'s docstring on each gNB class).
# ---------------------------------------------------------------------

def test_nru_rrc_attach_reaches_connected():
    env = simpy.Environment()
    channel = _make_channel(env)
    cfg = Config_NR()
    ue = NrUE(
        name="UE 1-1", pos=(10.0, 0.0), gnb_name="G1",
        env=env, channel=channel, config_nr=cfg,
        uplink_enabled=True, rrc_enabled=True,
    )
    gnb = Gnb(env, "G1", channel, (0.0, 0.0), [ue], cfg)

    assert ue.rrc_state is RrcState.IDLE

    # Real LBT contention delay (Step 15.C's documented gNB/own-UE
    # collision finding applies here too - give it a generous window).
    env.run(until=200_000)

    assert ue.rrc_state is RrcState.CONNECTED
    assert ue.rrc_attach_started_at == 0
    assert ue.rrc_setup_request_sent_at is not None
    assert ue.rrc_setup_received_at is not None
    assert ue.rrc_setup_complete_sent_at is not None
    assert ue.rrc_connected_at is not None
    # Strict ordering of the 3-message exchange's timestamps.
    assert (ue.rrc_attach_started_at
            <= ue.rrc_setup_request_sent_at
            <= ue.rrc_setup_received_at
            <= ue.rrc_setup_complete_sent_at
            == ue.rrc_connected_at)
    # gNB-side RRCSetup processing delay is a genuine, real timeout.
    assert ue.rrc_setup_received_at - ue.rrc_setup_request_sent_at == gnb._rrc_layer.setup_processing_delay_us


def test_nr_licensed_rrc_attach_reaches_connected_with_deterministic_timing():
    """Licensed NR's uplink is grant-based, not contention-based, so
    unlike NR-U's version this timing is exactly deterministic: two
    SR->grant delays (RRCSetupRequest + RRCSetupComplete) plus one
    gNB-side setup-processing delay, no collisions possible."""
    env = simpy.Environment()
    channel = _make_channel(env)
    cfg = Config_NRL(tdd_enabled=True)
    ue = NrUeLicensed(
        name="UE 1-1", pos=(10.0, 0.0), gnb_name="G1",
        env=env, config=cfg, uplink_enabled=True, rrc_enabled=True,
    )
    gnb = GnbLicensedNR(env, "G1", channel, (0.0, 0.0), [ue], cfg)

    assert ue.rrc_state is RrcState.IDLE

    env.run(until=20_000)

    assert ue.rrc_state is RrcState.CONNECTED
    expected_connected_at = (
        2 * cfg.sr_to_grant_delay_us + gnb._rrc_layer.setup_processing_delay_us
    )
    assert ue.rrc_connected_at == expected_connected_at
    assert ue.rrc_setup_request_sent_at == cfg.sr_to_grant_delay_us
    assert ue.rrc_setup_received_at == cfg.sr_to_grant_delay_us + gnb._rrc_layer.setup_processing_delay_us
    assert ue.rrc_setup_complete_sent_at == expected_connected_at


def test_nr_licensed_rrc_attach_does_not_require_tdd_enabled():
    """RRC attach's uplink delay hook (SR->grant) is independent of
    whether TDD/UL scheduling itself is enabled - config.tdd_enabled
    only gates the DATA-plane UL scheduler (Step 15.E), not RRC's own
    control-plane messages."""
    env = simpy.Environment()
    channel = _make_channel(env)
    cfg = Config_NRL(tdd_enabled=False)  # UL data scheduler inert
    ue = NrUeLicensed(
        name="UE 1-1", pos=(10.0, 0.0), gnb_name="G1",
        env=env, config=cfg, uplink_enabled=True, rrc_enabled=True,
    )
    gnb = GnbLicensedNR(env, "G1", channel, (0.0, 0.0), [ue], cfg)

    env.run(until=20_000)

    assert ue.rrc_state is RrcState.CONNECTED


# ---------------------------------------------------------------------
# Multiple UEs: each gets its own independent attach process (RrcLayer
# is stateless/shared, exactly like LbtChannelAccess/SlotScheduledAccess).
# ---------------------------------------------------------------------

def test_nr_licensed_multiple_ues_each_attach_independently():
    env = simpy.Environment()
    channel = _make_channel(env)
    cfg = Config_NRL(tdd_enabled=True)
    ues = [
        NrUeLicensed(
            name=f"UE 1-{i}", pos=(10.0 * i, 0.0), gnb_name="G1",
            env=env, config=cfg, uplink_enabled=True, rrc_enabled=True,
        )
        for i in range(1, 4)
    ]
    gnb = GnbLicensedNR(env, "G1", channel, (0.0, 0.0), ues, cfg)

    env.run(until=20_000)

    for ue in ues:
        assert ue.rrc_state is RrcState.CONNECTED
# Rashed-Step 15.F-09-18-2026-end
