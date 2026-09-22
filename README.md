> **⚠️ EDUCATIONAL USE ONLY — AUTHORIZED TESTING ONLY.**
> This project exists for education, research, and **defense of systems you own
> or hold explicit written authorization to assess**. Unauthorized use is
> prohibited and may be illegal. Read [ETHICS.md](ETHICS.md) and
> [SCOPE.md](SCOPE.md) before use. Use at your own risk; **AS IS**, no warranty.

# P5 — PHYTbed: Multi-Protocol Physical-Layer Testbed Orchestrator

Pure-Python orchestrator for a multi-protocol **physical-layer (PHY) security
testbed** — 802.11, ESP-NOW, 802.15.4/BLE, and sub-GHz radios — with a scenario
DSL, clock-alignment model, event logging, and interference-matrix automation
for **RF security** and **embedded-system** research.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Stars](https://img.shields.io/github/stars/5h4d0wn1k/p5-phytbed)](https://github.com/5h4d0wn1k/p5-phytbed)
[![Issues](https://img.shields.io/github/issues/5h4d0wn1k/p5-phytbed)](https://github.com/5h4d0wn1k/p5-phytbed/issues)
[![Last commit](https://img.shields.io/github/last-commit/5h4d0wn1k/p5-phytbed)](https://github.com/5h4d0wn1k/p5-phytbed)

## Why

Cross-protocol interference is a quiet but devastating attack class: a
sub-GHz jammer, an nRF24 burst, or a Wi-Fi flood can break Zigbee or BLE
services that *should* coexist. Studying it rigorously needs phase-aligned
radios, scripted multi-protocol scenarios, and synchronized logging — expensive
hardware that most labs cannot afford. PHYTbed attacks that problem from the
orchestrator side: before any radio is switched on, the scenario DSL, common
event timeline, clock-alignment model, and interference-matrix automation are
fully exercised offline on embedded sample data. When a hardware rig arrives,
the same scenario scripts and log formats are reused, so results produced here
stay drop-in compatible with real on-air runs — all within authorized,
regulatory-compliant PHY-layer security research.

## Features

- **Scenario DSL parser** — `t=<ms> <protocol> <op> [<n>% duty]` grammar with
  protocol aliases and per-event duty parsing
- **Clock-alignment model** — per-radio `local(t) = (1+drift)·t + offset`,
  least-squares calibration against a shared GPIO-pulse ground truth, sub-ms
  alignment targets
- **Event-log builder** — unified JSONL log (per-radio CSV frames +
  `labels.jsonl`)
- **Interference-matrix automation** — closed-form precision/recall/F1 from an
  embedded 24-trial labelled suppression table
- **Case-study runner** — 4 scripted cross-protocol scenarios: Wi-Fi vs Zigbee,
  ESP-NOW vs Wi-Fi, nRF24 vs BLE, sub-GHz jam
- **Deterministic offline demo** — stdlib-only, no hardware required

## Quickstart

No external dependencies — pure Python stdlib.

```bash
# Full offline demo (DSL + alignment + logs + interference + case studies)
python3 firmware/phytbed_orchestrator.py
```

Programmatic use:

```python
from firmware.phytbed_orchestrator import ScenarioDSL, ClockAlignment, InterferenceF1, run_case_study

events = ScenarioDSL().parse("t=0 zigbee net joins; t=30 nrf24 burst 90% duty")
align = ClockAlignment(["wifi", "zigbee", "nrf24"])
align.calibrate()
f1 = InterferenceF1()
print(f1.get("wifi", "zigbee"))   # precision / recall / F1
```

## Live lab plan

Phase table: Phase 0 offline orchestrator validation (DONE in this repo); Phase
1–3 rig bring-up, GPIO-pulse alignment, and on-air case studies (PENDING —
requires owned hardware, licensed ISM bands, and written scope).

## Project structure

- `firmware/phytbed_orchestrator.py` — DSL, alignment, event logs, interference F1, case studies
- `run_demo.py` — convenience runner
- `tests/` — verification suite

## Legal & authorized use

For **educational and authorized security research purposes only**. Only operate
radios you own or have written authorization to test, and stay within licensed
RF bands and local emission limits. Jamming or flooding any radio traffic you
are not authorized to affect is prohibited. See [ETHICS.md](ETHICS.md),
[SCOPE.md](SCOPE.md), and [SECURITY.md](SECURITY.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).