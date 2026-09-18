# Rashed-Step 1.B_1-12-26-2025-start

from dataclasses import dataclass
from common.common import Pos
# Rashed-Step 5.G-02-06-2026-start
from typing import Optional, Any
# Rashed-Step 5.G-02-06-2026-end
# Rashed-Step 15.B-09-18-2026-start
import random
from common.common import Frame, log, colors
from common.packet import Packet, TrafficConfig
from channel.channel import ActiveTx
from Times import Times, WIFI_MCS_SINR_THRESHOLDS_DB
from common.common_phy import dist, rx_power_dbm, mcs_sinr_threshold_db
# Rashed-Step 15.B-09-18-2026-end


@dataclass
class WiFiSTA:
    name: str
    pos: Pos  # initial/static position - if mobility is set, use current_pos() instead
    ap_name: str  # associated AP
    # Rashed-Step 5.G-02-06-2026-start
    # Optional common_phy.WaypointMobility instance. None (default) = the
    # STA never moves, current_pos() just returns the static pos above -
    # byte-identical to every pre-5.G run.
    mobility: Optional[Any] = None

    def current_pos(self) -> Pos:
        return self.mobility.pos_now() if self.mobility is not None else self.pos
    # Rashed-Step 5.G-02-06-2026-end

    # Rashed-Step 15.B-09-18-2026-start
    """
    Step 15.B: a real uplink transmit/contention path for WiFiSTA - see
    "Project details/Step pre_15.txt"'s Phase 1/Step 15 sub-step
    breakdown. Before this step, WiFiSTA was a purely passive dataclass
    (a position + an AP-association label, read by WiFi's own
    generate_new_frame() as a downlink destination) - no technology in
    this simulator ever modeled uplink traffic. This closes that gap for
    Wi-Fi: a STA that actually contends for the channel (CSMA/CA: DIFS +
    binary-exponential backoff, freeze-on-busy/resume-on-idle - the
    exact same mechanics as WiFi.wait_back_off()) and transmits real
    frames to its AP, decided by the same SINR-vs-required-MCS-threshold
    physics every other technology in this simulator already uses.

    SCOPE (first cut, deliberately narrow - mirrors how Step 8.B/10.B
    each scoped their own first cut and documented it up front):
      - Opt-in via uplink_enabled (default False) - every existing
        WiFiSTA(...) call site (simulation.py, simulation_spectrum.py,
        simulation_generic.py, simulation_attacker.py) constructs this
        dataclass with none of the new fields set, so uplink_enabled
        stays False and __post_init__ below returns immediately having
        touched nothing - byte-identical to every pre-15.B run.
      - Legacy DCF only (mirrors WiFi's qos_enabled=False path) - no
        EDCA differentiation for uplink traffic in this first cut.
      - Saturated traffic only (mirrors WiFi's own EDCA scope-out) -
        this STA always has a fresh frame ready the instant it wins
        contention. Poisson/cbr uplink queueing is a real, separate
        piece of complexity, deferred to a follow-up.
      - Fixed MCS (self.config.mcs) - no rate adaptation for the
        uplink direction yet (WiFi's own ARF/CQI-predictor logic, Steps
        11.A/13.E.1, lives on the AP and is downlink-only today).
      - The AP's ACK is modeled the same simplified way WiFi's own
        downlink already models it: a fixed time cost
        (Times.get_ack_frame_time() on success, Times.ack_timeout on
        failure) the transmitter waits out, NOT a second, independently-
        contending ActiveTx - matching send_frame()'s own precedent
        exactly, not a new abstraction.
      - Does NOT write into channel.backoffs (the diagnostic drawn-slot
        histogram) - that structure is indexed by channel.n_of_stations
        (the AP count) and only ever pre-sized/populated for AP-side
        draws (see WiFi.generate_new_back_off_slots()); a second writer
        would conflate AP and STA draws under one counter and can
        KeyError against fixtures/scenarios that pass backoffs={}
        without any WiFi AP in them. Skipped rather than risking either.

    WIRING: a STA discovers its AP object (needed for a real rx_pos/
    rx_name/sinr target - ap_name alone is just a label) via a back-
    reference WiFi.__init__ sets on every STA in its own sta_list (see
    that method) - every simulation*.py caller already builds a STA's
    AP-associated stas_for_ap list BEFORE constructing the WiFi AP
    itself, so this stays purely additive with no construction-order
    changes anywhere. If uplink_enabled=True but a STA is never actually
    placed in a WiFi AP's sta_list (e.g. constructed standalone in a
    test), start_uplink() raises a clear RuntimeError instead of a
    confusing AttributeError three calls deep.
    """

    # Rashed-Step 15.B-09-18-2026-start
    # Opt-in uplink fields - all Optional/False-defaulted so every
    # existing WiFiSTA(...) call site is unaffected. `config` is duck-
    # typed against wifi.wifi.Config's shape (cw_min/cw_max/r_limit/mcs/
    # data_size/tx_power_dbm/f_ghz/pl_exp/ed_threshold_dbm/
    # bandwidth_mhz/noise_figure_db/wifi_sinr_thr_db_override) rather
    # than imported directly, avoiding a hard dependency from this
    # module back onto wifi.wifi (same duck-typing convention as
    # ran/protocol/channel_access.py's LbtChannelAccess/
    # SlotScheduledAccess).
    env: Optional[Any] = None
    channel: Optional[Any] = None
    config: Optional[Any] = None
    # Set automatically by WiFi.__init__ - see this class's own
    # docstring's WIRING section. Not meant to be passed by callers.
    ap: Optional[Any] = None
    # None (default) -> TrafficConfig(mode="saturated"). Any other mode
    # raises ValueError at construction - see class docstring's SCOPE.
    traffic_config: Optional[TrafficConfig] = None
    uplink_enabled: bool = False

    def __post_init__(self):
        if not self.uplink_enabled:
            return
        if self.env is None or self.channel is None or self.config is None:
            raise ValueError(
                "WiFiSTA: uplink_enabled=True requires env, channel, "
                "and config to be supplied (the AP reference is wired "
                "in automatically by WiFi.__init__ once this STA is "
                "placed in an AP's sta_list, so it does not need to be "
                "passed here - see this class's own docstring)."
            )
        self.traffic_config = (
            self.traffic_config if self.traffic_config is not None
            else TrafficConfig(mode="saturated")
        )
        if self.traffic_config.mode != "saturated":
            raise ValueError(
                "WiFiSTA: uplink_enabled=True currently only supports "
                "traffic_config.mode='saturated' - poisson/cbr uplink "
                "queueing is a deferred follow-up, mirroring WiFi's "
                "own qos_enabled=True EDCA path (see wifi.py's WiFi "
                "class docstring for the precedent)."
            )
        self.col = random.choice(colors)
        self.times = Times(self.config.data_size, self.config.mcs)
        self.cw_min = self.config.cw_min
        self.cw_max = self.config.cw_max
        self.failed_transmissions_in_row = 0
        self.succeeded_transmissions = 0
        self.failed_transmissions = 0
        self.frame_to_send: Optional[Frame] = None
        self._packet_seq = 0
        self._ack_seq = 0
        self.packet_log = []
        self.process = None
        # Same "cheap, .get()-safe downstream" registration WiFi.__init__
        # does for the AP - see channel.unregister_tx()'s .get(tx.tx_id,
        # 0) fallback for why this isn't strictly required, but matching
        # the AP's own convention keeps this dict populated up front for
        # any diagnostic code that iterates its keys.
        self.channel.airtime_data.setdefault(self.name, 0)
        self.channel.airtime_control.setdefault(self.name, 0)
        self.env.process(self.start_uplink())

    def _make_packet(self) -> Packet:
        self._packet_seq += 1
        payload = (
            self.traffic_config.packet_size_bytes
            if self.traffic_config.packet_size_bytes is not None
            else self.config.data_size
        )
        return Packet(
            packet_id=f"{self.name}-{self._packet_seq:06d}",
            source=self.name,
            destination=self.ap.name,
            payload_bytes=payload,
            header_bytes=Times.mac_overhead // 8,
            created_at=self.env.now,
        )

    def _make_ack_packet(self, data_packet: Optional[Packet]) -> Packet:
        self._ack_seq += 1
        return Packet(
            packet_id=f"{self.name}-ACK-{self._ack_seq:06d}",
            source=self.ap.name,
            destination=self.name,
            payload_bytes=0,
            header_bytes=Times.ack_size // 8,
            packet_type="ACK",
            created_at=self.env.now,
            traffic_class=data_packet.traffic_class if data_packet is not None else "best_effort",
        )

    def generate_new_back_off_slots(self, failed_transmissions_in_row: int) -> int:
        upper_limit = pow(2, failed_transmissions_in_row) * (self.cw_min + 1) - 1
        upper_limit = upper_limit if upper_limit <= self.cw_max else self.cw_max
        return random.randint(0, upper_limit)

    def required_sinr_db(self) -> float:
        if self.config.wifi_sinr_thr_db_override is not None:
            return self.config.wifi_sinr_thr_db_override
        return mcs_sinr_threshold_db(WIFI_MCS_SINR_THRESHOLDS_DB, self.config.mcs)

    def generate_new_frame(self, packet: Packet) -> Frame:
        frame_length = self.times.get_ppdu_frame_time(packet.payload_bytes)
        fr = Frame(frame_length, self.name, self.col, packet.payload_bytes, self.env.now)
        my_pos = self.current_pos()
        rx_pos = self.ap.current_pos()
        fr.tx_pos = my_pos
        fr.rx_name = self.ap.name
        fr.rx_pos = rx_pos
        fr.distance_m = dist(my_pos, rx_pos)
        fr.pr_dbm = rx_power_dbm(
            tx_power_dbm=self.config.tx_power_dbm,
            d_m=fr.distance_m,
            f_hz=self.config.f_ghz,
            n=self.config.pl_exp,
            shadow_db=self.channel.shadow_db(self.name, fr.rx_pos)
        )
        return fr

    def wait_back_off(self):
        backoff_slots = self.generate_new_back_off_slots(self.failed_transmissions_in_row)
        dif_remaining = Times.t_difs
        while dif_remaining > 0:
            if self.channel.is_busy(self.current_pos(), self.config.ed_threshold_dbm, exclude_tx_id=self.name,
                                     sense_f_hz=self.config.f_ghz, sense_bw_mhz=self.config.bandwidth_mhz):
                log(self, "Channel busy during DIFS (uplink), waiting...")
                yield self.channel.state_changed
                continue
            step = min(1, dif_remaining)
            yield self.env.timeout(step)
            dif_remaining -= step

        while backoff_slots > 0:
            if self.channel.is_busy(self.current_pos(), self.config.ed_threshold_dbm, exclude_tx_id=self.name,
                                     sense_f_hz=self.config.f_ghz, sense_bw_mhz=self.config.bandwidth_mhz):
                log(self, "Channel busy during backoff (uplink), waiting...")
                yield self.channel.state_changed
                continue
            yield self.env.timeout(Times.t_slot)
            backoff_slots -= 1

        log(self, "Backoff waited (uplink), sending frame...")
        return

    def send_frame(self):
        log(self, f'Starting sending frame (uplink): {self.frame_to_send.frame_time}')
        tx_start = self.env.now
        tx_pos = self.current_pos()
        rx_pos = self.ap.current_pos()
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
            bandwidth_mhz=self.config.bandwidth_mhz,
            noise_figure_db=self.config.noise_figure_db,
            packet=self.frame_to_send.packet,
        )
        self.channel.register_tx(tx)

        was_sent = False
        try:
            yield self.env.timeout(self.frame_to_send.frame_time)
            sinr = self.channel.sinr_db(tx)
            self.frame_to_send.packet.measured_sinr_db = sinr
            required_sinr = self.required_sinr_db()
            log(self, f"Uplink TX->AP SINR(dB) = {sinr:.2f} dB, required (MCS {self.config.mcs}) = {required_sinr:.2f} dB")
            was_sent = (sinr >= required_sinr)
            if was_sent:
                self.sent_completed()
            else:
                self.sent_failed()
            # Same same-instant-tie-break reasoning as WiFi.send_frame()'s
            # own extra zero-duration tick before unregistering - see
            # that method's comment.
            yield self.env.timeout(0)
            self.channel.unregister_tx(tx, success=was_sent)
        except BaseException:
            # Same GeneratorExit-safety fix as WiFi.send_frame() - see
            # that method's comment for the full rationale.
            self.channel.unregister_tx(tx, success=was_sent)
            raise

        if was_sent:
            self.channel.airtime_control[self.name] += self.times.get_ack_frame_time()
            yield self.env.timeout(self.times.get_ack_frame_time())
            if self.frame_to_send.ack_packet is not None:
                self.frame_to_send.ack_packet.status = "DELIVERED"
                self.frame_to_send.ack_packet.delivered_at = self.env.now
            return True
        else:
            yield self.env.timeout(self.times.ack_timeout)
            return False

    def sent_completed(self):
        log(self, f"Uplink: successfully sent frame, waiting ack: {self.times.get_ack_frame_time()}")
        self.frame_to_send.t_end = self.env.now
        self.frame_to_send.t_to_send = self.frame_to_send.t_end - self.frame_to_send.t_start
        self.channel.succeeded_transmissions += 1
        self.succeeded_transmissions += 1
        self.failed_transmissions_in_row = 0
        self.channel.bytes_sent += self.frame_to_send.data_size
        if self.frame_to_send.packet is not None:
            self.frame_to_send.packet.status = "DELIVERED"
            self.frame_to_send.packet.delivered_at = self.env.now
            self.packet_log.append(self.frame_to_send.packet)
        self.frame_to_send.ack_packet = self._make_ack_packet(self.frame_to_send.packet)
        return True

    def sent_failed(self):
        log(self, "Uplink: there was a collision")
        self.frame_to_send.number_of_retransmissions += 1
        self.channel.failed_transmissions += 1
        self.failed_transmissions += 1
        self.failed_transmissions_in_row += 1
        if self.frame_to_send.packet is not None:
            self.frame_to_send.packet.retry_count = self.frame_to_send.number_of_retransmissions
        if self.frame_to_send.number_of_retransmissions > self.config.r_limit:
            if self.frame_to_send.packet is not None:
                self.frame_to_send.packet.status = "DROPPED"
                self.packet_log.append(self.frame_to_send.packet)
            new_packet = self._make_packet()
            self.frame_to_send = self.generate_new_frame(new_packet)
            self.frame_to_send.packet = new_packet
            self.failed_transmissions_in_row = 0

    def start_uplink(self):
        if self.ap is None:
            raise RuntimeError(
                f"WiFiSTA {self.name}: uplink_enabled=True but no AP "
                "reference was wired in - this STA was never placed in "
                "a WiFi AP's sta_list at construction time (see "
                "WiFi.__init__, which back-references self.ap on every "
                "STA in its own sta_list - see this class's own "
                "docstring's WIRING section)."
            )
        while True:
            packet = self._make_packet()
            self.frame_to_send = self.generate_new_frame(packet)
            self.frame_to_send.packet = packet
            was_sent = False
            while not was_sent:
                self.process = self.env.process(self.wait_back_off())
                yield self.process
                was_sent = yield self.env.process(self.send_frame())
    # Rashed-Step 15.B-09-18-2026-end


# Rashed-Step 1.B_1-12-26-2025-end
