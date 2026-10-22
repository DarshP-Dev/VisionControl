"""Profile interpretation, real pose transitions and fake-input safety regressions."""

from dataclasses import replace
import math
import threading
import unittest
from unittest.mock import patch

from controls.interaction import PalmInteraction
from controls.models import ControlSettings, Screen
from controls.profiles import PROFILES
from gestures.events import PINCH, SWIPES, EventType as E, GestureState as S
from gestures.features import extract_features
from gestures.models import HandednessPrediction, HandSide as H, ImageSize
from gestures.motion import PALM_ANCHORS
from gestures.static_gestures import Gesture as G
from gestures.tests.static_fixtures import SIZE, pose_hand
from gestures.tests.test_swipe import sample_hand
from .profile_fixtures import ProfileRun
from .rearm_fixtures import feature


class ProfileGeometryTest(unittest.TestCase):
    def test_palm_anchor_is_exact_wrist_and_four_mcp_mean_in_normalized_image_axes(self):
        for size in (SIZE, ImageSize(640, 480), ImageSize(600, 1000)):
            for side in ("Left", "Right"):
                item = sample_hand(side=side, image_size=size)
                actual = PROFILES["palm-cursor"].anchor(item, 0)
                expected = tuple(sum(getattr(item.observation[i], axis) for i in PALM_ANCHORS) / 5
                                 for axis in ("x", "y"))
                for a, b in zip(actual, expected):
                    self.assertAlmostEqual(a, b)

    def test_finger_pose_changes_do_not_move_palm_anchor(self):
        anchors = [PROFILES["palm-cursor"].anchor(sample_hand(pose=pose), 0)
                   for pose in ("open", "point", "fist")]
        self.assertEqual(anchors[0], anchors[1])
        self.assertEqual(anchors[0], anchors[2])

    def test_legacy_anchor_remains_index_fingertip(self):
        item = sample_hand()
        self.assertEqual(PROFILES["legacy"].anchor(item, 0),
                         (item.observation[8].x, item.observation[8].y))
        self.assertEqual(ControlSettings().gesture_profile, "legacy")
        self.assertEqual(ControlSettings().cursor_resume, "automatic")

    def test_palm_anchor_maps_existing_80_percent_region_corners_without_geometry_changes(self):
        from controls.cursor import AbsoluteCursor
        cursor = AbsoluteCursor(ControlSettings(gesture_profile="palm-cursor", mapping="absolute"), Screen())
        item = sample_hand(scale=.015)
        base = PROFILES["palm-cursor"].anchor(item, 0)
        for x in (.1, .9):
            for y in (.1, .9):
                shifted = replace(item.observation, landmarks=tuple(
                    replace(p, x=p.x + x - base[0], y=p.y + y - base[1]) for p in item.observation.landmarks))
                anchor = PROFILES["palm-cursor"].anchor(extract_features(shifted, image_size=SIZE), 0)
                self.assertEqual(cursor.screen.clamp(*cursor.map_point(anchor, SIZE)),
                                 (1919 if x == .1 else 0, 0 if y == .1 else 1079))

    def test_invalid_individual_palm_coordinates_cannot_average_into_valid_anchor(self):
        item = sample_hand()
        for index in PALM_ANCHORS:
            points = list(item.observation.landmarks)
            points[index] = replace(points[index], x=1.01)
            invalid = replace(item, observation=replace(item.observation, landmarks=tuple(points)))
            with self.assertRaises(ValueError):
                PROFILES["palm-cursor"].anchor(invalid, 0)

    def test_profile_settings_reject_incompatible_hand_or_resume(self):
        for kwargs in ({"gesture_profile": "other"}, {"cursor_resume": "other"},
                       {"gesture_profile": "palm-cursor", "hand": H.LEFT},
                       {"cursor_resume": "left-pinch", "gesture_rearm": True},
                       {"gesture_profile": "palm-cursor", "cursor_resume": "left-pinch"}):
            with self.assertRaises(ValueError):
                ControlSettings(**kwargs)


