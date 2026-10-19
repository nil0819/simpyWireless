# Rashed-Step 8.A-08-06-2026-start
"""
Step 8.A: Packet - the shared, technology-agnostic unit of data this
simulator moves around, plus TrafficConfig - the knob that decides how
packets get created (saturated / poisson / cbr). See "Project details/
Step 8.txt" for the full rationale.

WHY THIS EXISTS
Until now, every technology's "thing being transmitted" (wifi.Frame,
nru.Transmission_NR, channel.ActiveTx) has been a technology-specific,
duration-and-diagnostics-only object - real enough to drive airtime/
SINR math, but with no persistent identity, no notion of a generic
"packet" a queue or a sniffer could reason about independent of which
technology sent it, and (for WiFi at least) already a fixed payload
size assumed to always be ready to send (the "saturated" traffic
model baked into Steps 5/6's validation work). Packet is the new,
shared layer underneath all of that: every technology's own
Frame/Transmission_NR/ActiveTx gets an optional `packet` field
pointing at one of these, so a Packet's identity/size/retry history/
delivery status is visible regardless of which technology carried it.

WHAT THIS FILE DELIBERATELY DOES NOT DO YET
  - Packet.header_bytes is a plain int set by whoever constructs the
    Packet (wifi.py currently uses Times.mac_overhead//8, i.e. the
    same 40-byte MAC header size the PHY duration formula already
    assumes) - there's no per-technology header-size table here yet.
  - Nothing in this file computes on-air duration from a Packet's
    size - that wiring (Times.py taking a Packet's real size instead
    of a fixed config.data_size scalar) is explicitly deferred to a
    later Step 8 sub-step (8.C in the roadmap), to keep this one
    additive/non-behavior-changing.
  - No fragmentation/aggregation, no real payload bytes (content) -
    payload_bytes is a size only, matching this simulator's existing
    MAC/PHY-layer scope (not an application-layer simulator).
"""

from dataclasses import dataclass
from typing import Dict, Optional
import random
import statistics


# Rashed-Step 10.A-08-07-2026-start
# Canonical traffic-class labels this simulator recognizes, in PRIORITY
# ORDER (index 0 = highest priority) - deliberately named after Wi-Fi
# WMM's real Access Categories (AC_VO/AC_VI/AC_BE/AC_BK, 802.11e) rather
# than something simulator-specific, since that's the real standard
# Step 10.B (differentiated EDCA-style channel access, not built yet)
# will map these onto. "best_effort" is the class every Packet has
# always implicitly been before this step - see Packet.traffic_class's
# own default and TrafficConfig.traffic_class_mix's docstring for why
# that keeps every pre-Step-10.A run byte-identical.
QOS_TRAFFIC_CLASSES = ("voice", "video", "best_effort", "background")


def traffic_class_priority_rank(traffic_class: str) -> int:
    """
    Lower return value = higher priority (0 = "voice", the highest).
    An unrecognized label (any string not in QOS_TRAFFIC_CLASSES) ranks
    LOWEST rather than raising - deliberately lenient, matching this
    project's existing "don't validate caller-supplied labels" policy
    (e.g. attacker.packet_attacker.spoof()'s forged_source isn't
    checked against the real topology either). Not used by anything
    yet in Step 10.A itself - defined here as the shared ordering a
    later differentiated-channel-access phase (Step 10.B) will consume,
    so that phase doesn't need to invent its own ranking scheme.
    """
    try:
        return QOS_TRAFFIC_CLASSES.index(traffic_class)
    except ValueError:
        return len(QOS_TRAFFIC_CLASSES)


def pick_traffic_class(traffic_class_mix: "dict[str, float]") -> str:
    """
    Weighted random draw of one traffic-class label from
    traffic_class_mix (e.g. {"voice": 0.1, "video": 0.2,
    "best_effort": 0.5, "background": 0.2} - weights don't need to sum
    to 1, random.choices() normalizes them itself). Split out as its
    own function (rather than inlined in wifi.py/nru.py) so the actual
    draw logic has one implementation both technologies share and so
    it's independently unit-testable without constructing a full WiFi/
    Gnb object. Uses the global `random` module directly (not a
    per-object Random instance) - matches every other random draw in
    this simulator (wifi.py/nru.py's own traffic generators, backoff
    slot selection, etc.), all of which go through the single
    `random.seed(seed)` call at the top of run_simulation() for
    reproducibility. Callers are responsible for only calling this when
    traffic_class_mix is not None (see TrafficConfig.traffic_class_mix's
    docstring on why the None case must skip this entirely, not just
    skip via a trivial single-key dict) - keeps this function simple
    and its one random.choices() call an honest, minimal footprint.
    """
    classes = list(traffic_class_mix.keys())
    weights = list(traffic_class_mix.values())
    return random.choices(classes, weights=weights)[0]
# Rashed-Step 10.A-08-07-2026-end


