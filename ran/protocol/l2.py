# Rashed-Step 18.F-10-06-2026-start
"""
Layer 2 above HARQ (Step 18.F): PDCP and RLC on top of the per-UE byte
buffers (ran/protocol/buffer.py), for licensed NR (buffered traffic) and
NR-U "slots".

L2Buffer is a ByteBuffer that adds:
  - PDCP (TS 38.323): a sequence number and a 2-byte (12-bit SN) or
    3-byte (18-bit SN) header on every packet; in-order delivery - a
    packet reaches the upper layer only after every earlier one has
    (been delivered or given up), so a gap shows up as head-of-line
    delay (the reordering wait is counted).
  - RLC (TS 38.322) segmentation overhead on every piece put in a
    transport block: UM 1 byte for a whole SDU, 2 bytes (12-bit SN) for
    a segment; AM 2 bytes (12-bit SN) or 3 (18-bit); +2 bytes segment
    offset for a segment that isn't the SDU's first; plus the MAC
    subheader (TS 38.321): 2 bytes for a PDU up to 255 bytes, else 3.
  - RLC AM ARQ: bytes of a transport block that is finally lost (HARQ
    gave up) are queued again after am_status_delay_us (the receiver
    noticing the gap and sending a STATUS report) and go out ahead of
    new data; a packet is dropped after am_max_retx such retransmission
    rounds. UM has no ARQ: a lost piece drops its packet.
It always uses the take/ack/drop path (the owners give a link a one-
attempt HARQ entity when HARQ itself is off).

Not modeled: ROHC, ciphering/integrity (MAC-I), SDAP header, polling
details, PDCP duplication, PDCP t-Reordering for UM losses (a known
loss releases the packets behind it at once).
"""
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional

from ran.protocol.buffer import ByteBuffer, Segment

RLC_MODES = ("um", "am")


@dataclass(frozen=True)
class L2Config:
    rlc_mode: str = "um"
    sn_bits: int = 12            # PDCP SN (and RLC AM SN) length: 12 or 18
    am_max_retx: int = 4         # RLC maxRetxThreshold
    am_status_delay_us: float = 10_000.0

    def __post_init__(self):
        if self.rlc_mode not in RLC_MODES:
            raise ValueError(f"RLC mode must be one of {RLC_MODES} (got {self.rlc_mode!r})")
        if self.sn_bits not in (12, 18):
            raise ValueError(f"SN length must be 12 or 18 bits (got {self.sn_bits})")
        if self.am_max_retx < 0:
            raise ValueError(f"RLC AM max retransmissions must be >= 0 (got {self.am_max_retx})")
        if self.am_status_delay_us < 0:
            raise ValueError(f"RLC AM status delay must be >= 0 (got {self.am_status_delay_us})")

    @property
    def pdcp_header_bytes(self) -> int:
        return 2 if self.sn_bits == 12 else 3

    def rlc_header_bytes(self, whole_sdu: bool, first_segment: bool) -> int:
        if self.rlc_mode == "um":
            if whole_sdu:
                return 1
            base = 2  # 12-bit UM SN
        else:
            base = 2 if self.sn_bits == 12 else 3
            if whole_sdu:
                return base
        return base + (0 if first_segment else 2)

    @staticmethod
    def mac_subheader_bytes(pdu_bytes: int) -> int:
        return 2 if pdu_bytes <= 255 else 3


class _Sdu:
    """Per-packet state while any of it is in flight or queued again."""
    __slots__ = ("pkt", "open", "all_taken", "failed", "retx_pending", "retx_rounds")

    def __init__(self, pkt):
        self.pkt = pkt
        self.open = 0
        self.all_taken = False
        self.failed = False
        self.retx_pending = 0
        self.retx_rounds = 0


