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
Downlink MU-MIMO: Step 25.C (mu_groups / mu_sinr_db below).
Not modeled: uplink MU-MIMO, uplink power control / RU-dependent power limits,
buffer status reports and random-access RUs (the AP is assumed to know
the STAs' buffers), cascaded / multi-TID A-MPDUs, MU-RTS.
"""
import math

from channel.channel import ActiveTx
from common.error_model import decode_ok
from Times import Times
from wifi import mac as wifi_mac
from wifi import phy as wifi_phy
# Rashed-Step 21.C-10-11-2026-start
from dataclasses import dataclass
from wifi import ampdu as wifi_ampdu


@dataclass
class MuEdcaParams:
    """MU EDCA parameters (802.11ax): for timer_us after a STA has been
    triggered, its own contention uses this AIFSN / CW instead of the
    normal ones - so a STA served by triggers mostly leaves the channel
    to the AP. Representative values (the AP chooses them in practice;
    the timer is in 8-TU units: 8 x 8.192 ms)."""
    aifsn: int = 12
    cw_min: int = 255
    cw_max: int = 1023
    timer_us: float = 8 * 8 * 1024.0
# Rashed-Step 21.C-10-11-2026-end

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


# Rashed-Step 25.D-10-20-2026-start
# Demand-based RU plan (Step 25.D, Config.ofdma_ru_alloc = "demand"). The
# equal plan gives every user the same RU size, so 3 users in 20 MHz get
# 3 x 52 tones and a third of the channel is unused, and a user with one
# small frame gets as much as one with a full A-MPDU. Here the channel is
# split along the 802.11ax RU tree (1992 -> 2 x 996 -> 2 x 484 -> 2 x 242
# -> 2 x 106 -> 2 x 52 -> 2 x 26; the centre 26-tone RUs stay unused): a
# node with one user is that user's RU; otherwise its users are shared out
# between the two halves, largest demand first, each to the half with the
# smaller total demand (as long as it has room). A heavy user so ends up
# alone on a large RU while light users share the other half in smaller
# ones, and the PPDU - as long as the longest user - gets shorter. Demand
# = bytes waiting for the user (queued + retries; the access category's
# only with EDCA); saturated traffic = equal demand. More users than the
# tree holds (e.g. 9 in 20 MHz) -> the equal plan.
RU_CHILD = {1992: 996, 996: 484, 484: 242, 242: 106, 106: 52, 52: 26}
RU_CAP = {26: 1, 52: 2, 106: 4, 242: 8, 484: 16, 996: 32, 1992: 64}


def demand_plan(width_mhz: int, demands):
    """[(tones, centre offset Hz, bandwidth MHz)] per user (in the order of
    demands), or None when there are more users than the RU tree holds."""
    n = len(demands)
    root = FULL_TONES[width_mhz]
    if n == 0 or n > RU_CAP[root]:
        return None
    out = [None] * n

    def alloc(tones, centre_mhz, span_mhz, idx):
        if len(idx) == 1:
            out[idx[0]] = (tones, centre_mhz * 1e6, tones * SUBCARRIER_MHZ)
            return
        child = RU_CHILD[tones]
        halves, load = ([], []), [0.0, 0.0]
        for i in sorted(idx, key=lambda i: (-demands[i], i)):
            h = 0 if load[0] <= load[1] else 1
            if len(halves[h]) >= RU_CAP[child]:
                h = 1 - h
            halves[h].append(i)
            load[h] += demands[i]
        alloc(child, centre_mhz - span_mhz / 4.0, span_mhz / 2.0, halves[0])
        alloc(child, centre_mhz + span_mhz / 4.0, span_mhz / 2.0, halves[1])

    alloc(root, 0.0, float(width_mhz), list(range(n)))
    return out


def dl_demand(ap, sta, ac=None) -> float:
    if ap.traffic_config.mode == "saturated":
        return 1.0
    pk = list(ap.ofdma_dl[sta.name]) + list(ap.ofdma_dl_pending[sta.name])
    return float(sum(p.payload_bytes for p in pk if ac is None or p.traffic_class == ac))


def ul_demand(sta) -> float:
    if sta.traffic_config.mode == "saturated":
        return 1.0
    return float(sum(p.payload_bytes for p in list(sta.packet_queue.items) + list(sta.ofdma_ul_pending)))


def _plan(cfg, width, users, demand):
    if getattr(cfg, "ofdma_ru_alloc", "equal") == "demand":
        plan = demand_plan(width, [demand(s) for s in users])
        if plan is not None:
            return plan
    return ru_plan(width, len(users))
# Rashed-Step 25.D-10-20-2026-end


def ru_rate_mbps(tones: int, mcs: int, gi_ns: int, nss: int = 1) -> float:  # 25.C: nss
    bpsc, rate = wifi_phy.MODULATION[mcs]
    return RU_NSD[tones] * bpsc * rate * nss / wifi_phy.symbol_us("he", gi_ns)


# Rashed-Step 25.C-10-20-2026-start
MU_MIMO_MIN_TONES = 106


def mu_groups(width_mhz: int, n_users: int, k_max: int):
    """Downlink MU-MIMO grouping (Step 25.C): up to k_max users per RU -
    the fewest groups, so the largest RUs and the most streams in use -
    balanced over the groups; the RUs must have at least 106 tones (the
    802.11ax minimum for MU-MIMO). Returns the group sizes, or None when
    the groups don't fit (plain OFDMA then)."""
    g = -(-n_users // max(1, k_max))
    if g > RU_COUNT[width_mhz].get(MU_MIMO_MIN_TONES, 0):
        return None
    return [n_users // g + (1 if i < n_users % g else 0) for i in range(g)]


def mu_sinr_db(sinr_db: float, k: int, residual_db: float) -> float:
    """SINR of one MU-MIMO user: channel SINR (own stream) with the
    precoding residual of the k - 1 other streams added as interference."""
    if k <= 1:
        return sinr_db
    return -10.0 * math.log10(10.0 ** (-sinr_db / 10.0) + (k - 1) * 10.0 ** (residual_db / 10.0))
# Rashed-Step 25.C-10-20-2026-end


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


def _decode_user(channel, em, tx, t0, mpdus, per_mpdu, required, header_ok, mu=None):  # 25.C: mu = (k, residual_db)
    ok = []
    for p in mpdus:
        t1 = t0 + per_mpdu(p.payload_bytes)
        sinr = channel.sinr_db(tx, window=(t0, t1))
        if mu is not None:
            sinr = mu_sinr_db(sinr, *mu)
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


def downlink_round(ap, users, ac=None):  # 21.C: ac = the EDCA access category that won (None = DCF)
    """Generator: one HE MU PPDU to `users` (STAs with downlink data).
    Returns True if at least one user's Block Ack came back."""
    cfg, env, ch = ap.config, ap.env, ap.channel
    width, gi, mcs = cfg.channel_width_mhz, cfg.guard_interval_ns, cfg.mcs
    # Rashed-Step 25.C-10-20-2026-start
    nss = wifi_phy.n_ss(cfg)
    groups = mu_groups(width, len(users), cfg.mu_mimo_users) if getattr(cfg, "mu_mimo_users", 1) > 1 else None
    if groups is None:
        plan = _plan(cfg, width, users, lambda s: dl_demand(ap, s, ac))  # 25.D: = ru_plan(width, len(users)) by default
        ks = [1] * len(users)
    else:                                   # MU-MIMO: users of one group share an RU, one stream each
        rus = ru_plan(width, len(groups))
        plan = [ru for ru, k in zip(rus, groups) for _ in range(k)]
        ks = [k for k in groups for _ in range(k)]
        ap.ofdma_stats["mu_groups"] = ap.ofdma_stats.get("mu_groups", 0) + sum(1 for k in groups if k > 1)
    pre = mu_preamble_us(len(users)) + wifi_phy.ltf_extra_us("he", max(nss, max(ks)), gi)
    # Rashed-Step 25.C-10-20-2026-end
    budget = wifi_ampdu.ppdu_budget_us(ap, ac) - pre   # 21.C: TXOP limit of the AC (= aPPDUMaxTime without EDCA)
    em = getattr(cfg, "error_model", None)
    required = ap.required_sinr_db()
    required_mu = required - wifi_phy.ss_penalty_db(nss)   # 25.C: an MU-MIMO user gets one stream
    per_user = []
    for sta, (tones, off, bw), k in zip(users, plan, ks):
        rate = ru_rate_mbps(tones, mcs, gi, nss if k == 1 else 1)  # 25.C
        per = (lambda r: (lambda payload: (Times.mac_overhead + payload * 8 + 32) / r))(rate)
        q = ap.ofdma_dl[sta.name]
        # Rashed-Step 21.C-10-11-2026-start
        pend = [p for p in ap.ofdma_dl_pending[sta.name] if ac is None or p.traffic_class == ac]
        # Rashed-Step 21.C-10-11-2026-end
        mpdus, used = _fill(lambda q=q, s=sta: ap._ofdma_take_dl(s, ac), lambda p, q=q: q.insert(0, p), per, budget,
                            cfg.ampdu_max_mpdus, pend)
        per_user.append((sta, tones, off, bw, per, mpdus, used))
        ap.ofdma_stats["ru_tones"][tones] = ap.ofdma_stats["ru_tones"].get(tones, 0) + 1
    data_us = max(u[6] for u in per_user)
    start = env.now
    dur = pre + data_us
    txs = []
    for (sta, tones, off, bw, per, mpdus, used), k in zip(per_user, ks):
        p_dbm = cfg.tx_power_dbm + 10.0 * math.log10(tones / FULL_TONES[width]) - 10.0 * math.log10(k)  # 25.C: / k users
        tx = _ru_tx(cfg, ap.name, ap.current_pos(), sta.current_pos(), p_dbm, cfg.f_ghz + off, bw, start, dur,
                    mpdus[0] if mpdus else None)
        ch.register_tx(tx)
        # Rashed-Step pre_21.E-10-11-2026-start
        tx.ru_secondary = bool(txs)             # all but the first RU: not counted again
        # Rashed-Step pre_21.E-10-11-2026-end
        txs.append(tx)
    results = []
    try:
        yield env.timeout(dur)
        for tx, (sta, tones, off, bw, per, mpdus, used), k in zip(txs, per_user, ks):
            # Rashed-Step 25.C-10-20-2026-start
            mu = (k, cfg.mu_mimo_residual_db) if k > 1 else None
            req = required_mu if k > 1 else required
            header_ok = decode_ok(em, mu_sinr_db(ch.sinr_db(tx, window=(start, start + pre)), *(mu or (1, 0.0))), req)
            results.append(_decode_user(ch, em, tx, start + pre, mpdus, per, req, header_ok, mu))
            # Rashed-Step 25.C-10-20-2026-end
        yield env.timeout(0)
    finally:
        # Rashed-Step pre_21.E-10-11-2026-start
        n_ok = sum(1 for r in results if r)
        for tx, res in zip(txs, results + [[]] * (len(txs) - len(results))):
            tx.ppdu_ok = n_ok > 0                     # read on the primary RU only
            tx.airtime_share = 1.0 / n_ok if n_ok else 1.0
            ch.unregister_tx(tx, success=bool(res))
        # Rashed-Step pre_21.E-10-11-2026-end
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
                # Rashed-Step pre_21.E-10-11-2026-start
                b.ru_secondary = bool(btxs)
                # Rashed-Step pre_21.E-10-11-2026-end
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
        # Rashed-Step 21.C-10-11-2026-start
        other = [p for p in ap.ofdma_dl_pending[sta.name] if not (ac is None or p.traffic_class == ac)]
        # Rashed-Step 21.C-10-11-2026-end
        ap.ofdma_dl_pending[sta.name] = other + _settle(ap, mpdus, dec, ack, cfg.r_limit, ap.packet_log, ch, now)
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
    plan = _plan(cfg, width, users, ul_demand)                   # 25.D: = ru_plan(width, n) by default
    nss = wifi_phy.n_ss(cfg)                                     # 25.C
    budget = cfg.ampdu_max_ppdu_us - TB_PREAMBLE_US - wifi_phy.ltf_extra_us("he", nss, gi)
    per_user = []
    for sta, (tones, off, bw) in zip(users, plan):
        rate = ru_rate_mbps(tones, mcs, gi, nss)                 # 25.C
        per = (lambda r: (lambda payload: (Times.mac_overhead + payload * 8 + 32) / r))(rate)
        mpdus, used = _fill(sta._take_queued_packet, sta._put_back_packet, per, budget, cfg.ampdu_max_mpdus,
                            sta.ofdma_ul_pending)
        per_user.append((sta, tones, off, bw, per, mpdus, used))
        ap.ofdma_stats["ru_tones"][tones] = ap.ofdma_stats["ru_tones"].get(tones, 0) + 1
    data_us = max(u[6] for u in per_user)
    start = env.now
    dur = TB_PREAMBLE_US + wifi_phy.ltf_extra_us("he", nss, gi) + data_us   # 25.C: + LTFs
    txs = []
    for (sta, tones, off, bw, per, mpdus, used), h in zip(per_user, heard):
        if h and mpdus and not getattr(sta, "_tx_active", False):   # 21.C: a STA busy with its own exchange can't answer
            tx = _ru_tx(cfg, sta.name, sta.current_pos(), ap.current_pos(), cfg.tx_power_dbm, cfg.f_ghz + off,
                        bw, start, dur, mpdus[0])
            ch.register_tx(tx)
            # Rashed-Step pre_21.E-10-11-2026-start
            tx.ru_secondary = any(t is not None for _, t in txs)
            # Rashed-Step pre_21.E-10-11-2026-end
            txs.append((sta, tx))
            # Rashed-Step 21.C-10-11-2026-start
            sta._in_tb = True                  # its own contention treats this as busy
            # Rashed-Step 21.C-10-11-2026-end
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
                # Rashed-Step pre_21.E-10-11-2026-start
                n_ok = sum(1 for r in results if r)
                tx.ppdu_ok = n_ok > 0
                tx.airtime_share = 1.0 / n_ok if n_ok else 1.0
                # Rashed-Step pre_21.E-10-11-2026-end
                ch.unregister_tx(tx, success=bool(res))
                # Rashed-Step 21.C-10-11-2026-start
                sta._in_tb = False
                if getattr(cfg, "mu_edca", None) is not None:   # MU EDCA timer starts with the trigger-based PPDU
                    sta._mu_until = env.now + cfg.mu_edca.timer_us
                # Rashed-Step 21.C-10-11-2026-end
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
