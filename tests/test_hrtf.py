import math
import unittest

import numpy as np

from hrtf import HRTF


class HRTFTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hrtf = HRTF()

    def test_front_and_back_have_different_spectral_filters(self):
        front = self.hrtf.impulse_response(0)
        back = self.hrtf.impulse_response(math.pi)
        self.assertEqual(front.shape, (128, 2))
        self.assertFalse(np.allclose(np.abs(np.fft.rfft(front[:, 0])), np.abs(np.fft.rfft(back[:, 0]))))

    def test_right_source_is_louder_and_arrives_earlier_in_right_ear(self):
        response = self.hrtf.impulse_response(math.pi / 2)
        self.assertGreater(np.sum(response[:, 1] ** 2), np.sum(response[:, 0] ** 2))
        self.assertLess(np.argmax(np.abs(response[:, 1])), np.argmax(np.abs(response[:, 0])))

    def test_left_right_mirror_and_angle_wrap(self):
        np.testing.assert_allclose(self.hrtf.impulse_response(-.7), self.hrtf.impulse_response(.7)[:, ::-1])
        np.testing.assert_allclose(self.hrtf.impulse_response(.7 + 2 * math.pi), self.hrtf.impulse_response(.7), atol=1e-12)
        np.testing.assert_allclose(self.hrtf.impulse_response(-math.pi), self.hrtf.impulse_response(math.pi), atol=1e-12)

    def test_filter_interpolation(self):
        expected = (self.hrtf.filters[10] + self.hrtf.filters[11]) / 2
        np.testing.assert_allclose(self.hrtf.impulse_response(math.radians(52.5)), expected, atol=1e-12)

    def test_linear_convolution_preserves_delay_and_tail(self):
        impulse = np.zeros(20)
        impulse[3] = 1
        response = self.hrtf.impulse_response(.4)
        left, right = self.hrtf.process(impulse, .4)
        self.assertEqual(len(left), 20 + 128 - 1)
        np.testing.assert_allclose(left[3:131], response[:, 0])
        np.testing.assert_allclose(right[3:131], response[:, 1])
        self.assertTrue(np.all(np.isfinite(left)))
