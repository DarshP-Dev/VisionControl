from dataclasses import FrozenInstanceError
import math
import unittest

from face_tracking.face_geometry import adapt_result, convert_box, dimensions
from .helpers import detection, result


class GeometryTest(unittest.TestCase):
    def test_center_and_original_frame_coordinates(self):
        f = convert_box(160, 90, 320, 180, (640, 360), (1920, 1080), .9)
        self.assertEqual((f.box_pixels.x_min, f.box_pixels.y_min, f.box_pixels.x_max, f.box_pixels.y_max),
                         (480, 270, 1440, 810))
        self.assertEqual((f.center_x, f.center_y), (960, 540))
        self.assertEqual((f.normalized_center_x,f.normalized_center_y),(.5,.5))
        self.assertEqual((f.offset_x, f.offset_y, f.normalized_offset_x, f.normalized_offset_y), (0, 0, 0, 0))

    def test_signs_and_normalization_for_four_quadrants(self):
        for x,y in ((0,0),(50,0),(0,50),(50,50)):
            f=convert_box(x,y,50,50,(100,100),(200,200))
            self.assertEqual(f.normalized_offset_x, -.5 if x==0 else .5)
            self.assertEqual(f.normalized_offset_y, -.5 if y==0 else .5)

    def test_partial_box_is_clipped_and_visible_center_used(self):
        f=convert_box(-20,-10,60,30,(100,100),(200,200))
        self.assertEqual((f.box_pixels.x_min,f.box_pixels.y_min,f.center_x,f.center_y),(0,0,40,20))
        self.assertEqual(f.box_normalized.x_max,.4)

    def test_full_frame_edges_are_W_and_H_not_last_pixel_indices(self):
        f=convert_box(-10,-10,120,120,(100,100),(1920,1080))
        self.assertEqual((f.box_pixels.x_max,f.box_pixels.y_max),(1920,1080))
        self.assertEqual(f.box_normalized.area,1)

    def test_invalid_dimensions_rejected(self):
        for size in (None,(),(0,10),(-1,10),(True,10),(1.5,10),(10,math.inf),'10'):
            with self.subTest(size=size),self.assertRaises(ValueError):dimensions(size)

    def test_invalid_box_coordinates_and_scores_rejected(self):
        for box in ((0,0,0,10),(0,0,-1,10),(math.nan,0,1,1),(0,math.inf,1,1),(True,0,1,1),(101,0,10,10)):
            with self.subTest(box=box),self.assertRaises(ValueError):convert_box(*box,(100,100),(100,100))
        for confidence in (-1,2,math.nan,math.inf,True):
            with self.assertRaises(ValueError):convert_box(0,0,10,10,(100,100),(100,100),confidence)

    def test_single_face_selection_and_no_face_clear(self):
        a=adapt_result(result(detection()),(640,360),(1920,1080),1)
        b=adapt_result(result(),(640,360),(1920,1080),2)
        self.assertIs(a.primary,a.faces[0]);self.assertEqual(a.status,'detected')
        self.assertEqual(b.faces,());self.assertIsNone(b.primary);self.assertEqual(b.status,'no_face')

    def test_multiple_faces_highest_score_then_area_then_coordinates(self):
        boxes=[detection(100,10,30,30,.8),detection(200,10,30,30,.9),detection(20,10,40,40,.9),detection(10,10,40,40,.9)]
        a=adapt_result(result(*boxes),(640,360),(640,360),3)
        b=adapt_result(result(*reversed(boxes)),(640,360),(640,360),3)
        self.assertEqual(a,b);self.assertEqual(len(a.faces),4)
        self.assertEqual(a.primary.box_pixels.x_min,10)

    def test_low_confidence_and_malformed_detection_are_filtered(self):
        a=adapt_result(result(detection(score=.4),detection(w=-1),object(),detection(score=math.nan),detection()),(640,360),(640,360),1)
        self.assertEqual(len(a.faces),1)

    def test_unavailable_confidence_is_explicit_and_lower_ranked(self):
        a=adapt_result(result(detection(score=None),detection(score=.6)),(640,360),(640,360),1)
        self.assertEqual(a.primary.confidence,.6);self.assertIsNone(a.faces[1].confidence)

    def test_offscreen_box_is_omitted_and_valid_faces_retained(self):
        a=adapt_result(result(detection(x=700),detection(x=-700),detection()),(640,360),(640,360),1)
        self.assertEqual(len(a.faces),1)

    def test_observations_are_immutable(self):
        a=adapt_result(result(detection()),(640,360),(640,360),1)
        with self.assertRaises(FrozenInstanceError):a.primary.center_x=10
