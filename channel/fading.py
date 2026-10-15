# Rashed-Step 22.C-10-15-2026-start
"""
Flat block fading (Step 22.C, Phase D realism).

One complex gain per link, the same for sensing and decoding, constant over
a coherence block and correlated from block to block (Doppler):

  h = sqrt(K/(K+1)) e^{j 2 pi d / lambda} + sqrt(1/(K+1)) h_s,  |h|^2 the power gain

h_s is the Rayleigh (diffuse) part: a Clarke / Jakes sum of M sinusoids
over the link's two END POSITIONS with |k| = 2 pi / lambda in uniform
directions - so its spatial correlation is J0(2 pi Δ / lambda) and a node
moving at v sees the classic Doppler v / lambda with no explicit speed
input - plus a slow time term for the environment moving around a static
link (scatterers at --fading-env-speed-mps, default 0.333 m/s = 1.2 km/h,
the TGn/TGax environment speed: fd ~ 5.8 Hz at 5 GHz). Symmetrized like
link_field.py, so the gain is the same in both directions (TDD
reciprocity), normalized to unit mean power. Stateless: a function of
(end positions, time block, frequency).

Block: the environment term is sampled at the start of each block of a
tenth of the coherence time T_c = 0.423 / f_env (~73 ms at 5.18 GHz, so
blocks of ~7.3 ms - far longer than a frame) and held ("block fading");
consecutive blocks correlate as J0(2 pi f_env T_block) ~ 0.98, so the gain
follows the Doppler process. Movement changes the gain immediately (a new
position is a new point of the field).

K (Rician factor) on LOS links: 38.901 Table 7.5-6 InH 7 dB, UMi 9, UMa 9;
TGax (TGn models B / D within the breakpoint distance): residential 0 dB,
enterprise 3 dB, Rayleigh beyond it; NLOS links Rayleigh. Without a
path-loss model every link uses --fading-k-db (default None = Rayleigh).

Limitation: a fade doesn't wake nodes waiting for the channel state to
change (Channel.state_changed fires on transmissions starting / ending), so
sensing sees a new fade at its next check.
"""
import math
from typing import Optional

import numpy as np

C_M_S = 3.0e8
M_PATHS = 64
DEFAULT_ENV_SPEED_MPS = 1.2 / 3.6
K_DB = {"inh-office-mixed": 7.0, "inh-office-open": 7.0, "umi": 9.0, "uma": 9.0,
        "tgax-residential": 0.0, "tgax-enterprise": 3.0}
_CACHE_MAX = 200_000


def _j0(x: float) -> float:
    from scipy.special import j0
    return float(j0(x))


class Fading:
    def __init__(self, seed: int, env_speed_mps: float = DEFAULT_ENV_SPEED_MPS, k_db: Optional[float] = None,
                 m: int = M_PATHS):
        if env_speed_mps <= 0:
            raise ValueError("fading environment speed must be > 0")
        rng = np.random.default_rng([int(seed) & 0xFFFFFFFF, 22, 5])
        th_k = rng.uniform(0.0, 2.0 * math.pi, m)
        th_l = rng.uniform(0.0, 2.0 * math.pi, m)
        self._uk = np.stack([np.cos(th_k), np.sin(th_k)], axis=1)
        self._ul = np.stack([np.cos(th_l), np.sin(th_l)], axis=1)
        self._cos_env = np.cos(rng.uniform(0.0, 2.0 * math.pi, m))
        self._phi = rng.uniform(0.0, 2.0 * math.pi, m)
        self.m = m
        self.v_env = float(env_speed_mps)
        self.k_db = k_db
        self._cache = {}

    def coherence_us(self, f_hz: float) -> float:
        return 0.423 / (self.v_env * f_hz / C_M_S) * 1e6

    def block_us(self, f_hz: float) -> float:
        return 0.1 * self.coherence_us(f_hz)

    def _raw(self, a, b, t_s: float, kmag: float, w_env: float) -> complex:
        ph = kmag * (self._uk @ a + self._ul @ b) + w_env * self._cos_env * t_s + self._phi
        return complex(np.exp(1j * ph).sum()) / math.sqrt(self.m)

    def diffuse(self, a, b, now_us: float, f_hz: float) -> complex:
        """Unit-power Rayleigh part h_s for the block containing now_us."""
        a, b = (tuple(a), tuple(b))
        if b < a:
            a, b = b, a
        tc = self.block_us(f_hz)
        block = math.floor(now_us / tc)
        key = (a, b, block, f_hz)
        h = self._cache.get(key)
        if h is None:
            lam = C_M_S / f_hz
            kmag = 2.0 * math.pi / lam
            w_env = 2.0 * math.pi * self.v_env / lam
            t_s = block * tc * 1e-6
            av, bv = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
            r = math.hypot(a[0] - b[0], a[1] - b[1])
            h = (self._raw(av, bv, t_s, kmag, w_env) + self._raw(bv, av, t_s, kmag, w_env)) \
                / math.sqrt(2.0 * (1.0 + _j0(kmag * r) ** 2))
            if len(self._cache) >= _CACHE_MAX:
                self._cache.clear()
            self._cache[key] = h
        return h

    def gain_db(self, a, b, now_us: float, f_hz: float, k_db: Optional[float] = None) -> float:
        """Power gain of the link (dB, mean 0 dB in linear terms)."""
        if k_db is None:
            k_db = self.k_db
        hs = self.diffuse(a, b, now_us, f_hz)
        if k_db is None:
            p = abs(hs) ** 2
        else:
            k = 10.0 ** (k_db / 10.0)
            r = math.hypot(a[0] - b[0], a[1] - b[1])
            los = complex(math.cos(2.0 * math.pi * r * f_hz / C_M_S), math.sin(2.0 * math.pi * r * f_hz / C_M_S))
            p = abs(math.sqrt(k / (k + 1.0)) * los + math.sqrt(1.0 / (k + 1.0)) * hs) ** 2
        return 10.0 * math.log10(max(p, 1e-12))
# Rashed-Step 22.C-10-15-2026-end
