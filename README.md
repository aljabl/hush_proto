# Hush audio localization playtest (Python)

Install dependencies and launch the desktop app:

```sh
python3 -m pip install -r requirements.txt
python3 main.py
```

Wear headphones. The playtest view is black during each round. **Space** starts the practice round and later test rounds; during a round, it toggles a bird's-eye map. The player is a green box, the entity a red box, and the white line shows facing. **Esc** exits the round and records `exited`.

**W/A/S/D** moves, **Shift** runs, and mouse motion or **Left/Right arrows** turns. **H** opens the researcher map and live audio sliders. Click the tester ID field to enter an ID. **T** plays a circling sound check. **E** writes JSON, sample CSV, and summary CSV to the current directory. Closing the window quits the app.

The six test routes are shuffled without repeats after a practice route. Each test route follows distinct waypoints across at least 48 m of both map axes, mixing running and walking. Travel lasts exactly 60 seconds; the last waypoint segment ends at the time limit. The practice entity walks clockwise in a circle around the player’s fixed spawn point, completing three rotations in 60 seconds (one lap every 20 seconds). At 1.2 m/s its circle has a radius of about 3.82 m. The circle does not follow the player if they move. A capture within 2 m ends the round early. Sample data is recorded at 10 Hz; the practice flag lets analysts exclude the practice round.

Entity footsteps now use measured MIT KEMAR HRTFs for horizontal front/back and left/right cues. Each footstep is convolved with interpolated left/right impulse responses for the entity’s direction relative to the player’s heading. Player footsteps and confirmation tones remain centered. Use headphones and **T** to check the circling source. Mouse turning and arrow-key turning both work in the full bird’s-eye map. Mouse grab is released for the researcher panel so its controls can be clicked.


## Verification

Run the tests from the project directory:

```sh
python3 -m unittest discover -s tests -v
```

The suite uses Python's built-in `unittest` and SDL dummy video/audio drivers, so it does not open a window or require headphones. It checks route constraints, round outcomes, movement, controls, text input, map colors, slider limits, exports, PCM format, stereo panning, and cleanup. Headphone perception, real device latency, and operating-system mouse capture still require a manual playtest.

The Pygame review used Context7's `/pygame/pygame` official-source documentation: [main loop and delta time](https://www.pygame.org/docs/), [mixer format and initialization](https://www.pygame.org/docs/ref/mixer.html), [sound arrays](https://www.pygame.org/docs/ref/sndarray.html), and [Unicode text input](https://www.pygame.org/docs/ref/key.html). The implementation requests an exact signed 16-bit stereo format, processes events every frame, uses `TEXTINPUT` for tester IDs, suppresses movement while typing or unfocused, and releases Pygame resources even when the loop raises an exception. The round clock continues while the window is unfocused.

Footsteps use `audio/footstep-on-concrete-1.wav` through `footstep-on-concrete-4.wav` for both player and entity. The app preloads these files relative to `main.py`, uses all four in shuffled order, and avoids consecutive repeats. Walking and running keep their respective stride, gain, and audible-range settings; distance filtering and stereo panning still apply. Small gain variation is controlled by `footstep_gain_variation` in `CONFIG`. The supplied recordings replace the procedural footstep generator; confirmation and countdown tones remain synthesized.

Footstep audio is from [SFXLibrary](https://www.sfxlibrary.com/category/footstep/?p=1).

Mouse turning uses relative movement with a hidden, captured cursor for continuous rotation. The default sensitivity is 0.0075 radians per pixel (about 838 pixels for a full turn), three times the previous sensitivity. Tune **mouse sensitivity** in the **H** researcher panel to suit your mouse or trackpad.

**Directional strength** in the **H** panel exaggerates left/right separation for the entity (default **2.2**, range **1–3**; **1** uses the base panning strength). Higher values push off-center sounds more strongly into the corresponding ear. This can make the side easier to identify while reducing angular precision once panning saturates. Measured HRTF filters now add front/back spectral cues alongside the additional panning. Player footsteps remain centered.


## HRTF processing

The bundled 44.1 kHz horizontal KEMAR measurements by **Bill Gardner and Keith Martin, MIT Media Laboratory (1994)** provide 128-tap filters for each ear. See [the source dataset](https://sound.media.mit.edu/resources/KEMAR.html) and `audio/hrtf/README.md` for attribution. No new Python dependencies or runtime downloads are required.

HRTF convolution preserves the measured interaural timing and spectral differences, and interpolates between directions spaced five degrees apart. The default distance filter now retains more high-frequency detail (18 kHz near, 5 kHz far) so it does not suppress most pinna cues. Lower cutoff settings can weaken front/back localization. Direction is evaluated at each footstep onset; an already-playing recording retains its initial filter until it finishes. This is a generic horizontal HRTF, not a personalized head model; front/back performance varies by listener and headphones. Turning while listening can help resolve ambiguity. Include the dataset attribution in any research report.

For exaggerated direction cues, the default **directional strength** is now **2.2** and **front back contrast** is **0.85**. The latter adds a continuous high-frequency color cue on top of the measured HRTF: front is crisper, rear more muffled, and sides neutral. Set contrast to **0** for the measured HRTF without this extra coloration. Both controls are in **H**. The centered echo is reduced for lateral sources so it does not mask ear separation. These intentional gameplay cues are exaggerated rather than a physically accurate acoustic simulation.