class PalmCursorTest(unittest.TestCase):
    def test_open_palm_moves_in_both_mapping_modes_and_both_inversion_settings(self):
        for mapping in ("absolute", "relative"):
            for invert in (False, True):
                r = ProfileRun(mapping=mapping, invert_x=invert)
                r.arm()
                r.ready()  # settle initial absolute reacquisition
                before = r.backend.position
                r.step(dx=.2)
                self.assertNotEqual(r.backend.position, before)
                self.assertEqual(r.controller.cursor.previous is None, False)

    def test_fingertip_movement_alone_does_not_move_cursor(self):
        r = ProfileRun(alpha=1.)
        r.arm()
        r.ready()
        before = r.backend.position
        items = r.features()
        points = list(items[1].observation.landmarks)
        for index in (6, 7, 8):
            points[index] = replace(points[index], x=points[index].x + .003)
        changed = extract_features(replace(items[1].observation, landmarks=tuple(points)), image_size=SIZE)
        r.step(features=(items[0], changed))
        self.assertEqual(r.backend.position, before)
        self.assertTrue(r.controller.interaction.active)

    def test_pointing_pauses_on_first_pending_frame_without_system_disarm(self):
        r = ProfileRun()
        r.arm()
        before = r.backend.counts["move"]
        frame = r.step("point", dx=.3)
        self.assertEqual(frame.hands[1].candidate, G.POINTING)
        self.assertEqual(r.backend.counts["move"], before)
        self.assertTrue(r.controller.armed)

    def test_fist_and_unknown_cancel_cursor_without_movement(self):
        for pose in ("fist", "unknown"):
            r = ProfileRun()
            r.arm()
            before = r.backend.counts["move"]
            items = r.features("fist")
            if pose == "unknown":
                from gestures.models import Finger
                unknown = pose_hand(curled=(Finger.RING, Finger.PINKY), side="Right", scale=.04)
                unknown = replace(unknown, landmarks=tuple(replace(p, x=p.x + .22) for p in unknown.landmarks))
                items = (items[0], extract_features(unknown, image_size=SIZE))
            for _ in range(5):
                r.step(features=items)
            self.assertEqual(r.backend.counts["move"], before)
            self.assertFalse(r.controller.interaction.active)

    def test_valid_pinch_drags_palm_without_open_palm_and_one_down_up(self):
        for mode in ("simulate", "live"):
            r = ProfileRun(mouse=True, mode=mode)
            r.arm()
            before = r.backend.position
            r.step(right=.08)
            self.assertEqual(r.backend.position, before)
            self.assertEqual(r.backend.counts["down"], 1)
            self.assertIsNotNone(r.controller.cursor.drag_offset)
            for dx in (.2, .4, .6):
                frame = r.step(right=.08, dx=dx)
                self.assertEqual(frame.hands[1].confirmed, PINCH)
            self.assertNotEqual(r.backend.position, before)
            self.assertEqual(r.backend.counts["down"], 1)
            r.step(dx=.6)
            self.assertEqual(r.backend.counts["up"], 1)
            r.step(dx=.6)
            self.assertEqual(r.backend.counts["up"], 1)

    def test_cursor_only_pinch_keeps_tracking_without_sending_mouse_buttons(self):
        r = ProfileRun(mouse=False)
        r.arm()
        before = r.backend.position
        r.step(right=.08)
        r.step(right=.08, dx=.4)
        self.assertNotEqual(r.backend.position, before)
        self.assertEqual(r.backend.counts["down"], 0)

    def test_pinch_cannot_acquire_cursor_before_open_palm(self):
        r = ProfileRun(mouse=True)
        r.step(right=.8)  # valid pinch OPEN, but unsupported static geometry
        self.assertTrue(r.controller.arm())
        r.step(right=.8)
        r.step(right=.08)
        r.step(right=.08, dx=.3)
        self.assertEqual(r.backend.counts["down"], 0)
        self.assertEqual(r.backend.counts["move"], 0)

    def test_gradual_pinch_approach_stops_unknown_motion_then_admits_fresh_start(self):
        r = ProfileRun(mouse=True)
        r.arm()
        before = r.backend.counts["move"]
        r.step(right=.5, dx=.1)
        r.step(right=.3, dx=.2)
        self.assertFalse(r.controller.interaction.active)
        self.assertEqual(r.backend.counts["move"], before)
        r.step(right=.08, dx=.2)
        self.assertEqual(r.backend.counts["down"], 1)
        r.step(right=.08, dx=.4)
        self.assertGreater(r.backend.counts["move"], before)

    def test_unknown_approach_admission_expires_and_fist_revokes_it_immediately(self):
        for pose in ("unknown", "fist"):
            r = ProfileRun(mouse=True)
            r.arm()
            if pose == "unknown":
                for _ in range(6):
                    r.step(right=.5)
            else:
                r.step("fist")
            before = r.backend.counts["move"]
            r.step(right=.08)
            self.assertEqual(r.backend.counts["down"], 0)
            self.assertEqual(r.backend.counts["move"], before)

    def test_drag_precedence_suppresses_injected_swipe_events(self):
        from gestures.events import GestureEvent, SWIPE_RIGHT
        r = ProfileRun(mouse=True, tabs=True)
        r.arm()
        r.step(right=.08)
        frame = r.step(right=.08, dx=.2)
        event = GestureEvent(SWIPE_RIGHT, E.GESTURE_STARTED, r.stamp + 50, H.RIGHT, S.ACTIVE)
        # Preserve an admitted HELD pinch in an aligned synthetic event frame.
        r.stamp += 50
        pinches = tuple(replace(p, timestamp_ms=r.stamp) for p in r.last[2])
        r.controller.update(replace(frame, timestamp_ms=r.stamp, events=(event,)), r.last[1], pinches)
        self.assertTrue(r.controller.button_down)
        self.assertEqual(r.backend.counts["tab"], 0)


