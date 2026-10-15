"""Phase 2.1: one-hand MediaPipe Tasks tracking with a synchronous webcam preview."""

import argparse
from contextlib import ExitStack
import logging
import math
from pathlib import Path
import time

import cv2

from camera.camera_diagnostics import (
    BACKENDS, StageTimings, capture_snapshot, configure_capture, read_frame,
)
from .download_model import MODEL_PATH
from .tracking_utils import ApplicationFPS, FrameTimestamp, make_preview


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
    return parser.parse_args(argv)


def create_landmarker(model_path):
    # Lazy import lets --help and missing-model diagnostics work without MediaPipe.
    import mediapipe as mp

    options = mp.tasks.vision.HandLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(
            model_asset_path=str(model_path.resolve()),
            delegate=mp.tasks.BaseOptions.Delegate.CPU,
        ),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_hands=1,
    )
    return mp, mp.tasks.vision.HandLandmarker.create_from_options(options)


def process_frames(cap, landmarker, mp):
    start = time.perf_counter()
    timestamps = FrameTimestamp(start)
    fps = ApplicationFPS(start)
    timings = StageTimings()
    show_help = False
    try:
        while True:
            before_read = time.perf_counter()
            frame = read_frame(cap)
            after_read = time.perf_counter()
            timings.add("cap.read", after_read - before_read)
            # Never derive VIDEO timestamps from the requested or reported camera FPS.
            timestamp_ms = timestamps.next(after_read)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = landmarker.detect_for_video(image, timestamp_ms)
            after_inference = time.perf_counter()
            timings.add("RGB conversion + inference", after_inference - after_read)
            if fps.frames == 0:
                LOGGER.info("Actual captured frame: %d x %d", frame.shape[1], frame.shape[0])
            preview = make_preview(frame, result, fps.current, show_help)
            cv2.imshow(WINDOW, preview)
            key = cv2.waitKey(1) & 0xFF
            end = time.perf_counter()
            timings.add("preview + GUI", end - after_inference)
            rate = fps.record(end)
            if rate is not None:
                LOGGER.info("End-to-end application FPS: %.2f | hands: %d",
                            rate, min(1, len(result.hand_landmarks)))
            if key in (ord("q"), ord("Q")):
                return 0
            if key in (ord("h"), ord("H")):
                show_help = not show_help
            if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                return 0
    finally:
        end = time.perf_counter()
        LOGGER.info("Completed frames: %d | duration: %.3f s | average application FPS: %.2f",
                    fps.frames, end - start, fps.average(end))
        timings.report()
        LOGGER.info("Application FPS includes capture, RGB conversion, inference and preview; "
                    "the webcam's tested ~60 FPS does not guarantee 60 FPS tracking.")


def run(args):
    try:
        if not args.model.is_file() or args.model.stat().st_size == 0:
            LOGGER.error("Hand Landmarker model missing or empty: %s. "
                         "Run: .\\.venv\\Scripts\\python.exe -m hand_tracking.download_model",
                         args.model)
            return 1
        with ExitStack() as resources:
            mp, landmarker = create_landmarker(args.model)
            resources.callback(landmarker.close)
            cap = cv2.VideoCapture(args.camera_index, BACKENDS[args.backend])
            resources.callback(cap.release)
            if not cap.isOpened():
                LOGGER.error("Cannot open camera %d using %s. Check USB connection, camera "
                             "permissions and other apps, or try another --camera-index.",
                             args.camera_index, args.backend)
                return 1
            configure_capture(cap, args)
            capture_snapshot(cap, args, "After configuration")
            LOGGER.info("MediaPipe Hand Landmarker: VIDEO mode | CPU | maximum one hand")
            LOGGER.info("Q: Quit | H: Toggle help. No camera throughput claim is made by inference FPS.")
            cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
            resources.callback(cv2.destroyAllWindows)
            return process_frames(cap, landmarker, mp)
    except (ImportError, OSError, ValueError, RuntimeError, cv2.error) as exc:
        LOGGER.error("Hand tracking failed: %s. Check the model and install dependencies with "
                     ".\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt", exc)
        return 1
    except KeyboardInterrupt:
        LOGGER.info("Hand tracking interrupted; resources released.")
        return 0


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
