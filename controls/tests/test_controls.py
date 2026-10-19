from dataclasses import replace
import unittest

from controls.backends import SimulationBackend
from controls.controller import DesktopController
from controls.cursor import RelativeCursor
from controls.models import ControlSettings, Screen
from gestures.events import (PINCH, SWIPE_LEFT, SWIPE_RIGHT, EventMetadata, EventType as E,
                             GestureEvent, GestureState as S, HandState, StateFrame)
from gestures.features import extract_features
from gestures.models import HandSide as H, HandednessPrediction, ImageSize
from gestures.pinch import PinchMeasurement, PinchResult, PinchStatus as P
from gestures.static_gestures import Gesture as G
from gestures.tests.static_fixtures import pose_hand


def feature(side="Right", dx=0., offset=0.):
    hand = pose_hand(side=side)
    hand = replace(hand, landmarks=tuple(replace(p, x=p.x+dx+offset) for p in hand.landmarks))
    return extract_features(hand, image_size=ImageSize(1920, 1080))


class Harness:
    def __init__(self, **settings):
        self.now = 0.
        self.stamp = 0
        self.backend = SimulationBackend()
        self.controller = DesktopController(self.backend, ControlSettings(**settings), clock=lambda: self.now)

    def step(self, gesture=G.POINTING, pinch=P.OPEN, *, dx=0., events=(), features=None,
             state_reason="", candidate=None, event_side=H.RIGHT, stamp=None):
        self.stamp = self.stamp+33 if stamp is None else stamp
        self.now += .033
        items = tuple(features) if features is not None else (feature(dx=dx),)
        states = tuple(HandState(H(reliable_name(item)), S.ACTIVE if gesture else S.IDLE,
                                 gesture, candidate, reason=state_reason) for item in items)
        pinches = tuple(PinchResult(pinch, PinchMeasurement(.1 if pinch in (P.STARTED, P.HELD) else .8,
                                                           pinch != P.UNAVAILABLE, "test"),
                                   self.stamp, item.observation.handedness, "test") for item in items)
        made = tuple(GestureEvent(g, kind, self.stamp, event_side,
                                  S.ACTIVE if kind == E.GESTURE_STARTED else S.COOLDOWN,
                                  EventMetadata(reason)) for g, kind, reason in events)
        frame = StateFrame(self.stamp, states, made)
        self.controller.update(frame, items, pinches)
        return frame, items, pinches

    def arm(self):
        self.step()
        assert self.controller.arm()
        self.step()  # fresh open after manual arm

    def start(self):
        self.step(PINCH, P.STARTED, events=((PINCH, E.GESTURE_STARTED, "confirmed"),))


def reliable_name(item):
    return item.observation.handedness[0].category_name if item.observation.handedness else "Unknown"


