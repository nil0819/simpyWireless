# Rashed-Step pre_17.A-10-04-2026-start
"""
Step pre_17.A tests: nru.nru.Gnb downlink packet destination.

Before the fix, Gnb._make_packet() stamped destination = ue_list[0] on
every packet while gen_new_transmission() picked the real receiver
(tx.rx_ue) at random - and re-picked it on every retry. Now the
destination is the UE actually picked, a retry keeps its receiver while
that UE is still eligible, and a packet sent with no eligible UE carries
the gNB's own name.
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
from nru.nru import Gnb, Config_NR
from nru.ue import NrUE


def _make_channel(env):
    return Channel(
        tx_queue=simpy.PriorityResource(env, capacity=1),
        tx_lock=simpy.Resource(env, capacity=1),
        n_of_stations=0, n_of_gNB=1, backoffs={},
        airtime_data={}, airtime_control={},
        airtime_data_NR={}, airtime_control_NR={},
    )


class _NoAutoStartGnb(Gnb):
    """gNB whose own downlink loop never runs, so gen_new_transmission()
    can be driven directly."""
    def start(self):
        return
        yield


class _RecordingGnb(Gnb):
    """Real, running gNB that records the receiver of every attempt."""
    def gen_new_transmission(self, packet=None):
        tx = super().gen_new_transmission(packet)
        self.rx_log = getattr(self, "rx_log", [])
        self.rx_log.append((tx.packet.packet_id, tx.rx_ue.name if tx.rx_ue else None))
        return tx


def _cell(n_ues=3, gnb_cls=_NoAutoStartGnb):
    env = simpy.Environment()
    channel = _make_channel(env)
    ues = [NrUE(name=f"UE 1-{i}", pos=(10.0 + i, 0.0), gnb_name="G1") for i in range(1, n_ues + 1)]
    gnb = gnb_cls(env, "G1", channel, (0.0, 0.0), ues, Config_NR())
    return env, gnb, ues


def test_destination_is_the_receiver_actually_picked():
    random.seed(1)
    env, gnb, ues = _cell()
    seen = set()
    for _ in range(50):
        tx = gnb.gen_new_transmission()
        assert tx.packet.destination == tx.rx_ue.name
        seen.add(tx.rx_ue.name)
    assert seen == {"UE 1-1", "UE 1-2", "UE 1-3"}  # not stuck on ue_list[0]


def test_retry_keeps_its_receiver():
    random.seed(2)
    env, gnb, ues = _cell()
    packet = gnb._make_packet()
    first = gnb.gen_new_transmission(packet).rx_ue.name
    packet.retry_count = 1
    for _ in range(30):
        tx = gnb.gen_new_transmission(packet)
        assert tx.rx_ue.name == first
        assert packet.destination == first


def test_retry_repicks_when_previous_receiver_no_longer_eligible():
    random.seed(3)
    env, gnb, ues = _cell()
    packet = gnb._make_packet()
    first_ue = gnb.gen_new_transmission(packet).rx_ue
    packet.retry_count = 1
    first_ue.rrc_state = RrcState.CONNECTING  # drops out of candidate_ues
    for _ in range(20):
        tx = gnb.gen_new_transmission(packet)
        assert tx.rx_ue is not first_ue
        assert packet.destination == tx.rx_ue.name


def test_no_eligible_ue_credits_the_gnb_not_a_ue():
    env, gnb, ues = _cell()
    for ue in ues:
        ue.rrc_state = RrcState.CONNECTING
    tx = gnb.gen_new_transmission()
    assert tx.rx_ue is None
    assert tx.packet.destination == "G1"


def test_single_ue_cell_unchanged():
    """One UE: the receiver is always that UE, exactly as before (the
    random draw still happens, so the RNG stream is untouched too)."""
    random.seed(4)
    env, gnb, (ue,) = _cell(n_ues=1)
    for _ in range(10):
        tx = gnb.gen_new_transmission()
        assert tx.rx_ue is ue and tx.packet.destination == "UE 1-1"


def test_running_multi_ue_cell_log_matches_real_receivers():
    """End to end on a running gNB: every logged packet's destination is
    the receiver of its last attempt, and the cell really serves several
    UEs."""
    random.seed(5)
    env, gnb, ues = _cell(gnb_cls=_RecordingGnb)
    env.run(until=300_000)
    last_rx = {}
    for pid, rx in gnb.rx_log:
        last_rx[pid] = rx
    assert len(gnb.packet_log) > 20
    for p in gnb.packet_log:
        assert p.destination == last_rx[p.packet_id]
    assert len({p.destination for p in gnb.packet_log}) > 1
# Rashed-Step pre_17.A-10-04-2026-end