class AutomaticResumeTest(unittest.TestCase):
    def test_stable_open_palm_resumes_without_waiting_swipe_cooldown(self):
        r = ProfileRun()
        r.arm()
        r.pause()
        before = r.backend.counts["move"]
        r.step()
        self.assertEqual(r.backend.counts["move"], before)
        r.step(dt=100)
        r.step()
        self.assertTrue(r.controller.interaction.active)
        self.assertTrue(r.controller.armed)

    def test_brief_open_flicker_does_not_resume(self):
        r = ProfileRun()
        r.arm()
        r.pause()
        before = r.backend.counts["move"]
        r.step()
        r.step("point")
        self.assertEqual(r.backend.counts["move"], before)
        self.assertFalse(r.controller.interaction.active)

    def test_swipe_candidate_blocks_even_a_confirmed_open_palm_snapshot(self):
        from gestures.swipe import SwipeObservation
        from gestures.events import HandState
        interaction = PalmInteraction(ControlSettings(gesture_profile="palm-cursor"), Screen())
        state = HandState(H.RIGHT, S.ACTIVE, G.OPEN_PALM)
        motion = SwipeObservation(0, S.CANDIDATE)
        self.assertFalse(interaction.observe(state, motion, False, 0))
        self.assertTrue(interaction.paused)

    def test_large_absolute_mismatch_is_bounded_then_reaches_unmodified_mapping(self):
        r = ProfileRun(alpha=1.)
        r.arm()
        r.ready()
        r.pause()
        # Return translated, preserving current association continuity.
        for dx in (1., 2., 3.):
            r.step("point", dx=dx)
        before = r.backend.position
        maximum_step = math.hypot(1919, 1079) * 50 / 600 + 2
        previous = before
        positions = []
        for _ in range(25):
            r.step(dx=3.)
            positions.append(r.backend.position)
            self.assertLessEqual(math.dist(previous, r.backend.position), maximum_step)
            previous = r.backend.position
        self.assertNotEqual(positions[-1], before)
        anchor = PROFILES["palm-cursor"].anchor(r.last[1][1], r.stamp)
        self.assertEqual(positions[-1], r.backend.screen.clamp(*r.controller.cursor.map_point(anchor, SIZE)))
        self.assertEqual(r.controller.interaction.label, "ACTIVE")