@dataclass
class L2Buffer(ByteBuffer):
    l2: L2Config = field(default_factory=L2Config)
    _retx: Deque[list] = field(default_factory=deque, init=False, repr=False)  # [pkt, bytes, ready_at]
    _retx_bytes: int = field(default=0, init=False)
    _sdus: dict = field(default_factory=dict, init=False, repr=False)
    _sn: dict = field(default_factory=dict, init=False, repr=False)
    _next_sn: int = field(default=0, init=False)
    _next_release: int = field(default=0, init=False)
    _done: dict = field(default_factory=dict, init=False, repr=False)  # sn -> (pkt, failed, done_at)

    def __post_init__(self):
        super().__post_init__()
        self.stats.update({"l2_overhead_bytes": 0, "am_retx_segments": 0, "am_retx_bytes": 0,
                           "dropped_max_retx": 0, "reorder_wait_us_sum": 0.0, "reordered_packets": 0})

    # ---------------- queue state ----------------
    def has_ready(self, now: float) -> bool:
        return bool(self._queue) or (bool(self._retx) and self._retx[0][2] <= now)

    @property
    def new_bytes(self) -> int:
        return self._backlog - self._retx_bytes

    def enqueue(self, packet) -> bool:
        packet.header_bytes += self.l2.pdcp_header_bytes
        ok = super().enqueue(packet)
        if ok:
            self._sn[id(packet)] = self._next_sn
            self._next_sn += 1
        return ok

    # ---------------- building a transport block ----------------
    def _piece(self, room: int, left: int, first: bool):
        """Data bytes and L2 overhead of one piece fitting in `room`."""
        if first:
            h = self.l2.rlc_header_bytes(True, True)
            m = self.l2.mac_subheader_bytes(left + h)
            if left + h + m <= room:
                return left, h + m
        h = self.l2.rlc_header_bytes(False, first)
        m = 3 if room - h - 2 > 255 else 2
        t = min(left, room - h - m)
        if t <= 0:
            return 0, 0
        return t, h + self.l2.mac_subheader_bytes(t + h)

    def take(self, capacity_bytes: int, now: float = 0.0) -> List[Segment]:
        segs: List[Segment] = []
        room = int(capacity_bytes)
        overhead = 0
        # RLC AM retransmissions first.
        while room > 0 and self._retx and self._retx[0][2] <= now:
            entry = self._retx[0]
            pkt, n = entry[0], entry[1]
            t, oh = self._piece(room, n, first=False)
            if t <= 0:
                break
            sdu = self._sdus[id(pkt)]
            sdu.open += 1
            sdu.retx_pending -= t
            self._retx_bytes -= t
            self._backlog -= t
            room -= t + oh
            overhead += oh
            segs.append((pkt, t, False))
            self.stats["am_retx_segments"] += 1
            self.stats["am_retx_bytes"] += t
            if t == n:
                self._retx.popleft()
            else:
                entry[1] -= t
        # Then new data, head first.
        while room > 0 and self._queue:
            pkt = self._queue[0]
            left = pkt.total_bytes() - self._head_sent
            t, oh = self._piece(room, left, first=self._head_sent == 0)
            if t <= 0:
                break
            sdu = self._sdus.setdefault(id(pkt), _Sdu(pkt))
            sdu.open += 1
            self._backlog -= t
            room -= t + oh
            overhead += oh
            last = t == left
            segs.append((pkt, t, last))
            if last:
                self._queue.popleft()
                self._head_sent = 0
                sdu.all_taken = True
            else:
                self._head_sent += t
        self.stats["l2_overhead_bytes"] += overhead
        return segs

    # ---------------- outcomes ----------------
    def ack(self, segs: List[Segment], now: float) -> int:
        delivered = 0
        for pkt, nbytes, _last in segs:
            sdu = self._sdus[id(pkt)]
            sdu.open -= 1
            if not sdu.failed:
                delivered += nbytes
            self._settle(sdu, now)
        self.stats["delivered_bytes"] += delivered
        return delivered

    def drop(self, segs: List[Segment], now: Optional[float] = None) -> None:
        now = 0.0 if now is None else now
        counted = set()
        for pkt, nbytes, _last in segs:
            sdu = self._sdus[id(pkt)]
            sdu.open -= 1
            if not sdu.failed and self.l2.rlc_mode == "am":
                if id(pkt) not in counted:
                    sdu.retx_rounds += 1
                    counted.add(id(pkt))
                if sdu.retx_rounds <= self.l2.am_max_retx:
                    self._retx.append([pkt, nbytes, now + self.l2.am_status_delay_us])
                    sdu.retx_pending += nbytes
                    self._retx_bytes += nbytes
                    self._backlog += nbytes
                    self._settle(sdu, now)
                    continue
                if id(pkt) in counted and sdu.retx_rounds == self.l2.am_max_retx + 1:
                    self.stats["dropped_max_retx"] += 1
            if not sdu.failed:
                self._fail(sdu)
            self._settle(sdu, now)

    def _fail(self, sdu: _Sdu) -> None:
        sdu.failed = True
        pkt = sdu.pkt
        if not sdu.all_taken and self._queue and self._queue[0] is pkt:
            self._backlog -= pkt.total_bytes() - self._head_sent
            self._queue.popleft()
            self._head_sent = 0
            sdu.all_taken = True
        if sdu.retx_pending:
            keep = deque()
            for e in self._retx:
                if e[0] is pkt:
                    self._backlog -= e[1]
                    self._retx_bytes -= e[1]
                else:
                    keep.append(e)
            self._retx = keep
            sdu.retx_pending = 0

    def _settle(self, sdu: _Sdu, now: float) -> None:
        if sdu.open > 0 or not sdu.all_taken or sdu.retx_pending > 0:
            return
        pkt = sdu.pkt
        del self._sdus[id(pkt)]
        self._done[self._sn.pop(id(pkt))] = (pkt, sdu.failed, now)
        # PDCP in-order delivery.
        while self._next_release in self._done:
            p, failed, done_at = self._done.pop(self._next_release)
            self._next_release += 1
            if failed:
                p.status = "DROPPED"
                self.stats["dropped_tb_error"] += 1
            else:
                p.status = "DELIVERED"
                p.delivered_at = now
                self.stats["delivered_packets"] += 1
                if now > done_at:
                    self.stats["reorder_wait_us_sum"] += now - done_at
                    self.stats["reordered_packets"] += 1
            self.finished.append(p)


