"""Bounded profiling and aspect-preserving inference image preparation."""

import argparse
from collections import deque
import json
import logging
import math
from pathlib import Path
import re
import time

import cv2
import numpy as np


LOGGER = logging.getLogger("hand_tracking")
INFERENCE_MODES = ("full", "1280x720", "960x540", "640x360")


def inference_resolution(value):
    if value.lower() == "full":
        return None
    match = re.fullmatch(r"([1-9]\d*)x([1-9]\d*)", value.lower())
    if not match:
        raise argparse.ArgumentTypeError("use full or positive WIDTHxHEIGHT, e.g. 960x540")
    return tuple(map(int, match.groups()))


def fit_size(width, height, bounds):
    if width <= 0 or height <= 0 or (bounds and min(bounds) <= 0):
        raise ValueError("Image dimensions must be positive")
    if bounds is None:
        return width, height
    scale = min(bounds[0] / width, bounds[1] / height, 1.0)
    return max(1, round(width * scale)), max(1, round(height * scale))


class Profile:
    """All-run means/maxima, percentiles over the latest bounded sample window."""

    def __init__(self, enabled=True, capacity=8192):
        if capacity <= 0:
            raise ValueError("Sample capacity must be positive")
        self.enabled = enabled
        self.capacity = capacity
        self.stages = {}

    def add(self, name, seconds):
        if not self.enabled:
            return
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Timing must be finite and nonnegative")
        if name not in self.stages:
            self.stages[name] = {
                "count": 0, "total": 0.0, "max": 0.0, "samples": deque(maxlen=self.capacity),
            }
        stage = self.stages[name]
        stage["count"] += 1
        stage["total"] += seconds
        stage["max"] = max(stage["max"], seconds)
        stage["samples"].append(seconds)

    def summary(self):
        output = {}
        for name, stage in self.stages.items():
            percentiles = np.percentile(stage["samples"], [50, 95, 99]) * 1000
            output[name] = {
                "count": stage["count"], "percentile_samples": len(stage["samples"]),
                "mean_ms": 1000 * stage["total"] / stage["count"],
                "max_ms": 1000 * stage["max"],
                "p50_ms": float(percentiles[0]), "p95_ms": float(percentiles[1]),
                "p99_ms": float(percentiles[2]),
            }
        return output

    def report(self):
        for name, stage in self.summary().items():
            LOGGER.info("Timing %s: mean %.3f / p50 %.3f / p95 %.3f / p99 %.3f / max %.3f ms "
                        "(%d calls; percentiles use last %d)", name, stage["mean_ms"],
                        stage["p50_ms"], stage["p95_ms"], stage["p99_ms"], stage["max_ms"],
                        stage["count"], stage["percentile_samples"])


class WorkloadProfile(Profile):
    """Stratify completed-frame timings by observed 0/1/2-hand model results."""

    def __init__(self, enabled=True, capacity=8192):
        super().__init__(enabled, capacity)
        self.by_hands = {}

    def finish_frame(self, hand_count):
        if not self.enabled:
            return
        if hand_count not in self.by_hands:
            self.by_hands[hand_count] = Profile(capacity=self.capacity)
        group = self.by_hands[hand_count]
        for name in ("camera_read", "inference_resize", "bgr_to_rgb", "mediapipe_image",
                     "inference", "smoothing", "preview_resize", "landmark_drawing",
                     "text_overlay", "imshow", "gui_events", "gui_total",
                     "processing", "end_to_end", "frame_interval"):
            if name in self.stages:
                group.add(name, self.stages[name]["samples"][-1])

    def workload_summary(self):
        return {str(count): profile.summary() for count, profile in self.by_hands.items()}

    def report(self):
        super().report()
        for count, stages in self.workload_summary().items():
            def text(name):
                stage = stages.get(name)
                return (f"{stage['mean_ms']:.3f}/{stage['p95_ms']:.3f} ms"
                        if stage else "not measured")

            LOGGER.info("Observed %s hand(s), mean/p95: inference %s | GUI %s | loop %s",
                        count, text("inference"), text("gui_total"), text("end_to_end"))


def process_cpu_usage(cpu_seconds, wall_seconds, frames):
    """Whole-process CPU time, including native threads; 100% means one core."""
    return {"process_cpu_seconds": cpu_seconds, "process_wall_seconds": wall_seconds,
            "process_cpu_percent_of_one_core": 100 * cpu_seconds / wall_seconds if wall_seconds > 0 else None,
            "process_cpu_ms_per_frame": 1000 * cpu_seconds / frames if frames > 0 else None}


class InferenceInput:
    """Resize BGR before conversion; reuse buffers, never crop/pad/stretch/upscale."""

    def __init__(self, bounds=None):
        self.bounds = bounds
        self.resized = None
        self.rgb = None

    def prepare(self, frame, profile):
        start = time.perf_counter()
        width, height = fit_size(frame.shape[1], frame.shape[0], self.bounds)
        shape = (height, width, 3)
        if self.rgb is None or self.rgb.shape != shape or self.rgb.dtype != frame.dtype:
            self.rgb = np.empty(shape, dtype=frame.dtype)
            self.resized = None
        source = frame
        if (width, height) != (frame.shape[1], frame.shape[0]):
            if self.resized is None:
                self.resized = np.empty(shape, dtype=frame.dtype)
            source = cv2.resize(frame, (width, height), dst=self.resized, interpolation=cv2.INTER_AREA)
        converted = time.perf_counter()
        profile.add("inference_resize", converted - start)
        cv2.cvtColor(source, cv2.COLOR_BGR2RGB, dst=self.rgb)
        profile.add("bgr_to_rgb", time.perf_counter() - converted)
        return self.rgb


def write_report(path, report):
    def finite(value):
        if isinstance(value, dict):
            return {key: finite(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [finite(item) for item in value]
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects earlier benchmark results from accidental overwrite.
    with path.open("x", encoding="utf-8") as output:
        json.dump(finite(report), output, indent=2, allow_nan=False)
        output.write("\n")
