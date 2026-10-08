
from common.common import *
from Times import *
from common.common import Pos
# Rashed-Step 2.D_1-01-08-2026-start
from common.common_phy import dist, rx_power_dbm

# Rashed-Step 2.D_1-01-08-2026-end


# Rashed-Step 3.D-01-12-2026-start
from channel.channel import ActiveTx
# Rashed-Step pre_18.D-10-05-2026-start
from ran.protocol.channel_access import DcfChannelAccess
_DCF_ACCESS = DcfChannelAccess(Times.t_slot, Times.t_difs)
# Rashed-Step pre_18.D-10-05-2026-end
# Rashed-Step 3.D-01-12-2026-end

# Rashed-Step 5.D-02-06-2026-start
from common.common_phy import mcs_sinr_threshold_db
from Times import WIFI_MCS_SINR_THRESHOLDS_DB
from typing import Optional
# Rashed-Step 18.A-10-06-2026-start
from common.error_model import decode_ok
# Rashed-Step 20.A-10-08-2026-start
from wifi import mac as wifi_mac
# Rashed-Step 20.B-10-08-2026-start
from wifi import ampdu as wifi_ampdu
# Rashed-Step 20.B-10-08-2026-end
# Rashed-Step 20.A-10-08-2026-end
# Rashed-Step 18.A-10-06-2026-end
# Rashed-Step 5.D-02-06-2026-end
# Rashed-Step 5.G-02-06-2026-start
from typing import Any
# Rashed-Step 5.G-02-06-2026-end
# Rashed-Step 8.B-08-06-2026-start
from common.packet import Packet, TrafficConfig
# Rashed-Step 10.A-08-07-2026-start
from common.packet import pick_traffic_class
# Rashed-Step 10.A-08-07-2026-end
# Rashed-Step 10.B-08-07-2026-start
from common.packet import QOS_TRAFFIC_CLASSES, traffic_class_priority_rank, EdcaAcParams, DEFAULT_EDCA_PARAMS
# Rashed-Step 10.B-08-07-2026-end
# Rashed-Step 8.B-08-06-2026-end





@dataclass()
class Config:
    data_size: int = 1472  # size od payload in b
    cw_min: int = 15  # min cw window size
    cw_max: int = 63  # max cw window size 1023 def
    r_limit: int = 7
    mcs: int = 7

    # Rashed-Step 2.C_1-01-12-2026-start
    tx_power_dbm: float = 20.0 
    f_ghz: float = 5.18e9
    pl_exp : float = 3.0        #indoor-ish
    # Rashed-Step 2.C_1-12-26-2025-end

    # Rashed-Step 3.A-01-12-2026-start
    ed_threshold_dbm: float = -62.0   # energy detect threshold 
    # Rashed-Step pre_20.A-10-08-2026-start
    # 802.11 preamble detection (pre_20.A): Wi-Fi defers to Wi-Fi-
    # decodable frames from this level (-82 dBm), to anything else from
    # ed_threshold_dbm. None (default) = the single ed_threshold_dbm
    # rule for everything, as in every earlier run.
    preamble_detect_dbm: Optional[float] = None
    # Rashed-Step pre_20.B-10-08-2026-start
    # A-MPDU aggregation (pre_20.B, AP downlink, DCF path; since 20.B also
    # EDCA per access category and STA uplink - wifi/ampdu.py): up to this many
    # MPDUs per channel access, in one PPDU of at most ampdu_max_ppdu_us
    # (802.11 aPPDUMaxTime, 5.484 ms); per-MPDU decoding + Block Ack.
    # 1 (default) = one frame per access, as in every earlier run.
    ampdu_max_mpdus: int = 1
    ampdu_max_ppdu_us: float = 5484.0
    # Rashed-Step pre_20.B-10-08-2026-end
    # Rashed-Step 20.A-10-08-2026-start
    # 802.11 frame exchange on the air (Step 20.A, wifi/mac.py): ACK /
    # Block Ack transmitted after SIFS by the receiver, NAV from every
    # decoded frame, EIFS after an undecoded one. rts_threshold_bytes:
    # RTS/CTS before data whose payload exceeds it (None = never; needs
    # mac_exchange). False (default) = ACK time only waited out, as in
    # every earlier run.
    mac_exchange: bool = False
    rts_threshold_bytes: Optional[int] = None
    # Rashed-Step 20.A-10-08-2026-end
    # Rashed-Step pre_20.A-10-08-2026-end
    # Rashed-Step 3.A-01-12-2026-end

    # Rashed-Step 4.D_1-01-28-2026-start
    # Rashed-Step 5.D-02-06-2026-start
    # BUGFIX+UPGRADE: the old `wifi_sinr_thr_db = 10.0` had no type
    # annotation, so it was NOT actually a dataclass field - Config(...)
    # could never set it, every instance silently used the class-level
    # 10.0 no matter what. Given a real annotation now and repurposed as
    # an explicit override: None (default) means "look up the required
    # SINR for `mcs` in WIFI_MCS_SINR_THRESHOLDS_DB"; set it to force a
    # flat threshold instead.
    wifi_sinr_thr_db_override: Optional[float] = None
    # Rashed-Step 5.D-02-06-2026-end
    # Rashed-Step 4.D_1-01-28-2026-end

    # Rashed-Step 5.C-02-06-2026-start
    # Receiver-side noise params, used to derive the SINR noise floor
    # (see common_phy.thermal_noise_dbm) instead of the old hardcoded
    # -94.0 dBm constant. 20 MHz matches the legacy-OFDM rate table in
    # Times.py; 7 dB NF is a typical Wi-Fi NIC value. Together they land
    # right back at ~-94 dBm by default.
    bandwidth_mhz: float = 20.0
    noise_figure_db: float = 7.0
    # Rashed-Step 5.C-02-06-2026-end

    # Rashed-Step 10.B-08-07-2026-start
    # False (default) = legacy single-CW/DIFS DCF contention, the exact
    # code path (start()/wait_back_off()/send_frame()/sent_completed()/
    # sent_failed()) every run before this step used - completely
    # untouched by this flag, so unset is byte-identical to every
    # pre-Step-10.B run. True switches this AP onto the parallel EDCA
    # code path (start_edca() and friends) instead - see WiFi class
    # docstring for the full scope (Wi-Fi only, SATURATED TRAFFIC ONLY
    # for this first cut - see that docstring for why poisson/cbr EDCA
    # is deliberately deferred).
    qos_enabled: bool = False
    # None (default) = DEFAULT_EDCA_PARAMS (the real 802.11e/WMM
    # standard AC_VO/AC_VI/AC_BE/AC_BK values). Only read when
    # qos_enabled is True. Set to override per-AC CWmin/CWmax/AIFSN
    # (e.g. for an experiment comparing against non-standard values) -
    # no CLI flag for this yet, programmatic-only for this first cut.
    edca_params: Optional[Dict[str, EdcaAcParams]] = None
    # Rashed-Step 10.B-08-07-2026-end

    # Rashed-Step 11.A-08-21-2026-start
    # Dynamic rate adaptation (Step 11) - ARF-style (Kamerman & Monteban
    # 1997): step MCS up after N consecutive successes, down after M
    # consecutive failures, tracked per associated STA. False (default)
    # = self.config.mcs is used exactly as before this step (fixed for
    # the whole run) - zero behavior change, zero new state touched.
    # See "Project details/Step 11.txt" for the full design.
    rate_adapt_enabled: bool = False
    # 10 consecutive successes -> step up one MCS. This is the classic
    # ARF "probe a faster rate" threshold from the original paper.
    rate_adapt_up_streak: int = 10
    # 2 consecutive failures -> step down one MCS. The original 1997
    # ARF paper uses 1-2 depending on variant; 2 avoids a single unlucky
    # SINR dip immediately crashing the rate (a documented refinement).
    rate_adapt_down_streak: int = 2
    # Rashed-Step 11.A-08-21-2026-end

    # Rashed-Step 13.E.1-08-23-2026-start
    # Opt-in ML-driven MCS selection, mirroring Config_NR.sinr_predictor
    # (Step 13.D). None (default) = ARF's streak-based up/down logic
    # exactly as Step 11.A left it - zero behavior change. When set (a
    # duck-typed object exposing .lag_k/.predict_next(), see
    # ml/predictor.py's SinrPredictor), current_mcs_for_link() switches
    # this link to a CQI-style direct SINR-threshold lookup on the
    # predictor's PREDICTED next SINR instead, once enough history
    # exists - bypassing the streak counters entirely while active (the
    # two are alternate MCS-selection modes for the same link, not
    # blended - see "Project details/Step 13.txt"'s 13.E section for
    # the full rationale). Kept as Any (not a real type import) so
    # wifi.py never needs to import sklearn/pandas/joblib itself, same
    # zero-cost-when-unused convention as nru.py's field.
    sinr_predictor: Any = None
    # Rashed-Step 13.E.1-08-23-2026-end

    # Rashed-Step 18.A-10-06-2026-start
    # Shared BlerErrorModel (common/error_model.py), also used by this
    # AP's STAs. None (default) = the hard "SINR >= threshold" rule,
    # byte-identical to every earlier run.
    error_model: Any = None
    # Rashed-Step 18.A-10-06-2026-end



