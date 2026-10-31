from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from face_tracking import benchmark_tracking as benchmark


class TrackingBenchmarkTest(unittest.TestCase):
    def test_paired_report_uses_synthetic_units_and_never_opens_camera(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory)/'benchmark.json'
            with patch.object(benchmark, 'memory_probe', return_value={'separate_probe': True}), \
                    patch('cv2.VideoCapture', side_effect=AssertionError('camera opened')), redirect_stdout(io.StringIO()):
                benchmark.main(['--frames','12','--warmup','3','--repeats','1','--faces','1','--report',str(path)])
            saved = json.loads(path.read_text())
            self.assertEqual(saved['kind'], 'synthetic_host_only')
            self.assertEqual(len(saved['cases']), 4)
            self.assertEqual(len(saved['comparisons']), 2)
            self.assertEqual(len(saved['source_sha256']['face_tracker.py']), 64)
            self.assertTrue(saved['continuity_probe']['crossing_current_coordinates_withheld'])
            for case in saved['cases']:
                self.assertEqual(case['timings']['host_total']['count'], 12)
                if case['tracking']:
                    self.assertEqual(case['synthetic_known_trajectory_id_switches'], 0)
                    self.assertIn('face_association', case['timings'])
                else:
                    self.assertNotIn('face_tracking', case['timings'])
            with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit), patch('sys.stderr', io.StringIO()):
                benchmark.main(['--report',str(path)])

    def test_invalid_benchmark_workload_is_rejected(self):
        for values in ({'faces':3}, {'frames':0}, {'warmup':-1}):
            with self.assertRaises(ValueError):
                benchmark.run_case(**values)
