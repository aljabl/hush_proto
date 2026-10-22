"""Deterministic logic tests plus SDL dummy-driver integration checks."""
import os
os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
import csv
import json
import math
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pygame
import main


class RouteTests(unittest.TestCase):
    def test_routes_obey_research_constraints(self):
        routes = main.make_routes()
        self.assertEqual(len(routes), 7)
        self.assertTrue(routes[0]['practice'])
        self.assertEqual(len({r['id'] for r in routes}), 7)
        for route in routes:
            self.assertAlmostEqual(route['duration'], 60)
            if not route['practice']:
                self.assertGreaterEqual(math.dist(route['start'], (30, 30)), 25)
                self.assertEqual({leg[3] for leg in route['legs']}, {'walk', 'run'})
                points = [leg[1] for leg in route['legs']] + [route['legs'][-1][2]]
                self.assertGreaterEqual(max(p[0] for p in points) - min(p[0] for p in points), 48)
                self.assertGreaterEqual(max(p[1] for p in points) - min(p[1] for p in points), 48)
            for start, a, b, mode, speed in route['legs']:
                midpoint = main.route_position(route, start + math.dist(a, b) / speed / 2)
                self.assertAlmostEqual(midpoint[0], (a[0] + b[0]) / 2)
                self.assertAlmostEqual(midpoint[1], (a[1] + b[1]) / 2)
                self.assertLess(speed, main.CONFIG['run_speed'])
                self.assertTrue(all(0 <= v <= 60 for point in (a, b) for v in point))
                self.assertEqual(main.route_position(route, start)[:2], a)
            self.assertEqual(main.route_position(route, 60)[:2], route['legs'][-1][2])
            self.assertEqual(main.route_position(route, -1)[:2], route['start'])


