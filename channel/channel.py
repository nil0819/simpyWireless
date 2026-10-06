from common.common import *
# from wifi.wifi import *
# from nru.nru import *

# Rashed-Step 3.B-01-12-2026-start
from dataclasses import dataclass
# Rashed-Step pre_18.A-10-04-2026-start
from dataclasses import field
# Rashed-Step pre_18.A-10-04-2026-end
import simpy
import math
from common.common_phy import rx_power_dbm, dbm_to_mw, mw_to_dbm, Pos, sample_shadow_db, thermal_noise_dbm, spectral_overlap_fraction
from typing import Optional, List
from typing import Any, List, Tuple
# Rashed-Step 8.A-08-06-2026-start
from common.packet import Packet
# Rashed-Step 8.A-08-06-2026-end
# Rashed-Step 3.B-01-12-2026-end


# Rashed-Step 3.B-01-12-2026-start
@dataclass
class ActiveTx:
    tx_id: str
    tx_pos: Pos
    # Rashed-Step 3.F-01-13-2026-start
    tx_start: int
    # Rashed-Step 3.F-01-13-2026-end
    # Rashed-Step 4.B_1-01-20-2026-start
    rx_pos: Pos 
    # Rashed-Step 4.B_1-01-20-2026-end
    tx_power_dbm: float
    f_hz: float
    pl_exp: float
    t_end: int
    tech: str  # "WiFi", "NRU", or "NR" (licensed, Step 6.B)
    # Rashed-Step 5.C-02-06-2026-start
    # Receiver-side noise params for this link, used to derive the SINR
    # noise floor (see common_phy.thermal_noise_dbm). Defaults (20 MHz,
    # 7 dB NF -> ~-94 dBm) match the old hardcoded constant, so any code
    # constructing ActiveTx without passing these (e.g. the standalone
    # test/*.py files) is unaffected.
    bandwidth_mhz: float = 20.0
    noise_figure_db: float = 7.0
    # Rashed-Step 5.C-02-06-2026-end
    # Rashed-Step 8.A-08-06-2026-start
    # Optional reference to the Packet this on-air transmission is
    # carrying - None by default (every existing ActiveTx(...) call
    # site, including the standalone test/*.py files that construct
    # ActiveTx directly, is unaffected). Lets a sniffer/spectrum
    # analyzer (generic.generic_device.GenericWirelessDevice.sniff(),
    # Step 7.A) eventually inspect real packet identity/size instead of
    # only PHY-level tx_id/tech - not wired up yet as of Step 8.A/8.B,
    # sniff() still only reports what channel.active_txs already
    # exposes today.
    packet: Optional[Packet] = None
    # Rashed-Step 8.A-08-06-2026-end
    # Rashed-Step pre_18.A-10-04-2026-start
    # Every other transmission that overlapped this one in time at any
    # point, as TxSnapshot records (plain values, no object references,
    # so long runs don't keep the whole history alive). Filled by
    # Channel.register_tx(); read by Channel.sinr_db() so interference
    # that ENDED before this transmission still counts - see sinr_db().
    overlap_history: list = field(default_factory=list, repr=False, compare=False)
    # Unique per registered transmission (set by Channel.register_tx), so
    # sinr_db() can tell "the same transmission, on air AND remembered"
    # apart from DIFFERENT transmissions sharing tx_id and timing -
    # licensed NR registers one ActiveTx per UE allocation, all named
    # after the gNB, in the same slot. -1 = never registered.
    uid: int = field(default=-1, repr=False, compare=False)
    # Rashed-Step pre_18.A-10-04-2026-end
    # Rashed-Step pre_18.F-10-06-2026-start
    # Name of the cell whose scheduler placed this transmission on its
    # own resource blocks (OFDMA), or None. Transmissions sharing a
    # non-None value use orthogonal RBs of one carrier, so sinr_db()
    # doesn't count them as interference to each other - the same way it
    # already skips a gNB's own per-UE downlink allocations by tx_id.
    # Set on licensed NR uplink (several UEs per slot, different tx_ids).
    ofdma_cell: Optional[str] = field(default=None, compare=False)
    # Rashed-Step pre_18.F-10-06-2026-end
