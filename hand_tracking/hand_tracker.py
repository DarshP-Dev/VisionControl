"""Synchronous two-hand tracking with independent opt-in static and pinch recognition."""

import argparse
from collections import Counter
from contextlib import ExitStack
from dataclasses import asdict
import logging
import math
import os
import platform
from pathlib import Path
import time

import cv2

from controls import cli as control_cli
from gestures.models import ImageSize
from gestures.pinch import PinchThresholds, PinchTracker
from gestures.state_machine import GestureStateManager, StateSettings
from gestures.swipe import SwipeSettings
from gestures.static_gestures import DEFAULT_THRESHOLDS
from camera.camera_diagnostics import (
    BACKENDS, capture_snapshot, configure_capture, read_frame,
)
from .download_model import MODEL_PATH
from .gesture_debug import GestureDebug
from .gesture_preview import classify_result, prepare_features
from .gui import GuiEvents
from .performance import (
    InferenceInput, WorkloadProfile, inference_resolution, process_cpu_usage, write_report,
)
from .smoothing import DEFAULT_ALPHA, LandmarkSmoother, valid_alpha
from .tracking_utils import (
    MAX_HANDS, ONE_HAND_REFERENCE_FPS, PERFORMANCE_DROP_RATIO,
    ApplicationFPS, FrameTimestamp, PreviewRenderer, make_preview, significant_fps_drop,
)


LOGGER = logging.getLogger("hand_tracking")
WINDOW = "VisionControl - Hand Tracking"


def positive_int(value):
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return result


def nonnegative_int(value):
    result = int(value)
    if result < 0:
        raise argparse.ArgumentTypeError("must be a nonnegative integer")
    return result


