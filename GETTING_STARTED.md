# Getting Started

A guided first run of this simulator: setup, then a short hands-on look at
each of the four scenarios it supports, and at the uplink / 5G control-plane
options. Each section is a real command you
can copy-paste, followed by a sentence on what it's showing you. For the
full flag reference and design/verification history, see `readme.md` and
`Project details/`.

## 1. Setup

```bash
# (optional) isolate dependencies in a virtual env
python3 -m venv env && source env/bin/activate

# install dependencies
pip install -r requirements.txt
```

Confirm everything's working by running the test suite:

```bash
pip install pytest
pytest test/
```

You should see `553 passed` (as of Step pre_20). If that's clean, you're ready to run simulations.

## 2. Scenario 1 - Wi-Fi + NR-U coexistence

This is the main scenario: Wi-Fi access points (CSMA/CA) and NR-U gNBs
(Cat-4 LBT) contending for the same 5 GHz unlicensed channel, with a real
physical layer (path loss, SINR-based success/failure) underneath.

```bash
python singleRun.py --ap-number 2 --gnb-number 2 -t 1 -r 1
```

This places 2 Wi-Fi APs (each with one associated STA) and 2 NR-U gNBs
(each with one associated UE) at random positions, runs 1 simulated second,
and prints: the topology (positions/distances), per-technology
success/failure counts, channel occupancy/efficiency/collision-probability
numbers, and (since Step 8/9) packet-level delivery/latency statistics
both aggregated and broken down per node. Try `--rogue True` to swap the
first AP for a CAD-attack rogue AP instead of a benign one, or
`--shadowing-sigma-db 4 --ap-mobility-speed-mps 1.4` to add realistic
shadow fading and node movement. Run `python singleRun.py --help` for
every available flag (grouped and explained in `readme.md`).

## 3. Scenario 2 - Licensed 5G NR (standalone)

