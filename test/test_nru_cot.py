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
