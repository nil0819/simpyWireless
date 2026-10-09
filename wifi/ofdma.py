# Rashed-Step 20.E-10-09-2026-start
"""
802.11ax OFDMA (Step 20.E, Config.ofdma with phy="he").

Resource units (RUs): the channel is split into equal RUs, the size picked
by how many users are served (the largest RU size with at least that many
RUs in the channel - the 802.11ax RU layout):
    RU tones   data subcarriers   ~MHz    per 20 / 40 / 80 / 160 MHz
      26             24           2.0      9 / 18 / 37 / 74
      52             48           4.1      4 /  8 / 16 / 32
     106            102           8.3      2 /  4 /  8 / 16
     242            234          18.9      1 /  2 /  4 /  8
     484            468          37.8      - /  1 /  2 /  4
     996            980          77.8      - /  - /  1 /  2
    1992           1960         155.6      - /  - /  - /  1
Each RU is its own transmission (ActiveTx) at its own centre frequency and
bandwidth, so users don't interfere with each other and other networks see
the right in-band power (Step pre_20.C0). Rate per RU = data subcarriers x
bits/subcarrier x code rate / (12.8 us + GI) at the configured MCS. In the
downlink the AP's power is split over the RUs by tone count (constant power
spectral density); in the uplink each STA transmits at its own power on
its RU.

  - Downlink (HE MU PPDU): when the AP wins channel access (DCF) it serves
    up to ofdma_max_users STAs with queued data (round robin), each with an
    A-MPDU on its RU; the PPDU lasts as long as the longest user's A-MPDU
    (capped by aPPDUMaxTime). Preamble 44 us + HE-SIG-B 4 us per two users.
    Each MPDU is decoded on its own RU and time window. Acknowledgement:
    each user sends its Block Ack after SIFS in an HE TB PPDU on its RU (64
    us) - on the air with --wifi-mac-exchange, else that time is waited.
  - Uplink (trigger-based, ul_ofdma): the AP sends a Trigger frame
    (non-HT, 28 + 6 bytes per user), SIFS, the scheduled STAs send HE TB
    PPDUs (48 us preamble) simultaneously on their RUs, as long as the AP
    asks for (the longest buffered A-MPDU), SIFS, the AP sends one
    multi-STA Block Ack (non-HT, 22 + 10 bytes per user). STAs then send
    uplink ONLY when triggered (no contention of their own - like MU EDCA
    parameters that block it).
  - When the AP has both downlink and uplink data it alternates rounds.
    MPDUs that fail are retried in a later round (retry limit r_limit).
    The AP's contention window doubles when no user of a round got
    through.
Not modeled: MU-MIMO, uplink power control / RU-dependent power limits,
buffer status reports and random-access RUs (the AP is assumed to know
the STAs' buffers), cascaded / multi-TID A-MPDUs, MU-RTS.
"""
import math

from channel.channel import ActiveTx
from common.error_model import decode_ok
from Times import Times
from wifi import mac as wifi_mac
from wifi import phy as wifi_phy

RU_NSD = {26: 24, 52: 48, 106: 102, 242: 234, 484: 468, 996: 980, 1992: 1960}
RU_COUNT = {20: {26: 9, 52: 4, 106: 2, 242: 1},
            40: {26: 18, 52: 8, 106: 4, 242: 2, 484: 1},
            80: {26: 37, 52: 16, 106: 8, 242: 4, 484: 2, 996: 1},
            160: {26: 74, 52: 32, 106: 16, 242: 8, 484: 4, 996: 2, 1992: 1}}
FULL_TONES = {20: 242, 40: 484, 80: 996, 160: 1992}
SUBCARRIER_MHZ = 0.078125
TB_PREAMBLE_US = 48.0
TB_BA_US = 64.0


def ru_plan(width_mhz: int, n_users: int):
    """[(tones, centre offset Hz, bandwidth MHz)] for n_users equal RUs."""
    counts = RU_COUNT[width_mhz]
    tones = max(t for t, c in counts.items() if c >= n_users)
    slot_mhz = width_mhz / counts[tones]
    return [(tones, (-width_mhz / 2.0 + (k + 0.5) * slot_mhz) * 1e6, tones * SUBCARRIER_MHZ)
            for k in range(n_users)]


def ru_rate_mbps(tones: int, mcs: int, gi_ns: int) -> float:
    bpsc, rate = wifi_phy.MODULATION[mcs]
    return RU_NSD[tones] * bpsc * rate / wifi_phy.symbol_us("he", gi_ns)


