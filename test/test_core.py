# Rashed-Step 16.B-10-02-2026-start
"""
Step 16.B unit tests: core/network.py's Amf/Smf/Upf/CoreNetwork
skeleton (state only - procedure timing arrives in 16.C/16.D).

Same style/harness as test_rrc.py: plain assert-based pytest-discovered
functions.
"""

import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import simpy

from core.network import (
    Amf, Smf, Upf, CoreNetwork, CoreConfig, PduSessionState,
)


def _expect_value_error(fn, needle):
    try:
        fn()
    except ValueError as e:
        assert needle in str(e)
    else:
        assert False, "expected ValueError"


def test_core_config_defaults_are_sourced_values():
    cfg = CoreConfig()
    assert cfg.registration_delay_us == 90_000.0
    assert cfg.pdu_session_delay_us == 125_000.0
    assert cfg.dnn == "internet"


def test_amf_register_and_deregister():
    amf = Amf()
    assert not amf.is_registered("UE 1-1")
    amf.register("UE 1-1", "G1")
    assert amf.is_registered("UE 1-1")
    assert amf.serving_gnb["UE 1-1"] == "G1"
    amf.deregister("UE 1-1")
    assert not amf.is_registered("UE 1-1")
    amf.deregister("UE 1-1")  # idempotent


def test_upf_gate():
    upf = Upf()
    assert not upf.allows("UE 1-1")
    upf.anchor("UE 1-1")
    assert upf.allows("UE 1-1")
    upf.release("UE 1-1")
    assert not upf.allows("UE 1-1")


def test_smf_requires_at_least_one_upf():
    _expect_value_error(lambda: Smf(Amf(), []), "at least one Upf")


def test_smf_session_needs_registration_first():
    smf = Smf(Amf(), [Upf()])
    _expect_value_error(lambda: smf.request_session("UE 1-1", now=0.0), "not registered")


def test_smf_session_lifecycle_drives_upf_gate():
    amf, upf = Amf(), Upf()
    smf = Smf(amf, [upf])
    amf.register("UE 1-1", "G1")
    assert smf.session_state("UE 1-1") is PduSessionState.INACTIVE

    s = smf.request_session("UE 1-1", now=100.0)
    assert s.state is PduSessionState.PENDING
    assert s.session_id == 1 and s.upf_name == upf.name and s.dnn == "internet"
    assert s.requested_at == 100.0
    assert not upf.allows("UE 1-1")  # PENDING does not open the gate

    smf.activate_session("UE 1-1", now=250.0)
    assert smf.session_state("UE 1-1") is PduSessionState.ACTIVE
    assert s.activated_at == 250.0
    assert upf.allows("UE 1-1")

    smf.release_session("UE 1-1")
    assert smf.session_state("UE 1-1") is PduSessionState.INACTIVE
    assert not upf.allows("UE 1-1")


def test_smf_rejects_duplicate_and_out_of_order_calls():
    amf = Amf()
    smf = Smf(amf, [Upf()])
    amf.register("UE 1-1", "G1")
    _expect_value_error(lambda: smf.activate_session("UE 1-1", now=0.0), "no PENDING session")
    smf.request_session("UE 1-1", now=0.0)
    _expect_value_error(lambda: smf.request_session("UE 1-1", now=1.0), "already has a pending session")
    smf.activate_session("UE 1-1", now=2.0)
    _expect_value_error(lambda: smf.activate_session("UE 1-1", now=3.0), "no PENDING session")
    # A released session can be re-established, with a fresh ID.
    smf.release_session("UE 1-1")
    assert smf.request_session("UE 1-1", now=4.0).session_id == 2


def test_smf_spreads_sessions_across_multiple_upfs():
    amf = Amf()
    upfs = [Upf("UPF 1"), Upf("UPF 2")]
    smf = Smf(amf, upfs)
    for i in range(1, 5):
        amf.register(f"UE {i}", "G1")
        smf.request_session(f"UE {i}", now=0.0)
    assert [smf.sessions[f"UE {i}"].upf_name for i in range(1, 5)] == ["UPF 1", "UPF 2", "UPF 1", "UPF 2"]


