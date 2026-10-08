# Rashed-Step pre_19.F-10-07-2026-start
"""
Step pre_19.F test: NR-U "slots" + HARQ with several UEs per COT - a due
retransmission must not wait forever for its original RB count once the
max-min split gives each UE less (all HARQ processes stuck -> no new data).
"""

import contextlib
import io
import logging
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import simulation
from common.packet import TrafficConfig
from nru.nru import Config_NR
from ran.protocol.harq import HarqConfig
from wifi.wifi import Config


def _nru_multi_ue_harq():
    logging.disable(logging.CRITICAL)
    gnbs = []
    orig = simulation.Gnb

    class Spy(orig):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            gnbs.append(self)

    simulation.Gnb = Spy
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            wifi = Config()
            backoffs = {k: {1: 0} for k in range(wifi.cw_max + 1)}
            simulation.run_simulation(1, 1, 1, 0.5, wifi, Config_NR(cot_model="slots", harq=HarqConfig()),
                                      backoffs, {}, {}, {}, {}, False, nr_ues_per_gnb=4, ue_radius=40.0,
                                      nru_traffic_config=TrafficConfig(mode="poisson", arrival_rate_pps=20000.0))
    finally:
        simulation.Gnb = orig
        logging.disable(logging.NOTSET)
    return gnbs[0]


def test_pre_19f_retransmissions_dont_starve_a_multi_ue_cell():
    g = _nru_multi_ue_harq()
    # Every UE keeps getting data, and no HARQ entity ends up with all
    # 16 processes stuck on retransmissions that never fit.
    # (Packet counts depend on the link: a 1500-byte packet spans many small
    # TBs here and one lost TB loses it - so check the HARQ level.)
    for ue in g.ue_list:
        ent = g._harq_for(g.dl_buffers[ue.name])
        assert ent.pending() < 16
        assert ent.stats["ok_first"] + ent.stats["ok_retx"] > 100
    assert sum(e.stats["ok_retx"] for e in g.harq_entities(False)) > 0
# Rashed-Step pre_19.F-10-07-2026-end
