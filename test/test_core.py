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


def test_ran_packages_never_import_core():
    """Was test_nothing_outside_core_imports_it_yet (16.B: nothing at all
    could import core/). Since 16.F the orchestrators/CLIs do, by design,
    so this now guards the rule 16.E relies on instead: the RAN packages
    stay Core-agnostic and reach it only through ue.core_network
    (ran/protocol/user_plane.py)."""
    import pathlib
    import re
    root = pathlib.Path(PROJECT_ROOT)
    offenders = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if not rel.startswith(("nr/", "nru/", "ran/", "wifi/", "channel/", "common/")):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        # Real import statements only (16.E: ran/protocol/user_plane.py's
        # docstring mentions "import core/" in prose).
        if re.search(r"^\s*(from core[.\s]|import core\b)", text, re.MULTILINE):
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
# Rashed-Step 17.E-10-04-2026-start
from nru.nru import NruUplinkAccessMode
# Rashed-Step 17.E-10-04-2026-end
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
    cfg = Config_NR(ul_access_mode=NruUplinkAccessMode.AUTONOMOUS)  # Rashed-Step 17.F-10-04-2026: pinned - autonomous (Cat-4) RRC path; COT sharing needs a transmitting gNB
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


def test_ran_does_not_schedule_ue_mid_registration():
    """Was test_core_registration_leaves_ran_scheduling_untouched (16.C:
    the RAN ignored the Core). Since 16.E the UPF gate applies: RRC
    connected but registration still pending -> no DL data yet."""
    env, gnb, (ue,) = _licensed(rrc_enabled=True)
    core = CoreNetwork(env)
    core.start_ue(gnb, ue)
    env.run(until=20_000)  # RRC connected, registration still pending
    assert ue.reg_state is RegistrationState.DEREGISTERED
    assert not any(p.destination == ue.name for p in gnb.packet_log)
# Rashed-Step 16.C-10-02-2026-end


# Rashed-Step 16.D-10-02-2026-start
# ---------------------------------------------------------------------
# 16.D: PDU session establishment, chained after registration.
# Defaults: RRC 4000us (licensed), registration 90000us, PDU session
# 125000us.
# ---------------------------------------------------------------------

from core.procedures import compute_pdu_session_stats


def test_licensed_nr_full_chain_timing_and_upf_gate():
    env, gnb, (ue,) = _licensed(rrc_enabled=True)
    core = CoreNetwork(env)
    core.start_ue(gnb, ue)

    env.run(until=94_000 + 1)  # registered at 94000, session just requested
    assert ue.reg_state is RegistrationState.REGISTERED
    assert ue.pdu_session.state is PduSessionState.PENDING
    assert ue.pdu_session.requested_at == 94_000
    assert not core.user_plane_allows(ue.name)

    env.run(until=219_000 - 1)
    assert not core.user_plane_allows(ue.name)

    env.run(until=219_000 + 1)
    assert ue.pdu_session.state is PduSessionState.ACTIVE
    assert ue.pdu_session.activated_at == 94_000 + 125_000
    assert ue.pdu_session.session_id == 1
    assert ue.pdu_session.upf_name == "UPF 1"
    assert ue.pdu_session.dnn == "internet"
    assert ue.pdu_session is core.smf.sessions[ue.name]
    assert core.user_plane_allows(ue.name)


def test_no_rrc_chain_and_attach_latency_from_core_start():
    env, gnb, (ue,) = _licensed(rrc_enabled=False)
    core = CoreNetwork(env)
    core.start_ue(gnb, ue)
    env.run(until=300_000)
    assert ue.core_started_at == 0
    assert ue.pdu_session.activated_at == 90_000 + 125_000
    stats = compute_pdu_session_stats([ue])
    assert stats["attach_latencies_us"] == [215_000]


def test_nru_session_follows_registration():
    random.seed(1)
    env = simpy.Environment()
    channel = _make_channel(env)
    cfg = Config_NR(ul_access_mode=NruUplinkAccessMode.AUTONOMOUS)  # Rashed-Step 17.F-10-04-2026: pinned - autonomous (Cat-4) RRC path; COT sharing needs a transmitting gNB
    ue = NrUE(
        name="UE 1-1", pos=(10.0, 0.0), gnb_name="G1",
        env=env, channel=channel, config_nr=cfg,
        uplink_enabled=True, rrc_enabled=True,
    )
    gnb = _NoAutoStartGnb(env, "G1", channel, (0.0, 0.0), [ue], cfg)
    core = CoreNetwork(env)
    core.start_ue(gnb, ue)
    env.run(until=400_000)
    assert ue.pdu_session.requested_at == ue.registered_at
    assert ue.pdu_session.activated_at == ue.rrc_connected_at + 215_000
    assert core.user_plane_allows("UE 1-1")
    stats = compute_pdu_session_stats([ue])
    assert stats["attach_latencies_us"] == [ue.pdu_session.activated_at - ue.rrc_attach_started_at]


