# Rashed-Step 19.F-10-07-2026-start
"""
NR-U as a secondary cell (Step 19.F) - LAA-anchored carrier aggregation
(NruDeploymentMode.LAA_ANCHORED, recognized since Step 15.D, functional
now): a licensed-NR UE served by a gNB with a co-located NR-U gNB also
gets an NR-U SCell.

  - Control plane on the licensed PCell: RRC, random access, the 5G Core
    attach, radio link monitoring and handover stay there.
  - Uplink on the licensed PCell (LAA's split: DL in unlicensed, UL in
    licensed). The SCell leg has no uplink.
  - Downlink on both carriers from ONE queue: the SCell leg points at the
    UE's licensed downlink buffer, so whichever carrier has room serves
    it - one MAC entity scheduling over two carriers. HARQ stays per
    carrier (each gNB keeps its own entity for the buffer). NR-U's
    downlink is still LBT-gated: the SCell only carries data inside the
    NR-U gNB's COTs.
  - Activation: the SCell is active only while the UE is CONNECTED on
    the licensed cell AND still served by the co-located anchor gNB (a
    handover away deactivates it; coming back re-activates it).

ScellLeg is what the NR-U gNB schedules: same name and position as the
licensed UE, its RRC state / Core gate mirrored from it.
"""
from typing import Any, List

from ran.protocol.rrc import RrcState


class ScellLeg:
    uplink_enabled = False

    def __init__(self, ue: Any, anchor: Any, nru_gnb: Any):
        self.scell_of = ue
        self.anchor = anchor
        self.nru_gnb = nru_gnb
        self.name = ue.name
        self.packet_log: list = []

    def current_pos(self):
        return self.scell_of.current_pos()

    @property
    def rrc_state(self):
        ue = self.scell_of
        st = getattr(ue, "rrc_state", RrcState.CONNECTED)
        if st is RrcState.CONNECTED and getattr(ue, "gnb", self.anchor) is self.anchor:
            return RrcState.CONNECTED
        return RrcState.IDLE  # SCell deactivated

    @property
    def core_network(self):
        return getattr(self.scell_of, "core_network", None)


def attach_scells(nr_gnbs: List[Any], nru_gnbs: List[Any]) -> List[ScellLeg]:
    """Give every licensed UE of nr_gnbs[i] an SCell on nru_gnbs[i] (the
    co-located NR-U gNB), sharing its licensed downlink buffer."""
    legs = []
    for lic, nru in zip(nr_gnbs, nru_gnbs):
        for ue in list(lic.ue_list):
            buf = lic.dl_buffers[ue.name]
            leg = ScellLeg(ue, lic, nru)
            nru.ue_list.append(leg)
            nru.dl_buffers[leg.name] = buf
            # New downlink data wakes the NR-U gNB too (it only contends
            # when it has work).
            prev = buf.on_enqueue
            kick = nru._kick_slots
            buf.on_enqueue = kick if prev is None else (lambda p=prev, k=kick: (p(), k()))
            ue.scell_leg = leg
            legs.append(leg)
    return legs


def print_scell_stats(nr_gnbs: List[Any], nru_gnbs: List[Any], legs: List[ScellLeg], simulation_time: float) -> dict:
    from common.packet import compute_packet_stats
    names = {leg.name for leg in legs}
    pcell_bits = sum(g.bits_delivered for g in nr_gnbs)
    scell_bits = sum(g.slot_stats.get("scell_dl_bits", 0) for g in nru_gnbs)
    total = pcell_bits + scell_bits
    pkts = [p for g in list(nr_gnbs) + list(nru_gnbs) for p in g.packet_log
            if p.destination in names]
    ps = compute_packet_stats(pkts)
    s = {
        "ues": len(legs),
        "pcell_mbps": pcell_bits / (simulation_time * 1e6) if simulation_time > 0 else 0.0,
        "scell_mbps": scell_bits / (simulation_time * 1e6) if simulation_time > 0 else 0.0,
        "scell_share": (scell_bits / total) if total else 0.0,
        "packet_stats": ps,
    }
    print("=== NR-U SCell (LAA) ===")
    print(f"LAA UEs with an NR-U SCell: {s['ues']}")
    print(f"LAA DL throughput on the licensed PCell (Mbps): {s['pcell_mbps']}")
    print(f"LAA DL throughput on the NR-U SCell (Mbps): {s['scell_mbps']}")
    print(f"LAA DL share carried by the NR-U SCell: {s['scell_share']}")
    print(f"LAA DL packets delivered (both carriers): {ps['delivered']}, dropped: {ps['dropped']}")
    print(f"LAA DL packet avg latency (us): {ps['avg_latency_us']}")
    return s
# Rashed-Step 19.F-10-07-2026-end
