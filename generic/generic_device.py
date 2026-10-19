# Rashed-Step 7.A-08-05-2026-start
"""
Step 7.A: GenericWirelessDevice - a protocol-agnostic wireless node.

WHY THIS EXISTS
Every existing node type (wifi.WiFi, nru.Gnb, nr.GnbLicensedNR) bundles
raw PHY sense/transmit plumbing together with a specific MAC protocol
(CSMA/CA backoff for WiFi, Cat-3/4 LBT gap-based backoff for NR-U,
scheduled/always-on for licensed NR). Rashed asked (Step 7) for a
generic building block that separates the two: raw "sense the channel"
(sniffer) and raw "transmit a signal" primitives, with NO protocol
baked in, so it can become the base for several different future
things without duplicating the PHY plumbing each time:
  1. A spectrum analyzer / passive monitor (sniff() only, never
     transmits).
  2. An attacker/jammer base class (subclasses call transmit()
     however/whenever their attack logic decides, no CSMA/LBT in the
     way).
  3. A brand-new, custom-protocol node (subclass composes sniff() +
     transmit() into whatever MAC discipline it wants - including
     sense-before-transmit, if a subclass chooses to build that on top,
     the same way wifi.py/nru.py already do internally).

Confirmed with Rashed via AskUserQuestion:
  - Purpose: all three of the above - genuinely general-purpose, not
    narrowed to just one.
  - transmit() is UNRESTRICTED: it registers an ActiveTx on the shared
    channel the instant it's called, no built-in sense-before-transmit
    wait. Any channel-access discipline is layered on top by whoever
    calls it (e.g. a subclass could call is_channel_busy() in a loop
    before calling transmit(), but the base class itself never does).

DESIGN NOTES
  - Reuses the exact same shared primitives every existing technology
    already uses (channel.sensed_energy_dbm/is_busy/shadow_db/sinr_db,
    common_phy.rx_power_dbm/dist, common_phy.WaypointMobility) - a
    GenericWirelessDevice is a first-class citizen on the same channel
    model as WiFi/NR-U/NR, not a separate parallel system.
  - Airtime/transmission history is tracked LOCALLY on the device
    (self.tx_log), not added to channel.py's per-technology airtime
    dicts (airtime_data/airtime_data_NR/airtime_data_NRL). Those 3
    dicts are keyed to 3 fixed tech strings ("WiFi"/"NRU"/"NR");
    a generic device's tech_label is caller-defined and could be
    anything (many different attacker/analyzer/custom-protocol
    subclasses, each with its own label), so extending channel.py's
    schema again for this would mean growing it indefinitely. Local
    bookkeeping keeps this module 100% additive - zero changes to
    channel.py/wifi.py/nru.py/nr/nr.py to introduce it.
  - No MAC protocol, no receive/decode/ACK logic, no scheduler. Those
    are all left to subclasses (or later Step 7 sub-steps) to define,
    on top of the primitives here.

NOT YET DONE (future Step 7 sub-steps, per "one sub-step at a time" -
this file is only the core module + its own unit tests):
  - No spectrum-analyzer scenario/CLI built on top of this yet.
  - No attacker/jammer refactored to subclass this yet (existing
    attacker/*.py files are untouched).
  - No 3-way integration with WiFi/NR-U/NR in a shared scenario yet.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import simpy

from common.common_phy import Pos, dist, rx_power_dbm, WaypointMobility
from channel.channel import Channel, ActiveTx
# Rashed-Step 9.B-08-07-2026-start
from common.packet import Packet
from common.packet_log import new_packet_log  # Rashed-Step 24.B-10-19-2026
# Rashed-Step 9.B-08-07-2026-end


@dataclass
class Config_Generic:
    tx_power_dbm: float = 20.0
    f_hz: float = 5.18e9
    pl_exp: float = 3.0
    bandwidth_mhz: float = 20.0
    noise_figure_db: float = 7.0
    # Used as the default threshold for is_channel_busy()/sniff() - not
    # tied to any real standard's CCA level like WiFi's -62 dBm or
    # NR-U's -72 dBm (those are protocol-specific regulatory/spec
    # values); this is just a sane default a generic device can use or
    # override per call.
    ed_threshold_dbm: float = -62.0
    # Default "tech" string stamped on this device's own transmissions'
    # ActiveTx.tech field - purely a label (used for logging/sniffing
    # breakdowns and to route real per-tech airtime dicts in
    # channel.unregister_tx() IF this happens to match "WiFi"/"NRU"/
    # "NR" exactly, e.g. an attacker impersonating a real technology's
    # label on purpose - otherwise it's just an opaque string channel.py
    # doesn't do anything special with).
    tech_label: str = "GENERIC"


@dataclass
class VisibleTx:
    """One entry in a SpectrumSnapshot's breakdown - a transmission this
    device can currently see on the channel."""
    tx_id: str
    tech: str
    f_hz: float
    distance_m: float
    rx_power_dbm: float
    # Rashed-Step 9.B-08-07-2026-start
    # The actual Packet this transmission is carrying, if the sender
    # populated one on its ActiveTx (wifi.WiFi/nru.Gnb both do, as of
    # this same sub-step - see their send_frame()/send_transmission()).
    # None for anything that didn't - a generic device's own transmit()
    # call with no packet= given, or attacker/*.py transmissions (out
    # of scope, never wired up). Surfaced UNCONDITIONALLY whenever
    # present, same policy as every other VisibleTx field - this class
    # has never modeled a distance/SINR-gated "can this device actually
    # decode it" cutoff for any field, packet included; a passive
    # sniffer here sees full metadata for everything in
    # channel.active_txs regardless of how far away or how weak the
    # signal is. Real per-technology *decode success* (was this
    # specific frame received correctly) is a different, separate
    # question already answered by SINR in wifi.py/nru.py's own success
    # logic - this is a monitor seeing "what's out there", not itself
    # reproducing anyone else's receiver chain.
    packet: Optional[Packet] = None
    # Rashed-Step 9.B-08-07-2026-end


@dataclass
class SpectrumSnapshot:
    """Result of GenericWirelessDevice.sniff() - a full spectrum-analyzer-
    style read of the channel at this device's current position/instant."""
    wideband_energy_dbm: float
    inband_energy_dbm: float
    is_busy_wideband: bool
    is_busy_inband: bool
    visible_txs: List[VisibleTx] = field(default_factory=list)


