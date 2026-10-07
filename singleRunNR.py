# Rashed-Step 6.B-07-31-2026-start
# Standalone CLI for the licensed 5G NR scenario (simulation_nr.py) -
# separate from singleRun.py (WiFi/NR-U coexistence) per the confirmed
# "standalone first" scope for Step 6.B. Run e.g.:
#   python singleRunNR.py --gnb-number 2 --ues-per-gnb 6 -t 1 --scheduler proportional_fair

import click

from simulation_nr import run_simulation_licensed_nr, parse_pos_list_nr
from nr.nr import Config_NRL
# Rashed-Step 16.F-10-02-2026-start
from core.network import core_config_from_cli
# Rashed-Step 18.A-10-06-2026-start
from common.error_model import error_model_config_from_cli
# Rashed-Step 18.B-10-06-2026-start
from ran.protocol.buffer import traffic_configs_from_cli
# Rashed-Step 18.E-10-06-2026-start
from ran.protocol.harq import harq_config_from_cli
# Rashed-Step 18.F-10-06-2026-start
from ran.protocol.l2 import l2_config_from_cli
# Rashed-Step 19.A-10-07-2026-start
from ran.protocol.rach import rach_config_from_cli
# Rashed-Step 19.A-10-07-2026-end
# Rashed-Step 18.F-10-06-2026-end
# Rashed-Step 18.E-10-06-2026-end
# Rashed-Step 18.B-10-06-2026-end
# Rashed-Step 18.A-10-06-2026-end
# Rashed-Step 16.F-10-02-2026-end


