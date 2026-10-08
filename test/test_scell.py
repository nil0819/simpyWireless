# Rashed-Step 19.F-10-07-2026-start
"""
Step 19.F tests: NR-U as a secondary cell (LAA-anchored carrier
aggregation, ran/protocol/scell.py).
(Step pre_19.F has its own test file, test_nru_harq_multi_ue.py.)
"""

import contextlib
import io
import logging
import os
import re
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from click.testing import CliRunner

import simulation
from common.packet import Packet, TrafficConfig
from nru.nru import Config_NR, NruUplinkAccessMode
from ran.protocol.buffer import ByteBuffer
from ran.protocol.harq import HarqConfig
from ran.protocol.rrc import RrcState
from ran.protocol.scell import ScellLeg, attach_scells
from singleRun import single_run
from wifi.wifi import Config


class _Ue:
    def __init__(self, gnb):
        self.name, self.gnb, self.rrc_state, self.pos = "UeNR 1-1", gnb, RrcState.CONNECTED, (1.0, 2.0)

    def current_pos(self):
        return self.pos


def test_leg_mirrors_the_licensed_ue_and_deactivates_after_handover():
    anchor, other = object(), object()
    ue = _Ue(anchor)
    ue.core_network = "core"
    leg = ScellLeg(ue, anchor, nru_gnb=None)
    assert leg.name == ue.name and leg.current_pos() == (1.0, 2.0) and not leg.uplink_enabled
    assert leg.rrc_state is RrcState.CONNECTED and leg.core_network == "core"
    ue.rrc_state = RrcState.INACTIVE
    assert leg.rrc_state is RrcState.IDLE
    ue.rrc_state, ue.gnb = RrcState.CONNECTED, other        # handed over away from the anchor
    assert leg.rrc_state is RrcState.IDLE
    ue.gnb = anchor
    assert leg.rrc_state is RrcState.CONNECTED


def test_attach_shares_the_downlink_queue_and_wakes_the_nru_gnb():
    class Lic:
        def __init__(self):
            self.ue_list = []
            self.dl_buffers = {}

    class Nru:
        def __init__(self):
            self.ue_list, self.dl_buffers, self.kicks = [], {}, 0

        def _kick_slots(self):
            self.kicks += 1

    lic, nru = Lic(), Nru()
    ue = _Ue(lic)
    lic.ue_list.append(ue)
    lic.dl_buffers[ue.name] = ByteBuffer()
    legs = attach_scells([lic], [nru])
    assert len(legs) == 1 and nru.ue_list == legs and ue.scell_leg is legs[0]
    assert nru.dl_buffers[ue.name] is lic.dl_buffers[ue.name]          # one queue, two carriers
    lic.dl_buffers[ue.name].enqueue(Packet(packet_id="p", source="g", destination=ue.name,
                                           payload_bytes=100, header_bytes=0))
    assert nru.kicks == 1


BASE = ["--ap-number", "1", "--gnb-number", "1", "--seed", "1", "-t", "0.5", "-r", "1",
        "--nru-cot-model", "slots", "--nru-traffic-model", "poisson", "--nru-arrival-rate-pps", "20",
        "--nr-gnb-number", "1", "--nr-colocated", "--nr-bandwidth-mhz", "20",
        "--nr-dl-traffic", "poisson", "--nr-dl-arrival-rate-pps", "4000"]


def _cli(args):
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("log", exist_ok=True)
        return runner.invoke(single_run, args)


def test_laa_adds_unlicensed_capacity_to_an_overloaded_pcell():
    alone, laa = _cli(BASE), _cli(BASE + ["--nru-scell", "--harq"])
    assert alone.exit_code == 0 and laa.exit_code == 0, (alone.output[-400:], laa.output[-400:])
    num = lambda o, label: float(re.search(re.escape(label) + r" ([\d.]+)", o).group(1))
    pcell_only = num(alone.output, "NR DL delivered throughput (Mbps):")
    total = num(laa.output, "NR DL delivered throughput (Mbps):")
    scell = num(laa.output, "LAA DL throughput on the NR-U SCell (Mbps):")
    assert scell > 5 and total > pcell_only + 5
    assert "=== NR-U SCell (LAA) ===" in laa.output and "LAA UEs with an NR-U SCell: 4" in laa.output


def test_scell_validation():
    r = _cli(BASE[:10] + ["--nr-gnb-number", "1", "--nr-dl-traffic", "cbr", "--nru-scell"])
    assert r.exit_code != 0 and "co-located" in r.output
    r = _cli([a for a in BASE if a not in ("--nr-dl-traffic", "poisson")][:-0 or None] + ["--nru-scell"])
    assert r.exit_code != 0
    r = _cli(BASE + ["--nru-scell", "--nru-ue-uplink-enabled"])
    assert r.exit_code != 0 and "LAA's uplink is on the licensed PCell" in r.output
# Rashed-Step 19.F-10-07-2026-end
