# Rashed-Step 18.B-10-06-2026-start
"""
Per-UE byte buffers (Step 18.B) - the queue a gNB keeps for each UE's
downlink, and a UE keeps for its own uplink, so the scheduler serves
real bytes that arrived from a traffic source instead of turning each
slot's capacity straight into bits (full buffer).

Serving one transport block (TB) is two-phase, because the TB's fate is
only known after the slot's SINR is evaluated:
  1. segments(capacity_bytes): which packets (and how many bytes of
     each) a TB of that size carries, head of line first. Read-only.
  2. deliver(segments, now) on a decoded TB, or lose(segments) on a
     block error.
Only the owning scheduler takes from the head, once per slot, and new
arrivals only append at the tail, so the head can't change between the
two phases.

A packet bigger than what is left in the TB is split across TBs (its
remaining bytes go first in the next one) and counts as DELIVERED when
its last byte is. This is the segmentation RLC does (18.F adds RLC's
headers and reassembly rules).

There is no HARQ or ARQ yet (18.E/18.F): a block error drops every
packet that had bytes in that TB, including one whose earlier segments
already got through.

Limits: optional drop-tail at limit_bytes (None = unbounded).
"""
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, List, Optional, Tuple

from common.packet import Packet, TrafficConfig

# (packet, bytes of it in this TB, True if those are its last bytes)
Segment = Tuple[Packet, int, bool]

BUFFERED_TRAFFIC_MODES = ("poisson", "cbr")


