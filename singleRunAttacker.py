# Rashed-Step 9.C-08-07-2026-start
# Standalone CLI for the packet-attacker scenario (simulation_attacker.py)
# - separate from singleRun.py (WiFi/NR-U coexistence), singleRunNR.py
# (licensed NR), and singleRunSpectrum.py (spectrum analyzer), per the
# confirmed "own new file" scope for Step 9.C.
# Run e.g.:
#   python singleRunAttacker.py --ap-number 2 --gnb-number 1 -t 0.1 \
#       --spoof-target "AP 1" --spoof-count 5 --replay-max 3

import click

from simulation_attacker import run_simulation_attacker
from wifi.wifi import Config as WifiConfig
from nru.nru import Config_NR
from attacker.packet_attacker import Config_PacketAttacker
from simulation_nr import parse_pos_list_nr as parse_pos_list  # reused verbatim, see that file's docstring


@click.command()
@click.option("-r", "--runs", "runs", default=1, help="Number of simulation runs")
@click.option("--seed", "seed", default=1, help="Seed for simulation")
@click.option("--ap-number", "ap_number", type=int, required=True, help="Number of Wi-Fi APs generating real traffic")
@click.option("--gnb-number", "gnb_number", type=int, required=True, help="Number of NR-U gNBs generating real traffic")
@click.option("--attacker-number", "attacker_number", type=int, default=1, help="Number of PacketAttacker nodes")
@click.option("-t", "--simulation-time", "simulation_time", default=1.0, help="Duration of the simulation in s")
@click.option("--area-w", "area_w", type=float, default=50.0, help="Deployment area width (m)")
@click.option("--area-h", "area_h", type=float, default=50.0, help="Deployment area height (m)")
@click.option("--sta-radius", "sta_radius", type=float, default=10.0, help="Radius (m) around its AP within which a Wi-Fi STA is placed")
@click.option("--ue-radius", "ue_radius", type=float, default=15.0, help="Radius (m) around its gNB within which an NR-U UE is placed")
@click.option("--attacker-pos", "attacker_pos", type=str, multiple=True, help="Explicit attacker position 'x,y' (repeatable)")
@click.option("--attacker-tx-power-dbm", "attacker_tx_power_dbm", type=float, default=20.0, help="Attacker's own tx power (dBm) for spoof()/replay() transmissions")
@click.option("--attacker-bitrate-mbps", "attacker_bitrate_mbps", type=float, default=54.0, help="Simplified link-rate (Mbit/s) used to estimate spoof()/replay() on-air duration when not given explicitly - see attacker/packet_attacker.py's module docstring")
@click.option("--capture-window-s", "capture_window_s", type=float, default=0.02, help="How long (s), from the start of the run, the attacker only passively sniffs (capture phase) before spoofing/replaying begins")
@click.option("--sniff-interval-us", "sniff_interval_us", type=float, default=50.0, help="How often (us) the attacker samples the channel during the capture phase")
@click.option("--spoof-count", "spoof_count", type=int, default=5, help="Number of forged-source packets to transmit during the spoof phase (0 = disable spoofing)")
@click.option("--spoof-interval-us", "spoof_interval_us", type=float, default=200.0, help="Gap (us) between consecutive spoof transmissions")
@click.option("--spoof-target", "spoof_target", type=str, default="AP 1", help="Node name to forge as Packet.source on spoofed transmissions (e.g. a real AP/gNB name - not validated against the actual topology)")
@click.option("--spoof-payload-bytes", "spoof_payload_bytes", type=int, default=1000, help="Payload size (bytes) of each spoofed packet")
@click.option("--replay-interval-us", "replay_interval_us", type=float, default=200.0, help="Gap (us) between consecutive replay transmissions")
@click.option("--replay-max", "replay_max", type=int, default=-1, help="Max number of captured packets to replay (-1 = replay all captured packets, 0 = disable replay)")
@click.option("--wifi_cw_min", "wifi_cw_min", default=15, help="Size of Wi-Fi cw min")
@click.option("--wifi_cw_max", "wifi_cw_max", default=63, help="Size of Wi-Fi cw max")
@click.option("--nru_cw_min", "nru_cw_min", default=15, help="Size of NR-U cw min")
@click.option("--nru_cw_max", "nru_cw_max", default=63, help="Size of NR-U cw max")
@click.option("--mcot", "mcot", default=6, help="Max channel occupancy time for NR-U (ms)")
@click.option("-syn_slot", "--synchronization_slot_duration", "synchronization_slot_duration", default=1000, help="Synchronization slot length in microseconds")
@click.option("--shadowing-sigma-db", "shadowing_sigma_db", type=float, default=0.0, help="Log-normal shadow fading std dev in dB (0 = disabled/deterministic)")
@click.option("--wifi-tx-power-dbm", "wifi_tx_power_dbm", type=float, default=20.0, help="Wi-Fi tx power (dBm)")
@click.option("--nru-tx-power-dbm", "nru_tx_power_dbm", type=float, default=23.0, help="NR-U tx power (dBm)")
@click.option("--log-file", "log_file", is_flag=True, default=False, help="Write the per-event debug log to log/<timestamp>.log (Step 24.A: off by default - it took ~45 % of a run's time and 20-30 MB per 100 simulated seconds; printed results don't depend on it).")  # Rashed-Step 24.A-10-19-2026
@click.option("--log-level", "log_level", type=click.Choice(["INFO", "DEBUG"]), default="INFO", help="Level for --log-file (default INFO, as before).")  # Rashed-Step 24.A-10-19-2026
def single_run_attacker(
        runs, seed, ap_number, gnb_number, attacker_number, simulation_time,
        area_w, area_h, sta_radius, ue_radius,
        attacker_pos, attacker_tx_power_dbm, attacker_bitrate_mbps,
        capture_window_s, sniff_interval_us,
        spoof_count, spoof_interval_us, spoof_target, spoof_payload_bytes,
        replay_interval_us, replay_max,
        wifi_cw_min, wifi_cw_max, nru_cw_min, nru_cw_max, mcot, synchronization_slot_duration,
        shadowing_sigma_db, wifi_tx_power_dbm, nru_tx_power_dbm,
        log_file: bool = False, log_level: str = "INFO",  # 24.A
):
    # Rashed-Step 24.A-10-19-2026-start
    if log_file:
        from common.common import enable_file_log
        print(f"Log file: {enable_file_log(level=log_level)}")
    # Rashed-Step 24.A-10-19-2026-end
    attacker_positions = parse_pos_list(attacker_pos, "--attacker-pos") if attacker_pos else None
    replay_max_val = None if replay_max < 0 else replay_max

    wifi_config = WifiConfig(cw_min=wifi_cw_min, cw_max=wifi_cw_max, tx_power_dbm=wifi_tx_power_dbm)
    configNr = Config_NR(
        cw_min=nru_cw_min, cw_max=nru_cw_max, mcot=mcot,
        synchronization_slot_duration=synchronization_slot_duration,
        tx_power_dbm=nru_tx_power_dbm,
    )
    attacker_config = Config_PacketAttacker(
        tx_power_dbm=attacker_tx_power_dbm,
        bitrate_mbps=attacker_bitrate_mbps,
    )

    for i in range(runs):
        curr_seed = seed + i
        run_simulation_attacker(
            ap_number, gnb_number, attacker_number, curr_seed, simulation_time,
            wifi_config, configNr, attacker_config,
            area_w=area_w, area_h=area_h,
            sta_radius=sta_radius, ue_radius=ue_radius,
            attacker_positions=attacker_positions,
            capture_window_s=capture_window_s,
            sniff_interval_us=sniff_interval_us,
            spoof_count=spoof_count,
            spoof_interval_us=spoof_interval_us,
            spoof_target=spoof_target,
            spoof_payload_bytes=spoof_payload_bytes,
            replay_interval_us=replay_interval_us,
            replay_max=replay_max_val,
            shadowing_sigma_db=shadowing_sigma_db,
        )


if __name__ == "__main__":
    single_run_attacker()
# Rashed-Step 9.C-08-07-2026-end
