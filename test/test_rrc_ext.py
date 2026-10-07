# Rashed-Step 19.B.1-10-07-2026-start
"""
Step 19.B tests: RRC extensions.
  19.B.1 - Type 1 LBT fallback for RRC messages under COT sharing.
  19.B.2 - radio link monitoring, radio link failure, re-establishment.
"""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import re

import simpy
from click.testing import CliRunner

from nru.nru import Config_NR
from ran.protocol.rlm import RlmConfig, compute_rlf_stats, radio_link_monitor, rlm_config_from_cli
from ran.protocol.rrc import RrcLayer, RrcState
from singleRun import single_run
from singleRunNR import single_run_nr


def _expect_value_error(fn, needle):
    try:
        fn()
    except ValueError as e:
        assert needle in str(e)
    else:
        assert False, "expected ValueError"


def _cli(cmd, args):
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("log", exist_ok=True)
        return runner.invoke(cmd, args)


# ---------------------------------------------------------------------
# 19.B.1 Type 1 fallback
# ---------------------------------------------------------------------

HIDDEN = ["--ap-number", "2", "--gnb-number", "2", "--seed", "4", "-t", "0.5", "-r", "1",
          "--wifi-sta-uplink-enabled", "--nru-ue-uplink-enabled", "--nru-rrc-enabled", "--nru-core-enabled"]


def _rrc_ms(output):
    return float(re.search(r"NRU RRC mean connection setup latency \(us\): ([\d.]+)", output).group(1)) / 1000


def test_type1_fallback_shortens_the_hidden_node_attach():
    base = _cli(single_run, HIDDEN)
    fb = _cli(single_run, HIDDEN + ["--nru-rrc-type1-fallback", "1"])
    assert base.exit_code == 0 and fb.exit_code == 0, (base.output[-500:], fb.output[-500:])
    assert _rrc_ms(base.output) > 150   # the Step 17.H case: ~212 ms
    assert _rrc_ms(fb.output) < 0.5 * _rrc_ms(base.output)
    assert "NRU RRC Type 1 fallbacks: 2" in fb.output
    assert "Type 1 fallbacks" not in base.output


def test_type1_fallback_validation():
    _expect_value_error(lambda: Config_NR(rrc_type1_fallback_after=0), "must be >= 1")
    r = _cli(single_run, ["--ap-number", "1", "--gnb-number", "1", "-t", "0.05", "-r", "1",
                          "--nru-rrc-type1-fallback", "2"])
    assert r.exit_code != 0 and "needs --nru-rrc-enabled" in r.output
# Rashed-Step 19.B.1-10-07-2026-end


# Rashed-Step 19.B.2-10-07-2026-start
# ---------------------------------------------------------------------
# 19.B.2 radio link monitoring
# ---------------------------------------------------------------------

class _FakeGnb:
    """Serving cell whose downlink SINR follows a script of (until_us, dB)."""

    def __init__(self, env, script, ul_delay_us=1000.0):
        self.env = env
        self.script = script
        self.ul_delay_us = ul_delay_us

    def dl_sinr_estimate(self, ue):
        for until, db in self.script:
            if self.env.now < until:
                return db
        return self.script[-1][1]

    def rrc_uplink_delay(self, ue):
        yield self.env.timeout(self.ul_delay_us)


class _Ue:
    name = "ue"
    rrc_state = RrcState.CONNECTED


def _run(script, until_us, cfg=None):
    env = simpy.Environment()
    g, ue = _FakeGnb(env, script), _Ue()
    ue.rrc_state = RrcState.CONNECTED
    env.process(radio_link_monitor(g, ue, cfg or RlmConfig(), RrcLayer()))
    env.run(until=until_us)
    return ue


def test_good_link_never_starts_t310():
    ue = _run([(1e9, 10.0)], 3e6)
    assert ue.rlm_t310_starts == 0 and ue.rlf_count == 0


