# Rashed-Step 9.C-08-07-2026-start
"""
Standalone entry point for the packet-attacker scenario (Step 9.C) -
drops one or more attacker.packet_attacker.PacketAttacker nodes into a
REAL WiFi + NR-U coexistence topology (the same wifi.WiFi/nru.Gnb
classes simulation.py already uses) and drives them through a 3-phase
attack timeline: capture (passive sniffing) -> spoof (forged-source
transmissions) -> replay (re-transmit captured content).

Deliberately kept separate from simulation.py/singleRun.py, same
"standalone first" pattern as simulation_nr.py (Step 6.B) and
simulation_spectrum.py (Step 7.B) - confirmed with Rashed via
AskUserQuestion for 9.C: a new standalone file, not touching the
already-verified singleRun.py/simulation.py or the existing
attacker/roguewificad.py / roguewifijammer.py / roguewifiselfbackoff.py
files (all three remain completely untouched by this step).

WHAT "ATTACK IMPACT" MEANS IN THIS SCENARIO'S OUTPUT
The attacker's forged/replayed transmissions are completely real
ActiveTx entries on the shared channel (real tx power, position,
duration) - so they DO consume airtime and DO count as real
interference in every real WiFi AP / NR-U gNB's own already-verified
SINR/collision math, exactly like any other transmitter. This
scenario's printed results reflect that: real WiFi/NR-U succ/fail
counts are printed the same way singleRun.py does, so a comparison run
with --spoof-count 0 --replay-max 0 (i.e. capture-only, no actual
transmissions) shows the attacker's channel-level impact by contrast.
What is NOT modeled (see attacker/packet_attacker.py's module
docstring): any real receiver being fooled by the forged/replayed
packet's CONTENT - there is no receiver-side application logic in this
simulator for that at all, attacker or not.
"""

import random
import simpy
from typing import List, Optional
from dataclasses import dataclass, field

from common.common import Pos, rand_pos, dist
from common.common_phy import WaypointMobility, check_eirp_compliance
from channel.channel import Channel
from wifi.wifi import WiFi, Config as WifiConfig
from wifi.sta import WiFiSTA
from nru.nru import Gnb, Config_NR
from nru.ue import NrUE
from attacker.packet_attacker import Config_PacketAttacker, PacketAttacker


def rand_pos_near(center: Pos, radius: float) -> Pos:
    import math
    angle = random.uniform(0, 2 * math.pi)
    r = radius * math.sqrt(random.random())
    return (center[0] + r * math.cos(angle), center[1] + r * math.sin(angle))


@dataclass
class AttackerReport:
    name: str
    pos: Pos
    captured_count: int = 0
    captured_ids: List[str] = field(default_factory=list)
    spoofed_count: int = 0
    replayed_count: int = 0
    airtime_us: float = 0.0


def _attacker_process(env, attacker: PacketAttacker, report: AttackerReport,
                       capture_window_us: float, sniff_interval_us: float,
                       spoof_count: int, spoof_interval_us: float,
                       spoof_target: str, spoof_payload_bytes: int,
                       replay_interval_us: float, replay_max: Optional[int]):
    # --- Phase 1: capture (passive) ---
    yield from attacker.capture_loop(duration_us=capture_window_us,
                                      interval_us=sniff_interval_us)

    # --- Phase 2: spoof (forged-source transmissions) ---
    for _ in range(spoof_count):
        yield from attacker.spoof(forged_source=spoof_target,
                                   payload_bytes=spoof_payload_bytes)
        yield env.timeout(spoof_interval_us)

    # --- Phase 3: replay every captured packet (up to replay_max, None = all) ---
    to_replay = list(attacker.captured_packets.values())
    if replay_max is not None:
        to_replay = to_replay[:replay_max]
    for pkt in to_replay:
        yield from attacker.replay(pkt)
        yield env.timeout(replay_interval_us)

    report.captured_count = len(attacker.captured_packets)
    report.captured_ids = sorted(attacker.captured_packets.keys())
    report.spoofed_count = len(attacker.spoofed_log)
    report.replayed_count = len(attacker.replayed_log)
    report.airtime_us = attacker.total_airtime_us()


