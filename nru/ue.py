# Rashed-Step 1.B_2-12-26-2025-start

from dataclasses import dataclass
from common.common import Pos
# Rashed-Step 5.G-02-06-2026-start
from typing import Optional, Any
# Rashed-Step 5.G-02-06-2026-end
# Rashed-Step 15.C-09-18-2026-start
import random
from common.common import log, colors
from common.packet import Packet, TrafficConfig
from channel.channel import ActiveTx
from common.common_phy import dist, rx_power_dbm, mcs_sinr_threshold_db
from ran.protocol.channel_access import LbtChannelAccess
from nru.nru import Transmission_NR, NRU_MCS_SINR_THRESHOLDS_DB, NruDeploymentMode
# Rashed-Step 15.C-09-18-2026-end
# Rashed-Step 15.F-09-18-2026-start
from ran.protocol.rrc import RrcState
# Rashed-Step 15.F-09-18-2026-end
# Rashed-Step 17.B-10-04-2026-start
from nru.nru import NruUplinkAccessMode
# Rashed-Step 17.B-10-04-2026-end

@dataclass
class NrUE:
    name: str
    pos: Pos  # initial/static position - if mobility is set, use current_pos() instead
    gnb_name: str  # associated gNB
    # Rashed-Step 5.G-02-06-2026-start
    # See wifi.sta.WiFiSTA.mobility - same idea. None (default) = static,
    # byte-identical to every pre-5.G run.
    mobility: Optional[Any] = None

    def current_pos(self) -> Pos:
        return self.mobility.pos_now() if self.mobility is not None else self.pos
    # Rashed-Step 5.G-02-06-2026-end

    """
    Step 15.C: a real uplink LBT transmit path for NrUE - the NR-U
    counterpart of wifi/sta.py's WiFiSTA Step 15.B work, and the
    reason ran/protocol/channel_access.py's LbtChannelAccess was
    designed as a reusable, parametrized abstraction in Step 15.A
    rather than staying inline in nru.py's Gnb. Before this step, NrUE
    was a purely passive dataclass (a position + a gNB-association
    label) - no NR-U uplink existed anywhere in this simulator.

    SCOPE (first cut, same discipline as WiFiSTA's Step 15.B):
      - Opt-in via uplink_enabled (default False) - every existing
        NrUE(...) call site (simulation.py, simulation_spectrum.py,
        simulation_generic.py, simulation_attacker.py) constructs this
        dataclass with none of the new fields set, so uplink_enabled
        stays False and __post_init__ below returns immediately having
        touched nothing - byte-identical to every pre-15.C run.
      - Saturated traffic only - mirrors WiFiSTA's own scope-out;
        poisson/cbr uplink queueing is a deferred follow-up.
      - Fixed MCS (self.config_nr.mcs) - no CQI-style rate adaptation
        for the uplink direction yet (Gnb's own rate-adaptation logic,
        Step 11.B/13.D, is downlink-only today).
      - No ACK modeling - matches NR-U's existing downlink exactly
        (Gnb.send_transmission() has no ACK-equivalent wait either;
        only WiFi models one, see WiFiSTA's own docstring).
      - STANDALONE_MULTIFIRE only. This *is* what LbtChannelAccess-
        based uplink means (see NruDeploymentMode's own docstring in
        nru/nru.py) - uplink_enabled=True with
        config_nr.deployment_mode == LAA_ANCHORED raises
        NotImplementedError in __post_init__ rather than silently
        giving LAA-labeled traffic MultiFire-shaped (LBT-contended,
        unlicensed-band) uplink behavior it wouldn't really have.

    WIRING: a UE discovers its gNB object (needed for a real rx_pos/
    sinr target, and to read the gNB's live next_sync_slot_boundry
    rather than run a second, independent per-UE sync process) via a
    back-reference Gnb.__init__ sets on every UE in its own ue_list
    (mirrors wifi.WiFi.__init__'s sta.ap = self, Step 15.B) - purely
    additive, no construction-order changes anywhere. If
    uplink_enabled=True but a UE is never actually placed in a Gnb's
    ue_list, start_uplink() raises a clear RuntimeError instead of a
    confusing AttributeError.
    """

    # Rashed-Step 15.C-09-18-2026-start
    # Opt-in uplink fields - all Optional/False-defaulted so every
    # existing NrUE(...) call site is unaffected. `config_nr` is duck-
    # typed against nru.nru.Config_NR's shape rather than imported
    # directly as a type, matching wifi/sta.py's WiFiSTA convention.
    env: Optional[Any] = None
    channel: Optional[Any] = None
    config_nr: Optional[Any] = None
    # Set automatically by Gnb.__init__ - see this class's own
    # docstring's WIRING section. Not meant to be passed by callers.
    gnb: Optional[Any] = None
    # None (default) -> TrafficConfig(mode="saturated"). Any other mode
    # raises ValueError at construction - see class docstring's SCOPE.
    traffic_config: Optional[TrafficConfig] = None
    uplink_enabled: bool = False
    # Rashed-Step 15.F-09-18-2026-start
    # Opt-in RRC attach (see ran/protocol/rrc.py's module docstring for
    # the full design) - requires uplink_enabled=True too (validated in
    # __post_init__ below). False (default) means this UE has no
    # rrc_state attribute at all, same "byte-identical when unused"
    # convention as every other opt-in field here.
    rrc_enabled: bool = False
    # Rashed-Step 15.F-09-18-2026-end

    @property
    def next_sync_slot_boundry(self) -> float:
        """
        LbtChannelAccess.wait() reads this to know when the next NR-U
        synchronization slot boundary is (see that method's docstring
        in ran/protocol/channel_access.py). Rather than running a
        second, independent sync_slot_counter process for every UE
        (which would desync from its own gNB's boundary and wouldn't
        model anything real - a UE's uplink timing is derived from its
        serving cell, not self-generated), this simply reads the live
        value off self.gnb, which already runs exactly one such
        process per cell. 0.0 if this UE has no gnb wired yet (never
        actually read in that state - see start_uplink()'s guard).
        """
        return self.gnb.next_sync_slot_boundry if self.gnb is not None else 0.0

    def __post_init__(self):
        # Rashed-Step 15.F-09-18-2026-start
        if self.rrc_enabled and not self.uplink_enabled:
            raise ValueError(
                "NrUE: rrc_enabled=True requires uplink_enabled=True "
                "too - RRC attach genuinely needs real uplink "
                "capability to send RRCSetupRequest/RRCSetupComplete "
                "(see ran/protocol/rrc.py's module docstring)."
            )
        # Rashed-Step 15.F-09-18-2026-end
        if not self.uplink_enabled:
            return
        if self.env is None or self.channel is None or self.config_nr is None:
            raise ValueError(
                "NrUE: uplink_enabled=True requires env, channel, and "
                "config_nr to be supplied (the gNB reference is wired "
                "in automatically by Gnb.__init__ once this UE is "
                "placed in a gNB's ue_list, so it does not need to be "
                "passed here - see this class's own docstring)."
            )
        if self.config_nr.deployment_mode == NruDeploymentMode.LAA_ANCHORED:
            raise NotImplementedError(
                "NrUE: uplink_enabled=True with "
                "config_nr.deployment_mode=NruDeploymentMode.LAA_ANCHORED "
                "is not supported yet - this class's LBT-based uplink "
                "path is STANDALONE_MULTIFIRE only (contention in the "
                "unlicensed band). LAA_ANCHORED's uplink is grant-based, "
                "through a licensed anchor cell, a different mechanism "
                "not built yet - see NruDeploymentMode's docstring in "
                "nru/nru.py and Step pre_15.txt's Section 3 roadmap "
                "(Step 15.E)."
            )
        # Rashed-Step 17.B-10-04-2026-start
        # (17.B's "COT_SHARING not built yet" guard was removed in 17.E,
        # when COT sharing started working and became the default.)
        # Rashed-Step 17.B-10-04-2026-end
        self.traffic_config = (
            self.traffic_config if self.traffic_config is not None
            else TrafficConfig(mode="saturated")
        )
        if self.traffic_config.mode != "saturated":
            raise ValueError(
                "NrUE: uplink_enabled=True currently only supports "
                "traffic_config.mode='saturated' - poisson/cbr uplink "
                "queueing is a deferred follow-up, mirroring "
                "WiFiSTA's own scope-out (see wifi/sta.py's class "
                "docstring for the precedent)."
            )
        self.col = random.choice(colors)
        self.cw_min = self.config_nr.cw_min
        self.cw_max = self.config_nr.cw_max
        self.failed_transmissions_in_row = 0
        self.succeeded_transmissions = 0
        self.failed_transmissions = 0
        self.transmission_to_send: Optional[Transmission_NR] = None
        self._packet_seq = 0
        self.packet_log = []
        self.process = None
        # Rashed-Step 17.D-10-04-2026-start
        # COT sharing counters (see send_in_shared_cot()): grants this UE
        # was given inside its gNB's COT, and how many it had to skip
        # because the Type 2A check found the channel busy.
        self.ul_grants_received = 0
        self.type2a_skips = 0
        # Rashed-Step 17.D-10-04-2026-end
        # Same shared, stateless Cat-4 LBT strategy nru.py's Gnb uses
        # (Step 15.A) - this is the whole point of that refactor.
        self._channel_access = LbtChannelAccess()
        self.channel.airtime_data_NR.setdefault(self.name, 0)
        self.channel.airtime_control_NR.setdefault(self.name, 0)
        # Rashed-Step 15.F-09-18-2026-start
        # Set here (construction time, before env.run() starts) so
        # there's a genuine observable IDLE state before Gnb.__init__'s
        # back-reference loop starts the actual attach process (which
        # transitions IDLE -> CONNECTING as its first action once the
        # simulation clock actually starts running) - see
        # ran/protocol/rrc.py's RrcLayer.attach().
        if self.rrc_enabled:
            self.rrc_state = RrcState.IDLE
        # Rashed-Step 15.F-09-18-2026-end
        # Rashed-Step 15.G-09-18-2026-start
        # "wake me up when RRC connects" event - created here (unused/
        # None-holding attribute doesn't even exist when rrc_enabled=
        # False) so start_uplink() below has something deterministic to
        # yield on before it starts genuinely contending for real
        # uplink data traffic. Fired by ran.protocol.rrc.RrcLayer.
        # attach() the instant this UE's rrc_state actually becomes
        # RrcState.CONNECTED (see that method's own comment) - not
        # polled, so the gate releases on the exact same simulated tick
        # as rrc_connected_at.
        if self.rrc_enabled:
            self._rrc_connected_event = self.env.event()
        # Rashed-Step 15.G-09-18-2026-end
        self.env.process(self.start_uplink())

    def _make_packet(self) -> Packet:
        self._packet_seq += 1
        payload = (
            self.traffic_config.packet_size_bytes
            if self.traffic_config.packet_size_bytes is not None
            else 1500
        )
        return Packet(
            packet_id=f"{self.name}-{self._packet_seq:06d}",
            source=self.name,
            destination=self.gnb.name,
            payload_bytes=payload,
            header_bytes=0,
            created_at=self.env.now,
        )

    def required_sinr_db(self) -> float:
        if self.config_nr.nru_sinr_thr_db_override is not None:
            return self.config_nr.nru_sinr_thr_db_override
        return mcs_sinr_threshold_db(NRU_MCS_SINR_THRESHOLDS_DB, self.config_nr.mcs)

    def gen_new_transmission(self, packet: Packet) -> Transmission_NR:
        """
        Same mcot-based duration convention as Gnb.gen_new_transmission()
        (NR-U's transmission duration has never been payload-size-driven
        - see that method's own comment) - rs_time is always 0 here
        (unlike Gnb's `0 if gap else ...` branch): gap=True is a
        hardcoded, never-toggled constant in this whole repo (see
        ran/protocol/channel_access.py's module docstring for the full
        discovery), so a real reservation-signal wait never actually
        happens for the one live NR-U code path this simulator has -
        porting the dead `else` branch here would just be unreachable
        code, the same reasoning Step 15.A used to leave Gnb's two dead
        backoff methods untouched.

        Reuses Transmission_NR's `rx_ue` field to hold this UE's
        serving gNB object (not literally a UE - a deliberate, low-risk
        reuse of an existing field rather than adding a new one just
        for the reversed uplink direction; send_transmission() reads it
        the exact same way Gnb's version does: "the node object to
        re-read current_pos() from, fresh, at actual transmission
        time").
        """
        transmission_time = self.config_nr.mcot * 1000
        rs_time = 0
        airtime = transmission_time - rs_time

        tx = Transmission_NR(
            transmission_time, self.name, self.col, self.env.now, airtime, rs_time
        )
        tx.packet = packet

        my_pos = self.current_pos()
        tx.tx_pos = my_pos
        tx.rx_ue = self.gnb
        rx_pos = self.gnb.current_pos()
        tx.rx_name = self.gnb.name
        tx.rx_pos = rx_pos
        tx.distance_m = dist(my_pos, rx_pos)
        tx.pr_dbm = rx_power_dbm(
            tx_power_dbm=self.config_nr.tx_power_dbm,
            d_m=tx.distance_m,
            f_hz=self.config_nr.f_ghz,
            n=self.config_nr.pl_exp,
            shadow_db=self.channel.shadow_db(self.name, tx.rx_pos)
        )
        return tx

    def wait_back_off(self):
        yield from self._channel_access.wait(self)

    def send_transmission(self):
        log(self, f'Starting uplink transmission: {self.transmission_to_send.transmission_time}')
        tx_start = self.env.now
        tx_pos = self.current_pos()
        rx_gnb = self.transmission_to_send.rx_ue  # actually the gNB - see gen_new_transmission()
        rx_pos = rx_gnb.current_pos()
        tx_dur = self.transmission_to_send.transmission_time

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
            bandwidth_mhz=self.config_nr.bandwidth_mhz,
            noise_figure_db=self.config_nr.noise_figure_db,
            packet=self.transmission_to_send.packet,
        )
        self.channel.register_tx(active)

        was_sent = False
        try:
            yield self.env.timeout(tx_dur)
            sinr = self.channel.sinr_db(active)
            self.transmission_to_send.packet.measured_sinr_db = sinr
            required_sinr = self.required_sinr_db()
            log(self, f"Uplink TX->gNB SINR(dB) = {sinr:.2f} dB, required (MCS {self.config_nr.mcs}) = {required_sinr:.2f} dB")
            was_sent = (sinr >= required_sinr)
            if was_sent:
                self.sent_completed()
            else:
                self.sent_failed()
            # Same same-instant-tie-break reasoning as Gnb.send_
            # transmission()'s own extra zero-duration tick - see that
            # method's comment.
            yield self.env.timeout(0)
            self.channel.unregister_tx(active, success=was_sent)
        except BaseException:
            # Same GeneratorExit-safety fix as Gnb.send_transmission() -
            # see that method's comment for the full rationale.
            self.channel.unregister_tx(active, success=was_sent)
            raise

        if was_sent:
            self.channel.airtime_control_NR[self.name] += self.transmission_to_send.rs_time
            return True
        else:
            return False

    def sent_completed(self):
        log(self, "Uplink: successfully sent transmission")
        self.transmission_to_send.t_end = self.env.now
        self.transmission_to_send.t_to_send = (
            self.transmission_to_send.t_end - self.transmission_to_send.t_start
        )
        self.channel.succeeded_transmissions_NR += 1
        self.succeeded_transmissions += 1
        self.failed_transmissions_in_row = 0
        if self.transmission_to_send.packet is not None:
            self.transmission_to_send.packet.status = "DELIVERED"
            self.transmission_to_send.packet.delivered_at = self.env.now
            self.packet_log.append(self.transmission_to_send.packet)
        return True

    def sent_failed(self):
        log(self, f"Uplink: TX failed (SINR < {self.required_sinr_db():.2f} dB)")
        self.transmission_to_send.number_of_retransmissions += 1
        self.channel.failed_transmissions_NR += 1
        self.failed_transmissions += 1
        self.failed_transmissions_in_row += 1
        if self.transmission_to_send.packet is not None:
            self.transmission_to_send.packet.retry_count += 1
        if (self.transmission_to_send.packet is not None
                and self.transmission_to_send.packet.retry_count > self.config_nr.r_limit):
            self.transmission_to_send.packet.status = "DROPPED"
            self.packet_log.append(self.transmission_to_send.packet)
            new_packet = self._make_packet()
            self.transmission_to_send = self.gen_new_transmission(new_packet)
            self.failed_transmissions_in_row = 0

    # Rashed-Step 17.D-10-04-2026-start
    def _channel_busy(self) -> bool:
        return self.channel.is_busy(
            self.current_pos(), self.config_nr.ed_threshold_dbm, exclude_tx_id=self.name,
            sense_f_hz=self.config_nr.f_ghz, sense_bw_mhz=self.config_nr.bandwidth_mhz,
        )

    def type2a_lbt(self):
        """
        Generator -> bool. Type 2A LBT (3GPP TS 37.213) for uplink inside
        the gNB's shared COT: the channel must be idle for
        config_nr.ul_type2a_sense_us (25us = a 16us gap + one 9us slot).
        Modeled as three checks - at the start, after 16us, and at the
        end; busy at any of them means the UE may not send in this COT.
        No backoff and no retrying within the window, unlike Cat-4.
        """
        total = self.config_nr.ul_type2a_sense_us
        gap = min(16.0, total)
        for step in (gap, total - gap):
            if self._channel_busy():
                return False
            if step > 0:
                yield self.env.timeout(step)
        return not self._channel_busy()

    def send_in_shared_cot(self, window_us: float):
        """
        Generator -> True (sent and decoded), False (sent, failed SINR) or
        None (grant skipped: Type 2A found the channel busy). Uses one
        uplink grant inside the gNB's COT: Type 2A check, then transmit
        for the rest of the window through the normal send path, so
        packet bookkeeping is exactly the autonomous uplink's - a new
        packet after a success, the same packet retried after a failure,
        dropped past r_limit.
        """
        self.ul_grants_received += 1
        if self.transmission_to_send is None:
            self.transmission_to_send = self.gen_new_transmission(self._make_packet())
        clear = yield from self.type2a_lbt()
        if not clear:
            self.type2a_skips += 1
            log(self, "Uplink: Type 2A found the channel busy, skipping this grant")
            return None
        duration = window_us - self.config_nr.ul_type2a_sense_us
        self.transmission_to_send.transmission_time = duration
        self.transmission_to_send.airtime = duration
        was_sent = yield from self.send_transmission()
        if was_sent:
            self.transmission_to_send = None
        return was_sent
    # Rashed-Step 17.D-10-04-2026-end

    def start_uplink(self):
        if self.gnb is None:
            raise RuntimeError(
                f"NrUE {self.name}: uplink_enabled=True but no gNB "
                "reference was wired in - this UE was never placed in "
                "a Gnb's ue_list at construction time (see "
                "Gnb.__init__, which back-references self.gnb on every "
                "UE in its own ue_list - see this class's own "
                "docstring's WIRING section)."
            )
        # Rashed-Step 17.E-10-04-2026-start
        # COT sharing: this UE sends data only when its gNB grants it part
        # of a COT (Gnb._run_ul_window -> send_in_shared_cot), so it runs
        # no autonomous Cat-4 loop of its own. RRC/UPF gating is applied
        # by the gNB's eligibility filter instead.
        if self.config_nr.ul_access_mode is NruUplinkAccessMode.COT_SHARING:
            return
        # Rashed-Step 17.E-10-04-2026-end
        # Rashed-Step 15.G-09-18-2026-start
        # Gate real uplink DATA traffic on RRC connection setup, when
        # this UE opted into RRC - see __post_init__'s own comment on
        # self._rrc_connected_event and ran/protocol/rrc.py's RrcLayer.
        # attach()'s firing side. No-op (returns immediately) when
        # rrc_enabled=False, exactly as before Step 15.G - this UE's
        # uplink starts contending the instant the simulation clock
        # starts, same as every pre-15.F/15.G run.
        if self.rrc_enabled:
            yield self._rrc_connected_event
        # Rashed-Step 15.G-09-18-2026-end
        # Rashed-Step 16.E-10-02-2026-start
        # UPF gate (ran/protocol/user_plane.py): a UE handed to the 5G
        # Core waits for its PDU session to become ACTIVE. The event
        # exists only after core.network.CoreNetwork.start_ue(), so
        # every other UE skips this. Checked once, here: start_ue() must
        # be called before the simulation reaches this point (16.F's
        # orchestrators call it at setup, t=0).
        user_plane_event = getattr(self, "_user_plane_event", None)
        if user_plane_event is not None:
            yield user_plane_event
        # Rashed-Step 16.E-10-02-2026-end
        while True:
            packet = self._make_packet()
            self.transmission_to_send = self.gen_new_transmission(packet)
            was_sent = False
            while not was_sent:
                self.process = self.env.process(self.wait_back_off())
                yield self.process
                was_sent = yield self.env.process(self.send_transmission())
    # Rashed-Step 15.C-09-18-2026-end

# Rashed-Step 1.B_2-12-26-2025-end
