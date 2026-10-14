# Rashed-Step pre_11.C-08-13-2026-start
"""
High-level comparison harness: run a real simulator scenario (via
runner.py), run the matching analytical model with the same parameters,
and report measured-vs-model deviation. This formalizes the workflow used
by hand throughout this project's Step 6.A/6.D/pre_11.C validation work.
"""
import math
from typing import Dict, List, Optional

from model import bianchi, dtmc
from model.runner import run_scenario


# Rashed-Step pre_22.G-10-14-2026-start
def sim_accounted_cw(model: Dict, Twp_us: float, Tack_us: float = 44.0) -> float:
    """The DTMC's Wi-Fi occupancy counted the way the simulator counts it:
    Pws successes per mean interval, each worth Twp + Tack_us (the
    simulator's get_ack_frame_time(), SIFS included) instead of the
    model's Tws = Twp + SIFS + ACK + DIFS + sigma. model = dtmc.predict()."""
    return model["Pws"] * (Twp_us + Tack_us) / model["Tinterval"]
# Rashed-Step pre_22.G-10-14-2026-end


def _cluster_ap_positions(center: str, w: int, cluster_radius: float) -> List[str]:
    """
    Deterministically place w AP positions evenly around a circle of the
    given radius centered on `center` ("x,y" string) - used so that at
    higher w (5, 6, ...), all APs stay close enough to mutually sense each
    other, matching the DTMC model's single-collision-domain assumption
    (see compare_dtmc()'s ap_cluster_radius docs for why this matters:
    without it, singleRun.py's default random placement can scatter APs
    across the full area_w x area_h box, letting some pairs fall outside
    sensing range - a real hidden-terminal/spatial-reuse effect, but not
    one the DTMC model accounts for, so it produces measured occupancy
    sums >1.0 that aren't comparable to the model at all - found while
    sweeping w=1..6, Project details/Step pre_11.txt).
    """
    cx, cy = (float(v) for v in center.split(","))
    if w <= 1:
        return [f"{cx},{cy}"]
    positions = []
    for i in range(w):
        angle = 2.0 * math.pi * i / w
        x = cx + cluster_radius * math.cos(angle)
        y = cy + cluster_radius * math.sin(angle)
        positions.append(f"{x:.4f},{y:.4f}")
    return positions


def compare_bianchi(n_stations: int, cw_min: int, cw_max: int, sim_time_s: float,
                     seed: int = 1, area_w: float = 20.0, area_h: float = 20.0,
                     sta_radius: float = 3.0, ap_pos: str = "0,0",
                     ap_cluster_radius: Optional[float] = None,
                     extra_argv: Optional[List[str]] = None) -> Dict:
    """
    Runs a Wi-Fi-only saturated scenario (gnb-number=0) with n_stations
    APs and compares the simulator's measured PCOLL against
    bianchi.collision_probability(). Raises bianchi.BianchiNotValidError
    if the simplified closed-form has no solution at this n/window (see
    model/bianchi.py's KNOWN LIMITATION) - this is a real answer ("the
    model doesn't apply here"), not a bug, so it's allowed to propagate
    rather than being swallowed into a wrong number.

    ap_cluster_radius: same rationale as compare_dtmc()'s - Bianchi
    assumes all n_stations share ONE collision domain, but without this,
    singleRun.py places all n_stations APs randomly across area_w x
    area_h, which for n_stations=5 already scatters them ~10-20m apart
    (confirmed: wifi_occ=1.72, >1.0, the same tell as compare_dtmc()'s
    w=5/6 issue - some AP pairs are weakly coupled or non-interfering,
    so fewer than n_stations real contenders share the channel). Passing
    a cluster radius here places all n_stations APs evenly around a
    circle of that radius centered on ap_pos instead, isolating the
    remaining deviation to the real cause Bianchi is expected to miss:
    this simulator's SINR-based capture effect (Bianchi treats every
    overlapping transmission as a guaranteed double failure; this
    simulator can let the higher-SINR link still succeed). Leave as None
    to keep the old (pre-Step pre_11.txt sweep) random-placement
    behavior.
    """
    if ap_cluster_radius is not None:
        ap_pos_argv: List[str] = []
        for pos in _cluster_ap_positions(ap_pos, n_stations, ap_cluster_radius):
            ap_pos_argv += ["--ap-pos", pos]
    else:
        ap_pos_argv = []

    argv = [
        "--ap-number", str(n_stations), "--gnb-number", "0",
        "-t", str(sim_time_s), "-r", "1", "--seed", str(seed),
        "--wifi-traffic-model", "saturated",
        "--area-w", str(area_w), "--area-h", str(area_h),
        "--sta-radius", str(sta_radius),
        "--wifi_cw_min", str(cw_min), "--wifi_cw_max", str(cw_max),
    ] + ap_pos_argv + (extra_argv or [])
    measured = run_scenario(argv)

    model_p = bianchi.collision_probability(n_stations, cw_min, cw_max)
    measured_p = measured["pcoll_wifi"]
    deviation = None
    if measured_p is not None and model_p > 0:
        deviation = abs(measured_p - model_p) / model_p
    elif measured_p is not None and model_p == 0:
        deviation = abs(measured_p - model_p)  # absolute, since relative is undefined at 0

    return {
        "n_stations": n_stations, "cw_min": cw_min, "cw_max": cw_max,
        "model_pcoll": model_p, "measured_pcoll": measured_p,
        "deviation": deviation,
        "measured_wifi_succ": measured["wifi_succ"], "measured_wifi_fail": measured["wifi_fail"],
    }


