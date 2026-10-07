# Rashed-Step 19.D.2-10-07-2026-start
"""
Step 19.D.2 tests: 5G Core failure modes - registration / PDU session
rejects with retries and give-up, and AMF/SMF capacity (signaling storm
queueing).
"""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import simpy
from click.testing import CliRunner

from core.network import CoreConfig, CoreNetwork, PduSessionState, RegistrationState, core_config_from_cli
from core.procedures import compute_core_failure_stats, pdu_session_establishment, registration
from singleRunNR import single_run_nr


def _expect_value_error(fn, needle):
    try:
        fn()
    except ValueError as e:
        assert needle in str(e)
    else:
        assert False, "expected ValueError"


class _Gnb:
    name = "g"


class _Ue:
    def __init__(self, name):
        self.name = name
        self.reg_state = RegistrationState.DEREGISTERED


def _register_all(cfg, n, seed=1):
    env = simpy.Environment()
    core = CoreNetwork(env, cfg, seed=seed)
    ues = [_Ue(f"u{i}") for i in range(n)]
    results = {}

    def run(ue):
        results[ue.name] = yield from registration(core, _Gnb(), ue)
    for ue in ues:
        env.process(run(ue))
    env.run()
    return env, core, ues, results


def test_defaults_are_one_plain_wait():
    env, core, ues, res = _register_all(CoreConfig(), 3)
    assert all(res.values()) and env.now == 90_000.0
    assert all(ue.registered_at == 90_000.0 for ue in ues)
    assert not CoreConfig().failure_modes_on


def test_amf_capacity_queues_a_signaling_storm():
    env, core, ues, res = _register_all(CoreConfig(amf_capacity=1), 4)
    # Each registration holds the AMF for 10 ms: they finish 10 ms apart.
    assert sorted(ue.registered_at for ue in ues) == [90_000.0, 100_000.0, 110_000.0, 120_000.0]
    s = compute_core_failure_stats(ues)
    assert s["mean_amf_wait_us"] == (0 + 10_000 + 20_000 + 30_000) / 4


def test_reject_then_retry_succeeds():
    cfg = CoreConfig(registration_reject_prob=0.5, retry_us=50_000.0)
    env, core, ues, res = _register_all(cfg, 20, seed=3)
    rejected = [ue for ue in ues if getattr(ue, "reg_rejects", 0) > 0]
    assert rejected and all(res.values())
    for ue in rejected:
        # each reject costs the procedure delay plus the retry wait
        assert ue.registered_at == (ue.reg_rejects + 1) * 90_000.0 + ue.reg_rejects * 50_000.0


def test_gives_up_after_max_attempts():
    cfg = CoreConfig(registration_reject_prob=0.999, retry_us=0.0, max_attempts=3)
    env, core, ues, res = _register_all(cfg, 2)
    assert not any(res.values())
    assert all(ue.reg_rejects == 3 and ue.reg_state is RegistrationState.DEREGISTERED for ue in ues)
    assert compute_core_failure_stats(ues)["registration_failed"] == 2


def test_pdu_reject_releases_and_retries():
    env = simpy.Environment()
    core = CoreNetwork(env, CoreConfig(pdu_reject_prob=0.999, retry_us=1000.0, max_attempts=2), seed=1)
    ue = _Ue("u")
    core.amf.register(ue.name, "g")
    env.process(pdu_session_establishment(core, ue))
    env.run()
    assert ue.pdu_rejects == 2 and ue.pdu_failed_at is not None
    assert core.smf.session_state(ue.name) is PduSessionState.INACTIVE
    assert not core.user_plane_allows(ue.name)


def test_config_validation_and_cli():
    _expect_value_error(lambda: CoreConfig(registration_reject_prob=1.0), "must be in [0, 1)")
    _expect_value_error(lambda: CoreConfig(amf_capacity=0), "must be >= 1")
    _expect_value_error(lambda: CoreConfig(amf_capacity=1, service_us=200_000.0), "must not exceed")
    _expect_value_error(lambda: core_config_from_cli(False, amf_capacity=2), "only apply with the 5G Core")
    assert core_config_from_cli(True, amf_capacity=2).amf_capacity == 2
    runner = CliRunner()
    nr = ["--gnb-number", "1", "--ues-per-gnb", "6", "--seed", "2", "-t", "0.6",
          "--tdd-enabled", "--ue-uplink-enabled", "--rrc-enabled"]
    with runner.isolated_filesystem():
        r = runner.invoke(single_run_nr, nr + ["--core-enabled", "--core-amf-capacity", "1"])
        assert r.exit_code == 0, (r.output, r.exception)
        assert "NR mean AMF queue wait (us): 25000.0" in r.output   # 0..50 ms, mean 25
        r = runner.invoke(single_run_nr, nr + ["--core-enabled"])
        assert "queue wait" not in r.output
        r = runner.invoke(single_run_nr, nr + ["--core-amf-capacity", "1"])
        assert r.exit_code != 0 and "only apply with the 5G Core" in r.output
# Rashed-Step 19.D.2-10-07-2026-end
