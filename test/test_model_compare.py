# Rashed-Step pre_11.C-08-13-2026-start
"""
Integration tests for model/runner.py + model/compare.py - these DO
invoke a real (short) singleRun.py run each, unlike test_model_bianchi.py/
test_model_dtmc.py's pure-math tests. Kept to short --sim-time values
(a few seconds at most) so they don't meaningfully slow down `pytest
test/` - each still exercises the full run_scenario() -> regex-parse ->
model-comparison pipeline end to end, just without the tight statistical
convergence a longer run would give (that's demonstrated separately, see
model/compare.py's own __main__ block and Project details/Step
pre_11.txt for the longer, hand-run comparisons this module's default
numbers are validated against).
"""
import pytest

from model.bianchi import BianchiNotValidError
from model.compare import compare_bianchi, compare_dtmc
from model.runner import run_scenario


def test_run_scenario_parses_all_expected_keys():
    stats = run_scenario([
        "--ap-number", "1", "--gnb-number", "1", "-t", "1", "-r", "1", "--seed", "1",
        "--wifi-traffic-model", "saturated", "--nru-traffic-model", "saturated",
        "--area-w", "20", "--area-h", "20", "--ap-pos", "0,0", "--gnb-pos", "10,0",
        "--sta-radius", "3", "--ue-radius", "3",
    ])
    for key in ("wifi_occ", "gnb_occ", "fairness", "joint", "wifi_succ", "wifi_fail",
                "nru_succ", "nru_fail", "pcoll_wifi", "pcoll_gnb"):
        assert stats[key] is not None, f"{key} was not parsed from stdout"
    assert 0.0 <= stats["wifi_occ"] <= 1.0
    assert 0.0 <= stats["gnb_occ"] <= 1.0
    assert stats["wifi_succ"] > 0
    assert stats["nru_succ"] > 0


def test_compare_bianchi_returns_sane_deviation():
    result = compare_bianchi(n_stations=5, cw_min=15, cw_max=63, sim_time_s=1.0)
    assert result["model_pcoll"] == pytest.approx(0.2903, abs=0.001)
    assert result["measured_pcoll"] is not None
    assert 0.0 <= result["measured_pcoll"] <= 1.0
    assert result["deviation"] is not None
    assert result["measured_wifi_succ"] > 0


def test_compare_bianchi_lone_station_never_collides_in_sim_either():
    # n=1: model predicts PCOLL=0% exactly, and there's no OTHER Wi-Fi AP
    # to collide with in the simulator either (NR-U isn't running in this
    # scenario at all - gnb-number=0), so measured should also be 0 (or
    # very close - a lone station can still occasionally fail on SINR/
    # noise grounds in principle, though not in this simulator's model
    # without shadowing/noise variance enabled).
    result = compare_bianchi(n_stations=1, cw_min=15, cw_max=63, sim_time_s=1.0)
    assert result["model_pcoll"] == 0.0
    assert result["measured_pcoll"] == pytest.approx(0.0, abs=1e-9)


def test_compare_bianchi_raises_for_known_invalid_regime():
    with pytest.raises(BianchiNotValidError):
        compare_bianchi(n_stations=20, cw_min=15, cw_max=63, sim_time_s=1.0)


def test_compare_dtmc_returns_sane_deviation():
    result = compare_dtmc(w=1, Wo=32, ng=55, Twp_us=5400.0, Tmcot_us=6000.0,
                           sim_time_s=2.0, wifi_packet_size_bytes=36286)
    assert result["model_Cn"] == pytest.approx(0.2530, abs=0.001)
    assert result["measured_Cn"] is not None
    assert 0.0 <= result["measured_Cn"] <= 1.0
    assert result["deviation_Cn"] is not None
    assert result["measured_wifi_succ"] > 0
    assert result["measured_nru_succ"] > 0


def test_compare_dtmc_default_wifi_frame_matches_step6d_ballpark():
    # Default 242us Wi-Fi frame (no --wifi-packet-size-bytes override) -
    # NR-U should dominate occupancy per both the model and the
    # simulator, matching this whole conversation's original "why is
    # gNB out-occupying my AP" starting point.
    result = compare_dtmc(w=1, Wo=32, ng=55, Twp_us=242.0, Tmcot_us=6000.0, sim_time_s=2.0)
    assert result["model_Cn"] > result["model_Cw"]
    assert result["measured_Cn"] > result["measured_Cw"]
# Rashed-Step pre_11.C-08-13-2026-end


# Rashed-Step pre_22.G-10-14-2026-start
def test_sim_accounted_cw_counts_data_plus_ack_per_success():
    from model import dtmc
    from model.compare import sim_accounted_cw
    m = dtmc.predict(w=1, Wo=32, ng=55, Twp_us=5400.0, Tmcot_us=6000.0)
    # Same successes per interval, 5444 instead of 5503 us each.
    assert sim_accounted_cw(m, 5400.0) == pytest.approx(m["Cw"] * 5444.0 / 5503.0, rel=1e-12)
    assert m["Cw"] == pytest.approx(0.7267, abs=0.001)          # the paper's eq. value is unchanged


def test_compare_dtmc_reports_both_cw_values():
    r = compare_dtmc(w=1, Wo=32, ng=55, Twp_us=5400.0, Tmcot_us=6000.0, sim_time_s=1.0,
                     wifi_packet_size_bytes=36286)
    assert r["model_Cw"] < r["model_Cw_dtmc"]
    assert r["deviation_Cw"] == pytest.approx(abs(r["measured_Cw"] - r["model_Cw"]) / r["model_Cw"])
# Rashed-Step pre_22.G-10-14-2026-end
