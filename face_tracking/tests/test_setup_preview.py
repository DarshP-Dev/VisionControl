import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from face_tracking import download_model as setup
from face_tracking.face_geometry import adapt_result
from face_tracking.preview import draw_faces
from .helpers import detection,result


class SetupPreviewTest(unittest.TestCase):
    def test_download_is_explicit_versioned_verified_and_exclusive(self):
        data=b'test model';digest=hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            path=Path(directory)/'model.tflite'
            with patch.object(setup,'MODEL_SHA256',digest),patch.object(setup.urllib.request,'urlopen',return_value=io.BytesIO(data)) as url:
                setup.download_model(path);setup.download_model(path)
            self.assertEqual(path.read_bytes(),data);url.assert_called_once()
            self.assertIn('/float16/1/',url.call_args.args[0])

    def test_invalid_download_does_not_create_or_overwrite_model(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            path=Path(directory)/'model.tflite'
            with patch.object(setup.urllib.request,'urlopen',return_value=io.BytesIO(b'bad')),self.assertRaises(ValueError):
                setup.download_model(path)
            self.assertFalse(path.exists())
            path.write_bytes(b'existing')
            with patch.object(setup.urllib.request,'urlopen') as url,self.assertRaises(ValueError):setup.download_model(path)
            url.assert_not_called();self.assertEqual(path.read_bytes(),b'existing')

    def test_current_overlay_includes_boxes_centers_scores_offsets(self):
        r=adapt_result(result(detection(),detection(x=0,score=.8)),(640,360),(1920,1080),1)
        with patch.object(cv2,'rectangle') as rectangle,patch.object(cv2,'circle') as circle, \
                patch.object(cv2,'line') as line,patch.object(cv2,'putText') as text:
            draw_faces(np.zeros((540,960,3),np.uint8),r)
        self.assertEqual(rectangle.call_count,2);self.assertEqual(circle.call_count,2);line.assert_called_once()
        self.assertTrue(any('X: +0.00' in c.args[1] for c in text.call_args_list))

    def test_empty_overlay_does_not_draw_previous_coordinates(self):
        with patch.object(cv2,'rectangle') as rectangle,patch.object(cv2,'putText') as text:
            draw_faces(np.zeros((50,100,3),np.uint8),adapt_result(result(),(100,50),(100,50),2))
        rectangle.assert_not_called();self.assertIn('none',text.call_args.args[1])
