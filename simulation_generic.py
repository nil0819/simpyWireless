# Rashed-Step 11.A-08-12-2026-start
"""
Standalone entry point for the "generic transmitter" scenario (Step
11.A) - drops one or more generic.generic_transmitter.GenericTransmitter
nodes (Step 11.A: a THIRD, protocol-agnostic device that actively
senses-then-transmits saturated traffic, unlike the passive
spectrum-analyzer sniffers in simulation_spectrum.py) into a REAL WiFi
+ NR-U coexistence topology (the same wifi.WiFi/nru.Gnb classes
simulation.py uses) sharing the same Channel.

Deliberately kept separate from simulation.py/singleRun.py, same
"standalone first" pattern as simulation_nr.py (6.B), simulation_
spectrum.py (7.B), and simulation_attacker.py (9.C) - no changes to
those already-verified files.

UNLIKE simulation_attacker.py/simulation_spectrum.py (which only ever
place Wi-Fi APs/NR-U gNBs at RANDOM positions), this file supports
EXPLICIT ap_positions/gnb_positions/generic_positions (same "matched
in order, random fallback beyond the given count" convention
simulation.py's --ap-pos/--gnb-pos already use) - needed to guarantee
"these specific nodes share a sensing region" or "these are two
separate zones" scenarios, rather than hoping a random placement
happens to land that way.

WHAT THE PRINTED RESULTS MEAN
Same "this is a completely real ActiveTx, real interference" framing
as simulation_attacker.py: a GenericTransmitter's transmissions are
ordinary entries in channel.active_txs, so they consume real airtime
and appear in every real WiFi AP's/NR-U gNB's own SINR/collision math
exactly like any other transmitter would. transmissions_completed
counts completed AIRTIME (this device's own transmit() call ran
uninterrupted), NOT confirmed delivery - there is no receive/decode
logic in this simulator for a generic device (see generic_transmitter.
py's module docstring).
"""

import random
import simpy
from typing import List, Optional
from dataclasses import dataclass, field

from common.common import Pos, rand_pos, dist
from common.common_phy import check_eirp_compliance
from channel.channel import Channel
from wifi.wifi import WiFi, Config as WifiConfig
from wifi.sta import WiFiSTA
from nru.nru import Gnb, Config_NR
from nru.ue import NrUE
from generic.generic_device import Config_Generic
from generic.generic_transmitter import GenericTransmitter
# Rashed-Step 13.E.2-08-23-2026-start
from common.packet import export_packets_csv
# Rashed-Step 13.E.2-08-23-2026-end


def rand_pos_near(center: Pos, radius: float) -> Pos:
    import math
    angle = random.uniform(0, 2 * math.pi)
    r = radius * math.sqrt(random.random())
    return (center[0] + r * math.cos(angle), center[1] + r * math.sin(angle))


