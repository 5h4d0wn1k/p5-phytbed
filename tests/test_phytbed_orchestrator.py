#!/usr/bin/env python3
"""P5 — PHYTbed orchestrator: unit tests."""
import json
import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "firmware"))

from phytbed_orchestrator import (
    CASE_STUDIES,
    CASE_WINDOW_MS,
    PROTOCOLS,
    SUPPRESSION_DB,
    ClockAlignment,
    InterferenceF1,
    ScenarioDSL,
    _least_squares,
    expand_activity,
    run_case_study,
    write_logs,
)


class TestScenarioDSL(unittest.TestCase):
    def setUp(self):
        self.parser = ScenarioDSL()

    def test_parse_simple(self):
        events = self.parser.parse("t=0 zigbee net joins; t=10 wifi bulk TCP")
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["protocol"], "zigbee")
        self.assertEqual(events[1]["protocol"], "wifi")
        self.assertEqual(events[0]["op"], "join")
        self.assertEqual(events[1]["op"], "bulk")

    def test_sorted_by_time(self):
        events = self.parser.parse("t=30 nrf24 burst; t=0 zigbee join; t=10 wifi bulk")
        times = [e["time_ms"] for e in events]
        self.assertEqual(times, sorted(times))
        self.assertEqual(events[0]["time_ms"], 0.0)
        self.assertEqual(events[-1]["time_ms"], 30.0)

    def test_duty_parsing(self):
        events = self.parser.parse("t=0 nrf24 burst 90% duty")
        self.assertEqual(events[0]["duty_pct"], 90)

    def test_duty_clipped_to_100(self):
        events = self.parser.parse("t=0 nrf24 burst 150% duty")
        self.assertEqual(events[0]["duty_pct"], 100)

    def test_duty_default_none(self):
        events = self.parser.parse("t=0 zigbee net joins")
        self.assertIsNone(events[0]["duty_pct"])

    def test_protocol_alias(self):
        events = self.parser.parse("t=0 802.15.4 net joins")
        self.assertEqual(events[0]["protocol"], "zigbee")

    def test_missing_time_raises(self):
        with self.assertRaises(ValueError):
            self.parser.parse("zigbee join")

    def test_unknown_protocol_raises(self):
        with self.assertRaises(ValueError):
            self.parser.parse("t=0 unicorn burst")

    def test_empty_script(self):
        self.assertEqual(self.parser.parse(""), [])

    def test_deterministic(self):
        s = "t=0 zigbee join; t=5 espnow beacon; t=10 wifi bulk"
        self.assertEqual(
            json.dumps(self.parser.parse(s)),
            json.dumps(self.parser.parse(s)),
        )


class TestLeastSquares(unittest.TestCase):
    def test_perfect_line(self):
        xs = [0, 1, 2, 3]
        ys = [2, 4, 6, 8]
        slope, intercept = _least_squares(xs, ys)
        self.assertAlmostEqual(slope, 2.0, places=6)
        self.assertAlmostEqual(intercept, 2.0, places=6)

    def test_constant_x_returns_identity(self):
        slope, intercept = _least_squares([5, 5, 5], [1, 2, 3])
        self.assertEqual((slope, intercept), (1.0, 0.0))


class TestClockAlignment(unittest.TestCase):
    def test_aligns_radios(self):
        align = ClockAlignment(PROTOCOLS)
        align.calibrate()
        for r in PROTOCOLS:
            self.assertIn(r, align.fits)

    def test_alignment_error_small(self):
        align = ClockAlignment(PROTOCOLS)
        align.calibrate()
        for r in PROTOCOLS:
            err = abs(align.align(r, 30.0) - 30.0)
            self.assertLess(err, 1.0)

    def test_deterministic(self):
        a = ClockAlignment(PROTOCOLS, seed=0x5EED)
        b = ClockAlignment(PROTOCOLS, seed=0x5EED)
        a.calibrate()
        b.calibrate()
        for r in PROTOCOLS:
            self.assertAlmostEqual(a.align(r, 50.0), b.align(r, 50.0), places=6)

    def test_align_is_idempotent_approx(self):
        align = ClockAlignment(PROTOCOLS)
        align.calibrate()
        t = align.align("wifi", 40.0)
        self.assertLess(abs(t - 40.0), 0.5)


