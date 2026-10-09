# Simpy Enabled Wireless Simulator

## Intro
Simulator created based on the master thesis `Jakub_Cichon_Master_s_Thesis.pdf` by Jakub Cichoń, which was based on two existing implementations:
* [Wi-Fi simulator](https://github.com/ToporPawel/DCF-Simpy)
* [NR-U simulator](https://github.com/marekzajac97/nru-channel-access)

This branch (`improved-simulator-2025`) extends that original process/collision-count-based simulator with a real physical layer (path loss, shadowing, SINR/capture-effect success decisions, per-technology MCS/frequency/bandwidth modeling, regulatory EIRP checks, node mobility), a shared real-packet abstraction (queueing/traffic models, retries, ACKs, latency/loss/jitter statistics), a protocol-agnostic generic wireless node usable as a spectrum analyzer or an attack base class, and packet-level attacker capabilities (spoofing, replay) - on top of the original Wi-Fi/NR-U CSMA/LBT coexistence logic, without changing that original access-protocol behavior. Since Steps 15-16 it also models the uplink for all three technologies (Wi-Fi CSMA/CA, NR-U Cat-4 LBT, licensed NR TDD with grant-based scheduling), an RRC connection-setup state machine, and a minimal 5G Core (AMF/SMF/UPF: registration and PDU session establishment, with the RAN carrying a UE's data only once its session is active) - all opt-in, so every earlier run is unchanged. See "Project details/" for the full, chronological design/verification log of every change (one `Step N.txt` file per major step, each with a `DONE` section per sub-step listing exactly what changed and how it was verified).

**New here?** See [`GETTING_STARTED.md`](GETTING_STARTED.md) for a short, hands-on walkthrough of all four scenarios - the sections below are the full reference.

## Installation

- (Optional) Launch virtual env: `python3 -m venv env && source env/bin/activate`
- Install requirements: `pip install -r requirements.txt`
- Requirements (see `requirements.txt`):
  - click
  - simpy
  - pandas
  - matplotlib
  - scipy

## Structure

Four independent, runnable scenarios, each with its own CLI entry point and its own `simulation_*.py` driver. They share the same underlying PHY/channel model but are kept separate on purpose (a "standalone first" convention followed since Step 6.B), so extending one scenario never risks the others' already-verified behavior:

| Scenario | CLI entry point | Driver |
|---|---|---|
| Wi-Fi + NR-U unlicensed coexistence (the main scenario) | `singleRun.py` | `simulation.py` |
| Licensed 5G NR (standalone, full RB scheduler) | `singleRunNR.py` | `simulation_nr.py` |
| Passive spectrum-analyzer sniffers over real Wi-Fi/NR-U traffic | `singleRunSpectrum.py` | `simulation_spectrum.py` |
| Packet-level attacker (spoofing/replay) over real Wi-Fi/NR-U traffic | `singleRunAttacker.py` | `simulation_attacker.py` |

Code layout:
```
common/common.py       - shared constants, Pos type, rand_pos(), Frame, log()
common/common_phy.py   - path loss, shadowing, thermal noise, MCS/SINR tables,
                          spectral overlap, EIRP caps, WaypointMobility
common/packet.py        - Packet/TrafficConfig, latency/loss/jitter stats,
                          packet-level CSV export
common/error_model.py   - link error model: hard SINR threshold (default)
                          or a BLER curve per MCS (Step 18.A)
channel/channel.py      - Channel: tx queues, ActiveTx, CCA/ED sensing, SINR
wifi/wifi.py, wifi/sta.py       - Wi-Fi AP + STA (CSMA/CA)
wifi/mac.py, ampdu.py, phy.py,  - Step 20: frame exchange (ACK/NAV/RTS/EIFS),
wifi/mgmt.py, ofdma.py            A-MPDU, HT/VHT/HE rates, beacons /
                                   association / roaming, OFDMA
nru/nru.py, nru/ue.py           - NR-U gNB + UE (Type 1 / Cat-4 LBT,
                                   unlicensed; UE uplink inside the
                                   gNB's channel occupancy time)
nr/nr.py, nr/ue.py              - Licensed 5G NR gNB + UE (scheduled, no LBT)
ran/protocol/channel_access.py  - shared channel-access strategies: NR-U
                                   Type 1 LBT, Wi-Fi DCF on a shared slot
                                   grid, licensed-NR slot scheduling
ran/protocol/rrc.py             - RRC attach state machine (IDLE ->
                                   CONNECTING -> CONNECTED), shared by NR-U
                                   and licensed NR
ran/protocol/user_plane.py      - RAN-side UPF gate (no data before a UE's
                                   PDU session is active)
ran/protocol/buffer.py          - per-UE byte buffers and traffic arrivals
                                   (segmentation across transport blocks)
ran/protocol/harq.py            - HARQ processes with chase combining
ran/protocol/l2.py              - PDCP (SN, headers, in-order delivery) +
                                   RLC UM/AM (segmentation headers, ARQ)
ran/protocol/rach.py            - 4-step random access (Step 19.A)
ran/protocol/rlm.py             - radio link monitoring, RLF, re-establishment
ran/protocol/inactive.py        - RRC_INACTIVE with resume
ran/protocol/drb.py             - one DRB per QoS flow, priority-ordered TBs
ran/protocol/handover.py        - measurements, event A3, Xn handover
ran/protocol/scell.py           - NR-U secondary cell (LAA carrier aggregation)
common/qos.py                   - 5QI table, class -> 5QI -> Wi-Fi AC mapping
core/network.py                 - minimal 5G Core: Amf, Smf, Upf,
                                   CoreNetwork, CoreConfig
core/procedures.py              - registration + PDU session procedures and
                                   their latency stats
model/                          - analytical models (Bianchi DCF, CAD-paper
                                   DTMC) and sweep harness for validation
analysis/                       - scripts that generate the paper figures
                                   into analysis/generated/
generic/generic_device.py       - GenericWirelessDevice: protocol-agnostic
                                   sniff()/transmit() base class (spectrum
                                   analyzer, attacker base, or a custom-
                                   protocol node)
attacker/packet_attacker.py     - PacketAttacker (spoof/replay), built on
                                   GenericWirelessDevice
attacker/roguewificad.py,
attacker/roguewifijammer.py,
attacker/roguewifiselfbackoff.py - CAD-attack-paper-related attacker models
                                    (roguewificad.py is wired into
                                    singleRun.py's --rogue flag; the other
                                    two are standalone/not currently wired in)
test/                            - assert-based regression test suite
                                    (run via `pytest test/` or
                                    `python test/test_X.py` directly)
Project details/                 - design/verification log, one Step N.txt
                                    per major step, plus a top-level
                                    "STATUS - resume context.txt"
```

## Usage

Every scenario supports `--help` for its full, current flag list - the summaries below are grouped by feature area rather than reproduced in full, since the underlying flag set has grown substantially since Steps 5-9 and is easiest to keep accurate by reading directly from `--help`.

### Wi-Fi + NR-U coexistence (`singleRun.py`)

The main scenario: Wi-Fi APs (CSMA/CA) and NR-U gNBs (Cat-4 LBT) contending for the same 5 GHz unlicensed spectrum.

```bash
python singleRun.py --help
```

Flag groups (see `--help` for exact names/defaults/full descriptions):
- **Topology**: `--ap-number`/`--gnb-number` (required), `--area-w`/`--area-h`, `--ap-pos`/`--gnb-pos` (explicit placement), `--sta-radius`/`--ue-radius`
- **MAC parameters**: `--wifi_cw_min`/`--wifi_cw_max`/`--nru_cw_min`/`--nru_cw_max`, `--wifi_r_limit`/`--nru_r_limit`, `-m`/`--mcs-value`, `--mcot`, `-syn_slot`, `-max_des`/`-min_des`, `-nru_obser_slots`
- **PHY realism (Step 5)**: `--shadowing-sigma-db`, `--wifi-bandwidth-mhz`/`--nru-bandwidth-mhz`, `--wifi-noise-figure-db`/`--nru-noise-figure-db`, `--nru-mcs`, `--wifi-sinr-thr-db-override`/`--nru-sinr-thr-db-override`, `--wifi-freq-ghz`/`--nru-freq-ghz`, `--wifi-tx-power-dbm`/`--nru-tx-power-dbm` (checked against FCC U-NII EIRP caps at startup, warning only)
- **Mobility (Step 5.G)**: `--ap-mobility-speed-mps`, `--gnb-mobility-speed-mps`, `--sta-mobility-speed-mps`, `--ue-mobility-speed-mps`, `--mobility-pause-s`
- **Traffic model / real packets (Step 8)**: `--wifi-traffic-model`/`--nru-traffic-model` (`saturated`/`poisson`/`cbr`), `--wifi-arrival-rate-pps`/`--nru-arrival-rate-pps`, `--wifi-packet-size-bytes`/`--nru-packet-size-bytes`
- **Packet-level CSV export (Step 9.D/10.E/13.A)**: `--export-packets-csv <path>` - appends one row per packet (technology, node, id, source/destination, sizes, status, latency, traffic class, measured SINR) for offline analysis
- **QoS/QoE (Step 10.A-10.D, Wi-Fi)**: `--wifi-traffic-class-mix`/`--nru-traffic-class-mix` (repeatable `class=weight`, tags packets voice/video/best_effort/background), `--wifi-edca` (real 802.11e differentiated channel access per class, Wi-Fi only, requires `--wifi-traffic-model=saturated`) - printed per-class latency/loss/SLA-compliance stats and QoE scores (voice: real E-model MOS; video: a labeled heuristic proxy) come free once a class mix is set, no extra flag needed
- **Dynamic rate adaptation (Step 11)**: `--wifi-rate-adapt` (per-STA ARF - Auto Rate Fallback, Kamerman & Monteban 1997: step MCS up after 10 consecutive successes, down after 2 consecutive failures, no channel-state feedback), `--nru-rate-adapt` (per-UE CQI-style - picks the MCS whose required-SINR threshold best fits the most recently measured link SINR, approximating 3GPP UE-reported Channel Quality Indicator feedback). Both default off (`-m`/`--mcs-value` and `--nru-mcs` stay fixed for the whole run, unchanged from every pre-Step-11 run).
- **Rogue AP**: `--rogue True` (routes AP traffic through `attacker/roguewificad.py`'s CAD-attack model instead of benign Wi-Fi)
- **Uplink (Steps 15.B/15.C, pre_17.B)**: `--wifi-sta-uplink-enabled` (every STA contends with CSMA/CA and sends saturated uplink to its AP; prints a "Wi-Fi Uplink" block; not with `--rogue True`), `--nru-ue-uplink-enabled` (NR-U uplink; how UEs reach the channel is set by `--nru-ul-access-mode`: `cot_sharing` (default, Step 17) - the gNB splits each channel occupancy time into a downlink part and an uplink part granted to one of its UEs, who sends after a 25 us Type 2A check; `autonomous` (Step 15.C) - every UE runs its own Cat-4 LBT, which collides with its own gNB, kept for comparison), `--nru-ul-cot-fraction` (uplink share of the COT, default 0.5). With NR-U uplink on, an "NR-U Uplink" block reports throughput, attempts and (in cot_sharing) windows and skipped grants
- **NR-U user plane (Step 18, opt-in)**: `--nru-cot-model slots` (the COT's downlink becomes NR slots with one transport block per UE per slot, RBs shared max-min fair, per-slot SINR and a CQI-based MCS; the COT-sharing uplink window becomes slots on interlaces shared by up to 5 UEs; prints an "NR-U Slots" block), `--nru-numerology`, `--nru-buffer-limit-bytes`, `--nru-ul-traffic-model` / `--nru-ul-arrival-rate-pps`; with slots also `--harq` (+ `--harq-max-tx`, `--harq-rtt-slots`) and `--rlc-mode um|am` (+ `--pdcp-sn-bits`, `--rlc-am-max-retx`, `--rlc-am-status-delay-ms`). `--error-model bler` (any model) replaces the hard SINR threshold with a block-error-rate curve, for Wi-Fi too. See "5G user plane" below
- **RRC and 5G Core (Steps 15-16, NR-U only)**: `--nru-rrc-enabled` (RRC connection setup before any data; needs `--nru-ue-uplink-enabled`), `--nru-core-enabled` (registration + PDU session; no NR-U data to/from a UE until its session is active), `--core-registration-delay-us` / `--core-pdu-session-delay-us` (override the 90 ms / 125 ms defaults; need `--nru-core-enabled`). See "5G control plane" below.

Example:
```bash
python singleRun.py --ap-number 2 --gnb-number 2 -t 1 -r 1
python singleRun.py --ap-number 1 --gnb-number 1 -t 1 -r 1 --mcot 10 -syn_slot 500 --rogue True
python singleRun.py --ap-number 2 --gnb-number 1 -t 0.1 --area-w 50 --area-h 50 --seed 1 --shadowing-sigma-db 4 --ap-mobility-speed-mps 1.4 --wifi-traffic-model poisson --export-packets-csv packets.csv
```
Sample output (2 AP / 2 gNB, defaults):
```
SEED = 1 N_stations:=2 N_gNB:=2  CW_MIN = 15 CW_MAX = 63 WiFi pcol:=0.1217 WiFi cot:=0.8879164 WiFi eff:=0.88074 gNB pcol:=0.0000 gNB cot:=0.0354 gNB eff:=0.0354  all cot:=0.9233164 all eff:=0.91614
 Wifi succ: 1631 fail: 226
 NR succ: 59 fail: 0
fairness: 0.5398053473945499
joint: 0.4984111300570852
```
(Plus, since Step 8.G/9.A, per-technology and per-node packet stats: delivery/loss counts, average/min/max/stddev/jitter/p50/p95/p99 latency. Since Step 10.C/10.D, also per-traffic-class stats with SLA-budget compliance and QoE scores - "best_effort" is the only class shown unless `--wifi/nru-traffic-class-mix` is set.)

### Licensed 5G NR, standalone (`singleRunNR.py`)

A full-scheduler licensed-spectrum NR gNB/UE model (round-robin or proportional-fair RB scheduling, numerology-based slot timing, no LBT) - built and verified standalone (Step 6.B), not integrated into the unlicensed coexistence scenario above.

```bash
python singleRunNR.py --help
python singleRunNR.py --gnb-number 1 --ues-per-gnb 4 -t 1 --scheduler proportional_fair
```

Uplink, RRC and Core flags (Steps 15.E-16.F): `--tdd-enabled` / `--tdd-pattern` (TDD slot pattern, default `DDDU`), `--ue-uplink-enabled` (grant-based uplink after a one-time scheduling request), `--rrc-enabled` (needs `--ue-uplink-enabled`), `--core-enabled`, `--core-registration-delay-us` / `--core-pdu-session-delay-us`.

```bash
python singleRunNR.py --gnb-number 1 --ues-per-gnb 2 -t 0.5 --tdd-enabled --ue-uplink-enabled --rrc-enabled --core-enabled
```

User-plane flags (Step 18): `--dl-traffic` / `--ul-traffic` `full_buffer|poisson|cbr` with `--dl-arrival-rate-pps` / `--ul-arrival-rate-pps`, `--packet-size-bytes`, `--buffer-limit-bytes` (per-UE buffers; only UEs with data are scheduled), `--error-model bler`, and on buffered traffic `--harq` and `--rlc-mode um|am`. With uplink on, a "Licensed 5G NR Uplink Results" block is printed (Step pre_18.F).

### 5G control plane: RRC and 5G Core (Steps 15-16)

With RRC and the Core turned on, every UE goes through one attach chain before it may carry data: **RRC connection setup -> NAS registration (AMF) -> PDU session establishment (SMF/UPF)**. The RAN schedulers (licensed NR downlink/uplink, NR-U downlink/uplink) only serve a UE once its session is active.

| Stage | Default | Source / note |
|---|---|---|
| RRC setup, licensed NR | 4 ms | 2 x 1 ms uplink grant + 2 ms gNB processing; within 3GPP TR 38.913's 10 ms control-plane target |
| RRC setup, NR-U | 4 ms + COT wait | same grant cost, then each RRC message waits for its gNB's next channel occupancy time and a 25 us Type 2A check (COT sharing, default) - never faster than licensed NR: ~13.7 ms in a single cell, ~20 ms alongside a Wi-Fi AP in the sample run below |
| Registration | 90 ms | measured Open5GS 5G SA testbed (arXiv:2412.21162); `--core-registration-delay-us` |
| PDU session | 125 ms | same testbed; `--core-pdu-session-delay-us` |

Both CLIs print an "RRC Connection Setup" block and a "5G Core" block (registration, PDU session, full attach latency, attach-to-first-packet latency). Sample from the licensed-NR command above:
```
NR mean registration latency (us): 90000.0
NR mean PDU session latency (us): 125000.0
NR mean attach latency, start -> session active (us): 219000.0
NR mean attach-to-first-packet latency (us): 219500.0
```
Keep runs longer than the attach time (about 0.22 s at defaults) - a shorter run carries no data at all. Scope is deliberately minimal: one Core per run, one data network, no slicing, and registration/sessions always succeed (no rejects or retries yet). The registration and PDU-session delays are fixed inputs, not something the simulator measures, so they dominate the attach time at defaults.

Figures: `python -m analysis.rrc_connection_setup_latency` (RRC setup per technology) and `python -m analysis.core_attach_latency` (stacked RRC / registration / PDU session breakdown), written to `analysis/generated/`.

### 5G user plane: error model, buffers, slots, HARQ, PDCP/RLC (Step 18)

All opt-in; every default run is unchanged. The layers stack from the radio up:

| Layer | Flag | What it does |
|---|---|---|
| Error model | `--error-model bler` | a frame/transport block decodes with a probability from a BLER curve per MCS (10% at the MCS's SINR threshold, the 3GPP CQI definition) instead of a hard threshold; all technologies |
| Buffers | `--dl-traffic` / `--ul-traffic` (NR), `--nru-traffic-model` (NR-U slots) | per-UE byte queues; a transport block carries what is queued, splitting packets across blocks |
| NR-U slots | `--nru-cot-model slots` | the COT's downlink is a run of NR slots (30 kHz: 500 us, 51 RBs in 20 MHz) shared by the cell's UEs; uplink window on interlaces (TS 38.211) after one joint Type 2A check; TS 37.213 reference-slot rule for the contention window |
| HARQ | `--harq` | failed blocks retransmitted after a round trip with chase combining, up to 4 attempts |
| PDCP / RLC | `--rlc-mode um\|am` | PDCP sequence numbers, headers and in-order delivery; RLC/MAC segmentation headers; AM retransmits what HARQ couldn't recover |

Example (licensed NR, error model on, 8 UEs heavily loaded, 1 s): block-error drops 6131 packets -> 17 with `--harq` -> 0 with `--harq --rlc-mode am`. NR-U alone goes from 1.7 Mbps (burst: one packet per 6 ms COT) to 92.7 Mbps with `--nru-cot-model slots`. Not modeled yet: uplink power control, PDCCH/DMRS overhead, delayed CSI/HARQ feedback, ROHC/ciphering.

```bash
python singleRunNR.py --gnb-number 2 --ues-per-gnb 4 --seed 2 -t 1 --error-model bler --dl-traffic poisson --dl-arrival-rate-pps 3000 --harq --rlc-mode am
python singleRun.py --ap-number 1 --gnb-number 1 -t 1 -r 1 --nru-cot-model slots --nru-ue-uplink-enabled --nru-traffic-model poisson --nru-arrival-rate-pps 1500 --harq --rlc-mode am
```

### Spectrum analyzer (`singleRunSpectrum.py`)

Drops passive `GenericWirelessDevice` sniffer nodes (Step 7.A/7.B) into a real Wi-Fi + NR-U topology and periodically samples the channel (wideband/in-band energy, busy fraction, per-technology duty cycle) - the same way a real spectrum analyzer would, with no privileged access to the simulator's internal bookkeeping.

```bash
python singleRunSpectrum.py --help
python singleRunSpectrum.py --ap-number 2 --gnb-number 1 --sniffer-number 2 -t 1
```

### Packet-level attacker (`singleRunAttacker.py`)

Drops `PacketAttacker` nodes (Step 9.C, built on `GenericWirelessDevice`) into a real Wi-Fi + NR-U topology, driven through a capture -> spoof -> replay timeline: passively sniffs real traffic, then transmits packets with a forged source identity and/or re-transmits exact captured content, from the attacker's own real physical position/power. Prints real Wi-Fi/NR-U succ/fail counts alongside the attack results, so the attack's actual channel-level impact (airtime, SINR degradation for legitimate traffic) is directly comparable to a no-attack run.

```bash
python singleRunAttacker.py --help
python singleRunAttacker.py --ap-number 2 --gnb-number 1 -t 0.1 --spoof-target "AP 1" --spoof-count 5 --replay-max 3
```

### SINR/channel-quality dataset generation (`ml/generate_sinr_dataset.py`)

Step 13.B: runs a documented grid of Wi-Fi + NR-U coexistence scenarios (varying distance, shadowing, mobility, interferer count) - the data prerequisite for the SINR-prediction work in `Project details/Step 13.txt`. Each scenario writes its own timestamped packet CSV (non-destructive - rerunning never overwrites a prior sweep's files) plus an appended row in a shared manifest. Output goes to `ml/data/` (gitignored, regenerate by re-running the script).

```bash
python ml/generate_sinr_dataset.py
```

### SINR prediction: baseline + model (`ml/train_sinr_model.py`)

Step 13.C: trains a lag-3 persistence baseline and a gradient-boosting model (scikit-learn) on the Step 13.B dataset, split by scenario (not row) so results reflect genuine generalization to unseen scenarios. Reports metrics separately for links with real SINR variation vs. links that are mathematically constant (static, unshadowed, non-interfered links - not a bug, see the script's docstring) so a trivial case can't inflate the headline number. Current honest result: the model does not beat the persistence baseline on MAE for held-out scenarios (though it does on RMSE) - see `Project details/Step 13.txt` for the full writeup and why this motivates richer per-packet features next.

```bash
python ml/train_sinr_model.py
```

### ML-driven NR-U rate adaptation (`ml/predictor.py`, Step 13.D)

Opt-in flag `--nru-rate-adapt-ml-model <path>` (requires `--nru-rate-adapt` also set) swaps NR-U's CQI-style MCS pick from "last measured SINR" to a Step 13.C model's *predicted* next SINR, once a link has enough history. Demonstrates the simulator is easy to extend with an ML-in-the-loop pathway (zero cost when the flag is unused - `ml/predictor.py`'s sklearn/pandas imports are lazy). The predictor is automatically skipped (falls back to plain last-observed) whenever a link's recent SINR history is exactly constant - a fix for a real collapse bug found and root-caused after this feature shipped (a constant history can lock the model onto a persistently wrong prediction with no way to self-correct). With that fix in place, re-measured result: on a static link the predictor is now byte-for-byte identical to the heuristic (97.9% PDR both, 20 seeds); on a mobile link there's no meaningful difference either (69.0% vs 68.5% PDR). See `Project details/Step 13.txt` for the full comparison, including the original (now-superseded) pre-fix numbers.

```bash
python singleRun.py --nru-rate-adapt --nru-rate-adapt-ml-model ml/data/sinr_model.joblib -t 0.1
```

### ML-driven Wi-Fi rate adaptation (Step 13.E.1)

Same idea, mirrored onto Wi-Fi: `--wifi-rate-adapt-ml-model <path>` (requires `--wifi-rate-adapt`) switches Wi-Fi from ARF's success/fail-streak logic to a CQI-style MCS pick from the model's predicted SINR, once a link has enough history - reuses the same `ml/data/sinr_model.joblib` (it already has a `technology_is_wifi` feature). Initial testing found the predictor could fully collapse a static/constant-SINR link (a persistently wrong prediction with no way to self-correct from an unchanging history) - fixed by skipping the predictor whenever the recent history is exactly constant, falling back to plain ARF instead (same fix applied to NR-U's 13.D). With the fix, re-measured result (20 seeds each): on a static link the predictor is now byte-for-byte identical to ARF (89.9% PDR both, zero remaining risk); on a mobile link the predictor gives a genuine, modest, reproducible win (72.6% vs 76.0% PDR). See `Project details/Step 13.txt`'s 13.E.1 section for the full comparison, root-cause analysis, and the fix.

```bash
python singleRun.py --wifi-rate-adapt --wifi-rate-adapt-ml-model ml/data/sinr_model.joblib -t 0.1
```

### Generic-device SINR logging (Step 13.E.2)

`GenericTransmitter`/`GenericWirelessDevice` now populate `measured_sinr_db` on every completed transmission that carries a `Packet` (same convention as Wi-Fi/NR-U, Step 13.A) - no rate-adaptation counterpart exists here since this class has no MCS/data-rate concept at all. Opt-in `--export-packets-csv <path>` on `singleRunGeneric.py` exports these rows (technology bucket `"GENERIC"`) via the same technology-agnostic CSV format every other scenario uses.

```bash
python singleRunGeneric.py --ap-number 1 --gnb-number 1 --generic-number 2 -t 0.05 --export-packets-csv generic_packets.csv
```

### Licensed NR: SINR logging + ahead-of-time rate adaptation (Step 13.E.3)

`nr.py`'s existing `select_mcs_for_sinr()` pick is a "genie-aided" oracle - it already runs AFTER a slot's real SINR is known, so no predictor could ever legitimately beat it. Step 13.E.3 adds a genuine, fallible AHEAD-OF-TIME mode instead: `--rate-adapt` picks a UE's MCS from its last-measured SINR BEFORE the slot's real SINR is known (a wrong guess now really fails, unlike the oracle); `--rate-adapt-ml-model <path>` swaps that for the model's prediction. `--export-packets-csv <path>` exports per-slot packets (technology `"NR"`), each with `measured_sinr_db`. Honest result: in the one scenario tested, ordering was consistent across 20 seeds - oracle (46.3% slot success, an unbeatable ceiling) > ahead-of-time heuristic (37.7%) > ahead-of-time ML-driven (22.5%), the clearest negative ML result in Step 13, most likely because the reused model was trained on Wi-Fi/NR-U data, not licensed NR's very different SINR regime. See `Project details/Step 13.txt`'s 13.E.3 section for the full writeup.

```bash
python singleRunNR.py --gnb-number 1 --ues-per-gnb 3 -t 0.1 --rate-adapt --rate-adapt-ml-model ml/data/sinr_model.joblib --export-packets-csv nr_packets.csv
```

### 5G control plane, mobility and the unified run (Step 19)

All opt-in; every default run is unchanged.

| Feature | Flags | What it does |
|---|---|---|
| Random access | `--rach` (+ `--prach-period-ms`, `--rach-backoff-ms`, `--rar-window-ms`) | 4-step RACH before RRC: PRACH occasions every 10 ms, 64 preambles, power ramping, RAR, contention resolution; a UE that runs out of preambles goes back to IDLE (NR-U: Msg1 after a channel check, RAR rides a gNB COT) |
| RRC Type 1 fallback | `--nru-rrc-type1-fallback N` | NR-U, COT sharing: after N failed Type 2A checks an RRC message goes out after the UE's own Cat-4 LBT (hidden-node attach: 212 -> 51 ms) |
| Radio link failure | `--rlm` (+ `--t310-ms`, `--t311-ms`) | Qout/Qin monitoring, T310, radio link failure, RRC re-establishment at the best cell, or IDLE |
| RRC_INACTIVE | `--rrc-inactive` (+ `--inactivity-timer-ms`, `--paging-cycle-ms`) | idle UEs suspended; uplink data resumes at once, downlink data at the next paging occasion; no Core signaling |
| RRC reconfiguration | `--rrc-reconfig` (+ `--rrc-reconfig-ms`) | data radio bearer set up (10 ms UE processing) before the user plane opens, and after a re-establishment |
| QoS flows / 5QI | `--qos-flows`, `--traffic-class-mix` | one DRB per 5QI (voice 1, video 2, best effort 8, background 9 - the same classes as Wi-Fi's access categories), transport blocks filled in priority order |
| Handover | `--handover` (licensed NR; `--nr-handover` in the unified run, + `--a3-offset-db`, `--ttt-ms`) | L3-filtered RSRP, event A3 with time-to-trigger, Xn preparation, HO command, execution, random access at the target; interruption and ping-pongs reported |
| Core failure modes | `--core-registration-reject-prob`, `--core-pdu-reject-prob`, `--core-retry-ms`, `--core-amf-capacity`, `--core-smf-capacity`, `--core-service-ms` | rejects with retries and give-up (TS 24.501), AMF/SMF capacity limits (signaling storms queue) |
| Unified run | `singleRun.py --nr-gnb-number N` (+ `--nr-colocated`, `--nr-f-ghz`, `--nr-*`) | licensed-NR cells in the same run as Wi-Fi and NR-U - same channel (own band, 3.5 GHz, by default), one 5G Core for every UE |
| NR-U secondary cell | `--nru-scell` | LAA-anchored carrier aggregation: each licensed UE gets an NR-U SCell on the co-located NR-U gNB; one downlink queue served by both carriers, control plane and uplink on the licensed PCell |

Examples:

```bash
python singleRunNR.py --gnb-number 2 --ues-per-gnb 4 --gnb-pos 300,500 --gnb-pos 900,500 --area-w 1200 --area-h 1000 --ue-radius 150 --ue-mobility-speed-mps 20 --seed 3 -t 30 --tdd-enabled --ue-uplink-enabled --rrc-enabled --dl-traffic poisson --dl-arrival-rate-pps 200 --rach --rlm --handover
python singleRun.py --ap-number 1 --gnb-number 1 --seed 1 -t 1 -r 1 --nru-cot-model slots --nru-traffic-model poisson --nru-arrival-rate-pps 20 --nr-gnb-number 1 --nr-colocated --nr-bandwidth-mhz 20 --nr-dl-traffic poisson --nr-dl-arrival-rate-pps 4000 --nru-scell --harq
```

The second one is the LAA case: an overloaded 20 MHz licensed cell (193 Mbps offered) delivers 108 Mbps on its own and about 133 Mbps with the NR-U SCell (19% carried in unlicensed spectrum) - while the Wi-Fi neighbor drops from about 30 to 3 Mbps, because the SCell's deep queue keeps NR-U on the channel most of the time even with LBT (studied in Step pre_20, below). Not modeled yet: NR-U handover, cross-UE QoS scheduling, GBR enforcement, 2-step / contention-free RACH, SCell uplink.

### LAA / NR-U fairness study (Step pre_20)

Is NR-U fair to Wi-Fi, and what fixes it? Scored with the 3GPP replacement test (NR-U must not hurt a Wi-Fi network more than another Wi-Fi network would). Full write-up with figures: [`docs/laa_fairness_study.md`](docs/laa_fairness_study.md). All flags opt-in; every default run is unchanged.

| Feature | Flags | What it does |
|---|---|---|
| Fairness report | `--fairness-report` | per-technology airtime share (failed transmissions included), successful airtime, failure ratio, throughput, latency, Jain's index, per-AP / per-gNB results |
| 802.11 preamble detection | `--wifi-preamble-detect` | Wi-Fi defers to Wi-Fi frames from -82 dBm and to other signals from -62 dBm (energy detection) |
| Wi-Fi A-MPDU | `--wifi-ampdu N` (+ `--wifi-max-ppdu-us`) | AP downlink: up to N MPDUs per channel access in one PPDU (max 5.484 ms), per-MPDU decoding, Block Ack, per-MPDU retries |
| Priority classes | `--nru-priority-class 1-4` | TS 37.213 channel access priority class: defer slots, CW_min/CW_max and MCOT (gNB downlink table; UEs' own Type 1 LBT use the uplink table) |
| ED threshold | `--nru-ed-mode ts37213`, `--nru-ed-threshold-dbm` | NR-U energy-detection threshold from TS 37.213 clause 4.1.5 (from tx power and bandwidth; -72 dBm at 23 dBm / 20 MHz), or any value |
| COTs visible to Wi-Fi | `--nru-wifi-reservation preamble\|cts_to_self` (needs `--wifi-preamble-detect`) | NR-U transmissions carry an 802.11 preamble, or the gNB sends a CTS-to-self (44 us + SIFS) whose NAV covers the COT |
| Reference-slot feedback | `--nru-ref-nack-threshold`, `--nru-adaptive-cot` | contention window grows when this share of the reference slot's blocks fail (TS 37.213 Z, default 0.8); adaptive COT halves the next COT after a failed reference slot |

Findings in short: the unfairness is a sensing problem - between about 32 and 45 m neither side hears the other by energy detection while NR-U still breaks Wi-Fi frames (network A latency 75.6 vs 7.5 ms next to Wi-Fi). Priority classes, the standard 37.213 threshold and reference-slot feedback don't fix it (feedback can't see it at all: NR-U's own reference slots never fail there). A lower NR-U threshold (-82 dBm, non-standard) plus CTS-to-self passes the replacement test at every distance up to 60 m with ~0 Wi-Fi frame failures.

```bash
python singleRun.py --ap-number 1 --gnb-number 1 --seed 1 -t 1 -r 1 --nru-cot-model slots --wifi-preamble-detect --fairness-report --nru-ed-threshold-dbm -82 --nru-wifi-reservation cts_to_self
python -m analysis.laa_fairness_sweeps          # distance / load / A-MPDU sweeps
python -m analysis.laa_fairness_mitigations     # priority classes, ED threshold, preamble / CTS-to-self
python -m analysis.laa_scell_mitigations        # the Step 19.F LAA scenario per mitigation
```

### Full-stack Wi-Fi (Step 20)

The Wi-Fi side brought up to the 5G side's depth. All opt-in; every default run is unchanged.

| Feature | Flags | What it does |
|---|---|---|
| Frame exchange on the air | `--wifi-mac-exchange` (+ `--wifi-rts-threshold BYTES`) | ACK / Block Ack transmitted by the receiver after SIFS (they can collide, are sensed, NR-U sees them); NAV from every decoded frame; EIFS after an undecoded one; RTS/CTS above the threshold. With it the collision probability of co-located APs matches Bianchi's model (it was ~0.05 low) |
| STA uplink traffic | `--wifi-sta-traffic-model poisson\|cbr`, `--wifi-sta-arrival-rate-pps` | per-STA queues; a STA contends only while backlogged |
| EDCA with queues | `--wifi-edca` with `--wifi-traffic-model poisson\|cbr` | one queue per access category; an AC contends only while backlogged |
| A-MPDU everywhere | `--wifi-ampdu N` | now also on EDCA (per AC, capped by its TXOP limit: voice 1.504 ms, video 3.008 ms) and STA uplink |
| 802.11n/ac/ax PHY | `--wifi-phy ht\|vht\|he`, `--wifi-channel-width 20\|40\|80\|160`, `--wifi-gi`, `-m` | standard rates (one stream; e.g. VHT80 MCS 9 433 Mbps, HE80 MCS 11 600 Mbps), HT/VHT/HE preambles, SINR thresholds to 1024-QAM, wider channel = more noise; control responses stay non-HT |
| Management plane | `--wifi-management` (+ `--wifi-beacon-interval-ms`, `--wifi-scan-ms`, `--wifi-roam-threshold-dbm`, `--wifi-roam-hysteresis-db`) | beacons (PIFS, 6 Mbps); STAs scan, authenticate and associate with the strongest AP; data only to/from associated STAs; roaming with the interruption measured |
| OFDMA (802.11ax) | `--wifi-ofdma` (+ `--wifi-ofdma-max-users`), `--wifi-ul-ofdma` (needs `--wifi-phy he`) | downlink HE MU PPDUs on resource units (26-996 tones, each its own transmission); trigger-based uplink - STAs then send only when triggered |

Two channel-model fixes came with it: a Wi-Fi frame's SINR now counts one interferer's back-to-back frames once (pre_20.D.3a), and interference / sensed energy use the share of the transmitter's power in the receiver's band, which matters as soon as bandwidths differ (pre_20.C0).

```bash
python singleRun.py --ap-number 3 --gnb-number 1 --seed 1 -t 0.5 -r 1 --wifi-mac-exchange --wifi-preamble-detect --wifi-rts-threshold 1000 --wifi-edca --wifi-traffic-model poisson --wifi-arrival-rate-pps 2000 --wifi-ampdu 16
python singleRun.py --ap-number 1 --gnb-number 0 --seed 1 -t 0.3 -r 1 --wifi-phy he --wifi-channel-width 80 -m 11 --wifi-ampdu 64 --wifi-mac-exchange
python singleRun.py --ap-number 2 --gnb-number 0 --seed 1 -t 5 -r 1 --ap-pos 0,10 --ap-pos 60,10 --area-w 60 --area-h 20 --sta-mobility-speed-mps 10 --wifi-management --wifi-traffic-model poisson --wifi-arrival-rate-pps 500 --wifi-mac-exchange --wifi-preamble-detect
python singleRun.py --ap-number 1 --gnb-number 1 --seed 1 -t 0.5 -r 1 --wifi-phy he --wifi-ofdma --wifi-ampdu 16 --wifi-sta-uplink-enabled --wifi-ul-ofdma --wifi-mac-exchange --wifi-preamble-detect
```

Some numbers: HE80 MCS 11 delivers 518.7 of its 600.5 Mbps with 64-MPDU A-MPDUs and ACKs on the air, but VHT80 MCS 9 without aggregation only 54.7 of 433 Mbps (per-access overhead); roaming between two APs 60 m apart costs 2.5-3.4 ms; with 9 STAs at high uplink load, trigger-based OFDMA halves the latency of contended uplink (7.4 -> 3.7 ms, no collisions). Not modeled yet: MU-MIMO / several spatial streams, active scanning, WPA2 handshakes, power save, OFDMA with EDCA. Single-user downlink still addresses every packet to the AP's first STA (an old simplification).

## Testing

Assert-based regression suite (no print-and-eyeball scripts for anything added since Step 5.H) - covers PHY primitives, the packet system, `GenericWirelessDevice`, `PacketAttacker`, the analytical models, uplink for all three technologies, RRC, and the 5G Core (including CLI-level tests):
```bash
pip install pytest
pytest test/
```
597 tests passing as of Step 20. Most files are also runnable directly (`python test/test_phy_unit.py`, etc.) without pytest installed.

## Current Work Status

----> Step 1 — Add topology + distance (positions)
----> Step 2 — Add path loss + received power (RSSI)
----> Step 3 — Per-node CCA / ED-based channel sensing
----> Step 4 — Hidden/exposed terminal + SINR-based success/failure
----> Step pre_5 — Bug fixes: multi-AP/gNB topology, WiFi airtime reporting, MCS-based frame duration, rogue AP reconnected onto ED/SINR pipeline
----> Step 5 (5.A-5.I) — PHY realism: configurable placement, log-normal shadowing, real thermal noise floor, MCS-adaptive SINR thresholds, frequency/spectral-overlap-aware interference and CCA, per-technology tx queues, regulatory EIRP caps, node mobility, PHY unit test suite, GeneratorExit fix
----> Step 6 (6.A-6.E) — Real same-technology collisions (removed tx_queue serialization), standalone licensed 5G NR mode (full scheduler), airtime-undercounting-race bugfix, benign-scenario validation against a published CAD-paper DTMC model, full regression pass
----> Step 7 (7.A-7.C) — GenericWirelessDevice (protocol-agnostic sniff()/transmit() base class), spectrum-analyzer CLI scenario, shadowing/mobility/EIRP parity for that scenario
----> Step 8 (8.A-8.G) — Real Packet abstraction: Packet/TrafficConfig data structures, per-node queue with saturated/poisson/cbr traffic models, packet-size-driven Wi-Fi PPDU duration, NR-U retry-limit parity fix, r_limit-exceeded queue-routing fix, real ACK packets, latency/loss stats collector
----> Step 9 (9.A-9.D) — Extended traffic analytics (jitter/percentile latency/per-node breakdown), real Packet visibility wired into GenericWirelessDevice, packet-level attacker capabilities (spoofing + replay, PacketAttacker + a full runnable scenario), packet-level CSV export
----> Step pre_10 — readme.md full refresh to reflect Steps 5-9
----> Step 10 (10.A-10.E) — QoS/QoE: traffic-class tagging (voice/video/best_effort/background), real 802.11e EDCA differentiated channel access for Wi-Fi (per-AC virtual contention, opt-in via `--wifi-edca`), per-class latency/loss stats with SLA-budget compliance, QoE scoring (voice: real simplified ITU-T G.107 E-model MOS; video: a clearly-labeled heuristic proxy), traffic_class column added to the packet-level CSV export
----> Step pre_11 (A-E) — analytical validation `model/` package (Bianchi DCF + CAD-paper DTMC, plus a w=1..6 sweep harness), console-output cleanup (packet stats moved to `packet.log`), repo hygiene pass
----> Step 11 — dynamic per-link MCS rate adaptation: `--wifi-rate-adapt` (ARF - Auto Rate Fallback, Kamerman & Monteban 1997: blind consecutive-success/failure counters, matching real legacy 802.11 hardware), `--nru-rate-adapt` (CQI-style - picks the MCS that best fits the most recently measured link SINR, approximating 3GPP UE-reported Channel Quality Indicator feedback). Both opt-in, both default off (byte-identical to every pre-Step-11 run)
----> Step 13.A — per-packet channel-quality logging: `Packet.measured_sinr_db`, populated at every WiFi/NR-U transmission attempt (success AND failure alike), exported as a new trailing `measured_sinr_db` column in the packet-level CSV. Prerequisite for the SINR/channel-quality prediction work (see `Project details/Step 13.txt`) - a first step toward an IEEE CCNC 2027 submission demonstrating the simulator's extensibility as open-source software for wireless networking research
----> Step 13.B — documented 24-scenario SINR dataset generation (`ml/generate_sinr_dataset.py`), one timestamped packet CSV per scenario, non-destructive
----> Step 13.C — persistence baseline + gradient-boosting SINR predictor (`ml/train_sinr_model.py`), split by scenario not row; honest result: model doesn't beat persistence on MAE for variable links (does on RMSE)
----> Step 13.D — closes the loop: opt-in `--nru-rate-adapt-ml-model` flag drives NR-U rate adaptation from the Step 13.C model's predictions instead of raw last-measured SINR (`ml/predictor.py`)
----> Step 13.E.1 — same ML-driven closed loop mirrored onto Wi-Fi's ARF (`--wifi-rate-adapt-ml-model`, reuses the same trained model)
----> Step 13.D/13.E.1 FIX — found and fixed a real collapse bug (predictor could permanently lock a genuinely constant-SINR link onto an unreachable MCS); with the fix, the predictor is now provably safe on static links (identical to the heuristic) for both technologies, and gives a genuine modest win for Wi-Fi on mobile links (no meaningful difference for NR-U's mobile case)
----> Step 13.E.2 — SINR logging extended to GenericWirelessDevice/GenericTransmitter (`measured_sinr_db` populated on every completed transmission carrying a Packet); new `--export-packets-csv` flag on `singleRunGeneric.py`. No rate-adaptation counterpart - this device class has no MCS/data-rate concept
----> Step 13.E.3 — licensed NR (`nr/nr.py`) gains full Packet/SINR-logging parity plus a new opt-in ahead-of-time rate-adaptation mode (`--rate-adapt`/`--rate-adapt-ml-model`) alongside its existing oracle/post-hoc MCS pick. Honest result: oracle > heuristic > ML-driven consistently across 20 seeds, the clearest negative ML finding in Step 13 (likely domain mismatch - the reused model was trained on Wi-Fi/NR-U data). STEP 13.E (13.E.1-13.E.3) IS NOW FULLY COMPLETE
----> Step 14 — `analysis/` figure scripts for the IEEE CCNC 2027 paper (model-vs-simulation occupancy with 95% CIs, sensing-region impact, mobility transition, Wi-Fi/NR-U performance comparison, ML figures), one shared house style
----> Step pre_15 — 5G architecture assessment + roadmap; dead-code cleanup (channel2.py) and Pos/dist de-duplication
----> Step 15 (15.A-15.H) — bidirectional links: shared channel-access strategies, uplink for Wi-Fi (CSMA/CA), NR-U (Cat-4 LBT) and licensed NR (TDD + scheduling request/grant), NR-U deployment modes (MultiFire default), generic RRC attach state machine, scheduler gating on RRC state, RRC setup-latency metric and figure
----> Step 16 (16.A-16.H) — minimal 5G Core: RRC timing fix (licensed NR 4 ms, NR-U never faster), `core/` package (AMF/SMF/UPF), registration and PDU session procedures, RAN-side UPF gate, `--core-enabled` / `--nru-core-enabled` flags, attach-latency breakdown figure, whole-step regression
----> Step pre_17 — NR-U downlink packets now record their real receiver (and retries keep it), `--wifi-sta-uplink-enabled` flag, this readme / GETTING_STARTED refresh
----> Step 17 (17.A-17.H) — NR-U uplink inside the gNB's channel occupancy time (COT sharing, now the default): the gNB grants its UEs the uplink part of its COT, UEs send after a 25 us Type 2A check, RRC messages ride the same COT. Fixes the gNB/own-UE self-collision of the autonomous Cat-4 uplink (single cell: 0 -> 1.68 Mbps uplink). New flags `--nru-ul-access-mode` / `--nru-ul-cot-fraction`, an "NR-U Uplink" stdout block, and comparison figures (`python -m analysis.nru_ul_access_comparison`)
----> Step 19 (19.A-19.F) — 5G control plane, mobility and the unified run, all opt-in: random access (`--rach`); RRC Type 1 fallback, radio link failure + re-establishment (`--rlm`), RRC_INACTIVE (`--rrc-inactive`), reconfiguration (`--rrc-reconfig`); QoS flows / 5QI (`--qos-flows`); handover (`--handover`); Core failure modes (`--core-*`); Wi-Fi + NR-U + licensed NR in one run with one Core (`--nr-gnb-number`); NR-U as an LAA secondary cell (`--nru-scell`). Step pre_19.F: NR-U HARQ retransmissions no longer starve when several UEs share a COT
----> Step 18 (18.A-18.F) — 5G user plane, all opt-in: BLER error model (`--error-model bler`), per-UE byte buffers and traffic for licensed NR, NR-U COTs made of slots with transport blocks and several UEs per COT (`--nru-cot-model slots`, uplink on interlaces), HARQ with chase combining (`--harq`), PDCP + RLC UM/AM (`--rlc-mode`). Step pre_18.F: licensed NR uplink UEs of one cell on separate RBs no longer interfere with each other, and uplink results are now printed
----> Step pre_18 (A-E) — channel-model fixes found while validating Step 17: (A-B) SINR counts every transmission that overlapped the target at any point - Wi-Fi frames (one decode unit) at full power, NR-U/NR bursts weighted by the fraction covered - instead of only what was still on the air when the target ended (results used to depend on timing and processing order); (D) Wi-Fi DCF counts backoff on a shared 9 us slot grid with event-driven sensing and a fresh DIFS after every busy period; (E) NR-U LBT is 3GPP TS 37.213 Type 1 - a full 43 us defer period after every busy period. (C) Paper figures regenerated: the DTMC validation now matches the model within 0.8-2.7 points for Wi-Fi and 0.4-1.4 for NR-U
----> Step pre_20 (A-E) - LAA / NR-U fairness study with the 3GPP replacement test: fairness report and 802.11 preamble detection (`--fairness-report`, `--wifi-preamble-detect`), Wi-Fi A-MPDU (`--wifi-ampdu`), diagnosis sweeps, and four mitigations - TS 37.213 priority classes (`--nru-priority-class`), ED threshold (`--nru-ed-mode`, `--nru-ed-threshold-dbm`), preamble / CTS-to-self with a Wi-Fi NAV (`--nru-wifi-reservation`), reference-slot feedback (`--nru-ref-nack-threshold`, `--nru-adaptive-cot`). Report: `docs/laa_fairness_study.md`. Step pre_20.D.3a: Wi-Fi's SINR no longer counts one interferer's back-to-back frames twice
----> Step 20 (20.A-20.E) - full-stack Wi-Fi, all opt-in: 802.11 frame exchange on the air (`--wifi-mac-exchange`, `--wifi-rts-threshold`: ACK/Block Ack, NAV, RTS/CTS, EIFS - collision probability now matches Bianchi); STA uplink and EDCA with poisson/cbr queues, A-MPDU on every path (`--wifi-sta-traffic-model`); 802.11n/ac/ax PHY (`--wifi-phy`, `--wifi-channel-width`, `--wifi-gi`); management plane - beacons, association, roaming (`--wifi-management`); 802.11ax OFDMA downlink and trigger-based uplink (`--wifi-ofdma`, `--wifi-ul-ofdma`). Fix pre_20.C0: interference uses the transmitter's in-band power share (unequal bandwidths)

Full detail (design rationale, exact verified numbers, what was deliberately left out) for every sub-step above is in `Project details/Step N.txt`; `Project details/STATUS - resume context.txt` is the current single-file "start here" summary.

#### Citation


Please consider citing the following works if relevant to your research

- [1] Rahman, Md Rashedur, and Moinul Hossain. "Rancad: Random channel access deterrence attack against spectrum coexistence between nr-u and wi-fi on the 5ghz unlicensed band." ICC 2024-IEEE International Conference on Communications. IEEE, 2024.
- [2] Rahman, Md Rashedur, et al. "Channel Access Deterrence Attack: An Attack against Spectrum Coexistence between NR-U and Wi-Fi in the 5 GHz Band." Proceedings of IEEE INFOCOM 2025, IEEE, 2025.
- [3] J. Cichon. A Wi-Fi and NR-U Coexistence Channel Access Simulator based on the Python SimPy Library. [Online]. Available: https://github.com/CichonJakub/5G-Coexistence-SimPy.

#### License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