def positive_float(value):
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("must be finite and positive")
    return result


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera-index", type=nonnegative_int, default=0)
    parser.add_argument("--width", type=positive_int, default=1920)
    parser.add_argument("--height", type=positive_int, default=1080)
    parser.add_argument("--fps", type=positive_float, default=60.0)
    parser.add_argument("--backend", choices=BACKENDS, default="msmf",
                        help="Windows backend (default: msmf; dshow previously measured ~5 FPS)")
    parser.add_argument("--fourcc", choices=("MJPG", "YUY2"), default="MJPG",
                        help="format request only; actual MSMF transport is unverified")
    parser.add_argument("--model", type=Path, default=MODEL_PATH,
                        help="local Hand Landmarker .task bundle")
    parser.add_argument("--inference-resolution", type=inference_resolution, default=None,
                        help="full (default), 1280x720, 960x540, 640x360 or WIDTHxHEIGHT bounds; "
                             "preserves aspect ratio, never upscales")
    parser.add_argument("--benchmark", action="store_true",
                        help="timed benchmark with warm-up excluded from measurements")
    parser.add_argument("--warmup", type=positive_float, default=3.0,
                        help="warm-up seconds for --benchmark (default: 3)")
    parser.add_argument("--duration", type=positive_float, default=30.0,
                        help="measurement seconds for --benchmark (default: 30)")
    parser.add_argument("--report", type=Path, help="write JSON profile; refuses existing files")
    parser.add_argument("--smoothing", action=argparse.BooleanOptionalAction, default=True,
                        help="enable conservative landmark EMA (default); --no-smoothing uses raw results")
    parser.add_argument("--smoothing-alpha", type=valid_alpha, default=DEFAULT_ALPHA,
                        help="current-measurement weight in (0, 1] (default: 0.75); higher reduces lag")
    parser.add_argument("--show-raw-landmarks", action="store_true",
                        help="draw raw measured points as white crosses for comparison")
    parser.add_argument("--gui-mode", choices=("auto", "waitkey", "pollkey"), default="auto",
                        help="auto uses native Win32 pollKey; waitkey preserves the earlier GUI path")
    parser.add_argument("--headless", action="store_true",
                        help="benchmark capture/inference/smoothing without rendering or GUI")
    parser.add_argument("--gestures", action=argparse.BooleanOptionalAction, default=False,
                        help="enable static gesture labels; --no-gestures preserves tracking only (default)")
    parser.add_argument("--gesture-debug", action="store_true",
                        help="requires --gestures; log numeric POINTING checks at most once every 2 seconds")
    parser.add_argument("--pinch", action="store_true", help="enable independent pinch lifecycle (default: off)")
    parser.add_argument("--pinch-debug", action="store_true", help="requires --pinch; show numeric distance/thresholds")
    parser.add_argument("--pinch-activation", type=positive_float, default=.25,
                        help="start below this normalized distance (default: 0.25 palm units)")
    parser.add_argument("--pinch-release", type=positive_float, default=.40,
                        help="release above this distance (default: 0.40; activation < release <= 2)")
    parser.add_argument("--gesture-states", action="store_true",
                        help="opt-in stabilized intent events; requires --gestures and/or --pinch")
    parser.add_argument("--gesture-event-debug", action="store_true",
                        help="requires --gesture-states; log lifecycle events (no images)")
    parser.add_argument("--gesture-activation-ms", type=nonnegative_int, default=100,
                        help="static candidate confirmation, 0-5000 ms (default: 100)")
    parser.add_argument("--gesture-transition-ms", type=nonnegative_int, default=60,
                        help="stable known static replacement before END, 0-5000 ms (default: 60)")
    parser.add_argument("--gesture-cooldown-ms", type=nonnegative_int, default=150,
                        help="same static gesture reactivation block per hand, 0-5000 ms (default: 150)")
    parser.add_argument("--gesture-update-ms", type=nonnegative_int, default=250,
                        help="pinch distance update interval; 0 disables UPDATED events (default: 250 ms)")
    parser.add_argument("--swipes", action="store_true",
                        help="requires --gestures --pinch --gesture-states; recognize horizontal palm movements")
    parser.add_argument("--swipe-debug", action="store_true", help="requires --swipes; numeric motion overlay and trail")
    parser.add_argument("--swipe-distance", type=positive_float, default=1.5, help="minimum net displacement in palm units")
    parser.add_argument("--swipe-velocity", type=positive_float, default=3., help="minimum average/recent speed in palms/s")
    parser.add_argument("--swipe-dominance", type=positive_float, default=3., help="net horizontal / total vertical travel")
    parser.add_argument("--swipe-consistency", type=positive_float, default=.85, help="net horizontal / horizontal path")
    parser.add_argument("--swipe-min-ms", type=positive_int, default=120)
    parser.add_argument("--swipe-max-ms", type=positive_int, default=600)
    parser.add_argument("--swipe-cooldown-ms", type=nonnegative_int, default=800)
    parser.add_argument("--swipe-reset-ms", type=nonnegative_int, default=250, help="eligible stationary hold before arming")
    parser.add_argument("--swipe-feedback-ms", type=nonnegative_int, default=350, help="short confirmation feedback duration")
    parser.add_argument("--swipe-max-scale-change", type=positive_float, default=.25)
    parser.add_argument("--swipe-pose", choices=("open-palm", "open-palm-or-fist"), default="open-palm")
    control_cli.add_arguments(parser)
    args = parser.parse_args(argv)
    if args.headless and not args.benchmark:
        parser.error("--headless requires --benchmark for a timed run (Ctrl+C can interrupt)")
    if args.headless and args.show_raw_landmarks:
        parser.error("--show-raw-landmarks needs a preview and cannot be used with --headless")
    if args.gesture_debug and not args.gestures:
        parser.error("--gesture-debug requires --gestures")
    if args.pinch_debug and not args.pinch:
        parser.error("--pinch-debug requires --pinch")
    try:
        PinchThresholds(args.pinch_activation, args.pinch_release)
    except ValueError as exc:
        parser.error(str(exc))
    if args.gesture_states and not (args.gestures or args.pinch):
        parser.error("--gesture-states requires --gestures and/or --pinch")
    if args.gesture_event_debug and not args.gesture_states:
        parser.error("--gesture-event-debug requires --gesture-states")
    try:
        state_settings(args)
        swipe_settings(args)
    except ValueError as exc:
        parser.error(str(exc))
    if args.swipes and not (args.gestures and args.pinch and args.gesture_states):
        parser.error("--swipes requires --gestures --pinch --gesture-states (pose eligibility, pinch safety and events)")
    if args.swipe_debug and not args.swipes:
        parser.error("--swipe-debug requires --swipes")
    control_cli.validate(parser, args)
    return args


