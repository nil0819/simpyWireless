# Rashed-Step 19.A-10-07-2026-start
"""
Random access (Step 19.A) - the 4-step contention-based RACH a UE runs
before RRC connection setup (TS 38.321 5.1, TS 38.213 8), shared by
licensed NR and NR-U the same way ran/protocol/rrc.py is.

  Msg1  the UE waits for the next PRACH occasion (every prach_period_us,
        on a grid shared by every cell), picks one of n_preambles at
        random and sends it at open-loop power: target received power +
        path loss + (attempt - 1) x ramp step, capped at the UE's max
        power. NR-U: the UE must find the channel idle at the occasion
        (a short sensing check, like Type 2A, inside the serving gNB's
        COT - so only other transmitters count); if busy, that is an
        LBT failure - it tries the next occasion without ramping.
  Msg2  the gNB detects the preamble if its SINR over the PRACH
        bandwidth (139 subcarriers) reaches detect_snr_db - for NR-U
        counting the interference on the channel at that moment - and
        answers with a random access response (RAR) after
        rar_delay_us. NR-U: the RAR is downlink, so it also waits for
        the gNB's next channel occupancy time. No RAR within
        rar_window_us = try again (ramped).
  Msg3/4  RRCSetupRequest / RRCSetup - the existing RRC chain
        (rrc.py) carries on from here. If another UE picked the same
        preamble in the same occasion, both send Msg3 on the same grant
        and neither wins contention resolution: they find out when
        ra-ContentionResolutionTimer expires, back off uniformly in
        [0, backoff_us] and try again.
After preamble_trans_max preambles without success the procedure fails:
the UE goes back to IDLE and its RRC attach is abandoned (counted by the
RRC success rate, which until now could only be 100%).

Simplifications: no capture (a collision always fails both UEs); no
2-step RACH, contention-free RA or beam selection; licensed NR has no
PRACH interference (dedicated UL resources in synchronized cells).
"""
import math
import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from channel.channel import ActiveTx
from common.common_phy import thermal_noise_dbm, dbm_to_mw


@dataclass(frozen=True)
class RachConfig:
    prach_period_us: float = 10_000.0         # one PRACH occasion per 10 ms frame
    n_preambles: int = 64
    target_rx_power_dbm: float = -100.0        # preambleReceivedTargetPower
    ramp_step_db: float = 2.0                  # powerRampingStep
    preamble_trans_max: int = 10               # preambleTransMax
    detect_snr_db: float = -10.0               # preamble detection threshold
    rar_delay_us: float = 1000.0               # gNB processing before the RAR
    rar_window_us: float = 10_000.0            # ra-ResponseWindow
    contention_timer_us: float = 64_000.0      # ra-ContentionResolutionTimer
    backoff_us: float = 0.0                    # backoff indicator (0 = none)

    def __post_init__(self):
        for name in ("prach_period_us", "rar_window_us"):
            if not getattr(self, name) > 0:
                raise ValueError(f"RACH {name} must be > 0 (got {getattr(self, name)})")
        for name in ("rar_delay_us", "contention_timer_us", "backoff_us", "ramp_step_db"):
            if getattr(self, name) < 0:
                raise ValueError(f"RACH {name} must be >= 0 (got {getattr(self, name)})")
        if self.n_preambles < 1 or self.preamble_trans_max < 1:
            raise ValueError("RACH n_preambles and preamble_trans_max must be >= 1")


