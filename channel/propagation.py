# Rashed-Step 22.A-10-15-2026-start
"""
Path-loss models for Channel (Step 22.A, Phase D realism).

Default (no model): the original log-distance path loss with each
transmission's pl_exp - Channel.rx_power_at() then runs exactly the old
expression, byte-identical. With --pathloss-model one of:

  inh-office-mixed / inh-office-open   3GPP TR 38.901 InH-Office
  umi                                  38.901 UMi-Street Canyon
  uma                                  38.901 UMa
  tgax-residential / tgax-enterprise   IEEE 802.11-14/0980 (TGax)

38.901 (Table 7.4.1-1, fc in GHz, distances in m):
  InH LOS  : 32.4 + 17.3 log10(d3D) + 20 log10(fc)
  InH NLOS : max(LOS, 38.3 log10(d3D) + 17.30 + 24.9 log10(fc))
  UMi LOS  : 32.4 + 21 log10(d3D) + 20 log10(fc)          d2D <= d'BP
             32.4 + 40 log10(d3D) + 20 log10(fc)
                  - 9.5 log10(d'BP^2 + (hBS - hUT)^2)     beyond
  UMi NLOS : max(LOS, 35.3 log10(d3D) + 22.4 + 21.3 log10(fc) - 0.3 (hUT - 1.5))
  UMa LOS  : 28 + 22 log10(d3D) + 20 log10(fc)            d2D <= d'BP
             28 + 40 log10(d3D) + 20 log10(fc)
                - 9 log10(d'BP^2 + (hBS - hUT)^2)         beyond
  UMa NLOS : max(LOS, 13.54 + 39.08 log10(d3D) + 20 log10(fc) - 0.6 (hUT - 1.5))
  d'BP = 4 (hBS - 1)(hUT - 1) fc[Hz] / c (effective environment height 1 m).
  LOS probability (Table 7.4.2-1) from d2D - mixed / open office, UMi, UMa
  (hUT <= 13 m). Distances below 1 m are taken as 1 m.
TGax: 40.05 + 20 log10(fc/2.4) + 20 log10(min(d, dBP))
      + (d > dBP) 35 log10(d/dBP) + 18.3 F^((F+2)/(F+1) - 0.46) + L_W W
  residential dBP 5 m, L_W 5 dB; enterprise dBP 10 m, L_W 7 dB. W = walls
  crossed on a square grid of rooms (--tgax-room-size-m, default 10 / 20 m);
  F = 0 (floors come with the Step 22.D layouts).

Heights: infrastructure nodes (names "AP ..." / "Gnb...") at the BS height,
everyone else at the UT height (defaults per model: InH 3 / 1.5 m, UMi 10 /
1.5, UMa 25 / 1.5, TGax 3 / 1.5). A link's LOS state is drawn once from its
LOS probability and kept for the run, the same in both directions (keyed by
the unordered pair of end positions); --pathloss-los los|nlos forces it.
Shadowing is unchanged here (--shadowing-sigma-db); Step 22.B adds the
models' own.
"""
import math
import random
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

C_M_S = 3.0e8

MODELS = ("inh-office-mixed", "inh-office-open", "umi", "uma", "tgax-residential", "tgax-enterprise")
LOS_MODES = ("auto", "los", "nlos")

# model -> (BS height, UT height)
DEFAULT_HEIGHTS = {
    "inh-office-mixed": (3.0, 1.5), "inh-office-open": (3.0, 1.5),
    "umi": (10.0, 1.5), "uma": (25.0, 1.5),
    "tgax-residential": (3.0, 1.5), "tgax-enterprise": (3.0, 1.5),
}
TGAX = {"tgax-residential": (5.0, 5.0, 10.0), "tgax-enterprise": (10.0, 7.0, 20.0)}  # dBP, wall dB, room size


def is_infrastructure(name: Optional[str]) -> bool:
    """APs and gNBs (NR-U "Gnb n", licensed "GnbNR n") sit at the BS height."""
    return bool(name) and (name.startswith("AP") or name.startswith("Gnb"))


def los_probability(model: str, d2d: float) -> float:
    """38.901 Table 7.4.2-1. TGax has no LOS state (always 1)."""
    if model == "inh-office-mixed":
        if d2d <= 1.2:
            return 1.0
        if d2d < 6.5:
            return math.exp(-(d2d - 1.2) / 4.7)
        return 0.32 * math.exp(-(d2d - 6.5) / 32.6)
    if model == "inh-office-open":
        if d2d <= 5.0:
            return 1.0
        if d2d <= 49.0:
            return math.exp(-(d2d - 5.0) / 70.8)
        return 0.54 * math.exp(-(d2d - 49.0) / 211.7)
    if model in ("umi", "uma"):
        if d2d <= 18.0:
            return 1.0
        k = 36.0 if model == "umi" else 63.0
        return 18.0 / d2d + math.exp(-d2d / k) * (1.0 - 18.0 / d2d)
    return 1.0


def _umx_los(model: str, d2d: float, d3d: float, fc: float, h_bs: float, h_ut: float) -> float:
    a, b, c = (32.4, 21.0, 9.5) if model == "umi" else (28.0, 22.0, 9.0)
    d_bp = 4.0 * max(h_bs - 1.0, 0.0) * max(h_ut - 1.0, 0.0) * fc * 1e9 / C_M_S
    if d2d <= d_bp or d_bp <= 0.0:
        return a + b * math.log10(d3d) + 20.0 * math.log10(fc)
    return a + 40.0 * math.log10(d3d) + 20.0 * math.log10(fc) - c * math.log10(d_bp ** 2 + (h_bs - h_ut) ** 2)


