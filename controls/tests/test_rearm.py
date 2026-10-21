"""Left pinch validation, lifecycle, identity refusal and trusted arming safety."""

from dataclasses import replace
import threading
import unittest
from unittest.mock import MagicMock, patch

from controls.models import ControlSettings
from controls.safety import GlobalSafety
from gestures.events import PINCH, SWIPE_RIGHT, EventMetadata, EventType as E, GestureEvent, GestureState as S
from gestures.models import HandednessPrediction, HandSide as H
from gestures.pinch import PinchStatus as P
from gestures.tests.test_swipe import sample_hand
from .rearm_fixtures import ControllerRun, ValidatorRun, feature, observation
from .test_windows import FakeAPI
from controls.windows import WindowsBackend


class RearmSequenceTest(unittest.TestCase):
    def test_complete_800_ms_hold_requires_release_and_emits_once(self):
        r = ValidatorRun()
        r.ready()
        r.held()
        self.assertEqual(r.validator.feedback, "RELEASE LEFT PINCH TO CONFIRM")
        self.assertTrue(r.step(P.RELEASED))
        self.assertFalse(r.step(P.RELEASED))
        self.assertFalse(r.step(P.HELD))

    def test_short_hold_and_release_fail(self):
        r = ValidatorRun()
        r.ready()
        r.held(700)
        self.assertFalse(r.step(P.RELEASED))
        self.assertEqual(r.validator.phase, "WAITING_FOR_OPEN")

    def test_release_time_does_not_count_as_an_extra_held_observation(self):
        r = ValidatorRun()
        r.ready()
        r.held(600)
        self.assertFalse(r.step(P.RELEASED, dt=250))

    def test_missing_open_or_already_pinched_entry_cannot_start(self):
        for first in (P.STARTED, P.HELD, P.RELEASED):
            r = ValidatorRun()
            for _ in range(8):
                self.assertFalse(r.step(first))
            self.assertFalse(r.step(P.RELEASED))
            self.assertEqual(r.validator.phase, "WAITING_FOR_OPEN")

    def test_no_release_never_confirms_even_after_many_held_frames(self):
        r = ValidatorRun()
        r.ready()
        r.held(3000)
        for _ in range(100):
            self.assertFalse(r.step(P.HELD))
        self.assertEqual(r.validator.phase, "HOLDING")

    def test_open_during_hold_cancels_and_requires_fresh_open(self):
        r = ValidatorRun()
        r.ready()
        r.held(800)
        self.assertFalse(r.step(P.OPEN))
        self.assertFalse(r.step(P.RELEASED))
        self.assertEqual(r.validator.phase, "WAITING_FOR_OPEN")

    def test_repeated_started_is_not_held(self):
        r = ValidatorRun()
        r.ready()
        r.held(300)
        self.assertFalse(r.step(P.STARTED))
        self.assertFalse(r.step(P.RELEASED))

    def test_missing_or_stale_manager_start_event_rejects(self):
        for events in ((), (GestureEvent(PINCH, E.GESTURE_STARTED, 0, H.LEFT, S.ACTIVE),)):
            r = ValidatorRun()
            r.ready()
            self.assertFalse(r.step(P.STARTED, events=events))
            self.assertEqual(r.validator.phase, "WAITING_FOR_OPEN")

    def test_missing_manager_release_event_rejects(self):
        r = ValidatorRun()
        r.ready()
        r.held()
        self.assertFalse(r.step(P.RELEASED, events=()))

    def test_pinches_unadmitted_by_state_manager_cannot_rearm(self):
        r = ValidatorRun()
        r.ready()
        frame, features, pinches = observation(r.stamp+100, P.STARTED)
        frame = replace(frame, hands=(replace(frame.hands[0], confirmed=None), frame.hands[1]))
        self.assertFalse(r.validator.update(frame, features, pinches))

    def test_variable_fps_uses_elapsed_time_and_exact_boundary(self):
        r = ValidatorRun()
        for dt in (50, 100, 150, 50):
            self.assertFalse(r.step(dt=dt))
        self.assertEqual(r.validator.phase, "READY_FOR_PINCH")
        self.assertFalse(r.step(P.STARTED, dt=40))
        for dt in (20, 180, 100, 200, 50, 250):  # Exactly 800 ms of continuous HELD.
            self.assertFalse(r.step(P.HELD, dt=dt))
        self.assertTrue(r.step(P.RELEASED, dt=33))

    def test_repeated_backward_and_long_gap_timestamps_cancel(self):
        for dt in (0, -1, 251, 1000):
            r = ValidatorRun()
            r.ready()
            r.held(800)
            watermark = r.stamp
            self.assertFalse(r.step(P.RELEASED, dt=dt))
            self.assertGreaterEqual(r.validator.last_stamp, watermark)
            self.assertEqual(r.validator.phase, "WAITING_FOR_OPEN")

    def test_invalid_timestamp_types_cancel(self):
        for stamp in (True, -1, 1.5, None):
            r = ValidatorRun()
            frame, features, pinches = observation(100)
            self.assertFalse(r.validator.update(replace(frame, timestamp_ms=stamp), features, pinches))

    def test_configured_hold_and_stability_intervals_apply(self):
        r = ValidatorRun(rearm_hold_ms=1000, rearm_stable_ms=500)
        r.ready()
        r.held(1000)
        self.assertTrue(r.step(P.RELEASED))