# Rashed-Step 10.B-08-07-2026-start
@dataclass
class EdcaAcParams:
    """
    Per-Access-Category EDCA channel-access parameters (802.11e). cw_min/
    cw_max are contention-window bounds in SLOTS (same units as
    wifi.Config.cw_min/cw_max already use for the non-EDCA path); aifsn
    is the Arbitration Inter-Frame Space Number - the AIFS itself
    (analogous to DCF's fixed DIFS) is aifsn * Times.t_slot + Times.
    t_sifs, computed by Times.get_aifs_us(). TXOP bursting (multiple
    frames per won contention) is NOT modeled - see wifi.WiFi's EDCA
    docstring for the full scope note.
    """
    cw_min: int
    cw_max: int
    aifsn: int


# Standard default EDCA parameter set (802.11-2020 Table 9-155 / the
# same values widely published as the Wi-Fi Alliance WMM default set),
# for the legacy-OFDM/non-HT PHY this simulator's Times.py already
# models (aCWmin=15, aCWmax=1023, aSlotTime=9us, aSIFSTime=16us - see
# Times.py). AC_VO/AC_VI's aifsn=2 giving AIFS=34us is a deliberate,
# checkable consistency point: that's EXACTLY Times.t_difs (fixed at
# 34us since Step 6.A's DIFS bugfix) - i.e. non-EDCA DCF's single DIFS
# IS, by construction, what AC_VO/AC_VI's AIFS already equals. Keyed by
# the same QOS_TRAFFIC_CLASSES labels (voice=AC_VO, video=AC_VI,
# best_effort=AC_BE, background=AC_BK) rather than raw "AC_VO"-style
# strings, so this table plugs directly into Packet.traffic_class /
# TrafficConfig.traffic_class_mix without a separate label mapping.
DEFAULT_EDCA_PARAMS: Dict[str, EdcaAcParams] = {
    "voice": EdcaAcParams(cw_min=3, cw_max=7, aifsn=2),
    "video": EdcaAcParams(cw_min=7, cw_max=15, aifsn=2),
    "best_effort": EdcaAcParams(cw_min=15, cw_max=1023, aifsn=3),
    "background": EdcaAcParams(cw_min=15, cw_max=1023, aifsn=7),
}
# Rashed-Step 10.B-08-07-2026-end


@dataclass(slots=True)  # Rashed-Step 24.B-10-19-2026: no per-object __dict__ (memory)
class Packet:
    packet_id: str
    source: str
    destination: str
    payload_bytes: int
    header_bytes: int
    # "DATA" (the only kind actually produced as of Step 8.A/8.B - ACK
    # stays the existing fixed-duration constant in Times.py for now),
    # "ACK"/"CONTROL"/"MGMT" reserved for a later sub-step.
    packet_type: str = "DATA"
    created_at: float = 0.0
    retry_count: int = 0
    # "PENDING" (in flight / still queued or being retried), "DELIVERED"
    # (successfully sent, see delivered_at), or "DROPPED" (gave up after
    # exceeding the technology's retry limit).
    status: str = "PENDING"
    delivered_at: Optional[float] = None
    # Rashed-Step 10.A-08-07-2026-start
    # QoS traffic class - see QOS_TRAFFIC_CLASSES for the recognized
    # labels (not enforced/validated here, same leniency policy as
    # traffic_class_priority_rank()). Default "best_effort" matches
    # every Packet's implicit class before this field existed, so any
    # code that doesn't know about traffic classes yet (every call site
    # before Step 10.A, and every technology/scenario that never opts
    # into TrafficConfig.traffic_class_mix) is completely unaffected -
    # this field is added at the END of the dataclass specifically so
    # it cannot shift any existing POSITIONAL Packet(...) construction
    # call's argument indices (every real call site in this codebase
    # already uses keyword arguments, but appending at the end is the
    # zero-risk choice regardless).
    traffic_class: str = "best_effort"
    # Rashed-Step 10.A-08-07-2026-end
    # Rashed-Step 13.A-08-23-2026-start
    # Channel quality (SINR, dB) measured by the TRANSMITTER at the
    # instant this packet's transmission attempt was checked for
    # success/failure (channel.sinr_db(...) inside wifi.py's
    # send_frame()/send_frame_edca() and nru.py's send_transmission()).
    # None until that point (queued/never-attempted packets), and also
    # recorded on FAILED attempts, not just delivered ones - a failed
    # attempt's SINR is real channel-quality information too, and only
    # logging successes would bias any downstream analysis/training
    # toward "good link" conditions. Added at the END of the dataclass,
    # same zero-risk convention as traffic_class (Step 10.A) - no
    # existing positional Packet(...) call site is affected.
    measured_sinr_db: Optional[float] = None
    # Rashed-Step 13.A-08-23-2026-end
    # Rashed-Step 23.C-10-17-2026-start
    # FTP Model 3 (TrafficConfig mode "ftp3"): the file this packet is part
    # of, how many packets / bytes that file has, and when it arrived.
    file_id: Optional[str] = None
    file_packets: int = 0
    file_bytes: int = 0
    file_arrival: Optional[float] = None
    # Rashed-Step 23.C-10-17-2026-end
    # Rashed-Step 24.B-10-19-2026-start
    # Set at runtime by licensed NR (the slot's transport block, 22.D) and
    # the A-MPDU code (duplicate until a Block Ack confirms it, 20.B); with
    # __slots__ they have to be declared.
    tb_bits: Optional[float] = None
    _dup: bool = False
    # Rashed-Step 24.B-10-19-2026-end

    def total_bytes(self) -> int:
        return self.payload_bytes + self.header_bytes


