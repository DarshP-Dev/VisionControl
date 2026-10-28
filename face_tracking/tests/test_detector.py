from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from face_tracking.face_detector import FaceDetector, FaceDetectionError
from hand_tracking.performance import Profile
from .helpers import MP, detection, result


class DetectorTest(unittest.TestCase):
    def detector(self, **kwargs):
        backend=MagicMock();backend.detect.return_value=result(detection())
        d=FaceDetector(mp=MP,backend=backend,**kwargs);self.addCleanup(d.close)
        return d,backend

    def test_resize_original_coordinates_and_bgr_to_rgb(self):
        d,b=self.detector();frame=np.zeros((1080,1920,3),np.uint8);frame[:]=[1,2,3]
        f=d.detect(frame,12,Profile())
        image=b.detect.call_args.args[0];self.assertEqual(image.shape,(360,640,3))
        np.testing.assert_array_equal(image[0,0],[3,2,1]);self.assertEqual(f.primary.center_x,960)

    def test_full_resolution_and_buffer_reuse(self):
        d,b=self.detector(bounds=None);frame=np.zeros((100,200,3),np.uint8)
        d.detect(frame,1,Profile());original=d.rgb
        d.detect(frame,2,Profile());self.assertIs(d.rgb,original)
        self.assertEqual(b.detect.call_args.args[0].shape,frame.shape)

    def test_current_rgb_hint_avoids_duplicate_color_conversion(self):
        d,b=self.detector();frame=np.zeros((1080,1920,3),np.uint8);hint=np.full((1080,1920,3),7,np.uint8)
        with patch.object(cv2,'cvtColor',side_effect=AssertionError('duplicate conversion')):
            d.detect(frame,1,Profile(),rgb_hint=hint)
        self.assertEqual(b.detect.call_args.args[0][0,0,0],7)

    def test_exact_sized_hint_is_used_without_resize_or_copy(self):
        d,b=self.detector();hint=np.zeros((360,640,3),np.uint8)
        with patch.object(cv2,'resize',side_effect=AssertionError('resize')):
            d.detect(np.zeros((1080,1920,3),np.uint8),1,Profile(),rgb_hint=hint)
        self.assertIs(b.detect.call_args.args[0],hint)

    def test_too_small_hint_does_not_reduce_face_resolution(self):
        d,b=self.detector();d.detect(np.zeros((1080,1920,3),np.uint8),1,Profile(),rgb_hint=np.zeros((90,160,3),np.uint8))
        self.assertEqual(b.detect.call_args.args[0].shape,(360,640,3))

    def test_no_history_or_coordinates_after_loss(self):
        d,b=self.detector();b.detect.side_effect=[result(detection()),result(),result(detection(x=0))]
        observations=[d.detect(np.zeros((360,640,3),np.uint8),n,Profile()) for n in range(3)]
        self.assertIsNone(observations[1].primary)
        self.assertNotEqual(observations[0].primary.center_x,observations[2].primary.center_x)

    def test_invalid_frames_do_not_call_backend(self):
        d,b=self.detector()
        for f in (None,np.zeros((0,10,3),np.uint8),np.zeros((10,10),np.uint8),np.zeros((10,10,4),np.uint8),np.zeros((10,10,3),float)):
            with self.assertRaises(ValueError):d.detect(f,0,Profile())
        b.detect.assert_not_called()

    def test_native_failure_is_fatal_no_previous_result(self):
        d,b=self.detector();b.detect.side_effect=RuntimeError('native fault')
        with self.assertRaisesRegex(FaceDetectionError,'native fault'):d.detect(np.zeros((20,20,3),np.uint8),1,Profile())

    def test_cleanup_idempotent_and_use_after_close_rejected(self):
        d,b=self.detector();d.close();d.close();b.close.assert_called_once()
        with self.assertRaises(FaceDetectionError):d.detect(np.zeros((20,20,3),np.uint8),1,Profile())

    def test_cpu_image_task_initialization_and_model_failure(self):
        mp=MagicMock();b=MagicMock();mp.tasks.vision.FaceDetector.create_from_options.return_value=b
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            model=Path(directory)/'test.tflite';model.write_bytes(b'fake')
            with patch('face_tracking.face_detector.verify_model'):
                d=FaceDetector(model,mp=mp);d.close()
            self.assertEqual(mp.tasks.vision.FaceDetectorOptions.call_args.kwargs['running_mode'],mp.tasks.vision.RunningMode.IMAGE)
            self.assertEqual(mp.tasks.BaseOptions.call_args.kwargs['delegate'],mp.tasks.BaseOptions.Delegate.CPU)
            with self.assertRaises(ValueError):FaceDetector(model,mp=mp)

    def test_profile_has_separate_face_stage_names(self):
        d,_=self.detector();p=Profile();d.detect(np.zeros((20,20,3),np.uint8),1,p)
        self.assertEqual(set(p.summary()),{'face_preprocessing','face_image','face_inference','face_geometry'})

    def test_buffers_handle_shape_changes_without_upscaling(self):
        d,b=self.detector()
        for shape in ((300,100,3),(20,40,3),(1080,1920,3)):
            f=d.detect(np.zeros(shape,np.uint8),1,Profile())
            self.assertLessEqual(f.inference_size[0],shape[1]);self.assertLessEqual(f.inference_size[1],shape[0])

    def test_incompatible_hint_aspect_does_not_distort_detection_geometry(self):
        d,b=self.detector();frame=np.zeros((1080,1920,3),np.uint8);frame[:]=[1,2,3]
        d.detect(frame,1,Profile(),rgb_hint=np.full((480,640,3),9,np.uint8))
        np.testing.assert_array_equal(b.detect.call_args.args[0][0,0],[3,2,1])

    def test_failed_native_cleanup_is_reported_and_inference_stays_stopped(self):
        d,b=self.detector();b.close.side_effect=[RuntimeError('cleanup fault'),None]
        with self.assertRaisesRegex(FaceDetectionError,'cleanup fault'):d.close()
        self.assertFalse(d.metadata()['closed']);self.assertEqual(d.metadata()['cleanup_error'],'cleanup fault')
        with self.assertRaises(FaceDetectionError):d.detect(np.zeros((20,20,3),np.uint8),1,Profile())
        d.close();self.assertTrue(d.metadata()['closed'])