def test_multiple_ues_get_distinct_sessions_across_upfs():
    env, gnb, ues = _licensed(rrc_enabled=True, n_ues=4)
    core = CoreNetwork(env, n_upfs=2)
    for ue in ues:
        core.start_ue(gnb, ue)
    env.run(until=300_000)
    assert sorted(ue.pdu_session.session_id for ue in ues) == [1, 2, 3, 4]
    assert sorted(ue.pdu_session.upf_name for ue in ues) == ["UPF 1", "UPF 1", "UPF 2", "UPF 2"]
    for ue in ues:
        assert core.user_plane_allows(ue.name)
        assert any(u.allows(ue.name) for u in core.upfs if u.name == ue.pdu_session.upf_name)


def test_pdu_session_stats_mid_procedure_custom_delays_and_partial_set():
    env, gnb, ues = _licensed(rrc_enabled=True, n_ues=3)
    core = CoreNetwork(env, CoreConfig(registration_delay_us=1000.0, pdu_session_delay_us=2000.0))
    for ue in ues[:2]:
        core.start_ue(gnb, ue)

    env.run(until=5500)  # RRC 4000 + registration 1000 = 5000: sessions PENDING
    mid = compute_pdu_session_stats(gnb.ue_list)
    assert mid["attempted"] == 2 and mid["active"] == 0 and mid["success_rate"] == 0.0
    assert mid["mean_latency_us"] is None and mid["mean_attach_latency_us"] is None

    env.run(until=10_000)
    stats = compute_pdu_session_stats(gnb.ue_list)
    assert stats["attempted"] == 2 and stats["active"] == 2 and stats["success_rate"] == 1.0
    assert stats["latencies_us"] == [2000.0, 2000.0]
    assert stats["attach_latencies_us"] == [7000.0, 7000.0]
    assert stats["mean_attach_latency_us"] == 7000.0
    assert not hasattr(ues[2], "pdu_session")
    assert compute_pdu_session_stats([])["success_rate"] is None


def test_late_start_attach_latency_counts_from_rrc_start():
    """Documented choice: for a UE that went through RRC, the attach
    clock starts at RRC, even if the Core was only told later."""
    env, gnb, (ue,) = _licensed(rrc_enabled=True)
    core = CoreNetwork(env)
    env.run(until=10_000)
    core.start_ue(gnb, ue)
    env.run(until=300_000)
    assert ue.pdu_session.activated_at == 10_000 + 215_000
    assert compute_pdu_session_stats([ue])["attach_latencies_us"] == [225_000]
# Rashed-Step 16.D-10-02-2026-end


# Rashed-Step 16.E-10-02-2026-start
# ---------------------------------------------------------------------
# 16.E: RAN-side UPF gate (ran/protocol/user_plane.py). A UE handed to
# the Core carries no DATA until its PDU session is ACTIVE (219ms for
# licensed NR with RRC at defaults); every other UE is unaffected.
# ---------------------------------------------------------------------

from ran.protocol.user_plane import user_plane_allows

ACTIVE_AT_US = 219_000  # RRC 4000 + registration 90000 + session 125000


class _Bare:
    name = "UE X"


def test_user_plane_allows_defaults_to_true_without_core():
    assert user_plane_allows(_Bare())


def _two_licensed_ues_one_in_core(rrc_enabled=True):
    env, gnb, (ue1, ue2) = _licensed(rrc_enabled=rrc_enabled, n_ues=2)
    core = CoreNetwork(env)
    core.start_ue(gnb, ue2)  # ue1 never handed to the Core
    return env, gnb, core, ue1, ue2


def test_licensed_dl_gated_until_session_active():
    env, gnb, core, ue1, ue2 = _two_licensed_ues_one_in_core()
    env.run(until=ACTIVE_AT_US - 1)
    assert not any(p.destination == ue2.name for p in gnb.packet_log)
    assert any(p.destination == ue1.name for p in gnb.packet_log)
    n_before = len(gnb.packet_log)
    env.run(until=ACTIVE_AT_US + 20_000)
    assert any(p.destination == ue2.name for p in gnb.packet_log[n_before:])
    assert all(p.created_at >= ACTIVE_AT_US for p in gnb.packet_log if p.destination == ue2.name)


def test_licensed_ul_gated_until_session_active():
    env, gnb, core, ue1, ue2 = _two_licensed_ues_one_in_core()
    env.run(until=ACTIVE_AT_US - 1)
    assert ue2.ul_ready is True  # its own SR timer finished long ago
    assert not any(p.source == ue2.name for p in gnb.packet_log)
    assert any(p.source == ue1.name for p in gnb.packet_log)
    env.run(until=ACTIVE_AT_US + 20_000)
    ul2 = [p for p in gnb.packet_log if p.source == ue2.name]
    assert ul2 and all(p.created_at >= ACTIVE_AT_US for p in ul2)
    assert any(p.status == "DELIVERED" for p in ul2)


