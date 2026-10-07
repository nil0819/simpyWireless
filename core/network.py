# Rashed-Step 16.B-10-02-2026-start
"""
Step 16.B: minimal 5G Core skeleton - Amf, Smf, Upf, and a CoreNetwork
container that wires them together (Project details/Step 16.txt,
Step pre_15.txt roadmap "Phase 3" / Section 4's "5G Core" design).

WHAT THIS IS (and is not)
  - Simplified, orchestration-level stand-ins, documented the same way
    generic/generic_device.py's GenericWirelessDevice is: each class owns
    one piece of Core state and nothing else. The real N1/N2/N3/N4
    interfaces (NAS, NGAP, GTP-U, PFCP) are NOT modeled - they are plain
    Python method calls between these objects.
  - No slicing, one DNN, one UPF by default, one PDU session per UE.
  - Every state change here is instantaneous. The time a procedure
    takes (registration, PDU session establishment) is charged by the
    simpy procedures 16.C/16.D add in core/procedures.py, which call
    these methods at the right simulated instant - same split as
    ran/protocol/rrc.py, where RrcLayer.attach() owns the timing and
    the UE/gNB objects only hold state.
  - Success-only for now (Step 16.txt open decision 3): the only
    "rejections" are programming errors (e.g. asking the SMF for a
    session for a UE the AMF never registered), raised as ValueError
    rather than silently modeled as a network-side reject.

TIMING DEFAULTS (CoreConfig, Step 16.A)
  Sourced from a measured COTS 5G SA testbed rather than invented:
  Open5GS registration ~90 ms and PDU session establishment ~125 ms
  (arXiv:2412.21162, Figs. 5-6; free5GC/OAI measured ~102/139 ms and
  ~126/146 ms). Those were measured UE-side end to end, so they include
  a few ms of radio signaling this simulator already models separately
  through RRC - negligible next to 90/125 ms, noted rather than
  subtracted. Both are plain config fields; set them per scenario.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class RegistrationState(Enum):
    DEREGISTERED = "deregistered"
    REGISTERED = "registered"


class PduSessionState(Enum):
    INACTIVE = "inactive"
    PENDING = "pending"
    ACTIVE = "active"


@dataclass
class CoreConfig:
    # Registration Request -> Registration Accept (NAS, via AMF).
    registration_delay_us: float = 90_000.0
    # PDU Session Establishment Request -> Accept (via SMF/UPF).
    pdu_session_delay_us: float = 125_000.0
    # Single data network name every session is established on.
    dnn: str = "internet"
    # Rashed-Step 19.D.2-10-07-2026-start
    # Failure modes (Step 19.D.2, TS 24.501). Defaults = never fails,
    # unlimited capacity: exactly the earlier behavior.
    # Chance that one Registration / PDU Session Establishment request is
    # rejected (e.g. congestion). A rejected UE retries after retry_us
    # (T3511 = 10 s) and gives up after max_attempts (the attempt counter's
    # limit, 5).
    registration_reject_prob: float = 0.0
    pdu_reject_prob: float = 0.0
    retry_us: float = 10_000_000.0
    max_attempts: int = 5
    # Overload: how many procedures the AMF / SMF handle at once (None =
    # unlimited). Each holds a slot for service_us at the start of its
    # normal delay; the rest queue - a signaling storm when many UEs
    # attach together.
    amf_capacity: Optional[int] = None
    smf_capacity: Optional[int] = None
    service_us: float = 10_000.0
    
    def __post_init__(self):
        for name in ("registration_reject_prob", "pdu_reject_prob"):
            v = getattr(self, name)
            if not 0.0 <= v < 1.0:
                raise ValueError(f"{name} must be in [0, 1) (got {v}).")
        if self.max_attempts < 1:
            raise ValueError(f"max_attempts must be >= 1 (got {self.max_attempts}).")
        for name in ("amf_capacity", "smf_capacity"):
            v = getattr(self, name)
            if v is not None and v < 1:
                raise ValueError(f"{name} must be >= 1 (got {v}).")
        if self.retry_us < 0 or self.service_us < 0:
            raise ValueError("retry_us / service_us must be >= 0.")
        if self.service_us > min(self.registration_delay_us, self.pdu_session_delay_us) and (
                self.amf_capacity is not None or self.smf_capacity is not None):
            raise ValueError("service_us must not exceed the registration / PDU session delay.")
    
    @property
    def failure_modes_on(self) -> bool:
        return (self.registration_reject_prob > 0 or self.pdu_reject_prob > 0
                or self.amf_capacity is not None or self.smf_capacity is not None)
    # Rashed-Step 19.D.2-10-07-2026-end


# Rashed-Step 16.F-10-02-2026-start
def core_config_from_cli(core_enabled: bool,
                         registration_delay_us: Optional[float] = None,
                         pdu_session_delay_us: Optional[float] = None,
                         **failure_overrides) -> Optional["CoreConfig"]:  # 19.D.2: failure_overrides
    """Shared by singleRun.py and singleRunNR.py: a CoreConfig with any
    delay overrides applied, or None when the Core is off. Raises
    ValueError (each CLI turns it into click.BadParameter) for delay
    flags given without the Core flag, or negative delays."""
    overrides = {}
    if registration_delay_us is not None:
        overrides["registration_delay_us"] = registration_delay_us
    if pdu_session_delay_us is not None:
        overrides["pdu_session_delay_us"] = pdu_session_delay_us
    # Rashed-Step 19.D.2-10-07-2026-start
    fo = {k: v for k, v in failure_overrides.items() if v is not None}
    if fo and not core_enabled:
        raise ValueError("--core-* failure-mode flags only apply with the 5G Core enabled.")
    # Rashed-Step 19.D.2-10-07-2026-end
    if not core_enabled:
        if overrides:
            raise ValueError(
                "--core-registration-delay-us/--core-pdu-session-delay-us "
                "only apply with the 5G Core enabled (--core-enabled in "
                "singleRunNR.py, --nru-core-enabled in singleRun.py)."
            )
        return None
    for name, value in overrides.items():
        if value < 0:
            raise ValueError(f"{name} must be >= 0 (got {value}).")
    return CoreConfig(**overrides, **fo)  # 19.D.2: + failure-mode overrides
# Rashed-Step 16.F-10-02-2026-end


@dataclass
class PduSession:
    session_id: int
    ue_name: str
    dnn: str
    upf_name: str
    state: PduSessionState = PduSessionState.PENDING
    requested_at: Optional[float] = None
    activated_at: Optional[float] = None


class Amf:
    """Access and Mobility Management Function stand-in: which UEs are
    registered, and which gNB serves each one."""

    def __init__(self, name: str = "AMF 1"):
        self.name = name
        self.serving_gnb: Dict[str, str] = {}

    def register(self, ue_name: str, gnb_name: str) -> None:
        self.serving_gnb[ue_name] = gnb_name

    def deregister(self, ue_name: str) -> None:
        self.serving_gnb.pop(ue_name, None)

    def is_registered(self, ue_name: str) -> bool:
        return ue_name in self.serving_gnb


class Upf:
    """User Plane Function stand-in: a gate. A UE's DATA packets may only
    reach the channel while this UPF anchors an ACTIVE session for it
    (enforced by the RAN in 16.E, not here)."""

    def __init__(self, name: str = "UPF 1"):
        self.name = name
        self._anchored: set = set()

    def anchor(self, ue_name: str) -> None:
        self._anchored.add(ue_name)

    def release(self, ue_name: str) -> None:
        self._anchored.discard(ue_name)

    def allows(self, ue_name: str) -> bool:
        return ue_name in self._anchored


class Smf:
    """Session Management Function stand-in: owns each UE's PDU session
    state machine (INACTIVE -> PENDING -> ACTIVE) and picks the UPF
    that anchors it."""

    def __init__(self, amf: Amf, upfs: List[Upf], dnn: str = "internet", name: str = "SMF 1"):
        if not upfs:
            raise ValueError("Smf needs at least one Upf to anchor sessions on.")
        self.name = name
        self.amf = amf
        self.upfs = upfs
        self.dnn = dnn
        self.sessions: Dict[str, PduSession] = {}
        self._next_session_id = 1

    def select_upf(self, ue_name: str) -> Upf:
        # Single-UPF topology by default; with several, spread UEs by
        # session order. Real UPF selection (DNN/slice/location-aware)
        # is out of scope.
        return self.upfs[(self._next_session_id - 1) % len(self.upfs)]

    def _upf_by_name(self, upf_name: str) -> Upf:
        return next(u for u in self.upfs if u.name == upf_name)

    def request_session(self, ue_name: str, now: float) -> PduSession:
        """PDU Session Establishment Request received -> PENDING."""
        if not self.amf.is_registered(ue_name):
            raise ValueError(f"Smf: {ue_name} is not registered with {self.amf.name}.")
        existing = self.sessions.get(ue_name)
        if existing is not None and existing.state is not PduSessionState.INACTIVE:
            raise ValueError(f"Smf: {ue_name} already has a {existing.state.value} session.")
        upf = self.select_upf(ue_name)
        session = PduSession(
            session_id=self._next_session_id, ue_name=ue_name, dnn=self.dnn,
            upf_name=upf.name, state=PduSessionState.PENDING, requested_at=now,
        )
        self._next_session_id += 1
        self.sessions[ue_name] = session
        return session

    def activate_session(self, ue_name: str, now: float) -> PduSession:
        """PDU Session Establishment Accept -> ACTIVE; the UPF starts
        letting this UE's traffic through."""
        session = self.sessions.get(ue_name)
        if session is None or session.state is not PduSessionState.PENDING:
            raise ValueError(f"Smf: {ue_name} has no PENDING session to activate.")
        session.state = PduSessionState.ACTIVE
        session.activated_at = now
        self._upf_by_name(session.upf_name).anchor(ue_name)
        return session

    def release_session(self, ue_name: str) -> None:
        session = self.sessions.get(ue_name)
        if session is None:
            return
        self._upf_by_name(session.upf_name).release(ue_name)
        session.state = PduSessionState.INACTIVE

    def session_state(self, ue_name: str) -> PduSessionState:
        session = self.sessions.get(ue_name)
        return session.state if session is not None else PduSessionState.INACTIVE


