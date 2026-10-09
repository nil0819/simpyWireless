# Rashed-Step 20.D-10-08-2026-start
"""
802.11 management plane (Step 20.D, Config.management = MgmtConfig()).

  - Beacons: every AP sends a beacon at each target beacon transmission
    time (TBTT, every beacon_interval_us = 102.4 ms by default, a random
    offset per AP), after the channel has been idle for PIFS (SIFS + slot
    = 25 us, no backoff - the priority beacons get), at the 6 Mbps basic
    rate. Every STA that decodes it (SINR >= the 6 Mbps threshold) records
    the AP's RSSI.
  - Joining: a STA starts unassociated, listens for scan_us (passive scan
    on this channel), then tries the strongest AP: open-system
    authentication (request, response) and association (request,
    response) - four management frames at 6 Mbps, each sent after
    DIFS + backoff, ACKed (on the air with --wifi-mac-exchange), retried
    up to r_limit. If a frame fails for good, the next AP is tried, then
    a rescan.
  - Data: an AP sends downlink only to its associated STAs (round robin,
    one per channel access) and waits while it has none; a STA sends
    uplink only while associated, to the AP it associated with.
  - Roaming: once a beacon interval a STA checks its AP's latest beacon
    RSSI. Below roam_threshold_dbm (or no beacon for beacon_loss_intervals)
    with another AP heard at least roam_hysteresis_db stronger, it leaves
    (disassociation) and reassociates there (authentication +
    reassociation). The interruption (leave -> associated again) is
    recorded. No candidate and beacons lost: full rescan.

Senders are proxies named "<node>/mgmt" and "<AP>/beacon": they use the
same DCF access and the same channel, but as their own transmitter IDs,
so an AP's data process and its management frames sense each other like
any two transmitters. Not modeled: active scanning (probe requests),
other channels, WPA2 4-way handshake, power save, 802.11k/v/r.
"""
import random
from dataclasses import dataclass
from typing import Dict

import simpy

from channel.channel import ActiveTx
from common.error_model import decode_ok
from Times import Times, WIFI_MCS_SINR_THRESHOLDS_DB
from ran.protocol.channel_access import DcfChannelAccess, sense_idle_for
from wifi import mac as wifi_mac

_DCF = DcfChannelAccess(Times.t_slot, Times.t_difs)
PIFS_US = Times.t_sifs + Times.t_slot
BASIC_RATE_MBPS = 6
REQUIRED_SINR_DB = WIFI_MCS_SINR_THRESHOLDS_DB[0]


@dataclass
class MgmtConfig:
    beacon_interval_us: float = 102400.0       # 100 TU
    beacon_bytes: int = 250
    scan_us: float = 120000.0                  # passive-scan dwell (> one beacon interval)
    mgmt_frame_bytes: int = 80                 # authentication / association frames
    roam_threshold_dbm: float = -75.0
    roam_hysteresis_db: float = 6.0
    beacon_loss_intervals: int = 4


class _Sender:
    """A DCF transmitter identity for management frames / beacons."""

    def __init__(self, name, owner, env, channel, config, pos_fn):
        self.name, self.owner = name, owner
        self.col = ""                       # common.log() colour
        self.env, self.channel, self.config = env, channel, config
        self.current_pos = pos_fn
        self.cw_min, self.cw_max = config.cw_min, config.cw_max
        self.failed_transmissions_in_row = 0
        self.mac_stats = wifi_mac.new_stats()
        self.lock = simpy.Resource(env, capacity=1)

    def tx(self, rx_pos, nbytes):
        cfg = self.config
        now = self.env.now
        dur = wifi_mac.ctrl_frame_us(nbytes, BASIC_RATE_MBPS)
        return ActiveTx(tx_id=self.name, tx_pos=self.current_pos(), rx_pos=rx_pos, tx_start=now,
                        tx_power_dbm=cfg.tx_power_dbm, f_hz=cfg.f_ghz, pl_exp=cfg.pl_exp, t_end=now + dur,
                        tech="WiFi", bandwidth_mhz=cfg.bandwidth_mhz, noise_figure_db=cfg.noise_figure_db)


class StaState:
    def __init__(self, sta, sender, env):
        self.sta, self.sender = sta, sender
        self.state = "scanning"
        self.ap = None
        self.rssi: Dict[str, tuple] = {}        # AP name -> (rssi dBm, time heard)
        self.assoc_event = env.event()
        self.assoc_time_us = None
        self.joins_failed = 0
        self.roams = 0
        self.interruptions_us = []


