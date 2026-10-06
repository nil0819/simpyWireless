import click
import sys

from simulation import *
# Rashed-Step 16.F-10-02-2026-start
from core.network import core_config_from_cli
# Rashed-Step 16.F-10-02-2026-end


# Rashed-Step 5.A-02-06-2026-start
def parse_pos_list(raw_values, label: str):
    """Parse a tuple of 'x,y' strings (from a repeatable click option) into
    a list of (float, float) tuples. Raises click.BadParameter on malformed
    input so the CLI fails fast with a clear message instead of a raw
    ValueError/IndexError deep in simulation.py."""
    positions = []
    for raw in raw_values:
        parts = raw.split(",")
        if len(parts) != 2:
            raise click.BadParameter(
                f"{label} must be given as 'x,y' (got: {raw!r})"
            )
        try:
            x, y = float(parts[0]), float(parts[1])
        except ValueError:
            raise click.BadParameter(
                f"{label} coordinates must be numeric (got: {raw!r})"
            )
        positions.append((x, y))
    return positions
# Rashed-Step 5.A-02-06-2026-end


# Rashed-Step 10.A-08-07-2026-start
def parse_traffic_class_mix(raw_values, label: str):
    """Parse a tuple of 'class_label=weight' strings (from a repeatable
    click option, e.g. --wifi-traffic-class-mix voice=0.1 --wifi-traffic-
    class-mix video=0.2 ...) into a {label: weight} dict. Raises
    click.BadParameter on malformed input, same fail-fast convention as
    parse_pos_list(). Does NOT validate labels against
    common.packet.QOS_TRAFFIC_CLASSES - matches that module's own
    deliberate leniency (see traffic_class_priority_rank()'s docstring),
    so a typo'd or custom label doesn't hard-error, it just ranks lowest
    if Step 10.B's priority ordering ever reads it."""
    mix = {}
    for raw in raw_values:
        parts = raw.split("=")
        if len(parts) != 2:
            raise click.BadParameter(
                f"{label} must be given as 'class_label=weight' (got: {raw!r})"
            )
        label_name, weight_str = parts[0], parts[1]
        try:
            weight = float(weight_str)
        except ValueError:
            raise click.BadParameter(
                f"{label} weight must be numeric (got: {raw!r})"
            )
        mix[label_name] = weight
    return mix
# Rashed-Step 10.A-08-07-2026-end


