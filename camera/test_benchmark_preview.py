"""Diagnostic matrix B with fake camera/UI. No model or desktop input."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from camera import benchmark_delivery as benchmark
from camera.test_windows_timing import FakeAPI
from camera.windows_timing import WindowsTimerPolicy
from hand_tracking.preview_window import PreviewWindow


class CameraPreviewTest(unittest.TestCase):
    def test_interrupt_during_camera_release_still_destroys_gui_and_restores_timer_policy(self):
        api = FakeAPI()
        cap, window = MagicMock(), MagicMock()
        cap.read.return_value = (False, None)
        cap.release.side_effect = KeyboardInterrupt()
        window.state.return_value = "focused"
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory, \
                patch.object(cv2, "VideoCapture", return_value=cap), \
                patch.object(benchmark, "configure_capture", return_value={}), \
                patch.object(benchmark, "capture_snapshot", return_value={}), \
                patch.object(benchmark, "WindowsTimerPolicy", side_effect=lambda mode: WindowsTimerPolicy(mode, api=api)), \
                patch.object(cv2, "namedWindow"), patch.object(cv2, "destroyAllWindows") as destroy, \
                patch.object(benchmark, "create_preview_window", return_value=window), \
                patch.object(benchmark, "GuiEvents") as gui, redirect_stdout(io.StringIO()):
            gui.return_value.read_key.return_value = -1
            with self.assertRaises(KeyboardInterrupt):
                benchmark.main(["--preview", "--windows-timer-policy", "honor-requests", "--report",
                                str(Path(directory)/"interrupted_release.json")])
        destroy.assert_called_once()
        self.assertEqual(api.state, (1, 1, 1))
        self.assertEqual(len(api.sets), 2)

    def test_gui_setup_and_cleanup_failure_still_saves_numeric_failure_report(self):
        cap = MagicMock()
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory, \
                patch.object(cv2, "VideoCapture", return_value=cap), \
                patch.object(benchmark, "configure_capture", return_value={}), \
                patch.object(benchmark, "capture_snapshot", return_value={}), \
                patch.object(cv2, "namedWindow", side_effect=cv2.error("no UI")), \
                patch.object(cv2, "destroyAllWindows", side_effect=cv2.error("no UI cleanup")), \
                redirect_stdout(io.StringIO()):
            path = Path(directory)/"ui_failure.json"
            code = benchmark.main(["--preview", "--report", str(path)])
            d = json.loads(path.read_text())
        self.assertEqual(code, 1)
        self.assertEqual(d["status"], "error")
        self.assertIn("no UI", d["error"])
        self.assertIn("no UI cleanup", d["preview_cleanup_error"])
        cap.release.assert_called_once()

    def test_sync_release_failure_is_recorded_after_read_failure(self):
        cap = MagicMock()
        cap.read.return_value = (False, None)
        cap.release.side_effect = OSError("release failed")
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory, \
                patch.object(cv2, "VideoCapture", return_value=cap), \
                patch.object(benchmark, "configure_capture", return_value={}), \
                patch.object(benchmark, "capture_snapshot", return_value={}), redirect_stdout(io.StringIO()):
            path = Path(directory)/"release_failure.json"
            code = benchmark.main(["--report", str(path)])
            d = json.loads(path.read_text())
        self.assertEqual(code, 1)
        self.assertEqual(d["status"], "error")
        self.assertEqual(d["shutdown_error"], "release failed")

    def run_benchmark(self, pipeline, *, close=False, fail=False, timer_policy="system", repeat_states=False):
        api = FakeAPI()
        owner, gui_threads, state_threads = [], [], []
        cap, window = MagicMock(), MagicMock()
        reads = []
        def read():
            owner.append(threading.get_ident())
            time.sleep(.002)
            reads.append(1)
            return (False, None) if fail and len(reads) >= 3 else (True, np.zeros((12, 20, 3), np.uint8))
        cap.read.side_effect = read
        cap.release.side_effect = lambda: owner.append(threading.get_ident())
        checks = []
        def state():
            state_threads.append(threading.get_ident())
            checks.append(1)
            n = (len(checks)-1) % 18+1 if repeat_states else len(checks)
            return "closed" if close and n >= 12 else ("focused" if n < 4 or n >= 18
                    else "unfocused" if n < 8 else "minimized")
        window.state.side_effect = state
        window.should_render.side_effect = PreviewWindow.should_render
        def display(*_):
            gui_threads.append(threading.get_ident())
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory, \
                patch.object(cv2, "VideoCapture", return_value=cap), \
                patch.object(benchmark, "configure_capture", return_value={}), \
                patch.object(benchmark, "capture_snapshot", return_value={}), \
                patch.object(cv2, "namedWindow", side_effect=display), \
                patch.object(cv2, "imshow", side_effect=display) as show, \
                patch.object(cv2, "destroyAllWindows", side_effect=display), \
                patch.object(benchmark, "create_preview_window", return_value=window), \
                patch.object(benchmark, "GuiEvents") as gui, \
                patch.object(benchmark, "WindowsTimerPolicy", side_effect=lambda mode: WindowsTimerPolicy(mode, api=api)), \
                patch("hand_tracking.hand_tracker.create_landmarker") as model, \
                patch("controls.windows.WindowsBackend") as backend, redirect_stdout(io.StringIO()):
            gui.return_value.read_key.return_value = -1
            gui.return_value.metadata.return_value = {"effective": "mock"}
            path = Path(directory)/"preview.json"
            code = benchmark.main(["--capture-pipeline", pipeline, "--windows-timer-policy", timer_policy,
                                   "--preview", "--warmup", "0",
                                   "--duration", ".05", "--report", str(path)])
            report = json.loads(path.read_text())
            model.assert_not_called()
            backend.assert_not_called()
            self.assertTrue(gui_threads)
            self.assertTrue(all(t == threading.get_ident() for t in gui_threads+state_threads))
            cap.release.assert_called_once()
            self.assertTrue(all(t == owner[0] for t in owner))
            self.assertEqual(api.state, (1, 1, 1))
            self.assertEqual(len(api.sets), 2 if timer_policy == "honor-requests" else 0)
            return code, report, show.call_count, window

    def test_honor_policy_restores_after_minimize_restore_close_and_capture_fault(self):
        for pipeline in ("sync", "latest-thread"):
            for options in ({}, {"repeat_states": True}, {"close": True}, {"fail": True}):
                with self.subTest(pipeline=pipeline, options=options):
                    _, d, _, _ = self.run_benchmark(pipeline, timer_policy="honor-requests", **options)
                    self.assertEqual(d["windows_timer_policy"]["requested"], "honor-requests")
                    self.assertTrue(d["windows_timer_policy"]["changed"])
                    self.assertTrue(d["windows_timer_policy"]["restored"])
                    self.assertFalse(d["windows_timer_policy"]["active"])

    def test_both_pipelines_measure_gui_without_model_and_skip_minimized_draws(self):
        for pipeline in ("sync", "latest-thread"):
            with self.subTest(pipeline=pipeline):
                code, d, draws, window = self.run_benchmark(pipeline)
                self.assertEqual(code, 0)
                self.assertEqual(d["kind"], "camera_highgui_host_delivery")
                self.assertGreater(d["preview_renders_skipped"], 0)
                self.assertGreater(draws, 0)
                self.assertGreater(d["frames"], draws)
                b = d["capture_timeline"]["buckets"][0]
                self.assertEqual(b["counts"]["processed_frames"], d["frames"])
                self.assertIn("minimized", b["preview_state_seconds"])
                self.assertIn("focused", b["preview_state_seconds"])
                if pipeline == "latest-thread":
                    capture = d["capture_pipeline"]
                    self.assertFalse(capture["worker_alive"])
                    self.assertTrue(capture["release_completed"])
                    self.assertEqual(capture["max_buffer_occupancy"], 1)

    def test_x_is_terminal_in_both_diagnostic_pipelines(self):
        for pipeline in ("sync", "latest-thread"):
            with self.subTest(pipeline=pipeline):
                code, d, _, _ = self.run_benchmark(pipeline, close=True)
                self.assertEqual(code, 1)  # Early exit is not a completed timed benchmark.
                self.assertEqual(d["status"], "preview_closed")
                if pipeline == "latest-thread":
                    self.assertTrue(d["capture_pipeline"]["release_completed"])
                    self.assertFalse(d["capture_pipeline"]["worker_alive"])

    def test_read_failure_records_fault_and_releases_while_minimized(self):
        for pipeline in ("sync", "latest-thread"):
            with self.subTest(pipeline=pipeline):
                code, d, _, _ = self.run_benchmark(pipeline, fail=True)
                self.assertEqual(code, 1)
                self.assertEqual(d["status"], "error")
                self.assertEqual(sum(b["counts"]["read_failures"] for b in d["capture_timeline"]["buckets"]), 1)


if __name__ == "__main__":
    unittest.main()
