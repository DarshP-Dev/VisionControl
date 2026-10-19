"""Small timing and drawing helpers independent of the MediaPipe runtime."""

import math
from dataclasses import dataclass
import time
from typing import TYPE_CHECKING

import cv2
import numpy as np

if TYPE_CHECKING:
    from gestures.pinch import PinchResult
    from gestures.events import HandState


MAX_HANDS = 2
HAND_COLORS = {"Left": (80, 220, 80), "Right": (255, 160, 60), "Unknown": (180, 180, 180)}
ALTERNATE_COLOR = (200, 80, 220)
ONE_HAND_REFERENCE_FPS = 35.81
PERFORMANCE_DROP_RATIO = 0.75
PINCH_COLORS = {"OPEN": (180, 180, 180), "STARTED": (0, 255, 255),
                "HELD": (80, 255, 80), "RELEASED": (0, 160, 255), "UNAVAILABLE": (180, 100, 220)}


# MediaPipe's 21-landmark hand topology: wrist, fingers and palm edges.
HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (0, 17), (17, 18), (18, 19), (19, 20),
)


class FrameTimestamp:
    """Elapsed monotonic milliseconds, strictly increasing even within one ms."""

    def __init__(self, start):
        self.start = start
        self.previous = -1

    def next(self, now):
        self.previous = max(0, int((now - self.start) * 1000), self.previous + 1)
        return self.previous


class ApplicationFPS:
    """Count completed read/inference/render/event-pump iterations."""

    def __init__(self, start):
        self.start = start
        self.window_start = start
        self.frames = 0
        self.window_frames = 0
        self.current = None

    def record(self, end):
        self.frames += 1
        self.window_frames += 1
        elapsed = end - self.window_start
        if elapsed >= 2.0:
            self.current = self.window_frames / elapsed
            self.window_frames = 0
            self.window_start = end
            return self.current
        return None

    def average(self, end):
        duration = end - self.start
        return self.frames / duration if duration > 0 else 0.0


def landmark_pixels(landmarks, width, height):
    """Map normalized coordinates onto the actual displayed image, clipping edges."""
    if width <= 0 or height <= 0:
        raise ValueError("Display dimensions must be positive")
    points = []
    for point in landmarks:
        if not math.isfinite(point.x) or not math.isfinite(point.y):
            raise ValueError("Landmark coordinates must be finite")
        points.append((round(max(0.0, min(1.0, point.x)) * (width - 1)),
                       round(max(0.0, min(1.0, point.y)) * (height - 1))))
    return points


@dataclass
class HandOverlay:
    label: str
    color: tuple
    points: list
    gesture: str | None = None
    pinch: "PinchResult | None" = None
    stabilized: "HandState | None" = None


def handedness_label(categories):
    """Current Tasks labels use the subject's hands for our unmirrored input.

    This is not the legacy mp.solutions.hands mirrored-input convention.
    Missing/unrecognized predictions remain Unknown instead of inventing a side.
    """
    candidates = [category for category in categories
                  if getattr(category, "score", None) is not None
                  and math.isfinite(category.score)]
    if not candidates:
        return "Unknown"
    category = max(candidates, key=lambda item: item.score)
    name = getattr(category, "category_name", None)
    return name if name in ("Left", "Right") else "Unknown"


def hand_overlays(result, width, height, gesture_results=None, pinch_results=None, gesture_states=None):
    """Pair landmarks and handedness within this result only; retain no track IDs."""
    overlays = []
    handedness = getattr(result, "handedness", None) or []
    used_colors = set()
    for index, landmarks in enumerate((getattr(result, "hand_landmarks", None) or [])[:MAX_HANDS]):
        if not landmarks or len(landmarks) != 21:
            continue
        try:
            points = landmark_pixels(landmarks, width, height)
        except ValueError:
            continue
        categories = handedness[index] if index < len(handedness) else []
        label = handedness_label(categories or [])
        color = HAND_COLORS[label]
        # Do not collapse two detections when the model predicts the same side.
        if color in used_colors:
            color = ALTERNATE_COLOR
        used_colors.add(color)
        gesture = None
        if gesture_results is not None:
            gesture = (gesture_results[index].gesture.value if index < len(gesture_results)
                       else "UNKNOWN")
        pinch = pinch_results[index] if pinch_results is not None and index < len(pinch_results) else None
        stabilized = gesture_states[index] if gesture_states is not None and index < len(gesture_states) else None
        overlays.append(HandOverlay(label, color, points, gesture, pinch, stabilized))
    return overlays


