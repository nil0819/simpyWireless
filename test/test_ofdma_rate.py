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

    def current_mcs_for_link(self, key, ofdma=False):
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


# Rashed-Step 26.B-11-03-2026-start
def test_uplink_has_its_own_state():
    ap = _Ap(Config(phy="he", ofdma=True, mcs=7, rate_adapt_enabled=True), {"A": 2, "A/UL": 9})
    sta = _Sta("A")
    assert ofdma.ul_key(sta) == "A/UL"
    assert ofdma.user_mcs(ap, sta) == 2 and ofdma.user_mcs(ap, sta, key=ofdma.ul_key(sta)) == 9
    ofdma.rate_feedback(ap, sta, True, 30.0, key=ofdma.ul_key(sta))
    assert ap.fed == [("A/UL", True, 30.0)]


def _ul(args):
    from singleRun import single_run
    base = ["--seed", "1", "-t", "0.5", "-r", "1", "--ap-number", "1", "--gnb-number", "0", "--ap-pos", "50,50",
            "--area-w", "100", "--area-h", "100", "--sta-radius", "40", "--wifi-stas-per-ap", "6",
            "--wifi-phy", "he", "-m", "7", "--wifi-ofdma", "--wifi-ampdu", "32",
            "--wifi-sta-uplink-enabled", "--wifi-ul-ofdma"]
    with CliRunner().isolated_filesystem():
        r = CliRunner().invoke(single_run, base + args)
    assert r.exit_code == 0, r.output[-600:]
    return float([l for l in r.output.splitlines() if l.startswith("Wifi uplink packet throughput (Mbps)")][0].split(":")[1])


def test_cli_uplink_rates_adapt():
    # STAs send at full power on small RUs: MCS 7 is conservative, per-user rates go higher
    assert _ul(["--wifi-rate-adapt"]) > 1.05 * _ul([])
# Rashed-Step 26.B-11-03-2026-end


# Rashed-Step 26.C-11-03-2026-start
class _ArfAp:
    def __init__(self, cfg, states):
        self.config, self.link_rate_state, self._minstrel = cfg, states, None


def test_peek_has_no_side_effects():
    ms = Minstrel({m: 10.0 * (m + 1) for m in range(8)}, 5, seed=1)
    ap = _ArfAp(Config(phy="he", ofdma=True, mcs=5), {})
    ap._minstrel = ms
    assert ofdma.peek_mcs(ap, "A/MU") == 5 and ms.links == {}         # no state created, no draw
    arf = _ArfAp(Config(phy="he", ofdma=True, mcs=7), {"A": {"mcs": 3}})
    assert ofdma.peek_mcs(arf, "A") == 3 and ofdma.peek_mcs(arf, "B") == 7
    assert ofdma.mu_key(_Sta("A")) == "A/MU"


def test_mu_worth_it_compares_sum_rates_and_probes():
    users = [_Sta(n) for n in "ABCD"]
    cfg = Config(phy="he", channel_width_mhz=80, ofdma=True, spatial_streams=2, mu_mimo_users=2, mcs=7)
    plan = ofdma.ru_plan(80, 4)                                       # 4 x 242 tones
    good = _ArfAp(cfg, {f"{n}/MU": {"mcs": 7} for n in "ABCD"} | {n: {"mcs": 2} for n in "ABCD"})
    bad = _ArfAp(cfg, {f"{n}/MU": {"mcs": 0} for n in "ABCD"} | {n: {"mcs": 7} for n in "ABCD"})
    picks = [ofdma.mu_worth_it(bad, users, [2, 2], plan, 80, 800, 2) for _ in range(20)]
    assert picks.count(True) == 2 and picks[9] and picks[19]          # only the every-10th probes
    assert all(ofdma.mu_worth_it(good, users, [2, 2], plan, 80, 800, 2) for _ in range(5))


