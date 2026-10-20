"""Mapping-specific X defaults and explicit overrides; all desktop input is fake."""

from contextlib import redirect_stderr
import io
import unittest

from controls import cli
from controls.backends import SimulationBackend
from controls.controller import DesktopController
from controls.cursor import AbsoluteCursor, RelativeCursor
from controls.models import ControlSettings, Screen
from controls.tests.test_controls import Harness
from controls.tests.test_windows import FakeAPI
from controls.windows import WindowsBackend
from gestures.events import PINCH, EventType as E
from gestures.models import ImageSize
from gestures.pinch import PinchStatus as P
from . import hand_tracker as tracker


FLAGS = ["--gestures", "--pinch", "--gesture-states", "--controls"]
SIZE = ImageSize(1920, 1080)


class InversionDefaultTest(unittest.TestCase):
    def configured(self, mapping="absolute", mode="simulate", extra=()):
        return cli.settings(tracker.parse_args(FLAGS+[
            "--control-mapping", mapping, "--control-mode", mode]+list(extra)))

    def test_model_defaults_are_resolved_for_each_mapping(self):
        self.assertIs(ControlSettings().invert_x, False)
        self.assertIs(ControlSettings(mapping="relative").invert_x, False)
        settings = ControlSettings(mapping="absolute")
        self.assertIs(settings.invert_x, True)
        self.assertEqual((settings.region_width, settings.region_height, settings.alpha), (.8, .8, .6))

    def test_model_explicit_overrides_are_preserved(self):
        for mapping in ("relative", "absolute"):
            for explicit in (False, True):
                settings = ControlSettings(mapping=mapping, invert_x=explicit)
                self.assertIs(settings.invert_x, explicit)

    def test_cli_defaults_and_overrides_in_simulation_and_live(self):
        for mode in ("simulate", "live"):
            for mapping in ("relative", "absolute"):
                self.assertIs(self.configured(mapping, mode).invert_x, mapping == "absolute")
                self.assertIs(self.configured(mapping, mode, ["--control-invert-x"]).invert_x, True)
                self.assertIs(self.configured(mapping, mode, ["--control-no-invert-x"]).invert_x, False)

    def test_conflicting_override_flags_are_rejected(self):
        for flags in (["--control-invert-x", "--control-no-invert-x"],
                      ["--control-no-invert-x", "--control-invert-x"]):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                tracker.parse_args(FLAGS+flags)

    def test_both_explicit_flags_require_enabled_controls(self):
        for flag in ("--control-invert-x", "--control-no-invert-x"):
            with self.subTest(flag=flag), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                tracker.parse_args([flag])

    def test_physical_finger_left_right_under_observed_camera_convention(self):
        # Webcam testing established: physical left increases raw camera X.
        cursor = AbsoluteCursor(ControlSettings(mapping="absolute", alpha=1.), Screen())
        cursor.update((.5, .5), SIZE, (960, 540))
        center = cursor.update((.5, .5), SIZE, (0, 0))
        physical_left = cursor.update((.55, .5), SIZE, (0, 0))
        physical_right = cursor.update((.45, .5), SIZE, (0, 0))
        self.assertLess(physical_left[0], center[0])
        self.assertGreater(physical_right[0], center[0])
        self.assertEqual(physical_left[1], physical_right[1])
        self.assertEqual(physical_left[1], center[1])

    def test_y_mapping_and_up_down_are_unchanged(self):
        normal = AbsoluteCursor(ControlSettings(mapping="absolute", invert_x=False), Screen())
        default = AbsoluteCursor(ControlSettings(mapping="absolute"), Screen())
        previous_y = -1
        for y in (.1, .3, .5, .7, .9):
            expected = normal.map_point((.3, y), SIZE)
            actual = default.map_point((.3, y), SIZE)
            self.assertEqual(actual[1], expected[1])
            self.assertGreater(actual[1], previous_y)
            self.assertAlmostEqual(actual[0]+expected[0], 1919)
            previous_y = actual[1]

    def test_relative_default_still_matches_explicit_no_inversion(self):
        outputs = []
        for settings in (ControlSettings(alpha=1.), ControlSettings(alpha=1., invert_x=False)):
            cursor = RelativeCursor(settings, Screen())
            cursor.update((.5, .5), SIZE, (960, 540))
            outputs.append(cursor.update((.52, .52), SIZE, (0, 0)))
        self.assertEqual(outputs[0], outputs[1])
        self.assertGreater(outputs[0][0], 960)
        self.assertGreater(outputs[0][1], 540)

    def test_default_and_explicit_on_are_identical_without_double_inversion(self):
        default = AbsoluteCursor(self.configured(), Screen())
        explicit = AbsoluteCursor(self.configured(extra=["--control-invert-x"]), Screen())
        disabled = AbsoluteCursor(self.configured(extra=["--control-no-invert-x"]), Screen())
        for point in ((.1, .1), (.3, .4), (.5, .5), (.8, .7), (.9, .9)):
            actual = default.map_point(point, SIZE)
            self.assertEqual(actual, explicit.map_point(point, SIZE))
            unmirrored = disabled.map_point(point, SIZE)
            self.assertAlmostEqual(actual[0]+unmirrored[0], 1919)
            self.assertEqual(actual[1], unmirrored[1])

    def test_simulated_and_fake_win32_delivery_share_default_and_override(self):
        for override in ((), ("--control-invert-x",), ("--control-no-invert-x",)):
            for mode in ("simulate", "live"):
                with self.subTest(override=override, mode=mode):
                    settings = self.configured(mode=mode, extra=["--control-alpha", "1", *override])
                    api = FakeAPI() if mode == "live" else None
                    backend = WindowsBackend(api=api) if api else SimulationBackend()
                    h = Harness()
                    h.backend = backend
                    h.controller = DesktopController(backend, settings, clock=lambda: h.now)
                    h.controller.safety_ready = True  # Fake readiness; no real hotkey/input.
                    h.arm()
                    for dx in (0., .03, -.03):
                        _, features, _ = h.step(dx=dx)
                        tip = features[0].observation[8]
                        u, v = (tip.x-.1)/.8, (tip.y-.1)/.8
                        if settings.invert_x:
                            u = 1-u
                        expected = backend.screen.clamp(u*1919, v*1079)
                        if api:
                            packet = api.sent[-1][0].mi
                            self.assertEqual((packet.dx, packet.dy),
                                             (round((expected[0]+2560)*65535/4479),
                                              round(expected[1]*65535/1439)))
                            self.assertEqual(packet.dwFlags, 0xC001)
                        else:
                            self.assertEqual(backend.position, expected)
                    h.controller.close()

    def test_default_inverted_pinch_anchor_drag_and_release_both_modes(self):
        for mode in ("simulate", "live"):
            settings = self.configured(mode=mode, extra=["--control-mouse", "--control-alpha", "1"])
            backend = SimulationBackend()
            backend.is_live = mode == "live"  # Pure virtual sink exercising the live policy.
            h = Harness()
            h.backend = backend
            h.controller = DesktopController(backend, settings, clock=lambda: h.now)
            h.controller.safety_ready = True
            h.arm(); h.step()
            before = backend.position
            h.start()
            self.assertEqual(backend.position, before)
            self.assertEqual(backend.counts["down"], 1)
            h.step(PINCH, P.HELD, dx=.02)
            self.assertLess(backend.position[0], before[0])
            self.assertEqual(backend.position[1], before[1])
            h.step(PINCH, P.HELD, dx=.03)
            self.assertEqual(backend.counts["down"], 1)
            h.step(None, P.RELEASED, events=((PINCH, E.GESTURE_ENDED, "pinch_released"),))
            h.step(None)
            self.assertEqual(backend.counts["up"], 1)
            self.assertIsNone(h.controller.cursor.drag_offset)
            h.controller.close()


if __name__ == "__main__":
    unittest.main()