class CoreNetwork:
    """One AMF, one SMF, and (by default) one UPF, wired together. One
    instance per orchestrator run (Step 16.txt open decision 2)."""

    def __init__(self, env: Any, config: Optional[CoreConfig] = None, n_upfs: int = 1,
                 seed: Optional[int] = None):  # 19.D.2: seed
        self.env = env
        self.config = config if config is not None else CoreConfig()
        # Rashed-Step 19.D.2-10-07-2026-start
        # Failure modes: own random stream (draws only when a reject
        # probability is set) and AMF / SMF capacity.
        import random as _random
        import simpy as _simpy
        self.rng = _random.Random((0 if seed is None else seed) + 19_002)
        c = self.config
        self.amf_slots = _simpy.Resource(env, capacity=c.amf_capacity) if c.amf_capacity else None
        self.smf_slots = _simpy.Resource(env, capacity=c.smf_capacity) if c.smf_capacity else None
        # Rashed-Step 19.D.2-10-07-2026-end
        self.amf = Amf()
        self.upfs = [Upf(f"UPF {i}") for i in range(1, n_upfs + 1)]
        self.smf = Smf(self.amf, self.upfs, dnn=self.config.dnn)

    def user_plane_allows(self, ue_name: str) -> bool:
        """The single question the RAN will ask in 16.E."""
        return any(upf.allows(ue_name) for upf in self.upfs)
