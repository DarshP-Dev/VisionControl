"""Controls CLI dependencies and lazy, explicit resource setup."""

from .backends import SimulationBackend
from .controller import DesktopController
from .models import ControlSettings, Screen
from .hotkeys import DEFAULT_EMERGENCY_HOTKEY
from gestures.models import HandSide


def add_arguments(parser):
    parser.add_argument("--controls", action="store_true", help="opt-in desktop mapper; starts DISARMED")
    parser.add_argument("--control-mode", choices=("simulate", "live"), default="simulate")
    parser.add_argument("--control-gesture-profile", choices=("legacy", "palm-cursor"), default="legacy")
    parser.add_argument("--control-cursor-resume", choices=("automatic", "left-pinch"), default="automatic",
                        help="palm-cursor resume; left-pinch requires --control-gesture-rearm")
    parser.add_argument("--control-emergency-hotkey", default=DEFAULT_EMERGENCY_HOTKEY,
                        help="live global stop: ctrl+alt+esc (default) or ctrl+shift+f9/f10/f11; case-insensitive")
    parser.add_argument("--control-mapping", choices=("relative", "absolute"), default="relative")
    parser.add_argument("--control-region-width", type=float, default=.80,
                        help="absolute mapping: centered frame-width fraction (0,1]")
    parser.add_argument("--control-region-height", type=float, default=.80,
                        help="absolute mapping: centered frame-height fraction (0,1]")
    parser.add_argument("--control-hand", choices=("left", "right"), default="right")
    parser.add_argument("--control-gesture-rearm", action="store_true",
                        help="opt-in Left pinch rearm after routine loss; Right control and initial A required")
    parser.add_argument("--control-rearm-hold-ms", type=int, default=800, help="Left pinch hold [500,3000] ms")
    parser.add_argument("--control-rearm-stable-ms", type=int, default=300,
                        help="stable confident two-hand association [150,2000] ms before fresh Left OPEN")
    parser.add_argument("--control-rearm-debug", action="store_true", help="sample rearm diagnostics at most every 2 s")
    parser.add_argument("--control-mouse", action="store_true", help="enable pinch click/drag (default: cursor only)")
    parser.add_argument("--control-tabs", action="store_true", help="enable confirmed swipe-to-tab actions (default: off)")
    parser.add_argument("--control-sensitivity", type=float, default=1.5)
    parser.add_argument("--control-alpha", type=float, default=.6, help="screen-space EMA current weight [.01,1]")
    parser.add_argument("--control-margin", type=float, default=.10, help="relative mapping: image edge margin [0,.4]")
    inversion = parser.add_mutually_exclusive_group()
    inversion.add_argument("--control-invert-x", dest="control_invert_x", action="store_true", default=None,
                           help="enable X inversion (default: on for absolute, off for relative); Y unchanged")
    inversion.add_argument("--control-no-invert-x", dest="control_invert_x", action="store_false", default=None,
                           help="disable X inversion explicitly, including in absolute mode; Y unchanged")
    parser.add_argument("--control-monitor", type=int, default=0, help="live physical monitor index; 0 is primary")
    parser.add_argument("--control-sim-size", default="1920x1080", help="simulated physical screen WIDTHxHEIGHT")
    parser.add_argument("--control-sim-app", default="chrome.exe", help="simulated foreground executable basename")
    parser.add_argument("--control-browser", action="append", help="permitted browser .exe basename; repeat to replace defaults")
    parser.add_argument("--control-debug", action="store_true", help="sample control diagnostics at most every 2 seconds")


def simulation_screen(args):
    try:
        width, height = (int(v) for v in args.control_sim_size.lower().split("x"))
        return Screen(width=width, height=height)
    except (TypeError, ValueError):
        raise ValueError("--control-sim-size requires WIDTHxHEIGHT, both at least 2") from None


