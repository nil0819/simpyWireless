from common.common import *
from Times import *
from common.common import Pos
# Rashed-Step 2.D_2-01-08-2026-start
from common.common_phy import rx_power_dbm, dist
# Rashed-Step 2.D_2-01-08-2026-end

# Rashed-Step 3.E_3-01-12-2026-start
from channel.channel import ActiveTx
# Rashed-Step 3.E_3-01-12-2026-end

# Rashed-Step 5.D-02-06-2026-start
from common.common_phy import mcs_sinr_threshold_db
from typing import Optional
# Rashed-Step 5.D-02-06-2026-end
# Rashed-Step 5.G-02-06-2026-start
from typing import Any
# Rashed-Step 5.G-02-06-2026-end
# Rashed-Step 8.B-08-06-2026-start
from common.packet import Packet, TrafficConfig
# Rashed-Step 10.A-08-07-2026-start
from common.packet import pick_traffic_class
# Rashed-Step 10.A-08-07-2026-end
# Rashed-Step 8.B-08-06-2026-end

# Rashed-Step 15.A-09-18-2026-start
from ran.protocol.channel_access import LbtChannelAccess, generate_backoff_slots as _lbt_generate_backoff_slots
# Rashed-Step pre_20.D.1-10-08-2026-start
from ran.protocol.channel_access import CAPC_DL
# Rashed-Step pre_20.D.2-10-08-2026-start
from ran.protocol.channel_access import ts37213_ed_threshold_dbm
# Rashed-Step pre_20.D.2-10-08-2026-end
# Rashed-Step pre_20.D.1-10-08-2026-end
# Rashed-Step 15.A-09-18-2026-end
# Rashed-Step 15.F-09-18-2026-start
from ran.protocol.rrc import RrcLayer
# Rashed-Step 15.F-09-18-2026-end
# Rashed-Step 15.G-09-18-2026-start
from ran.protocol.rrc import RrcState
# Rashed-Step 15.G-09-18-2026-end
# Rashed-Step 16.E-10-02-2026-start
from ran.protocol.user_plane import user_plane_allows
# Rashed-Step 16.E-10-02-2026-end
# Rashed-Step 15.D-09-18-2026-start
from enum import Enum
# Rashed-Step 18.A-10-06-2026-start
from common.error_model import decode_ok
# Rashed-Step 18.A-10-06-2026-end
# Rashed-Step 18.C-10-06-2026-start
from common.common_phy import thermal_noise_dbm
from nr.nr import (NR_MCS_TABLE, NUMEROLOGY_SCS_KHZ, resource_block_count, select_mcs_for_sinr,
                   slot_duration_us)
from ran.protocol.buffer import ByteBuffer, arrival_process
# Rashed-Step 18.E-10-06-2026-start
from ran.protocol.harq import HarqConfig, HarqEntity, HarqTb
# Rashed-Step 18.F-10-06-2026-start
from ran.protocol.l2 import L2Config, make_buffer
# Rashed-Step 19.A-10-07-2026-start
from ran.protocol.rach import RachConfig, RachCell
# Rashed-Step 19.B.2-10-07-2026-start
from ran.protocol.rlm import RlmConfig
# Rashed-Step 19.B.3-10-07-2026-start
from ran.protocol.inactive import InactiveConfig
# Rashed-Step 19.B.3-10-07-2026-end
# Rashed-Step 19.B.2-10-07-2026-end
# Rashed-Step 19.A-10-07-2026-end
# Rashed-Step 18.F-10-06-2026-end
# Rashed-Step 18.E-10-06-2026-end
COT_MODELS = ("burst", "slots")
# Rashed-Step 18.D-10-06-2026-start
NRU_UL_INTERLACES = {0: 10, 1: 5}  # TS 38.211 4.4.4.6
# Rashed-Step 18.D-10-06-2026-end
# Rashed-Step 18.C-10-06-2026-end
# Rashed-Step 15.D-09-18-2026-end


# Rashed-Step 15.D-09-18-2026-start
class NruDeploymentMode(Enum):
    """
    Which real-world NR-U deployment this gNB/UE pair is modeling - see
    "Project details/Step pre_15.txt" Section 4's "Bidirectional
    uplink/downlink channel access" subsection for the full background
    on both modes.

    STANDALONE_MULTIFIRE (the default, per Rashed's confirmed decision,
      2026-09-18): both downlink AND uplink live entirely in the
      unlicensed band, both LBT-gated (Cat-4). Fully functional as of
      Step 15.C - Gnb's downlink LBT (already existed) and NrUE's
      uplink LBT (Step 15.C, via the shared
      ran.protocol.channel_access.LbtChannelAccess both now use) are
      exactly this mode; no mode-specific branching is needed anywhere
      in Gnb/NrUE, since STANDALONE_MULTIFIRE *is* "both directions use
      LBT", which is simply how this simulator's NR-U already behaves.

    LAA_ANCHORED: downlink in the unlicensed band (still LBT-gated -
      real LAA's DL is a Cat-4 LBT burst too, same as MultiFire's),
      uplink in a LICENSED anchor cell instead (grant-based, no LBT at
      all) - a fundamentally different uplink mechanism from
      STANDALONE_MULTIFIRE's, not a variant of it. Recognized here as a
      real enum value so config/CLI code can start referring to it, but
      NOT wired to any functional behavior yet - it needs an anchor
      licensed-NR gNB and the Section 6 orchestrator-unification
      prerequisite (simulation.py/simulation_nr.py currently build
      completely separate Channel objects), neither of which exists as
      of Step 15.D. Selecting it and actually trying to use NrUE's
      LBT-based uplink (Step 15.C) raises NotImplementedError instead
      of silently giving you MultiFire-shaped behavior under an
      LAA_ANCHORED label - see NrUE.__post_init__ in nru/ue.py.
    """
    STANDALONE_MULTIFIRE = "standalone_multifire"
    LAA_ANCHORED = "laa_anchored"
# Rashed-Step 15.D-09-18-2026-end


# Rashed-Step 17.B-10-04-2026-start
class NruUplinkAccessMode(Enum):
    """
    How an NR-U UE gets the channel for uplink (Project details/Step
    17.txt). Only matters when a UE has uplink_enabled=True.

    AUTONOMOUS: Step 15.C's behavior - each UE runs its own full Cat-4
      LBT, independently of its gNB, then waits for the same sync-slot
      boundary as the gNB. Kept for comparison: it makes a gNB and its
      own UE start transmitting at the same instant and collide on
      every saturated attempt (Step 17.A measured 100% lockstep and 0
      packets delivered either way in a single cell).

    COT_SHARING (default since 17.E): real NR-U - the gNB wins Cat-4
      LBT, uses the first part of its channel occupancy time (COT) for
      downlink, and grants the rest (Config_NR.ul_cot_fraction) to one of
      its own UEs (round-robin across COTs), who sends after a single
      25us Type 2A LBT check. The UE runs no Cat-4 of its own for data,
      so it can't collide with its own gNB. Built in Steps 17.C-17.E.
    """
    AUTONOMOUS = "autonomous"
    COT_SHARING = "cot_sharing"
# Rashed-Step 17.B-10-04-2026-end


# Rashed-Step 5.D-02-06-2026-start
# NR-U never had an MCS/rate table before (unlike WiFi's Times.py MCS
# dict) - transmission duration here is still purely mcot-based, not
# MCS-dependent (a real per-MCS resource-block/throughput model is out of
# scope for this pass). This table only feeds the success/failure SINR
# gate, giving NR-U a similarly-shaped MCS index -> required-SINR curve to
# WiFi's for a fair side-by-side coexistence comparison. Same caveat as
# Times.WIFI_MCS_SINR_THRESHOLDS_DB: representative/typical values, not
# vendor- or 3GPP-conformance-tested figures.
NRU_MCS_SINR_THRESHOLDS_DB = {
    0: 5.0,
    1: 7.0,
    2: 9.0,
    3: 12.0,
    4: 15.0,
    5: 18.0,
    6: 21.0,
    7: 24.0,
}
# Rashed-Step 5.D-02-06-2026-end


