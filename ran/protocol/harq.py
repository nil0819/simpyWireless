# Rashed-Step 18.E-10-06-2026-start
"""
HARQ (Step 18.E) - hybrid ARQ with chase combining, shared by licensed NR
and NR-U's "slots" COT model.

Each link (one UE, one direction) has a HarqEntity with up to
n_processes stop-and-wait processes. A transport block (TB) that fails
to decode is kept in its process: after rtt_us (feedback + processing)
it is retransmitted - ahead of new data - with the same size, MCS and
RBs. Each retransmission is decoded on the SUM of the linear SINRs of
all its attempts (chase combining: the receiver soft-combines identical
copies), so a TB just below its threshold usually gets through on the
second try. After max_tx attempts it is dropped.

The TB's bytes leave the buffer when it is first sent (ByteBuffer.take)
and are acknowledged or dropped later (ByteBuffer.ack / .drop). While
all n_processes are waiting, the link sends no new data.
"""
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional

from common.error_model import decode_ok


@dataclass(frozen=True)
class HarqConfig:
    # Total transmissions per TB (1 new + 3 retransmissions, the usual
    # NR maximum).
    max_tx: int = 4
    n_processes: int = 16  # NR's maximum per carrier and direction
    # Retransmission no earlier than this many slots after the attempt
    # ended (HARQ-ACK timing + processing).
    rtt_slots: int = 4

    def __post_init__(self):
        if self.max_tx < 1:
            raise ValueError(f"HARQ max_tx must be >= 1 (got {self.max_tx})")
        if self.n_processes < 1:
            raise ValueError(f"HARQ n_processes must be >= 1 (got {self.n_processes})")
        if self.rtt_slots < 0:
            raise ValueError(f"HARQ rtt_slots must be >= 0 (got {self.rtt_slots})")


@dataclass
class HarqTb:
    segments: list          # ByteBuffer segments carried by this TB
    mcs: int
    rbs: int
    tb_bytes: int
    tx_count: int = 0
    sinr_lin_sum: float = 0.0
    ready_at: float = 0.0   # earliest retransmission time

    @property
    def payload_bytes(self) -> int:
        return sum(n for _p, n, _l in self.segments)


@dataclass
class HarqEntity:
    config: HarqConfig
    _waiting: Deque[HarqTb] = field(default_factory=deque, init=False, repr=False)
    stats: dict = field(init=False)

    def __post_init__(self):
        self.stats = {"new_tbs": 0, "retx": 0, "ok_first": 0, "ok_retx": 0, "dropped": 0}

    def pending(self) -> int:
        return len(self._waiting)

    def can_send_new(self) -> bool:
        return len(self._waiting) < self.config.n_processes

    def next_retx(self, now: float) -> Optional[HarqTb]:
        """The oldest TB whose retransmission is due, removed from the
        queue (put it back with failed() if it fails again)."""
        for i, tb in enumerate(self._waiting):
            if tb.ready_at <= now:
                del self._waiting[i]
                return tb
        return None

    def peek_retx(self, now: float) -> Optional[HarqTb]:
        return next((tb for tb in self._waiting if tb.ready_at <= now), None)

    def attempt(self, tb: HarqTb, sinr_db: float, required_db: float, error_model,
                outcome: Optional[bool] = None) -> bool:
        """Decode one (re)transmission of `tb` with chase combining.
        `outcome` = already decoded elsewhere (a first attempt), just record it."""
        if tb.tx_count == 0:
            self.stats["new_tbs"] += 1
        else:
            self.stats["retx"] += 1
        tb.tx_count += 1
        tb.sinr_lin_sum += 10.0 ** (sinr_db / 10.0)
        combined_db = 10.0 * math.log10(tb.sinr_lin_sum) if tb.sinr_lin_sum > 0 else -math.inf
        ok = decode_ok(error_model, combined_db, required_db) if outcome is None else outcome
        if ok:
            self.stats["ok_first" if tb.tx_count == 1 else "ok_retx"] += 1
        return ok

    def failed(self, tb: HarqTb, now: float, rtt_us: float) -> bool:
        """After a failed attempt: keep it for retransmission (True) or,
        past max_tx, give up (False - the caller drops its packets)."""
        if tb.tx_count >= self.config.max_tx:
            self.stats["dropped"] += 1
            return False
        tb.ready_at = now + rtt_us
        self._waiting.append(tb)
        return True

    def drain(self) -> List[HarqTb]:
        """TBs still waiting at the end of a run."""
        out, self._waiting = list(self._waiting), deque()
        return out


def sum_harq_stats(entities) -> dict:
    total = {"new_tbs": 0, "retx": 0, "ok_first": 0, "ok_retx": 0, "dropped": 0, "pending": 0}
    for e in entities:
        for k, v in e.stats.items():
            total[k] += v
        total["pending"] += e.pending()
    return total


def print_harq_stats(title: str, label: str, s: dict) -> None:
    print(f"=== {title} ===")
    print(f"{label} HARQ new TBs: {s['new_tbs']}")
    print(f"{label} HARQ retransmissions: {s['retx']}")
    print(f"{label} HARQ decoded on 1st try: {s['ok_first']}")
    print(f"{label} HARQ recovered by retransmission: {s['ok_retx']}")
    print(f"{label} HARQ dropped after max attempts: {s['dropped']}")
    print(f"{label} HARQ still pending at end: {s['pending']}")
    done = s["ok_first"] + s["ok_retx"] + s["dropped"]
    print(f"{label} HARQ residual TB loss: {(s['dropped'] / done) if done else 0.0}")


def harq_config_from_cli(enabled: bool, max_tx: Optional[int], rtt_slots: Optional[int]) -> Optional[HarqConfig]:
    if not enabled:
        if max_tx is not None or rtt_slots is not None:
            raise ValueError("--harq-max-tx / --harq-rtt-slots require --harq.")
        return None
    kw = {}
    if max_tx is not None:
        kw["max_tx"] = max_tx
    if rtt_slots is not None:
        kw["rtt_slots"] = rtt_slots
    return HarqConfig(**kw)
# Rashed-Step 18.E-10-06-2026-end