@dataclass
class ByteBuffer:
    limit_bytes: Optional[int] = None
    # Rashed-Step 18.C-10-06-2026-start
    # Called after every accepted packet (NR-U's gNB uses it to wake up
    # and contend for the channel when data arrives).
    on_enqueue: Optional[Callable[[], None]] = field(default=None, repr=False)
    # Rashed-Step 18.C-10-06-2026-end
    _queue: Deque[Packet] = field(default_factory=deque, init=False, repr=False)
    # Bytes of the head packet already delivered in earlier TBs.
    _head_sent: int = field(default=0, init=False)
    _backlog: int = field(default=0, init=False)
    stats: dict = field(init=False)
    # Every packet that reached a final state (DELIVERED/DROPPED), in
    # the order it got there; the owner appends these to its packet_log.
    finished: List[Packet] = field(default_factory=list, init=False, repr=False)
    # Rashed-Step 18.E-10-06-2026-start
    _inflight: dict = field(default_factory=dict, init=False, repr=False)
    # Rashed-Step 18.E-10-06-2026-end

    def __post_init__(self):
        self.stats = {
            "enqueued_packets": 0,
            "enqueued_bytes": 0,
            "delivered_packets": 0,
            "delivered_bytes": 0,
            "dropped_overflow": 0,
            "dropped_tb_error": 0,
            "max_backlog_bytes": 0,
        }

    @property
    def backlog_bytes(self) -> int:
        """Bytes still waiting to be delivered."""
        return self._backlog

    def __len__(self) -> int:
        return len(self._queue)

    # Rashed-Step 18.F-10-06-2026-start
    # Same interface as ran/protocol/l2.py's L2Buffer, whose RLC AM bytes
    # waiting for retransmission count in the backlog but aren't sendable
    # until their STATUS report arrives.
    def has_ready(self, now: float) -> bool:
        return self._backlog > 0

    @property
    def new_bytes(self) -> int:
        return self._backlog
    # Rashed-Step 18.F-10-06-2026-end

    def head(self) -> Optional[Packet]:
        return self._queue[0] if self._queue else None

    def enqueue(self, packet: Packet) -> bool:
        size = packet.total_bytes()
        if self.limit_bytes is not None and self._backlog + size > self.limit_bytes:
            packet.status = "DROPPED"
            self.stats["dropped_overflow"] += 1
            self.finished.append(packet)
            return False
        self._queue.append(packet)
        self._backlog += size
        self.stats["enqueued_packets"] += 1
        self.stats["enqueued_bytes"] += size
        self.stats["max_backlog_bytes"] = max(self.stats["max_backlog_bytes"], self._backlog)
        # Rashed-Step 18.C-10-06-2026-start
        if self.on_enqueue is not None:
            self.on_enqueue()
        # Rashed-Step 18.C-10-06-2026-end
        return True

    def segments(self, capacity_bytes: int) -> List[Segment]:
        out: List[Segment] = []
        room = int(capacity_bytes)
        sent_before = self._head_sent
        for pkt in self._queue:
            if room <= 0:
                break
            left = pkt.total_bytes() - sent_before
            take = min(left, room)
            out.append((pkt, take, take == left))
            room -= take
            sent_before = 0
        return out

    def deliver(self, segs: List[Segment], now: float) -> int:
        """Apply a decoded TB; returns the bytes it delivered."""
        delivered = 0
        for pkt, nbytes, last in segs:
            assert self._queue and self._queue[0] is pkt, "segments must come from the head"
            delivered += nbytes
            self._backlog -= nbytes
            if last:
                self._queue.popleft()
                self._head_sent = 0
                pkt.status = "DELIVERED"
                pkt.delivered_at = now
                self.stats["delivered_packets"] += 1
                self.finished.append(pkt)
            else:
                self._head_sent += nbytes
        self.stats["delivered_bytes"] += delivered
        return delivered

    def lose(self, segs: List[Segment]) -> int:
        """Apply a block error: drop every packet with bytes in the TB.
        Returns how many packets were dropped."""
        for i, (pkt, _nbytes, _last) in enumerate(segs):
            assert self._queue and self._queue[0] is pkt, "segments must come from the head"
            unsent = pkt.total_bytes() - (self._head_sent if i == 0 else 0)
            self._queue.popleft()
            self._backlog -= unsent
            self._head_sent = 0
            pkt.status = "DROPPED"
            self.stats["dropped_tb_error"] += 1
            self.finished.append(pkt)
        return len(segs)

    # Rashed-Step 18.E-10-06-2026-start
    # HARQ path: a TB's bytes leave the queue when it is first sent and
    # are acknowledged or dropped later, possibly out of order (several
    # HARQ processes in flight). A packet split across TBs is DELIVERED
    # once all its bytes are acked, DROPPED if any TB carrying it is.
    def take(self, capacity_bytes: int, now: float = 0.0) -> List[Segment]:
        segs = self.segments(capacity_bytes)
        for pkt, nbytes, last in segs:
            st = self._inflight.setdefault(id(pkt), [pkt, 0, False, False])  # pkt, open segs, all taken, failed
            st[1] += 1
            self._backlog -= nbytes
            if last:
                self._queue.popleft()
                self._head_sent = 0
                st[2] = True
            else:
                self._head_sent += nbytes
        return segs

    def _settle(self, st, now: Optional[float]) -> None:
        pkt, open_segs, all_taken, failed = st
        if open_segs > 0 or not all_taken:
            return
        del self._inflight[id(pkt)]
        if failed:
            pkt.status = "DROPPED"
            self.stats["dropped_tb_error"] += 1
        else:
            pkt.status = "DELIVERED"
            pkt.delivered_at = now
            self.stats["delivered_packets"] += 1
        self.finished.append(pkt)

    def ack(self, segs: List[Segment], now: float) -> int:
        """A TB from take() decoded; returns its bytes."""
        delivered = 0
        for pkt, nbytes, _last in segs:
            st = self._inflight[id(pkt)]
            st[1] -= 1
            if not st[3]:
                delivered += nbytes
            self._settle(st, now)
        self.stats["delivered_bytes"] += delivered
        return delivered

    def drop(self, segs: List[Segment], now: Optional[float] = None) -> None:
        """A TB from take() is given up: its packets are lost, including
        any bytes of them still queued."""
        for pkt, _nbytes, _last in segs:
            st = self._inflight[id(pkt)]
            st[1] -= 1
            st[3] = True
            if not st[2] and self._queue and self._queue[0] is pkt:
                # The rest of a partly sent head packet is useless now.
                self._backlog -= pkt.total_bytes() - self._head_sent
                self._queue.popleft()
                self._head_sent = 0
                st[2] = True
            self._settle(st, None)
    # Rashed-Step 18.E-10-06-2026-end

    def drain_finished(self) -> List[Packet]:
        done, self.finished = self.finished, []
        return done


def validate_buffered_traffic(traffic: TrafficConfig) -> None:
    if traffic.mode not in BUFFERED_TRAFFIC_MODES:
        raise ValueError(
            f"buffered traffic mode must be one of {BUFFERED_TRAFFIC_MODES} (got {traffic.mode!r}); "
            "full buffer is the default (no traffic config)"
        )
    if not traffic.arrival_rate_pps > 0:
        raise ValueError(f"arrival rate must be > 0 packets/s (got {traffic.arrival_rate_pps})")
    if traffic.packet_size_bytes is not None and not traffic.packet_size_bytes > 0:
        raise ValueError(f"packet size must be > 0 bytes (got {traffic.packet_size_bytes})")


