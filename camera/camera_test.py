"""Phase 1 webcam preview and application capture-rate measurements."""

import argparse
from collections import Counter
from datetime import datetime
import logging
import math
from pathlib import Path
import time

import cv2

from camera_diagnostics import (
    BACKENDS, StageTimings, benchmark, capture_snapshot, compare_modes,
    configure_capture,
)


LOGGER = logging.getLogger("camera_test")
WINDOW = "VisionControl - Camera Test"
CAPTURES = Path(__file__).resolve().parent / "captures"
MEASUREMENT_SECONDS = 2.0
DROP_RATIO = 0.80


def positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def camera_index(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("camera index must be nonnegative")
    return number


def positive_float(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return number


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera-index", type=camera_index, default=0)
    parser.add_argument("--width", type=positive_int, default=1920)
    parser.add_argument("--height", type=positive_int, default=1080)
    parser.add_argument("--fps", type=positive_float, default=60.0)
    parser.add_argument("--backend", choices=BACKENDS, default="msmf",
                        help="Windows capture backend (default: msmf; DirectShow: dshow)")
    parser.add_argument("--fourcc", choices=("MJPG", "YUY2"), default="MJPG")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--benchmark", action="store_true", help="headless capture throughput test")
    modes.add_argument("--compare-modes", action="store_true",
                       help="headless test of all 5 modes, 2 formats and 2 backends sequentially")
    parser.add_argument("--warmup", type=positive_float, default=3.0,
                        help="discarded warm-up seconds for headless tests (default: 3)")
    parser.add_argument("--duration", type=positive_float, default=10.0,
                        help="measured seconds per headless test (default: 10)")
    parser.add_argument("--log-file", type=Path, help="also write diagnostics to this file (append)")
    return parser.parse_args(argv)


def fps_text(value):
    if not math.isfinite(value) or value <= 0:
        return "unavailable (driver returned zero, negative, or non-finite FPS)"
    return f"{value:.2f} (driver claim; may be inaccurate)"


class CaptureStats:
    """Count successful reads; window rates include preview and saving overhead."""

    def __init__(self, start):
        self.start = start
        self.window_start = start
        self.frames = 0
        self.window_frames = 0
        self.window_rates = []
        self.resolutions = Counter()

    def record(self, now, width, height):
        self.frames += 1
        self.window_frames += 1
        self.resolutions[(width, height)] += 1
        elapsed = now - self.window_start
        if elapsed < MEASUREMENT_SECONDS:
            return None
        rate = self.window_frames / elapsed
        self.window_rates.append(rate)
        self.window_start = now
        self.window_frames = 0
        return rate

    def average(self, end):
        duration = end - self.start
        return self.frames / duration if duration > 0 else 0.0


def save_screenshot(frame, directory=CAPTURES):
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = directory / f"camera_{stamp}.png"
    # Exclusive creation prevents even an unlikely timestamp collision overwrite.
    success, encoded = cv2.imencode(".png", frame)
    if not success:
        raise OSError("OpenCV could not encode the screenshot")
    with path.open("xb") as output:
        output.write(encoded.tobytes())
    return path


def preview_frame(frame, args, driver_fps, measured, show_help, timings=None):
    resize_start = time.perf_counter()
    height, width = frame.shape[:2]
    scale = min(1100 / width, 650 / height, 1.0)
    preview = cv2.resize(frame, (max(1, round(width * scale)),
                                 max(1, round(height * scale))))
    overlay_start = time.perf_counter()
    if timings is not None:
        timings.add("resize", overlay_start - resize_start)
    if show_help:
        rate = "--" if measured is None else f"{measured:.1f}"
        text = f"FPS: {rate} | {width} x {height}"
        font = cv2.FONT_HERSHEY_SIMPLEX
        padding = 8
        font_scale = 0.55
        (text_width, _), _ = cv2.getTextSize(text, font, font_scale, 1)
        font_scale *= min(1.0, max(1, preview.shape[1] - 2 * padding) / text_width)
        (text_width, text_height), baseline = cv2.getTextSize(text, font, font_scale, 1)
        # Cover only the text and its padding, leaving the rest of the feed visible.
        preview[:text_height + baseline + 2 * padding, :text_width + 2 * padding] = 0
        cv2.putText(preview, text, (padding, padding + text_height), font,
                    font_scale, (255, 255, 255), 1, cv2.LINE_AA)
    if timings is not None:
        timings.add("overlay", time.perf_counter() - overlay_start)
    return preview


def print_summary(args, stats, driver_fps, end):
    resolutions = ", ".join(
        f"{width} x {height} ({count} frames)"
        for (width, height), count in stats.resolutions.items()
    ) or "unavailable (no frames captured)"
    LOGGER.info("--- Camera test summary ---")
    LOGGER.info("Requested: %d x %d at %g FPS", args.width, args.height, args.fps)
    LOGGER.info("Actual captured dimensions: %s", resolutions)
    LOGGER.info("Driver-reported FPS: %s", fps_text(driver_fps))
    LOGGER.info("Average application preview-loop FPS: %.2f (not isolated capture throughput)",
                stats.average(end))
    if stats.window_rates:
        LOGGER.info("Measurement-window FPS: min %.2f / max %.2f (%d windows)",
                    min(stats.window_rates), max(stats.window_rates),
                    len(stats.window_rates))
    else:
        LOGGER.info("Measurement-window FPS: min/max unavailable (test shorter than 2 seconds)")
    LOGGER.info("Total testing duration: %.2f seconds", max(0.0, end - stats.start))
    LOGGER.info("Frames captured: %d", stats.frames)
    LOGGER.info("Rates count successful reads, not verified unique sensor exposures. "
                "Preview, saving, lighting, buffering and driver behavior can affect results.")


def run(args):
    cap = None
    stats = None
    driver_fps = float("nan")
    exit_code = 0
    timings = StageTimings()
    try:
        CAPTURES.mkdir(parents=True, exist_ok=True)
        cap = cv2.VideoCapture(args.camera_index, BACKENDS[args.backend])
        if not cap.isOpened():
            LOGGER.error("Cannot open camera index %d with backend %s. "
                         "Check the USB connection, Windows camera permissions, "
                         "other apps using the camera, or try --camera-index 1.",
                         args.camera_index, args.backend)
            return 1

        configure_capture(cap, args)
        snapshot = capture_snapshot(cap, args, "After configuration")
        driver_fps = snapshot["fps"]
        LOGGER.info("Application FPS includes read/preview/save overhead; it does not prove sensor FPS.")
        LOGGER.info("S: save full-resolution PNG | Q: quit | H: toggle FPS/resolution overlay")
        cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
        stats = CaptureStats(time.perf_counter())
        measured = None
        show_help = True
        while True:
            read_start = time.perf_counter()
            success, frame = cap.read()
            read_end = time.perf_counter()
            timings.add("cap.read", read_end - read_start)
            if not success or frame is None or frame.size == 0:
                LOGGER.error("Camera failed to return a frame. Ending test.")
                exit_code = 1
                break
            height, width = frame.shape[:2]
            new_resolution = (width, height) not in stats.resolutions
            window_rate = stats.record(time.perf_counter(), width, height)
            if new_resolution:
                LOGGER.info("Captured frame dimensions: %d x %d", width, height)
                snapshot = capture_snapshot(cap, args, "After frame read", (width, height))
                driver_fps = snapshot["fps"]
                if (width, height) != (args.width, args.height):
                    LOGGER.warning("Captured dimensions differ from the requested resolution.")
            if window_rate is not None:
                measured = window_rate
                LOGGER.info("Application preview loop: %.2f FPS | requested: %g | driver: %s",
                            measured, args.fps, fps_text(driver_fps))
                timings.report()
                if measured < args.fps * DROP_RATIO:
                    LOGGER.warning("Significant FPS shortfall: below 80%% of requested FPS.")
            preview = preview_frame(frame, args, driver_fps, measured, show_help, timings)
            display_start = time.perf_counter()
            cv2.imshow(WINDOW, preview)
            wait_start = time.perf_counter()
            key = cv2.waitKey(1) & 0xFF
            wait_end = time.perf_counter()
            timings.add("imshow", wait_start - display_start)
            timings.add("waitKey", wait_end - wait_start)
            if key in (ord("q"), ord("Q")):
                break
            if key in (ord("h"), ord("H")):
                show_help = not show_help
            if key in (ord("s"), ord("S")):
                try:
                    path = save_screenshot(frame)
                    LOGGER.info("Saved %d x %d screenshot: %s", width, height, path)
                except (OSError, cv2.error) as exc:
                    LOGGER.error("Screenshot could not be saved: %s", exc)
            if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                break
    except KeyboardInterrupt:
        LOGGER.info("Test interrupted.")
    except (cv2.error, OSError) as exc:
        LOGGER.error("Camera test failed: %s", exc)
        exit_code = 1
    finally:
        end = time.perf_counter()
        if cap is not None:
            cap.release()
        cv2.destroyAllWindows()
        if stats is not None:
            print_summary(args, stats, driver_fps, end)
            timings.report()
    return exit_code


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    if args.log_file:
        try:
            args.log_file.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(args.log_file, mode="a", encoding="utf-8")
        except OSError as exc:
            LOGGER.error("Cannot open diagnostic log: %s", exc)
            return 1
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
        LOGGER.addHandler(handler)
    else:
        handler = None
    try:
        if args.compare_modes:
            return compare_modes(args)
        if args.benchmark:
            return int(benchmark(args).error is not None)
        return run(args)
    except KeyboardInterrupt:
        LOGGER.info("Diagnostics interrupted; camera released. Remaining comparisons cancelled.")
        return 130
    finally:
        if handler is not None:
            LOGGER.removeHandler(handler)
            handler.close()


if __name__ == "__main__":
    raise SystemExit(main())
