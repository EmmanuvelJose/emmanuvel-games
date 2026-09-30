"""
Moto Rush - a side-scrolling bike racing game built with pygame.

Install:  pip install pygame
Run:      python moto_rush.py

Race 30,000 px of rolling hills and jump ramps against three rivals.
Nail your landings, pull off flips for free nitro, hit orange boost pads,
and don't crash - a wipe-out costs you 3 seconds and sends you back to the
last checkpoint.

Controls
  UP / W        throttle
  DOWN / S      brake
  LEFT / A      in the air: lean back (nose up / backflip)
  RIGHT / D     in the air: lean forward (nose down / frontflip)
  SPACE         nitro (blue meter)
  P or ESC      pause (ESC quits from the menu)
  ENTER         start / race again
  R             restart the race
"""

import bisect
import math
import os
import random
import sys
from typing import Optional

import pygame

# ---------------------------------------------------------------- settings
WIDTH, HEIGHT = 960, 540
FPS = 60

WHEEL_R = 16
WHEEL_BASE = 66
GRAVITY = 0.30
MAX_SPEED = 20.0

TRACK_LEN = 30000
CHECKPOINTS = [7500, 15000, 22500]
BASE_Y = 430
RAMP_LEN = 230
RAMP_H = 150
PAD_LEN = 70
START_X = 120

SKY_TOP = (70, 150, 240)
SKY_BOTTOM = (200, 232, 255)
GRASS = (62, 172, 72)
DIRT = (142, 96, 62)
DIRT_DARK = (104, 70, 46)

BEST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "besttime.txt")


# ----------------------------------------------------------------- helpers
def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def wrap(a):
    """Wrap an angle to [-pi, pi]."""
    return (a + math.pi) % (2 * math.pi) - math.pi