def _mu(args):
    from singleRun import single_run
    base = ["--seed", "1", "-t", "0.5", "-r", "1", "--ap-number", "1", "--gnb-number", "0", "--ap-pos", "0,0",
            "--area-w", "20", "--area-h", "20", "--wifi-stas-per-ap", "8", "--wifi-phy", "he",
            "--wifi-channel-width", "80", "-m", "7", "--wifi-ofdma", "--wifi-ampdu", "64",
            "--wifi-spatial-streams", "4", "--wifi-mu-mimo-users", "4", "--wifi-rate-adapt"]
    with CliRunner().isolated_filesystem():
        r = CliRunner().invoke(single_run, base + args)
    assert r.exit_code == 0, r.output[-600:]
    line = [l for l in r.output.splitlines() if l.startswith("Wifi OFDMA MU-MIMO groups:")][0]
    groups = int(line.split("groups: ")[1].split(",")[0])
    return groups, int(line.rsplit(": ", 1)[1])


def test_cli_mu_only_when_it_pays():
    g_bad, fb_bad = _mu(["--wifi-mu-mimo-residual-db", "-20"])        # leaky precoding: mostly plain OFDMA
    g_good, fb_good = _mu(["--wifi-mu-mimo-residual-db", "-40"])      # clean precoding: MU-MIMO
    assert fb_bad > g_bad and fb_good == 0 and g_good > 0


def test_ofdma_report_with_lazy_mu_counters():
    # two APs, only some rounds group: the OFDMA report must not need every AP to have every counter
    from singleRun import single_run
    args = ["--seed", "2", "-t", "0.3", "-r", "1", "--ap-number", "2", "--gnb-number", "0", "--wifi-stas-per-ap", "3",
            "--wifi-phy", "he", "--wifi-channel-width", "40", "--wifi-ofdma", "--wifi-spatial-streams", "2",
            "--wifi-mu-mimo-users", "2", "--wifi-rate-adapt"]
    with CliRunner().isolated_filesystem():
        r = CliRunner().invoke(single_run, args)
    assert r.exit_code == 0, r.output[-600:]
    assert "Wifi OFDMA MU-MIMO groups:" in r.output
# Rashed-Step 26.C-11-03-2026-end


# Rashed-Step 26.D-11-03-2026-start
def test_ofdma_retry_chain_stops_at_most_reliable():
    ms = Minstrel({m: 10.0 * (m + 1) for m in range(8)}, 0, seed=7)
    for u in range(10):                                   # learn: MCS <= 5 decode
        now = (u + 1) * 100_000.0
        for _ in range(200):
            m = ms.choose("A", now)
            ms.record("A", m <= 5, now)
    st = ms.links["A"]
    st["fails"] = 3
    assert ms.choose("A", 2e6, chain_lowest=False) == st["maxp"] != 0      # OFDMA: no lowest-rate step
    ms.override("A", st["pending"]); st["pending"] = None
    assert ms.choose("A", 2e6) == 0                                         # single-user: lowest, as 25.E


def test_demand_plan_in_airtime_with_rate_adaptation():
    users = [_Sta(n) for n in "ABC"]
    cfg = Config(phy="he", ofdma=True, ofdma_ru_alloc="demand", rate_adapt_enabled=True, mcs=7)
    ap = _ArfAp(cfg, {"A": {"mcs": 1}, "B": {"mcs": 9}, "C": {"mcs": 9}})   # A is slow
    plan = ofdma._plan(cfg, 20, users, lambda s: 1.0, ap, lambda s: s.name)
    assert plan[0][0] == 106 and plan[1][0] == plan[2][0] == 52             # the slow user gets the big RU
    off = Config(phy="he", ofdma=True, ofdma_ru_alloc="demand", mcs=7)      # no rate adaptation: bytes only
    assert ofdma._plan(off, 20, users, lambda s: 1.0, _ArfAp(off, {}), lambda s: s.name) == ofdma.demand_plan(20, [1.0] * 3)
# Rashed-Step 26.D-11-03-2026-end
