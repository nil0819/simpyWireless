# Rashed-Step 17.C-10-04-2026-start
"""
Step 17 tests: NR-U uplink inside the gNB's COT (COT sharing).

17.C covers the gNB side only: in COT_SHARING mode with at least one
eligible UE, the downlink uses the first (1 - ul_cot_fraction) of the
COT, then the gNB opens an uplink window for the rest and holds until it
ends. Otherwise the whole COT is downlink, exactly as before.

The eligible UE is a real uplink-capable NrUE. (In 17.C it was a passive
UE with uplink_enabled flipped on, since the window did nothing yet; 17.E
made the window actually call the UE, which needs the real thing. In
COT_SHARING a real uplink UE runs no autonomous loop, so the gNB still
fully controls the timing.)
"""

import random
import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import simpy

from channel.channel import Channel
from ran.protocol.rrc import RrcState
from nru.nru import Gnb, Config_NR, NruUplinkAccessMode
from nru.ue import NrUE


def _make_channel(env):
    return Channel(
        tx_queue=simpy.PriorityResource(env, capacity=1),
        tx_lock=simpy.Resource(env, capacity=1),
        n_of_stations=0, n_of_gNB=1, backoffs={},
        airtime_data={}, airtime_control={},
        airtime_data_NR={}, airtime_control_NR={},
    )


def _cell(mode=NruUplinkAccessMode.COT_SHARING, fraction=0.5, eligible=True, seed=1):
    random.seed(seed)
    env = simpy.Environment()
    channel = _make_channel(env)
    cfg = Config_NR(ul_access_mode=mode, ul_cot_fraction=fraction)
    # Rashed-Step 17.E-10-04-2026: real uplink UE (see module docstring).
    if eligible:
        ue = NrUE(name="UE 1-1", pos=(10.0, 0.0), gnb_name="Gnb 1",
                  env=env, channel=channel, config_nr=cfg, uplink_enabled=True)
    else:
        ue = NrUE(name="UE 1-1", pos=(10.0, 0.0), gnb_name="Gnb 1")
    gnb = Gnb(env, "Gnb 1", channel, (0.0, 0.0), [ue], cfg)
    txs = []
    original = channel.register_tx
    def recording(tx):
        txs.append(tx)
        return original(tx)
    channel.register_tx = recording
    return env, channel, cfg, gnb, ue, txs


def _durations(txs):
    return [tx.t_end - tx.tx_start for tx in txs if tx.tx_id == "Gnb 1"]


def test_autonomous_mode_keeps_full_cot_downlink_and_no_window():
    env, channel, cfg, gnb, ue, txs = _cell(mode=NruUplinkAccessMode.AUTONOMOUS)
    env.run(until=60_000)
    assert _durations(txs) and set(_durations(txs)) == {cfg.mcot * 1000}
    assert gnb.ul_windows == []


def test_cot_sharing_without_eligible_ue_keeps_full_cot_downlink():
    env, channel, cfg, gnb, ue, txs = _cell(eligible=False)
    env.run(until=60_000)
    assert set(_durations(txs)) == {cfg.mcot * 1000}
    assert gnb.ul_windows == []


def test_cot_sharing_splits_cot_into_downlink_then_uplink_window():
    env, channel, cfg, gnb, ue, txs = _cell(fraction=0.5)
    env.run(until=60_000)
    cot = cfg.mcot * 1000
    dl = [tx for tx in txs if tx.tx_id == "Gnb 1"]
    assert dl and all(tx.t_end - tx.tx_start == cot * 0.5 for tx in dl)
    assert len(gnb.ul_windows) == gnb.succeeded_transmissions > 0
    for tx, w in zip(dl, gnb.ul_windows):
        # Window starts when that downlink ends and fills the rest of the COT.
        assert w["start"] == tx.t_end
        assert w["end"] - w["start"] == cot * 0.5
        assert w["ues"] == ["UE 1-1"]
    # The gNB doesn't start another transmission until its COT is over.
    for w, nxt in zip(gnb.ul_windows, dl[1:]):
        assert nxt.tx_start >= w["end"]


def test_ul_fraction_sets_the_split():
    env, channel, cfg, gnb, ue, txs = _cell(fraction=0.25)
    env.run(until=40_000)
    cot = cfg.mcot * 1000
    assert set(_durations(txs)) == {cot * 0.75}
    assert {w["end"] - w["start"] for w in gnb.ul_windows} == {cot * 0.25}


