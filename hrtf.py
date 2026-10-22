"""Horizontal MIT KEMAR HRIR convolution (44.1 kHz, 128 taps per ear)."""
import math
from pathlib import Path
import wave

import numpy as np


class HRTF:
    def __init__(self):
        folder = Path(__file__).resolve().parent / 'audio' / 'hrtf'
        filters = []
        for angle in range(0, 181, 5):
            path = folder / f'H0e{angle:03d}a.wav'
            try:
                with wave.open(str(path), 'rb') as source:
                    if (source.getframerate(), source.getnchannels(), source.getsampwidth(), source.getnframes()) != (44100, 2, 2, 128):
                        raise ValueError(f'Unexpected HRIR format: {path}')
                    filters.append(np.frombuffer(source.readframes(128), dtype='<i2').reshape(-1, 2).astype(np.float64) / 32768.)
            except (OSError, wave.Error) as error:
                raise RuntimeError(f'Cannot load HRTF measurement: {path}') from error
        self.filters = np.array(filters)
        # One common scale preserves level and timing differences between ears
        # and directions. Never normalize the ears independently.
        self.filters /= np.sqrt(np.max(np.sum(self.filters ** 2, axis=1)))

    def impulse_response(self, azimuth):
        """Radians clockwise from forward. Mirror the symmetric left hemisphere."""
        angle = math.degrees(math.atan2(math.sin(azimuth), math.cos(azimuth)))
        position = abs(angle) / 5
        lower = min(36, int(position))
        upper = min(36, lower + 1)
        fraction = position - lower
        response = self.filters[lower] * (1 - fraction) + self.filters[upper] * fraction
        return response[:, ::-1] if angle < 0 else response

    def process(self, mono, azimuth):
        response = self.impulse_response(azimuth)
        return (np.convolve(mono, response[:, 0], mode='full'),
                np.convolve(mono, response[:, 1], mode='full'))
