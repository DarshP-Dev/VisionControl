"""Unmirrored, clipped continuous pixel edges: x right, y down; W/H are outer edges."""

import math
from numbers import Integral, Real

from .face_models import BoundingBox, FaceDetection, FaceFrame


def dimensions(size):
    if not isinstance(size, (tuple, list)) or len(size) != 2 or any(isinstance(v, bool) or not isinstance(v, Integral) or v <= 0 for v in size):
        raise ValueError("Image dimensions must be positive integer width/height")
    return tuple(map(int, size))


def convert_box(x, y, width, height, inference_size, frame_size, confidence=None):
    iw, ih = dimensions(inference_size)
    fw, fh = dimensions(frame_size)
    values = (x, y, width, height)
    if any(isinstance(v, bool) or not isinstance(v, Real) or not math.isfinite(v) for v in values):
        raise ValueError("Box coordinates must be finite numbers")
    if width <= 0 or height <= 0:
        raise ValueError("Box area must be positive")
    if confidence is not None and (isinstance(confidence, bool) or not isinstance(confidence, Real)
                                  or not math.isfinite(confidence) or not 0 <= confidence <= 1):
        raise ValueError("Confidence must be within [0,1] or unavailable")
    edges = (x/iw*fw, y/ih*fh, (x+width)/iw*fw, (y+height)/ih*fh)
    if not all(math.isfinite(v) for v in edges):
        raise ValueError("Box conversion overflow")
    left, top, right, bottom = (min(fw, max(0., edges[0])), min(fh, max(0., edges[1])),
                                min(fw, max(0., edges[2])), min(fh, max(0., edges[3])))
    if right <= left or bottom <= top:
        raise ValueError("Box does not intersect the frame")
    cx, cy = (left+right)/2, (top+bottom)/2
    ox, oy = cx-fw/2, cy-fh/2
    return FaceDetection(BoundingBox(left, top, right, bottom),
        BoundingBox(left/fw, top/fh, right/fw, bottom/fh), cx, cy,
        float(confidence) if confidence is not None else None, ox, oy, ox/(fw/2), oy/(fh/2))


def adapt_result(result, inference_size, frame_size, timestamp_ms, min_confidence=.5):
    if not math.isfinite(min_confidence) or not 0 <= min_confidence <= 1:
        raise ValueError("Face confidence threshold must be within [0,1]")
    dimensions(inference_size)
    dimensions(frame_size)
    faces = []
    for detection in result.detections or ():
        try:
            categories = detection.categories or ()
            confidence = categories[0].score if categories else None
            box = detection.bounding_box
            face = convert_box(box.origin_x, box.origin_y, box.width, box.height,
                               inference_size, frame_size, confidence)
            if face.confidence is None or face.confidence >= min_confidence:
                faces.append(face)
        except (AttributeError, TypeError, ValueError, OverflowError):
            continue  # Invalid individual detections never leave stale/invalid coordinates.
    faces.sort(key=lambda f: (-(f.confidence if f.confidence is not None else -1.),
        -f.box_pixels.area, f.box_pixels.x_min, f.box_pixels.y_min, f.box_pixels.x_max, f.box_pixels.y_max))
    return FaceFrame(timestamp_ms, frame_size, inference_size, tuple(faces), 0 if faces else None,
                     "detected" if faces else "no_face")