def test_airtime_counts_actual_transmissions_only():
    """Occupancy counts actual transmissions: the gNB gets its downlink
    part, the UE its uplink (window minus the 25us Type 2A check) -
    never the whole COT for either. (17.C version: window unused, only
    the downlink counted.)"""
    env, channel, cfg, gnb, ue, txs = _cell(fraction=0.5)
    env.run(until=60_000)
    half = cfg.mcot * 1000 * 0.5
    assert channel.airtime_data_NR["Gnb 1"] == gnb.succeeded_transmissions * half
    assert ue.succeeded_transmissions > 0
    assert channel.airtime_data_NR["UE 1-1"] == ue.succeeded_transmissions * (half - cfg.ul_type2a_sense_us)


def test_ue_not_rrc_connected_is_not_given_a_window():
    env, channel, cfg, gnb, ue, txs = _cell()
    ue.rrc_state = RrcState.CONNECTING
    env.run(until=40_000)
    assert gnb.ul_windows == []
    assert set(_durations(txs)) == {cfg.mcot * 1000}


def test_window_opens_only_after_a_successful_downlink():
    """Grants ride in the downlink: a failed downlink opens no window.
    Forced here by making every SINR check fail."""
    env, channel, cfg, gnb, ue, txs = _cell()
    channel.sinr_db = lambda tx: -100.0
    env.run(until=40_000)
    assert gnb.failed_transmissions > 0 and gnb.succeeded_transmissions == 0
    assert gnb.ul_windows == []
# Rashed-Step 17.C-10-04-2026-end


# Rashed-Step 17.D-10-04-2026-start
# ---------------------------------------------------------------------
# 17.D: the UE side - Type 2A LBT (25us) and one uplink transmission
# inside a granted window (NrUE.type2a_lbt / send_in_shared_cot). Driven
# directly here; 17.E wires it to the gNB's window. A loud interferer
# right next to the UE is placed on the channel at chosen times to make
# the Type 2A check fail or pass.
# ---------------------------------------------------------------------

from channel.channel import ActiveTx


class _NoLoopUE(NrUE):
    """Uplink-capable UE without its own autonomous uplink loop."""
    def start_uplink(self):
        return
        yield


class _QuietGnb(Gnb):
    """gNB that never transmits on its own."""
    def start(self):
        return
        yield


def _ue_cell():
    random.seed(1)
    env = simpy.Environment()
    channel = _make_channel(env)
    cfg = Config_NR()
    ue = _NoLoopUE(name="UE 1-1", pos=(10.0, 0.0), gnb_name="Gnb 1",
                   env=env, channel=channel, config_nr=cfg, uplink_enabled=True)
    gnb = _QuietGnb(env, "Gnb 1", channel, (0.0, 0.0), [ue], cfg)
    return env, channel, cfg, gnb, ue


def _interferer(env, channel, start, end, pos=(11.0, 0.0)):
    def proc():
        yield env.timeout(start)
        tx = ActiveTx(tx_id="Wi-Fi X", tx_pos=pos, tx_start=env.now, rx_pos=(12.0, 0.0),
                      tx_power_dbm=20.0, f_hz=channel_f(), pl_exp=3.0,
                      t_end=end, tech="WiFi")
        channel.register_tx(tx)
        yield env.timeout(end - start)
        channel.unregister_tx(tx, success=False)
    env.process(proc())


def channel_f():
    return Config_NR().f_ghz


def _grant(env, ue, at, window_us, results):
    def proc():
        yield env.timeout(at)
        results.append((yield from ue.send_in_shared_cot(window_us)))
    env.process(proc())


def test_type2a_on_idle_channel_sends_for_rest_of_window():
    env, channel, cfg, gnb, ue, = _ue_cell()
    txs = []
    original = channel.register_tx
    channel.register_tx = lambda tx: (txs.append(tx), original(tx))[1]
    results = []
    _grant(env, ue, 1000, 3000, results)
    env.run(until=10_000)
    assert results == [True]
    (tx,) = [t for t in txs if t.tx_id == "UE 1-1"]
    assert tx.tx_start == 1000 + cfg.ul_type2a_sense_us
    assert tx.t_end == 1000 + 3000  # exactly fills the window
    assert ue.ul_grants_received == 1 and ue.type2a_skips == 0
    assert [p.status for p in ue.packet_log] == ["DELIVERED"]
    assert channel.airtime_data_NR["UE 1-1"] == 3000 - cfg.ul_type2a_sense_us
    assert ue.transmission_to_send is None  # next grant starts a new packet


