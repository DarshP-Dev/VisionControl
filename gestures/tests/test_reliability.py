"""Variable timing and thousands of mixed frames using the real event pipeline."""

from dataclasses import replace
import unittest

from controls.backends import SimulationBackend
from controls.controller import DesktopController
from controls.models import ControlSettings
from gestures.events import PINCH, SWIPES, EventType as E
from gestures.features import extract_features
from gestures.pinch import PinchTracker
from gestures.state_machine import GestureStateManager
from gestures.static_gestures import Gesture as G, classify_hand
from gestures.swipe import MAX_SAMPLES, SwipeSettings
from .pinch_fixtures import pinch_hand
from .static_fixtures import SIZE
from .test_swipe import Run, sample_hand


class MixedRig:
    def __init__(self, mapping="relative"):
        self.stamp = 0
        self.pinch = PinchTracker()
        self.manager = GestureStateManager(swipe_settings=SwipeSettings())
        self.backend = SimulationBackend()
        self.controller = DesktopController(self.backend, ControlSettings(mouse=True, tabs=True, mapping=mapping),
                                            clock=lambda: self.stamp/1000)

    def update(self, features, delta=33, static=None):
        self.stamp += delta
        pinches = self.pinch.update(features, self.stamp)
        static = static if static is not None else tuple(classify_hand(item, self.stamp) for item in features)
        state = self.manager.update(features, self.stamp, static, pinches)
        self.controller.update(state, features, pinches)
        return state

    def close(self):
        self.controller.close()
        return self.manager.reset()


class EventTimingTest(unittest.TestCase):
    def test_static_confirmation_uses_elapsed_time_and_exact_boundary(self):
        for intervals in ((0, 17, 56, 99, 100), (0, 99, 100), (0, 25, 50, 75, 100)):
            run = Run()
            for stamp in intervals:
                frame = run.single(stamp, side="Right", pose="point")
                self.assertEqual(any(e.gesture == G.POINTING and e.event_type == E.GESTURE_STARTED for e in frame.events),
                                 stamp == 100)

    def test_unknown_cancels_immediately_no_temporal_conversion_to_pointing(self):
        rig = MixedRig()
        features = (sample_hand(side="Right", pose="point"),)
        for _ in range(5):
            rig.update(features)
        self.assertTrue(rig.controller.arm())
        rig.update(features)
        before = rig.backend.counts["move"]
        unknown = replace(classify_hand(features[0], rig.stamp+33), gesture=G.UNKNOWN, matched_rules=())
        state = rig.update(features, static=(unknown,))
        self.assertIsNone(state.hands[0].confirmed)
        self.assertEqual(rig.backend.counts["move"], before)
        self.assertEqual([e.event_type for e in state.events], [E.GESTURE_CANCELED])
        rig.close()

    def test_repeated_backward_and_delayed_timestamps_never_create_stale_actions(self):
        for stamps in ((0, 50, 100, 100, 101), (0, 50, 100, 70, 101), (0, 100, 351, 400)):
            run = Run()
            for stamp in stamps:
                frame = run.single(stamp, side="Right", pose="point")
                self.assertFalse(any(e.gesture in SWIPES or e.gesture == PINCH for e in frame.events))
            self.assertLessEqual(len(run.manager._tracks), 1)
            self.assertFalse(any(e.event_type == E.GESTURE_STARTED for e in frame.events))

    def test_variable_fps_swipe_one_lifecycle_then_pose_reset_required(self):
        for movement_times in ((300, 340, 390, 440, 490), (310, 350, 400, 470, 500)):
            run = Run()
            run.arm(side="Right")
            for stamp, dx in zip(movement_times, (.4, .8, 1.2, 1.6, 2.)):
                run.single(stamp, dx, side="Right")
            for stamp in range(550, 1501, 50):
                run.single(stamp, 0., side="Right")  # Return with same pose must not trigger opposite.
            events = run.swipe_events()
            self.assertEqual([e.event_type for e in events], [E.GESTURE_STARTED, E.GESTURE_ENDED])
            self.assertEqual({e.gesture for e in events}, {"SWIPE_RIGHT"})