def state_settings(args):
    return StateSettings(args.gesture_activation_ms, args.gesture_transition_ms,
                         args.gesture_cooldown_ms, args.gesture_update_ms)


def swipe_settings(args):
    return SwipeSettings(args.swipe_distance, args.swipe_velocity, args.swipe_dominance, args.swipe_consistency,
                         args.swipe_min_ms, args.swipe_max_ms, args.swipe_cooldown_ms, args.swipe_reset_ms,
                         args.swipe_feedback_ms, args.swipe_max_scale_change, args.swipe_pose)


def log_state_events(events):
    for event in events:
        motion = event.metadata.motion
        details = (f" | dx={motion.dx:.3f} dy={motion.dy:.3f} vx={motion.velocity_x:.3f} "
                   f"duration={motion.duration_ms}ms cons={motion.consistency:.3f} dom={motion.dominance:.3f}"
                   if motion is not None else "")
        LOGGER.info("%s | %s | %s | t=%d ms | %s%s%s", event.side.value, event.gesture,
                    event.event_type.value, event.timestamp_ms, event.metadata.reason,
                    " (former association)" if not event.metadata.association_current else "", details)


def create_landmarker(model_path):
    # Lazy import lets --help and missing-model diagnostics work without MediaPipe.
    import mediapipe as mp

    options = mp.tasks.vision.HandLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(
            model_asset_path=str(model_path.resolve()),
            delegate=mp.tasks.BaseOptions.Delegate.CPU,
        ),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_hands=MAX_HANDS,
    )
    return mp, mp.tasks.vision.HandLandmarker.create_from_options(options)


