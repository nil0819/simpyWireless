from common.common import *
from nru.ue import NrUE
from wifi.wifi import *
from nru.nru import *
from channel.channel import *
from attacker.roguewificad import *
# from roguewifiselfbackoff import *
# from roguewifijammer import *
# Rashed-Step 1.D_2-12-26-2025-start
from wifi.sta import *
# Rashed-Step 1.D_2-12-26-2025-end
# Rashed-Step 5.A-02-06-2026-start
from typing import Optional
# Rashed-Step 5.A-02-06-2026-end
# Rashed-Step 5.F-02-06-2026-start
from common.common_phy import check_eirp_compliance
# Rashed-Step 5.F-02-06-2026-end
# Rashed-Step 5.G-02-06-2026-start
from common.common_phy import WaypointMobility
# Rashed-Step 14.D-08-28-2026-start
from common.common_phy import LinearMobility, RelativeMobility
# Rashed-Step 14.D-08-28-2026-end
# Rashed-Step 5.G-02-06-2026-end
# Rashed-Step 8.G-08-06-2026-start
from common.packet import compute_packet_stats
# Rashed-Step 8.G-08-06-2026-end
# Rashed-Step 9.A-08-07-2026-start
from common.packet import compute_packet_stats_by_node
# Rashed-Step 9.A-08-07-2026-end
# Rashed-Step 10.C-08-11-2026-start
from common.packet import compute_packet_stats_by_class
# Rashed-Step 10.C-08-11-2026-end
# Rashed-Step 10.D-08-11-2026-start
from common.packet import compute_qoe_by_class
# Rashed-Step 10.D-08-11-2026-end
# Rashed-Step 12.A-08-13-2026-start
from common.packet import write_packet_report
# Rashed-Step 12.A-08-13-2026-end
# Rashed-Step 9.D-08-07-2026-start
from common.packet import export_packets_csv
# Rashed-Step 9.D-08-07-2026-end
# Rashed-Step 15.G-09-18-2026-start
from ran.protocol.rrc import compute_connection_setup_stats
# Rashed-Step 15.G-09-18-2026-end
# Rashed-Step 16.F-10-02-2026-start
from core.network import CoreNetwork, CoreConfig
from core.procedures import compute_core_stats, print_core_stats
# Rashed-Step 18.A-10-06-2026-start
from dataclasses import replace as _dc_replace
from common.error_model import ErrorModelConfig, make_error_model, print_error_model_stats
# Rashed-Step 18.C-10-06-2026-start
from ran.protocol.buffer import summarize_buffers, print_buffer_stats
# Rashed-Step 18.C-10-06-2026-end
# Rashed-Step 18.A-10-06-2026-end
# Rashed-Step 16.F-10-02-2026-end


# Rashed-Step 1.D_2-12-26-2025-start
def rand_pos_near(center:Pos, radius:float) -> Pos:
    angle = random.uniform(0, 2*math.pi)
    r = radius * math.sqrt(random.random())
    return (center[0] + r*math.cos(angle), center[1] + r*math.sin(angle))
# Rashed-Step 1.D_2-12-26-2025-end