@dataclass
class TrafficConfig:
    """
    Controls how a node's packets get created. Passed as an optional
    constructor arg to WiFi/Gnb (None, the default, is normalized to
    TrafficConfig(mode="saturated") internally - i.e. every existing
    caller that doesn't know about this yet gets EXACTLY today's
    always-has-something-to-send behavior, byte-identical to before
    Step 8.B).

    mode:
      "saturated" - the node always has a packet ready the instant it
        gets channel access (today's implicit behavior, made explicit).
        No queue/arrival process is actually used in this mode - see
        wifi.WiFi._next_packet()/nru.Gnb's equivalent.
      "poisson" - packets arrive per a Poisson process at
        arrival_rate_pps (packets/sec); the node's queue can genuinely
        sit empty, and the node does not contend for the channel while
        it has nothing queued.
      "cbr" - constant bit/packet rate: packets arrive at a fixed
        interval of 1/arrival_rate_pps seconds. Same "can sit idle"
        behavior as poisson, just deterministic inter-arrival times.
      "ftp3" - 3GPP TR 36.889 FTP Model 3 (Step 23.C): FILES arrive per a
        Poisson process at arrival_rate_pps files/s (per cell; a per-UE
        buffer gets its share), each file_size_bytes (0.5 MB) split into
        packet_size_bytes packets that arrive together, tagged with the
        file (Packet.file_id). common/ftp.py derives the user-perceived
        throughput (file size / transfer time).
    """
    mode: str = "saturated"
    arrival_rate_pps: float = 100.0
    # None (default) = use the node's own config.data_size for payload
    # size, matching today's fixed-size behavior exactly. Set this to
    # override with a different fixed size without touching the
    # node's main Config/Config_NR object.
    packet_size_bytes: Optional[int] = None
    # Rashed-Step 10.A-08-07-2026-start
    # None (default) = every packet this node creates gets
    # traffic_class="best_effort" (Packet's own default) via a plain
    # hardcoded assignment - NO random draw happens at all, so a run
    # with this unset is not just behaviorally but RNG-footprint
    # identical to every pre-Step-10.A run (an important distinction in
    # this codebase - see Step 8.E's writeup on how even an
    # unconsumed-but-still-called random draw can shift unrelated
    # downstream random sequences and break regression baselines).
    # Set to a dict of {traffic_class_label: weight, ...} (labels
    # should normally be from QOS_TRAFFIC_CLASSES, though this isn't
    # enforced - see traffic_class_priority_rank()'s docstring) to have
    # each new packet draw its class via pick_traffic_class() instead -
    # e.g. {"voice": 0.1, "video": 0.2, "best_effort": 0.5,
    # "background": 0.2} models one node generating a realistic mixed
    # traffic load, rather than every packet being the same class.
    traffic_class_mix: "Optional[dict[str, float]]" = None
    # Rashed-Step 10.A-08-07-2026-end
    file_size_bytes: int = 500_000  # Rashed-Step 23.C-10-17-2026: "ftp3" only (TR 36.889: 0.5 MB)
# Rashed-Step 8.A-08-06-2026-end