def arrival_process(env, buffer: ByteBuffer, traffic: TrafficConfig, make_packet: Callable[[], Packet],
                    rng_expovariate: Callable[[float], float]):
    """SimPy process: packets arrive (Poisson or constant rate) into
    `buffer` from t=0. Arrivals for a UE that isn't connected yet just
    wait in the buffer, the way a UPF buffers downlink for an idle UE."""
    rate_per_us = traffic.arrival_rate_pps / 1e6
    while True:
        if traffic.mode == "poisson":
            interval_us = rng_expovariate(rate_per_us)
        else:
            interval_us = 1.0 / rate_per_us
        yield env.timeout(interval_us)
        buffer.enqueue(make_packet())

def traffic_configs_from_cli(dl_mode: str, dl_rate_pps: Optional[float], ul_mode: str,
                             ul_rate_pps: Optional[float], packet_size_bytes: Optional[int],
                             buffer_limit_bytes: Optional[int], ue_uplink_enabled: bool
                             ) -> Tuple[Optional[TrafficConfig], Optional[TrafficConfig]]:
    """Map singleRunNR.py's traffic flags to (dl, ul) TrafficConfigs
    (None = full buffer); ValueError on misuse."""
    def one(mode, rate, name):
        if mode == "full_buffer":
            if rate is not None:
                raise ValueError(f"--{name}-arrival-rate-pps requires --{name}-traffic poisson or cbr.")
            return None
        tc = TrafficConfig(mode=mode, arrival_rate_pps=100.0 if rate is None else rate,
                           packet_size_bytes=packet_size_bytes)
        validate_buffered_traffic(tc)
        return tc
    dl = one(dl_mode, dl_rate_pps, "dl")
    ul = one(ul_mode, ul_rate_pps, "ul")
    if ul is not None and not ue_uplink_enabled:
        raise ValueError("--ul-traffic poisson/cbr requires --ue-uplink-enabled.")
    if dl is None and ul is None and (packet_size_bytes is not None or buffer_limit_bytes is not None):
        raise ValueError("--packet-size-bytes / --buffer-limit-bytes require --dl-traffic or --ul-traffic poisson/cbr.")
    if buffer_limit_bytes is not None and not buffer_limit_bytes > 0:
        raise ValueError(f"--buffer-limit-bytes must be > 0 (got {buffer_limit_bytes}).")
    return dl, ul


def summarize_buffers(buffers: List[ByteBuffer], packets: List[Packet], sim_time_s: float) -> dict:
    """Aggregate one direction's buffers. `packets` are that direction's
    finished packets (for latency/loss via compute_packet_stats)."""
    from common.packet import compute_packet_stats
    agg = {k: 0 for k in ("enqueued_packets", "enqueued_bytes", "delivered_packets", "delivered_bytes",
                          "dropped_overflow", "dropped_tb_error")}
    for b in buffers:
        for k in agg:
            agg[k] += b.stats[k]
    agg["buffers"] = len(buffers)
    agg["max_backlog_bytes"] = max((b.stats["max_backlog_bytes"] for b in buffers), default=0)
    agg["backlog_bytes"] = sum(b.backlog_bytes for b in buffers)
    agg["queued_packets"] = sum(len(b) for b in buffers)
    agg["offered_mbps"] = agg["enqueued_bytes"] * 8 / (sim_time_s * 1e6) if sim_time_s > 0 else 0.0
    agg["delivered_mbps"] = agg["delivered_bytes"] * 8 / (sim_time_s * 1e6) if sim_time_s > 0 else 0.0
    agg["packet_stats"] = compute_packet_stats(packets)
    return agg


def print_buffer_stats(title: str, label: str, stats: dict) -> None:
    ps = stats["packet_stats"]
    print(f"=== {title} ===")
    print(f"{label} buffers: {stats['buffers']}")
    print(f"{label} offered load (Mbps): {stats['offered_mbps']}")
    print(f"{label} delivered throughput (Mbps): {stats['delivered_mbps']}")
    print(f"{label} packets delivered: {stats['delivered_packets']}")
    print(f"{label} packets dropped (block error): {stats['dropped_tb_error']}")
    print(f"{label} packets dropped (buffer full): {stats['dropped_overflow']}")
    print(f"{label} packets still queued: {stats['queued_packets']} ({stats['backlog_bytes']} bytes)")
    print(f"{label} max buffer backlog (bytes): {stats['max_backlog_bytes']}")
    print(f"{label} packet avg latency (us): {ps['avg_latency_us']}")
    print(f"{label} packet p95 latency (us): {ps.get('p95_latency_us')}")
# Rashed-Step 18.B-10-06-2026-end
