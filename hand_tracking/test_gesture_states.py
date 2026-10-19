from contextlib import redirect_stderr
from copy import deepcopy
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from gestures.events import EventType as E, GestureState as S
from gestures.state_machine import GestureStateManager, StateSettings
from gestures.tests.pinch_fixtures import pinch_hand
from gestures.tests.static_fixtures import SIZE, as_result, pose_hand
from . import gesture_preview, hand_tracker as tracker
from .performance import Profile
from .tracking_utils import PreviewRenderer, make_preview


class GestureStateIntegrationTest(unittest.TestCase):
    def test_cli_opt_in_channels_timing_validation_and_existing_defaults(self):
        defaults = tracker.parse_args([])
        self.assertFalse(defaults.gesture_states)
        self.assertFalse(defaults.gesture_event_debug)
        self.assertEqual(tracker.state_settings(defaults), StateSettings())
        self.assertEqual((defaults.backend, defaults.width, defaults.height, defaults.gui_mode),
                         ("msmf", 1920, 1080, "auto"))
        for flags in (["--gestures", "--gesture-states"], ["--pinch", "--gesture-states", "--no-gestures"],
                      ["--gestures", "--pinch", "--gesture-states", "--gesture-event-debug"],
                      ["--gestures", "--gesture-states", "--gesture-activation-ms", "0",
                       "--gesture-transition-ms", "0", "--gesture-cooldown-ms", "0", "--gesture-update-ms", "0"]):
            self.assertTrue(tracker.parse_args(flags).gesture_states)
        for flags in (["--gesture-states"], ["--gesture-event-debug"],
                      ["--gestures", "--no-gestures", "--gesture-states"],
                      ["--gesture-activation-ms", "-1"], ["--gesture-transition-ms", "2.5"],
                      ["--gesture-cooldown-ms", "5001"], ["--gesture-update-ms", "nan"]):
            with self.subTest(flags=flags), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                tracker.parse_args(flags)

    def test_disabled_states_skip_engine_and_new_profiling(self):
        cap, detector = MagicMock(), MagicMock()
        cap.read.return_value = True, np.zeros((1080, 1920, 3), np.uint8)
        detector.detect_for_video.return_value = as_result(pose_hand())
        mp = SimpleNamespace(Image=lambda **kw: kw["data"], ImageFormat=SimpleNamespace(SRGB=1))
        report = {}
        with patch.object(tracker, "GestureStateManager") as manager, patch.object(cv2, "imshow"), \
                patch.object(cv2, "waitKey", return_value=ord("q")), self.assertLogs(tracker.LOGGER):
            tracker.process_frames(cap, detector, mp, tracker.parse_args(["--gui-mode", "waitkey"]), report)
        manager.assert_not_called()
        self.assertFalse(report["gesture_states"]["enabled"])
        self.assertNotIn("state_management", report["timings"])

    def test_live_static_states_share_features_native_polling_and_q_h(self):
        cap, detector = MagicMock(), MagicMock()
        cap.read.return_value = True, np.full((1080, 1920, 3), 120, np.uint8)
        detector.detect_for_video.return_value = as_result(pose_hand())
        mp = SimpleNamespace(Image=lambda **kw: kw["data"], ImageFormat=SimpleNamespace(SRGB=1))
        now = iter(i*.001 for i in range(2000))
        report = {}
        with patch.object(tracker.time, "perf_counter", side_effect=lambda: next(now)), \
                patch.object(cv2, "currentUIFramework", return_value="WIN32", create=True), \
                patch.object(cv2, "pollKey", side_effect=[ord("h")] + [-1]*8 + [ord("q")], create=True), \
                patch.object(cv2, "waitKey") as wait, patch.object(cv2, "imshow"), \
                patch.object(cv2, "getWindowProperty", return_value=1), \
                patch.object(tracker, "make_preview", wraps=make_preview) as preview, \
                patch.object(gesture_preview, "extract_features", wraps=gesture_preview.extract_features) as extract, \
                self.assertLogs(tracker.LOGGER) as logs:
            tracker.process_frames(cap, detector, mp, tracker.parse_args(["--gestures", "--gesture-states"]), report)
        self.assertEqual(extract.call_count, 10)
        self.assertEqual(detector.detect_for_video.call_count, 10)
        self.assertEqual(report["gesture_states"]["event_counts"], {"GESTURE_STARTED:OPEN_PALM": 1})
        self.assertEqual(report["timings"]["state_management"]["count"], 10)
        self.assertEqual(report["timings_by_detected_hands"]["1"]["state_management"]["count"], 10)
        self.assertEqual(report["gui"]["effective"], "pollkey")
        self.assertEqual(report["gesture_states"]["shutdown_events"][0]["event_type"], E.GESTURE_CANCELED)
        self.assertFalse(preview.call_args_list[0].args[3])
        self.assertTrue(preview.call_args_list[1].args[3])
        self.assertTrue(any(h.state == S.ACTIVE for call in preview.call_args_list for h in call.kwargs["gesture_states"]))
        self.assertFalse(any("GESTURE_STARTED |" in message for message in logs.output))
        wait.assert_not_called()
        json.dumps(report, allow_nan=False)

    def test_live_both_channels_preserve_raw_results_and_reuse_extraction(self):
        frames = [as_result(pinch_hand(d, offset=-.23), pinch_hand(d, side="Right", offset=.23))
                  for d in (.8, .1, .1, .8)]
        before = deepcopy(frames)
        cap, detector = MagicMock(), MagicMock()
        cap.read.return_value = True, np.zeros((1080, 1920, 3), np.uint8)
        detector.detect_for_video.side_effect = frames
        mp = SimpleNamespace(Image=lambda **kw: kw["data"], ImageFormat=SimpleNamespace(SRGB=1))
        now = iter(i*.001 for i in range(1000))
        report = {}
        flags = ["--gestures", "--pinch", "--gesture-states", "--gesture-event-debug", "--no-smoothing",
                 "--gui-mode", "waitkey"]
        with patch.object(tracker.time, "perf_counter", side_effect=lambda: next(now)), \
                patch.object(cv2, "imshow"), patch.object(cv2, "waitKey", side_effect=[-1]*3+[ord("q")]), \
                patch.object(cv2, "getWindowProperty", return_value=1), \
                patch.object(tracker, "make_preview", wraps=make_preview) as preview, \
                patch.object(gesture_preview, "extract_features", wraps=gesture_preview.extract_features) as extract, \
                self.assertLogs(tracker.LOGGER) as logs:
            tracker.process_frames(cap, detector, mp, tracker.parse_args(flags), report)
        self.assertEqual(frames, before)
        self.assertEqual(extract.call_count, 8)
        self.assertEqual(report["gesture_states"]["event_counts"], {"GESTURE_STARTED:PINCH": 2, "GESTURE_ENDED:PINCH": 2})
        self.assertEqual(report["pinch"]["status_counts"], {"OPEN": 2, "STARTED": 2, "HELD": 2, "RELEASED": 2})
        for call in preview.call_args_list:
            self.assertEqual(len(call.kwargs["gesture_results"]), 2)
            self.assertEqual(len(call.kwargs["pinch_results"]), 2)
        self.assertTrue(any("Left | PINCH | GESTURE_STARTED" in message for message in logs.output))
        self.assertTrue(any("Right | PINCH | GESTURE_ENDED" in message for message in logs.output))

    def test_headless_pinch_states_exclude_warmup_and_keep_report(self):
        now = 0.0
        cap, detector = MagicMock(), MagicMock()
        frame = np.zeros((1080, 1920, 3), np.uint8)
        def read():
            nonlocal now
            now += .05
            return True, frame
        cap.read.side_effect = read
        detector.detect_for_video.return_value = as_result(pinch_hand(.8))
        mp = SimpleNamespace(Image=lambda **kw: kw["data"], ImageFormat=SimpleNamespace(SRGB=1))
        report = {}
        flags = ["--pinch", "--no-gestures", "--gesture-states", "--benchmark", "--headless",
                 "--warmup", ".1", "--duration", ".2"]
        with patch.object(tracker.time, "perf_counter", side_effect=lambda: now), \
                patch.object(cv2, "imshow") as display, patch.object(cv2, "pollKey") as pump, \
                patch.object(tracker, "classify_result") as static, self.assertLogs(tracker.LOGGER):
            tracker.process_frames(cap, detector, mp, tracker.parse_args(flags), report)
        display.assert_not_called()
        pump.assert_not_called()
        static.assert_not_called()
        self.assertLess(report["frames"], cap.read.call_count)
        self.assertEqual(report["timings"]["state_management"]["count"], report["frames"])
        self.assertEqual(report["gesture_states"]["state_counts"], {"IDLE": report["frames"]})

    def test_optional_transition_logs_distinguish_loss_and_release(self):
        item = gesture_preview.prepare_features(as_result(pinch_hand(.8)), 0, SIZE)
        manager = GestureStateManager(StateSettings(0))
        raw = gesture_preview.classify_result(as_result(pose_hand()), 0, SIZE, Profile())
        # Use matching feature metadata and any supported static rule for diagnostics.
        frame = manager.update(item, 0, raw)
        with self.assertLogs(tracker.LOGGER) as logs:
            tracker.log_state_events(frame.events)
            tracker.log_state_events(manager.update((), 1, ()).events)
        text = "\n".join(logs.output)
        self.assertIn("GESTURE_STARTED", text)
        self.assertIn("GESTURE_CANCELED", text)
        self.assertIn("tracking_lost (former association)", text)
        self.assertNotIn("GESTURE_ENDED", text)
        self.assertNotIn("array(", text)

    def test_compact_state_overlay_keeps_raw_static_pinch_and_black_background(self):
        raw = as_result(pose_hand())
        cached = []
        static = gesture_preview.classify_result(raw, 0, SIZE, Profile(), features_out=cached)
        frame = GestureStateManager(StateSettings(0)).update(tuple(cached), 0, static)
        image = np.full((1080, 1920, 3), 120, np.uint8)
        renderer = PreviewRenderer()
        with patch.object(cv2, "putText", wraps=cv2.putText) as texts, \
                patch.object(cv2, "rectangle", wraps=cv2.rectangle) as rectangles:
            preview = make_preview(image, raw, 36, False, renderer=renderer,
                                   gesture_results=static, gesture_states=frame.hands)
        labels = [call.args[1] for call in texts.call_args_list]
        self.assertIn("Left - OPEN_PALM", labels)
        self.assertTrue(any("ACTIVE | Confirmed: OPEN_PALM | Last: STARTED:OPEN_PALM" in label for label in labels))
        self.assertTrue(all(call.args[3] == (0, 0, 0) for call in rectangles.call_args_list))
        fresh = make_preview(image, as_result(), 36, False, renderer=renderer, gesture_states=())
        self.assertIs(preview, fresh)
        self.assertTrue(np.all(fresh[30:] == 120))
        self.assertTrue(np.all(image == 120))

    def test_render_candidate_and_no_state_when_disabled(self):
        raw = as_result(pose_hand())
        cached = []
        static = gesture_preview.classify_result(raw, 0, SIZE, Profile(), features_out=cached)
        states = GestureStateManager().update(tuple(cached), 0, static).hands
        image = np.zeros((1080, 1920, 3), np.uint8)
        with patch.object(cv2, "putText", wraps=cv2.putText) as texts:
            make_preview(image, raw, 36, True, gesture_results=static, gesture_states=states)
        self.assertTrue(any("CANDIDATE (OPEN_PALM)" in call.args[1] for call in texts.call_args_list))
        with patch.object(cv2, "putText", wraps=cv2.putText) as texts:
            make_preview(image, raw, 36, True, gesture_results=static)
        self.assertFalse(any("Confirmed:" in call.args[1] for call in texts.call_args_list))


if __name__ == "__main__":
    unittest.main()
