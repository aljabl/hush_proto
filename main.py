"""Hush audio localization playtest. Run: python3 main.py"""
import csv
import json
import math
import random
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pygame


CONFIG = {
    "world": 60, "round_seconds": 60, "capture_radius": 2,
    "walk_speed": 1.5, "run_speed": 3.5,
    "entity_walk_speed": 1.2, "entity_run_speed": 3,
    "walk_stride": .75, "run_stride": 1.0,
    "ref_distance": 4, "rolloff_factor": 1.1,
    "cutoff_near": 4500, "cutoff_far": 500, "reverb_mix": .18,
    "entity_walk_gain": .78, "entity_run_gain": 1.15, "player_gain": .23,
    "walk_range": 35, "run_range": 55,
    "footstep_gain_variation": .05,
    "mouse_sensitivity": .0075, "arrow_turn_speed": 2.2,
}
ROUTE_SPECS = [
    ("practice", (8, 30), [0, 0, 0, 0, 180, 180, 180, 180, 0, 0, 0, 0], "wwwwwwwwwwww", True),
    ("NW", (5, 5), [45, 225, 0, 180, 45, 225, 90, 270, 0, 180, 45, 225], "rrwwrrwwwwrr", False),
    ("NE", (55, 5), [135, 315, 180, 0, 135, 315, 90, 270, 180, 0, 135, 315], "rrwwrrwwwwrr", False),
    ("SE", (55, 55), [225, 45, 180, 0, 225, 45, 270, 90, 180, 0, 225, 45], "rrwwrrwwwwrr", False),
    ("SW", (5, 55), [315, 135, 0, 180, 315, 135, 270, 90, 0, 180, 315, 135], "rrwwrrwwwwrr", False),
    ("N", (30, 3), [90, 270, 0, 180, 90, 270, 0, 180, 90, 270, 0, 180], "rrwwrrwwrrww", False),
    ("S", (30, 57), [270, 90, 0, 180, 270, 90, 0, 180, 270, 90, 0, 180], "rrwwrrwwrrww", False),
]
SAMPLE_RATE = 44100
WIDTH, HEIGHT = 1080, 720


def make_routes():
    routes = []
    for name, start, angles, modes, practice in ROUTE_SPECS:
        x, y = start
        legs = []
        for i, (angle, letter) in enumerate(zip(angles, modes)):
            mode = "run" if letter == "r" else "walk"
            speed = CONFIG["entity_run_speed" if mode == "run" else "entity_walk_speed"]
            a = math.radians(angle)
            end = (x + math.cos(a) * speed * 5, y + math.sin(a) * speed * 5)
            legs.append((i * 5, (x, y), end, mode, speed))
            x, y = end
        routes.append(dict(id=name, start=start, legs=legs, practice=practice))
        if abs(5 * len(legs) - 60) > .5:
            print(f"WARNING: {name} duration is not 60 s", file=sys.stderr)
        if not practice and math.dist(start, (30, 30)) < 25:
            print(f"WARNING: {name} starts too close", file=sys.stderr)
        for _, a, b, _, speed in legs:
            if any(v < 0 or v > 60 for p in (a, b) for v in p):
                print(f"WARNING: {name} leaves bounds", file=sys.stderr)
            if speed >= CONFIG["run_speed"]:
                print(f"WARNING: {name} entity speed too high", file=sys.stderr)
    return routes


def route_position(route, seconds):
    start, a, b, mode, _ = route["legs"][max(0, min(len(route["legs"]) - 1, int(seconds / 5)))]
    t = max(0, min(1, (seconds - start) / 5))
    return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, mode


