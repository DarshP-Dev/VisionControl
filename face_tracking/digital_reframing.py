"""Bounded virtual-viewport translation; no pixels, GUI, camera or input ownership."""

from collections import Counter
from dataclasses import asdict, dataclass
import math
from numbers import Integral
import time

from .centering import CenteringResult, DeadZone
from .centering_geometry import finite, point
from .face_geometry import dimensions
from .reframing_models import CropRectangle, ReframeResult, ReframeStatus


@dataclass(frozen=True, slots=True)
class ReframeConfig:
    scale: float = 2/3
    follow_tau: float = .2
    max_speed: float = 600.  # Source pixels/second, Euclidean two-axis limit.
    horizontal: DeadZone = DeadZone(.10, .06)
    vertical: DeadZone = DeadZone(.10, .06)
    composition: tuple[float, float] = (.5, .5)

    def __post_init__(self):
        if not finite(self.scale) or not 0 < self.scale <= 1:
            raise ValueError("Crop scale must be finite and within (0,1]")
        if not finite(self.follow_tau) or self.follow_tau < 0:
            raise ValueError("Follow tau must be finite and nonnegative")
        if not finite(self.max_speed) or self.max_speed <= 0:
            raise ValueError("Maximum speed must be finite and positive source pixels/second")
        if not all(isinstance(zone, DeadZone) for zone in (self.horizontal, self.vertical)):
            raise ValueError("Each crop axis requires a DeadZone")
        if not isinstance(self.composition, tuple):
            raise ValueError("Composition must be an immutable normalized X/Y tuple")
        point(self.composition, (1, 1))


def crop_dimensions(source_size, scale=2/3):
    width, height = dimensions(source_size)
    if not finite(scale) or not 0 < scale <= 1:
        raise ValueError("Crop scale must be within (0,1]")
    # Equal scale on both axes, round-half-up. Integer raster aspect is within
    # one pixel of ideal scaling, including coprime/odd source dimensions.
    return max(1, min(width, math.floor(width*scale+.5))), max(1, min(height, math.floor(height*scale+.5)))


def clamp_center(center, source_size, crop_size):
    width, height = dimensions(source_size)
    cw, ch = dimensions(crop_size)
    if cw > width or ch > height or not isinstance(center, (tuple,list)) or len(center) != 2 or not all(finite(v) for v in center):
        raise ValueError("Crop must fit the source and have a finite center")
    return min(width-cw/2, max(cw/2, center[0])), min(height-ch/2, max(ch/2, center[1]))


def crop_rectangle(center, source_size, crop_size):
    cx, cy = clamp_center(center, source_size, crop_size)
    width, height = dimensions(source_size)
    cw, ch = dimensions(crop_size)
    left = max(0, min(width-cw, math.floor(cx-cw/2+.5)))
    top = max(0, min(height-ch, math.floor(cy-ch/2+.5)))
    return CropRectangle(left, top, left+cw, top+ch)


def _active_sign(error, previous, zone):
    sign = 1 if error > 0 else -1 if error < 0 else 0
    threshold = zone.deactivation if sign == previous and previous else zone.activation
    return sign if abs(error)-threshold > 8*math.ulp(1.) else 0