def compare_dtmc(w: int, Wo: int, ng: int, Twp_us: float, Tmcot_us: float, sim_time_s: float,
                  seed: int = 1, area_w: float = 20.0, area_h: float = 20.0,
                  ap_pos: str = "0,0", gnb_pos: str = "10,0",
                  sta_radius: float = 3.0, ue_radius: float = 3.0,
                  wifi_packet_size_bytes: Optional[int] = None,
                  sync_slot_us: Optional[int] = None,
                  ap_cluster_radius: Optional[float] = None,
                  extra_argv: Optional[List[str]] = None) -> Dict:
    """
    Runs a w-AP + 1-gNB saturated scenario with a FIXED contention window
    (cw_min=cw_max=Wo-1 on both technologies, matching the DTMC's own
    fixed-window assumption - see Project details/Step 6.D for why this
    matters: the simulator's DEFAULT exponential-backoff CW is NOT
    directly comparable to this model) and compares measured Cn/Cw
    (from the printed "Gnb/Wifi occupancy (Normalized)" lines) against
    dtmc.predict()'s Cn/Cw.

    wifi_packet_size_bytes: if given, passed straight to --wifi-packet-
    size-bytes so the simulator's actual Wi-Fi PPDU duration matches
    Twp_us (caller is responsible for picking a byte count that produces
    Twp_us via Times.get_ppdu_frame_time() - see model/compare.py's own
    __main__ block for a worked example using 36286 bytes = 5400us).

    ng: the paper's "number of mini-slots in a gap period" parameter -
    NOTE this does NOT simply equal sync_slot_us/sigma_us. This
    simulator's actual gap period (nru.py's wait_back_off_gap_after())
    waits a RANDOM amount until the next sync-slot boundary, uniformly
    distributed over [0, sync_slot_duration) - so its AVERAGE length is
    sync_slot_duration/2, and ng should be derived from THAT instead:
    ng ~= (sync_slot_us/2) / sigma_us. This was found (and this
    docstring written) after an earlier version of this function forced
    -syn_slot=500 to superficially match a leftover ng=55 assumption,
    silently changing the SIMULATOR's real behavior away from its actual
    1000us default rather than fixing ng to match that default - see
    Project details/Step pre_11.txt for the full story. The default
    ng=55 used throughout this project's Step 6.D/pre_11.C validation
    already matches the simulator's default 1000us sync slot correctly:
    (1000/2)/9 ~= 55.6 -> 55 - so leave sync_slot_us=None (the
    simulator's real default) whenever ng=55 is used; don't pass both.
    sync_slot_us: only pass this if you deliberately want the SIMULATOR
    itself to use a non-default sync slot - and if you do, recompute ng
    to match via the formula above, don't reuse ng=55.

    ap_cluster_radius: the DTMC model assumes all w Wi-Fi APs share ONE
    collision domain (every AP senses every other AP). singleRun.py's
    default random placement only fixes AP 1 at ap_pos - APs 2..w land
    randomly anywhere in area_w x area_h, so at higher w some pairs can
    end up outside each other's sensing range (a real hidden-terminal/
    spatial-reuse effect the DTMC doesn't model at all - discovered
    sweeping w=1..6, see Project details/Step pre_11.txt). Passing a
    cluster radius here places all w APs evenly around a circle of that
    radius centered on ap_pos instead of using singleRun.py's random
    fallback, keeping every AP within 2*ap_cluster_radius of every other
    AP so they stay mutually visible and the comparison stays valid.
    Leave as None to keep the old (w=1..4 only) random-placement
    behavior.
    """
    if ap_cluster_radius is not None:
        ap_pos_list = _cluster_ap_positions(ap_pos, w, ap_cluster_radius)
        ap_pos_argv: List[str] = []
        for pos in ap_pos_list:
            ap_pos_argv += ["--ap-pos", pos]
    else:
        ap_pos_argv = ["--ap-pos", ap_pos]

    argv = [
        "--ap-number", str(w), "--gnb-number", "1",
        "-t", str(sim_time_s), "-r", "1", "--seed", str(seed),
        "--wifi-traffic-model", "saturated", "--nru-traffic-model", "saturated",
        "--area-w", str(area_w), "--area-h", str(area_h),
    ] + ap_pos_argv + [
        "--gnb-pos", gnb_pos,
        "--sta-radius", str(sta_radius), "--ue-radius", str(ue_radius),
        "--wifi_cw_min", str(Wo - 1), "--wifi_cw_max", str(Wo - 1),
        "--nru_cw_min", str(Wo - 1), "--nru_cw_max", str(Wo - 1),
        "--mcot", str(int(Tmcot_us / 1000)),
    ]
    if wifi_packet_size_bytes is not None:
        argv += ["--wifi-packet-size-bytes", str(wifi_packet_size_bytes)]
    if sync_slot_us is not None:
        argv += ["-syn_slot", str(sync_slot_us)]
    argv += (extra_argv or [])

    measured = run_scenario(argv)

    model = dtmc.predict(w=w, Wo=Wo, ng=ng, Twp_us=Twp_us, Tmcot_us=Tmcot_us)
    # Rashed-Step pre_22.G-10-14-2026-start
    # Compare like with like: the DTMC's Cw counts Tws = Twp + SIFS + ACK +
    # DIFS + sigma per success, the simulator's "Wifi occupancy" counts the
    # data airtime + get_ack_frame_time() (SIFS + ACK = 44 us). model_Cw is
    # now the DTMC's own success rate at the simulator's accounting
    # (5503 -> 5444 us per success at Twp 5400, about -0.9 points);
    # model_Cw_dtmc keeps the paper's eq. value.
    model_cw = sim_accounted_cw(model, Twp_us)
    # Rashed-Step pre_22.G-10-14-2026-end
    measured_cn = measured["gnb_occ"]
    measured_cw = measured["wifi_occ"]
    dev_cn = abs(measured_cn - model["Cn"]) / model["Cn"] if measured_cn is not None else None
    dev_cw = abs(measured_cw - model_cw) / model_cw if measured_cw is not None else None

    return {
        "w": w, "Wo": Wo, "ng": ng, "Twp_us": Twp_us, "Tmcot_us": Tmcot_us,
        "model_Cn": model["Cn"], "model_Cw": model_cw, "model_Cw_dtmc": model["Cw"],
        "model_tau_w": model["tau_w"], "model_tau_n": model["tau_n"],
        "measured_Cn": measured_cn, "measured_Cw": measured_cw,
        "deviation_Cn": dev_cn, "deviation_Cw": dev_cw,
        "measured_wifi_succ": measured["wifi_succ"], "measured_wifi_fail": measured["wifi_fail"],
        "measured_nru_succ": measured["nru_succ"], "measured_nru_fail": measured["nru_fail"],
    }


