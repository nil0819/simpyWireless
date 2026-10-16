# Rashed-Step 22.D-10-15-2026-start
"""
Multi-cell / dense deployment layouts (Step 22.D, Phase D realism).

A Layout lists cell sites (position + operator) and each site's users;
singleRun.py's --layout turns it into AP / gNB / STA / UE positions. One
floor (positions stay 2D).

  tr38889-indoor   3GPP TR 38.889 8.1.1 / A.1.1 indoor sub-7 GHz: a
                   120 m x 80 m room, two operators x 3 cells, a = c = 20 m,
                   b = d = 40 m - read as a 3 x 2 grid: operator A at
                   (20, 20), (60, 20), (100, 20), operator B at y = 60 (the
                   spec's figure isn't in its text; this is the only grid
                   the four distances fit). 5 users per cell, dropped
                   uniformly in the room and kept with the nearest cell of
                   their operator (A.1.1: "5 UEs associated with each gNB").
  tgax-residential IEEE 802.11ax SS1 (11-14/0980, one floor): rows x cols
                   apartments of 10 m x 10 m (default 2 x 10), one AP at a
                   random point in each, its STAs random in the same
                   apartment (default 2).
  tgax-enterprise  IEEE 802.11ax SS2 (one floor): rows x cols offices of
                   20 m x 20 m (default 2 x 4), 4 APs per office on a 2 x 2
                   grid (5 / 15 m), STAs random in their AP's 10 m x 10 m
                   quarter (default 4 per AP; SS2 itself has far more).
  hex              hexagonal grid: 1 (7 sites) or 2 (19) rings at an
                   inter-site distance, one omni cell per site, users
                   uniform in each site's hexagon.

assign_channels(): a reuse pattern over N 20 MHz channels (36/40/44/48 at
5.18/5.20/5.22/5.24 GHz): greedy, each site takes the channel whose
nearest co-channel site (of the same technology) is farthest away.
"""
import math
import random
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

Pos = Tuple[float, float]

LAYOUTS = ("tr38889-indoor", "tgax-residential", "tgax-enterprise", "hex")
CHANNELS_GHZ = (5.18, 5.20, 5.22, 5.24, 5.26, 5.28, 5.30, 5.32)  # 20 MHz channels 36..64


@dataclass
class Site:
    pos: Pos
    operator: str            # "A" / "B" (tr38889-indoor), else "A"
    users: List[Pos] = field(default_factory=list)


@dataclass
class Layout:
    name: str
    area_w: float
    area_h: float
    sites: List[Site]
    room_size_m: Optional[float] = None   # TGax wall grid that matches the layout

    def operator_sites(self, op: str) -> List[Site]:
        return [s for s in self.sites if s.operator == op]


def _nearest(p: Pos, sites: List[Site]) -> Site:
    return min(sites, key=lambda s: (s.pos[0] - p[0]) ** 2 + (s.pos[1] - p[1]) ** 2)


def _drop_associated(rng: random.Random, sites: List[Site], n: int, area_w: float, area_h: float,
                     inside=None, serving_ok=None) -> None:
    """n users per site, uniform over the area (optionally `inside(p)`),
    each kept by its nearest site until every site has n. serving_ok(site,
    p) (Step 22.E): drop the position again if its serving power is too low
    (TR 38.889 A.1.1: below -82 dBm)."""
    need = {id(s): n for s in sites}
    for _ in range(200000):
        if not any(need.values()):
            return
        p = (rng.uniform(0.0, area_w), rng.uniform(0.0, area_h))
        if inside is not None and not inside(p):
            continue
        s = _nearest(p, sites)
        if serving_ok is not None and not serving_ok(s, p):  # Rashed-Step 22.E-10-15-2026
            continue
        if need[id(s)] > 0:
            s.users.append(p)
            need[id(s)] -= 1
    raise RuntimeError("could not drop users for every site")


def tr38889_indoor(rng: random.Random, users_per_cell: int = 5, serving_ok=None) -> Layout:
    a, b, c, d = 20.0, 40.0, 20.0, 40.0
    xs = [a, a + b, a + 2 * b]
    sites = [Site((x, c), "A") for x in xs] + [Site((x, c + d), "B") for x in xs]
    for op in ("A", "B"):
        _drop_associated(rng, [s for s in sites if s.operator == op], users_per_cell, 120.0, 80.0,
                         serving_ok=serving_ok)
    return Layout("tr38889-indoor", 120.0, 80.0, sites)


def tgax_residential(rng: random.Random, rows: int = 2, cols: int = 10, users_per_cell: int = 2,
                     room: float = 10.0) -> Layout:
    sites = []
    for r in range(rows):
        for c in range(cols):
            x0, y0 = c * room, r * room
            ap = (x0 + rng.uniform(0.0, room), y0 + rng.uniform(0.0, room))
            users = [(x0 + rng.uniform(0.0, room), y0 + rng.uniform(0.0, room)) for _ in range(users_per_cell)]
            sites.append(Site(ap, "A", users))
    return Layout("tgax-residential", cols * room, rows * room, sites, room_size_m=room)


def tgax_enterprise(rng: random.Random, rows: int = 2, cols: int = 4, users_per_cell: int = 4,
                    office: float = 20.0) -> Layout:
    sites = []
    q = office / 2.0
    for r in range(rows):
        for c in range(cols):
            for qy in range(2):
                for qx in range(2):
                    x0, y0 = c * office + qx * q, r * office + qy * q
                    users = [(x0 + rng.uniform(0.0, q), y0 + rng.uniform(0.0, q)) for _ in range(users_per_cell)]
                    sites.append(Site((x0 + q / 2.0, y0 + q / 2.0), "A", users))
    return Layout("tgax-enterprise", cols * office, rows * office, sites, room_size_m=office)


