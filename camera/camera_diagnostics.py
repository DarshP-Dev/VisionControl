"""Capture diagnostics shared by the interactive tester and headless benchmark."""

from dataclasses import dataclass
import logging
import math
import time

import cv2


LOGGER = logging.getLogger("camera_test")
BACKENDS = {"dshow": cv2.CAP_DSHOW, "msmf": cv2.CAP_MSMF}
MODES = ((1920, 1080, 60), (1920, 1080, 30), (1280, 720, 60),
         (1280, 720, 30), (640, 480, 30))


def fourcc_text(value):
    if not math.isfinite(value) or value <= 0 or value > 0xFFFFFFFF:
        return "unavailable"
    raw = int(value)
    return "".join(chr((raw >> (8 * i)) & 255) for i in range(4))


class StageTimings:
    """Keep constant-memory per-call totals and maxima, in seconds."""

    def __init__(self):
        self.stages = {}

    def add(self, name, elapsed):
        count, total, maximum = self.stages.get(name, (0, 0.0, 0.0))
        self.stages[name] = (count + 1, total + elapsed, max(maximum, elapsed))

    def report(self):
        for name, (count, total, maximum) in self.stages.items():
            LOGGER.info("Timing %s: mean %.3f ms / max %.3f ms / %d calls",
                        name, 1000 * total / count, 1000 * maximum, count)


def configure_capture(cap, args):
    LOGGER.info("Camera index: %d | selected backend: %s | requested: %dx%d @ %g FPS | FOURCC: %s",
                args.camera_index, args.backend, args.width, args.height, args.fps, args.fourcc)
    accepted = {}
    for prop, value, name in (
        (cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*args.fourcc), "FOURCC"),
        (cv2.CAP_PROP_FRAME_WIDTH, args.width, "width"),
        (cv2.CAP_PROP_FRAME_HEIGHT, args.height, "height"),
        (cv2.CAP_PROP_FPS, args.fps, "FPS"),
    ):
        try:
            accepted[name] = bool(cap.set(prop, value))
        except cv2.error as exc:
            accepted[name] = False
            LOGGER.warning("Configuration request %s raised: %s", name, exc)
        LOGGER.info("Configuration request %s=%s: OpenCV accepted=%s",
                    name, args.fourcc if name == "FOURCC" else value, accepted[name])
    LOGGER.info("Accepted requests are not proof of the applied capture mode.")
    return accepted


def capture_snapshot(cap, args, phase, dimensions=None):
    def get_property(prop):
        try:
            return cap.get(prop)
        except cv2.error as exc:
            LOGGER.warning("Property %s readback unavailable: %s", prop, exc)
            return float("nan")

    try:
        backend = cap.getBackendName()
    except cv2.error:
        backend = "unavailable"
    snapshot = {
        "backend": backend,
        "width": get_property(cv2.CAP_PROP_FRAME_WIDTH),
        "height": get_property(cv2.CAP_PROP_FRAME_HEIGHT),
        "fps": get_property(cv2.CAP_PROP_FPS),
        "fourcc": fourcc_text(get_property(cv2.CAP_PROP_FOURCC)),
    }
    LOGGER.info("%s readback: backend=%s | driver dimensions=%s x %s | "
                "driver FPS=%s | FOURCC=%r | actual frame=%s",
                phase, backend, snapshot["width"], snapshot["height"],
                snapshot["fps"], snapshot["fourcc"], dimensions or "not read yet")
    if snapshot["fourcc"] != args.fourcc:
        LOGGER.warning("Requested FOURCC %s differs from readback %r; format may be unsupported "
                       "or readback unreliable.", args.fourcc, snapshot["fourcc"])
    if dimensions is not None and dimensions != (args.width, args.height):
        LOGGER.warning("Actual frame dimensions differ from the requested mode.")
    if not math.isfinite(snapshot["fps"]) or snapshot["fps"] <= 0:
        LOGGER.warning("Driver FPS is unavailable/invalid; use measured throughput.")
    elif not math.isclose(snapshot["fps"], args.fps, rel_tol=0.01):
        LOGGER.warning("Driver FPS readback differs from requested FPS.")
    LOGGER.info("Readbacks are driver claims; FOURCC describes reported transport, "
                "while OpenCV normally returns decoded BGR frames.")
    return snapshot


