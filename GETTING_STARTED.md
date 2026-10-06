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

You should see `379 passed` (as of Step 17). If that's clean, you're ready to run simulations.

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

## Where to go next

- `readme.md` - full flag reference (grouped by feature area) for all four
  scenarios, plus the project's structure and citation info.
- `Project details/STATUS - resume context.txt` - a single-file summary of
  everything that's been built and why.
- `Project details/Step N.txt` - the full design/verification log for
  every step, one file per major step, each with exact numbers.
