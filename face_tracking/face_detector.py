"""Single main-thread synchronous IMAGE detector. No camera, history, GUI or input."""

import math
import time

import cv2
import numpy as np

from hand_tracking.performance import fit_size
from .download_model import MODEL_PATH, MODEL_SHA256, verify_model
from .face_geometry import adapt_result


class FaceDetectionError(OSError):
    pass


class FaceDetector:
    def __init__(self, model_path=MODEL_PATH, *, bounds=(640, 360), min_confidence=.5, mp=None, backend=None):
        if not math.isfinite(min_confidence) or not 0 <= min_confidence <= 1:
            raise ValueError("Face confidence must be within [0,1]")
        fit_size(1920, 1080, bounds)
        self.bounds, self.min_confidence = bounds, min_confidence
        self.rgb = self.resized = None
        self.closed = False
        self.backend_released = False
        self.cleanup_error = None
        self.last_inference_size = None
        started = time.perf_counter()
        if backend is None:
            from pathlib import Path
            verify_model(Path(model_path).read_bytes())
            if mp is None:
                import mediapipe as mp
            options = mp.tasks.vision.FaceDetectorOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=str(Path(model_path).resolve()),
                                                 delegate=mp.tasks.BaseOptions.Delegate.CPU),
                running_mode=mp.tasks.vision.RunningMode.IMAGE,
                min_detection_confidence=min_confidence,
            )
            backend = mp.tasks.vision.FaceDetector.create_from_options(options)
        self.mp, self.backend = mp, backend
        self.initialization_seconds = time.perf_counter()-started

    def detect(self, frame, timestamp_ms, profile, *, rgb_hint=None):
        if self.closed:
            raise FaceDetectionError("Face detector is closed")
        if (not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3
                or frame.dtype != np.uint8 or min(frame.shape[:2]) <= 0):
            raise ValueError("Face detector requires a nonempty uint8 BGR frame")
        started = time.perf_counter()
        fw, fh = frame.shape[1], frame.shape[0]
        size = fit_size(fw, fh, self.bounds)
        shape = (size[1], size[0], 3)
        # Reuse only this frame's hand-prepared RGB when it has sufficient size.
        hint_ok = (isinstance(rgb_hint, np.ndarray) and rgb_hint.ndim == 3 and rgb_hint.shape[2] == 3
                   and rgb_hint.dtype == np.uint8 and rgb_hint.shape[1] >= size[0] and rgb_hint.shape[0] >= size[1])
        if hint_ok:
            hint_ok = fit_size(fw, fh, (rgb_hint.shape[1], rgb_hint.shape[0])) == (rgb_hint.shape[1], rgb_hint.shape[0])
        if hint_ok and rgb_hint.shape[:2] == shape[:2]:
            rgb = rgb_hint
        else:
            if self.rgb is None or self.rgb.shape != shape:
                self.rgb, self.resized = np.empty(shape, np.uint8), np.empty(shape, np.uint8)
            if hint_ok:
                rgb = cv2.resize(rgb_hint, size, dst=self.rgb, interpolation=cv2.INTER_AREA)
            else:
                source = frame if (fw, fh) == size else cv2.resize(frame, size, dst=self.resized, interpolation=cv2.INTER_AREA)
                rgb = cv2.cvtColor(source, cv2.COLOR_BGR2RGB, dst=self.rgb)
        prepared = time.perf_counter()
        profile.add("face_preprocessing", prepared-started)
        self.last_inference_size = size
        try:
            image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb)
            infer = time.perf_counter()
            profile.add("face_image", infer-prepared)
            result = self.backend.detect(image)
            inferred = time.perf_counter()
            profile.add("face_inference", inferred-infer)
            output = adapt_result(result, size, (fw, fh), timestamp_ms, self.min_confidence)
            profile.add("face_geometry", time.perf_counter()-inferred)
            return output
        except Exception as exc:
            raise FaceDetectionError(f"Face detection failed: {type(exc).__name__}: {exc}") from exc

    def close(self):
        if not self.backend_released:
            self.closed = True
            self.rgb = self.resized = None
            try:
                self.backend.close()
            except Exception as exc:
                self.cleanup_error = str(exc)
                raise FaceDetectionError(f"Face detector cleanup failed: {exc}") from exc
            self.backend_released = True
            self.cleanup_error = None

    def metadata(self):
        return {"detector": "MediaPipe FaceDetector / BlazeFace short-range float16 v1", "mode": "IMAGE",
                "model_sha256": MODEL_SHA256, "initialization_seconds": self.initialization_seconds,
                "min_confidence": self.min_confidence, "inference_bounds": self.bounds or "full",
                "primary_policy": "confidence descending, area descending, then box coordinates ascending",
                "temporal_history": False, "closed": self.backend_released, "inference_stopped": self.closed,
                "cleanup_error": self.cleanup_error}