def process_frames(cap, landmarker, mp, args=None, report=None, controller=None):
    args = args if args is not None else parse_args([])
    if args.controls and controller is None:
        # Direct callers get the same cleanup and explicit live safety initialization as run().
        with ExitStack() as resources:
            configured_controller = control_cli.create_controller(args, resources)
            return process_frames(cap, landmarker, mp, args, report, configured_controller)
    start = time.perf_counter()
    timestamps = FrameTimestamp(start)
    fps = ApplicationFPS(start)
    measuring = not args.benchmark
    measurement_start = start if measuring else None
    measurement_end = None
    cpu_start = time.process_time() if measuring else None
    timings = WorkloadProfile(enabled=measuring)
    inference_input = InferenceInput(args.inference_resolution)
    renderer = PreviewRenderer() if not args.headless else None
    gui = GuiEvents(args.gui_mode) if not args.headless else None
    smoother = LandmarkSmoother(enabled=args.smoothing, alpha=args.smoothing_alpha)
    capture_sizes, inference_sizes, hand_counts = Counter(), Counter(), Counter()
    gesture_counts = Counter()
    gesture_image_size = None
    gesture_debug = GestureDebug() if args.gesture_debug else None
    pinch_thresholds = PinchThresholds(args.pinch_activation, args.pinch_release)
    pinch_tracker = PinchTracker(pinch_thresholds) if args.pinch else None
    pinch_counts = Counter()
    configured_swipes = swipe_settings(args)
    state_manager = (GestureStateManager(state_settings(args),
                                       swipe_settings=configured_swipes if args.swipes else None,
                                       swipe_diagnostics=args.swipe_debug) if args.gesture_states else None)
    state_counts, event_counts = Counter(), Counter()
    swipe_counts = Counter()
    frames = 0
    capture_logged = False
    warned_slow = False
    status = "stopped"
    show_help = False
    previous_frame_end = start
    LOGGER.info("Execution: %s | GUI: %s", "headless tracking" if args.headless else "preview",
                gui.metadata() if gui else "disabled (no GUI work)")
    if args.benchmark:
        LOGGER.info("Benchmark: %.1f s warm-up, then %.1f s measured %s. "
                    "Ctrl+C interrupts; Q/H work when a preview is enabled.", args.warmup, args.duration,
                    "headless tracking" if args.headless else "preview pipeline")
    try:
        while True:
            before_read = time.perf_counter()
            frame = read_frame(cap)
            after_read = time.perf_counter()
            timings.add("camera_read", after_read - before_read)
            # Never derive VIDEO timestamps from the requested or reported camera FPS.
            timestamp_ms = timestamps.next(after_read)
            rgb = inference_input.prepare(frame, timings)
            before_image = time.perf_counter()
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            before_inference = time.perf_counter()
            raw_result = landmarker.detect_for_video(image, timestamp_ms)
            after_inference = time.perf_counter()
            timings.add("mediapipe_image", before_inference - before_image)
            timings.add("inference", after_inference - before_inference)
            before_smoothing = time.perf_counter()
            result = smoother.apply(raw_result, timestamp_ms, frame.shape[:2])
            timings.add("smoothing", time.perf_counter() - before_smoothing)
            classifications = None
            pinches = None
            state_frame = None
            if args.gestures or args.pinch:
                if (gesture_image_size is None or
                        (gesture_image_size.height, gesture_image_size.width) != frame.shape[:2]):
                    gesture_image_size = ImageSize(frame.shape[1], frame.shape[0])
                prepared = [] if args.pinch or args.gesture_states else None
                if args.gestures:
                    sampled = gesture_debug is not None and gesture_debug.due(timestamp_ms)
                    shared = {"features_out": prepared} if prepared is not None else {}
                    classifications = classify_result(result, timestamp_ms, gesture_image_size, timings,
                                                      diagnostics=sampled, **shared)
                    if sampled:
                        gesture_debug.log(classifications, timestamp_ms)
                else:
                    before_features = time.perf_counter()
                    prepared = prepare_features(result, timestamp_ms, gesture_image_size)
                    timings.add("pinch_features", time.perf_counter() - before_features)
                if pinch_tracker is not None:
                    before_pinch = time.perf_counter()
                    pinches = pinch_tracker.update(tuple(prepared), timestamp_ms)
                    timings.add("pinch_processing", time.perf_counter() - before_pinch)
                if state_manager is not None:
                    before_states = time.perf_counter()
                    state_frame = state_manager.update(tuple(prepared), timestamp_ms, classifications, pinches)
                    timings.add("state_management", time.perf_counter() - before_states)
                    if args.swipes:
                        timings.add("swipe_processing", state_manager.last_swipe_seconds)
                    if args.gesture_event_debug:
                        log_state_events(state_frame.events)
            if controller is not None:
                before_controls = time.perf_counter()
                controller.update(state_frame, tuple(prepared), pinches)
                timings.add("controller_processing", time.perf_counter() - before_controls)
                if args.control_gesture_rearm:
                    timings.add("gesture_rearm", controller.last_rearm_seconds)
            if not capture_logged:
                LOGGER.info("Actual capture: %d x %d | actual inference: %d x %d",
                            frame.shape[1], frame.shape[0], rgb.shape[1], rgb.shape[0])
                capture_logged = True
            key = -1
            if not args.headless:
                preview = make_preview(frame, result, fps.current, show_help,
                                       renderer=renderer, timings=timings,
                                       raw_result=raw_result if args.show_raw_landmarks else None,
                                       gesture_results=classifications, pinch_results=pinches,
                                       pinch_thresholds=pinch_thresholds if args.pinch_debug else None,
                                       gesture_states=state_frame.hands if state_frame is not None else None,
                                       swipe_results=state_frame.motion if state_frame is not None and args.swipes else None,
                                       swipe_config=configured_swipes if args.swipe_debug else None,
                                       control_status=controller.status() if controller is not None else None)
                before_display = time.perf_counter()
                cv2.imshow(WINDOW, preview)
                before_events = time.perf_counter()
                key = gui.read_key()
                end = time.perf_counter()
                timings.add("imshow", before_events - before_display)
                timings.add(gui.api, end - before_events)
                timings.add("gui_events", end - before_events)
                timings.add("gui_total", end - before_display)
            else:
                end = time.perf_counter()
            timings.add("processing", end - after_read)
            timings.add("end_to_end", end - before_read)
            timings.add("frame_interval", end - previous_frame_end)
            previous_frame_end = end
            rate = None
            if measuring:
                frames += 1
                measurement_end = end
                capture_sizes[f"{frame.shape[1]}x{frame.shape[0]}"] += 1
                inference_sizes[f"{rgb.shape[1]}x{rgb.shape[0]}"] += 1
                hand_counts[str(min(MAX_HANDS, len(result.hand_landmarks)))] += 1
                if classifications is not None:
                    gesture_counts.update(item.gesture.value for item in classifications)
                if pinches is not None:
                    pinch_counts.update(item.status.value for item in pinches)
                if state_frame is not None:
                    state_counts.update(item.state.value for item in state_frame.hands)
                    event_counts.update(f"{item.event_type.value}:{item.gesture}" for item in state_frame.events)
                    swipe_counts.update(item.gesture for item in state_frame.motion
                                        if item is not None and item.confirmed and item.admitted)
                timings.finish_frame(min(MAX_HANDS, len(raw_result.hand_landmarks)))
                rate = fps.record(end)
            if rate is not None and not args.benchmark:
                LOGGER.info("End-to-end application FPS: %.2f | hands: %d",
                            rate, min(MAX_HANDS, len(result.hand_landmarks)))
                slow = significant_fps_drop(rate)
                if slow and not warned_slow:
                    LOGGER.warning("Significant application FPS decrease: %.2f FPS is below %.0f%% "
                                   "of the reported Phase 2.1 baseline %.2f FPS. "
                                   "Two-hand inference may cost more; inspect stage timings.",
                                   rate, PERFORMANCE_DROP_RATIO * 100, ONE_HAND_REFERENCE_FPS)
                warned_slow = slow
            if key in (ord("q"), ord("Q")):
                return 0
            if key in (ord("h"), ord("H")):
                show_help = not show_help
            if controller is not None:
                if key in (ord("a"), ord("A")):
                    controller.arm()
                elif key in (ord("d"), ord("D")):
                    controller.disarm()
            if not args.headless and cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                return 0
            if not measuring and end - start >= args.warmup:
                measuring = True
                measurement_start = end
                cpu_start = time.process_time()
                fps = ApplicationFPS(end)
                timings.enabled = True
                LOGGER.info("Warm-up complete; starting steady-state measurement.")
            elif args.benchmark and measuring and end - measurement_start >= args.duration:
                status = "completed"
                return 0
    finally:
        if controller is not None:
            controller.disarm("Tracking shutdown")
        cpu_end = time.process_time()
        cpu_wall_seconds = (max(0.0, time.perf_counter() - measurement_start)
                            if measurement_start is not None else 0.0)
        smoother.reset()
        if pinch_tracker is not None:
            pinch_tracker.reset()
        shutdown_events = state_manager.reset() if state_manager is not None else ()
        if args.gesture_event_debug:
            log_state_events(shutdown_events)
        duration = (measurement_end - measurement_start
                    if measurement_start is not None and measurement_end is not None else 0.0)
        average = frames / duration if duration > 0 else None
        resources = process_cpu_usage(max(0.0, cpu_end - cpu_start) if cpu_start is not None else 0.0,
                                      cpu_wall_seconds, frames)
        LOGGER.info("Completed frames: %d | duration: %.3f s | average application FPS: %.2f",
                    frames, duration, average or 0.0)
        timings.report()
        LOGGER.info("Process CPU: %s", resources)
        if not frames:
            LOGGER.info("No completed measured frames; FPS and percentiles are unavailable.")
        if report is not None:
            report.update({
                "status": status, "benchmark": args.benchmark,
                "frames": frames, "measurement_seconds": duration,
                "average_application_fps": average,
                "capture_resolution_frames": dict(capture_sizes),
                "inference_resolution_frames": dict(inference_sizes),
                "detected_hands_frames": dict(hand_counts),
                "warmup_seconds_requested": args.warmup if args.benchmark else 0,
                "measurement_seconds_requested": args.duration if args.benchmark else None,
                "timings": timings.summary(),
                "timings_by_detected_hands": timings.workload_summary(),
                "execution_mode": "headless_tracking" if args.headless else "preview",
                "gui": gui.metadata() if gui else {"requested": args.gui_mode, "effective": "none",
                                                  "backend": None, "fallback_reason": None},
                "resources": resources,
                "gestures": {"enabled": args.gestures,
                             "debug_enabled": args.gesture_debug,
                             "input": "smoothed" if args.smoothing else "raw",
                             "thresholds": asdict(DEFAULT_THRESHOLDS),
                             "classification_counts": dict(gesture_counts)},
                "pinch": {"enabled": args.pinch, "debug_enabled": args.pinch_debug,
                          "thresholds": asdict(pinch_thresholds), "status_counts": dict(pinch_counts),
                          "input": "smoothed" if args.smoothing else "raw",
                          "recovery": "open beyond release threshold to rearm; no release on loss"},
                "gesture_states": {"enabled": args.gesture_states, "debug_enabled": args.gesture_event_debug,
                                   "settings": asdict(state_settings(args)),
                                   "state_counts": dict(state_counts), "event_counts": dict(event_counts),
                                   "shutdown_events": [asdict(event) for event in shutdown_events],
                                   "policy": "PINCH takes precedence; UNKNOWN/unavailable cancels; no OS actions"},
                "swipes": {"enabled": args.swipes, "debug_enabled": args.swipe_debug,
                           "settings": asdict(configured_swipes), "confirmation_counts": dict(swipe_counts),
                           "coordinates": "unmirrored image: right increases x, left decreases x",
                           "event_policy": "one STARTED then ENDED at confirmation; consume STARTED once"},
                "controls": {"enabled": args.controls, "settings": asdict(control_cli.settings(args)),
                             "final_status": asdict(controller.status()) if controller is not None else None,
                             "mapping": ("absolute centered active region; smoothed physical-pixel targets"
                                         if args.control_mapping == "absolute" else
                                         "relative aspect-correct smoothed index tip; activation anchors cursor"),
                             "emergency_stop": f"{args.control_emergency_hotkey} (live only); 500 ms host-stall watchdog"},
                "latency_note": "Host read-to-processing/GUI completion only; camera/driver frame age is unknown.",
            })
        LOGGER.info("Application FPS includes capture, preparation, inference, smoothing%s; "
                    "the webcam's tested ~60 FPS does not guarantee 60 FPS tracking.",
                    " and preview/GUI" if not args.headless else " (preview/GUI disabled)")