A separate, standalone scenario: a full-scheduler licensed-spectrum NR
gNB/UE model (round-robin or proportional-fair resource-block scheduling,
no LBT/contention - licensed spectrum doesn't need it). Not integrated
with the Wi-Fi/NR-U coexistence scenario above; it's its own thing.

```bash
python singleRunNR.py --gnb-number 1 --ues-per-gnb 4 -t 1 --scheduler proportional_fair
```

Prints the topology and, per gNB, the fraction of scheduled slots that
succeeded and the resulting throughput in Mbps.

## 4. Scenario 3 - Spectrum analyzer

Drops passive sniffer nodes into a real Wi-Fi + NR-U topology and has them
periodically sample the channel - the same way a real spectrum analyzer
would (point-in-time energy readings, no privileged access to what's
"really" happening in the simulation).

```bash
python singleRunSpectrum.py --ap-number 2 --gnb-number 1 --sniffer-number 2 -t 1
```

Prints, per sniffer: how often it read the channel as busy (wideband and
in-band), the mean/min/max energy it measured, and a per-technology duty
cycle breakdown (what fraction of samples saw at least one Wi-Fi
transmission visible, versus NR-U).

## 5. Scenario 4 - Packet-level attacker

Drops an attacker node into a real Wi-Fi + NR-U topology and runs it
through three phases: passively capture real packets off the channel,
transmit forged-source ("spoofed") packets claiming to be a real AP, and
re-transmit ("replay") exact copies of packets it captured earlier - all
from its own real physical position and transmit power.

```bash
python singleRunAttacker.py --ap-number 2 --gnb-number 1 -t 0.1 --spoof-target "AP 1" --spoof-count 5 --replay-max 3
```

Prints the topology, then per attacker: how many packets it captured,
how many it spoofed (with the forged source name), how many it replayed,
and its own channel occupancy - followed by the real Wi-Fi/NR-U
success/failure counts, so you can see the attack ran alongside normal
traffic rather than instead of it.

## 6. Uplink and the 5G control plane

By default every scenario above is downlink only, and UEs can send data
from the first instant. These opt-in flags (Steps 15-16) add uplink, RRC
connection setup, and a minimal 5G Core.

Wi-Fi uplink - the STA contends for the channel just like its AP:

```bash
python singleRun.py --ap-number 1 --gnb-number 1 -t 0.5 -r 1 --wifi-sta-uplink-enabled
```

Adds a "Wi-Fi Uplink" block. With one AP and one STA you'll see the
AP's downlink and the STA's uplink split the Wi-Fi airtime roughly
evenly (about 4.5 vs 4.1 Mbps here).

Licensed NR with the full attach chain - RRC setup, then registration
with the AMF, then a PDU session; the gNB sends a UE nothing until its
session is active:

```bash
python singleRunNR.py --gnb-number 1 --ues-per-gnb 2 -t 0.5 --tdd-enabled --ue-uplink-enabled --rrc-enabled --core-enabled
```

Look for the "RRC Connection Setup" block (4 ms) and the "5G Core" block:
registration 90 ms, PDU session 125 ms, full attach 219 ms, first data
packet 219.5 ms. The same chain for NR-U, sharing the channel with Wi-Fi:

```bash
python singleRun.py --ap-number 1 --gnb-number 1 -t 0.5 -r 1 --nru-ue-uplink-enabled --nru-rrc-enabled --nru-core-enabled
```

Here RRC setup takes about 20 ms instead of 4 ms: each NR-U RRC
message waits for its gNB's next channel occupancy time, which the gNB
has to win against the Wi-Fi AP first. Add
`--nru-ul-access-mode autonomous` to compare with the older uplink,
where every UE runs its own Cat-4 LBT (about 41 ms here, and it
collides with its own gNB).
Keep `-t` above about 0.25 s with the Core on; the attach alone takes
over 0.2 s, so a shorter run carries no data. The readme's "5G control
plane" section lists where each default delay comes from.

## 7. The 5G user plane (Step 18)

All off by default. Licensed NR with real traffic instead of a full
buffer, a block-error-rate error model, HARQ and RLC AM:

```bash
python singleRunNR.py --gnb-number 2 --ues-per-gnb 4 --seed 2 -t 1 --error-model bler --dl-traffic poisson --dl-arrival-rate-pps 3000 --harq --rlc-mode am
```

Look for the "DL Traffic", "DL HARQ" and "DL PDCP/RLC" blocks: drop
`--harq --rlc-mode am` and about 6000 packets are lost to block errors;
with them, none. NR-U with its COTs made of NR slots (several UEs per
COT, uplink on interlaces):

```bash
python singleRun.py --ap-number 1 --gnb-number 1 -t 1 -r 1 --nru-cot-model slots --nru-ue-uplink-enabled --nru-traffic-model poisson --nru-arrival-rate-pps 1500
```

The "NR-U Slots" block shows downlink and uplink transport blocks,
their error rate (Wi-Fi frames hitting single slots) and the MCS used.

## 8. Mobility, the control plane and everything in one run (Step 19)

UEs moving between two licensed cells, with random access, radio link
monitoring and handover:

```bash
python singleRunNR.py --gnb-number 2 --ues-per-gnb 4 --gnb-pos 300,500 --gnb-pos 900,500 --area-w 1200 --area-h 1000 --ue-radius 150 --ue-mobility-speed-mps 20 --seed 3 -t 30 --tdd-enabled --ue-uplink-enabled --rrc-enabled --dl-traffic poisson --dl-arrival-rate-pps 200 --rach --rlm --handover
```

The "Handover" block shows 3 handovers with about 26 ms of interruption
each, and no radio link failures; drop `--handover` and the UEs fail
and re-establish instead. Wi-Fi, NR-U and a licensed cell in one run,
with NR-U as the licensed cell's secondary carrier (LAA):

```bash
python singleRun.py --ap-number 1 --gnb-number 1 --seed 1 -t 1 -r 1 --nru-cot-model slots --nru-traffic-model poisson --nru-arrival-rate-pps 20 --nr-gnb-number 1 --nr-colocated --nr-bandwidth-mhz 20 --nr-dl-traffic poisson --nr-dl-arrival-rate-pps 4000 --nru-scell --harq
```

The "NR-U SCell (LAA)" block splits the licensed UEs' downlink between
the licensed PCell and the NR-U SCell - and the Wi-Fi line shows what
that extra unlicensed traffic costs the neighbor.

## 9. Is NR-U fair to Wi-Fi? (Step pre_20)

The same coexistence run with the fairness report and 802.11 preamble
detection on:

```bash
python singleRun.py --ap-number 1 --gnb-number 1 --seed 1 -t 1 -r 1 --nru-cot-model slots --wifi-preamble-detect --fairness-report
```

The "Coexistence Fairness" block shows each technology's airtime share,
how much of it succeeded, its failure ratio, throughput and latency. Add
the two mitigations that work together - a lower NR-U energy-detection
threshold and a CTS-to-self before every COT - and compare:

```bash
python singleRun.py --ap-number 1 --gnb-number 1 --seed 1 -t 1 -r 1 --nru-cot-model slots --wifi-preamble-detect --fairness-report --nru-ed-threshold-dbm -82 --nru-wifi-reservation cts_to_self
```

Wi-Fi goes from about 2.8 to 6.5 Mbps (no more frames lost to COTs it
couldn't hear) while NR-U keeps about 84 Mbps; what is left is airtime
per channel access - one short Wi-Fi frame against a 6 ms COT.

The full study (the 3GPP replacement test over distance and load, and
four mitigations) is in `docs/laa_fairness_study.md`; its figures come
from `python -m analysis.laa_fairness_sweeps`,
`python -m analysis.laa_fairness_mitigations` and
`python -m analysis.laa_scell_mitigations`.

## Where to go next

- `readme.md` - full flag reference (grouped by feature area) for all four
  scenarios, plus the project's structure and citation info.
- `Project details/STATUS - resume context.txt` - a single-file summary of
  everything that's been built and why.
- `Project details/Step N.txt` - the full design/verification log for
  every step, one file per major step, each with exact numbers.