@dataclass()
class Config_NR:
    deter_period: int = 16  # time used for waiting in prioritization period, microsec
    observation_slot_duration: int = 9  # observation slot in mikros
    # synchronization slot lenght in mikros
    synchronization_slot_duration: int = 1000
    max_sync_slot_desync: int = 1000
    min_sync_slot_desync: int = 0
    # channel access class related:
    M: int = 3  # amount of observation slots to wait after deter perion in prioritization period
    cw_min: int = 15
    cw_max: int = 63
    mcot: int = 6  # max ocupancy time

    # Rashed-Step 8.D-08-06-2026-start
    # NEW: NR-U had no working retry limit at all before this - see
    # sent_failed()'s note and "Project details/Step 8.txt" for the full
    # history (a dead `> 7` check compared a per-Transmission_NR counter
    # that always reset to 0 every attempt, since gen_new_transmission()
    # rebuilds a fresh Transmission_NR every single try). Default (7)
    # matches wifi.Config.r_limit's default and the magic number the
    # dead check used, so a run with no --nru_r_limit flag now actually
    # enforces the same "give up after 7" cap that was already implied
    # but never enforced.
    r_limit: int = 7
    # Rashed-Step 8.D-08-06-2026-end

    # Rashed-Step 2.C_2-12-26-2025-start
    tx_power_dbm: float = 23.0 
    f_ghz: float = 5.18e9
    pl_exp : float = 3.0        #indoor-ish
    # Rashed-Step 2.C_2-12-26-2025-end

    # Rashed-Step 3.A-12-26-2025-start
    ed_threshold_dbm: float = -72.0   # example; tune later
    # Rashed-Step 3.A-12-26-2025-end

    # Rashed-Step 4.D_1-01-28-2026-start
    # Rashed-Step 5.D-02-06-2026-start
    # UPGRADE: this used to be a single flat threshold applied regardless
    # of mcs. Renamed to an explicit override: None (default) means "look
    # up the required SINR for `mcs` in NRU_MCS_SINR_THRESHOLDS_DB"; set it
    # to force a flat threshold instead (e.g. for comparison against the
    # old behavior).
    nru_sinr_thr_db_override: Optional[float] = None
    # mcs is new - NR-U had no MCS concept before Step 5.D. Only feeds the
    # SINR threshold lookup above; transmission duration stays mcot-based
    # regardless of mcs (see NRU_MCS_SINR_THRESHOLDS_DB note above).
    mcs: int = 4
    # Rashed-Step 5.D-02-06-2026-end
    # Rashed-Step 4.D_1-01-28-2026-end

    # Rashed-Step 11.B-08-21-2026-start
    # Dynamic rate adaptation (Step 11), CQI-style: pick the MCS whose
    # required-SINR threshold best fits the most recently MEASURED
    # link SINR - approximates real 3GPP UE-reported Channel Quality
    # Indicator feedback (this simulator has no explicit CQI report
    # message, so "last measured SINR" stands in for it). Unlike
    # Wi-Fi's ARF (Config.rate_adapt_enabled), this is NOT a streak-
    # counter/blind-fallback scheme - it directly uses the channel
    # model's own SINR measurement, matching how a real gNB scheduler
    # picks MCS from feedback rather than reacting after the fact.
    # False (default) = config_nr.mcs is used exactly as before this
    # step - zero behavior change. See "Project details/Step 11.txt".
    rate_adapt_enabled: bool = False
    # Rashed-Step 11.B-08-21-2026-end

    # Rashed-Step 13.D-08-23-2026-start
    # Optional injected predictor (duck-typed: exposes .lag_k and
    # .predict_next(history) -> float - see ml/predictor.py's
    # SinrPredictor) for using a trained model's predicted NEXT SINR
    # instead of the raw last-measured value in current_mcs_for_link().
    # None (default) = every pre-Step-13.D behavior is completely
    # unchanged - only rate_adapt_enabled matters, same as before this
    # step. Typed Any (not a concrete class) specifically so nru.py
    # never has to import ml/ or sklearn/joblib itself - only the CLI
    # wiring that actually constructs a SinrPredictor does (Step 13.txt
    # design decision 6: ML code stays outside the simulator core).
    # Only meaningful when rate_adapt_enabled is also True.
    sinr_predictor: Any = None
    # Rashed-Step 13.D-08-23-2026-end

    # Rashed-Step 18.A-10-06-2026-start
    # Shared BlerErrorModel (common/error_model.py) for this run, also
    # used by this gNB's UEs. None (default) = the hard "SINR >=
    # threshold" rule, byte-identical to every earlier run.
    error_model: Any = None
    # Rashed-Step 18.A-10-06-2026-end

    # Rashed-Step 5.C-02-06-2026-start
    # See wifi.Config's matching fields - same idea, drives the SINR noise
    # floor via common_phy.thermal_noise_dbm() instead of a hardcoded
    # -94.0 dBm constant. Defaults land back at ~-94 dBm.
    bandwidth_mhz: float = 20.0
    noise_figure_db: float = 7.0
    # Rashed-Step 5.C-02-06-2026-end

    # Rashed-Step 15.D-09-18-2026-start
    # Which real-world NR-U deployment this config models - see
    # NruDeploymentMode's own docstring above. STANDALONE_MULTIFIRE
    # (default, per Rashed's confirmed decision, 2026-09-18) is fully
    # functional as of Step 15.C. LAA_ANCHORED is recognized but not yet
    # wired to anything - see NrUE.__post_init__ in nru/ue.py for the
    # guard that raises NotImplementedError rather than silently
    # misbehaving if it's selected with uplink_enabled=True.
    deployment_mode: NruDeploymentMode = NruDeploymentMode.STANDALONE_MULTIFIRE
    # Rashed-Step 15.D-09-18-2026-end

    # Rashed-Step 16.A-10-02-2026-start
    # Per-message uplink grant delay for RRC signaling, same meaning and
    # default as nr.nr.Config_NRL.rrc_ul_grant_delay_us. NR-U pays this
    # grant cost AND its Cat-4 LBT wait (see Gnb.rrc_uplink_delay()),
    # so its attach is never faster than licensed NR's at matching
    # defaults. Only read when a UE has rrc_enabled=True.
    rrc_ul_grant_delay_us: float = 1000.0
    # Rashed-Step 16.A-10-02-2026-end

    # Rashed-Step 17.B-10-04-2026-start
    # How UEs with uplink_enabled=True access the channel - see
    # NruUplinkAccessMode.
    # Rashed-Step 17.E-10-04-2026-start
    # Default flipped from AUTONOMOUS to COT_SHARING now that it works
    # (Rashed's decision 1, 2026-10-04). Only changes runs with NR-U
    # uplink on: the gNB opens uplink windows only for uplink-capable
    # UEs, so every other run is unaffected.
    ul_access_mode: NruUplinkAccessMode = NruUplinkAccessMode.COT_SHARING
    # Rashed-Step 17.E-10-04-2026-end
    # COT_SHARING only: share of the gNB's COT (mcot) granted to its UEs
    # for uplink, after the downlink part. Fixed fraction, default 50/50
    # (Rashed's decision, 2026-10-04). Must be strictly between 0 and 1 -
    # checked in __post_init__ below.
    ul_cot_fraction: float = 0.5
    # Rashed-Step 17.D-10-04-2026-start
    # COT_SHARING only: Type 2A LBT - a UE granted uplink inside its
    # gNB's COT checks that the channel is idle for this long (a 16us
    # gap + one 9us sensing slot = 25us, 3GPP TS 37.213) and then sends,
    # instead of running full Cat-4. See NrUE.type2a_lbt().
    ul_type2a_sense_us: float = 25.0
    # Rashed-Step 19.B.1-10-07-2026-start
    # COT sharing: after this many failed Type 2A checks in a row for one
    # RRC message, the UE stops waiting for its gNB's COTs and sends it
    # after its own Type 1 (Cat-4) LBT instead - a hidden Wi-Fi node
    # can otherwise fail the check for every COT (Step 17.H: 33 tries,
    # ~212 ms). None (default) = never fall back.
    rrc_type1_fallback_after: Optional[int] = None
    # Rashed-Step 19.B.1-10-07-2026-end
    # Rashed-Step 17.D-10-04-2026-end

    # Rashed-Step 18.C-10-06-2026-start
    # How a COT's downlink carries data.
    #   "burst" (default): the whole downlink part is one transmission
    #     carrying one packet, judged by one SINR at the configured MCS -
    #     byte-identical to every earlier run.
    #   "slots": the downlink part is a run of NR slots (numerology
    #     below). Each slot carries one transport block for the COT's UE,
    #     sized MCS efficiency x RBs x slot time (nr/nr.py's tables), with
    #     its own SINR over that slot. The MCS comes from the UE's last
    #     reported SINR (CQI); its first slot uses the interference-free
    #     SINR. Data comes from per-UE byte buffers (refilled on demand
    #     for saturated traffic). The first slot is the TS 37.213
    #     reference slot: if it fails, the contention window doubles.
    #     mcs / rate_adapt_enabled / nru_sinr_thr_db_override only apply
    #     to "burst".
    cot_model: str = "burst"
    numerology: int = 1  # mu; 30 kHz SCS, the usual NR-U choice at 5 GHz
    # Drop-tail limit of each per-UE buffer in "slots"; None = unbounded.
    buffer_limit_bytes: Optional[int] = None
    # Rashed-Step 18.C-10-06-2026-end
    # Rashed-Step 18.D-10-06-2026-start
    # "slots" + COT sharing: uplink traffic per UE. None (default) =
    # saturated (each UE's uplink buffer is refilled on demand); a
    # TrafficConfig (poisson/cbr) = arrivals into each UE's buffer at
    # arrival_rate_pps per UE.
    ul_traffic: Optional[TrafficConfig] = None
    # Rashed-Step 18.D-10-06-2026-end
    # Rashed-Step 18.E-10-06-2026-start
    # HARQ in "slots" (ran/protocol/harq.py), both directions. None
    # (default) = a failed TB's packets are dropped.
    harq: Optional[HarqConfig] = None
    # Rashed-Step 18.F-10-06-2026-start
    # PDCP + RLC (ran/protocol/l2.py) in "slots", both directions.
    # None (default) = no L2 headers / ARQ / reordering.
    l2: Optional[L2Config] = None
    # Rashed-Step 19.A-10-07-2026-start
    # 4-step random access before RRC (ran/protocol/rach.py), with LBT
    # before Msg1 and the RAR riding a gNB COT. None (default) = off.
    rach: Optional[RachConfig] = None
    # Rashed-Step 19.B.2-10-07-2026-start
    # Radio link monitoring + RLF + re-establishment for RRC UEs
    # (ran/protocol/rlm.py). None (default) = off.
    rlm: Optional[RlmConfig] = None
    # Rashed-Step 19.B.3-10-07-2026-start
    # RRC_INACTIVE with resume (ran/protocol/inactive.py) for RRC UEs.
    # Needs cot_model "slots" (per-UE buffers). None (default) = off.
    inactive: Optional[InactiveConfig] = None
    # Rashed-Step 19.B.4-10-07-2026-start
    # RRCReconfiguration (data radio bearer setup) after each PDU session
    # and after a re-establishment: UE processing time in us. None
    # (default) = no reconfiguration step.
    rrc_reconfig_us: Optional[float] = None
    # Rashed-Step 19.C-10-07-2026-start
    # One DRB per QoS flow / 5QI in each "slots" buffer, served in 5QI
    # priority order; uplink packets then take their class from the
    # same traffic_class_mix as downlink. Needs "slots". False (default)
    # = one buffer per UE and direction.
    qos_flows: bool = False
    # Rashed-Step 19.C-10-07-2026-end
    # Rashed-Step pre_20.D.1-10-08-2026-start
    # TS 37.213 channel access priority class (pre_20.D.1): 1-4 sets
    # M, cw_min, cw_max and mcot from CAPC_DL (ran/protocol/
    # channel_access.py), overriding whatever was passed for them; UEs
    # running their own Type 1 LBT take the uplink table (CAPC_UL).
    # None (default) = the fields as given (M=3, CW 15-63 = class 3 with
    # the ETSI 6 ms MCOT), byte-identical to every earlier run.
    priority_class: Optional[int] = None
    # Rashed-Step pre_20.D.2-10-08-2026-start
    # Energy-detection threshold rule (pre_20.D.2): "ts37213" sets
    # ed_threshold_dbm from TS 37.213 clause 4.1.5 (tx_power_dbm,
    # bandwidth_mhz, ed_t_a_db) - see channel_access.
    # ts37213_ed_threshold_dbm. None (default) = ed_threshold_dbm as
    # given (-72 dBm), byte-identical.
    ed_threshold_mode: Optional[str] = None
    ed_t_a_db: float = 10.0
    # Rashed-Step pre_20.D.2-10-08-2026-end
    # Rashed-Step pre_20.D.1-10-08-2026-end
    # Rashed-Step 19.B.4-10-07-2026-end
    # Rashed-Step 19.B.3-10-07-2026-end
    # Rashed-Step 19.B.2-10-07-2026-end
    # Rashed-Step 19.A-10-07-2026-end
    # Rashed-Step 18.F-10-06-2026-end
    # Rashed-Step 18.E-10-06-2026-end

    def __post_init__(self):
        # Rashed-Step 18.C-10-06-2026-start
        if self.cot_model not in COT_MODELS:
            raise ValueError(f"Config_NR.cot_model must be one of {COT_MODELS} (got {self.cot_model!r})")
        if self.numerology not in NUMEROLOGY_SCS_KHZ:
            raise ValueError(f"Config_NR.numerology must be one of {sorted(NUMEROLOGY_SCS_KHZ)} (got {self.numerology})")
        # Rashed-Step 18.E-10-06-2026-start
        if self.harq is not None and self.cot_model != "slots":
            raise ValueError("Config_NR.harq needs cot_model=\"slots\" (the burst model has no transport blocks).")
        # Rashed-Step 18.F-10-06-2026-start
        if self.l2 is not None and self.cot_model != "slots":
            raise ValueError("Config_NR.l2 needs cot_model=\"slots\" (the burst model has no transport blocks).")
        # Rashed-Step 19.B.1-10-07-2026-start
        # Rashed-Step 19.B.3-10-07-2026-start
        # Rashed-Step 19.C-10-07-2026-start
        if self.qos_flows and self.cot_model != "slots":
            raise ValueError("Config_NR.qos_flows needs cot_model=\"slots\" (per-UE buffers).")
        # Rashed-Step 19.C-10-07-2026-end
        if self.inactive is not None and self.cot_model != "slots":
            raise ValueError("Config_NR.inactive needs cot_model=\"slots\" (per-UE buffers).")
        # Rashed-Step 19.B.3-10-07-2026-end
        if self.rrc_type1_fallback_after is not None and self.rrc_type1_fallback_after < 1:
            raise ValueError(f"Config_NR.rrc_type1_fallback_after must be >= 1 (got {self.rrc_type1_fallback_after})")
        # Rashed-Step 19.B.1-10-07-2026-end
        # Rashed-Step 18.F-10-06-2026-end
        # Rashed-Step 18.E-10-06-2026-end
        # Rashed-Step 18.C-10-06-2026-end
        # Rashed-Step pre_20.D.1-10-08-2026-start
        if self.priority_class is not None:
            if self.priority_class not in CAPC_DL:
                raise ValueError(f"Config_NR.priority_class must be 1-4 (got {self.priority_class})")
            self.M, self.cw_min, self.cw_max, self.mcot = CAPC_DL[self.priority_class]
        # Rashed-Step pre_20.D.1-10-08-2026-end
        # Rashed-Step pre_20.D.2-10-08-2026-start
        if self.ed_threshold_mode is not None:
            if self.ed_threshold_mode != "ts37213":
                raise ValueError(f"Config_NR.ed_threshold_mode must be None or 'ts37213' (got {self.ed_threshold_mode!r})")
            self.ed_threshold_dbm = ts37213_ed_threshold_dbm(self.tx_power_dbm, self.bandwidth_mhz, self.ed_t_a_db)
        # Rashed-Step pre_20.D.2-10-08-2026-end
        if not (0.0 < self.ul_cot_fraction < 1.0):
            raise ValueError(
                f"Config_NR.ul_cot_fraction must be strictly between 0 and 1 "
                f"(got {self.ul_cot_fraction}) - the COT needs both a "
                f"downlink and an uplink part."
            )
    # Rashed-Step 17.B-10-04-2026-end



@dataclass()
class Transmission_NR:
    transmission_time: int
    gnb_name: str  # name of the owning it station
    col: str
    t_start: int  # generation time / transmision start (including RS)
    airtime: int  # time spent on sending data
    rs_time: int  # time spent on sending reservation signal before data
    number_of_retransmissions: int = 0
    t_end: int = None  # sent time / transsmision end = start + rs_time + airtime
    t_to_send: int = None
    collided: bool = False  # true if transmission colided with another one

    # Rashed-Step 2.B_2-12-30-2025-start
    tx_pos: Pos = None
    rx_name: str = None
    rx_pos: Pos = None
    distance_m: float = None
    pr_dbm: float = None
    # Rashed-Step 2.B_2-12-30-2025-end
    # Rashed-Step 5.G-02-06-2026-start
    # Reference to the actual chosen NrUE object (not just a position
    # snapshot) - gen_new_transmission() does random.choice(self.ue_list)
    # to pick which UE this transmission targets; send_transmission()
    # needs to re-read *that same UE's* current_pos() after potentially
    # waiting on tx_queue_nru, not fall back to an arbitrary/first UE.
    rx_ue: Optional[Any] = None
    # Rashed-Step 5.G-02-06-2026-end

    # Rashed-Step 8.A-08-06-2026-start
    # Same optional Packet reference as wifi.Frame - see common/packet.py
    # and "Project details/Step 8.txt" for the rationale. None by
    # default; Step 8.B is what actually populates it.
    packet: Optional[Packet] = None
    # Rashed-Step 8.A-08-06-2026-end





