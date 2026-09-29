"""
Turbo Racer - a top-down endless car racing game built with pygame.

Install:  pip install pygame
Run:      python turbo_racer.py

Controls
  LEFT / RIGHT  (or A / D)  steer
  UP / DOWN     (or W / S)  accelerate / brake
  SPACE                     nitro boost (drains the blue meter)
  P or ESC                  pause
  ENTER / R                 start / restart
"""

import math
import os
import random
import sys

import pygame

# ---------------------------------------------------------------- settings
WIDTH, HEIGHT = 480, 720
FPS = 60

ROAD_W = 360
ROAD_X = (WIDTH - ROAD_W) // 2
LANES = 4
LANE_W = ROAD_W // LANES

CAR_W, CAR_H = 44, 80
PLAYER_Y = HEIGHT - 140

GRASS = (34, 139, 64)
GRASS_DARK = (28, 122, 56)
ASPHALT = (54, 56, 62)
LINE = (235, 235, 235)
EDGE = (240, 200, 40)

ENEMY_COLORS = [
    (220, 60, 60), (240, 150, 40), (150, 80, 200),
    (60, 170, 220), (230, 230, 230), (60, 60, 70),
]

HIGHSCORE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "highscore.txt")


def lane_center(lane):
    return ROAD_X + lane * LANE_W + LANE_W / 2


def load_high():
    try:
        with open(HIGHSCORE_FILE) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return 0


def save_high(value):
    try:
        with open(HIGHSCORE_FILE, "w") as f:
            f.write(str(value))
    except OSError:
        pass


def draw_car(surf, cx, cy, color, w=CAR_W, h=CAR_H, braking=False, boosting=False):
    """Draw a car (facing up) centred on (cx, cy)."""
    # wheels
    for dx in (-1, 1):
        for dy in (-0.3, 0.3):
            r = pygame.Rect(0, 0, w * 0.2, h * 0.22)
            r.center = (cx + dx * w / 2, cy + dy * h)
            pygame.draw.rect(surf, (15, 15, 15), r, border_radius=3)

    body = pygame.Rect(0, 0, w, h)
    body.center = (cx, cy)
    pygame.draw.rect(surf, color, body, border_radius=12)

    # racing stripe
    stripe = pygame.Rect(0, 0, w * 0.16, h * 0.96)
    stripe.center = (cx, cy)
    lighter = tuple(min(255, c + 45) for c in color)
    pygame.draw.rect(surf, lighter, stripe, border_radius=4)

    # windshield / rear window
    ws = pygame.Rect(0, 0, w * 0.72, h * 0.2)
    ws.center = (cx, cy - h * 0.14)
    pygame.draw.rect(surf, (25, 35, 55), ws, border_radius=6)
    ws2 = pygame.Rect(0, 0, w * 0.7, h * 0.13)
    ws2.center = (cx, cy + h * 0.25)
    pygame.draw.rect(surf, (25, 35, 55), ws2, border_radius=5)

    # headlights
    for dx in (-1, 1):
        pygame.draw.circle(surf, (255, 250, 200), (int(cx + dx * w * 0.33), int(cy - h / 2 + 5)), 4)
    # tail lights
    tail = (255, 40, 40) if braking else (150, 20, 20)
    for dx in (-1, 1):
        pygame.draw.rect(surf, tail, (cx + dx * w * 0.33 - 4, cy + h / 2 - 7, 8, 5), border_radius=2)

    # nitro flames
    if boosting:
        for dx in (-1, 1):
            fl = random.randint(14, 28)
            pts = [(cx + dx * w * 0.25 - 5, cy + h / 2),
                   (cx + dx * w * 0.25 + 5, cy + h / 2),
                   (cx + dx * w * 0.25, cy + h / 2 + fl)]
            pygame.draw.polygon(surf, (90, 170, 255), pts)
            pts2 = [(p[0] * 0.5 + cx * 0.5 + (dx * w * 0.25) * 0.0, p[1]) for p in pts]
            pygame.draw.polygon(surf, (230, 245, 255), [
                (cx + dx * w * 0.25 - 2, cy + h / 2),
                (cx + dx * w * 0.25 + 2, cy + h / 2),
                (cx + dx * w * 0.25, cy + h / 2 + fl * 0.6)])


