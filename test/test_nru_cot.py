# Rashed-Step 17.C-10-04-2026-start
"""
Step 17 tests: NR-U uplink inside the gNB's COT (COT sharing).

17.C covers the gNB side only: in COT_SHARING mode with at least one
eligible UE, the downlink uses the first (1 - ul_cot_fraction) of the
COT, then the gNB opens an uplink window for the rest and holds until it
ends. Otherwise the whole COT is downlink, exactly as before.

To test the gNB alone, "eligible UE" here is a passive NrUE with
uplink_enabled flipped on after construction - eligible for the gNB's
filter, but without starting its own (autonomous) uplink process.
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
    ue = NrUE(name="UE 1-1", pos=(10.0, 0.0), gnb_name="Gnb 1")
    if eligible:
        ue.uplink_enabled = True  # eligible for the gNB, no own uplink process
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


def test_unused_window_is_not_counted_as_nru_airtime():
    """Occupancy counts actual transmissions: with nobody sending in the
    uplink window yet (17.C), only the downlink part is NR-U airtime."""
    env, channel, cfg, gnb, ue, txs = _cell(fraction=0.5)
    env.run(until=60_000)
    assert channel.airtime_data_NR["Gnb 1"] == gnb.succeeded_transmissions * cfg.mcot * 1000 * 0.5


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
