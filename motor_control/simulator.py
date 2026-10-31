"""Pure deterministic kinematics. No clock, camera, GUI, device or input APIs."""

from .models import AngularVelocity, AxisState, MotorConfig, finite


class SimulatedMotorDriver:
    def __init__(self,config=None):
        self.config=config or MotorConfig()
        self._angles=[self.config.pan.home_deg,self.config.tilt.home_deg]
        self._velocities=[0.,0.]
        self._targets=[0.,0.]

    def snapshot(self):
        return tuple(AxisState(angle,velocity,target,angle<=axis.minimum_deg,angle>=axis.maximum_deg)
                     for angle,velocity,target,axis in zip(self._angles,self._velocities,self._targets,(self.config.pan,self.config.tilt)))

    def stop(self):
        self._velocities[:]=self._targets[:]=[0.,0.]
        return self.snapshot()

    @staticmethod
    def _integrate(position,v0,target,dt,ramp,axis):
        acceleration=(target-v0)/ramp if ramp else 0.
        def at(t):
            r=min(t,ramp)
            return position+v0*r+.5*acceleration*r*r+target*max(0.,t-ramp)
        # Velocity-zero extrema catch an intermediate boundary crossing even
        # when a reversal would return inside by the final sample.
        points=[dt]
        if acceleration and 0 < -v0/acceleration < min(dt,ramp):points.append(-v0/acceleration)
        if 0 < ramp < dt:points.append(ramp)
        for t in sorted(points):
            value=at(t)
            if value >= axis.maximum_deg:return axis.maximum_deg,0.
            if value <= axis.minimum_deg:return axis.minimum_deg,0.
        velocity=target if dt>=ramp else v0+acceleration*dt
        return at(dt),velocity

    def step(self,velocity,dt):
        if not isinstance(velocity,AngularVelocity) or not finite(dt) or not 0<=dt<=self.config.max_update_interval+1e-9:
            self.stop()
            raise ValueError('Virtual step requires a valid velocity and bounded nonnegative dt')
        axes=(self.config.pan,self.config.tilt)
        targets=[velocity.pan_deg_s,velocity.tilt_deg_s]
        if any(not finite(v) or abs(v)>a.max_speed_deg_s+1e-9 for v,a in zip(targets,axes)):
            self.stop();raise ValueError('Requested virtual speed exceeds configured axis limit')
        norm=sum((v/a.max_speed_deg_s)**2 for v,a in zip(targets,axes))
        if norm>1+1e-9:
            self.stop();raise ValueError('Combined normalized virtual speed must not exceed one')
        for i,(target,axis) in enumerate(zip(targets,axes)):
            if (target==0 or self._angles[i]>=axis.maximum_deg and target>0
                    or self._angles[i]<=axis.minimum_deg and target<0):
                # Inactive axes and limit stops do not coast.
                self._velocities[i]=targets[i]=0.
        ramp=max(abs(target-v)/axis.max_acceleration_deg_s2 for target,v,axis in zip(targets,self._velocities,axes))
        self._targets[:]=targets
        if dt==0:return self.snapshot()
        for i,(target,axis) in enumerate(zip(targets,axes)):
            self._angles[i],self._velocities[i]=self._integrate(self._angles[i],self._velocities[i],target,dt,ramp,axis)
            if self._angles[i] in (axis.minimum_deg,axis.maximum_deg) and self._velocities[i]==0:
                self._targets[i]=0.
        return self.snapshot()
