# Rashed-Step 25.D-10-20-2026-start
"""
Step 25.D tests: demand-based OFDMA RU plan (wifi/ofdma.demand_plan) and
the --wifi-ofdma-ru-alloc flag.
"""
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest
from click.testing import CliRunner

from wifi import ofdma
from wifi.wifi import Config


def _tones(p):
    return [t for t, _, _ in p]


def _no_overlap(width, plan):
    spans = sorted((o / 1e6 - t * ofdma.SUBCARRIER_MHZ / 2, o / 1e6 + t * ofdma.SUBCARRIER_MHZ / 2) for t, o, _ in plan)
    assert spans[0][0] >= -width / 2 and spans[-1][1] <= width / 2
    assert all(a[1] <= b[0] + 1e-9 for a, b in zip(spans, spans[1:]))


def test_mixed_sizes_and_valid_layout():
    for width, dem in [(20, [1, 1, 1]), (20, [100, 1, 1]), (20, [5, 5, 1, 1, 1]), (40, [10, 1, 1, 1, 1, 1]),
                       (80, [1] * 5), (160, [3, 1, 2, 7, 1, 1, 1]), (20, [1] * 8)]:
        p = ofdma.demand_plan(width, dem)
        assert len(p) == len(dem) and all(t in ofdma.RU_NSD for t in _tones(p))
        _no_overlap(width, p)
    assert sorted(_tones(ofdma.demand_plan(20, [1, 1, 1]))) == [52, 52, 106]       # equal plan: 3 x 52
    assert _tones(ofdma.demand_plan(20, [100, 1, 1]))[0] == 106                     # heavy user alone
    assert _tones(ofdma.demand_plan(80, [1])) == [996]


def test_falls_back_when_tree_is_full():
    assert ofdma.demand_plan(20, [1] * 9) is None                                   # needs the centre 26
    assert ofdma.demand_plan(20, []) is None


def test_config_validation():
    with pytest.raises(ValueError):
        Config(phy="he", ofdma_ru_alloc="demand")                                   # no OFDMA
    with pytest.raises(ValueError):
        Config(phy="he", ofdma=True, ofdma_ru_alloc="greedy")
    Config(phy="he", ofdma=True, ofdma_ru_alloc="demand")


def _run(args):
    from singleRun import single_run
    base = ["--seed", "3", "-t", "0.5", "-r", "1", "--ap-number", "1", "--gnb-number", "0", "--ap-pos", "0,0",
            "--area-w", "10", "--area-h", "10", "--wifi-stas-per-ap", "5", "--wifi-phy", "he", "-m", "5",
            "--wifi-ofdma", "--wifi-ampdu", "16"]
    with CliRunner().isolated_filesystem():
        return CliRunner().invoke(single_run, base + args)


def test_cli():
    eq, dm = _run([]), _run(["--wifi-ofdma-ru-alloc", "demand"])
    assert eq.exit_code == 0 and dm.exit_code == 0, (eq.output + dm.output)[-600:]
    tput = [float([l for l in r.output.splitlines() if l.startswith("Wifi packet throughput (Mbps)")][0].split(":")[1])
            for r in (eq, dm)]
    assert tput[1] > tput[0]                     # 5 users: 5 x 26 tones vs 52/52/52/26/26
    assert "{26:" in eq.output.replace(" ", "") or "26:" in eq.output
# Rashed-Step 25.D-10-20-2026-end