class Game:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Turbo Racer")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.canvas = pygame.Surface((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("arial", 22, bold=True)
        self.big = pygame.font.SysFont("arial", 56, bold=True)
        self.mid = pygame.font.SysFont("arial", 30, bold=True)
        self.small = pygame.font.SysFont("arial", 16)
        self.high = load_high()
        self.state = "menu"  # menu | play | over
        self.reset()

    # ----------------------------------------------------------- state
    def reset(self):
        self.px = lane_center(1)
        self.vx = 0.0
        self.speed = 7.0
        self.distance = 0.0
        self.coins_collected = 0
        self.nitro = 100.0
        self.enemies = []
        self.coins = []
        self.particles = []
        self.spawn_timer = 250
        self.road_offset = 0.0
        self.shake = 0
        self.paused = False
        self.braking = False
        self.boosting = False
        self.new_high = False

    @property
    def score(self):
        return int(self.distance) + self.coins_collected * 50

    @property
    def difficulty(self):
        return min(self.distance / 2500.0, 1.0)

    # ---------------------------------------------------------- update
    def spawn_row(self):
        n_cars = 1 if random.random() < 0.55 else 2
        lanes = random.sample(range(LANES), n_cars)
        for ln in lanes:
            self.enemies.append({
                "x": lane_center(ln),
                "y": -CAR_H - 20,
                "e": random.uniform(2.0, 4.5),  # enemy's own forward speed
                "color": random.choice(ENEMY_COLORS),
            })
        free = [l for l in range(LANES) if l not in lanes]
        if free and random.random() < 0.4:
            self.coins.append({"x": lane_center(random.choice(free)), "y": -260, "spin": 0.0})

    def update(self):
        keys = pygame.key.get_pressed()
        left = keys[pygame.K_LEFT] or keys[pygame.K_a]
        right = keys[pygame.K_RIGHT] or keys[pygame.K_d]
        up = keys[pygame.K_UP] or keys[pygame.K_w]
        down = keys[pygame.K_DOWN] or keys[pygame.K_s]
        space = keys[pygame.K_SPACE]

        # speed control
        target = 7 + 7 * self.difficulty
        self.braking = bool(down)
        if up:
            target += 3
        if down:
            target = max(4, target - 5)
        self.boosting = bool(space and self.nitro > 0)
        if self.boosting:
            target += 6
            self.nitro = max(0, self.nitro - 0.9)
        else:
            self.nitro = min(100, self.nitro + 0.12)
        self.speed += (target - self.speed) * 0.05

        # steering (scaled a little with speed so it stays responsive)
        steer = 4.5 + self.speed * 0.15
        want = (right - left) * steer
        self.vx += (want - self.vx) * 0.22
        self.px += self.vx
        half = CAR_W / 2 + 6
        self.px = max(ROAD_X + half, min(ROAD_X + ROAD_W - half, self.px))

        # world scroll
        self.road_offset = (self.road_offset + self.speed) % 80
        self.distance += self.speed / 10

        # spawning
        self.spawn_timer -= self.speed
        if self.spawn_timer <= 0:
            self.spawn_row()
            base = 430 - 210 * self.difficulty
            self.spawn_timer = random.uniform(0.75, 1.1) * base

        # enemies
        for e in self.enemies:
            e["y"] += self.speed - e["e"]
        self.enemies = [e for e in self.enemies if -500 < e["y"] < HEIGHT + 120]

        # coins
        for c in self.coins:
            c["y"] += self.speed
            c["spin"] += 0.15
        self.coins = [c for c in self.coins if c["y"] < HEIGHT + 40]

        # collisions
        hit = pygame.Rect(0, 0, CAR_W - 8, CAR_H - 10)
        hit.center = (self.px, PLAYER_Y)
        for c in self.coins[:]:
            if math.hypot(c["x"] - self.px, c["y"] - PLAYER_Y) < 34:
                self.coins.remove(c)
                self.coins_collected += 1
                self.nitro = min(100, self.nitro + 8)
                self.burst(c["x"], c["y"], (255, 215, 0), 10, 3)
        for e in self.enemies:
            r = pygame.Rect(0, 0, CAR_W - 8, CAR_H - 10)
            r.center = (e["x"], e["y"])
            if hit.colliderect(r):
                self.crash()
                break

        self.update_particles()
        if self.boosting and random.random() < 0.6:
            self.particles.append([self.px + random.choice((-10, 10)), PLAYER_Y + CAR_H / 2,
                                   random.uniform(-0.6, 0.6), random.uniform(2, 4),
                                   14, (120, 190, 255), 3])

    def burst(self, x, y, color, n, power):
        for _ in range(n):
            a = random.uniform(0, math.tau)
            s = random.uniform(0.5, power)
            self.particles.append([x, y, math.cos(a) * s, math.sin(a) * s,
                                   random.randint(20, 40), color, random.randint(2, 5)])

    def update_particles(self):
        for p in self.particles:
            p[0] += p[2]
            p[1] += p[3]
            p[4] -= 1
        self.particles = [p for p in self.particles if p[4] > 0]
        if self.shake > 0:
            self.shake -= 1

    def crash(self):
        self.state = "over"
        self.shake = 22
        for col in ((255, 120, 30), (255, 220, 60), (90, 90, 90)):
            self.burst(self.px, PLAYER_Y, col, 25, 6)
        if self.score > self.high:
            self.high = self.score
            self.new_high = True
            save_high(self.high)

    # ------------------------------------------------------------ draw
    def draw_road(self, s):
        s.fill(GRASS)
        # grass stripes for a sense of speed
        for i in range(-1, HEIGHT // 80 + 2):
            y = i * 80 + self.road_offset
            pygame.draw.rect(s, GRASS_DARK, (0, y, ROAD_X, 40))
            pygame.draw.rect(s, GRASS_DARK, (ROAD_X + ROAD_W, y, WIDTH - ROAD_X - ROAD_W, 40))
        pygame.draw.rect(s, ASPHALT, (ROAD_X, 0, ROAD_W, HEIGHT))
        pygame.draw.rect(s, EDGE, (ROAD_X - 6, 0, 6, HEIGHT))
        pygame.draw.rect(s, EDGE, (ROAD_X + ROAD_W, 0, 6, HEIGHT))
        # dashed lane lines
        for lane in range(1, LANES):
            x = ROAD_X + lane * LANE_W
            for i in range(-1, HEIGHT // 80 + 2):
                y = i * 80 + self.road_offset
                pygame.draw.rect(s, LINE, (x - 2, y, 4, 40))
        # roadside posts
        for i in range(-1, HEIGHT // 160 + 2):
            y = i * 160 + (self.road_offset * 1.0) % 160
            pygame.draw.rect(s, (200, 200, 200), (ROAD_X - 26, y, 8, 22), border_radius=2)
            pygame.draw.rect(s, (200, 200, 200), (ROAD_X + ROAD_W + 18, y, 8, 22), border_radius=2)

    def draw_world(self, s):
        self.draw_road(s)
        for c in self.coins:
            w = max(3, int(11 * abs(math.cos(c["spin"]))))
            pygame.draw.ellipse(s, (255, 205, 30), (c["x"] - w, c["y"] - 12, w * 2, 24))
            pygame.draw.ellipse(s, (255, 240, 130), (c["x"] - w, c["y"] - 12, w * 2, 24), 2)
        for e in self.enemies:
            draw_car(s, e["x"], e["y"], e["color"])
        if self.state != "over":
            tilt_surf = pygame.Surface((CAR_W + 60, CAR_H + 80), pygame.SRCALPHA)
            draw_car(tilt_surf, tilt_surf.get_width() / 2, tilt_surf.get_height() / 2 - 10,
                     (230, 40, 50), braking=self.braking, boosting=self.boosting)
            tilt_surf = pygame.transform.rotate(tilt_surf, -self.vx * 2.2)
            s.blit(tilt_surf, tilt_surf.get_rect(center=(self.px, PLAYER_Y + 10)))
        for x, y, _, _, life, col, size in self.particles:
            pygame.draw.circle(s, col, (int(x), int(y)), max(1, int(size * life / 30) + 1))

    def text(self, s, txt, font, color, pos, center=False, shadow=True):
        img = font.render(txt, True, color)
        rect = img.get_rect(center=pos) if center else img.get_rect(topleft=pos)
        if shadow:
            sh = font.render(txt, True, (0, 0, 0))
            s.blit(sh, rect.move(2, 2))
        s.blit(img, rect)

    def draw_hud(self, s):
        self.text(s, f"Score {self.score}", self.font, (255, 255, 255), (12, 10))
        self.text(s, f"Best {max(self.high, self.score)}", self.small, (255, 230, 120), (12, 40))
        self.text(s, f"{int(self.speed * 12)} km/h", self.font, (255, 255, 255), (WIDTH - 125, 10))
        # nitro bar
        bar = pygame.Rect(WIDTH - 22, 70, 12, 160)
        pygame.draw.rect(s, (20, 20, 30), bar, border_radius=5)
        fill = pygame.Rect(bar.x, bar.bottom - bar.h * self.nitro / 100, bar.w, bar.h * self.nitro / 100)
        pygame.draw.rect(s, (90, 170, 255), fill, border_radius=5)
        pygame.draw.rect(s, (255, 255, 255), bar, 2, border_radius=5)
        self.text(s, "N", self.small, (255, 255, 255), (WIDTH - 16, 236))
        self.text(s, f"Coins {self.coins_collected}", self.small, (255, 215, 0), (12, 62))

    def draw_overlay(self, s):
        dim = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 150))
        s.blit(dim, (0, 0))

    def draw(self):
        c = self.canvas
        self.draw_world(c)
        if self.state == "play":
            self.draw_hud(c)
            if self.paused:
                self.draw_overlay(c)
                self.text(c, "PAUSED", self.big, (255, 255, 255), (WIDTH // 2, HEIGHT // 2 - 20), True)
                self.text(c, "Press P to resume", self.font, (220, 220, 220), (WIDTH // 2, HEIGHT // 2 + 30), True)
        elif self.state == "menu":
            self.draw_overlay(c)
            self.text(c, "TURBO", self.big, (255, 70, 70), (WIDTH // 2, 190), True)
            self.text(c, "RACER", self.big, (255, 255, 255), (WIDTH // 2, 250), True)
            lines = ["Arrows / WASD  -  steer & speed",
                     "SPACE  -  nitro boost",
                     "Dodge traffic, grab coins",
                     "P  -  pause"]
            for i, ln in enumerate(lines):
                self.text(c, ln, self.small, (230, 230, 230), (WIDTH // 2, 340 + i * 26), True)
            blink = int(pygame.time.get_ticks() / 500) % 2 == 0
            if blink:
                self.text(c, "Press ENTER to start", self.mid, (255, 230, 100), (WIDTH // 2, 500), True)
            self.text(c, f"Best: {self.high}", self.font, (255, 255, 255), (WIDTH // 2, 560), True)
        elif self.state == "over":
            self.draw_hud(c)
            self.draw_overlay(c)
            self.text(c, "CRASH!", self.big, (255, 80, 60), (WIDTH // 2, 230), True)
            self.text(c, f"Score: {self.score}", self.mid, (255, 255, 255), (WIDTH // 2, 310), True)
            if self.new_high:
                self.text(c, "NEW HIGH SCORE!", self.font, (255, 230, 90), (WIDTH // 2, 350), True)
            else:
                self.text(c, f"Best: {self.high}", self.font, (255, 230, 90), (WIDTH // 2, 350), True)
            self.text(c, f"Distance {int(self.distance)} m   Coins {self.coins_collected}",
                      self.small, (220, 220, 220), (WIDTH // 2, 385), True)
            self.text(c, "Press ENTER or R to race again", self.font, (255, 255, 255), (WIDTH // 2, 450), True)

        ox = oy = 0
        if self.shake > 0:
            ox, oy = random.randint(-6, 6), random.randint(-6, 6)
        self.screen.fill((0, 0, 0))
        self.screen.blit(c, (ox, oy))
        pygame.display.flip()

    # ------------------------------------------------------------ loop
    def handle_event(self, event):
        if event.type == pygame.QUIT:
            pygame.quit()
            sys.exit()
        if event.type != pygame.KEYDOWN:
            return
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_r):
            if self.state in ("menu", "over"):
                self.reset()
                self.state = "play"
        elif event.key in (pygame.K_p, pygame.K_ESCAPE):
            if self.state == "play":
                self.paused = not self.paused
            elif event.key == pygame.K_ESCAPE:
                pygame.quit()
                sys.exit()

    def run(self):
        while True:
            for event in pygame.event.get():
                self.handle_event(event)
            if self.state == "play" and not self.paused:
                self.update()
            elif self.state == "over":
                self.update_particles()
            elif self.state == "menu":
                self.road_offset = (self.road_offset + 4) % 80
            self.draw()
            self.clock.tick(FPS)


if __name__ == "__main__":
    Game().run()
