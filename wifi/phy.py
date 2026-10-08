# Rashed-Step 20.C-10-08-2026-start
"""
802.11n/ac/ax PHY rates (Step 20.C): Config.phy = "ht" | "vht" | "he" with
Config.channel_width_mhz and Config.guard_interval_ns. "legacy" (the
default) is the original 802.11a table in Times.py, untouched.

Single spatial stream (no MIMO channel model, so more streams would only
multiply the rate for free). Data rate = N_SD x bits/subcarrier x code
rate / symbol time:
  - data subcarriers N_SD: HT 52 / 108 (20 / 40 MHz); VHT 52 / 108 / 234 /
    468 (20-160 MHz); HE (RU of the whole channel) 234 / 468 / 980 / 1960.
  - symbol: HT/VHT 3.2 us + GI 0.8 (long) or 0.4 (short); HE 12.8 us + GI
    0.8 / 1.6 / 3.2.
  - e.g. HT20 MCS 7 long GI 65 Mbps, VHT80 MCS 9 short GI 433.3, HE80 MCS
    11 GI 0.8 600.5 - the standard's rate tables.
Preamble (non-HT part + PHY-specific fields, one LTF): HT mixed 36 us,
VHT 40 us, HE SU 44 us. Duration = preamble + ceil((16 + bits + 6) /
N_DBPS) symbols. Control responses (ACK, CTS, Block Ack) stay non-HT
(duplicate) at a basic rate chosen by the data modulation: BPSK 6, QPSK
12, 16-QAM and up 24 Mbps.

Required SINR per MCS: representative values on the same modulation /
coding scale as the legacy table (BPSK 1/2 5 dB ... 64-QAM 3/4 25 dB),
extended for 64-QAM 5/6 (27), 256-QAM (30 / 32) and 1024-QAM (35 / 37).
The SINR is over the whole channel: a wider channel has 3 dB more noise
per doubling (thermal_noise_dbm uses the ActiveTx bandwidth).
"""
import math

from Times import Times, MCS as LEGACY_MCS, WIFI_MCS_SINR_THRESHOLDS_DB

PHYS = ("legacy", "ht", "vht", "he")
WIDTHS_MHZ = {"ht": (20, 40), "vht": (20, 40, 80, 160), "he": (20, 40, 80, 160)}
MAX_MCS = {"legacy": 7, "ht": 7, "vht": 9, "he": 11}
GI_NS = {"ht": (800, 400), "vht": (800, 400), "he": (800, 1600, 3200)}
PREAMBLE_US = {"ht": 36.0, "vht": 40.0, "he": 44.0}
N_SD = {"ht": {20: 52, 40: 108},
        "vht": {20: 52, 40: 108, 80: 234, 160: 468},
        "he": {20: 234, 40: 468, 80: 980, 160: 1960}}
# MCS -> (bits per subcarrier, code rate)
MODULATION = {0: (1, 1 / 2), 1: (2, 1 / 2), 2: (2, 3 / 4), 3: (4, 1 / 2), 4: (4, 3 / 4), 5: (6, 2 / 3),
              6: (6, 3 / 4), 7: (6, 5 / 6), 8: (8, 3 / 4), 9: (8, 5 / 6), 10: (10, 3 / 4), 11: (10, 5 / 6)}
HT_SINR_THRESHOLDS_DB = {0: 5.0, 1: 8.0, 2: 11.0, 3: 15.0, 4: 19.0, 5: 23.0, 6: 25.0, 7: 27.0,
                         8: 30.0, 9: 32.0, 10: 35.0, 11: 37.0}


def phy_of(config) -> str:
    return getattr(config, "phy", "legacy") or "legacy"


def sinr_table(config) -> dict:
    """MCS -> required SINR (dB) for this config's PHY."""
    p = phy_of(config)
    if p == "legacy":
        return WIFI_MCS_SINR_THRESHOLDS_DB
    return {m: v for m, v in HT_SINR_THRESHOLDS_DB.items() if m <= MAX_MCS[p]}