@click.command()
@click.option("-r", "--runs", "runs", default=10, help="Number of simulation runs")
@click.option("--seed", "seed", default=1, help="Seed for simulation")
@click.option(
    "--ap-number",
    "ap_number",
    type=int,
    required=True,
    help="Number of Wi-Fi stations",
)
@click.option(
    "--gnb-number",
    "gnb_number",
    type=int,
    required=True,
    help="Number of NR-U gNBs",
)
@click.option(
    "-t",
    "--simulation-time",
    "simulation_time",
    default=100.0,
    help="Duration of the simulation per stations number in s",
)
@click.option("--wifi_cw_min", "wifi_cw_min", default=15, help="Size of Wi-Fi cw min")
@click.option("--wifi_cw_max", "wifi_cw_max", default=63, help="Size of Wi-Fi cw max")
@click.option("--nru_cw_min", "nru_cw_min", default=15, help="Size of NR-U cw min")
@click.option("--nru_cw_max", "nru_cw_max", default=63, help="Size of NR-U cw max")
@click.option(
    "--wifi_r_limit", "wifi_r_limit", default=7, help="Number of failed transmissions in a row",
)
# Rashed-Step 8.D-08-06-2026-start
@click.option(
    "--nru_r_limit", "nru_r_limit", default=7, help="NR-U: number of failed transmissions in a row before the packet is dropped and replaced. Mirrors --wifi_r_limit - unlike Wi-Fi, this cap was never actually enforced before Step 8.D (see Project details/Step 8.txt).",
)
# Rashed-Step 8.D-08-06-2026-end
@click.option("-m", "--mcs-value", "mcs_value", default=7, help="Value of mcs")
@click.option("-syn_slot", "--synchronization_slot_duration", default=1000, help="Synchronization slot length in mikrosecounds")
@click.option("-max_des", "--max_sync_slot_desync", default=1000, help="Max value of gNB desynchronization")
@click.option("-min_des", "--min_sync_slot_desync", default=0, help="Min value of gNB desynchronization")
@click.option("-nru_obser_slots", "--nru_observation_slot", default=3, help="amount of observation slots for NR_U")
@click.option("--mcot", default=6, help="Max channel occupancy time for NR-U (ms)")
@click.option("--rogue","rogue_wifi",default=False,help="Presence of rogue Wi-Fi AP(True/False)")
# Rashed-Step 5.A-02-06-2026-start
@click.option("--area-w", "area_w", type=float, default=50.0, help="Deployment area width (m) used for randomly placed devices")
@click.option("--area-h", "area_h", type=float, default=50.0, help="Deployment area height (m) used for randomly placed devices")
@click.option("--ap-pos", "ap_pos", type=str, multiple=True, help="Explicit AP position as 'x,y' (repeatable, e.g. --ap-pos 0,0 --ap-pos 50,0). Matched in order to AP 1, AP 2, ...; any AP beyond the number given falls back to a random position within --area-w/--area-h.")
@click.option("--gnb-pos", "gnb_pos", type=str, multiple=True, help="Explicit gNB position as 'x,y' (repeatable). Matched in order to Gnb 1, Gnb 2, ...; same random fallback as --ap-pos.")
@click.option("--sta-radius", "sta_radius", type=float, default=10.0, help="Radius (m) around its AP within which an associated Wi-Fi STA is randomly placed")
@click.option("--ue-radius", "ue_radius", type=float, default=15.0, help="Radius (m) around its gNB within which an associated NR-U UE is randomly placed")
# Rashed-Step 5.A-02-06-2026-end
# Rashed-Step 5.B-02-06-2026-start
@click.option("--shadowing-sigma-db", "shadowing_sigma_db", type=float, default=0.0, help="Log-normal shadow fading std dev in dB, applied on top of the deterministic path loss (0 = disabled/deterministic, matches pre-Step-5.B behavior; typical indoor value ~4-8)")
# Rashed-Step 5.B-02-06-2026-end
# Rashed-Step 5.C-02-06-2026-start
@click.option("--wifi-bandwidth-mhz", "wifi_bandwidth_mhz", type=float, default=20.0, help="Wi-Fi channel bandwidth (MHz), used to derive the SINR noise floor")
@click.option("--wifi-noise-figure-db", "wifi_noise_figure_db", type=float, default=7.0, help="Wi-Fi receiver noise figure (dB), used to derive the SINR noise floor")
@click.option("--nru-bandwidth-mhz", "nru_bandwidth_mhz", type=float, default=20.0, help="NR-U channel bandwidth (MHz), used to derive the SINR noise floor")
@click.option("--nru-noise-figure-db", "nru_noise_figure_db", type=float, default=7.0, help="NR-U receiver noise figure (dB), used to derive the SINR noise floor")
# Rashed-Step 5.C-02-06-2026-end
# Rashed-Step 5.D-02-06-2026-start
@click.option("--nru-mcs", "nru_mcs", type=int, default=4, help="NR-U MCS index (0-7), drives the required-SINR threshold via NRU_MCS_SINR_THRESHOLDS_DB. Note: unlike Wi-Fi's -m/--mcs-value, this does NOT affect NR-U transmission duration (still mcot-based).")
@click.option("--wifi-sinr-thr-db-override", "wifi_sinr_thr_db_override", type=float, default=None, help="Force a flat Wi-Fi SINR success threshold (dB) instead of the per-MCS table lookup")
@click.option("--nru-sinr-thr-db-override", "nru_sinr_thr_db_override", type=float, default=None, help="Force a flat NR-U SINR success threshold (dB) instead of the per-MCS table lookup")
# Rashed-Step 5.D-02-06-2026-end
# Rashed-Step 5.E-02-06-2026-start
@click.option("--wifi-freq-ghz", "wifi_freq_ghz", type=float, default=5.18, help="Wi-Fi center frequency (GHz). Default matches --nru-freq-ghz's default (full co-channel overlap, same as before Step 5.E). Set them apart to model adjacent/non-overlapping channels.")
@click.option("--nru-freq-ghz", "nru_freq_ghz", type=float, default=5.18, help="NR-U center frequency (GHz). See --wifi-freq-ghz.")
# Rashed-Step 5.E-02-06-2026-end
# Rashed-Step 5.F-02-06-2026-start
@click.option("--wifi-tx-power-dbm", "wifi_tx_power_dbm", type=float, default=20.0, help="Wi-Fi tx power (dBm), treated as EIRP directly (no separate antenna-gain model). Checked at startup against the FCC U-NII EIRP cap for --wifi-freq-ghz (warning only, not clamped/enforced). Default (20.0) matches wifi.Config.tx_power_dbm's pre-existing class default - regression-safe.")
@click.option("--nru-tx-power-dbm", "nru_tx_power_dbm", type=float, default=23.0, help="NR-U tx power (dBm). See --wifi-tx-power-dbm. Default (23.0) matches nru.Config_NR.tx_power_dbm's pre-existing class default - regression-safe (NOT the same default as --wifi-tx-power-dbm, intentionally, to match each config's own prior constant).")
# Rashed-Step 5.F-02-06-2026-end
# Rashed-Step 5.G-02-06-2026-start
@click.option("--ap-mobility-speed-mps", "ap_mobility_speed_mps", type=float, default=0.0, help="AP walking/roaming speed (m/s). 0.0 (default) = static, byte-identical to every pre-5.G run. >0 enables random-waypoint mobility within the [0,area-w]x[0,area-h] box.")
@click.option("--gnb-mobility-speed-mps", "gnb_mobility_speed_mps", type=float, default=0.0, help="gNB roaming speed (m/s). See --ap-mobility-speed-mps.")
@click.option("--sta-mobility-speed-mps", "sta_mobility_speed_mps", type=float, default=0.0, help="Wi-Fi STA walking speed (m/s), e.g. ~1.4 for a typical walking pace. See --ap-mobility-speed-mps.")
@click.option("--ue-mobility-speed-mps", "ue_mobility_speed_mps", type=float, default=0.0, help="NR-U UE walking speed (m/s). See --ap-mobility-speed-mps.")
@click.option("--mobility-pause-s", "mobility_pause_s", type=float, default=0.0, help="Dwell time (s) at each waypoint before picking the next one, for any node type with mobility enabled. 0.0 (default) = keep moving continuously between waypoints.")
# Rashed-Step 14.D-08-28-2026-start
@click.option("--gnb-mobility-linear-target", "gnb_mobility_linear_target", type=str, default=None, help="Deterministic directed gNB mobility: 'x,y' target position. The gNB moves in a straight line from --gnb-pos to this target over --gnb-mobility-linear-duration-s seconds, then holds there for the rest of the run - unlike --gnb-mobility-speed-mps's random-waypoint roaming, this gives a REPRODUCIBLE, precisely-timed transition (e.g. starting outside a sensing-range crossover distance and arriving inside it at a known time). Mutually exclusive with --gnb-mobility-speed-mps (fails fast if both are set).")
@click.option("--gnb-mobility-linear-duration-s", "gnb_mobility_linear_duration_s", type=float, default=0.0, help="Duration (s) of the directed move above - required (and only meaningful) when --gnb-mobility-linear-target is set.")
@click.option("--ue-follow-gnb-offset", "ue_follow_gnb_offset", type=str, default=None, help="'dx,dy' - the UE rigidly tracks its gNB's CURRENT position (however the gNB moves, or doesn't) plus this fixed offset, instead of its own independent placement/mobility. Guarantees the gNB-UE distance never changes, so their own link quality is unaffected by whatever mobility the gNB has. Mutually exclusive with --ue-mobility-speed-mps (fails fast if both are set).")
# Rashed-Step 14.D-08-28-2026-end
# Rashed-Step 5.G-02-06-2026-end
# Rashed-Step 8.B-08-06-2026-start
@click.option("--wifi-traffic-model", "wifi_traffic_model", type=click.Choice(["saturated", "poisson", "cbr"]), default="saturated", help="Wi-Fi traffic arrival model. saturated (default) = every AP always has a frame ready the instant it gets channel access, byte-identical to every pre-Step-8.B run. poisson/cbr = packets arrive per the given rate; the AP can genuinely sit idle with nothing to send.")
@click.option("--wifi-arrival-rate-pps", "wifi_arrival_rate_pps", type=float, default=100.0, help="Wi-Fi packet arrival rate (packets/sec), used only when --wifi-traffic-model is poisson or cbr.")
@click.option("--nru-traffic-model", "nru_traffic_model", type=click.Choice(["saturated", "poisson", "cbr"]), default="saturated", help="NR-U traffic arrival model. See --wifi-traffic-model.")
@click.option("--nru-arrival-rate-pps", "nru_arrival_rate_pps", type=float, default=100.0, help="NR-U packet arrival rate (packets/sec), used only when --nru-traffic-model is poisson or cbr.")
# Rashed-Step 8.B-08-06-2026-end
# Rashed-Step 8.C-08-06-2026-start
@click.option("--wifi-packet-size-bytes", "wifi_packet_size_bytes", type=int, default=None, help="Override Wi-Fi packet payload size (bytes). Default (unset/None) = each AP's --mcs-value-controlled config.data_size (1472B), byte-identical to every pre-Step-8.C run. When set, this size now genuinely drives the PPDU on-air duration (Times.get_ppdu_frame_time()), not just a label.")
@click.option("--nru-packet-size-bytes", "nru_packet_size_bytes", type=int, default=None, help="Override NR-U packet payload size (bytes). Default (unset/None) = 1500B placeholder. NOTE: unlike Wi-Fi, this does NOT affect NR-U's on-air duration - NR-U's Transmission_NR duration stays purely mcot-based (real 3GPP Category-4 LBT channel-occupancy semantics), so this only affects the Packet bookkeeping (payload_bytes/total_bytes()), not timing. See Project details/Step 8.txt.")
# Rashed-Step 8.C-08-06-2026-end
# Rashed-Step 9.D-08-07-2026-start
@click.option("--export-packets-csv", "export_packets_csv_path", type=str, default=None, help="Append one CSV row per packet (both technologies, per-node) to this path, for offline analysis at individual-packet granularity. Default (unset/None) = feature off, no file touched - byte-identical to every pre-Step-9.D run. Same 'write header once if the file doesn't exist yet, then append' behavior as -r/--runs > 1 or repeated invocations against the same path (a 'seed' column keeps rows from different runs distinguishable). See common/packet.py's export_packets_csv()/PACKET_CSV_HEADER for the exact columns.")
# Rashed-Step 9.D-08-07-2026-end
# Rashed-Step 10.A-08-07-2026-start
@click.option("--wifi-traffic-class-mix", "wifi_traffic_class_mix", type=str, multiple=True, help="Wi-Fi QoS traffic-class mix, repeatable 'class_label=weight' (e.g. --wifi-traffic-class-mix voice=0.1 --wifi-traffic-class-mix video=0.2 --wifi-traffic-class-mix best_effort=0.5 --wifi-traffic-class-mix background=0.2). Default (unset) = every packet stays 'best_effort' with NO random draw at all - byte-identical to every pre-Step-10.A run. When set, each new packet draws its class via a weighted random choice. Labels are conventionally from common.packet.QOS_TRAFFIC_CLASSES (voice/video/best_effort/background, WMM-AC-flavored) but not enforced. This only tags packets for now - actual differentiated channel access (EDCA-style priority) is a later step, not yet implemented.")
@click.option("--nru-traffic-class-mix", "nru_traffic_class_mix", type=str, multiple=True, help="NR-U QoS traffic-class mix. See --wifi-traffic-class-mix.")
# Rashed-Step 10.A-08-07-2026-end
# Rashed-Step 10.B-08-07-2026-start
@click.option("--wifi-edca", "wifi_edca", is_flag=True, default=False, help="Enable real 802.11e EDCA differentiated channel access for Wi-Fi (per-AC voice/video/best_effort/background contention with independent CWmin/CWmax/AIFSN and virtual-collision resolution - see Project details/Step 10.txt's 10.B section). Wi-Fi only (NR-U is unaffected - no standardized EDCA-equivalent exists for unlicensed LBT). Default (unset/False) = legacy single-queue DCF contention, byte-identical to every pre-Step-10.B run. Currently requires --wifi-traffic-model=saturated (the default) - EDCA + poisson/cbr queueing is a deferred follow-up.")
# Rashed-Step 10.B-08-07-2026-end
# Rashed-Step 11.A-08-21-2026-start
@click.option("--wifi-rate-adapt", "wifi_rate_adapt", is_flag=True, default=False, help="Enable dynamic per-STA MCS rate adaptation for Wi-Fi, ARF-style (Kamerman & Monteban 1997): step MCS up after 10 consecutive successes, down after 2 consecutive failures - no channel-state feedback, matches real legacy 802.11 hardware behavior. Default (unset/False) = -m/--mcs-value stays fixed for the whole run, byte-identical to every pre-Step-11 run.")
# Rashed-Step 11.A-08-21-2026-end
# Rashed-Step 11.B-08-21-2026-start
@click.option("--nru-rate-adapt", "nru_rate_adapt", is_flag=True, default=False, help="Enable dynamic per-UE MCS rate adaptation for NR-U, CQI-style: pick the MCS whose required-SINR threshold best fits the most recently MEASURED link SINR (approximates 3GPP's UE-reported Channel Quality Indicator feedback - this simulator has no explicit CQI report message, so 'last measured SINR' stands in for it). Only affects the success/failure SINR threshold, NOT transmission duration (NR-U stays mcot-based - see --nru-mcs's own help). Default (unset/False) = --nru-mcs stays fixed for the whole run, byte-identical to every pre-Step-11 run.")
# Rashed-Step 11.B-08-21-2026-end
# Rashed-Step 13.D-08-23-2026-start
@click.option("--nru-rate-adapt-ml-model", "nru_rate_adapt_ml_model", type=str, default=None, help="Path to a trained SINR-prediction model (ml/train_sinr_model.py's saved output, e.g. ml/data/sinr_model.joblib). When set, NR-U's CQI-style rate adaptation (--nru-rate-adapt, required alongside this flag) uses the model's PREDICTED next SINR instead of the raw last-measured value, once a link has enough history (ml/train_sinr_model.LAG_K measurements). Default (unset/None) = every pre-Step-13.D run's exact behavior. NOTE: Step 13.C's own evaluation found this model does not beat plain 'last observed' on MAE for held-out scenarios - this flag is provided to empirically test its effect on actual coexistence outcomes, not because it's known to help (see Project details/Step 13.txt's 13.D section).")
# Rashed-Step 13.D-08-23-2026-end
# Rashed-Step 13.E.1-08-23-2026-start
@click.option("--wifi-rate-adapt-ml-model", "wifi_rate_adapt_ml_model", type=str, default=None, help="Same idea as --nru-rate-adapt-ml-model, for Wi-Fi. When set, Wi-Fi's rate adaptation (--wifi-rate-adapt, required alongside this flag) switches from ARF's success/fail-streak logic to a CQI-style direct MCS pick from the model's PREDICTED next SINR, once a link has enough history. Default (unset/None) = every pre-Step-13.E run's exact ARF behavior. The same model file trained for NR-U works here too (it was trained with a technology_is_wifi feature already) - no separate Wi-Fi model needed.")
# Rashed-Step 13.E.1-08-23-2026-end
# Rashed-Step 15.G-09-18-2026-start
@click.option("--nru-ue-uplink-enabled", "nru_ue_uplink_enabled", is_flag=True, default=False, help="Enable real NR-U uplink (saturated traffic). How the UE gets the channel is set by --nru-ul-access-mode: by default (cot_sharing, Step 17) its gNB grants it the uplink part of the gNB's own channel occupancy time and the UE sends after a 25us Type 2A check; with autonomous (Step 15.C) every UE runs its own Cat-4 LBT, which makes it collide with its own gNB. Default (unset/False) = every UE stays the passive position+label object it always was, byte-identical to every pre-15.C run.")
@click.option("--nru-rrc-enabled", "nru_rrc_enabled", is_flag=True, default=False, help="Enable the generic RRC attach state machine (Step 15.F) for every NR-U UE: IDLE -> CONNECTING -> CONNECTED, via a real RRCSetupRequest/RRCSetup/RRCSetupComplete exchange whose uplink messages wait for the gNB's next channel occupancy time plus a 25us Type 2A check (--nru-ul-access-mode cot_sharing, default) or for the UE's own Cat-4 LBT (autonomous). Requires --nru-ue-uplink-enabled too (RRC attach needs real uplink capability - fails fast otherwise). Once set, the gNB's own downlink scheduling AND each UE's own uplink data traffic (Step 15.G) are gated on rrc_state==CONNECTED - see Project details/Step pre_15.txt's STEP 15 - 15.G DONE section. Default (unset/False) = every UE has no rrc_state at all, byte-identical to every pre-15.F run.")
# Rashed-Step 15.G-09-18-2026-end
# Rashed-Step 16.F-10-02-2026-start
@click.option("--nru-core-enabled", "nru_core_enabled", is_flag=True, default=False, help="Enable the minimal 5G Core (Step 16) for every NR-U UE (Wi-Fi untouched): registration with the AMF and a PDU session (SMF/UPF) after RRC connects (or from t=0 without --nru-rrc-enabled); the gNB's downlink and each UE's uplink carry no data for a UE until its session is ACTIVE. Prints an 'NR-U 5G Core' stdout block (its first-packet line counts downlink and, with --nru-ue-uplink-enabled, uplink). Default (unset/False) = no Core, byte-identical to every pre-16.F run.")
@click.option("--core-registration-delay-us", "core_registration_delay_us", type=float, default=None, help="Registration Request -> Accept time in us (default 90000, measured Open5GS testbed - see core/network.py). Requires --nru-core-enabled.")
@click.option("--core-pdu-session-delay-us", "core_pdu_session_delay_us", type=float, default=None, help="PDU Session Establishment Request -> Accept time in us (default 125000, measured Open5GS testbed). Requires --nru-core-enabled.")
# Rashed-Step 16.F-10-02-2026-end
# Rashed-Step pre_17.B-10-04-2026-start
@click.option("--wifi-sta-uplink-enabled", "wifi_sta_uplink_enabled", is_flag=True, default=False, help="Enable real Wi-Fi uplink (Step 15.B): every STA contends for the channel with the same CSMA/CA backoff as its AP and sends saturated uplink traffic to it. Prints a 'Wi-Fi Uplink' stdout block, and with --export-packets-csv adds each STA's uplink packets (node = STA name). Not supported with --rogue True. Default (unset/False) = STAs stay passive, byte-identical to every earlier run.")
# Rashed-Step pre_17.B-10-04-2026-end
# Rashed-Step 17.G-10-04-2026-start
@click.option("--nru-ul-access-mode", "nru_ul_access_mode", type=click.Choice(["cot_sharing", "autonomous"]), default="cot_sharing", help="How NR-U UEs access the channel for uplink (only matters with --nru-ue-uplink-enabled). cot_sharing (default, Step 17): the gNB splits each channel occupancy time into a downlink part and an uplink part granted to one of its UEs (round-robin), who sends after a 25us Type 2A check. autonomous (Step 15.C): every UE runs its own Cat-4 LBT - kept for comparison; it makes a gNB and its own UE collide on every saturated attempt.")
@click.option("--nru-ul-cot-fraction", "nru_ul_cot_fraction", type=float, default=0.5, help="cot_sharing only: share of the gNB's channel occupancy time given to uplink (strictly between 0 and 1; default 0.5).")
# Rashed-Step 17.G-10-04-2026-end

