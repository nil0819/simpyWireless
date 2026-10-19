# Rashed-Step 11.A-08-12-2026-start
# Standalone CLI for the generic-transmitter scenario (simulation_
# generic.py) - separate from singleRun.py (WiFi/NR-U coexistence),
# singleRunNR.py (licensed NR), singleRunSpectrum.py (passive spectrum
# analyzer), and singleRunAttacker.py (packet attacker), same "own new
# file" pattern each of those followed.
#
# Run e.g.:
#   python singleRunGeneric.py --ap-number 1 --gnb-number 1 --generic-number 1 -t 0.1 \
#       --ap-pos 0,0 --gnb-pos 5,5 --generic-pos 2,2 --area-w 20 --area-h 20

import click

from simulation_generic import run_simulation_generic
from wifi.wifi import Config as WifiConfig
from nru.nru import Config_NR
from generic.generic_device import Config_Generic
from simulation_nr import parse_pos_list_nr as parse_pos_list  # reused verbatim, see that file's docstring


@click.command()
@click.option("-r", "--runs", "runs", default=1, help="Number of simulation runs")
@click.option("--seed", "seed", default=1, help="Seed for simulation")
@click.option("--ap-number", "ap_number", type=int, required=True, help="Number of Wi-Fi APs generating real (saturated by default) traffic")
@click.option("--gnb-number", "gnb_number", type=int, required=True, help="Number of NR-U gNBs generating real (saturated by default) traffic")
@click.option("--generic-number", "generic_number", type=int, default=1, help="Number of GenericTransmitter nodes (Step 11.A - actively senses+transmits, unlike the passive sniffers in singleRunSpectrum.py)")
@click.option("-t", "--simulation-time", "simulation_time", default=1.0, help="Duration of the simulation in s")
@click.option("--area-w", "area_w", type=float, default=50.0, help="Deployment area width (m), used for any node without an explicit position")
@click.option("--area-h", "area_h", type=float, default=50.0, help="Deployment area height (m)")
@click.option("--ap-pos", "ap_pos", type=str, multiple=True, help="Explicit AP position 'x,y' (repeatable, matched in order to AP 1, AP 2, ... - any AP beyond the given count falls back to random placement)")
@click.option("--gnb-pos", "gnb_pos", type=str, multiple=True, help="Explicit gNB position 'x,y' (repeatable). See --ap-pos.")
@click.option("--generic-pos", "generic_pos", type=str, multiple=True, help="Explicit GenericTransmitter position 'x,y' (repeatable). See --ap-pos.")
@click.option("--sta-radius", "sta_radius", type=float, default=10.0, help="Radius (m) around its AP within which a Wi-Fi STA is placed")
@click.option("--ue-radius", "ue_radius", type=float, default=15.0, help="Radius (m) around its gNB within which an NR-U UE is placed")
@click.option("--generic-tx-duration-us", "generic_tx_duration_us", type=float, default=500.0, help="Fixed on-air duration (us) of each GenericTransmitter transmission - NOT derived from payload_bytes (unlike Wi-Fi's PPDU duration), see generic/generic_transmitter.py's module docstring")
@click.option("--generic-backoff-min-us", "generic_backoff_min_us", type=float, default=0.0, help="Lower bound (us) of the GenericTransmitter's flat uniform random backoff before each attempt")
@click.option("--generic-backoff-max-us", "generic_backoff_max_us", type=float, default=500.0, help="Upper bound (us) of the same backoff range. NOT a contention-window (no growth on failure) - deliberately simpler/protocol-agnostic, see generic_transmitter.py")
@click.option("--generic-payload-bytes", "generic_payload_bytes", type=int, default=500, help="Payload size (bytes) stamped on each GenericTransmitter packet (bookkeeping only - does not affect tx duration, see --generic-tx-duration-us)")
@click.option("--generic-tx-power-dbm", "generic_tx_power_dbm", type=float, default=20.0, help="GenericTransmitter tx power (dBm)")
@click.option("--generic-ed-threshold-dbm", "generic_ed_threshold_dbm", type=float, default=-62.0, help="GenericTransmitter's own energy-detect threshold (dBm) for sensing the channel busy/idle - defaults to the same value as Wi-Fi's real CCA threshold, but this is a generic device, not a Wi-Fi one, so it's independently overridable")
@click.option("--generic-freq-ghz", "generic_freq_ghz", type=float, default=5.18, help="GenericTransmitter center frequency (GHz) - defaults to full co-channel overlap with Wi-Fi/NR-U's own default frequency")
@click.option("--generic-bandwidth-mhz", "generic_bandwidth_mhz", type=float, default=20.0, help="GenericTransmitter channel bandwidth (MHz)")
@click.option("--generic-mobility-speed-mps", "generic_mobility_speed_mps", type=float, default=0.0, help="GenericTransmitter walking/roaming speed (m/s) - 0.0 (default) = stays at its given/random position the whole run. >0 enables random-waypoint mobility within [0,area-w]x[0,area-h], so the device can traverse between zones while continuing to sense+transmit from wherever it currently is.")
@click.option("--mobility-pause-s", "mobility_pause_s", type=float, default=0.0, help="Dwell time (s) at each waypoint before picking the next one (only relevant if --generic-mobility-speed-mps > 0)")
@click.option("--wifi_cw_min", "wifi_cw_min", default=15, help="Size of Wi-Fi cw min")
@click.option("--wifi_cw_max", "wifi_cw_max", default=63, help="Size of Wi-Fi cw max")
@click.option("--nru_cw_min", "nru_cw_min", default=15, help="Size of NR-U cw min")
@click.option("--nru_cw_max", "nru_cw_max", default=63, help="Size of NR-U cw max")
@click.option("--mcot", "mcot", default=6, help="Max channel occupancy time for NR-U (ms)")
@click.option("-syn_slot", "--synchronization_slot_duration", "synchronization_slot_duration", default=1000, help="Synchronization slot length in microseconds")
@click.option("--shadowing-sigma-db", "shadowing_sigma_db", type=float, default=0.0, help="Log-normal shadow fading std dev in dB (0 = disabled/deterministic)")
@click.option("--wifi-tx-power-dbm", "wifi_tx_power_dbm", type=float, default=20.0, help="Wi-Fi tx power (dBm)")
@click.option("--nru-tx-power-dbm", "nru_tx_power_dbm", type=float, default=23.0, help="NR-U tx power (dBm)")
# Rashed-Step 13.E.2-08-23-2026-start
@click.option("--export-packets-csv", "export_packets_csv_path", type=str, default=None, help="Path to write a packet-level CSV of every GenericTransmitter transmission (technology-agnostic format, same as singleRun.py's --export-packets-csv, Step 9.D/13.E.2) - includes each packet's measured_sinr_db (Step 13.E.2). Default (unset) = no CSV, byte-identical to every pre-13.E.2 run.")
# Rashed-Step 13.E.2-08-23-2026-end
@click.option("--log-file", "log_file", is_flag=True, default=False, help="Write the per-event debug log to log/<timestamp>.log (Step 24.A: off by default - it took ~45 % of a run's time and 20-30 MB per 100 simulated seconds; printed results don't depend on it).")  # Rashed-Step 24.A-10-19-2026
@click.option("--log-level", "log_level", type=click.Choice(["INFO", "DEBUG"]), default="INFO", help="Level for --log-file (default INFO, as before).")  # Rashed-Step 24.A-10-19-2026
def single_run_generic(
        runs, seed, ap_number, gnb_number, generic_number, simulation_time,
        area_w, area_h, ap_pos, gnb_pos, generic_pos,
        sta_radius, ue_radius,
        generic_tx_duration_us, generic_backoff_min_us, generic_backoff_max_us,
        generic_payload_bytes, generic_tx_power_dbm, generic_ed_threshold_dbm,
        generic_freq_ghz, generic_bandwidth_mhz,
        generic_mobility_speed_mps, mobility_pause_s,
        wifi_cw_min, wifi_cw_max, nru_cw_min, nru_cw_max, mcot, synchronization_slot_duration,
        shadowing_sigma_db, wifi_tx_power_dbm, nru_tx_power_dbm,
        # Rashed-Step 13.E.2-08-23-2026-start
        export_packets_csv_path=None,
        # Rashed-Step 13.E.2-08-23-2026-end
        log_file: bool = False, log_level: str = "INFO",  # 24.A
):
    # Rashed-Step 24.A-10-19-2026-start
    if log_file:
        from common.common import enable_file_log
        print(f"Log file: {enable_file_log(level=log_level)}")
    # Rashed-Step 24.A-10-19-2026-end
    ap_positions = parse_pos_list(ap_pos, "--ap-pos") if ap_pos else None
    gnb_positions = parse_pos_list(gnb_pos, "--gnb-pos") if gnb_pos else None
    generic_positions = parse_pos_list(generic_pos, "--generic-pos") if generic_pos else None

    wifi_config = WifiConfig(cw_min=wifi_cw_min, cw_max=wifi_cw_max, tx_power_dbm=wifi_tx_power_dbm)
    configNr = Config_NR(
        cw_min=nru_cw_min, cw_max=nru_cw_max, mcot=mcot,
        synchronization_slot_duration=synchronization_slot_duration,
        tx_power_dbm=nru_tx_power_dbm,
    )
    generic_config = Config_Generic(
        tx_power_dbm=generic_tx_power_dbm,
        ed_threshold_dbm=generic_ed_threshold_dbm,
        f_hz=generic_freq_ghz * 1e9,
        bandwidth_mhz=generic_bandwidth_mhz,
        tech_label="GENERIC",
    )

    for i in range(runs):
        curr_seed = seed + i
        run_simulation_generic(
            ap_number, gnb_number, generic_number, curr_seed, simulation_time,
            wifi_config, configNr, generic_config,
            area_w=area_w, area_h=area_h,
            sta_radius=sta_radius, ue_radius=ue_radius,
            ap_positions=ap_positions, gnb_positions=gnb_positions, generic_positions=generic_positions,
            generic_tx_duration_us=generic_tx_duration_us,
            generic_backoff_min_us=generic_backoff_min_us,
            generic_backoff_max_us=generic_backoff_max_us,
            generic_payload_bytes=generic_payload_bytes,
            generic_mobility_speed_mps=generic_mobility_speed_mps,
            mobility_pause_s=mobility_pause_s,
            shadowing_sigma_db=shadowing_sigma_db,
            # Rashed-Step 13.E.2-08-23-2026-start
            export_packets_csv_path=export_packets_csv_path,
            # Rashed-Step 13.E.2-08-23-2026-end
        )


if __name__ == "__main__":
    single_run_generic()
# Rashed-Step 11.A-08-12-2026-end