def mu_preamble_us(n_users: int) -> float:
    return 44.0 + 4.0 * math.ceil(n_users / 2)


def new_stats():
    return {"dl_ppdus": 0, "dl_users": 0, "dl_mpdus": 0, "dl_mpdus_ok": 0,
            "ul_rounds": 0, "ul_users": 0, "ul_mpdus": 0, "ul_mpdus_ok": 0, "ru_tones": {}}


def _ru_tx(cfg, tx_id, tx_pos, rx_pos, power_dbm, f_hz, bw_mhz, start, dur, packet=None):
    return ActiveTx(tx_id=tx_id, tx_pos=tx_pos, rx_pos=rx_pos, tx_start=start, tx_power_dbm=power_dbm,
                    f_hz=f_hz, pl_exp=cfg.pl_exp, t_end=start + dur, tech="WiFi", bandwidth_mhz=bw_mhz,
                    noise_figure_db=cfg.noise_figure_db, packet=packet)


def _fill(queue_take, put_back, per_mpdu, budget_us, max_mpdus, pending):
    """Retransmissions first, then queued packets, up to budget_us / max_mpdus."""
    mpdus, used = [], 0.0
    for p in pending:
        if len(mpdus) < max_mpdus and used + per_mpdu(p.payload_bytes) <= budget_us:
            mpdus.append(p)
            used += per_mpdu(p.payload_bytes)
    while len(mpdus) < max_mpdus:
        p = queue_take()
        if p is None:
            break
        if used + per_mpdu(p.payload_bytes) > budget_us:
            put_back(p)
            break
        mpdus.append(p)
        used += per_mpdu(p.payload_bytes)
    return mpdus, used


def _decode_user(channel, em, tx, t0, mpdus, per_mpdu, required, header_ok):
    ok = []
    for p in mpdus:
        t1 = t0 + per_mpdu(p.payload_bytes)
        sinr = channel.sinr_db(tx, window=(t0, t1))
        if p.status != "DELIVERED":
            p.measured_sinr_db = sinr
        if header_ok and decode_ok(em, sinr, required):
            ok.append(p)
        t0 = t1
    return ok


def _settle(owner, mpdus, decoded, acked, r_limit, log_list, channel, now):
    """Delivery / retry bookkeeping for one user's MPDUs; returns those to retry."""
    retry = []
    dec_ids = {id(p) for p in decoded}
    for p in mpdus:
        if id(p) in dec_ids and p.status != "DELIVERED":
            p.status, p.delivered_at = "DELIVERED", now
            channel.bytes_sent += p.payload_bytes
            log_list.append(p)
        if acked and id(p) in dec_ids:
            continue
        p.retry_count += 1
        if p.status == "DELIVERED":
            if p.retry_count <= r_limit:
                retry.append(p)               # receiver has it; BA lost -> duplicate retry
        elif p.retry_count > r_limit:
            p.status = "DROPPED"
            log_list.append(p)
        else:
            retry.append(p)
    return retry