def test_core_network_wiring_and_user_plane_query():
    env = simpy.Environment()
    core = CoreNetwork(env)
    assert core.env is env
    assert isinstance(core.config, CoreConfig)
    assert core.smf.amf is core.amf
    assert len(core.upfs) == 1 and core.smf.upfs is core.upfs

    assert not core.user_plane_allows("UE 1-1")
    core.amf.register("UE 1-1", "G1")
    core.smf.request_session("UE 1-1", now=env.now)
    core.smf.activate_session("UE 1-1", now=env.now)
    assert core.user_plane_allows("UE 1-1")


def test_core_network_honors_custom_config():
    cfg = CoreConfig(registration_delay_us=1.0, pdu_session_delay_us=2.0, dnn="ims")
    core = CoreNetwork(simpy.Environment(), cfg, n_upfs=2)
    assert core.config is cfg
    assert core.smf.dnn == "ims"
    assert [u.name for u in core.upfs] == ["UPF 1", "UPF 2"]


def test_nothing_outside_core_imports_it_yet():
    """16.B is a skeleton: no existing module may depend on core/ until
    16.F wires it in, so every pre-16 run is untouched by construction.
    Expected to start failing in 16.F - delete it there and rely on the
    byte-identical CLI check instead."""
    import pathlib
    root = pathlib.Path(PROJECT_ROOT)
    offenders = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(("core/", "test/test_core.py")):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "from core" in text or "import core" in text:
            offenders.append(rel)
    assert offenders == [], offenders
# Rashed-Step 16.B-10-02-2026-end


# Rashed-Step 16.C-10-02-2026-start
# ---------------------------------------------------------------------
# 16.C: Registration procedure (core/procedures.py) driven by
# CoreNetwork.start_ue(), for both technologies, with and without RRC.
# ---------------------------------------------------------------------

import random

from channel.channel import Channel
from core.network import RegistrationState
from core.procedures import compute_registration_stats
from ran.protocol.rrc import RrcState

from nru.nru import Gnb, Config_NR
from nru.ue import NrUE
from nr.nr import GnbLicensedNR, Config_NRL
from nr.ue import NrUeLicensed


def _make_channel(env):
    return Channel(
        tx_queue=simpy.PriorityResource(env, capacity=1),
        tx_lock=simpy.Resource(env, capacity=1),
        n_of_stations=0, n_of_gNB=1, backoffs={},
        airtime_data={}, airtime_control={},
        airtime_data_NR={}, airtime_control_NR={},
    )


class _NoAutoStartGnb(Gnb):
    """NR-U gNB with its own downlink silenced (same isolation technique
    as test_nru_uplink.py) so RRC timing is reproducible."""
    def start(self):
        return
        yield


def _licensed(rrc_enabled, n_ues=1):
    env = simpy.Environment()
    cfg = Config_NRL(tdd_enabled=True)
    ues = [
        NrUeLicensed(
            name=f"UE 1-{i}", pos=(10.0, 0.0), gnb_name="G1",
            env=env, config=cfg, uplink_enabled=rrc_enabled, rrc_enabled=rrc_enabled,
        )
        for i in range(1, n_ues + 1)
    ]
    gnb = GnbLicensedNR(env, "G1", _make_channel(env), (0.0, 0.0), ues, cfg)
    return env, gnb, ues


def test_ue_never_handed_to_core_has_no_reg_state():
    env, gnb, (ue,) = _licensed(rrc_enabled=False)
    CoreNetwork(env)
    env.run(until=200_000)
    assert not hasattr(ue, "reg_state")
    assert getattr(ue, "reg_state", RegistrationState.REGISTERED) is RegistrationState.REGISTERED


