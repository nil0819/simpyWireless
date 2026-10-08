import click
import sys

from simulation import *
# Rashed-Step 16.F-10-02-2026-start
from core.network import core_config_from_cli
# Rashed-Step 18.A-10-06-2026-start
from common.error_model import error_model_config_from_cli
# Rashed-Step 18.E-10-06-2026-start
from ran.protocol.harq import harq_config_from_cli
# Rashed-Step 18.F-10-06-2026-start
from ran.protocol.l2 import l2_config_from_cli
# Rashed-Step 19.A-10-07-2026-start
from ran.protocol.rach import rach_config_from_cli
# Rashed-Step 19.B.2-10-07-2026-start
from ran.protocol.rlm import rlm_config_from_cli
# Rashed-Step 19.B.3-10-07-2026-start
from ran.protocol.inactive import inactive_config_from_cli
# Rashed-Step 19.B.3-10-07-2026-end
# Rashed-Step 19.B.2-10-07-2026-end
# Rashed-Step 19.A-10-07-2026-end
# Rashed-Step 18.F-10-06-2026-end
# Rashed-Step 18.E-10-06-2026-end
# Rashed-Step 18.A-10-06-2026-end
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
@click.option("--wifi-edca", "wifi_edca", is_flag=True, default=False, help="Enable real 802.11e EDCA differentiated channel access for Wi-Fi (per-AC voice/video/best_effort/background contention with independent CWmin/CWmax/AIFSN and virtual-collision resolution - see Project details/Step 10.txt's 10.B section). Wi-Fi only (NR-U is unaffected - no standardized EDCA-equivalent exists for unlicensed LBT). Default (unset/False) = legacy single-queue DCF contention, byte-identical to every pre-Step-10.B run. Works with any --wifi-traffic-model: poisson/cbr arrivals go into one queue per access category (Step 20.B), and --wifi-ampdu aggregates per access category within its TXOP limit.")
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
# Rashed-Step 18.A-10-06-2026-start
@click.option("--error-model", "error_model", type=click.Choice(["threshold", "bler"]), default="threshold", help="Link error model for every technology in the run (Step 18.A). threshold (default): a frame/transport block decodes iff its SINR meets its MCS threshold, byte-identical to every earlier run. bler: a random draw against a block-error-rate curve that hits 10% at the MCS threshold (the 3GPP CQI definition) - needed for HARQ. Prints an 'Error Model' stdout block.")
@click.option("--bler-slope-db", "bler_slope_db", type=float, default=None, help="bler only: steepness of the BLER curve in 1/dB (default 2.0: 90% -> 10% BLER over ~2.2 dB). Requires --error-model bler.")
# Rashed-Step 18.A-10-06-2026-end
# Rashed-Step 18.C-10-06-2026-start
@click.option("--nru-cot-model", "nru_cot_model", type=click.Choice(["burst", "slots"]), default="burst", help="How an NR-U COT's downlink carries data (Step 18.C). burst (default): one transmission with one packet at --nru-mcs, byte-identical to every earlier run. slots: a run of NR slots (--nru-numerology), each a transport block sized from MCS x RBs x slot time with its own SINR; MCS from the UE's last reported SINR; data from per-UE buffers (--nru-traffic-model; --nru-arrival-rate-pps stays a per-gNB total). Prints an 'NR-U Slots' stdout block.")
@click.option("--nru-numerology", "nru_numerology", type=int, default=None, help="slots only: NR numerology mu (default 1 = 30 kHz SCS, 500 us slots).")
@click.option("--nru-ul-traffic-model", "nru_ul_traffic_model", type=click.Choice(["saturated", "poisson", "cbr"]), default="saturated", help="slots + --nru-ue-uplink-enabled with cot_sharing (Step 18.D): uplink traffic per UE. saturated (default): every UE always has uplink data. poisson / cbr: packets arrive at --nru-ul-arrival-rate-pps per UE into its uplink buffer.")
@click.option("--nru-ul-arrival-rate-pps", "nru_ul_arrival_rate_pps", type=float, default=None, help="Uplink packets per second per UE (default 100). Requires --nru-ul-traffic-model poisson or cbr.")
# Rashed-Step 18.E-10-06-2026-start
@click.option("--harq", "harq", is_flag=True, default=False, help="Enable HARQ (Step 18.E): a transport block that fails is retransmitted (ahead of new data, after --harq-rtt-slots) and decoded with chase combining; dropped after --harq-max-tx attempts. Prints a HARQ stdout block. Default (unset) = a failed block's packets are dropped, byte-identical to earlier runs. NR-U only, needs --nru-cot-model slots.")
@click.option("--harq-max-tx", "harq_max_tx", type=int, default=None, help="Transmissions per transport block, first one included (default 4). Requires --harq.")
@click.option("--harq-rtt-slots", "harq_rtt_slots", type=int, default=None, help="Slots from a failed attempt to its earliest retransmission (default 4). Requires --harq.")
# Rashed-Step 18.E-10-06-2026-end
# Rashed-Step 18.F-10-06-2026-start
@click.option("--rlc-mode", "rlc_mode", type=click.Choice(["none", "um", "am"]), default="none", help="Enable PDCP + RLC (Step 18.F): PDCP sequence numbers and headers with in-order delivery; RLC segmentation headers (+ MAC subheaders) on every piece of a transport block. um: a lost piece drops its packet. am: lost pieces are retransmitted after --rlc-am-status-delay-ms, packet dropped after --rlc-am-max-retx rounds. Prints an L2 stdout block. Default none = no L2, byte-identical to earlier runs. NR-U only, needs --nru-cot-model slots.")
@click.option("--pdcp-sn-bits", "pdcp_sn_bits", type=click.Choice(["12", "18"]), default=None, help="PDCP (and RLC AM) sequence number length (default 12: 2-byte headers; 18: 3-byte). Requires --rlc-mode um or am.")
@click.option("--rlc-am-max-retx", "rlc_am_max_retx", type=int, default=None, help="RLC AM retransmission rounds before a packet is dropped (default 4). Requires --rlc-mode am.")
@click.option("--rlc-am-status-delay-ms", "rlc_am_status_delay_ms", type=float, default=None, help="Time from a lost transport block to its RLC AM retransmission (STATUS report delay, default 10 ms). Requires --rlc-mode am.")
# Rashed-Step 18.F-10-06-2026-end
# Rashed-Step 19.A-10-07-2026-start
@click.option("--rach", "rach", is_flag=True, default=False, help="Run 4-step random access (Step 19.A) before RRC setup: preamble on the next PRACH occasion with power ramping, random access response, contention resolution; colliding UEs retry, and a UE that reaches the preamble limit goes back to IDLE (its attach is abandoned). Prints a RACH stdout block. Default (unset) = RRC starts straight away, byte-identical to earlier runs. NR-U: Msg1 after a channel-idle check, the RAR rides a gNB COT.")
@click.option("--prach-period-ms", "prach_period_ms", type=float, default=None, help="PRACH occasion period (default 10 ms). Requires --rach.")
@click.option("--rach-backoff-ms", "rach_backoff_ms", type=float, default=None, help="Random backoff after a lost contention, uniform in [0, value] (default 0 = no backoff indicator). Requires --rach.")
@click.option("--rar-window-ms", "rar_window_ms", type=float, default=None, help="Random access response window (default 10 ms). Requires --rach.")
# Rashed-Step 19.A-10-07-2026-end
# Rashed-Step 19.B.2-10-07-2026-start
@click.option("--rlm", "rlm", is_flag=True, default=False, help="Radio link monitoring (Step 19.B.2) for RRC UEs: the UE measures its downlink SINR every 10 ms; below -8 dB (200 ms mean) starts T310, back above -6 dB (100 ms mean) stops it; T310 expiring is a radio link failure - the UE stops being scheduled and re-establishes RRC (random access if on, then 3 messages) once its cell is usable again, or drops to IDLE when T311 expires. Prints a Radio Link stdout block. Default (unset) = off, byte-identical to earlier runs.")
@click.option("--t310-ms", "t310_ms", type=float, default=None, help="T310: time out of sync before a radio link failure (default 1000 ms). Requires --rlm.")
@click.option("--t311-ms", "t311_ms", type=float, default=None, help="T311: time to find a usable cell after a radio link failure (default 1000 ms). Requires --rlm.")
# Rashed-Step 19.B.2-10-07-2026-end
# Rashed-Step 19.B.3-10-07-2026-start
@click.option("--rrc-inactive", "rrc_inactive", is_flag=True, default=False, help="RRC_INACTIVE (Step 19.B.3) for RRC UEs: a UE with nothing queued either way for --inactivity-timer-ms is released to INACTIVE (context and PDU session kept, not scheduled); new uplink data resumes it at once, new downlink data at its next paging occasion; resume = random access if on + 3 RRC messages, no Core signaling. Prints an RRC Inactive stdout block. Default (unset) = UEs stay CONNECTED, byte-identical. NR-U: needs --nru-cot-model slots.")
@click.option("--inactivity-timer-ms", "inactivity_timer_ms", type=float, default=None, help="Idle time before release to INACTIVE (default 100 ms). Requires --rrc-inactive.")
@click.option("--paging-cycle-ms", "paging_cycle_ms", type=float, default=None, help="RAN paging cycle for downlink-triggered resume (default 320 ms). Requires --rrc-inactive.")
# Rashed-Step 19.B.3-10-07-2026-end
# Rashed-Step 19.B.4-10-07-2026-start
@click.option("--rrc-reconfig", "rrc_reconfig", is_flag=True, default=False, help="RRC reconfiguration (Step 19.B.4): after the Core accepts a PDU session (and after a re-establishment), the gNB sets up the data radio bearer with RRCReconfiguration - the UE processes it (--rrc-reconfig-ms, default 10 ms, TS 38.331 clause 12) and answers RRCReconfigurationComplete - before the user plane opens. Needs the 5G Core. Default (unset) = no reconfiguration step, byte-identical.")
@click.option("--rrc-reconfig-ms", "rrc_reconfig_ms", type=float, default=None, help="UE processing time for RRCReconfiguration (default 10 ms). Requires --rrc-reconfig.")
# Rashed-Step 19.B.4-10-07-2026-end
# Rashed-Step 19.D.2-10-07-2026-start
@click.option("--core-registration-reject-prob", "core_registration_reject_prob", type=float, default=None, help="Chance a Registration Request is rejected (Step 19.D.2); the UE retries after --core-retry-ms and gives up after 5 attempts. Requires the Core. Default 0.")
@click.option("--core-pdu-reject-prob", "core_pdu_reject_prob", type=float, default=None, help="Chance a PDU Session Establishment Request is rejected; same retry rule. Requires the Core. Default 0.")
@click.option("--core-retry-ms", "core_retry_ms", type=float, default=None, help="Wait before retrying after a reject (default 10000 ms, T3511). Requires the Core.")
@click.option("--core-amf-capacity", "core_amf_capacity", type=int, default=None, help="Registrations the AMF handles at once (default unlimited); each holds a slot for --core-service-ms, the rest queue. Requires the Core.")
@click.option("--core-smf-capacity", "core_smf_capacity", type=int, default=None, help="PDU session procedures the SMF handles at once (default unlimited). Requires the Core.")
@click.option("--core-service-ms", "core_service_ms", type=float, default=None, help="AMF/SMF processing time per procedure, part of its delay (default 10 ms). Requires the Core.")
# Rashed-Step 19.D.2-10-07-2026-end
# Rashed-Step 19.C-10-07-2026-start
@click.option("--qos-flows", "qos_flows", is_flag=True, default=False, help="NR-U slots only (Step 19.C): one data radio bearer per 5QI in each UE's buffers (voice=5QI 1, video=2, best_effort=8, background=9), transport blocks filled in 5QI priority order; packets get their class from --nru-traffic-class-mix (uplink too). Prints an NR-U QoS Flows block. Default (unset) = one buffer per UE, byte-identical.")
# Rashed-Step 19.C-10-07-2026-end
# Rashed-Step 19.B.1-10-07-2026-start
@click.option("--nru-rrc-type1-fallback", "nru_rrc_type1_fallback", type=int, default=None, help="cot_sharing + --nru-rrc-enabled (Step 19.B.1): after this many failed Type 2A checks in a row for one RRC message, the UE sends it after its own Type 1 (Cat-4) LBT instead of waiting for more gNB COTs. Default (unset) = never fall back, byte-identical to earlier runs.")
# Rashed-Step 19.B.1-10-07-2026-end
# Rashed-Step 19.E.2-10-07-2026-start
@click.option("--nr-gnb-number", "nr_gnb_number", type=int, default=0, help="Licensed 5G NR cells in the same run (Step 19.E): same environment and channel as Wi-Fi/NR-U, in their own band (--nr-f-ghz, default 3.5 GHz), same 5G Core (--nru-core-enabled covers every UE). Shared flags apply to them where valid: --error-model; --harq / --rlc-mode with --nr-dl-traffic/--nr-ul-traffic; --rach / --rlm / --rrc-reconfig with --nr-rrc-enabled; --nr-handover. Prints the licensed-NR blocks too. Default 0 = none, byte-identical.")
@click.option("--nr-ues-per-gnb", "nr_ues_per_gnb", type=int, default=4, help="UEs per licensed gNB (default 4).")
@click.option("--nr-ue-radius", "nr_ue_radius", type=float, default=50.0, help="Licensed UEs are placed within this radius (m) of their gNB (default 50).")
@click.option("--nr-colocated", "nr_colocated", is_flag=True, default=False, help="Put licensed gNB i on NR-U gNB i's site (needs --nr-gnb-number <= --gnb-number).")
@click.option("--nr-f-ghz", "nr_f_ghz", type=float, default=3.5, help="Licensed NR carrier (GHz, default 3.5 = its own band; 5.18 puts it on the Wi-Fi/NR-U channel, with no LBT).")
@click.option("--nr-bandwidth-mhz", "nr_bandwidth_mhz", type=float, default=100.0, help="Licensed NR bandwidth (default 100 MHz).")
@click.option("--nr-numerology", "nr_numerology", type=int, default=1, help="Licensed NR numerology mu (default 1).")
@click.option("--nr-tx-power-dbm", "nr_tx_power_dbm", type=float, default=30.0, help="Licensed gNB tx power (default 30 dBm).")
@click.option("--nr-scheduler", "nr_scheduler", type=click.Choice(["round_robin", "proportional_fair"]), default="round_robin", help="Licensed NR scheduler.")
@click.option("--nr-tdd", "nr_tdd", is_flag=True, default=False, help="Licensed NR TDD (DDDU) - needed for licensed uplink.")
@click.option("--nr-ue-uplink-enabled", "nr_ue_uplink_enabled", is_flag=True, default=False, help="Licensed NR uplink (needs --nr-tdd).")
@click.option("--nr-rrc-enabled", "nr_rrc_enabled", is_flag=True, default=False, help="RRC for licensed UEs (needs --nr-ue-uplink-enabled).")
@click.option("--nr-dl-traffic", "nr_dl_traffic", type=click.Choice(["full_buffer", "poisson", "cbr"]), default="full_buffer", help="Licensed downlink traffic per UE (default full buffer).")
@click.option("--nr-dl-arrival-rate-pps", "nr_dl_arrival_rate_pps", type=float, default=None, help="Licensed downlink packets/s per UE (default 100).")
@click.option("--nr-ul-traffic", "nr_ul_traffic", type=click.Choice(["full_buffer", "poisson", "cbr"]), default="full_buffer", help="Licensed uplink traffic per UE (needs --nr-ue-uplink-enabled).")
@click.option("--nr-ul-arrival-rate-pps", "nr_ul_arrival_rate_pps", type=float, default=None, help="Licensed uplink packets/s per UE (default 100).")
# Rashed-Step 19.F-10-07-2026-start
@click.option("--nru-scell", "nru_scell", is_flag=True, default=False, help="NR-U as a secondary cell (Step 19.F, LAA-anchored carrier aggregation): every licensed UE also gets an NR-U SCell on the co-located NR-U gNB - one downlink queue served by both carriers, RRC/Core/uplink on the licensed PCell, SCell active only while the UE is connected to that anchor. Needs --nr-colocated, --nr-dl-traffic poisson/cbr, --nru-cot-model slots and no --nru-ue-uplink-enabled (LAA's uplink is licensed). Prints an 'NR-U SCell (LAA)' block.")
# Rashed-Step 19.F-10-07-2026-end
# Rashed-Step pre_20.A-10-08-2026-start
# Rashed-Step pre_20.D.1-10-08-2026-start
# Rashed-Step pre_20.D.2-10-08-2026-start
@click.option("--nru-ed-threshold-dbm", "nru_ed_threshold_dbm", type=float, default=None, help="NR-U energy-detection threshold for LBT (Step pre_20.D.2). Default (unset) = -72 dBm, byte-identical.")
@click.option("--nru-ed-mode", "nru_ed_mode", type=click.Choice(["ts37213"]), default=None, help="NR-U energy-detection threshold from 3GPP TS 37.213 clause 4.1.5 (Step pre_20.D.2): computed from --nru-tx-power-dbm and --nru-bandwidth-mhz (T_A 10 dB, P_H 23 dBm) - -72 dBm at 23 dBm / 20 MHz, up to -62 dBm at 13 dBm. Overrides --nru-ed-threshold-dbm.")
# Rashed-Step pre_20.D.2-10-08-2026-end
# Rashed-Step pre_20.D.3-10-08-2026-start
@click.option("--nru-wifi-reservation", "nru_wifi_reservation", type=click.Choice(["preamble", "cts_to_self"]), default=None, help="Make NR-U COTs visible to Wi-Fi (Step pre_20.D.3; needs --wifi-preamble-detect). preamble: NR-U transmissions carry an 802.11-decodable preamble, Wi-Fi defers from -82 dBm (no airtime cost, upper bound). cts_to_self: before each COT the gNB sends an 802.11 CTS-to-self (44 us + SIFS) whose NAV covers the COT; needs --nru-cot-model slots. Default (unset) = neither, byte-identical.")
# Rashed-Step pre_20.D.3-10-08-2026-end
# Rashed-Step pre_20.D.4-10-08-2026-start
@click.option("--nru-ref-nack-threshold", "nru_ref_nack_threshold", type=click.FloatRange(0.0, 1.0, min_open=True), default=0.8, help="NR-U contention window grows when at least this share of the reference slot's transport blocks fail (Step pre_20.D.4; TS 37.213 Z). Default 0.8 = 80%%, as before. Slots model.")
@click.option("--nru-adaptive-cot", "nru_adaptive_cot", is_flag=True, default=False, help="NR-U adaptive COT (Step pre_20.D.4): a COT whose reference slot failed halves the next COT's length cap (down to one slot); a good one doubles it back to --mcot. Needs --nru-cot-model slots. Prints an adaptive-COT line in the NR-U Slots block. Default (unset) = full MCOT, byte-identical.")
# Rashed-Step pre_20.D.4-10-08-2026-end
@click.option("--nru-priority-class", "nru_priority_class", type=click.IntRange(1, 4), default=None, help="NR-U channel access priority class (Step pre_20.D.1, 3GPP TS 37.213): sets the defer slots m_p, CW_min/CW_max and MCOT from Table 4.1.1-1 (gNB downlink: p1 1/3/7/2ms, p2 1/7/15/3ms, p3 3/15/63/8ms, p4 7/15/1023/8ms) and Table 4.2.1-1 for UEs' own Type 1 LBT; overrides --nru_cw_min/--nru_cw_max/--mcot. Default (unset) = those flags as given, byte-identical.")
# Rashed-Step pre_20.D.1-10-08-2026-end
# Rashed-Step pre_20.B-10-08-2026-start
@click.option("--wifi-ampdu", "wifi_ampdu", type=int, default=1, help="Wi-Fi A-MPDU aggregation (Step pre_20.B; AP downlink, and since Step 20.B also EDCA per access category within its TXOP limit and STA uplink): up to this many MPDUs per channel access in one PPDU of at most --wifi-max-ppdu-us, each MPDU decoded on its own, Block Ack, failed MPDUs retried. Default 1 = one frame per access, byte-identical. Prints a Wi-Fi A-MPDU block.")
@click.option("--wifi-max-ppdu-us", "wifi_max_ppdu_us", type=float, default=5484.0, help="Longest A-MPDU PPDU (us; default 5484 = 802.11 aPPDUMaxTime).")
# Rashed-Step pre_20.B-10-08-2026-end
# Rashed-Step 20.A-10-08-2026-start
@click.option("--wifi-mac-exchange", "wifi_mac_exchange", is_flag=True, default=False, help="802.11 frame exchange on the air (Step 20.A): the receiver transmits the ACK (or Block Ack) after SIFS, every decoded frame sets a NAV for the rest of its exchange, and a node that heard an undecoded frame defers EIFS (94 us) instead of DIFS. Prints a Wi-Fi MAC block. Default (unset) = the ACK time is only waited out, byte-identical.")
@click.option("--wifi-rts-threshold", "wifi_rts_threshold", type=click.IntRange(0, None), default=None, help="RTS/CTS before any Wi-Fi data frame (or A-MPDU) whose payload exceeds this many bytes (Step 20.A; 0 = always). Needs --wifi-mac-exchange. Default (unset) = never.")
# Rashed-Step 20.A-10-08-2026-end
# Rashed-Step 20.B-10-08-2026-start
@click.option("--wifi-sta-traffic-model", "wifi_sta_traffic_model", type=click.Choice(["saturated", "poisson", "cbr"]), default="saturated", help="Wi-Fi STA uplink traffic (Step 20.B; with --wifi-sta-uplink-enabled): saturated (default, as before) or poisson/cbr arrivals into a per-STA queue at --wifi-sta-arrival-rate-pps.")
@click.option("--wifi-sta-arrival-rate-pps", "wifi_sta_arrival_rate_pps", type=float, default=100.0, help="Per-STA uplink arrival rate (packets/s) for --wifi-sta-traffic-model poisson/cbr (Step 20.B).")
# Rashed-Step 20.B-10-08-2026-end
@click.option("--wifi-preamble-detect", "wifi_preamble_detect", is_flag=True, default=False, help="802.11 preamble detection (Step pre_20.A): Wi-Fi defers to Wi-Fi frames from -82 dBm and to other signals (NR-U, licensed NR) from its -62 dBm energy-detection threshold - the asymmetry behind LAA coexistence. Default (unset) = one -62 dBm rule for everything, byte-identical.")
@click.option("--fairness-report", "fairness_report", is_flag=True, default=False, help="Print a Coexistence Fairness block (Step pre_20.A): per technology the share of airtime it occupied (failed transmissions included), transmissions and their failure ratio, throughput and latency, and Jain's index over the airtime shares. Default (unset) = not printed.")
# Rashed-Step pre_20.A-10-08-2026-end
@click.option("--nr-handover", "nr_handover", is_flag=True, default=False, help="A3 handover between the licensed cells (needs --nr-rrc-enabled).")
# Rashed-Step 19.E.2-10-07-2026-end
@click.option("--nru-buffer-limit-bytes", "nru_buffer_limit_bytes", type=int, default=None, help="slots only: drop-tail limit of each per-UE downlink buffer (default unbounded).")
# Rashed-Step 18.C-10-06-2026-end

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
        # Rashed-Step 18.A-10-06-2026-start
        error_model: str = "threshold",
        bler_slope_db: float = None,
        # Rashed-Step 18.C-10-06-2026-start
        nru_cot_model: str = "burst",
        nru_numerology: int = None,
        nru_buffer_limit_bytes: int = None,
        # Rashed-Step 18.D-10-06-2026-start
        nru_ul_traffic_model: str = "saturated",
        nru_ul_arrival_rate_pps: float = None,
        # Rashed-Step 18.E-10-06-2026-start
        harq: bool = False,
        harq_max_tx: int = None,
        harq_rtt_slots: int = None,
        # Rashed-Step 18.F-10-06-2026-start
        rlc_mode: str = "none",
        pdcp_sn_bits: str = None,
        rlc_am_max_retx: int = None,
        rlc_am_status_delay_ms: float = None,
        # Rashed-Step 19.A-10-07-2026-start
        rach: bool = False,
        prach_period_ms: float = None,
        rach_backoff_ms: float = None,
        rar_window_ms: float = None,
        # Rashed-Step 19.B.1-10-07-2026-start
        nru_rrc_type1_fallback: int = None,
        # Rashed-Step 19.B.2-10-07-2026-start
        rlm: bool = False,
        t310_ms: float = None,
        t311_ms: float = None,
        # Rashed-Step 19.B.3-10-07-2026-start
        rrc_inactive: bool = False,
        inactivity_timer_ms: float = None,
        paging_cycle_ms: float = None,
        # Rashed-Step 19.B.4-10-07-2026-start
        rrc_reconfig: bool = False,
        rrc_reconfig_ms: float = None,
        # Rashed-Step 19.C-10-07-2026-start
        qos_flows: bool = False,
        # Rashed-Step 19.E.2-10-07-2026-start
        nr_gnb_number: int = 0, nr_ues_per_gnb: int = 4, nr_ue_radius: float = 50.0,
        nr_colocated: bool = False, nr_f_ghz: float = 3.5, nr_bandwidth_mhz: float = 100.0,
        nr_numerology: int = 1, nr_tx_power_dbm: float = 30.0, nr_scheduler: str = "round_robin",
        nr_tdd: bool = False, nr_ue_uplink_enabled: bool = False, nr_rrc_enabled: bool = False,
        nr_dl_traffic: str = "full_buffer", nr_dl_arrival_rate_pps: float = None,
        nr_ul_traffic: str = "full_buffer", nr_ul_arrival_rate_pps: float = None,
        nr_handover: bool = False,
        # Rashed-Step 19.F-10-07-2026-start
        nru_scell: bool = False,
        # Rashed-Step pre_20.A-10-08-2026-start
        fairness_report: bool = False,
        wifi_preamble_detect: bool = False,  # pre_20.A
        wifi_ampdu: int = 1, wifi_max_ppdu_us: float = 5484.0,  # pre_20.B
        nru_priority_class: Optional[int] = None,  # pre_20.D.1
        nru_ed_threshold_dbm: Optional[float] = None, nru_ed_mode: Optional[str] = None,  # pre_20.D.2
        nru_wifi_reservation: Optional[str] = None,  # pre_20.D.3
        nru_ref_nack_threshold: float = 0.8, nru_adaptive_cot: bool = False,  # pre_20.D.4
        wifi_mac_exchange: bool = False, wifi_rts_threshold: Optional[int] = None,  # 20.A
        wifi_sta_traffic_model: str = "saturated", wifi_sta_arrival_rate_pps: float = 100.0,  # 20.B
        # Rashed-Step pre_20.A-10-08-2026-end
        # Rashed-Step 19.F-10-07-2026-end
        # Rashed-Step 19.E.2-10-07-2026-end
        # Rashed-Step 19.D.2-10-07-2026-start
        core_registration_reject_prob: float = None,
        core_pdu_reject_prob: float = None,
        core_retry_ms: float = None,
        core_amf_capacity: int = None,
        core_smf_capacity: int = None,
        core_service_ms: float = None,
        # Rashed-Step 19.D.2-10-07-2026-end
        # Rashed-Step 19.C-10-07-2026-end
        # Rashed-Step 19.B.4-10-07-2026-end
        # Rashed-Step 19.B.3-10-07-2026-end
        # Rashed-Step 19.B.2-10-07-2026-end
        # Rashed-Step 19.B.1-10-07-2026-end
        # Rashed-Step 19.A-10-07-2026-end
        # Rashed-Step 18.F-10-06-2026-end
        # Rashed-Step 18.E-10-06-2026-end
        # Rashed-Step 18.D-10-06-2026-end
        # Rashed-Step 18.C-10-06-2026-end
        # Rashed-Step 18.A-10-06-2026-end
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
    # Rashed-Step 20.B-10-08-2026-start
    # --wifi-edca with poisson/cbr traffic is supported since Step 20.B
    # (per-AC queues); it used to be rejected here.
    if wifi_sta_traffic_model != "saturated" and not wifi_sta_uplink_enabled:
        raise click.BadParameter("--wifi-sta-traffic-model needs --wifi-sta-uplink-enabled.")
    # Rashed-Step 20.B-10-08-2026-end
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
        core_config = core_config_from_cli(
            nru_core_enabled, core_registration_delay_us, core_pdu_session_delay_us,
            registration_reject_prob=core_registration_reject_prob, pdu_reject_prob=core_pdu_reject_prob,
            retry_us=None if core_retry_ms is None else core_retry_ms * 1000.0,
            amf_capacity=core_amf_capacity, smf_capacity=core_smf_capacity,
            service_us=None if core_service_ms is None else core_service_ms * 1000.0)  # 19.D.2
    except ValueError as e:
        raise click.BadParameter(str(e))
    # Rashed-Step pre_17.B-10-04-2026-start
    # Rashed-Step 17.G-10-04-2026-start
    if not (0.0 < nru_ul_cot_fraction < 1.0):
        raise click.BadParameter(
            f"--nru-ul-cot-fraction must be strictly between 0 and 1 (got {nru_ul_cot_fraction})."
        )
    # Rashed-Step 17.G-10-04-2026-end
    # Rashed-Step 18.A-10-06-2026-start
    try:
        error_model_config = error_model_config_from_cli(error_model, bler_slope_db)
    except ValueError as e:
        raise click.BadParameter(str(e))
    # Rashed-Step 18.A-10-06-2026-end
    # Rashed-Step 18.C-10-06-2026-start
    if nru_cot_model != "slots" and (nru_numerology is not None or nru_buffer_limit_bytes is not None):
        raise click.BadParameter("--nru-numerology / --nru-buffer-limit-bytes require --nru-cot-model slots.")
    # Rashed-Step pre_20.D.3-10-08-2026-start
    if nru_wifi_reservation is not None and not wifi_preamble_detect:
        raise click.BadParameter("--nru-wifi-reservation needs --wifi-preamble-detect (Wi-Fi only decodes the preamble / CTS with it).")
    # Rashed-Step pre_20.D.4-10-08-2026-start
    # Rashed-Step 20.A-10-08-2026-start
    if wifi_rts_threshold is not None and not wifi_mac_exchange:
        raise click.BadParameter("--wifi-rts-threshold needs --wifi-mac-exchange.")
    # Rashed-Step 20.A-10-08-2026-end
    if nru_adaptive_cot and nru_cot_model != "slots":
        raise click.BadParameter("--nru-adaptive-cot needs --nru-cot-model slots.")
    # Rashed-Step pre_20.D.4-10-08-2026-end
    if nru_wifi_reservation == "cts_to_self" and nru_cot_model != "slots":
        raise click.BadParameter("--nru-wifi-reservation cts_to_self needs --nru-cot-model slots.")
    # Rashed-Step pre_20.D.3-10-08-2026-end
    # Rashed-Step 18.D-10-06-2026-start
    if nru_ul_traffic_model != "saturated" and nru_cot_model != "slots":
        raise click.BadParameter("--nru-ul-traffic-model poisson/cbr requires --nru-cot-model slots.")
    if nru_ul_traffic_model != "saturated" and not nru_ue_uplink_enabled:
        raise click.BadParameter("--nru-ul-traffic-model poisson/cbr requires --nru-ue-uplink-enabled.")
    if nru_ul_arrival_rate_pps is not None and nru_ul_traffic_model == "saturated":
        raise click.BadParameter("--nru-ul-arrival-rate-pps requires --nru-ul-traffic-model poisson or cbr.")
    if nru_ul_arrival_rate_pps is not None and nru_ul_arrival_rate_pps <= 0:
        raise click.BadParameter(f"--nru-ul-arrival-rate-pps must be > 0 (got {nru_ul_arrival_rate_pps}).")
    nru_ul_traffic = None
    if nru_ul_traffic_model != "saturated":
        nru_ul_traffic = TrafficConfig(mode=nru_ul_traffic_model,
                                       arrival_rate_pps=100.0 if nru_ul_arrival_rate_pps is None else nru_ul_arrival_rate_pps)
    # Rashed-Step 18.D-10-06-2026-end
    # Rashed-Step 19.E.2-10-07-2026-start
    # Licensed cells (19.E): checked first, because the shared flags
    # below may be valid for them even when NR-U doesn't qualify.
    from ran.protocol.buffer import traffic_configs_from_cli
    nr_on = nr_gnb_number > 0
    nr_flags = (nr_colocated or nr_tdd or nr_ue_uplink_enabled or nr_rrc_enabled or nr_handover
                or nr_dl_traffic != "full_buffer" or nr_ul_traffic != "full_buffer")
    if nr_gnb_number < 0:
        raise click.BadParameter("--nr-gnb-number must be >= 0.")
    if nr_flags and not nr_on:
        raise click.BadParameter("--nr-* options need --nr-gnb-number >= 1.")
    if nr_colocated and nr_gnb_number > gnb_number:
        raise click.BadParameter("--nr-colocated needs --nr-gnb-number <= --gnb-number.")
    if nr_ue_uplink_enabled and not nr_tdd:
        raise click.BadParameter("--nr-ue-uplink-enabled needs --nr-tdd.")
    if nr_rrc_enabled and not nr_ue_uplink_enabled:
        raise click.BadParameter("--nr-rrc-enabled needs --nr-ue-uplink-enabled.")
    if nr_handover and not nr_rrc_enabled:
        raise click.BadParameter("--nr-handover needs --nr-rrc-enabled.")
    try:
        nr_dl_cfg, nr_ul_cfg = traffic_configs_from_cli(nr_dl_traffic, nr_dl_arrival_rate_pps, nr_ul_traffic,
                                                        nr_ul_arrival_rate_pps, None, None, nr_ue_uplink_enabled)
    except ValueError as e:
        raise click.BadParameter(str(e).replace("--dl-", "--nr-dl-").replace("--ul-", "--nr-ul-"))
    nr_buffered = nr_on and (nr_dl_cfg is not None or nr_ul_cfg is not None)
    nr_rrc = nr_on and nr_rrc_enabled
    nru_slots = nru_cot_model == "slots"
    # Rashed-Step 19.F-10-07-2026-start
    if nru_scell:
        if not (nr_on and nr_colocated):
            raise click.BadParameter("--nru-scell needs co-located licensed cells (--nr-gnb-number, --nr-colocated).")
        if nr_dl_cfg is None:
            raise click.BadParameter("--nru-scell needs --nr-dl-traffic poisson or cbr (the shared downlink queue).")
        if not nru_slots:
            raise click.BadParameter("--nru-scell needs --nru-cot-model slots.")
        if nru_ue_uplink_enabled:
            raise click.BadParameter("--nru-scell: LAA's uplink is on the licensed PCell - drop --nru-ue-uplink-enabled.")
    # Rashed-Step 19.F-10-07-2026-end
    # Rashed-Step 19.E.2-10-07-2026-end
    # Rashed-Step 18.E-10-06-2026-start
    try:
        harq_config = harq_config_from_cli(harq, harq_max_tx, harq_rtt_slots)
    except ValueError as e:
        raise click.BadParameter(str(e))
    # Rashed-Step 18.E-10-06-2026-end
    # Rashed-Step 18.E-10-06-2026-start
    if harq_config is not None and not nru_slots and not nr_buffered:  # 19.E: or licensed buffered
        raise click.BadParameter("--harq needs --nru-cot-model slots (the burst model has no transport blocks) "
                                 "or licensed cells with --nr-dl-traffic / --nr-ul-traffic.")
    # Rashed-Step 18.F-10-06-2026-start
    try:
        l2_config = l2_config_from_cli(rlc_mode, None if pdcp_sn_bits is None else int(pdcp_sn_bits),
                                       rlc_am_max_retx, rlc_am_status_delay_ms)
    except ValueError as e:
        raise click.BadParameter(str(e))
    # Rashed-Step 18.F-10-06-2026-end
    # Rashed-Step 18.F-10-06-2026-start
    if l2_config is not None and not nru_slots and not nr_buffered:  # 19.E: or licensed buffered
        raise click.BadParameter("--rlc-mode needs --nru-cot-model slots (the burst model has no transport blocks).")
    # Rashed-Step 19.A-10-07-2026-start
    try:
        rach_config = rach_config_from_cli(rach, prach_period_ms, rach_backoff_ms, rar_window_ms)
    except ValueError as e:
        raise click.BadParameter(str(e))
    if rach_config is not None and not nru_rrc_enabled and not nr_rrc:  # 19.E: or licensed RRC
        raise click.BadParameter("--rach requires --nru-rrc-enabled (random access starts the RRC attach).")
    # Rashed-Step 19.B.2-10-07-2026-start
    try:
        rlm_config = rlm_config_from_cli(rlm, t310_ms, t311_ms)
    except ValueError as e:
        raise click.BadParameter(str(e))
    if rlm_config is not None and not nru_rrc_enabled and not nr_rrc:  # 19.E: or licensed RRC
        raise click.BadParameter("--rlm requires --nru-rrc-enabled.")
    # Rashed-Step 19.B.3-10-07-2026-start
    try:
        inactive_config = inactive_config_from_cli(rrc_inactive, inactivity_timer_ms, paging_cycle_ms)
    except ValueError as e:
        raise click.BadParameter(str(e))
    if inactive_config is not None and not (nru_rrc_enabled and nru_slots) and not (nr_rrc and nr_buffered):  # 19.E
        raise click.BadParameter("--rrc-inactive needs --nru-rrc-enabled and --nru-cot-model slots.")
    # Rashed-Step 19.B.4-10-07-2026-start
    if rrc_reconfig_ms is not None and not rrc_reconfig:
        raise click.BadParameter("--rrc-reconfig-ms requires --rrc-reconfig.")
    if rrc_reconfig_ms is not None and rrc_reconfig_ms < 0:
        raise click.BadParameter(f"--rrc-reconfig-ms must be >= 0 (got {rrc_reconfig_ms}).")
    if rrc_reconfig and not nru_core_enabled:
        raise click.BadParameter("--rrc-reconfig needs --nru-core-enabled (the bearer belongs to a PDU session).")
    rrc_reconfig_us = None if not rrc_reconfig else (10_000.0 if rrc_reconfig_ms is None else rrc_reconfig_ms * 1000.0)
    # Rashed-Step 19.C-10-07-2026-start
    if qos_flows and nru_cot_model != "slots":
        raise click.BadParameter("--qos-flows needs --nru-cot-model slots.")
    # Rashed-Step 19.C-10-07-2026-end
    # Rashed-Step 19.B.4-10-07-2026-end
    # Rashed-Step 19.B.3-10-07-2026-end
    # Rashed-Step 19.B.2-10-07-2026-end
    # Rashed-Step 19.B.1-10-07-2026-start
    if nru_rrc_type1_fallback is not None:
        if not nru_rrc_enabled or nru_ul_access_mode != "cot_sharing":
            raise click.BadParameter("--nru-rrc-type1-fallback needs --nru-rrc-enabled with --nru-ul-access-mode cot_sharing.")
        if nru_rrc_type1_fallback < 1:
            raise click.BadParameter(f"--nru-rrc-type1-fallback must be >= 1 (got {nru_rrc_type1_fallback}).")
    # Rashed-Step 19.B.1-10-07-2026-end
    # Rashed-Step 19.A-10-07-2026-end
    # Rashed-Step 18.F-10-06-2026-end
    # Rashed-Step 18.E-10-06-2026-end
    if nru_buffer_limit_bytes is not None and nru_buffer_limit_bytes <= 0:
        raise click.BadParameter(f"--nru-buffer-limit-bytes must be > 0 (got {nru_buffer_limit_bytes}).")
    # Rashed-Step 18.C-10-06-2026-end
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

    # Rashed-Step 19.E.2-10-07-2026-start
    nr_config = None
    if nr_on:
        from ran.protocol.handover import HandoverConfig
        nr_config = Config_NRL(
            numerology=nr_numerology, bandwidth_mhz=nr_bandwidth_mhz, scheduler=nr_scheduler,
            tx_power_dbm=nr_tx_power_dbm, f_ghz=nr_f_ghz * 1e9, tdd_enabled=nr_tdd,
            dl_traffic=nr_dl_cfg, ul_traffic=nr_ul_cfg,
            harq=harq_config if nr_buffered else None,
            l2=l2_config if nr_buffered else None,
            rach=rach_config if nr_rrc else None,
            rlm=rlm_config if nr_rrc else None,
            inactive=inactive_config if (nr_rrc and nr_buffered) else None,
            rrc_reconfig_us=rrc_reconfig_us if nr_rrc else None,
            handover=HandoverConfig() if nr_handover else None,
        )
    # Rashed-Step 19.E.2-10-07-2026-end
    for i in range(0, runs):
        curr_seed = seed + i
        print("before simulation")
        run_simulation(ap_number, gnb_number, curr_seed, simulation_time,
                       # Rashed-Step 5.C-02-06-2026-start
                       Config(1472, wifi_cw_min, wifi_cw_max, wifi_r_limit, mcs_value,
                              bandwidth_mhz=wifi_bandwidth_mhz, noise_figure_db=wifi_noise_figure_db,
                              preamble_detect_dbm=-82.0 if wifi_preamble_detect else None,  # pre_20.A
                              ampdu_max_mpdus=wifi_ampdu, ampdu_max_ppdu_us=wifi_max_ppdu_us,  # pre_20.B
                              mac_exchange=wifi_mac_exchange, rts_threshold_bytes=wifi_rts_threshold,  # 20.A
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
                                 # Rashed-Step 18.C-10-06-2026-start
                                 cot_model=nru_cot_model,
                                 priority_class=nru_priority_class,  # pre_20.D.1
                                 ed_threshold_mode=nru_ed_mode,  # pre_20.D.2
                                 wifi_reservation=nru_wifi_reservation,  # pre_20.D.3
                                 ref_slot_nack_threshold=nru_ref_nack_threshold, adaptive_cot=nru_adaptive_cot,  # pre_20.D.4
                                 **({} if nru_ed_threshold_dbm is None else {"ed_threshold_dbm": nru_ed_threshold_dbm}),
                                 numerology=1 if nru_numerology is None else nru_numerology,
                                 buffer_limit_bytes=nru_buffer_limit_bytes,
                                 # Rashed-Step 18.D-10-06-2026-start
                                 ul_traffic=nru_ul_traffic,
                                 # Rashed-Step 18.E-10-06-2026-start
                                 harq=harq_config if nru_slots else None,  # 19.E: may be for licensed only
                                 # Rashed-Step 18.F-10-06-2026-start
                                 l2=l2_config if nru_slots else None,  # 19.E
                                 # Rashed-Step 19.A-10-07-2026-start
                                 rach=rach_config,
                                 # Rashed-Step 19.B.1-10-07-2026-start
                                 rrc_type1_fallback_after=nru_rrc_type1_fallback,
                                 # Rashed-Step 19.B.2-10-07-2026-start
                                 rlm=rlm_config,
                                 # Rashed-Step 19.B.3-10-07-2026-start
                                 inactive=inactive_config if nru_slots else None,  # 19.E
                                 # Rashed-Step 19.B.4-10-07-2026-start
                                 rrc_reconfig_us=rrc_reconfig_us,
                                 # Rashed-Step 19.C-10-07-2026-start
                                 qos_flows=qos_flows,
                                 # Rashed-Step 19.F-10-07-2026-start
                                 deployment_mode=NruDeploymentMode.LAA_ANCHORED if nru_scell
                                 else NruDeploymentMode.STANDALONE_MULTIFIRE,
                                 # Rashed-Step 19.F-10-07-2026-end
                                 # Rashed-Step 19.C-10-07-2026-end
                                 # Rashed-Step 19.B.4-10-07-2026-end
                                 # Rashed-Step 19.B.3-10-07-2026-end
                                 # Rashed-Step 19.B.2-10-07-2026-end
                                 # Rashed-Step 19.B.1-10-07-2026-end
                                 # Rashed-Step 19.A-10-07-2026-end
                                 # Rashed-Step 18.F-10-06-2026-end
                                 # Rashed-Step 18.E-10-06-2026-end
                                 # Rashed-Step 18.D-10-06-2026-end
                                 # Rashed-Step 18.C-10-06-2026-end
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
                       wifi_sta_traffic_config=(None if wifi_sta_traffic_model == "saturated" else
                           TrafficConfig(mode=wifi_sta_traffic_model, arrival_rate_pps=wifi_sta_arrival_rate_pps,
                                         packet_size_bytes=wifi_packet_size_bytes)),  # 20.B
                       # Rashed-Step pre_17.B-10-04-2026-end
                       # Rashed-Step 18.A-10-06-2026-start
                       error_model_config=error_model_config,
                       # Rashed-Step 18.A-10-06-2026-end
                       # Rashed-Step 19.E.2-10-07-2026-start
                       nr_gnb_number=nr_gnb_number, nr_config=nr_config, nr_licensed_ues_per_gnb=nr_ues_per_gnb,
                       nr_ue_radius=nr_ue_radius, nr_colocated=nr_colocated,
                       nr_ue_uplink_enabled=nr_ue_uplink_enabled, nr_rrc_enabled=nr_rrc_enabled,
                       nru_scell=nru_scell,  # 19.F
                       fairness_report=fairness_report,  # pre_20.A
                       # Rashed-Step 19.E.2-10-07-2026-end
                       # Rashed-Step 16.F-10-02-2026-end
                       )





if __name__ == "__main__":
    single_run()