def downlink_round(ap, users):
    """Generator: one HE MU PPDU to `users` (STAs with downlink data).
    Returns True if at least one user's Block Ack came back."""
    cfg, env, ch = ap.config, ap.env, ap.channel
    width, gi, mcs = cfg.channel_width_mhz, cfg.guard_interval_ns, cfg.mcs
    plan = ru_plan(width, len(users))
    pre = mu_preamble_us(len(users))
    budget = cfg.ampdu_max_ppdu_us - pre
    em = getattr(cfg, "error_model", None)
    required = ap.required_sinr_db()
    per_user = []
    for sta, (tones, off, bw) in zip(users, plan):
        rate = ru_rate_mbps(tones, mcs, gi)
        per = (lambda r: (lambda payload: (Times.mac_overhead + payload * 8 + 32) / r))(rate)
        q = ap.ofdma_dl[sta.name]
        mpdus, used = _fill(lambda q=q, s=sta: ap._ofdma_take_dl(s), lambda p, q=q: q.insert(0, p), per, budget,
                            cfg.ampdu_max_mpdus, ap.ofdma_dl_pending[sta.name])
        per_user.append((sta, tones, off, bw, per, mpdus, used))
        ap.ofdma_stats["ru_tones"][tones] = ap.ofdma_stats["ru_tones"].get(tones, 0) + 1
    data_us = max(u[6] for u in per_user)
    start = env.now
    dur = pre + data_us
    txs = []
    for sta, tones, off, bw, per, mpdus, used in per_user:
        p_dbm = cfg.tx_power_dbm + 10.0 * math.log10(tones / FULL_TONES[width])
        tx = _ru_tx(cfg, ap.name, ap.current_pos(), sta.current_pos(), p_dbm, cfg.f_ghz + off, bw, start, dur,
                    mpdus[0] if mpdus else None)
        ch.register_tx(tx)
        txs.append(tx)
    results = []
    try:
        yield env.timeout(dur)
        for tx, (sta, tones, off, bw, per, mpdus, used) in zip(txs, per_user):
            header_ok = decode_ok(em, ch.sinr_db(tx, window=(start, start + pre)), required)
            results.append(_decode_user(ch, em, tx, start + pre, mpdus, per, required, header_ok))
        yield env.timeout(0)
    finally:
        for tx, res in zip(txs, results + [[]] * (len(txs) - len(results))):
            ch.unregister_tx(tx, success=bool(res))
    # per-user Block Acks in HE TB PPDUs on the same RUs
    yield env.timeout(wifi_mac.SIFS_US)
    acks = []
    if getattr(cfg, "mac_exchange", False):
        bstart = env.now
        btxs = []
        for (sta, tones, off, bw, per, mpdus, used), dec in zip(per_user, results):
            if dec:
                b = _ru_tx(cfg, sta.name, sta.current_pos(), ap.current_pos(), cfg.tx_power_dbm, cfg.f_ghz + off,
                           bw, bstart, TB_BA_US)
                ch.register_tx(b)
                btxs.append((sta, b))
        try:
            yield env.timeout(TB_BA_US)
            ok_names = {sta.name for sta, b in btxs
                        if decode_ok(em, ch.sinr_db(b), wifi_phy.HT_SINR_THRESHOLDS_DB[0])}
            yield env.timeout(0)
        finally:
            for sta, b in btxs:
                ch.unregister_control_tx(b, ch.airtime_control, account_to=ap.name)
        acks = [sta.name in ok_names for sta, *_ in per_user]
    else:
        yield env.timeout(TB_BA_US)
        acks = [bool(dec) for dec in results]
    now = env.now
    st = ap.ofdma_stats
    st["dl_ppdus"] += 1
    st["dl_users"] += len(users)
    for (sta, tones, off, bw, per, mpdus, used), dec, ack in zip(per_user, results, acks):
        st["dl_mpdus"] += len(mpdus)
        st["dl_mpdus_ok"] += len(dec)
        ap.ofdma_dl_pending[sta.name] = _settle(ap, mpdus, dec, ack, cfg.r_limit, ap.packet_log, ch, now)
    return any(acks)