def print_report(result: Dict, kind: str) -> None:
    """Pretty-prints the dict returned by compare_bianchi()/compare_dtmc()."""
    if kind == "bianchi":
        print(f"Bianchi DCF comparison: N={result['n_stations']} stations, "
              f"cw_min={result['cw_min']} cw_max={result['cw_max']}")
        print(f"  model PCOLL    = {result['model_pcoll']*100:.2f}%")
        mp = result["measured_pcoll"]
        print(f"  measured PCOLL = {'N/A' if mp is None else f'{mp*100:.2f}%'} "
              f"({result['measured_wifi_succ']} succ / {result['measured_wifi_fail']} fail)")
        dev = result["deviation"]
        print(f"  deviation      = {'N/A' if dev is None else f'{dev*100:.1f}%'}")
    elif kind == "dtmc":
        print(f"DTMC comparison: w={result['w']} Wo={result['Wo']} ng={result['ng']} "
              f"Twp={result['Twp_us']}us Tmcot={result['Tmcot_us']}us")
        print(f"  model  Cn(gNB)={result['model_Cn']:.4f}  Cw(WiFi)={result['model_Cw']:.4f}")
        mcn, mcw = result["measured_Cn"], result["measured_Cw"]
        print(f"  measured  Cn(gNB)={'N/A' if mcn is None else f'{mcn:.4f}'}  "
              f"Cw(WiFi)={'N/A' if mcw is None else f'{mcw:.4f}'}")
        devn, devw = result["deviation_Cn"], result["deviation_Cw"]
        print(f"  deviation  Cn={'N/A' if devn is None else f'{devn*100:.1f}%'}  "
              f"Cw={'N/A' if devw is None else f'{devw*100:.1f}%'}")
    else:
        raise ValueError(f"unknown kind {kind!r}, expected 'bianchi' or 'dtmc'")


if __name__ == "__main__":
    print("=== Bianchi (N=5, default CW 15/63) ===")
    r = compare_bianchi(n_stations=5, cw_min=15, cw_max=63, sim_time_s=3.0)
    print_report(r, "bianchi")

    print()
    print("=== DTMC (w=1, Wo=32, Twp=5400us - this session's pre_11.C scenario) ===")
    # NOTE: ng=55 already matches the simulator's DEFAULT 1000us sync
    # slot (its average gap length is 500us, not the full 1000us - see
    # compare_dtmc()'s docstring) - do NOT also pass sync_slot_us=500
    # here, that would change the simulator's real behavior away from
    # the default instead of just informing the model.
    r = compare_dtmc(w=1, Wo=32, ng=55, Twp_us=5400.0, Tmcot_us=6000.0, sim_time_s=30.0,
                      wifi_packet_size_bytes=36286)
    print_report(r, "dtmc")
# Rashed-Step pre_11.C-08-13-2026-end