def ordinal(n):
    return {1: "1st", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")


def load_best():
    try:
        with open(BEST_FILE) as f:
            return float(f.read().strip())
    except (OSError, ValueError):
        return None


def save_best(value):
    try:
        with open(BEST_FILE, "w") as f:
            f.write(f"{value:.2f}")
    except OSError:
        pass


# ------------------------------------------------------------------ track
def _build_track():
    rng = random.Random(11)
    ramps = []
    x = 1800
    while x < TRACK_LEN - 1800:
        if all(not (cp - 600 < x + RAMP_LEN and x < cp + 600) for cp in CHECKPOINTS):
            ramps.append(x)
        x += rng.randint(1500, 2500)
    pads = []
    x = 1000
    while x < TRACK_LEN - 800:
        near_ramp = any(r - 350 < x + PAD_LEN and x < r + RAMP_LEN + 350 for r in ramps)
        near_cp = any(cp - 300 < x + PAD_LEN and x < cp + 300 for cp in CHECKPOINTS)
        if not near_ramp and not near_cp:
            pads.append(x)
        x += rng.randint(900, 1700)
    return ramps, pads


RAMPS, PADS = _build_track()


def ground(x):
    """World y of the ground surface at world x (bigger y = lower)."""
    f = min(clamp(x / 700.0, 0, 1), clamp((TRACK_LEN + 300 - x) / 600.0, 0, 1))
    y = 50 * math.sin(x / 320.0) + 22 * math.sin(x / 127.0 + 1.3) + 9 * math.sin(x / 53.0 + 0.4)
    y = BASE_Y + y * f
    i = bisect.bisect_right(RAMPS, x) - 1
    if i >= 0:
        rx = RAMPS[i]
        if x < rx + RAMP_LEN:
            t = (x - rx) / RAMP_LEN
            y -= RAMP_H * t ** 1.4
    return y


# ------------------------------------------------------------------- bike
class Bike:
    """Physics for one bike. The same code drives the player and the AI."""

    def __init__(self, x, color, rider, name, can_crash=False, cap=11.0):
        self.color = color
        self.rider = rider
        self.name = name
        self.can_crash = can_crash
        self.cap = cap
        self.nitro = 100.0
        self.used_pads = set()
        self.finish_frame: Optional[int] = None
        self.boosting = False
        self.respawn(x, 0.0)

    def respawn(self, x, speed=0.0):
        self.x = x
        self.vx = speed
        self.av = 0.0
        self.air_rot = 0.0
        self.air_time = 0
        self.grounded = True
        self.pad_boost = 0
        self.invuln = 0
        self.spin = 0.0
        self._snap()
        self.vy = self.vx * math.tan(self.angle)
        self.vr = self.vy

    def _wheel_ys(self, x):
        h = WHEEL_BASE / 2
        return ground(x - h) - WHEEL_R, ground(x + h) - WHEEL_R

    def _snap(self):
        yr, yf = self._wheel_ys(self.x)
        self.y = (yr + yf) / 2
        self.yr = yr
        self.angle = math.atan2(yf - yr, WHEEL_BASE)

    def update(self, up, down, boost, lean):
        """Advance one frame. lean: -1 nose up, +1 nose down. Returns events."""
        events = []
        if self.invuln > 0:
            self.invuln -= 1

        self.boosting = bool(boost and self.nitro > 0)
        if self.boosting:
            self.nitro = max(0.0, self.nitro - 0.8)
        elif self.grounded:
            self.nitro = min(100.0, self.nitro + 0.05)

        if self.grounded:
            acc = math.sin(self.angle) * 0.12  # downhill speeds you up
            if up:
                acc += 0.17
            if down:
                acc -= 0.32
            if self.boosting:
                acc += 0.07
            if self.pad_boost > 0:
                acc += 0.20
                self.pad_boost -= 1
            self.vx = clamp((self.vx + acc) * 0.985, 0.0, MAX_SPEED)

            nx = self.x + self.vx
            yr, yf = self._wheel_ys(nx)
            # the bike pitches toward the slope (limited, so it can't nose-dive off a lip instantly)
            target = clamp(math.atan2(yf - yr, WHEEL_BASE), -1.1, 0.55)
            new_angle = self.angle + clamp(wrap(target - self.angle), -0.10, 0.10)
            ny = yr + math.tan(new_angle) * (WHEEL_BASE / 2)
            yr_ball = self.yr + self.vr + 0.5 * GRAVITY  # where gravity alone would put the rear wheel
            if self.vx > 4.0 and yr > yr_ball + 2.5:
                # the ground fell away from under the rear wheel: take off
                self.grounded = False
                self.vy += GRAVITY  # keep the velocity we had on the ramp
                self.x = nx
                self.y += self.vy
                self.angle = new_angle
                self.av = 0.0
                self.air_rot = 0.0
                self.air_time = 0
            else:
                self.vr = yr - self.yr
                self.yr = yr
                self.vy = ny - self.y
                self.x = nx
                self.y = ny
                self.angle = new_angle
            self.spin += self.vx / WHEEL_R

            for i, px in enumerate(PADS):
                if px - 100 < self.x < px + PAD_LEN:
                    if i not in self.used_pads and px <= self.x <= px + PAD_LEN and self.grounded:
                        self.used_pads.add(i)
                        self.pad_boost = 45
                        events.append(("pad",))
        else:
            self.air_time += 1
            self.vy += GRAVITY
            if self.boosting:
                self.vx = min(MAX_SPEED, self.vx + 0.05)
            self.vx *= 0.9995
            self.x += self.vx
            self.y += self.vy
            if lean:
                self.av += lean * 0.016
            else:
                target = math.atan2(self.vy, self.vx)  # gently level out with the flight path
                self.angle += wrap(target - self.angle) * 0.03
                self.av *= 0.85
            self.av = clamp(self.av * 0.99, -0.16, 0.16)
            self.angle += self.av
            self.air_rot += self.av
            self.spin += self.vx / WHEEL_R * 0.6

            h = WHEEL_BASE / 2
            ca, sa = math.cos(self.angle), math.sin(self.angle)
            for sgn in (-1, 1):
                wx = self.x + sgn * h * ca
                wy = self.y + sgn * h * sa
                if wy + WHEEL_R >= ground(wx):
                    self._land(events)
                    break
        return events

    def _land(self, events):
        yr, yf = self._wheel_ys(self.x)
        slope = math.atan2(yf - yr, WHEEL_BASE)
        diff = abs(wrap(self.angle - slope))
        flips = int((abs(self.air_rot) + 0.7) / (2 * math.pi))
        big_air = self.air_time > 22

        if diff > 1.0 and self.can_crash and self.invuln == 0 and self.air_time > 8:
            events.append(("crash",))
            return

        self.grounded = True
        self.angle = slope
        self.y = (yr + yf) / 2
        self.vy = self.vx * math.tan(slope)
        self.vr = self.vy
        self.yr = yr
        if diff > 1.0:
            self.vx *= 0.5
        else:
            self.vx *= 1 - 0.18 * diff
        if flips:
            direction = -1 if self.air_rot < 0 else 1
            events.append(("flip", flips, direction))
            self.nitro = min(100.0, self.nitro + 25 * flips)
        if big_air and diff < 0.25:
            self.vx = min(MAX_SPEED, self.vx + 0.6)
            events.append(("perfect",))
        self.av = 0.0
        self.air_rot = 0.0


# --------------------------------------------------------------- drawing
def draw_bike(surf, sx, sy, angle, color, rider, spin, boosting=False):
    """Draw a motorbike + rider. (sx, sy) is the point midway between wheel centres."""
    ca, sa = math.cos(angle), math.sin(angle)

    def P(lx, ly):
        return (sx + lx * ca - ly * sa, sy + lx * sa + ly * ca)

    def I(pt):
        return (int(pt[0]), int(pt[1]))

    h = WHEEL_BASE / 2
    # wheels
    for wx in (-h, h):
        cx, cy = P(wx, 0)
        c = (int(cx), int(cy))
        pygame.draw.circle(surf, (18, 18, 22), c, WHEEL_R)
        pygame.draw.circle(surf, (150, 155, 165), c, WHEEL_R - 5)
        for k in range(4):
            a = spin + k * math.pi / 2
            pygame.draw.line(surf, (60, 60, 70), c,
                             (cx + math.cos(a) * (WHEEL_R - 5), cy + math.sin(a) * (WHEEL_R - 5)), 2)
        pygame.draw.circle(surf, (40, 40, 50), c, 4)

    rear, front = P(-h, 0), P(h, 0)
    pygame.draw.line(surf, (70, 70, 80), P(-12, -12), rear, 5)             # swingarm
    pygame.draw.line(surf, (200, 200, 210), P(h - 10, -44), front, 5)      # fork
    pygame.draw.line(surf, (110, 110, 120), P(-8, -10), P(-h - 10, -16), 6)  # exhaust
    if boosting:
        e = P(-h - 10, -16)
        ln = random.randint(26, 46)
        pygame.draw.polygon(surf, (90, 170, 255), [e, P(-h - 10 - ln, -16), P(-h - 10, -10)])
        pygame.draw.polygon(surf, (235, 248, 255), [e, P(-h - 10 - ln * 0.55, -16), P(-h - 10, -13)])

    pygame.draw.polygon(surf, color, [P(-22, -14), P(-16, -32), P(8, -38), P(24, -28), P(14, -10), P(-10, -6)])
    pygame.draw.polygon(surf, (25, 25, 30), [P(-26, -30), P(-8, -37), P(-5, -32), P(-24, -26)])  # seat
    pygame.draw.polygon(surf, (70, 72, 80), [P(-6, -8), P(14, -8), P(14, -20), P(-6, -20)])       # engine
    pygame.draw.circle(surf, (255, 250, 190), I(P(h - 6, -44)), 4)                                 # headlight

    hip, knee, foot = P(-10, -38), P(8, -32), P(-2, -12)
    shoulder, head, hand = P(2, -62), P(6, -74), P(h - 14, -46)
    pygame.draw.line(surf, (30, 30, 40), hip, knee, 7)
    pygame.draw.line(surf, (30, 30, 40), knee, foot, 6)
    pygame.draw.line(surf, rider, hip, shoulder, 10)
    pygame.draw.line(surf, rider, shoulder, hand, 5)
    pygame.draw.circle(surf, (245, 245, 245), I(head), 9)
    pygame.draw.circle(surf, (30, 40, 70), I(P(10, -74)), 4)


def draw_checkered(surf, x, y_top, w, h, cell=10):
    for r in range(int(h // cell) + 1):
        for c in range(int(w // cell)):
            col = (250, 250, 250) if (r + c) % 2 == 0 else (20, 20, 20)
            pygame.draw.rect(surf, col, (x + c * cell, y_top + r * cell, cell, cell))


# ------------------------------------------------------------------- game
class Game:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Moto Rush")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.canvas = pygame.Surface((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("arial", 22, bold=True)
        self.small = pygame.font.SysFont("arial", 16, bold=True)
        self.mid = pygame.font.SysFont("arial", 34, bold=True)
        self.big = pygame.font.SysFont("arial", 84, bold=True)
        self.best = load_best()
        self.state = "menu"  # menu | race | finished
        self.sky = self.make_sky()
        rng = random.Random(3)
        self.clouds = [(rng.randint(0, WIDTH + 300), rng.randint(20, 200), rng.uniform(0.7, 1.5))
                       for _ in range(7)]
        self.reset_race()

    @staticmethod
    def make_sky():
        s = pygame.Surface((WIDTH, HEIGHT))
        for y in range(HEIGHT):
            t = y / HEIGHT
            col = tuple(int(SKY_TOP[i] + (SKY_BOTTOM[i] - SKY_TOP[i]) * t) for i in range(3))
            pygame.draw.line(s, col, (0, y), (WIDTH, y))
        return s

    # ---------------------------------------------------------- setup
    def reset_race(self):
        self.player = Bike(START_X, (225, 45, 55), (40, 60, 210), "YOU", can_crash=True)
        self.rivals = [
            Bike(60, (40, 120, 230), (250, 205, 40), "Blue", cap=9.4),
            Bike(0, (250, 190, 30), (40, 40, 50), "Gold", cap=10.2),
            Bike(-60, (60, 200, 90), (210, 60, 60), "Jade", cap=11.0),
        ]
        self.countdown = 210
        self.frame = 0
        self.penalty = 0.0
        self.checkpoint_x = START_X
        self.dead = 0
        self.finished = False
        self.after_finish = 0
        self.place = 0
        self.total_time = 0.0
        self.new_best = False
        self.paused = False
        self.particles = []
        self.popups = []
        self.shake = 0
        self.cam_x = self.player.x - 300
        self.cam_y = self.player.y - 330

    def popup(self, text, color=(255, 255, 255)):
        self.popups.append([text, 90, color])
        self.popups = self.popups[-4:]

    def burst(self, x, y, color, n, power, grav=0.0):
        for _ in range(n):
            a = random.uniform(0, math.tau)
            s = random.uniform(0.5, power)
            self.particles.append([x, y, math.cos(a) * s, math.sin(a) * s,
                                   random.randint(20, 45), color, random.randint(2, 5), grav])

    # --------------------------------------------------------- update
    def time_now(self):
        return self.frame / 60.0 + self.penalty

    def position(self):
        return 1 + sum(1 for r in self.rivals if r.x > self.player.x)

    def update(self):
        p = self.player
        if self.countdown > 0:
            self.countdown -= 1
        else:
            if not self.finished:
                self.frame += 1
            self.update_player()
            self.update_rivals()

        # particles / popups / shake
        for q in self.particles:
            q[0] += q[2]
            q[1] += q[3]
            q[3] += q[7]
            q[4] -= 1
        self.particles = [q for q in self.particles if q[4] > 0]
        for pu in self.popups:
            pu[1] -= 1
        self.popups = [pu for pu in self.popups if pu[1] > 0]
        if self.shake > 0:
            self.shake -= 1

        # camera
        self.cam_x += (p.x - 300 - self.cam_x) * 0.15
        self.cam_y += (p.y - 330 - self.cam_y) * 0.10

        if self.finished:
            self.after_finish += 1
            if self.after_finish > 150:
                self.state = "finished"

    def update_player(self):
        p = self.player
        if self.dead > 0:
            self.dead -= 1
            if self.dead == 0:
                self.respawn_player()
            return

        keys = pygame.key.get_pressed()
        up = keys[pygame.K_UP] or keys[pygame.K_w]
        down = keys[pygame.K_DOWN] or keys[pygame.K_s]
        left = keys[pygame.K_LEFT] or keys[pygame.K_a]
        right = keys[pygame.K_RIGHT] or keys[pygame.K_d]
        boost = keys[pygame.K_SPACE]
        lean = int(bool(right)) - int(bool(left))
        if self.finished:
            up, down, boost, lean = False, p.vx > 0.5, False, 0

        was_grounded = p.grounded
        events = p.update(bool(up), bool(down), bool(boost), lean)
        if was_grounded and not p.grounded:
            self.burst(p.x, p.y + WHEEL_R, (200, 170, 120), 8, 3)

        for ev in events:
            if ev[0] == "crash":
                self.dead = 70
                self.penalty += 3.0
                self.shake = 24
                for col in ((255, 140, 30), (255, 220, 70), (80, 80, 90), p.color):
                    self.burst(p.x, p.y, col, 18, 6, 0.15)
                self.popup("WIPE-OUT!  +3s", (255, 90, 70))
            elif ev[0] == "flip":
                n, d = ev[1], ev[2]
                name = "BACKFLIP" if d < 0 else "FRONTFLIP"
                self.popup(f"{name} x{n}  +nitro" if n > 1 else f"{name}  +nitro", (255, 230, 90))
                self.burst(p.x, p.y + WHEEL_R, (255, 230, 120), 12, 4)
            elif ev[0] == "perfect":
                self.popup("PERFECT LANDING", (120, 255, 160))
            elif ev[0] == "pad":
                self.popup("BOOST!", (255, 160, 40))

        # dust from the rear wheel
        if p.grounded and p.vx > 6 and random.random() < 0.5 and self.dead == 0:
            rx = p.x - WHEEL_BASE / 2
            self.particles.append([rx, ground(rx), random.uniform(-2.5, -0.5), random.uniform(-1.5, -0.3),
                                   random.randint(12, 22), (196, 168, 120), random.randint(2, 4), 0.02])
        if p.boosting and random.random() < 0.7 and self.dead == 0:
            self.particles.append([p.x - 46, p.y - 12, random.uniform(-3, -1), random.uniform(-0.5, 0.5),
                                   14, (120, 190, 255), 3, 0.0])

        # checkpoints
        for cp in CHECKPOINTS:
            if p.x >= cp > self.checkpoint_x:
                self.checkpoint_x = cp
                self.popup("CHECKPOINT", (140, 255, 140))

        # finish
        if not self.finished and p.x >= TRACK_LEN:
            self.finished = True
            self.place = 1 + sum(1 for r in self.rivals if r.finish_frame is not None)
            self.total_time = self.time_now()
            if self.best is None or self.total_time < self.best:
                self.best = self.total_time
                self.new_best = True
                save_best(self.best)

    def respawn_player(self):
        p = self.player
        p.respawn(self.checkpoint_x, 4.0)
        p.invuln = 120
        p.nitro = max(p.nitro, 40.0)
        p.used_pads = {i for i in p.used_pads if PADS[i] < self.checkpoint_x}

    def update_rivals(self):
        p = self.player
        for r in self.rivals:
            r.cap = {"Blue": 9.4, "Gold": 10.2, "Jade": 11.0}[r.name] + clamp((p.x - r.x) / 600.0, -1.2, 2.2)
            up = r.vx < r.cap
            r.update(up, False, False, 0)
            if r.finish_frame is None and r.x >= TRACK_LEN:
                r.finish_frame = self.frame
            if r.finish_frame is not None:
                r.vx *= 0.96

    # ----------------------------------------------------------- draw
    def draw_mountains(self, s, factor, base, amp, color, phase):
        pts = [(0, HEIGHT)]
        for sx in range(0, WIDTH + 20, 20):
            wx = sx + self.cam_x * factor
            y = (base - self.cam_y * 0.05 -
                 amp * (0.6 + 0.4 * math.sin(wx / 260 + phase)) * (0.5 + 0.5 * math.sin(wx / 610 + phase * 2)))
            pts.append((sx, y))
        pts.append((WIDTH, HEIGHT))
        pygame.draw.polygon(s, color, pts)

    def draw_background(self, s):
        s.blit(self.sky, (0, 0))
        for cx, cy, sc in self.clouds:
            sx = (cx - self.cam_x * 0.15) % (WIDTH + 300) - 150
            for dx, dy, rw, rh in ((0, 0, 70, 26), (-34, 8, 50, 20), (36, 8, 54, 22)):
                pygame.draw.ellipse(s, (255, 255, 255),
                                    (sx + dx * sc - rw * sc / 2, cy + dy * sc, rw * sc, rh * sc))
        self.draw_mountains(s, 0.10, 360, 190, (150, 175, 215), 0.0)
        self.draw_mountains(s, 0.25, 430, 150, (104, 140, 170), 2.0)

    def draw_terrain(self, s):
        pts = []
        for sx in range(0, WIDTH + 8, 6):
            pts.append((sx, ground(self.cam_x + sx) - self.cam_y))
        pygame.draw.polygon(s, DIRT, pts + [(WIDTH, HEIGHT + 10), (0, HEIGHT + 10)])
        deep = [(x, y + 34) for x, y in pts]
        pygame.draw.polygon(s, DIRT_DARK, deep + [(WIDTH, HEIGHT + 10), (0, HEIGHT + 10)])
        pygame.draw.lines(s, GRASS, False, pts, 9)

        # ramps highlighted in yellow
        for rx in RAMPS:
            if rx + RAMP_LEN < self.cam_x - 20 or rx > self.cam_x + WIDTH + 20:
                continue
            rp = [(wx - self.cam_x, ground(wx) - self.cam_y) for wx in range(rx, rx + RAMP_LEN, 8)]
            pygame.draw.lines(s, (255, 205, 40), False, rp, 9)
            ax = rx - self.cam_x - 40
            ay = ground(rx - 40) - self.cam_y
            for k in range(2):  # warning chevrons
                pygame.draw.lines(s, (255, 205, 40), False,
                                  [(ax + k * 14, ay - 30), (ax + k * 14 + 10, ay - 22), (ax + k * 14, ay - 14)], 4)

        # boost pads
        for px in PADS:
            if px + PAD_LEN < self.cam_x or px > self.cam_x + WIDTH:
                continue
            used = False
            pp = [(wx - self.cam_x, ground(wx) - self.cam_y - 2) for wx in range(px, px + PAD_LEN + 1, 10)]
            pygame.draw.lines(s, (255, 130, 20), False, pp, 9)
            for k in range(3):
                wx = px + 10 + k * 20
                gx, gy = wx - self.cam_x, ground(wx) - self.cam_y
                pygame.draw.lines(s, (255, 235, 120), False, [(gx, gy - 14), (gx + 9, gy - 8), (gx, gy - 2)], 3)

        # checkpoints, start and finish
        for cp in CHECKPOINTS:
            if abs(cp - self.cam_x - WIDTH / 2) < WIDTH / 2 + 60:
                gx, gy = cp - self.cam_x, ground(cp) - self.cam_y
                reached = self.checkpoint_x >= cp
                pygame.draw.line(s, (230, 230, 230), (gx, gy), (gx, gy - 110), 5)
                col = (60, 220, 90) if reached else (230, 70, 70)
                pygame.draw.polygon(s, col, [(gx, gy - 110), (gx + 50, gy - 92), (gx, gy - 74)])
        if abs(START_X + 140 - self.cam_x - WIDTH / 2) < WIDTH / 2 + 60:
            gx, gy = START_X + 140 - self.cam_x, ground(START_X + 140) - self.cam_y
            pygame.draw.rect(s, (255, 255, 255), (gx, gy - 4, 6, 6))
            pygame.draw.line(s, (255, 255, 255), (gx, gy - 6), (gx, gy - 150), 4)
        if abs(TRACK_LEN - self.cam_x - WIDTH / 2) < WIDTH / 2 + 80:
            gx, gy = TRACK_LEN - self.cam_x, ground(TRACK_LEN) - self.cam_y
            pygame.draw.rect(s, (60, 60, 70), (gx - 8, gy - 190, 8, 190))
            draw_checkered(s, gx, gy - 190, 30, 60)
            pygame.draw.rect(s, (60, 60, 70), (gx + 30, gy - 190, 8, 190))

    def draw_world(self, s):
        self.draw_background(s)
        self.draw_terrain(s)
        for r in self.rivals:
            draw_bike(s, r.x - self.cam_x, r.y - self.cam_y, r.angle, r.color, r.rider, r.spin)
            self.text(s, r.name, self.small, (255, 255, 255),
                      (r.x - self.cam_x, r.y - self.cam_y - 100), True)
        p = self.player
        if self.dead == 0 and not (p.invuln > 0 and (p.invuln // 5) % 2 == 0):
            draw_bike(s, p.x - self.cam_x, p.y - self.cam_y, p.angle, p.color, p.rider, p.spin, p.boosting)
        for x, y, _, _, life, col, size, _ in self.particles:
            pygame.draw.circle(s, col, (int(x - self.cam_x), int(y - self.cam_y)),
                               max(1, int(size * min(life, 30) / 30) + 1))

    def text(self, s, txt, font, color, pos, center=False, shadow=True):
        img = font.render(txt, True, color)
        rect = img.get_rect(center=pos) if center else img.get_rect(topleft=pos)
        if shadow:
            s.blit(font.render(txt, True, (0, 0, 0)), rect.move(2, 2))
        s.blit(img, rect)

    def draw_hud(self, s):
        p = self.player
        pos = self.place if self.finished else self.position()
        self.text(s, f"{ordinal(pos)} / 4", self.mid, (255, 255, 255), (16, 10))
        t = self.total_time if self.finished else self.time_now()
        self.text(s, f"Time {t:5.1f}s", self.font, (255, 255, 255), (16, 54))
        if self.penalty:
            self.text(s, f"(+{self.penalty:.0f}s penalties)", self.small, (255, 150, 130), (16, 82))
        self.text(s, f"{int(p.vx * 8)} km/h", self.mid, (255, 255, 255), (WIDTH - 170, 10))

        # nitro bar
        bar = pygame.Rect(16, HEIGHT - 34, 200, 16)
        pygame.draw.rect(s, (20, 25, 40), bar, border_radius=6)
        w = int(bar.w * p.nitro / 100)
        if w > 0:
            pygame.draw.rect(s, (90, 170, 255), (bar.x, bar.y, w, bar.h), border_radius=6)
        pygame.draw.rect(s, (255, 255, 255), bar, 2, border_radius=6)
        self.text(s, "NITRO", self.small, (255, 255, 255), (bar.right + 10, bar.y - 1))

        # progress bar
        x0, x1, y = 300, 660, 26
        pygame.draw.line(s, (20, 25, 40), (x0, y), (x1, y), 8)
        pygame.draw.line(s, (235, 235, 235), (x0, y), (x1, y), 4)
        for cp in CHECKPOINTS:
            cx = x0 + (x1 - x0) * cp / TRACK_LEN
            pygame.draw.line(s, (40, 40, 40), (cx, y - 7), (cx, y + 7), 2)
        draw_checkered(s, x1, y - 9, 10, 18, 5)
        for r in self.rivals:
            rx = x0 + (x1 - x0) * clamp(r.x / TRACK_LEN, 0, 1)
            pygame.draw.circle(s, r.color, (int(rx), y), 6)
            pygame.draw.circle(s, (0, 0, 0), (int(rx), y), 6, 1)
        px = x0 + (x1 - x0) * clamp(p.x / TRACK_LEN, 0, 1)
        pygame.draw.circle(s, p.color, (int(px), y), 9)
        pygame.draw.circle(s, (255, 255, 255), (int(px), y), 9, 2)

        # popups
        for i, (txt, life, col) in enumerate(reversed(self.popups)):
            self.text(s, txt, self.mid, col, (WIDTH // 2, 100 + i * 40), True)

    def draw_overlay(self, s, alpha=150):
        dim = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        dim.fill((0, 0, 0, alpha))
        s.blit(dim, (0, 0))

    def draw(self):
        c = self.canvas
        self.draw_world(c)
        if self.state == "menu":
            self.draw_overlay(c)
            self.text(c, "MOTO RUSH", self.big, (255, 90, 70), (WIDTH // 2, 130), True)
            lines = ["UP / DOWN  -  throttle & brake",
                     "LEFT / RIGHT  -  lean in the air (flips give free nitro)",
                     "SPACE  -  nitro        P  -  pause",
                     "Land level to keep your speed. Crash = +3s and back to the checkpoint."]
            for i, ln in enumerate(lines):
                self.text(c, ln, self.font, (235, 235, 235), (WIDTH // 2, 235 + i * 34), True)
            if int(pygame.time.get_ticks() / 500) % 2 == 0:
                self.text(c, "Press ENTER to race", self.mid, (255, 230, 100), (WIDTH // 2, 420), True)
            if self.best is not None:
                self.text(c, f"Best time: {self.best:.1f}s", self.font, (255, 255, 255), (WIDTH // 2, 475), True)
        else:
            self.draw_hud(c)
            if self.countdown > 0:
                n = (self.countdown + 29) // 60
                self.text(c, str(n) if n > 0 else "GO!", self.big,
                          (255, 230, 90) if n > 0 else (120, 255, 150), (WIDTH // 2, 230), True)
            if self.finished and self.state == "race":
                self.text(c, "FINISH!", self.big, (255, 255, 255), (WIDTH // 2, 230), True)
            if self.paused:
                self.draw_overlay(c)
                self.text(c, "PAUSED", self.big, (255, 255, 255), (WIDTH // 2, 230), True)
                self.text(c, "Press P to resume", self.font, (225, 225, 225), (WIDTH // 2, 300), True)
            if self.state == "finished":
                self.draw_overlay(c, 170)
                self.text(c, f"You finished {ordinal(self.place)}!", self.big if self.place < 4 else self.mid,
                          (255, 230, 90) if self.place == 1 else (255, 255, 255), (WIDTH // 2, 150), True)
                self.text(c, f"Time: {self.total_time:.2f}s  (penalties: +{self.penalty:.0f}s)",
                          self.mid, (255, 255, 255), (WIDTH // 2, 255), True)
                if self.new_best:
                    self.text(c, "NEW BEST TIME!", self.mid, (120, 255, 160), (WIDTH // 2, 310), True)
                elif self.best is not None:
                    self.text(c, f"Best: {self.best:.2f}s", self.font, (225, 225, 225), (WIDTH // 2, 310), True)
                self.text(c, "Press ENTER to race again", self.mid, (255, 230, 100), (WIDTH // 2, 400), True)

        ox = oy = 0
        if self.shake > 0:
            ox, oy = random.randint(-7, 7), random.randint(-7, 7)
        self.screen.fill((0, 0, 0))
        self.screen.blit(c, (ox, oy))
        pygame.display.flip()

    # ----------------------------------------------------------- loop
    def handle_event(self, event):
        if event.type == pygame.QUIT:
            pygame.quit()
            sys.exit()
        if event.type != pygame.KEYDOWN:
            return
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            if self.state in ("menu", "finished"):
                self.reset_race()
                self.state = "race"
        elif event.key == pygame.K_r:
            if self.state == "race":
                self.reset_race()
                self.state = "race"
        elif event.key in (pygame.K_p, pygame.K_ESCAPE):
            if self.state == "race":
                self.paused = not self.paused
            elif event.key == pygame.K_ESCAPE:
                pygame.quit()
                sys.exit()

    def run(self):
        while True:
            for event in pygame.event.get():
                self.handle_event(event)
            if self.state == "race" and not self.paused:
                self.update()
            elif self.state == "finished":
                self.update()
            elif self.state == "menu":
                # let the rivals cruise behind the title screen
                for r in self.rivals:
                    r.cap = 8.0
                    r.update(r.vx < r.cap, False, False, 0)
                    if r.x > 4000:
                        r.respawn(0, 0.0)
                self.cam_x += (self.rivals[2].x - 300 - self.cam_x) * 0.15
                self.cam_y += (self.rivals[2].y - 330 - self.cam_y) * 0.10
            self.draw()
            self.clock.tick(FPS)


if __name__ == "__main__":
    Game().run()