class RachCell:
    """One cell's PRACH: occasion bookkeeping plus the per-UE procedure.

    `gnb` must expose env, channel, current_pos(), name. Technology hooks:
    ue_max_power_dbm, f_hz, pl_exp, scs_khz, noise_figure_db and
    lbt (NR-U: True - sense before Msg1, RAR needs a COT, interference
    counts at detection).
    """

    def __init__(self, gnb: Any, config: RachConfig, *, ue_max_power_dbm: float, f_hz: float,
                 pl_exp: float, scs_khz: float, noise_figure_db: float, lbt: bool):
        self.gnb = gnb
        self.config = config
        self.ue_max_power_dbm = ue_max_power_dbm
        self.f_hz = f_hz
        self.pl_exp = pl_exp
        self.prach_bw_mhz = 139 * scs_khz / 1000.0
        self.noise_figure_db = noise_figure_db
        self.lbt = lbt
        self._occasions: Dict[float, List[tuple]] = {}

    def _next_occasion(self, now: float) -> float:
        p = self.config.prach_period_us
        k = math.floor(now / p + 1e-9) + 1
        return k * p

    def _path_loss_db(self, ue) -> float:
        """Path loss UE -> gNB incl. shadowing, from a 0 dBm probe."""
        env = self.gnb.env
        probe = ActiveTx(tx_id=ue.name, tx_pos=ue.current_pos(), tx_start=env.now,
                         rx_pos=self.gnb.current_pos(), tx_power_dbm=0.0, f_hz=self.f_hz,
                         pl_exp=self.pl_exp, t_end=env.now + 1, tech="NR",
                         bandwidth_mhz=self.prach_bw_mhz)
        return -self.gnb.channel._rx_pwr_dbm(probe, probe.rx_pos)

    def _preamble_snr_db(self, ue, tx_power_dbm: float) -> float:
        rx_dbm = tx_power_dbm - self._path_loss_db(ue)
        noise_mw = dbm_to_mw(thermal_noise_dbm(self.prach_bw_mhz, self.noise_figure_db))
        interf_mw = 0.0
        if self.lbt:
            interf_dbm = self.gnb.channel.sensed_energy_dbm(self.gnb.current_pos(), exclude_tx_id=self.gnb.name)
            interf_mw = dbm_to_mw(interf_dbm) if interf_dbm > -math.inf else 0.0
        return rx_dbm - 10.0 * math.log10(noise_mw + interf_mw)

    def _busy_for_prach(self, ue) -> bool:
        """NR-U channel check before Msg1. PRACH occasions are taken to sit
        in a gap the serving gNB leaves inside its own COT (Rel-16 lets a
        gNB share its COT for PRACH), so only OTHER transmitters - Wi-Fi,
        other cells - make it busy. Energy is summed at the UE like
        Channel.sensed_energy_dbm, minus the serving gNB's share."""
        ch = self.gnb.channel
        pos = ue.current_pos()
        total = ch.sensed_energy_dbm(pos, exclude_tx_id=ue.name, sense_f_hz=self.f_hz,
                                     sense_bw_mhz=ue.config_nr.bandwidth_mhz)
        if total == -math.inf:
            return False
        own_mw = sum(dbm_to_mw(ch._rx_pwr_dbm(t, pos)) for t in ch.active_txs
                     if t.tx_id == self.gnb.name and t.t_end > ch.env.now)
        rest_mw = dbm_to_mw(total) - own_mw
        return rest_mw > 0 and 10.0 * math.log10(rest_mw) >= ue.config_nr.ed_threshold_dbm

    def access(self, ue):
        """Generator -> True when Msg1/Msg2 succeed and contention is won,
        False after preamble_trans_max attempts."""
        env = self.gnb.env
        cfg = self.config
        ue.rach_started_at = env.now
        ue.rach_attempts = 0
        ue.rach_collisions = 0
        ue.rach_no_rar = 0
        ue.rach_lbt_failures = 0
        while ue.rach_attempts < cfg.preamble_trans_max:
            t_occ = self._next_occasion(env.now)
            yield env.timeout(t_occ - env.now)
            if self.lbt and self._busy_for_prach(ue):
                ue.rach_lbt_failures += 1
                continue
            ue.rach_attempts += 1
            power = min(self.ue_max_power_dbm,
                        cfg.target_rx_power_dbm + self._path_loss_db(ue) + (ue.rach_attempts - 1) * cfg.ramp_step_db)
            preamble = random.randrange(cfg.n_preambles)
            detected = self._preamble_snr_db(ue, power) >= cfg.detect_snr_db
            group = self._occasions.setdefault(t_occ, [])
            group.append((ue, preamble))
            window_end = t_occ + cfg.rar_window_us
            yield env.timeout(cfg.rar_delay_us)
            rar = detected
            if rar and self.lbt:
                rar = yield from self._wait_cot(window_end)
            # Everyone in this occasion is registered by now.
            collided = sum(1 for _u, p in group if p == preamble) > 1
            if not rar:
                ue.rach_no_rar += 1
                if env.now < window_end:
                    yield env.timeout(window_end - env.now)
                continue
            if collided:
                ue.rach_collisions += 1
                yield env.timeout(cfg.contention_timer_us)
                if cfg.backoff_us > 0:
                    yield env.timeout(random.uniform(0.0, cfg.backoff_us))
                continue
            ue.rach_done_at = env.now
            return True
        ue.rach_failed_at = env.now
        return False

    def _wait_cot(self, deadline: float):
        """NR-U: the RAR rides the gNB's next COT; False if none comes
        before the RAR window closes."""
        env = self.gnb.env
        g = self.gnb
        g._rrc_ul_waiters += 1
        if getattr(g.config_nr, "cot_model", "burst") == "slots":
            g._kick_slots()
        try:
            remaining = deadline - env.now
            if remaining <= 0:
                return False
            done = g._dl_cot_done
            res = yield done | env.timeout(remaining)
            return done in res
        finally:
            g._rrc_ul_waiters -= 1


