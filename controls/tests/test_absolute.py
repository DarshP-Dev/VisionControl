"""Absolute geometry, transitions and fake-only input delivery; no real desktop input."""

from dataclasses import replace
from types import SimpleNamespace
import math
import threading
import unittest
from unittest.mock import MagicMock

from controls.backends import SimulationBackend
from controls.controller import DesktopController
from controls.cursor import AbsoluteCursor, RelativeCursor
from controls.models import ControlSettings, Screen
from controls.region import ActiveRegion
from controls.safety import GlobalSafety
from controls.windows import WindowsBackend
from gestures.events import PINCH, EventType as E
from gestures.features import extract_features
from gestures.models import HandSide, ImageSize
from gestures.pinch import PinchStatus as P
from gestures.static_gestures import Gesture as G
from .test_controls import Harness, feature
from .test_windows import FakeAPI


SIZE = ImageSize(1920, 1080)


class RegionTest(unittest.TestCase):
    def test_default_geometry_1080p_and_symmetric_margins(self):
        left, top, width, height = ActiveRegion().geometry(SIZE)
        for actual, expected in zip((left, top, width, height), (192, 108, 1536, 864)):
            self.assertAlmostEqual(actual, expected)
        self.assertAlmostEqual(SIZE.width-left-width, left)
        self.assertAlmostEqual(SIZE.height-top-height, top)

    def test_other_camera_resolutions(self):
        for size in (ImageSize(640, 480), ImageSize(1280, 720), ImageSize(1080, 1920)):
            left, top, width, height = ActiveRegion().geometry(size)
            self.assertAlmostEqual(left, .1*size.width)
            self.assertAlmostEqual(top, .1*size.height)
            self.assertAlmostEqual(width, .8*size.width)
            self.assertAlmostEqual(height, .8*size.height)

    def test_independent_width_and_height(self):
        self.assertEqual(ActiveRegion(.8, .7).normalize((.5, .5), SIZE), (.5, .5))
        left, top, width, height = ActiveRegion(.8, .7).geometry(SIZE)
        for actual, expected in zip((left, top, width, height), (192, 162, 1536, 756)):
            self.assertAlmostEqual(actual, expected)

    def test_full_frame_region(self):
        region = ActiveRegion(1., 1.)
        self.assertEqual(region.geometry(SIZE), (0, 0, 1920, 1080))
        self.assertEqual(region.normalize((0, 0), SIZE), (0, 0))
        self.assertEqual(region.normalize((1, 1), SIZE), (1, 1))

    def test_invalid_region_fractions(self):
        for value in (0, -.1, 1.01, math.nan, math.inf, -math.inf, True, None, "0.8"):
            for key in ("width", "height"):
                with self.subTest(value=value, key=key), self.assertRaises(ValueError):
                    ActiveRegion(**{key: value})

    def test_invalid_control_settings(self):
        for kwargs in ({"mapping": "other"}, {"region_width": 0}, {"region_height": 2},
                       {"region_width": math.nan}, {"region_height": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ControlSettings(**kwargs)

    def test_invalid_frame_dimensions(self):
        for width, height in ((0, 1080), (1920, -1), (True, 10), (10., 10)):
            with self.assertRaises(ValueError):
                ImageSize(width, height)
        for size in (None, (1920, 1080), SimpleNamespace(width=0, height=1080)):
            with self.assertRaises(ValueError):
                ActiveRegion().geometry(size)
            with self.assertRaises(ValueError):
                ActiveRegion().normalize((.5, .5), size)

    def test_preview_bounds_match_skeleton_coordinate_convention(self):
        self.assertEqual(ActiveRegion().preview_bounds(1100, 619), ((110, 62), (989, 556)))
        self.assertEqual(ActiveRegion(1, 1).preview_bounds(640, 480), ((0, 0), (639, 479)))


class AbsoluteCursorTest(unittest.TestCase):
    def cursor(self, **kwargs):
        return AbsoluteCursor(ControlSettings(mapping="absolute", **kwargs), Screen())

    def test_all_four_corners(self):
        cursor = self.cursor()
        for point, expected in (((.1, .1), (0, 0)), ((.9, .1), (1919, 0)),
                                ((.1, .9), (0, 1079)), ((.9, .9), (1919, 1079))):
            with self.subTest(point=point):
                self.assertEqual(cursor.screen.clamp(*cursor.map_point(point, SIZE)), expected)

    def test_center_maps_to_center_with_origin(self):
        screen = Screen(left=-2560, top=-300, width=2560, height=1440)
        cursor = AbsoluteCursor(ControlSettings(mapping="absolute"), screen)
        self.assertEqual(cursor.map_point((.5, .5), SIZE), (-1280.5, 419.5))

    def test_beyond_active_region_clamps_to_screen_edges(self):
        cursor = self.cursor()
        for point, expected in (((0, .5), (0, 540)), ((1, .5), (1919, 540)),
                                ((.5, 0), (960, 0)), ((.5, 1), (960, 1079))):
            self.assertEqual(cursor.screen.clamp(*cursor.map_point(point, SIZE)), expected)

    def test_horizontal_inversion_mirrors_position_without_changing_y(self):
        normal, inverted = self.cursor(), self.cursor(invert_x=True)
        for point in ((.1, .1), (.9, .9), (.3, .6), (.5, .5)):
            a, b = normal.map_point(point, SIZE), inverted.map_point(point, SIZE)
            self.assertAlmostEqual(a[0]+b[0], 1919)
            self.assertEqual(a[1], b[1])

    def test_camera_aspect_ratio_does_not_distort_absolute_axes(self):
        cursor = self.cursor()
        expected = cursor.map_point((.3, .8), SIZE)
        self.assertEqual(cursor.map_point((.3, .8), ImageSize(640, 480)), expected)
        self.assertEqual(cursor.map_point((.3, .8), ImageSize(1080, 1920)), expected)

    def test_activation_skips_first_sample_then_maps_without_accumulation(self):
        cursor = self.cursor(alpha=1.)
        self.assertIsNone(cursor.update((.2, .2), SIZE, (500, 500)))
        self.assertEqual(cursor.update((.9, .9), SIZE, (0, 0)), (1919, 1079))
        for _ in range(5):
            self.assertEqual(cursor.update((.9, .9), SIZE, (0, 0)), (1919, 1079))
        self.assertEqual(cursor.update((.1, .1), SIZE, (0, 0)), (0, 0))

    def test_screen_ema_uses_existing_alpha(self):
        cursor = self.cursor(alpha=.5)
        cursor.update((.5, .5), SIZE, (100, 100))
        target = cursor.map_point((.9, .9), SIZE)
        first = cursor.update((.9, .9), SIZE, (0, 0))
        self.assertEqual(first, cursor.screen.clamp((target[0]+100)/2, (target[1]+100)/2))
        second = cursor.update((.9, .9), SIZE, (0, 0))
        self.assertGreater(second[0], first[0])
        for _ in range(30):
            last = cursor.update((.9, .9), SIZE, (0, 0))
        self.assertEqual(last, (1919, 1079))

    def test_reset_clears_stale_positions_and_drag_offset(self):
        cursor = self.cursor()
        cursor.begin_drag((.2, .2), SIZE, (500, 500))
        cursor.reset()
        self.assertIsNone(cursor.drag_offset)
        self.assertIsNone(cursor.filtered)
        self.assertIsNone(cursor.update((.8, .8), SIZE, (200, 300)))

    def test_resolution_change_requires_fresh_activation(self):
        cursor = self.cursor()
        cursor.update((.2, .2), SIZE, (500, 500))
        self.assertIsNone(cursor.update((.8, .8), ImageSize(640, 480), (100, 200)))

    def test_invalid_tip_is_rejected_before_any_target(self):
        for point in ((math.nan, .5), (.5, math.inf), (-.1, .5), (1.1, .5),
                      (True, .5), ("0.5", .5), (.5,), None):
            with self.subTest(point=point), self.assertRaises(ValueError):
                self.cursor().update(point, SIZE, (500, 500))

    def test_outside_monitor_activation_rejected(self):
        with self.assertRaises(ValueError):
            self.cursor().update((.5, .5), SIZE, (-1, 0))

    def test_drag_offset_prevents_pinch_jump_and_allows_held_motion(self):
        for inverted in (False, True):
            cursor = self.cursor(alpha=1., invert_x=inverted)
            cursor.begin_drag((.3, .4), SIZE, (800, 500))
            self.assertIsNone(cursor.update((.3, .4), SIZE, (0, 0)))
            self.assertEqual(cursor.update((.3, .4), SIZE, (0, 0)), (800, 500))
            moved = cursor.update((.32, .42), SIZE, (0, 0))
            self.assertGreater((moved[0]-800)*(-1 if inverted else 1), 0)
            self.assertGreater(moved[1], 500)

    def test_drag_clamps_without_accumulation_or_edge_windup(self):
        cursor = self.cursor(alpha=1.)
        cursor.begin_drag((.2, .5), SIZE, (1500, 500))
        cursor.update((.2, .5), SIZE, (0, 0))
        self.assertEqual(cursor.update((.9, .5), SIZE, (0, 0))[0], 1919)
        self.assertEqual(cursor.update((.2, .5), SIZE, (0, 0)), (1500, 500))

    def test_drag_rejects_capture_geometry_change(self):
        cursor = self.cursor()
        cursor.begin_drag((.3, .4), SIZE, (800, 500))
        with self.assertRaises(ValueError):
            cursor.update((.3, .4), ImageSize(640, 480), (800, 500))

    def test_absolute_ignores_relative_sensitivity_and_margin(self):
        a = self.cursor(alpha=1., sensitivity=.1, margin=0)
        b = self.cursor(alpha=1., sensitivity=5, margin=.4)
        self.assertEqual(a.map_point((.25, .75), SIZE), b.map_point((.25, .75), SIZE))


class AbsoluteControllerTest(unittest.TestCase):
    def harness(self, **kwargs):
        return Harness(mapping="absolute", **kwargs)

    def test_strategy_default_and_opt_in(self):
        self.assertIsInstance(Harness().controller.cursor, RelativeCursor)
        self.assertIsInstance(self.harness().controller.cursor, AbsoluteCursor)

    def test_disarmed_has_no_updates_or_real_windows_backend(self):
        h = self.harness(mouse=True)
        h.step(); h.step(dx=.02); h.start()
        self.assertEqual(h.backend.counts, {})
        self.assertFalse(h.backend.is_live)
        self.assertIsNone(h.controller.cursor.previous)

    def test_armed_mapping_and_inversion(self):
        for invert in (False, True):
            h = self.harness(alpha=1., invert_x=invert)
            h.arm()
            self.assertEqual(h.backend.counts["move"], 0)
            _, items, _ = h.step(dx=.02)
            tip = items[0].observation[8]
            expected = h.controller.cursor.map_point((tip.x, tip.y), SIZE)
            self.assertEqual(h.backend.position, h.backend.screen.clamp(*expected))
            self.assertEqual(h.controller.reason, "Absolute pointing")

    def test_pinch_click_once_drag_without_pointing_and_release_no_jump(self):
        h = self.harness(mouse=True, alpha=.5)
        h.arm(); h.step(dx=.02)
        before, moves = h.backend.position, h.backend.counts["move"]
        h.step(PINCH, P.STARTED, dx=-.04, events=((PINCH, E.GESTURE_STARTED, "confirmed"),))
        self.assertEqual(h.backend.position, before)
        self.assertEqual(h.backend.counts["move"], moves)
        h.step(PINCH, P.HELD, dx=-.02)
        self.assertGreater(h.backend.position[0], before[0])
        held = h.backend.position
        self.assertEqual(h.backend.counts["down"], 1)
        h.step(G.POINTING, P.RELEASED, events=((PINCH, E.GESTURE_ENDED, "pinch_released"),))
        self.assertEqual(h.backend.position, held)
        self.assertEqual(h.backend.counts["up"], 1)
        self.assertIsNone(h.controller.cursor.drag_offset)
        h.step()
        self.assertEqual(h.backend.counts["up"], 1)
        self.assertTrue(h.controller.armed)

    def test_pending_static_pose_stops_motion_and_resets(self):
        h = self.harness(); h.arm(); h.step(dx=.02)
        moves = h.backend.counts["move"]
        h.step(dx=.03, candidate=G.FIST)
        self.assertEqual(h.backend.counts["move"], moves)
        self.assertIsNone(h.controller.cursor.previous)

    def test_hand_loss_requires_manual_rearm_and_new_coordinates(self):
        h = self.harness(mouse=True); h.arm(); h.start()
        h.step(features=())
        self.assertFalse(h.controller.armed)
        self.assertEqual(h.backend.counts["up"], 1)
        self.assertIsNone(h.controller.cursor.drag_offset)
        moves = h.backend.counts["move"]
        h.step(dx=.05)
        self.assertEqual(h.backend.counts["move"], moves)
        self.assertTrue(h.controller.arm())
        h.step(dx=-.05)
        self.assertEqual(h.backend.counts["move"], moves)

    def test_does_not_transfer_to_other_hand(self):
        h = self.harness(mouse=True); h.arm(); h.start()
        h.step(features=(feature(side="Left"),))
        self.assertFalse(h.controller.armed)
        self.assertEqual(h.backend.counts["up"], 1)

    def test_ambiguous_hands_disarm_and_release(self):
        h = self.harness(mouse=True); h.arm(); h.start()
        h.step(features=(feature(), feature(dx=.02)))
        self.assertFalse(h.controller.armed)
        self.assertEqual(h.backend.counts["up"], 1)

    def test_invalid_tip_disarms_without_unsafe_move(self):
        h = self.harness(mouse=True); h.arm(); h.start()
        item = feature()
        observation = replace(item.observation, landmarks=tuple(
            replace(p, x=1.1) if index == 8 else p for index, p in enumerate(item.observation.landmarks)))
        invalid = extract_features(observation, image_size=SIZE)
        moves = h.backend.counts["move"]
        h.step(PINCH, P.HELD, features=(invalid,))
        self.assertFalse(h.controller.armed)
        self.assertEqual(h.backend.counts["up"], 1)
        self.assertEqual(h.backend.counts["move"], moves)

    def test_manual_emergency_shutdown_and_watchdog_clear_drag(self):
        for action in (lambda h: h.controller.disarm(), lambda h: h.controller.disarm("GLOBAL EMERGENCY STOP"),
                       lambda h: h.controller.close(), lambda h: self.stall(h)):
            h = self.harness(mouse=True); h.arm(); h.start()
            action(h)
            self.assertFalse(h.controller.armed)
            self.assertEqual(h.backend.counts["up"], 1)
            self.assertIsNone(h.controller.cursor.drag_offset)

    @staticmethod
    def stall(h):
        h.now += .501
        h.controller.check_timeout()

    def test_live_controller_through_fake_win32_primary_pixels(self):
        api = FakeAPI()
        backend = WindowsBackend(api=api)
        h = Harness()
        h.controller = DesktopController(backend, ControlSettings(mode="live", mapping="absolute", alpha=1.),
                                         clock=lambda: h.now)
        h.step()
        self.assertFalse(h.controller.arm())  # Safety has not initialized.
        self.assertEqual(api.sent, [])
        h.controller.safety_ready = True
        h.arm()
        self.assertEqual(api.sent, [])
        _, items, _ = h.step(dx=.02)
        tip = items[0].observation[8]
        x, y = backend.screen.clamp(*h.controller.cursor.map_point((tip.x, tip.y), SIZE))
        packet = api.sent[-1][0].mi
        self.assertEqual((packet.dx, packet.dy), (round((x+2560)*65535/4479), round(y*65535/1439)))
        self.assertEqual(packet.dwFlags, 0xC001)
        api.prepare_dpi.assert_called_once()

    def test_negative_monitor_origin_maps_before_win32_normalization(self):
        api = FakeAPI()
        backend = WindowsBackend(1, api=api)
        cursor = AbsoluteCursor(ControlSettings(mapping="absolute", alpha=1.), backend.screen)
        cursor.update((.5, .5), SIZE, (-100, 200))
        target = cursor.update((.1, .1), SIZE, (0, 0))
        self.assertEqual(target, (-2560, 0))
        backend.move(*target)
        self.assertEqual((api.sent[-1][0].mi.dx, api.sent[-1][0].mi.dy), (0, 0))

    def test_global_hotkey_thread_releases_absolute_drag_using_fake_api(self):
        h = self.harness(mouse=True)
        h.arm(); h.start()
        api = MagicMock()
        api.stop_requested.return_value = False
        stopped = threading.Event()
        original = h.controller.disarm
        def disarm(reason):
            original(reason)
            if reason.startswith("GLOBAL"):
                stopped.set()
        h.controller.disarm = disarm
        safety = GlobalSafety(h.controller, api).start()
        try:
            api.stop_requested.return_value = True
            self.assertTrue(stopped.wait(1))
            self.assertFalse(h.controller.armed)
            self.assertEqual(h.backend.counts["up"], 1)
            self.assertIsNone(h.controller.cursor.drag_offset)
        finally:
            safety.close()
        api.register_stop.assert_called_once()
        api.unregister_stop.assert_called_once()

    def test_backend_error_fails_closed_and_clears_absolute_state(self):
        h = self.harness(mouse=True)
        h.arm(); h.start()
        def fail(*args):
            raise OSError("Fake input failure")
        h.backend.move = fail
        with self.assertLogs("controls", level="ERROR"):
            h.step(PINCH, P.HELD, dx=.02)
        self.assertTrue(h.controller.faulted)
        self.assertFalse(h.controller.armed)
        self.assertEqual(h.backend.counts["up"], 1)
        self.assertIsNone(h.controller.cursor.drag_offset)
        self.assertFalse(h.controller.arm())

    def test_release_reacquisition_uses_current_cursor_and_existing_ema(self):
        h = self.harness(mouse=True, alpha=.5)
        h.arm(); h.start(); h.step(PINCH, P.HELD, dx=.02)
        h.step(None, P.RELEASED, events=((PINCH, E.GESTURE_ENDED, "pinch_released"),))
        held = h.backend.position
        h.step(dx=-.02)
        self.assertEqual(h.backend.position, held)  # Fresh POINTING is move-free.
        _, items, _ = h.step(dx=-.02)
        tip = items[0].observation[8]
        mapped = h.controller.cursor.map_point((tip.x, tip.y), SIZE)
        expected = h.backend.screen.clamp((held[0]+mapped[0])/2, (held[1]+mapped[1])/2)
        self.assertEqual(h.backend.position, expected)

    def test_click_and_tab_flags_remain_independent(self):
        h = self.harness()
        h.arm(); h.start(); h.step(PINCH, P.HELD, dx=.02)
        self.assertEqual(h.backend.counts["down"], 0)
        self.assertEqual(h.backend.counts["tab"], 0)
        self.assertEqual(h.backend.counts["move"], 0)


if __name__ == "__main__":
    unittest.main()