def run_simulation_generic(
        number_of_stations: int,
        number_of_gnb: int,
        number_of_generic: int,
        seed: int,
        simulation_time: float,
        wifi_config: WifiConfig,
        configNr: Config_NR,
        generic_config: Config_Generic,
        area_w: float = 50.0,
        area_h: float = 50.0,
        wifi_stas_per_ap: int = 1,
        nr_ues_per_gnb: int = 1,
        sta_radius: float = 10.0,
        ue_radius: float = 15.0,
        ap_positions: Optional[List[Pos]] = None,
        gnb_positions: Optional[List[Pos]] = None,
        generic_positions: Optional[List[Pos]] = None,
        generic_tx_duration_us: float = 500.0,
        generic_backoff_min_us: float = 0.0,
        generic_backoff_max_us: float = 500.0,
        generic_payload_bytes: int = 500,
        generic_mobility_speed_mps: float = 0.0,
        mobility_pause_s: float = 0.0,
        shadowing_sigma_db: float = 0.0,
        # Rashed-Step 13.E.2-08-23-2026-start
        export_packets_csv_path: Optional[str] = None,
        # Rashed-Step 13.E.2-08-23-2026-end
):
    # Rashed-Step 24.B-10-19-2026-start
    from common.packet_log import set_compact_packet_log
    set_compact_packet_log(False)  # every run sets it, so one run's choice doesn't leak into the next
    # Rashed-Step 24.B-10-19-2026-end
    random.seed(seed)
    environment = simpy.Environment()

    # Same pre-population requirement as simulation.py/simulation_
    # spectrum.py/simulation_attacker.py - see those files' comments.
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

    # --- WiFi topology ---
    wifi_aps = []
    for i in range(1, number_of_stations + 1):
        ap_name = f"AP {i}"
        if ap_positions is not None and i - 1 < len(ap_positions):
            ap_pos = ap_positions[i - 1]
        else:
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
        if gnb_positions is not None and i - 1 < len(gnb_positions):
            gnb_pos = gnb_positions[i - 1]
        else:
            gnb_pos = rand_pos(area_w, area_h)
        ues_for_gnb = []
        for k in range(1, nr_ues_per_gnb + 1):
            ue_pos = rand_pos_near(gnb_pos, radius=ue_radius)
            ue = NrUE(name=f"UE {i}-{k}", pos=ue_pos, gnb_name=gnb_name)
            ues_for_gnb.append(ue)
        g = Gnb(environment, gnb_name, channel, gnb_pos, ues_for_gnb, configNr)
        gnbs.append(g)

    # --- Generic transmitters (Step 11.A) ---
    sim_duration_us = simulation_time * 1_000_000
    generic_devices: List[GenericTransmitter] = []
    for i in range(1, number_of_generic + 1):
        name = f"GENERIC {i}"
        if generic_positions is not None and i - 1 < len(generic_positions):
            pos = generic_positions[i - 1]
        else:
            pos = rand_pos(area_w, area_h)
        dev = GenericTransmitter(
            environment, name, channel, generic_config, pos,
            tx_duration_us=generic_tx_duration_us,
            backoff_min_us=generic_backoff_min_us,
            backoff_max_us=generic_backoff_max_us,
            payload_bytes=generic_payload_bytes,
            mobility_speed_mps=generic_mobility_speed_mps,
            area_w=area_w, area_h=area_h, mobility_pause_s=mobility_pause_s,
        )
        generic_devices.append(dev)

    print("=== Generic-Transmitter Scenario Topology ===")
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
    print("Generic:")
    for dev in generic_devices:
        print(" ", dev.name, dev.current_pos(),
              "(mobile)" if dev.mobility is not None else "(static)")

    environment.run(until=sim_duration_us)

    print("\n=== Generic-Transmitter Results ===")
    for dev in generic_devices:
        occ = dev.channel_occupancy(sim_duration_us)
        print(f"{dev.name} @ {dev.current_pos()}: "
              f"attempted={dev.transmissions_attempted} completed={dev.transmissions_completed} "
              f"airtime_us={dev.total_airtime_us():.0f} occupancy={occ:.4f}")

    print("\n=== Real WiFi/NR-U Traffic (unaffected code path, printed for comparison) ===")
    succ_wifi = sum(ap.succeeded_transmissions for ap in wifi_aps)
    fail_wifi = sum(ap.failed_transmissions for ap in wifi_aps)
    succ_nru = sum(g.succeeded_transmissions for g in gnbs)
    fail_nru = sum(g.failed_transmissions for g in gnbs)
    print(f"WiFi succ={succ_wifi} fail={fail_wifi}")
    print(f"NRU  succ={succ_nru} fail={fail_nru}")

    # Rashed-Step 13.E.2-08-23-2026-start
    # Opt-in packet-level CSV export, same "write header once, append"
    # behavior and same technology-agnostic export_packets_csv() as
    # singleRun.py's --export-packets-csv (Step 9.D) - generic devices'
    # packet_log (Step 9.B) already carries real Packet objects, and
    # measured_sinr_db (Step 13.E.2) is now populated on each one at
    # transmit()-completion time, so this reuses the exact same export
    # path rather than a separate generic-only CSV format. Keyed under
    # generic_config.tech_label (default "GENERIC") - a completely
    # separate technology bucket from "WiFi"/"NRU" in the exported CSV,
    # never mixed with those rows even though it's the same file/format.
    if export_packets_csv_path and generic_devices:
        export_packets_csv(
            export_packets_csv_path, seed,
            {generic_config.tech_label: {dev.name: dev.packet_log for dev in generic_devices}},
        )
    # Rashed-Step 13.E.2-08-23-2026-end

    return generic_devices
# Rashed-Step 11.A-08-12-2026-end
