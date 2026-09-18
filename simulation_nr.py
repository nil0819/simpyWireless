# Rashed-Step 6.B-07-31-2026-start
# Standalone entry point for licensed 5G NR (nr/nr.py), deliberately
# kept separate from simulation.py's run_simulation() (the existing
# WiFi/NR-U coexistence path) per the confirmed Step 6.B scope:
# "standalone first" - validate the new licensed-NR scheduler in
# isolation, on its own band, before any 3-way Wi-Fi/NR-U/NR
# integration. Mirrors run_simulation()'s topology-building style
# (random or explicit placement, optional mobility) so it's familiar to
# read side by side with simulation.py.

import random
import simpy
from typing import List, Optional

from common.common import Pos, rand_pos, dist
from common.common_phy import WaypointMobility
from channel.channel import Channel
from nr.nr import Config_NRL, GnbLicensedNR, NUMEROLOGY_SCS_KHZ, slot_duration_us
from nr.ue import NrUeLicensed
# Rashed-Step 13.E.3-08-23-2026-start
from common.packet import export_packets_csv
# Rashed-Step 13.E.3-08-23-2026-end
# Rashed-Step 15.G-09-18-2026-start
from ran.protocol.rrc import compute_connection_setup_stats
# Rashed-Step 15.G-09-18-2026-end


def rand_pos_near(center: Pos, radius: float) -> Pos:
    import math
    angle = random.uniform(0, 2 * math.pi)
    r = radius * math.sqrt(random.random())
    return (center[0] + r * math.cos(angle), center[1] + r * math.sin(angle))


def parse_pos_list_nr(raw_values, label: str):
    """Same as singleRun.py's parse_pos_list - parses repeatable 'x,y'
    CLI options into a list of (float, float) tuples, duplicated here
    (rather than imported from singleRun.py) so this standalone licensed-
    NR entry point has zero import dependency on the WiFi/NR-U CLI."""
    import click
    positions = []
    for raw in raw_values:
        parts = raw.split(",")
        if len(parts) != 2:
            raise click.BadParameter(f"{label} must be given as 'x,y' (got: {raw!r})")
        try:
            x, y = float(parts[0]), float(parts[1])
        except ValueError:
            raise click.BadParameter(f"{label} coordinates must be numeric (got: {raw!r})")
        positions.append((x, y))
    return positions