def test_type2a_busy_at_start_skips_grant():
    env, channel, cfg, gnb, ue = _ue_cell()
    _interferer(env, channel, 900, 1500)
    results = []
    _grant(env, ue, 1000, 3000, results)
    env.run(until=10_000)
    assert results == [None]
    assert ue.type2a_skips == 1 and ue.succeeded_transmissions == 0 and ue.failed_transmissions == 0
    assert "UE 1-1" not in channel.airtime_data_NR or channel.airtime_data_NR["UE 1-1"] == 0


def test_type2a_busy_during_sensing_skips_grant():
    env, channel, cfg, gnb, ue = _ue_cell()
    _interferer(env, channel, 1010, 1500)  # appears 10us into the 25us check
    results = []
    _grant(env, ue, 1000, 3000, results)
    env.run(until=10_000)
    assert results == [None] and ue.type2a_skips == 1


def test_type2a_does_not_protect_after_sensing():
    """Something starting after the 25us check is not detected - the UE
    sends anyway (and here loses on SINR), as in real Type 2A. The
    interferer sits next to the gNB - the uplink's receiver - so it
    breaks the SINR there."""
    env, channel, cfg, gnb, ue = _ue_cell()
    _interferer(env, channel, 1100, 4500, pos=(0.5, 0.0))
    results = []
    _grant(env, ue, 1000, 3000, results)
    env.run(until=10_000)
    assert results == [False]
    assert ue.type2a_skips == 0 and ue.failed_transmissions == 1


def test_failed_packet_is_retried_on_next_grant_then_new_packet():
    env, channel, cfg, gnb, ue = _ue_cell()
    _interferer(env, channel, 1100, 4500, pos=(0.5, 0.0))  # at the gNB: first grant fails on SINR
    results = []
    _grant(env, ue, 1000, 3000, results)
    _grant(env, ue, 8000, 3000, results)   # clean second grant
    _grant(env, ue, 15000, 3000, results)  # third grant: new packet
    env.run(until=20_000)
    assert results == [False, True, True]
    first, second = ue.packet_log
    assert first.packet_id == "UE 1-1-000001" and first.retry_count == 1 and first.status == "DELIVERED"
    assert second.packet_id == "UE 1-1-000002" and second.retry_count == 0
# Rashed-Step 17.D-10-04-2026-end


# Rashed-Step 17.E-10-04-2026-start
# ---------------------------------------------------------------------
# 17.E: end to end - running gNB + real uplink UEs, COT_SHARING (the
# default now). The gNB grants its uplink window to one UE per COT,
# round-robin; UEs run no Cat-4 of their own.
# ---------------------------------------------------------------------

from core.network import CoreNetwork


def _running_cell(n_ues=1, mode=None, rrc=False, seed=1):
    random.seed(seed)
    env = simpy.Environment()
    channel = _make_channel(env)
    cfg = Config_NR() if mode is None else Config_NR(ul_access_mode=mode)
    ues = [NrUE(name=f"UE 1-{i}", pos=(10.0 + i, 0.0), gnb_name="Gnb 1",
                env=env, channel=channel, config_nr=cfg,
                uplink_enabled=True, rrc_enabled=rrc)
           for i in range(1, n_ues + 1)]
    gnb = Gnb(env, "Gnb 1", channel, (0.0, 0.0), ues, cfg)
    starts = []
    original = channel.register_tx
    channel.register_tx = lambda tx: (starts.append((tx.tx_id, tx.tx_start)), original(tx))[1]
    return env, channel, cfg, gnb, ues, starts


def test_default_is_cot_sharing_and_fixes_single_cell_self_collision():
    """The 17.A failure case (one gNB + its own uplink UE, both
    saturated): autonomous delivers nothing either way; COT sharing
    delivers in both directions and the two never start together."""
    env, channel, cfg, gnb, (ue,), starts = _running_cell(mode=NruUplinkAccessMode.AUTONOMOUS)
    env.run(until=300_000)
    assert gnb.succeeded_transmissions == 0 and ue.succeeded_transmissions == 0

    env, channel, cfg, gnb, (ue,), starts = _running_cell()
    assert cfg.ul_access_mode is NruUplinkAccessMode.COT_SHARING
    env.run(until=300_000)
    assert gnb.failed_transmissions == 0 and ue.failed_transmissions == 0
    assert gnb.succeeded_transmissions > 10
    # One window per successful downlink; the last may still be in
    # progress when the run stops, so compare completed windows.
    assert len(gnb.ul_windows) == gnb.succeeded_transmissions
    completed = [w for w in gnb.ul_windows if w["result"] is not None]
    assert ue.succeeded_transmissions == len(completed) >= len(gnb.ul_windows) - 1
    gnb_starts = {t for who, t in starts if who == "Gnb 1"}
    assert not any(t in gnb_starts for who, t in starts if who == "UE 1-1")
    assert all(p.status == "DELIVERED" for p in ue.packet_log)