class Audio:
    def __init__(self):
        if pygame.mixer.get_init() != (SAMPLE_RATE, -16, 2):
            raise RuntimeError("Hush requires a 44100 Hz signed 16-bit stereo mixer")
        pygame.mixer.set_num_channels(48)
        self.rng = np.random.default_rng()
        # Resolve relative to this script so launching from another folder works.
        folder = Path(__file__).resolve().parent / "audio"
        self.sample_paths = [folder / f"footstep-on-concrete-{i}.wav" for i in range(1, 5)]
        self.footsteps = []
        for path in self.sample_paths:
            try:
                sound = pygame.mixer.Sound(str(path))
                pcm = pygame.sndarray.array(sound)
            except (pygame.error, OSError) as error:
                raise RuntimeError(f"Cannot load footstep audio: {path}") from error
            # Collapse to a centered mono source before applying game panning.
            mono = pcm.astype(np.float64).mean(axis=1) / 32768.0
            if not len(mono):
                raise RuntimeError(f"Empty footstep audio: {path}")
            self.footsteps.append(mono)
        self._sample_bag = []
        self._last_sample = None

    def play(self, left, right):
        data = np.column_stack((left, right))
        pygame.sndarray.make_sound(np.ascontiguousarray(np.clip(data, -1, 1) * 32767, dtype=np.int16)).play()

    def next_footstep(self):
        """Use every recording before reshuffling; avoid adjacent repeats."""
        if not self._sample_bag:
            self._sample_bag = list(range(len(self.footsteps)))
            self.rng.shuffle(self._sample_bag)
            if self._sample_bag[-1] == self._last_sample:
                self._sample_bag[0], self._sample_bag[-1] = self._sample_bag[-1], self._sample_bag[0]
        self._last_sample = self._sample_bag.pop()
        variation = CONFIG["footstep_gain_variation"]
        return self.footsteps[self._last_sample] * self.rng.uniform(1 - variation, 1 + variation)

    def step(self, x, y, mode, player, own=False, force=False):
        distance = math.hypot(x - player["x"], y - player["y"])
        audible = CONFIG["run_range" if mode == "run" else "walk_range"]
        if not own and not force and distance > audible:
            return
        mono = self.next_footstep()
        depth = min(1, distance / max(1, audible))
        cutoff = CONFIG["cutoff_near"] + (CONFIG["cutoff_far"] - CONFIG["cutoff_near"]) * depth
        frequencies = np.fft.rfftfreq(len(mono), 1 / SAMPLE_RATE)
        lowpass = 1 / np.sqrt(1 + (frequencies / max(50, cutoff)) ** 6)
        mono = np.fft.irfft(np.fft.rfft(mono) * lowpass, len(mono))
        gain = CONFIG["player_gain"] if own else CONFIG["entity_run_gain" if mode == "run" else "entity_walk_gain"]
        gain *= 1.18 if mode == "run" else 1
        if own:
            left = right = mono * gain * .34
        else:
            dx, dy = x - player["x"], y - player["y"]
            side = (dx * math.cos(player["yaw"]) + dy * math.sin(player["yaw"])) / max(.001, distance)
            pan = max(-1, min(1, side))
            attenuation = CONFIG["ref_distance"] / (CONFIG["ref_distance"] + CONFIG["rolloff_factor"] * max(0, distance - CONFIG["ref_distance"]))
            edge = min(1, max(0, (audible - distance) / 5))
            gain *= attenuation * edge
            left = mono * gain * math.sqrt((1 - pan) / 2)
            right = mono * gain * math.sqrt((1 + pan) / 2)
            delay = int(SAMPLE_RATE * .035)
            wet = CONFIG["reverb_mix"] * (.2 + .8 * depth)
            left = np.pad(left, (0, delay))
            right = np.pad(right, (0, delay))
            left[delay:] += mono * gain * wet * .22
            right[delay:] += mono * gain * wet * .22
        self.play(left, right)

    def tone(self, notes, duration=.3):
        output = np.zeros(int(SAMPLE_RATE * (duration + .14 * (len(notes) - 1))))
        for i, note in enumerate(notes):
            start = int(i * .14 * SAMPLE_RATE)
            n = min(int(duration * SAMPLE_RATE), len(output) - start)
            t = np.arange(n) / SAMPLE_RATE
            output[start:start + n] += .22 * np.sin(2 * np.pi * note * t) * np.exp(-10 * t)
        self.play(output, output)


