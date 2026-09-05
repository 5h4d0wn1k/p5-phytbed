#!/usr/bin/env python3
"""P5 — PHYTbed: multi-protocol PHY testbed orchestrator.

Scenario DSL parser, clock-alignment model (shared GPIO-pulse ground truth),
unified JSONL event-log builder (per-radio CSV frames + labels.jsonl), pairwise
interference-matrix automation with an F1 classifier benchmark, and four
scripted cross-protocol case studies.

Educational / authorized security-research only. Pure Python stdlib.
The offline demo runs entirely on embedded sample data; the hardware rig is
exercised later as part of the P5 research-portfolio paper.
"""

import csv
import io
import json
import os
import random
import re
import sys
import tempfile

# ---------------------------------------------------------------------------
# Protocol catalogue (radio families on the PHY testbed)
# ---------------------------------------------------------------------------
PROTOCOLS = ["wifi", "espnow", "zigbee", "ble", "nrf24", "subghz"]

PROTOCOL_ALIASES = {
    "wifi": "wifi",
    "wi-fi": "wifi",
    "802.11": "wifi",
    "wlan": "wifi",
    "espnow": "espnow",
    "esp-now": "espnow",
    "espnow": "espnow",
    "zigbee": "zigbee",
    "zig": "zigbee",
    "802.15.4": "zigbee",
    "zb": "zigbee",
    "ble": "ble",
    "bluetooth": "ble",
    "nrf24": "nrf24",
    "nrf": "nrf24",
    "nordic": "nrf24",
    "subghz": "subghz",
    "sub-ghz": "subghz",
    "lora": "subghz",
    "cc1101": "subghz",
}


