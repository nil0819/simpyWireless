# Rashed-Step 25.C-10-20-2026-start
"""
Step 25.C tests: Wi-Fi spatial streams (wifi/phy.py) and downlink MU-MIMO
grouping / SINR (wifi/ofdma.py), plus the CLI flags.
"""
import math
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest
from click.testing import CliRunner

from wifi import ofdma, phy
from wifi.wifi import Config


def test_streams_scale_rate_threshold_and_preamble():
    assert phy.rate_mbps("he", 80, 11, 800, 2) == pytest.approx(2 * phy.rate_mbps("he", 80, 11, 800))
    c1, c4 = Config(phy="he", mcs=7), Config(phy="he", mcs=7, spatial_streams=4)
    t1, t4 = phy.sinr_table(c1), phy.sinr_table(c4)
    assert all(t4[m] == pytest.approx(t1[m] + 10 * math.log10(4)) for m in t1)
    p1, p4 = phy.make_times(c1, 1500, 7), phy.make_times(c4, 1500, 7)
    assert p4.data_rate == pytest.approx(4 * p1.data_rate)
    assert p4.ofdm_preamble == pytest.approx(p1.ofdm_preamble + 3 * 7.2)         # 4 HE-LTFs
    assert phy.ltf_extra_us("vht", 3, 400) == pytest.approx(3 * 4.0)              # 3 streams -> 4 LTFs
    assert phy.sinr_table(Config()) is phy.WIFI_MCS_SINR_THRESHOLDS_DB            # legacy untouched


def test_validation():
    with pytest.raises(ValueError):
        Config(spatial_streams=2)                                                  # legacy
    with pytest.raises(ValueError):
        Config(phy="he", spatial_streams=5)
    with pytest.raises(ValueError):
        Config(phy="he", spatial_streams=2, mu_mimo_users=2)                       # no OFDMA
    with pytest.raises(ValueError):
        Config(phy="he", ofdma=True, spatial_streams=2, mu_mimo_users=3)          # > antennas
    Config(phy="vht", mcs=9, spatial_streams=3)                                    # VHT20 MCS 9 ok with 3 SS
    with pytest.raises(ValueError):
        Config(phy="vht", mcs=9, spatial_streams=2)


def test_mu_groups():
    assert ofdma.mu_groups(20, 4, 2) == [2, 2]            # two 106-tone RUs, 2 users each
    assert ofdma.mu_groups(20, 2, 4) == [2]               # one 242-tone RU
    assert ofdma.mu_groups(20, 3, 2) == [2, 1]
    assert ofdma.mu_groups(20, 9, 4) is None              # 3 groups don't fit at >= 106 tones
    assert ofdma.mu_groups(80, 8, 2) == [2, 2, 2, 2]
    assert ofdma.mu_groups(80, 8, 4) == [4, 4]            # two 484-tone RUs
    assert ofdma.mu_groups(80, 7, 4) == [4, 3]


def test_mu_sinr():
    assert ofdma.mu_sinr_db(20.0, 1, -20.0) == 20.0
    assert ofdma.mu_sinr_db(20.0, 2, -20.0) == pytest.approx(10 * math.log10(1 / (0.01 + 0.01)))   # 17 dB
    assert ofdma.mu_sinr_db(40.0, 4, -20.0) < 15.3                                # residual-limited


def _out(args):
    from singleRun import single_run
    base = ["--seed", "2", "-t", "0.5", "-r", "1", "--ap-number", "1", "--gnb-number", "0", "--ap-pos", "0,0",
            "--area-w", "10", "--area-h", "10", "--wifi-stas-per-ap", "4", "--wifi-phy", "he", "-m", "5"]
    runner = CliRunner()
    with runner.isolated_filesystem():
        return runner.invoke(single_run, base + args)


def _tput(res):
    assert res.exit_code == 0, res.output[-600:]
    line = [l for l in res.output.splitlines() if l.startswith("Wifi packet throughput (Mbps)")][0]
    return float(line.split(":")[1])


def test_cli_streams_and_mu_mimo():
    one = _tput(_out(["--wifi-ofdma"]))
    two = _out(["--wifi-ofdma", "--wifi-spatial-streams", "2"])
    mu = _out(["--wifi-ofdma", "--wifi-spatial-streams", "2", "--wifi-mu-mimo-users", "2"])
    assert "2 streams ->" in two.output and "DL MU-MIMO up to 2 users" in mu.output
    assert _tput(two) > one and _tput(mu) > 0
    assert _out(["--wifi-spatial-streams", "2", "--wifi-phy", "legacy"]).exit_code != 0
    assert _out(["--wifi-mu-mimo-users", "2", "--wifi-spatial-streams", "2"]).exit_code != 0     # no OFDMA
    assert _out(["--wifi-ofdma", "--wifi-mu-mimo-users", "2"]).exit_code != 0                   # 1 stream
# Rashed-Step 25.C-10-20-2026-end
