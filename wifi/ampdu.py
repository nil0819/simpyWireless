# Rashed-Step 20.B-10-08-2026-start
"""
A-MPDU aggregation shared by every Wi-Fi sender (Step 20.B). Moved out of
wifi.WiFi (where pre_20.B built it for the AP's DCF downlink only) so the
EDCA path (per access category) and STA uplink use the same code. The AP
DCF path behaves exactly as before.

A node (wifi.WiFi or wifi.sta.WiFiSTA) must expose env, channel, config,
name, times, current_pos(), required_sinr_db(), packet_log, ampdu_stats,
mac_stats, succeeded_transmissions / failed_transmissions /
failed_transmissions_in_row (and ac_failed_in_row for EDCA). Rate
adaptation hooks are optional (the AP has them, a STA doesn't).
"""
from channel.channel import ActiveTx
from common.error_model import decode_ok
from Times import Times
from wifi import mac as wifi_mac
from wifi import phy as wifi_phy  # 20.C

AMPDU_DELIMITER_BITS = 32
# 802.11 default EDCA TXOP limits for the OFDM PHY (us); 0 = one PPDU per
# access, bounded only by aPPDUMaxTime. One PPDU per TXOP is modeled.
TXOP_LIMIT_US = {"voice": 1504.0, "video": 3008.0, "best_effort": 0.0, "background": 0.0}


def new_stats():
    return {"ppdus": 0, "mpdus": 0, "mpdus_ok": 0, "header_lost": 0}


def times_for(node):
    """(PHY header us, us per MPDU of payload_bytes) at the node's current MCS."""
    t = node.times
    if getattr(node.config, "rate_adapt_enabled", False) and hasattr(node, "current_mcs_for_link"):
        t = wifi_phy.make_times(node.config, node.config.data_size,
                                node.current_mcs_for_link(node.rate_adapt_link_key()))  # 20.C
    header_us = t.ofdm_preamble + t.ofdm_signal
    per_mpdu = lambda payload: (Times.mac_overhead + payload * 8 + AMPDU_DELIMITER_BITS) / t.data_rate
    return header_us, per_mpdu


def ppdu_budget_us(node, ac=None):
    limit = node.config.ampdu_max_ppdu_us
    txop = TXOP_LIMIT_US.get(ac, 0.0) if ac is not None else 0.0
    return min(limit, txop) if txop > 0 else limit


def build(pending, take, put_back, header_us, per_mpdu, max_mpdus, max_ppdu_us):
    """MPDUs for one PPDU: retransmissions first, then fresh packets from
    take() (None = nothing waiting), capped by count and PPDU time; a
    packet that doesn't fit goes back with put_back(). A single MPDU longer
    than the budget is sent alone."""
    budget = max_ppdu_us - header_us
    mpdus, used = [], 0.0
    for pkt in pending:
        if len(mpdus) < max_mpdus and used + per_mpdu(pkt.payload_bytes) <= budget:
            mpdus.append(pkt)
            used += per_mpdu(pkt.payload_bytes)
    while len(mpdus) < max_mpdus:
        nxt = take()
        if nxt is None:
            break
        if used + per_mpdu(nxt.payload_bytes) > budget:
            put_back(nxt)
            break
        mpdus.append(nxt)
        used += per_mpdu(nxt.payload_bytes)
    if not mpdus:
        mpdus = pending[:1]
    return mpdus


def next_pending(pending, mpdus):
    """Retransmission list after a PPDU: what wasn't carried, then the
    carried MPDUs still waiting (or retried as duplicates, 20.A)."""
    carried = {id(p) for p in mpdus}
    return [p for p in pending if id(p) not in carried] + \
           [p for p in mpdus if p.status == "PENDING" or getattr(p, "_dup", False)]


def _cw_ok(node, ac):
    node.channel.succeeded_transmissions += 1
    node.succeeded_transmissions += 1
    if ac is None:
        node.failed_transmissions_in_row = 0
    else:
        node.ac_failed_in_row[ac] = 0


def _cw_fail(node, ac):
    node.channel.failed_transmissions += 1
    node.failed_transmissions += 1
    if ac is None:
        node.failed_transmissions_in_row += 1
    else:
        node.ac_failed_in_row[ac] += 1


def _cw_wrap(node, ac):
    if ac is None:
        if node.failed_transmissions_in_row > node.config.r_limit:
            node.failed_transmissions_in_row = 0
    elif node.ac_failed_in_row[ac] > node.config.r_limit:
        node.ac_failed_in_row[ac] = 0


def _rate_feedback(node, ok, sinr):
    rec = getattr(node, "rate_adapt_record_result", None)
    if rec is not None:
        rec(node.rate_adapt_link_key(), ok, measured_sinr_db=sinr)


def _ppdu_tx(node, mpdus, start, dur, rx_pos):
    cfg = node.config
    return ActiveTx(tx_id=node.name, tx_pos=node.current_pos(), rx_pos=rx_pos, tx_start=start,
                    tx_power_dbm=cfg.tx_power_dbm, f_hz=cfg.f_ghz, pl_exp=cfg.pl_exp,
                    t_end=start + dur, tech="WiFi", bandwidth_mhz=cfg.bandwidth_mhz,
                    noise_figure_db=cfg.noise_figure_db, packet=mpdus[0])