def compute_rach_stats(ue_list: List[Any]) -> Dict[str, Any]:
    ran = [ue for ue in ue_list if getattr(ue, "rach_started_at", None) is not None]
    ok = [ue for ue in ran if getattr(ue, "rach_done_at", None) is not None]
    failed = [ue for ue in ran if getattr(ue, "rach_failed_at", None) is not None]
    lat = [ue.rach_done_at - ue.rach_started_at for ue in ok]
    return {
        "attempted": len(ran),
        "succeeded": len(ok),
        "failed": len(failed),
        "latencies_us": lat,
        "mean_latency_us": (sum(lat) / len(lat)) if lat else None,
        "mean_preambles": (sum(ue.rach_attempts for ue in ok) / len(ok)) if ok else None,
        "collisions": sum(ue.rach_collisions for ue in ran),
        "no_rar": sum(ue.rach_no_rar for ue in ran),
        "lbt_failures": sum(ue.rach_lbt_failures for ue in ran),
    }


def print_rach_stats(title: str, label: str, s: Dict[str, Any]) -> None:
    print(f"=== {title} ===")
    print(f"{label} RACH attempted: {s['attempted']}")
    print(f"{label} RACH succeeded: {s['succeeded']}")
    print(f"{label} RACH failed (preamble max reached): {s['failed']}")
    print(f"{label} RACH mean latency, start -> contention resolved (us): {s['mean_latency_us']}")
    print(f"{label} RACH mean preambles per success: {s['mean_preambles']}")
    print(f"{label} RACH preamble collisions: {s['collisions']}")
    print(f"{label} RACH preambles without RAR: {s['no_rar']}")
    if s["lbt_failures"]:
        print(f"{label} RACH LBT failures (channel busy at occasion): {s['lbt_failures']}")


def rach_config_from_cli(enabled: bool, prach_period_ms: Optional[float], backoff_ms: Optional[float],
                         rar_window_ms: Optional[float]) -> Optional[RachConfig]:
    if not enabled:
        if any(v is not None for v in (prach_period_ms, backoff_ms, rar_window_ms)):
            raise ValueError("--prach-period-ms / --rach-backoff-ms / --rar-window-ms require --rach.")
        return None
    kw = {}
    if prach_period_ms is not None:
        kw["prach_period_us"] = prach_period_ms * 1000.0
    if backoff_ms is not None:
        kw["backoff_us"] = backoff_ms * 1000.0
    if rar_window_ms is not None:
        kw["rar_window_us"] = rar_window_ms * 1000.0
    return RachConfig(**kw)
# Rashed-Step 19.A-10-07-2026-end
