# Rashed-Step 6.B-07-31-2026-start
# Standalone CLI for the licensed 5G NR scenario (simulation_nr.py) -
# separate from singleRun.py (WiFi/NR-U coexistence) per the confirmed
# "standalone first" scope for Step 6.B. Run e.g.:
#   python singleRunNR.py --gnb-number 2 --ues-per-gnb 6 -t 1 --scheduler proportional_fair

import click

from simulation_nr import run_simulation_licensed_nr, parse_pos_list_nr
from nr.nr import Config_NRL


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
@click.option("--rrc-enabled", "rrc_enabled", is_flag=True, default=False, help="Enable the generic RRC attach state machine (Step 15.F) for every UE: IDLE -> CONNECTING -> CONNECTED, via a real RRCSetupRequest/RRCSetup/RRCSetupComplete exchange that reuses the SchedulingRequest->grant delay for its uplink messages (deterministic timing, unlike NR-U's LBT-contention-driven version). Requires --ue-uplink-enabled too (fails fast otherwise). Once set, the gNB's own DL/UL scheduling (Step 15.G) is gated on rrc_state==CONNECTED - see Project details/Step pre_15.txt's STEP 15 - 15.G DONE section. Default (unset/False) = every UE has no rrc_state at all, byte-identical to every pre-15.F run.")
# Rashed-Step 15.G-09-18-2026-end
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
        )


if __name__ == "__main__":
    single_run_nr()
# Rashed-Step 6.B-07-31-2026-end