def send(node, mpdus, header_us, per_mpdu, rx_pos, ac=None):
    """pre_20.B behaviour: one PPDU, the PHY header has to survive (else
    nothing decodes and no Block Ack comes back), then each MPDU on its own
    window; the Block Ack time is waited out. True if any MPDU got through."""
    start = node.env.now
    dur = header_us + sum(per_mpdu(p.payload_bytes) for p in mpdus)
    tx = _ppdu_tx(node, mpdus, start, dur, rx_pos)
    node.channel.register_tx(tx)
    required = node.required_sinr_db()
    em = getattr(node.config, "error_model", None)
    n_ok = 0
    try:
        yield node.env.timeout(dur)
        sinr_h = node.channel.sinr_db(tx, window=(start, start + header_us))
        header_ok = decode_ok(em, sinr_h, required)
        t0 = start + header_us
        for p in mpdus:
            t1 = t0 + per_mpdu(p.payload_bytes)
            sinr = node.channel.sinr_db(tx, window=(t0, t1))
            p.measured_sinr_db = sinr
            if header_ok and decode_ok(em, sinr, required):
                p.status = "DELIVERED"
                n_ok += 1
            t0 = t1
        _rate_feedback(node, n_ok > 0, sinr_h)
        yield node.env.timeout(0)
        node.channel.unregister_tx(tx, success=n_ok > 0)
    except BaseException:
        node.channel.unregister_tx(tx, success=n_ok > 0)
        raise
    node.ampdu_stats["ppdus"] += 1
    node.ampdu_stats["mpdus"] += len(mpdus)
    node.ampdu_stats["mpdus_ok"] += n_ok
    if n_ok > 0:
        _cw_ok(node, ac)
        node.channel.airtime_control[node.name] += node.times.get_ack_frame_time()
        yield node.env.timeout(node.times.get_ack_frame_time())   # SIFS + Block Ack
    else:
        _cw_fail(node, ac)
        if not header_ok:
            node.ampdu_stats["header_lost"] += 1
        yield node.env.timeout(node.times.ack_timeout)              # no Block Ack
    for p in mpdus:
        if p.status == "DELIVERED":
            p.delivered_at = node.env.now
            node.channel.bytes_sent += p.payload_bytes
            node.packet_log.append(p)
        else:
            p.retry_count += 1
            if p.retry_count > node.config.r_limit:
                p.status = "DROPPED"
                node.packet_log.append(p)
    _cw_wrap(node, ac)
    return n_ok > 0


def send_mac(node, mpdus, header_us, per_mpdu, rx_name, rx_pos, ac=None):
    """send() with the Block Ack on the air (and RTS/CTS above the
    threshold) - Step 20.A. An MPDU is delivered when it is decoded; a lost
    Block Ack makes the sender retry every MPDU of the PPDU, the ones the
    receiver already has as duplicates (p._dup) until a Block Ack confirms
    them."""
    start = node.env.now
    dur = header_us + sum(per_mpdu(p.payload_bytes) for p in mpdus)
    tx = _ppdu_tx(node, mpdus, start, dur, rx_pos)
    required = node.required_sinr_db()
    em = getattr(node.config, "error_model", None)
    st = {"header_ok": False, "decoded": []}

    def decide(t):
        s0 = t.tx_start
        sinr_h = node.channel.sinr_db(t, window=(s0, s0 + header_us))
        st["header_ok"] = decode_ok(em, sinr_h, required)
        t0 = s0 + header_us
        for p in mpdus:
            t1 = t0 + per_mpdu(p.payload_bytes)
            sinr = node.channel.sinr_db(t, window=(t0, t1))
            if st["header_ok"] and decode_ok(em, sinr, required):
                st["decoded"].append(p)
                if p.status == "DELIVERED":
                    node.mac_stats["duplicates"] += 1
                else:
                    p.measured_sinr_db = sinr
                    p.status = "DELIVERED"
                    p.delivered_at = node.env.now
                    node.channel.bytes_sent += p.payload_bytes
                    node.packet_log.append(p)
            elif p.status != "DELIVERED":
                p.measured_sinr_db = sinr
            t0 = t1
        _rate_feedback(node, bool(st["decoded"]), sinr_h)
        return bool(st["decoded"])
    res, _ = yield from wifi_mac.data_exchange(node, tx, dur, sum(p.payload_bytes for p in mpdus), rx_name,
                                               rx_pos, decide, response_bytes=wifi_mac.BA_BYTES)
    node.ampdu_stats["ppdus"] += 1
    node.ampdu_stats["mpdus"] += len(mpdus)
    node.ampdu_stats["mpdus_ok"] += len(st["decoded"])
    acked = {id(p) for p in st["decoded"]} if res == "ok" else set()
    if res == "ok":
        _cw_ok(node, ac)
    else:
        _cw_fail(node, ac)
        if res == "data_fail" and not st["header_ok"]:
            node.ampdu_stats["header_lost"] += 1
    for p in mpdus:
        if id(p) in acked:
            p._dup = False
            continue
        p.retry_count += 1
        if p.status == "DELIVERED":
            p._dup = p.retry_count <= node.config.r_limit   # retry until a Block Ack confirms it
        elif p.retry_count > node.config.r_limit:
            p.status = "DROPPED"
            node.packet_log.append(p)
    _cw_wrap(node, ac)
    return res == "ok"


def send_any(node, mpdus, header_us, per_mpdu, rx_name, rx_pos, ac=None):
    """send_mac() when the node's config has mac_exchange, else send()."""
    if getattr(node.config, "mac_exchange", False):
        return (yield from send_mac(node, mpdus, header_us, per_mpdu, rx_name, rx_pos, ac))
    return (yield from send(node, mpdus, header_us, per_mpdu, rx_pos, ac))
# Rashed-Step 20.B-10-08-2026-end