class TestExpandActivity(unittest.TestCase):
    def test_expands_frames(self):
        events = ScenarioDSL().parse("t=0 zigbee net joins; t=10 wifi bulk TCP")
        frames = expand_activity(events)
        # join has 4 packets, bulk has 12
        self.assertEqual(len(frames), 16)
        self.assertEqual(sum(1 for f in frames if f["radio"] == "zigbee"), 4)
        self.assertEqual(sum(1 for f in frames if f["radio"] == "wifi"), 12)

    def test_frames_sorted(self):
        events = ScenarioDSL().parse("t=20 ble advertise; t=0 espnow beacon; t=10 subghz jam")
        frames = expand_activity(events)
        for i in range(len(frames) - 1):
            self.assertLessEqual(frames[i]["true_ms"], frames[i + 1]["true_ms"])

    def test_payload_len_set(self):
        events = ScenarioDSL().parse("t=0 zigbee net joins")
        frames = expand_activity(events)
        self.assertEqual(frames[0]["payload_len"], 22)


class TestWriteLogs(unittest.TestCase):
    def test_writes_files(self):
        align = ClockAlignment(PROTOCOLS)
        align.calibrate()
        events = ScenarioDSL().parse("t=0 zigbee join; t=10 wifi bulk")
        frames = expand_activity(events)
        with tempfile.TemporaryDirectory() as td:
            manifest = write_logs(frames, align, td)
            self.assertEqual(len(manifest), 7)  # 6 radios + labels.jsonl
            for p in manifest:
                self.assertTrue(os.path.exists(p))
            with open(manifest[-1]) as fh:
                lines = [json.loads(l) for l in fh if l.strip()]
            self.assertEqual(len(lines), len(frames))
            self.assertIn("time_ms", lines[0])
            self.assertIn("radio", lines[0])


class TestInterferenceF1(unittest.TestCase):
    def setUp(self):
        self.interf = InterferenceF1()

    def test_all_pairs(self):
        for a in PROTOCOLS:
            for b in PROTOCOLS:
                m = self.interf.get(a, b)
                self.assertIn("f1", m)

    def test_f1_range(self):
        for a in PROTOCOLS:
            for b in PROTOCOLS:
                m = self.interf.get(a, b)
                self.assertGreaterEqual(m["f1"], 0.0)
                self.assertLessEqual(m["f1"], 1.0)

    def test_deterministic(self):
        a = InterferenceF1()
        b = InterferenceF1()
        self.assertEqual(a.get("wifi", "zigbee"), b.get("wifi", "zigbee"))


class TestRunCaseStudy(unittest.TestCase):
    def test_runs_all_cases(self):
        rng = random.Random(0xC0DE)
        interfer = InterferenceF1()
        for cs in CASE_STUDIES:
            result = run_case_study(cs, rng, interfer)
            self.assertEqual(result["id"], cs["id"])
            self.assertIn("verdict", result)
            self.assertLessEqual(result["lost_frames"], result["victim_frames"])

    def test_verdict_valid(self):
        rng = random.Random(0xC0DE)
        interfer = InterferenceF1()
        valid = {"SEVERE", "DEGRADED", "PARTIAL", "MARGINAL"}
        for cs in CASE_STUDIES:
            result = run_case_study(cs, rng, interfer)
            self.assertIn(result["verdict"], valid)


class TestSuppressionTable(unittest.TestCase):
    def test_cross_band_low(self):
        self.assertLessEqual(SUPPRESSION_DB.get(("wifi", "subghz"), 1.0), 1.0)


class TestDemo(unittest.TestCase):
    def test_demo_runs(self):
        from phytbed_orchestrator import demo
        ret = demo(argv=[])
        self.assertEqual(ret, 0)


if __name__ == "__main__":
    unittest.main()
