"""Hardware-independent virtual units: degrees, degrees/second, seconds."""

from dataclasses import dataclass, field
from enum import StrEnum
import math
from numbers import Real
from typing import Protocol


def finite(value):
    try:
        return isinstance(value,Real) and not isinstance(value,bool) and math.isfinite(value)
    except OverflowError:
        return False


class MotorStatus(StrEnum):
    DISABLED='DISABLED'
    IDLE='IDLE'
    MOVING='MOVING'
    CENTERED='CENTERED'
    STOPPED='STOPPED'
    STALLED='STALLED'
    FAULTED='FAULTED'
    LIMIT_REACHED='LIMIT_REACHED'


class MotorReason(StrEnum):
    DISABLED='DISABLED'
    INITIALIZING='INITIALIZING'
    TRACKING='TRACKING'
    CENTERED='CENTERED'
    NO_TARGET='NO_TARGET'
    WAITING_FOR_TARGET='WAITING_FOR_TARGET'
    TARGET_LOST='TARGET_LOST'
    TARGET_UNCERTAIN='TARGET_UNCERTAIN'
    STALE_OBSERVATION='STALE_OBSERVATION'
    INVALID_OBSERVATION='INVALID_OBSERVATION'
    INVALID_TIMESTAMP='INVALID_TIMESTAMP'
    INVALID_DEMAND='INVALID_DEMAND'
    REPLAY='REPLAY'
    STALLED='STALLED'
    TARGET_CHANGED='TARGET_CHANGED'
    LIMIT_REACHED='LIMIT_REACHED'
    SHUTDOWN='SHUTDOWN'


@dataclass(frozen=True,slots=True)
class AxisConfig:
    minimum_deg: float
    maximum_deg: float
    max_speed_deg_s: float
    max_acceleration_deg_s2: float
    home_deg: float=0.

    def __post_init__(self):
        values=(self.minimum_deg,self.maximum_deg,self.max_speed_deg_s,self.max_acceleration_deg_s2,self.home_deg)
        if (not all(finite(v) for v in values) or not -180 <= self.minimum_deg < self.maximum_deg <= 180
                or not self.minimum_deg <= self.home_deg <= self.maximum_deg
                or not 0 < self.max_speed_deg_s <= 360 or not 0 < self.max_acceleration_deg_s2 <= 3600):
            raise ValueError('Virtual axes require -180<=min<max<=180, home within limits, speed (0,360], acceleration (0,3600]')


@dataclass(frozen=True,slots=True)
class MotorConfig:
    pan: AxisConfig=AxisConfig(-45,45,30,60)
    tilt: AxisConfig=AxisConfig(-25,25,20,40)
    max_update_interval: float=.1
    max_observation_age: float=.25

    def __post_init__(self):
        if not isinstance(self.pan,AxisConfig) or not isinstance(self.tilt,AxisConfig):
            raise ValueError('Both virtual axes require AxisConfig')
        if (not finite(self.max_update_interval) or not 0 < self.max_update_interval <= .25
                or not finite(self.max_observation_age) or not 0 < self.max_observation_age <= .25):
            raise ValueError('Update/freshness intervals must be positive and at most 250 ms')


@dataclass(frozen=True,slots=True)
class MotorInput:
    pan_demand: float=0.
    tilt_demand: float=0.
    observation_timestamp: float | None=None
    source_timestamp_ms: int | None=None
    tracking_id: int | None=None
    valid: bool=False
    reason: MotorReason=MotorReason.NO_TARGET


@dataclass(frozen=True,slots=True)
class AngularVelocity:
    pan_deg_s: float=0.
    tilt_deg_s: float=0.


@dataclass(frozen=True,slots=True)
class MotorCommand:
    requested: AngularVelocity=AngularVelocity()
    accepted: AngularVelocity=AngularVelocity()
    observation_timestamp: float | None=None
    tracking_id: int | None=None
    source_timestamp_ms: int | None=None
    valid: bool=False
    reason: MotorReason=MotorReason.NO_TARGET


@dataclass(frozen=True,slots=True)
class AxisState:
    angle_deg: float
    velocity_deg_s: float
    target_velocity_deg_s: float
    at_minimum: bool
    at_maximum: bool


@dataclass(frozen=True,slots=True)
class MotorState:
    pan: AxisState
    tilt: AxisState
    command: MotorCommand
    status: MotorStatus
    reason: MotorReason
    updated_at: float | None
    last_valid_update: float | None
    hardware_output_enabled: bool=field(default=False,init=False)

    @property
    def moving(self):
        return self.pan.velocity_deg_s != 0 or self.tilt.velocity_deg_s != 0


class MotorDriver(Protocol):
    """Future implementations need their own arming/watchdog/safety boundary.

    Phase 4.5 constructs ONLY SimulatedMotorDriver; there is no hardware factory.
    """
    def step(self, velocity: AngularVelocity, dt: float) -> tuple[AxisState,AxisState]: ...
    def stop(self) -> tuple[AxisState,AxisState]: ...
    def snapshot(self) -> tuple[AxisState,AxisState]: ...
