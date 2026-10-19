# Rashed-Step 7.B-08-05-2026-start
# Standalone CLI for the spectrum-analyzer scenario (simulation_spectrum.py)
# - separate from singleRun.py (WiFi/NR-U coexistence) and singleRunNR.py
# (licensed NR), per the confirmed "standalone first" scope for Step 7.B.
# Run e.g.:
#   python singleRunSpectrum.py --ap-number 2 --gnb-number 1 --sniffer-number 2 -t 1

import click

from simulation_spectrum import run_simulation_spectrum
from wifi.wifi import Config as WifiConfig
from nru.nru import Config_NR
from generic.generic_device import Config_Generic
from simulation_nr import parse_pos_list_nr as parse_pos_list  # reused verbatim, see that file's docstring


@click.command()
@click.option("-r", "--runs", "runs", default=1, help="Number of simulation runs")
@click.option("--seed", "seed", default=1, help="Seed for simulation")
@click.option("--ap-number", "ap_number", type=int, required=True, help="Number of Wi-Fi APs generating traffic")
@click.option("--gnb-number", "gnb_number", type=int, required=True, help="Number of NR-U gNBs generating traffic")
@click.option("--sniffer-number", "sniffer_number", type=int, default=1, help="Number of spectrum-analyzer sniffer nodes")
@click.option("-t", "--simulation-time", "simulation_time", default=1.0, help="Duration of the simulation in s")
@click.option("--area-w", "area_w", type=float, default=50.0, help="Deployment area width (m)")
@click.option("--area-h", "area_h", type=float, default=50.0, help="Deployment area height (m)")
@click.option("--sta-radius", "sta_radius", type=float, default=10.0, help="Radius (m) around its AP within which a Wi-Fi STA is placed")
@click.option("--ue-radius", "ue_radius", type=float, default=15.0, help="Radius (m) around its gNB within which an NR-U UE is placed")
@click.option("--sniffer-pos", "sniffer_pos", type=str, multiple=True, help="Explicit sniffer position 'x,y' (repeatable)")
@click.option("--sniff-interval-us", "sniff_interval_us", type=float, default=50.0, help="How often (us) each sniffer samples the channel")
@click.option("--sniffer-ed-threshold-dbm", "sniffer_ed_threshold_dbm", type=float, default=-62.0, help="Energy-detect threshold (dBm) sniffers use for their busy/idle read")
@click.option("--sniffer-bandwidth-mhz", "sniffer_bandwidth_mhz", type=float, default=20.0, help="Sniffer's own in-band channel width (MHz) - only affects the in-band (not wideband) reading")
@click.option("--sniffer-freq-ghz", "sniffer_freq_ghz", type=float, default=5.18, help="Sniffer's own in-band center frequency (GHz) - only affects the in-band (not wideband) reading")
@click.option("--wifi_cw_min", "wifi_cw_min", default=15, help="Size of Wi-Fi cw min")
@click.option("--wifi_cw_max", "wifi_cw_max", default=63, help="Size of Wi-Fi cw max")
@click.option("--nru_cw_min", "nru_cw_min", default=15, help="Size of NR-U cw min")
@click.option("--nru_cw_max", "nru_cw_max", default=63, help="Size of NR-U cw max")
@click.option("--mcot", "mcot", default=6, help="Max channel occupancy time for NR-U (ms)")
@click.option("-syn_slot", "--synchronization_slot_duration", "synchronization_slot_duration", default=1000, help="Synchronization slot length in microseconds")
# Rashed-Step 7.C-08-05-2026-start
# Shadowing/mobility/EIRP knobs, brought over from singleRun.py for
# parity - same flag names/defaults/help text where directly
# applicable, so anyone already familiar with singleRun.py's CLI
# doesn't have to relearn anything here.
@click.option("--shadowing-sigma-db", "shadowing_sigma_db", type=float, default=0.0, help="Log-normal shadow fading std dev in dB, applied on top of the deterministic path loss (0 = disabled/deterministic; typical indoor value ~4-8)")
@click.option("--wifi-tx-power-dbm", "wifi_tx_power_dbm", type=float, default=20.0, help="Wi-Fi tx power (dBm), treated as EIRP directly. Checked at startup against the FCC U-NII EIRP cap (warning only, not clamped/enforced).")
@click.option("--nru-tx-power-dbm", "nru_tx_power_dbm", type=float, default=23.0, help="NR-U tx power (dBm). See --wifi-tx-power-dbm.")
@click.option("--ap-mobility-speed-mps", "ap_mobility_speed_mps", type=float, default=0.0, help="AP walking/roaming speed (m/s). 0.0 (default) = static. >0 enables random-waypoint mobility within the [0,area-w]x[0,area-h] box.")
@click.option("--gnb-mobility-speed-mps", "gnb_mobility_speed_mps", type=float, default=0.0, help="gNB roaming speed (m/s). See --ap-mobility-speed-mps.")
@click.option("--sta-mobility-speed-mps", "sta_mobility_speed_mps", type=float, default=0.0, help="Wi-Fi STA walking speed (m/s), e.g. ~1.4 for a typical walking pace. See --ap-mobility-speed-mps.")
@click.option("--ue-mobility-speed-mps", "ue_mobility_speed_mps", type=float, default=0.0, help="NR-U UE walking speed (m/s). See --ap-mobility-speed-mps.")
@click.option("--sniffer-mobility-speed-mps", "sniffer_mobility_speed_mps", type=float, default=0.0, help="Sniffer roaming speed (m/s) - e.g. a vehicle- or drone-mounted spectrum scanner doing a moving sweep instead of sitting at a fixed point. See --ap-mobility-speed-mps.")
@click.option("--mobility-pause-s", "mobility_pause_s", type=float, default=0.0, help="Dwell time (s) at each waypoint before picking the next one, for any node type with mobility enabled.")
# Rashed-Step 7.C-08-05-2026-end
@click.option("--log-file", "log_file", is_flag=True, default=False, help="Write the per-event debug log to log/<timestamp>.log (Step 24.A: off by default - it took ~45 % of a run's time and 20-30 MB per 100 simulated seconds; printed results don't depend on it).")  # Rashed-Step 24.A-10-19-2026
@click.option("--log-level", "log_level", type=click.Choice(["INFO", "DEBUG"]), default="INFO", help="Level for --log-file (default INFO, as before).")  # Rashed-Step 24.A-10-19-2026
def single_run_spectrum(
        runs, seed, ap_number, gnb_number, sniffer_number, simulation_time,
        area_w, area_h, sta_radius, ue_radius,
        sniffer_pos, sniff_interval_us, sniffer_ed_threshold_dbm,
        sniffer_bandwidth_mhz, sniffer_freq_ghz,
        wifi_cw_min, wifi_cw_max, nru_cw_min, nru_cw_max, mcot, synchronization_slot_duration,
        shadowing_sigma_db, wifi_tx_power_dbm, nru_tx_power_dbm,
        ap_mobility_speed_mps, gnb_mobility_speed_mps, sta_mobility_speed_mps,
        ue_mobility_speed_mps, sniffer_mobility_speed_mps, mobility_pause_s,
        log_file: bool = False, log_level: str = "INFO",  # 24.A
):
    # Rashed-Step 24.A-10-19-2026-start
    if log_file:
        from common.common import enable_file_log
        print(f"Log file: {enable_file_log(level=log_level)}")
    # Rashed-Step 24.A-10-19-2026-end
    sniffer_positions = parse_pos_list(sniffer_pos, "--sniffer-pos") if sniffer_pos else None

    wifi_config = WifiConfig(cw_min=wifi_cw_min, cw_max=wifi_cw_max, tx_power_dbm=wifi_tx_power_dbm)
    configNr = Config_NR(
        cw_min=nru_cw_min, cw_max=nru_cw_max, mcot=mcot,
        synchronization_slot_duration=synchronization_slot_duration,
        tx_power_dbm=nru_tx_power_dbm,
    )
    sniffer_config = Config_Generic(
        f_hz=sniffer_freq_ghz * 1e9,
        bandwidth_mhz=sniffer_bandwidth_mhz,
        ed_threshold_dbm=sniffer_ed_threshold_dbm,
        tech_label="SNIFFER",
    )

    for i in range(runs):
        curr_seed = seed + i
        run_simulation_spectrum(
            ap_number, gnb_number, sniffer_number, curr_seed, simulation_time,
            wifi_config, configNr, sniffer_config,
            area_w=area_w, area_h=area_h,
            sta_radius=sta_radius, ue_radius=ue_radius,
            sniffer_positions=sniffer_positions,
            sniff_interval_us=sniff_interval_us,
            shadowing_sigma_db=shadowing_sigma_db,
            ap_mobility_speed_mps=ap_mobility_speed_mps,
            gnb_mobility_speed_mps=gnb_mobility_speed_mps,
            sta_mobility_speed_mps=sta_mobility_speed_mps,
            ue_mobility_speed_mps=ue_mobility_speed_mps,
            sniffer_mobility_speed_mps=sniffer_mobility_speed_mps,
            mobility_pause_s=mobility_pause_s,
        )


if __name__ == "__main__":
    single_run_spectrum()
# Rashed-Step 7.B-08-05-2026-end
