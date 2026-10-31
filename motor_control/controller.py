"""Safety/planning around a sealed simulated driver. No face, GUI or hardware APIs."""

from collections import Counter
from dataclasses import asdict
import math
from numbers import Integral
import time

from .models import (AngularVelocity, MotorCommand, MotorConfig, MotorInput, MotorReason as R,
                     MotorState, MotorStatus as S, finite)
from .simulator import SimulatedMotorDriver


_FAULTS=frozenset((R.INVALID_DEMAND,R.INVALID_OBSERVATION,R.INVALID_TIMESTAMP,R.REPLAY))


class MotorController:
    def __init__(self,config=None,*,enabled=False):
        if not isinstance(enabled,bool):raise ValueError('Simulation enabled must be explicit boolean')
        self.config=config or MotorConfig()
        self._driver=SimulatedMotorDriver(self.config)  # No hardware factory/injection path.
        self.enabled=enabled
        self._enabled_at_start=enabled
        self._ready=False
        self._last_now=self._last_source=self._last_observed=self._tracking_id=self._last_valid=None
        self.counts=Counter()
        self.reasons=Counter()
        self.requested_nonzero_seconds=self.accepted_nonzero_seconds=0.
        pan,tilt=self._driver.snapshot()
        self._state=MotorState(pan,tilt,MotorCommand(),S.IDLE if enabled else S.DISABLED,
                               R.INITIALIZING if enabled else R.DISABLED,None,None)
        self._limits=self._flags(pan,tilt)

    @staticmethod
    def _flags(pan,tilt):
        return pan.at_minimum or pan.at_maximum,tilt.at_minimum or tilt.at_maximum

    @property
    def state(self):return self._state

    def metadata(self):
        return {'enabled':True,'enabled_at_start':self._enabled_at_start,'simulation_enabled':self.enabled,'hardware_output_enabled':False,
                'driver':'SimulatedMotorDriver only','config':asdict(self.config),
                'counters':dict(self.counts),'reasons':dict(self.reasons),
                'requested_nonzero_update_seconds':self.requested_nonzero_seconds,
                'accepted_nonzero_update_seconds':self.accepted_nonzero_seconds,
                'final_virtual_angles_deg':{'pan':self.state.pan.angle_deg,'tilt':self.state.tilt.angle_deg},
                'counter_scope':'whole session including warmup; seconds cover accepted update intervals, not sensor time',
                'camera_feedback':'controller never alters observations; real webcam stays fixed; only the separate synthetic scene projects virtual orientation'}

    def _record(self,state):
        if state.reason!=self._state.reason:self.counts['status_transitions']+=1
        self.reasons[str(state.reason)]+=1
        self._state=state
        return state

    def stop(self,reason=R.NO_TARGET,*,now=None):
        if not isinstance(reason,R):reason=R.INVALID_OBSERVATION
        previous=self._state
        pan,tilt=self._driver.stop()
        self._ready=False
        if (previous.moving or previous.command.accepted!=AngularVelocity() or previous.reason!=reason):
            self.counts['safety_stops']+=1
        status=S.DISABLED if not self.enabled else S.FAULTED if reason in _FAULTS else S.STALLED if reason==R.STALLED else S.IDLE if reason==R.INITIALIZING else S.STOPPED
        command=MotorCommand(observation_timestamp=previous.command.observation_timestamp,
                             tracking_id=previous.command.tracking_id,source_timestamp_ms=previous.command.source_timestamp_ms,reason=reason)
        return self._record(MotorState(pan,tilt,command,status,reason,now if finite(now) and now>=0 else None,self._last_valid))

    def set_enabled(self,enabled,*,now=None):
        if not isinstance(enabled,bool):raise ValueError('Simulation enabled must be a boolean')
        self.enabled=enabled
        return self.stop(R.INITIALIZING if enabled else R.DISABLED,now=now)

    def shutdown(self,*,now=None):
        self.enabled=False
        return self.stop(R.SHUTDOWN,now=now)

    def check_timeout(self,*,now):
        """No integration, no new observation, no freshness refresh; safe during capture waits."""
        if not self.enabled or not self._ready:return self.state
        if not finite(now) or self._last_now is not None and now<self._last_now:
            return self.stop(R.INVALID_TIMESTAMP,now=now)
        if self._last_now is not None and now-self._last_now>self.config.max_update_interval+1e-9:
            return self.stop(R.STALLED,now=now)
        observed=self.state.command.observation_timestamp
        if observed is None or now-observed>self.config.max_observation_age:
            return self.stop(R.STALE_OBSERVATION,now=now)
        return self.state

    def update(self,observation,*,now,profile=None):
        measured=profile is not None and profile.enabled
        started=time.perf_counter() if measured else None
        self.counts['updates']+=1
        age=None
        def stopped(reason):
            if reason in _FAULTS:self.counts['invalid_updates']+=1
            return self.stop(reason,now=now)
        def finish(state):
            if measured:
                profile.add('motor_control_update',time.perf_counter()-started)
                if age is not None:profile.add('motor_observation_age',age)
            return state
        if not self.enabled:return finish(stopped(R.DISABLED))
        if not finite(now) or now<0 or self._last_now is not None and now<=self._last_now:
            return finish(stopped(R.INVALID_TIMESTAMP))
        dt=now-self._last_now if self._last_now is not None else 0.
        self._last_now=now
        if observation is None:return finish(stopped(R.NO_TARGET))
        if not isinstance(observation,MotorInput):return finish(stopped(R.INVALID_OBSERVATION))
        source=observation.source_timestamp_ms
        if not isinstance(observation.valid,bool):return finish(stopped(R.INVALID_OBSERVATION))
        if not observation.valid:
            if isinstance(source,Integral) and not isinstance(source,bool) and 0<=source<=2**63-1:
                self._last_source=max(int(source),self._last_source if self._last_source is not None else -1)
            reason=observation.reason if isinstance(observation.reason,R) else R.INVALID_OBSERVATION
            if reason in (R.TRACKING,R.CENTERED,R.INITIALIZING):reason=R.INVALID_OBSERVATION
            return finish(stopped(reason))
        if not isinstance(source,Integral) or isinstance(source,bool) or not 0<=source<=2**63-1:
            return finish(stopped(R.INVALID_TIMESTAMP))
        if self._last_source is not None and source<=self._last_source:return finish(stopped(R.REPLAY))
        self._last_source=int(source)
        detected=observation.observation_timestamp
        if not finite(detected) or not 0<=detected<=now:return finish(stopped(R.INVALID_TIMESTAMP))
        age=now-detected
        if age>self.config.max_observation_age:return finish(stopped(R.STALE_OBSERVATION))
        if self._last_observed is not None and detected<=self._last_observed:return finish(stopped(R.REPLAY))
        self._last_observed=detected
        if dt>self.config.max_update_interval+1e-9:return finish(stopped(R.STALLED))
        key=observation.tracking_id
        if not isinstance(key,Integral) or isinstance(key,bool) or key<1:return finish(stopped(R.INVALID_OBSERVATION))
        if self._tracking_id is not None and key!=self._tracking_id:
            self._tracking_id=int(key)
            return finish(stopped(R.TARGET_CHANGED))
        self._tracking_id=int(key)
        demands=(observation.pan_demand,observation.tilt_demand)
        if (not all(finite(v) and abs(v)<=1 for v in demands)
                or observation.reason not in (R.TRACKING,R.CENTERED)
                or observation.reason==R.CENTERED and any(demands)):
            return finish(stopped(R.INVALID_DEMAND))
        before_plan=time.perf_counter() if measured else None
        divisor=max(1.,math.hypot(*demands))
        requested=AngularVelocity(demands[0]/divisor*self.config.pan.max_speed_deg_s,
                                  demands[1]/divisor*self.config.tilt.max_speed_deg_s)
        axes=self._driver.snapshot()
        raw=(requested.pan_deg_s,requested.tilt_deg_s)
        blocked=tuple(v>0 and a.at_maximum or v<0 and a.at_minimum for v,a in zip(raw,axes))
        accepted=AngularVelocity(*(0. if block else v for v,block in zip(raw,blocked)))
        fresh_start=not self._ready
        if fresh_start:accepted=AngularVelocity();dt=0.
        self._ready=True
        self._last_valid=now
        if measured:profile.add('motor_planning',time.perf_counter()-before_plan)
        before_step=time.perf_counter() if measured else None
        try:
            pan,tilt=self._driver.step(accepted,dt)
        except (ValueError,RuntimeError,OverflowError):
            self.stop(R.INVALID_OBSERVATION,now=now)
            raise
        accepted=AngularVelocity(pan.target_velocity_deg_s,tilt.target_velocity_deg_s)
        if measured:profile.add('motor_simulated_step',time.perf_counter()-before_step)
        flags=self._flags(pan,tilt)
        entries=sum(new and not old for new,old in zip(flags,self._limits))
        self.counts['limit_hits']+=entries
        self._limits=flags
        if any(raw):self.requested_nonzero_seconds+=dt
        if accepted!=AngularVelocity():self.accepted_nonzero_seconds+=dt
        reason=(R.INITIALIZING if fresh_start else R.LIMIT_REACHED if any(blocked) or entries else
                R.CENTERED if requested==AngularVelocity() else R.TRACKING)
        status=(S.IDLE if fresh_start else S.LIMIT_REACHED if reason==R.LIMIT_REACHED else
                S.CENTERED if reason==R.CENTERED else S.MOVING if pan.velocity_deg_s or tilt.velocity_deg_s else S.IDLE)
        command=MotorCommand(requested,accepted,detected,int(key),int(source),True,reason)
        return finish(self._record(MotorState(pan,tilt,command,status,reason,now,self._last_valid)))