class WifiManagement:
    def __init__(self, env, channel, aps, stas, config):
        self.env, self.channel, self.config = env, channel, config
        self.mc = config.management
        self.aps = list(aps)
        self.stats = {"beacons": 0, "beacon_airtime_us": 0.0, "mgmt_frames": 0, "mgmt_retries": 0}
        self.ap_by_name = {ap.name: ap for ap in self.aps}
        self.ap_sender, self.beacon_sender = {}, {}
        for ap in self.aps:
            ap._mgmt = self
            ap.associated = []
            ap._assoc_event = env.event()
            ap._mgmt_rx = None
            ap._mgmt_rr = 0
            self.ap_sender[ap.name] = _Sender(f"{ap.name}/mgmt", ap.name, env, channel, config, ap.current_pos)
            self.beacon_sender[ap.name] = _Sender(f"{ap.name}/beacon", ap.name, env, channel, config, ap.current_pos)
            env.process(self._beacons(ap))
        self.sta_state = {}
        for sta in stas:
            st = StaState(sta, _Sender(f"{sta.name}/mgmt", sta.name, env, channel, config, sta.current_pos), env)
            sta._mgmt = self
            self.sta_state[sta.name] = st
            env.process(self._sta_process(st))

    # -------------------------------------------------------------- data plane gates
    def wait_ap_has_stas(self, ap):
        """Generator: until the AP has an associated STA; picks the next one
        (round robin) as this channel access's downlink receiver."""
        while not ap.associated:
            yield ap._assoc_event
        ap._mgmt_rx = ap.associated[ap._mgmt_rr % len(ap.associated)]
        ap._mgmt_rr += 1

    def current_rx(self, ap):
        """This access's receiver; if it left meanwhile, another associated
        STA - or, with none left, still the one picked (the AP only learns
        of a departure later; no disassociation frame is modeled)."""
        rx = ap._mgmt_rx
        if rx is not None and rx not in ap.associated and ap.associated:
            rx = ap.associated[0]
        return rx

    def wait_sta_associated(self, sta):
        st = self.sta_state[sta.name]
        while st.state != "associated":
            yield st.assoc_event

    # -------------------------------------------------------------- beacons
    def _beacons(self, ap):
        snd = self.beacon_sender[ap.name]
        busy = lambda: _DCF._busy(snd)
        tbtt = random.uniform(0.0, self.mc.beacon_interval_us)
        yield self.env.timeout(tbtt)
        while True:
            while True:
                while busy():
                    yield self.channel.state_changed
                if (yield from sense_idle_for(snd, PIFS_US, busy)):
                    break
            tx = snd.tx(ap.current_pos(), self.mc.beacon_bytes)
            self.channel.register_tx(tx)
            try:
                yield self.env.timeout(tx.t_end - tx.tx_start)
                self._hear_beacon(ap, tx)
                yield self.env.timeout(0)
            finally:
                self.channel.unregister_control_tx(tx, self.channel.airtime_control, account_to=ap.name)
            self.stats["beacons"] += 1
            self.stats["beacon_airtime_us"] += tx.t_end - tx.tx_start
            tbtt += self.mc.beacon_interval_us
            yield self.env.timeout(max(0.0, tbtt - self.env.now))

    def _hear_beacon(self, ap, tx):
        em = getattr(self.config, "error_model", None)
        for st in self.sta_state.values():
            pos = st.sta.current_pos()
            view = ActiveTx(tx_id=tx.tx_id, tx_pos=tx.tx_pos, rx_pos=pos, tx_start=tx.tx_start,
                            tx_power_dbm=tx.tx_power_dbm, f_hz=tx.f_hz, pl_exp=tx.pl_exp, t_end=tx.t_end,
                            tech="WiFi", bandwidth_mhz=tx.bandwidth_mhz, noise_figure_db=tx.noise_figure_db)
            view.overlap_history = tx.overlap_history
            if decode_ok(em, self.channel.sinr_db(view), REQUIRED_SINR_DB):
                st.rssi[ap.name] = (self.channel._rx_pwr_dbm(view, pos), self.env.now)

    # -------------------------------------------------------------- management frames
    def _send(self, snd, rx_name, rx_pos_fn, nbytes):
        """Generator: one management frame after DIFS + backoff, decoded at
        the receiver, ACKed, retried up to r_limit. True if acknowledged."""
        cfg = self.config
        em = getattr(cfg, "error_model", None)
        with snd.lock.request() as req:
            yield req
            for _ in range(cfg.r_limit + 1):
                upper = min((cfg.cw_min + 1) * 2 ** snd.failed_transmissions_in_row - 1, cfg.cw_max)
                yield from _DCF.wait(snd, random.randint(0, upper))
                tx = snd.tx(rx_pos_fn(), nbytes)
                self.channel.register_tx(tx)
                ok = False
                try:
                    yield self.env.timeout(tx.t_end - tx.tx_start)
                    ok = decode_ok(em, self.channel.sinr_db(tx), REQUIRED_SINR_DB)
                    self.channel.note_wifi_frame(tx, ok)
                    yield self.env.timeout(0)
                finally:
                    self.channel.unregister_control_tx(tx, self.channel.airtime_control, account_to=snd.owner)
                self.stats["mgmt_frames"] += 1
                if ok:
                    if getattr(cfg, "mac_exchange", False):
                        yield self.env.timeout(wifi_mac.SIFS_US)
                        ok = yield from wifi_mac.send_control(snd, rx_name, rx_pos_fn(), tx.tx_pos, wifi_mac.ACK_BYTES)
                    else:
                        yield self.env.timeout(Times(cfg.data_size, cfg.mcs).get_ack_frame_time())
                if ok:
                    snd.failed_transmissions_in_row = 0
                    return True
                snd.failed_transmissions_in_row += 1
                self.stats["mgmt_retries"] += 1
                yield self.env.timeout(Times.ack_timeout)
            snd.failed_transmissions_in_row = 0
            return False

    def _join(self, st, ap):
        """Authentication + (re)association with ap. True when associated."""
        sta, n = st.sta, self.mc.mgmt_frame_bytes
        apsnd = self.ap_sender[ap.name]
        for frm, to_name, to_pos in ((st.sender, ap.name, ap.current_pos),       # authentication request
                                     (apsnd, sta.name, sta.current_pos),         # authentication response
                                     (st.sender, ap.name, ap.current_pos),       # (re)association request
                                     (apsnd, sta.name, sta.current_pos)):        # (re)association response
            if not (yield from self._send(frm, to_name, to_pos, n)):
                st.joins_failed += 1
                return False
        st.state, st.ap = "associated", ap
        sta.ap = ap
        ap.associated.append(sta)
        ev_ap, ap._assoc_event = ap._assoc_event, self.env.event()
        ev_sta, st.assoc_event = st.assoc_event, self.env.event()
        ev_ap.succeed()
        ev_sta.succeed()
        return True

    def _leave(self, st):
        if st.ap is not None and st.sta in st.ap.associated:
            st.ap.associated.remove(st.sta)
        st.state = "roaming"

    def _fresh(self, st, max_age_us):
        now = self.env.now
        return {a: r for a, (r, t) in st.rssi.items() if now - t <= max_age_us}

    def _sta_process(self, st):
        mc = self.mc
        start = self.env.now
        while True:
            # ---- scan and join
            st.state = "scanning"
            joined = False
            while not joined:
                yield self.env.timeout(mc.scan_us)
                heard = self._fresh(st, mc.scan_us + mc.beacon_interval_us)
                for name in sorted(heard, key=heard.get, reverse=True):
                    st.state = "joining"
                    if (yield from self._join(st, self.ap_by_name[name])):
                        joined = True
                        break
                if not joined:
                    st.state = "scanning"
            if st.assoc_time_us is None:
                st.assoc_time_us = self.env.now - start
            # ---- associated: watch the AP's beacons, roam when it fades
            while True:
                yield self.env.timeout(mc.beacon_interval_us)
                cur = st.ap.name
                r = st.rssi.get(cur)
                lost = r is None or self.env.now - r[1] > mc.beacon_loss_intervals * mc.beacon_interval_us
                cur_rssi = float("-inf") if lost else r[0]
                if not lost and cur_rssi >= mc.roam_threshold_dbm:
                    continue
                cands = {a: v for a, v in self._fresh(st, 2 * mc.beacon_interval_us).items()
                         if a != cur and v >= cur_rssi + mc.roam_hysteresis_db}
                if not cands and not lost:
                    continue
                t_leave = self.env.now
                self._leave(st)
                if cands:
                    best = max(cands, key=cands.get)
                    st.state = "joining"
                    if (yield from self._join(st, self.ap_by_name[best])):
                        st.roams += 1
                        st.interruptions_us.append(self.env.now - t_leave)
                        continue
                break                                   # no candidate / reassociation failed: rescan

    # -------------------------------------------------------------- report
    def summary(self, sim_time_us):
        sts = list(self.sta_state.values())
        assoc = [s.assoc_time_us for s in sts if s.assoc_time_us is not None]
        intr = [x for s in sts for x in s.interruptions_us]
        return {
            "beacons": self.stats["beacons"],
            "beacon_airtime_share": self.stats["beacon_airtime_us"] / sim_time_us if sim_time_us else 0.0,
            "associated": sum(1 for s in sts if s.state == "associated"),
            "stas": len(sts),
            "mean_assoc_ms": (sum(assoc) / len(assoc) / 1000.0) if assoc else None,
            "mgmt_frames": self.stats["mgmt_frames"],
            "mgmt_retries": self.stats["mgmt_retries"],
            "joins_failed": sum(s.joins_failed for s in sts),
            "roams": sum(s.roams for s in sts),
            "mean_interruption_ms": (sum(intr) / len(intr) / 1000.0) if intr else None,
        }
# Rashed-Step 20.D-10-08-2026-end
