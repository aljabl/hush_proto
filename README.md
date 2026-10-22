# Hush audio localization playtest (Python)

Install dependencies and launch the desktop app:

```sh
python3 -m pip install -r requirements.txt
python3 main.py
```

Wear headphones. The playtest view is black during each round. **Space** starts the practice round and later test rounds; during a round, it toggles a bird's-eye map. The player is a green box, the entity a red box, and the white line shows facing. **Esc** exits the round and records `exited`.

**W/A/S/D** moves, **Shift** runs, and mouse motion or **Left/Right arrows** turns. **H** opens the researcher map and live audio sliders. Click the tester ID field to enter an ID. **T** plays a circling sound check. **E** writes JSON, sample CSV, and summary CSV to the current directory. Closing the window quits the app.

The six test routes are shuffled without repeats after a practice route. Every route has twelve five-second legs and exactly 60 seconds of scripted travel. A capture within 2 m ends the round early. Sample data is recorded at 10 Hz; the practice flag lets analysts exclude the practice round.

Python/Pygame does not provide Web Audio's HRTF. This version uses the four concrete footstep recordings in `audio/`, with stereo processing with left/right panning, distance attenuation, distance-based low-pass filtering, and short synthesized echo. It gives left/right localization but limited front/back cues. **T** checks headphone orientation. Mouse grab is released while a map is shown; arrow keys remain available for turning.


## Verification

Run the tests from the project directory:

```sh
python3 -m unittest discover -s tests -v
```

The suite uses Python's built-in `unittest` and SDL dummy video/audio drivers, so it does not open a window or require headphones. It checks route constraints, round outcomes, movement, controls, text input, map colors, slider limits, exports, PCM format, stereo panning, and cleanup. Headphone perception, real device latency, and operating-system mouse capture still require a manual playtest.

The Pygame review used Context7's `/pygame/pygame` official-source documentation: [main loop and delta time](https://www.pygame.org/docs/), [mixer format and initialization](https://www.pygame.org/docs/ref/mixer.html), [sound arrays](https://www.pygame.org/docs/ref/sndarray.html), and [Unicode text input](https://www.pygame.org/docs/ref/key.html). The implementation requests an exact signed 16-bit stereo format, processes events every frame, uses `TEXTINPUT` for tester IDs, suppresses movement while typing or unfocused, and releases Pygame resources even when the loop raises an exception. The round clock continues while the window is unfocused.

Footsteps use `audio/footstep-on-concrete-1.wav` through `footstep-on-concrete-4.wav` for both player and entity. The app preloads these files relative to `main.py`, uses all four in shuffled order, and avoids consecutive repeats. Walking and running keep their respective stride, gain, and audible-range settings; distance filtering and stereo panning still apply. Small gain variation is controlled by `footstep_gain_variation` in `CONFIG`. The supplied recordings replace the procedural footstep generator; confirmation and countdown tones remain synthesized.
