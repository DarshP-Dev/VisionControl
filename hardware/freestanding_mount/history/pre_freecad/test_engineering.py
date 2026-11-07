import ast
import json
import math
from pathlib import Path
import unittest
import engineering

ROOT=Path(__file__).resolve().parent

class EngineeringChecks(unittest.TestCase):
    def setUp(self):self.p=json.loads((ROOT/'parameters.json').read_text())
    def test_camera_interface_stays_blank(self):self.assertFalse(self.p['CameraHoleEnabled'])
    def test_height_and_cover_clearance(self):
        r=engineering.calculate(self.p)
        self.assertGreaterEqual(r['optical_height_desk_mm'],101.6)
        self.assertGreater(self.p['FootThickness']-1,3)
    def test_torque_units_and_cable_sensitivity(self):
        r=engineering.calculate(self.p)
        self.assertAlmostEqual(r['advertised_stall_Nm'],.196133)
        high=engineering.calculate(dict(self.p,AssumedCableForceN=1.))
        self.assertAlmostEqual(high['conservative_sum_Nm']-r['conservative_sum_Nm'],.032)
        self.assertGreater(high['conservative_sum_Nm'],high['planning_screen_25pct_stall_Nm'])
    def test_ballast_meets_assumed_moment_equation(self):
        s=engineering.calculate(self.p)['stability']
        mass=(self.p['AssumedFixedMassG']+self.p['AssumedTotalMovingMassG']+s['required_ballast_g'])/1000
        self.assertAlmostEqual(mass*9.80665*s['support_half_span_m'],self.p['TargetTipMargin']*(s['offset_moment_Nm']+s['external_moment_Nm']))
    def test_wider_support_reduces_required_ballast(self):
        a=engineering.calculate(self.p)['stability']['required_ballast_g']
        b=engineering.calculate(dict(self.p,BaseWidth=140.,BaseDepth=120.))['stability']['required_ballast_g']
        self.assertLess(b,a)
    def test_floor_corner_formula(self):
        r=engineering.calculate(self.p);a=math.radians(self.p['TiltLimit'])
        expected=self.p['TiltAxisZ']-(self.p['CameraBottomBelowAxis']+2*self.p['Wall'])*math.cos(a)-self.p['CradleDepth']/2*math.sin(a)
        self.assertAlmostEqual(r['cradle_floor_corner_min_z_mm'],expected)
        self.assertGreater(expected-(self.p['PanDeckZ']+self.p['Wall'])-3,3)
    def test_python_syntax_only(self):
        for path in ROOT.glob('*.py'):
            with self.subTest(path=path.name):ast.parse(path.read_text(encoding='utf-8'))

if __name__=='__main__':unittest.main()