class ExtendedUseTest(unittest.TestCase):
    def test_thousands_of_pinch_frames_have_exactly_one_down_up_and_bounded_state(self):
        opened = tuple(extract_features(pinch_hand(.8, side=side, scale=.04, offset=offset), image_size=SIZE)
                       for side, offset in (("Right", .22), ("Left", -.22)))
        closed = tuple(extract_features(pinch_hand(.1, side=side, scale=.04, offset=offset), image_size=SIZE)
                       for side, offset in (("Right", .22), ("Left", -.22)))
        for mapping in ("relative", "absolute"):
            rig = MixedRig(mapping)
            rig.update(opened)
            self.assertTrue(rig.controller.arm())
            for cycle in range(500):
                reverse = cycle % 2 == 1
                for features, delta in ((opened, 17), (closed, 33), (closed, 55), (closed, 80), (opened, 20)):
                    rig.update(features[::-1] if reverse else features, delta)
                    self.assertTrue(rig.controller.armed)
                    self.assertLessEqual(len(rig.manager._tracks), 2)
                    self.assertLessEqual(len(rig.pinch._history), 2)
                self.assertEqual(rig.backend.counts["down"], cycle+1)
                self.assertEqual(rig.backend.counts["up"], cycle+1)
            self.assertFalse(rig.backend.button_down)
            rig.close()

    def test_repeated_loss_crossing_and_closed_reacquisition_do_not_fabricate_clicks(self):
        opened = (extract_features(pinch_hand(.8, side="Right", scale=.04), image_size=SIZE),)
        closed = (extract_features(pinch_hand(.1, side="Right", scale=.04), image_size=SIZE),)
        for mapping in ("relative", "absolute"):
            rig = MixedRig(mapping)
            for _ in range(150):
                rig.update(opened)
                self.assertTrue(rig.controller.arm())
                rig.update(opened)
                rig.update(closed)
                old = rig.backend.counts["down"]
                canceled = rig.update(())
                self.assertTrue(any(e.gesture == PINCH and e.event_type == E.GESTURE_CANCELED
                                    and not e.metadata.association_current for e in canceled.events))
                self.assertFalse(rig.backend.button_down)
                self.assertFalse(rig.controller.armed)
                rig.update(closed)
                self.assertEqual(rig.backend.counts["down"], old)
                rig.update((opened[0], replace(opened[0], observation=replace(opened[0].observation,
                                   handedness=sample_hand(side="Left").observation.handedness))))
                self.assertFalse(rig.controller.armed)
                self.assertEqual(len(rig.manager._tracks), 0)
            rig.close()

    def test_hundreds_of_swipes_have_one_action_each_and_bounded_trajectory_buffers(self):
        rig = MixedRig()
        point = (sample_hand(side="Right", pose="point"),)
        stationary = (sample_hand(side="Right"),)
        rig.update(point)
        self.assertTrue(rig.controller.arm())
        for cycle in range(200):
            rig.update(point)
            rig.update(point, 200)  # Neutral pose; established reset policy is unchanged.
            for _ in range(6):
                rig.update(stationary, 50)
            for dx in (.4, .8, 1.2, 1.6, 2.):
                rig.update((sample_hand(dx, side="Right"),), 50)
            for dx in (1.6, 1.2, .8, .4, 0.):
                rig.update((sample_hand(dx, side="Right"),), 50)  # Gradual return; no pose reset yet.
            for _ in range(3):
                rig.update(point, 200)
            self.assertEqual(rig.backend.counts["tab"], cycle+1)
            for track in rig.manager._tracks.values():
                self.assertLessEqual(len(track.swipe.samples), MAX_SAMPLES)
                self.assertLessEqual(len(track.swipe.rest), MAX_SAMPLES)
                self.assertLessEqual(len(track.cooldowns), 5)
        rig.close()


if __name__ == "__main__":
    unittest.main()
