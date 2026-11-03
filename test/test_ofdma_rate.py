# Rashed-Step 26.A-11-03-2026-start
"""
Step 26.A tests: per-user rate adaptation in downlink OFDMA (wifi/ofdma.py
user_mcs / mcs_floor / rate_feedback, Minstrel.override).
"""
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from click.testing import CliRunner

from wifi import ofdma
from wifi.minstrel import Minstrel
from wifi.wifi import Config


class _Sta:
    def __init__(self, name):
        self.name = name


class _Ap:
    """Just what user_mcs / rate_feedback use."""
    def __init__(self, cfg, per_sta, minstrel=None):
        self.config, self.per_sta, self._minstrel, self.fed = cfg, per_sta, minstrel, []

    def current_mcs_for_link(self, key):
        return self.per_sta[key]

    def rate_adapt_record_result(self, key, ok, measured_sinr_db=None):
        self.fed.append((key, ok, measured_sinr_db))


def test_user_mcs_off_is_configured_mcs():
    ap = _Ap(Config(phy="he", ofdma=True, mcs=7), {"A": 2, "B": 9})
    assert [ofdma.user_mcs(ap, _Sta(n)) for n in "AB"] == [7, 7]
    ofdma.rate_feedback(ap, _Sta("A"), True, 20.0)
    assert ap.fed == []                                     # no rate adaptation: no feedback


def test_user_mcs_per_sta_and_floor():
    ap = _Ap(Config(phy="he", ofdma=True, mcs=7, rate_adapt_enabled=True), {"A": 2, "B": 9, "C": 0})
    assert [ofdma.user_mcs(ap, _Sta(n)) for n in "AB"] == [2, 9]
    assert ofdma.user_mcs(ap, _Sta("C"), floor=2) == 2      # raised to what fits on the RU
    ofdma.rate_feedback(ap, _Sta("B"), False, 12.5)
    assert ap.fed == [("B", False, 12.5)]


def test_mcs_floor():
    cfg = Config(phy="he", ofdma=True)
    assert ofdma.mcs_floor(cfg, 26, 1, 800, 1500, 5484.0) == 2   # MCS 0 / 1 on 26 tones: MPDU > 5.5 ms
    assert ofdma.mcs_floor(cfg, 242, 1, 800, 1500, 5484.0) == 0
    assert ofdma.mcs_floor(cfg, 26, 1, 800, 1500, 10.0) == 11    # nothing fits: highest


def test_minstrel_override_counts_for_used_mcs():
    ms = Minstrel({m: 10.0 * (m + 1) for m in range(8)}, 0, seed=1)
    assert ms.choose("A", 0.0) in range(8)
    ms.override("A", 3)
    ms.record("A", True, 0.0)
    assert ms.links["A"]["att"] == {3: 1} and ms.links["A"]["succ"] == {3: 1}


def _wifi_line(args):
    from singleRun import single_run
    base = ["--seed", "1", "-t", "0.5", "-r", "1", "--ap-number", "1", "--gnb-number", "0", "--ap-pos", "50,50",
            "--area-w", "100", "--area-h", "100", "--sta-radius", "40", "--wifi-stas-per-ap", "6",
            "--wifi-phy", "he", "-m", "7", "--wifi-ofdma", "--wifi-ampdu", "32", "--cell-report"]
    with CliRunner().isolated_filesystem():
        r = CliRunner().invoke(single_run, base + args)
    assert r.exit_code == 0, r.output[-600:]
    line = [l for l in r.output.splitlines() if l.startswith("Wi-Fi:")][0]
    return float(line.split("5th percentile ")[1].split()[0])


def test_cli_far_users_get_served():
    # STAs up to 40 m away: at the fixed MCS 7 the far ones never decode; per-user ARF / Minstrel serve them
    assert _wifi_line([]) == 0.0
    assert _wifi_line(["--wifi-rate-adapt"]) > 1.0
    assert _wifi_line(["--wifi-rate-adapt", "--wifi-rate-algo", "minstrel"]) > 0.5
# Rashed-Step 26.A-11-03-2026-end