# Rashed-Step 3.B-01-12-2026-end


# Rashed-Step pre_18.A-10-04-2026-start
@dataclass(frozen=True)
class TxSnapshot:
    """What sinr_db() needs to know about an interferer after it has
    left the air: same attribute names as ActiveTx, so _rx_pwr_dbm()
    works on either."""
    tx_id: str
    tx_pos: Pos
    tx_start: float
    t_end: float
    tx_power_dbm: float
    f_hz: float
    pl_exp: float
    bandwidth_mhz: float
    uid: int = -1
    # Rashed-Step pre_18.F-10-06-2026-start
    ofdma_cell: Optional[str] = None
    # Rashed-Step pre_18.F-10-06-2026-end

    @staticmethod
    def of(tx: "ActiveTx") -> "TxSnapshot":
        return TxSnapshot(tx.tx_id, tx.tx_pos, tx.tx_start, tx.t_end,
                          tx.tx_power_dbm, tx.f_hz, tx.pl_exp, tx.bandwidth_mhz, tx.uid,
                          # Rashed-Step pre_18.F-10-06-2026-start
                          tx.ofdma_cell)
                          # Rashed-Step pre_18.F-10-06-2026-end
# Rashed-Step pre_18.A-10-04-2026-end


@dataclass()
class Channel:
    # lock for the stations with the longest frame to transmit
    # Rashed-Step 5.E.1-02-06-2026-start
    # BUGFIX: this used to be THE ONE tx_queue shared by WiFi AND NR-U
    # (and the rogue AP), so even after Step 5.E made CCA/SINR
    # frequency-aware, WiFi and NR-U on completely separate, non-
    # overlapping frequencies still couldn't transmit "at the same time"
    # in the MAC layer - they were still taking turns holding this single
    # capacity=1 resource. Confirmed by comparing WiFi running alone
    # (2521 succ in a 1s test) vs WiFi + a gNB on a totally separate
    # frequency (394 succ) - should have been ~equal if truly independent.
    # This field is now WiFi's queue specifically; see tx_queue_nru below
    # for NR-U's own queue.
    # Rashed-Step 5.E.1-02-06-2026-end
    tx_queue: simpy.PreemptiveResource
    # channel lock (locked when there is ongoing transmission)
    tx_lock: simpy.Resource
    n_of_stations: int  # number of transmitting stations in the channel
    n_of_gNB: int
    backoffs: Dict[int, Dict[int, int]]
    airtime_data: Dict[str, int]
    airtime_control: Dict[str, int]
    airtime_data_NR: Dict[str, int]
    airtime_control_NR: Dict[str, int]
    # transmitting stations in the channel
    tx_list: List[Any] = field(default_factory=list)
    back_off_list: List[Any] = field(
        default_factory=list)  # stations in backoff phase
    # transmitting stations in the channel
    tx_list_NR: List[Any] = field(default_factory=list)
    back_off_list_NR: List[Any] = field(
        default_factory=list)  # stations in backoff phase
    # problem list of station objects, what if we 2 differenet station objects???

    failed_transmissions: int = 0  # total failed transmissions
    succeeded_transmissions: int = 0  # total succeeded transmissions
    bytes_sent: int = 0  # total bytes sent
    failed_transmissions_NR: int = 0  # total failed transmissions
    succeeded_transmissions_NR: int = 0  # total succeeded transmissions

    # Rashed-Step 6.B-07-31-2026-start
    # Licensed 5G NR (as opposed to NR-U, unlicensed) - separate counters/
    # airtime dicts so its stats never get mixed up with NR-U's. All have
    # defaults so simulation.py's Channel(...) call and the standalone
    # test/*.py files (which construct Channel directly, without knowing
    # about licensed NR at all) don't need to change.
    failed_transmissions_NRL: int = 0
    succeeded_transmissions_NRL: int = 0
    airtime_data_NRL: Dict[str, int] = field(default_factory=dict)
    airtime_control_NRL: Dict[str, int] = field(default_factory=dict)
    # Rashed-Step 6.B-07-31-2026-end


    # Rashed-Step 3.B-01-12-2026-start
    active_txs: List[ActiveTx] = field(default_factory=list)
    state_changed: simpy.Event = field(init=False)
    env: simpy.Environment = field(init=False)
    # Rashed-Step 3.B-01-12-2026-end

    # Rashed-Step 5.B-02-06-2026-start
    # 0.0 = shadowing disabled (default - deterministic path loss only,
    # matches pre-Step-5.B behavior bit-for-bit). Typical indoor log-normal
    # shadowing sigma is ~4-8 dB.
    shadowing_sigma_db: float = 0.0
    # One stable shadow draw per (transmitter, receiver position) pair,
    # cached for the life of the run - "once per link", not re-rolled every
    # transmission. Keyed by rx_pos rather than a receiver id since that's
    # what's already available everywhere shadow_db() is called from.
    shadow_cache: Dict[Tuple[str, Pos], float] = field(default_factory=dict)
    # Rashed-Step 5.B-02-06-2026-end

    # Rashed-Step 5.E.1-02-06-2026-start
    # NR-U's own tx_queue, separate from WiFi's (tx_queue above). Optional/
    # None by default and lazily built in __post_init__ (needs a real
    # simpy.Environment, which isn't available until construction time via
    # tx_lock._env) so existing callers - simulation.py's Channel(...) and
    # the 3 standalone test/*.py files - don't need to be touched just to
    # keep constructing Channel the way they already do.
    tx_queue_nru: Optional[simpy.PriorityResource] = None
    # Rashed-Step 5.E.1-02-06-2026-end

     # Rashed-Step 3.B-01-12-2026-start
    def __post_init__(self):
            self.env = self.tx_lock._env
            self.state_changed = self.env.event()
            # Rashed-Step 5.E.1-02-06-2026-start
            if self.tx_queue_nru is None:
                self.tx_queue_nru = simpy.PriorityResource(self.env, capacity=1)
            # Rashed-Step 5.E.1-02-06-2026-end


    def _pulse_state_changed(self):
        # Rashed-Step 3.F-12-26-2025-start
        #print(self.env.now, "STATE_CHANGED PULSE", len(self.active_txs))
        # Rashed-Step 3.F-12-26-2025-end
        
        if not self.state_changed.triggered:
            self.state_changed.succeed()
        self.state_changed = self.env.event()


    def register_tx(self, tx: ActiveTx):
         # Rashed-Step pre_18.A-10-04-2026-start
         self._tx_serial = getattr(self, "_tx_serial", 0) + 1
         tx.uid = self._tx_serial
         # Record every time-overlapping pair both ways, so each side's
         # SINR can count the other even after it has left the air (see
         # sinr_db()). active_txs may still hold entries past their t_end
         # (pruned lazily), hence the explicit time check.
         for other in self.active_txs:
              if other is tx or other.tx_id == tx.tx_id:
                   continue
              if other.tx_start < tx.t_end and other.t_end > tx.tx_start:
                   other.overlap_history.append(TxSnapshot.of(tx))
                   tx.overlap_history.append(TxSnapshot.of(other))
         # Rashed-Step pre_18.A-10-04-2026-end
         self.active_txs.append(tx)
         self._pulse_state_changed()

    # Rashed-Step 3.F-01-13-2026-start
    # Rashed-Step 5.1-02-06-2026-start
    # BUGFIX: this was one of TWO places adding to airtime_data/
    # airtime_data_NR on every successful transmission - wifi.py's
    # sent_completed(), nru.py's send_transmission() post-block, and
    # attacker/roguewificad.py's sent_completed() each did it a second
    # time (leftover from before this method existed), so every success
    # was counted twice and occupancy/efficiency were ~2x inflated (could
    # even exceed 1.0 for a single node, which is physically impossible).
    # This is now the single source of truth: success is passed in and
    # airtime is only recorded when the transmission actually succeeded.
    def unregister_tx(self, tx: ActiveTx, success: bool = True):
    # Rashed-Step 5.1-02-06-2026-end
    # Rashed-Step 6.C-08-05-2026-start
    # BUGFIX: this used to gate the ENTIRE airtime-recording block below
    # behind `if tx in self.active_txs`. But sensed_energy_dbm() (called
    # by every node's is_busy() sensing, from ANY technology sharing the
    # channel) prunes any ActiveTx past its t_end out of active_txs as a
    # side effect - if some OTHER node's sensing call happened to prune
    # this tx before its OWN owner got a chance to call unregister_tx()
    # on it, the old code would silently skip recording airtime for it
    # entirely, even though it still counted as a success (sent_completed()
    # isn't gated on active_txs membership, so the success counter and
    # the airtime bookkeeping could go out of sync). Confirmed happening
    # for real: 4 of 14 NR-U successes in a mixed WiFi+NR-U run lost
    # their airtime this way (see "Project details/Step 6.txt", "BUG
    # FOUND WHILE VERIFYING"). Fixed by computing dur/recording airtime
    # unconditionally from the tx object itself - it's self-contained
    # (t_start/t_end don't stop being valid just because another
    # process's sensing call already evicted it from active_txs) - only
    # the actual list removal still needs the membership check, to avoid
    # a ValueError on an already-pruned entry.
         if tx in self.active_txs:
              self.active_txs.remove(tx)

         dur = max(0, tx.t_end - tx.tx_start)

         if success:
             if tx.tech == "WiFi":
                  self.airtime_data[tx.tx_id] = self.airtime_data.get(tx.tx_id, 0) + dur
             elif tx.tech == "NRU":
                  self.airtime_data_NR[tx.tx_id] = self.airtime_data_NR.get(tx.tx_id, 0) + dur
             elif tx.tech == "NR":
                  self.airtime_data_NRL[tx.tx_id] = self.airtime_data_NRL.get(tx.tx_id, 0) + dur

         self._pulse_state_changed()
    # Rashed-Step 6.C-08-05-2026-end

    # Rashed-Step 3.F-01-13-2026-end

    # Rashed-Step 3.B-01-12-2026-end


    # Rashed-Step 5.B-02-06-2026-start
    def shadow_db(self, tx_id: str, rx_pos: Pos) -> float:
        """
        Stable log-normal shadow-fading value for the (tx_id, rx_pos) link,
        sampled once and cached for the rest of the run. Returns 0.0
        immediately (no cache write, no RNG draw) when shadowing_sigma_db
        <= 0, so disabling shadowing is exactly equivalent to the old
        deterministic-only path loss.
        """
        if self.shadowing_sigma_db <= 0.0:
            return 0.0
        key = (tx_id, rx_pos)
        if key not in self.shadow_cache:
            self.shadow_cache[key] = sample_shadow_db(self.shadowing_sigma_db)
        return self.shadow_cache[key]
    # Rashed-Step 5.B-02-06-2026-end

    # Rashed-Step 3.C-01-12-2026-start
    # Rashed-Step 5.E-02-06-2026-start
    # sense_f_hz/sense_bw_mhz are optional and default to None, meaning
    # "sum every active transmitter's power regardless of frequency" - the
    # old behavior, kept for backward compatibility with callers that
    # don't know/care about frequency (the standalone test/*.py files
    # construct Channel/ActiveTx directly without ever passing these).
    # When a caller DOES pass its own channel (f_hz + bandwidth_mhz),
    # each transmitter's contribution is scaled by how much spectral
    # overlap it actually has with the sensing node's own channel - a
    # node tuned to a non-overlapping channel shouldn't defer to energy
    # it can't actually hear.
    def sensed_energy_dbm(self, sense_pos: Pos, exclude_tx_id: Optional[str] = None,
                           sense_f_hz: Optional[float] = None, sense_bw_mhz: Optional[float] = None) -> float:
    # Rashed-Step 5.E-02-06-2026-end
        total_mw = 0.0
        now = self.env.now

        expired = [t for t in self.active_txs if t.t_end <= now]

        # Rashed-Step 3.F-01-13-2026-start
        # for t in expired:
        #     self.active_txs.remove(t)
        self.active_txs = [t for t in self.active_txs if t.t_end > now]

        # Rashed-Step 3.F-01-13-2026-end

        for tx in self.active_txs:
             if exclude_tx_id is not None and tx.tx_id == exclude_tx_id:
                  continue
             # Rashed-Step 5.E-02-06-2026-start
             if sense_f_hz is not None:
                 overlap = spectral_overlap_fraction(sense_f_hz, sense_bw_mhz, tx.f_hz, tx.bandwidth_mhz)
                 if overlap <= 0.0:
                     continue
             else:
                 overlap = 1.0
             # Rashed-Step 5.E-02-06-2026-end
             d = dist(tx.tx_pos, sense_pos)
             # Rashed-Step 5.B-02-06-2026-start
             shadow = self.shadow_db(tx.tx_id, sense_pos)
             pr = rx_power_dbm(tx.tx_power_dbm, d, tx.f_hz, n = tx.pl_exp, shadow_db=shadow)
             # Rashed-Step 5.B-02-06-2026-end
             # Rashed-Step 5.E-02-06-2026-start
             total_mw += dbm_to_mw(pr) * overlap
             # Rashed-Step 5.E-02-06-2026-end

        if total_mw == 0.0:
            return -math.inf

        return mw_to_dbm(total_mw)


    # Rashed-Step 5.E-02-06-2026-start
    def is_busy(self, sense_pos: Pos, ed_threshold_dbm: float, exclude_tx_id: Optional[str] = None,
                sense_f_hz: Optional[float] = None, sense_bw_mhz: Optional[float] = None) -> bool:
        return self.sensed_energy_dbm(sense_pos, exclude_tx_id, sense_f_hz, sense_bw_mhz) >= ed_threshold_dbm
    # Rashed-Step 5.E-02-06-2026-end


    # Rashed-Step 3.C-01-12-2026-end



    # Rashed-Step 4.C-01-20-2026-start

    def _rx_pwr_dbm(self, tx:ActiveTx, at_pos: Pos) -> float:
         d = dist(tx.tx_pos, at_pos)
         # Rashed-Step 5.B-02-06-2026-start
         shadow = self.shadow_db(tx.tx_id, at_pos)
         return rx_power_dbm(tx.tx_power_dbm, d, tx.f_hz, n=tx.pl_exp, shadow_db=shadow)
         # Rashed-Step 5.B-02-06-2026-end
    
    # Rashed-Step 5.C-02-06-2026-start
    # BUGFIX/upgrade: noise_dbm used to default to a hardcoded -94.0 dBm
    # constant regardless of bandwidth or receiver noise figure. Now
    # defaults to None, meaning "derive it from target's own
    # bandwidth_mhz/noise_figure_db via thermal_noise_dbm()" - callers can
    # still pass an explicit noise_dbm to override (e.g. for tests that
    # want a fixed noise value).
    def sinr_db(self, target: ActiveTx, noise_dbm: Optional[float] = None) -> float:
        """
        SINR at target.rx_pos considering only transmissions that overlap in time
        with [target.tx_start, target.t_end].

        Rashed-Step pre_18.A (2026-10-04) - HYBRID rule (Rashed's choice
        after comparing end-only / time-averaged / hybrid / worst case on
        the same scenarios - see Step pre_18.txt):
          - Wi-Fi target (tech "WiFi"): every interferer that overlapped
            it at any point counts at FULL power - a Wi-Fi frame is one
            decode unit, so a strong hit on any part of it ruins it.
          - Any other target (NR-U, licensed NR, generic devices): each
            interferer is weighted by the fraction of the target's
            duration it overlapped ("effective SINR") - an NR-U/NR burst
            is many separately checked slots, so a short hit only spoils
            part of it.
        Before this,
        only transmissions still in active_txs when SINR was evaluated
        (at the target's END) counted, at full power - so a short Wi-Fi
        frame (242us) that hit a long NR-U transmission (3-6ms) and ended
        first was ignored, while the reverse was almost always counted:
        a one-sided bias in NR-U's favor (Step 17.txt, 17.G FINDING).
        Now: transmissions on the air now (as before - this also covers
        never-registered trial estimates like licensed NR's scheduler)
        PLUS target.overlap_history (ones that already ended). An
        interferer covering the whole target gets weight exactly 1.0, so
        fully aligned cases (e.g. licensed NR's synchronized slots)
        compute exactly as before.
        """
        if noise_dbm is None:
            noise_dbm = thermal_noise_dbm(target.bandwidth_mhz, target.noise_figure_db)
        # Rashed-Step 5.C-02-06-2026-end
        s_dbm = self._rx_pwr_dbm(target, target.rx_pos)
        s_mw = dbm_to_mw(s_dbm)

        i_mw = 0.0

        # Rashed-Step pre_18.A-10-04-2026-start
        duration = target.t_end - target.tx_start

        def time_weight(other) -> float:
            if duration <= 0 or target.tech == "WiFi":
                return 1.0
            covered = min(other.t_end, target.t_end) - max(other.tx_start, target.tx_start)
            if covered >= duration:
                return 1.0
            return max(0.0, covered / duration)

        seen = set()
        # On the air now first (same order as before, so shadowing draws
        # happen in the same order), then remembered ones that ended.
        candidates = list(self.active_txs) + list(getattr(target, "overlap_history", ()))
        # Rashed-Step pre_18.A-10-04-2026-end

        for other in candidates:
            if other.tx_id == target.tx_id:
                continue
            # Rashed-Step pre_18.F-10-06-2026-start
            if target.ofdma_cell is not None and getattr(other, "ofdma_cell", None) == target.ofdma_cell:
                continue
            # Rashed-Step pre_18.F-10-06-2026-end

            if not (other.tx_start < target.t_end and other.t_end > target.tx_start):
                continue

            # Rashed-Step pre_18.A-10-04-2026-start
            key = other.uid if other.uid >= 0 else ("unregistered", id(other))
            if key in seen:
                continue
            seen.add(key)
            # Rashed-Step pre_18.A-10-04-2026-end

            # Rashed-Step 5.E-02-06-2026-start
            # BUGFIX/upgrade: interference used to be counted at full
            # strength regardless of frequency - two techs on completely
            # different, non-overlapping channels would still "interfere"
            # here just because they were both active_txs. Now scaled by
            # how much of the *victim's* channel bandwidth the interferer
            # actually overlaps (1.0 = full co-channel, same as before
            # Step 5.E when both were hardcoded to 5.18 GHz; 0.0 = fully
            # separated channels, no RF interference).
            overlap = spectral_overlap_fraction(
                target.f_hz, target.bandwidth_mhz, other.f_hz, other.bandwidth_mhz
            )
            if overlap <= 0.0:
                continue
            i_dbm = self._rx_pwr_dbm(other, target.rx_pos)
            i_mw += dbm_to_mw(i_dbm) * overlap * time_weight(other)  # Rashed-Step pre_18.A-10-04-2026
            # Rashed-Step 5.E-02-06-2026-end

        n_mw = dbm_to_mw(noise_dbm)

        # guard against weird numerical issues

        denom = i_mw + n_mw

        if denom == 0.0:
             return float('inf')
        
        sinr_linear = s_mw / denom

        return 10.0 * math.log10(sinr_linear)
    
        

        
         




    # Rashed-Step 4.C-01-20-2026-end