def test_window_grants_rotate_round_robin():
    env, channel, cfg, gnb, ues, starts = _running_cell(n_ues=3)
    env.run(until=300_000)
    granted = [w["granted"] for w in gnb.ul_windows]
    assert len(granted) >= 9
    assert granted[:6] == ["UE 1-1", "UE 1-2", "UE 1-3"] * 2
    counts = [ue.ul_grants_received for ue in ues]
    assert max(counts) - min(counts) <= 1
    assert all(ue.succeeded_transmissions > 0 for ue in ues)


def test_skipped_grant_still_holds_gnb_until_window_end():
    """If the granted UE's Type 2A check fails, the rest of the window is
    left idle - the gNB doesn't reclaim it - and the next COT starts no
    earlier than the window end."""
    env, channel, cfg, gnb, (ue,), starts = _running_cell()
    busy_until = {"t": 0}
    original_busy = ue._channel_busy
    def busy_first_window():
        if not gnb.ul_windows or len(gnb.ul_windows) > 1:
            return original_busy()
        return True
    ue._channel_busy = busy_first_window
    env.run(until=40_000)
    first, second = gnb.ul_windows[0], gnb.ul_windows[1]
    assert first["result"] is None and ue.type2a_skips == 1
    assert second["result"] is True
    gnb_starts = sorted(t for who, t in starts if who == "Gnb 1")
    assert gnb_starts[1] >= first["end"]


def test_no_windows_until_rrc_connected():
    env, channel, cfg, gnb, (ue,), starts = _running_cell(rrc=True)
    env.run(until=300_000)
    assert ue.rrc_state is RrcState.CONNECTED
    assert gnb.ul_windows and all(w["start"] >= ue.rrc_connected_at for w in gnb.ul_windows)


def test_no_windows_until_pdu_session_active():
    env, channel, cfg, gnb, (ue,), starts = _running_cell()
    core = CoreNetwork(env)
    core.start_ue(gnb, ue)
    env.run(until=400_000)
    activated = ue.pdu_session.activated_at
    assert activated is not None
    assert gnb.ul_windows and all(w["start"] >= activated for w in gnb.ul_windows)
    assert all(p.created_at >= activated for p in ue.packet_log)
# Rashed-Step 17.E-10-04-2026-end


# Rashed-Step 17.F-10-04-2026-start
# ---------------------------------------------------------------------
# 17.F: RRC uplink messages in COT sharing - grant delay, then the next
# successful downlink COT of the UE's own gNB, then a 25us Type 2A check
# at its end (next COT if busy). No Cat-4 by the UE.
# ---------------------------------------------------------------------

def _rrc_cell(seed, gnb_cls=Gnb):
    random.seed(seed)
    env = simpy.Environment()
    channel = _make_channel(env)
    cfg = Config_NR()
    ue = NrUE(name="UE 1-1", pos=(10.0, 0.0), gnb_name="Gnb 1",
              env=env, channel=channel, config_nr=cfg,
              uplink_enabled=True, rrc_enabled=True)
    gnb = gnb_cls(env, "Gnb 1", channel, (0.0, 0.0), [ue], cfg)
    dl_ends = []
    original = channel.unregister_tx
    def recording(tx, success=True):
        if tx.tx_id == "Gnb 1" and success:
            dl_ends.append(tx.t_end)
        return original(tx, success=success)
    channel.unregister_tx = recording
    return env, cfg, gnb, ue, dl_ends


def test_rrc_messages_ride_the_gnbs_downlink_cots():
    for seed in range(1, 6):
        env, cfg, gnb, ue, dl_ends = _rrc_cell(seed)
        env.run(until=200_000)
        assert ue.rrc_state is RrcState.CONNECTED, seed
        sense = cfg.ul_type2a_sense_us
        # Both uplink RRC messages leave exactly one Type 2A check after
        # the end of one of this gNB's successful downlinks...
        assert ue.rrc_setup_request_sent_at - sense in dl_ends, seed
        assert ue.rrc_setup_complete_sent_at - sense in dl_ends, seed
        # ...and not before the grant delay.
        assert ue.rrc_setup_request_sent_at >= ue.rrc_attach_started_at + cfg.rrc_ul_grant_delay_us
        assert ue.rrc_setup_complete_sent_at >= ue.rrc_setup_received_at + cfg.rrc_ul_grant_delay_us
        # No data windows before CONNECTED (17.E), so these were
        # full-COT downlinks.
        assert all(w["start"] >= ue.rrc_connected_at for w in gnb.ul_windows)