def test_licensed_gate_closes_again_on_session_release():
    env, gnb, core, ue1, ue2 = _two_licensed_ues_one_in_core()
    env.run(until=ACTIVE_AT_US + 10_000)
    core.smf.release_session(ue2.name)
    released_at = env.now
    env.run(until=released_at + 20_000)
    assert not any(
        p.destination == ue2.name and p.created_at > released_at for p in gnb.packet_log
    )


def test_licensed_no_rrc_ue_in_core_gated_from_t0():
    env, gnb, core, ue1, ue2 = _two_licensed_ues_one_in_core(rrc_enabled=False)
    env.run(until=90_000 + 125_000 - 1)
    assert not any(p.destination == ue2.name for p in gnb.packet_log)
    env.run(until=90_000 + 125_000 + 20_000)
    assert any(p.destination == ue2.name for p in gnb.packet_log)


class _RecordingGnb(Gnb):
    """NR-U gNB that records which UE each downlink transmission really
    targets (tx.rx_ue). Written in 16.E, when Packet.destination was
    always ue_list[0]; since Step pre_17.A it matches tx.rx_ue (see
    test_nru_destination.py), but recording rx_ue directly still tests
    the gate independently of that fix."""
    def gen_new_transmission(self, packet=None):
        tx = super().gen_new_transmission(packet)
        self.rx_log = getattr(self, "rx_log", [])
        self.rx_log.append((self.env.now, tx.rx_ue.name if tx.rx_ue is not None else None))
        return tx


def test_nru_dl_destination_gated_until_session_active():
    random.seed(3)
    env = simpy.Environment()
    channel = _make_channel(env)
    cfg = Config_NR()
    ue1 = NrUE(name="UE 1-1", pos=(10.0, 0.0), gnb_name="G1")
    ue2 = NrUE(name="UE 1-2", pos=(12.0, 0.0), gnb_name="G1")
    gnb = _RecordingGnb(env, "G1", channel, (0.0, 0.0), [ue1, ue2], cfg)
    core = CoreNetwork(env)
    core.start_ue(gnb, ue2)
    active_at = 90_000 + 125_000  # no RRC on these UEs
    env.run(until=active_at + 100_000)
    before = [name for t, name in gnb.rx_log if t < active_at]
    after = [name for t, name in gnb.rx_log if t >= active_at]
    assert before and set(before) == {"UE 1-1"}
    assert "UE 1-2" in after


def test_nru_ul_waits_for_session_active():
    random.seed(1)
    env = simpy.Environment()
    channel = _make_channel(env)
    cfg = Config_NR(ul_access_mode=NruUplinkAccessMode.AUTONOMOUS)  # Rashed-Step 17.E-10-04-2026: pinned - this test describes the autonomous (Cat-4) uplink
    ue = NrUE(
        name="UE 1-1", pos=(10.0, 0.0), gnb_name="G1",
        env=env, channel=channel, config_nr=cfg,
        uplink_enabled=True, rrc_enabled=True,
    )
    gnb = _NoAutoStartGnb(env, "G1", channel, (0.0, 0.0), [ue], cfg)
    core = CoreNetwork(env)
    core.start_ue(gnb, ue)
    ue_active_bound = 300_000
    env.run(until=ue_active_bound)
    activated_at = ue.pdu_session.activated_at
    assert activated_at is not None and activated_at < ue_active_bound
    assert ue.packet_log, "uplink should have delivered packets after activation"
    assert all(p.created_at >= activated_at for p in ue.packet_log)
    assert ue.transmission_to_send.packet.created_at >= activated_at


def test_nru_ul_without_core_unaffected():
    """Control for the test above: same UE, not handed to the Core,
    starts sending right after RRC (well before 215ms)."""
    random.seed(1)
    env = simpy.Environment()
    channel = _make_channel(env)
    cfg = Config_NR(ul_access_mode=NruUplinkAccessMode.AUTONOMOUS)  # Rashed-Step 17.E-10-04-2026: pinned - this test describes the autonomous (Cat-4) uplink
    ue = NrUE(
        name="UE 1-1", pos=(10.0, 0.0), gnb_name="G1",
        env=env, channel=channel, config_nr=cfg,
        uplink_enabled=True, rrc_enabled=True,
    )
    _NoAutoStartGnb(env, "G1", channel, (0.0, 0.0), [ue], cfg)
    env.run(until=50_000)
    assert ue.packet_log
    assert min(p.created_at for p in ue.packet_log) < 50_000
# Rashed-Step 16.E-10-02-2026-end