def single_run(
        runs: int,
        seed: int,
        ap_number: int,
        gnb_number: int,
        simulation_time: int,
        wifi_cw_min: int,
        wifi_cw_max: int,
        wifi_r_limit: int,
        mcs_value: int,

        nru_cw_min: int,
        nru_cw_max: int,
        # Rashed-Step 8.D-08-06-2026-start
        nru_r_limit: int,
        # Rashed-Step 8.D-08-06-2026-end
        synchronization_slot_duration: int,
        max_sync_slot_desync: int,
        min_sync_slot_desync: int,
        nru_observation_slot: int,
        mcot: int,
        rogue_wifi: bool,
        # Rashed-Step 5.A-02-06-2026-start
        area_w: float,
        area_h: float,
        ap_pos: tuple,
        gnb_pos: tuple,
        sta_radius: float,
        ue_radius: float,
        # Rashed-Step 5.A-02-06-2026-end
        # Rashed-Step 5.B-02-06-2026-start
        shadowing_sigma_db: float,
        # Rashed-Step 5.B-02-06-2026-end
        # Rashed-Step 5.C-02-06-2026-start
        wifi_bandwidth_mhz: float,
        wifi_noise_figure_db: float,
        nru_bandwidth_mhz: float,
        nru_noise_figure_db: float,
        # Rashed-Step 5.C-02-06-2026-end
        # Rashed-Step 5.D-02-06-2026-start
        nru_mcs: int,
        wifi_sinr_thr_db_override: float,
        nru_sinr_thr_db_override: float,
        # Rashed-Step 5.D-02-06-2026-end
        # Rashed-Step 5.E-02-06-2026-start
        wifi_freq_ghz: float,
        nru_freq_ghz: float,
        # Rashed-Step 5.E-02-06-2026-end
        # Rashed-Step 5.F-02-06-2026-start
        wifi_tx_power_dbm: float,
        nru_tx_power_dbm: float,
        # Rashed-Step 5.F-02-06-2026-end
        # Rashed-Step 5.G-02-06-2026-start
        ap_mobility_speed_mps: float,
        gnb_mobility_speed_mps: float,
        sta_mobility_speed_mps: float,
        ue_mobility_speed_mps: float,
        mobility_pause_s: float,
        # Rashed-Step 5.G-02-06-2026-end
        # Rashed-Step 8.B-08-06-2026-start
        wifi_traffic_model: str,
        wifi_arrival_rate_pps: float,
        nru_traffic_model: str,
        nru_arrival_rate_pps: float,
        # Rashed-Step 8.B-08-06-2026-end
        # Rashed-Step 8.C-08-06-2026-start
        wifi_packet_size_bytes: int,
        nru_packet_size_bytes: int,
        # Rashed-Step 8.C-08-06-2026-end
        # Rashed-Step 9.D-08-07-2026-start
        export_packets_csv_path: Optional[str] = None,
        # Rashed-Step 9.D-08-07-2026-end
        # Rashed-Step 10.A-08-07-2026-start
        wifi_traffic_class_mix=(),
        nru_traffic_class_mix=(),
        # Rashed-Step 10.A-08-07-2026-end
        # Rashed-Step 10.B-08-07-2026-start
        wifi_edca: bool = False,
        # Rashed-Step 10.B-08-07-2026-end
        # Rashed-Step 11.A-08-21-2026-start
        wifi_rate_adapt: bool = False,
        # Rashed-Step 11.A-08-21-2026-end
        # Rashed-Step 11.B-08-21-2026-start
        nru_rate_adapt: bool = False,
        # Rashed-Step 11.B-08-21-2026-end
        # Rashed-Step 13.D-08-23-2026-start
        nru_rate_adapt_ml_model: str = None,
        # Rashed-Step 13.D-08-23-2026-end
        # Rashed-Step 13.E.1-08-23-2026-start
        wifi_rate_adapt_ml_model: str = None,
        # Rashed-Step 13.E.1-08-23-2026-end
        # Rashed-Step 14.D-08-28-2026-start
        gnb_mobility_linear_target: str = None,
        gnb_mobility_linear_duration_s: float = 0.0,
        ue_follow_gnb_offset: str = None,
        # Rashed-Step 14.D-08-28-2026-end
        # Rashed-Step 15.G-09-18-2026-start
        nru_ue_uplink_enabled: bool = False,
        nru_rrc_enabled: bool = False,
        # Rashed-Step 15.G-09-18-2026-end
        # Rashed-Step 16.F-10-02-2026-start
        nru_core_enabled: bool = False,
        core_registration_delay_us: float = None,
        core_pdu_session_delay_us: float = None,
        # Rashed-Step pre_17.B-10-04-2026-start
        wifi_sta_uplink_enabled: bool = False,
        # Rashed-Step 17.G-10-04-2026-start
        nru_ul_access_mode: str = "cot_sharing",
        nru_ul_cot_fraction: float = 0.5,
        # Rashed-Step 17.G-10-04-2026-end
        # Rashed-Step pre_17.B-10-04-2026-end
        # Rashed-Step 16.F-10-02-2026-end
):
    backoffs = {key: {ap_number: 0} for key in range(wifi_cw_max + 1)}
    airtime_data = {"Station {}".format(i): 0 for i in range(1, ap_number + 1)}
    airtime_control = {"Station {}".format(i): 0 for i in range(1, ap_number + 1)}
    airtime_data_NR = {"Gnb {}".format(i): 0 for i in range(1, gnb_number + 1)}
    airtime_control_NR = {"Gnb {}".format(i): 0 for i in range(1, gnb_number + 1)}

    # Rashed-Step 5.A-02-06-2026-start
    ap_positions = parse_pos_list(ap_pos, "--ap-pos") if ap_pos else None
    gnb_positions = parse_pos_list(gnb_pos, "--gnb-pos") if gnb_pos else None
    # Rashed-Step 5.A-02-06-2026-end

    # Rashed-Step 14.D-08-28-2026-start
    if gnb_mobility_linear_target and gnb_mobility_speed_mps > 0.0:
        raise click.BadParameter(
            "--gnb-mobility-linear-target and --gnb-mobility-speed-mps are "
            "mutually exclusive - the gNB can have random-waypoint roaming "
            "OR a directed linear move, not both."
        )
    if ue_follow_gnb_offset and ue_mobility_speed_mps > 0.0:
        raise click.BadParameter(
            "--ue-follow-gnb-offset and --ue-mobility-speed-mps are "
            "mutually exclusive - the UE can have its own random-waypoint "
            "roaming OR rigidly follow the gNB, not both."
        )
    gnb_mobility_linear_target_pos = (
        parse_pos_list((gnb_mobility_linear_target,), "--gnb-mobility-linear-target")[0]
        if gnb_mobility_linear_target else None
    )
    ue_follow_gnb_offset_pos = (
        parse_pos_list((ue_follow_gnb_offset,), "--ue-follow-gnb-offset")[0]
        if ue_follow_gnb_offset else None
    )
    # Rashed-Step 14.D-08-28-2026-end

    # Rashed-Step 10.A-08-07-2026-start
    # Empty tuple (default, no --wifi/nru-traffic-class-mix given) ->
    # empty dict from parse_traffic_class_mix() -> falsy -> normalized
    # to None here, NOT an empty-but-not-None dict, so
    # TrafficConfig.traffic_class_mix stays exactly None (the "no random
    # draw at all" case its own docstring requires) rather than a
    # technically-truthy-check-passing empty dict that would behave
    # differently depending on how downstream code tests it.
    wifi_class_mix = parse_traffic_class_mix(wifi_traffic_class_mix, "--wifi-traffic-class-mix") or None
    nru_class_mix = parse_traffic_class_mix(nru_traffic_class_mix, "--nru-traffic-class-mix") or None
    # Rashed-Step 10.A-08-07-2026-end

    # Rashed-Step 10.B-08-07-2026-start
    # Fail fast with a clear CLI-level message rather than letting the
    # user hit wifi.WiFi.__init__'s deeper ValueError - same information,
    # surfaced earlier. That ValueError guard stays in place too (defense
    # in depth for anyone constructing WiFi directly, not just via this
    # CLI).
    if wifi_edca and wifi_traffic_model != "saturated":
        raise click.BadParameter(
            "--wifi-edca currently only supports --wifi-traffic-model=saturated "
            "(EDCA + poisson/cbr queueing is a deferred follow-up - see "
            "Project details/Step 10.txt's 10.B NOT DONE list)."
        )
    # Rashed-Step 10.B-08-07-2026-end

    # Rashed-Step 13.D-08-23-2026-start
    # Same fail-fast-at-the-CLI convention as the --wifi-edca guard
    # above, not a deep AttributeError inside nru.py.
    if nru_rate_adapt_ml_model and not nru_rate_adapt:
        raise click.BadParameter(
            "--nru-rate-adapt-ml-model requires --nru-rate-adapt to also be "
            "set (the model only replaces WHICH SINR value drives an "
            "already-enabled CQI-style pick, it doesn't enable rate "
            "adaptation on its own)."
        )
    nru_sinr_predictor = None
    if nru_rate_adapt_ml_model:
        # Imported here, not at module level - so running singleRun.py
        # without this flag never requires sklearn/pandas/joblib to be
        # installed (Step 13.txt design decision 6: ML code stays out
        # of the simulator core's normal dependency footprint).
        from ml.predictor import SinrPredictor
        nru_sinr_predictor = SinrPredictor(nru_rate_adapt_ml_model)
    # Rashed-Step 13.D-08-23-2026-end

    # Rashed-Step 13.E.1-08-23-2026-start
    if wifi_rate_adapt_ml_model and not wifi_rate_adapt:
        raise click.BadParameter(
            "--wifi-rate-adapt-ml-model requires --wifi-rate-adapt to also "
            "be set (the model only replaces WHICH SINR value drives an "
            "already-enabled MCS pick, it doesn't enable rate adaptation "
            "on its own)."
        )
    wifi_sinr_predictor = None
    if wifi_rate_adapt_ml_model:
        from ml.predictor import SinrPredictor
        wifi_sinr_predictor = SinrPredictor(wifi_rate_adapt_ml_model)
    # Rashed-Step 13.E.1-08-23-2026-end

    # Rashed-Step 15.G-09-18-2026-start
    # Same fail-fast-at-the-CLI convention as the --wifi-edca/--nru-
    # rate-adapt-ml-model guards above - NrUE.__post_init__ would raise
    # this same ValueError anyway, but at construction time deep inside
    # simulation.py, not here at the CLI entry point.
    if nru_rrc_enabled and not nru_ue_uplink_enabled:
        raise click.BadParameter(
            "--nru-rrc-enabled requires --nru-ue-uplink-enabled to also "
            "be set (RRC attach needs real uplink capability to send "
            "RRCSetupRequest/RRCSetupComplete - see ran/protocol/rrc.py's "
            "module docstring)."
        )
    # Rashed-Step 15.G-09-18-2026-end

    # Rashed-Step 16.F-10-02-2026-start
    try:
        core_config = core_config_from_cli(nru_core_enabled, core_registration_delay_us, core_pdu_session_delay_us)
    except ValueError as e:
        raise click.BadParameter(str(e))
    # Rashed-Step pre_17.B-10-04-2026-start
    # Rashed-Step 17.G-10-04-2026-start
    if not (0.0 < nru_ul_cot_fraction < 1.0):
        raise click.BadParameter(
            f"--nru-ul-cot-fraction must be strictly between 0 and 1 (got {nru_ul_cot_fraction})."
        )
    # Rashed-Step 17.G-10-04-2026-end
    if wifi_sta_uplink_enabled and rogue_wifi:
        raise click.BadParameter(
            "--wifi-sta-uplink-enabled is not supported with --rogue True "
            "(the rogue AP never wires its STAs, so they would have no AP "
            "to send uplink to)."
        )
    # Rashed-Step pre_17.B-10-04-2026-end
    # Rashed-Step 16.F-10-02-2026-end

    # Rashed-Step 8.B-08-06-2026-start
    # Rashed-Step 8.C-08-06-2026: added packet_size_bytes=... (defaults
    # to None, matching TrafficConfig's own default - unset means "use
    # the node's own built-in default size", exactly as before).
    wifi_traffic_config = TrafficConfig(
        mode=wifi_traffic_model, arrival_rate_pps=wifi_arrival_rate_pps, packet_size_bytes=wifi_packet_size_bytes,
        # Rashed-Step 10.A-08-07-2026-start
        traffic_class_mix=wifi_class_mix,
        # Rashed-Step 10.A-08-07-2026-end
    )
    nru_traffic_config = TrafficConfig(
        mode=nru_traffic_model, arrival_rate_pps=nru_arrival_rate_pps, packet_size_bytes=nru_packet_size_bytes,
        # Rashed-Step 10.A-08-07-2026-start
        traffic_class_mix=nru_class_mix,
        # Rashed-Step 10.A-08-07-2026-end
    )
    # Rashed-Step 8.B-08-06-2026-end

    for i in range(0, runs):
        curr_seed = seed + i
        print("before simulation")
        run_simulation(ap_number, gnb_number, curr_seed, simulation_time,
                       # Rashed-Step 5.C-02-06-2026-start
                       Config(1472, wifi_cw_min, wifi_cw_max, wifi_r_limit, mcs_value,
                              bandwidth_mhz=wifi_bandwidth_mhz, noise_figure_db=wifi_noise_figure_db,
                              # Rashed-Step 5.D-02-06-2026-start
                              wifi_sinr_thr_db_override=wifi_sinr_thr_db_override,
                              # Rashed-Step 5.D-02-06-2026-end
                              # Rashed-Step 5.E-02-06-2026-start
                              f_ghz=wifi_freq_ghz * 1e9,
                              # Rashed-Step 5.E-02-06-2026-end
                              # Rashed-Step 5.F-02-06-2026-start
                              tx_power_dbm=wifi_tx_power_dbm,
                              # Rashed-Step 5.F-02-06-2026-end
                              # Rashed-Step 10.B-08-07-2026-start
                              qos_enabled=wifi_edca,
                              # Rashed-Step 10.B-08-07-2026-end
                              # Rashed-Step 11.A-08-21-2026-start
                              rate_adapt_enabled=wifi_rate_adapt,
                              # Rashed-Step 11.A-08-21-2026-end
                              # Rashed-Step 13.E.1-08-23-2026-start
                              sinr_predictor=wifi_sinr_predictor,
                              # Rashed-Step 13.E.1-08-23-2026-end
                              ),
                       Config_NR(16, 9, synchronization_slot_duration, max_sync_slot_desync, min_sync_slot_desync,  nru_observation_slot, nru_cw_min, nru_cw_max, mcot,
                                 # Rashed-Step 8.D-08-06-2026-start
                                 r_limit=nru_r_limit,
                                 # Rashed-Step 8.D-08-06-2026-end
                                 bandwidth_mhz=nru_bandwidth_mhz, noise_figure_db=nru_noise_figure_db,
                                 # Rashed-Step 5.D-02-06-2026-start
                                 mcs=nru_mcs, nru_sinr_thr_db_override=nru_sinr_thr_db_override,
                                 # Rashed-Step 5.D-02-06-2026-end
                                 # Rashed-Step 5.E-02-06-2026-start
                                 f_ghz=nru_freq_ghz * 1e9,
                                 # Rashed-Step 5.E-02-06-2026-end
                                 # Rashed-Step 5.F-02-06-2026-start
                                 tx_power_dbm=nru_tx_power_dbm,
                                 # Rashed-Step 5.F-02-06-2026-end
                                 # Rashed-Step 11.B-08-21-2026-start
                                 rate_adapt_enabled=nru_rate_adapt,
                                 # Rashed-Step 11.B-08-21-2026-end
                                 # Rashed-Step 13.D-08-23-2026-start
                                 sinr_predictor=nru_sinr_predictor,
                                 # Rashed-Step 13.D-08-23-2026-end
                                 # Rashed-Step 17.G-10-04-2026-start
                                 ul_access_mode=NruUplinkAccessMode(nru_ul_access_mode),
                                 ul_cot_fraction=nru_ul_cot_fraction,
                                 # Rashed-Step 17.G-10-04-2026-end
                                 ),
                       # Rashed-Step 5.C-02-06-2026-end
                       backoffs, airtime_data, airtime_control, airtime_data_NR, airtime_control_NR, rogue_wifi,
                       # Rashed-Step 5.A-02-06-2026-start
                       area_w=area_w, area_h=area_h,
                       ap_positions=ap_positions, gnb_positions=gnb_positions,
                       sta_radius=sta_radius, ue_radius=ue_radius,
                       # Rashed-Step 5.A-02-06-2026-end
                       # Rashed-Step 5.B-02-06-2026-start
                       shadowing_sigma_db=shadowing_sigma_db,
                       # Rashed-Step 5.B-02-06-2026-end
                       # Rashed-Step 5.G-02-06-2026-start
                       ap_mobility_speed_mps=ap_mobility_speed_mps,
                       gnb_mobility_speed_mps=gnb_mobility_speed_mps,
                       sta_mobility_speed_mps=sta_mobility_speed_mps,
                       ue_mobility_speed_mps=ue_mobility_speed_mps,
                       mobility_pause_s=mobility_pause_s,
                       # Rashed-Step 5.G-02-06-2026-end
                       # Rashed-Step 8.B-08-06-2026-start
                       wifi_traffic_config=wifi_traffic_config,
                       nru_traffic_config=nru_traffic_config,
                       # Rashed-Step 8.B-08-06-2026-end
                       # Rashed-Step 9.D-08-07-2026-start
                       export_packets_csv_path=export_packets_csv_path,
                       # Rashed-Step 9.D-08-07-2026-end
                       # Rashed-Step 14.D-08-28-2026-start
                       gnb_mobility_linear_target=gnb_mobility_linear_target_pos,
                       gnb_mobility_linear_duration_s=gnb_mobility_linear_duration_s,
                       ue_follow_gnb_offset=ue_follow_gnb_offset_pos,
                       # Rashed-Step 14.D-08-28-2026-end
                       # Rashed-Step 15.G-09-18-2026-start
                       nru_ue_uplink_enabled=nru_ue_uplink_enabled,
                       nru_rrc_enabled=nru_rrc_enabled,
                       # Rashed-Step 15.G-09-18-2026-end
                       # Rashed-Step 16.F-10-02-2026-start
                       nru_core_enabled=nru_core_enabled,
                       core_config=core_config,
                       # Rashed-Step pre_17.B-10-04-2026-start
                       wifi_sta_uplink_enabled=wifi_sta_uplink_enabled,
                       # Rashed-Step pre_17.B-10-04-2026-end
                       # Rashed-Step 16.F-10-02-2026-end
                       )





if __name__ == "__main__":
    single_run()