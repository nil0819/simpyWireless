# Rashed-Step 19.C-10-07-2026-start
"""
Data radio bearers per QoS flow (Step 19.C): QosBuffer keeps one buffer
per 5QI - one DRB per QoS flow, each with its own PDCP/RLC when L2 is on
- behind the same interface as a single ByteBuffer, so the schedulers,
HARQ and the INACTIVE hooks use it unchanged.

Filling a transport block follows MAC logical channel prioritization
(TS 38.321 5.4.3.1) in its strict-priority form: the DRB with the best
(lowest) 5QI priority level is served first, then the next, until the
block is full. No prioritized bit rate / bucket sizes.

The drop-tail limit applies per DRB.
"""
from typing import Callable, Dict, List, Optional

from common.qos import FIVE_QI_TABLE, DEFAULT_5QI, five_qi_for

_STAT_MAX_KEYS = ("max_backlog_bytes",)


class QosBuffer:
    def __init__(self, limit_bytes: Optional[int] = None, on_enqueue: Optional[Callable[[], None]] = None,
                 make_sub=None):
        self.limit_bytes = limit_bytes
        self.on_enqueue = on_enqueue
        self._make_sub = make_sub
        self.drbs: Dict[int, object] = {}
        self._order: List[int] = []
        self._of: Dict[int, object] = {}

    # ---------------- bearers ----------------
    def _sub(self, q: int):
        if q not in self.drbs:
            self.drbs[q] = self._make_sub(self.limit_bytes)
            prio = lambda v: FIVE_QI_TABLE.get(v, FIVE_QI_TABLE[DEFAULT_5QI]).priority_level
            self._order = sorted(self.drbs, key=prio)
        return self.drbs[q]

    def _subs(self):
        return [self.drbs[q] for q in self._order]

    # ---------------- queue state ----------------
    def enqueue(self, packet) -> bool:
        sub = self._sub(five_qi_for(packet.traffic_class))
        ok = sub.enqueue(packet)
        if ok:
            self._of[id(packet)] = sub
            if self.on_enqueue is not None:
                self.on_enqueue()
        return ok

    @property
    def backlog_bytes(self) -> int:
        return sum(b.backlog_bytes for b in self.drbs.values())

    @property
    def new_bytes(self) -> int:
        return sum(b.new_bytes for b in self.drbs.values())

    def has_ready(self, now: float) -> bool:
        return any(b.has_ready(now) for b in self.drbs.values())

    def __len__(self) -> int:
        return sum(len(b) for b in self.drbs.values())

    def queued_packets(self):
        return [pk for b in self._subs() for pk in b.queued_packets()]

    def head(self):
        for b in self._subs():
            h = b.head()
            if h is not None:
                return h
        return None

    @property
    def stats(self) -> dict:
        out: dict = {}
        for b in self.drbs.values():
            for k, v in b.stats.items():
                out[k] = max(out.get(k, 0), v) if k in _STAT_MAX_KEYS else out.get(k, 0) + v
        if not out:
            out = {"enqueued_packets": 0, "enqueued_bytes": 0, "delivered_packets": 0, "delivered_bytes": 0,
                   "dropped_overflow": 0, "dropped_tb_error": 0, "max_backlog_bytes": 0}
        return out

    # ---------------- transport blocks (LCP: strict priority) ----------------
    def segments(self, capacity_bytes: int):
        out, room = [], int(capacity_bytes)
        for b in self._subs():
            if room <= 0:
                break
            segs = b.segments(room)
            out += segs
            room -= sum(n for _p, n, _l in segs)
        return out

    def take(self, capacity_bytes: int, now: float = 0.0):
        out, room = [], int(capacity_bytes)
        for b in self._subs():
            if room <= 0:
                break
            oh0 = b.stats.get("l2_overhead_bytes", 0)
            segs = b.take(room, now)
            out += segs
            room -= sum(n for _p, n, _l in segs) + (b.stats.get("l2_overhead_bytes", 0) - oh0)
        return out

    def _split(self, segs):
        groups: Dict[int, list] = {}
        subs: Dict[int, object] = {}
        for seg in segs:
            sub = self._of[id(seg[0])]
            groups.setdefault(id(sub), []).append(seg)
            subs[id(sub)] = sub
        return [(subs[k], g) for k, g in groups.items()]

    def deliver(self, segs, now: float) -> int:
        return sum(sub.deliver(g, now) for sub, g in self._split(segs))

    def lose(self, segs) -> int:
        return sum(sub.lose(g) for sub, g in self._split(segs))

    def ack(self, segs, now: float) -> int:
        return sum(sub.ack(g, now) for sub, g in self._split(segs))

    def drop(self, segs, now: Optional[float] = None) -> None:
        for sub, g in self._split(segs):
            sub.drop(g, now)

    def drain_finished(self):
        out = []
        for b in self.drbs.values():
            for p in b.drain_finished():
                self._of.pop(id(p), None)
                out.append(p)
        return out
# Rashed-Step 19.C-10-07-2026-end