class PointingSwipeTest(unittest.TestCase):
    def run_swipe(self, direction=1, **kwargs):
        r = ProfileRun(tabs=True, **kwargs)
        r.arm()
        for _ in range(8):
            r.step("point")
        before = r.backend.counts["move"]
        frames = [r.step("point", dx=direction * dx) for dx in (.4, .8, 1.2, 1.6, 2.)]
        return r, frames, before

    def test_pointing_uses_palm_trajectory_and_preserves_both_tab_directions(self):
        for direction in (-1, 1):
            r, frames, before = self.run_swipe(direction)
            events = [e for frame in frames for e in frame.events
                      if e.gesture in SWIPES and e.event_type == E.GESTURE_STARTED]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].gesture, "SWIPE_LEFT" if direction == -1 else "SWIPE_RIGHT")
            self.assertEqual(r.backend.counts["tab"], 1)
            self.assertEqual(r.backend.last_keys, ("CTRL", "SHIFT", "TAB") if direction == -1 else ("CTRL", "TAB"))
            self.assertEqual(r.backend.counts["move"], before)
            self.assertTrue(r.controller.armed)

    def test_open_palm_return_does_not_generate_reverse_swipe_or_wait_full_cooldown(self):
        r, _, _ = self.run_swipe()
        confirmation = r.stamp
        for dx in (1.6, 1.2, .8, .4, 0):
            r.step(dx=dx)
        self.assertEqual(r.backend.counts["tab"], 1)
        self.assertTrue(r.controller.interaction.active)
        self.assertLess(r.stamp - confirmation, 800)
        # Keep POINTING through cooldown without the stationary reset: no repeat.
        for i in range(15):
            r.step("point", dx=(i % 5) * .3)
        self.assertEqual(r.backend.counts["tab"], 1)

    def test_neutral_pose_cooldown_and_stationary_pointing_rearm_next_swipe(self):
        r, _, _ = self.run_swipe()
        for dx in (1.6, 1.2, .8, .4, 0):
            r.step(dx=dx)
        r.ready()
        for _ in range(25):
            r.step("point")
        for dx in (.4, .8, 1.2, 1.6, 2.):
            r.step("point", dx=dx)
        self.assertEqual(r.backend.counts["tab"], 2)

    def test_open_palm_moves_but_cannot_swipe_in_palm_profile(self):
        r = ProfileRun(tabs=True)
        r.arm()
        for dx in [0] * 8 + [.4, .8, 1.2, 1.6, 2.]:
            r.step(dx=dx)
        self.assertEqual(r.backend.counts["tab"], 0)
        self.assertGreater(r.backend.counts["move"], 0)

    def test_index_tip_displacement_cannot_create_swipe_trajectory(self):
        r = ProfileRun(tabs=True)
        r.arm()
        for _ in range(8):
            r.step("point")
        base = r.features("point")
        for dx in (.002, .004, .006, .008, .010):
            points = list(base[1].observation.landmarks)
            for index in (6, 7, 8):
                points[index] = replace(points[index], x=points[index].x + dx)
            changed = extract_features(replace(base[1].observation, landmarks=tuple(points)), image_size=SIZE)
            r.step(features=(base[0], changed))
        self.assertEqual(r.backend.counts["tab"], 0)

    def test_opposing_two_hand_pointing_swipes_are_suppressed(self):
        r = ProfileRun(tabs=True)
        r.arm()
        def pair(dx):
            return (sample_hand(-dx, pose="point", side="Left", offset=-.22),
                    sample_hand(dx, pose="point", side="Right", offset=.22))
        for _ in range(8):
            r.step(features=pair(0))
        for dx in (.4, .8, 1.2, 1.6, 2.):
            r.step(features=pair(dx))
        self.assertEqual(r.backend.counts["tab"], 0)

    def test_unknown_interrupts_and_invalidates_a_swipe_candidate(self):
        from gestures.models import Finger
        r = ProfileRun(tabs=True)
        r.arm()
        for _ in range(8):
            r.step("point")
        r.step("point", dx=.4)
        unknown = pose_hand(curled=(Finger.RING, Finger.PINKY), side="Right", scale=.04)
        unknown = replace(unknown, landmarks=tuple(replace(p, x=p.x + .22) for p in unknown.landmarks))
        r.step(features=(feature(), extract_features(unknown, image_size=SIZE)))
        frame = r.step("point", dx=.8)
        self.assertNotEqual(frame.motion[1].state, S.CANDIDATE)
        self.assertEqual(r.backend.counts["tab"], 0)


