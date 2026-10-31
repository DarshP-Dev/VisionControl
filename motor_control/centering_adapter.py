"""The only face-package bridge. Normalized observations stay separate from angles."""

from face_tracking.centering import CenteringResult, CenteringStatus, CorrectionDirection
from face_tracking.face_geometry import dimensions
from face_tracking.centering_geometry import point
from .models import MotorInput, MotorReason, finite


_REASONS={CenteringStatus.NO_TARGET:MotorReason.NO_TARGET,CenteringStatus.WAITING_FOR_TARGET:MotorReason.WAITING_FOR_TARGET,
          CenteringStatus.TARGET_LOST:MotorReason.TARGET_LOST,CenteringStatus.TARGET_UNCERTAIN:MotorReason.TARGET_UNCERTAIN,
          CenteringStatus.STALE_OBSERVATION:MotorReason.STALE_OBSERVATION,CenteringStatus.INVALID_OBSERVATION:MotorReason.INVALID_OBSERVATION}


def from_centering(result,*,now):
    if result is None:return MotorInput()
    if not isinstance(result,CenteringResult):return MotorInput(reason=MotorReason.INVALID_OBSERVATION)
    common={'observation_timestamp':result.observation_timestamp,'source_timestamp_ms':result.source_timestamp_ms,'tracking_id':result.primary_id}
    if not isinstance(result.status,CenteringStatus):return MotorInput(**common,reason=MotorReason.INVALID_OBSERVATION)
    if not result.actionable:return MotorInput(**common,reason=_REASONS.get(result.status,MotorReason.INVALID_OBSERVATION))
    if (not all(finite(v) for v in (now,result.observation_timestamp,result.evaluated_at,result.max_observation_age))
            or not 0<result.max_observation_age<=.25 or not 0<=result.observation_timestamp<=result.evaluated_at<=now):
        return MotorInput(**common,reason=MotorReason.INVALID_TIMESTAMP)
    if not result.fresh_at(now) or now-result.observation_timestamp>.25:
        return MotorInput(**common,reason=MotorReason.STALE_OBSERVATION)
    try:
        dimensions(result.frame_size)
        point(result.smoothed_center,result.frame_size)
        for axis,negative,positive in ((result.horizontal,CorrectionDirection.PAN_LEFT,CorrectionDirection.PAN_RIGHT),
                                       (result.vertical,CorrectionDirection.TILT_UP,CorrectionDirection.TILT_DOWN)):
            if (not finite(axis.demand) or abs(axis.demand)>1 or not isinstance(axis.active,bool)
                    or axis.active != (axis.demand!=0) or not axis.active and axis.direction!=CorrectionDirection.NONE
                    or axis.demand>0 and axis.direction!=positive or axis.demand<0 and axis.direction!=negative):
                return MotorInput(**common,reason=MotorReason.INVALID_DEMAND)
        if result.is_centered and (result.horizontal.demand!=0 or result.vertical.demand!=0):
            return MotorInput(**common,reason=MotorReason.INVALID_DEMAND)
    except (AttributeError,TypeError,ValueError,OverflowError):
        return MotorInput(**common,reason=MotorReason.INVALID_OBSERVATION)
    return MotorInput(result.horizontal.demand,result.vertical.demand,**common,valid=True,
                      reason=MotorReason.CENTERED if result.is_centered else MotorReason.TRACKING)