def _clip(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


# ---------------------------------------------------------------------------
# 1. Scenario DSL parser
# ---------------------------------------------------------------------------
class ScenarioDSL:
    """Parse scripted scenarios into a sorted common event timeline (ms).

    Grammar (clauses separated by ';'):

        t=<ms> <protocol> <operation> [<n>% duty] [n=<count>]

    Example:
        t=0 zigbee net joins; t=10 wifi bulk TCP; t=30 nrf24 burst 90% duty
    """

    TIME_RE = re.compile(r"t\s*=\s*(\d+(?:\.\d+)?)")
    DUTY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
    COUNT_RE = re.compile(r"n\s*=\s*(\d+)")

    # (matched keyword, canonical operation) — first match wins
    OPS = [
        ("net join", "join"),
        ("bulk", "bulk"),
        ("burst", "burst"),
        ("jam", "jam"),
        ("advertise", "advertise"),
        ("beacon", "beacon"),
        ("connect", "connect"),
        ("command", "command"),
        ("ack", "ack"),
        ("scan", "scan"),
        ("send", "send"),
    ]

    def _protocol(self, rest):
        words = re.findall(r"[A-Za-z0-9.]+", rest.lower())
        for w in words:
            if w in PROTOCOL_ALIASES:
                return PROTOCOL_ALIASES[w]
            if w in PROTOCOLS:
                return w
        raise ValueError(f"unknown protocol in clause: {rest!r}")

    def _operation(self, rest):
        low = rest.lower()
        for keyword, op in self.OPS:
            if keyword in low:
                return op
        return "send"

    def _duty(self, rest):
        m = self.DUTY_RE.search(rest)
        return _clip(int(float(m.group(1))), 0, 100) if m else None

    def _count(self, rest):
        m = self.COUNT_RE.search(rest)
        return int(m.group(1)) if m else None

    def parse(self, script):
        """Parse a scenario script -> sorted list of event dicts."""
        events = []
        for clause in script.split(";"):
            clause = clause.strip()
            if not clause:
                continue
            m = self.TIME_RE.search(clause)
            if not m:
                raise ValueError(f"scenario clause missing t=<ms>: {clause!r}")
            t_ms = round(float(m.group(1)), 3)  # ms precision
            rest = clause[m.end():].strip()
            events.append(
                {
                    "time_ms": t_ms,
                    "protocol": self._protocol(rest),
                    "op": self._operation(rest),
                    "duty_pct": self._duty(rest),
                    "count": self._count(rest),
                }
            )
        events.sort(key=lambda e: (e["time_ms"], PROTOCOLS.index(e["protocol"])))
        return events


# ---------------------------------------------------------------------------
# 2. Clock-alignment model
# ---------------------------------------------------------------------------
# Shared GPIO pulse ground truth (embedded sample values): the common timeline
# reference every radio aligns against before events are merged.
GPIO_PULSE_GROUND_TRUTH_MS = [0.0, 100.0, 200.0, 300.0, 400.0, 500.0]


def _least_squares(xs, ys):
    """Fit ys = slope * xs + intercept; returns (slope, intercept)."""
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0.0:
        return (1.0, 0.0)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
    return (slope, my - slope * mx)


class ClockAlignment:
    """Simulate per-radio local clocks with drift and align to the common clock.

    Each radio owns a local clock  local(t) = (1 + drift) * t + offset.
    Calibration observes the shared GPIO pulse train from each local clock and
    least-squares-fits (slope, intercept); alignment then maps a radio-local
    observation back onto the common ms timeline.
    """

    def __init__(self, radios, ppm=40.0, offset_max_ms=2.0, jitter_ms=0.06, seed=0x5EED):
        self.radios = list(radios)
        self.jitter_ms = jitter_ms
        rng = random.Random(seed)
        self.clocks = {}
        self.fits = {}
        for r in self.radios:
            drift = rng.uniform(-ppm, ppm) * 1e-6
            offset = rng.uniform(-offset_max_ms, offset_max_ms)
            self.clocks[r] = (1.0 + drift, offset)

    def _jitter(self, radio, t):
        # deterministic per-(radio, time) jitter: pure function of inputs
        return random.Random(f"{radio}|{t:.6f}|phytbed").gauss(0.0, self.jitter_ms)

    def observed(self, radio, t):
        """Radio-local observation of common-clock time t (with jitter)."""
        a, b = self.clocks[radio]
        return a * t + b + self._jitter(radio, t)

    def calibrate(self, pulses=None):
        """Fit each radio clock against the shared GPIO ground truth."""
        pulses = pulses if pulses is not None else GPIO_PULSE_GROUND_TRUTH_MS
        for r in self.radios:
            xs = pulses
            ys = [self.observed(r, t) for t in pulses]
            self.fits[r] = _least_squares(xs, ys)
        return self.fits

    def align(self, radio, t):
        """Map a radio-local observation back to the common timeline (ms)."""
        a, b = self.fits[radio]
        return (self.observed(radio, t) - b) / a


# ---------------------------------------------------------------------------
# 3. Event log builder
# ---------------------------------------------------------------------------
# Per-operation packet structure used when expanding events into frame-level
# radio activity (delta offsets in ms from the event timestamp).
OP_PACKET_DELTAS_MS = {
    "join": [0, 15, 30, 45],
    "bulk": [0, 4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44],
    "burst": [0, 5, 10, 15, 20, 25, 30, 35],
    "advertise": [0, 10, 20, 30, 40],
    "beacon": [0, 20, 40, 60, 80],
    "send": [0, 8, 16],
    "command": [0, 20],
    "ack": [0],
    "connect": [0, 12, 24],
    "scan": [0, 7, 14, 21, 28, 35],
    "jam": [0, 5, 10, 15, 20, 25, 30, 35, 40, 45],
}

OP_PAYLOAD_LEN = {
    "join": 22, "bulk": 1400, "burst": 32, "advertise": 37,
    "beacon": 31, "send": 16, "command": 8, "ack": 4,
    "connect": 11, "scan": 25, "jam": 64,
}


def expand_activity(events):
    """Expand scripted events into frame-level radio activity (sorted)."""
    frames = []
    for e in events:
        radio = e["protocol"]
        for i, dt in enumerate(OP_PACKET_DELTAS_MS[e["op"]]):
            frames.append(
                {
                    "radio": radio,
                    "op": e["op"],
                    "event_time_ms": e["time_ms"],
                    "true_ms": round(e["time_ms"] + dt, 3),
                    "packet_seq": i + 1,
                    "payload_len": OP_PAYLOAD_LEN[e["op"]],
                }
            )
    frames.sort(key=lambda f: (f["true_ms"], PROTOCOLS.index(f["radio"]),
                               f["packet_seq"]))
    return frames


def write_logs(frames, align, out_dir):
    """Write a unified JSONL event log: per-radio CSV frames + labels.jsonl."""
    radio_rows = {r: [] for r in PROTOCOLS}
    radio_counters = {r: 0 for r in PROTOCOLS}
    labels = []
    for idx, f in enumerate(frames, 1):
        aligned = align.align(f["radio"], f["true_ms"])
        radio_counters[f["radio"]] += 1
        radio_rows[f["radio"]].append(
            [idx, f["radio"], f"{f['true_ms']:.3f}", f"{aligned:.3f}",
             radio_counters[f["radio"]], f["payload_len"], f["op"]]
        )
        labels.append(
            {
                "id": idx,
                "time_ms": round(aligned, 3),
                "radio": f["radio"],
                "label": f["op"],
                "seq": radio_counters[f["radio"]],
                "payload_len": f["payload_len"],
            }
        )

    manifest = []
    for radio in PROTOCOLS:
        path = os.path.join(out_dir, f"frames_{radio}.csv")
        with open(path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["seq", "radio", "true_ms", "aligned_ms",
                        "counter", "payload_len", "op"])
            w.writerows(radio_rows[radio])
        manifest.append(path)

    labels_path = os.path.join(out_dir, "labels.jsonl")
    with open(labels_path, "w") as fh:
        for line in labels:
            fh.write(json.dumps(line) + "\n")
    manifest.append(labels_path)
    return manifest


# ---------------------------------------------------------------------------
# 4. Interference matrix automation
# ---------------------------------------------------------------------------
# Embedded pairwise suppression table (aggressor -> victim) in dB. Cross-band
# combos involving sub-GHz are ~0.2 dB (bands do not overlap with 2.4 GHz).
SUPPRESSION_DB = {
    ("wifi", "zigbee"): 8.5, ("zigbee", "wifi"): 3.0,
    ("wifi", "espnow"): 7.0, ("espnow", "wifi"): 5.0,
    ("wifi", "ble"): 6.0, ("ble", "wifi"): 4.5,
    ("wifi", "nrf24"): 6.0, ("nrf24", "wifi"): 4.5,
    ("wifi", "subghz"): 0.2, ("subghz", "wifi"): 0.2,
    ("espnow", "zigbee"): 3.5, ("zigbee", "espnow"): 3.5,
    ("espnow", "ble"): 4.0, ("ble", "espnow"): 4.0,
    ("espnow", "nrf24"): 5.0, ("nrf24", "espnow"): 5.0,
    ("espnow", "subghz"): 0.2, ("subghz", "espnow"): 0.2,
    ("zigbee", "ble"): 3.5, ("ble", "zigbee"): 2.5,
    ("zigbee", "nrf24"): 3.5, ("nrf24", "zigbee"): 4.0,
    ("zigbee", "subghz"): 0.2, ("subghz", "zigbee"): 0.2,
    ("ble", "nrf24"): 4.0, ("nrf24", "ble"): 9.0,
    ("ble", "subghz"): 0.2, ("subghz", "ble"): 0.2,
    ("nrf24", "subghz"): 0.2, ("subghz", "nrf24"): 0.2,
    ("subghz", "subghz"): 12.0,  # same sub-GHz band (jam case study)
    ("wifi", "wifi"): 3.0, ("espnow", "espnow"): 3.0,
    ("zigbee", "zigbee"): 3.0, ("ble", "ble"): 3.0,
    ("nrf24", "nrf24"): 3.0,
}


class InterferenceF1:
    """Pairwise interference benchmark: weak detector worker vs labeled truth.

    Embedded trial data (24 labeled trials per ordered pair) is regenerated
    deterministically at import time from the suppression table: interference
    present with probability proportional to suppression, detected by a worker
    with fixed skill and false-alarm rate. Precision / recall / F1 are then
    closed-form on the labeled worker outputs.
    """

    def __init__(self, n_trials=24, skill=0.90, false_alarm=0.12, seed=0xF1):
        self.n_trials = n_trials
        self.skill = skill
        self.false_alarm = false_alarm
        rng = random.Random(seed)
        self.trials = {}  # (aggressor, victim) -> {truth, pred}
        self.metrics = {}
        for a in PROTOCOLS:
            for b in PROTOCOLS:
                p_true = _clip(0.15 + SUPPRESSION_DB.get((a, b), 0.4) / 45.0,
                               0.15, 0.95)
                truth, pred = [], []
                for _ in range(n_trials):
                    t = rng.random() < p_true
                    truth.append(t)
                    pred.append((rng.random() < skill) if t
                                else (rng.random() < false_alarm))
                self.trials[(a, b)] = {"truth": truth, "pred": pred}
                self.metrics[(a, b)] = self._scores(truth, pred)

    def _scores(self, pred, truth):
        tp = fp = fn = 0
        for p, t in zip(pred, truth):
            if p and t:
                tp += 1
            elif p and not t:
                fp += 1
            elif not p and t:
                fn += 1
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        return {
            "collided": tp + fn,
            "precision": round(prec, 3),
            "recall": round(rec, 3),
            "f1": round(f1, 3),
        }

    def get(self, a, b):
        return self.metrics[(a, b)]


# ---------------------------------------------------------------------------
# 5. Case-study runner
# ---------------------------------------------------------------------------
CASE_WINDOW_MS = 3.0  # frames within this true-time window contend

CASE_STUDIES = [
    {
        "id": 1,
        "name": "Wi-Fi vs Zigbee",
        "victim": "zigbee",
        "aggressor": "wifi",
        "scenario": ("t=0 zigbee net joins; t=10 wifi bulk TCP; "
                     "t=12 zigbee net joins; t=30 wifi bulk TCP; "
                     "t=35 zigbee net joins"),
    },
    {
        "id": 2,
        "name": "ESP-NOW vs Wi-Fi",
        "victim": "espnow",
        "aggressor": "wifi",
        "scenario": ("t=0 espnow beacon broadcast; t=5 wifi bulk TCP; "
                     "t=20 espnow command ack; t=30 wifi burst 60% duty; "
                     "t=40 espnow scan"),
    },
    {
        "id": 3,
        "name": "nRF24 vs BLE",
        "victim": "ble",
        "aggressor": "nrf24",
        "scenario": ("t=0 ble advertise; t=8 nrf24 burst 90% duty; "
                     "t=20 nrf24 burst 80% duty; t=40 ble connect"),
    },
    {
        "id": 4,
        "name": "sub-GHz jam",
        "victim": "subghz",
        "aggressor": "subghz",
        "scenario": ("t=0 subghz link send; t=5 subghz jam 100% duty; "
                     "t=25 subghz link send; t=45 subghz jam 60% duty; "
                     "t=60 subghz link send"),
    },
]


def run_case_study(cs, rng, interference):
    """Simulate frames lost by the victim in cross-protocol contention."""
    events = ScenarioDSL().parse(cs["scenario"])
    frames = expand_activity(events)
    vframes = [f for f in frames if f["radio"] == cs["victim"]]
    aframes = [f for f in frames if f["radio"] == cs["aggressor"]]

    supp = SUPPRESSION_DB.get((cs["aggressor"], cs["victim"]), 0.3)
    p_loss = _clip(0.15 + supp / 50.0, 0.15, 0.95)

    lost = 0
    for vf in vframes:
        contended = any(abs(af["true_ms"] - vf["true_ms"]) <= CASE_WINDOW_MS
                        for af in aframes)
        if contended and rng.random() < p_loss:
            lost += 1

    n = len(vframes)
    loss_pct = 100.0 * lost / n if n else 0.0
    f1 = interference.get(cs["aggressor"], cs["victim"])["f1"]

    if loss_pct >= 40.0:
        verdict = "SEVERE"
    elif loss_pct >= 15.0:
        verdict = "DEGRADED"
    elif loss_pct >= 5.0:
        verdict = "PARTIAL"
    else:
        verdict = "MARGINAL"

    return {
        "id": cs["id"],
        "name": cs["name"],
        "victim": cs["victim"],
        "aggressor": cs["aggressor"],
        "events": len(events),
        "victim_frames": n,
        "lost_frames": lost,
        "loss_pct": round(loss_pct, 1),
        "f1": f1,
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# Demo / offline self-test
# ---------------------------------------------------------------------------
MAIN_SCENARIO = (
    "t=0 zigbee net joins; t=5 espnow beacon broadcast; "
    "t=10 wifi bulk TCP; t=20 ble advertise; "
    "t=25 nrf24 burst 40% duty; t=30 nrf24 burst 90% duty; "
    "t=40 wifi bulk TCP; t=50 subghz link send; "
    "t=60 espnow command ack; t=70 ble connect; "
    "t=80 zigbee net joins; t=90 subghz jam 30% duty"
)


def demo(argv=None):
    print("=" * 78)
    print("  P5 — PHYTbed: multi-protocol PHY testbed orchestrator")
    print("=" * 78)

    # --- [1] Scenario DSL -> unified event timeline -------------------------
    print("\n[1] SCENARIO DSL PARSER  ->  unified event timeline (ms precision)")
    parser = ScenarioDSL()
    events = parser.parse(MAIN_SCENARIO)
    print(f"  parsed {len(events)} events from embedded scenario:")
    hdr = f"  {'idx':>3}  {'time_ms':>8}  {'protocol':<7}  {'op':<10} {'duty%':>5}"
    print(hdr)
    print("  " + "-" * (len(hdr) - 1))
    for i, e in enumerate(events, 1):
        duty = e["duty_pct"] if e["duty_pct"] is not None else "-"
        print(f"  {i:>3}  {e['time_ms']:>8.3f}  {e['protocol']:<7}  "
              f"{e['op']:<10} {duty:>5}")

    # --- [2] Clock alignment ------------------------------------------------
    print("\n[2] CLOCK-ALIGNMENT MODEL  (shared GPIO-pulse ground truth)")
    align = ClockAlignment(PROTOCOLS)
    align.calibrate()
    print("  per-radio local clock model (drift ppm + offset, ..., "
          "calibration pulses=6):")
    for r in PROTOCOLS:
        a, b = align.clocks[r]
        print(f"    {r:<7} drift={((a - 1.0) * 1e6):+.1f} ppm  "
              f"offset={b:+.3f} ms")

    errs = []
    print(f"  alignment error vs GPIO ground truth (target < 1.0 ms):")
    largest = 0.0
    total = 0.0
    for e in events:
        aligned = align.align(e["protocol"], e["time_ms"])
        err = abs(aligned - e["time_ms"])
        errs.append(err)
        largest = max(largest, err)
        total += err
    mean_err = total / len(events) if events else 0.0
    ok_align = largest < 1.0
    print(f"    max |error| = {largest:.4f} ms   mean = {mean_err:.4f} ms  "
          f"-> {'PASS' if ok_align else 'FAIL'}")

    # --- [3] Event log builder ---------------------------------------------
    print("\n[3] EVENT LOG BUILDER  (unified JSONL log: CSV frames + labels)")
    frames = expand_activity(events)
    with tempfile.TemporaryDirectory(prefix="p5_phytbed_logs_") as td:
        manifest = write_logs(frames, align, td)
        print(f"  expanded {len(frames)} radio frames across {len(PROTOCOLS)} radios")
        for p in manifest:
            print(f"    wrote {p}")
        with open(manifest[-1]) as fh:
            sample = [fh.readline(), fh.readline()]

    print("  sample labels.jsonl:")
    for line in sample:
        print(f"    {line.rstrip()}")

    # --- [4] Interference matrix automation --------------------------------
    print("\n[4] INTERFERENCE MATRIX AUTOMATION  (suppression + F1 benchmark)")
    print("  embedded classified worker outputs: trials=24, skill=0.90, "
          "false_alarm=0.12")
    interfer = InterferenceF1()
    hdr = f"  {'aggressor->victim':<20} {'supp(dB)':>9} {'collided':>9} " \
          f"{'precision':>10} {'recall':>7} {'F1':>6}"
    print(hdr)
    print("  " + "-" * (len(hdr) - 1))
    for a in PROTOCOLS:
        for b in PROTOCOLS:
            m = interfer.get(a, b)
            supp = SUPPRESSION_DB.get((a, b), 0.2)
            print(f"  {f'{a}->{b}':<20} {supp:>9.1f} {m['collided']:>9d} "
                  f"{m['precision']:>10.3f} {m['recall']:>7.3f} {m['f1']:>6.3f}")

    # --- [5] Case-study runner ---------------------------------------------
    print("\n[5] CROSS-PROTOCOL CASE STUDIES")
    rng = random.Random(0xC0DE)
    cases = [run_case_study(cs, rng, interfer) for cs in CASE_STUDIES]
    hdr = f"  {'id':>2}  {'case':<20} {'victim':<8} {'aggressor':<9} " \
          f"{'sent':>5} {'lost':>4} {'loss%':>6} {'F1':>6}  verdict"
    print(hdr)
    print("  " + "-" * (len(hdr) - 1))
    for c in cases:
        print(f"  {c['id']:>2}  {c['name']:<20} {c['victim']:<8} "
              f"{c['aggressor']:<9} {c['victim_frames']:>5} {c['lost_frames']:>4} "
              f"{c['loss_pct']:>6.1f} {c['f1']:>6.3f}  {c['verdict']}")

    # --- [6] Self-test -------------------------------------------------------
    print("\n[6] OFFLINE SELF-TEST")
    checks = []
    checks.append(("scenario re-parse deterministic",
                   json.dumps(parser.parse(MAIN_SCENARIO)) ==
                   json.dumps(parser.parse(MAIN_SCENARIO))))
    checks.append(("timeline sorted by time_ms",
                   all(events[i]["time_ms"] <= events[i + 1]["time_ms"]
                       for i in range(len(events) - 1))))
    checks.append(("all aligned errors < 1.0 ms",
                   all(e < 1.0 for e in errs)))
    checks.append(("expanded frames sorted & non-empty",
                   len(frames) > 0 and all(
                       frames[i]["true_ms"] <= frames[i + 1]["true_ms"]
                       for i in range(len(frames) - 1))))
    checks.append(("case-study runner emitted 4 summaries", len(cases) == 4))
    ok_all = True
    for name, result in checks:
        ok_all = ok_all and result
        print(f"    [{'PASS' if result else 'FAIL'}] {name}")

    if not ok_all:
        print("[!] Self-test FAILED")
        return 1

    print("\n[+] Demo complete — alignment check PASSED, deterministic, exit 0")
    return 0


def main(argv=None):
    return demo(argv)


if __name__ == "__main__":
    sys.exit(main())