def test_registration_without_rrc_starts_immediately():
    env, gnb, (ue,) = _licensed(rrc_enabled=False)
    core = CoreNetwork(env)
    core.start_ue(gnb, ue)
    assert ue.reg_state is RegistrationState.DEREGISTERED

    env.run(until=core.config.registration_delay_us - 1)
    assert ue.reg_state is RegistrationState.DEREGISTERED
    assert not core.amf.is_registered(ue.name)

    env.run(until=core.config.registration_delay_us + 1)
    assert ue.reg_state is RegistrationState.REGISTERED
    assert ue.reg_requested_at == 0
    assert ue.registered_at == core.config.registration_delay_us
    assert core.amf.serving_gnb[ue.name] == "G1"


def test_licensed_nr_registration_waits_for_rrc_connected():
    env, gnb, (ue,) = _licensed(rrc_enabled=True)
    core = CoreNetwork(env)
    core.start_ue(gnb, ue)
    env.run(until=200_000)
    assert ue.rrc_connected_at == 4000.0  # Step 16.A default
    assert ue.reg_requested_at == ue.rrc_connected_at
    assert ue.registered_at == 4000.0 + core.config.registration_delay_us
    assert ue.reg_state is RegistrationState.REGISTERED


def test_nru_registration_waits_for_rrc_connected():
    random.seed(1)
    env = simpy.Environment()
    channel = _make_channel(env)
    cfg = Config_NR()
    ue = NrUE(
        name="UE 1-1", pos=(10.0, 0.0), gnb_name="G1",
        env=env, channel=channel, config_nr=cfg,
        uplink_enabled=True, rrc_enabled=True,
    )
    gnb = _NoAutoStartGnb(env, "G1", channel, (0.0, 0.0), [ue], cfg)
    core = CoreNetwork(env)
    core.start_ue(gnb, ue)
    env.run(until=300_000)
    assert ue.rrc_state is RrcState.CONNECTED
    assert ue.reg_requested_at == ue.rrc_connected_at
    assert ue.registered_at == ue.rrc_connected_at + core.config.registration_delay_us
    assert core.amf.serving_gnb["UE 1-1"] == "G1"


def test_start_ue_after_rrc_already_connected_registers_from_now():
    env, gnb, (ue,) = _licensed(rrc_enabled=True)
    core = CoreNetwork(env)
    env.run(until=10_000)  # RRC done at 4000
    assert ue.rrc_state is RrcState.CONNECTED
    core.start_ue(gnb, ue)
    env.run(until=200_000)
    assert ue.reg_requested_at == 10_000
    assert ue.registered_at == 10_000 + core.config.registration_delay_us


def test_custom_registration_delay_and_stats():
    env, gnb, ues = _licensed(rrc_enabled=True, n_ues=3)
    core = CoreNetwork(env, CoreConfig(registration_delay_us=5000.0))
    for ue in ues[:2]:  # third UE never handed to the Core
        core.start_ue(gnb, ue)
    env.run(until=20_000)
    stats = compute_registration_stats(gnb.ue_list)
    assert stats["attempted"] == 2
    assert stats["registered"] == 2
    assert stats["success_rate"] == 1.0
    assert stats["latencies_us"] == [5000.0, 5000.0]
    assert stats["mean_latency_us"] == 5000.0
    assert not hasattr(ues[2], "reg_state")


def test_registration_stats_mid_procedure_and_empty():
    env, gnb, (ue,) = _licensed(rrc_enabled=True)
    core = CoreNetwork(env)
    core.start_ue(gnb, ue)
    env.run(until=50_000)
    stats = compute_registration_stats([ue])
    assert stats == {"attempted": 1, "registered": 0, "success_rate": 0.0,
                     "latencies_us": [], "mean_latency_us": None}
    assert compute_registration_stats([])["success_rate"] is None


def test_core_registration_leaves_ran_scheduling_untouched():
    """Registration is Core-side only in 16.C: the RAN keeps scheduling
    the UE as soon as RRC connects (user-plane gating is 16.E)."""
    env, gnb, (ue,) = _licensed(rrc_enabled=True)
    core = CoreNetwork(env)
    core.start_ue(gnb, ue)
    env.run(until=20_000)  # RRC connected, registration still pending
    assert ue.reg_state is RegistrationState.DEREGISTERED
    assert any(p.destination == ue.name for p in gnb.packet_log)
# Rashed-Step 16.C-10-02-2026-end