def uplink_round(ap, users):
    """Generator: Trigger -> HE TB PPDUs from `users` -> multi-STA Block Ack.
    Returns True if any user's data got through."""
    cfg, env, ch = ap.config, ap.env, ap.channel
    width, gi, mcs = cfg.channel_width_mhz, cfg.guard_interval_ns, cfg.mcs
    em = getattr(cfg, "error_model", None)
    required = ap.required_sinr_db()
    ctrl = wifi_phy.ctrl_rate_mbps(cfg)
    n = len(users)
    # Trigger frame (non-HT)
    trig_us = wifi_mac.ctrl_frame_us(28 + 6 * n, ctrl)
    t = ActiveTx(tx_id=ap.name, tx_pos=ap.current_pos(), rx_pos=ap.current_pos(), tx_start=env.now,
                 tx_power_dbm=cfg.tx_power_dbm, f_hz=cfg.f_ghz, pl_exp=cfg.pl_exp, t_end=env.now + trig_us,
                 tech="WiFi", bandwidth_mhz=cfg.bandwidth_mhz, noise_figure_db=cfg.noise_figure_db)
    ch.register_tx(t)
    try:
        yield env.timeout(trig_us)
        heard = [decode_ok(em, ch.sinr_db(_view(t, sta.current_pos())), wifi_phy.HT_SINR_THRESHOLDS_DB[0])
                 for sta in users]
        yield env.timeout(0)
    finally:
        ch.unregister_control_tx(t, ch.airtime_control, account_to=ap.name)
    yield env.timeout(wifi_mac.SIFS_US)
    plan = ru_plan(width, n)
    budget = cfg.ampdu_max_ppdu_us - TB_PREAMBLE_US
    per_user = []
    for sta, (tones, off, bw) in zip(users, plan):
        rate = ru_rate_mbps(tones, mcs, gi)
        per = (lambda r: (lambda payload: (Times.mac_overhead + payload * 8 + 32) / r))(rate)
        mpdus, used = _fill(sta._take_queued_packet, sta._put_back_packet, per, budget, cfg.ampdu_max_mpdus,
                            sta.ofdma_ul_pending)
        per_user.append((sta, tones, off, bw, per, mpdus, used))
        ap.ofdma_stats["ru_tones"][tones] = ap.ofdma_stats["ru_tones"].get(tones, 0) + 1
    data_us = max(u[6] for u in per_user)
    start = env.now
    dur = TB_PREAMBLE_US + data_us
    txs = []
    for (sta, tones, off, bw, per, mpdus, used), h in zip(per_user, heard):
        if h and mpdus:                       # a STA that missed the trigger stays silent
            tx = _ru_tx(cfg, sta.name, sta.current_pos(), ap.current_pos(), cfg.tx_power_dbm, cfg.f_ghz + off,
                        bw, start, dur, mpdus[0])
            ch.register_tx(tx)
            txs.append((sta, tx))
        else:
            txs.append((sta, None))
    results = []
    try:
        yield env.timeout(dur)
        for (sta, tx), (_, tones, off, bw, per, mpdus, used) in zip(txs, per_user):
            if tx is None:
                results.append([])
                continue
            header_ok = decode_ok(em, ch.sinr_db(tx, window=(start, start + TB_PREAMBLE_US)), required)
            results.append(_decode_user(ch, em, tx, start + TB_PREAMBLE_US, mpdus, per, required, header_ok))
        yield env.timeout(0)
    finally:
        for (sta, tx), res in zip(txs, results + [[]] * (len(txs) - len(results))):
            if tx is not None:
                ch.unregister_tx(tx, success=bool(res))
    # multi-STA Block Ack (non-HT) from the AP
    yield env.timeout(wifi_mac.SIFS_US)
    ba_us = wifi_mac.ctrl_frame_us(22 + 10 * n, ctrl)
    if getattr(cfg, "mac_exchange", False):
        b = ActiveTx(tx_id=ap.name, tx_pos=ap.current_pos(), rx_pos=ap.current_pos(), tx_start=env.now,
                     tx_power_dbm=cfg.tx_power_dbm, f_hz=cfg.f_ghz, pl_exp=cfg.pl_exp, t_end=env.now + ba_us,
                     tech="WiFi", bandwidth_mhz=cfg.bandwidth_mhz, noise_figure_db=cfg.noise_figure_db)
        ch.register_tx(b)
        try:
            yield env.timeout(ba_us)
            acks = [bool(dec) and decode_ok(em, ch.sinr_db(_view(b, sta.current_pos())),
                                            wifi_phy.HT_SINR_THRESHOLDS_DB[0])
                    for (sta, _), dec in zip(txs, results)]
            yield env.timeout(0)
        finally:
            ch.unregister_control_tx(b, ch.airtime_control, account_to=ap.name)
    else:
        yield env.timeout(ba_us)
        acks = [bool(dec) for dec in results]
    now = env.now
    st = ap.ofdma_stats
    st["ul_rounds"] += 1
    st["ul_users"] += n
    for (sta, tones, off, bw, per, mpdus, used), dec, ack in zip(per_user, results, acks):
        st["ul_mpdus"] += len(mpdus)
        st["ul_mpdus_ok"] += len(dec)
        sta.ofdma_ul_pending = _settle(sta, mpdus, dec, ack, cfg.r_limit, sta.packet_log, ch, now)
    return any(bool(d) for d in results)


def _view(tx, rx_pos):
    v = ActiveTx(tx_id=tx.tx_id, tx_pos=tx.tx_pos, rx_pos=rx_pos, tx_start=tx.tx_start,
                 tx_power_dbm=tx.tx_power_dbm, f_hz=tx.f_hz, pl_exp=tx.pl_exp, t_end=tx.t_end, tech=tx.tech,
                 bandwidth_mhz=tx.bandwidth_mhz, noise_figure_db=tx.noise_figure_db)
    v.overlap_history = tx.overlap_history
    return v
# Rashed-Step 20.E-10-09-2026-end