# Rashed-Step 16.B-10-02-2026-end

    # Rashed-Step 16.C-10-02-2026-start
    def start_ue(self, gnb: Any, ue: Any):
        """Hand one UE to the Core: marks it DEREGISTERED and starts its
        procedure chain (core/procedures.py's ue_attach - waits for RRC
        CONNECTED, registers, then establishes a PDU session). Returns
        the simpy Process. The only way a UE gains reg_state - see
        core/procedures.py's backward-compat contract."""
        # Imported here: core/procedures.py imports this module.
        from core.procedures import ue_attach
        ue.reg_state = RegistrationState.DEREGISTERED
        # Rashed-Step 16.D-10-02-2026-start
        # Start of the attach for UEs without RRC (see
        # compute_pdu_session_stats' attach_latencies_us).
        ue.core_started_at = self.env.now
        # Rashed-Step 16.D-10-02-2026-end
        # Rashed-Step 16.E-10-02-2026-start
        # RAN-side UPF gate hooks (ran/protocol/user_plane.py): the
        # schedulers ask ue.core_network.user_plane_allows(); NR-U's
        # autonomous uplink waits on _user_plane_event, fired by
        # pdu_session_establishment() at activation.
        ue.core_network = self
        ue._user_plane_event = self.env.event()
        # Rashed-Step 16.E-10-02-2026-end
        return self.env.process(ue_attach(self, gnb, ue))
    # Rashed-Step 16.C-10-02-2026-end