def settings(args):
    return ControlSettings(args.control_mode, HandSide(args.control_hand.title()), args.control_mouse,
                           args.control_tabs, args.control_sensitivity, args.control_alpha, args.control_margin,
                           args.control_monitor, args.control_debug,
                           tuple(s.casefold() for s in args.control_browser) if args.control_browser else
                           ("chrome.exe", "msedge.exe", "firefox.exe"), invert_x=args.control_invert_x,
                           mapping=args.control_mapping, region_width=args.control_region_width,
                           region_height=args.control_region_height, emergency_hotkey=args.control_emergency_hotkey,
                           gesture_rearm=args.control_gesture_rearm, rearm_hold_ms=args.control_rearm_hold_ms,
                           rearm_stable_ms=args.control_rearm_stable_ms, rearm_debug=args.control_rearm_debug,
                           gesture_profile=args.control_gesture_profile, cursor_resume=args.control_cursor_resume)


def validate(parser, args):
    try:
        configured = settings(args)
        args.control_emergency_hotkey = configured.emergency_hotkey
        simulation_screen(args)
    except ValueError as exc:
        parser.error(str(exc))
    if not args.controls and (args.control_gesture_profile != "legacy" or args.control_cursor_resume != "automatic"):
        parser.error("Control profile/resume options require --controls")
    if args.controls:
        if configured.gesture_profile == "palm-cursor" and args.swipe_pose != "pointing":
            parser.error("Palm cursor requires POINTING swipe eligibility; omit --swipe-pose or use pointing")
        if configured.gesture_profile == "legacy" and args.swipe_pose == "pointing":
            parser.error("POINTING swipes with controls require --control-gesture-profile palm-cursor")
    if args.control_gesture_rearm and not args.controls:
        parser.error("--control-gesture-rearm requires --controls --gestures --pinch --gesture-states")
    if not args.control_gesture_rearm and (args.control_rearm_debug or args.control_rearm_hold_ms != 800
                                         or args.control_rearm_stable_ms != 300):
        parser.error("--control-rearm-* options require --control-gesture-rearm")
    if args.control_invert_x is not None and not args.controls:
        parser.error("--control-invert-x/--control-no-invert-x require --controls")
    if not args.controls and (args.control_mapping != "relative" or args.control_region_width != .80
                              or args.control_region_height != .80):
        parser.error("Absolute mapping/region options require --controls")
    if not args.controls and (args.control_mode != "simulate" or args.control_mouse or args.control_tabs or args.control_debug):
        parser.error("--control-mode live/--control-mouse/--control-tabs/--control-debug require --controls")
    if args.controls:
        if not (args.gestures and args.pinch and args.gesture_states):
            parser.error("--controls requires explicit --gestures --pinch --gesture-states")
        if args.headless:
            parser.error("--controls requires a visible preview for status and explicit A/D arming")
        if not args.smoothing:
            parser.error("--controls requires landmark smoothing; remove --no-smoothing")
        if args.smoothing_alpha == 1 and args.control_alpha == 1:
            parser.error("--controls requires smoothing: keep landmark or cursor alpha below 1")
        if args.control_tabs and not args.swipes:
            parser.error("--control-tabs requires explicit --swipes")
        if args.control_mode == "simulate" and args.control_monitor != 0:
            parser.error("Simulation has one virtual monitor; use --control-sim-size")


def create_controller(args, resources):
    configured = settings(args)
    if configured.mode == "simulate":
        backend = SimulationBackend(simulation_screen(args), args.control_sim_app)
    else:
        from .windows import WindowsBackend
        backend = WindowsBackend(configured.monitor)
    resources.callback(backend.close)
    controller = DesktopController(backend, configured)
    resources.callback(controller.close)
    if configured.mode == "live":
        from .safety import GlobalSafety
        safety = GlobalSafety(controller, backend.api)
        resources.callback(safety.close)
        safety.start()  # Fails closed before camera/model/window setup.
    return controller