class RearmAssociationTest(unittest.TestCase):
    def reject_during_hold(self, modify):
        r = ValidatorRun()
        r.ready()
        r.held(800)
        data = observation(r.stamp+100, P.HELD)
        self.assertFalse(r.validator.update(*modify(*data)))
        self.assertEqual(r.validator.phase, "WAITING_FOR_OPEN")
        self.assertFalse(r.step(P.RELEASED, dt=200))

    def test_left_or_right_disappearance_cancels(self):
        for remaining in ((feature(),), (feature("Right"),), ()):
            self.reject_during_hold(lambda frame, feats, pinches: observation(frame.timestamp_ms, P.HELD, features=remaining))

    def test_confidence_missing_low_or_ambiguous_labels_cancel(self):
        for metadata in ((), (HandednessPrediction("Left", None),), (HandednessPrediction("Left", .89),),
                         (HandednessPrediction("Unknown", .99),),
                         (HandednessPrediction("Left", .99), HandednessPrediction("Right", .99))):
            bad = replace(feature(), observation=replace(feature().observation, handedness=metadata))
            self.reject_during_hold(lambda frame, feats, pinches: observation(frame.timestamp_ms, P.HELD,
                                                                             features=(bad, feature("Right"))))

    def test_right_hand_requires_same_high_confidence(self):
        bad = replace(feature("Right"), observation=replace(feature("Right").observation,
                      handedness=(HandednessPrediction("Right", .85),)))
        self.reject_during_hold(lambda frame, feats, pinches: observation(frame.timestamp_ms, P.HELD,
                                                                         features=(feature(), bad)))

    def test_duplicate_left_or_duplicate_right_labels_rejected(self):
        for pair in ((feature(), feature()), (feature("Right"), feature("Right"))):
            self.reject_during_hold(lambda frame, feats, pinches: observation(frame.timestamp_ms, P.HELD, features=pair))

    def test_same_observation_cannot_fill_both_roles(self):
        first = feature()
        relabeled = replace(first, observation=replace(first.observation, handedness=feature("Right").observation.handedness))
        self.reject_during_hold(lambda frame, feats, pinches: observation(frame.timestamp_ms, P.HELD,
                                                                         features=(first, relabeled)))

    def test_sudden_left_or_right_wrist_jump_rejected(self):
        for pair in ((feature(offset=-.05), feature("Right")), (feature(), feature("Right", offset=.4))):
            self.reject_during_hold(lambda frame, feats, pinches: observation(frame.timestamp_ms, P.HELD, features=pair))

    def test_time_based_continuity_rejects_small_but_implausibly_fast_jump(self):
        r = ValidatorRun()
        r.ready()
        data = observation(r.stamp+1, features=(feature(offset=-.18), feature("Right")))
        self.assertFalse(r.validator.update(*data))
        self.assertEqual(r.validator.phase, "WAITING_FOR_OPEN")

    def test_two_labels_swapping_positions_rejected(self):
        self.reject_during_hold(lambda frame, feats, pinches: observation(frame.timestamp_ms, P.HELD,
            features=(feature(offset=.22), feature("Right", offset=-.22))))

    def test_overlap_rejected(self):
        self.reject_during_hold(lambda frame, feats, pinches: observation(frame.timestamp_ms, P.HELD,
            features=(feature(offset=0), feature("Right", offset=0))))

    def test_detection_order_changes_preserve_validation(self):
        r = ValidatorRun()
        r.ready()
        r.held()
        self.assertTrue(r.step(P.RELEASED, features=(feature("Right"), feature())))

    def test_invalid_geometry_or_unavailable_pinch_cancels(self):
        for invalid in (float("nan"), 0.):
            self.reject_during_hold(lambda frame, feats, pinches:
                                    (frame, (replace(feats[0], palm_scale=invalid), feats[1]), pinches))
        self.reject_during_hold(lambda frame, feats, pinches:
                                (frame, feats, (replace(pinches[0], status=P.UNAVAILABLE), pinches[1])))
        self.reject_during_hold(lambda frame, feats, pinches:
                                (frame, feats, (replace(pinches[0], measurement=replace(pinches[0].measurement,
                                                                                     valid=False)), pinches[1])))

    def test_channel_timestamp_or_metadata_mismatch_cancels(self):
        self.reject_during_hold(lambda frame, feats, pinches:
                                (frame, feats, (replace(pinches[0], timestamp_ms=0), pinches[1])))
        self.reject_during_hold(lambda frame, feats, pinches:
                                (frame, feats, (replace(pinches[0], handedness=()), pinches[1])))

    def test_manager_cancellation_or_stale_association_cancels(self):
        for metadata in (EventMetadata(), EventMetadata(association_current=False)):
            self.reject_during_hold(lambda frame, feats, pinches: (replace(frame, events=(
                GestureEvent(PINCH, E.GESTURE_CANCELED, frame.timestamp_ms, H.LEFT, S.IDLE, metadata),)), feats, pinches))

    def test_safe_recovery_requires_new_stable_open_and_completed_sequence(self):
        r = ValidatorRun()
        r.ready()
        r.held()
        self.assertFalse(r.step(P.HELD, features=()))
        self.assertFalse(r.step(P.RELEASED))
        r.ready()
        r.held()
        self.assertTrue(r.step(P.RELEASED))


