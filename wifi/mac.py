# Rashed-Step 20.A-10-08-2026-start
"""
802.11 MAC frame exchange on the air (Step 20.A, Config.mac_exchange).

Without it (the default, every earlier run) a Wi-Fi sender only WAITS the
ACK time (Times.get_ack_frame_time(), 44 us) or the ACK timeout - nothing
is transmitted, so ACKs can't collide, nobody senses them and NR-U can
start on top of them. With it, one data exchange is:

    [RTS] -SIFS- [CTS] -SIFS-  DATA  -SIFS-  ACK   (or Block Ack after an A-MPDU)

  - RTS/CTS only when the payload exceeds Config.rts_threshold_bytes.
  - Control frames are real Wi-Fi transmissions at the control rate
    (Times.MCS[mcs][1]: 6/12/24 Mbps) from the node that sends them -
    the ACK and CTS from the RECEIVER's position - decoded at their own
    receiver against that rate's SINR threshold.
  - NAV: a frame that was decoded at its receiver sets a NAV (Duration
    field) for the rest of the exchange: RTS -> CTS + DATA + ACK, CTS ->
    DATA + ACK, DATA -> ACK. Honoured by Wi-Fi nodes where that frame
    arrived at -82 dBm or more (Channel.nav_busy). Approximation: "decoded
    at its receiver" stands in for "decoded by each third party".
  - EIFS: after the channel goes idle following a Wi-Fi frame that was
    NOT decoded (a collision), a node that heard it defers EIFS = SIFS +
    ACK at 6 Mbps + DIFS = 94 us instead of DIFS (DCF path).
  - The sender sees success only if the ACK comes back. An ACK lost after
    a decoded data frame: the packet is delivered (the receiver has it),
    the sender retries anyway - the retransmission is a duplicate (no
    second delivery), counted in mac_stats["duplicates"].
"""
import math

from channel.channel import ActiveTx
from common.error_model import decode_ok
from Times import Times, MCS, WIFI_MCS_SINR_THRESHOLDS_DB

ACK_BYTES = 14
CTS_BYTES = 14
RTS_BYTES = 20
BA_BYTES = 32           # compressed Block Ack
SIFS_US = Times.t_sifs
# Control-rate (Mbps) -> the MCS index whose SINR threshold it uses.
CTRL_RATE_MCS = {6: 0, 12: 2, 24: 4}


def ctrl_frame_us(nbytes: int, rate_mbps: int) -> float:
    """802.11a OFDM duration: 20 us preamble + SIGNAL, then 16 service +
    8*nbytes + 6 tail bits in 4 us symbols of 4*rate bits."""
    return 20 + math.ceil((16 + 8 * nbytes + 6) / (4 * rate_mbps)) * 4


EIFS_US = SIFS_US + ctrl_frame_us(ACK_BYTES, 6) + Times.t_difs   # 16 + 44 + 34 = 94


def ctrl_rate(node) -> int:
    return MCS[node.config.mcs][1]


def new_stats():
    return {"exchanges": 0, "rts": 0, "rts_failed": 0, "cts_failed": 0, "acks": 0, "acks_lost": 0,
            "duplicates": 0, "eifs": 0}


def _nav(node, tx_id, pos, until):
    cfg = node.config
    node.channel.set_nav(ActiveTx(tx_id=tx_id, tx_pos=pos, rx_pos=pos, tx_start=node.env.now,
                                  tx_power_dbm=cfg.tx_power_dbm, f_hz=cfg.f_ghz, pl_exp=cfg.pl_exp,
                                  t_end=until, tech="WiFi", bandwidth_mhz=cfg.bandwidth_mhz,
                                  noise_figure_db=cfg.noise_figure_db))


def send_control(node, tx_id, tx_pos, rx_pos, nbytes, nav_after_us=None):
    """Generator: one control frame from tx_pos to rx_pos at the control
    rate. Returns True if decoded at rx_pos; then, if nav_after_us is
    given, sets a NAV from the frame's end for that long."""
    cfg = node.config
    rate = ctrl_rate(node)
    dur = ctrl_frame_us(nbytes, rate)
    now = node.env.now
    tx = ActiveTx(tx_id=tx_id, tx_pos=tx_pos, rx_pos=rx_pos, tx_start=now, tx_power_dbm=cfg.tx_power_dbm,
                  f_hz=cfg.f_ghz, pl_exp=cfg.pl_exp, t_end=now + dur, tech="WiFi",
                  bandwidth_mhz=cfg.bandwidth_mhz, noise_figure_db=cfg.noise_figure_db)
    node.channel.register_tx(tx)
    ok = False
    try:
        yield node.env.timeout(dur)
        sinr = node.channel.sinr_db(tx)
        ok = decode_ok(getattr(cfg, "error_model", None), sinr, WIFI_MCS_SINR_THRESHOLDS_DB[CTRL_RATE_MCS[rate]])
        node.channel.note_wifi_frame(tx, ok)
        if ok and nav_after_us:
            _nav(node, tx_id, tx_pos, node.env.now + nav_after_us)
        yield node.env.timeout(0)
    finally:
        node.channel.unregister_control_tx(tx, node.channel.airtime_control, account_to=node.name)
    return ok