def run_simulation(
        number_of_stations: int,
        number_of_gnb: int,
        seed: int,
        simulation_time: int,
        config: Config,
        configNr: Config_NR,
        backoffs: Dict[int, Dict[int, int]],
        airtime_data: Dict[str, int],
        airtime_control: Dict[str, int],
        airtime_data_NR: Dict[str, int],
        airtime_control_NR: Dict[str, int],
        is_rogue_wifi: bool,
        # Rashed-Step 1.D_1-12-26-2025-start
        area_w: float = 50.0,
        area_h: float = 50.0,
        wifi_stas_per_ap: int = 1,
        nr_ues_per_gnb: int = 1,
        # Rashed-Step 1.D_1-12-26-2025-end
        # Rashed-Step 5.A-02-06-2026-start
        # Explicit device placement. Matched by order to AP 1, AP 2, ... /
        # Gnb 1, Gnb 2, ... ; any AP/gNB beyond len(ap_positions) /
        # len(gnb_positions) still falls back to rand_pos(area_w, area_h).
        ap_positions: Optional[List[Pos]] = None,
        gnb_positions: Optional[List[Pos]] = None,
        sta_radius: float = 10.0,
        ue_radius: float = 15.0,
        # Rashed-Step 5.A-02-06-2026-end
        # Rashed-Step 5.B-02-06-2026-start
        # 0.0 = shadowing disabled (deterministic path loss only, same as
        # before Step 5.B). Typical indoor log-normal shadowing sigma is
        # ~4-8 dB.
        shadowing_sigma_db: float = 0.0,
        # Rashed-Step 5.B-02-06-2026-end
        # Rashed-Step 5.G-02-06-2026-start
        # 0.0 (default, for every one of these) = that node type never
        # moves - common_phy.WaypointMobility is only constructed for a
        # node type when its speed is > 0, so a run with all four at 0.0
        # is byte-identical to every pre-5.G run (no WaypointMobility
        # objects exist at all, current_pos() just returns the static
        # pos it always did). Mobile nodes roam within the same
        # [0,area_w] x [0,area_h] box used for random initial placement.
        ap_mobility_speed_mps: float = 0.0,
        gnb_mobility_speed_mps: float = 0.0,
        sta_mobility_speed_mps: float = 0.0,
        ue_mobility_speed_mps: float = 0.0,
        mobility_pause_s: float = 0.0,
        # Rashed-Step 5.G-02-06-2026-end
        # Rashed-Step 8.B-08-06-2026-start
        # None (default, for both) = TrafficConfig(mode="saturated"),
        # byte-identical to every pre-Step-8.B run - see
        # wifi.WiFi/nru.Gnb's own traffic_config param docs.
        wifi_traffic_config: Optional[TrafficConfig] = None,
        nru_traffic_config: Optional[TrafficConfig] = None,
        # Rashed-Step 8.B-08-06-2026-end
        # Rashed-Step 9.D-08-07-2026-start
        # None (default) = feature off, byte-identical to every pre-
        # Step-9.D run (no file touched at all). Set to a path (via
        # singleRun.py's --export-packets-csv) to append one CSV row
        # per Packet (both technologies, per-node) to that file - see
        # common/packet.py's export_packets_csv()/PACKET_CSV_HEADER.
        export_packets_csv_path: Optional[str] = None,
        # Rashed-Step 9.D-08-07-2026-end
        # Rashed-Step 14.D-08-28-2026-start
        # Deterministic directed gNB mobility - an alternative to the
        # random-waypoint gnb_mobility_speed_mps above, for experiments
        # that need a REPRODUCIBLE, precisely-timed transition (e.g.
        # "start outside a sensing-range crossover distance, arrive at a
        # specific distance at a specific simulated time" - see
        # common.common_phy.LinearMobility's docstring). None (default)
        # = completely unused, byte-identical to every pre-14.D run.
        # Takes precedence over gnb_mobility_speed_mps when both are set
        # (singleRun.py's CLI guards against setting both, but this
        # function itself doesn't refuse it - the precedence is just
        # this straightforward "linear wins if given" rule).
        gnb_mobility_linear_target: Optional[Pos] = None,
        gnb_mobility_linear_duration_s: float = 0.0,
        # UE rigidly follows the gNB's CURRENT position (whatever moves
        # it - linear or waypoint or fully static) plus this fixed
        # offset, instead of getting its own independent mobility/
        # placement. None (default) = unused, byte-identical to every
        # pre-14.D run (UE keeps its existing rand_pos_near(gnb_pos,
        # ue_radius) placement + optional independent ue_mobility_speed_
        # mps roaming). Guarantees the gNB-UE distance never changes
        # regardless of how the gNB moves - see common.common_phy.
        # RelativeMobility's docstring.
        ue_follow_gnb_offset: Optional[Pos] = None,
        # Rashed-Step 14.D-08-28-2026-end
        # Rashed-Step 15.G-09-18-2026-start
        # Opt-in NR-U uplink (Step 15.C) + generic RRC attach (Step
        # 15.F) for every UE this function constructs - False (default,
        # both) means every NrUE(...) built below gets neither kwarg
        # set at all (uplink_enabled/rrc_enabled stay at THEIR OWN
        # False defaults), byte-identical to every pre-15.G run.
        # nru_rrc_enabled=True requires nru_ue_uplink_enabled=True too
        # (NrUE.__post_init__'s own fail-fast validation - see nru/
        # ue.py), so this function doesn't duplicate that check, it
        # just lets the ValueError surface naturally.
        nru_ue_uplink_enabled: bool = False,
        nru_rrc_enabled: bool = False,
        # Rashed-Step 15.G-09-18-2026-end
        # Rashed-Step 16.F-10-02-2026-start
        # Opt-in minimal 5G Core (Step 16) for every NR-U UE (Wi-Fi is
        # untouched): registration -> PDU session after RRC (or from
        # t=0 without RRC), and NR-U data to/from a UE only once its
        # session is ACTIVE (16.E). core_config=None means CoreConfig()
        # defaults. False (default) = no Core object at all,
        # byte-identical to every pre-16.F run.
        nru_core_enabled: bool = False,
        core_config: Optional[CoreConfig] = None,
        # Rashed-Step 16.F-10-02-2026-end
        # Rashed-Step pre_17.B-10-04-2026-start
        # Opt-in Wi-Fi uplink (Step 15.B's WiFiSTA transmit path, never
        # exposed until now) for every STA built below: saturated
        # CSMA/CA uplink to its AP. False (default) = STAs get none of
        # the uplink kwargs, byte-identical to every earlier run. Not
        # supported with is_rogue_wifi (RogueWiFiCAD never wires
        # sta.ap) - singleRun.py rejects that combination.
        wifi_sta_uplink_enabled: bool = False,
        # Rashed-Step pre_17.B-10-04-2026-end
        # Rashed-Step 18.A-10-06-2026-start
        # Link error model shared by every Wi-Fi AP/STA and NR-U gNB/UE
        # in this run (common/error_model.py). None (default) = the hard
        # SINR-threshold rule, byte-identical to every earlier run.
        error_model_config: Optional[ErrorModelConfig] = None,
        # Rashed-Step 18.A-10-06-2026-end
):
    random.seed(seed)
    environment = simpy.Environment()

    # Rashed-Step pre_5.D-02-06-2026-start
    # BUGFIX: is_rogue_wifi used to only be checked *after* the topology
    # loop had already built every AP as benign WiFi (the reassigned
    # `config` was never used to construct anything), so --rogue True never
    # actually spawned an attacker. Decide the WiFi config up front and use
    # it inside the AP-building loop below.
    if is_rogue_wifi:
        wifi_config = ConfigRoguesWiFi()
    else:
        wifi_config = config
    # Rashed-Step pre_5.D-02-06-2026-end
    # Rashed-Step 18.A-10-06-2026-start
    # One model per run, built from this run's seed. Copies of the
    # configs carry it, so the caller's objects (reused across -r runs)
    # are never mutated. The rogue AP's ConfigRoguesWiFi has no
    # error_model field and keeps the threshold rule.
    error_model = make_error_model(error_model_config, seed)
    if error_model is not None:
        if hasattr(wifi_config, "error_model"):
            wifi_config = _dc_replace(wifi_config, error_model=error_model)
        configNr = _dc_replace(configNr, error_model=error_model)
    # Rashed-Step 18.A-10-06-2026-end
    # Rashed-Step 3.F-01-13-2026-start
    # channel = Channel(
    #     simpy.PreemptiveResource(environment, capacity=1),
    #     simpy.Resource(environment, capacity=1),
    #     number_of_stations,
    #     number_of_gnb,
    #     backoffs,
    #     airtime_data,
    #     airtime_control,
    #     airtime_data_NR,
    #     airtime_control_NR
    # )
    channel = Channel(
        simpy.PriorityResource(environment, capacity=1),  # <-- change this
        simpy.Resource(environment, capacity=1),
        number_of_stations,
        number_of_gnb,
        backoffs,
        airtime_data,
        airtime_control,
        airtime_data_NR,
        airtime_control_NR,
        # Rashed-Step 5.B-02-06-2026-start
        shadowing_sigma_db=shadowing_sigma_db
        # Rashed-Step 5.B-02-06-2026-end
    )

    # Rashed-Step 3.F-01-13-2026-end

    

    # Rashed-Step 1.D_2-12-26-2025-start
    # Rashed-Step pre_5.A-02-06-2026-start
    # BUGFIX: ap = WiFi(...) / wifi_aps.append(ap) used to sit outside this
    # for-loop (same indent as the loop itself), so only the AP built on the
    # loop's LAST iteration was ever instantiated regardless of
    # number_of_stations. Moved inside the loop so every AP (and its STA
    # list) actually gets created.
    # Rashed-Step pre_5.A-02-06-2026-end
    wifi_aps = []
    wifi_stas = []

    for i in range(1, number_of_stations + 1):
        ap_name = f"AP {i}"
        # Rashed-Step 5.A-02-06-2026-start
        if ap_positions is not None and i - 1 < len(ap_positions):
            ap_pos = ap_positions[i - 1]
        else:
            ap_pos = rand_pos(area_w, area_h)
        # Rashed-Step 5.A-02-06-2026-end

        # Rashed-Step 5.G-02-06-2026-start
        ap_mobility = None
        if ap_mobility_speed_mps > 0.0:
            ap_mobility = WaypointMobility(environment, area_w, area_h,
                                            ap_mobility_speed_mps, mobility_pause_s, ap_pos)
        # Rashed-Step 5.G-02-06-2026-end

        stas_for_ap = []
        for k in range(1, wifi_stas_per_ap + 1):
            sta_pos = rand_pos_near(ap_pos, radius=sta_radius)
            # Rashed-Step 5.G-02-06-2026-start
            sta_mobility = None
            if sta_mobility_speed_mps > 0.0:
                sta_mobility = WaypointMobility(environment, area_w, area_h,
                                                 sta_mobility_speed_mps, mobility_pause_s, sta_pos)
            # Rashed-Step 5.G-02-06-2026-end
            sta = WiFiSTA(
                name=f"STA {i}-{k}",
                # Rashed-Step 5.A-02-06-2026-start
                pos=sta_pos,
                # Rashed-Step 5.A-02-06-2026-end
                ap_name=ap_name,
                # Rashed-Step 5.G-02-06-2026-start
                mobility=sta_mobility,
                # Rashed-Step 5.G-02-06-2026-end
                # Rashed-Step pre_17.B-10-04-2026-start
                env=environment if wifi_sta_uplink_enabled else None,
                channel=channel if wifi_sta_uplink_enabled else None,
                config=wifi_config if wifi_sta_uplink_enabled else None,
                uplink_enabled=wifi_sta_uplink_enabled,
                # Rashed-Step pre_17.B-10-04-2026-end
            )
            stas_for_ap.append(sta)
            wifi_stas.append(sta)

        # Rashed-Step pre_5.A-02-06-2026-start
        # Rashed-Step pre_5.D-02-06-2026-start
        if is_rogue_wifi:
            # Rashed-Step 5.G-02-06-2026-start
            # NOT given mobility - attack-path changes are out of scope
            # per current instructions (roguewificad.py is left alone
            # elsewhere in Step 5 for the same reason).
            # Rashed-Step 5.G-02-06-2026-end
            ap = RogueWiFiCAD(
                environment,
                ap_name,
                channel,
                ap_pos,
                wifi_config
            )
        else:
            ap = WiFi(
                environment,
                ap_name,
                channel,
                ap_pos,
                stas_for_ap,
                wifi_config,
                # Rashed-Step 5.G-02-06-2026-start
                mobility=ap_mobility,
                # Rashed-Step 5.G-02-06-2026-end
                # Rashed-Step 8.B-08-06-2026-start
                traffic_config=wifi_traffic_config
                # Rashed-Step 8.B-08-06-2026-end
            )
        # Rashed-Step pre_5.D-02-06-2026-end
        wifi_aps.append(ap)
        # Rashed-Step pre_5.A-02-06-2026-end
    # Rashed-Step 1.D_2-12-26-2025-end

    # Rashed-Step 1.D_3-12-26-2025-start
    # Rashed-Step pre_5.A-02-06-2026-start
    # BUGFIX: same issue as above for gNBs - g = Gnb(...) / gnbs.append(g)
    # moved inside the loop.
    # Rashed-Step pre_5.A-02-06-2026-end
    gnbs = []
    ues = []
    for i in range(1, number_of_gnb + 1):
        gnb_name = f"Gnb {i}"
        # Rashed-Step 5.A-02-06-2026-start
        if gnb_positions is not None and i - 1 < len(gnb_positions):
            gnb_pos = gnb_positions[i - 1]
        else:
            gnb_pos = rand_pos(area_w, area_h)
        # Rashed-Step 5.A-02-06-2026-end

        # Rashed-Step 5.G-02-06-2026-start
        gnb_mobility = None
        if gnb_mobility_speed_mps > 0.0:
            gnb_mobility = WaypointMobility(environment, area_w, area_h,
                                             gnb_mobility_speed_mps, mobility_pause_s, gnb_pos)
        # Rashed-Step 5.G-02-06-2026-end
        # Rashed-Step 14.D-08-28-2026-start
        # Directed linear mobility takes precedence over the random-
        # waypoint speed above when given (see this param's docstring).
        if gnb_mobility_linear_target is not None:
            gnb_mobility = LinearMobility(environment, gnb_pos, gnb_mobility_linear_target,
                                           gnb_mobility_linear_duration_s)
        # Rashed-Step 14.D-08-28-2026-end

        ues_for_gnb = []
        for k in range(1, nr_ues_per_gnb + 1):
            ue_pos = rand_pos_near(gnb_pos, radius=ue_radius)
            # Rashed-Step 5.G-02-06-2026-start
            ue_mobility = None
            if ue_mobility_speed_mps > 0.0:
                ue_mobility = WaypointMobility(environment, area_w, area_h,
                                                ue_mobility_speed_mps, mobility_pause_s, ue_pos)
            # Rashed-Step 5.G-02-06-2026-end
            # Rashed-Step 14.D-08-28-2026-start
            # UE rigidly follows the gNB's CURRENT position (whichever
            # mobility - or lack of one - it has) instead of getting its
            # own independent placement/mobility - takes precedence over
            # ue_mobility_speed_mps above when given, same "linear/
            # coupled wins" precedence as the gNB's own override.
            # gnb_mobility is None here only when the gNB is fully static
            # (no linear target AND speed<=0) - RelativeMobility handles
            # a plain static Pos base directly (see its docstring), so
            # this works whether the gNB moves or not.
            if ue_follow_gnb_offset is not None:
                ue_pos = (gnb_pos[0] + ue_follow_gnb_offset[0], gnb_pos[1] + ue_follow_gnb_offset[1])
                ue_mobility = RelativeMobility(gnb_mobility if gnb_mobility is not None else gnb_pos,
                                                ue_follow_gnb_offset)
            # Rashed-Step 14.D-08-28-2026-end
            ue = NrUE(
                name=f"UE {i}-{k}",
                # Rashed-Step 5.A-02-06-2026-start
                pos=ue_pos,
                # Rashed-Step 5.A-02-06-2026-end
                gnb_name=gnb_name,
                # Rashed-Step 5.G-02-06-2026-start
                mobility=ue_mobility,
                # Rashed-Step 5.G-02-06-2026-end
                # Rashed-Step 15.G-09-18-2026-start
                env=environment if nru_ue_uplink_enabled else None,
                channel=channel if nru_ue_uplink_enabled else None,
                config_nr=configNr if nru_ue_uplink_enabled else None,
                uplink_enabled=nru_ue_uplink_enabled,
                rrc_enabled=nru_rrc_enabled,
                # Rashed-Step 15.G-09-18-2026-end
            )
            ues_for_gnb.append(ue)
            ues.append(ue)

        # Rashed-Step pre_5.A-02-06-2026-start
        g = Gnb(
            environment,
            gnb_name,
            channel,
            gnb_pos,
            ues_for_gnb,
            configNr,
            # Rashed-Step 5.G-02-06-2026-start
            mobility=gnb_mobility,
            # Rashed-Step 5.G-02-06-2026-end
            # Rashed-Step 8.B-08-06-2026-start
            traffic_config=nru_traffic_config
            # Rashed-Step 8.B-08-06-2026-end
        )
        gnbs.append(g)
        # Rashed-Step pre_5.A-02-06-2026-end
    # Rashed-Step 1.D_3-12-26-2025-end

    # Rashed-Step 1.E-12-26-2025-start
    print("=== Wi-Fi Topology ===")
    for ap in wifi_aps:
        print(ap.name, ap.pos)
        # Rashed-Step pre_5.D-02-06-2026-start
        # BUGFIX: RogueWiFiCAD has no sta_list (an attacker has no
        # legitimate associated STA), so this crashed with AttributeError
        # whenever --rogue True was used. Guard with getattr.
        for sta in getattr(ap, "sta_list", []):
            print("  ", sta.name, sta.pos, "d=", dist(ap.pos, sta.pos))
        # Rashed-Step pre_5.D-02-06-2026-end

    print("=== NR-U Topology ===")
    for gnb in gnbs:
        print(gnb.name, gnb.pos)
        for ue in gnb.ue_list:
            print("  ", ue.name, ue.pos, "d=", dist(gnb.pos, ue.pos))
    # Rashed-Step 1.E-12-26-2025-end

    # Rashed-Step pre_5.D-02-06-2026-start
    # BUGFIX: this used to reassign `config` to a fresh ConfigRoguesWiFi()/
    # Config() *after* the AP loop had already built every AP with the
    # original `config` argument, so it never affected which class/config
    # got instantiated. AP construction above now uses wifi_config (decided
    # before the loop); reuse it here for the reporting/log lines instead of
    # building a second, disconnected config object.
    # Rashed-Step 12.A-08-13-2026-start
    # BUGFIX: commented out - both were leftover development-time debug
    # prints (a raw bool, then a redundant "Rogue WiFi"/"Benign WiFi"
    # label), never gated behind a verbosity flag, so every normal run's
    # stdout got a stray "False"/"Benign WiFi" pair with no label
    # explaining what they meant. --rogue is still fully in effect either
    # way (this only silenced the announcement of it) - use --rogue True/
    # False and check the actual topology print above (RogueWiFiCAD vs
    # WiFi instances) if you need to confirm which one is active.
    # print(is_rogue_wifi)
    # print("Rogue WiFi" if is_rogue_wifi else "Benign WiFi")
    # Rashed-Step 12.A-08-13-2026-end
    config = wifi_config
    # Rashed-Step pre_5.D-02-06-2026-end

    # Rashed-Step 5.F-02-06-2026-start
    # Informational-only regulatory EIRP check (does not clamp/raise) -
    # see common_phy.check_eirp_compliance() for the U-NII band table and
    # the simplifications involved (tx_power_dbm treated as EIRP directly,
    # no separate antenna-gain field). Checked once per run against each
    # tech's configured frequency, not per-AP/gNB, since every WiFi AP
    # shares wifi_config and every gNB shares configNr in this CLI.
    if number_of_stations != 0:
        check_eirp_compliance("WiFi", wifi_config.tx_power_dbm, wifi_config.f_ghz)
    if number_of_gnb != 0:
        check_eirp_compliance("NR-U", configNr.tx_power_dbm, configNr.f_ghz)
    # Rashed-Step 5.F-02-06-2026-end

    # Rashed-Step 6.E-08-05-2026-start
    # BUGFIX: this used to be `config_nr = Config_NR()` - a fresh, always-
    # default Config_NR object, disconnected from `configNr` (the real
    # config actually used to build the Gnb objects below, populated from
    # CLI flags like --nru_cw_min/--nru_cw_max). It was only ever read for
    # the "CW_MIN=/CW_MAX=" diagnostic print further down, so that print
    # always showed 15/63 regardless of the real --nru_cw_min/--nru_cw_max
    # values passed in - misleading, though the real simulation logic
    # (which uses configNr throughout) was never affected. Found during
    # Step 6.D/6.E regression testing. Point the print at the real object.
    config_nr = configNr
    # Rashed-Step 6.E-08-05-2026-end

    # Rashed-Step 1.E-12-26-2025-start
    # for i in range(1, number_of_stations + 1):
    #     if is_rogue_wifi:
    #         print("Rogue WiFi")
    #         #RogueWiFiCAD(environment, "Station {}".format(i), channel, config)
    #         #RogueWiFiSelfBackoff(environment, "Station {}".format(i), channel, config)
    #         #RogueWiFiJammer(environment, "Station {}".format(i), channel, config)
    #     else:
    #         print("Benign WiFi")
    #         WiFi(environment, "Station {}".format(i), channel, config)
    # Rashed-Step 1.E-12-26-2025-end

        
    # Rashed-Step 1.E-12-26-2025-start
    # for i in range(1, number_of_gnb + 1):
    #     # Gnb(environment, "Gnb {}".format(i), channel, config_nr)
    #     Gnb(environment, "Gnb {}".format(i), channel, configNr)
    # Rashed-Step 1.E-12-26-2025-end

    # Rashed-Step 3.F-12-26-2025-start
    # print("APs: ", [ap.name for ap in wifi_aps])
    # print("GNBs: ", [g.name for g in gnbs])
    # Rashed-Step 3.F-12-26-2025-end

    # Rashed-Step 16.F-10-02-2026-start
    # Must happen before environment.run(): NR-U's uplink checks the
    # user-plane gate once, before its first packet (16.E).
    nru_core = None
    if nru_core_enabled:
        nru_core = CoreNetwork(environment, core_config)
        for g in gnbs:
            for ue in g.ue_list:
                nru_core.start_ue(g, ue)
    # Rashed-Step 16.F-10-02-2026-end

    # environment.run(until=simulation_time * 1000000) 10^6 milisekundy
    environment.run(until=simulation_time * 1000000)
    # Rashed-Step 18.C-10-06-2026-start
    for g in gnbs:
        if hasattr(g, "flush_buffer_logs"):
            g.flush_buffer_logs()
    # Rashed-Step 18.C-10-06-2026-end

    # Rashed-Step 6.E-08-05-2026-start
    # BUGFIX: this "WiFi airtime data:.../NRU airtime ctrl:" debug print
    # block used to sit BEFORE environment.run() (i.e. before the
    # simulation actually executed), so it always printed all-zero
    # airtime/succ/fail regardless of what really happened - misleading
    # debug output (channel.airtime_data etc. are only ever populated as
    # a side effect of the simulation running). Moved here, right after
    # environment.run(), so it reflects real post-simulation state.
    # Found during Step 6.D/6.E regression testing.
    print("WiFi airtime data:", sum(channel.airtime_data.values()))
    print("WiFi airtime ctrl:", sum(channel.airtime_control.values()))
    print("NRU airtime data:", sum(channel.airtime_data_NR.values()))
    print("NRU airtime ctrl:", sum(channel.airtime_control_NR.values()))
    print("succ WiFi:", channel.succeeded_transmissions, "fail WiFi:", channel.failed_transmissions)
    print("succ NRU:", channel.succeeded_transmissions_NR, "fail NRU:", channel.failed_transmissions_NR)
    # Rashed-Step 6.E-08-05-2026-end

    # Rashed-Step 8.G-08-06-2026-start
    # Per-packet latency/loss report, built from each AP's/gNB's
    # packet_log (populated by sent_completed()/sent_failed() - see
    # wifi.WiFi/nru.Gnb and common.packet.compute_packet_stats()). This
    # is a genuinely different signal from PCOLL/succ/fail above: those
    # count TRANSMISSION ATTEMPTS (every retry counts separately);
    # this counts PACKETS (one entry per packet's final DELIVERED/
    # DROPPED outcome, however many attempts it took to get there), and
    # adds latency (created_at -> delivered_at), which nothing else in
    # this print block reports at all.
    # getattr(..., []) instead of ap.packet_log directly: when --rogue
    # True, wifi_aps holds RogueWiFiCAD instances instead of WiFi ones
    # (attacker/roguewificad.py - out of scope for Step 8's packet work
    # per standing project convention, never given a packet_log). This
    # just skips those rather than erroring, without touching that file.
    wifi_packets = [p for ap in wifi_aps for p in getattr(ap, "packet_log", [])]
    nru_packets = [p for g in gnbs for p in g.packet_log]
    wifi_pkt_stats = compute_packet_stats(wifi_packets)
    nru_pkt_stats = compute_packet_stats(nru_packets)

    # Rashed-Step 14.A-08-28-2026-start
    # Per-technology GOODPUT throughput (Mbps) and avg delay (us), printed
    # to stdout so model/runner.py's existing stdout-scraping run_scenario()
    # can pick them up - same convention as the "Wifi/Gnb occupancy
    # (Normalized)"/"fairness" lines below, added for the new analysis/
    # module's WiFi-vs-NR-U performance-comparison figure (channel
    # occupancy was already available; throughput/delay were not - delay
    # was computed as wifi_pkt_stats/nru_pkt_stats["avg_latency_us"] but
    # never printed, and throughput wasn't computed anywhere at all).
    # GOODPUT, not raw attempted-bytes rate: only DELIVERED packets count,
    # matching what "channel_efficiency" (data-only airtime, excluding
    # control frames and failed attempts) already represents for
    # occupancy - so this is throughput's natural counterpart, not a new,
    # inconsistent definition. Purely additive - two new printed lines,
    # nothing existing changes, so this is byte-identical for every
    # caller that doesn't look for these two new lines.
    wifi_delivered_bytes = sum(p.total_bytes() for p in wifi_packets if p.status == "DELIVERED")
    nru_delivered_bytes = sum(p.total_bytes() for p in nru_packets if p.status == "DELIVERED")
    wifi_throughput_mbps = (wifi_delivered_bytes * 8) / (simulation_time * 1e6)
    nru_throughput_mbps = (nru_delivered_bytes * 8) / (simulation_time * 1e6)
    print(f'Wifi packet throughput (Mbps): {wifi_throughput_mbps}')
    print(f'Wifi packet avg latency (us): {wifi_pkt_stats["avg_latency_us"]}')
    print(f'NRU packet throughput (Mbps): {nru_throughput_mbps}')
    print(f'NRU packet avg latency (us): {nru_pkt_stats["avg_latency_us"]}')
    # Rashed-Step 14.A-08-28-2026-end

    # Rashed-Step 15.G-09-18-2026-start
    # RRC connection-setup metrics - only printed when at least one UE
    # actually opted into RRC (nru_rrc_enabled=True), so a default
    # (nru_rrc_enabled=False) run's stdout is byte-identical to every
    # pre-15.G run - see compute_connection_setup_stats()'s own
    # docstring in ran/protocol/rrc.py for exactly what these numbers
    # mean (and the documented "no failure mode yet" limitation on
    # success_rate).
    nru_rrc_stats = compute_connection_setup_stats(ues)
    if nru_rrc_stats["attempted"] > 0:
        print("=== NR-U RRC Connection Setup ===")
        print(f'NRU RRC attempted: {nru_rrc_stats["attempted"]}')
        print(f'NRU RRC connected: {nru_rrc_stats["connected"]}')
        print(f'NRU RRC success_rate: {nru_rrc_stats["success_rate"]}')
        print(f'NRU RRC mean connection setup latency (us): {nru_rrc_stats["mean_latency_us"]}')
    # Rashed-Step 15.G-09-18-2026-end

    # Rashed-Step 16.F-10-02-2026-start
    # Rashed-Step pre_17.A-10-04-2026-start
    # First-packet now counts both directions: each gNB's downlink
    # packet_log plus each UE's own uplink packet_log. 16.F had to use
    # uplink only, because nru.Gnb stamped every downlink packet
    # destination=ue_list[0], including ones sent before the UE's
    # session existed (rx_ue=None) - fixed in Step pre_17.A, where those
    # now carry the gNB's own name and credit no UE.
    if nru_core is not None:
        nru_core_stats = compute_core_stats(
            ues,
            [p for g in gnbs for p in g.packet_log]
            + [p for ue in ues for p in getattr(ue, "packet_log", [])],
        )
        print_core_stats("NR-U 5G Core", "NRU", nru_core_stats, "packet")
    # Rashed-Step pre_17.A-10-04-2026-end
    # Rashed-Step 16.F-10-02-2026-end

    # Rashed-Step pre_17.B-10-04-2026-start
    # Wi-Fi uplink results - only when the flag is on, so default runs'
    # stdout is unchanged. The "Wifi packet throughput" line above is
    # AP (downlink) packets only, as before; uplink goodput is here.
    wifi_ul_packets = []
    if wifi_sta_uplink_enabled:
        wifi_ul_packets = [p for sta in wifi_stas for p in getattr(sta, "packet_log", [])]
        wifi_ul_stats = compute_packet_stats(wifi_ul_packets)
        wifi_ul_delivered_bytes = sum(p.total_bytes() for p in wifi_ul_packets if p.status == "DELIVERED")
        print("=== Wi-Fi Uplink ===")
        print(f"Wifi uplink STAs: {len(wifi_stas)}")
        print(f'Wifi uplink packets delivered: {wifi_ul_stats["delivered"]}')
        print(f'Wifi uplink packets dropped: {wifi_ul_stats["dropped"]}')
        print(f"Wifi uplink packet throughput (Mbps): {(wifi_ul_delivered_bytes * 8) / (simulation_time * 1e6)}")
        print(f'Wifi uplink packet avg latency (us): {wifi_ul_stats["avg_latency_us"]}')
    # Rashed-Step pre_17.B-10-04-2026-end

    # Rashed-Step 17.G-10-04-2026-start
    # NR-U uplink results - only when NR-U uplink is on, so default runs'
    # stdout is unchanged. "NRU packet throughput" above stays gNB
    # (downlink) packets only, as before.
    if nru_ue_uplink_enabled:
        nru_ul_packets = [p for ue in ues for p in getattr(ue, "packet_log", [])]
        nru_ul_stats = compute_packet_stats(nru_ul_packets)
        nru_ul_bytes = sum(p.total_bytes() for p in nru_ul_packets if p.status == "DELIVERED")
        print("=== NR-U Uplink ===")
        print(f"NRU uplink access mode: {configNr.ul_access_mode.value}")
        print(f"NRU uplink UEs: {len(ues)}")
        print(f'NRU uplink packets delivered: {nru_ul_stats["delivered"]}')
        print(f'NRU uplink packets dropped: {nru_ul_stats["dropped"]}')
        print(f"NRU uplink attempts ok/failed: {sum(ue.succeeded_transmissions for ue in ues)}/"
              f"{sum(ue.failed_transmissions for ue in ues)}")
        print(f"NRU uplink packet throughput (Mbps): {(nru_ul_bytes * 8) / (simulation_time * 1e6)}")
        print(f'NRU uplink packet avg latency (us): {nru_ul_stats["avg_latency_us"]}')
        if configNr.ul_access_mode is NruUplinkAccessMode.COT_SHARING:
            print(f"NRU COT uplink fraction: {configNr.ul_cot_fraction}")
            print(f"NRU uplink windows opened: {sum(len(g.ul_windows) for g in gnbs)}")
            print(f"NRU uplink grants skipped (Type 2A busy): {sum(ue.type2a_skips for ue in ues)}")
    # Rashed-Step 17.G-10-04-2026-end

    # Rashed-Step 18.C-10-06-2026-start
    # NR-U "slots" COT model results - only then, so burst runs' stdout
    # is unchanged.
    if configNr.cot_model == "slots" and gnbs:
        ss = {k: sum(g.slot_stats[k] for g in gnbs) for k in gnbs[0].slot_stats}
        n_slots = ss["slots_ok"] + ss["slots_failed"]
        print("=== NR-U Slots ===")
        print(f"NRU numerology mu={configNr.numerology} (SCS={gnbs[0].scs_khz} kHz, slot={gnbs[0].slot_us} us), "
              f"RBs={gnbs[0].total_rbs} in {configNr.bandwidth_mhz} MHz")
        print(f'NRU COTs: {ss["cots"]} (reference slot failed: {ss["cots_failed"]}, '
              f'control only: {ss["control_only_cots"]})')
        print(f'NRU DL slots ok/failed: {ss["slots_ok"]}/{ss["slots_failed"]}')
        print(f'NRU DL slot error rate: {(ss["slots_failed"] / n_slots) if n_slots else 0.0}')
        print(f'NRU DL mean MCS (decoded slots): {(ss["mcs_sum"] / ss["slots_ok"]) if ss["slots_ok"] else None}')
        print(f'NRU DL slot throughput (Mbps): {ss["bits_delivered"] / (simulation_time * 1e6)}')
        if nru_traffic_config is not None and nru_traffic_config.mode != "saturated":
            nru_bufs = [b for g in gnbs for b in g.dl_buffers.values()]
            nru_dl_pkts = [p for g in gnbs for p in g.packet_log]
            print_buffer_stats("NR-U DL Traffic", "NRU DL",
                               summarize_buffers(nru_bufs, nru_dl_pkts, simulation_time))
    # Rashed-Step 18.C-10-06-2026-end

    # Rashed-Step 18.A-10-06-2026-start
    print_error_model_stats(error_model)
    # Rashed-Step 18.A-10-06-2026-end

    # Rashed-Step 12.A-08-13-2026-start
    # No longer printed directly to stdout (see below, after every
    # section is computed) - collected into packet_report_sections
    # instead and written to a log file via write_packet_report().
    packet_report_sections = {
        "packet stats WiFi": wifi_pkt_stats,
        "packet stats NRU": nru_pkt_stats,
    }
    # Rashed-Step 12.A-08-13-2026-end
    # Rashed-Step 8.G-08-06-2026-end

    # Rashed-Step 9.A-08-07-2026-start
    # Per-node breakdown of the same stats - an aggregate-only number
    # can hide one struggling AP/gNB (e.g. one station near the edge of
    # range with much higher loss) behind a healthy-looking average
    # across the rest. Same getattr(...) fallback as the aggregated
    # version above, for the same --rogue True reason.
    wifi_node_logs = {ap.name: getattr(ap, "packet_log", []) for ap in wifi_aps}
    nru_node_logs = {g.name: g.packet_log for g in gnbs}
    # Rashed-Step 12.A-08-13-2026-start
    packet_report_sections["packet stats WiFi by node"] = compute_packet_stats_by_node(wifi_node_logs)
    packet_report_sections["packet stats NRU by node"] = compute_packet_stats_by_node(nru_node_logs)
    # Rashed-Step 12.A-08-13-2026-end
    # Rashed-Step 9.A-08-07-2026-end

    # Rashed-Step 10.C-08-11-2026-start
    # Per-traffic-class breakdown of the same aggregated stats (Step
    # 10.A gave every Packet a traffic_class; this is the first thing
    # in simulation.py that actually reports on it). Uses the SAME
    # aggregated wifi_packets/nru_packets lists already built above for
    # the plain compute_packet_stats() call - no new packet collection
    # needed. Reports per class regardless of whether --wifi-traffic-
    # class-mix/--wifi-edca were set - if every packet is still
    # "best_effort" (the default), this just prints one class with the
    # same numbers as the aggregate line above, which is the correct,
    # regression-safe "no-op-looking" behavior for a run with no new
    # flags (a real key gets ADDED to the printed output, but nothing
    # about the existing lines/values changes).
    wifi_stats_by_class = compute_packet_stats_by_class(wifi_packets)
    nru_stats_by_class = compute_packet_stats_by_class(nru_packets)
    # Rashed-Step 12.A-08-13-2026-start
    packet_report_sections["packet stats WiFi by class"] = wifi_stats_by_class
    packet_report_sections["packet stats NRU by class"] = nru_stats_by_class
    # Rashed-Step 12.A-08-13-2026-end
    # Rashed-Step 10.C-08-11-2026-end

    # Rashed-Step 10.D-08-11-2026-start
    # QoE scoring layer, built directly on top of the per-class stats
    # just computed above (compute_qoe_by_class() takes that dict as
    # its input, not raw packets - see its docstring). voice gets a
    # real MOS via a simplified ITU-T G.107 E-model; video gets a
    # clearly-labeled simulator-local heuristic proxy score (NOT
    # comparable to voice's MOS scale); best_effort/background get
    # qoe_score=None (QoE isn't a meaningful concept for non-
    # interactive data traffic). Same regression-safe shape as 10.C:
    # unconditional, additive-only - a default run just adds one
    # "best_effort" class with qoe_score=None, no existing line changes.
    # Rashed-Step 12.A-08-13-2026-start
    packet_report_sections["packet QoE WiFi by class"] = compute_qoe_by_class(wifi_stats_by_class)
    packet_report_sections["packet QoE NRU by class"] = compute_qoe_by_class(nru_stats_by_class)
    # Rashed-Step 10.D-08-11-2026-end

    # All 8 packet-stats/QoE sections are now collected (not printed to
    # stdout - see the individual Rashed-Step 12.A blocks above). Write
    # them to a separate packet.log file instead, per Rashed's request
    # ("Keep this as a separate log file naming packet.log ... Not in
    # the output"). One call, appends one full report block per run
    # (see write_packet_report()'s own docstring in common/packet.py
    # for why plain text was chosen over .pcap).
    write_packet_report("packet.log", seed, packet_report_sections)
    # Rashed-Step 12.A-08-13-2026-end

    # Rashed-Step 9.D-08-07-2026-start
    # Opt-in packet-level CSV export - only touches the filesystem when
    # export_packets_csv_path was actually given (default None), so a
    # run with no new flags set is completely unaffected by this block
    # (not even an unconditional no-op file check, unlike lool.csv's
    # own end-of-run block below, which always writes regardless of any
    # flag).
    if export_packets_csv_path is not None:
        # Rashed-Step pre_17.B-10-04-2026-start
        # With Wi-Fi uplink on, each STA's uplink packets are exported
        # too, as their own WiFi nodes (node = STA name). Without it
        # this dict is exactly wifi_node_logs, as before.
        csv_wifi_logs = dict(wifi_node_logs)
        if wifi_sta_uplink_enabled:
            csv_wifi_logs.update({sta.name: getattr(sta, "packet_log", []) for sta in wifi_stas})
        rows_written = export_packets_csv(
            export_packets_csv_path, seed,
            {"WiFi": csv_wifi_logs, "NRU": nru_node_logs},
        )
        # Rashed-Step pre_17.B-10-04-2026-end
        print(f"packet-level CSV export: wrote {rows_written} row(s) to {export_packets_csv_path}")
    # Rashed-Step 9.D-08-07-2026-end

    if number_of_stations != 0:
        if(channel.failed_transmissions + channel.succeeded_transmissions) != 0:
            p_coll = "{:.4f}".format(
                channel.failed_transmissions / (channel.failed_transmissions + channel.succeeded_transmissions))
        else:
            p_coll = 0
    else:
        p_coll = 0

    if number_of_gnb != 0:
        if (channel.failed_transmissions_NR + channel.succeeded_transmissions_NR) != 0:
            p_coll_NR = "{:.4f}".format(
                channel.failed_transmissions_NR / (
                        channel.failed_transmissions_NR + channel.succeeded_transmissions_NR))
        else:
            p_coll_NR = 0
    else:
        p_coll_NR = 0

    # DETAILED OUTPUTS:

    print(
        f"SEED = {seed} N_stations:={number_of_stations}  CW_MIN = {config.cw_min} CW_MAX = {config.cw_max}  PCOLL: {p_coll} THR:"
        f" {(channel.bytes_sent * 8) / (simulation_time * 100000)} "
        f"FAILED_TRANSMISSIONS: {channel.failed_transmissions}"
        f" SUCCEEDED_TRANSMISSION {channel.succeeded_transmissions}"
    )

    print('stats for GNB ------------------')

    print(
        f"SEED = {seed} N_gnbs={number_of_gnb} CW_MIN = {config_nr.cw_min} CW_MAX = {config_nr.cw_max}  PCOLL: {p_coll_NR} "
        f"FAILED_TRANSMISSIONS: {channel.failed_transmissions_NR}"
        f" SUCCEEDED_TRANSMISSION {channel.succeeded_transmissions_NR}"
    )

    print('airtimes summary: Wifi, NR ---- 1)data, 2)control')

    print(channel.airtime_data)
    print(channel.airtime_control)
    print(channel.airtime_data_NR)
    print(channel.airtime_control_NR)

    print("sumarizing airtime --------------")
    channel_occupancy_time = 0
    channel_efficiency = 0
    channel_occupancy_time_NR = 0
    channel_efficiency_NR = 0
    time = simulation_time * 1000000  # DEBUG

    # nodes = number_of_stations + number_of_gnb

    # Rashed-Step pre_5.B-02-06-2026-start
    # BUGFIX: this used to read channel.airtime_data["Station {i}"], but
    # WiFi.__init__ registers airtime under the AP's real name ("AP {i}"),
    # so these lookups always hit the initial 0 and WiFi occupancy/
    # efficiency printed as 0.0 even when frames succeeded. Fixed to use
    # the same naming scheme WiFi actually registers under.
    # Rashed-Step pre_5.B-02-06-2026-end
    for i in range(1, number_of_stations + 1):
        channel_occupancy_time += channel.airtime_data["AP {}".format(i)] + channel.airtime_control[
            "AP {}".format(i)]
        channel_efficiency += channel.airtime_data["AP {}".format(i)]

    for i in range(1, number_of_gnb + 1):
        channel_occupancy_time_NR += channel.airtime_data_NR["Gnb {}".format(i)] + channel.airtime_control_NR[
            "Gnb {}".format(i)]
        channel_efficiency_NR += channel.airtime_data_NR["Gnb {}".format(i)]

    normalized_channel_occupancy_time = channel_occupancy_time / time
    normalized_channel_efficiency = channel_efficiency / time
    print(f'Wifi occupancy (Normalized): {normalized_channel_occupancy_time}')
    print(f'Wifi efficieny (Normalized): {normalized_channel_efficiency}')

    normalized_channel_occupancy_time_NR = channel_occupancy_time_NR / time
    normalized_channel_efficiency_NR = channel_efficiency_NR / time
    print(
        f'Gnb occupancy (Normalized): {normalized_channel_occupancy_time_NR}')
    print(f'Gnb efficieny (Normalized): {normalized_channel_efficiency_NR}')

    normalized_channel_occupancy_time_all = (
        channel_occupancy_time + channel_occupancy_time_NR) / time
    normalized_channel_efficiency_all = (
        channel_efficiency + channel_efficiency_NR) / time
    print(f'All occupancy: {normalized_channel_occupancy_time_all}')
    print(f'All efficieny: {normalized_channel_efficiency_all}')

    print(
        f"SEED = {seed} N_stations:={number_of_stations} N_gNB:={number_of_gnb}  CW_MIN = {config.cw_min} CW_MAX = {config.cw_max} "
        f"WiFi pcol:={p_coll} WiFi cot:={normalized_channel_occupancy_time} WiFi eff:={normalized_channel_efficiency} "
        f"gNB pcol:={p_coll_NR} gNB cot:={normalized_channel_occupancy_time_NR} gNB eff:={normalized_channel_efficiency_NR} "
        f" all cot:={normalized_channel_occupancy_time_all} all eff:={normalized_channel_efficiency_all}"
    )
    print(
        f" Wifi succ: {channel.succeeded_transmissions} fail: {channel.failed_transmissions}")
    print(
        f" NR succ: {channel.succeeded_transmissions_NR} fail: {channel.failed_transmissions_NR}")

    # Rashed-Step 3.F-01-12-2026-start

    #fairness_den = 2 * (normalized_channel_occupancy_time_wifi**2 + normalized_channel_occupancy_time_nru**2)

    fairness = (normalized_channel_occupancy_time_all**2) / (2 * (normalized_channel_occupancy_time**2 + normalized_channel_occupancy_time_NR**2)) if (normalized_channel_occupancy_time or normalized_channel_occupancy_time_NR) else 0.0
    # Rashed-Step 3.F-01-12-2026-end
    print(f'fairness: {fairness}')
    joint = fairness * normalized_channel_occupancy_time_all
    print(f'joint: {joint}')

    # Rashed-Step pre_11.E-08-18-2026-start
    # Retired the unconditional lool.csv writer that used to run here
    # (original pre-fork code, no Rashed-Step marker of its own - every
    # run silently appended a row to lool.csv regardless of any CLI
    # flag). Rashed asked to remove it: "there is no need for that"
    # (2026-08-18), now that Step 9.D's export_packets_csv() and Step
    # pre_11.B's packet.log give proper, opt-in, per-run output instead.
    # It was also known-buggy - see common/packet.py's own comment on
    # PACKET_CSV_HEADER: lool.csv's header was a single quoted field
    # with embedded commas instead of separate columns, and its header/
    # data column counts didn't match. Commented out rather than
    # deleted outright, matching this file's own precedent for retired
    # blocks (Step pre_11.B's debug prints). output_csv (common/
    # common.py) is now unused by this function.
    #
    # write_header = True
    # if os.path.isfile(output_csv):
    #     write_header = False
    # with open(output_csv, mode='a', newline="") as result_file:
    #     result_adder = csv.writer(
    #         result_file, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
    #
    #     if write_header:
    #         result_adder.writerow(
    #             ['Seed,WiFi,Gnb,ChannelOccupancyWiFi,ChannelEfficiencyWiFi,PcolWifi,ChannelOccupancyNR,ChannelEfficiencyNR,PcolNR,ChannelOccupancyAll,ChannelEfficiencyAll'])
    #
    #     result_adder.writerow(
    #         [seed, config.cw_max, fairness, number_of_stations, number_of_gnb, normalized_channel_occupancy_time, normalized_channel_efficiency,
    #          p_coll,
    #          normalized_channel_occupancy_time_NR, normalized_channel_efficiency_NR, p_coll_NR,
    #          normalized_channel_occupancy_time_all, normalized_channel_efficiency_all])
    # Rashed-Step pre_11.E-08-18-2026-end