def path_loss_db(model: str, d2d: float, h_bs: float, h_ut: float, f_hz: float, los: bool,
                 walls: int = 0, floors: int = 0) -> float:
    """Path loss of one link in dB (no shadowing). h_bs >= h_ut."""
    fc = f_hz / 1e9
    d2d = max(d2d, 1.0)
    d3d = max(math.hypot(d2d, h_bs - h_ut), 1.0)
    if model.startswith("inh-office"):
        pl_los = 32.4 + 17.3 * math.log10(d3d) + 20.0 * math.log10(fc)
        if los:
            return pl_los
        return max(pl_los, 38.3 * math.log10(d3d) + 17.30 + 24.9 * math.log10(fc))
    if model in ("umi", "uma"):
        pl_los = _umx_los(model, d2d, d3d, fc, h_bs, h_ut)
        if los:
            return pl_los
        if model == "umi":
            nlos = 35.3 * math.log10(d3d) + 22.4 + 21.3 * math.log10(fc) - 0.3 * (h_ut - 1.5)
        else:
            nlos = 13.54 + 39.08 * math.log10(d3d) + 20.0 * math.log10(fc) - 0.6 * (h_ut - 1.5)
        return max(pl_los, nlos)
    if model in TGAX:
        d_bp, wall_db, _ = TGAX[model]
        pl = 40.05 + 20.0 * math.log10(fc / 2.4) + 20.0 * math.log10(min(d3d, d_bp))
        if d3d > d_bp:
            pl += 35.0 * math.log10(d3d / d_bp)
        if floors > 0:
            pl += 18.3 * floors ** ((floors + 2.0) / (floors + 1.0) - 0.46)
        return pl + wall_db * walls
    raise ValueError(f"unknown path-loss model {model!r}")


def walls_between(a: Tuple[float, float], b: Tuple[float, float], room_m: float) -> int:
    """Walls crossed between two points on a square grid of rooms."""
    return (abs(math.floor(a[0] / room_m) - math.floor(b[0] / room_m))
            + abs(math.floor(a[1] / room_m) - math.floor(b[1] / room_m)))


@dataclass(frozen=True)
class PathLossSpec:
    """What the CLI chose; Propagation(spec, seed) is the per-run state."""
    model: str
    los_mode: str = "auto"
    bs_height_m: Optional[float] = None
    ut_height_m: Optional[float] = None
    room_size_m: Optional[float] = None

    def __post_init__(self):
        if self.model not in MODELS:
            raise ValueError(f"pathloss model must be one of {MODELS}, got {self.model!r}")
        if self.los_mode not in LOS_MODES:
            raise ValueError(f"pathloss LOS mode must be one of {LOS_MODES}, got {self.los_mode!r}")
        for v in (self.bs_height_m, self.ut_height_m, self.room_size_m):
            if v is not None and v <= 0:
                raise ValueError("heights and room size must be > 0")
        if self.room_size_m is not None and self.model not in TGAX:
            raise ValueError("room size (walls) only applies to the TGax models")


@dataclass
class Propagation:
    spec: PathLossSpec
    seed: int = 0
    _los: Dict[tuple, bool] = field(default_factory=dict, repr=False)
    _rng: random.Random = field(init=False, repr=False)

    def __post_init__(self):
        # Own RNG: switching a model on doesn't move any other random draw.
        self._rng = random.Random(self.seed * 1_000_003 + 22)
        bs, ut = DEFAULT_HEIGHTS[self.spec.model]
        self.h_bs = self.spec.bs_height_m if self.spec.bs_height_m is not None else bs
        self.h_ut = self.spec.ut_height_m if self.spec.ut_height_m is not None else ut
        self.room_m = (self.spec.room_size_m if self.spec.room_size_m is not None
                       else TGAX[self.spec.model][2] if self.spec.model in TGAX else None)

    def is_los(self, a, b, d2d: float) -> bool:
        if self.spec.los_mode != "auto":
            return self.spec.los_mode == "los"
        key = (a, b) if a <= b else (b, a)
        if key not in self._los:
            self._los[key] = self._rng.random() < los_probability(self.spec.model, d2d)
        return self._los[key]

    def loss_db(self, tx_pos, rx_pos, f_hz: float, tx_infra: bool, rx_infra: bool) -> float:
        d2d = math.hypot(tx_pos[0] - rx_pos[0], tx_pos[1] - rx_pos[1])
        h_tx = self.h_bs if tx_infra else self.h_ut
        h_rx = self.h_bs if rx_infra else self.h_ut
        model = self.spec.model
        walls = walls_between(tx_pos, rx_pos, self.room_m) if model in TGAX else 0
        los = True if model in TGAX else self.is_los(tuple(tx_pos), tuple(rx_pos), d2d)
        return path_loss_db(model, d2d, max(h_tx, h_rx), min(h_tx, h_rx), f_hz, los, walls=walls)


def pathloss_spec_from_cli(model: Optional[str], los: str = "auto", bs_height_m: Optional[float] = None,
                           ut_height_m: Optional[float] = None,
                           room_size_m: Optional[float] = None) -> Optional[PathLossSpec]:
    """--pathloss-model & co. -> PathLossSpec, or None (log-distance)."""
    if model is None or model == "log-distance":
        if los != "auto" or bs_height_m is not None or ut_height_m is not None or room_size_m is not None:
            raise ValueError("--pathloss-los / --bs-height-m / --ut-height-m / --tgax-room-size-m need --pathloss-model")
        return None
    return PathLossSpec(model, los, bs_height_m, ut_height_m, room_size_m)
# Rashed-Step 22.A-10-15-2026-end
