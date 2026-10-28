"""Application integration with a real worker and injected camera/model/UI."""

from contextlib import redirect_stderr
import io
from pathlib import Path
import threading
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import cv2

from camera.latest_capture import CapturedFrame, CaptureError, LatestCapture
from camera.test_latest_capture import ScriptedCamera
from controls.backends import SimulationBackend
from controls.controller import DesktopController
from gestures.tests.static_fixtures import as_result
from gestures.tests.test_swipe import sample_hand
from . import hand_tracker as tracker
from .preview_window import PreviewWindow


FLAGS = ["--capture-pipeline", "latest-thread", "--gui-mode", "waitkey", "--gestures", "--pinch", "--gesture-states"]


class PipelineIntegrationTest(unittest.TestCase):
    def start(self, **kwargs):
        camera = ScriptedCamera()
        original = camera.read
        def read():
            item = original()
            time.sleep(.002)  # Real unique milliseconds, independent of UI speed.
            return item
        camera.read = read
        source = LatestCapture(lambda: camera, **kwargs).start()
        def cleanup():
            source.request_stop()
            camera.unblock.set()
            source.close(1)
        self.addCleanup(cleanup)
        self.assertTrue(camera.read_entered.wait(1))
        return source, camera

    def test_default_sync_no_worker_and_cli_restrictions_remain(self):
        self.assertEqual(tracker.parse_args([]).capture_pipeline, "sync")
        for flags in (["--capture-pipeline", "bad"], FLAGS+["--controls", "--max-hands", "4"],
                      FLAGS+["--controls", "--benchmark", "--headless"]):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                tracker.parse_args(flags)
        args = tracker.parse_args(FLAGS)
        with self.assertRaises(ValueError):
            tracker.process_frames(None, None, None, args)

    def test_slow_main_thread_window_query_cannot_hold_capture_lock_or_stop_publications(self):
        source, camera = self.start(profile=True)
        entered, published = threading.Event(), threading.Event()
        errors = []
        def feed():
            try:
                if not entered.wait(1):
                    raise RuntimeError("GUI query not entered")
                for n in (1, 2):
                    camera.send(n)
                    with source.condition:
                        if not source.condition.wait_for(lambda: source.counts["successful_frames"] >= n, 1):
                            raise RuntimeError("GUI query blocked publication")
            except Exception as exc:
                errors.append(exc)
            finally:
                published.set()
        producer = threading.Thread(target=feed)
        window, detector = MagicMock(), MagicMock()
        def slow_state():
            entered.set()
            self.assertTrue(published.wait(2))
            return "closed"
        window.state.side_effect = slow_state
        producer.start()
        try:
            with patch.object(cv2, "waitKey", return_value=-1), self.assertLogs(tracker.LOGGER):
                tracker.process_frames(None, detector, None, tracker.parse_args(FLAGS), {},
                                       capture_source=source, preview_window=window)
        finally:
            producer.join(2)
        self.assertFalse(producer.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(source.counts["successful_frames"], 2)
        self.assertEqual(source.counts["overwritten_unconsumed_frames"], 1)
        detector.detect_for_video.assert_not_called()

    def test_real_worker_tracking_recognition_minimize_restore_and_unique_model_timestamps(self):
        source, camera = self.start(profile=True)
        detector = MagicMock()
        detection = as_result(sample_hand(side="Right").observation, sample_hand(side="Left", offset=-.3).observation)
        def infer(_image, _timestamp):
            if detector.detect_for_video.call_count < 6:
                camera.send(detector.detect_for_video.call_count+1)
            return detection
        detector.detect_for_video.side_effect = infer
        mp = SimpleNamespace(Image=lambda **kw: kw["data"], ImageFormat=SimpleNamespace(SRGB=1))
        window = MagicMock()
        def state():
            n = detector.detect_for_video.call_count
            return "minimized" if n in (3, 4) else "unfocused" if n == 2 else "focused"
        window.state.side_effect = state
        window.should_render.side_effect = PreviewWindow.should_render
        def key(*_):
            return ord("q") if detector.detect_for_video.call_count >= 6 else -1
        camera.send()
        report = {}
        with patch.object(cv2, "waitKey", side_effect=key), patch.object(cv2, "imshow") as display, \
                self.assertLogs(tracker.LOGGER):
            tracker.process_frames(None, detector, mp, tracker.parse_args(FLAGS), report,
                                   capture_source=source, preview_window=window)
        stamps = [c.args[1] for c in detector.detect_for_video.call_args_list]
        self.assertEqual(len(stamps), 6)
        self.assertTrue(all(b > a for a, b in zip(stamps, stamps[1:])))
        self.assertEqual(report["detected_hands_frames"], {"2": 6})
        self.assertEqual(display.call_count, 4)
        self.assertEqual(report["pacing"]["preview_frames_skipped"], 2)
        self.assertEqual(report["capture_pipeline_mode"], "latest-thread")
        self.assertIn("frame_age_at_inference_start", report["timings"])
        self.assertIn("processed_observation_interval", report["timings"])
        self.assertTrue(source.stop.is_set())
        timeline = report["capture_timeline"]["buckets"]
        self.assertEqual(sum(b["counts"]["processed_frames"] for b in timeline), 6)
        self.assertEqual(sum(b["hand_count_frames"].get("2", 0) for b in timeline), 6)
        states = {state for b in timeline for state in b["preview_state_seconds"]}
        self.assertTrue({"focused", "unfocused", "minimized"} <= states)

    def test_preview_x_while_waiting_for_first_frame_cancels_drag_without_inference(self):
        source, camera = self.start()
        controller = DesktopController(SimulationBackend())
        controller.armed = True
        controller.button_down = controller.backend.button_down = True
        detector = MagicMock()
        window = MagicMock()
        window.state.return_value = "closed"
        with patch.object(cv2, "waitKey", return_value=-1), self.assertLogs(tracker.LOGGER):
            report = {}
            tracker.process_frames(None, detector, None, tracker.parse_args(FLAGS+["--controls"]), report,
                                   controller, capture_source=source, preview_window=window)
        detector.detect_for_video.assert_not_called()
        self.assertFalse(controller.backend.button_down)
        self.assertFalse(controller.armed)
        self.assertEqual(report["status"], "preview_closed")
        self.assertTrue(source.stop.is_set())

    def test_worker_fault_during_inference_discards_result_and_releases_drag(self):
        source, camera = self.start()
        controller = DesktopController(SimulationBackend())
        controller.armed = True
        controller.button_down = controller.backend.button_down = True
        detector = MagicMock()
        def infer(*_):
            camera.queue.put(RuntimeError("fault during inference"))
            self.assertTrue(source.failed.wait(1))
            return as_result()
        detector.detect_for_video.side_effect = infer
        mp = SimpleNamespace(Image=lambda **kw: kw["data"], ImageFormat=SimpleNamespace(SRGB=1))
        camera.send()
        window = MagicMock()
        window.state.return_value = "focused"
        with self.assertLogs(tracker.LOGGER), self.assertRaisesRegex(CaptureError, "fault during inference"):
            tracker.process_frames(None, detector, mp, tracker.parse_args(FLAGS+["--controls"]), {}, controller,
                                   capture_source=source, preview_window=window)
        self.assertFalse(controller.backend.button_down)
        self.assertFalse(controller.armed)
        self.assertEqual(controller.backend.counts["move"], 0)

    def test_stalled_initial_read_keeps_gui_polling_and_fails_with_deadline(self):
        source, camera = self.start(startup_timeout=.04)
        detector = MagicMock()
        window = MagicMock()
        window.state.return_value = "minimized"
        with patch.object(cv2, "waitKey", return_value=-1) as pump, \
                self.assertLogs(tracker.LOGGER), self.assertRaisesRegex(CaptureError, "first-frame timeout"):
            tracker.process_frames(None, detector, None, tracker.parse_args(FLAGS), {},
                                   capture_source=source, preview_window=window)
        self.assertGreater(pump.call_count, 0)
        detector.detect_for_video.assert_not_called()
        self.assertTrue(source.stop.is_set())

    def test_benchmark_deadline_progresses_even_when_all_inference_results_are_stale(self):
        import numpy as np
        now = [0.]
        source = MagicMock()
        source.origin, source.session = 0., "test-session"
        def take(_timeout):
            now[0] += .001
            return CapturedFrame(source.session, source.take.call_count, now[0], .001, now[0],
                                 (20, 12), np.zeros((12, 20, 3), np.uint8))
        source.take.side_effect = take
        detector = MagicMock()
        def infer(*_):
            now[0] += .3
            return as_result()
        detector.detect_for_video.side_effect = infer
        mp = SimpleNamespace(Image=lambda **kw: kw["data"], ImageFormat=SimpleNamespace(SRGB=1))
        args = tracker.parse_args(FLAGS+["--benchmark", "--headless", "--warmup", ".1", "--duration", ".5"])
        report = {}
        with patch.object(tracker.time, "perf_counter", side_effect=lambda: now[0]), self.assertLogs(tracker.LOGGER):
            tracker.process_frames(None, detector, mp, args, report, capture_source=source)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["frames"], 0)
        self.assertEqual(report["average_application_fps"], 0.)
        self.assertGreaterEqual(report["measurement_seconds"], .5)
        self.assertEqual(source.record_rejection.call_count, 3)
        self.assertEqual(detector.detect_for_video.call_count, 3)

    def test_worker_initialization_time_does_not_replace_model_warmup(self):
        import numpy as np
        now, boundaries = [0.], []
        source = MagicMock()
        source.origin, source.session = 0., "slow-open"
        def take(_):
            now[0] = 6. if source.take.call_count == 1 else now[0]+.2
            return CapturedFrame(source.session, source.take.call_count, now[0], .001, now[0],
                                 (20, 12), np.zeros((12, 20, 3), np.uint8))
        source.take.side_effect = take
        source.begin_measurement.side_effect = lambda: boundaries.append(now[0])
        detector = MagicMock()
        def infer(*_):
            now[0] += .01
            return as_result()
        detector.detect_for_video.side_effect = infer
        mp = SimpleNamespace(Image=lambda **kw: kw["data"], ImageFormat=SimpleNamespace(SRGB=1))
        args = tracker.parse_args(FLAGS+["--benchmark", "--headless", "--warmup", ".5", "--duration", ".5"])
        report = {}
        with patch.object(tracker.time, "perf_counter", side_effect=lambda: now[0]), self.assertLogs(tracker.LOGGER):
            tracker.process_frames(None, detector, mp, args, report, capture_source=source)
        self.assertEqual(len(boundaries), 1)
        self.assertGreaterEqual(boundaries[0], 6.5)
        self.assertEqual(report["status"], "completed")

    def test_equal_capture_milliseconds_are_suppressed_before_model_inference(self):
        import numpy as np
        source = MagicMock()
        source.origin, source.session = 1., "millisecond-test"
        packets = [CapturedFrame(source.session, i, stamp, .001, stamp, (20, 12),
                                  np.zeros((12, 20, 3), np.uint8))
                   for i, stamp in enumerate((1.0001, 1.0002, 1.0105), 1)]
        source.take.side_effect = packets
        detector = MagicMock()
        detector.detect_for_video.return_value = as_result()
        mp = SimpleNamespace(Image=lambda **kw: kw["data"], ImageFormat=SimpleNamespace(SRGB=1))
        window = MagicMock()
        window.state.return_value = "focused"
        with patch.object(tracker.time, "perf_counter", return_value=1.02), \
                patch.object(cv2, "waitKey", side_effect=lambda *_: ord("q") if detector.detect_for_video.call_count == 2 else -1), \
                patch.object(cv2, "imshow"), self.assertLogs(tracker.LOGGER):
            tracker.process_frames(None, detector, mp, tracker.parse_args(FLAGS), {},
                                   capture_source=source, preview_window=window)
        self.assertEqual([call.args[1] for call in detector.detect_for_video.call_args_list], [0, 10])
        source.record_rejection.assert_called_once_with("millisecond_timestamp_collisions_suppressed")

    def test_stale_slot_is_not_inferred_and_next_fresh_snapshot_is_processed_once(self):
        import numpy as np
        source = MagicMock()
        source.origin, source.session = 0., "stale-slot"
        source.take.side_effect = [CapturedFrame(source.session, i, stamp, .001, stamp,
                                                (20, 12), np.zeros((12, 20, 3), np.uint8))
                                   for i, stamp in enumerate((.7, 1.01), 1)]
        detector = MagicMock()
        detector.detect_for_video.return_value = as_result()
        mp = SimpleNamespace(Image=lambda **kw: kw["data"], ImageFormat=SimpleNamespace(SRGB=1))
        window = MagicMock()
        window.state.return_value = "focused"
        with patch.object(tracker.time, "perf_counter", return_value=1.02), \
                patch.object(cv2, "waitKey", side_effect=lambda *_: ord("q") if detector.detect_for_video.call_count else -1), \
                patch.object(cv2, "imshow"), self.assertLogs(tracker.LOGGER):
            tracker.process_frames(None, detector, mp, tracker.parse_args(FLAGS), {},
                                   capture_source=source, preview_window=window)
        detector.detect_for_video.assert_called_once()
        self.assertEqual(source.take.call_count, 2)
        source.record_rejection.assert_called_once_with("stale_frames_rejected")

    def test_worker_four_hand_observation_path_preserves_all_slots_and_ids(self):
        from .test_multi_hand import four
        source, camera = self.start()
        detector = MagicMock()
        def infer(*_):
            if detector.detect_for_video.call_count == 1:
                camera.send(2)
            return as_result(*four())
        detector.detect_for_video.side_effect = infer
        mp = SimpleNamespace(Image=lambda **kw: kw["data"], ImageFormat=SimpleNamespace(SRGB=1))
        window = MagicMock()
        window.state.return_value = "focused"
        camera.send()
        with patch.object(cv2, "waitKey", side_effect=lambda *_: ord("q") if detector.detect_for_video.call_count == 2 else -1), \
                patch.object(cv2, "imshow"), self.assertLogs(tracker.LOGGER):
            report = {}
            tracker.process_frames(None, detector, mp, tracker.parse_args(FLAGS+["--max-hands", "4"]), report,
                                   capture_source=source, preview_window=window)
        self.assertEqual(report["detected_hands_frames"], {"4": 2})
        self.assertEqual(report["association_transitions"]["created"], 4)
        self.assertEqual(report["timings"]["association"]["count"], 2)

    def test_real_worker_palm_simulation_keeps_moving_while_minimized_without_phantom_click(self):
        from controls import cli
        source, camera = self.start()
        detector = MagicMock()
        def infer(*_):
            n = detector.detect_for_video.call_count
            if n < 16:
                camera.send(n+1)
            time.sleep(.02)  # Let real capture timestamps exercise activation timing.
            return as_result(sample_hand(dx=n*.01, side="Right").observation)
        detector.detect_for_video.side_effect = infer
        mp = SimpleNamespace(Image=lambda **kw: kw["data"], ImageFormat=SimpleNamespace(SRGB=1))
        args = tracker.parse_args(FLAGS+["--controls", "--control-gesture-profile", "palm-cursor",
                                        "--control-mapping", "absolute", "--control-mouse"])
        controller = DesktopController(SimulationBackend(), cli.settings(args))
        snapshots = {}
        update = controller.update
        def record(*a, **kw):
            update(*a, **kw)
            snapshots[detector.detect_for_video.call_count] = (controller.armed, controller.backend.counts["move"])
        controller.update = record
        window = MagicMock()
        window.state.side_effect = lambda: "minimized" if 10 <= detector.detect_for_video.call_count <= 13 else "focused"
        window.should_render.side_effect = PreviewWindow.should_render
        armed = []
        def key(*_):
            n = detector.detect_for_video.call_count
            if n >= 16:
                return ord("q")
            if n == 7 and not armed:
                armed.append(True)
                return ord("a")
            return -1
        camera.send()
        with patch.object(cv2, "waitKey", side_effect=key), patch.object(cv2, "imshow"), self.assertLogs(tracker.LOGGER):
            tracker.process_frames(None, detector, mp, args, {}, controller,
                                   capture_source=source, preview_window=window)
        self.assertTrue(all(snapshots[n][0] for n in range(10, 14)))
        self.assertGreater(snapshots[13][1], snapshots[9][1])
        self.assertGreater(snapshots[15][1], snapshots[13][1])
        self.assertEqual(controller.backend.counts["down"], 0)
        self.assertFalse(controller.backend.button_down)
        self.assertFalse(controller.armed)
        camera.unblock.set()
        source.close(1)
        self.assertFalse(source.thread.is_alive())

    def test_discarded_inference_cost_does_not_leak_into_next_completed_hand_bin(self):
        import numpy as np
        now = [1.]
        source = MagicMock()
        source.origin, source.session = 0., "discarded-model-work"
        source.take.side_effect = lambda _: CapturedFrame(source.session, source.take.call_count, now[0], .001,
                                                          now[0], (20, 12), np.zeros((12, 20, 3), np.uint8))
        detector = MagicMock()
        def infer(*_):
            now[0] += .3 if detector.detect_for_video.call_count == 1 else .01
            return as_result()
        detector.detect_for_video.side_effect = infer
        mp = SimpleNamespace(Image=lambda **kw: kw["data"], ImageFormat=SimpleNamespace(SRGB=1))
        window = MagicMock()
        window.state.return_value = "focused"
        with patch.object(tracker.time, "perf_counter", side_effect=lambda: now[0]), \
                patch.object(cv2, "waitKey", side_effect=lambda *_: ord("q") if detector.detect_for_video.call_count == 2 else -1), \
                patch.object(cv2, "imshow"), self.assertLogs(tracker.LOGGER):
            report = {}
            tracker.process_frames(None, detector, mp, tracker.parse_args(FLAGS), report,
                                   capture_source=source, preview_window=window)
        self.assertEqual(report["frames"], 1)
        self.assertEqual(report["timings"]["inference"]["count"], 2)
        self.assertAlmostEqual(report["timings_by_detected_hands"]["0"]["inference"]["mean_ms"], 10.)

    def test_preemption_before_clock_translation_does_not_extend_input_age(self):
        import numpy as np
        now, gui_delayed = [1.], []
        source = MagicMock()
        source.origin, source.session = 0., "clock-domains"
        source.input_allowed.return_value = True
        source.take.return_value = CapturedFrame(source.session, 1, .9, .001, .9,
                                                (20, 12), np.zeros((12, 20, 3), np.uint8))
        def timestamp(_):
            now[0] += .1  # Scheduling/validation delay AFTER initial packet-age check.
            return 900
        controller = DesktopController(SimulationBackend(), clock=lambda: now[0])
        controller.armed = controller.button_down = controller.backend.button_down = True
        controller._stop_requested.clear()
        controller._update = MagicMock()  # Observe acceptance before any geometry/action processing.
        detector = MagicMock()
        detector.detect_for_video.return_value = as_result()
        mp = SimpleNamespace(Image=lambda **kw: kw["data"], ImageFormat=SimpleNamespace(SRGB=1))
        window = MagicMock()
        window.state.side_effect = ["focused", "focused", "closed"]
        window.should_render.side_effect = PreviewWindow.should_render
        def key(*_):
            if detector.detect_for_video.call_count and not gui_delayed:
                gui_delayed.append(True)
                now[0] += .1  # Frame age is now 300 ms; cached acquisition age was only 100 ms.
            return -1
        with patch.object(tracker.time, "perf_counter", side_effect=lambda: now[0]), \
                patch.object(tracker, "CaptureTimestamp", return_value=SimpleNamespace(next=timestamp)), \
                patch.object(cv2, "waitKey", side_effect=key), patch.object(cv2, "imshow"), self.assertLogs(tracker.LOGGER):
            tracker.process_frames(None, detector, mp, tracker.parse_args(FLAGS+["--controls"]), {}, controller,
                                   capture_source=source, preview_window=window)
        controller._update.assert_not_called()
        self.assertFalse(controller.backend.button_down)
        self.assertFalse(controller.armed)

    def test_run_opens_configures_and_releases_msmf_only_on_worker(self):
        directory = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(directory.cleanup)
        model = Path(directory.name)/"mock.task"
        model.write_bytes(b"mock model; not loaded")
        camera = ScriptedCamera()
        camera.isOpened = lambda: True
        camera.set = lambda *_: camera.calls.append(("set", threading.get_ident())) or True
        camera.get = lambda *_: camera.calls.append(("get", threading.get_ident())) or 0.
        camera.getBackendName = lambda: "MSMF"
        owners = []
        def factory(*args):
            owners.append(threading.get_ident())
            self.assertEqual(args, (0, cv2.CAP_MSMF))
            return camera
        detector = MagicMock()
        window = MagicMock()
        window.state.return_value = "closed"
        # Unblock read on requested stop so cleanup is owner-only and bounded.
        original = LatestCapture.request_stop
        def stop(source):
            original(source)
            camera.unblock.set()
        with patch.object(tracker, "create_landmarker", return_value=(MagicMock(), detector)), \
                patch.object(cv2, "VideoCapture", side_effect=factory), \
                patch.object(tracker, "configure_capture", wraps=tracker.configure_capture) as configure, \
                patch.object(cv2, "namedWindow"), patch.object(cv2, "destroyAllWindows") as destroy, \
                patch.object(tracker, "create_preview_window", return_value=window), \
                patch.object(cv2, "waitKey", return_value=-1), \
                patch.object(LatestCapture, "request_stop", stop), self.assertLogs(level="INFO"):
            report = {}
            self.assertEqual(tracker.run(tracker.parse_args(FLAGS+["--model", str(model)]), report), 0)
        self.assertNotEqual(owners[0], threading.get_ident())
        self.assertTrue(all(owner == owners[0] for _, owner in camera.calls))
        self.assertEqual(camera.release_count, 1)
        configure.assert_called_once()
        detector.close.assert_called_once()
        destroy.assert_called_once()
        self.assertTrue(report["capture_pipeline"]["release_completed"])
        self.assertFalse(report["capture_pipeline"]["worker_alive"])


if __name__ == "__main__":
    unittest.main()