def hex_sites(rings: int, isd: float) -> List[Pos]:
    """Site centres of a hexagonal grid (axial coordinates), rings >= 0."""
    out = []
    for q in range(-rings, rings + 1):
        for r in range(max(-rings, -q - rings), min(rings, -q + rings) + 1):
            out.append((isd * (q + r / 2.0), isd * r * math.sqrt(3) / 2.0))
    return out


def hexagon(rng: random.Random, rings: int = 1, isd: float = 200.0, users_per_cell: int = 5,
            serving_ok=None) -> Layout:
    if rings not in (1, 2):
        raise ValueError("hex layout: rings must be 1 or 2")
    pts = hex_sites(rings, isd)
    margin = isd / math.sqrt(3)                       # hexagon circumradius
    min_x, min_y = min(p[0] for p in pts) - margin, min(p[1] for p in pts) - margin
    sites = [Site((p[0] - min_x, p[1] - min_y), "A") for p in pts]
    w = max(p[0] for p in pts) - min_x + margin
    h = max(p[1] for p in pts) - min_y + margin
    # Inside the network: closer to a site than half the ISD x 2/sqrt(3)
    # (its hexagon) - the nearest-site rule then keeps it in that hexagon.
    inside = lambda p: min(math.hypot(p[0] - s.pos[0], p[1] - s.pos[1]) for s in sites) <= margin
    _drop_associated(rng, sites, users_per_cell, w, h, inside, serving_ok)
    return Layout("hex", w, h, sites)


def build_layout(name: str, seed: int, users_per_cell: Optional[int] = None, rows: Optional[int] = None,
                 cols: Optional[int] = None, hex_rings: int = 1, hex_isd_m: float = 200.0,
                 serving_ok=None) -> Layout:
    """The layout for one run; its own RNG (seed-derived), so the rest of
    the run's random draws don't move. serving_ok(site, p): optional
    coverage rule for tr38889-indoor / hex user drops (Step 22.E)."""
    rng = random.Random(int(seed) * 1_000_003 + 2204)
    kw = {} if users_per_cell is None else {"users_per_cell": users_per_cell}
    grid = {k: v for k, v in (("rows", rows), ("cols", cols)) if v is not None}
    if name == "tr38889-indoor":
        if grid:
            raise ValueError("--layout-rows/--layout-cols don't apply to tr38889-indoor")
        return tr38889_indoor(rng, serving_ok=serving_ok, **kw)
    if name.startswith("tgax") and serving_ok is not None:
        raise ValueError("the minimum serving power applies to tr38889-indoor and hex (TGax users stay in their room)")
    if name == "tgax-residential":
        return tgax_residential(rng, **grid, **kw)
    if name == "tgax-enterprise":
        return tgax_enterprise(rng, **grid, **kw)
    if name == "hex":
        if grid:
            raise ValueError("--layout-rows/--layout-cols don't apply to hex (use --hex-rings)")
        return hexagon(rng, hex_rings, hex_isd_m, serving_ok=serving_ok, **kw)
    raise ValueError(f"layout must be one of {LAYOUTS}, got {name!r}")


def assign_channels(positions: List[Pos], n_channels: int) -> List[float]:
    """Reuse pattern: centre frequency (Hz) per site over n_channels 20 MHz
    channels - greedy, each site (in order) takes the channel whose
    nearest co-channel site is farthest away (ties: lowest channel)."""
    if not 1 <= n_channels <= len(CHANNELS_GHZ):
        raise ValueError(f"channel reuse must be 1..{len(CHANNELS_GHZ)}")
    chosen: List[int] = []
    for i, p in enumerate(positions):
        best, best_d = 0, -1.0
        for ch in range(n_channels):
            d = min((math.hypot(p[0] - positions[j][0], p[1] - positions[j][1])
                     for j in range(i) if chosen[j] == ch), default=math.inf)
            if d > best_d:
                best, best_d = ch, d
        chosen.append(best)
    return [CHANNELS_GHZ[c] * 1e9 for c in chosen]
# Rashed-Step 22.D-10-15-2026-end


# Rashed-Step 22.E-10-15-2026-start
def serving_rule(min_dbm: float, tx_dbm_of, f_hz_of, pathloss=None, seed: int = 0):
    """serving_ok(site, p) for build_layout: the site's received power at p
    (its tx power - path loss incl. the model's shadowing, as the run will
    see it: Propagation is a function of the seed and positions) >= min_dbm.
    No path-loss model: log-distance, exponent 3. tx_dbm_of / f_hz_of map a
    Site to its cell's tx power / frequency."""
    from channel.propagation import Propagation
    from common.common_phy import rx_power_dbm
    prop = Propagation(pathloss, seed) if pathloss is not None else None

    def ok(site, p):
        if prop is not None:
            pr = tx_dbm_of(site) - prop.loss_db(site.pos, p, f_hz_of(site), True, False)
        else:
            pr = rx_power_dbm(tx_dbm_of(site), math.hypot(site.pos[0] - p[0], site.pos[1] - p[1]), f_hz_of(site), n=3.0)
        return pr >= min_dbm
    return ok
# Rashed-Step 22.E-10-15-2026-end