def run_simulation_licensed_nr(
        number_of_gnb: int,
        seed: int,
        simulation_time: float,
        config: Config_NRL,
        area_w: float = 100.0,
        area_h: float = 100.0,
        gnb_positions: Optional[List[Pos]] = None,
        ue_radius: float = 200.0,
        nr_ues_per_gnb: int = 4,
        gnb_mobility_speed_mps: float = 0.0,
        ue_mobility_speed_mps: float = 0.0,
        mobility_pause_s: float = 0.0,
        # Rashed-Step 13.E.3-08-23-2026-start
        export_packets_csv_path: Optional[str] = None,
        # Rashed-Step 13.E.3-08-23-2026-end
        # Rashed-Step 15.G-09-18-2026-start
        # Opt-in licensed-NR uplink (Step 15.E) + generic RRC attach
        # (Step 15.F) for every UE this function constructs - False
        # (default, both) means every NrUeLicensed(...) built below
        # gets neither kwarg set, byte-identical to every pre-15.E run.
        # nr_rrc_enabled=True requires nr_ue_uplink_enabled=True too
        # (NrUeLicensed.__post_init__'s own fail-fast validation), not
        # duplicated here - the ValueError surfaces naturally.
        nr_ue_uplink_enabled: bool = False,
        nr_rrc_enabled: bool = False,
        # Rashed-Step 15.G-09-18-2026-end
):
    random.seed(seed)
    environment = simpy.Environment()

    # Channel() needs tx_queue/tx_lock for backward compatibility with
    # the WiFi/NR-U path's constructor signature, even though licensed
    # NR never touches either (no LBT, see nr/nr.py) - just needs
    # *something* simpy.Environment-bound to seed self.env in
    # __post_init__.
    channel = Channel(
        simpy.PriorityResource(environment, capacity=1),
        simpy.Resource(environment, capacity=1),
        0,  # n_of_stations - no WiFi in this standalone scenario
        number_of_gnb,
        {},  # backoffs - unused (no contention/backoff in licensed NR)
        {},  # airtime_data - unused (WiFi)
        {},  # airtime_control - unused (WiFi)
        {},  # airtime_data_NR - unused (NR-U)
        {},  # airtime_control_NR - unused (NR-U)
    )

    gnbs = []
    for i in range(1, number_of_gnb + 1):
        gnb_name = f"GnbNR {i}"
        if gnb_positions is not None and i - 1 < len(gnb_positions):
            gnb_pos = gnb_positions[i - 1]
        else:
            gnb_pos = rand_pos(area_w, area_h)

        gnb_mobility = None
        if gnb_mobility_speed_mps > 0.0:
            gnb_mobility = WaypointMobility(environment, area_w, area_h,
                                             gnb_mobility_speed_mps, mobility_pause_s, gnb_pos)

        ues_for_gnb = []
        for k in range(1, nr_ues_per_gnb + 1):
            ue_pos = rand_pos_near(gnb_pos, radius=ue_radius)
            ue_mobility = None
            if ue_mobility_speed_mps > 0.0:
                ue_mobility = WaypointMobility(environment, area_w, area_h,
                                                ue_mobility_speed_mps, mobility_pause_s, ue_pos)
            ue = NrUeLicensed(
                name=f"UeNR {i}-{k}",
                pos=ue_pos,
                gnb_name=gnb_name,
                mobility=ue_mobility,
                # Rashed-Step 15.G-09-18-2026-start
                env=environment if nr_ue_uplink_enabled else None,
                config=config if nr_ue_uplink_enabled else None,
                uplink_enabled=nr_ue_uplink_enabled,
                rrc_enabled=nr_rrc_enabled,
                # Rashed-Step 15.G-09-18-2026-end
            )
            ues_for_gnb.append(ue)

        g = GnbLicensedNR(
            environment,
            gnb_name,
            channel,
            gnb_pos,
            ues_for_gnb,
            config,
            mobility=gnb_mobility,
        )
        gnbs.append(g)

    print("=== Licensed 5G NR Topology ===")
    scs_khz = NUMEROLOGY_SCS_KHZ[config.numerology]
    slot_us = slot_duration_us(config.numerology)
    print(f"numerology mu={config.numerology} (SCS={scs_khz} kHz, slot={slot_us} us), "
          f"bandwidth={config.bandwidth_mhz} MHz, f={config.f_ghz/1e9:.2f} GHz, "
          f"scheduler={config.scheduler}, total_rbs(per gNB)={gnbs[0].total_rbs if gnbs else 'n/a'}")
    for g in gnbs:
        print(g.name, g.pos)
        for ue in g.ue_list:
            print("  ", ue.name, ue.pos, "d=", dist(g.pos, ue.pos))

    environment.run(until=simulation_time * 1_000_000)

    print("=== Licensed 5G NR Results ===")
    total_succ = 0
    total_fail = 0
    total_bits = 0.0
    for g in gnbs:
        total_succ += g.succeeded_transmissions
        total_fail += g.failed_transmissions
        total_bits += g.bits_delivered
        n_slots = g.succeeded_transmissions + g.failed_transmissions
        slot_success_rate = (g.succeeded_transmissions / n_slots) if n_slots else 0.0
        thr_mbps = g.bits_delivered / (simulation_time * 1e6) if simulation_time > 0 else 0.0
        print(f"{g.name}: slots_ok={g.succeeded_transmissions} slots_failed={g.failed_transmissions} "
              f"slot_success_rate={slot_success_rate:.4f} throughput={thr_mbps:.3f} Mbps")

    total_slots = total_succ + total_fail
    overall_success_rate = (total_succ / total_slots) if total_slots else 0.0
    overall_thr_mbps = total_bits / (simulation_time * 1e6) if simulation_time > 0 else 0.0
    print(f"TOTAL: slots_ok={total_succ} slots_failed={total_fail} "
          f"slot_success_rate={overall_success_rate:.4f} throughput={overall_thr_mbps:.3f} Mbps")

    # Rashed-Step 15.G-09-18-2026-start
    # RRC connection-setup metrics - only printed when at least one UE
    # actually opted into RRC (nr_rrc_enabled=True), so a default
    # (nr_rrc_enabled=False) run's stdout is byte-identical to every
    # pre-15.G run - see compute_connection_setup_stats()'s own
    # docstring in ran/protocol/rrc.py.
    nr_rrc_stats = compute_connection_setup_stats([ue for g in gnbs for ue in g.ue_list])
    if nr_rrc_stats["attempted"] > 0:
        print("=== Licensed 5G NR RRC Connection Setup ===")
        print(f'NR RRC attempted: {nr_rrc_stats["attempted"]}')
        print(f'NR RRC connected: {nr_rrc_stats["connected"]}')
        print(f'NR RRC success_rate: {nr_rrc_stats["success_rate"]}')
        print(f'NR RRC mean connection setup latency (us): {nr_rrc_stats["mean_latency_us"]}')
    # Rashed-Step 15.G-09-18-2026-end

    # Rashed-Step 13.E.3-08-23-2026-start
    # Opt-in packet-level CSV export, same technology-agnostic
    # export_packets_csv() (Step 9.D) every other scenario uses - keyed
    # under "NR" (licensed 5G NR's own tech label, distinct from "NRU").
    if export_packets_csv_path and gnbs:
        export_packets_csv(
            export_packets_csv_path, seed,
            {"NR": {g.name: g.packet_log for g in gnbs}},
        )
    # Rashed-Step 13.E.3-08-23-2026-end

    return {
        "succeeded_slots": total_succ,
        "failed_slots": total_fail,
        "slot_success_rate": overall_success_rate,
        "throughput_mbps": overall_thr_mbps,
        # Rashed-Step 15.G-09-18-2026-start
        # Always present (not just when attempted>0, unlike the stdout
        # print above) so a caller (e.g. an analysis/ script) doesn't
        # need to special-case a missing key - attempted==0/connected==0
        # /success_rate==None/latencies_us==[]/mean_latency_us==None is
        # itself a meaningful, valid "no UE opted into RRC" result.
        "rrc_stats": nr_rrc_stats,
        # Rashed-Step 15.G-09-18-2026-end
    }
# Rashed-Step 6.B-07-31-2026-end