class RearmControllerTest(unittest.TestCase):
    def eligible(self, **settings):
        r = ControllerRun(**settings)
        r.initial_arm()
        r.routine_loss()
        self.assertTrue(r.controller._routine_rearm)
        return r

    def test_startup_left_sequence_cannot_arm(self):
        r = ControllerRun(mouse=True, tabs=True)
        for _ in range(5):
            r.step()
        for _ in range(10):
            r.step(left=.08)
        r.step()
        self.assertFalse(r.controller.armed)
        self.assertEqual(r.backend.counts, {})
        self.assertIn("MANUAL ARM REQUIRED", r.controller.status().rearm_status)

    def test_routine_loss_and_real_pinch_manager_pipeline_rearm_once_without_actions(self):
        r = self.eligible(mouse=True, tabs=True)
        before = dict(r.backend.counts)
        r.complete()
        self.assertTrue(r.controller.armed)
        self.assertEqual(dict(r.backend.counts), before)
        self.assertEqual(r.controller.status().rearm_status, "REARMED")
        self.assertEqual(r.controller.arm_after, r.stamp)
        self.assertFalse(r.controller.open_seen)
        self.assertIsNone(r.controller.cursor.previous)
        generation = r.controller._stop_generation
        for _ in range(12):
            r.step(left=.08)
        self.assertEqual(r.controller._stop_generation, generation)
        self.assertTrue(r.controller.armed)
        self.assertEqual(r.backend.counts["down"], 0)

    def test_short_pinch_does_not_rearm(self):
        r = self.eligible()
        r.ready()
        r.hold(600)
        r.step()
        self.assertFalse(r.controller.armed)

    def test_right_hand_pinch_cannot_rearm(self):
        r = self.eligible(mouse=True)
        r.ready()
        for _ in range(10):
            r.step(right=.08)
        r.step()
        self.assertFalse(r.controller.armed)
        self.assertEqual(r.backend.counts["down"], 0)

    def test_right_or_left_loss_during_hold_cancels(self):
        for missing in ("left", "right"):
            r = self.eligible()
            r.ready()
            r.hold()
            r.step(**{missing: None})
            r.step()
            self.assertFalse(r.controller.armed)
            r.complete()
            self.assertTrue(r.controller.armed)

    def test_order_changes_work_with_real_pinch_and_state_manager(self):
        r = self.eligible()
        r.ready(reverse=True)
        r.hold(reverse=True)
        r.step(reverse=True)
        self.assertTrue(r.controller.armed)

    def test_brief_right_to_left_label_change_is_not_a_rearm(self):
        r = self.eligible()
        relabeled = replace(feature("Right"), observation=replace(feature("Right").observation,
                            handedness=(HandednessPrediction("Left", .99),)))
        for _ in range(12):
            r.step(features=(relabeled,))
        self.assertFalse(r.controller.armed)
        r.complete()
        self.assertTrue(r.controller.armed)

    def test_manual_disarm_blocks_rearm_despite_later_routine_loss(self):
        r = self.eligible()
        r.controller.disarm()
        r.routine_loss()
        for _ in range(5):
            r.step()
        for _ in range(10):
            r.step(left=.08)
        r.step()
        self.assertFalse(r.controller.armed)
        self.assertFalse(r.controller._routine_rearm)
        self.assertTrue(r.controller.arm())  # A remains the explicit recovery path.
        r.routine_loss()
        r.complete()
        self.assertTrue(r.controller.armed)

    def test_global_emergency_blocks_gesture_rearm_until_manual_recovery(self):
        r = self.eligible()
        r.controller.disarm("GLOBAL EMERGENCY STOP; rearm manually")
        for _ in range(20):
            r.step(left=.08)
        r.step()
        self.assertFalse(r.controller.armed)
        self.assertFalse(r.controller._routine_rearm)
        self.assertTrue(r.controller.arm())

    def test_watchdog_and_invalid_timestamps_block_gesture_recovery(self):
        r = ControllerRun()
        r.initial_arm()
        r.now += .501
        r.controller.check_timeout()
        self.assertFalse(r.controller._routine_rearm)
        self.assertTrue(r.controller._hard_stopped)
        r = self.eligible()
        r.ready()
        frame, features, pinches = r.last
        r.controller.update(frame, features, pinches)  # Repeated timestamp is a hard invariant failure.
        self.assertTrue(r.controller._hard_stopped)
        self.assertFalse(r.controller._routine_rearm)

    def test_critical_manager_reason_takes_precedence_over_side_mismatch(self):
        for reason in ("invalid_time", "image_size_changed", "invalid_geometry_or_channel",
                       "conflicting_image_sizes", "invalid_channel_alignment"):
            with self.subTest(reason=reason):
                r = ControllerRun()
                r.initial_arm()
                r.stamp += 100
                r.now = r.stamp / 1000
                frame, features, pinches = observation(r.stamp)
                states = list(frame.hands)
                states[1] = replace(states[1], side=H.LEFT, reason=reason)
                r.controller.update(replace(frame, hands=tuple(states)), features, pinches)
                self.assertFalse(r.controller.armed)
                self.assertTrue(r.controller._hard_stopped)
                self.assertFalse(r.controller._can_gesture_rearm())
                for _ in range(5):
                    r.step()
                for _ in range(10):
                    r.step(left=.08)
                r.step()
                self.assertFalse(r.controller.armed)
                self.assertTrue(r.controller.arm())  # Healthy, explicit A recovery remains possible.

    def test_backend_failure_and_emergency_monitor_failure_never_gesture_rearm(self):
        r = self.eligible()
        r.ready()
        r.hold()
        r.backend.cursor_position = MagicMock(side_effect=OSError("fake backend failure"))
        r.step()
        self.assertFalse(r.controller.armed)
        self.assertTrue(r.controller.faulted)
        self.assertFalse(r.controller.arm())
        r = self.eligible()
        r.controller.safety_failure("Emergency monitor failed")
        self.assertFalse(r.controller._routine_rearm)
        self.assertFalse(r.controller.arm())

    def test_routine_loss_during_drag_releases_button_before_rearm(self):
        r = ControllerRun(mouse=True)
        r.initial_arm()
        r.step(right=.08)
        self.assertTrue(r.backend.button_down)
        r.routine_loss()
        self.assertFalse(r.backend.button_down)
        self.assertEqual(r.backend.counts["up"], 1)
        r.complete()
        self.assertTrue(r.controller.armed)
        self.assertEqual(r.backend.counts["down"], 1)

    def test_held_right_pinch_during_rearm_cannot_create_stale_down(self):
        r = self.eligible(mouse=True)
        # Closed reacquisition itself is unavailable until an OPEN is observed.
        for _ in range(5):
            r.step(right=.08)
        self.assertFalse(r.controller.armed)
        r.ready()
        r.step(right=.08)
        r.hold(right=.08)
        r.step(right=.08)
        self.assertTrue(r.controller.armed)
        for _ in range(5):
            r.step(right=.08)
        self.assertEqual(r.backend.counts["down"], 0)
        r.step()  # Fresh Right release/open after rearm.
        r.step(right=.08)
        self.assertEqual(r.backend.counts["down"], 1)

    def test_current_and_stale_right_swipes_not_replayed_after_rearm(self):
        r = self.eligible(mouse=True, tabs=True)
        r.ready()
        r.hold()
        event = GestureEvent(SWIPE_RIGHT, E.GESTURE_STARTED, r.stamp+100, H.RIGHT, S.ACTIVE)
        r.step(events=(event,))
        self.assertTrue(r.controller.armed)
        self.assertEqual(r.backend.counts["tab"], 0)
        r.step(events=(event,))
        self.assertEqual(r.backend.counts["tab"], 0)

    def test_normal_pointing_resumes_with_fresh_anchor_in_both_mappings(self):
        for mapping in ("relative", "absolute"):
            r = self.eligible(mapping=mapping)
            r.complete()
            before = r.backend.counts["move"]
            items = (feature(), sample_hand(pose="point", side="Right", offset=.22))
            r.step(features=items)
            r.step(features=items)
            self.assertEqual(r.backend.counts["move"], before)  # First active sample only anchors.
            for i in range(4):
                r.step(features=(feature(), sample_hand(dx=i*.1, pose="point", side="Right", offset=.22)))
            self.assertGreater(r.backend.counts["move"], before)

    def test_failed_release_latches_fault_and_cannot_gesture_rearm(self):
        r = ControllerRun(mouse=True)
        r.initial_arm()
        r.step(right=.08)
        r.backend.left_up = MagicMock(side_effect=OSError("fake release refused"))
        with self.assertLogs("controls", level="ERROR"):
            r.routine_loss()
        self.assertTrue(r.controller.faulted)
        self.assertFalse(r.controller._can_gesture_rearm())

    def test_delayed_rearm_request_cannot_override_newer_stop(self):
        r = self.eligible()
        token = r.controller._stop_generation
        r.controller.disarm("GLOBAL EMERGENCY STOP")
        self.assertFalse(r.controller._arm(gesture_generation=token))
        self.assertFalse(r.controller.armed)

    def test_stop_inside_gesture_arming_query_cannot_be_undone(self):
        r = self.eligible()
        r.ready()
        r.hold()
        original = r.backend.cursor_position
        def stop():
            r.controller.disarm("GLOBAL EMERGENCY STOP")
            return original()
        r.backend.cursor_position = stop
        r.step()
        self.assertFalse(r.controller.armed)
        self.assertTrue(r.controller._hard_stopped)

    def test_pending_emergency_during_gesture_arming_query_blocks_input(self):
        r = self.eligible()
        r.ready()
        r.hold()
        entered, resume = threading.Event(), threading.Event()
        original = r.backend.cursor_position
        def blocked():
            entered.set()
            if not resume.wait(2):
                raise TimeoutError("fake query timed out")
            return original()
        r.backend.cursor_position = blocked
        latched = threading.Event()
        original_set = r.controller._stop_requested.set
        def latch():
            original_set()
            latched.set()
        worker = threading.Thread(target=r.step)
        stop = threading.Thread(target=lambda: r.controller.disarm("GLOBAL EMERGENCY STOP"))
        try:
            with patch.object(r.controller._stop_requested, "set", side_effect=latch):
                worker.start()
                self.assertTrue(entered.wait(1))
                stop.start()
                self.assertTrue(latched.wait(1))
                resume.set()
                worker.join(2)
                stop.join(2)
        finally:
            resume.set()
            worker.join(2)
            if stop.ident is not None:
                stop.join(2)
        self.assertFalse(worker.is_alive())
        self.assertFalse(stop.is_alive())
        self.assertFalse(r.controller.armed)
        self.assertEqual(r.backend.counts["down"], 0)
        self.assertEqual(r.backend.counts["move"], 0)

    def test_live_policy_with_fake_windows_backend_uses_same_validation(self):
        r = ControllerRun(live=True, mouse=True, emergency_hotkey="ctrl+shift+f10")
        api = FakeAPI()
        r.backend = WindowsBackend(api=api)
        r.controller.backend = r.backend
        r.backend.input_allowed = r.controller._input_allowed
        monitor_api = MagicMock()
        monitor_api.stop_requested.return_value = False
        safety = GlobalSafety(r.controller, monitor_api).start()
        try:
            self.assertFalse(r.controller.armed)
            r.initial_arm()
            r.routine_loss()
            r.complete()
            self.assertTrue(r.controller.armed)
            self.assertEqual(api.sent, [])
        finally:
            safety.close()
        monitor_api.register_stop.assert_called_once_with("ctrl+shift+f10")

    def test_thousands_of_frames_keep_rearm_state_bounded(self):
        r = self.eligible()
        for _ in range(150):
            r.complete()
            self.assertTrue(r.controller.armed)
            r.routine_loss()
        self.assertLessEqual(len(vars(r.controller.rearm)), 11)
        self.assertLessEqual(len(r.pinch._history), 2)
        self.assertLessEqual(len(r.manager._tracks), 2)
        self.assertEqual(r.backend.counts["down"], 0)


if __name__ == "__main__":
    unittest.main()