def run_simulation_attacker(
        number_of_stations: int,
        number_of_gnb: int,
        number_of_attackers: int,
        seed: int,
        simulation_time: float,
        wifi_config: WifiConfig,
        configNr: Config_NR,
        attacker_config: Config_PacketAttacker,
        area_w: float = 50.0,
        area_h: float = 50.0,
        wifi_stas_per_ap: int = 1,
        nr_ues_per_gnb: int = 1,
        sta_radius: float = 10.0,
        ue_radius: float = 15.0,
        attacker_positions: Optional[List[Pos]] = None,
        capture_window_s: float = 0.02,
        sniff_interval_us: float = 50.0,
        spoof_count: int = 5,
        spoof_interval_us: float = 200.0,
        spoof_target: str = "AP 1",
        spoof_payload_bytes: int = 1000,
        replay_interval_us: float = 200.0,
        replay_max: Optional[int] = None,
        shadowing_sigma_db: float = 0.0,
):
    # Rashed-Step 24.B-10-19-2026-start
    from common.packet_log import set_compact_packet_log
    set_compact_packet_log(False)  # every run sets it, so one run's choice doesn't leak into the next
    # Rashed-Step 24.B-10-19-2026-end
    random.seed(seed)
    environment = simpy.Environment()

    # Same pre-population requirement as simulation.py/simulation_spectrum.py
    # - see those files' comments for why this dict has to exist before
    # any WiFi AP starts its first backoff draw.
    backoffs = {key: {number_of_stations: 0} for key in range(wifi_config.cw_max + 1)}

    channel = Channel(
        simpy.PriorityResource(environment, capacity=1),
        simpy.Resource(environment, capacity=1),
        number_of_stations,
        number_of_gnb,
        backoffs,
        {},  # airtime_data
        {},  # airtime_control
        {},  # airtime_data_NR
        {},  # airtime_control_NR
        shadowing_sigma_db=shadowing_sigma_db,
    )

    if number_of_stations != 0:
        check_eirp_compliance("WiFi", wifi_config.tx_power_dbm, wifi_config.f_ghz)
    if number_of_gnb != 0:
        check_eirp_compliance("NR-U", configNr.tx_power_dbm, configNr.f_ghz)

    # --- WiFi topology (same pattern as simulation.py/simulation_spectrum.py) ---
    wifi_aps = []
    for i in range(1, number_of_stations + 1):
        ap_name = f"AP {i}"
        ap_pos = rand_pos(area_w, area_h)
        stas_for_ap = []
        for k in range(1, wifi_stas_per_ap + 1):
            sta_pos = rand_pos_near(ap_pos, radius=sta_radius)
            sta = WiFiSTA(name=f"STA {i}-{k}", pos=sta_pos, ap_name=ap_name)
            stas_for_ap.append(sta)
        ap = WiFi(environment, ap_name, channel, ap_pos, stas_for_ap, wifi_config)
        wifi_aps.append(ap)

    # --- NR-U topology ---
    gnbs = []
    for i in range(1, number_of_gnb + 1):
        gnb_name = f"Gnb {i}"
        gnb_pos = rand_pos(area_w, area_h)
        ues_for_gnb = []
        for k in range(1, nr_ues_per_gnb + 1):
            ue_pos = rand_pos_near(gnb_pos, radius=ue_radius)
            ue = NrUE(name=f"UE {i}-{k}", pos=ue_pos, gnb_name=gnb_name)
            ues_for_gnb.append(ue)
        g = Gnb(environment, gnb_name, channel, gnb_pos, ues_for_gnb, configNr)
        gnbs.append(g)

    # --- Attacker nodes (Step 9.C's PacketAttacker) ---
    sim_duration_us = simulation_time * 1_000_000
    capture_window_us = capture_window_s * 1_000_000
    attackers: List[PacketAttacker] = []
    reports: List[AttackerReport] = []
    for i in range(1, number_of_attackers + 1):
        name = f"ATTACKER {i}"
        if attacker_positions is not None and i - 1 < len(attacker_positions):
            pos = attacker_positions[i - 1]
        else:
            pos = rand_pos(area_w, area_h)
        dev = PacketAttacker(environment, name, channel, attacker_config, pos)
        attackers.append(dev)
        report = AttackerReport(name=name, pos=pos)
        reports.append(report)
        environment.process(_attacker_process(
            environment, dev, report, capture_window_us, sniff_interval_us,
            spoof_count, spoof_interval_us, spoof_target, spoof_payload_bytes,
            replay_interval_us, replay_max,
        ))

    print("=== Packet-Attacker Scenario Topology ===")
    print("Wi-Fi:")
    for ap in wifi_aps:
        print(" ", ap.name, ap.pos)
        for sta in ap.sta_list:
            print("   ", sta.name, sta.pos, "d=", dist(ap.pos, sta.pos))
    print("NR-U:")
    for g in gnbs:
        print(" ", g.name, g.pos)
        for ue in g.ue_list:
            print("   ", ue.name, ue.pos, "d=", dist(g.pos, ue.pos))
    print("Attackers:")
    for dev in attackers:
        print(" ", dev.name, dev.current_pos())

    environment.run(until=sim_duration_us)

    print("\n=== Packet-Attacker Results ===")
    for report in reports:
        print(f"{report.name} @ {report.pos}:")
        print(f"  captured: {report.captured_count} packet(s) -> {report.captured_ids}")
        print(f"  spoofed:  {report.spoofed_count} (forged source='{spoof_target}')")
        print(f"  replayed: {report.replayed_count}")
        print(f"  attacker airtime: {report.airtime_us}us "
              f"(occupancy={report.airtime_us / sim_duration_us:.4f})")

    print("\n=== Real WiFi/NR-U Traffic (unaffected code path, printed for comparison) ===")
    succ_wifi = sum(ap.succeeded_transmissions for ap in wifi_aps)
    fail_wifi = sum(ap.failed_transmissions for ap in wifi_aps)
    succ_nru = sum(g.succeeded_transmissions for g in gnbs)
    fail_nru = sum(g.failed_transmissions for g in gnbs)
    print(f"WiFi succ={succ_wifi} fail={fail_wifi}")
    print(f"NRU  succ={succ_nru} fail={fail_nru}")

    return reports
# Rashed-Step 9.C-08-07-2026-end