def test_short_fade_recovers_before_t310_expires():
    ue = _run([(1e6, 10.0), (1.5e6, -20.0), (1e9, 10.0)], 4e6)
    assert ue.rlm_t310_starts == 1 and ue.rlm_recoveries == 1
    assert ue.rlf_count == 0 and ue.rrc_state is RrcState.CONNECTED


def test_long_fade_is_a_radio_link_failure_then_re_establishment():
    ue = _run([(1e6, 10.0), (2.6e6, -20.0), (1e9, 10.0)], 5e6)
    assert ue.rlf_count == 1 and ue.reestablishments == 1
    assert ue.rrc_state is RrcState.CONNECTED
    # RLF ~1 s after T310 started (T310 starts once the 200 ms mean drops).
    assert 2.0e6 <= ue.rlf_at <= 2.3e6
    # Waited for the cell to come back (2.6 s), then 1 + 2 + 1 ms of RRC.
    assert ue.rlm_outage_us >= (2.6e6 - ue.rlf_at) + 4000.0 - 1


def test_no_cell_within_t311_drops_to_idle():
    ue = _run([(1e6, 10.0), (1e9, -20.0)], 5e6)
    assert ue.rlf_count == 1 and ue.reestablishments == 0
    assert ue.rrc_state is RrcState.IDLE and ue.rlf_to_idle_at is not None
    s = compute_rlf_stats([ue])
    assert (s["rlf"], s["to_idle"], s["reestablished"]) == (1, 1, 0)


def test_rlm_config_and_cli_mapping():
    _expect_value_error(lambda: RlmConfig(qin_db=-10.0, qout_db=-8.0), "must be >= qout_db")
    assert rlm_config_from_cli(False, None, None) is None
    assert rlm_config_from_cli(True, 500.0, None).t310_us == 500_000.0
    _expect_value_error(lambda: rlm_config_from_cli(False, 100.0, None), "require --rlm")


def test_cli_blocks_and_validation():
    nr = ["--gnb-number", "1", "--ues-per-gnb", "2", "--seed", "1", "-t", "0.1"]
    r = _cli(single_run_nr, nr + ["--tdd-enabled", "--ue-uplink-enabled", "--rrc-enabled", "--rlm"])
    assert r.exit_code == 0, (r.output, r.exception)
    assert "=== Licensed 5G NR Radio Link ===" in r.output and "NR radio link failures: 0" in r.output
    r = _cli(single_run_nr, nr + ["--rlm"])
    assert r.exit_code != 0 and "--rlm requires --rrc-enabled" in r.output
    nru = ["--ap-number", "1", "--gnb-number", "1", "--seed", "1", "-r", "1", "-t", "0.1"]
    r = _cli(single_run, nru + ["--nru-ue-uplink-enabled", "--nru-rrc-enabled", "--rlm"])
    assert r.exit_code == 0, (r.output, r.exception)
    assert "=== NR-U Radio Link ===" in r.output
# Rashed-Step 19.B.2-10-07-2026-end


# Rashed-Step 19.B.3-10-07-2026-start
# ---------------------------------------------------------------------
# 19.B.3 RRC_INACTIVE + resume
# ---------------------------------------------------------------------
from common.packet import Packet
from ran.protocol.buffer import ByteBuffer
from ran.protocol.inactive import InactiveConfig, compute_inactive_stats, inactive_config_from_cli, inactivity_manager


class _BufGnb(_FakeGnb):
    """Fake cell with a downlink and an uplink buffer for one UE; a packet
    is 'served' (removed) by drain()."""

    def __init__(self, env, script=((1e12, 10.0),)):
        super().__init__(env, list(script))
        self.dl, self.ul = ByteBuffer(), ByteBuffer()

    def ue_buffers(self, ue):
        return self.dl, self.ul

    def ue_has_pending(self, ue):
        return self.dl.backlog_bytes > 0 or self.ul.backlog_bytes > 0


def _pkt(i):
    return Packet(packet_id=str(i), source="a", destination="b", payload_bytes=100, header_bytes=0)


