"""Controlled clocks and threads only; never camera hardware or Windows input."""

import json
import threading
import unittest
from unittest.mock import Mock, patch

from camera.capture_timeline import CaptureTimeline
from hand_tracking.performance import Profile


class TimelineTest(unittest.TestCase):
    def timeline(self, **kwargs):
        self.now, self.cpu = 100., 10.
        return CaptureTimeline(True, clock=lambda: self.now, cpu_clock=lambda: self.cpu, **kwargs)

    def test_disabled_never_reads_clock_or_allocates_buckets(self):
        clock = Mock(side_effect=AssertionError("disabled clock"))
        t = CaptureTimeline(clock=clock, cpu_clock=clock)
        t.begin()
        t.record(counts={"capture_attempts": 1}, processed=True, state="minimized")
        t.finish()
        self.assertEqual(t.summary(), {"enabled": False, "buckets": []})
        clock.assert_not_called()

    def test_empty_warmup_has_no_fabricated_rate_or_measurement(self):
        t = self.timeline()
        t.record(counts={"successful_frames": 99}, state="minimized", hands=2)
        self.assertEqual(t.summary()["buckets"], [])
        t.begin()
        t.finish()
        b = t.summary()["buckets"][0]
        self.assertIsNone(b["processed_application_fps"])
        self.assertEqual(b["counts"]["successful_frames"], 0)
        self.assertEqual(b["last_observed_hand_count"], 2)

    def test_bucket_counts_rates_and_percentiles_use_actual_elapsed_time(self):
        t = self.timeline()
        t.begin()
        for n in range(1, 5):
            self.now = 100+n*.25
            self.cpu = 10+n*.1
            t.record(counts={"successful_frames": 1, "consumed_frames": 1}, processed=True, hands=2,
                     timings={"camera_read": n*.01, "consumer_wait": .002})
        t.finish()
        b = t.summary()["buckets"][0]
        self.assertEqual(b["elapsed_seconds"], 1.)
        self.assertEqual(b["capture_worker_delivery_fps"], 4.)
        self.assertEqual(b["processed_application_fps"], 4.)
        self.assertEqual(b["hand_count_frames"], {"2": 4})
        self.assertAlmostEqual(b["timings"]["camera_read"]["mean_ms"], 25)
        self.assertAlmostEqual(b["timings"]["camera_read"]["p95_ms"], 38.5)
        self.assertAlmostEqual(b["process_cpu_percent_of_one_core_estimated"], 40)

    def test_state_residence_and_endpoint_attribution_across_boundaries(self):
        t = self.timeline()
        t.record(state="focused")
        t.begin()
        for at, state in ((100.5, "unfocused"), (101., "minimized"), (102.5, "focused")):
            self.now = at
            t.record(state=state, counts={"successful_frames": 1})
        self.now = 103.
        t.finish()
        a, b = t.summary()["buckets"]
        self.assertEqual(a["preview_state"], "mixed")
        self.assertEqual(a["preview_state_seconds"], {"focused": .5, "unfocused": .5, "minimized": 1.})
        self.assertEqual(b["preview_state_seconds"], {"minimized": .5, "focused": .5})
        self.assertEqual((a["counts"]["successful_frames"], b["counts"]["successful_frames"]), (2, 1))

    def test_no_frames_or_progress_still_retains_zero_delivery_buckets(self):
        t = self.timeline()
        t.begin()
        t.record(read_started=self.now, counts={"capture_attempts": 1}, state="minimized")
        self.now += 5.
        self.cpu += .25
        t.record(counts={"consumer_wait_timeouts": 1})
        t.finish()
        buckets = t.summary()["buckets"]
        self.assertEqual([b["elapsed_seconds"] for b in buckets], [2., 2., 1.])
        self.assertTrue(all(b["capture_worker_delivery_fps"] == 0 for b in buckets))
        self.assertTrue(all(b["read_in_progress_at_end"] for b in buckets))
        self.assertAlmostEqual(sum(b["process_cpu_seconds_estimated"] for b in buckets), .25)
        self.assertEqual(sum(b["counts"]["capture_attempts"] for b in buckets), 1)

    def test_cursor_intervals_are_actual_dispatch_endpoints(self):
        t = self.timeline()
        t.begin()
        for at in (100.1, 100.12, 100.16):
            self.now = at
            t.record(cursor_at=at, timings={"host_frame_age_at_dispatch": .025})
        t.finish()
        timings = t.summary()["buckets"][0]["timings"]
        self.assertEqual(timings["cursor_update_interval"]["count"], 2)
        self.assertAlmostEqual(timings["cursor_update_interval"]["mean_ms"], 30.)
        self.assertAlmostEqual(timings["host_frame_age_at_dispatch"]["mean_ms"], 25.)

    def test_sync_reports_host_reads_without_claiming_independent_worker_fps(self):
        t = self.timeline(producer_mode="sync")
        t.begin()
        self.now += 1.
        t.record(counts={"successful_frames": 20, "consumed_frames": 20})
        t.finish()
        b = t.summary()["buckets"][0]
        self.assertIsNone(b["capture_worker_delivery_fps"])
        self.assertEqual(b["host_read_or_publication_fps"], 20.)
        self.assertIsNone(b["capture_thread_cpu_percent_of_one_core_estimated"])

    def test_bounded_retention_and_percentile_samples(self):
        t = self.timeline(capacity=2, sample_capacity=3)
        t.begin()
        for n in range(30):
            self.now = 100+n*.25
            t.record(timings={"camera_read": n*.001}, counts={"successful_frames": 1})
        t.finish()
        d = t.summary()
        self.assertEqual(len(d["buckets"]), 2)
        self.assertEqual(d["buckets_discarded"], 2)
        self.assertTrue(all(b["timings"]["camera_read"]["percentile_samples"] <= 3 for b in d["buckets"]))

    def test_long_suspend_keeps_accounting_and_work_bounded(self):
        t = self.timeline(capacity=3)
        t.begin()
        self.now += 1000000.5
        t.finish()
        d = t.summary()
        self.assertEqual(len(d["buckets"]), 3)
        self.assertEqual(d["buckets"][-1]["index"], 500000)
        self.assertEqual(d["buckets_discarded"], 499998)

    def test_reset_measurement_excludes_warmup_and_previous_intervals(self):
        t = self.timeline()
        t.begin()
        t.record(processed=True, counts={"successful_frames": 100})
        self.now += 10.
        t.begin()
        t.record(processed=True)
        self.now += .5
        t.finish()
        b = t.summary()["buckets"][0]
        self.assertEqual(b["counts"]["successful_frames"], 0)
        self.assertNotIn("frame_interval", b["timings"])
        self.assertEqual(b["processed_application_fps"], 2.)

    def test_finish_is_idempotent_and_late_publications_cannot_extend_measurement(self):
        t = self.timeline()
        t.begin()
        self.now += 1.
        t.finish()
        original = t.summary()
        self.now += 50.
        t.record(counts={"successful_frames": 999}, state="focused")
        t.finish()
        self.assertEqual(t.summary(), original)

    def test_invalid_keys_states_hands_and_timings_are_rejected(self):
        t = self.timeline()
        t.begin()
        for args in ({"state": "foreign title"}, {"hands": 5}, {"hands": True},
                     {"counts": {"arbitrary_key": 1}}, {"timings": {"camera_read": -.1}},
                     {"timings": {"camera_read": float("nan")}}, {"timings": {"unknown": .1}}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                t.record(**args)

    def test_json_contains_numeric_diagnostics_without_pixels(self):
        t = self.timeline()
        t.begin()
        self.now += .1
        t.record(processed=True, hands=0, timings={"inference": .01})
        t.finish()
        report = json.loads(json.dumps(t.summary(), allow_nan=False))
        self.assertEqual(report["buckets"][0]["hand_count_frames"], {"0": 1})
        self.assertNotIn("image", report)

    def test_percentile_serialization_does_not_hold_event_lock(self):
        t = self.timeline()
        t.begin()
        t.record(timings={"camera_read": .01})
        entered, release, recorded = threading.Event(), threading.Event(), threading.Event()
        original = Profile.summary
        def slow_summary(profile):
            entered.set()
            if not release.wait(2):
                raise RuntimeError("test summary deadline")
            return original(profile)
        with patch.object(Profile, "summary", slow_summary):
            exporter = threading.Thread(target=t.summary)
            producer = threading.Thread(target=lambda: (t.record(counts={"successful_frames": 1}), recorded.set()))
            try:
                exporter.start()
                self.assertTrue(entered.wait(1))
                producer.start()
                self.assertTrue(recorded.wait(1))
            finally:
                release.set()
                exporter.join(2)
                if producer.ident is not None:
                    producer.join(2)
        self.assertFalse(exporter.is_alive())
        self.assertFalse(producer.is_alive())


if __name__ == "__main__":
    unittest.main()