class ManualResumeTest(unittest.TestCase):
    def paused(self, **kwargs):
        r = ProfileRun(cursor_resume="left-pinch", gesture_rearm=True, **kwargs)
        r.arm()
        r.pause()
        r.ready()
        self.assertTrue(r.controller.interaction.paused)
        return r

    def test_full_sequence_resumes_once_without_confirmation_input_or_system_rearm(self):
        r = self.paused(mouse=True, tabs=True)
        before = dict(r.backend.counts)
        generation, arm_after = r.controller._stop_generation, r.controller.arm_after
        r.hold()
        r.step(dt=100)
        self.assertTrue(r.controller.armed)
        self.assertFalse(r.controller.interaction.paused)
        self.assertEqual(dict(r.backend.counts), before)
        self.assertEqual(r.controller._stop_generation, generation)
        self.assertEqual(r.controller.arm_after, arm_after)
        self.assertIsNone(r.controller.cursor.previous)
        r.step()  # fresh acquisition also sends no movement
        self.assertEqual(dict(r.backend.counts), before)
        r.step()
        self.assertTrue(r.controller.interaction.active)

    def test_short_hold_or_missing_release_cannot_resume(self):
        for duration, release in ((700, True), (1000, False)):
            r = self.paused(mouse=True)
            before = dict(r.backend.counts)
            r.hold(duration)
            if release:
                r.step(dt=100)
            self.assertTrue(r.controller.interaction.paused)
            self.assertEqual(dict(r.backend.counts), before)

    def test_missing_fresh_left_open_cannot_resume(self):
        r = ProfileRun(cursor_resume="left-pinch", gesture_rearm=True)
        r.arm()
        # Start the left pinch while cursor is still active; it cannot become
        # a fresh command later when POINTING pauses the cursor.
        r.step(left=.08)
        for _ in range(4):
            r.step("point", left=.08, dt=100)
        for _ in range(12):
            r.step(left=.08, dt=100)
        r.step()
        self.assertTrue(r.controller.interaction.paused)

    def test_right_pinch_never_resumes_or_clicks_while_paused(self):
        r = self.paused(mouse=True)
        before = dict(r.backend.counts)
        for _ in range(12):
            r.step(right=.08, dt=100)
        r.step(right=.8)
        self.assertTrue(r.controller.interaction.paused)
        self.assertEqual(dict(r.backend.counts), before)

    def test_left_hand_loss_cancels_attempt_then_fresh_sequence_required(self):
        r = self.paused()
        r.hold()
        r.step(left=None)
        self.assertTrue(r.controller.armed)
        self.assertTrue(r.controller.interaction.paused)
        r.step()
        self.assertTrue(r.controller.interaction.paused)
        r.complete()
        self.assertFalse(r.controller.interaction.paused)

    def test_low_confidence_left_cancels_attempt_without_identity_transfer(self):
        r = self.paused()
        r.hold()
        items = r.features()
        left = replace(items[0], observation=replace(items[0].observation,
                       handedness=(HandednessPrediction("Left", .85),)))
        r.step(features=(left, items[1]))
        self.assertTrue(r.controller.interaction.paused)
        self.assertEqual(r.controller.rearm.phase, "WAITING_FOR_OPEN")

    def test_detection_reordering_does_not_change_resume_hand(self):
        r = self.paused()
        r.ready(reverse=True)
        r.hold(reverse=True)
        r.step(reverse=True)
        self.assertFalse(r.controller.interaction.paused)

    def test_left_pinch_while_active_does_not_reset_cursor(self):
        r = ProfileRun(cursor_resume="left-pinch", gesture_rearm=True)
        r.arm()
        with patch.object(r.controller.cursor, "reset", wraps=r.controller.cursor.reset) as reset:
            r.complete()
        reset.assert_not_called()
        self.assertTrue(r.controller.interaction.active)

    def test_brief_pending_pointing_flicker_does_not_latch_manual_pause(self):
        r = ProfileRun(cursor_resume="left-pinch", gesture_rearm=True)
        r.arm()
        r.step("point")
        self.assertFalse(r.controller.interaction.active)
        self.assertFalse(r.controller.interaction.paused)
        r.step()
        self.assertTrue(r.controller.interaction.active)

    def test_completed_left_command_requires_stable_right_open_on_release(self):
        r = self.paused()
        r.hold(pose="point")
        r.step("point")
        self.assertTrue(r.controller.interaction.paused)
        r.ready()
        self.assertTrue(r.controller.interaction.paused)
        r.complete()
        self.assertFalse(r.controller.interaction.paused)

    def test_keyboard_a_fallback_resumes_only_with_stable_open_and_sends_no_input(self):
        r = self.paused()
        before = dict(r.backend.counts)
        self.assertTrue(r.controller.arm())
        self.assertFalse(r.controller.interaction.paused)
        self.assertEqual(dict(r.backend.counts), before)
        r.pause()
        self.assertFalse(r.controller.arm())

    def test_routine_tracking_loss_uses_same_validator_for_system_rearm_only(self):
        r = self.paused(mouse=True)
        r.step(features=())
        self.assertFalse(r.controller.armed)
        before = dict(r.backend.counts)
        r.complete()
        self.assertTrue(r.controller.armed)
        self.assertFalse(r.controller.interaction.active)
        self.assertFalse(r.controller.interaction.paused)
        self.assertEqual(dict(r.backend.counts), before)

    def test_manual_disarm_emergency_watchdog_and_backend_fault_block_left_recovery(self):
        for stop in ("manual", "emergency", "watchdog", "backend"):
            r = self.paused(mouse=True)
            if stop == "watchdog":
                r.stamp += 501
                r.controller.check_timeout()
            elif stop == "backend":
                r.controller.safety_failure("Input backend unavailable")
            else:
                r.controller.disarm("Manual disarm" if stop == "manual" else "GLOBAL EMERGENCY STOP")
            before = dict(r.backend.counts)
            r.complete()
            self.assertFalse(r.controller.armed)
            self.assertFalse(r.controller.interaction.active)
            self.assertEqual(dict(r.backend.counts), before)

    def test_newer_stop_generation_overrides_a_completed_resume_request(self):
        r = self.paused()
        r.hold()
        original = r.controller.rearm.update
        def stop_after_validation(*args):
            result = original(*args)
            self.assertTrue(result)
            r.controller.disarm("GLOBAL EMERGENCY STOP")
            return result
        before = dict(r.backend.counts)
        with patch.object(r.controller.rearm, "update", side_effect=stop_after_validation):
            r.step()
        self.assertFalse(r.controller.armed)
        self.assertFalse(r.controller.interaction.active)
        self.assertEqual(dict(r.backend.counts), before)
        self.assertEqual(r.controller.reason, "GLOBAL EMERGENCY STOP")

    def test_right_hand_loss_cancels_pending_resume_and_stale_release_does_not_arm(self):
        r = self.paused()
        r.hold()
        r.step(features=(feature(ratio=.08),))
        self.assertFalse(r.controller.armed)
        r.step()
        self.assertFalse(r.controller.armed)
        self.assertFalse(r.controller.interaction.active)

    def test_pending_emergency_during_validator_completion_prevents_resume(self):
        r = self.paused()
        r.hold()
        entered, release = threading.Event(), threading.Event()
        original = r.controller.rearm.update
        def blocked(*args):
            result = original(*args)
            entered.set()
            if not release.wait(2):
                raise TimeoutError("fake validator timed out")
            return result
        worker = threading.Thread(target=r.step)
        stop = threading.Thread(target=lambda: r.controller.disarm("GLOBAL EMERGENCY STOP"))
        try:
            with patch.object(r.controller.rearm, "update", side_effect=blocked):
                worker.start()
                self.assertTrue(entered.wait(1))
                stop.start()
                self.assertTrue(r.controller._stop_requested.wait(1))
                release.set()
                worker.join(2)
                stop.join(2)
        finally:
            release.set()
            worker.join(2)
            if stop.ident is not None:
                stop.join(2)
        self.assertFalse(worker.is_alive())
        self.assertFalse(stop.is_alive())
        self.assertFalse(r.controller.armed)
        self.assertFalse(r.controller.interaction.active)