def _inactive_setup(cfg=None):
    env = simpy.Environment()
    g, ue = _BufGnb(env), _Ue()
    ue.rrc_state = RrcState.CONNECTED
    env.process(inactivity_manager(g, ue, cfg or InactiveConfig(), RrcLayer()))
    return env, g, ue


def test_idle_ue_is_released_after_the_timer():
    env, g, ue = _inactive_setup()
    env.run(until=95_000)
    assert ue.rrc_state is RrcState.CONNECTED
    env.run(until=105_000)
    assert ue.rrc_state is RrcState.INACTIVE and ue.rrc_releases == 1


def test_uplink_data_resumes_at_once():
    env, g, ue = _inactive_setup()
    env.run(until=150_000)
    g.ul.enqueue(_pkt(0))               # UE has something to send
    env.run(until=160_000)
    assert ue.rrc_state is RrcState.CONNECTED and ue.rrc_resumes == 1
    # Resume request 1 ms + RRCResume 2 ms + complete 1 ms.
    assert ue.rrc_resume_latencies_us == [4000.0]


def test_downlink_data_waits_for_the_paging_occasion():
    env, g, ue = _inactive_setup()
    env.run(until=150_000)
    g.dl.enqueue(_pkt(0))               # page at the next 320 ms occasion
    env.run(until=400_000)
    assert ue.rrc_state is RrcState.CONNECTED
    assert ue.rrc_resume_latencies_us == [320_000.0 - 150_000.0 + 4000.0]


def test_pending_data_keeps_the_ue_connected():
    env, g, ue = _inactive_setup()
    g.dl.enqueue(_pkt(0))               # never served by the fake cell
    env.run(until=1_000_000)
    assert ue.rrc_state is RrcState.CONNECTED and ue.rrc_releases == 0


def test_rlm_pauses_while_inactive():
    env = simpy.Environment()
    g, ue = _BufGnb(env, [(1e12, -30.0)]), _Ue()   # terrible link throughout
    ue.rrc_state = RrcState.CONNECTED
    env.process(inactivity_manager(g, ue, InactiveConfig(inactivity_timer_us=10_000.0), RrcLayer()))
    env.process(radio_link_monitor(g, ue, RlmConfig(t310_us=50_000.0), RrcLayer()))
    env.run(until=3_000_000)
    # Released after ~10 ms, long before T310 could expire; no RLF while INACTIVE.
    assert ue.rrc_state is RrcState.INACTIVE and ue.rlf_count == 0


def test_inactive_config_cli_and_licensed_run():
    assert inactive_config_from_cli(False, None, None) is None
    assert inactive_config_from_cli(True, 50.0, 160.0) == InactiveConfig(50_000.0, 160_000.0)
    _expect_value_error(lambda: inactive_config_from_cli(False, 50.0, None), "require --rrc-inactive")
    nr = ["--gnb-number", "1", "--ues-per-gnb", "2", "--seed", "2", "-t", "2",
          "--tdd-enabled", "--ue-uplink-enabled", "--rrc-enabled", "--rrc-inactive"]
    r = _cli(single_run_nr, nr + ["--dl-traffic", "poisson", "--dl-arrival-rate-pps", "5"])
    assert r.exit_code == 0, (r.output, r.exception)
    rel = int(re.search(r"NR RRC releases to INACTIVE: (\d+)", r.output).group(1))
    res = int(re.search(r"NR RRC resumes: (\d+)", r.output).group(1))
    assert rel > 0 and res > 0 and rel - res <= 2
    r = _cli(single_run_nr, nr)
    assert r.exit_code != 0 and "--rrc-inactive needs" in r.output
    r = _cli(single_run, ["--ap-number", "0", "--gnb-number", "1", "-t", "0.05", "-r", "1",
                          "--nru-ue-uplink-enabled", "--nru-rrc-enabled", "--rrc-inactive"])
    assert r.exit_code != 0 and "--nru-cot-model slots" in r.output
# Rashed-Step 19.B.3-10-07-2026-end
