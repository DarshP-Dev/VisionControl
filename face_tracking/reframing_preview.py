"""Crop slicing and isolated, reusable display buffers. No camera or GUI ownership."""

import time

import cv2
import numpy as np

from hand_tracking.performance import fit_size


def extract_crop(frame, viewport):
    if (not isinstance(frame,np.ndarray) or frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != 3
            or (frame.shape[1],frame.shape[0]) != viewport.source_size):
        raise ValueError('Crop extraction requires the matching original uint8 BGR frame')
    r = viewport.rectangle
    if not (0 <= r.left < r.right <= frame.shape[1] and 0 <= r.top < r.bottom <= frame.shape[0]
            and r.size == viewport.crop_size):
        raise ValueError('Invalid in-frame crop rectangle')
    crop = frame[r.top:r.bottom,r.left:r.right]
    crop.setflags(write=False)  # Read-only view; display annotation uses a separate buffer.
    return crop


class ReframeRenderer:
    def __init__(self, bounds=(960,540)):
        self.bounds = bounds
        self.buffer = None

    def close(self):
        self.buffer = None

    def render(self, frame, viewport, *, now, profile=None):
        measured = profile is not None and profile.enabled
        start = time.perf_counter() if measured else None
        crop = extract_crop(frame,viewport)
        if measured:
            after_slice = time.perf_counter()
            profile.add('reframe_crop_extraction',after_slice-start)
        size = fit_size(crop.shape[1],crop.shape[0],self.bounds)
        shape = size[1],size[0],3
        if self.buffer is None or self.buffer.shape != shape:
            self.buffer = np.empty(shape,np.uint8)
        if size == (crop.shape[1],crop.shape[0]):
            np.copyto(self.buffer,crop)
        else:
            cv2.resize(crop,size,dst=self.buffer,interpolation=cv2.INTER_LINEAR)
        fresh = viewport.fresh_at(now)
        label = f'AUTO-FRAME | FACE #{viewport.primary_id}' if fresh else f'AUTO-FRAME PAUSED | {viewport.reason if not viewport.fresh_target else "STALE_OBSERVATION"}'
        if fresh and viewport.boundaries:
            label += ' | CLAMPED ' + '/'.join(viewport.boundaries)
        cv2.putText(self.buffer,label,(8,min(size[1]-1,20)),cv2.FONT_HERSHEY_SIMPLEX,.45,(0,0,0),3,cv2.LINE_AA)
        cv2.putText(self.buffer,label,(8,min(size[1]-1,20)),cv2.FONT_HERSHEY_SIMPLEX,.45,(0,220,255),1,cv2.LINE_AA)
        if measured:
            profile.add('reframe_rendering',time.perf_counter()-after_slice)
        return self.buffer


def draw_viewport(preview, viewport):
    width,height = viewport.source_size
    ph,pw = preview.shape[:2]
    r = viewport.rectangle
    first = min(pw-1,round(r.left/width*pw)), min(ph-1,round(r.top/height*ph))
    last = min(pw-1,round(r.right/width*pw)), min(ph-1,round(r.bottom/height*ph))
    cv2.rectangle(preview,first,last,(180,100,255),1,cv2.LINE_AA)
