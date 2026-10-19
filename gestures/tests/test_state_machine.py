from dataclasses import FrozenInstanceError, replace
import unittest

from gestures.arbitration import resolved_input
from gestures.events import PINCH, EventMetadata, EventType as E, GestureEvent, GestureState as S
from gestures.features import extract_features
from gestures.models import HandednessPrediction, HandSide, ImageSize
from gestures.pinch import PinchMeasurement, PinchResult, PinchStatus as P, PinchTracker
from gestures.state_machine import GestureStateManager, StateSettings
from gestures.static_gestures import Gesture as G, GestureResult
from .pinch_fixtures import pinch_hand
from .static_fixtures import SIZE


def hand(side="Left", distance=.8, offset=None, **kwargs):
    offset = (-.23 if side == "Left" else .23) if offset is None else offset
    return extract_features(pinch_hand(distance, side=side, offset=offset, **kwargs),
                            image_size=kwargs.get("image_size", SIZE))


def classification(feature, stamp, gesture=G.POINTING):
    matches = () if gesture == G.UNKNOWN else (gesture,)
    return GestureResult(gesture, stamp, feature.observation.handedness, matches)


def pinch(feature, stamp, status, distance=None):
    return PinchResult(status, PinchMeasurement(feature.thumb_index_ratio if distance is None else distance, True),
                       stamp, feature.observation.handedness)


def observe(manager, stamp, gesture=G.POINTING, feature=None, pinch_status=None):
    feature = feature or hand()
    raw = (classification(feature, stamp, gesture),) if gesture is not None else None
    pinches = (pinch(feature, stamp, pinch_status),) if pinch_status is not None else None
    return manager.update((feature,), stamp, raw, pinches)