class CursorTest(unittest.TestCase):
    def test_horizontal_inversion_reverses_delta_with_same_gain_and_vertical_motion(self):
        size = ImageSize(1920, 1080)
        for alpha in (1., .6):
            for dx in (-.02, .02):
                with self.subTest(alpha=alpha, dx=dx):
                    targets = []
                    for invert_x in (False, True):
                        cursor = RelativeCursor(ControlSettings(alpha=alpha, invert_x=invert_x), Screen())
                        self.assertIsNone(cursor.update((.5, .5), size, (960, 540)))
                        targets.append(cursor.update((.5+dx, .52), size, (0, 0)))
                    self.assertEqual(targets[0][0]-960, -(targets[1][0]-960))
                    self.assertEqual(targets[0][1], targets[1][1])
                    self.assertGreater(targets[0][1], 540)
                    self.assertGreater((targets[0][0]-960)*dx, 0)
                    self.assertLess((targets[1][0]-960)*dx, 0)

    def test_vertical_only_motion_unchanged_with_horizontal_inversion(self):
        for dy in (-.02, .02):
            targets = []
            for invert_x in (False, True):
                cursor = RelativeCursor(ControlSettings(invert_x=invert_x), Screen())
                cursor.update((.5, .5), ImageSize(1920, 1080), (960, 540))
                targets.append(cursor.update((.5, .5+dy), ImageSize(1920, 1080), (0, 0)))
            self.assertEqual(targets[0], targets[1])
            self.assertEqual(targets[0][0], 960)
            self.assertGreater((targets[0][1]-540)*dy, 0)

    def test_inversion_keeps_activation_reset_and_resolution_change_jump_free(self):
        cursor = RelativeCursor(ControlSettings(invert_x=True), Screen())
        size = ImageSize(1920, 1080)
        self.assertIsNone(cursor.update((.2, .3), size, (960, 540)))
        self.assertEqual(cursor.update((.2, .3), size, (0, 0)), (960, 540))
        cursor.reset()
        self.assertIsNone(cursor.update((.8, .7), size, (700, 300)))
        self.assertEqual(cursor.update((.8, .7), size, (0, 0)), (700, 300))
        self.assertIsNone(cursor.update((.1, .2), ImageSize(640, 480), (700, 300)))

    def test_activation_has_no_move_and_relative_displacement(self):
        c = RelativeCursor(ControlSettings(alpha=1., sensitivity=1.), Screen())
        size = ImageSize(1920, 1080)
        self.assertIsNone(c.update((.2, .3), size, (100, 200)))
        self.assertEqual(c.update((.3, .3), size, (0, 0)), (340, 200))

    def test_isotropic_gain_on_aspect_correct_axes(self):
        size = ImageSize(1920, 1080)
        c = RelativeCursor(ControlSettings(alpha=1., sensitivity=1.), Screen())
        c.update((.2, .2), size, (400, 400))
        x, y = c.update((.25, .2+.05*1920/1080), size, (0, 0))
        self.assertEqual(x-400, y-400)

    def test_equivalent_normalized_coordinates_across_resolutions(self):
        positions = []
        for size in (ImageSize(1920, 1080), ImageSize(960, 540), ImageSize(1280, 720)):
            c = RelativeCursor(ControlSettings(), Screen())
            c.update((.4, .4), size, (500, 500))
            positions.append(c.update((.42, .44), size, (0, 0)))
        self.assertEqual(len(set(positions)), 1)

    def test_camera_size_change_and_reset_reanchor_without_jump(self):
        c = RelativeCursor(ControlSettings(), Screen())
        c.update((.3, .4), ImageSize(1920, 1080), (500, 500))
        self.assertIsNone(c.update((.8, .7), ImageSize(640, 480), (500, 500)))
        c.reset()
        self.assertIsNone(c.update((.1, .2), ImageSize(640, 480), (200, 300)))

    def test_screen_space_smoothing_reduces_initial_delta(self):
        def move(alpha):
            c = RelativeCursor(ControlSettings(alpha=alpha), Screen())
            c.update((.4, .4), ImageSize(1920, 1080), (500, 500))
            return c.update((.42, .4), ImageSize(1920, 1080), (0, 0))[0]-500
        self.assertGreater(move(1.), move(.5))
        self.assertGreater(move(.5), 0)

    def test_clamping_and_no_edge_windup(self):
        c = RelativeCursor(ControlSettings(alpha=1.), Screen(left=-1000, top=-200, width=1000, height=600))
        size = ImageSize(1920, 1080)
        c.update((.2, .2), size, (-2, 0))
        self.assertEqual(c.update((1., .2), size, (0, 0))[0], -1)
        self.assertLess(c.update((.85, .2), size, (0, 0))[0], -1)

    def test_outside_selected_monitor_rejected_without_teleport(self):
        c = RelativeCursor(ControlSettings(), Screen(left=-1920))
        with self.assertRaisesRegex(ValueError, "selected monitor"):
            c.update((.5, .5), ImageSize(1920, 1080), (100, 100))

    def test_invalid_coordinates_and_screen_geometry(self):
        for point in ((float("nan"), .5), (.5, float("inf")), (1.01, .5), (-.1, .5)):
            with self.subTest(point=point), self.assertRaises(ValueError):
                RelativeCursor(ControlSettings(), Screen()).update(point, ImageSize(1920, 1080), (0, 0))
        for kw in ({"width": 0}, {"height": 1}, {"left": .5}, {"width": True}):
            with self.assertRaises(ValueError):
                Screen(**kw)

    def test_active_margin_clips_camera_edges(self):
        c = RelativeCursor(ControlSettings(margin=.2, alpha=1.), Screen())
        c.update((.1, .5), ImageSize(1920, 1080), (500, 500))
        self.assertEqual(c.update((0., .5), ImageSize(1920, 1080), (0, 0)), (500, 500))