@click.command()
@click.option("-r", "--runs", "runs", default=1, help="Number of simulation runs")
@click.option("--seed", "seed", default=1, help="Seed for simulation")
@click.option("--gnb-number", "gnb_number", type=int, required=True, help="Number of licensed-NR gNBs")
@click.option("--ues-per-gnb", "ues_per_gnb", type=int, default=4, help="Number of UEs associated to each gNB")
@click.option("-t", "--simulation-time", "simulation_time", default=1.0, help="Duration of the simulation in s")
@click.option("--area-w", "area_w", type=float, default=200.0, help="Deployment area width (m)")
@click.option("--area-h", "area_h", type=float, default=200.0, help="Deployment area height (m)")
@click.option("--gnb-pos", "gnb_pos", type=str, multiple=True, help="Explicit gNB position 'x,y' (repeatable)")
@click.option("--ue-radius", "ue_radius", type=float, default=200.0, help="Radius (m) around its gNB within which a UE is randomly placed")
@click.option("--numerology", "numerology", type=int, default=1, help="NR numerology index mu (0=15kHz SCS, 1=30kHz, 2=60kHz, 3=120kHz)")
@click.option("--bandwidth-mhz", "bandwidth_mhz", type=float, default=100.0, help="Channel bandwidth (MHz), drives resource-block count")
@click.option("--scheduler", "scheduler", type=click.Choice(["round_robin", "proportional_fair"]), default="round_robin", help="Per-slot RB scheduler")
@click.option("--tx-power-dbm", "tx_power_dbm", type=float, default=30.0, help="gNB downlink tx power (dBm EIRP)")
@click.option("--f-ghz", "f_ghz", type=float, default=3.5, help="Carrier frequency (GHz) - default 3.5 GHz matches 3GPP band n78")
@click.option("--noise-figure-db", "noise_figure_db", type=float, default=7.0, help="UE receiver noise figure (dB)")
@click.option("--gnb-mobility-speed-mps", "gnb_mobility_speed_mps", type=float, default=0.0, help="gNB roaming speed (m/s), 0=static")
@click.option("--ue-mobility-speed-mps", "ue_mobility_speed_mps", type=float, default=0.0, help="UE walking speed (m/s), 0=static")
@click.option("--mobility-pause-s", "mobility_pause_s", type=float, default=0.0, help="Dwell time (s) at each waypoint if mobility is enabled")
# Rashed-Step 13.E.3-08-23-2026-start
@click.option("--export-packets-csv", "export_packets_csv_path", type=str, default=None, help="Path to write a packet-level CSV of every licensed-NR slot allocation (technology-agnostic format, same as singleRun.py's --export-packets-csv) - includes each packet's measured_sinr_db (Step 13.E.3). Default (unset) = no CSV, byte-identical to every pre-13.E.3 run.")
@click.option("--rate-adapt", "rate_adapt", is_flag=True, default=False, help="Enable AHEAD-OF-TIME rate adaptation (Step 13.E.3): MCS is chosen from the UE's last-measured SINR BEFORE this slot's real SINR is known, instead of the default oracle/post-hoc pick (which already has perfect real-time channel knowledge and can only fail below MCS0). A wrong ahead-of-time guess is a genuine failure (DROPPED) here. Default (unset/False) = the pre-13.E.3 oracle behavior, byte-identical to every earlier run.")
@click.option("--rate-adapt-ml-model", "rate_adapt_ml_model", type=str, default=None, help="Path to a trained SINR-prediction model (ml/train_sinr_model.py's saved output). When set, --rate-adapt's ahead-of-time pick uses the model's PREDICTED next SINR instead of the raw last-measured value, once a UE's link has enough history. Requires --rate-adapt also set.")
# Rashed-Step 13.E.3-08-23-2026-end
# Rashed-Step 15.G-09-18-2026-start
@click.option("--tdd-enabled", "tdd_enabled", is_flag=True, default=False, help="Enable licensed-NR TDD uplink scheduling (Step 15.E): run_one_slot() cycles --tdd-pattern instead of every slot being DL. Default (unset/False) = every slot stays DL, byte-identical to every pre-15.E run. Only useful combined with --ue-uplink-enabled (a 'U' slot with no uplink-capable UE simply does nothing that slot, by design).")
@click.option("--tdd-pattern", "tdd_pattern", type=str, default="DDDU", help="TDD D/U slot pattern, cycled per slot index. Only read when --tdd-enabled is set. Default 'DDDU' matches Config_NRL.tdd_pattern's own class default.")
@click.option("--ue-uplink-enabled", "ue_uplink_enabled", is_flag=True, default=False, help="Enable real licensed-NR uplink (Step 15.E): every UE gets a one-time SchedulingRequest timer, then becomes a standing grant-based UL candidate on 'U' slots (see nr/ue.py's NrUeLicensed class docstring). Default (unset/False) = every UE stays passive (no uplink at all), byte-identical to every pre-15.E run.")
@click.option("--rrc-enabled", "rrc_enabled", is_flag=True, default=False, help="Enable the generic RRC attach state machine (Step 15.F) for every UE: IDLE -> CONNECTING -> CONNECTED, via a real RRCSetupRequest/RRCSetup/RRCSetupComplete exchange whose uplink messages each wait a fixed RRC grant delay (Config_NRL.rrc_ul_grant_delay_us, 1000us by default since Step 16.A; deterministic timing, unlike NR-U's LBT-contention-driven version). Requires --ue-uplink-enabled too (fails fast otherwise). Once set, the gNB's own DL/UL scheduling (Step 15.G) is gated on rrc_state==CONNECTED - see Project details/Step pre_15.txt's STEP 15 - 15.G DONE section. Default (unset/False) = every UE has no rrc_state at all, byte-identical to every pre-15.F run.")
# Rashed-Step 15.G-09-18-2026-end
# Rashed-Step 16.F-10-02-2026-start
@click.option("--core-enabled", "core_enabled", is_flag=True, default=False, help="Enable the minimal 5G Core (Step 16): every UE registers with the AMF and establishes a PDU session (SMF/UPF) after RRC connects (or from t=0 without --rrc-enabled), and the gNB carries no data for a UE until its session is ACTIVE. Prints a '5G Core' stdout block. Default (unset/False) = no Core, byte-identical to every pre-16.F run.")
@click.option("--core-registration-delay-us", "core_registration_delay_us", type=float, default=None, help="Registration Request -> Accept time in us (default 90000, measured Open5GS testbed - see core/network.py). Requires --core-enabled.")
@click.option("--core-pdu-session-delay-us", "core_pdu_session_delay_us", type=float, default=None, help="PDU Session Establishment Request -> Accept time in us (default 125000, measured Open5GS testbed). Requires --core-enabled.")
# Rashed-Step 16.F-10-02-2026-end
# Rashed-Step 18.A-10-06-2026-start
@click.option("--error-model", "error_model", type=click.Choice(["threshold", "bler"]), default="threshold", help="Link error model for every technology in the run (Step 18.A). threshold (default): a frame/transport block decodes iff its SINR meets its MCS threshold, byte-identical to every earlier run. bler: a random draw against a block-error-rate curve that hits 10% at the MCS threshold (the 3GPP CQI definition) - needed for HARQ. Prints an 'Error Model' stdout block.")
@click.option("--bler-slope-db", "bler_slope_db", type=float, default=None, help="bler only: steepness of the BLER curve in 1/dB (default 2.0: 90% -> 10% BLER over ~2.2 dB). Requires --error-model bler.")
# Rashed-Step 18.A-10-06-2026-end
# Rashed-Step 18.B-10-06-2026-start
@click.option("--dl-traffic", "dl_traffic", type=click.Choice(["full_buffer", "poisson", "cbr"]), default="full_buffer", help="Downlink traffic per UE (Step 18.B). full_buffer (default): every scheduled UE always has data, byte-identical to every earlier run. poisson / cbr: packets arrive at --dl-arrival-rate-pps into a per-UE buffer at the gNB; only UEs with queued data are scheduled and a slot delivers what is queued. Prints a 'Licensed 5G NR DL Traffic' stdout block.")
@click.option("--dl-arrival-rate-pps", "dl_arrival_rate_pps", type=float, default=None, help="Downlink packets per second per UE (default 100). Requires --dl-traffic poisson or cbr.")
@click.option("--ul-traffic", "ul_traffic", type=click.Choice(["full_buffer", "poisson", "cbr"]), default="full_buffer", help="Uplink traffic per UE (Step 18.B). full_buffer (default): every scheduled UE always has data, byte-identical to every earlier run. poisson / cbr: packets arrive at --ul-arrival-rate-pps into a per-UE buffer at each UE; only UEs with queued data are scheduled and a slot delivers what is queued. Prints a 'Licensed 5G NR UL Traffic' stdout block. Requires --ue-uplink-enabled.")
@click.option("--ul-arrival-rate-pps", "ul_arrival_rate_pps", type=float, default=None, help="Uplink packets per second per UE (default 100). Requires --ul-traffic poisson or cbr.")
@click.option("--packet-size-bytes", "packet_size_bytes", type=int, default=None, help="Packet size for buffered traffic (default 1500). Requires --dl-traffic or --ul-traffic poisson/cbr.")
@click.option("--buffer-limit-bytes", "buffer_limit_bytes", type=int, default=None, help="Drop-tail limit of each per-UE buffer (default unbounded). Requires --dl-traffic or --ul-traffic poisson/cbr.")
# Rashed-Step 18.B-10-06-2026-end
# Rashed-Step 18.E-10-06-2026-start
@click.option("--harq", "harq", is_flag=True, default=False, help="Enable HARQ (Step 18.E): a transport block that fails is retransmitted (ahead of new data, after --harq-rtt-slots) and decoded with chase combining; dropped after --harq-max-tx attempts. Prints a HARQ stdout block. Default (unset) = a failed block's packets are dropped, byte-identical to earlier runs. Needs --dl-traffic or --ul-traffic poisson/cbr.")
@click.option("--harq-max-tx", "harq_max_tx", type=int, default=None, help="Transmissions per transport block, first one included (default 4). Requires --harq.")
@click.option("--harq-rtt-slots", "harq_rtt_slots", type=int, default=None, help="Slots from a failed attempt to its earliest retransmission (default 4). Requires --harq.")
# Rashed-Step 18.E-10-06-2026-end
# Rashed-Step 18.F-10-06-2026-start
@click.option("--rlc-mode", "rlc_mode", type=click.Choice(["none", "um", "am"]), default="none", help="Enable PDCP + RLC (Step 18.F): PDCP sequence numbers and headers with in-order delivery; RLC segmentation headers (+ MAC subheaders) on every piece of a transport block. um: a lost piece drops its packet. am: lost pieces are retransmitted after --rlc-am-status-delay-ms, packet dropped after --rlc-am-max-retx rounds. Prints an L2 stdout block. Default none = no L2, byte-identical to earlier runs. Needs --dl-traffic or --ul-traffic poisson/cbr.")
@click.option("--pdcp-sn-bits", "pdcp_sn_bits", type=click.Choice(["12", "18"]), default=None, help="PDCP (and RLC AM) sequence number length (default 12: 2-byte headers; 18: 3-byte). Requires --rlc-mode um or am.")
@click.option("--rlc-am-max-retx", "rlc_am_max_retx", type=int, default=None, help="RLC AM retransmission rounds before a packet is dropped (default 4). Requires --rlc-mode am.")
@click.option("--rlc-am-status-delay-ms", "rlc_am_status_delay_ms", type=float, default=None, help="Time from a lost transport block to its RLC AM retransmission (STATUS report delay, default 10 ms). Requires --rlc-mode am.")
# Rashed-Step 18.F-10-06-2026-end
# Rashed-Step 19.A-10-07-2026-start
@click.option("--rach", "rach", is_flag=True, default=False, help="Run 4-step random access (Step 19.A) before RRC setup: preamble on the next PRACH occasion with power ramping, random access response, contention resolution; colliding UEs retry, and a UE that reaches the preamble limit goes back to IDLE (its attach is abandoned). Prints a RACH stdout block. Default (unset) = RRC starts straight away, byte-identical to earlier runs.")
@click.option("--prach-period-ms", "prach_period_ms", type=float, default=None, help="PRACH occasion period (default 10 ms). Requires --rach.")
@click.option("--rach-backoff-ms", "rach_backoff_ms", type=float, default=None, help="Random backoff after a lost contention, uniform in [0, value] (default 0 = no backoff indicator). Requires --rach.")
@click.option("--rar-window-ms", "rar_window_ms", type=float, default=None, help="Random access response window (default 10 ms). Requires --rach.")
# Rashed-Step 19.A-10-07-2026-end
def single_run_nr(
        runs, seed, gnb_number, ues_per_gnb, simulation_time,
        area_w, area_h, gnb_pos, ue_radius,
        numerology, bandwidth_mhz, scheduler, tx_power_dbm, f_ghz, noise_figure_db,
        gnb_mobility_speed_mps, ue_mobility_speed_mps, mobility_pause_s,
        # Rashed-Step 13.E.3-08-23-2026-start
        export_packets_csv_path=None, rate_adapt=False, rate_adapt_ml_model=None,
        # Rashed-Step 13.E.3-08-23-2026-end
        # Rashed-Step 15.G-09-18-2026-start
        tdd_enabled=False, tdd_pattern="DDDU", ue_uplink_enabled=False, rrc_enabled=False,
        # Rashed-Step 15.G-09-18-2026-end
        # Rashed-Step 16.F-10-02-2026-start
        core_enabled=False, core_registration_delay_us=None, core_pdu_session_delay_us=None,
        # Rashed-Step 16.F-10-02-2026-end
        # Rashed-Step 18.A-10-06-2026-start
        error_model="threshold", bler_slope_db=None,
        # Rashed-Step 18.A-10-06-2026-end
        # Rashed-Step 18.B-10-06-2026-start
        dl_traffic="full_buffer", dl_arrival_rate_pps=None, ul_traffic="full_buffer",
        ul_arrival_rate_pps=None, packet_size_bytes=None, buffer_limit_bytes=None,
        # Rashed-Step 18.B-10-06-2026-end
        # Rashed-Step 18.E-10-06-2026-start
        harq=False, harq_max_tx=None, harq_rtt_slots=None,
        # Rashed-Step 18.F-10-06-2026-start
        rlc_mode="none", pdcp_sn_bits=None, rlc_am_max_retx=None, rlc_am_status_delay_ms=None,
        # Rashed-Step 19.A-10-07-2026-start
        rach=False, prach_period_ms=None, rach_backoff_ms=None, rar_window_ms=None,
        # Rashed-Step 19.A-10-07-2026-end
        # Rashed-Step 18.F-10-06-2026-end
        # Rashed-Step 18.E-10-06-2026-end
):
    gnb_positions = parse_pos_list_nr(gnb_pos, "--gnb-pos") if gnb_pos else None

    # Rashed-Step 15.G-09-18-2026-start
    if rrc_enabled and not ue_uplink_enabled:
        raise click.BadParameter(
            "--rrc-enabled requires --ue-uplink-enabled to also be set "
            "(RRC attach needs real uplink capability to send "
            "RRCSetupRequest/RRCSetupComplete - see ran/protocol/rrc.py's "
            "module docstring)."
        )
    # Rashed-Step 15.G-09-18-2026-end

    # Rashed-Step 16.F-10-02-2026-start
    try:
        core_config = core_config_from_cli(core_enabled, core_registration_delay_us, core_pdu_session_delay_us)
    except ValueError as e:
        raise click.BadParameter(str(e))
    # Rashed-Step 16.F-10-02-2026-end
    # Rashed-Step 18.A-10-06-2026-start
    try:
        error_model_config = error_model_config_from_cli(error_model, bler_slope_db)
    except ValueError as e:
        raise click.BadParameter(str(e))
    # Rashed-Step 18.A-10-06-2026-end
    # Rashed-Step 18.B-10-06-2026-start
    try:
        dl_traffic_config, ul_traffic_config = traffic_configs_from_cli(
            dl_traffic, dl_arrival_rate_pps, ul_traffic, ul_arrival_rate_pps,
            packet_size_bytes, buffer_limit_bytes, ue_uplink_enabled)
    except ValueError as e:
        raise click.BadParameter(str(e))
    # Rashed-Step 18.E-10-06-2026-start
    try:
        harq_config = harq_config_from_cli(harq, harq_max_tx, harq_rtt_slots)
    except ValueError as e:
        raise click.BadParameter(str(e))
    # Rashed-Step 18.E-10-06-2026-end
    # Rashed-Step 18.E-10-06-2026-start
    if harq_config is not None and dl_traffic_config is None and ul_traffic_config is None:
        raise click.BadParameter("--harq needs --dl-traffic or --ul-traffic poisson/cbr (full buffer has no data to recover).")
    # Rashed-Step 18.F-10-06-2026-start
    try:
        l2_config = l2_config_from_cli(rlc_mode, None if pdcp_sn_bits is None else int(pdcp_sn_bits),
                                       rlc_am_max_retx, rlc_am_status_delay_ms)
    except ValueError as e:
        raise click.BadParameter(str(e))
    # Rashed-Step 18.F-10-06-2026-end
    # Rashed-Step 18.F-10-06-2026-start
    if l2_config is not None and dl_traffic_config is None and ul_traffic_config is None:
        raise click.BadParameter("--rlc-mode needs --dl-traffic or --ul-traffic poisson/cbr.")
    # Rashed-Step 19.A-10-07-2026-start
    try:
        rach_config = rach_config_from_cli(rach, prach_period_ms, rach_backoff_ms, rar_window_ms)
    except ValueError as e:
        raise click.BadParameter(str(e))
    if rach_config is not None and not rrc_enabled:
        raise click.BadParameter("--rach requires --rrc-enabled (random access starts the RRC attach).")
    # Rashed-Step 19.A-10-07-2026-end
    # Rashed-Step 18.F-10-06-2026-end
    # Rashed-Step 18.E-10-06-2026-end
    # Rashed-Step 18.B-10-06-2026-end

    # Rashed-Step 13.E.3-08-23-2026-start
    if rate_adapt_ml_model and not rate_adapt:
        raise click.BadParameter(
            "--rate-adapt-ml-model requires --rate-adapt to also be set "
            "(the model only replaces WHICH SINR value drives an already-"
            "enabled ahead-of-time pick, it doesn't enable rate adaptation "
            "on its own)."
        )
    sinr_predictor = None
    if rate_adapt_ml_model:
        # Imported here, not at module level - keeps this CLI's normal
        # dependency footprint free of sklearn/pandas/joblib unless the
        # flag is actually used (Step 13.txt design decision 6).
        from ml.predictor import SinrPredictor
        sinr_predictor = SinrPredictor(rate_adapt_ml_model)
    # Rashed-Step 13.E.3-08-23-2026-end

    config = Config_NRL(
        numerology=numerology,
        bandwidth_mhz=bandwidth_mhz,
        scheduler=scheduler,
        tx_power_dbm=tx_power_dbm,
        f_ghz=f_ghz * 1e9,
        noise_figure_db=noise_figure_db,
        # Rashed-Step 13.E.3-08-23-2026-start
        rate_adapt_enabled=rate_adapt,
        sinr_predictor=sinr_predictor,
        # Rashed-Step 13.E.3-08-23-2026-end
        # Rashed-Step 15.G-09-18-2026-start
        tdd_enabled=tdd_enabled,
        tdd_pattern=tdd_pattern,
        # Rashed-Step 15.G-09-18-2026-end
        # Rashed-Step 18.B-10-06-2026-start
        dl_traffic=dl_traffic_config,
        ul_traffic=ul_traffic_config,
        buffer_limit_bytes=buffer_limit_bytes,
        # Rashed-Step 18.B-10-06-2026-end
        # Rashed-Step 18.E-10-06-2026-start
        harq=harq_config,
        # Rashed-Step 18.F-10-06-2026-start
        l2=l2_config,
        # Rashed-Step 19.A-10-07-2026-start
        rach=rach_config,
        # Rashed-Step 19.A-10-07-2026-end
        # Rashed-Step 18.F-10-06-2026-end
        # Rashed-Step 18.E-10-06-2026-end
    )

    for i in range(runs):
        curr_seed = seed + i
        run_simulation_licensed_nr(
            gnb_number, curr_seed, simulation_time, config,
            area_w=area_w, area_h=area_h,
            gnb_positions=gnb_positions, ue_radius=ue_radius,
            nr_ues_per_gnb=ues_per_gnb,
            gnb_mobility_speed_mps=gnb_mobility_speed_mps,
            ue_mobility_speed_mps=ue_mobility_speed_mps,
            mobility_pause_s=mobility_pause_s,
            # Rashed-Step 13.E.3-08-23-2026-start
            export_packets_csv_path=export_packets_csv_path,
            # Rashed-Step 13.E.3-08-23-2026-end
            # Rashed-Step 15.G-09-18-2026-start
            nr_ue_uplink_enabled=ue_uplink_enabled,
            nr_rrc_enabled=rrc_enabled,
            # Rashed-Step 15.G-09-18-2026-end
            # Rashed-Step 16.F-10-02-2026-start
            core_enabled=core_enabled,
            core_config=core_config,
            # Rashed-Step 16.F-10-02-2026-end
            # Rashed-Step 18.A-10-06-2026-start
            error_model_config=error_model_config,
            # Rashed-Step 18.A-10-06-2026-end
        )


if __name__ == "__main__":
    single_run_nr()
# Rashed-Step 6.B-07-31-2026-end