def test_rrc_cot_sharing_never_faster_than_licensed():
    for seed in range(1, 11):
        env, cfg, gnb, ue, dl_ends = _rrc_cell(seed)
        env.run(until=200_000)
        latency = ue.rrc_connected_at - ue.rrc_attach_started_at
        assert latency >= 2 * cfg.rrc_ul_grant_delay_us + gnb._rrc_layer.setup_processing_delay_us


def test_rrc_waits_for_next_cot_when_type2a_busy():
    env, cfg, gnb, ue, dl_ends = _rrc_cell(1)
    calls = {"n": 0}
    original_busy = ue._channel_busy
    def busy_on_first_check():
        calls["n"] += 1
        return True if calls["n"] == 1 else original_busy()
    ue._channel_busy = busy_on_first_check
    env.run(until=200_000)
    assert ue.rrc_state is RrcState.CONNECTED
    assert ue.rrc_type2a_skips == 1
    sense = cfg.ul_type2a_sense_us
    # The request went out after the SECOND downlink end it could use.
    usable = [t for t in dl_ends if t >= ue.rrc_attach_started_at + cfg.rrc_ul_grant_delay_us]
    assert ue.rrc_setup_request_sent_at == usable[1] + sense


def test_rrc_never_completes_without_a_transmitting_gnb():
    """By design: in COT sharing the grant comes in the gNB's COT, so a
    gNB that never transmits never lets the UE attach."""
    env, cfg, gnb, ue, dl_ends = _rrc_cell(1, gnb_cls=_QuietGnb)
    env.run(until=200_000)
    assert dl_ends == []
    assert ue.rrc_state is RrcState.CONNECTING
# Rashed-Step 17.F-10-04-2026-end


# Rashed-Step 17.G-10-04-2026-start
# ---------------------------------------------------------------------
# 17.G: singleRun.py --nru-ul-access-mode / --nru-ul-cot-fraction and the
# "NR-U Uplink" stdout block. CliRunner in an isolated filesystem so
# packet.log doesn't land in the repo.
# ---------------------------------------------------------------------

from click.testing import CliRunner
from singleRun import single_run

_CLI = ["--ap-number", "0", "--gnb-number", "1", "-t", "0.3", "-r", "1", "--seed", "1"]


def _cli(args):
    runner = CliRunner()
    with runner.isolated_filesystem():
        return runner.invoke(single_run, args)


def _value(output, label):
    for line in output.splitlines():
        if line.startswith(label + ": "):
            return line.split(": ", 1)[1]
    raise AssertionError(f"{label!r} not in output")


def test_cli_no_uplink_block_without_nru_uplink():
    r = _cli(_CLI)
    assert r.exit_code == 0, r.output
    assert "NR-U Uplink" not in r.output


def test_cli_default_mode_is_cot_sharing_and_delivers():
    r = _cli(_CLI + ["--nru-ue-uplink-enabled"])
    assert r.exit_code == 0, (r.output, r.exception)
    assert _value(r.output, "NRU uplink access mode") == "cot_sharing"
    assert int(_value(r.output, "NRU uplink packets delivered")) > 0
    assert _value(r.output, "NRU COT uplink fraction") == "0.5"
    assert int(_value(r.output, "NRU uplink windows opened")) > 0


def test_cli_autonomous_mode_reproduces_self_collision():
    r = _cli(_CLI + ["--nru-ue-uplink-enabled", "--nru-ul-access-mode", "autonomous"])
    assert r.exit_code == 0, r.output
    assert _value(r.output, "NRU uplink access mode") == "autonomous"
    assert _value(r.output, "NRU uplink packets delivered") == "0"
    assert "NRU uplink windows opened" not in r.output


def test_cli_cot_fraction_changes_split_and_is_validated():
    r = _cli(_CLI + ["--nru-ue-uplink-enabled", "--nru-ul-cot-fraction", "0.25"])
    assert r.exit_code == 0, r.output
    assert _value(r.output, "NRU COT uplink fraction") == "0.25"
    bad = _cli(_CLI + ["--nru-ul-cot-fraction", "1.0"])
    assert bad.exit_code != 0 and "strictly between 0 and 1" in bad.output
# Rashed-Step 17.G-10-04-2026-end