@dataclass
class BenchmarkResult:
    frames: int = 0
    duration: float = 0.0
    dimensions: tuple | None = None
    snapshot: dict | None = None
    accepted: dict | None = None
    error: str | None = None

    @property
    def fps(self):
        return self.frames / self.duration if self.duration > 0 else 0.0

    def mode_status(self, args):
        snapshot = self.snapshot or {}
        driver_fps = snapshot.get("fps", float("nan"))
        agrees = (
            bool(self.accepted) and all(self.accepted.values())
            and self.dimensions == (args.width, args.height)
            and snapshot.get("fourcc") == args.fourcc
            and math.isfinite(driver_fps)
            and math.isclose(driver_fps, args.fps, rel_tol=0.01)
            and snapshot.get("backend", "").lower() == args.backend
        )
        return "readbacks agree (unverified)" if agrees else "REQUEST REJECTED / READBACK MISMATCH OR UNKNOWN"


def read_frame(cap):
    success, frame = cap.read()
    if not success or frame is None or frame.size == 0:
        raise OSError("Camera failed to return a frame")
    return frame


def benchmark(args):
    """One headless run. No frame processing or GUI; always release before return."""
    result = BenchmarkResult()
    timings = StageTimings()
    cap = None
    start = None
    try:
        cap = cv2.VideoCapture(args.camera_index, BACKENDS[args.backend])
        if not cap.isOpened():
            raise OSError(f"Cannot open camera {args.camera_index} with {args.backend}")
        result.accepted = configure_capture(cap, args)
        capture_snapshot(cap, args, "After configuration")
        LOGGER.info("Headless warm-up: %g seconds (discarded); measurement: %g seconds",
                    args.warmup, args.duration)
        warmup_end = time.perf_counter() + args.warmup
        while time.perf_counter() < warmup_end:
            frame = read_frame(cap)
            result.dimensions = (frame.shape[1], frame.shape[0])
        result.snapshot = capture_snapshot(cap, args, "After warm-up", result.dimensions)
        start = time.perf_counter()
        end = start
        while end - start < args.duration:
            before = time.perf_counter()
            frame = read_frame(cap)
            end = time.perf_counter()
            timings.add("cap.read", end - before)
            result.frames += 1
            result.duration = end - start
            dimensions = (frame.shape[1], frame.shape[0])
            if result.dimensions != dimensions:
                LOGGER.warning("Frame dimensions changed to %s during measurement", dimensions)
            result.dimensions = dimensions
        result.snapshot = capture_snapshot(cap, args, "After measurement", result.dimensions)
    except (cv2.error, OSError) as exc:
        result.error = str(exc)
        if start is not None:
            result.duration = time.perf_counter() - start
        LOGGER.error("Headless benchmark failed: %s", exc)
    finally:
        if cap is not None:
            cap.release()
    LOGGER.info("Headless capture throughput: %.2f FPS | %d frames / %.3f s | actual frame=%s | %s",
                result.fps, result.frames, result.duration, result.dimensions,
                "FAILED/PARTIAL" if result.error else "completed")
    timings.report()
    if not result.error and result.fps < args.fps * 0.8:
        LOGGER.warning("Headless throughput is below 80%% of requested FPS.")
    LOGGER.info("Headless throughput includes OpenCV read/decode/conversion and small timing overhead; "
                "it is not verified unique sensor FPS. Warm-up is excluded.")
    return result


def compare_modes(args):
    results = []
    for backend in BACKENDS:
        for fourcc in ("MJPG", "YUY2"):
            for width, height, fps in MODES:
                mode = replace_args(args, backend=backend, fourcc=fourcc,
                                    width=width, height=height, fps=fps)
                # benchmark() releases its handle in finally, including failed reads.
                results.append((mode, benchmark(mode)))
    LOGGER.info("--- Sequential headless mode comparison ---")
    for mode, result in results:
        snap = result.snapshot or {}
        LOGGER.info("%s %s %dx%d@%g -> actual=%s FOURCC=%r driverFPS=%s | %.2f FPS | %s | %s",
                    mode.backend, mode.fourcc, mode.width, mode.height, mode.fps,
                    result.dimensions, snap.get("fourcc", "unavailable"), snap.get("fps", "unavailable"),
                    result.fps, result.error or "completed", result.mode_status(mode))
    return int(any(result.error for _, result in results))


def replace_args(args, **changes):
    # argparse Namespace copy: preserve the original interactive arguments.
    from argparse import Namespace
    return Namespace(**(vars(args) | changes))
