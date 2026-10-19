"""Synchronous two-hand tracking with optional Phase 3.2 static gesture labels."""

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

from gestures.models import ImageSize
from gestures.static_gestures import DEFAULT_THRESHOLDS
from camera.camera_diagnostics import (
    BACKENDS, capture_snapshot, configure_capture, read_frame,
)
from .download_model import MODEL_PATH
from .gesture_debug import GestureDebug
from .gesture_preview import classify_result
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
    args = parser.parse_args(argv)
    if args.headless and not args.benchmark:
        parser.error("--headless requires --benchmark for a timed run (Ctrl+C can interrupt)")
    if args.headless and args.show_raw_landmarks:
        parser.error("--show-raw-landmarks needs a preview and cannot be used with --headless")
    if args.gesture_debug and not args.gestures:
        parser.error("--gesture-debug requires --gestures")
    return args


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


def process_frames(cap, landmarker, mp, args=None, report=None):
    args = args if args is not None else parse_args([])
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
            if args.gestures:
                if (gesture_image_size is None or
                        (gesture_image_size.height, gesture_image_size.width) != frame.shape[:2]):
                    gesture_image_size = ImageSize(frame.shape[1], frame.shape[0])
                sampled = gesture_debug is not None and gesture_debug.due(timestamp_ms)
                classifications = classify_result(result, timestamp_ms, gesture_image_size, timings,
                                                  diagnostics=sampled)
                if sampled:
                    gesture_debug.log(classifications, timestamp_ms)
            if not capture_logged:
                LOGGER.info("Actual capture: %d x %d | actual inference: %d x %d",
                            frame.shape[1], frame.shape[0], rgb.shape[1], rgb.shape[0])
                capture_logged = True
            key = -1
            if not args.headless:
                preview = make_preview(frame, result, fps.current, show_help,
                                       renderer=renderer, timings=timings,
                                       raw_result=raw_result if args.show_raw_landmarks else None,
                                       gesture_results=classifications)
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
        cpu_end = time.process_time()
        cpu_wall_seconds = (max(0.0, time.perf_counter() - measurement_start)
                            if measurement_start is not None else 0.0)
        smoother.reset()
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
            LOGGER.info("Preview/input: unmirrored. Left/Right identify the subject's hands; "
                        "colors follow each frame's handedness predictions, not detection order.")
            LOGGER.info("%s No camera throughput claim is made by inference FPS.",
                        "Timed headless run; Ctrl+C interrupts." if args.headless
                        else "Q: Quit | H: Toggle help.")
            if not args.headless:
                cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
                resources.callback(cv2.destroyAllWindows)
            return process_frames(cap, landmarker, mp, args=args, report=report)
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
