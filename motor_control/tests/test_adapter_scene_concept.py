from dataclasses import replace
import math
from pathlib import Path
import re
import unittest

import cv2
import numpy as np

from face_tracking.centering import FaceCentering, CorrectionDirection
from face_tracking.tests.test_centering import observation
from motor_control.centering_adapter import from_centering
from motor_control.closed_loop import SceneConfig, project_target, run_scene
from motor_control.controller import MotorController
from motor_control.models import AxisConfig, MotorConfig, MotorReason as R
from motor_control.visualization import MotorRenderer
from .test_controller import motor_input


class AdapterTest(unittest.TestCase):
    def test_uses_actual_smoothed_centering_demand_and_keeps_timestamp(self):
        result=FaceCentering().update(observation(1,x=.5,y=-.3),now=1)
        request=from_centering(result,now=1.02)
        self.assertEqual(request.pan_demand,result.horizontal.demand)
        self.assertEqual(request.tilt_demand,result.vertical.demand)
        self.assertEqual(request.observation_timestamp,1)
        self.assertTrue(request.valid)

    def test_centered_input_is_valid_zero(self):
        request=from_centering(FaceCentering().update(observation(),now=1),now=1)
        self.assertTrue(request.valid)
        self.assertEqual((request.pan_demand,request.tilt_demand),(0,0))
        self.assertEqual(request.reason,R.CENTERED)

    def test_lost_tentative_expired_uncertain_and_missing_are_unsafe(self):
        for kwargs,reason in (({'state':'LOST','visible':False},R.TARGET_LOST),
                              ({'state':'TENTATIVE'},R.WAITING_FOR_TARGET),
                              ({'state':'EXPIRED','visible':False},R.TARGET_LOST),
                              ({'uncertain':True},R.TARGET_UNCERTAIN)):
            result=FaceCentering().update(observation(x=.5,**kwargs),now=1)
            request=from_centering(result,now=1)
            self.assertFalse(request.valid)
            self.assertEqual(request.reason,reason)
        self.assertEqual(from_centering(None,now=1).reason,R.NO_TARGET)

    def test_stale_source_is_not_refreshed_by_adapter(self):
        result=FaceCentering().update(observation(x=.5),now=1)
        request=from_centering(result,now=1.3)
        self.assertFalse(request.valid)
        self.assertEqual(request.reason,R.STALE_OBSERVATION)
        self.assertEqual(request.observation_timestamp,1)

    def test_bad_clock_and_geometry_are_not_validated(self):
        result=FaceCentering().update(observation(x=.5),now=1)
        for changes in ({'observation_timestamp':math.nan},{'observation_timestamp':None},{'evaluated_at':math.inf},
                        {'max_observation_age':1},{'smoothed_center':None},{'smoothed_center':(1,2,3)},
                        {'frame_size':(0,1)}):
            self.assertFalse(from_centering(replace(result,**changes),now=1).valid)

    def test_invalid_or_inactive_nonzero_demand_is_not_authorized(self):
        result=FaceCentering().update(observation(x=.5),now=1)
        for changes in ({'demand':math.nan},{'demand':1.1},{'active':False},
                        {'direction':CorrectionDirection.PAN_LEFT}):
            bad=replace(result,horizontal=replace(result.horizontal,**changes))
            self.assertFalse(from_centering(bad,now=1).valid)

    def test_adapter_never_modifies_real_coordinates(self):
        observed=observation(x=.5)
        result=FaceCentering().update(observed,now=1)
        original=(result.raw_center,result.smoothed_center,observed.primary.raw)
        request=from_centering(result,now=1)
        motor=MotorController(enabled=True)
        for i in range(10):
            t=1+i*.02
            motor.update(replace(request,observation_timestamp=t,source_timestamp_ms=round(t*1000)),now=t)
        self.assertEqual(original,(result.raw_center,result.smoothed_center,observed.primary.raw))


