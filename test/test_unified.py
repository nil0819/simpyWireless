# Rashed-Step 19.E-10-07-2026-start
"""
Step 19.E tests: one run with Wi-Fi, NR-U and licensed NR - the extracted
licensed-NR builder (19.E.1), licensed cells in simulation.py /
singleRun.py (19.E.2), one shared 5G Core (19.E.3) and the cross-band
checks (19.E.4).
"""

import contextlib
import io
import logging
import os
import re
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import simpy
from click.testing import CliRunner

import simulation
from channel.channel import ActiveTx, Channel
from nr.nr import Config_NRL
from nru.nru import Config_NR
from singleRun import single_run
from wifi.wifi import Config


def _tx(name, pos, f_ghz, bw, tech):
    return ActiveTx(tx_id=name, tx_pos=pos, tx_start=0, rx_pos=(0.0, 0.0), tx_power_dbm=30.0,
                    f_hz=f_ghz * 1e9, pl_exp=3.0, t_end=1000, tech=tech, bandwidth_mhz=bw)


def test_3_5_ghz_licensed_does_not_touch_5_ghz_sinr_or_sensing():
    env = simpy.Environment()
    ch = Channel(simpy.PriorityResource(env, capacity=1), simpy.Resource(env, capacity=1), 1, 1, {}, {}, {}, {}, {})
    wifi = _tx("ap", (5.0, 0.0), 5.18, 20.0, "WiFi")
    ch.register_tx(wifi)
    clean = ch.sinr_db(wifi)
    ch.register_tx(_tx("GnbNR 1", (1.0, 0.0), 3.5, 100.0, "NR"))
    assert ch.sinr_db(wifi) == clean                                   # other band: no interference
    assert not ch.is_busy((0.0, 0.0), -62.0, exclude_tx_id="ap", sense_f_hz=5.18e9, sense_bw_mhz=20.0)
    ch.register_tx(_tx("GnbNR 2", (1.0, 0.0), 5.18, 20.0, "NR"))      # same band: interferes
    assert ch.sinr_db(wifi) < clean - 10
    assert ch.is_busy((0.0, 0.0), -62.0, exclude_tx_id="ap", sense_f_hz=5.18e9, sense_bw_mhz=20.0)


def _run(**kw):
    logging.disable(logging.CRITICAL)
    spies = {"nru": [], "nr": []}
    orig_g = simulation.Gnb
    import simulation_nr
    orig_l = simulation_nr.GnbLicensedNR

    class SpyG(orig_g):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            spies["nru"].append(self)

    class SpyL(orig_l):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            spies["nr"].append(self)

    simulation.Gnb, simulation_nr.GnbLicensedNR = SpyG, SpyL
    try:
        with contextlib.redirect_stdout(io.StringIO()) as out:
            wifi = Config()
            backoffs = {k: {1: 0} for k in range(wifi.cw_max + 1)}
            simulation.run_simulation(1, kw.pop("n_nru", 1), 1, kw.pop("t", 0.4), wifi, Config_NR(), backoffs,
                                      {}, {}, {}, {}, False, **kw)
    finally:
        simulation.Gnb, simulation_nr.GnbLicensedNR = orig_g, orig_l
        logging.disable(logging.NOTSET)
    return spies, out.getvalue()


def test_colocated_licensed_cells_and_one_core():
    from core.network import CoreNetwork
    spies, out = _run(n_nru=2, nr_gnb_number=2, nr_colocated=True, nr_licensed_ues_per_gnb=2,
                      nr_config=Config_NRL(f_ghz=3.5e9, tdd_enabled=True),
                      nr_ue_uplink_enabled=True, nr_rrc_enabled=True,
                      nru_ue_uplink_enabled=True, nru_rrc_enabled=True, nru_core_enabled=True)
    nru, nr = spies["nru"], spies["nr"]
    assert [g.pos for g in nr] == [g.pos for g in nru]                 # co-located sites
    cores = {id(ue.core_network) for g in nru + nr for ue in g.ue_list}
    assert len(cores) == 1                                             # one Core for everyone
    assert all(ue.reg_state.name == "REGISTERED" for g in nru + nr for ue in g.ue_list)
    assert "=== Licensed 5G NR Results ===" in out and "=== NR-U 5G Core ===" in out
    assert nr[0].neighbors == [nr[1]]


def test_cli_licensed_at_5ghz_without_lbt_blocks_wifi_and_nru():
    base = ["--ap-number", "1", "--gnb-number", "1", "--seed", "1", "-t", "0.3", "-r", "1"]
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("log", exist_ok=True)
        own = runner.invoke(single_run, base + ["--nr-gnb-number", "1"])
        same = runner.invoke(single_run, base + ["--nr-gnb-number", "1", "--nr-f-ghz", "5.18", "--nr-bandwidth-mhz", "20"])
    assert own.exit_code == 0 and same.exit_code == 0, (own.output[-400:], same.output[-400:])
    thr = lambda o, t: float(re.search(t + r" packet throughput \(Mbps\): ([\d.]+)", o).group(1))
    assert thr(own.output, "Wifi") > 0 and thr(own.output, "NRU") > 0
    assert thr(same.output, "Wifi") == 0.0 and thr(same.output, "NRU") == 0.0


def test_cli_validation_and_shared_flags():
    base = ["--ap-number", "1", "--gnb-number", "1", "-t", "0.05", "-r", "1"]
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("log", exist_ok=True)
        r = runner.invoke(single_run, base + ["--nr-tdd"])
        assert r.exit_code != 0 and "need --nr-gnb-number" in r.output
        r = runner.invoke(single_run, base + ["--nr-gnb-number", "2", "--nr-colocated"])
        assert r.exit_code != 0 and "--nr-colocated needs" in r.output
        # --harq is valid for buffered licensed cells even with NR-U on the burst model.
        r = runner.invoke(single_run, base + ["--nr-gnb-number", "1", "--nr-dl-traffic", "cbr", "--harq"])
        assert r.exit_code == 0, (r.output, r.exception)
        assert "=== Licensed 5G NR DL HARQ ===" in r.output and "NR-U DL HARQ" not in r.output
        r = runner.invoke(single_run, base + ["--harq"])
        assert r.exit_code != 0 and "--harq needs" in r.output
# Rashed-Step 19.E-10-07-2026-end
