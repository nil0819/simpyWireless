# Rashed-Step 25.B-10-20-2026-start
"""
Step 25.B tests: Minstrel-style Wi-Fi rate adaptation (wifi/minstrel.py)
and its CLI flag.
"""
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from click.testing import CliRunner

from wifi import minstrel
from wifi.minstrel import Minstrel, UPDATE_US

RATES = {m: 10.0 * (m + 1) for m in range(8)}        # 10 .. 80 Mbps


def _run(ms, decodes, n_updates=20, per_update=200):
    """Drive one link: decodes(mcs) -> success. Returns the MCS picks."""
    picks = []
    for u in range(n_updates):
        now = (u + 1) * UPDATE_US
        for _ in range(per_update):
            m = ms.choose("STA", now)
            picks.append(m)
            ms.record("STA", decodes(m), now)
    return picks


def test_starts_at_configured_mcs_and_holds_choice_until_recorded():
    ms = Minstrel(RATES, 3, seed=1)
    first = ms.choose("STA", 0.0)
    assert all(ms.choose("STA", 0.0) == first for _ in range(20))   # held until a result
    assert first == 3 or RATES[first] > RATES[3]                    # configured, or a look-around probe
    ms.record("STA", True, 0.0)
    ms.record("STA", True, 0.0)                                     # second MPDU of the same A-MPDU
    assert ms.links["STA"]["att"] == {first: 2} and ms.links["STA"]["succ"] == {first: 2}


def test_converges_to_highest_decodable_mcs():
    ms = Minstrel(RATES, 0, seed=2)
    picks = _run(ms, lambda m: m <= 5)
    assert ms.links["STA"]["best"] == 5
    tail = picks[-1000:]
    assert tail.count(5) / len(tail) > 0.85                         # ~90 % best, ~10 % look-around


def test_prefers_throughput_over_probability():
    # MCS 7 succeeds 45 % (36 Mbps expected), MCS 4 always (50 Mbps), MCS 5 50 % (30)
    import random
    rng = random.Random(0)
    p = {m: 1.0 for m in range(5)}
    p.update({5: 0.5, 6: 0.0, 7: 0.45})
    ms = Minstrel(RATES, 0, seed=3)
    picks = _run(ms, lambda m: rng.random() < p[m], n_updates=40)[-4000:]
    assert max(set(picks), key=picks.count) == 4 and picks.count(4) / len(picks) > 0.7


def test_collisions_do_not_walk_the_rate_down():
    # every 3rd attempt collides regardless of MCS: ARF (2 failures -> down) would drift,
    # Minstrel stays on the highest decodable MCS because its throughput is still best
    k = {"n": 0}

    def dec(m):
        k["n"] += 1
        return m <= 6 and k["n"] % 3 != 0
    ms = Minstrel(RATES, 6, seed=4)
    _run(ms, dec)
    assert ms.links["STA"]["best"] == 6


def test_nominal_rates_per_phy():
    class C:
        phy = "he"
        channel_width_mhz = 20
        guard_interval_ns = 800
    he = minstrel.nominal_rates(C)
    assert set(he) == set(range(12)) and he[11] > he[0] > 0
    C.phy = "legacy"
    assert minstrel.nominal_rates(C)[7] == 54.0


def test_cli():
    from singleRun import single_run
    base = ["--seed", "1", "-t", "0.3", "-r", "1", "--ap-number", "1", "--gnb-number", "1"]
    runner = CliRunner()
    with runner.isolated_filesystem():
        ok = runner.invoke(single_run, base + ["--wifi-rate-adapt", "--wifi-rate-algo", "minstrel"])
        okhe = runner.invoke(single_run, base + ["--wifi-phy", "he", "--wifi-rate-adapt", "--wifi-rate-algo", "minstrel"])
        bad = runner.invoke(single_run, base + ["--wifi-rate-algo", "minstrel"])
    assert ok.exit_code == 0 and okhe.exit_code == 0, (ok.output + okhe.output)[-600:]
    assert bad.exit_code != 0
# Rashed-Step 25.B-10-20-2026-end