class Game:
    def __init__(self):
        pygame.mixer.pre_init(SAMPLE_RATE, -16, 2, 512, allowedchanges=0)
        pygame.init()
        if pygame.mixer.get_init() is None:
            pygame.quit()
            raise RuntimeError("Audio device unavailable; Hush requires stereo audio")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption("Hush — audio localization playtest")
        self.font = pygame.font.SysFont(None, 22)
        self.clock = pygame.time.Clock()
        self.audio = Audio()
        self.routes = make_routes()
        self.bag = self.routes[1:].copy()
        random.shuffle(self.bag)
        self.round = None
        self.round_index = 0
        self.player = dict(x=30., y=30., yaw=0., steps=0., path=0.)
        self.entity = dict(x=0., y=0., mode="walk", steps=0.)
        self.player_trail, self.entity_trail = [], []
        self.samples, self.summaries = [], []
        self.tester_id = ""
        self.edit_id = self.bird = self.research = False
        self.message = "Press Space to start the practice round"
        self.dragging = None
        self.check = None
        self.focused = True
        pygame.key.stop_text_input()
        self.sliders = [
            ("ref_distance", 1, 15), ("rolloff_factor", .1, 3),
            ("cutoff_near", 1500, 8000), ("cutoff_far", 150, 2000),
            ("reverb_mix", 0, 1), ("entity_walk_gain", 0, 2),
            ("entity_run_gain", 0, 2), ("player_gain", 0, 1),
            ("walk_range", 10, 60), ("run_range", 20, 85),
            ("mouse_sensitivity", .001, .015),
        ]

    def mouse_look_enabled(self):
        # The bird's-eye view is playable; the researcher panel needs a cursor.
        return bool(self.round and self.focused and (self.bird or not self.research))

    def grab(self):
        enabled = self.mouse_look_enabled()
        pygame.event.set_grab(enabled)
        pygame.mouse.set_visible(not enabled)
        pygame.mouse.get_rel()

    def start_round(self):
        if self.round:
            return
        route = self.routes[0] if self.round_index == 0 else self.bag.pop(0) if self.bag else None
        if route is None:
            self.message = "Session complete. Press E to export."
            return
        self.round_index += 1
        self.player = dict(x=30., y=30., yaw=random.random() * math.tau, steps=0., path=0.)
        self.entity = dict(x=float(route["start"][0]), y=float(route["start"][1]), mode="walk", steps=0.)
        self.player_trail, self.entity_trail = [(30., 30.)], [route["start"]]
        self.bird = False
        self.round = dict(route=route, phase="countdown", at=time.monotonic() + .9, elapsed=0., sample_at=0.)
        self.message = ""
        self.audio.tone([660], .12)
        self.grab()

    def finish(self, outcome):
        if not self.round:
            return
        route = self.round["route"]
        elapsed = self.round["elapsed"]
        self.summaries.append(dict(
            tester_id=self.tester_id, round_index=self.round_index, route_id=route["id"],
            is_practice=route["practice"], entity_start_x=route["start"][0],
            entity_start_y=route["start"][1], outcome=outcome,
            time_to_capture=round(elapsed, 3) if outcome == "captured" else None,
            player_path_length=round(self.player["path"], 3)))
        self.round = None
        self.check = None
        pygame.mixer.stop()
        self.bird = False
        self.grab()
        if outcome == "captured":
            self.audio.tone([660, 880, 1320])
        elif outcome == "timeout":
            self.audio.tone([180], .6)
        label = dict(captured="Captured", timeout="Time expired", exited="Round exited")[outcome]
        self.message = label + (". Press Space for the next round." if self.bag or self.round_index == 1 else ". Session complete. Press E to export.")

    def export(self):
        ident = "".join(c if c.isalnum() or c in "_-" else "_" for c in self.tester_id) or "anonymous"
        stem = f"hush_{ident}_{datetime.now():%Y%m%d_%H%M%S}"
        folder = Path.cwd()
        (folder / f"{stem}.json").write_text(json.dumps(dict(config=CONFIG, summaries=self.summaries, samples=self.samples), indent=2))
        for suffix, rows in (("samples", self.samples), ("summary", self.summaries)):
            with (folder / f"{stem}_{suffix}.csv").open("w", newline="") as file:
                if rows:
                    writer = csv.DictWriter(file, fieldnames=list(rows[0]))
                    writer.writeheader()
                    writer.writerows(rows)
        self.message = f"Saved session to {folder}"

    def set_slider(self, x):
        key, low, high = self.sliders[self.dragging]
        precision = 5 if key == "mouse_sensitivity" else 2
        CONFIG[key] = round(low + (high - low) * max(0, min(1, (x - 710) / 320)), precision)

    def edit_tester(self, enabled):
        self.edit_id = enabled
        if enabled:
            pygame.key.start_text_input()
            pygame.key.set_text_input_rect(pygame.Rect(700, 96, 350, 28))
        else:
            pygame.key.stop_text_input()

    def event(self, event):
        if event.type == pygame.QUIT:
            return False
        if event.type == pygame.WINDOWFOCUSLOST:
            self.focused = False
            self.dragging = None
            self.edit_tester(False)
            self.grab()
        elif event.type == pygame.WINDOWFOCUSGAINED:
            self.focused = True
            self.grab()
        if event.type == pygame.TEXTINPUT and self.edit_id:
            self.tester_id = (self.tester_id + "".join(c for c in event.text if c.isprintable()))[:40]
        if event.type == pygame.MOUSEMOTION and self.mouse_look_enabled():
            self.player["yaw"] += event.rel[0] * CONFIG["mouse_sensitivity"]
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self.research and not self.bird:
            x, y = event.pos
            if pygame.Rect(700, 96, 350, 28).collidepoint(x, y):
                self.edit_tester(True)
            else:
                self.edit_tester(False)
            for i in range(len(self.sliders)):
                if pygame.Rect(710, 178 + i * 42, 320, 20).collidepoint(x, y):
                    self.dragging = i
                    self.set_slider(x)
        if event.type == pygame.MOUSEBUTTONUP:
            self.dragging = None
        if event.type == pygame.MOUSEMOTION and self.dragging is not None:
            self.set_slider(event.pos[0])
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE and self.round:
                self.finish("exited")
            elif self.edit_id:
                if event.key == pygame.K_RETURN:
                    self.edit_tester(False)
                elif event.key == pygame.K_BACKSPACE:
                    self.tester_id = self.tester_id[:-1]
            elif event.key == pygame.K_SPACE:
                if self.round:
                    self.bird = not self.bird
                    self.grab()
                else:
                    self.start_round()
            elif event.key == pygame.K_h:
                self.research = not self.research
                self.edit_tester(False)
                self.grab()
            elif event.key == pygame.K_t:
                self.check = dict(start=time.monotonic(), next=0.)
            elif event.key == pygame.K_e:
                self.export()
        return True

    def update(self, dt):
        now = time.monotonic()
        if self.check:
            age = now - self.check["start"]
            if age > 4.2:
                self.check = None
            elif age >= self.check["next"]:
                angle = age * math.tau / 4.2
                self.audio.step(self.player["x"] + math.sin(angle) * 6,
                                self.player["y"] - math.cos(angle) * 6, "run", self.player, force=True)
                self.check["next"] += .24
        if not self.round:
            return
        if self.round["phase"] == "countdown":
            if now < self.round["at"]:
                return
            self.round["phase"] = "playing"
        elapsed = min(CONFIG["round_seconds"], now - self.round["at"])
        self.round["elapsed"] = elapsed
        keys = pygame.key.get_pressed() if self.focused and not self.edit_id else dict.fromkeys(
            (pygame.K_RIGHT, pygame.K_LEFT, pygame.K_w, pygame.K_s, pygame.K_d, pygame.K_a, pygame.K_LSHIFT, pygame.K_RSHIFT), False)
        self.player["yaw"] += (int(keys[pygame.K_RIGHT]) - int(keys[pygame.K_LEFT])) * CONFIG["arrow_turn_speed"] * dt
        forward = int(keys[pygame.K_w]) - int(keys[pygame.K_s])
        right = int(keys[pygame.K_d]) - int(keys[pygame.K_a])
        length = math.hypot(forward, right)
        if length:
            speed = CONFIG["run_speed"] if keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT] else CONFIG["walk_speed"]
            forward, right = forward / length, right / length
            yaw = self.player["yaw"]
            dx = (math.sin(yaw) * forward + math.cos(yaw) * right) * speed * dt
            dy = (-math.cos(yaw) * forward + math.sin(yaw) * right) * speed * dt
            x = max(0, min(60, self.player["x"] + dx))
            y = max(0, min(60, self.player["y"] + dy))
            moved = math.hypot(x - self.player["x"], y - self.player["y"])
            self.player.update(x=x, y=y)
            self.player["path"] += moved
            self.player["steps"] += moved
            mode = "run" if speed == CONFIG["run_speed"] else "walk"
            stride = CONFIG["run_stride" if mode == "run" else "walk_stride"]
            while self.player["steps"] >= stride:
                self.player["steps"] -= stride
                self.audio.step(x, y, mode, self.player, own=True)
        x, y, mode = route_position(self.round["route"], elapsed)
        moved = math.hypot(x - self.entity["x"], y - self.entity["y"])
        self.entity.update(x=x, y=y, mode=mode)
        self.entity["steps"] += moved
        stride = CONFIG["run_stride" if mode == "run" else "walk_stride"]
        while self.entity["steps"] >= stride:
            self.entity["steps"] -= stride
            self.audio.step(x, y, mode, self.player)
        self.player_trail.append((self.player["x"], self.player["y"]))
        self.entity_trail.append((x, y))
        distance = math.hypot(self.player["x"] - x, self.player["y"] - y)
        while self.round["sample_at"] <= elapsed + 1e-9:
            self.samples.append(dict(
                tester_id=self.tester_id, round_index=self.round_index,
                route_id=self.round["route"]["id"], is_practice=self.round["route"]["practice"],
                time=round(self.round["sample_at"], 1),
                player_x=self.player["x"], player_y=self.player["y"], player_heading=self.player["yaw"],
                entity_x=x, entity_y=y, entity_mode=mode, distance=distance))
            self.round["sample_at"] += .1
        if distance <= CONFIG["capture_radius"]:
            self.finish("captured")
        elif elapsed >= CONFIG["round_seconds"]:
            self.finish("timeout")

    def text(self, value, x, y, color=(220, 220, 220)):
        self.screen.blit(self.font.render(value, True, color), (x, y))

    def draw_map(self, rect):
        pygame.draw.rect(self.screen, (17, 17, 17), rect)
        scale = rect.width / 60
        ox, oy = rect.topleft
        for meter in range(0, 61, 10):
            p = round(meter * scale)
            pygame.draw.line(self.screen, (48, 48, 48), (ox + p, oy), (ox + p, oy + rect.height))
            pygame.draw.line(self.screen, (48, 48, 48), (ox, oy + p), (ox + rect.width, oy + p))
        pygame.draw.rect(self.screen, (130, 130, 130), rect, 1)
        for trail, color in ((self.entity_trail, (130, 45, 45)), (self.player_trail, (45, 130, 45))):
            if len(trail) > 1:
                pygame.draw.lines(self.screen, color, False, [(ox + x * scale, oy + y * scale) for x, y in trail], 2)
        ex, ey = self.entity["x"], self.entity["y"]
        px, py = self.player["x"], self.player["y"]
        pygame.draw.rect(self.screen, (240, 60, 60), pygame.Rect(ox + ex * scale - 6, oy + ey * scale - 6, 12, 12))
        pygame.draw.rect(self.screen, (60, 220, 60), pygame.Rect(ox + px * scale - 6, oy + py * scale - 6, 12, 12))
        pygame.draw.line(self.screen, (230, 230, 230), (ox + px * scale, oy + py * scale),
                         (ox + (px + math.sin(self.player["yaw"]) * 2) * scale,
                          oy + (py - math.cos(self.player["yaw"]) * 2) * scale), 2)

    def draw(self):
        self.screen.fill((0, 0, 0))
        if self.research:
            self.screen.fill((24, 24, 24))
            self.draw_map(pygame.Rect(20, 20, 680, 680))
            route = self.round["route"]["id"] if self.round else "waiting"
            elapsed = self.round["elapsed"] if self.round else 0
            distance = math.hypot(self.player["x"] - self.entity["x"], self.player["y"] - self.entity["y"])
            self.text(f"Round {self.round_index}/7 · {route}", 710, 22)
            self.text(f"{elapsed:.1f} s · distance {distance:.1f} m", 710, 48)
            self.text("Tester ID", 710, 76)
            pygame.draw.rect(self.screen, (45, 45, 45), pygame.Rect(700, 96, 350, 28))
            self.text(self.tester_id + ("|" if self.edit_id else ""), 710, 100)
            self.text("Audio / input settings", 710, 140)
            for i, (key, low, high) in enumerate(self.sliders):
                y = 166 + i * 42
                value = f"{CONFIG[key]:.4f}" if key == "mouse_sensitivity" else f"{CONFIG[key]:.2f}"
                self.text(f"{key.replace('_', ' ')}: {value}", 710, y)
                pygame.draw.line(self.screen, (80, 80, 80), (710, y + 21), (1030, y + 21), 4)
                fraction = (CONFIG[key] - low) / (high - low)
                pygame.draw.circle(self.screen, (180, 180, 180), (round(710 + fraction * 320), y + 21), 7)
            self.text("H hide · Space map · Esc exit · T check · E export", 710, 650)
        if self.bird:
            self.screen.fill((0, 0, 0))
            self.draw_map(pygame.Rect(195, 15, 690, 690))
        if not self.round and self.message:
            self.text(self.message, 24, HEIGHT - 37)
        pygame.display.flip()

    def run(self):
        try:
            running = True
            while running:
                dt = min(.05, self.clock.tick(60) / 1000)
                for event in pygame.event.get():
                    if not self.event(event):
                        running = False
                        break
                if not running:
                    break
                self.update(dt)
                self.draw()
        finally:
            pygame.event.set_grab(False)
            pygame.mouse.set_visible(True)
            pygame.quit()


if __name__ == "__main__":
    try:
        Game().run()
    finally:
        pygame.quit()