class WiFi:
    # Rashed-Step 10.B-08-07-2026-start
    """
    Step 10.B: EDCA (802.11e differentiated channel access) - opt-in via
    Config.qos_enabled (default False = legacy single-CW/DIFS DCF,
    completely unchanged).

    SCOPE (confirmed with Rashed via AskUserQuestion before starting):
    Wi-Fi only (802.11e is a real, documented standard; NR-U's
    unlicensed LBT has no standardized QoS-differentiation equivalent -
    left single-priority). Faithful per-AC virtual contention (not a
    simplified single-queue priority scheme) - each of the 4 traffic
    classes (voice/video/best_effort/background, i.e. AC_VO/AC_VI/
    AC_BE/AC_BK) gets its OWN CWmin/CWmax/AIFSN and its own independent
    backoff state, with "virtual collision" resolving ties exactly like
    the real spec: when 2+ ACs' contention windows expire in the same
    instant, the highest-priority one wins and actually transmits; the
    losers grow their CW as if they'd suffered a real collision, but
    their PACKET's retry_count is NOT incremented (no real over-the-air
    attempt happened, so there's no risk of the peer ever seeing a
    duplicate - this is a genuine, deliberate distinction from an
    actual SINR/collision failure, not an oversight).

    IMPLEMENTATION CHOICE: a SINGLE unified SimPy process
    (start_edca()/wait_back_off_edca()) manages all 4 ACs' AIFS+backoff
    countdown together in one synchronous loop, rather than 4
    independent racing SimPy processes. This is a deliberate choice,
    not a shortcut: 4 independent processes resuming at the exact same
    env.now would need a separate cross-process synchronization barrier
    to resolve virtual collisions correctly and deterministically, and
    this project has hit real regressions before from subtle same-
    instant SimPy scheduling-order effects (see Step 8.E). A single
    process stepping all 4 counters together sidesteps that whole class
    of risk while still being functionally faithful to the spec - this
    is genuinely how one radio's MAC has to arbitrate 4 internal queues
    against ONE shared physical channel anyway. Steps in 1us increments
    throughout (both AIFS and backoff-slot phases, unlike the legacy
    single-queue path's slot-sized backoff steps) so multiple
    differently-timed AC countdowns can be advanced in lockstep - more
    SimPy events than the legacy path, not a correctness concern at
    this simulator's scale (the same 1us-stepping already happens
    throughout every DIFS wait in the legacy path today). Freeze-on-
    busy semantics match the legacy wait_back_off()'s own established
    (simplified vs. the exact spec, but already-validated-against-
    Bianchi - see Step 6.A) convention: a busy channel pauses and
    RESUMES a countdown from wherever it was, it does not force a full
    AIFS restart - kept consistent with the existing engine rather than
    "fixed" to be more spec-pure, since that would be an unrelated,
    out-of-scope behavioral change to already-validated non-EDCA logic.

    Step 20.B UPDATE: poisson/cbr traffic now works with EDCA (one queue
    per AC, an AC contends only while backlogged - _start_edca_queued),
    and with Config.ampdu_max_mpdus > 1 each won access carries an A-MPDU
    from that AC, capped by its TXOP limit (wifi/ampdu.py). The first and
    second items below are therefore historical (one PPDU per TXOP is
    still the model - no multi-PPDU bursting).

    NOT YET SUPPORTED (raises ValueError at construction if attempted -
    see __init__):
      - traffic_config.mode other than "saturated". EDCA-saturated
        means all 4 ACs are ALWAYS treated as having a fresh packet
        ready (4 simultaneous saturated sub-flows, one per AC) -
        deliberately IGNORES traffic_class_mix (that field only governs
        which single shared queue a legacy-DCF AP's packets are tagged
        into, per Step 10.A) - this is the standard way EDCA
        differentiation is evaluated in the literature (Bianchi-EDCA-
        style per-AC saturation analysis) and the cleanest, most
        tractable first cut. Real per-AC ARRIVAL-DRIVEN queueing
        (poisson/cbr traffic routed into 4 independent queues, an AC
        only contending once it actually has something queued) is a
        real, meaningfully different piece of complexity - deferred to
        a follow-up, not started here.
      - TXOP bursting (a station transmitting multiple frames per won
        contention opportunity) - single-frame-per-opportunity only,
        matching every other technology in this simulator.
      - No CLI-level per-AC CWmin/CWmax/AIFSN overrides yet - only the
        on/off --wifi-edca flag; Config.edca_params is programmatically
        overridable but not yet exposed per-parameter via CLI.
      - The diagnostic-only channel.backoffs histogram (drawn-slot ->
        count, used for "future analyzes" per its own comment) is not
        populated by EDCA's backoff draws - it's indexed for a single
        shared CW range, incompatible with 4 differently-ranged per-AC
        distributions; a per-AC version could be added later if wanted.
    """
    # Rashed-Step 10.B-08-07-2026-end

    def __init__(
            self,
            env: simpy.Environment,
            name: str,
            channel: dataclass,
            # Rashed-Step 1.C_1-01-12-2026-start
            pos: Pos,
            sta_list: list,
            # Rashed-Step 1.C_1-01-12-2026-start
            config: Config,
            # Rashed-Step 5.G-02-06-2026-start
            mobility: Optional[Any] = None,
            # Rashed-Step 5.G-02-06-2026-end
            # Rashed-Step 8.B-08-06-2026-start
            # None (default) is normalized to TrafficConfig(mode=
            # "saturated") below - every existing caller that doesn't
            # know about this yet (simulation.py, every standalone
            # test/*.py file) gets exactly today's always-has-a-frame-
            # ready behavior, unchanged.
            traffic_config: Optional[TrafficConfig] = None
            # Rashed-Step 8.B-08-06-2026-end
    ):
        self.config = config
        self.times = Times(config.data_size, config.mcs)  # using Times script to get time calculations
        # Rashed-Step 11.A-08-21-2026-start
        # Per-STA rate-adaptation state (see Config.rate_adapt_enabled).
        # Keyed by STA name, lazily populated on first use - empty dict
        # costs nothing when rate adaptation is disabled (the default).
        self.link_rate_state: Dict[str, Dict[str, int]] = {}
        # Rashed-Step 11.A-08-21-2026-end
        self.name = name  # name of the station
        self.env = env  # simpy environment
        self.col = random.choice(colors)  # color of output -- for future station distinction
        self.frame_to_send = None  # the frame object which is next to send
        self.succeeded_transmissions = 0  # all succeeded transmissions for station
        self.failed_transmissions = 0  # all failed transmissions for station
        self.failed_transmissions_in_row = 0  # all failed transmissions for station in a row
        self.cw_min = config.cw_min  # cw min parameter value
        self.cw_max = config.cw_max  # cw max parameter value
        self.channel = channel  # channel obj

        # Rashed-Step 8.B-08-06-2026-start
        # Queue + arrival-process state. self.packet_queue is
        # constructed unconditionally (cheap - an unused simpy.Store
        # costs nothing) but is only ever actually touched when
        # traffic_config.mode != "saturated" - see _next_packet()/
        # _traffic_generator() below. In saturated mode (the default),
        # packets are synthesized on demand instead, so this AP never
        # contends for the channel any differently than it did before
        # Step 8.B.
        self.traffic_config = traffic_config if traffic_config is not None else TrafficConfig(mode="saturated")
        self.packet_queue = simpy.Store(env)
        self._packet_seq = 0
        if self.traffic_config.mode != "saturated":
            env.process(self._traffic_generator())
        # Rashed-Step 8.B-08-06-2026-end

        # Rashed-Step 8.F-08-06-2026-start
        # Separate counter from _packet_seq so ACK packet_ids never
        # collide with (or get confused for) data packet_ids.
        self._ack_seq = 0
        # Rashed-Step 8.F-08-06-2026-end

        # Rashed-Step 8.E-08-06-2026-start
        # Set by sent_failed() when the retry limit is exceeded; consumed
        # by start()'s inner retry loop, which then blocks on
        # _next_packet() for a real replacement before contending for
        # the channel again. See sent_failed()'s comment for why this is
        # a flag instead of sent_failed() blocking directly.
        self._need_new_packet = False
        # Rashed-Step 8.E-08-06-2026-end

        # Rashed-Step 8.G-08-06-2026-start
        # Every DATA packet this AP has finished with (DELIVERED or
        # DROPPED - never PENDING), appended by sent_completed()/
        # sent_failed(). Feeds common.packet.compute_packet_stats() for
        # the latency/loss report printed at the end of simulation.py's
        # run_simulation(). Note: this keeps every such Packet object
        # alive for the whole run (a real, if modest, memory cost on
        # very long/high-rate runs) - acceptable for this simulator's
        # scale; a future step could cap/roll this off if it ever
        # matters.
        self.packet_log = []
        # Rashed-Step pre_20.B-10-08-2026-start
        self.ampdu_stats = {"ppdus": 0, "mpdus": 0, "mpdus_ok": 0, "header_lost": 0}  # = wifi_ampdu.new_stats()
        # Rashed-Step 20.A-10-08-2026-start
        self.mac_stats = wifi_mac.new_stats()
        # Rashed-Step 20.A-10-08-2026-end
        # Rashed-Step pre_20.B-10-08-2026-end
        # Rashed-Step 8.G-08-06-2026-end

        # Rashed-Step 10.B-08-07-2026-start
        # EDCA (qos_enabled=True) state - see WiFi class docstring for
        # the full design. Constructed unconditionally (cheap, same
        # "unused cost nothing" reasoning as self.packet_queue above)
        # but only ever touched by the EDCA code path.
        self.edca_params = config.edca_params if config.edca_params is not None else DEFAULT_EDCA_PARAMS
        self.ac_frame_to_send: Dict[str, Optional[Frame]] = {ac: None for ac in QOS_TRAFFIC_CLASSES}
        self.ac_failed_in_row: Dict[str, int] = {ac: 0 for ac in QOS_TRAFFIC_CLASSES}
        # Rashed-Step 20.B-10-08-2026-start
        # EDCA with poisson/cbr traffic (Step 20.B): arrivals go into one queue
        # per access category (by the packet's traffic class); an AC contends
        # only while it has something queued. A-MPDU retransmissions wait per
        # AC in ac_pending. (Before 20.B this combination raised ValueError.)
        self.ac_queue: Dict[str, list] = {ac: [] for ac in QOS_TRAFFIC_CLASSES}
        self.ac_pending: Dict[str, list] = {ac: [] for ac in QOS_TRAFFIC_CLASSES}
        self._ac_arrival = env.event()
        # Rashed-Step 20.B-10-08-2026-end
        # Rashed-Step 10.B-08-07-2026-end

        if config.qos_enabled:
            # Rashed-Step 10.B-08-07-2026-start
            env.process(self.start_edca())
            # Rashed-Step 10.B-08-07-2026-end
        else:
            env.process(self.start())  # starting simulation process
        self.process = None  # waiting back off process
        self.channel.airtime_data.update({name: 0})
        self.channel.airtime_control.update({name: 0})
        self.first_interrupt = False
        self.back_off_time = 0
        self.start = 0

        # Rashed-Step 1.C_1-01-12-2026-start
        self.pos = pos
        self.sta_list = sta_list
        # Rashed-Step 1.C_1-01-12-2026-end
        # Rashed-Step 15.B-09-18-2026-start
        # Back-reference each associated STA to this AP object, so a STA
        # whose uplink_enabled=True (see wifi/sta.py's WiFiSTA) can
        # compute a real rx_pos/rx_name against wherever this AP
        # currently is (its own current_pos(), mobility-aware) when it
        # actually transmits an uplink frame - the STA has no other way
        # to reach this AP object, since every simulation*.py caller
        # still builds a STA's stas_for_ap list BEFORE constructing the
        # WiFi AP that owns it (unchanged - this is purely additive, not
        # a construction-order change). A no-op assignment (None ->
        # this AP) for every STA that doesn't use uplink, i.e. byte-
        # identical to every pre-15.B run.
        for sta in self.sta_list:
            sta.ap = self
        # Rashed-Step 15.B-09-18-2026-end
        # Rashed-Step 5.G-02-06-2026-start
        self.mobility = mobility
        # Rashed-Step 5.G-02-06-2026-end


        # Rashed-Step 4.C_2-01-21-2026-start
        self.sinr_print_ctr = 0
        # Rashed-Step 4.C_2-01-21-2026-end

    # Rashed-Step 5.G-02-06-2026-start
    def current_pos(self) -> Pos:
        """
        Current interpolated position if mobility is enabled (see
        common_phy.WaypointMobility), else the static self.pos - byte-
        identical to every pre-5.G run when mobility is None (the
        default). All position reads that matter for CCA/collision
        physics (is_busy() sensing, tx_pos/rx_pos at actual transmission
        time) should go through this, not self.pos directly, so a moving
        AP's sensed/transmitted position is always "now", not "at
        construction time".
        """
        return self.mobility.pos_now() if self.mobility is not None else self.pos
    # Rashed-Step 5.G-02-06-2026-end

    # Rashed-Step 8.B-08-06-2026-start
    def _make_packet(self) -> Packet:
        """
        Synthesize a fresh Packet - used directly in saturated mode
        (bypasses the queue entirely, see _next_packet()) and by the
        traffic generator (poisson/cbr) to fill the queue. Payload size
        defaults to self.config.data_size (matching every pre-Step-8
        run exactly) unless traffic_config.packet_size_bytes overrides
        it. header_bytes uses Times.mac_overhead (the same 40-byte MAC
        header size the PHY duration formula already assumes), so
        total_bytes() is meaningful immediately rather than a
        placeholder - real per-technology header modeling is still a
        later sub-step, this just reuses the constant that already
        exists.
        """
        self._packet_seq += 1
        payload = self.traffic_config.packet_size_bytes if self.traffic_config.packet_size_bytes is not None else self.config.data_size
        destination = self.sta_list[0].name if self.sta_list else self.name
        # Rashed-Step 10.A-08-07-2026-start
        # None (default) = no random draw at all, plain "best_effort" -
        # see TrafficConfig.traffic_class_mix's docstring for why this
        # matters for RNG-footprint regression safety.
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
            header_bytes=Times.mac_overhead // 8,
            created_at=self.env.now,
            # Rashed-Step 10.A-08-07-2026-start
            traffic_class=traffic_class,
            # Rashed-Step 10.A-08-07-2026-end
        )

    # Rashed-Step 8.F-08-06-2026-start
    def _make_ack_packet(self, data_packet: Optional[Packet]) -> Packet:
        """
        Construct the ACK Packet sent back in response to a successfully
        delivered data_packet. Direction is reversed from the data
        packet: source is the receiving STA, destination is this AP.
        payload_bytes=0 (an ACK carries no payload); header_bytes uses
        Times.ack_size (14 bytes) - the same constant
        Times.get_ack_frame_time() already uses to compute the ACK's
        on-air duration, so total_bytes() is consistent with the timing
        model rather than an unrelated placeholder. Called only from
        sent_completed() (i.e. only when the data frame actually
        succeeded) - there is no ACK object for a failed transmission,
        matching real 802.11 semantics (the sender just times out
        waiting for one that was never sent).
        """
        self._ack_seq += 1
        rx_name = self.sta_list[0].name if self.sta_list else self.name
        return Packet(
            packet_id=f"{self.name}-ACK-{self._ack_seq:06d}",
            source=rx_name,
            destination=self.name,
            payload_bytes=0,
            header_bytes=Times.ack_size // 8,
            packet_type="ACK",
            created_at=self.env.now,
            # Rashed-Step 10.A-08-07-2026-start
            # Inherits the data packet's traffic_class - an ACK is part
            # of the same flow's QoS handling, not its own independent
            # class. Falls back to "best_effort" only in the
            # (non-real-world) case data_packet is None, matching
            # Packet.traffic_class's own default.
            traffic_class=data_packet.traffic_class if data_packet is not None else "best_effort",
            # Rashed-Step 10.A-08-07-2026-end
        )
    # Rashed-Step 8.F-08-06-2026-end

    def _next_packet(self):
        """
        Generator (SimPy-safe to `yield from` even though the saturated
        branch never actually yields - see module note in Step 8.txt).
        Saturated mode: returns a fresh Packet immediately, no queue
        involved - operationally identical to every pre-Step-8.B run,
        this AP is never idle waiting for "something to send".
        Poisson/cbr mode: blocks on self.packet_queue.get() until the
        traffic generator has produced one - this AP genuinely does not
        contend for the channel while its queue is empty.
        """
        if self.traffic_config.mode == "saturated":
            return self._make_packet()
        pkt = yield self.packet_queue.get()
        return pkt

    def _traffic_generator(self):
        """
        Only started (in __init__) when traffic_config.mode !=
        "saturated". Produces Packets per a Poisson process
        (exponential inter-arrival, mean = 1/arrival_rate_pps seconds)
        or CBR (fixed inter-arrival = 1/arrival_rate_pps seconds) and
        pushes them into self.packet_queue.
        """
        while True:
            if self.traffic_config.mode == "poisson":
                interval_us = random.expovariate(self.traffic_config.arrival_rate_pps / 1e6)
            else:  # "cbr"
                interval_us = 1e6 / self.traffic_config.arrival_rate_pps
            yield self.env.timeout(interval_us)
            # Rashed-Step 20.B-10-08-2026-start
            if self.config.qos_enabled:
                pkt = self._make_packet()
                self.ac_queue[pkt.traffic_class].append(pkt)
                if not self._ac_arrival.triggered:
                    self._ac_arrival.succeed()
                self._ac_arrival = self.env.event()
                continue
            # Rashed-Step 20.B-10-08-2026-end
            yield self.packet_queue.put(self._make_packet())
    # Rashed-Step 8.B-08-06-2026-end

    # Rashed-Step 10.B-08-07-2026-start
    # ------------------------------------------------------------------
    # EDCA (qos_enabled=True) - see WiFi class docstring for full scope.
    # ------------------------------------------------------------------
    def _make_packet_for_ac(self, ac: str) -> Packet:
        """
        Like _make_packet(), but FORCES traffic_class=ac directly - no
        pick_traffic_class()/traffic_class_mix draw at all (no random
        call, deterministic), since in EDCA-saturated mode the AC this
        packet belongs to is already decided by which per-AC "slot"
        called this - see class docstring on why traffic_class_mix is
        deliberately ignored here.
        """
        self._packet_seq += 1
        payload = self.traffic_config.packet_size_bytes if self.traffic_config.packet_size_bytes is not None else self.config.data_size
        destination = self.sta_list[0].name if self.sta_list else self.name
        return Packet(
            packet_id=f"{self.name}-{ac}-{self._packet_seq:06d}",
            source=self.name,
            destination=destination,
            payload_bytes=payload,
            header_bytes=Times.mac_overhead // 8,
            created_at=self.env.now,
            traffic_class=ac,
        )

    def _refresh_ac_frame(self, ac: str):
        """Synthesize a fresh packet+frame for AC `ac` and store it as
        that AC's pending transmission - called once at EDCA startup for
        every AC (all 4 start saturated) and again each time an AC's
        current packet reaches a terminal state (DELIVERED or DROPPED -
        see sent_completed_edca()/sent_failed_edca())."""
        packet = self._make_packet_for_ac(ac)
        frame = self.generate_new_frame(packet)
        frame.packet = packet
        self.ac_frame_to_send[ac] = frame

    def generate_new_back_off_slots_edca(self, ac: str) -> int:
        """
        Same CW-growth formula as generate_new_back_off_slots() (kept
        IDENTICAL on purpose, for consistency with the already-Bianchi-
        validated non-EDCA model - see Step 6.A), just parametrized by
        AC `ac`'s own cw_min/cw_max (from self.edca_params) and its own
        independent ac_failed_in_row[ac] counter instead of the single
        shared cw_min/cw_max/failed_transmissions_in_row the legacy path
        uses. Deliberately does NOT write into self.channel.backoffs
        (that diagnostic histogram is indexed for one shared CW range -
        see class docstring's NOT YET SUPPORTED list).
        """
        params = self.edca_params[ac]
        failed = self.ac_failed_in_row[ac]
        upper_limit = pow(2, failed) * (params.cw_min + 1) - 1
        upper_limit = upper_limit if upper_limit <= params.cw_max else params.cw_max
        return random.randint(0, upper_limit)

    def wait_back_off_edca(self):
        """
        Single unified contention episode across every AC that currently
        has a pending frame (self.ac_frame_to_send[ac] is not None) -
        see class docstring's "IMPLEMENTATION CHOICE" section for why
        this is one process stepping 4 counters together rather than 4
        independent racing processes. Returns the AC that won this
        episode (its contention window expired first; ties broken by
        traffic_class_priority_rank - lower rank wins). Every OTHER AC
        whose window ALSO expired in the same instant (a "virtual
        collision") has its ac_failed_in_row grown here before this
        returns - the caller only needs to actually transmit for the
        winner.
        """
        remaining_us = {}
        for ac, frame in self.ac_frame_to_send.items():
            if frame is None:
                continue
            params = self.edca_params[ac]
            aifs_us = Times.get_aifs_us(params.aifsn)
            backoff_slots = self.generate_new_back_off_slots_edca(ac)
            remaining_us[ac] = aifs_us + backoff_slots * Times.t_slot

        while True:
            # Rashed-Step 20.B-10-08-2026-start
            if self.traffic_config.mode != "saturated":
                for ac in QOS_TRAFFIC_CLASSES:          # newly non-empty ACs start their AIFS + backoff
                    if ac not in remaining_us:
                        self._edca_refresh(ac)
                        if self.ac_frame_to_send[ac] is not None:
                            remaining_us[ac] = (Times.get_aifs_us(self.edca_params[ac].aifsn)
                                                + self.generate_new_back_off_slots_edca(ac) * Times.t_slot)
            # Rashed-Step 20.B-10-08-2026-end
            if _DCF_ACCESS._busy(self):  # pre_20.A: same CCA as DCF (incl. preamble detection)
                log(self, "Channel busy during EDCA AIFS/backoff, waiting...")
                yield self.channel.state_changed
                continue
            step = 1
            yield self.env.timeout(step)
            finished = []
            for ac in remaining_us:
                remaining_us[ac] -= step
                if remaining_us[ac] <= 0:
                    finished.append(ac)
            if finished:
                winner = min(finished, key=traffic_class_priority_rank)
                for ac in finished:
                    if ac != winner:
                        # Virtual collision - CW grows exactly like a
                        # real one, but the packet itself is untouched
                        # (retry_count NOT incremented - no real
                        # transmission attempt happened). See class
                        # docstring.
                        self.ac_failed_in_row[ac] += 1
                return winner

    def send_frame_edca(self, ac: str):
        """
        Same structure/SINR-decision/GeneratorExit-safety as the legacy
        send_frame(), operating on self.ac_frame_to_send[ac] instead of
        self.frame_to_send, calling sent_completed_edca(ac)/
        sent_failed_edca(ac) instead of the plain ones. Kept as a fully
        separate method (not a parametrized shared helper) so the
        already-verified legacy path's code is never touched by this
        change at all - see class docstring.
        """
        # Rashed-Step 20.A-10-08-2026-start
        if self.config.mac_exchange and self.sta_list:
            return (yield from self._send_frame_mac(self.ac_frame_to_send[ac], lambda: self.sent_completed_edca(ac),
                                                    lambda: self.sent_failed_edca(ac)))
        # Rashed-Step 20.A-10-08-2026-end
        frame = self.ac_frame_to_send[ac]
        log(self, f'Starting sending frame (EDCA {ac}): {frame.frame_time}')
        tx_start = self.env.now
        tx_pos = self.current_pos()
        rx_pos = self.sta_list[0].current_pos() if self.sta_list else tx_pos
        tx = ActiveTx(
            tx_id=self.name,
            tx_pos=tx_pos,
            rx_pos=rx_pos,
            tx_start=tx_start,
            tx_power_dbm=self.config.tx_power_dbm,
            f_hz=self.config.f_ghz,
            pl_exp=self.config.pl_exp,
            t_end=tx_start + frame.frame_time,
            tech="WiFi",
            bandwidth_mhz=self.config.bandwidth_mhz,
            noise_figure_db=self.config.noise_figure_db,
            packet=frame.packet,
        )
        self.channel.register_tx(tx)

        was_sent = False
        try:
            yield self.env.timeout(frame.frame_time)
            sinr = self.channel.sinr_db(tx)
            # Rashed-Step 13.A-08-23-2026-start
            # Log measured SINR on the packet itself, success or
            # failure alike - see Packet.measured_sinr_db docstring.
            frame.packet.measured_sinr_db = sinr
            # Rashed-Step 13.A-08-23-2026-end
            required_sinr = self.required_sinr_db()
            log(self, f"TX->RX SINR(dB) = {sinr:.2f} dB, required (MCS {self.config.mcs}) = {required_sinr:.2f} dB (EDCA {ac})")
            # Rashed-Step 18.A-10-06-2026-start
            was_sent = decode_ok(getattr(self.config, "error_model", None), sinr, required_sinr)
            # Rashed-Step 18.A-10-06-2026-end
            # Rashed-Step 11.A-08-21-2026-start
            # Rashed-Step 13.E.1: also pass measured_sinr_db for the
            # predictor's rolling history (harmless no-op unless
            # config.sinr_predictor is set - see rate_adapt_record_result()).
            self.rate_adapt_record_result(self.rate_adapt_link_key(), was_sent, measured_sinr_db=sinr)
            # Rashed-Step 11.A-08-21-2026-end

            if was_sent:
                self.sent_completed_edca(ac)
            else:
                self.sent_failed_edca(ac)
            # Same same-instant-tie-break courtesy zero-duration yield as
            # the legacy send_frame() - see its own comment.
            yield self.env.timeout(0)
            self.channel.unregister_tx(tx, success=was_sent)
        except BaseException:
            # Same GeneratorExit-safe pattern as the legacy send_frame() -
            # see its own comment (Step 5.I).
            self.channel.unregister_tx(tx, success=was_sent)
            raise

        if was_sent:
            self.channel.airtime_control[self.name] += self.times.get_ack_frame_time()
            yield self.env.timeout(self.times.get_ack_frame_time())
            if frame.ack_packet is not None:
                frame.ack_packet.status = "DELIVERED"
                frame.ack_packet.delivered_at = self.env.now
            return True
        else:
            yield self.env.timeout(self.times.ack_timeout)
            return False

    def sent_failed_edca(self, ac: str):
        """Same structure as the legacy sent_failed(), keyed by AC. A
        REAL failed attempt (SINR too low / lost an over-the-air
        collision) - unlike a virtual-collision loss (see
        wait_back_off_edca()), this DOES increment the packet's own
        retry_count, matching real semantics: an actual frame really
        was put on the air this time."""
        frame = self.ac_frame_to_send[ac]
        log(self, f"There was a collision (EDCA {ac})")
        frame.number_of_retransmissions += 1
        self.channel.failed_transmissions += 1
        self.failed_transmissions += 1
        self.ac_failed_in_row[ac] += 1
        if frame.packet is not None:
            frame.packet.retry_count = frame.number_of_retransmissions
        if frame.number_of_retransmissions > self.config.r_limit:
            if frame.packet is not None:
                frame.packet.status = "DROPPED"
                self.packet_log.append(frame.packet)
            # Rashed-Step 20.B-10-08-2026-start
            if self.traffic_config.mode == "saturated":
                self._refresh_ac_frame(ac)
            else:
                self.ac_frame_to_send[ac] = None   # next queued packet, if any (start_edca)
            # Rashed-Step 20.B-10-08-2026-end
            self.ac_failed_in_row[ac] = 0

    def sent_completed_edca(self, ac: str):
        """Same structure as the legacy sent_completed(), keyed by AC."""
        frame = self.ac_frame_to_send[ac]
        log(self, f"Successfully sent frame, waiting ack: {self.times.get_ack_frame_time()} (EDCA {ac})")
        frame.t_end = self.env.now
        frame.t_to_send = (frame.t_end - frame.t_start)
        self.channel.succeeded_transmissions += 1
        self.succeeded_transmissions += 1
        self.ac_failed_in_row[ac] = 0
        self.channel.bytes_sent += frame.data_size
        if frame.packet is not None:
            frame.packet.status = "DELIVERED"
            frame.packet.delivered_at = self.env.now
            self.packet_log.append(frame.packet)
        # Reuse the exact same ACK-construction method the legacy path
        # uses (_make_ack_packet(), Step 8.F) rather than duplicating its
        # field logic here - one source of truth for ACK shape/traffic-
        # class inheritance across both paths.
        frame.ack_packet = self._make_ack_packet(frame.packet)
        # Fresh packet+frame is picked up for this AC once this delivery
        # is fully done (send_frame_edca() has already returned True by
        # the time the caller loops back) - see start_edca().

    def start_edca(self):
        """
        Top-level EDCA driving loop - see class docstring for full
        scope. Saturated-only: every AC always has a pending frame, so
        this never blocks waiting for "something to send" the way the
        poisson/cbr legacy path can.
        """
        # Rashed-Step 20.B-10-08-2026-start
        if self.traffic_config.mode != "saturated" or self.config.ampdu_max_mpdus > 1:
            yield from self._start_edca_queued()
            return
        # Rashed-Step 20.B-10-08-2026-end
        for ac in QOS_TRAFFIC_CLASSES:
            self._refresh_ac_frame(ac)
        while True:
            winner = yield from self.wait_back_off_edca()
            was_sent = yield self.env.process(self.send_frame_edca(winner))
            # A fresh packet+frame is needed for `winner` whenever its
            # CURRENT one reached a terminal state this attempt -
            # DELIVERED (was_sent) or DROPPED (retry limit just
            # exceeded, handled inside sent_failed_edca() via
            # _refresh_ac_frame()). A real failure that's still under
            # the retry limit keeps the SAME frame/packet for its next
            # attempt (retry_count already bumped) - exactly like the
            # legacy path's retry semantics.
            if was_sent:
                self._refresh_ac_frame(winner)
    # Rashed-Step 10.B-08-07-2026-end

    # Rashed-Step 20.B-10-08-2026-start
    def _edca_head(self, ac):
        """Next packet for AC ac without waiting: a new one (saturated) or
        the queue's head, or None."""
        if self.traffic_config.mode == "saturated":
            return self._make_packet_for_ac(ac)
        return self.ac_queue[ac].pop(0) if self.ac_queue[ac] else None

    def _edca_refresh(self, ac):
        """Make sure AC ac has a contending frame if it has anything to
        send. With A-MPDU the frame only stands for the AC's head packet
        in contention; the PPDU itself is built when the AC wins."""
        if self.ac_frame_to_send[ac] is not None:
            return
        if self.config.ampdu_max_mpdus > 1:
            if not self.ac_pending[ac]:
                p = self._edca_head(ac)
                if p is not None:
                    self.ac_pending[ac] = [p]
            head = self.ac_pending[ac][0] if self.ac_pending[ac] else None
        else:
            head = self._edca_head(ac)
        if head is not None:
            frame = self.generate_new_frame(head)
            frame.packet = head
            self.ac_frame_to_send[ac] = frame

    def _start_edca_queued(self):
        """EDCA driving loop for poisson/cbr traffic (per-AC queues) and/or
        A-MPDU (per-AC aggregation within the AC's TXOP limit, wifi/ampdu.py).
        Same contention (wait_back_off_edca) as the saturated loop."""
        agg = self.config.ampdu_max_mpdus > 1
        while True:
            for ac in QOS_TRAFFIC_CLASSES:
                self._edca_refresh(ac)
            if all(f is None for f in self.ac_frame_to_send.values()):
                yield self._ac_arrival
                continue
            winner = yield from self.wait_back_off_edca()
            if agg:
                header_us, per_mpdu = self._ampdu_times()
                put_back = (lambda p: None) if self.traffic_config.mode == "saturated" else \
                    (lambda p: self.ac_queue[winner].insert(0, p))
                mpdus = wifi_ampdu.build(self.ac_pending[winner], lambda: self._edca_head(winner), put_back,
                                         header_us, per_mpdu, self.config.ampdu_max_mpdus,
                                         wifi_ampdu.ppdu_budget_us(self, winner))
                rx_name, rx_pos = self._ampdu_rx()
                yield self.env.process(wifi_ampdu.send_any(self, mpdus, header_us, per_mpdu, rx_name, rx_pos,
                                                           ac=winner))
                self.ac_pending[winner] = wifi_ampdu.next_pending(self.ac_pending[winner], mpdus)
                self.ac_frame_to_send[winner] = None
            else:
                was_sent = yield self.env.process(self.send_frame_edca(winner))
                if was_sent:
                    self.ac_frame_to_send[winner] = None

    # Rashed-Step 20.B-10-08-2026-end
    def start(self):
        # Rashed-Step pre_20.B-10-08-2026-start
        if self.config.ampdu_max_mpdus > 1:
            yield from self._start_ampdu()
            return
        # Rashed-Step pre_20.B-10-08-2026-end
        # Rashed-Step 3.F-12-26-2025-start
        #print(self.env.now, self.name, "START LOOP")
        # Rashed-Step 3.F-12-26-2025-end
        while True:
            # Rashed-Step 8.B-08-06-2026-start
            # UPGRADE: used to unconditionally call generate_new_frame()
            # here, i.e. this AP always had a frame ready the instant it
            # got channel access ("saturated" traffic, implicit and
            # unconditional). Now goes through _next_packet() first -
            # in saturated mode (the default) that's still a same-tick,
            # non-blocking call (see _next_packet()'s docstring), so
            # this loop's timing is unchanged; in poisson/cbr mode this
            # AP now genuinely waits here, not contending for the
            # channel at all, until it actually has something to send.
            packet = yield from self._next_packet()
            # Rashed-Step 8.C-08-06-2026: pass packet through so frame
            # duration reflects its actual payload_bytes (see
            # generate_new_frame()'s docstring/comment).
            self.frame_to_send = self.generate_new_frame(packet)
            self.frame_to_send.packet = packet
            # Rashed-Step 8.B-08-06-2026-end
            was_sent = False
            while not was_sent:
                # Rashed-Step 8.E-08-06-2026-start
                # UPGRADE: sent_failed() (called inside the send_frame()
                # attempt below) sets this flag instead of directly
                # synthesizing a replacement packet when the retry limit
                # is exceeded. Checked at the top of every retry attempt
                # (not just once per episode) - this is exactly the
                # point, analogous to _next_packet() at the top of the
                # outer loop, where it's safe to block: send_frame() has
                # already fully finished the PREVIOUS attempt's own
                # bookkeeping (unregister_tx, ACK-timeout wait) before
                # returning was_sent=False, so waiting here for a new
                # packet doesn't delay that unrelated teardown. Saturated
                # mode: still a same-tick, non-blocking call. Poisson/
                # cbr mode: this AP now genuinely sits idle here, not
                # contending for the channel, until its queue actually
                # produces a replacement - closing the simplification
                # documented in Step 8.B/8.C where the replacement was
                # always synthesized immediately regardless of traffic
                # mode.
                if self._need_new_packet:
                    new_packet = yield from self._next_packet()
                    self.frame_to_send = self.generate_new_frame(new_packet)
                    self.frame_to_send.packet = new_packet
                    self._need_new_packet = False
                # Rashed-Step 8.E-08-06-2026-end
                self.process = self.env.process(self.wait_back_off())
                yield self.process
                # self.process = None
                was_sent = yield self.env.process(self.send_frame())
                # self.process = None

    
    # Rashed-Step 3.D-12-26-2025-start
    # def wait_back_off(self):
    #     #global start
    #     self.back_off_time = self.generate_new_back_off_time(
    #         self.failed_transmissions_in_row)  # generating the new Back Off time

    #     while self.back_off_time > -1:
    #         try:
    #             with self.channel.tx_lock.request() as req:  # waiting  for idle channel -- empty channel
    #                 yield req
    #             self.back_off_time += Times.t_difs  # add DIFS time
    #             log(self, f"Starting to wait backoff (with DIFS): ({self.back_off_time})u...")
    #             self.first_interrupt = True
    #             self.start = self.env.now  # store the current simulation time
    #             self.channel.back_off_list.append(self)  # join the list off stations which are waiting Back Offs

    #             yield self.env.timeout(self.back_off_time)  # join the environment action queue

    #             log(self, f"Backoff waited, sending frame...")
    #             self.back_off_time = -1  # leave the loop

    #             self.channel.back_off_list.remove(self)  # leave the waiting list as Backoff was waited successfully

    #         except simpy.Interrupt:  # handle the interruptions from transmitting stations
    #             if self.first_interrupt and self.start is not None:
    #                 #tak jest po mojemu:
    #                 log(self, "Waiting was interrupted, waiting to resume backoff...")
    #                 all_waited = self.env.now - self.start
    #                 if all_waited <= Times.t_difs:
    #                     self.back_off_time -= Times.t_difs
    #                     log(self, f"Interupted in DIFS ({Times.t_difs}), backoff {self.back_off_time}, already waited: {all_waited}")
    #                 else:
    #                     back_waited = all_waited - Times.t_difs
    #                     slot_waited = int(back_waited / Times.t_slot)
    #                     self.back_off_time -= ((slot_waited * Times.t_slot) + Times.t_difs)
    #                     log(self,
    #                         f"Completed slots(9us) {slot_waited} = {(slot_waited * Times.t_slot)}  plus DIFS time {Times.t_difs}")
    #                     log(self,
    #                         f"Backoff decresed by {((slot_waited * Times.t_slot) + Times.t_difs)} new Backoff {self.back_off_time}")
    #                 self.first_interrupt = False

        
    def wait_back_off(self):
        backoff_slots = self.generate_new_back_off_slots(self.failed_transmissions_in_row)
        # Rashed-Step pre_18.D-10-05-2026-start
        # DIFS + backoff now on the shared slot grid (ran/protocol/
        # channel_access.py DcfChannelAccess - see its docstring). The old
        # loop counted slots on this AP's own grid and only checked the
        # channel at the start of each slot, so it missed neighbours that
        # started a few microseconds earlier (~2x the DTMC model's Wi-Fi
        # collision rate). Same backoff draw as before.
        yield from _DCF_ACCESS.wait(self, backoff_slots)
        # Rashed-Step pre_18.D-10-05-2026-end

        log(self, f"Backoff waited, sending frame...")

        return


    # Rashed-Step 3.D-01-12-2026-end
    # Rashed-Step 3.F-01-13-2026-start
    # def send_frame(self):
    #     self.channel.tx_list.append(self)  # add station to currently transmitting list
    #     res = self.channel.tx_queue.request(
    #         priority=(big_num - self.frame_to_send.frame_time))  # create request basing on this station frame length

    #     try:
    #         result = yield res | self.env.timeout(
    #             0)  # try to hold transmitting lock(station with the longest frame will get this)
    #         if res not in result:  # check if this station got lock, if not just wait you frame time
    #             raise simpy.Interrupt("There is a longer frame...")


    #         with self.channel.tx_lock.request() as lock:  # this station has the longest frame so hold the lock
    #             yield lock

    #             # Rashed-Step 3.D-01-12-2026-start
    #             # for station in self.channel.back_off_list:  # stop all station which are waiting backoff as channel is not idle
    #             #     if station.process.is_alive:
    #             #         station.process.interrupt()
    #             # for gnb in self.channel.back_off_list_NR:  # stop all station which are waiting backoff as channel is not idle
    #             #     if gnb.process.is_alive:
    #             #         gnb.process.interrupt()
    #             # Rashed-Step 3.D-01-12-2026-end

    #             log(self, f'Starting sending frame: {self.frame_to_send.frame_time}')

    #             # Rashed-Step 2.E-01-08-2026-start
    #             if self.frame_to_send.pr_dbm is not None:
    #                 log(self, f"Frame TX pos: {self.frame_to_send.tx_pos}, RX pos: {self.frame_to_send.rx_pos}, Distance: {self.frame_to_send.distance_m} m, Pr: {self.frame_to_send.pr_dbm} dBm")
    #             # Rashed-Step 2.E-01-08-2026-end

    #             # Rashed-Step 3.D-12-26-2025-start
    #             tx_start = self.env.now
    #             tx_dur = self.frame_to_send.frame_time + self.times.get_ack_frame_time()

    #             tx_start = self.env.now
    #             tx = ActiveTx(
    #                 tx_id=self.name,
    #                 tx_pos=self.pos,
    #                 tx_start=tx_start,
    #                 tx_power_dbm=self.config.tx_power_dbm,
    #                 f_hz=self.config.f_ghz,
    #                 pl_exp=self.config.pl_exp,
    #                 t_end=tx_start + self.frame_to_send.frame_time,
    #                 tech="WiFi"
    #             )
    #             self.channel.register_tx(tx)
    #             # Rashed-Step 3.F-01-13-2026-start
    #             # yield self.env.timeout(self.frame_to_send.frame_time)  # wait this station frame time
    #             # self.channel.unregister_tx(tx)
    #             try:
    #                 yield self.env.timeout(self.frame_to_send.frame_time)
    #                 was_sent = self.check_collision()
    #             finally:
    #                 self.channel.unregister_tx(tx)


    #             # Rashed-Step 3.F-01-13-2026-end

    #             # Rashed-Step 3.D-12-26-2025-end
    #             #self.channel.back_off_list.clear()  # channel idle, clear backoff waiting list
    #             was_sent = self.check_collision()  # check if collision occurred

    #             if was_sent:  # transmission successful
    #                 self.channel.airtime_control[self.name] += self.times.get_ack_frame_time()
    #                 yield self.env.timeout(self.times.get_ack_frame_time())  # wait ack
    #                 # Rashed-Step 3.F-01-13-2026-start
    #                 #self.channel.tx_list.clear()  # clear transmitting list
    #                 #self.channel.tx_list_NR.clear()
    #                 # Rashed-Step 3.F-01-13-2026-end
                    
    #                 self.channel.tx_queue.release(res)  # leave the transmitting queue
    #                 return True
    #             # Rashed-Step 3.D-12-26-2025-start
    #             self.channel.unregister_tx(tx)
    #             # Rashed-Step 3.D-12-26-2025-end

    #             # there was collision
    #             self.channel.tx_list.clear()  # clear transmitting list
    #             self.channel.tx_list_NR.clear()
    #             self.channel.tx_queue.release(res)  # leave the transmitting queue
    #             self.channel.tx_queue = simpy.PreemptiveResource(self.env,
    #                                                              capacity=1)  # create new empty transmitting queue
    #             yield self.env.timeout(self.times.ack_timeout)  # simulate ack timeout after failed transmission
    #             return False

    #     except simpy.Interrupt:  # this station does not have the longest frame, waiting frame time
    #         yield self.env.timeout(self.frame_to_send.frame_time)

    #     was_sent = self.check_collision()

    #     if was_sent:  # check if collision occurred
    #         log(self, f'Waiting for ACK time: {self.times.get_ack_frame_time()}')
    #         yield self.env.timeout(self.times.get_ack_frame_time())  # wait ack
    #     else:
    #         log(self, "waiting ack timeout slave")
    #         yield self.env.timeout(Times.ack_timeout)  # simulate ack timeout after failed transmission
    #     return was_sent


    def send_frame(self):
        # Rashed-Step 6.A-07-31-2026-start
        # UPGRADE: this used to acquire self.channel.tx_queue (one
        # capacity-1 resource shared by every WiFi AP) before transmitting,
        # so no two WiFi APs could ever be "in flight" on the channel at
        # the same simulated instant - real 802.11 collisions (two
        # independent backoff counters hitting zero in the same slot) were
        # structurally impossible. This is the gap the realism validation
        # report (2026-07-31) flagged against Bianchi's DCF model: measured
        # PCOLL stayed at 0.0000 for N=1/5/20 stations while Bianchi
        # predicts 0%/22.7%/76.0%. wait_back_off() already does correct
        # per-station, per-slot channel sensing (freeze on busy, resume on
        # idle) independently for every AP, so removing the queue and
        # registering the transmission immediately lets two APs whose
        # backoff both hit zero in the same tick genuinely overlap on the
        # channel - the existing SINR/capture-effect logic below
        # (unchanged) then decides who, if anyone, survives, exactly like
        # it already does for cross-technology WiFi/NR-U interference.
        # Rashed-Step 6.A-07-31-2026-end
        # Rashed-Step 20.A-10-08-2026-start
        if self.config.mac_exchange and self.sta_list:
            return (yield from self._send_frame_mac(self.frame_to_send, self.sent_completed, self.sent_failed))
        # Rashed-Step 20.A-10-08-2026-end
        log(self, f'Starting sending frame: {self.frame_to_send.frame_time}')
        # Rashed-Step 4.D_2-01-28-2026-end
        # Rashed-Step 5.G-02-06-2026-start
        # BUGFIX/UPGRADE (Step 5.G, G_2): rx_pos is computed here (right
        # before actual transmission start), not back when send_frame()
        # was first called, so a moving STA's position is always "now".
        tx_start = self.env.now
        tx_pos = self.current_pos()
        rx_pos = self.sta_list[0].current_pos() if self.sta_list else tx_pos
        # Rashed-Step 5.G-02-06-2026-end
        tx = ActiveTx(
            tx_id=self.name,
            tx_pos=tx_pos,
            rx_pos=rx_pos,
            tx_start=tx_start,
            tx_power_dbm=self.config.tx_power_dbm,
            f_hz=self.config.f_ghz,
            pl_exp=self.config.pl_exp,
            t_end=tx_start + self.frame_to_send.frame_time,
            tech="WiFi",
            # Rashed-Step 5.C-02-06-2026-start
            bandwidth_mhz=self.config.bandwidth_mhz,
            noise_figure_db=self.config.noise_figure_db,
            # Rashed-Step 5.C-02-06-2026-end
            # Rashed-Step 9.B-08-07-2026-start
            # UPGRADE/BUGFIX: ActiveTx.packet has existed since Step
            # 8.A, but this construction never actually passed one
            # through - the field silently stayed None for every real
            # WiFi transmission ever registered on the channel, so
            # nothing reading channel.active_txs (like generic.
            # GenericWirelessDevice.sniff(), Step 7.A) could ever see a
            # WiFi packet's identity, only its RF/timing metadata. Found
            # while wiring GenericWirelessDevice into the packet system
            # (Step 9.B) - fixing this is a prerequisite for that,
            # not a side quest. Purely additive: .packet is never READ
            # anywhere in channel.py's collision/SINR/timing logic
            # (confirmed via grep before making this change), so this
            # cannot affect any existing simulation outcome.
            packet=self.frame_to_send.packet,
            # Rashed-Step 9.B-08-07-2026-end
        )
        # Rashed-Step 4.B_4-01-20-2026-start
        #print(self.env.now, self.name, "TX->RX d=", dist(self.pos, rx_pos))
        # Rashed-Step 4.B_4-01-20-2026-end
        self.channel.register_tx(tx)

        # Rashed-Step 5.1-02-06-2026-start
        was_sent = False
        # Rashed-Step 5.1-02-06-2026-end
        try:
            yield self.env.timeout(self.frame_to_send.frame_time)
            # Rashed-Step 4.C_2-01-21-2026-start
            #self.sinr_print_ctr += 1
            # if self.sinr_print_ctr % 50 == 0:
            #     print(self.env.now, self.name, "WiFi SINR(dB) =", self.channel.sinr_db(tx))
            # Rashed-Step 4.C_2-01-21-2026-end
            # Rashed-Step 4.D_2-01-28-2026-start
            sinr = self.channel.sinr_db(tx)
            # Rashed-Step 13.A-08-23-2026-start
            # Log measured SINR on the packet itself, success or
            # failure alike - see Packet.measured_sinr_db docstring.
            self.frame_to_send.packet.measured_sinr_db = sinr
            # Rashed-Step 13.A-08-23-2026-end
            # Rashed-Step 5.D-02-06-2026-start
            # UPGRADE: required SINR now depends on the configured MCS
            # (per-MCS table) instead of one flat threshold for every
            # rate. wifi_sinr_thr_db_override, if set, forces a flat
            # value instead (e.g. to compare against pre-5.D behavior).
            required_sinr = self.required_sinr_db()
            log(self, f"TX->RX SINR(dB) = {sinr:.2f} dB, required (MCS {self.config.mcs}) = {required_sinr:.2f} dB")
            # Rashed-Step 5.D-02-06-2026-end
            #was_sent = self.check_collision()
            # Rashed-Step 18.A-10-06-2026-start
            was_sent = decode_ok(getattr(self.config, "error_model", None), sinr, required_sinr)
            # Rashed-Step 18.A-10-06-2026-end
            # Rashed-Step 11.A-08-21-2026-start
            # ARF feedback - no-op when rate adaptation is disabled.
            # Rashed-Step 13.E.1: also pass measured_sinr_db (see the
            # EDCA call site's comment above for why).
            self.rate_adapt_record_result(self.rate_adapt_link_key(), was_sent, measured_sinr_db=sinr)
            # Rashed-Step 11.A-08-21-2026-end

            if was_sent:
                self.sent_completed()
            else:
                self.sent_failed()
            # Rashed-Step 4.D_2-01-28-2026-end
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
            # BUGFIX: pass success so airtime isn't recorded twice -
            # sent_completed() below no longer touches airtime_data,
            # unregister_tx() is now the only place that does.
            self.channel.unregister_tx(tx, success=was_sent)
            # Rashed-Step 5.1-02-06-2026-end
        except BaseException:
            # Rashed-Step 5.I-02-06-2026-start
            # BUGFIX: this used to be `finally: yield ...; unregister_tx
            # (...)`, which ran on EVERY exit path including the
            # generator being closed via GeneratorExit at simulation
            # shutdown (env.run(until=...) returning while this AP was
            # still mid-transmission - a near-certain occurrence at the
            # end of any run). Yielding again while a generator is being
            # closed is invalid and raised "RuntimeError: generator
            # ignored GeneratorExit" (printed by the interpreter as
            # "Exception ignored in: ..." since it happens during
            # garbage collection with no caller to propagate to -
            # harmless to already-computed results, but noisy on every
            # single run). Fixed by moving the yield+unregister above
            # into the normal (non-exception) tail of the try block, and
            # handling GeneratorExit (or any other exception) here with
            # a purely SYNCHRONOUS cleanup instead - was_sent is still
            # False here unless the try body got far enough to decide
            # otherwise, matching the original finally's intent of
            # "always unregister on the way out", just without the
            # illegal re-yield.
            self.channel.unregister_tx(tx, success=was_sent)
            raise
            # Rashed-Step 5.I-02-06-2026-end

        if was_sent:
            self.channel.airtime_control[self.name] += self.times.get_ack_frame_time()
            yield self.env.timeout(self.times.get_ack_frame_time())
            # Rashed-Step 8.F-08-06-2026-start
            # The ACK's own "airtime" has now genuinely elapsed (the
            # yield above) - mark it DELIVERED here, not when it was
            # constructed in sent_completed() (that was still mid-flight
            # at env.now - get_ack_frame_time()).
            if self.frame_to_send.ack_packet is not None:
                self.frame_to_send.ack_packet.status = "DELIVERED"
                self.frame_to_send.ack_packet.delivered_at = self.env.now
            # Rashed-Step 8.F-08-06-2026-end
            return True
        else:
            yield self.env.timeout(self.times.ack_timeout)
            return False
    # Rashed-Step 3.F-01-13-2026-end

    def check_collision(self):  # check if the collision occurred

        # if (len(self.channel.tx_list) + len(self.channel.tx_list_NR)) > 1 or (len(self.channel.tx_list) + len(self.channel.tx_list_NR)) == 0:
        #     self.sent_failed()
        #     return False
        # else:
        #     self.sent_completed()
        #     return True
        # Rashed-Step 3.F-12-26-2025-start
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
        # Rashed-Step 3.F-12-26-2025-end

    # Rashed-Step 3.D-12-26-2025-start
    #def generate_new_back_off_time(self, failed_transmissions_in_row):

        
        # upper_limit = (pow(2, failed_transmissions_in_row) * (
        #         self.cw_min + 1) - 1)  # define the upper limit basing on  unsuccessful transmissions in the row
        # upper_limit = (
        #     upper_limit if upper_limit <= self.cw_max else self.cw_max)  # set upper limit to CW Max if is bigger then this parameter
        # back_off = random.randint(0, upper_limit)  # draw the back off value
        # self.channel.backoffs[back_off][self.channel.n_of_stations] += 1  # store drawn value for future analyzes
        # return back_off * self.times.t_slot


    def generate_new_back_off_slots(self, failed_transmissions_in_row)-> int:
        upper_limit = (pow(2, failed_transmissions_in_row) * (self.cw_min + 1) - 1)# define the upper limit basing on  unsuccessful transmissions in the row
        upper_limit = upper_limit if upper_limit <= self.cw_max else self.cw_max
        back_off = random.randint(0, upper_limit)  # draw the back off value
        self.channel.backoffs[back_off][self.channel.n_of_stations] += 1  # store drawn value for future analyzes
        return back_off

    


    # Rashed-Step 3.D-12-26-2025-end

    def generate_new_frame(self, packet: Optional[Packet] = None):
        # Rashed-Step pre_5.C-02-06-2026-start
        # BUGFIX: frame duration was hardcoded to 5400us, so config.mcs had
        # zero effect on airtime or on the SINR window used for capture.
        # Times.get_ppdu_frame_time() already derives duration from
        # payload size + MCS - re-enabled it.
        # Rashed-Step 8.C-08-06-2026-start
        # UPGRADE: duration (and the reported data_size) now come from
        # the actual dequeued Packet's payload_bytes when one is passed
        # in, instead of always assuming self.config.data_size. packet
        # is None only for legacy/defensive call sites (there are none
        # left in wifi.py itself as of this change, but keeping the
        # default keeps this method safely callable standalone, e.g.
        # from a test) - falls back to config.data_size, which is
        # exactly the old behavior. Note: pass packet.payload_bytes, NOT
        # packet.total_bytes() - Times.get_ppdu_frame_time() already
        # adds the MAC header (Times.mac_overhead) internally, so
        # total_bytes() would double-count the header that
        # _make_packet() derived from that same constant.
        payload_bytes = packet.payload_bytes if packet is not None else self.config.data_size
        # Rashed-Step 11.A-08-21-2026-start
        # UPGRADE: when rate adaptation has moved this link off the
        # originally-configured MCS, self.times (built once in __init__
        # from config.mcs and never rebuilt - see that constructor) would
        # silently keep computing duration at the OLD rate forever. Build
        # a fresh Times for the CURRENT adapted MCS instead, but only
        # when adaptation is actually enabled - self.times is reused
        # as-is otherwise, so this is byte-identical to before Step 11
        # whenever Config.rate_adapt_enabled is False (the default).
        # Also covers the EDCA path for free: send_frame_edca()'s frame
        # comes from this same generate_new_frame() call (via
        # _refresh_ac_frame()), so no separate EDCA-specific fix needed.
        if self.config.rate_adapt_enabled:
            current_mcs = self.current_mcs_for_link(self.rate_adapt_link_key())
            frame_length = Times(payload_bytes, current_mcs).get_ppdu_frame_time(payload_bytes)
        else:
            frame_length = self.times.get_ppdu_frame_time(payload_bytes)
        # Rashed-Step 11.A-08-21-2026-end
        # Rashed-Step 8.C-08-06-2026-end
        # Rashed-Step pre_5.C-02-06-2026-end

        # Rashed-Step 2.D_1-01-08-2026-start

        rx_sta = random.choice(self.sta_list) if self.sta_list else None

        fr = Frame (frame_length, self.name, self.col, payload_bytes, self.env.now)

        # Rashed-Step 5.G-02-06-2026-start
        # current_pos() instead of self.pos/rx_sta.pos - this is a
        # diagnostic snapshot only (not used for the actual send_frame()
        # success decision, which recomputes its own tx_pos/rx_pos fresh
        # right at transmission time - see send_frame()), but should
        # still reflect where things actually are *now* if mobility is
        # enabled, not stale construction-time positions.
        my_pos = self.current_pos()
        fr.tx_pos = my_pos
        if rx_sta is not None:
            rx_pos = rx_sta.current_pos()
            fr.rx_name = rx_sta.name
            fr.rx_pos = rx_pos
            fr.distance_m = dist(my_pos, rx_pos)
            # Rashed-Step 5.G-02-06-2026-end
            # Rashed-Step 5.B-02-06-2026-start
            # Route through channel.shadow_db() so this diagnostic pr_dbm
            # (logged on the Frame, not used for the actual success
            # decision) reflects the same per-link shadow value sinr_db()
            # will use at transmission time.
            fr.pr_dbm = rx_power_dbm(
                tx_power_dbm=self.config.tx_power_dbm,
                d_m=fr.distance_m,
                f_hz=self.config.f_ghz,
                n=self.config.pl_exp,
                shadow_db=self.channel.shadow_db(self.name, fr.rx_pos)
            )
            # Rashed-Step 5.B-02-06-2026-end

        return fr

        #return Frame(frame_length, self.name, self.col, self.config.data_size, self.env.now)

        # Rashed-Step 2.D_1-01-08-2026-end

    # Rashed-Step 5.D-02-06-2026-start
    def required_sinr_db(self) -> float:
        """
        Required SINR for this AP's current MCS (rate-adapted if
        Config.rate_adapt_enabled, else the fixed configured value), or
        the flat override if config.wifi_sinr_thr_db_override is set.
        """
        if self.config.wifi_sinr_thr_db_override is not None:
            return self.config.wifi_sinr_thr_db_override
        # Rashed-Step 11.A-08-21-2026-start
        mcs = self.current_mcs_for_link(self.rate_adapt_link_key())
        # Rashed-Step 11.A-08-21-2026-end
        return mcs_sinr_threshold_db(WIFI_MCS_SINR_THRESHOLDS_DB, mcs)
    # Rashed-Step 5.D-02-06-2026-end

    # Rashed-Step 11.A-08-21-2026-start
    def rate_adapt_link_key(self) -> Optional[str]:
        """
        Identifies which per-link rate-adaptation state to use. Matches
        send_frame()/send_frame_edca()'s ACTUAL real transmission
        target (self.sta_list[0] - see their own rx_pos computation),
        not generate_new_frame()'s random.choice() (that's a diagnostic-
        only snapshot, not what really gets transmitted to - see that
        method's own comment). None when there's no associated STA at
        all (rate adaptation has nothing to track).
        """
        return self.sta_list[0].name if self.sta_list else None

    def current_mcs_for_link(self, link_key: Optional[str]) -> int:
        """
        The MCS to use RIGHT NOW for `link_key`. Returns config.mcs
        unchanged when rate adaptation is disabled, the link has no
        state yet (first transmission), or link_key is None - so
        "adaptation off" and "adaptation on, before any feedback"
        both behave exactly like today.

        Rashed-Step 13.E.1: when config.sinr_predictor is set AND this
        link already has at least predictor.lag_k measurements, the MCS
        pick is a CQI-style direct SINR-threshold lookup on the
        predictor's PREDICTED next SINR instead - bypassing ARF's
        streak-based state entirely while active. Predictor unset, or
        not enough history yet, falls back to the exact pre-13.E ARF
        behavior unchanged (mirrors nru.py's Step 13.D pattern).

        Rashed-Step 13.E.1-fix (2026-08-23): same constant-link guard as
        nru.py's - the predictor is SKIPPED when the recent history is
        exactly constant, falling back to ARF's own streak-based mcs
        instead. Investigated a real empirical collapse on a constant
        12.807 dB link (see nru.py's current_mcs_for_link() docstring
        for the full root-cause writeup, and "Project details/Step
        13.txt"'s 13.E.1 section for the Wi-Fi-specific numbers) - a
        constant history never gives the model new information to
        self-correct a bad prediction with, so a persistent
        overestimate can permanently lock a static link onto an
        unreachable MCS. ARF's own last-measured-driven state is exactly
        correct on a constant link by construction, same reasoning as
        13.C's persistence baseline. Variable-link behavior is
        completely untouched by this guard.
        """
        if not self.config.rate_adapt_enabled or link_key is None:
            return self.config.mcs
        state = self.link_rate_state.get(link_key)
        # Rashed-Step 13.E.1-08-23-2026-start
        predictor = self.config.sinr_predictor
        if predictor is not None and state is not None:
            history = state.get("sinr_history", [])
            # Rashed-Step 13.E.1-fix-08-23-2026-start
            if len(history) >= predictor.lag_k and len(set(history[-predictor.lag_k:])) > 1:
                predicted = predictor.predict_next(history, technology_is_wifi=1)
                return self._select_mcs_for_sinr(predicted)
            # Rashed-Step 13.E.1-fix-08-23-2026-end
        # Rashed-Step 13.E.1-08-23-2026-end
        return state["mcs"] if state is not None else self.config.mcs

    @staticmethod
    def _select_mcs_for_sinr(sinr_db: float) -> int:
        """
        Rashed-Step 13.E.1: CQI-style direct selection, same shape as
        nru.py's Gnb._select_mcs_for_sinr() - the HIGHEST mcs in
        WIFI_MCS_SINR_THRESHOLDS_DB whose required threshold is <=
        sinr_db. Falls back to the table's lowest mcs if even that
        isn't met.
        """
        candidates = [mcs for mcs, thr in WIFI_MCS_SINR_THRESHOLDS_DB.items() if thr <= sinr_db]
        if not candidates:
            return min(WIFI_MCS_SINR_THRESHOLDS_DB.keys())
        return max(candidates)

    def rate_adapt_record_result(self, link_key: Optional[str], success: bool, measured_sinr_db: Optional[float] = None) -> None:
        """
        ARF feedback: call once per completed transmission attempt with
        whether it succeeded. No-op when rate adaptation is disabled or
        link_key is None (keeps link_rate_state empty in that case, not
        just unused - see current_mcs_for_link()).

        Rashed-Step 13.E.1: measured_sinr_db is a new optional param
        (default None, so every pre-13.E call site/test keeps working
        unchanged) - when given, it's appended to a short rolling
        per-link sinr_history (capped at 8, same as nru.py's), used
        only when config.sinr_predictor is set. Harmless extra
        bookkeeping otherwise - the streak logic below is completely
        untouched.
        """
        if not self.config.rate_adapt_enabled or link_key is None:
            return
        min_mcs = min(WIFI_MCS_SINR_THRESHOLDS_DB.keys())
        max_mcs = max(WIFI_MCS_SINR_THRESHOLDS_DB.keys())
        state = self.link_rate_state.setdefault(
            link_key, {"mcs": self.config.mcs, "succ_streak": 0, "fail_streak": 0}
        )
        if success:
            state["succ_streak"] += 1
            state["fail_streak"] = 0
            if state["succ_streak"] >= self.config.rate_adapt_up_streak:
                state["mcs"] = min(state["mcs"] + 1, max_mcs)
                state["succ_streak"] = 0
        else:
            state["fail_streak"] += 1
            state["succ_streak"] = 0
            if state["fail_streak"] >= self.config.rate_adapt_down_streak:
                state["mcs"] = max(state["mcs"] - 1, min_mcs)
                state["fail_streak"] = 0
        # Rashed-Step 13.E.1-08-23-2026-start
        if measured_sinr_db is not None:
            history = state.setdefault("sinr_history", [])
            history.append(measured_sinr_db)
            del history[:-8]
        # Rashed-Step 13.E.1-08-23-2026-end
    # Rashed-Step 11.A-08-21-2026-end

    def sent_failed(self):
        log(self, "There was a collision")
        self.frame_to_send.number_of_retransmissions += 1
        self.channel.failed_transmissions += 1
        self.failed_transmissions += 1
        self.failed_transmissions_in_row += 1
        log(self, self.channel.failed_transmissions)
        # Rashed-Step 8.B-08-06-2026-start
        if self.frame_to_send.packet is not None:
            self.frame_to_send.packet.retry_count = self.frame_to_send.number_of_retransmissions
        # Rashed-Step 8.B-08-06-2026-end
        if self.frame_to_send.number_of_retransmissions > self.config.r_limit:
            # Rashed-Step 8.B-08-06-2026-start
            # UPGRADE: the old packet gave up on/exceeded its retry
            # limit here and used to just vanish with no record beyond
            # the aggregate failed_transmissions counter. Now marked
            # DROPPED before being replaced.
            # Rashed-Step 8.B-08-06-2026-end
            if self.frame_to_send.packet is not None:
                self.frame_to_send.packet.status = "DROPPED"
                # Rashed-Step 8.G-08-06-2026-start
                self.packet_log.append(self.frame_to_send.packet)
                # Rashed-Step 8.G-08-06-2026-end
            # Rashed-Step 8.E-08-06-2026-start
            # UPGRADE: saturated mode (the default) keeps the EXACT old
            # inline behavior - build the replacement frame/packet right
            # here, synchronously, byte-identical to every pre-8.E run.
            # This matters beyond just "no blocking": generate_new_frame()
            # calls random.choice(self.sta_list), and moving that call to
            # a different point in this generator's yield sequence (even
            # one that doesn't itself consume simulated time) shifts its
            # position relative to OTHER processes' events at the same
            # simulated instant, which cascades into a different random-
            # draw ordering downstream - confirmed empirically: an
            # earlier version of this fix that unconditionally deferred
            # to start()'s inner loop reproduced the mixed WiFi+NR-U and
            # NR-U-only baselines exactly, but shifted the WiFi-only N=5
            # collision baseline (PCOLL 0.6438->0.6462, a different but
            # equally valid run, not a bug - same class of divergence
            # documented in Step 8.D) even with r_limit at its DEFAULT
            # value and no new CLI flags set at all. That violated this
            # project's "no new flags -> byte-identical" convention, so
            # only poisson/cbr mode (a genuinely new code path with no
            # pre-8.E baseline to preserve) defers to the queue; saturated
            # mode is untouched.
            if self.traffic_config.mode == "saturated":
                new_packet = self._make_packet()
                self.frame_to_send = self.generate_new_frame(new_packet)
                self.frame_to_send.packet = new_packet
            else:
                # This method stays SYNCHRONOUS (not a generator) even
                # for this branch - it's called from deep inside
                # send_frame()'s try block, BEFORE that transmission's
                # own housekeeping (unregister_tx, the ACK-timeout wait)
                # has run. Blocking here to wait on the queue would delay
                # that unrelated bookkeeping. Instead, just flag that a
                # fresh packet is needed and let start()'s inner retry
                # loop pick it up via _next_packet() - genuinely blocking,
                # but only AFTER send_frame() has fully finished this
                # attempt and returned. See start() for where the flag is
                # consumed.
                self._need_new_packet = True
            # Rashed-Step 8.E-08-06-2026-end
            self.failed_transmissions_in_row = 0

    # Rashed-Step pre_20.B-10-08-2026-start
    # ------------------------------------------------------------------
    # A-MPDU aggregation (Config.ampdu_max_mpdus > 1), AP downlink on the
    # DCF path. One channel access carries one PPDU of several MPDUs.
    # ------------------------------------------------------------------
    # Rashed-Step 20.B-10-08-2026-start
    # The A-MPDU machinery moved to wifi/ampdu.py (shared with EDCA and STA
    # uplink); the AP DCF path below behaves exactly as before.
    AMPDU_DELIMITER_BITS = wifi_ampdu.AMPDU_DELIMITER_BITS

    def _ampdu_times(self):
        """(PHY header us, us per MPDU of payload_bytes) at the current MCS."""
        return wifi_ampdu.times_for(self)

    def _take_queued_packet(self):
        """A packet for the A-MPDU without waiting: a new one in saturated
        mode, else the next queued one, or None."""
        if self.traffic_config.mode == "saturated":
            return self._make_packet()
        if self.packet_queue.items:
            return self.packet_queue.items.pop(0)
        return None

    def _put_back_packet(self, pkt):
        if self.traffic_config.mode != "saturated":
            self.packet_queue.items.insert(0, pkt)

    def _ampdu_rx(self):
        rx = self.sta_list[0] if self.sta_list else None
        return (rx.name, rx.current_pos()) if rx is not None else (self.name, self.current_pos())

    def _start_ampdu(self):
        pending = []  # MPDUs waiting for a retransmission (Block Ack said failed)
        while True:
            if not pending:
                pending = [(yield from self._next_packet())]
            self.process = self.env.process(self.wait_back_off())
            yield self.process
            header_us, per_mpdu = self._ampdu_times()
            mpdus = wifi_ampdu.build(pending, self._take_queued_packet, self._put_back_packet, header_us, per_mpdu,
                                     self.config.ampdu_max_mpdus, self.config.ampdu_max_ppdu_us)
            rx_name, rx_pos = self._ampdu_rx()
            if self.config.mac_exchange and self.sta_list:
                ok = yield self.env.process(wifi_ampdu.send_mac(self, mpdus, header_us, per_mpdu, rx_name, rx_pos))
            else:
                ok = yield self.env.process(wifi_ampdu.send(self, mpdus, header_us, per_mpdu, rx_pos))
            pending = wifi_ampdu.next_pending(pending, mpdus)
    # Rashed-Step 20.B-10-08-2026-end
    # Rashed-Step pre_20.B-10-08-2026-end

    # Rashed-Step 20.A-10-08-2026-start
    # ------------------------------------------------------------------
    # 802.11 frame exchange on the air (Config.mac_exchange) - see
    # wifi/mac.py. The receiver is sta_list[0], the same STA the data
    # frame's SINR has always been evaluated at.
    # ------------------------------------------------------------------
    def _send_frame_mac(self, frame, on_ok, on_fail):
        rx = self.sta_list[0]
        now = self.env.now
        tx = ActiveTx(tx_id=self.name, tx_pos=self.current_pos(), rx_pos=rx.current_pos(), tx_start=now,
                      tx_power_dbm=self.config.tx_power_dbm, f_hz=self.config.f_ghz, pl_exp=self.config.pl_exp,
                      t_end=now + frame.frame_time, tech="WiFi", bandwidth_mhz=self.config.bandwidth_mhz,
                      noise_figure_db=self.config.noise_figure_db, packet=frame.packet)
        em = getattr(self.config, "error_model", None)

        def decide(t):
            sinr = self.channel.sinr_db(t)
            frame.packet.measured_sinr_db = sinr
            ok = decode_ok(em, sinr, self.required_sinr_db())
            self.rate_adapt_record_result(self.rate_adapt_link_key(), ok, measured_sinr_db=sinr)
            return ok
        res, data_end = yield from wifi_mac.data_exchange(self, tx, frame.frame_time, frame.packet.payload_bytes,
                                                          rx.name, tx.rx_pos, decide)
        return wifi_mac.finish(self, frame, res, data_end, on_ok, on_fail)

    # Rashed-Step 20.A-10-08-2026-end
    def sent_completed(self):
        log(self, f"Successfully sent frame, waiting ack: {self.times.get_ack_frame_time()}")
        self.frame_to_send.t_end = self.env.now
        self.frame_to_send.t_to_send = (self.frame_to_send.t_end - self.frame_to_send.t_start)
        self.channel.succeeded_transmissions += 1
        self.succeeded_transmissions += 1
        self.failed_transmissions_in_row = 0
        self.channel.bytes_sent += self.frame_to_send.data_size
        # Rashed-Step 8.B-08-06-2026-start
        if self.frame_to_send.packet is not None:
            self.frame_to_send.packet.status = "DELIVERED"
            self.frame_to_send.packet.delivered_at = self.env.now
            # Rashed-Step 8.G-08-06-2026-start
            self.packet_log.append(self.frame_to_send.packet)
            # Rashed-Step 8.G-08-06-2026-end
        # Rashed-Step 8.B-08-06-2026-end
        # Rashed-Step 8.F-08-06-2026-start
        # Construct the ACK packet now (data delivery just confirmed) -
        # status stays PENDING (Packet's own default) until send_frame()
        # finishes waiting out the ACK's on-air time and marks it
        # DELIVERED (see send_frame(), right after the
        # get_ack_frame_time() timeout). No ack_packet is ever created
        # on the failure path (sent_failed()) - matches real 802.11
        # semantics: a failed frame gets no ACK at all, the sender just
        # times out.
        self.frame_to_send.ack_packet = self._make_ack_packet(self.frame_to_send.packet)
        # Rashed-Step 8.F-08-06-2026-end
        # Rashed-Step 5.1-02-06-2026-start
        # BUGFIX: this used to also do
        # self.channel.airtime_data[self.name] += self.frame_to_send.frame_time
        # here, double-counting against channel.unregister_tx(tx,
        # success=...) in send_frame()'s finally block, which now records
        # airtime_data on success. Removed - unregister_tx is the single
        # source of truth.
        # Rashed-Step 5.1-02-06-2026-end
        return True
    