def symbol_us(phy: str, gi_ns: int) -> float:
    return (12.8 if phy == "he" else 3.2) + gi_ns / 1000.0


def ndbps(phy: str, width_mhz: int, mcs: int) -> float:
    bpsc, rate = MODULATION[mcs]
    return N_SD[phy][width_mhz] * bpsc * rate


def rate_mbps(phy: str, width_mhz: int, mcs: int, gi_ns: int) -> float:
    return ndbps(phy, width_mhz, mcs) / symbol_us(phy, gi_ns)


def validate(phy: str, width_mhz, mcs: int, gi_ns) -> None:
    if phy not in PHYS:
        raise ValueError(f"Wi-Fi phy must be one of {PHYS} (got {phy!r})")
    if phy == "legacy":
        return
    if width_mhz not in WIDTHS_MHZ[phy]:
        raise ValueError(f"{phy.upper()} channel width must be one of {WIDTHS_MHZ[phy]} MHz (got {width_mhz})")
    if gi_ns not in GI_NS[phy]:
        raise ValueError(f"{phy.upper()} guard interval must be one of {GI_NS[phy]} ns (got {gi_ns})")
    if not 0 <= mcs <= MAX_MCS[phy]:
        raise ValueError(f"{phy.upper()} MCS must be 0-{MAX_MCS[phy]} (got {mcs})")
    if phy == "vht" and width_mhz == 20 and mcs == 9:
        raise ValueError("VHT MCS 9 is not valid at 20 MHz with one spatial stream")


def ctrl_rate_mbps(config, mcs=None) -> int:
    """Basic rate (Mbps) for the control response to a data frame at mcs."""
    m = config.mcs if mcs is None else mcs
    if phy_of(config) == "legacy":
        return LEGACY_MCS[m][1]
    bpsc = MODULATION[m][0]
    return 24 if bpsc >= 4 else (12 if bpsc == 2 else 6)


class PhyTimes(Times):
    """Times for an HT / VHT / HE PPDU - same interface as Times (frame
    time, preamble, data_rate in bits/us, ACK time, IFS constants), so every
    caller (frames, A-MPDU, MAC exchange) works unchanged."""

    def __init__(self, payload: int, mcs: int, phy: str, width_mhz: int, gi_ns: int):
        self.payload = payload
        self.mcs = mcs
        self.phy = phy
        self.n_dbps = ndbps(phy, width_mhz, mcs)
        self.t_sym = symbol_us(phy, gi_ns)
        self.data_rate = self.n_dbps / self.t_sym            # [b/us]
        self.ctr_rate = ctrl_rate_mbps(_Cfg(phy, mcs))
        self.phy_data_rate = self.data_rate * 1e-6
        self.phy_ctr_rate = self.ctr_rate * 1e-6
        self.ofdm_preamble = PREAMBLE_US[phy]
        self.ofdm_signal = 0.0                                 # the SIG fields are in PREAMBLE_US

    def get_ppdu_frame_time(self, payload_bytes=None):
        payload = payload_bytes if payload_bytes is not None else self.payload
        bits = 16 + Times.mac_overhead + payload * 8 + 6       # service + MAC header/FCS + MSDU + tail
        return math.ceil(self.ofdm_preamble + math.ceil(bits / self.n_dbps) * self.t_sym)


class _Cfg:
    def __init__(self, phy, mcs):
        self.phy, self.mcs = phy, mcs


def make_times(config, payload: int, mcs: int):
    """Times for this config's PHY: the original Times for legacy (every
    earlier run), PhyTimes for HT / VHT / HE."""
    p = phy_of(config)
    if p == "legacy":
        return Times(payload, mcs)
    return PhyTimes(payload, mcs, p, config.channel_width_mhz, config.guard_interval_ns)
# Rashed-Step 20.C-10-08-2026-end
