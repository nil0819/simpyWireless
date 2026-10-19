# Rashed-Step 24.B-10-19-2026-start
"""
Compact packet log (Step 24.B, --compact-packet-log).

Every node keeps its finished packets in packet_log for the statistics.
On long runs those objects dominate memory (DTMC scenario, w = 1: ~0.35 MB
per simulated second). CompactPacketLog keeps the most recent entries as
ordinary Packet objects - so code that still changes a packet shortly after
logging it keeps working - and moves older ones into column arrays: strings
interned (packet / file ids split into prefix + number), numbers in typed
arrays. Iterating rebuilds a Packet per entry, so every consumer (packet
statistics, QoS, FTP, cell report, CSV export) reads the same values as
from a list. append / extend / iter / len like a list.

Lossy only where nothing reads it: a float field that is NaN comes back as
None (None is stored as NaN).
"""
import math
import re
from array import array
from dataclasses import fields

from common.packet import Packet

_ID = re.compile(r"^(.*)-(\d+)$")
_NAN = float("nan")

# Packet field -> storage kind. Checked against Packet at import, so a new
# Packet field fails loudly here instead of being silently dropped.
_SPEC = {
    "packet_id": "id", "source": "str", "destination": "str", "payload_bytes": "int", "header_bytes": "int",
    "packet_type": "code", "created_at": "float", "retry_count": "int", "status": "code", "delivered_at": "float",
    "traffic_class": "code", "measured_sinr_db": "float",
    # Rarely set (FTP Model 3, licensed NR, A-MPDU): kept only for the
    # packets where one differs from its default.
    "file_id": "sparse", "file_packets": "sparse", "file_bytes": "sparse", "file_arrival": "sparse",
    "tb_bits": "sparse", "_dup": "sparse",
}
_SPARSE = [n for n, k in _SPEC.items() if k == "sparse"]
_SPARSE_DEFAULT = {"file_id": None, "file_packets": 0, "file_bytes": 0, "file_arrival": None, "tb_bits": None,
                   "_dup": False}
_FIELDS = [f.name for f in fields(Packet)]
assert set(_FIELDS) == set(_SPEC), f"CompactPacketLog: Packet fields changed: {set(_FIELDS) ^ set(_SPEC)}"


class CompactPacketLog:
    LIVE = 10_000           # recent entries kept as Packet objects

    def __init__(self, live: int = None):
        self._keep = self.LIVE if live is None else max(0, live)
        self._live = []
        self._n = 0
        self._strs = [None]         # code 0 = None
        self._codes = {None: 0}
        self._small = [None]        # separate table for the "code" fields (status, class, type): stays tiny
        self._small_codes = {None: 0}
        self._cols = {}
        self._sparse = {}           # entry index -> tuple of the _SPARSE values (only when not all default)
        for name in _FIELDS:
            kind = _SPEC[name]
            if kind == "id":
                self._cols[name] = (array("l"), array("q"), array("b"))   # prefix code, number (-1: whole string), digits
            elif kind == "str":
                self._cols[name] = array("l")
            elif kind == "code":
                self._cols[name] = array("H")                            # few distinct values
            elif kind == "int":
                self._cols[name] = array("l")
            elif kind == "float":
                self._cols[name] = array("d")

    # -- list interface --------------------------------------------------
    def append(self, p: Packet) -> None:
        self._live.append(p)
        if len(self._live) > 2 * self._keep:
            cut = len(self._live) - self._keep
            for q in self._live[:cut]:
                self._store(q)
            del self._live[:cut]

    def extend(self, ps) -> None:
        for p in ps:
            self.append(p)

    def __len__(self) -> int:
        return self._n + len(self._live)

    def __iter__(self):
        for i in range(self._n):
            yield self._load(i)
        yield from list(self._live)

    # -- storage ---------------------------------------------------------
    def _code(self, s) -> int:
        c = self._codes.get(s)
        if c is None:
            c = len(self._strs)
            self._codes[s] = c
            self._strs.append(s)
        return c

    def _store(self, p: Packet) -> None:
        extra = tuple(getattr(p, n) for n in _SPARSE)
        if any(v != _SPARSE_DEFAULT[n] for n, v in zip(_SPARSE, extra)):
            self._sparse[self._n] = extra
        for name in _FIELDS:
            kind = _SPEC[name]
            if kind == "sparse":
                continue
            v = getattr(p, name)
            col = self._cols[name]
            if kind == "id":
                m = _ID.match(v) if isinstance(v, str) else None
                if m:
                    col[0].append(self._code(m.group(1)))
                    col[1].append(int(m.group(2)))
                    col[2].append(len(m.group(2)))
                else:
                    col[0].append(self._code(v))
                    col[1].append(-1)
                    col[2].append(0)
            elif kind == "str":
                col.append(self._code(v))
            elif kind == "code":
                c = self._small_codes.get(v)
                if c is None:
                    c = self._small_codes[v] = len(self._small)
                    self._small.append(v)
                col.append(c)
            elif kind == "int":
                col.append(int(v))
            else:
                col.append(_NAN if v is None else float(v))
        self._n += 1

    def _load(self, i: int) -> Packet:
        extra = self._sparse.get(i)
        kw = dict(zip(_SPARSE, extra)) if extra is not None else dict(_SPARSE_DEFAULT)
        for name in _FIELDS:
            kind = _SPEC[name]
            if kind == "sparse":
                continue
            col = self._cols[name]
            if kind == "id":
                prefix, num = self._strs[col[0][i]], col[1][i]
                kw[name] = prefix if num < 0 else f"{prefix}-{num:0{col[2][i]}d}"
            elif kind == "str":
                kw[name] = self._strs[col[i]]
            elif kind == "code":
                kw[name] = self._small[col[i]]
            elif kind == "int":
                kw[name] = col[i]
            else:
                v = col[i]
                kw[name] = None if math.isnan(v) else v
        return Packet(**kw)


class PacketView:
    """Iterate several packet logs as one (re-iterable, nothing copied) -
    what the end-of-run statistics read, so a compact log is never turned
    back into a full list of Packet objects."""

    def __init__(self, logs):
        self._logs = list(logs)

    def __iter__(self):
        for log_ in self._logs:
            yield from log_


_COMPACT = False


def set_compact_packet_log(on: bool) -> None:
    """Make new_packet_log() hand out CompactPacketLogs (one run's setting;
    run_simulation() sets it at the start of every run)."""
    global _COMPACT
    _COMPACT = bool(on)


def new_packet_log():
    """A node's packet_log: a plain list (default) or a CompactPacketLog."""
    return CompactPacketLog() if _COMPACT else []
# Rashed-Step 24.B-10-19-2026-end
