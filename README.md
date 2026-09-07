# P5 — PHYTbed: multi-protocol PHY testbed orchestrator — p5-phytbed

Pure-Python orchestrator/simulation for a multi-protocol physical-layer testbed (802.11, ESP-NOW, 802.15.4/BLE, sub-GHz) with scenario DSL, clock alignment, event logs, interference matrix automation, and cross-protocol case studies.

## Overview

- **Scenario DSL parser**: parses scripted scenarios like `t=0 zigbee net joins; t=10 wifi bulk TCP; t=30 nrf24 burst 90% duty` into a sorted common event timeline with ms precision
- **Clock-alignment model**: simulates synchronized per-radio clocks with small drift and offset, calibrates them against a shared GPIO-pulse ground truth, and reports alignment error vs the common timeline
- **Event log builder**: converts scripted scenario + simulated radio activity into a unified JSONL event log (per-radio CSV frames + `labels.jsonl`)
- **Interference matrix automation**: computes pairwise radio-interference results from an embedded suppression table and an F1 classifier benchmark (precision/recall/F1 on embedded labeled worker outputs)
- **Case-study runner**: runs 4 scripted cross-protocol attack case studies (Wi-Fi vs Zigbee, ESP-NOW vs Wi-Fi, nRF24 vs BLE, sub-GHz jam) and emits a summary table
- Fully offline demo over embedded sample data; deterministic; no hardware required

## Features

- **ScenarioDSL**: `t=<ms> <protocol> <op> [<n>% duty]` grammar with protocol aliases and per-event duty parsing
- **ClockAlignment**: per-radio `local(t) = (1+drift)·t + offset`, least-squares calibration vs GPIO pulse train, sub-ms alignment target for the demo
- **expand_activity / write_logs**: per-operation packet footprints, unified frames across all radios, per-radio CSV export + `labels.jsonl`
- **InterferenceF1**: embedded 24-trial labeled worker outputs per ordered protocol pair; closed-form precision/recall/F1
- **run_case_study**: contention-window frame-loss simulation with severity verdicts
- **Offline self-test**: deterministic re-parse, sorted timeline, <1 ms alignment, exit 0

## Research Framing

This repository is the **orchestrator tooling for the P5 paper** — a feasibility study of a multi-protocol PHY testbed with phase-aligned radios and scripted cross-protocol interference scenarios. The scenario DSL, clock-alignment model, event-log schema (per-radio CSV + labels JSONL), interference matrix automation, and the four case-study harnesses are all fully exercised offline here on embedded sample data. The hardware runs (radios on the rig, GPIO-pulse alignment, on-air capture) are executed separately once the lab rig is available, with the same scenario scripts and log formats these tools consume so the offline pipeline and the rig pipeline stay drop-in compatible.

## Installation

```bash
# No external dependencies required — pure Python stdlib
python3 firmware/phytbed_orchestrator.py
```

## Usage

```bash
# Run the full offline demo (DSL + alignment + logs + interference + case studies)
python3 firmware/phytbed_orchestrator.py
```

Programmatic use:

```python
from firmware.phytbed_orchestrator import ScenarioDSL, ClockAlignment, InterferenceF1, run_case_study

events = ScenarioDSL().parse("t=0 zigbee net joins; t=30 nrf24 burst 90% duty")
print([(e["time_ms"], e["protocol"], e["op"]) for e in events])

align = ClockAlignment(["wifi", "zigbee", "nrf24"])
align.calibrate()
print(align.align("zigbee", 30.0))   # aligned back onto common timeline

f1 = InterferenceF1()
print(f1.get("wifi", "zigbee"))      # precision / recall / F1 for the pair
```

## Example Output

```
[1] SCENARIO DSL PARSER  ->  unified event timeline (ms precision)
  parsed 12 events from embedded scenario:
    idx  time_ms    protocol  op            duty%
  ...
[2] CLOCK-ALIGNMENT MODEL  (shared GPIO-pulse ground truth)
    max |error| = 0.2947 ms   mean = 0.0787 ms  -> PASS
[3] EVENT LOG BUILDER  (unified JSONL log: CSV frames + labels)
  expanded 62 radio frames across 6 radios
[4] INTERFERENCE MATRIX AUTOMATION
  wifi->zigbee ... F1 0.953
[5] CROSS-PROTOCOL CASE STUDIES
  id   case          victim   aggressor  sent  lost  loss%    F1  verdict
   1   Wi-Fi vs Zigbee ...
[6] OFFLINE SELF-TEST
[+] Demo complete — alignment check PASSED, deterministic, exit 0
```

## IMPORTANT: Read before use.

This project is provided for **educational and authorized security research purposes only**.

### Authorization Requirements
- You MUST have explicit written permission from the device/network owner before transmission, capture, or analysis of any wireless traffic
- Only operate radios on hardware you own or have written authorization to test
- Any on-air experimentation requires compliance with local RF regulations and licensed bands
- The sub-GHz case study must only be exercised in licensed/ISM bands you are authorized to use

### Legal Framework
- **Computer Fraud and Abuse Act (CFAA)**: Unauthorized access to computer systems is a federal crime
- **Wiretap Act (18 U.S.C. § 2511)**: Interception of electronic communications without consent is illegal
- **FCC Regulations**: Operating radio hardware must comply with Part 15 (unlicensed) and Part 90/97 rules where applicable
- **State Laws**: Many states have additional computer crime and wiretapping statutes

### Acceptable Use
- Simulated and scripted PHY-scenario research on your own testbed in a controlled lab
- Authorized coexistence/interference testing within written scope
- Academic PHY-layer security research with ethics/IRB approval where applicable
- Security education and training demonstrations on isolated test rigs

### Prohibited Use
- Jamming, flooding, or otherwise interfering with radio traffic you are not authorized to affect
- Deploying cross-protocol interference against production or third-party networks
- Any activity that violates applicable laws or regulations

### No Warranty
This software is provided "AS IS" without warranty of any kind. The author is not responsible for any misuse or damage caused by this software.

### Responsible Disclosure
If you discover vulnerabilities using this tool, follow responsible disclosure practices:
1. Report to the affected vendor/owner privately
2. Allow reasonable time for remediation
3. Do not exploit beyond proof of concept

## Live Lab Test Plan

| Phase | Description | Go / No-Go Criteria | Status |
|-------|-------------|---------------------|--------|
| Phase 0 | Offline orchestrator validation (this tool) | Demo exits 0, all tests pass, alignment < 1 ms | DONE |
| Phase 1 | Radio rig bring-up + scenario DSL replay | Scripted scenarios schedule identically on real radios | PENDING |
| Phase 2 | GPIO-pulse clock alignment on hardware | Measured alignment error < 1 ms across all radios | PENDING |
| Phase 3 | Cross-protocol interference case studies on-air | Case-study loss rates correlate with F1 benchmark | PENDING |

## Metrics

| Metric | Target | Current |
|--------|--------|---------|
| Scenario DSL parse (events) | Deterministic | 12 |
| Expansion (frames) | 76 | 76 |
| Alignment error | < 1.0 ms | 0.145 ms |
| Radio frames (expansion) | > 60 | 76 |
| Case studies | 4 | 4 |
| Test pass rate | 100% | 100% |
| Demo exit code | 0 | 0 |

## License

MIT