class DigitalReframer:
    def __init__(self, config=None):
        self.config = config or ReframeConfig()
        self._size = self._crop = self._center = None
        self._last_now = self._last_source = self._last_observed = self._primary = None
        self._was_fresh = False
        self._x = self._y = 0
        self.counts = Counter()
        self.reasons = Counter()
        self._last_reason = None
        self._distance = self._max_step = 0.

    def reset(self):
        self._size = self._crop = self._center = self._primary = None
        self._was_fresh = False
        self._x = self._y = 0
        self.counts['resets'] += 1
        # Clock/source fences remain sticky within this session.

    def metadata(self):
        return {'enabled':True, 'config':asdict(self.config), 'counters':dict(self.counts),
                'reasons':dict(self.reasons), 'distance_pixels':self._distance, 'maximum_step_pixels':self._max_step,
                'counter_scope':'whole session including warmup; no stored coordinates or images',
                'large_gap_policy':'hold first valid frame after >250ms gap; cap subsequent integration dt at 100ms',
                'output':'output-only crop; tracking continues on the original source frame'}

    def update(self, observation, *, source_size, now, profile=None):
        measured = profile is not None and profile.enabled
        started = time.perf_counter() if measured else None
        size = dimensions(source_size)
        changed_size = size != self._size
        if changed_size:
            self._size, self._crop = size, crop_dimensions(size, self.config.scale)
            self._center = size[0]/2, size[1]/2
            self._was_fresh = False
            self._x = self._y = 0
            self.counts['source_initializations'] += 1
        good_clock = finite(now) and now >= 0 and (self._last_now is None or now >= self._last_now)
        dt = now-self._last_now if good_clock and self._last_now is not None else 0.
        if good_clock:
            self._last_now = now
        primary = detected_at = age = desired = target_in_crop = errors = None
        boundaries = ()
        moving = False

        def finish(reason, fresh=False):
            self.reasons[reason] += 1
            if self._last_reason is not None and reason != self._last_reason:
                self.counts['status_transitions'] += 1
            self._last_reason = reason
            if not fresh:
                self._was_fresh = False
                self._x = self._y = 0
            snapshot = ReframeResult(primary, ReframeStatus.TRACKING if fresh else ReframeStatus.HOLDING, reason,
                size, self._crop, crop_rectangle(self._center,size,self._crop), self._center, desired,
                target_in_crop, errors, bool(self._x), bool(self._y), boundaries, detected_at, age,
                now if good_clock else None, fresh, moving)
            if measured:
                profile.add('reframe_update',time.perf_counter()-started)
                if age is not None:
                    profile.add('reframe_observation_age',age)
            return snapshot

        if not good_clock:
            return finish('INVALID_TIMESTAMP')
        if not isinstance(observation, CenteringResult):
            return finish('NO_TARGET' if observation is None else 'INVALID_OBSERVATION')
        primary = observation.primary_id
        if finite(observation.observation_timestamp) and 0 <= observation.observation_timestamp <= now:
            detected_at = observation.observation_timestamp
            age = now-detected_at
        if observation.frame_size != size:
            return finish('INVALID_GEOMETRY')
        source = observation.source_timestamp_ms
        if not isinstance(source,Integral) or isinstance(source,bool) or not 0 <= source <= 2**63-1:
            return finish('INVALID_TIMESTAMP')
        if self._last_source is not None and source < self._last_source:
            return finish('INVALID_TIMESTAMP')
        duplicate = self._last_source == source
        self._last_source = int(source)
        if not observation.actionable:
            return finish(str(observation.status))
        if (not isinstance(primary,Integral) or isinstance(primary,bool) or primary < 1
                or detected_at is None or observation.evaluated_at is None or detected_at > observation.evaluated_at):
            return finish('INVALID_OBSERVATION')
        if not observation.fresh_at(now) or age > .25:
            return finish('STALE_OBSERVATION')
        if duplicate:
            return finish('DUPLICATE_OBSERVATION')
        if self._last_observed is not None and detected_at <= self._last_observed:
            return finish('INVALID_TIMESTAMP')
        try:
            face = point(observation.smoothed_center,size)
        except (TypeError,ValueError,OverflowError):
            return finish('INVALID_GEOMETRY')
        self._last_observed = detected_at
        restart = not self._was_fresh or primary != self._primary or dt > .25
        if restart:
            self._x = self._y = 0
            dt = 0.
            self.counts['motion_timing_restarts'] += 1
        self._primary, self._was_fresh = primary, True
        dt = min(.1,dt)
        cw,ch = self._crop
        cx,cy = self._center
        tx,ty = self.config.composition
        offset = (tx-.5)*cw, (ty-.5)*ch
        error = (face[0]-cx-offset[0])/(cw/2), (face[1]-cy-offset[1])/(ch/2)
        self._x = _active_sign(error[0],self._x,self.config.horizontal)
        self._y = _active_sign(error[1],self._y,self.config.vertical)
        raw_desired = face[0]-offset[0], face[1]-offset[1]
        clamped = clamp_center(raw_desired,size,self._crop)
        boundaries = tuple(name for name,yes in (
            ('LEFT',raw_desired[0] < cw/2), ('RIGHT',raw_desired[0] > size[0]-cw/2),
            ('TOP',raw_desired[1] < ch/2), ('BOTTOM',raw_desired[1] > size[1]-ch/2)) if yes)
        desired = clamped[0] if self._x else cx, clamped[1] if self._y else cy
        alpha = -math.expm1(-dt/self.config.follow_tau) if self.config.follow_tau else 1.
        dx,dy = alpha*(desired[0]-cx), alpha*(desired[1]-cy)
        distance = math.hypot(dx,dy)
        allowance = self.config.max_speed*dt
        remaining = math.dist((cx,cy),desired)
        if remaining <= .01 and remaining <= allowance:
            # Finish subpixel boundary convergence instead of integrating an
            # invisible asymptotic tail forever; still respect the speed budget.
            dx,dy = desired[0]-cx, desired[1]-cy
            distance = remaining
        if distance > allowance:
            ratio = allowance/distance
            dx,dy = dx*ratio, dy*ratio
        self._center = clamp_center((cx+dx,cy+dy),size,self._crop)
        step = math.dist((cx,cy),self._center)
        moving = step > 1e-9
        self._max_step = max(self._max_step,step)
        self._distance += step
        self.counts['moving_updates' if moving else 'stationary_updates'] += 1
        self.counts['boundary_constrained_updates'] += bool(boundaries)
        rect = crop_rectangle(self._center,size,self._crop)
        target_in_crop = face[0]-rect.left, face[1]-rect.top
        errors = (target_in_crop[0]-tx*cw)/(cw/2), (target_in_crop[1]-ty*ch)/(ch/2)
        return finish('FOLLOWING' if moving else 'BOUNDARY_HOLD' if boundaries else 'SETTLED',True)