class StaticStateTest(unittest.TestCase):
    def test_idle_candidate_active_and_started_once(self):
        manager = GestureStateManager()
        self.assertEqual(observe(manager, 0, G.UNKNOWN).hands[0].state, S.IDLE)
        first = observe(manager, 10)
        self.assertEqual(first.hands[0].state, S.CANDIDATE)
        self.assertEqual(first.events, ())
        self.assertEqual(observe(manager, 109).events, ())
        confirmed = observe(manager, 110)
        self.assertEqual(confirmed.hands[0].confirmed, G.POINTING)
        self.assertEqual(confirmed.hands[0].state, S.ACTIVE)
        self.assertEqual([(e.event_type, e.timestamp_ms) for e in confirmed.events], [(E.GESTURE_STARTED, 110)])
        for stamp in (111, 140, 200, 300):
            self.assertEqual(observe(manager, stamp).events, ())

    def test_candidate_disappears_changes_or_becomes_invalid(self):
        manager = GestureStateManager()
        observe(manager, 0)
        self.assertEqual(observe(manager, 50, G.UNKNOWN).hands[0].state, S.IDLE)
        observe(manager, 60)
        changed = observe(manager, 90, G.FIST)
        self.assertEqual(changed.hands[0].candidate, G.FIST)
        self.assertEqual(observe(manager, 160, G.FIST).events, ())
        self.assertEqual(observe(manager, 190, G.FIST).events[0].gesture, G.FIST)

    def test_known_transition_ends_once_then_confirms_new_pose(self):
        manager = GestureStateManager()
        observe(manager, 0)
        observe(manager, 100)
        self.assertEqual(observe(manager, 130, G.FIST).hands[0].confirmed, G.POINTING)
        self.assertEqual(observe(manager, 189, G.FIST).events, ())
        ended = observe(manager, 190, G.FIST)
        self.assertEqual([(e.event_type, e.gesture) for e in ended.events], [(E.GESTURE_ENDED, G.POINTING)])
        self.assertEqual(ended.hands[0].state, S.CANDIDATE)
        self.assertEqual(observe(manager, 230, G.FIST).events[0].gesture, G.FIST)
        self.assertEqual(observe(manager, 240, G.FIST).events, ())

    def test_brief_replacement_does_not_end_active_gesture(self):
        manager = GestureStateManager()
        observe(manager, 0)
        observe(manager, 100)
        observe(manager, 130, G.FIST)
        restored = observe(manager, 180)
        self.assertEqual(restored.events, ())
        self.assertIsNone(restored.hands[0].candidate)
        self.assertEqual(restored.hands[0].confirmed, G.POINTING)

    def test_unknown_cancels_immediately_never_becomes_actionable(self):
        manager = GestureStateManager()
        observe(manager, 0)
        observe(manager, 100)
        canceled = observe(manager, 101, G.UNKNOWN)
        self.assertEqual([e.event_type for e in canceled.events], [E.GESTURE_CANCELED])
        self.assertEqual(canceled.hands[0].state, S.IDLE)
        self.assertIsNone(canceled.hands[0].confirmed)
        self.assertEqual(observe(manager, 200, G.UNKNOWN).events, ())

    def test_per_gesture_cooldown_boundary_and_new_activation_clock(self):
        manager = GestureStateManager()
        observe(manager, 0)
        observe(manager, 100)
        observe(manager, 110, G.UNKNOWN)
        self.assertEqual(observe(manager, 259).hands[0].state, S.COOLDOWN)
        self.assertEqual(observe(manager, 260).hands[0].state, S.CANDIDATE)
        self.assertEqual(observe(manager, 359).events, ())
        self.assertEqual(observe(manager, 360).events[0].event_type, E.GESTURE_STARTED)

    def test_other_gesture_not_blocked_by_previous_gesture_cooldown(self):
        manager = GestureStateManager()
        observe(manager, 0)
        observe(manager, 100)
        observe(manager, 110, G.UNKNOWN)
        observe(manager, 120, G.FIST)
        self.assertEqual(observe(manager, 220, G.FIST).hands[0].confirmed, G.FIST)

    def test_variable_fps_uses_elapsed_time_not_frame_count(self):
        for stamps in ((0, 20, 55, 99, 100), (0, 100), (0, 200)):
            manager = GestureStateManager()
            frames = [observe(manager, stamp) for stamp in stamps]
            self.assertEqual(sum(len(frame.events) for frame in frames), 1)
            self.assertEqual(frames[-1].events[0].timestamp_ms, stamps[-1])

    def test_zero_intervals_are_immediate_and_bounded_settings_validated(self):
        manager = GestureStateManager(StateSettings(0, 0, 0, 0))
        self.assertEqual(observe(manager, 0).events[0].event_type, E.GESTURE_STARTED)
        self.assertEqual([e.event_type for e in observe(manager, 1, G.FIST).events],
                         [E.GESTURE_ENDED, E.GESTURE_STARTED])
        for value in (-1, True, 1.5, 5001, float("nan")):
            for name in ("activation_ms", "transition_ms", "cooldown_ms", "update_ms"):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    StateSettings(**{name: value})

    def test_conflicting_static_rules_cancel(self):
        manager = GestureStateManager(StateSettings(0))
        item = hand()
        observe(manager, 0, feature=item)
        conflict = replace(classification(item, 1), matched_rules=(G.POINTING, G.FIST))
        frame = manager.update((item,), 1, (conflict,))
        self.assertEqual(frame.events[0].event_type, E.GESTURE_CANCELED)
        self.assertIsNone(frame.hands[0].confirmed)