class GenericWirelessDevice:
    """
    Protocol-agnostic wireless node: raw sniffer (sense the channel) +
    raw transmitter (put a signal on the channel) primitives, no MAC/
    channel-access discipline built in. See module docstring for the
    full rationale/design notes.
    """

    def __init__(
        self,
        env: simpy.Environment,
        name: str,
        channel: Channel,
        config: Config_Generic,
        pos: Pos,
        # Rashed-Step 7.A-08-05-2026: same optional-mobility pattern as
        # every other node type (Step 5.G) - speed_mps<=0 (the default)
        # means static, no WaypointMobility object even constructed.
        mobility_speed_mps: float = 0.0,
        area_w: float = 50.0,
        area_h: float = 50.0,
        mobility_pause_s: float = 0.0,
    ):
        self.env = env
        self.name = name
        self.channel = channel
        self.config = config
        self._pos = pos

        self.mobility: Optional[WaypointMobility] = None
        if mobility_speed_mps > 0.0:
            self.mobility = WaypointMobility(
                env, area_w, area_h, mobility_speed_mps, mobility_pause_s, pos
            )

        # (tx_start, t_end, tech_label, success) per completed
        # transmission - see module docstring re: local vs channel.py
        # airtime bookkeeping.
        self.tx_log: List[Tuple[float, float, str, bool]] = []
        # The in-flight ActiveTx, if transmit() is currently running;
        # None otherwise. Exposed mainly so estimate_sinr_db() has a
        # sensible default target.
        self.active_tx: Optional[ActiveTx] = None

        # Rashed-Step 9.B-08-07-2026-start
        # Every Packet this device has transmit()'d to completion (i.e.
        # the transmission window elapsed without the simulation ending
        # mid-flight - see transmit()). Kept SEPARATE from tx_log rather
        # than adding a 5th element to its existing 4-tuple shape, since
        # test/test_generic_device.py already destructures tx_log
        # entries positionally as (t_start, t_end, tech, success) -
        # changing that shape would break those tests for no benefit.
        # Mirrors wifi.WiFi/nru.Gnb's own packet_log (Step 8.G) in name
        # and spirit, but NOTE the semantics are different: this class
        # has no MAC/receive/ACK logic at all (see module docstring), so
        # "completed" here just means "this device's own transmit()
        # call finished uninterrupted" - it says nothing about whether
        # anyone actually received/decoded the packet, unlike wifi.py/
        # nru.py's packet_log entries, which are only appended after a
        # real SINR-based success/failure decision. Callers/subclasses
        # that want delivery semantics need to build that themselves
        # (e.g. via estimate_sinr_db()).
        self.packet_log = new_packet_log()  # Rashed-Step 24.B-10-19-2026: list, or CompactPacketLog with --compact-packet-log
        # Rashed-Step 9.B-08-07-2026-end

    def current_pos(self) -> Pos:
        if self.mobility is not None:
            return self.mobility.pos_now()
        return self._pos

    # ------------------------------------------------------------------
    # Sniffer / sensing
    # ------------------------------------------------------------------
    def sense_energy_dbm(self, wideband: bool = True, exclude_self: bool = True) -> float:
        """
        Total sensed energy at this device's current position, in dBm.

        wideband=True (default): sums every active transmitter on the
        channel regardless of frequency - the "spectrum analyzer" read.
        wideband=False: restricts to this device's own configured
        f_hz/bandwidth_mhz (in-band only), via the exact same
        spectral_overlap_fraction-based filtering wifi.py/nru.py already
        use for their own CCA sensing (channel.sensed_energy_dbm's
        sense_f_hz/sense_bw_mhz params, Step 5.E).
        """
        exclude_id = self.name if exclude_self else None
        if wideband:
            return self.channel.sensed_energy_dbm(self.current_pos(), exclude_tx_id=exclude_id)
        return self.channel.sensed_energy_dbm(
            self.current_pos(), exclude_tx_id=exclude_id,
            sense_f_hz=self.config.f_hz, sense_bw_mhz=self.config.bandwidth_mhz,
        )

    def is_channel_busy(self, threshold_dbm: Optional[float] = None, wideband: bool = False) -> bool:
        """
        threshold_dbm defaults to config.ed_threshold_dbm. wideband=False
        (default) mirrors a real CCA/LBT check ("is MY channel busy");
        pass wideband=True for a "is anything, anywhere, busy" read
        instead.
        """
        thr = self.config.ed_threshold_dbm if threshold_dbm is None else threshold_dbm
        return self.sense_energy_dbm(wideband=wideband) >= thr

    def sniff(self, threshold_dbm: Optional[float] = None) -> SpectrumSnapshot:
        """
        Full spectrum-analyzer-style snapshot: wideband + in-band total
        energy, busy/idle for both, and a per-transmitter breakdown
        (tx_id, tech, frequency, distance, estimated RX power at this
        device's position) of every currently-active transmission on the
        channel. Built entirely from Channel's public API (same public
        methods wifi.py/nru.py use for their own diagnostics) - no reach
        into Channel's private helpers.
        """
        my_pos = self.current_pos()
        thr = self.config.ed_threshold_dbm if threshold_dbm is None else threshold_dbm

        wideband_dbm = self.sense_energy_dbm(wideband=True)
        inband_dbm = self.sense_energy_dbm(wideband=False)

        visible: List[VisibleTx] = []
        for tx in list(self.channel.active_txs):
            if tx.tx_id == self.name:
                continue
            d = dist(tx.tx_pos, my_pos)
            rx_dbm = self.channel.rx_power_at(tx, my_pos, False)  # Rashed-Step 22.A-10-15-2026
            visible.append(VisibleTx(
                tx_id=tx.tx_id, tech=tx.tech, f_hz=tx.f_hz,
                distance_m=d, rx_power_dbm=rx_dbm,
                # Rashed-Step 9.B-08-07-2026: tx.packet is None unless
                # the sender populated it - see VisibleTx.packet's
                # comment.
                packet=tx.packet,
            ))

        return SpectrumSnapshot(
            wideband_energy_dbm=wideband_dbm,
            inband_energy_dbm=inband_dbm,
            is_busy_wideband=wideband_dbm >= thr,
            is_busy_inband=inband_dbm >= thr,
            visible_txs=visible,
        )

    # ------------------------------------------------------------------
    # Transmitter
    # ------------------------------------------------------------------
    def transmit(self, duration_us: float, rx_pos: Optional[Pos] = None,
                 tech_label: Optional[str] = None, tx_power_dbm: Optional[float] = None,
                 # Rashed-Step 9.B-08-07-2026-start
                 packet: Optional[Packet] = None
                 # Rashed-Step 9.B-08-07-2026-end
                 ):
        """
        SimPy process - start with env.process(device.transmit(...)).

        UNRESTRICTED: registers an ActiveTx on the shared channel the
        instant this is called - no sense-before-transmit wait, no
        backoff, no LBT/CSMA. Confirmed with Rashed for Step 7: this is
        meant to be a raw building block: callers/subclasses that want
        polite coexisting behavior call is_channel_busy() themselves
        first, in their own loop, before calling this.

        rx_pos defaults to this device's own position (no specific
        intended receiver) - fine for sniffing/jamming use cases where
        nothing is meant to "receive" it. Any other node can still
        evaluate SINR against this transmission via channel.sinr_db()
        since it's a completely normal ActiveTx like WiFi/NR-U/NR's.

        # Rashed-Step 9.B-08-07-2026-start
        packet: optional - None (default, unchanged from every pre-9.B
        call) means this transmission carries no Packet identity, same
        as before. Pass one to stamp it onto this transmission's
        ActiveTx (so other nodes' sniff() calls can see it - see
        VisibleTx.packet) and to have it appended to self.packet_log on
        successful (uninterrupted) completion. Enables future subclasses
        (e.g. a replay attacker re-transmitting a packet captured via
        sniff()) to carry real packet identity through transmit()
        without needing to reimplement the ActiveTx plumbing themselves.
        # Rashed-Step 9.B-08-07-2026-end
        """
        tech = tech_label if tech_label is not None else self.config.tech_label
        power = tx_power_dbm if tx_power_dbm is not None else self.config.tx_power_dbm
        my_pos = self.current_pos()

        tx_start = self.env.now
        active = ActiveTx(
            tx_id=self.name,
            tx_pos=my_pos,
            rx_pos=rx_pos if rx_pos is not None else my_pos,
            tx_start=tx_start,
            tx_power_dbm=power,
            f_hz=self.config.f_hz,
            pl_exp=self.config.pl_exp,
            t_end=tx_start + duration_us,
            tech=tech,
            bandwidth_mhz=self.config.bandwidth_mhz,
            noise_figure_db=self.config.noise_figure_db,
            # Rashed-Step 9.B-08-07-2026-start
            packet=packet,
            # Rashed-Step 9.B-08-07-2026-end
        )
        self.channel.register_tx(active)
        self.active_tx = active

        try:
            yield self.env.timeout(duration_us)
            # Rashed-Step 13.E.2-08-23-2026-start
            # Same "log measured SINR right where sinr_db() is already
            # natural to compute" convention as wifi.py's send_frame()/
            # nru.py's send_transmission() (Step 13.A) - here that point
            # is right after the transmission completes uninterrupted,
            # using this device's own just-completed ActiveTx (same
            # target estimate_sinr_db() would compute). Only when a
            # packet= was actually given (this class's packet identity
            # is opt-in, unlike WiFi/NR-U where every frame always
            # carries one) - unset otherwise, same as every other
            # measured_sinr_db default. NOT logged in the except branch
            # below: unlike wifi.py/nru.py's SINR-GATED success/failure
            # (both branches there represent a real channel-quality
            # measurement), this class has no MAC-level success/failure
            # concept at all - the except branch here fires on
            # simulation-ending interruption (GeneratorExit), not a bad
            # channel reading, so there's nothing meaningful to measure.
            if packet is not None:
                packet.measured_sinr_db = self.channel.sinr_db(active)
            # Rashed-Step 13.E.2-08-23-2026-end
            self.channel.unregister_tx(active, success=True)
            self.tx_log.append((tx_start, active.t_end, tech, True))
            # Rashed-Step 9.B-08-07-2026-start
            # Only logged on the uninterrupted-completion path, not the
            # except branch below - mirrors wifi.WiFi/nru.Gnb's
            # packet_log convention of only recording a terminal
            # outcome, not one still "in flight" when the sim ended.
            # NOTE this does NOT mean "delivered" in the SINR-confirmed
            # sense wifi.py/nru.py use - see this method's docstring and
            # packet_log's __init__ comment for why.
            if packet is not None:
                self.packet_log.append(packet)
            # Rashed-Step 9.B-08-07-2026-end
        except BaseException:
            # Same GeneratorExit-safe pattern as wifi.WiFi.send_frame() /
            # nru.Gnb.send_transmission() (Step 5.I): purely synchronous
            # cleanup here, no further yields, so a simulation shutting
            # down mid-transmission (env.run(until=...) returning while
            # this process is still "in flight", a near-certain
            # occurrence at the end of any run) doesn't raise "generator
            # ignored GeneratorExit".
            self.channel.unregister_tx(active, success=False)
            self.tx_log.append((tx_start, self.env.now, tech, False))
            raise
        finally:
            self.active_tx = None

    def estimate_sinr_db(self, active_tx: Optional[ActiveTx] = None) -> float:
        """
        Convenience wrapper around channel.sinr_db() for a transmission
        this device made - defaults to self.active_tx (the in-flight
        one, if transmit() is currently running). Optional: nothing in
        this base class requires it, but it's here for subclasses that
        want a receive/decode or "did my own signal land" step (e.g. a
        jammer checking its own effective range) without reimplementing
        the SINR math.
        """
        target = active_tx if active_tx is not None else self.active_tx
        if target is None:
            raise ValueError("estimate_sinr_db: no active_tx given and no transmission in flight")
        return self.channel.sinr_db(target)

    # ------------------------------------------------------------------
    # Local airtime bookkeeping (see module docstring for why this is
    # local rather than in channel.py's shared per-tech dicts)
    # ------------------------------------------------------------------
    def total_airtime_us(self, successful_only: bool = True) -> float:
        return sum(
            (t_end - t_start) for (t_start, t_end, _tech, success) in self.tx_log
            if success or not successful_only
        )

    def channel_occupancy(self, sim_duration_us: float, successful_only: bool = True) -> float:
        """Fraction of sim_duration_us this device held the channel."""
        if sim_duration_us <= 0:
            return 0.0
        return self.total_airtime_us(successful_only=successful_only) / sim_duration_us
# Rashed-Step 7.A-08-05-2026-end