def run(args, report=None):
    report = report if report is not None else {}
    report.update({"requested_capture": {"width": args.width, "height": args.height, "fps": args.fps,
                                         "backend": args.backend, "fourcc": args.fourcc,
                                         "camera_index": args.camera_index},
                   "inference_bounds": args.inference_resolution or "full",
                   "smoothing": {"enabled": args.smoothing, "alpha": args.smoothing_alpha,
                                 "show_raw_landmarks": args.show_raw_landmarks},
                   "execution_mode": "headless_tracking" if args.headless else "preview",
                   "gui_mode_requested": args.gui_mode,
                   "gestures_enabled": args.gestures,
                   "gesture_debug_enabled": args.gesture_debug,
                   "gesture_states_enabled": args.gesture_states,
                   "swipes_enabled": args.swipes,
                   "logical_cpu_count": os.cpu_count(),
                   "python": platform.python_version(), "opencv": cv2.__version__})
    try:
        if not args.model.is_file() or args.model.stat().st_size == 0:
            report.update(status="error", error="Model missing or empty")
            LOGGER.error("Hand Landmarker model missing or empty: %s. "
                         "Run: .\\.venv\\Scripts\\python.exe -m hand_tracking.download_model",
                         args.model)
            return 1
        with ExitStack() as resources:
            controller = control_cli.create_controller(args, resources) if args.controls else None
            mp, landmarker = create_landmarker(args.model)
            report["mediapipe"] = getattr(mp, "__version__", "unavailable")
            resources.callback(landmarker.close)
            cap = cv2.VideoCapture(args.camera_index, BACKENDS[args.backend])
            resources.callback(cap.release)
            if not cap.isOpened():
                report.update(status="error", error="Cannot open camera")
                LOGGER.error("Cannot open camera %d using %s. Check USB connection, camera "
                             "permissions and other apps, or try another --camera-index.",
                             args.camera_index, args.backend)
                return 1
            configure_capture(cap, args)
            report["driver_readback"] = capture_snapshot(cap, args, "After configuration")
            LOGGER.info("MediaPipe Hand Landmarker: VIDEO mode | CPU | maximum %d hands", MAX_HANDS)
            LOGGER.info("Landmark smoothing: %s | alpha: %.2f | raw comparison markers: %s",
                        args.smoothing, args.smoothing_alpha, args.show_raw_landmarks)
            LOGGER.info("Static gestures: %s (heuristic rules; no confidence probability)", args.gestures)
            LOGGER.info("Pinch: %s | activation < %.3f | release > %.3f | projected proximity only; "
                        "open fingers to arm/rearm after startup or loss", args.pinch,
                        args.pinch_activation, args.pinch_release)
            LOGGER.info("Gesture states: %s | settings: %s | recognition emits intent events only",
                        args.gesture_states, asdict(state_settings(args)))
            LOGGER.info("Swipes: %s | settings: %s | unmirrored image directions; separate opt-in action mapper",
                        args.swipes, asdict(swipe_settings(args)))
            LOGGER.info("Preview/input: unmirrored. Left/Right identify the subject's hands; "
                        "colors follow each frame's handedness predictions, not detection order.")
            LOGGER.info("%s No camera throughput claim is made by inference FPS.",
                        "Timed headless run; Ctrl+C interrupts." if args.headless
                        else "Q: Quit | H: Toggle help.")
            if controller is not None:
                LOGGER.info("Cursor mapping: %s | centered absolute region: %.0f%% width x %.0f%% height | invert X: %s",
                            args.control_mapping, args.control_region_width*100, args.control_region_height*100,
                            controller.settings.invert_x)
                LOGGER.info("Controls: %s | starts DISARMED | selected %s | clicks=%s tabs=%s | "
                            "A: Arm, D: Disarm, Q: Quit | live global stop: %s",
                            args.control_mode, args.control_hand, args.control_mouse, args.control_tabs,
                            args.control_emergency_hotkey)
            if not args.headless:
                cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
                resources.callback(cv2.destroyAllWindows)
            options = {"controller": controller} if controller is not None else {}
            return process_frames(cap, landmarker, mp, args=args, report=report, **options)
    except (ImportError, OSError, ValueError, RuntimeError, cv2.error) as exc:
        report.update(status="error", error=str(exc))
        LOGGER.error("Hand tracking failed: %s. Check the model and install dependencies with "
                     ".\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt", exc)
        return 1
    except KeyboardInterrupt:
        report["status"] = "interrupted"
        LOGGER.info("Hand tracking interrupted; resources released.")
        return 0


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    if args.report and args.report.exists():
        LOGGER.error("Report already exists; choose a new path: %s", args.report)
        return 1
    report = {}
    code = run(args, report)
    if args.report:
        try:
            write_report(args.report, report)
            LOGGER.info("Saved performance report: %s", args.report)
        except OSError as exc:
            LOGGER.error("Cannot save performance report: %s", exc)
            return 1
    return 130 if report.get("status") == "interrupted" else code


if __name__ == "__main__":
    raise SystemExit(main())
