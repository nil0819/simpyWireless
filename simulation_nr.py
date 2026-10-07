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
# Rashed-Step 16.F-10-02-2026-start
from core.network import CoreNetwork, CoreConfig
from core.procedures import compute_core_stats, print_core_stats
# Rashed-Step 18.A-10-06-2026-start
from dataclasses import replace as _dc_replace
from common.error_model import ErrorModelConfig, make_error_model, print_error_model_stats
# Rashed-Step 18.B-10-06-2026-start
from ran.protocol.buffer import summarize_buffers, print_buffer_stats
# Rashed-Step 18.E-10-06-2026-start
from ran.protocol.harq import sum_harq_stats, print_harq_stats
# Rashed-Step 18.F-10-06-2026-start
from ran.protocol.l2 import sum_l2_stats, print_l2_stats
# Rashed-Step 19.A-10-07-2026-start
from ran.protocol.rach import compute_rach_stats, print_rach_stats
# Rashed-Step 19.B.2-10-07-2026-start
from ran.protocol.rlm import compute_rlf_stats, print_rlf_stats
# Rashed-Step 19.B.3-10-07-2026-start
from ran.protocol.inactive import compute_inactive_stats, print_inactive_stats
# Rashed-Step 19.C-10-07-2026-start
from common.qos import compute_qos_flow_stats, print_qos_flow_stats
# Rashed-Step 19.D.1-10-07-2026-start
from ran.protocol.handover import compute_handover_stats, print_handover_stats
# Rashed-Step 19.D.1-10-07-2026-end
# Rashed-Step 19.C-10-07-2026-end
# Rashed-Step 19.B.3-10-07-2026-end
# Rashed-Step 19.B.2-10-07-2026-end
# Rashed-Step 19.A-10-07-2026-end
# Rashed-Step 18.F-10-06-2026-end
# Rashed-Step 18.E-10-06-2026-end
# Rashed-Step 18.B-10-06-2026-end
# Rashed-Step 18.A-10-06-2026-end
# Rashed-Step 16.F-10-02-2026-end


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
        # Rashed-Step 16.F-10-02-2026-start
        # Opt-in minimal 5G Core (Step 16): every UE is handed to one
        # CoreNetwork at setup -> registration -> PDU session, and the
        # gNB only carries its data once the session is ACTIVE (16.E).
        # Works with or without RRC. core_config=None means CoreConfig()
        # defaults. False (default) = no Core object at all,
        # byte-identical to every pre-16.F run.
        core_enabled: bool = False,
        core_config: Optional[CoreConfig] = None,
        # Rashed-Step 16.F-10-02-2026-end
        # Rashed-Step 18.A-10-06-2026-start
        # Link error model for every gNB/UE in this run. None (default)
        # = the hard per-MCS threshold rule, byte-identical to earlier runs.
        error_model_config: Optional[ErrorModelConfig] = None,
        # Rashed-Step 18.A-10-06-2026-end
):
    random.seed(seed)
    # Rashed-Step 18.A-10-06-2026-start
    error_model = make_error_model(error_model_config, seed)
    if error_model is not None:
        config = _dc_replace(config, error_model=error_model)
    # Rashed-Step 18.A-10-06-2026-end
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

    # Rashed-Step 19.D.1-10-07-2026-start
    # Every gNB knows the others (handover / re-establishment candidates).
    for g in gnbs:
        g.neighbors = [o for o in gnbs if o is not g]
    # Rashed-Step 19.D.1-10-07-2026-end
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

    # Rashed-Step 16.F-10-02-2026-start
    # Must happen before environment.run() (see core/network.py's
    # start_ue() and ran/protocol/user_plane.py).
    core = None
    if core_enabled:
        core = CoreNetwork(environment, core_config, seed=seed)  # 19.D.2: seed for its reject draws
        for g in gnbs:
            for ue in g.ue_list:
                core.start_ue(g, ue)
    # Rashed-Step 16.F-10-02-2026-end

    environment.run(until=simulation_time * 1_000_000)
    # Rashed-Step 18.B-10-06-2026-start
    for g in gnbs:
        g.flush_buffer_logs()
    # Rashed-Step 18.B-10-06-2026-end

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

    # Rashed-Step pre_18.F-10-06-2026-start
    # Uplink results (Step 15.E's counters were never reported, which is
    # how the same-cell UL interference bug went unnoticed). Only printed
    # when uplink is on, so other runs' stdout is unchanged.
    ul_thr_mbps = None
    if nr_ue_uplink_enabled:
        print("=== Licensed 5G NR Uplink Results ===")
        ul_succ = ul_fail = 0
        ul_bits = 0.0
        for g in gnbs:
            ul_succ += g.succeeded_transmissions_ul
            ul_fail += g.failed_transmissions_ul
            ul_bits += g.bits_delivered_ul
            n = g.succeeded_transmissions_ul + g.failed_transmissions_ul
            rate = (g.succeeded_transmissions_ul / n) if n else 0.0
            thr = g.bits_delivered_ul / (simulation_time * 1e6) if simulation_time > 0 else 0.0
            print(f"{g.name} UL: slots_ok={g.succeeded_transmissions_ul} slots_failed={g.failed_transmissions_ul} "
                  f"slot_success_rate={rate:.4f} throughput={thr:.3f} Mbps")
        n = ul_succ + ul_fail
        ul_thr_mbps = ul_bits / (simulation_time * 1e6) if simulation_time > 0 else 0.0
        print(f"TOTAL UL: slots_ok={ul_succ} slots_failed={ul_fail} "
              f"slot_success_rate={(ul_succ / n) if n else 0.0:.4f} throughput={ul_thr_mbps:.3f} Mbps")
    # Rashed-Step pre_18.F-10-06-2026-end

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
    # Rashed-Step 19.A-10-07-2026-start
    nr_rach_stats = None
    if config.rach is not None:
        print(f'NR RRC failed (random access): {nr_rrc_stats["failed"]}')
        nr_rach_stats = compute_rach_stats([ue for g in gnbs for ue in g.ue_list])
        print_rach_stats("Licensed 5G NR Random Access", "NR", nr_rach_stats)
    # Rashed-Step 19.B.2-10-07-2026-start
    nr_rlf_stats = None
    if config.rlm is not None:
        nr_rlf_stats = compute_rlf_stats([ue for g in gnbs for ue in g.ue_list])
        print_rlf_stats("Licensed 5G NR Radio Link", "NR", nr_rlf_stats)
    # Rashed-Step 19.B.3-10-07-2026-start
    nr_inactive_stats = None
    if config.inactive is not None:
        nr_inactive_stats = compute_inactive_stats([ue for g in gnbs for ue in g.ue_list])
        print_inactive_stats("Licensed 5G NR RRC Inactive", "NR", nr_inactive_stats)
    # Rashed-Step 19.D.1-10-07-2026-start
    nr_ho_stats = None
    if config.handover is not None:
        nr_ho_stats = compute_handover_stats([ue for g in gnbs for ue in g.ue_list])
        print_handover_stats("Licensed 5G NR Handover", "NR", nr_ho_stats)
    # Rashed-Step 19.D.1-10-07-2026-end
    # Rashed-Step 19.B.3-10-07-2026-end
    # Rashed-Step 19.B.2-10-07-2026-end
    # Rashed-Step 19.A-10-07-2026-end
    # Rashed-Step 15.G-09-18-2026-end

    # Rashed-Step 16.F-10-02-2026-start
    # Licensed NR's gNB packet_log holds both DL (destination=UE) and UL
    # (source=UE) packets with correct UE names, so first-packet counts
    # both directions here.
    nr_core_stats = None
    if core is not None:
        nr_core_stats = compute_core_stats(
            [ue for g in gnbs for ue in g.ue_list],
            [p for g in gnbs for p in g.packet_log],
        )
        print_core_stats("Licensed 5G NR 5G Core", "NR", nr_core_stats, "packet")
        # Rashed-Step 19.D.2-10-07-2026-start
        if core.config.failure_modes_on:
            from core.procedures import compute_core_failure_stats, print_core_failure_stats
            print_core_failure_stats("NR", compute_core_failure_stats([ue for g in gnbs for ue in g.ue_list]))
        # Rashed-Step 19.D.2-10-07-2026-end
        # Rashed-Step 19.B.4-10-07-2026-start
        if config.rrc_reconfig_us is not None:
            from ran.protocol.rrc import compute_reconfig_stats
            rc = compute_reconfig_stats([ue for g in gnbs for ue in g.ue_list])
            print(f'NR RRC reconfigurations (DRB setup): {rc["reconfigurations"]}')
            print(f'NR RRC mean reconfiguration latency (us): {rc["mean_latency_us"]}')
        # Rashed-Step 19.B.4-10-07-2026-end
    # Rashed-Step 16.F-10-02-2026-end

    # Rashed-Step 18.B-10-06-2026-start
    # Buffered traffic (Config_NRL.dl_traffic/ul_traffic): only printed
    # when on, so full-buffer runs' stdout is unchanged.
    traffic_stats = {}
    for direction, label, enabled in (("dl", "NR DL", config.dl_traffic is not None),
                                      ("ul", "NR UL", config.ul_traffic is not None)):
        if not enabled:
            continue
        bufs = [b for g in gnbs for b in g.all_buffers()[direction]]
        # Rashed-Step 19.D.1-10-07-2026-start
        # Downlink = sent by a gNB (after a handover, a cell's log also holds
        # downlink packets another gNB created).
        gnb_names = {g.name for g in gnbs}
        pkts = [p for g in gnbs for p in g.packet_log
                if (p.source in gnb_names) == (direction == "dl")]
        # Rashed-Step 19.D.1-10-07-2026-end
        traffic_stats[direction] = summarize_buffers(bufs, pkts, simulation_time)
        print_buffer_stats(f"Licensed 5G NR {direction.upper()} Traffic", label, traffic_stats[direction])
        # Rashed-Step 18.E-10-06-2026-start
        if config.harq is not None:
            hs = sum_harq_stats([e for g in gnbs for e in g.harq_entities(direction == "ul")])
            traffic_stats[direction]["harq"] = hs
            print_harq_stats(f"Licensed 5G NR {direction.upper()} HARQ", label, hs)
        # Rashed-Step 18.F-10-06-2026-start
        if config.l2 is not None:
            ls = sum_l2_stats(bufs)
            traffic_stats[direction]["l2"] = ls
            print_l2_stats(f"Licensed 5G NR {direction.upper()} PDCP/RLC", label, config.l2, ls)
        # Rashed-Step 19.C-10-07-2026-start
        if config.qos_flows:
            qs = compute_qos_flow_stats(pkts, [p for b in bufs for p in b.queued_packets()], environment.now)
            traffic_stats[direction]["qos"] = qs
            print_qos_flow_stats(f"Licensed 5G NR {direction.upper()} QoS Flows", label, qs)
        # Rashed-Step 19.C-10-07-2026-end
        # Rashed-Step 18.F-10-06-2026-end
        # Rashed-Step 18.E-10-06-2026-end
    # Rashed-Step 18.B-10-06-2026-end

    # Rashed-Step 18.A-10-06-2026-start
    print_error_model_stats(error_model)
    # Rashed-Step 18.A-10-06-2026-end

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
        # Rashed-Step pre_18.F-10-06-2026-start
        # None unless nr_ue_uplink_enabled.
        "ul_throughput_mbps": ul_thr_mbps,
        # Rashed-Step pre_18.F-10-06-2026-end
        # Rashed-Step 15.G-09-18-2026-start
        # Always present (not just when attempted>0, unlike the stdout
        # print above) so a caller (e.g. an analysis/ script) doesn't
        # need to special-case a missing key - attempted==0/connected==0
        # /success_rate==None/latencies_us==[]/mean_latency_us==None is
        # itself a meaningful, valid "no UE opted into RRC" result.
        "rrc_stats": nr_rrc_stats,
        # Rashed-Step 19.A-10-07-2026-start
        # None unless config.rach.
        "rach_stats": nr_rach_stats,
        # Rashed-Step 19.B.2-10-07-2026-start
        # None unless config.rlm.
        "rlf_stats": nr_rlf_stats,
        # Rashed-Step 19.B.3-10-07-2026-start
        "inactive_stats": nr_inactive_stats,
        # Rashed-Step 19.D.1-10-07-2026-start
        "handover_stats": nr_ho_stats,
        # Rashed-Step 19.D.1-10-07-2026-end
        # Rashed-Step 19.B.3-10-07-2026-end
        # Rashed-Step 19.B.2-10-07-2026-end
        # Rashed-Step 19.A-10-07-2026-end
        # Rashed-Step 15.G-09-18-2026-end
        # Rashed-Step 16.F-10-02-2026-start
        # None when core_enabled=False.
        "core_stats": nr_core_stats,
        # Rashed-Step 16.F-10-02-2026-end
        # Rashed-Step 18.A-10-06-2026-start
        # None with the default threshold rule.
        "error_model_stats": dict(error_model.stats) if error_model is not None else None,
        # Rashed-Step 18.A-10-06-2026-end
        # Rashed-Step 18.B-10-06-2026-start
        # {"dl": ..., "ul": ...} per buffered direction; {} for full buffer.
        "traffic_stats": traffic_stats,
        # Rashed-Step 18.B-10-06-2026-end
    }
# Rashed-Step 6.B-07-31-2026-end
