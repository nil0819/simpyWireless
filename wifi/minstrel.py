# Rashed-Step 25.B-10-20-2026-start
"""
Minstrel-style Wi-Fi rate adaptation (Step 25.B, --wifi-rate-algo minstrel).

ARF (the default, wifi.WiFi.rate_adapt_record_result) steps the MCS down
after a few failures and up after a run of successes, so collisions in a
busy cell read as a bad channel and push the rate down. Minstrel (Linux
mac80211, simplified) chooses by expected throughput instead:

  - per link and MCS: attempts / successes in the current interval; every
    UPDATE_US (100 ms) an EWMA success probability p (75 % old, 25 % new);
  - expected throughput = nominal rate x p (0 when p < 10 %);
  - each transmission uses the best-throughput MCS, except LOOKAROUND
    (10 %) of them, which probe a faster MCS (one chosen at random among
    the faster ones) so a better rate is found when the channel allows it;
  - before any statistics: the configured MCS.

A choice holds until its result is recorded (frame time, decode threshold
and control rate all ask for the MCS of one transmission); every result
recorded at the same instant - an A-MPDU's MPDUs - counts for that MCS.
The probes use the node's own RNG, seeded from one draw of the global
random module when the node is built; the probes themselves never touch
the global random stream.
"""
import random
from typing import Dict

UPDATE_US = 100_000.0
EWMA_OLD = 0.75
LOOKAROUND = 0.10
MIN_PROB = 0.10


class Minstrel:
    def __init__(self, rates: Dict[int, float], start_mcs: int, seed: int):
        self.rates = dict(rates)                 # MCS -> nominal rate (Mbps)
        self.start = start_mcs if start_mcs in self.rates else min(self.rates)
        self.rng = random.Random(seed)
        self.links: Dict[str, dict] = {}

    def _link(self, key: str) -> dict:
        st = self.links.get(key)
        if st is None:
            st = self.links[key] = {"att": {}, "succ": {}, "prob": {}, "next_update": UPDATE_US,
                                    "best": self.start, "pending": None, "used": None}
        return st

    def _update(self, st: dict, now: float) -> None:
        if now < st["next_update"]:
            return
        for m, a in st["att"].items():
            if a > 0:
                p = st["succ"].get(m, 0) / a
                old = st["prob"].get(m)
                st["prob"][m] = p if old is None else EWMA_OLD * old + (1 - EWMA_OLD) * p
        st["att"].clear()
        st["succ"].clear()
        st["next_update"] = now + UPDATE_US
        tp = {m: (self.rates[m] * p if p >= MIN_PROB else 0.0) for m, p in st["prob"].items()}
        if tp and max(tp.values()) > 0:
            st["best"] = max(tp, key=lambda m: (tp[m], st["prob"][m]))

    def choose(self, key: str, now: float) -> int:
        st = self._link(key)
        if st["pending"] is None:
            self._update(st, now)
            mcs = st["best"]
            if self.rng.random() < LOOKAROUND:
                faster = [m for m in self.rates if self.rates[m] > self.rates[mcs]]
                if faster:
                    mcs = self.rng.choice(sorted(faster))
            st["pending"] = mcs
        return st["pending"]

    def record(self, key: str, success: bool, now: float) -> None:
        st = self._link(key)
        if st["pending"] is not None:
            st["used"], st["pending"] = st["pending"], None
        mcs = st["used"] if st["used"] is not None else st["best"]
        st["att"][mcs] = st["att"].get(mcs, 0) + 1
        if success:
            st["succ"][mcs] = st["succ"].get(mcs, 0) + 1


def nominal_rates(config) -> Dict[int, float]:
    """MCS -> nominal data rate (Mbps) for this Wi-Fi config's PHY."""
    from wifi import phy as wifi_phy
    p = wifi_phy.phy_of(config)
    table = wifi_phy.sinr_table(config)
    if p == "legacy":
        from Times import MCS
        return {m: float(MCS[m][0]) for m in table}
    return {m: wifi_phy.rate_mbps(p, int(config.channel_width_mhz), m, int(config.guard_interval_ns),
                                  wifi_phy.n_ss(config)) for m in table}  # 25.C: x spatial streams
# Rashed-Step 25.B-10-20-2026-end
