# Rashed-Step 22.B-10-15-2026-start
"""
Spatially correlated, reciprocal link variables (Step 22.B): shadowing and
the 38.901 LOS state.

LinkField(seed, stream, d_cor).value(a, b) is a zero-mean, unit-variance,
(close to) Gaussian random field over the two END POSITIONS of a link:

  - reciprocal: value(a, b) == value(b, a) exactly;
  - spatially consistent (Gudmundson): moving either end by Δa, Δb changes
    it with correlation exp(-|Δa|/d_cor) * exp(-|Δb|/d_cor);
  - stateless: a function of the positions only - no node IDs, no
    dependence on the order in which links are evaluated, the same value
    for the same geometry every time.

How: R(a, b) = sqrt(2/M) sum_i cos(k_i.a + l_i.b + phi_i) with M sinusoids
whose 2D wavevectors k_i, l_i are drawn from the spectrum of the
exponential correlation exp(-r/d) (|k| has CDF 1 - (1 + (k d)^2)^-1/2,
uniform direction); then E[R R'] = exp(-|Δa|/d) exp(-|Δb|/d). Symmetrized:
S(a, b) = (R(a, b) + R(b, a)) / sqrt(2 (1 + exp(-2|a - b|/d))), the
denominator keeping unit variance (cov(R(a,b), R(b,a)) = exp(-2|a-b|/d)).
"""
import math

import numpy as np

M_SINUSOIDS = 256
_CACHE_MAX = 200_000


class LinkField:
    def __init__(self, seed: int, stream: int, d_cor_m: float, m: int = M_SINUSOIDS):
        if d_cor_m <= 0:
            raise ValueError("decorrelation distance must be > 0")
        rng = np.random.default_rng([int(seed) & 0xFFFFFFFF, 22, int(stream)])
        self.d = float(d_cor_m)
        self.m = m
        self._k = self._wavevectors(rng)
        self._l = self._wavevectors(rng)
        self._phi = rng.uniform(0.0, 2.0 * math.pi, m)
        self._amp = math.sqrt(2.0 / m)
        self._cache = {}

    def _wavevectors(self, rng):
        u = rng.uniform(0.0, 1.0, self.m)
        mag = np.sqrt((1.0 - u) ** -2 - 1.0) / self.d
        ang = rng.uniform(0.0, 2.0 * math.pi, self.m)
        return np.stack([mag * np.cos(ang), mag * np.sin(ang)], axis=1)

    def _raw(self, a, b) -> float:
        ph = self._k @ np.asarray(a, dtype=float) + self._l @ np.asarray(b, dtype=float) + self._phi
        return self._amp * float(np.cos(ph).sum())

    def value(self, a, b) -> float:
        a, b = (tuple(a), tuple(b))
        if b < a:
            a, b = b, a
        key = (a, b)
        v = self._cache.get(key)
        if v is None:
            r = math.hypot(a[0] - b[0], a[1] - b[1])
            v = (self._raw(a, b) + self._raw(b, a)) / math.sqrt(2.0 * (1.0 + math.exp(-2.0 * r / self.d)))
            if len(self._cache) >= _CACHE_MAX:
                self._cache.clear()
            self._cache[key] = v
        return v

    def uniform(self, a, b) -> float:
        """value() mapped through the normal CDF: a correlated U(0, 1)."""
        return 0.5 * (1.0 + math.erf(self.value(a, b) / math.sqrt(2.0)))
# Rashed-Step 22.B-10-15-2026-end
