"""Small timing and drawing helpers independent of the MediaPipe runtime."""

import math

import cv2


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


def make_preview(frame, result, fps, show_help):
    height, width = frame.shape[:2]
    scale = min(1100 / width, 650 / height, 1.0)
    preview = cv2.resize(frame, (max(1, round(width * scale)),
                                 max(1, round(height * scale))))
    hands = result.hand_landmarks[:1]
    for landmarks in hands:
        if len(landmarks) != 21:
            raise ValueError("Expected 21 hand landmarks")
        points = landmark_pixels(landmarks, preview.shape[1], preview.shape[0])
        for start, end in HAND_CONNECTIONS:
            cv2.line(preview, points[start], points[end], (70, 230, 70), 2, cv2.LINE_AA)
        for point in points:
            cv2.circle(preview, point, 4, (0, 0, 0), -1, cv2.LINE_AA)
            cv2.circle(preview, point, 3, (0, 230, 255), -1, cv2.LINE_AA)
    rate = "--" if fps is None else f"{fps:.1f}"
    lines = [f"App FPS: {rate} | Hands: {len(hands)} | Q: Quit | H: Help"]
    if show_help:
        lines.append("Show one hand to see its 21 landmarks. Q: Quit | H: Hide help")
    for index, text in enumerate(lines):
        (text_width, text_height), baseline = cv2.getTextSize(
            text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        top = index * 27
        preview[top:top + 27, :text_width + 16] = 0
        cv2.putText(preview, text, (8, top + text_height + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return preview