class PalmSafetyTest(unittest.TestCase):
    def test_startup_sequence_cannot_arm_or_acquire_cursor(self):
        r = ProfileRun(cursor_resume="left-pinch", gesture_rearm=True, mouse=True)
        r.complete()
        self.assertFalse(r.controller.armed)
        self.assertFalse(r.controller.interaction.active)
        self.assertEqual(dict(r.backend.counts), {})

    def test_partial_down_backend_failure_releases_and_blocks_gesture_recovery(self):
        r = ProfileRun(mouse=True, gesture_rearm=True)
        r.arm()
        original = r.backend.left_down
        def failure():
            original()
            raise OSError("fake partial delivery")
        with patch.object(r.backend, "left_down", side_effect=failure), self.assertLogs("controls", level="ERROR"):
            r.step(right=.08)
        self.assertFalse(r.controller.armed)
        self.assertTrue(r.controller.faulted)
        self.assertFalse(r.backend.button_down)
        self.assertEqual(r.backend.counts["up"], 1)
        before = dict(r.backend.counts)
        r.complete()
        self.assertEqual(dict(r.backend.counts), before)

    def test_emergency_inside_automatic_reacquisition_query_blocks_move(self):
        r = ProfileRun()
        r.arm()
        r.pause()
        original = r.backend.cursor_position
        def stop():
            r.controller.disarm("GLOBAL EMERGENCY STOP")
            return original()
        before = dict(r.backend.counts)
        with patch.object(r.backend, "cursor_position", side_effect=stop):
            r.ready()
        self.assertFalse(r.controller.armed)
        self.assertFalse(r.controller.interaction.active)
        self.assertEqual(dict(r.backend.counts), before)
    def test_loss_disarm_and_emergency_release_owned_drag(self):
        for stop in ("loss", "manual", "emergency", "watchdog", "backend"):
            r = ProfileRun(mouse=True, gesture_rearm=True)
            r.arm()
            r.step(right=.08)
            self.assertTrue(r.controller.button_down)
            if stop == "loss":
                r.step(features=())
            elif stop == "watchdog":
                r.stamp += 501
                r.controller.check_timeout()
            elif stop == "backend":
                r.controller.safety_failure("Input backend unsafe")
            else:
                r.controller.disarm(stop)
            self.assertFalse(r.controller.armed)
            self.assertFalse(r.controller.button_down)
            self.assertEqual(r.backend.counts["up"], 1)
            self.assertIsNone(r.controller.cursor.drag_offset)
            self.assertFalse(r.controller.interaction.active)

    def test_duplicate_side_overlap_or_wrist_jump_disarms_without_transfer(self):
        for kind in ("duplicate", "overlap", "jump"):
            r = ProfileRun()
            r.arm()
            if kind == "duplicate":
                items = (feature("Right", offset=-.22), sample_hand(side="Right", offset=.22))
            elif kind == "overlap":
                items = (sample_hand(side="Left"), sample_hand(side="Right"))
            else:
                items = r.features(dx=3.)
            before = r.backend.counts["move"]
            r.step(features=items)
            self.assertFalse(r.controller.armed)
            self.assertEqual(r.backend.counts["move"], before)

    def test_invalid_palm_anchor_fails_closed_before_input(self):
        r = ProfileRun()
        r.arm()
        items = r.features()
        points = list(items[1].observation.landmarks)
        points[13] = replace(points[13], x=1.01)
        invalid = replace(items[1], observation=replace(items[1].observation, landmarks=tuple(points)))
        before = r.backend.counts["move"]
        r.step(features=(items[0], invalid))
        self.assertFalse(r.controller.armed)
        self.assertEqual(r.backend.counts["move"], before)

    def test_relative_palm_drag_retains_safe_acquisition_and_cleanup(self):
        r = ProfileRun(mapping="relative", mouse=True)
        r.arm()
        before = r.backend.position
        r.step(right=.08)
        self.assertEqual(r.backend.position, before)
        r.step(right=.08, dx=.4)
        self.assertNotEqual(r.backend.position, before)
        r.step()
        self.assertEqual(r.backend.counts["down"], 1)
        self.assertEqual(r.backend.counts["up"], 1)


if __name__ == "__main__":
    unittest.main()
