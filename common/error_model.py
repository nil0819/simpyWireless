# Rashed-Step 18.A-10-06-2026-start
"""
Link-level error model (Step 18.A) - whether a received frame/transport
block decodes, given its SINR and the SINR its MCS needs.

Two rules:
  - threshold (default, error_model=None everywhere): decodes iff
    sinr >= required. Exactly the rule every technology used before
    this step, so runs without --error-model bler are byte-identical.
  - bler: a random draw against a block error rate (BLER) curve. HARQ
    (18.E) needs this - under the threshold rule a retransmission at
    the same SINR fails every time.

BLER curve: logistic in dB, anchored so BLER = target_bler (10%) at the
MCS's existing required-SINR value. 3GPP defines CQI as the highest MCS
whose BLER stays at or below 10% (TS 38.214 5.2.2.1), so the per-MCS
tables in nr/nr.py, nru/nru.py and Times.py keep their meaning: "the
SINR where this MCS hits 10% BLER".

    BLER(s) = 1 / (1 + exp(k * (s - s50))),  s50 = req - ln((1-t)/t) / k

k = slope_per_db (default 2.0): BLER goes 90% -> 10% over ~2.2 dB and
10% -> 1% over another ~1.2 dB, a typical LDPC/turbo waterfall.

The model owns its random stream (random.Random(seed)), so decode draws
never consume the global `random` stream that backoffs, positions and
shadowing use.

First-cut limitations: one curve per MCS regardless of block length;
interference is treated like noise (the SINR passed in is already the
effective one from channel.sinr_db's overlap rule).
"""
import math
import random
from dataclasses import dataclass, field
from typing import Dict, Optional

ERROR_MODEL_MODES = ("threshold", "bler")

# Keeps the decode stream distinct from the global stream even though
# both derive from the same run seed.
_SEED_OFFSET = 18_001


@dataclass(frozen=True)
class ErrorModelConfig:
    slope_per_db: float = 2.0
    target_bler: float = 0.1

    def __post_init__(self):
        if not self.slope_per_db > 0:
            raise ValueError(f"BLER slope must be > 0 per dB (got {self.slope_per_db})")
        if not 0.0 < self.target_bler < 1.0:
            raise ValueError(f"target BLER must be strictly between 0 and 1 (got {self.target_bler})")


@dataclass
class BlerErrorModel:
    config: ErrorModelConfig
    seed: int
    rng: random.Random = field(init=False, repr=False)
    stats: Dict[str, int] = field(init=False)

    def __post_init__(self):
        self.rng = random.Random(self.seed + _SEED_OFFSET)
        self.stats = {
            "decodes": 0,
            "failures": 0,
            # Losses the threshold rule would have delivered, and
            # deliveries it would have lost.
            "failures_above_threshold": 0,
            "successes_below_threshold": 0,
        }

    def bler(self, sinr_db: float, required_db: float) -> float:
        k = self.config.slope_per_db
        t = self.config.target_bler
        s50 = required_db - math.log((1.0 - t) / t) / k
        x = k * (sinr_db - s50)
        # exp() overflows past ~709; the curve is flat there anyway.
        if x > 700:
            return 0.0
        if x < -700:
            return 1.0
        return 1.0 / (1.0 + math.exp(x))

    def decode(self, sinr_db: float, required_db: float) -> bool:
        ok = self.rng.random() >= self.bler(sinr_db, required_db)
        self.stats["decodes"] += 1
        if not ok:
            self.stats["failures"] += 1
            if sinr_db >= required_db:
                self.stats["failures_above_threshold"] += 1
        elif sinr_db < required_db:
            self.stats["successes_below_threshold"] += 1
        return ok


def decode_ok(error_model: Optional[BlerErrorModel], sinr_db: float, required_db: float) -> bool:
    """The success decision every technology's receive path calls."""
    if error_model is None:
        return sinr_db >= required_db
    return error_model.decode(sinr_db, required_db)


def make_error_model(config: Optional[ErrorModelConfig], seed: int) -> Optional[BlerErrorModel]:
    """One model per run (per seed); None means the threshold rule."""
    if config is None:
        return None
    return BlerErrorModel(config, seed)


def error_model_config_from_cli(mode: str, slope_per_db: Optional[float]) -> Optional[ErrorModelConfig]:
    """Map the --error-model / --bler-slope-db flags; ValueError on misuse."""
    if mode not in ERROR_MODEL_MODES:
        raise ValueError(f"--error-model must be one of {ERROR_MODEL_MODES} (got {mode!r})")
    if mode == "threshold":
        if slope_per_db is not None:
            raise ValueError("--bler-slope-db requires --error-model bler.")
        return None
    if slope_per_db is None:
        return ErrorModelConfig()
    return ErrorModelConfig(slope_per_db=slope_per_db)


def print_error_model_stats(error_model: Optional[BlerErrorModel]) -> None:
    if error_model is None:
        return
    s = error_model.stats
    rate = s["failures"] / s["decodes"] if s["decodes"] else 0.0
    print("=== Error Model ===")
    print(f"Error model: bler (slope {error_model.config.slope_per_db} per dB, "
          f"target {error_model.config.target_bler} at the MCS threshold)")
    print(f'Error model decodes: {s["decodes"]}')
    print(f'Error model block errors: {s["failures"]}')
    print(f"Error model block error rate: {rate}")
    print(f'Error model losses above threshold: {s["failures_above_threshold"]}')
    print(f'Error model successes below threshold: {s["successes_below_threshold"]}')
# Rashed-Step 18.A-10-06-2026-end