class ControlTest(unittest.TestCase):
    def test_simulated_controller_respects_horizontal_inversion(self):
        for invert_x in (False, True):
            with self.subTest(invert_x=invert_x):
                h = Harness(invert_x=invert_x)
                h.arm()
                initial = h.backend.position
                self.assertEqual(h.backend.counts["move"], 0)
                h.step(dx=.02)
                change = h.backend.position[0]-initial[0]
                if invert_x:
                    self.assertLess(change, 0)
                else:
                    self.assertGreater(change, 0)
                self.assertEqual(h.backend.position[1], initial[1])

    def test_simulation_starts_disarmed_and_does_no_input(self):
        h = Harness(mouse=True, tabs=True)
        h.step()
        h.step(dx=.02)
        h.start()
        self.assertEqual(h.backend.counts, {})
        self.assertFalse(h.controller.armed)

    def test_live_starts_disarmed_requires_initialized_safety_and_explicit_arm(self):
        h = Harness()
        h.backend.is_live = True
        c = DesktopController(h.backend, ControlSettings(mode="live"), clock=lambda: h.now)
        frame, features, pinches = h.step()
        c.update(frame, features, pinches)
        self.assertFalse(c.armed)
        self.assertFalse(c.arm())
        c.safety_ready = True
        self.assertTrue(c.arm())
        self.assertEqual(h.backend.counts, {})

    def test_mode_cannot_silently_select_wrong_backend(self):
        with self.assertRaises(ValueError):
            DesktopController(SimulationBackend(), ControlSettings(mode="live"))

    def test_arm_requires_current_valid_hand(self):
        h = Harness()
        self.assertFalse(h.controller.arm())
        h.step()
        h.now += .3
        self.assertFalse(h.controller.arm())

    def test_arm_rejects_cursor_outside_selected_monitor_without_input(self):
        h = Harness()
        h.step()
        h.backend.position = (-100, 100)
        self.assertFalse(h.controller.arm())
        self.assertIn("selected monitor", h.controller.reason)
        self.assertEqual(h.backend.counts, {})

    def test_stale_event_in_new_frame_cannot_replay_click(self):
        h = Harness(mouse=True)
        h.arm()
        frame, items, pinches = h.step(PINCH, P.STARTED, events=((PINCH, E.GESTURE_STARTED, "confirmed"),))
        h.controller.disarm()
        h.controller.arm()
        h.step()  # fresh open; old event remains from before arm
        stale = frame.events
        current, items, pinches = h.step(PINCH, P.HELD)
        # Advance the frame clock, but preserve the obsolete event's timestamp.
        current = replace(current, timestamp_ms=current.timestamp_ms+33, events=stale)
        pinches = tuple(replace(p, timestamp_ms=current.timestamp_ms) for p in pinches)
        h.controller.update(current, items, pinches)
        self.assertEqual(h.backend.counts["down"], 1)
        self.assertFalse(h.backend.button_down)

    def test_pointing_moves_and_other_static_poses_do_not(self):
        h = Harness()
        h.arm()
        h.step(dx=.02)
        self.assertGreater(h.backend.counts["move"], 0)
        n = h.backend.counts["move"]
        for gesture in (G.FIST, None, G.OPEN_PALM):
            h.step(gesture, dx=.03)
        self.assertEqual(h.backend.counts["move"], n)

    def test_pending_static_replacement_stops_pointing_immediately(self):
        h = Harness()
        h.arm()
        h.step(dx=.02, candidate=G.FIST)
        self.assertEqual(h.backend.counts["move"], 0)

    def test_pointing_reactivation_anchors_existing_cursor(self):
        h = Harness()
        h.arm()
        h.step(dx=.01)
        h.step(G.FIST)
        n = h.backend.counts["move"]
        h.step(dx=.04)
        self.assertEqual(h.backend.counts["move"], n)

    def test_pinch_click_one_down_held_no_duplicate_one_up(self):
        h = Harness(mouse=True)
        h.arm()
        h.start()
        h.step(PINCH, P.HELD)
        h.step(PINCH, P.HELD)
        self.assertEqual(h.backend.counts["down"], 1)
        h.step(None, P.RELEASED, events=((PINCH, E.GESTURE_ENDED, "pinch_released"),))
        h.step(None)
        self.assertEqual(h.backend.counts["up"], 1)
        self.assertFalse(h.backend.button_down)

    def test_drag_continues_without_static_pointing(self):
        h = Harness(mouse=True)
        h.arm()
        h.start()
        h.step(PINCH, P.HELD, dx=.02)
        self.assertGreater(h.backend.counts["move"], 0)
        self.assertTrue(h.backend.button_down)
        self.assertEqual(h.controller.status().reason, "Dragging")

    def test_curl_to_pinch_anchors_no_jump(self):
        h = Harness(mouse=True)
        h.arm()
        n = h.backend.counts["move"]
        h.start()
        self.assertEqual(h.backend.counts["move"], n)

    def test_mouse_disabled_by_default(self):
        h = Harness()
        h.arm()
        h.start()
        h.step(PINCH, P.HELD, dx=.02)
        self.assertEqual(h.backend.counts["down"], 0)
        self.assertEqual(h.backend.counts["move"], 0)

    def test_held_on_arming_cannot_click_until_fresh_open_and_start(self):
        h = Harness(mouse=True)
        h.step(PINCH, P.HELD)
        self.assertTrue(h.controller.arm())
        h.start()
        self.assertEqual(h.backend.counts["down"], 0)
        h.step(None, P.RELEASED)
        h.start()
        self.assertEqual(h.backend.counts["down"], 1)

    def test_unrelated_events_and_missing_start_cannot_click(self):
        h = Harness(mouse=True)
        h.arm()
        h.step(None, P.HELD)
        h.step(G.FIST, events=((G.FIST, E.GESTURE_STARTED, "confirmed"),))
        self.assertEqual(h.backend.counts["down"], 0)

    def test_tracking_loss_releases_and_disarms_without_mutating_recognizer(self):
        h = Harness(mouse=True)
        h.arm()
        h.start()
        frame, _, _ = h.step(features=())
        self.assertEqual(frame.events, ())
        self.assertFalse(h.controller.armed)
        self.assertEqual(h.backend.counts["up"], 1)
        h.step(PINCH, P.HELD)
        self.assertEqual(h.backend.counts["down"], 1)

    def test_pinch_cancellation_forces_up(self):
        h = Harness(mouse=True)
        h.arm()
        h.start()
        h.step(None, events=((PINCH, E.GESTURE_CANCELED, "tracking_lost"),))
        self.assertFalse(h.backend.button_down)
        self.assertFalse(h.controller.armed)

    def test_manual_emergency_and_shutdown_release_owned_input(self):
        for stop in (lambda c: c.disarm(), lambda c: c.disarm("GLOBAL EMERGENCY STOP"), lambda c: c.close()):
            h = Harness(mouse=True)
            h.arm()
            h.start()
            stop(h.controller)
            self.assertFalse(h.backend.button_down)
            self.assertFalse(h.controller.armed)
            self.assertEqual(h.backend.counts["up"], 1)

    def test_watchdog_releases_even_without_a_new_camera_frame(self):
        h = Harness(mouse=True)
        h.arm()
        h.start()
        h.now += .501
        h.controller.check_timeout()
        self.assertFalse(h.backend.button_down)
        self.assertFalse(h.controller.armed)

    def test_long_frame_gap_disarms(self):
        h = Harness(mouse=True)
        h.arm()
        h.start()
        h.step(PINCH, P.HELD, stamp=h.stamp+251)
        self.assertFalse(h.backend.button_down)
        self.assertFalse(h.controller.armed)

    def test_backend_move_failure_latches_closed(self):
        h = Harness()
        h.arm()
        def fail(*_):
            raise OSError("fake")
        h.backend.move = fail
        with self.assertLogs("controls", level="ERROR"):
            h.step(dx=.02)
        self.assertFalse(h.controller.armed)
        self.assertFalse(h.controller.arm())

    def test_partial_down_failure_still_attempts_up(self):
        h = Harness(mouse=True)
        h.arm()
        original = h.backend.left_down
        def fail():
            original()
            raise OSError("partial down")
        h.backend.left_down = fail
        with self.assertLogs("controls", level="ERROR"):
            h.start()
        self.assertFalse(h.backend.button_down)
        self.assertEqual(h.backend.counts["up"], 1)

    def test_release_failure_retains_ownership_for_cleanup_retry(self):
        h = Harness(mouse=True)
        h.arm()
        h.start()
        original = h.backend.left_up
        def fail():
            raise OSError("release failed")
        h.backend.left_up = fail
        with self.assertLogs("controls", level="ERROR"):
            h.controller.disarm()
        self.assertTrue(h.controller.button_down)
        h.backend.left_up = original
        h.controller.close()
        self.assertFalse(h.backend.button_down)

    def test_confirmed_swipe_directions_map_to_one_shortcut(self):
        for gesture, expected in ((SWIPE_RIGHT, ("CTRL", "TAB")), (SWIPE_LEFT, ("CTRL", "SHIFT", "TAB"))):
            h = Harness(tabs=True)
            h.arm()
            frame, items, pinches = h.step(None, events=((gesture, E.GESTURE_STARTED, "swipe_confirmed"),
                                                        (gesture, E.GESTURE_ENDED, "swipe_confirmed")))
            self.assertEqual(h.backend.last_keys, expected)
            self.assertEqual(h.backend.counts["tab"], 1)
            h.controller.update(frame, items, pinches)  # Replay rejected, never another shortcut.
            self.assertEqual(h.backend.counts["tab"], 1)

    def test_tabs_disabled_candidates_and_cooldown_no_shortcuts(self):
        h = Harness()
        h.arm()
        h.step(None, events=((SWIPE_RIGHT, E.GESTURE_STARTED, "swipe_confirmed"),))
        self.assertEqual(h.backend.counts["tab"], 0)
        h = Harness(tabs=True)
        h.arm()
        h.step(None, candidate=SWIPE_RIGHT)
        h.step(None, events=((SWIPE_RIGHT, E.GESTURE_ENDED, "swipe_confirmed"),))
        self.assertEqual(h.backend.counts["tab"], 0)

    def test_unsupported_foreground_blocks_tabs_preserves_recognition(self):
        h = Harness(tabs=True)
        h.arm()
        h.backend.foreground = "notepad.exe"
        frame, _, _ = h.step(None, events=((SWIPE_RIGHT, E.GESTURE_STARTED, "confirmed"),))
        self.assertEqual(frame.events[0].gesture, SWIPE_RIGHT)
        self.assertEqual(h.backend.counts["tab"], 0)
        self.assertIn("Tab blocked", h.controller.reason)

    def test_non_controlling_hand_can_leave_without_stopping_selected_hand(self):
        h = Harness()
        h.step(features=(feature("Left", offset=-.23), feature("Right", offset=.23)))
        self.assertTrue(h.controller.arm())
        h.step(features=(feature("Right", offset=.23),))
        h.step(features=(feature("Right", dx=.01, offset=.23),))
        self.assertTrue(h.controller.armed)
        self.assertGreater(h.backend.counts["move"], 0)

    def test_pinch_and_drag_block_tab_actions(self):
        for mouse in (True, False):
            h = Harness(mouse=mouse, tabs=True)
            h.arm()
            h.start()
            h.step(PINCH, P.HELD, events=((SWIPE_RIGHT, E.GESTURE_STARTED, "confirmed"),))
            self.assertEqual(h.backend.counts["tab"], 0)

    def test_opposite_simultaneous_events_are_suppressed(self):
        h = Harness(tabs=True)
        h.arm()
        frame, items, pinches = h.step(None, events=((SWIPE_RIGHT, E.GESTURE_STARTED, "confirmed"),))
        other = GestureEvent(SWIPE_LEFT, E.GESTURE_STARTED, frame.timestamp_ms+33, H.LEFT, S.ACTIVE)
        selected = replace(frame.events[0], timestamp_ms=frame.timestamp_ms+33)
        frame = replace(frame, timestamp_ms=frame.timestamp_ms+33, events=(selected, other))
        pinches = tuple(replace(p, timestamp_ms=frame.timestamp_ms) for p in pinches)
        h.controller.update(frame, items, pinches)
        self.assertEqual(h.backend.counts["tab"], 1)  # Only the earlier non-conflicting test frame.
        self.assertIn("Conflicting", h.controller.reason)

    def test_other_hand_ignored_and_order_changes_keep_selected_hand(self):
        h = Harness(mouse=True, tabs=True)
        left, right = feature("Left", offset=-.23), feature("Right", offset=.23)
        h.step(features=(left, right))
        h.controller.arm()
        h.step(features=(right, left))
        h.step(features=(left, feature("Right", dx=.02, offset=.23)),
               events=((PINCH, E.GESTURE_STARTED, "confirmed"),), event_side=H.LEFT)
        self.assertTrue(h.controller.armed)
        self.assertGreater(h.backend.counts["move"], 0)
        self.assertEqual(h.backend.counts["down"], 0)

    def test_selected_disappearing_never_switches_to_other_hand(self):
        h = Harness(mouse=True)
        h.arm()
        h.start()
        h.step(features=(feature("Left"),))
        self.assertFalse(h.controller.armed)
        self.assertFalse(h.backend.button_down)

    def test_ambiguous_prediction_and_crossings_disarm(self):
        for items in ((feature("Right"), feature("Right")),
                      (feature("Left"), feature("Right")),
                      (replace(feature(), observation=replace(feature().observation,
                          handedness=(HandednessPrediction("Right", .5),))),)):
            h = Harness(mouse=True)
            h.arm()
            h.start()
            h.step(features=items)
            self.assertFalse(h.controller.armed)
            self.assertFalse(h.backend.button_down)

    def test_engine_association_failures_disarm_and_release(self):
        for reason in ("wrist_jump", "image_size_changed", "tracking_gap", "invalid_geometry_or_channel"):
            h = Harness(mouse=True)
            h.arm()
            h.start()
            h.step(PINCH, P.HELD, state_reason=reason)
            self.assertFalse(h.controller.armed)
            self.assertFalse(h.backend.button_down)

    def test_invalid_tip_and_unavailable_pinch_fail_closed(self):
        h = Harness(mouse=True)
        h.arm()
        h.start()
        item = feature()
        points = list(item.observation.landmarks)
        points[8] = replace(points[8], x=1.1)
        item = replace(item, observation=replace(item.observation, landmarks=tuple(points)))
        h.step(PINCH, P.HELD, features=(item,))
        self.assertFalse(h.backend.button_down)
        h = Harness()
        h.arm()
        h.step(None, P.UNAVAILABLE)
        self.assertFalse(h.controller.armed)

    def test_invalid_timestamp_rejects_input_and_watermark_never_regresses(self):
        h = Harness()
        h.arm()
        last = h.stamp
        for stamp in (last, last-1, -1):
            h.step(stamp=stamp)
            self.assertFalse(h.controller.armed)
            self.assertEqual(h.controller.last_stamp, last)

    def test_no_stale_event_after_manual_rearm(self):
        h = Harness(mouse=True)
        h.arm()
        frame, items, pinches = h.step(PINCH, P.STARTED, events=((PINCH, E.GESTURE_STARTED, "confirmed"),))
        h.controller.disarm()
        h.controller.arm()
        h.controller.update(frame, items, pinches)
        self.assertEqual(h.backend.counts["down"], 1)
        self.assertFalse(h.backend.button_down)

    def test_configuration_rejects_invalid_values(self):
        for kw in ({"alpha": 0}, {"alpha": float("nan")}, {"sensitivity": 0}, {"margin": .5},
                   {"monitor": -1}, {"mode": "auto"}, {"hand": H.UNKNOWN}, {"browsers": ()},
                   {"browsers": ("C:\\chrome.exe",)}, {"invert_x": 1}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                ControlSettings(**kw)


if __name__ == "__main__":
    unittest.main()