def data_exchange(node, data_tx, data_us, payload_bytes, rx_name, rx_pos, decide, response_bytes=ACK_BYTES):
    """
    Generator: one full exchange for an already-built data ActiveTx
    (data_tx, not yet registered). decide(data_tx) -> bool is the
    caller's own data-decode step, run when the frame ends (SINR, rate
    adaptation, error model; an A-MPDU decodes per MPDU and returns True
    if any got through). Returns (result, data_end) with result one of
    "ok", "ack_lost", "data_fail", "rts_fail", "cts_fail".
    """
    cfg = node.config
    env = node.env
    rate = ctrl_rate(node)
    stats = node.mac_stats
    stats["exchanges"] += 1
    resp_us = ctrl_frame_us(response_bytes, rate)
    tx_pos = data_tx.tx_pos

    thr = getattr(cfg, "rts_threshold_bytes", None)
    if thr is not None and payload_bytes > thr:
        stats["rts"] += 1
        cts_us = ctrl_frame_us(CTS_BYTES, rate)
        nav = SIFS_US + cts_us + SIFS_US + data_us + SIFS_US + resp_us
        if not (yield from send_control(node, node.name, tx_pos, rx_pos, RTS_BYTES, nav)):
            stats["rts_failed"] += 1
            yield env.timeout(Times.ack_timeout)          # CTS timeout
            return "rts_fail", None
        yield env.timeout(SIFS_US)
        if not (yield from send_control(node, rx_name, rx_pos, tx_pos, CTS_BYTES,
                                        SIFS_US + data_us + SIFS_US + resp_us)):
            stats["cts_failed"] += 1
            return "cts_fail", None
        yield env.timeout(SIFS_US)
        start = env.now
        data_tx.tx_start, data_tx.t_end = start, start + data_us

    node.channel.register_tx(data_tx)
    decoded = False
    try:
        yield env.timeout(data_us)
        decoded = decide(data_tx)
        node.channel.note_wifi_frame(data_tx, decoded)
        if decoded:
            _nav(node, node.name, tx_pos, env.now + SIFS_US + resp_us)
        yield env.timeout(0)
        node.channel.unregister_tx(data_tx, success=decoded)
    except BaseException:
        node.channel.unregister_tx(data_tx, success=decoded)
        raise
    data_end = data_tx.t_end
    if not decoded:
        yield env.timeout(Times.ack_timeout)
        return "data_fail", data_end
    yield env.timeout(SIFS_US)
    stats["acks"] += 1
    if (yield from send_control(node, rx_name, rx_pos, tx_pos, response_bytes)):
        return "ok", data_end
    stats["acks_lost"] += 1
    return "ack_lost", data_end


def finish(node, frame, res, data_end, on_ok, on_fail):
    """Sender-side bookkeeping for one single-frame exchange. on_ok /
    on_fail are the node's own sent_completed / sent_failed. A data frame
    decoded but whose ACK was lost is remembered on the frame
    (rx_delivered_at): the later successful retry is a duplicate and
    keeps that delivery time; if the retries run out, the packet still
    counts as delivered (the receiver has it)."""
    first_rx = getattr(frame, "rx_delivered_at", None)
    if res in ("ok", "ack_lost") and first_rx is not None:
        node.mac_stats["duplicates"] += 1
    if res == "ok":
        on_ok()
        if frame.ack_packet is not None:
            frame.ack_packet.status = "DELIVERED"
            frame.ack_packet.delivered_at = node.env.now
        if first_rx is not None and frame.packet is not None:
            frame.packet.delivered_at = first_rx
        return True
    if res == "ack_lost" and first_rx is None:
        frame.rx_delivered_at = data_end
    on_fail()
    p = frame.packet
    if p is not None and p.status == "DROPPED" and getattr(frame, "rx_delivered_at", None) is not None:
        p.status = "DELIVERED"                         # already in packet_log (sent_failed appended it)
        p.delivered_at = frame.rx_delivered_at
        node.channel.bytes_sent += frame.data_size
    return False
# Rashed-Step 20.A-10-08-2026-end