class PinchEventTest(unittest.TestCase):
    def test_simultaneous_pinches_order_changes_and_one_hand_loss(self):
        manager, detector = GestureStateManager(), PinchTracker()
        outputs = []
        for stamp, distance in ((0, .8), (30, .1), (60, .1)):
            items = (hand(distance=distance), hand("Right", distance=distance))
            if stamp == 30:
                items = items[::-1]
            outputs.append(manager.update(items, stamp, pinches=detector.update(items, stamp)))
        self.assertEqual([e.side for e in outputs[1].events], [HandSide.LEFT, HandSide.RIGHT])
        self.assertTrue(all(e.event_type == E.GESTURE_STARTED for e in outputs[1].events))
        self.assertEqual(outputs[2].events, ())
        right = (hand("Right", distance=.1),)
        lost = manager.update(right, 90, pinches=detector.update(right, 90))
        self.assertEqual([(e.event_type, e.side) for e in lost.events], [(E.GESTURE_CANCELED, HandSide.LEFT)])
        self.assertEqual(lost.hands[0].confirmed, PINCH)

    def test_real_pinch_lifecycle_has_no_extra_activation_delay(self):
        manager, detector = GestureStateManager(), PinchTracker()
        statuses, events = [], []
        for stamp, distance in ((0, .8), (30, .1), (60, .1), (90, .8), (120, .8)):
            item = hand(distance=distance)
            results = detector.update((item,), stamp)
            statuses.append(results[0].status)
            frame = manager.update((item,), stamp, pinches=results)
            events.extend(frame.events)
        self.assertEqual(statuses, [P.OPEN, P.STARTED, P.HELD, P.RELEASED, P.OPEN])
        self.assertEqual([(e.event_type, e.timestamp_ms, e.gesture) for e in events],
                         [(E.GESTURE_STARTED, 30, PINCH), (E.GESTURE_ENDED, 90, PINCH)])

    def test_held_and_duplicate_started_do_not_duplicate_activation(self):
        manager = GestureStateManager()
        observe(manager, 0, None, pinch_status=P.OPEN)
        self.assertEqual(len(observe(manager, 1, None, pinch_status=P.STARTED).events), 1)
        for stamp, status in ((2, P.STARTED), (3, P.HELD), (4, P.STARTED)):
            self.assertEqual(observe(manager, stamp, None, pinch_status=status).events, ())

    def test_pinch_preempts_static_without_erasing_raw_classification(self):
        manager = GestureStateManager(StateSettings(0))
        observe(manager, 0, pinch_status=P.OPEN)
        raw = classification(hand(), 1)
        frame = manager.update((hand(),), 1, (raw,), (pinch(hand(), 1, P.STARTED),))
        self.assertEqual(raw.gesture, G.POINTING)
        self.assertEqual([(e.event_type, e.gesture) for e in frame.events],
                         [(E.GESTURE_CANCELED, G.POINTING), (E.GESTURE_STARTED, PINCH)])
        self.assertEqual(frame.hands[0].confirmed, PINCH)
        self.assertEqual(observe(manager, 2, G.FIST, pinch_status=P.HELD).hands[0].confirmed, PINCH)

    def test_unavailable_cancels_pinch_and_suppresses_static(self):
        manager = GestureStateManager(StateSettings(0))
        observe(manager, 0, pinch_status=P.OPEN)
        observe(manager, 1, pinch_status=P.STARTED)
        frame = observe(manager, 2, pinch_status=P.UNAVAILABLE)
        self.assertEqual([(e.event_type, e.gesture) for e in frame.events], [(E.GESTURE_CANCELED, PINCH)])
        self.assertIsNone(frame.hands[0].confirmed)
        self.assertEqual(observe(manager, 3, pinch_status=P.HELD).events, ())
        self.assertEqual(observe(manager, 4, pinch_status=P.STARTED).events, ())

    def test_closed_reacquisition_requires_open_in_both_layers(self):
        manager, detector = GestureStateManager(), PinchTracker()
        outputs = []
        sequence = ((0, .8), (30, .1), (60, None), (90, .1), (120, .1), (150, .8), (180, .1))
        for stamp, distance in sequence:
            items = () if distance is None else (hand(distance=distance),)
            results = detector.update(items, stamp)
            outputs.append(manager.update(items, stamp, pinches=results))
        self.assertEqual([e.event_type for e in outputs[2].events], [E.GESTURE_CANCELED])
        self.assertFalse(outputs[2].events[0].metadata.association_current)
        self.assertTrue(all(not frame.events for frame in outputs[3:6]))
        self.assertEqual(outputs[6].events[0].event_type, E.GESTURE_STARTED)

    def test_orphan_held_or_started_cannot_start_after_manager_reset(self):
        for status in (P.HELD, P.STARTED):
            manager = GestureStateManager()
            self.assertEqual(observe(manager, 0, None, pinch_status=status).events, ())
            self.assertIsNone(observe(manager, 1, None, pinch_status=P.HELD).hands[0].confirmed)
            observe(manager, 2, None, pinch_status=P.OPEN)
            self.assertEqual(observe(manager, 3, None, pinch_status=P.STARTED).events[0].event_type, E.GESTURE_STARTED)

    def test_distance_updates_are_useful_rate_limited_and_optional(self):
        manager = GestureStateManager(StateSettings(update_ms=100))
        observe(manager, 0, None, feature=hand(distance=.8), pinch_status=P.OPEN)
        observe(manager, 1, None, feature=hand(distance=.1), pinch_status=P.STARTED)
        self.assertEqual(observe(manager, 100, None, feature=hand(distance=.2), pinch_status=P.HELD).events, ())
        updated = observe(manager, 101, None, feature=hand(distance=.2), pinch_status=P.HELD).events
        self.assertEqual(updated[0].event_type, E.GESTURE_UPDATED)
        self.assertAlmostEqual(updated[0].metadata.normalized_pinch_distance, .2)
        self.assertEqual(observe(manager, 201, None, feature=hand(distance=.2), pinch_status=P.HELD).events, ())
        manager = GestureStateManager(StateSettings(update_ms=0))
        observe(manager, 0, None, pinch_status=P.OPEN)
        observe(manager, 1, None, pinch_status=P.STARTED)
        for stamp, distance in ((200, .2), (400, .1)):
            self.assertEqual(observe(manager, stamp, None, feature=hand(distance=distance), pinch_status=P.HELD).events, ())

    def test_missing_release_transition_cancels_instead_of_intentional_end(self):
        manager = GestureStateManager()
        observe(manager, 0, None, pinch_status=P.OPEN)
        observe(manager, 1, None, pinch_status=P.STARTED)
        frame = observe(manager, 2, None, pinch_status=P.OPEN)
        self.assertEqual(frame.events[0].event_type, E.GESTURE_CANCELED)

    def test_arbitration_unknown_conflict_pinch_and_open(self):
        item = hand()
        self.assertEqual(resolved_input(classification(item, 0), pinch(item, 0, P.HELD)), PINCH)
        self.assertIsNone(resolved_input(classification(item, 0), pinch(item, 0, P.UNAVAILABLE)))
        self.assertEqual(resolved_input(classification(item, 0), pinch(item, 0, P.OPEN)), G.POINTING)
        self.assertIsNone(resolved_input(classification(item, 0, G.UNKNOWN), None))