def make_buffer(limit_bytes, on_enqueue=None, l2: Optional[L2Config] = None) -> ByteBuffer:
    if l2 is None:
        return ByteBuffer(limit_bytes, on_enqueue=on_enqueue)
    return L2Buffer(limit_bytes, on_enqueue=on_enqueue, l2=l2)


def l2_config_from_cli(rlc_mode: str, sn_bits: Optional[int], am_max_retx: Optional[int],
                       am_status_delay_ms: Optional[float]) -> Optional[L2Config]:
    if rlc_mode == "none":
        if any(v is not None for v in (sn_bits, am_max_retx, am_status_delay_ms)):
            raise ValueError("--pdcp-sn-bits / --rlc-am-max-retx / --rlc-am-status-delay-ms require --rlc-mode um or am.")
        return None
    if rlc_mode != "am" and (am_max_retx is not None or am_status_delay_ms is not None):
        raise ValueError("--rlc-am-max-retx / --rlc-am-status-delay-ms require --rlc-mode am.")
    kw = {"rlc_mode": rlc_mode}
    if sn_bits is not None:
        kw["sn_bits"] = sn_bits
    if am_max_retx is not None:
        kw["am_max_retx"] = am_max_retx
    if am_status_delay_ms is not None:
        kw["am_status_delay_us"] = am_status_delay_ms * 1000.0
    return L2Config(**kw)


def sum_l2_stats(buffers) -> dict:
    keys = ("enqueued_bytes", "delivered_bytes", "l2_overhead_bytes", "am_retx_segments", "am_retx_bytes",
            "dropped_max_retx", "reorder_wait_us_sum", "reordered_packets", "delivered_packets")
    return {k: sum(b.stats.get(k, 0) for b in buffers) for k in keys}


def print_l2_stats(title: str, label: str, l2: L2Config, s: dict) -> None:
    print(f"=== {title} ===")
    print(f"{label} RLC mode: {l2.rlc_mode.upper()} (SN {l2.sn_bits} bit, PDCP header {l2.pdcp_header_bytes} B)")
    sent = s["delivered_bytes"] + s["l2_overhead_bytes"]
    print(f"{label} RLC/MAC header bytes: {s['l2_overhead_bytes']} "
          f"({(s['l2_overhead_bytes'] / sent) if sent else 0.0} of bytes sent)")
    if l2.rlc_mode == "am":
        print(f"{label} RLC AM retransmitted segments: {s['am_retx_segments']} ({s['am_retx_bytes']} bytes)")
        print(f"{label} RLC AM packets dropped after max retransmissions: {s['dropped_max_retx']}")
    print(f"{label} PDCP packets held for in-order delivery: {s['reordered_packets']}")
    held = s["reordered_packets"]
    print(f"{label} PDCP mean reordering wait (us): {(s['reorder_wait_us_sum'] / held) if held else 0.0}")
# Rashed-Step 18.F-10-06-2026-end