class GameTests(unittest.TestCase):
    def setUp(self):
        self.config = main.CONFIG.copy()
        self.game = main.Game()
        self.time = patch('main.time.monotonic', return_value=100.)
        self.now = self.time.start()
        self.keys = defaultdict(bool)
        self.key_patch = patch('pygame.key.get_pressed', return_value=self.keys)
        self.key_patch.start()

    def tearDown(self):
        self.key_patch.stop()
        self.time.stop()
        main.CONFIG.update(self.config)
        pygame.quit()

    def playing(self):
        self.game.start_round()
        self.now.return_value = 100.9
        self.game.update(0)

    def key(self, key):
        self.game.event(pygame.event.Event(pygame.KEYDOWN, key=key))

    def test_space_map_escape_and_no_repeats(self):
        ids = []
        for i in range(7):
            self.key(pygame.K_SPACE)
            ids.append(self.game.round['route']['id'])
            self.key(pygame.K_SPACE)
            self.assertTrue(self.game.bird)
            self.game.draw()
            self.key(pygame.K_ESCAPE)
            self.assertIsNone(self.game.round)
            self.assertFalse(self.game.bird)
            self.assertEqual(self.game.summaries[-1]['outcome'], 'exited')
        self.assertEqual(ids[0], 'practice')
        self.assertEqual(len(set(ids)), 7)
        self.key(pygame.K_SPACE)
        self.assertIsNone(self.game.round)

    def test_countdown_stationary_silence_and_logging(self):
        self.game.start_round()
        with patch.object(self.game.audio, 'step') as step:
            self.game.update(.05)
            step.assert_not_called()
            self.assertEqual(self.game.samples, [])
        self.now.return_value = 101.9
        self.game.update(0)
        self.assertAlmostEqual(self.game.round['elapsed'], 1.)
        self.assertEqual([s['time'] for s in self.game.samples], [i / 10 for i in range(11)])
        self.assertTrue(all(s['is_practice'] for s in self.game.samples))

    def test_diagonal_speed_stride_and_bounds(self):
        self.playing()
        self.game.player['yaw'] = 0
        self.keys[pygame.K_w] = self.keys[pygame.K_d] = True
        self.game.update(1.)
        self.assertAlmostEqual(self.game.player['path'], 1.5)
        self.keys[pygame.K_LSHIFT] = True
        self.game.update(1.)
        self.assertAlmostEqual(self.game.player['path'], 5.)
        self.game.player.update(x=60., y=0.)
        path = self.game.player['path']
        with patch.object(self.game.audio, 'step') as step:
            self.game.update(.1)
            self.assertEqual(self.game.player['path'], path)
            step.assert_not_called()

    def test_textinput_and_focus_do_not_move_player(self):
        self.playing()
        self.game.edit_tester(True)
        self.game.event(pygame.event.Event(pygame.TEXTINPUT, text='Zoë'))
        self.keys[pygame.K_w] = True
        self.game.update(1.)
        self.assertEqual(self.game.player['path'], 0)
        self.assertEqual(self.game.tester_id, 'Zoë')
        self.game.event(pygame.event.Event(pygame.WINDOWFOCUSLOST))
        self.game.update(1.)
        self.assertEqual(self.game.player['path'], 0)
        self.assertFalse(self.game.edit_id)

    def test_capture_and_timeout_summaries(self):
        self.playing()
        self.game.player.update(x=8., y=30.)
        self.game.update(0)
        self.assertEqual(self.game.summaries[-1]['outcome'], 'captured')
        self.assertEqual(self.game.summaries[-1]['time_to_capture'], 0)
        self.game.start_round()
        self.now.return_value = self.game.round['at'] + 60
        self.game.update(0)
        self.assertEqual(self.game.summaries[-1]['outcome'], 'timeout')
        self.assertIsNone(self.game.summaries[-1]['time_to_capture'])

    def test_exports_roundtrip(self):
        self.playing()
        self.game.finish('exited')
        with tempfile.TemporaryDirectory() as directory, patch('main.Path.cwd', return_value=Path(directory)):
            self.game.export()
            files = list(Path(directory).iterdir())
            self.assertEqual(len(files), 3)
            data = json.loads(next(p for p in files if p.suffix == '.json').read_text())
            self.assertEqual(data['summaries'], self.game.summaries)
            for file in files:
                if file.suffix == '.csv':
                    with file.open(newline='') as stream:
                        self.assertTrue(list(csv.DictReader(stream)))

    def test_audio_panning_center_and_range(self):
        player = dict(x=30., y=30., yaw=0.)
        audio = self.game.audio
        for x, louder in ((36, 1), (24, 0)):
            with patch.object(audio, 'play') as play:
                audio.step(x, 30, 'walk', player)
                left, right = play.call_args.args
                energies = [np.sum(left ** 2), np.sum(right ** 2)]
                self.assertGreater(energies[louder], energies[1 - louder])
                self.assertTrue(np.all(np.isfinite(left)))
        with patch.object(audio, 'play') as play:
            audio.step(30, 30, 'walk', player, own=True)
            np.testing.assert_array_equal(*play.call_args.args)
            play.reset_mock()
            audio.step(100, 30, 'walk', player)
            play.assert_not_called()

    def test_footsteps_load_recordings_without_changing_buffers(self):
        audio = self.game.audio
        self.assertEqual(len(audio.footsteps), 4)
        for path, mono in zip(audio.sample_paths, audio.footsteps):
            expected = pygame.sndarray.array(pygame.mixer.Sound(str(path))).astype(np.float64).mean(axis=1) / 32768.
            np.testing.assert_array_equal(mono, expected)
            self.assertTrue(np.all(np.isfinite(mono)))
            self.assertGreater(np.max(np.abs(mono)), 0)
        originals = [sample.copy() for sample in audio.footsteps]
        used = []
        for _ in range(12):
            sample = audio.next_footstep()
            used.append(audio._last_sample)
            self.assertEqual(len(sample), len(originals[used[-1]]))
        for start in range(0, 12, 4):
            self.assertEqual(set(used[start:start + 4]), {0, 1, 2, 3})
        self.assertTrue(all(a != b for a, b in zip(used, used[1:])))
        for original, sample in zip(originals, audio.footsteps):
            np.testing.assert_array_equal(original, sample)

    def test_audio_loads_from_another_working_directory(self):
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                self.assertEqual(len(main.Audio().footsteps), 4)
            finally:
                os.chdir(original)

    def test_missing_recording_reports_filename(self):
        with patch('pygame.mixer.Sound', side_effect=FileNotFoundError('missing')):
            with self.assertRaisesRegex(RuntimeError, 'footstep-on-concrete-1.wav'):
                main.Audio()

    def test_bird_view_supports_mouse_and_arrow_turning(self):
        self.playing()
        self.game.research = True
        self.key(pygame.K_SPACE)
        self.assertTrue(self.game.bird)
        with patch('pygame.event.set_grab') as grab:
            self.game.grab()
            grab.assert_called_once_with(True)
        before = self.game.player['yaw']
        motion = pygame.event.Event(pygame.MOUSEMOTION, rel=(80, 0), pos=(500, 300))
        self.game.event(motion)
        self.assertAlmostEqual(self.game.player['yaw'] - before, 80 * main.CONFIG['mouse_sensitivity'])
        before = self.game.player['yaw']
        self.keys[pygame.K_RIGHT] = True
        self.game.update(.1)
        self.assertAlmostEqual(self.game.player['yaw'] - before, .1 * main.CONFIG['arrow_turn_speed'])
        self.key(pygame.K_SPACE)
        before = self.game.player['yaw']
        self.game.event(motion)
        self.assertEqual(self.game.player['yaw'], before)
        with patch('pygame.event.set_grab') as grab:
            self.game.grab()
            grab.assert_called_once_with(False)
        self.game.bird = True
        self.game.focused = False
        self.game.event(motion)
        self.assertEqual(self.game.player['yaw'], before)

    def test_mouse_turn_is_continuous_and_sensitivity_is_adjustable(self):
        self.playing()
        start = self.game.player['yaw']
        # More than a full turn, accumulated from ordinary relative motion.
        for _ in range(100):
            self.game.event(pygame.event.Event(pygame.MOUSEMOTION, rel=(10, 0), pos=(0, 0)))
        self.assertAlmostEqual(self.game.player['yaw'] - start, 1000 * main.CONFIG['mouse_sensitivity'])
        self.assertGreater(self.game.player['yaw'] - start, math.tau)
        self.game.dragging = next(i for i, slider in enumerate(self.game.sliders) if slider[0] == 'mouse_sensitivity')
        self.game.set_slider(710)
        self.assertEqual(main.CONFIG['mouse_sensitivity'], .001)
        self.game.set_slider(1030)
        self.assertEqual(main.CONFIG['mouse_sensitivity'], .015)

    def test_directional_strength_increases_channel_separation(self):
        audio = self.game.audio
        player = dict(x=30., y=30., yaw=0.)
        main.CONFIG['reverb_mix'] = 0
        ratios = []
        for strength in (1., 1.8):
            main.CONFIG['directional_strength'] = strength
            with patch.object(audio, 'next_footstep', return_value=audio.footsteps[0]), patch.object(audio, 'play') as play:
                audio.step(33, 25, 'walk', player)
                left, right = play.call_args.args
                ratios.append(np.sum(right ** 2) / np.sum(left ** 2))
                self.assertTrue(np.all(np.isfinite(right)))
        self.assertGreater(ratios[1], ratios[0] * 3)
        # Centered player footsteps are unaffected by directional exaggeration.
        with patch.object(audio, 'play') as play:
            audio.step(30, 30, 'walk', player, own=True)
            np.testing.assert_array_equal(*play.call_args.args)

    def test_map_colors_and_slider_clamps(self):
        self.playing()
        self.game.player["yaw"] = 0.
        self.game.bird = True
        self.game.draw()
        # Map is at (195, 15), scale 690 / 60. Sample away from heading line.
        self.assertEqual(tuple(self.game.screen.get_at((540 - 3, 360 + 3)))[:3], (60, 220, 60))
        self.assertEqual(tuple(self.game.screen.get_at((287, 360)))[:3], (240, 60, 60))
        self.game.dragging = 0
        self.game.set_slider(-100)
        self.assertEqual(main.CONFIG['ref_distance'], 1)
        self.game.set_slider(5000)
        self.assertEqual(main.CONFIG['ref_distance'], 15)

    def test_mixer_format_and_pcm(self):
        self.assertEqual(pygame.mixer.get_init(), (44100, -16, 2))
        with patch('pygame.sndarray.make_sound') as make:
            self.game.audio.play(np.array([2., -2.]), np.array([0., .5]))
            pcm = make.call_args.args[0]
            self.assertEqual(pcm.dtype, np.int16)
            self.assertEqual(pcm.shape, (2, 2))
            self.assertTrue(pcm.flags.c_contiguous)
            self.assertEqual(pcm[0, 0], 32767)

    def test_quit_skips_update_and_cleans_up_on_error(self):
        with patch('pygame.event.get', return_value=[pygame.event.Event(pygame.QUIT)]), patch.object(self.game, 'update') as update:
            self.game.run()
            update.assert_not_called()
        self.assertFalse(pygame.get_init())
        self.game = main.Game()
        with patch('pygame.event.get', return_value=[]), patch.object(self.game, 'update', side_effect=ValueError('test')):
            with self.assertRaises(ValueError):
                self.game.run()
        self.assertFalse(pygame.get_init())


if __name__ == '__main__':
    unittest.main()
