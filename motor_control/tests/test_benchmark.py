from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import unittest

import cv2

from motor_control import benchmark, closed_loop


class BenchmarkTest(unittest.TestCase):
    def test_benchmark_json_is_synthetic_and_does_not_open_camera_or_gui(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path=Path(directory)/'report.json'
            with patch.object(benchmark,'motor_only',return_value={}),patch.object(benchmark,'memory_probe',return_value={}), \
                    patch.object(benchmark,'render_probe',return_value=[]),patch.object(benchmark,'run_scene',return_value={}), \
                    patch.object(cv2,'VideoCapture',side_effect=AssertionError('camera opened')), \
                    patch.object(cv2,'imshow',side_effect=AssertionError('GUI opened')),redirect_stdout(io.StringIO()):
                benchmark.main(['--frames','6','--warmup','3','--repeats','1','--render-frames','2','--report',str(path)])
            saved=json.loads(path.read_text())
            self.assertEqual(saved['kind'],'synthetic_simulation_and_host_only')
            self.assertEqual(len(saved['cases']),8)
            self.assertEqual(len(saved['comparisons']),4)
            for case in saved['cases']:
                self.assertEqual(case['timings']['host_total']['count'],6)
                self.assertEqual('motor_control_update' in case['timings'],case['motor_simulation'])
            with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):benchmark.main(['--report',str(path)])

    def test_closed_loop_requires_explicit_fov_and_refuses_overwriting(self):
        with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):closed_loop.main(['--report','unused.json'])
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path=Path(directory)/'scene.json'
            with redirect_stdout(io.StringIO()):
                closed_loop.main(['--horizontal-fov','60','--vertical-fov','40','--duration','1','--report',str(path)])
            saved=json.loads(path.read_text())
            self.assertEqual(saved['mode'],'synthetic_closed_loop')
            self.assertFalse(saved['motor']['hardware_output_enabled'])
            with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                closed_loop.main(['--horizontal-fov','60','--vertical-fov','40','--report',str(path)])

    def test_invalid_benchmark_settings(self):
        with self.assertRaises(ValueError):benchmark.motor_only(frames=0)
        with self.assertRaises(ValueError):benchmark.run_case(warmup=-1)