class SceneTest(unittest.TestCase):
    def test_projection_directions_and_camera_feedback(self):
        scene=SceneConfig(60,40,target_pan_deg=18,target_tilt_deg=8)
        initial=project_target(scene,0,0)
        self.assertGreater(initial[0],0);self.assertGreater(initial[1],0)
        self.assertLess(abs(project_target(scene,10,0)[0]),abs(initial[0]))
        self.assertLess(abs(project_target(scene,0,5)[1]),abs(initial[1]))

    def test_camera_pointing_at_world_target_has_zero_error(self):
        scene=SceneConfig(60,40)
        self.assertLess(math.hypot(*project_target(scene,18,-8)),1e-12)

    def test_closed_loop_reduces_error_without_hardware_output(self):
        report=run_scene(SceneConfig(60,40,duration=6))
        self.assertLess(math.hypot(*report['final_error']),.15)
        self.assertLess(math.hypot(*report['final_error']),math.hypot(*report['initial_error'])/4)
        self.assertFalse(report['motor']['hardware_output_enabled'])
        self.assertLessEqual(len(report['samples']),256)

    def test_30_and_60_fps_feedback_results_are_close(self):
        reports=[run_scene(SceneConfig(60,40,duration=6,fps=fps)) for fps in (30,60)]
        self.assertLess(abs(reports[0]['final_error'][0]-reports[1]['final_error'][0]),.01)
        self.assertLess(abs(reports[0]['final_error'][1]-reports[1]['final_error'][1]),.01)

    def test_closed_loop_limits_are_enforced(self):
        config=MotorConfig(pan=AxisConfig(-5,5,30,60),tilt=AxisConfig(-4,4,20,40))
        report=run_scene(SceneConfig(90,60,duration=5),motor_config=config)
        for item in report['samples']:
            self.assertLessEqual(abs(item['pan_deg']),5)
            self.assertLessEqual(abs(item['tilt_deg']),4)
        self.assertGreater(report['motor']['counters']['limit_hits'],0)

    def test_loss_interval_stops_motion_and_recovers(self):
        report=run_scene(SceneConfig(60,40,duration=4),loss_interval=(1,1.5))
        lost=[s for s in report['samples'] if 1<=s['time']<1.5]
        self.assertTrue(lost)
        self.assertTrue(all(s['pan_velocity_deg_s']==0 and s['tilt_velocity_deg_s']==0 for s in lost))
        self.assertTrue(all(s['pan_deg']==lost[0]['pan_deg'] for s in lost))

    def test_projection_behind_camera_is_unavailable(self):
        self.assertIsNone(project_target(SceneConfig(60,40),180,0))

    def test_invalid_assumed_fov_and_scene_settings(self):
        for args in ((0,40),(180,40),(60,math.nan),(60,-1)):
            with self.assertRaises(ValueError):SceneConfig(*args)
        with self.assertRaises(ValueError):SceneConfig(60,40,fps=0)
        with self.assertRaises(ValueError):run_scene(SceneConfig(60,40),loss_interval=(2,1))


class VisualizationConceptTest(unittest.TestCase):
    def test_renderer_uses_virtual_state_and_reuses_buffer(self):
        motor=MotorController(enabled=True)
        for i in range(30):state=motor.update(motor_input(i/60,.8,-.4),now=i/60)
        renderer=MotorRenderer(debug=True)
        one=renderer.render(state,motor.config)
        self.assertEqual(one.shape,(390,540,3))
        self.assertIs(one,renderer.render(state,motor.config))
        self.assertGreater(int(one.sum()),0)
        self.assertFalse(state.hardware_output_enabled)
        renderer.close();self.assertIsNone(renderer.buffer)

    def test_concept_source_exists_with_editable_parameters_and_layout_modules(self):
        root=Path(__file__).resolve().parents[2]
        source=(root/'hardware/concepts/pan_tilt_concept.scad').read_text(encoding='utf-8')
        for parameter in ('base_width','base_depth','base_height','camera_width','camera_depth','camera_height',
                          'bracket_spacing','pan_deg','tilt_deg','pan_motor_size','tilt_motor_size','camera_mount_offset'):
            self.assertRegex(source,rf'\b{parameter}\s*=')
        for module in ('stationary_base','tilt_brackets','camera_cradle','moving_assembly'):
            self.assertIn(f'module {module}()',source)
        self.assertIn('NOT FOR FABRICATION',source)

    def test_concept_delimiters_balance_without_claiming_scad_compilation(self):
        root=Path(__file__).resolve().parents[2]
        source=(root/'hardware/concepts/pan_tilt_concept.scad').read_text(encoding='utf-8')
        text=re.sub(r'/\*.*?\*/|//[^\n]*|"(?:[^"\\]|\\.)*"','',source,flags=re.S)
        stack=[]
        for char in text:
            if char in '([{':stack.append(char)
            elif char in ')]}':self.assertEqual(stack.pop(),{')':'(',']':'[','}':'{'}[char])
        self.assertFalse(stack)

    def test_concept_is_documented_as_independent_unverified_source(self):
        root=Path(__file__).resolve().parents[2]
        text=(root/'hardware/concepts/README.md').read_text(encoding='utf-8')
        self.assertIn('not an application dependency',text)
        self.assertIn('no OpenSCAD compilation',text)
        self.assertIn('not for fabrication',text)
