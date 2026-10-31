from dataclasses import FrozenInstanceError, replace
import math
import unittest
from unittest.mock import patch

from motor_control.models import (AngularVelocity, AxisConfig, MotorConfig, MotorInput, MotorReason as R, MotorStatus as S)
from motor_control.controller import MotorController
from motor_control.simulator import SimulatedMotorDriver
from hand_tracking.performance import Profile


def motor_input(t=1.,pan=1.,tilt=0.,key=1):
    return MotorInput(pan,tilt,t,round(t*1000),key,True,R.TRACKING if pan or tilt else R.CENTERED)


class ControllerTest(unittest.TestCase):
    def controller(self,**kwargs):return MotorController(enabled=True,**kwargs)

    def test_defaults_are_virtual_and_disabled(self):
        motor=MotorController()
        state=motor.update(motor_input(),now=1)
        self.assertEqual(state.status,S.DISABLED)
        self.assertEqual((state.pan.angle_deg,state.tilt.angle_deg),(0,0))
        self.assertFalse(state.hardware_output_enabled)

    def test_enabled_start_has_zero_velocity_and_no_first_frame_jump(self):
        motor=self.controller()
        state=motor.update(motor_input(),now=1)
        self.assertEqual(state.reason,R.INITIALIZING)
        self.assertEqual(state.pan.velocity_deg_s,0)
        self.assertEqual(state.pan.angle_deg,0)

    def test_pan_and_tilt_directions(self):
        for pan,tilt in ((1,0),(-1,0),(0,1),(0,-1)):
            motor=self.controller();motor.update(motor_input(1,pan,tilt),now=1)
            state=motor.update(motor_input(1.02,pan,tilt),now=1.02)
            self.assertGreater(state.pan.angle_deg*pan+state.tilt.angle_deg*tilt,0)

    def test_demand_maps_to_degrees_per_second(self):
        motor=self.controller();motor.update(motor_input(1,.5,-.25),now=1)
        state=motor.update(motor_input(1.02,.5,-.25),now=1.02)
        self.assertEqual(state.command.requested,AngularVelocity(15,-5))

    def test_diagonal_demand_is_normalized_not_amplified(self):
        motor=self.controller();motor.update(motor_input(1,1,1),now=1)
        state=motor.update(motor_input(1.02,1,1),now=1.02)
        self.assertAlmostEqual(state.command.requested.pan_deg_s,30/math.sqrt(2))
        self.assertAlmostEqual(state.command.requested.tilt_deg_s,20/math.sqrt(2))

    def test_positions_match_at_30_and_60_fps(self):
        results=[]
        for fps in (30,60):
            motor=self.controller()
            for i in range(fps+1):state=motor.update(motor_input(i/fps),now=i/fps)
            results.append(state.pan.angle_deg)
        self.assertAlmostEqual(results[0],22.5,places=8)
        self.assertAlmostEqual(results[0],results[1],places=8)

    def test_ordinary_acceleration_and_speed_bounds(self):
        motor=self.controller();previous=motor.update(motor_input(0,1,1),now=0)
        for i in range(1,61):
            state=motor.update(motor_input(i/60,1,1),now=i/60)
            for a,b,cfg in ((previous.pan,state.pan,motor.config.pan),(previous.tilt,state.tilt,motor.config.tilt)):
                self.assertLessEqual(abs(b.velocity_deg_s-a.velocity_deg_s),cfg.max_acceleration_deg_s2/60+1e-9)
                self.assertLessEqual(abs(b.velocity_deg_s),cfg.max_speed_deg_s)
            self.assertLessEqual(math.hypot(state.pan.velocity_deg_s/30,state.tilt.velocity_deg_s/20),1+1e-9)
            previous=state

    def test_coupled_ramp_preserves_vector_limit_with_unequal_accelerations(self):
        config=MotorConfig(pan=AxisConfig(-180,180,30,300),tilt=AxisConfig(-180,180,20,10))
        motor=self.controller(config=config)
        for i in range(120):
            state=motor.update(motor_input(i/60,1 if i<60 else 0,0 if i<60 else 1),now=i/60)
            self.assertLessEqual(math.hypot(state.pan.velocity_deg_s/30,state.tilt.velocity_deg_s/20),1+1e-9)

    def test_variable_time_intervals_match_analytic_ramp(self):
        motor=self.controller()
        for t in (0,.01,.04,.10,.13,.2,.28,.37,.45,.5,.58,.66,.75,.83,.9,1):
            state=motor.update(motor_input(t),now=t)
        self.assertAlmostEqual(state.pan.angle_deg,22.5,places=8)

    def test_all_virtual_angle_limits(self):
        for pan,tilt,expected in ((1,0,45),(-1,0,-45),(0,1,25),(0,-1,-25)):
            motor=self.controller()
            for i in range(240):state=motor.update(motor_input(i/60,pan,tilt),now=i/60)
            axis=state.pan if pan else state.tilt
            self.assertEqual(axis.angle_deg,expected)
            self.assertEqual(axis.velocity_deg_s,0)
            self.assertEqual(axis.target_velocity_deg_s,0)
            self.assertEqual(state.status,S.LIMIT_REACHED)
            self.assertEqual(motor.metadata()['counters']['limit_hits'],1)

    def test_limit_permits_return_toward_valid_range(self):
        motor=self.controller()
        for i in range(180):state=motor.update(motor_input(i/60),now=i/60)
        self.assertEqual(state.pan.angle_deg,45)
        state=motor.update(motor_input(3,-1),now=3)
        self.assertLess(state.pan.angle_deg,45)
        self.assertLess(state.pan.velocity_deg_s,0)

    def test_first_limit_contact_clears_target_and_accepted_command_immediately(self):
        motor=self.controller(config=MotorConfig(pan=AxisConfig(-1,1,30,60)))
        for i in range(60):
            state=motor.update(motor_input(i/60),now=i/60)
            if state.pan.at_maximum:break
        self.assertTrue(state.pan.at_maximum)
        self.assertEqual(state.pan.velocity_deg_s,0)
        self.assertEqual(state.pan.target_velocity_deg_s,0)
        self.assertEqual(state.command.accepted,AngularVelocity())
        self.assertEqual(state.command.requested.pan_deg_s,30)

    def test_zero_demand_immediately_stops_without_coasting_or_drift(self):
        motor=self.controller()
        for i in range(15):state=motor.update(motor_input(i/60),now=i/60)
        angle=state.pan.angle_deg
        for i in range(15,60):
            state=motor.update(motor_input(i/60,0,0),now=i/60)
            self.assertEqual(state.pan.angle_deg,angle)
            self.assertEqual(state.pan.velocity_deg_s,0)
            self.assertEqual(state.status,S.CENTERED)

    def test_inactive_axis_does_not_coast_while_other_axis_moves(self):
        motor=self.controller()
        for i in range(20):state=motor.update(motor_input(i/60,1,1),now=i/60)
        pan=state.pan.angle_deg
        state=motor.update(motor_input(20/60,0,1),now=20/60)
        self.assertEqual(state.pan.angle_deg,pan)
        self.assertEqual(state.pan.velocity_deg_s,0)
        self.assertGreater(state.tilt.velocity_deg_s,0)

    def test_direction_reversal_obeys_normal_acceleration(self):
        motor=self.controller()
        for i in range(20):state=motor.update(motor_input(i/60),now=i/60)
        before=state.pan.velocity_deg_s
        state=motor.update(motor_input(20/60,-1),now=20/60)
        self.assertAlmostEqual(state.pan.velocity_deg_s,before-1)

    def test_invalid_demands_stop_immediately(self):
        for demand in (1.1,-1.1,math.nan,math.inf,None,True):
            motor=self.controller();motor.update(motor_input(),now=1)
            motor.update(motor_input(1.02),now=1.02)
            state=motor.update(replace(motor_input(1.04),pan_demand=demand),now=1.04)
            self.assertEqual(state.reason,R.INVALID_DEMAND)
            self.assertEqual(state.command.accepted,AngularVelocity())
            self.assertEqual(state.pan.velocity_deg_s,0)

    def test_invalid_ids_are_not_authorized(self):
        for key in (None,0,-1,True,1.5):
            state=self.controller().update(replace(motor_input(),tracking_id=key),now=1)
            self.assertEqual(state.reason,R.INVALID_OBSERVATION)
            self.assertFalse(state.command.valid)

    def test_unsafe_tracking_states_stop_without_acceleration_ramp(self):
        for reason in (R.NO_TARGET,R.WAITING_FOR_TARGET,R.TARGET_LOST,R.TARGET_UNCERTAIN,R.STALE_OBSERVATION,R.INVALID_OBSERVATION):
            motor=self.controller();motor.update(motor_input(),now=1)
            before=motor.update(motor_input(1.02),now=1.02)
            unsafe=replace(motor_input(1.04),valid=False,reason=reason)
            after=motor.update(unsafe,now=1.04)
            self.assertEqual(after.pan.angle_deg,before.pan.angle_deg)
            self.assertEqual(after.pan.velocity_deg_s,0)
            self.assertEqual(after.command.accepted,AngularVelocity())
            self.assertEqual(after.reason,reason)

    def test_no_input_stops_and_preserves_pose(self):
        motor=self.controller();motor.update(motor_input(),now=1)
        before=motor.update(motor_input(1.02),now=1.02)
        after=motor.update(None,now=1.04)
        self.assertEqual(after.pan.angle_deg,before.pan.angle_deg)
        self.assertEqual(after.reason,R.NO_TARGET)

    def test_stale_observation_cannot_refresh_or_drive(self):
        motor=self.controller()
        state=motor.update(motor_input(),now=1.251)
        self.assertEqual(state.reason,R.STALE_OBSERVATION)
        self.assertEqual(state.pan.angle_deg,0)

    def test_invalid_observation_time(self):
        for stamp in (None,True,math.nan,math.inf,-1,2):
            state=self.controller().update(replace(motor_input(),observation_timestamp=stamp),now=1)
            self.assertEqual(state.reason,R.INVALID_TIMESTAMP)
            self.assertFalse(state.moving)

    def test_invalid_source_time(self):
        for stamp in (None,-1,True,math.nan,1.5,2**10000):
            state=self.controller().update(replace(motor_input(),source_timestamp_ms=stamp),now=1)
            self.assertEqual(state.reason,R.INVALID_TIMESTAMP)

    def test_repeated_source_or_actual_timestamp_cannot_replay_command(self):
        for values in ({'source_timestamp_ms':1000},{'observation_timestamp':1}):
            motor=self.controller();motor.update(motor_input(),now=1)
            state=motor.update(replace(motor_input(1.02),**values),now=1.02)
            self.assertEqual(state.reason,R.REPLAY)
            self.assertEqual(state.pan.velocity_deg_s,0)

    def test_invalid_backward_and_repeated_host_clock(self):
        for now in (None,True,math.nan,math.inf,-1,.9,1):
            motor=self.controller();motor.update(motor_input(),now=1)
            state=motor.update(motor_input(1.02),now=now)
            self.assertEqual(state.reason,R.INVALID_TIMESTAMP)
            self.assertFalse(state.moving)

    def test_large_stall_discards_motion_and_requires_new_observations(self):
        motor=self.controller();motor.update(motor_input(),now=1)
        before=motor.update(motor_input(1.02),now=1.02)
        stalled=motor.update(motor_input(2),now=2)
        self.assertEqual(stalled.reason,R.STALLED)
        self.assertEqual(stalled.pan.angle_deg,before.pan.angle_deg)
        replay=motor.update(motor_input(2),now=2.01)
        self.assertEqual(replay.reason,R.REPLAY)
        resumed=motor.update(motor_input(2.02),now=2.02)
        self.assertEqual(resumed.reason,R.INITIALIZING)
        self.assertEqual(resumed.pan.angle_deg,before.pan.angle_deg)
        self.assertTrue(motor.update(motor_input(2.04),now=2.04).moving)

    def test_timeout_check_stops_but_never_integrates_or_refreshes_time(self):
        motor=self.controller();motor.update(motor_input(),now=1)
        before=motor.update(motor_input(1.02),now=1.02)
        state=motor.check_timeout(now=1.13)
        self.assertEqual(state.reason,R.STALLED)
        self.assertEqual(state.pan.angle_deg,before.pan.angle_deg)
        self.assertEqual(state.last_valid_update,before.last_valid_update)
        self.assertEqual(state.command.observation_timestamp,before.command.observation_timestamp)

    def test_timeout_check_inside_interval_returns_same_snapshot(self):
        motor=self.controller();state=motor.update(motor_input(),now=1)
        self.assertIs(motor.check_timeout(now=1.05),state)

    def test_reacquisition_does_not_resume_old_velocity(self):
        motor=self.controller();motor.update(motor_input(),now=1)
        before=motor.update(motor_input(1.02),now=1.02)
        motor.update(MotorInput(reason=R.TARGET_LOST),now=1.04)
        recovered=motor.update(motor_input(1.06,-1),now=1.06)
        self.assertEqual(recovered.pan.angle_deg,before.pan.angle_deg)
        self.assertEqual(recovered.pan.velocity_deg_s,0)
        self.assertLess(motor.update(motor_input(1.08,-1),now=1.08).pan.velocity_deg_s,0)

    def test_target_id_change_stops_and_does_not_transfer_velocity(self):
        motor=self.controller();motor.update(motor_input(),now=1)
        before=motor.update(motor_input(1.02),now=1.02)
        state=motor.update(motor_input(1.04,-1,key=2),now=1.04)
        self.assertEqual(state.reason,R.TARGET_CHANGED)
        self.assertEqual(state.pan.angle_deg,before.pan.angle_deg)
        self.assertEqual(state.pan.velocity_deg_s,0)

    def test_disable_reenable_and_shutdown_hold_pose(self):
        motor=self.controller();motor.update(motor_input(),now=1)
        before=motor.update(motor_input(1.02),now=1.02)
        motor.set_enabled(False,now=1.03)
        state=motor.update(motor_input(1.04),now=1.04)
        self.assertEqual(state.status,S.DISABLED)
        self.assertEqual(state.pan.angle_deg,before.pan.angle_deg)
        motor.set_enabled(True,now=1.05)
        self.assertEqual(motor.update(motor_input(1.06),now=1.06).reason,R.INITIALIZING)
        self.assertEqual(motor.shutdown(now=1.07).reason,R.SHUTDOWN)

    def test_models_are_immutable_and_cannot_enable_hardware(self):
        state=self.controller().state
        with self.assertRaises(FrozenInstanceError):state.pan.angle_deg=100
        with self.assertRaises(TypeError):replace(state,hardware_output_enabled=True)
        self.assertFalse(state.hardware_output_enabled)

    def test_profile_is_opt_in_and_bounded(self):
        motor=self.controller();profile=Profile(capacity=2)
        for i in range(10):motor.update(motor_input(1+i*.02),now=1.01+i*.02,profile=profile)
        s=profile.summary()
        self.assertEqual(s['motor_control_update']['count'],10)
        self.assertEqual(s['motor_simulated_step']['percentile_samples'],2)
        self.assertAlmostEqual(s['motor_observation_age']['mean_ms'],10)

    def test_no_calculation_timer_when_profile_disabled(self):
        with patch('motor_control.controller.time.perf_counter',side_effect=AssertionError('timer read')):
            self.controller().update(motor_input(),now=1,profile=Profile(enabled=False))

    def test_long_session_metadata_has_bounded_keys(self):
        motor=self.controller()
        for i in range(1000):motor.update(motor_input(i*.02,1 if i%2 else -1),now=i*.02)
        self.assertLessEqual(len(motor.reasons),len(R))
        self.assertLess(len(motor.counts),15)
        self.assertFalse(motor.metadata()['hardware_output_enabled'])

    def test_invalid_virtual_config(self):
        for args in ((-45,45,0,60),(-181,45,30,60),(-45,-45,30,60),(-45,45,math.inf,60),(-45,45,30,3601),(-45,45,30,60,46)):
            with self.assertRaises(ValueError):AxisConfig(*args)
        for kwargs in ({'max_update_interval':0},{'max_observation_age':.3},{'pan':None}):
            with self.assertRaises(ValueError):MotorConfig(**kwargs)

    def test_driver_fault_leaves_controller_stopped_before_exception(self):
        motor=self.controller();motor.update(motor_input(),now=1)
        motor.update(motor_input(1.02),now=1.02)
        with patch.object(motor._driver,'step',side_effect=RuntimeError('driver fault')),self.assertRaises(RuntimeError):
            motor.update(motor_input(1.04),now=1.04)
        self.assertEqual(motor.state.status,S.FAULTED)
        self.assertFalse(motor.state.moving)


class DriverTest(unittest.TestCase):
    def test_direct_driver_rejects_bad_dt_and_velocity_and_stops(self):
        driver=SimulatedMotorDriver()
        driver.step(AngularVelocity(30,0),.02)
        for velocity,dt in ((AngularVelocity(31,0),.02),(AngularVelocity(30,20),.02),(AngularVelocity(),.2),(AngularVelocity(),math.nan)):
            with self.assertRaises(ValueError):driver.step(velocity,dt)
            self.assertEqual(driver.snapshot()[0].velocity_deg_s,0)

    def test_intermediate_reversal_peak_cannot_cross_angle_limit(self):
        driver=SimulatedMotorDriver(MotorConfig(pan=AxisConfig(-45,45,30,3600,44.999801)))
        driver.step(AngularVelocity(.2,0),.001)
        pan,_=driver.step(AngularVelocity(-30,0),.1)
        self.assertEqual(pan.angle_deg,45)
        self.assertEqual(pan.velocity_deg_s,0)
        self.assertEqual(pan.target_velocity_deg_s,0)