class AssociationAndTimingTest(unittest.TestCase):
    def test_two_hands_independent_order_changes_and_deterministic_event_order(self):
        def run(reverse):
            manager = GestureStateManager()
            frames = []
            for stamp in (0, 100, 130, 200):
                items = (hand(), hand("Right"))
                raw = (classification(items[0], stamp, G.FIST), classification(items[1], stamp))
                if reverse and stamp in (100, 200):
                    items, raw = items[::-1], raw[::-1]
                frames.append(manager.update(items, stamp, raw))
            return frames
        normal, shuffled = run(False), run(True)
        self.assertEqual([f.events for f in normal], [f.events for f in shuffled])
        self.assertEqual(normal[1].events[0].side, HandSide.LEFT)
        self.assertEqual(shuffled[1].hands[0].confirmed, G.POINTING)

    def test_one_or_both_hands_lost_only_cancels_missing_histories(self):
        manager = GestureStateManager(StateSettings(0))
        left, right = hand(), hand("Right")
        manager.update((left, right), 0, (classification(left, 0), classification(right, 0, G.FIST)))
        frame = manager.update((right,), 1, (classification(right, 1, G.FIST),))
        self.assertEqual([(e.event_type, e.side) for e in frame.events], [(E.GESTURE_CANCELED, HandSide.LEFT)])
        self.assertEqual(frame.hands[0].confirmed, G.FIST)
        lost = manager.update((), 2, ())
        self.assertEqual(lost.hands, ())
        self.assertEqual(lost.events[0].side, HandSide.RIGHT)
        self.assertEqual(manager.update((), 3, ()).events, ())

    def test_crossing_and_duplicate_or_uncertain_sides_cancel(self):
        left = hand()
        variants = (
            (hand(offset=0), hand("Right", offset=0)),
            (left, hand(side="Left", offset=.23)),
            (replace(left, observation=replace(left.observation, handedness=(HandednessPrediction("Left", .79),))),),
            (replace(left, observation=replace(left.observation, handedness=())),),
            (None,),
        )
        for items in variants:
            manager = GestureStateManager(StateSettings(0))
            observe(manager, 0)
            raw = tuple(classification(item, 1) if item is not None else GestureResult(G.UNKNOWN, 1) for item in items)
            frame = manager.update(items, 1, raw)
            self.assertEqual([e.event_type for e in frame.events], [E.GESTURE_CANCELED])
            self.assertTrue(all(state.confirmed is None for state in frame.hands))

    def test_reappearing_static_requires_fresh_candidate_interval(self):
        manager = GestureStateManager()
        observe(manager, 0)
        observe(manager, 100)
        manager.update((), 130, ())
        self.assertEqual(observe(manager, 150).hands[0].state, S.CANDIDATE)
        self.assertEqual(observe(manager, 249).events, ())
        self.assertEqual(observe(manager, 250).events[0].timestamp_ms, 250)

    def test_invalid_repeated_backward_and_missing_time_cancel_once(self):
        for stamp in (None, -1, True, 100.5, 100, 90):
            manager = GestureStateManager(StateSettings(0))
            observe(manager, 100)
            frame = manager.update((hand(),), stamp, (classification(hand(), 100),))
            self.assertEqual(frame.timestamp_ms, 100)
            self.assertEqual([e.event_type for e in frame.events], [E.GESTURE_CANCELED])
            self.assertEqual(manager.update((hand(),), stamp, ()).events, ())
            self.assertTrue(all(h.confirmed is None for h in frame.hands))
        manager = GestureStateManager()
        observe(manager, 100)
        manager.update((), 90, ())
        self.assertEqual(manager.update((hand(),), 95, (classification(hand(), 95),)).hands[0].reason, "invalid_time")

    def test_long_gap_and_image_change_cancel_then_start_fresh(self):
        for stamp, feature in ((400, hand()), (101, hand(image_size=ImageSize(640, 480)))):
            manager = GestureStateManager()
            observe(manager, 0)
            observe(manager, 100)
            frame = observe(manager, stamp, feature=feature)
            self.assertEqual(frame.events[0].event_type, E.GESTURE_CANCELED)
            self.assertIsNone(frame.hands[0].confirmed)
            self.assertEqual(observe(manager, stamp+1, feature=feature).hands[0].state, S.CANDIDATE)

    def test_large_wrist_jump_cancels_without_transferring_state(self):
        manager = GestureStateManager()
        observe(manager, 0)
        observe(manager, 100)
        frame = observe(manager, 101, feature=hand(offset=.1))
        self.assertEqual(frame.events[0].metadata.reason, "wrist_jump")
        self.assertIsNone(frame.hands[0].confirmed)

    def test_alignment_wrong_metadata_or_timestamp_rejected(self):
        for raw in ((), (classification(hand(), 1),)*2,
                    (classification(hand("Right"), 1),), (classification(hand(), 0),), (None,)):
            manager = GestureStateManager(StateSettings(0))
            observe(manager, 0)
            frame = manager.update((hand(),), 1, raw)
            self.assertEqual([e.event_type for e in frame.events], [E.GESTURE_CANCELED])
            self.assertTrue(all(h.confirmed is None for h in frame.hands))

    def test_degenerate_geometry_and_invalid_pinch_cannot_activate(self):
        manager = GestureStateManager(StateSettings(0))
        item = replace(hand(), palm_scale=0)
        self.assertIsNone(observe(manager, 0, feature=item).hands[0].confirmed)
        missing = replace(hand(), observation=None)
        self.assertIsNone(manager.update((missing,), 1, (GestureResult(G.UNKNOWN, 1),)).hands[0].confirmed)
        item = hand()
        bad = replace(pinch(item, 2, P.STARTED), measurement=PinchMeasurement(float("nan"), True))
        self.assertIsNone(manager.update((item,), 2, pinches=(bad,)).hands[0].confirmed)
        malformed = replace(classification(item, 3), matched_rules=None)
        self.assertIsNone(manager.update((item,), 3, (malformed,)).hands[0].confirmed)

    def test_reset_events_are_canceled_immutable_and_not_replayed(self):
        manager = GestureStateManager(StateSettings(0))
        event = observe(manager, 0).events[0]
        with self.assertRaises(FrozenInstanceError):
            event.timestamp_ms = 1
        with self.assertRaises(FrozenInstanceError):
            event.metadata.reason = "changed"
        canceled = manager.reset()
        self.assertEqual(canceled[0].event_type, E.GESTURE_CANCELED)
        self.assertFalse(canceled[0].metadata.association_current)
        self.assertEqual(manager.reset(), ())

    def test_same_ordered_sequence_produces_identical_events(self):
        def run():
            manager = GestureStateManager()
            return [observe(manager, stamp, gesture) for stamp, gesture in
                    ((0, G.POINTING), (100, G.POINTING), (130, G.FIST),
                     (190, G.FIST), (230, G.FIST), (250, G.UNKNOWN))]
        self.assertEqual(run(), run())

    def test_event_validation_and_frozen_metadata(self):
        for gesture, stamp, side in ((G.UNKNOWN, 0, HandSide.LEFT), (G.FIST, -1, HandSide.LEFT),
                                      (G.FIST, 0, HandSide.UNKNOWN), (G.FIST, True, HandSide.LEFT)):
            with self.assertRaises(ValueError):
                GestureEvent(gesture, E.GESTURE_STARTED, stamp, side, S.ACTIVE)
        for value in (-1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                EventMetadata(normalized_pinch_distance=value)


if __name__ == "__main__":
    unittest.main()