class Gnb:
    def __init__(
            self,
            env: simpy.Environment,
            name: str,
            channel: dataclass,
            # Rashed-Step 1.C_2-12-26-2025-start
            pos: Pos,
            ue_list: list,
            # Rashed-Step 1.C_2-12-26-2025-end
            config_nr: Config_NR,
            # Rashed-Step 5.G-02-06-2026-start
            mobility: Optional[Any] = None,
            # Rashed-Step 5.G-02-06-2026-end
            # Rashed-Step 8.B-08-06-2026-start
            # Same contract as wifi.WiFi's traffic_config - None
            # (default) normalizes to TrafficConfig(mode="saturated"),
            # byte-identical to every pre-Step-8.B run.
            traffic_config: Optional[TrafficConfig] = None
            # Rashed-Step 8.B-08-06-2026-end
    ):
        self.config_nr = config_nr
        # self.times = Times(config.data_size, config.mcs)  # using Times script to get time calculations
        # Rashed-Step 11.B-08-21-2026-start
        # Per-UE rate-adaptation state (see Config_NR.rate_adapt_enabled).
        # Keyed by UE name, lazily populated on first use - empty dict
        # costs nothing when rate adaptation is disabled (the default).
        self.link_rate_state: Dict[str, Dict[str, Optional[float]]] = {}
        # Rashed-Step 11.B-08-21-2026-end
        self.name = name  # name of the station
        self.env = env  # simpy environment
        # color of output -- for future station distinction
        self.col = random.choice(colors)
        self.transmission_to_send = None  # the transmision object which is next to send
        self.succeeded_transmissions = 0  # all succeeded transmissions for station
        self.failed_transmissions = 0  # all failed transmissions for station
        # all failed transmissions for station in a row
        self.failed_transmissions_in_row = 0
        self.cw_min = config_nr.cw_min  # cw min parameter value
        self.N = None  # backoff counter
        self.desync = 0
        self.next_sync_slot_boundry = 0
        self.cw_max = config_nr.cw_max  # cw max parameter value
        self.channel = channel  # channel objfirst_transmission

        # Rashed-Step 8.B-08-06-2026-start
        # Same queue/arrival-process pattern as wifi.WiFi - see that
        # class's __init__ comment for the full rationale. Saturated
        # mode (default) never touches packet_queue at all.
        self.traffic_config = traffic_config if traffic_config is not None else TrafficConfig(mode="saturated")
        self.packet_queue = simpy.Store(env)
        self._packet_seq = 0
        if self.traffic_config.mode != "saturated" and config_nr.cot_model != "slots":
            env.process(self._traffic_generator())
        # Rashed-Step 8.B-08-06-2026-end

        # Rashed-Step 8.D-08-06-2026-start
        # The packet currently "in flight" for this episode (set at the
        # top of start()'s outer loop, re-read fresh by start()'s inner
        # retry loop every attempt, instead of a stale local `packet`
        # variable captured once per episode). When the retry limit is
        # exceeded, start()'s inner loop (see Step 8.E below) replaces
        # this with a fresh packet before the next attempt.
        self.current_packet = None
        # Rashed-Step 8.D-08-06-2026-end
        # Rashed-Step 8.E-08-06-2026-start
        # Same deferred-replacement flag as wifi.WiFi - see that class's
        # __init__ comment and sent_failed() for the full rationale
        # (avoids blocking mid-transmission-teardown; the actual queue
        # wait happens in start()'s inner retry loop instead).
        self._need_new_packet = False
        # Rashed-Step 8.E-08-06-2026-end

        # Rashed-Step 8.G-08-06-2026-start
        # Every DATA packet this gNB has finished with (DELIVERED or
        # DROPPED - never PENDING), appended by sent_completed()/
        # sent_failed(). See wifi.WiFi's matching field for the full
        # rationale - feeds common.packet.compute_packet_stats().
        self.packet_log = []
        # Rashed-Step 8.G-08-06-2026-end
        # Rashed-Step 17.C-10-04-2026-start
        # Every uplink window this gNB opened inside its COT (COT_SHARING
        # only): {"start", "end", "ues"}. Stays empty otherwise.
        self.ul_windows = []
        # Rashed-Step 17.C-10-04-2026-end
        # Rashed-Step 17.E-10-04-2026-start
        # Round-robin pointer over eligible UEs for uplink-window grants.
        self._ul_rr = 0
        # Rashed-Step 17.E-10-04-2026-end
        # Rashed-Step 17.F-10-04-2026-start
        # Fired (and replaced) at the end of every successful downlink in
        # COT_SHARING mode - what a UE's RRC message waits on for its
        # grant (see rrc_uplink_delay()). Never fired in AUTONOMOUS mode.
        self._dl_cot_done = env.event()
        # Rashed-Step 17.F-10-04-2026-end

        # Rashed-Step 15.A-09-18-2026-start
        # Shared, stateless Cat-4 LBT strategy (see ran/protocol/
        # channel_access.py) - wait_back_off_gap_after() below now
        # delegates to it instead of running the algorithm inline, so
        # 15.C's NrUE can reuse the exact same implementation for its
        # own uplink LBT. Zero behavior change: same code, just moved.
        self._channel_access = LbtChannelAccess()
        # Rashed-Step 15.A-09-18-2026-end

        # Rashed-Step 15.F-09-18-2026-start
        # Shared, stateless RRC attach driver (see ran/protocol/rrc.py)
        # - cheap to construct unconditionally, only actually used for
        # UEs that opt into rrc_enabled (see the back-reference loop
        # below).
        self._rrc_layer = RrcLayer()
        # Rashed-Step 15.F-09-18-2026-end

        # Rashed-Step 18.C-10-06-2026-start
        self._rrc_ul_waiters = 0
        # Rashed-Step 19.A-10-07-2026-start
        # Rashed-Step 19.B.2-10-07-2026-start
        self.rlm_config = config_nr.rlm
        # Rashed-Step 19.B.3-10-07-2026-start
        self.inactive_config = config_nr.inactive
        # Rashed-Step 19.B.4-10-07-2026-start
        self.rrc_reconfig_us = config_nr.rrc_reconfig_us
        # Rashed-Step 19.B.4-10-07-2026-end
        # Rashed-Step 19.B.3-10-07-2026-end
        # Rashed-Step 19.B.2-10-07-2026-end
        self.rach_cell = None
        if config_nr.rach is not None:
            self.rach_cell = RachCell(self, config_nr.rach, ue_max_power_dbm=config_nr.tx_power_dbm,
                                      f_hz=config_nr.f_ghz, pl_exp=config_nr.pl_exp,
                                      scs_khz=NUMEROLOGY_SCS_KHZ[config_nr.numerology],
                                      noise_figure_db=config_nr.noise_figure_db, lbt=True)
        # Rashed-Step 19.A-10-07-2026-end
        if config_nr.cot_model == "slots":
            self.ue_list = ue_list  # (also set again below)
            self._init_slot_model()
        # Rashed-Step 18.C-10-06-2026-end

        env.process(self.start())  # starting simulation process
        env.process(self.sync_slot_counter())
        self.process = None  # waiting back off process
        self.channel.airtime_data_NR.update({name: 0})
        self.channel.airtime_control_NR.update({name: 0})
        self.desync_done = False
        self.first_interrupt = False
        self.back_off_time = 0
        self.time_to_next_sync_slot = 0
        self.waiting_backoff = False
        self.start_nr = 0
        


        # Rashed-Step 1.C_2-12-26-2025-start
        self.pos = pos
        self.ue_list = ue_list
        # Rashed-Step 1.C_2-12-26-2025-end
        # Rashed-Step 15.D-09-18-2026-start
        # Surfaced onto self for visibility/future use (e.g. a later
        # sub-step's scheduler/RRC orchestration reading it directly off
        # the gNB) - no branching on it here, since Gnb's existing
        # downlink LBT behavior is already correct for both
        # STANDALONE_MULTIFIRE and (eventually) LAA_ANCHORED's downlink
        # side (real LAA's DL is Cat-4-LBT-gated too, same as
        # MultiFire's - the two modes only actually differ on uplink).
        self.deployment_mode = config_nr.deployment_mode
        # Rashed-Step 15.D-09-18-2026-end
        # Rashed-Step 15.C-09-18-2026-start
        # Back-reference each associated UE to this gNB object, mirroring
        # wifi.WiFi.__init__'s sta.ap = self (Step 15.B) - a UE whose
        # uplink_enabled=True (see nru/ue.py's NrUE) can then compute a
        # real rx_pos/sinr target and read this gNB's live
        # next_sync_slot_boundry for its own LBT gap-wait, without this
        # simulator needing a second, independent per-UE sync process.
        # No-op for every UE that doesn't use uplink, i.e. byte-identical
        # to every pre-15.C run.
        for ue in self.ue_list:
            ue.gnb = self
            # Rashed-Step 15.F-09-18-2026-start
            # Kick off the RRC attach procedure for any UE that opted
            # in (see ran/protocol/rrc.py's module docstring's SCOPE -
            # requires uplink_enabled=True too, validated in NrUE.
            # __post_init__). Started here, not in NrUE's own
            # __post_init__, because attach() needs ue.gnb (just set
            # above) and this gNB's own rrc_uplink_delay() - neither
            # exists yet at UE-construction time (every simulation*.py
            # caller still builds UEs BEFORE the gNB that owns them).
            # No-op for every UE that doesn't use rrc_enabled.
            if getattr(ue, "rrc_enabled", False):
                env.process(self._rrc_layer.attach(self, ue))
            # Rashed-Step 15.F-09-18-2026-end
        # Rashed-Step 15.C-09-18-2026-end
        # Rashed-Step 5.G-02-06-2026-start
        self.mobility = mobility
        # Rashed-Step 5.G-02-06-2026-end
        # Rashed-Step 4.C_2-01-21-2026-start
        self.sinr_print_ctr = 0
        # Rashed-Step 4.C_2-01-21-2026-end

    # Rashed-Step 5.G-02-06-2026-start
    def current_pos(self) -> Pos:
        """See wifi.WiFi.current_pos() - same idea for gNBs."""
        return self.mobility.pos_now() if self.mobility is not None else self.pos
    # Rashed-Step 5.G-02-06-2026-end

    # Rashed-Step 8.B-08-06-2026-start
    def _make_packet(self) -> Packet:
        """
        Synthesize a fresh Packet - see wifi.WiFi._make_packet() for the
        general rationale. NR-U has no existing payload-size concept at
        all (Transmission_NR's duration is governed purely by
        config_nr.mcot, not by any byte count - deliberately NOT
        changed here, see "Project details/Step 8.txt"), so
        payload_bytes/header_bytes here are standalone values with
        nothing downstream reading them yet: payload defaults to 1500
        (a generic MTU-sized placeholder, distinct from WiFi's 1472 to
        avoid implying a shared/derived value) unless
        traffic_config.packet_size_bytes overrides it; header_bytes is
        0 (no NR-U-specific MAC/RLC/PDCP header-size model exists yet).
        """
        self._packet_seq += 1
        payload = self.traffic_config.packet_size_bytes if self.traffic_config.packet_size_bytes is not None else 1500
        destination = self.ue_list[0].name if self.ue_list else self.name
        # Rashed-Step 10.A-08-07-2026-start
        # See wifi.WiFi._make_packet()'s identical comment - None
        # (default) means no random draw at all, plain "best_effort".
        if self.traffic_config.traffic_class_mix is not None:
            traffic_class = pick_traffic_class(self.traffic_config.traffic_class_mix)
        else:
            traffic_class = "best_effort"
        # Rashed-Step 10.A-08-07-2026-end
        return Packet(
            packet_id=f"{self.name}-{self._packet_seq:06d}",
            source=self.name,
            destination=destination,
            payload_bytes=payload,
            header_bytes=0,
            created_at=self.env.now,
            # Rashed-Step 10.A-08-07-2026-start
            traffic_class=traffic_class,
            # Rashed-Step 10.A-08-07-2026-end
        )

    def _next_packet(self):
        """See wifi.WiFi._next_packet() - identical contract."""
        if self.traffic_config.mode == "saturated":
            return self._make_packet()
        pkt = yield self.packet_queue.get()
        return pkt

    def _traffic_generator(self):
        """See wifi.WiFi._traffic_generator() - identical contract."""
        while True:
            if self.traffic_config.mode == "poisson":
                interval_us = random.expovariate(self.traffic_config.arrival_rate_pps / 1e6)
            else:  # "cbr"
                interval_us = 1e6 / self.traffic_config.arrival_rate_pps
            yield self.env.timeout(interval_us)
            yield self.packet_queue.put(self._make_packet())
    # Rashed-Step 8.B-08-06-2026-end

    def start(self):
        # Rashed-Step 18.C-10-06-2026-start
        if self.config_nr.cot_model == "slots":
            yield from self._start_slots()
            return
        # Rashed-Step 18.C-10-06-2026-end
        # Rashed-Step 3.F-12-26-2025-start
        #print(self.env.now, self.name, "START LOOP")
        # Rashed-Step 3.F-12-26-2025-end

        # yield self.env.timeout(self.desync)
        while True:
            # Rashed-Step 8.B-08-06-2026-start
            # UPGRADE: obtain one Packet per "episode" (this outer loop
            # pass, covering the first attempt AND every retry within
            # it) instead of gen_new_transmission() always synthesizing
            # an unrelated fresh one on every single attempt (including
            # retries) as it silently did before. In saturated mode
            # (the default) this is still a same-tick, non-blocking
            # call - zero timing change. In poisson/cbr mode this gNB
            # now genuinely waits here when it has nothing queued,
            # instead of continuously contending for the channel with
            # phantom always-ready transmissions. gen_new_transmission()
            # itself (called fresh every attempt, from inside
            # send_transmission() - unchanged) now takes this same
            # packet reference each time instead of manufacturing its
            # own, so - as a side effect - a retried transmission is now
            # actually carrying the SAME logical packet across retries,
            # which it never did before (a real (if incidental)
            # improvement, not just packet bookkeeping).
            packet = yield from self._next_packet()
            # Rashed-Step 8.D-08-06-2026-start
            # Stashed on self (not just the local `packet` var) so a
            # mid-episode replacement (see Step 8.E below) is picked up
            # immediately on the very next retry - the inner loop reads
            # self.current_packet fresh every attempt instead of the
            # stale `packet` local.
            self.current_packet = packet
            # Rashed-Step 8.D-08-06-2026-end
            # Rashed-Step 8.B-08-06-2026-end
            was_sent = False
            while not was_sent:
                # Rashed-Step 8.E-08-06-2026-start
                # sent_failed() sets self._need_new_packet instead of
                # synthesizing a replacement directly (see its comment
                # for why - avoids blocking mid-teardown of the attempt
                # that just failed). Checked at the top of every retry:
                # saturated mode returns instantly (no change), poisson/
                # cbr mode genuinely waits here for the queue, AFTER
                # send_transmission()'s previous call has already fully
                # finished its own bookkeeping.
                if self._need_new_packet:
                    self.current_packet = yield from self._next_packet()
                    self._need_new_packet = False
                # Rashed-Step 8.E-08-06-2026-end
                if gap:
                    # Rashed-Step 3.E_2-01-12-2026-start
                    #self.process = self.env.process(self.wait_back_off_gap())
                    self.process = self.env.process(self.wait_back_off_gap_after())
                    # Rashed-Step 3.E_2-01-12-2026-end
                    yield self.process
                    was_sent = yield self.env.process(self.send_transmission(self.current_packet))
                else:
                    self.process = self.env.process(self.wait_back_off())
                    yield self.process
                    was_sent = yield self.env.process(self.send_transmission())

    # Rashed-Step 3.E_2-01-12-2026-start

    # Rashed-Step 15.A-09-18-2026-start
    # UPGRADE (pure refactor, zero behavior change): this method's body
    # used to run the Cat-4 LBT algorithm inline - it's now delegated to
    # ran.protocol.channel_access.LbtChannelAccess.wait(), a parametrized
    # move of the exact same code (see that module's docstring for the
    # full rationale and the real-world scope discovery made while
    # building this). Gnb satisfies LbtChannelAccess.wait()'s duck-typed
    # contract already (env/channel/current_pos()/name/config_nr/
    # failed_transmissions_in_row/next_sync_slot_boundry/cw_min/cw_max
    # all already exist on self), so this is a one-line delegation, not
    # a rewrite - same yields, same order, same simulated timing.
    # Rashed-Step 18.C-10-06-2026-start
    # Rashed-Step 18.D-10-06-2026-start
    # ------------------------------------------------------------------
    # "slots" COT model (Config_NR.cot_model) - see that field's comment.
    # 18.C built it for one UE per COT; 18.D shares each downlink slot
    # among the cell's UEs (resource blocks split max-min fair) and turns
    # the COT-sharing uplink window into slots shared by several UEs on
    # separate interlaces.
    # ------------------------------------------------------------------
    def _init_slot_model(self):
        cfg = self.config_nr
        self.slot_us = slot_duration_us(cfg.numerology)
        self.scs_khz = NUMEROLOGY_SCS_KHZ[cfg.numerology]
        self.total_rbs = resource_block_count(cfg.bandwidth_mhz, self.scs_khz)
        self.rb_bandwidth_hz = 12 * self.scs_khz * 1000.0
        # Uplink interlaces (TS 38.211 4.4.4.6): 10 at 15 kHz, 5 at 30 kHz.
        self.n_interlaces = NRU_UL_INTERLACES.get(cfg.numerology, 5)
        self._cqi_db = {}
        self._ul_cqi_db = {}
        # Rashed-Step 18.E-10-06-2026-start
        self._harq_entities = {}
        # Rashed-Step 18.F-10-06-2026-start
        self._harq_cfg = cfg.harq if cfg.harq is not None else (HarqConfig(max_tx=1) if cfg.l2 else None)
        # Rashed-Step 18.F-10-06-2026-end
        # Rashed-Step 18.E-10-06-2026-end
        self._slots_kick = self.env.event()
        self.slot_stats = {"cots": 0, "cots_failed": 0, "control_only_cots": 0,
                           "dl_tbs_ok": 0, "dl_tbs_failed": 0, "dl_bits": 0, "dl_mcs_sum": 0,
                           "ul_tbs_ok": 0, "ul_tbs_failed": 0, "ul_bits": 0, "ul_mcs_sum": 0,
                           "ul_grants": 0, "ul_type2a_skips": 0}
        self.dl_buffers = {}
        saturated = self.traffic_config.mode == "saturated"
        for ue in self.ue_list:
            # Rashed-Step 18.F-10-06-2026-start
            buf = make_buffer(cfg.buffer_limit_bytes, on_enqueue=self._kick_slots, l2=cfg.l2, qos=cfg.qos_flows)  # 19.C qos
            # Rashed-Step 18.F-10-06-2026-end
            self.dl_buffers[ue.name] = buf
            if not saturated and self.ue_list:
                # --nru-arrival-rate-pps stays a per-gNB total, split over its UEs.
                per_ue = TrafficConfig(mode=self.traffic_config.mode,
                                       arrival_rate_pps=self.traffic_config.arrival_rate_pps / len(self.ue_list),
                                       packet_size_bytes=self.traffic_config.packet_size_bytes,
                                       traffic_class_mix=self.traffic_config.traffic_class_mix)
                self.env.process(arrival_process(self.env, buf, per_ue,
                                                 lambda n=ue.name: self._make_dl_packet(n),
                                                 random.expovariate))
            # Uplink buffer at each uplink UE (COT sharing only; autonomous
            # uplink keeps its own one-packet path).
            if (getattr(ue, "uplink_enabled", False)
                    and cfg.ul_access_mode is NruUplinkAccessMode.COT_SHARING):
                # Rashed-Step 18.F-10-06-2026-start
                ue.ul_buffer = make_buffer(cfg.buffer_limit_bytes, on_enqueue=self._kick_slots, l2=cfg.l2, qos=cfg.qos_flows)  # 19.C qos
                # Rashed-Step 18.F-10-06-2026-end
                if cfg.ul_traffic is not None:
                    self.env.process(arrival_process(self.env, ue.ul_buffer, cfg.ul_traffic,
                                                     lambda n=ue.name: self._make_ul_packet(n),
                                                     random.expovariate))

    def _kick_slots(self):
        if not self._slots_kick.triggered:
            self._slots_kick.succeed()

    def _make_dl_packet(self, ue_name: str) -> Packet:
        """A downlink packet for one UE's buffer (same size/class rules as
        _make_packet())."""
        self._packet_seq += 1
        payload = self.traffic_config.packet_size_bytes if self.traffic_config.packet_size_bytes is not None else 1500
        if self.traffic_config.traffic_class_mix is not None:
            traffic_class = pick_traffic_class(self.traffic_config.traffic_class_mix)
        else:
            traffic_class = "best_effort"
        return Packet(
            packet_id=f"{self.name}-{self._packet_seq:06d}",
            source=self.name,
            destination=ue_name,
            payload_bytes=payload,
            header_bytes=0,
            created_at=self.env.now,
            traffic_class=traffic_class,
        )

    def _make_ul_packet(self, ue_name: str) -> Packet:
        ul = self.config_nr.ul_traffic
        size = ul.packet_size_bytes if ul is not None and ul.packet_size_bytes is not None else 1500
        self._packet_seq += 1
        return Packet(
            packet_id=f"{ue_name}-UL-{self._packet_seq:06d}",
            source=ue_name,
            destination=self.name,
            payload_bytes=size,
            header_bytes=0,
            created_at=self.env.now,
            # Rashed-Step 19.C-10-07-2026-start
            traffic_class=(pick_traffic_class(self.traffic_config.traffic_class_mix)
                           if self.config_nr.qos_flows and self.traffic_config.traffic_class_mix else "best_effort"),
            # Rashed-Step 19.C-10-07-2026-end
        )

    def _eligible_dl_ues(self) -> list:
        return [
            ue for ue in self.ue_list
            if getattr(ue, "rrc_state", RrcState.CONNECTED) is RrcState.CONNECTED
            and user_plane_allows(ue)
        ]

    def _dl_slot_ues(self) -> list:
        """UEs with downlink data (every eligible UE for saturated traffic)."""
        ues = self._eligible_dl_ues()
        # Rashed-Step 19.F-10-07-2026-start
        # Saturated traffic is this gNB's own; SCell legs (19.F) only carry
        # what is queued in their licensed UE's buffer.
        ues = [ue for ue in ues if self._own_saturated(ue)
               or self._link_has_data(self.dl_buffers[ue.name])]
        # Rashed-Step 19.F-10-07-2026-end
        return ues

    # Rashed-Step 19.F-10-07-2026-start
    def _own_saturated(self, ue) -> bool:
        return self.traffic_config.mode == "saturated" and getattr(ue, "scell_of", None) is None
    # Rashed-Step 19.F-10-07-2026-end

    def _ul_slot_ues(self) -> list:
        """COT-sharing UEs with uplink data (every one for saturated)."""
        ues = [ue for ue in self._cot_ul_ues() if getattr(ue, "ul_buffer", None) is not None]
        if self.config_nr.ul_traffic is not None:
            # Rashed-Step 18.E-10-06-2026-start
            ues = [ue for ue in ues if self._link_has_data(ue.ul_buffer)]
            # Rashed-Step 18.E-10-06-2026-end
        return ues

    def _slots_have_work(self) -> bool:
        if self.traffic_config.mode == "saturated":
            return True  # contends every time, like the burst model
        if self._dl_slot_ues() or self._ul_slot_ues():
            return True
        # A UE waiting to send an RRC message needs a COT too.
        return self._rrc_ul_waiters > 0

    def _start_slots(self):
        while True:
            # Sleep until there's work; re-check every sync slot too, since
            # RRC/Core state changes don't kick (cheap, and only while idle).
            while not self._slots_have_work():
                self._slots_kick = self.env.event()
                yield self._slots_kick | self.env.timeout(self.config_nr.synchronization_slot_duration)
            if gap:
                self.process = self.env.process(self.wait_back_off_gap_after())
            else:
                self.process = self.env.process(self.wait_back_off())
            yield self.process
            yield self.env.process(self._send_cot_slots())

    def _slot_mcs(self, ue, ul: bool = False) -> int:
        """MCS for this UE's next transport block from its last measured
        SINR in that direction (CQI for downlink, the gNB's own measurement
        for uplink); before any, the interference-free SINR. MCS 0 when even
        that is below MCS 0's threshold."""
        sinr = (self._ul_cqi_db if ul else self._cqi_db).get(ue.name)
        if sinr is None:
            a, b = (ue.current_pos(), self.current_pos()) if ul else (self.current_pos(), ue.current_pos())
            trial = ActiveTx(tx_id=ue.name if ul else self.name, tx_pos=a, tx_start=self.env.now,
                             rx_pos=b, tx_power_dbm=self.config_nr.tx_power_dbm,
                             f_hz=self.config_nr.f_ghz, pl_exp=self.config_nr.pl_exp,
                             t_end=self.env.now + self.slot_us, tech="NRU",
                             bandwidth_mhz=self.config_nr.bandwidth_mhz,
                             noise_figure_db=self.config_nr.noise_figure_db)
            sinr = (self.channel._rx_pwr_dbm(trial, trial.rx_pos)
                    - thermal_noise_dbm(self.config_nr.bandwidth_mhz, self.config_nr.noise_figure_db))
        mcs = select_mcs_for_sinr(sinr)
        return 0 if mcs is None else mcs

    def _tb_bytes(self, mcs: int, duration_us: float, rbs: Optional[int] = None) -> int:
        rbs = self.total_rbs if rbs is None else rbs
        bits = NR_MCS_TABLE[mcs][1] * (rbs * self.rb_bandwidth_hz) * (duration_us / 1e6)
        return int(bits // 8)

    def _rbs_needed(self, backlog_bytes: int, mcs: int, duration_us: float) -> int:
        per_rb = max(1, self._tb_bytes(mcs, duration_us, 1))
        return max(1, -(-backlog_bytes // per_rb))

    @staticmethod
    def _maxmin_rbs(total: int, needs: dict) -> dict:
        """Split `total` RBs max-min fair: smallest need first, nobody gets
        more than it needs or more than an equal share of what's left."""
        out = {}
        remaining = total
        order = sorted(needs, key=lambda k: needs[k])
        for i, name in enumerate(order):
            give = min(needs[name], remaining // (len(order) - i))
            out[name] = give
            remaining -= give
        return out

    def _dl_slot_alloc(self, ues: list, duration_us: float, saturated: bool) -> dict:
        needs = {}
        for ue in ues:
            # Rashed-Step 18.E-10-06-2026-start
            due = self._due_retx(self.dl_buffers[ue.name])
            if due is not None:
                needs[ue.name] = due.rbs
                continue
            # Rashed-Step 18.E-10-06-2026-end
            if saturated and getattr(ue, "scell_of", None) is None:  # 19.F: legs are buffered
                needs[ue.name] = self.total_rbs
            else:
                needs[ue.name] = self._rbs_needed(self.dl_buffers[ue.name].backlog_bytes,
                                                  self._slot_mcs(ue), duration_us)
        # Rashed-Step pre_19.F-10-07-2026-start
        # Due HARQ retransmissions get their RBs first (oldest need first);
        # the rest are split max-min among the others. Before this, a
        # retransmission cut below its original RBs by the max-min split
        # could never go out, and once all HARQ processes held such TBs
        # the UE got no new data either.
        retx = {ue.name: needs[ue.name] for ue in ues
                if self._due_retx(self.dl_buffers[ue.name]) is not None}
        if not retx:
            return self._maxmin_rbs(self.total_rbs, needs)
        out, remaining = {}, self.total_rbs
        for name, need in retx.items():
            out[name] = min(need, remaining)
            remaining -= out[name]
        rest = {k: v for k, v in needs.items() if k not in retx}
        out.update(self._maxmin_rbs(remaining, rest) if rest else {})
        return out
        # Rashed-Step pre_19.F-10-07-2026-end

    def _send_cot_slots(self):
        """One COT under the "slots" model: optional reservation signal,
        downlink slots shared by the cell's UEs, then (COT sharing) an
        uplink window of slots shared by up to n_interlaces UEs. The
        downlink is still ONE ActiveTx on the channel - the same footprint
        as the burst model - but each UE's transport block in each slot is
        decoded on its own, with that UE's SINR over just that slot."""
        cfg = self.config_nr
        saturated = self.traffic_config.mode == "saturated"
        tx_start = self.env.now
        total_us = cfg.mcot * 1000
        rs_time = 0 if gap else (self.next_sync_slot_boundry - self.env.now)
        ul_ues = self._ul_slot_ues()
        ul_window_us = total_us * cfg.ul_cot_fraction if ul_ues else 0.0
        data_us = max(0.0, total_us - ul_window_us - rs_time)
        n_full = int(data_us // self.slot_us)
        slots = [self.slot_us] * n_full
        if data_us - n_full * self.slot_us > 1e-9:
            slots.append(data_us - n_full * self.slot_us)  # partial last slot

        dl_ues = self._dl_slot_ues()
        if not dl_ues:
            # No downlink data: a single slot carrying only control (the
            # uplink grants).
            slots = slots[:1]
            self.slot_stats["control_only_cots"] += 1
        elif not saturated:
            # Only as many slots as the queued data needs at current CQIs:
            # the sum of each UE's share of a full-carrier slot.
            need = sum((self.dl_buffers[ue.name].backlog_bytes + self._harq_bytes(self.dl_buffers[ue.name]))
                       / max(1, self._tb_bytes(self._slot_mcs(ue), self.slot_us)) for ue in dl_ues)
            slots = slots[:max(1, math.ceil(need))]
        dl_us = rs_time + sum(slots)

        head = self.dl_buffers[dl_ues[0].name].head() if dl_ues else None
        self.transmission_to_send = Transmission_NR(total_us, self.name, self.col, tx_start, dl_us - rs_time, rs_time)
        self.transmission_to_send.rx_ue = dl_ues[0] if dl_ues else None
        self.transmission_to_send.packet = head
        active = ActiveTx(
            tx_id=self.name,
            tx_pos=self.current_pos(),
            rx_pos=dl_ues[0].current_pos() if dl_ues else self.current_pos(),
            tx_start=tx_start,
            tx_power_dbm=cfg.tx_power_dbm,
            f_hz=cfg.f_ghz,
            pl_exp=cfg.pl_exp,
            t_end=tx_start + dl_us,
            tech="NRU",
            bandwidth_mhz=cfg.bandwidth_mhz,
            noise_figure_db=cfg.noise_figure_db,
            packet=head,
        )
        self.channel.register_tx(active)
        self.slot_stats["cots"] += 1

        was_sent = False
        try:
            if rs_time > 0:
                yield self.env.timeout(rs_time)
            ref_ok = None
            for d in slots:
                t0 = self.env.now
                yield self.env.timeout(d)
                n_ok, n_fail = self._decode_dl_slot(active, dl_ues, t0, d, saturated)
                if ref_ok is None:
                    # TS 37.213: the contention window doubles when at least
                    # 80% of the reference slot's transport blocks fail.
                    n = n_ok + n_fail
                    ref_ok = n == 0 or n_fail < 0.8 * n
            was_sent = bool(ref_ok)
            # Same zero-duration tick before unregistering as the burst model.
            yield self.env.timeout(0)
            self.channel.unregister_tx(active, success=was_sent)
        except BaseException:
            self.channel.unregister_tx(active, success=was_sent)
            raise

        if was_sent:
            self.channel.succeeded_transmissions_NR += 1
            self.succeeded_transmissions += 1
            self.failed_transmissions_in_row = 0
        else:
            self.channel.failed_transmissions_NR += 1
            self.failed_transmissions += 1
            self.slot_stats["cots_failed"] += 1
            self.failed_transmissions_in_row += 1
            if self.failed_transmissions_in_row > cfg.r_limit:
                self.failed_transmissions_in_row = 0

        # Rashed-Step 19.A-10-07-2026-start
        if was_sent and (cfg.ul_access_mode is NruUplinkAccessMode.COT_SHARING or self._rrc_ul_waiters > 0):
        # Rashed-Step 19.A-10-07-2026-end
            done, self._dl_cot_done = self._dl_cot_done, self.env.event()
            done.succeed()
        if ul_window_us > 0 and was_sent:
            yield from self._run_ul_slots(ul_window_us, ul_ues)
        if was_sent:
            self.channel.airtime_control_NR[self.name] += rs_time
        return was_sent

    def _dl_view(self, active, ue):
        """The COT's downlink as seen at one UE: same transmission (and
        overlap history), received at that UE. Constant power per RB, so a
        UE's SINR doesn't depend on its RB share."""
        view = ActiveTx(tx_id=self.name, tx_pos=active.tx_pos, tx_start=active.tx_start,
                        rx_pos=ue.current_pos(), tx_power_dbm=active.tx_power_dbm, f_hz=active.f_hz,
                        pl_exp=active.pl_exp, t_end=active.t_end, tech="NRU",
                        bandwidth_mhz=active.bandwidth_mhz, noise_figure_db=active.noise_figure_db)
        view.overlap_history = active.overlap_history
        return view

    def _decode_dl_slot(self, active, dl_ues: list, t0: float, duration_us: float, saturated: bool):
        """Decode one downlink slot for every UE given RBs in it; returns
        (transport blocks ok, failed). With HARQ (18.E) a due retransmission
        goes ahead of new data."""
        # Rashed-Step 19.F-10-07-2026-start
        ues = [ue for ue in dl_ues if (saturated and getattr(ue, "scell_of", None) is None)
               or self._link_has_data(self.dl_buffers[ue.name])]
        # Rashed-Step 19.F-10-07-2026-end
        if not ues:
            return 0, 0
        alloc = self._dl_slot_alloc(ues, duration_us, saturated)
        n_ok = n_fail = 0
        for ue in ues:
            rbs = alloc.get(ue.name, 0)
            if rbs <= 0:
                continue
            buf = self.dl_buffers[ue.name]
            # Rashed-Step 18.E-10-06-2026-start
            # Same order as 18.D (MCS, refill, then SINR), so runs without
            # HARQ draw random numbers exactly as before.
            res = self._send_tb(buf, rbs, duration_us,
                                lambda u=ue: self.channel.sinr_db(self._dl_view(active, u), window=(t0, t0 + duration_us)),
                                ue, False, (lambda n=ue.name: self._make_dl_packet(n))
                                if saturated and getattr(ue, "scell_of", None) is None else None)  # 19.F
            if res is None:
                continue
            ok, mcs, tb, bits, sinr = res
            self._cqi_db[ue.name] = sinr  # the UE reports what it measured, pass or fail
            # Rashed-Step 18.E-10-06-2026-end
            if ok:
                n_ok += 1
                self.slot_stats["dl_tbs_ok"] += 1
                # Rashed-Step 19.F-10-07-2026-start
                if getattr(ue, "scell_of", None) is not None:
                    self.slot_stats["scell_dl_bits"] = self.slot_stats.get("scell_dl_bits", 0) + bits
                # Rashed-Step 19.F-10-07-2026-end
                self.slot_stats["dl_mcs_sum"] += mcs
                self.slot_stats["dl_bits"] += bits
            else:
                n_fail += 1
                self.slot_stats["dl_tbs_failed"] += 1
            self.packet_log.extend(buf.drain_finished())
            log(self, f"DL slot {'OK' if ok else 'FAILED'} to {ue.name}: SINR={sinr:.2f} dB, MCS={mcs}, RBs={rbs}, TB={tb} B")
        return n_ok, n_fail

    # Rashed-Step 18.E-10-06-2026-start
    def _harq_for(self, buffer) -> HarqEntity:
        entry = self._harq_entities.get(id(buffer))
        if entry is None:
            entry = (buffer, HarqEntity(self._harq_cfg))  # 18.F: _harq_cfg
            self._harq_entities[id(buffer)] = entry
        return entry[1]

    def harq_entities(self, ul: bool) -> list:
        if ul:
            bufs = {id(ue.ul_buffer) for ue in self.ue_list if getattr(ue, "ul_buffer", None) is not None}
        else:
            bufs = {id(b) for b in self.dl_buffers.values()}
        return [e for k, (_b, e) in self._harq_entities.items() if k in bufs]

    def _due_retx(self, buffer):
        if self._harq_cfg is None:  # 18.F: _harq_cfg
            return None
        return self._harq_for(buffer).peek_retx(self.env.now)

    def _harq_bytes(self, buffer) -> int:
        if self._harq_cfg is None:  # 18.F: _harq_cfg
            return 0
        return sum(tb.tb_bytes for tb in self._harq_for(buffer)._waiting)

    def _link_has_data(self, buffer) -> bool:
        """Queued data with a free HARQ process, or a retransmission
        waiting (due now or later in this COT)."""
        # Rashed-Step 18.F-10-06-2026-start
        if self._harq_cfg is None:
            return buffer.has_ready(self.env.now)
        # Rashed-Step 18.F-10-06-2026-end
        ent = self._harq_for(buffer)
        # Rashed-Step 18.F-10-06-2026-start
        return ent.pending() > 0 or (buffer.has_ready(self.env.now) and ent.can_send_new())
        # Rashed-Step 18.F-10-06-2026-end

    def _send_tb(self, buf, rbs: int, duration_us: float, sinr_fn, ue, ul: bool, refill):
        """One TB on one link: a due HARQ retransmission if there is one
        (and it fits its RBs), else new data. Returns (ok, mcs, tb bytes,
        delivered bits, sinr) or None when nothing was sent (no SINR
        measured then). `refill` = packet factory for saturated traffic."""
        harq = self._harq_cfg  # 18.F: also a one-attempt entity when only L2 is on
        em = self.config_nr.error_model
        rtt = None if harq is None else harq.rtt_slots * self.slot_us
        if harq is not None:
            ent = self._harq_for(buf)
            due = ent.peek_retx(self.env.now)
            # Rashed-Step pre_19.F-10-07-2026-start
            # A due retransmission goes out on the RBs it gets (same TB; on
            # fewer RBs that's a higher code rate - not modeled) instead of
            # waiting for a share it may never get again.
            if due is not None and rbs > 0:
            # Rashed-Step pre_19.F-10-07-2026-end
                tb = ent.next_retx(self.env.now)
                sinr = sinr_fn()
                for pkt, _n, _l in tb.segments:
                    pkt.measured_sinr_db = sinr
                ok = ent.attempt(tb, sinr, NR_MCS_TABLE[tb.mcs][0], em)
                bits = 0
                if ok:
                    bits = 8 * buf.ack(tb.segments, self.env.now)
                elif not ent.failed(tb, self.env.now, rtt):
                    buf.drop(tb.segments, self.env.now)
                return ok, tb.mcs, tb.tb_bytes, bits, sinr
            if not ent.can_send_new():
                return None
        mcs = self._slot_mcs(ue, ul=ul)
        tb_bytes = self._tb_bytes(mcs, duration_us, rbs)
        if refill is not None:
            # Rashed-Step 18.F-10-06-2026-start
            while buf.new_bytes < tb_bytes:
            # Rashed-Step 18.F-10-06-2026-end
                buf.enqueue(refill())
        # Rashed-Step 18.F-10-06-2026-start
        if not buf.has_ready(self.env.now):
            return None
        # Rashed-Step 18.F-10-06-2026-end
        sinr = sinr_fn()
        ok = decode_ok(em, sinr, NR_MCS_TABLE[mcs][0])
        if harq is None:
            segs = buf.segments(tb_bytes)
            for pkt, _n, _last in segs:
                pkt.measured_sinr_db = sinr
            if ok:
                return ok, mcs, tb_bytes, 8 * buf.deliver(segs, self.env.now), sinr
            buf.lose(segs)
            return ok, mcs, tb_bytes, 0, sinr
        # Rashed-Step 18.F-10-06-2026-start
        segs = buf.take(tb_bytes, self.env.now)
        if not segs:
            return None  # only L2 headers would have fit
        # Rashed-Step 18.F-10-06-2026-end
        for pkt, _n, _last in segs:
            pkt.measured_sinr_db = sinr
        tb = HarqTb(segs, mcs, rbs, tb_bytes)
        ent.attempt(tb, sinr, NR_MCS_TABLE[mcs][0], None, outcome=ok)
        if ok:
            return ok, mcs, tb_bytes, 8 * buf.ack(segs, self.env.now), sinr
        if not ent.failed(tb, self.env.now, rtt):
            buf.drop(segs, self.env.now)
        return ok, mcs, tb_bytes, 0, sinr
    # Rashed-Step 18.E-10-06-2026-end

    def _interlace_rbs(self, interlaces: list) -> int:
        return sum(len(range(m, self.total_rbs, self.n_interlaces)) for m in interlaces)

    def _run_ul_slots(self, window_us: float, ues: list):
        """Uplink part of a shared COT: up to n_interlaces UEs (round-robin
        across COTs) each get whole interlaces; all run Type 2A together,
        the ones that pass transmit their transport blocks slot by slot on
        their own interlaces (no interference between them - ofdma_cell).
        The gNB holds until the window ends."""
        cfg = self.config_nr
        start = self.env.now
        k = min(len(ues), self.n_interlaces)
        sched = [ues[(self._ul_rr + i) % len(ues)] for i in range(k)]
        self._ul_rr += k
        lanes = {ue.name: [] for ue in sched}
        for m in range(self.n_interlaces):
            lanes[sched[m % k].name].append(m)
        record = {"start": start, "end": start + window_us, "ues": [u.name for u in ues],
                  "granted": [u.name for u in sched], "result": {}}
        self.ul_windows.append(record)
        self.slot_stats["ul_grants"] += k

        # Everyone senses at the same time, before anyone transmits, so the
        # cell's own UEs don't block each other.
        checks = [self.env.process(ue.type2a_lbt()) for ue in sched]
        yield self.env.all_of(checks)
        senders = []
        for ue, chk in zip(sched, checks):
            ue.ul_grants_received += 1
            if chk.value:
                senders.append(ue)
            else:
                ue.type2a_skips += 1
                self.slot_stats["ul_type2a_skips"] += 1
                record["result"][ue.name] = None

        data_us = max(0.0, start + window_us - self.env.now)
        n_full = int(data_us // self.slot_us)
        slots = [self.slot_us] * n_full
        if data_us - n_full * self.slot_us > 1e-9:
            slots.append(data_us - n_full * self.slot_us)

        txs = {}
        now = self.env.now
        for ue in senders:
            rbs = self._interlace_rbs(lanes[ue.name])
            tx = ActiveTx(
                tx_id=ue.name, tx_pos=ue.current_pos(), tx_start=now, rx_pos=self.current_pos(),
                # Same constant power per RB as licensed NR uplink.
                tx_power_dbm=cfg.tx_power_dbm + 10.0 * math.log10(rbs / self.total_rbs),
                f_hz=cfg.f_ghz, pl_exp=cfg.pl_exp, t_end=now + data_us, tech="NRU",
                bandwidth_mhz=cfg.bandwidth_mhz * rbs / self.total_rbs,
                noise_figure_db=cfg.noise_figure_db,
                packet=ue.ul_buffer.head(),
                ofdma_cell=self.name,
            )
            self.channel.register_tx(tx)
            txs[ue.name] = (ue, tx, rbs, [0, 0])
        try:
            for d in slots:
                t0 = self.env.now
                yield self.env.timeout(d)
                for ue, tx, rbs, counts in txs.values():
                    ok = self._decode_ul_tb(ue, tx, rbs, t0, d)
                    if ok is not None:
                        counts[0 if ok else 1] += 1
            yield self.env.timeout(0)
            for ue, tx, rbs, counts in txs.values():
                self.channel.unregister_tx(tx, success=counts[0] > 0)
                record["result"][ue.name] = counts[0] > 0
        except BaseException:
            for ue, tx, rbs, counts in txs.values():
                self.channel.unregister_tx(tx, success=False)
            raise
        remaining = start + window_us - self.env.now
        if remaining > 0:
            yield self.env.timeout(remaining)

    def _decode_ul_tb(self, ue, tx, rbs: int, t0: float, duration_us: float):
        """Decode one uplink slot of one UE. True/False, or None when the
        UE had nothing to send in it."""
        buf = ue.ul_buffer
        # Rashed-Step 18.E-10-06-2026-start
        refill = (lambda n=ue.name: self._make_ul_packet(n)) if self.config_nr.ul_traffic is None else None
        res = self._send_tb(buf, rbs, duration_us,
                            lambda: self.channel.sinr_db(tx, window=(t0, t0 + duration_us)),
                            ue, True, refill)
        if res is None:
            return None
        ok, mcs, _tb, bits, sinr = res
        self._ul_cqi_db[ue.name] = sinr
        # Rashed-Step 18.E-10-06-2026-end
        if ok:
            ue.succeeded_transmissions += 1
            self.slot_stats["ul_tbs_ok"] += 1
            self.slot_stats["ul_mcs_sum"] += mcs
            self.slot_stats["ul_bits"] += bits
        else:
            ue.failed_transmissions += 1
            self.slot_stats["ul_tbs_failed"] += 1
        ue.packet_log.extend(buf.drain_finished())
        return ok

    def flush_buffer_logs(self) -> None:
        """Move packets finished since the last slot (e.g. drop-tail
        overflow) into packet_log; call once the run has ended."""
        for buf in getattr(self, "dl_buffers", {}).values():
            self.packet_log.extend(buf.drain_finished())
        for ue in self.ue_list:
            if getattr(ue, "ul_buffer", None) is not None:
                ue.packet_log.extend(ue.ul_buffer.drain_finished())
    # Rashed-Step 18.D-10-06-2026-end
    # Rashed-Step 18.C-10-06-2026-end

    # Rashed-Step 19.B.2-10-07-2026-start
    # Rashed-Step 19.B.3-10-07-2026-start
    def ue_buffers(self, ue):
        """(downlink buffer, uplink buffer) of one UE; None where absent."""
        dl = getattr(self, "dl_buffers", None)
        return (dl.get(ue.name) if dl else None), getattr(ue, "ul_buffer", None)
    
    def ue_has_pending(self, ue) -> bool:
        """Anything queued or waiting for a HARQ retransmission, either way."""
        for buf in self.ue_buffers(ue):
            if buf is None:
                continue
            if buf.backlog_bytes > 0:
                return True
            entry = getattr(self, "_harq_entities", {}).get(id(buf))
            if entry is not None and entry[1].pending() > 0:
                return True
        return False
    
    # Rashed-Step 19.B.3-10-07-2026-end
    def dl_sinr_estimate(self, ue) -> float:
        """Downlink SINR a UE measures for radio link monitoring: a probe
        of this gNB's downlink against whatever else is on the air now."""
        now = self.env.now
        probe = ActiveTx(tx_id=self.name, tx_pos=self.current_pos(), tx_start=now,
                         rx_pos=ue.current_pos(), tx_power_dbm=self.config_nr.tx_power_dbm,
                         f_hz=self.config_nr.f_ghz, pl_exp=self.config_nr.pl_exp, t_end=now + 1.0,
                         tech="NRU", bandwidth_mhz=self.config_nr.bandwidth_mhz,
                         noise_figure_db=self.config_nr.noise_figure_db)
        return self.channel.sinr_db(probe)
    
    # Rashed-Step 19.B.2-10-07-2026-end
    def wait_back_off_gap_after(self):
        yield from self._channel_access.wait(self)
    # Rashed-Step 15.A-09-18-2026-end

    # Rashed-Step 15.F-09-18-2026-start
    def rrc_uplink_delay(self, ue):
        """
        RRC attach's technology-specific "how long until this UE can
        actually send an uplink RRC message" hook (see
        ran/protocol/rrc.py's RrcLayer.attach()). Reuses the exact same
        shared LbtChannelAccess (15.A) this gNB's own downlink and
        NrUE's own real uplink (15.C) both use - `ue` satisfies its
        duck-typed contract already, since rrc_enabled requires
        uplink_enabled=True (see NrUE.__post_init__), which is what
        wires up ue.config_nr/ue.channel/ue.cw_min/ue.cw_max/etc. in
        the first place. A genuine, real Cat-4 LBT contention wait, not
        an invented delay - exactly what "genuinely has to win LBT
        contention to be sent at all" (Step pre_15.txt's 15.F SCOPE
        RESOLVED note) means.
        """
        # Rashed-Step 16.A-10-02-2026-start
        # Grant first (same cost licensed NR pays), then LBT on top -
        # see Config_NR.rrc_ul_grant_delay_us.
        yield self.env.timeout(self.config_nr.rrc_ul_grant_delay_us)
        # Rashed-Step 16.A-10-02-2026-end
        # Rashed-Step 17.F-10-04-2026-start
        # COT sharing: the RRC message goes the same way as uplink data -
        # its grant rides in this gNB's next successful downlink COT, and
        # the UE sends at the start of that COT's uplink part after a
        # 25us Type 2A check; if the check fails, it waits for the next
        # COT. No Cat-4 by the UE. (Still a signaling delay, no airtime
        # of its own - same as the autonomous version below.) Note: a
        # gNB that never transmits never opens a COT, so the attach then
        # never completes - by design, there is no grant to use.
        if self.config_nr.ul_access_mode is NruUplinkAccessMode.COT_SHARING:
            # Rashed-Step 19.B.1-10-07-2026-start
            failed_checks = 0
            # Rashed-Step 19.B.1-10-07-2026-end
            while True:
                # Rashed-Step 18.C-10-06-2026-start
                # In "slots" the gNB only contends when it has work; a UE
                # waiting to send an RRC message in its COT is work.
                self._rrc_ul_waiters += 1
                if self.config_nr.cot_model == "slots":
                    self._kick_slots()
                try:
                    yield self._dl_cot_done
                finally:
                    self._rrc_ul_waiters -= 1
                # Rashed-Step 18.C-10-06-2026-end
                if (yield from ue.type2a_lbt()):
                    return
                ue.rrc_type2a_skips = getattr(ue, "rrc_type2a_skips", 0) + 1
                # Rashed-Step 19.B.1-10-07-2026-start
                failed_checks += 1
                n = self.config_nr.rrc_type1_fallback_after
                if n is not None and failed_checks >= n:
                    ue.rrc_type1_fallbacks = getattr(ue, "rrc_type1_fallbacks", 0) + 1
                    yield from self._channel_access.wait(ue)
                    return
                # Rashed-Step 19.B.1-10-07-2026-end
        # Rashed-Step 17.F-10-04-2026-end
        yield from self._channel_access.wait(ue)
    # Rashed-Step 15.F-09-18-2026-end


    # Rashed-Step 3.E_2-01-12-2026-end

    def wait_back_off_gap(self):
        self.back_off_time = self.generate_new_back_off_time(
            self.failed_transmissions_in_row)
        # adding pp to the backoff timer
        m = self.config_nr.M
        prioritization_period_time = self.config_nr.deter_period + \
            m * self.config_nr.observation_slot_duration
        # add Priritization Period time to bacoff procedure
        self.back_off_time += prioritization_period_time

        while self.back_off_time > -1:
            try:
                with self.channel.tx_lock.request() as req:  # waiting  for idle channel -- empty channel
                    yield req

                self.time_to_next_sync_slot = self.next_sync_slot_boundry - self.env.now


                log(self,
                    f'Backoff = {self.back_off_time} , and time to next slot: {self.time_to_next_sync_slot}')
                while self.back_off_time >= self.time_to_next_sync_slot:
                    self.time_to_next_sync_slot += self.config_nr.synchronization_slot_duration
                    log(self,
                        f'Backoff > time to sync slot: new time to next possible sync +1000 = {self.time_to_next_sync_slot}')

                gap_time = self.time_to_next_sync_slot - self.back_off_time
                log(self, f"Waiting gap period of : {gap_time} us")
                assert gap_time >= 0, "Gap period is < 0!!!"

                yield self.env.timeout(gap_time)
                log(self, f"Finished gap period")

                self.first_interrupt = True

                self.start_nr = self.env.now  # store the current simulation time

                log(self,
                    f'Channels in use by {self.channel.tx_lock.count} stations')

                # checking if channel if idle
                if (len(self.channel.tx_list_NR) + len(self.channel.tx_list)) > 0:
                    log(self, 'Channel busy -- waiting to be free')
                    with self.channel.tx_lock.request() as req:
                        yield req
                    log(self, 'Finished waiting for free channel - restarting backoff procedure')

                else:
                    log(self, 'Channel free')
                    log(self,
                        f"Starting to wait backoff: ({self.back_off_time}) us...")
                    # join the list off stations which are waiting Back Offs
                    self.channel.back_off_list_NR.append(self)
                    self.waiting_backoff = True

                    # join the environment action queue
                    yield self.env.timeout(self.back_off_time)

                    log(self, f"Backoff waited, sending frame...")
                    self.back_off_time = -1  # leave the loop
                    self.waiting_backoff = False

                    self.channel.back_off_list_NR.remove(
                        self)  # leave the waiting list as Backoff was waited successfully

            except simpy.Interrupt:  # handle the interruptions from transmitting stations
                log(self, "Waiting was interrupted")
                if self.first_interrupt and self.start is not None and self.waiting_backoff is True:
                    log(self, "Backoff was interrupted, waiting to resume backoff...")
                    already_waited = self.env.now - self.start_nr

                    if already_waited <= prioritization_period_time:
                        self.back_off_time -= prioritization_period_time
                        log(self,
                            f"Interrupted in PP time {prioritization_period_time}, backoff {self.back_off_time}")
                    else:
                        slots_waited = int(
                            (already_waited - prioritization_period_time) / self.config_nr.observation_slot_duration)
                        # self.back_off_time -= already_waited  # set the Back Off to the remaining one
                        self.back_off_time -= (
                            (slots_waited * self.config_nr.observation_slot_duration) + prioritization_period_time)
                        log(self,
                            f"Completed slots(9us) {slots_waited} = {(slots_waited * self.config_nr.observation_slot_duration)}  plus PP time {prioritization_period_time}")
                        log(self, f"Backoff decresed by {(slots_waited * self.config_nr.observation_slot_duration) + prioritization_period_time} new Backoff {self.back_off_time}")

                    #log(self, f"already waited {already_waited} Backoff us, new Backoff {self.back_off_time}")
                    # addnin new PP before next weiting
                    self.back_off_time += prioritization_period_time
                    self.first_interrupt = False
                    self.waiting_backoff = False

    def wait_back_off(self):
        # Wait random number of slots N x OBSERVATION_SLOT_DURATION us
        global start
        self.back_off_time = self.generate_new_back_off_time(
            self.failed_transmissions_in_row)
        m = self.config_nr.M
        prioritization_period_time = self.config_nr.deter_period + \
            m * self.config_nr.observation_slot_duration

        while self.back_off_time > -1:

            try:
                with self.channel.tx_lock.request() as req:  # waiting  for idle channel -- empty channel
                    yield req

                self.first_interrupt = True
                # add Priritization Period time to bacoff procedure
                self.back_off_time += prioritization_period_time
                log(self,
                    f"Starting to wait backoff (with PP): ({self.back_off_time}) us...")
                start = self.env.now  # store the current simulation time
                # join the list off stations which are waiting Back Offs
                self.channel.back_off_list_NR.append(self)

                # join the environment action queue
                yield self.env.timeout(self.back_off_time)

                log(self, f"Backoff waited, sending frame...")
                self.back_off_time = -1  # leave the loop

                # leave the waiting list as Backoff was waited successfully
                self.channel.back_off_list_NR.remove(self)

            except simpy.Interrupt:  # handle the interruptions from transmitting stations
                log(self, "Backoff was interrupted, waiting to resume backoff...")
                if self.first_interrupt and start is not None:
                    already_waited = self.env.now - start

                    if already_waited <= prioritization_period_time:
                        self.back_off_time -= prioritization_period_time
                        log(self,
                            f"Interrupted in PP time {prioritization_period_time}, backoff {self.back_off_time}")
                    else:
                        slots_waited = int(
                            (already_waited - prioritization_period_time) / self.config_nr.observation_slot_duration)
                        # self.back_off_time -= already_waited  # set the Back Off to the remaining one
                        self.back_off_time -= (
                            (slots_waited * self.config_nr.observation_slot_duration) + prioritization_period_time)
                        log(self,
                            f"Completed slots(9us) {slots_waited} = {(slots_waited * self.config_nr.observation_slot_duration)}  plus PP time {prioritization_period_time}")
                        log(self, f"Backoff decresed by {(slots_waited * self.config_nr.observation_slot_duration) + prioritization_period_time} new Backoff {self.back_off_time}")

                    self.first_interrupt = False
                    self.waiting_backoff = False

    def sync_slot_counter(self):
        # Process responsible for keeping the next sync slot boundry timestamp
        self.desync = random.randint(
            self.config_nr.min_sync_slot_desync, self.config_nr.max_sync_slot_desync)
        self.next_sync_slot_boundry = self.desync
        log(self, f"Selected random desync to {self.desync} us")
        # waiting randomly chosen desync time
        yield self.env.timeout(self.desync)
        while True:
            self.next_sync_slot_boundry += self.config_nr.synchronization_slot_duration
            log(self,
                f"Next synch slot boundry is: {self.next_sync_slot_boundry}")
            #print(f"Next synch slot boundry is: ",self.next_sync_slot_boundry)
            yield self.env.timeout(self.config_nr.synchronization_slot_duration)

    # Rashed-Step 8.B-08-06-2026-start
    # packet=None default preserves every pre-Step-8.B call site/test
    # exactly (falls through to gen_new_transmission() synthesizing its
    # own, same as before) - start() now passes the episode's packet
    # explicitly (see start()'s comment).
    def send_transmission(self, packet: Optional[Packet] = None):
        self.transmission_to_send = self.gen_new_transmission(packet)
    # Rashed-Step 8.B-08-06-2026-end

        # Rashed-Step 6.A-07-31-2026-start
        # UPGRADE: this used to acquire self.channel.tx_queue_nru (one
        # capacity-1 resource shared by every gNB) before transmitting, so
        # no two gNBs could ever be "in flight" on the channel at the same
        # simulated instant - real Cat-4 LBT collisions (two independent
        # backoff/gap timers expiring in the same slot) were structurally
        # impossible, mirroring the gap fixed in wifi.WiFi.send_frame() (see
        # the Step 6.A note there) and flagged in the realism validation
        # report (2026-07-31). wait_back_off_gap_after() already does
        # correct per-gNB, per-slot channel sensing independently for every
        # gNB, so removing the queue and registering the transmission
        # immediately lets two gNBs whose backoff+gap both expire in the
        # same tick genuinely overlap on the channel - the existing
        # SINR/capture-effect logic below (unchanged) then decides who, if
        # anyone, survives.
        # Rashed-Step 6.A-07-31-2026-end
        log(self, f'Starting transmission: {self.transmission_to_send.transmission_time}')

        # Rashed-Step 5.G-02-06-2026-start
        # rx_pos is read fresh, right here at actual transmission start (not
        # back in gen_new_transmission()), so a moving UE's position is
        # always "now".
        tx_start = self.env.now
        tx_pos = self.current_pos()
        rx_ue = self.transmission_to_send.rx_ue
        rx_pos = rx_ue.current_pos() if rx_ue is not None else tx_pos
        tx_dur = self.transmission_to_send.transmission_time
        # Rashed-Step 5.G-02-06-2026-end

        # Rashed-Step 17.C-10-04-2026-start
        # COT sharing: if any of this gNB's UEs can send uplink right now,
        # the downlink only uses the first (1 - ul_cot_fraction) of the
        # COT and the rest becomes an uplink window for them (opened
        # below, after the downlink). Otherwise - AUTONOMOUS mode, or no
        # eligible UE - the whole COT is downlink, exactly as before.
        cot_ul_ues = self._cot_ul_ues()
        ul_window_us = 0.0
        if cot_ul_ues:
            ul_window_us = tx_dur * self.config_nr.ul_cot_fraction
            tx_dur = tx_dur - ul_window_us
        # Rashed-Step 17.C-10-04-2026-end

        active = ActiveTx(
            tx_id=self.name,
            tx_pos=tx_pos,
            rx_pos=rx_pos,
            tx_start=tx_start,
            tx_power_dbm=self.config_nr.tx_power_dbm,
            f_hz=self.config_nr.f_ghz,
            pl_exp=self.config_nr.pl_exp,
            t_end=tx_start + tx_dur,
            tech="NRU",
            # Rashed-Step 5.C-02-06-2026-start
            bandwidth_mhz=self.config_nr.bandwidth_mhz,
            noise_figure_db=self.config_nr.noise_figure_db,
            # Rashed-Step 5.C-02-06-2026-end
            # Rashed-Step 9.B-08-07-2026-start
            # Same bugfix as wifi.WiFi.send_frame() - see that
            # construction site's comment for the full rationale.
            # self.transmission_to_send.packet is already populated by
            # gen_new_transmission() (Step 8.B), just never threaded
            # through to the ActiveTx that actually gets registered on
            # the shared channel until now.
            packet=self.transmission_to_send.packet,
            # Rashed-Step 9.B-08-07-2026-end
        )
        # Rashed-Step 4.B_4-01-20-2026-start
        #print(self.env.now, self.name, "TX->RX d=", dist(self.pos, rx_pos))
        # Rashed-Step 4.B_4-01-20-2026-end
        self.channel.register_tx(active)

        # Rashed-Step 5.1-02-06-2026-start
        was_sent = False
        # Rashed-Step 5.1-02-06-2026-end
        try:
            yield self.env.timeout(tx_dur)
            # Rashed-Step 4.C_2-01-21-2026-start
            # Rashed-Step 12.A-08-13-2026-start
            # BUGFIX: commented out - this was a leftover development-
            # time debug print (every 50th successful NR-U transmission),
            # never gated behind a verbosity flag, so it cluttered every
            # normal run's stdout with raw "time name NRU SINR(dB) = ..."
            # lines mixed in among the real CLI output. wifi.py's exact
            # equivalent (self.sinr_print_ctr/"WiFi SINR(dB) =") was
            # already commented out for the same reason - this brings
            # nru.py to parity. self.sinr_print_ctr itself is left alone
            # (still incremented nowhere now, harmless leftover field) so
            # re-enabling this for local debugging later is a 2-line
            # uncomment, not a re-implementation.
            # self.sinr_print_ctr += 1
            # if self.sinr_print_ctr % 50 == 0:
            #     print(self.env.now, self.name, "NRU SINR(dB) =", self.channel.sinr_db(active))
            # Rashed-Step 12.A-08-13-2026-end
            # Rashed-Step 4.C_2-01-21-2026-end
            # Rashed-Step 4.D_3-01-29-2026-start
            #was_sent = self.check_collision()
            sinr = self.channel.sinr_db(active)
            # Rashed-Step 13.A-08-23-2026-start
            # Log measured SINR on the packet itself, success or
            # failure alike - see Packet.measured_sinr_db docstring.
            self.transmission_to_send.packet.measured_sinr_db = sinr
            # Rashed-Step 13.A-08-23-2026-end
            # Rashed-Step 5.D-02-06-2026-start
            required_sinr = self.required_sinr_db()
            log(self, f"TX->RX SINR(dB) = {sinr:.2f} dB, required (MCS {self.config_nr.mcs}) = {required_sinr:.2f} dB")
            # Rashed-Step 18.A-10-06-2026-start
            was_sent = decode_ok(self.config_nr.error_model, sinr, required_sinr)
            # Rashed-Step 18.A-10-06-2026-end
            # Rashed-Step 5.D-02-06-2026-end
            # Rashed-Step 11.B-08-21-2026-start
            # CQI-style feedback: record this transmission's measured
            # SINR so the NEXT transmission to this same UE can pick a
            # better-fitting MCS. No-op when rate adaptation is
            # disabled. Deliberately uses the link_key computed BEFORE
            # this transmission (self.transmission_to_send.rx_ue is
            # unchanged throughout this method), not a re-derived one.
            self.rate_adapt_record_result(self.rate_adapt_link_key(), sinr)
            # Rashed-Step 11.B-08-21-2026-end
            if was_sent:
                self.sent_completed()
            else:
                self.sent_failed()
            # Rashed-Step 4.D_3-01-29-2026-start
            # Rashed-Step 4.C_2-01-21-2026-start
            # Yield one extra zero-duration tick before unregistering,
            # so another transmission ending at this exact same env.now
            # still sees this one in channel.active_txs while computing
            # its own SINR (avoids an artificial tie-break bias from
            # unregistering "too early" relative to a same-tick peer -
            # see channel.sinr_db()/sensed_energy_dbm(), both of which
            # only count what's currently in active_txs).
            yield self.env.timeout(0)
            # Rashed-Step 4.C_2-01-21-2026-end
            # Rashed-Step 5.1-02-06-2026-start
            # BUGFIX: pass success so airtime isn't recorded twice - see
            # matching note below where the old manual
            # airtime_data_NR += line was removed.
            self.channel.unregister_tx(active, success=was_sent)
            # Rashed-Step 5.1-02-06-2026-end
        except BaseException:
            # Rashed-Step 5.I-02-06-2026-start
            # BUGFIX: this used to be `finally: yield ...; unregister_tx
            # (...)`, which ran on EVERY exit path including the
            # generator being closed via GeneratorExit at simulation
            # shutdown (env.run(until=...) returning while this gNB was
            # still mid-transmission - a near-certain occurrence at the
            # end of any run). Yielding again while a generator is being
            # closed is invalid and raised "RuntimeError: generator
            # ignored GeneratorExit" (printed by the interpreter as
            # "Exception ignored in: ..." since it happens during
            # garbage collection with no caller to propagate to -
            # harmless to already-computed results, but noisy on every
            # single run). Fixed the same way as wifi.WiFi.send_frame():
            # move the yield+unregister into the normal (non-exception)
            # tail of the try, and handle GeneratorExit (or any other
            # exception) here with purely SYNCHRONOUS cleanup instead.
            self.channel.unregister_tx(active, success=was_sent)
            raise
            # Rashed-Step 5.I-02-06-2026-end

        # Rashed-Step 17.C-10-04-2026-start
        # The uplink grants travel in the downlink part, so the window
        # only opens if that downlink got through. The gNB holds here
        # until its COT ends - it doesn't start a new LBT while its own
        # UEs are using the shared COT.
        # Rashed-Step 17.F-10-04-2026-start
        # Wake any UE whose RRC message is waiting for a grant (COT
        # sharing only). Fired before the uplink window so an RRC message
        # and a data grant can share the same COT end.
        # Rashed-Step 19.A-10-07-2026-start
        if was_sent and (self.config_nr.ul_access_mode is NruUplinkAccessMode.COT_SHARING
                         or self._rrc_ul_waiters > 0):
        # Rashed-Step 19.A-10-07-2026-end
            done, self._dl_cot_done = self._dl_cot_done, self.env.event()
            done.succeed()
        # Rashed-Step 17.F-10-04-2026-end
        if ul_window_us > 0 and was_sent:
            yield from self._run_ul_window(ul_window_us, cot_ul_ues)
        # Rashed-Step 17.C-10-04-2026-end

        if was_sent:
            self.channel.airtime_control_NR[self.name] += self.transmission_to_send.rs_time
            # Rashed-Step 5.1-02-06-2026-start
            # BUGFIX: this used to also do
            # self.channel.airtime_data_NR[self.name] += self.transmission_to_send.airtime
            # here, double-counting against channel.unregister_tx(active,
            # success=...) above, which now records airtime_data_NR on
            # success. Removed - unregister_tx is the single source of
            # truth. airtime_control_NR (RS time) is untouched since it
            # was never duplicated.
            # Rashed-Step 5.1-02-06-2026-end
            return True
        else:
            return False

    # Rashed-Step 17.C-10-04-2026-start
    def _cot_ul_ues(self) -> list:
        """UEs that get a slice of this gNB's next COT for uplink: only in
        COT_SHARING mode, and only UEs with uplink on, RRC CONNECTED (or
        no RRC) and allowed by the UPF gate - same eligibility filters as
        the downlink destination pick. Empty list = whole COT downlink."""
        if self.config_nr.ul_access_mode is not NruUplinkAccessMode.COT_SHARING:
            return []
        return [
            ue for ue in self.ue_list
            if getattr(ue, "uplink_enabled", False)
            and getattr(ue, "rrc_state", RrcState.CONNECTED) is RrcState.CONNECTED
            and user_plane_allows(ue)
        ]

    def _run_ul_window(self, duration_us: float, ues: list):
        """Uplink part of a shared COT: grants it to one eligible UE and
        holds the gNB until the window ends (also when that UE skips its
        grant - the gNB doesn't reclaim the rest of its COT)."""
        start = self.env.now
        # Rashed-Step 17.E-10-04-2026-start
        # The whole window goes to ONE UE, rotating round-robin across
        # COTs: NR-U here has no per-UE frequency split, so two UEs
        # sending at once would just interfere at this gNB.
        ue = ues[self._ul_rr % len(ues)]
        self._ul_rr += 1
        record = {"start": start, "end": start + duration_us,
                  "ues": [u.name for u in ues], "granted": ue.name, "result": None}
        self.ul_windows.append(record)
        record["result"] = yield from ue.send_in_shared_cot(duration_us)
        remaining = start + duration_us - self.env.now
        if remaining > 0:
            yield self.env.timeout(remaining)
        # Rashed-Step 17.E-10-04-2026-end
    # Rashed-Step 17.C-10-04-2026-end

    def check_collision(self):  # check if the collision occurred

        # if gap:
        #     # if (len(self.channel.tx_list) + len(self.channel.tx_list_NR)) > 1 and self.waiting_backoff is True:
        #     if (len(self.channel.tx_list) + len(self.channel.tx_list_NR)) > 1 or (len(self.channel.tx_list) + len(self.channel.tx_list_NR)) == 0:
        #         self.sent_failed()
        #         return False
        #     else:
        #         self.sent_completed()
        #         return True
        # else:
        #     if (len(self.channel.tx_list) + len(self.channel.tx_list_NR)) > 1 or (len(self.channel.tx_list) + len(self.channel.tx_list_NR)) == 0:
        #         self.sent_failed()
        #         return False
        #     else:
        #         self.sent_completed()
        #         return True
        # Rashed-Step 3.F-01-13-2026-start
        # ok = all(t.tx_id == self.name for t in self.channel.active_txs)
        # (self.sent_completed() if ok else self.sent_failed())
        # return ok
        mine = any(t.tx_id == self.name for t in self.channel.active_txs)

        if not mine:
            self.sent_failed()
            return False
        
        others = [t for t in self.channel.active_txs if t.tx_id != self.name]
        
        if others:
            self.sent_failed()
            return False
        
        self.sent_completed()
        return True
        # Rashed-Step 3.F-01-13-2026-end

    # Rashed-Step 8.B-08-06-2026-start
    # packet=None default preserves standalone/test-harness behavior
    # exactly (synthesizes its own via _make_packet(), same as an
    # implicit saturated-mode packet always was before this field
    # existed). start() now passes the current episode's packet
    # explicitly through send_transmission() so every attempt (first
    # try and every retry) within one episode stamps the SAME Packet
    # object here, even though a brand-new Transmission_NR is still
    # built fresh each call (unchanged - see Step 8.txt's note on why
    # NR-U's per-attempt regeneration pattern itself was deliberately
    # left untouched).
    def gen_new_transmission(self, packet: Optional[Packet] = None):
        # Rashed-Step 2.D_2-01-08-2026-start

        # transmission_time = self.config_nr.mcot * 1000  # transforming to usec
        # if gap:
        #     rs_time = 0
        # else:
        #     rs_time = self.next_sync_slot_boundry - self.env.now
        # airtime = transmission_time - rs_time
        # return Transmission_NR(transmission_time, self.name, self.col, self.env.now, airtime, rs_time)

        transmission_time = self.config_nr.mcot * 1000
        rs_time = 0 if gap else (self.next_sync_slot_boundry - self.env.now)
        airtime = transmission_time - rs_time

        # Rashed-Step 15.G-09-18-2026-start
        # Scheduler/RRC integration: only pick a downlink destination
        # from RRC-CONNECTED UEs (or UEs that never opted into RRC at
        # all - getattr(..., RrcState.CONNECTED) default, same
        # backward-compat contract as everywhere else in Step 15.F/G) -
        # mirrors licensed NR's own rrc_state==CONNECTED scheduler
        # filter (nr.nr.GnbLicensedNR._run_dl_slot()/_run_ul_slot()),
        # extended to NR-U per the confirmed 15.G scope decision
        # (2026-09-18: symmetric with 15.F's generic RRC design). A
        # cell with no rrc_enabled UEs at all sees candidate_ues ==
        # self.ue_list, so this is byte-identical to every pre-15.G
        # run. Falls back to rx_ue=None (same as the pre-existing empty
        # self.ue_list case below) if every UE happens to be mid-attach
        # right now - send_transmission() already handles that rx_ue=
        # None case (rx_pos falls back to tx_pos).
        candidate_ues = [
            ue for ue in self.ue_list
            if getattr(ue, "rrc_state", RrcState.CONNECTED) is RrcState.CONNECTED
            # Rashed-Step 16.E-10-02-2026-start
            # ...and only UEs whose PDU session is ACTIVE, for UEs handed
            # to the 5G Core (ran/protocol/user_plane.py). Same rx_ue=None
            # fallback as above when nobody qualifies yet.
            and user_plane_allows(ue)
            # Rashed-Step 16.E-10-02-2026-end
        ]
        rx_ue = random.choice(candidate_ues) if candidate_ues else None
        # Rashed-Step 15.G-09-18-2026-end

        tx = Transmission_NR(
            transmission_time, self.name, self.col, self.env.now, airtime, rs_time)
        tx.packet = packet if packet is not None else self._make_packet()
        # Rashed-Step 8.B-08-06-2026-end

        # Rashed-Step pre_17.A-10-04-2026-start
        # BUGFIX (found in Step 16.E): _make_packet() stamps destination =
        # ue_list[0] on every packet, but the real receiver is rx_ue,
        # picked above - so multi-UE cells mislabeled packets, and
        # packets sent with no eligible UE (rx_ue=None: mid-RRC or before
        # a PDU session) were credited to ue_list[0]. Also, rx_ue was
        # re-drawn on EVERY attempt, so a retry of the same packet could
        # go to a different UE; real HARQ retransmits to the same one.
        # Now: a retry (retry_count > 0 - its destination was set by the
        # previous attempt, below) keeps that receiver while it's still
        # eligible; destination = the UE actually picked, or this gNB's
        # own name when there is none (no UE credited). The random draw
        # above still always happens, so the RNG stream - and every
        # single-UE cell's output - is unchanged.
        if tx.packet.retry_count > 0:
            previous_rx = next(
                (ue for ue in candidate_ues if ue.name == tx.packet.destination), None
            )
            if previous_rx is not None:
                rx_ue = previous_rx
        tx.packet.destination = rx_ue.name if rx_ue is not None else self.name
        # Rashed-Step pre_17.A-10-04-2026-end

        # Rashed-Step 5.G-02-06-2026-start
        # current_pos() instead of self.pos/rx_ue.pos for this diagnostic
        # snapshot (distance_m/pr_dbm are logged, not used for the actual
        # send_transmission() success decision, which recomputes its own
        # tx_pos/rx_pos fresh right at transmission time). tx.rx_ue stores
        # the actual chosen UE object (not just its position) so
        # send_transmission() can re-read *its* current_pos() later, after
        # potentially waiting on tx_queue_nru - see send_transmission().
        my_pos = self.current_pos()
        tx.tx_pos = my_pos
        tx.rx_ue = rx_ue
        if rx_ue is not None:
            rx_pos = rx_ue.current_pos()
            tx.rx_name = rx_ue.name
            tx.rx_pos = rx_pos
            tx.distance_m = dist(my_pos, rx_pos)
            # Rashed-Step 5.G-02-06-2026-end

            # Rashed-Step 5.B-02-06-2026-start
            tx.pr_dbm = rx_power_dbm(
                tx_power_dbm=self.config_nr.tx_power_dbm,
                d_m= tx.distance_m,
                f_hz=self.config_nr.f_ghz,
                n = self.config_nr.pl_exp,
                shadow_db=self.channel.shadow_db(self.name, tx.rx_pos)
            )
            # Rashed-Step 5.B-02-06-2026-end

        return tx
        
        # Rashed-Step 2.D_2-01-08-2026-end


    # Rashed-Step 3.E_1-12-26-2025-start
    # def generate_new_back_off_time(self, failed_transmissions_in_row):
    #     # BACKOFF TIME GENERATION
    #     upper_limit = (pow(2, failed_transmissions_in_row) * (
    #         self.cw_min + 1) - 1)  # define the upper limit basing on  unsuccessful transmissions in the row
    #     upper_limit = (
    #         upper_limit if upper_limit <= self.cw_max else self.cw_max)  # set upper limit to CW Max if is bigger then this parameter
    #     back_off = random.randint(0, upper_limit)  # draw the back off value
    #     # store drawn value for future analyzes
    #     self.channel.backoffs[back_off][self.channel.n_of_stations] += 1
    #     return back_off * self.config_nr.observation_slot_duration

    # Rashed-Step 15.A-09-18-2026-start
    # UPGRADE (pure refactor, zero behavior change): delegates to
    # ran.protocol.channel_access.generate_backoff_slots() - the exact
    # same formula/single random.randint() draw, just parametrized on
    # cw_min/cw_max instead of reading them off self directly. Kept as a
    # real method (not deleted) since it's still callable directly.
    def generate_backoff_slots(self, failed_transmissions_in_row: int)-> int:
        return _lbt_generate_backoff_slots(failed_transmissions_in_row, self.cw_min, self.cw_max)
    # Rashed-Step 15.A-09-18-2026-end
    
    # Rashed-Step 3.E_1-12-26-2025-end

    # Rashed-Step 5.D-02-06-2026-start
    def required_sinr_db(self) -> float:
        """
        Required SINR for this gNB's current MCS (rate-adapted if
        Config_NR.rate_adapt_enabled, else the fixed configured value),
        or the flat override if config_nr.nru_sinr_thr_db_override is
        set. Shared by the send_transmission() success decision and the
        sent_failed() log line so they can't drift apart.
        """
        if self.config_nr.nru_sinr_thr_db_override is not None:
            return self.config_nr.nru_sinr_thr_db_override
        # Rashed-Step 11.B-08-21-2026-start
        mcs = self.current_mcs_for_link(self.rate_adapt_link_key())
        # Rashed-Step 11.B-08-21-2026-end
        return mcs_sinr_threshold_db(NRU_MCS_SINR_THRESHOLDS_DB, mcs)
    # Rashed-Step 5.D-02-06-2026-end

    # Rashed-Step 11.B-08-21-2026-start
    def rate_adapt_link_key(self) -> Optional[str]:
        """
        Identifies which per-link rate-adaptation state to use - the UE
        actually chosen for THIS transmission (self.transmission_to_
        send.rx_ue, set by gen_new_transmission()'s random.choice(self.
        ue_list) and re-read fresh at transmission time - see send_
        transmission()'s own comment on why it's stored on the
        Transmission_NR object rather than re-picked). None when
        there's no pending transmission or it has no target UE.
        """
        tx = self.transmission_to_send
        if tx is not None and tx.rx_ue is not None:
            return tx.rx_ue.name
        return None

    def current_mcs_for_link(self, link_key: Optional[str]) -> int:
        """
        The MCS to use RIGHT NOW for `link_key`. Returns config_nr.mcs
        unchanged when rate adaptation is disabled, link_key is None,
        or this link has no SINR measurement yet (first transmission -
        there's nothing to base a CQI-style pick on) - so "adaptation
        off" and "adaptation on, before any feedback" both behave
        exactly like today.

        Rashed-Step 13.D: when config_nr.sinr_predictor is set AND this
        link already has at least predictor.lag_k measurements, the
        MCS pick is based on the predictor's PREDICTED next SINR
        instead of the raw last-measured value - everything else
        (predictor unset, or not enough history yet) falls back to the
        exact pre-13.D behavior unchanged. See ml/predictor.py's module
        docstring / "Project details/Step 13.txt" for why this is NOT
        assumed to be an improvement going in - Step 13.C's own
        evaluation found this same model didn't beat plain "last
        observed" on MAE.

        Rashed-Step 13.D-fix (2026-08-23): the predictor is deliberately
        SKIPPED when the recent history is exactly constant (a genuinely
        static/unshadowed-relative-to-itself link - the same "constant-
        link" category Step 13.C already tags and reports separately).
        Investigated a real empirical collapse: on a constant 12.807 dB
        link, the model predicted 16.111 dB (a persistent +3.3 dB
        overestimate) from a [12.807]*3 history, crossing an MCS
        threshold the real channel could never clear - every
        transmission after that hit the retry limit, for the rest of
        the run, because a constant history never gives the model new
        information to self-correct with. Persistence (last observed)
        is EXACTLY correct on a constant link by construction (13.C's
        own finding - 0.000 MAE there), so there is no principled reason
        to ever prefer a noisy model prediction over it in this specific,
        cheaply-detectable case. This guard does not touch the variable-
        link case at all - the predictor is still used there exactly as
        before.
        """
        if not self.config_nr.rate_adapt_enabled or link_key is None:
            return self.config_nr.mcs
        state = self.link_rate_state.get(link_key)
        if state is None or state.get("last_sinr_db") is None:
            return self.config_nr.mcs
        # Rashed-Step 13.D-08-23-2026-start
        predictor = self.config_nr.sinr_predictor
        if predictor is not None:
            history = state.get("sinr_history", [])
            # Rashed-Step 13.D-fix-08-23-2026-start
            if len(history) >= predictor.lag_k and len(set(history[-predictor.lag_k:])) > 1:
                predicted = predictor.predict_next(history, technology_is_wifi=0)
                return self._select_mcs_for_sinr(predicted)
            # Rashed-Step 13.D-fix-08-23-2026-end
        # Rashed-Step 13.D-08-23-2026-end
        return self._select_mcs_for_sinr(state["last_sinr_db"])

    @staticmethod
    def _select_mcs_for_sinr(sinr_db: float) -> int:
        """
        CQI-style direct selection: the HIGHEST mcs in NRU_MCS_SINR_
        THRESHOLDS_DB whose required threshold is <= sinr_db (the best
        rate this link can currently sustain). Falls back to the
        table's lowest mcs if even that isn't met (most robust rate
        available, same "don't crash on a bad link" spirit as mcs_
        sinr_threshold_db()'s own clamping behavior).
        """
        candidates = [mcs for mcs, thr in NRU_MCS_SINR_THRESHOLDS_DB.items() if thr <= sinr_db]
        if not candidates:
            return min(NRU_MCS_SINR_THRESHOLDS_DB.keys())
        return max(candidates)

    def rate_adapt_record_result(self, link_key: Optional[str], measured_sinr_db: float) -> None:
        """
        CQI-style feedback: call once per completed transmission
        attempt with the SINR that was actually measured for it -
        regardless of success/failure (CQI reflects channel quality,
        not a success/failure outcome; even a FAILED transmission's
        SINR is real information about the link). No-op when rate
        adaptation is disabled or link_key is None (keeps link_rate_
        state empty in that case - see current_mcs_for_link()).
        """
        if not self.config_nr.rate_adapt_enabled or link_key is None:
            return
        state = self.link_rate_state.setdefault(link_key, {"last_sinr_db": None})
        state["last_sinr_db"] = measured_sinr_db
        # Rashed-Step 13.D-08-23-2026-start
        # Short rolling history (oldest first, capped) - only actually
        # consulted when config_nr.sinr_predictor is set (see
        # current_mcs_for_link()); harmless extra bookkeeping otherwise.
        # Capped at 8 - comfortably more than any reasonable predictor's
        # lag_k (ml/train_sinr_model.LAG_K is 3 as of this writing)
        # without growing unbounded over a long run.
        history = state.setdefault("sinr_history", [])
        history.append(measured_sinr_db)
        del history[:-8]
        # Rashed-Step 13.D-08-23-2026-end
    # Rashed-Step 11.B-08-21-2026-end

    def sent_failed(self):
        # Rashed-Step 2.D_4-02-03-2026-start
        #log(self, "There was a collision")
        # Rashed-Step 5.D-02-06-2026-start
        log(self, f"TX failed (SINR < {self.required_sinr_db():.2f} dB)")
        # Rashed-Step 5.D-02-06-2026-end
        # Rashed-Step 2.D_4-02-03-2026-end
        self.transmission_to_send.number_of_retransmissions += 1
        self.channel.failed_transmissions_NR += 1
        self.failed_transmissions += 1
        self.failed_transmissions_in_row += 1
        log(self, self.channel.failed_transmissions_NR)
        # Rashed-Step 8.B-08-06-2026-start
        # number_of_retransmissions above is PER-Transmission_NR-OBJECT
        # and, since gen_new_transmission() creates a fresh
        # Transmission_NR every attempt, can never itself exceed 1 - the
        # OLD `> 7` check here compared THAT counter and was dead code
        # (found during Step 8.A's design, documented, left untouched at
        # the time). Step 8.D (below) replaces it with a check against
        # the persisted Packet's retry_count instead, which DOES
        # accumulate correctly across every retry within an episode
        # (same Packet object throughout, since Step 8.B).
        if self.transmission_to_send.packet is not None:
            self.transmission_to_send.packet.retry_count += 1
        # Rashed-Step 8.B-08-06-2026-end
        # Rashed-Step 8.D-08-06-2026-start
        # UPGRADE: real retry-limit + DROP now enforced, mirroring
        # wifi.WiFi.sent_failed()'s r_limit-exceeded handling. Checked
        # against the Packet's retry_count (persists across every
        # attempt in this episode - see above), not the old dead
        # per-Transmission_NR counter. If packet is None (only possible
        # via a direct/standalone call that explicitly passed packet=
        # None, not any real code path through start()), there is no
        # reliable persistent identity to limit on, so this falls back
        # to the prior (always-infinite-retry) behavior for that edge
        # case only - unchanged, not a regression.
        if (self.transmission_to_send.packet is not None
                and self.transmission_to_send.packet.retry_count > self.config_nr.r_limit):
            self.transmission_to_send.packet.status = "DROPPED"
            # Rashed-Step 8.G-08-06-2026-start
            self.packet_log.append(self.transmission_to_send.packet)
            # Rashed-Step 8.G-08-06-2026-end
            # Rashed-Step 8.E-08-06-2026-start
            # UPGRADE: used to synthesize the replacement immediately via
            # _make_packet() right here unconditionally, even in
            # poisson/cbr mode (same simplification wifi.WiFi.
            # sent_failed() had). Mirrors wifi.WiFi.sent_failed()'s split:
            # saturated mode keeps the exact old inline behavior
            # (_make_packet() has no randomness of its own for NR-U, so
            # this split isn't strictly required for byte-identical
            # output the way it IS for WiFi's generate_new_frame() - see
            # that method's comment - but kept symmetric/defensive
            # anyway, so a future change to _make_packet() can't
            # silently reintroduce the same class of reordering bug).
            # poisson/cbr mode defers to start()'s inner loop instead,
            # which genuinely blocks on the queue via _next_packet(),
            # AFTER send_transmission() has fully finished this attempt's
            # own bookkeeping (unregister_tx, etc.) - not from inside it.
            if self.traffic_config.mode == "saturated":
                self.current_packet = self._make_packet()
            else:
                self._need_new_packet = True
            # Rashed-Step 8.E-08-06-2026-end
            self.failed_transmissions_in_row = 0
        # Rashed-Step 8.D-08-06-2026-end

    def sent_completed(self):
        log(self, f"Successfully sent transmission")
        self.transmission_to_send.t_end = self.env.now
        self.transmission_to_send.t_to_send = (
            self.transmission_to_send.t_end - self.transmission_to_send.t_start)
        self.channel.succeeded_transmissions_NR += 1
        self.succeeded_transmissions += 1
        self.failed_transmissions_in_row = 0
        # Rashed-Step 8.B-08-06-2026-start
        if self.transmission_to_send.packet is not None:
            self.transmission_to_send.packet.status = "DELIVERED"
            self.transmission_to_send.packet.delivered_at = self.env.now
            # Rashed-Step 8.G-08-06-2026-start
            self.packet_log.append(self.transmission_to_send.packet)
            # Rashed-Step 8.G-08-06-2026-end
        # Rashed-Step 8.B-08-06-2026-end
        return True

    