# Rashed-Step 23.C-10-17-2026-start
def ftp3_file(make_packet, traffic: "TrafficConfig", file_id: str, now: float,
              destination: Optional[str] = None) -> "list[Packet]":
    """One FTP Model 3 file: ceil(file_size / packet size) packets from
    make_packet(), tagged with the file (and sent to `destination` if
    given)."""
    first = make_packet()
    size = max(1, first.total_bytes())
    n = max(1, -(-traffic.file_size_bytes // size))
    pkts = [first] + [make_packet() for _ in range(n - 1)]
    for p in pkts:
        p.file_id, p.file_packets, p.file_bytes, p.file_arrival = file_id, n, traffic.file_size_bytes, now
        if destination is not None:
            p.destination = destination
    return pkts
# Rashed-Step 23.C-10-17-2026-end


# Rashed-Step 8.G-08-06-2026-start
def compute_packet_stats(packets: "list[Packet]") -> dict:
    """
    Aggregate latency/loss stats over a list of Packets that have
    reached a terminal state (DELIVERED or DROPPED) - see wifi.WiFi/
    nru.Gnb's packet_log, populated by sent_completed()/sent_failed().
    A Packet still PENDING at the moment its owning node's log is read
    (e.g. mid-retry when the simulation ends) is deliberately excluded -
    it never reached a terminal state, so it has no delivered_at and no
    resolved fate to count as a loss or a success either way.

    Returns a plain dict (not a dataclass - this is a report snapshot,
    not a live object anything mutates) with:
      total            - len(delivered) + len(dropped) (PENDING excluded)
      delivered        - count of status == "DELIVERED"
      dropped          - count of status == "DROPPED"
      loss_rate         - dropped / total, or 0.0 if total == 0
      avg_latency_us   - mean(delivered_at - created_at) over DELIVERED
                          packets only, or None if there are none
      min_latency_us   - min of the same set, or None if empty
      max_latency_us   - max of the same set, or None if empty
      # Rashed-Step 9.A-08-07-2026-start
      latency_stddev_us - population stddev (statistics.pstdev) of the
                          same latency set. 0.0 for exactly one
                          DELIVERED packet (no variation to observe,
                          not "unknown"), None only when there are zero.
      jitter_us         - mean absolute difference between EACH
                          DELIVERED packet's latency and the PREVIOUS
                          one's, in packet-creation order (sorted by
                          created_at - NOT packet_log append order,
                          which can interleave multiple nodes'
                          packets arbitrarily when this function is
                          called on an aggregated cross-node list).
                          None if fewer than 2 DELIVERED packets (no
                          successive pair to compare). This is the
                          conventional "packet delay variation"
                          definition (same spirit as RFC 3550's jitter,
                          simplified for this simulator's timestamps).
      p50_latency_us,
      p95_latency_us,
      p99_latency_us    - percentiles of the same latency set, linear-
                          interpolation method (same convention as
                          numpy's default 'linear' interpolation) - see
                          _percentile() below. None if empty.
      # Rashed-Step 9.A-08-07-2026-end
    """
    # Rashed-Step 24.B-10-19-2026-start
    # One pass over `packets` (any iterable - a list or a CompactPacketLog
    # view), keeping only (created_at, latency) per delivered packet instead
    # of lists of Packet objects. Same values, same order, same stable sort.
    return _stats_from(*_accumulate(packets))


def _accumulate(packets):
    n_delivered = n_dropped = 0
    pairs = []  # (created_at, latency) of DELIVERED packets with delivered_at, in input order
    for p in packets:
        st = p.status
        if st == "DELIVERED":
            n_delivered += 1
            if p.delivered_at is not None:
                pairs.append((p.created_at, p.delivered_at - p.created_at))
        elif st == "DROPPED":
            n_dropped += 1
    return n_delivered, n_dropped, pairs


def _stats_from(n_delivered: int, n_dropped: int, pairs: list) -> dict:
    total = n_delivered + n_dropped
    latencies = [lat for _c, lat in pairs]
    # Rashed-Step 9.A-08-07-2026-start
    # Sorted by created_at (generation order) - the order packets sit in the
    # input is whatever order they were logged in, which for a cross-node
    # aggregate is arbitrary relative to when each was GENERATED. Jitter is
    # only a meaningful "variation between consecutive packets" measure if
    # "consecutive" means consecutive in time. (24.B: a stable sort of the
    # (created_at, latency) pairs - same order as sorting the packets.)
    delivered_by_creation = sorted(pairs, key=lambda t: t[0])
    latencies_in_order = [lat for _c, lat in delivered_by_creation]
    # Rashed-Step 24.B-10-19-2026-end

    if len(latencies_in_order) >= 2:
        diffs = [
            abs(latencies_in_order[i] - latencies_in_order[i - 1])
            for i in range(1, len(latencies_in_order))
        ]
        jitter_us = sum(diffs) / len(diffs)
    else:
        jitter_us = None

    latency_stddev_us = statistics.pstdev(latencies) if latencies else None

    sorted_latencies = sorted(latencies)
    p50 = _percentile(sorted_latencies, 50)
    p95 = _percentile(sorted_latencies, 95)
    p99 = _percentile(sorted_latencies, 99)
    # Rashed-Step 9.A-08-07-2026-end

    return {
        "total": total,
        "delivered": n_delivered,  # Rashed-Step 24.B-10-19-2026 (was len(delivered))
        "dropped": n_dropped,
        "loss_rate": (n_dropped / total) if total > 0 else 0.0,
        "avg_latency_us": (sum(latencies) / len(latencies)) if latencies else None,
        "min_latency_us": min(latencies) if latencies else None,
        "max_latency_us": max(latencies) if latencies else None,
        # Rashed-Step 9.A-08-07-2026-start
        "latency_stddev_us": latency_stddev_us,
        "jitter_us": jitter_us,
        "p50_latency_us": p50,
        "p95_latency_us": p95,
        "p99_latency_us": p99,
        # Rashed-Step 9.A-08-07-2026-end
    }
# Rashed-Step 8.G-08-06-2026-end


# Rashed-Step 9.A-08-07-2026-start
def _percentile(sorted_values: list, p: float):
    """
    Linear-interpolation percentile (same convention as numpy's default
    'linear' method): rank = (n-1) * p/100, interpolate between the
    values at floor(rank) and ceil(rank). sorted_values must already be
    sorted ascending. Returns None for an empty list.

    Example: sorted_values=[100,150,200,250,300], p=95 -> rank=3.8 ->
    interpolate between index 3 (250) and index 4 (300) at 80% ->
    250 + 0.8*(300-250) = 290.
    """
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * (p / 100.0)
    lower = int(rank // 1)
    upper = lower + 1
    if upper >= len(sorted_values):
        return sorted_values[-1]
    frac = rank - lower
    return sorted_values[lower] + frac * (sorted_values[upper] - sorted_values[lower])


def compute_packet_stats_by_node(node_packet_logs: "dict[str, list[Packet]]") -> dict:
    """
    Per-node breakdown: {node_name: packet_log, ...} ->
    {node_name: compute_packet_stats(packet_log), ...}. Same underlying
    computation as compute_packet_stats(), just run once per node
    instead of once over an aggregated cross-node list - useful for
    spotting a single AP/gNB behaving differently from its peers (e.g.
    one station stuck near the edge of range with much higher loss)
    that an aggregate-only number would average away.
    """
    return {name: compute_packet_stats(log) for name, log in node_packet_logs.items()}
# Rashed-Step 9.A-08-07-2026-end


# Rashed-Step 10.C-08-11-2026-start
# Representative one-way latency budgets per traffic class (Packet.
# traffic_class - see QOS_TRAFFIC_CLASSES above), used only to compute
# an SLA-style "% of DELIVERED packets under budget" metric in
# compute_packet_stats_by_class() below. Real, citable numbers, not
# invented for this simulator:
#   voice: 150000us (150ms) - ITU-T G.114's well-known one-way delay
#     recommendation for acceptable conversational voice quality (the
#     same "voice needs to be fast" reasoning behind WMM/802.11e's
#     AC_VO getting the shortest CW/AIFSN, which QOS_TRAFFIC_CLASSES'
#     "voice" label already borrows from - see Step 10.A/10.B).
#   video: 400000us (400ms) - a commonly cited looser bound for
#     interactive/conversational video (ITU-T G.1010 places
#     "conversational video" in a category that tolerates more delay
#     than voice but still wants well under a second end-to-end).
#   best_effort/background: None - no standardized SLA exists for
#     these classes by design (that's WHY they're lower priority in
#     EDCA), so compute_packet_stats_by_class() skips the SLA
#     calculation for them entirely. None here means "not applicable",
#     NOT "0us budget, always violated".
QOS_LATENCY_BUDGET_US = {
    "voice": 150_000,
    "video": 400_000,
    "best_effort": None,
    "background": None,
}


def compute_packet_stats_by_class(packets: "list[Packet]", latency_budget_us: "Optional[Dict[str, Optional[float]]]" = None) -> dict:
    """
    Per-traffic-class breakdown of compute_packet_stats() (Step 9.A),
    keyed by Packet.traffic_class (Step 10.A) - {"voice": {...},
    "video": {...}, ...} - plus 3 extra SLA-style keys per class on top
    of compute_packet_stats()'s existing ones:
      sla_budget_us       - the latency budget used for this class (see
                             QOS_LATENCY_BUDGET_US), or None if this
                             class has no standardized budget.
      sla_compliance_rate - fraction of DELIVERED packets in this class
                             whose latency (delivered_at - created_at)
                             was <= sla_budget_us. None if sla_budget_us
                             is None (not applicable), or if there are
                             zero DELIVERED packets in this class (no
                             data to compute a rate from - NOT the same
                             as 0.0, which would mean "100% violated").
      sla_violation_rate  - 1.0 - sla_compliance_rate. Same None cases.

    Only traffic classes actually PRESENT in `packets` become keys - an
    empty input list returns an empty dict, not one key per
    QOS_TRAFFIC_CLASSES member zero-filled - matching
    compute_packet_stats_by_node()'s "only report what's actually
    there" convention. A packet with a traffic_class that isn't in
    QOS_TRAFFIC_CLASSES (e.g. a typo'd --wifi-traffic-class-mix label -
    see 10.A's deliberate leniency) still becomes its own key here,
    just with sla_budget_us=None (an unrecognized label is never in
    QOS_LATENCY_BUDGET_US, so it falls through to the same "no SLA"
    treatment as best_effort/background).

    latency_budget_us: optional override for QOS_LATENCY_BUDGET_US
    (e.g. a caller wanting a stricter voice budget for a specific
    scenario) - defaults to the module-level table when omitted/None.
    """
    budgets = latency_budget_us if latency_budget_us is not None else QOS_LATENCY_BUDGET_US
    # Rashed-Step 24.B-10-19-2026-start
    # One pass: per class the delivered / dropped counts and (created_at,
    # latency) pairs (a class whose packets are all still pending still gets
    # its key, as before).
    acc = {}
    for p in packets:
        a = acc.setdefault(p.traffic_class, [0, 0, []])
        st = p.status
        if st == "DELIVERED":
            a[0] += 1
            if p.delivered_at is not None:
                a[2].append((p.created_at, p.delivered_at - p.created_at))
        elif st == "DROPPED":
            a[1] += 1
    result = {}
    for cls in sorted(acc):
        n_del, n_drop, pairs = acc[cls]
        stats = _stats_from(n_del, n_drop, pairs)
        budget = budgets.get(cls)
        if budget is None:
            stats["sla_budget_us"] = None
            stats["sla_compliance_rate"] = None
            stats["sla_violation_rate"] = None
        else:
            delivered_latencies = [lat for _c, lat in pairs]
            # Rashed-Step 24.B-10-19-2026-end
            stats["sla_budget_us"] = budget
            if delivered_latencies:
                within_budget = sum(1 for lat in delivered_latencies if lat <= budget)
                compliance = within_budget / len(delivered_latencies)
                stats["sla_compliance_rate"] = compliance
                stats["sla_violation_rate"] = 1.0 - compliance
            else:
                stats["sla_compliance_rate"] = None
                stats["sla_violation_rate"] = None

        result[cls] = stats
    return result
# Rashed-Step 10.C-08-11-2026-end


# Rashed-Step 10.D-08-11-2026-start
def _voice_e_model_mos(avg_latency_us, loss_rate):
    """
    Real, citable QoE model for voice: a simplified form of the ITU-T
    G.107 E-model, specifically the closed-form delay/loss impairment
    formulas from Cole & Rosenbluth, "Voice over IP Performance
    Monitoring", ACM SIGCOMM Computer Communication Review, 2001 - a
    widely used simplification of the full E-model for VoIP QoE
    estimation that needs only mean one-way delay and packet loss rate
    (both of which this simulator already tracks via
    compute_packet_stats()), not the full E-model's much larger
    parameter set (room noise, echo, talker levels, etc. - not modeled
    by this simulator's PHY/MAC layers at all).

    Id (delay impairment), Cole & Rosenbluth eq. for one-way delay d
    (ms), no echo term (this simulator has no echo path concept):
        Id = 0.024*d + 0.11*(d - 177.3) * H(d - 177.3)
    where H is the Heaviside step (0 for d <= 177.3, 1 otherwise) -
    delay under ~177ms has a small linear cost; beyond that, a much
    steeper additional penalty kicks in (this is the same "impairment
    accelerates past ~150-180ms" shape behind ITU-T G.114's 150ms
    voice budget already used in Step 10.C's QOS_LATENCY_BUDGET_US).

    Ie-eff (equipment impairment, codec + packet loss), same source,
    assuming G.711 (Ie=0 base codec impairment, Bpl=25.1 packet-loss
    robustness factor - G.711's own published constants, not tuned for
    this simulator):
        Ie_eff = Ie + (95 - Ie) * (Ppl / (Ppl + Bpl))
    where Ppl is packet loss AS A PERCENTAGE (0-100, not a 0-1 fraction).

    R = 93.2 - Id - Ie_eff (R0=93.2, Is=0, A=0 - the "best case" basic
    signal-to-noise term and no user-advantage bonus, matching the
    common simplified-E-model convention when only transport-layer
    delay/loss are being modeled, same as Cole & Rosenbluth's own
    worked examples).

    R-to-MOS conversion is the standard ITU-T G.107 formula:
        MOS = 1                                   if R < 0
        MOS = 4.5                                 if R > 100
        MOS = 1 + 0.035*R + R*(R-60)*(100-R)*7e-6  otherwise
    Verified against well-known reference points before use: R=93.2
    (zero delay, zero loss) -> MOS=4.409 (the commonly cited "G.711,
    no impairment" ceiling of ~4.4, not 5.0 - even a perfect network
    can't make G.711 sound like an in-person conversation); R=100 ->
    MOS=4.5 exactly (the formula's own ceiling).

    Returns (R, mos) - both None if avg_latency_us is None (no
    DELIVERED packets to measure delay from at all - "no data", not
    "worst possible quality").
    """
    if avg_latency_us is None:
        return None, None

    d_ms = avg_latency_us / 1000.0
    Id = 0.024 * d_ms + 0.11 * (d_ms - 177.3) * (1.0 if d_ms > 177.3 else 0.0)

    Ie = 0.0    # G.711, no codec-inherent impairment
    Bpl = 25.1  # G.711 packet-loss robustness factor
    Ppl = (loss_rate or 0.0) * 100.0  # fraction -> percent
    Ie_eff = Ie + (95.0 - Ie) * (Ppl / (Ppl + Bpl))

    R = 93.2 - Id - Ie_eff

    if R < 0:
        mos = 1.0
    elif R > 100:
        mos = 4.5
    else:
        mos = 1 + 0.035 * R + R * (R - 60) * (100 - R) * 7e-6
    return R, mos


def _video_qoe_proxy_score(avg_latency_us, loss_rate, budget_us):
    """
    NOT a standardized metric - there is no video equivalent of the
    E-model with the same universal acceptance (real video QoE models
    like ITU-T P.1203 need bitstream/codec/resolution/rebuffering
    details this simulator's MAC/PHY-only scope has no concept of).
    This is a clearly-labeled, simulator-local heuristic: a 1 (worst)
    to 5 (best) score that penalizes loss and over-budget latency
    linearly, capped, purely to give video traffic SOME illustrative
    per-class quality signal alongside voice's real MOS - callers must
    not treat this as directly comparable to a real MOS score from
    voice or from any published video QoE study.

    score = 5.0
            - up to 2.0 points for loss_rate, scaling linearly to the
              full 2.0-point penalty at 5% loss or worse (an arbitrary
              but documented threshold - real video codecs' actual
              loss tolerance varies hugely by codec/GOP structure,
              which this simulator does not model)
            - up to 2.0 points for latency exceeding budget_us, scaling
              linearly from 0 penalty at exactly the budget to the full
              2.0-point penalty at 2x budget or worse
    Clamped to [1.0, 5.0]. Returns None if avg_latency_us is None (no
    DELIVERED packets) or budget_us is None (no budget to measure
    "over budget" against, e.g. a class other than video using this
    function with a custom budget table).
    """
    if avg_latency_us is None or budget_us is None:
        return None

    loss_penalty = min(1.0, (loss_rate or 0.0) / 0.05) * 2.0

    latency_ratio_over = max(0.0, (avg_latency_us / budget_us) - 1.0)
    latency_penalty = min(1.0, latency_ratio_over) * 2.0

    score = 5.0 - loss_penalty - latency_penalty
    return max(1.0, min(5.0, score))


def compute_qoe_by_class(stats_by_class: dict) -> dict:
    """
    QoE scoring layer built ON TOP OF compute_packet_stats_by_class()'s
    output (Step 10.C) - takes that function's return value directly as
    input, does not recompute anything from raw Packets itself. Adds 2
    new keys per class:
      qoe_score - voice: a real MOS (1.0-4.5) via _voice_e_model_mos().
                  video: a simulator-local 1.0-5.0 heuristic via
                  _video_qoe_proxy_score() - NOT comparable to voice's
                  MOS scale or any standardized video metric.
                  best_effort/background (and any unrecognized class):
                  None - QoE (perceived quality by a human observer) is
                  not a meaningful concept for non-interactive best-
                  effort/background data traffic the way it is for
                  voice/video, so no score is invented for them.
      qoe_model - a short string identifying which model/formula
                  produced qoe_score (or None to match qoe_score=None),
                  so a caller reading a printed/exported result always
                  knows a voice MOS and a video proxy score are NOT the
                  same kind of number even though both happen to look
                  like "a number between 1 and 5".

    Returns a NEW dict (does not mutate the input stats_by_class or its
    per-class dicts) with every existing key from the input preserved
    plus the 2 new ones above.
    """
    result = {}
    for cls, stats in stats_by_class.items():
        stats = dict(stats)  # shallow copy - don't mutate caller's dict
        if cls == "voice":
            r_factor, mos = _voice_e_model_mos(stats.get("avg_latency_us"), stats.get("loss_rate"))
            stats["qoe_score"] = mos
            stats["qoe_r_factor"] = r_factor
            stats["qoe_model"] = "E-model (ITU-T G.107, Cole & Rosenbluth 2001 simplified formula, G.711 codec)"
        elif cls == "video":
            score = _video_qoe_proxy_score(
                stats.get("avg_latency_us"), stats.get("loss_rate"), stats.get("sla_budget_us"),
            )
            stats["qoe_score"] = score
            stats["qoe_model"] = "video_qoe_proxy (simulator-local heuristic, NOT a standardized metric)"
        else:
            stats["qoe_score"] = None
            stats["qoe_model"] = None
        result[cls] = stats
    return result
# Rashed-Step 10.D-08-11-2026-end


# Rashed-Step 12.A-08-13-2026-start
def write_packet_report(path: str, seed, sections: "dict[str, dict]") -> None:
    """
    Append a human-readable packet stats/QoE report block to `path`.

    WHY THIS EXISTS: simulation.py used to print every one of these
    aggregate/per-node/per-class/QoE dicts (Steps 8.G/9.A/10.C/10.D)
    directly to stdout, on every single run, unconditionally. Rashed
    asked (2026-08-13) to keep this information but stop cluttering the
    console with it - a plain text log file instead of a real packet-
    capture format (.pcap): pcap is a binary format for raw 802.11/
    Ethernet FRAMES (specific header bytes, timestamps, payloads) meant
    for tools like Wireshark - it has no way to represent an aggregate
    Python dict of stats (loss_rate, percentile latencies, QoE scores,
    etc.), so it would be the wrong tool here. A plain .log file with
    the exact same text each line used to print keeps this genuinely
    useful (still greppable, still diffable against old console output)
    without misusing a format meant for something else.

    `sections` is an ordered {label: stats_dict} mapping, e.g.
    {"packet stats WiFi": {...}, "packet stats NRU": {...}, ...} -
    written one "label: dict" line per entry, in the same str(dict)
    text a print(label, dict) call used to produce, so this file's
    content is byte-for-byte comparable to the console output it
    replaced (just redirected, not reformatted).

    Appends (does not overwrite) so multiple runs (-r N > 1, or
    repeated CLI invocations against the same path) accumulate,
    distinguished by a "seed=..." header line before each run's block -
    same "write, don't clobber, distinguish by seed" convention as
    export_packets_csv()/lool.csv.
    """
    import os
    from datetime import datetime

    file_already_had_content = os.path.isfile(path) and os.path.getsize(path) > 0
    with open(path, "a") as f:
        if file_already_had_content:
            f.write("\n")
        f.write(f"=== Packet Report (seed={seed}, {datetime.now().isoformat(timespec='seconds')}) ===\n")
        for label, stats in sections.items():
            f.write(f"{label}: {stats}\n")
# Rashed-Step 12.A-08-13-2026-end


# Rashed-Step 9.D-08-07-2026-start
# Packet-level CSV export - optional (opt-in via singleRun.py's
# --export-packets-csv, unset by default), for offline analysis at
# individual-packet granularity rather than the aggregate/per-node
# stats compute_packet_stats()/compute_packet_stats_by_node() already
# print. Deliberately its own proper multi-column CSV, NOT copying
# common/common.py's existing lool.csv pattern's two known bugs (a
# single quoted header field with embedded commas instead of separate
# columns, and a header/data column-count mismatch) - see "Project
# details/Step 9.txt"'s 9.D section for the lool.csv code this was
# checked against before writing this.
PACKET_CSV_HEADER = [
    "seed", "technology", "node", "packet_id", "source", "destination",
    "payload_bytes", "header_bytes", "total_bytes", "packet_type",
    "created_at_us", "retry_count", "status", "delivered_at_us", "latency_us",
    # Rashed-Step 10.E-08-11-2026-start
    # Deferred from Step 10.A ("No CLI/simulation.py prints of the
    # class mix, no CSV column (10.E)") - appended at the END of the
    # header, same reasoning as Packet.traffic_class itself being
    # appended at the end of the dataclass (Step 10.A): existing
    # column INDICES for every column before this one are unchanged,
    # so any offline script already parsing this CSV by position keeps
    # working; only a script that assumes a FIXED total column count
    # would need updating, and appending a header once per file means
    # that's a one-time, visible break (a header row present, not a
    # silent index misalignment).
    "traffic_class",
    # Rashed-Step 10.E-08-11-2026-end
    # Rashed-Step 13.A-08-23-2026-start
    # Same "append at the end" convention as traffic_class above - any
    # offline script reading columns by fixed position keeps working;
    # only a script assuming a fixed total column count needs updating.
    "measured_sinr_db",
    # Rashed-Step 13.A-08-23-2026-end
]


def packet_to_csv_row(packet: Packet, seed, technology: str, node: str) -> list:
    """
    Pure function (no I/O) - builds one CSV row (list, same column
    order as PACKET_CSV_HEADER) for a single Packet. Split out from
    export_packets_csv() so it's independently unit-testable without
    touching the filesystem. latency_us is delivered_at - created_at
    for a DELIVERED packet with a real delivered_at, "" otherwise
    (PENDING/DROPPED packets, or the theoretical case of a DELIVERED
    packet somehow missing delivered_at) - same "no defined latency"
    treatment compute_packet_stats() already uses for those cases,
    just expressed as an empty CSV cell instead of a Python None.
    """
    if packet.status == "DELIVERED" and packet.delivered_at is not None:
        latency_us = packet.delivered_at - packet.created_at
    else:
        latency_us = ""
    return [
        seed, technology, node, packet.packet_id, packet.source, packet.destination,
        packet.payload_bytes, packet.header_bytes, packet.total_bytes(), packet.packet_type,
        packet.created_at, packet.retry_count, packet.status,
        packet.delivered_at if packet.delivered_at is not None else "",
        latency_us,
        # Rashed-Step 10.E-08-11-2026-start
        packet.traffic_class,
        # Rashed-Step 10.E-08-11-2026-end
        # Rashed-Step 13.A-08-23-2026-start
        packet.measured_sinr_db if packet.measured_sinr_db is not None else "",
        # Rashed-Step 13.A-08-23-2026-end
    ]


def export_packets_csv(path: str, seed, node_packet_logs_by_tech: "dict[str, dict[str, list[Packet]]]") -> int:
    """
    Append one CSV row per Packet to `path`, across every (technology,
    node) pair in node_packet_logs_by_tech - e.g.
    {"WiFi": {"AP 1": [...], "AP 2": [...]}, "NRU": {"Gnb 1": [...]}}.
    Same "write header once if the file doesn't already exist, then
    append rows" pattern as lool.csv (so running with -r N > 1, or
    running the same --export-packets-csv path across multiple
    separate invocations, accumulates rows rather than overwriting) -
    the `seed` column is what keeps rows from different runs
    distinguishable once appended to the same file.

    Returns the number of rows written (packet count), mainly so a
    caller/scenario can print a confirmation without re-counting.
    """
    import csv
    import os

    write_header = not os.path.isfile(path)
    rows_written = 0
    with open(path, mode="a", newline="") as f:
        writer = csv.writer(f, delimiter=",", quotechar='"', quoting=csv.QUOTE_MINIMAL)
        if write_header:
            writer.writerow(PACKET_CSV_HEADER)
        for technology, node_logs in node_packet_logs_by_tech.items():
            for node, packets in node_logs.items():
                for p in packets:
                    writer.writerow(packet_to_csv_row(p, seed, technology, node))
                    rows_written += 1
    return rows_written
# Rashed-Step 9.D-08-07-2026-end