def draw_hand(preview, hand, top_margin=27, pinch_thresholds=None):
    """Shared drawing path for either hand, with a label close to its wrist."""
    for start, end in HAND_CONNECTIONS:
        cv2.line(preview, hand.points[start], hand.points[end], hand.color, 2, cv2.LINE_AA)
    for point in hand.points:
        cv2.circle(preview, point, 4, (0, 0, 0), -1, cv2.LINE_AA)
        cv2.circle(preview, point, 3, hand.color, -1, cv2.LINE_AA)
    text = f"{hand.label} - {hand.gesture}" if hand.gesture is not None else f"{hand.label} hand"
    if hand.pinch is not None:
        status = hand.pinch.status.value
        text += f" | Pinch: {status}"
        color = PINCH_COLORS[status]
        cv2.line(preview, hand.points[4], hand.points[8], color, 2, cv2.LINE_AA)
        for index in (4, 8):
            cv2.circle(preview, hand.points[index], 7, (0, 0, 0), -1, cv2.LINE_AA)
            cv2.circle(preview, hand.points[index], 5, color, -1, cv2.LINE_AA)
    (width, height), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
    x = max(4, min(hand.points[0][0] + 8, preview.shape[1] - width - 5))
    diagnostic_row = 23 if hand.pinch is not None and pinch_thresholds is not None else 0
    state_row = 23 if hand.stabilized is not None else 0
    y = max(top_margin + height + 4,
            min(hand.points[0][1] + 22, preview.shape[0] - baseline - 5 - diagnostic_row - state_row))
    cv2.rectangle(preview, (x - 3, y - height - 3), (x + width + 3, y + baseline + 3),
                  (0, 0, 0), -1)
    cv2.putText(preview, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                0.55, hand.color, 1, cv2.LINE_AA)
    if diagnostic_row:
        measurement = hand.pinch.measurement
        distance = "--" if measurement.normalized_distance is None else f"{measurement.normalized_distance:.3f}"
        debug = (f"d={distance} A<{pinch_thresholds.activation:g} R>{pinch_thresholds.release:g} "
                 f"valid={'yes' if measurement.valid else 'no'}")
        if hand.pinch.reason:
            debug += f" | {hand.pinch.reason}"
        (width, height), baseline = cv2.getTextSize(debug, cv2.FONT_HERSHEY_SIMPLEX, .45, 1)
        x = max(4, min(x, preview.shape[1] - width - 5))
        y += diagnostic_row
        cv2.rectangle(preview, (x - 3, y - height - 3), (x + width + 3, y + baseline + 3), (0, 0, 0), -1)
        cv2.putText(preview, debug, (x, y), cv2.FONT_HERSHEY_SIMPLEX, .45, (255, 255, 255), 1, cv2.LINE_AA)
    if state_row:
        state = hand.stabilized
        last = (f"{state.last_event.event_type.value.removeprefix('GESTURE_')}:{state.last_event.gesture}"
                if state.last_event is not None else "--")
        current = state.confirmed or "--"
        candidate = f" ({state.candidate})" if state.candidate is not None else ""
        text = f"{state.state.value}{candidate} | Confirmed: {current} | Last: {last}"
        (width, height), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, .43, 1)
        x = max(4, min(x, preview.shape[1] - width - 5))
        y += state_row
        cv2.rectangle(preview, (x - 3, y - height - 3), (x + width + 3, y + baseline + 3), (0, 0, 0), -1)
        cv2.putText(preview, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, .43, (255, 255, 255), 1, cv2.LINE_AA)


def significant_fps_drop(rate):
    """Compare application throughput with the owner's Phase 2.1 benchmark."""
    return (rate is not None and math.isfinite(rate)
            and rate < ONE_HAND_REFERENCE_FPS * PERFORMANCE_DROP_RATIO)


class PreviewRenderer:
    """One reusable BGR display buffer, refreshed completely on each frame."""

    def __init__(self):
        self.buffer = None

    def resize(self, frame, size):
        shape = (size[1], size[0], 3)
        if self.buffer is None or self.buffer.shape != shape or self.buffer.dtype != frame.dtype:
            self.buffer = np.empty(shape, dtype=frame.dtype)
        if frame.shape[:2] == shape[:2]:
            np.copyto(self.buffer, frame)
        else:
            cv2.resize(frame, size, dst=self.buffer)
        return self.buffer


def make_preview(frame, result, fps, show_help, renderer=None, timings=None, raw_result=None,
                 gesture_results=None, pinch_results=None, pinch_thresholds=None, gesture_states=None):
    start = time.perf_counter()
    height, width = frame.shape[:2]
    scale = min(1100 / width, 650 / height, 1.0)
    renderer = renderer if renderer is not None else PreviewRenderer()
    preview = renderer.resize(frame, (max(1, round(width * scale)), max(1, round(height * scale))))
    resized = time.perf_counter()
    if timings is not None:
        timings.add("preview_resize", resized - start)
    hands = hand_overlays(result, preview.shape[1], preview.shape[0], gesture_results, pinch_results, gesture_states)
    for hand in hands:
        draw_hand(preview, hand, top_margin=54 if show_help else 27, pinch_thresholds=pinch_thresholds)
    if raw_result is not None:
        for hand in hand_overlays(raw_result, preview.shape[1], preview.shape[0]):
            for point in hand.points:
                cv2.drawMarker(preview, point, (255, 255, 255), cv2.MARKER_CROSS,
                               markerSize=7, thickness=1, line_type=cv2.LINE_AA)
    drawn = time.perf_counter()
    if timings is not None:
        timings.add("landmark_drawing", drawn - resized)
    rate = "--" if fps is None else f"{fps:.1f}"
    lines = [f"App FPS: {rate} | Hands: {len(hands)} | {width} x {height} | Q: Quit | H: Help"]
    if show_help:
        lines.append("Left: green | Right: blue | Raw: white + | H: Hide help"
                     if raw_result is not None else
                     "Show one or two hands. Left: green | Right: blue | H: Hide help")
    for index, text in enumerate(lines):
        (text_width, text_height), baseline = cv2.getTextSize(
            text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        top = index * 27
        preview[top:top + 27, :text_width + 16] = 0
        cv2.putText(preview, text, (8, top + text_height + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    if timings is not None:
        timings.add("text_overlay", time.perf_counter() - drawn)
    return preview
