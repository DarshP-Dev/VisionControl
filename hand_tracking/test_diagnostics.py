import json
import unittest

from .diagnostics import PacingDiagnostics, process_memory
from .performance import WorkloadProfile


class PacingTest(unittest.TestCase):
    def test_frame_intervals_stalls_and_state_transition(self):
        stats = PacingDiagnostics(True, stall_seconds=.1)
        for read, end, state in ((.01, .02, "focused"), (.04, .05, "focused"),
                                 (.15, .18, "minimized"), (.19, .20, "focused")):
            stats.begin(read, state)
            stats.finish(read-.005, end)
        report = stats.summary()
        self.assertEqual(report["long_frame_stalls"], {"minimized": 1})
        self.assertEqual(report["transitions"], {"focused->minimized": 1, "minimized->focused": 1})
        self.assertAlmostEqual(report["timings"]["frame_completion_interval"]["p50_ms"], 30)
        self.assertAlmostEqual(report["timings"]["frame_completion_interval"]["max_ms"], 130)
        self.assertAlmostEqual(report["capture_delivery_fps"], 1/.06)
        self.assertAlmostEqual(report["by_preview_state"]["focused"]["application_fps"], 3/.065)
        self.assertIsNone(report["dropped_camera_frames"])
        self.assertIsNone(report["camera_sensor_fps"])

    def test_cursor_intervals_backend_latency_and_frame_age(self):
        stats = PacingDiagnostics(True)
        for read, before, after, state in ((1., 1.010, 1.012, "focused"),
                                           (1.030, 1.040, 1.045, "focused"),
                                           (1.060, 1.070, 1.072, "unfocused")):
            stats.begin(read, state)
            stats.moved(before, after)
        stages = stats.summary()["timings"]
        self.assertEqual(stages["cursor_update_interval"]["count"], 2)
        self.assertAlmostEqual(stages["cursor_update_interval"]["mean_ms"], 30)
        self.assertAlmostEqual(stages["cursor_dispatch"]["mean_ms"], 3)
        self.assertAlmostEqual(stages["host_frame_age_at_dispatch"]["p95_ms"], 14.7)
        self.assertEqual(stages["cursor_update_interval_transition"]["count"], 1)
        # Even if no moves occur out of focus, a switch away and back is a
        # transition interval rather than a steady-state pacing sample.
        stats = PacingDiagnostics(True)
        stats.begin(1., "focused")
        stats.moved(1.01, 1.02)
        stats.begin(1.03, "unfocused")
        stats.begin(1.06, "focused")
        stats.moved(1.07, 1.08)
        self.assertEqual(stats.summary()["timings"]["cursor_update_interval_transition"]["count"], 1)
        self.assertNotIn("cursor_update_interval_same_state", stats.summary()["timings"])

    def test_samples_and_states_are_bounded(self):
        stats = PacingDiagnostics(True, capacity=3)
        for i in range(100):
            stats.begin(i*.03, "minimized")
            stats.moved(i*.03+.001, i*.03+.002)
            stats.finish(i*.03, i*.03+.003)
        report = stats.summary()
        self.assertEqual(report["cursor_updates"], 100)
        self.assertTrue(all(s["percentile_samples"] <= 3 for s in report["timings"].values()))
        with self.assertRaises(ValueError):
            stats.begin(4., "arbitrary_foreign_title")

    def test_empty_disabled_and_memory_reports_are_json_serializable(self):
        stats = PacingDiagnostics(False)
        stats.begin(1., "focused")
        stats.moved(1.1, 1.2)
        stats.finish(1., 1.3)
        self.assertEqual(stats.summary()["timings"], {})
        self.assertEqual(stats.summary()["frames_by_preview_state"], {})
        self.assertIsNone(stats.summary()["capture_delivery_fps"])
        json.dumps({"pacing": stats.summary(), "memory": process_memory()}, allow_nan=False)
        stats = PacingDiagnostics(True)
        stats.begin(.01, "focused")
        stats.finish(0., .02)
        self.assertEqual(stats.summary()["by_preview_state"]["focused"]["frames"], 1)
        self.assertAlmostEqual(stats.summary()["by_preview_state"]["focused"]["application_fps"], 50.)

    def test_stage_percentiles_are_separated_by_preview_state(self):
        stats = WorkloadProfile(capacity=3)
        for state, cost in (("focused", .01), ("minimized", .002), ("focused", .02)):
            stats.add("inference", cost)
            stats.finish_frame(2, state)
        self.assertAlmostEqual(stats.preview_summary()["focused"]["inference"]["mean_ms"], 15)
        self.assertAlmostEqual(stats.preview_summary()["minimized"]["inference"]["p99_ms"], 2)
        self.assertEqual(stats.workload_summary()["2"]["inference"]["count"], 3)

    def test_first_frame_stall_and_intentional_cursor_gap_are_visible(self):
        stats = PacingDiagnostics(True)
        stats.begin(.01, "focused")
        stats.moved(.2, .21)
        stats.finish(0., .22)
        stats.begin(.50, "focused")
        stats.moved(.51, .52)
        self.assertEqual(stats.summary()["long_frame_stalls"], {"focused": 1})
        self.assertEqual(stats.summary()["cursor_gaps_over_threshold_including_intentional_pauses"], {"focused": 1})


if __name__ == "__main__":
    unittest.main()
