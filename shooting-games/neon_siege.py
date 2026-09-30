"""
NEON SIEGE - a twin-stick arena shooter built with pygame.
All graphics and sound are generated in code (no asset files needed).

Install:  pip install pygame
Run:      python neon_siege.py

Controls
  W A S D        move
  Mouse          aim
  Left click     shoot (hold)
  Shift / Right  dash (brief invulnerability)
  Space          bomb (clears bullets, damages everything nearby)
  P / Esc        pause (Esc quits from the menu)
  G              toggle bloom (turn off if the game runs slowly)
  F11            fullscreen
  Enter          start / play again

Pick up glowing items: green = repair, yellow star = weapon upgrade,
blue = shield, pink = bomb, orange = rapid fire. Every 5th wave is a boss.
"""

import array
import math
import os
import random
import sys

import pygame

# ---------------------------------------------------------------- settings
W, H = 1280, 720
FPS = 60
M = 26                                   # arena margin
ARENA = (M, M, W - 2 * M, H - 2 * M)
AX0, AY0, AX1, AY1 = M, M, W - M, H - M
MAX_PART = 1300

HS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "neon_siege_highscore.txt")

CYAN = (60, 220, 255)
PINK = (255, 70, 170)
ORANGE = (255, 150, 50)
YELLOW = (255, 225, 80)
GREEN = (90, 255, 140)
PURPLE = (170, 100, 255)
RED = (255, 70, 80)
WHITE = (255, 255, 255)
BLUE = (80, 140, 255)

PLAYER_SPEED = 310.0
DASH_SPEED = 980.0
DASH_TIME = 0.17
DASH_CD = 1.1
BULLET_SPEED = 1000.0

WEAPONS = {
    1: [(0, 0)],
    2: [(0, -8), (0, 8)],
    3: [(-0.13, 0), (0, 0), (0.13, 0)],
    4: [(-0.24, 0), (-0.12, 0), (0, 0), (0.12, 0), (0.24, 0)],
    5: [(-0.24, 0), (-0.12, 0), (0, 0), (0.12, 0), (0.24, 0), (0, -16), (0, 16)],
}
FIRE_INT = [0.17, 0.17, 0.15, 0.15, 0.13]

KINDS = {
    "drone":    dict(hp=2,  r=16, speed=125, color=RED,    score=100,  sides=3),
    "swarm":    dict(hp=1,  r=9,  speed=215, color=ORANGE, score=40,   sides=3),
    "mini":     dict(hp=2,  r=11, speed=170, color=GREEN,  score=50,   sides=4),
    "shooter":  dict(hp=5,  r=18, speed=110, color=CYAN,   score=250,  sides=4),
    "splitter": dict(hp=6,  r=23, speed=95,  color=GREEN,  score=200,  sides=4),
    "tank":     dict(hp=16, r=30, speed=70,  color=PURPLE, score=500,  sides=6),
    "boss":     dict(hp=1,  r=64, speed=0,   color=PINK,   score=5000, sides=8),
}


# ----------------------------------------------------------------- helpers
def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def lerp(a, b, t):
    return a + (b - a) * t


def sc(c, k):
    """Scale a colour toward black (k<1) or brighten (k>1), clamped."""
    return (min(255, max(0, int(c[0] * k))),
            min(255, max(0, int(c[1] * k))),
            min(255, max(0, int(c[2] * k))))


def mixc(a, b, t):
    t = clamp(t, 0.0, 1.0)
    return (int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t), int(a[2] + (b[2] - a[2]) * t))


def poly(x, y, r, sides, ang):
    return [(x + math.cos(ang + i * math.tau / sides) * r, y + math.sin(ang + i * math.tau / sides) * r)
            for i in range(sides)]


def star(x, y, r_out, r_in, ang, points=5):
    pts = []
    for i in range(points * 2):
        rr = r_out if i % 2 == 0 else r_in
        a = ang + i * math.pi / points
        pts.append((x + math.cos(a) * rr, y + math.sin(a) * rr))
    return pts


def rrect(surf, color, rect, radius, width=0):
    try:
        pygame.draw.rect(surf, color, rect, width, border_radius=radius)
    except TypeError:
        pygame.draw.rect(surf, color, rect, width)


def load_high():
    try:
        with open(HS_FILE) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return 0


def save_high(v):
    try:
        with open(HS_FILE, "w") as f:
            f.write(str(int(v)))
    except OSError:
        pass


# ------------------------------------------------------------- glow sprites
_GLOW = {}


def glow_sprite(color, radius, k):
    radius = max(4, int(radius / 4) * 4)
    key = (color, radius, int(k * 10))
    s = _GLOW.get(key)
    if s is None:
        s = pygame.Surface((radius * 2, radius * 2))
        s.fill((0, 0, 0))
        steps = max(6, radius // 2)
        for i in range(steps):
            rr = radius - i * radius / steps
            t = (i + 1) / steps
            b = (t ** 2.2) * (int(k * 10) / 10.0)
            col = (int(color[0] * b), int(color[1] * b), int(color[2] * b))
            pygame.draw.circle(s, col, (radius, radius), int(rr))
        _GLOW[key] = s
    return s


def draw_glow(surf, x, y, color, radius, k=1.0):
    if k <= 0.05:
        return
    spr = glow_sprite(color, radius, min(k, 1.0))
    r = spr.get_width() // 2
    surf.blit(spr, (int(x) - r, int(y) - r), special_flags=pygame.BLEND_RGB_ADD)


# ------------------------------------------------------------------- sound
class Sfx:
    """Tiny synthesiser. Silently disables itself if audio isn't available."""

    def __init__(self):
        self.ok = False
        self.sounds = {}
        self.last = {}
        try:
            init = pygame.mixer.get_init()
            if not init:
                return
            self.sr, fmt, self.ch = init
            if fmt != -16:
                return
            pygame.mixer.set_num_channels(24)
            self.add("shoot", 1100, 380, 0.07, 0.22, 0.10, 1.5)
            self.add("eshoot", 700, 250, 0.08, 0.16, 0.20, 1.5)
            self.add("hit", 320, 120, 0.05, 0.22, 0.70, 1.0)
            self.add("boom", 170, 40, 0.45, 0.55, 0.85, 1.6)
            self.add("bigboom", 110, 30, 1.0, 0.65, 0.90, 1.3)
            self.add("pickup", 520, 1250, 0.16, 0.30, 0.0, 1.0, sine=True)
            self.add("hurt", 230, 60, 0.28, 0.50, 0.60, 1.3)
            self.add("dash", 300, 950, 0.14, 0.22, 0.60, 1.4)
            self.add("bomb", 95, 30, 0.85, 0.65, 0.80, 1.2)
            self.add("wave", 380, 820, 0.35, 0.28, 0.0, 1.2, sine=True)
            self.ok = True
        except Exception:
            self.ok = False

    def add(self, name, f0, f1, dur, vol, noise, decay, sine=False):
        n = int(self.sr * dur)
        rnd = random.Random(7)
        data = array.array("h")
        phase = 0.0
        lp = 0.0
        for i in range(n):
            t = i / n
            phase += (f0 + (f1 - f0) * t) / self.sr
            s = math.sin(phase * math.tau) if sine else (1.0 if (phase % 1.0) < 0.5 else -1.0)
            lp += (rnd.uniform(-1, 1) - lp) * 0.3
            v = (s * (1 - noise) + lp * noise * 1.8) * vol * (1 - t) ** decay
            data.append(int(clamp(v, -1, 1) * 30000))
        if self.ch == 2:
            st = array.array("h")
            for v in data:
                st.append(v)
                st.append(v)
            data = st
        self.sounds[name] = pygame.mixer.Sound(buffer=data.tobytes())

    def play(self, name, min_gap=30):
        if not self.ok:
            return
        now = pygame.time.get_ticks()
        if now - self.last.get(name, -9999) < min_gap:
            return
        self.last[name] = now
        try:
            self.sounds[name].play()
        except Exception:
            pass


# ---------------------------------------------------------------- entities
class Player:
    def __init__(self):
        self.x, self.y = W / 2, H / 2
        self.vx = self.vy = 0.0
        self.r = 14
        self.angle = 0.0
        self.hp = self.max_hp = 100.0
        self.shield = 0.0
        self.iframes = 0.0
        self.fire_cd = 0.0
        self.weapon = 1
        self.rapid = 0.0
        self.bombs = 2
        self.dash_t = 0.0
        self.dash_cd = 0.0
        self.dash_dx, self.dash_dy = 1.0, 0.0
        self.alive = True
        self.thrust = 0.0


class Bullet:
    __slots__ = ("x", "y", "vx", "vy", "life", "dmg", "pierce", "color", "hit")

    def __init__(self, x, y, vx, vy, dmg, pierce, color):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.life = 1.3
        self.dmg = dmg
        self.pierce = pierce
        self.color = color
        self.hit = set()


class EBullet:
    __slots__ = ("x", "y", "vx", "vy", "life", "r", "color")

    def __init__(self, x, y, vx, vy, r=6, color=PINK):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.life = 7.0
        self.r = r
        self.color = color


class Particle:
    __slots__ = ("x", "y", "vx", "vy", "life", "max", "color", "size", "kind", "drag", "rot", "vrot")

    def __init__(self, x, y, vx, vy, life, color, size, kind, drag=0.0, rot=0.0, vrot=0.0):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.life = self.max = life
        self.color = color
        self.size = size
        self.kind = kind
        self.drag = drag
        self.rot = rot
        self.vrot = vrot


class Enemy:
    def __init__(self, kind, x, y, wave, eid):
        d = KINDS[kind]
        self.kind = kind
        self.id = eid
        self.x, self.y = x, y
        self.vx = self.vy = 0.0
        self.hp = self.max_hp = float(d["hp"])
        self.r = d["r"]
        self.color = d["color"]
        self.score = d["score"]
        self.speed = d["speed"] * (1 + 0.025 * wave)
        self.sides = d["sides"]
        self.angle = random.uniform(0, math.tau)
        self.spin = random.choice((-1, 1)) * random.uniform(0.8, 1.8)
        self.flash = 0.0
        self.t = 0.0
        self.spawn_max = 1.8 if kind == "boss" else 0.9
        self.spawn = self.spawn_max
        self.cd = random.uniform(0.8, 2.0)
        self.cd2 = 1.0
        self.dir = random.choice((-1, 1))
        self.dir_t = random.uniform(1.0, 2.5)
        self.dead = False
        # boss state
        self.spin_a = 0.0
        self.cstate = "aim"
        self.ct = 0.9
        self.cdx, self.cdy = 1.0, 0.0


class Pickup:
    def __init__(self, kind, x, y):
        self.kind = kind
        self.x, self.y = x, y
        self.t = random.uniform(0, 6)
        self.life = 14.0
        a = random.uniform(0, math.tau)
        self.vx, self.vy = math.cos(a) * 60, math.sin(a) * 60


class Shockwave:
    def __init__(self, x, y):
        self.x, self.y = x, y
        self.r = 0.0
        self.max_r = 820.0
        self.speed = 1150.0
        self.hit = set()

    @property
    def done(self):
        return self.r >= self.max_r


PICK_COLORS = {"hp": GREEN, "weapon": YELLOW, "shield": BLUE, "bomb": PINK, "rapid": ORANGE}


# -------------------------------------------------------------------- game
class Game:
    def __init__(self):
        try:
            pygame.mixer.pre_init(44100, -16, 1, 512)
        except Exception:
            pass
        pygame.init()
        pygame.display.set_caption("NEON SIEGE")
        try:
            self.screen = pygame.display.set_mode((W, H), pygame.SCALED | pygame.RESIZABLE)
        except Exception:
            self.screen = pygame.display.set_mode((W, H))
        pygame.mouse.set_visible(False)
        self.clock = pygame.time.Clock()
        self.canvas = pygame.Surface((W, H)).convert()
        self.bloom_a = pygame.Surface((W, H), 0, self.canvas)
        self.bloom_b = pygame.Surface((W, H), 0, self.canvas)
        self.bloom = True
        self.bg = self.make_background()
        self.vig_dark = self.make_vignette((0, 0, 8), 210)
        self.vig_red = self.make_vignette((255, 30, 40), 200)
        self.flash_surf = pygame.Surface((W, H), pygame.SRCALPHA)

        names = "bahnschrift,segoeui,consolas,arial"
        self.f_small = pygame.font.SysFont(names, 17, bold=True)
        self.f_med = pygame.font.SysFont(names, 26, bold=True)
        self.f_big = pygame.font.SysFont(names, 46, bold=True)
        self.f_huge = pygame.font.SysFont(names, 104, bold=True)

        self.sfx = Sfx()
        self.high = load_high()
        rng = random.Random(5)
        self.stars = [[rng.uniform(0, W), rng.uniform(0, H), rng.uniform(0.2, 1.0), rng.uniform(0, 6.28)]
                      for _ in range(160)]
        self.t = 0.0
        self.state = "menu"      # menu | play | paused | over
        self.menu_enemies = []
        for k in ("drone", "tank", "shooter", "splitter", "swarm", "mini", "drone", "tank"):
            e = Enemy(k, rng.uniform(100, W - 100), rng.uniform(100, H - 100), 0, 0)
            e.spawn = 0
            a = rng.uniform(0, 6.28)
            e.vx, e.vy = math.cos(a) * 50, math.sin(a) * 50
            self.menu_enemies.append(e)
        self.reset()

    # ----------------------------------------------------------- building
    @staticmethod
    def make_background():
        s = pygame.Surface((W, H))
        for y in range(H):
            t = y / H
            pygame.draw.line(s, (int(12 - 7 * t), int(14 - 8 * t), int(32 - 18 * t)), (0, y), (W, y))
        for x in range(M, W - M + 1, 64):
            major = ((x - M) // 64) % 4 == 0
            pygame.draw.line(s, (30, 44, 96) if major else (18, 26, 58), (x, AY0), (x, AY1))
        for y in range(M, H - M + 1, 64):
            major = ((y - M) // 64) % 4 == 0
            pygame.draw.line(s, (30, 44, 96) if major else (18, 26, 58), (AX0, y), (AX1, y))
        for x in range(M, W - M + 1, 256):
            for y in range(M, H - M + 1, 256):
                pygame.draw.circle(s, (50, 80, 150), (x, y), 3)
        return s

    @staticmethod
    def make_vignette(color, strength):
        s = pygame.Surface((W, H), pygame.SRCALPHA)
        steps = 28
        for i in range(steps):
            a = int(strength * (1 - i / steps) ** 2.4)
            rect = (i * 12, i * 12, W - 2 * i * 12, H - 2 * i * 12)
            rrect(s, (color[0], color[1], color[2], a), rect, 50 + i * 6, 12)
        return s

    # -------------------------------------------------------------- state
    def reset(self):
        self.player = Player()
        self.enemies, self.bullets, self.ebullets = [], [], []
        self.pickups, self.particles, self.texts = [], [], []
        self.shocks, self.booms = [], []
        self.score = 0
        self.disp_score = 0.0
        self.combo = 0
        self.combo_t = 0.0
        self.mult = 1
        self.wave = 0
        self.queue = []
        self.spawn_t = 0.0
        self.wave_state = "clear"
        self.wave_delay = 1.6
        self.banner = None
        self.shake = 0.0
        self.flash = 0.0
        self.flash_col = WHITE
        self.hurt_flash = 0.0
        self.slow_t = 0.0
        self.time_scale = 1.0
        self.kills = 0
        self.time_alive = 0.0
        self.next_id = 1
        self.over_t = 0.0
        self.new_high = False
        self.firing_pulse = 0.0
        self.boss = None

    def start_game(self):
        self.reset()
        self.state = "play"
        self.banner = ["GET READY", "survive the siege", 0.0, 2.0]

    # ------------------------------------------------------------- input
    def handle_event(self, e):
        if e.type == pygame.QUIT:
            self.quit()
        elif e.type == pygame.KEYDOWN:
            k = e.key
            if k in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if self.state in ("menu", "over"):
                    self.start_game()
            elif k in (pygame.K_p, pygame.K_ESCAPE):
                if self.state == "play":
                    self.state = "paused"
                elif self.state == "paused":
                    self.state = "play"
                elif k == pygame.K_ESCAPE:
                    self.quit()
            elif k == pygame.K_SPACE:
                if self.state == "play":
                    self.use_bomb()
            elif k in (pygame.K_LSHIFT, pygame.K_RSHIFT):
                if self.state == "play":
                    self.try_dash()
            elif k == pygame.K_g:
                self.bloom = not self.bloom
            elif k == pygame.K_F11:
                try:
                    pygame.display.toggle_fullscreen()
                except Exception:
                    pass
        elif e.type == pygame.MOUSEBUTTONDOWN:
            if e.button == 3 and self.state == "play":
                self.try_dash()
            elif e.button == 1 and self.state in ("menu", "over"):
                self.start_game()

    @staticmethod
    def quit():
        pygame.quit()
        sys.exit()

    def move_dir(self):
        k = pygame.key.get_pressed()
        dx = (1 if (k[pygame.K_d] or k[pygame.K_RIGHT]) else 0) - (1 if (k[pygame.K_a] or k[pygame.K_LEFT]) else 0)
        dy = (1 if (k[pygame.K_s] or k[pygame.K_DOWN]) else 0) - (1 if (k[pygame.K_w] or k[pygame.K_UP]) else 0)
        l = math.hypot(dx, dy)
        if l:
            return dx / l, dy / l
        return 0.0, 0.0

    def try_dash(self):
        p = self.player
        if not p.alive or p.dash_cd > 0 or p.dash_t > 0:
            return
        dx, dy = self.move_dir()
        if dx == 0 and dy == 0:
            dx, dy = math.cos(p.angle), math.sin(p.angle)
        p.dash_dx, p.dash_dy = dx, dy
        p.dash_t = DASH_TIME
        p.dash_cd = DASH_CD
        p.iframes = max(p.iframes, DASH_TIME + 0.12)
        self.sfx.play("dash")
        self.add_ring(p.x, p.y, CYAN, 8, 0.3, 240)

    def use_bomb(self):
        p = self.player
        if not p.alive or p.bombs <= 0:
            return
        p.bombs -= 1
        self.shocks.append(Shockwave(p.x, p.y))
        self.flash, self.flash_col = 0.55, (200, 230, 255)
        self.shake = max(self.shake, 16)
        self.add_ring(p.x, p.y, WHITE, 10, 0.5, 900)
        self.add_ring(p.x, p.y, PINK, 10, 0.7, 1150)
        self.sfx.play("bomb", 100)

    # ---------------------------------------------------------- particles
    def add_particle(self, *args, **kw):
        if len(self.particles) < MAX_PART:
            self.particles.append(Particle(*args, **kw))

    def add_ring(self, x, y, color, r0, life, growth):
        self.particles.append(Particle(x, y, growth, 0, life, color, r0, "ring"))

    def add_spark_burst(self, x, y, color, n, speed, life=0.5, size=2.5):
        for _ in range(n):
            a = random.uniform(0, math.tau)
            s = random.uniform(speed * 0.3, speed)
            c = color if random.random() < 0.7 else WHITE
            self.add_particle(x, y, math.cos(a) * s, math.sin(a) * s, random.uniform(life * 0.5, life),
                              c, size, "spark", 2.2)

    def explode(self, x, y, color, size=1.0, shape=None):
        n = int(14 * size) + 10
        self.add_spark_burst(x, y, color, n, 260 + 140 * size, 0.7, 3)
        self.add_spark_burst(x, y, YELLOW, n // 3, 200 + 80 * size, 0.5, 2)
        self.add_ring(x, y, color, 6, 0.45, 280 * size)
        self.add_ring(x, y, WHITE, 4, 0.28, 440 * size)
        self.add_particle(x, y, 0, 0, 0.28, color, 60 + 55 * size, "glow")
        self.add_particle(x, y, 0, 0, 0.14, WHITE, 40 + 30 * size, "glow")
        for _ in range(int(4 * size) + 2):
            a = random.uniform(0, math.tau)
            s = random.uniform(20, 120)
            self.add_particle(x, y, math.cos(a) * s, math.sin(a) * s, random.uniform(0.6, 1.3),
                              ORANGE, random.uniform(2, 4), "ember", 1.2)
        if shape:
            for i in range(len(shape)):
                x1, y1 = shape[i]
                x2, y2 = shape[(i + 1) % len(shape)]
                mx, my = (x1 + x2) / 2, (y1 + y2) / 2
                a = math.atan2(my - y, mx - x)
                s = random.uniform(60, 200)
                self.add_particle(mx, my, math.cos(a) * s, math.sin(a) * s, random.uniform(0.5, 1.0), color,
                                  math.hypot(x2 - x1, y2 - y1), "shard", 1.5,
                                  math.atan2(y2 - y1, x2 - x1), random.uniform(-6, 6))
        self.shake = min(26, self.shake + 5 * size ** 0.7)

    def float_text(self, x, y, text, color=WHITE, big=False):
        self.texts.append([x, y, text, color, 1.0, 1.0, big])

    # -------------------------------------------------------------- waves
    def start_wave(self, n):
        self.wave = n
        self.wave_state = "fight"
        self.queue = []
        boss_wave = n % 5 == 0
        if boss_wave:
            self.queue.append("boss")
            budget = 4 + n
        else:
            budget = 6 + n * 4 if n > 1 else 8
        options = [("drone", 2, 3)]
        if n >= 2:
            options.append(("swarm", 6, 2))
        if n >= 3:
            options.append(("shooter", 4, 2))
        if n >= 4:
            options.append(("splitter", 5, 2))
        if n >= 6:
            options.append(("tank", 9, 1))
        pool = []
        while budget >= 2:
            cand = [o for o in options if o[1] <= budget]
            if not cand:
                break
            o = random.choices(cand, weights=[c[2] for c in cand])[0]
            pool.append(o[0])
            budget -= o[1]
        random.shuffle(pool)
        self.queue += pool
        self.spawn_t = 0.6
        if boss_wave:
            self.banner = ["WARNING", f"BOSS  -  WAVE {n}", 0.0, 2.6]
        else:
            self.banner = [f"WAVE {n}", "", 0.0, 1.8]
        self.sfx.play("wave", 200)

    def find_spawn_point(self, margin=70, min_dist=380):
        p = self.player
        x, y = W / 2, H / 2
        for _ in range(30):
            x = random.uniform(AX0 + margin, AX1 - margin)
            y = random.uniform(AY0 + margin, AY1 - margin)
            if math.hypot(x - p.x, y - p.y) >= min_dist:
                break
        return x, y

    def spawn_enemy(self, kind, x, y, instant=False):
        e = Enemy(kind, x, y, self.wave, self.next_id)
        self.next_id += 1
        if instant:
            e.spawn = 0.15
            e.spawn_max = 0.15
        if kind == "boss":
            lvl = max(1, self.wave // 5)
            e.hp = e.max_hp = 150.0 + 80.0 * (lvl - 1)
            self.boss = e
        self.enemies.append(e)
        return e

    def update_waves(self, dt):
        if self.wave_state == "fight":
            self.spawn_t -= dt
            cap = 10 + int(self.wave * 1.5)
            if self.queue and self.spawn_t <= 0 and len(self.enemies) < cap:
                kind = self.queue.pop(0)
                if kind == "boss":
                    self.spawn_enemy("boss", W / 2, H / 2 - 80)
                elif kind == "swarm":
                    cx, cy = self.find_spawn_point()
                    for i in range(7):
                        a = i * math.tau / 7
                        self.spawn_enemy("swarm", clamp(cx + math.cos(a) * 46, AX0 + 20, AX1 - 20),
                                         clamp(cy + math.sin(a) * 46, AY0 + 20, AY1 - 20))
                else:
                    x, y = self.find_spawn_point()
                    self.spawn_enemy(kind, x, y)
                self.spawn_t = max(0.12, random.uniform(0.25, 0.8) - 0.02 * self.wave)
            if not self.queue and not self.enemies:
                self.wave_state = "clear"
                self.wave_delay = 2.8
                bonus = self.wave * 250
                self.score += bonus
                self.player.hp = min(self.player.max_hp, self.player.hp + 10)
                self.banner = ["WAVE CLEARED", f"+{bonus}", 0.0, 2.2]
                self.drop_pickup(W / 2, H / 2, force=True)
                self.sfx.play("wave", 200)
        else:
            self.wave_delay -= dt
            if self.wave_delay <= 0:
                self.start_wave(self.wave + 1)

    # ------------------------------------------------------------- combat
    def add_score(self, base, x, y):
        self.combo += 1
        self.combo_t = 3.2
        self.mult = min(10, 1 + self.combo // 4)
        pts = base * self.mult
        self.score += pts
        self.float_text(x, y - 18, f"+{pts}", YELLOW if self.mult > 1 else WHITE)

    def drop_pickup(self, x, y, force=False, chance=0.0):
        if not force and random.random() > chance:
            return
        kind = random.choices(["hp", "weapon", "shield", "bomb", "rapid"], weights=[28, 22, 20, 12, 18])[0]
        if force and self.player.weapon < 5 and random.random() < 0.5:
            kind = "weapon"
        self.pickups.append(Pickup(kind, x, y))

    def damage_enemy(self, e, dmg, sparks=True):
        if e.dead or e.spawn > 0:
            return
        e.hp -= dmg
        e.flash = 0.08
        if sparks:
            self.add_spark_burst(e.x, e.y, e.color, 4, 240, 0.3, 2)
        if e.hp <= 0:
            self.kill_enemy(e)
        else:
            self.sfx.play("hit", 45)

    def kill_enemy(self, e):
        if e.dead:
            return
        e.dead = True
        e.hp = 0
        self.kills += 1
        big = e.kind in ("tank", "splitter", "boss")
        if e.kind == "boss":
            self.boss = None
            self.ebullets = []
            for i in range(16):
                ox, oy = random.uniform(-e.r, e.r), random.uniform(-e.r, e.r)
                self.booms.append([i * 0.09, e.x + ox, e.y + oy, random.uniform(0.8, 1.6)])
            self.booms.append([1.5, e.x, e.y, 4.5])
            self.slow_t = 1.7
            self.add_score(e.score, e.x, e.y)
            for _ in range(3):
                self.pickups.append(Pickup(random.choice(["hp", "weapon", "shield", "bomb"]), e.x, e.y))
            self.sfx.play("bigboom", 50)
            return
        shape = poly(e.x, e.y, e.r, e.sides, e.angle)
        self.explode(e.x, e.y, e.color, e.r / 16.0, shape)
        self.add_score(e.score, e.x, e.y)
        self.sfx.play("bigboom" if big else "boom", 40)
        if e.kind == "splitter":
            for i in range(2):
                a = random.uniform(0, math.tau)
                m = self.spawn_enemy("mini", e.x + math.cos(a) * 16, e.y + math.sin(a) * 16, instant=True)
                m.vx, m.vy = math.cos(a) * 260, math.sin(a) * 260
        chance = {"drone": 0.05, "swarm": 0.02, "mini": 0.02, "shooter": 0.14, "splitter": 0.12, "tank": 0.45}
        self.drop_pickup(e.x, e.y, chance=chance.get(e.kind, 0.05))
        if big:
            self.time_scale_hit(0.08)

    def time_scale_hit(self, secs):
        self.slow_t = max(self.slow_t, secs)

    def hurt_player(self, amount, sx, sy, knock=0.0):
        p = self.player
        if not p.alive or p.iframes > 0:
            return
        p.iframes = 0.9
        self.combo = 0
        self.mult = 1
        self.shake = min(28, self.shake + 12)
        self.hurt_flash = 1.0
        self.time_scale_hit(0.07)
        self.sfx.play("hurt", 80)
        if p.shield > 0:
            absorbed = min(p.shield, amount)
            p.shield -= absorbed
            amount -= absorbed
            self.add_ring(p.x, p.y, BLUE, 16, 0.3, 200)
        p.hp -= amount
        self.add_spark_burst(p.x, p.y, CYAN, 12, 300, 0.5, 3)
        if knock:
            a = math.atan2(p.y - sy, p.x - sx)
            p.vx += math.cos(a) * knock
            p.vy += math.sin(a) * knock
        if p.hp <= 0:
            self.kill_player()

    def kill_player(self):
        p = self.player
        p.alive = False
        p.hp = 0
        self.explode(p.x, p.y, CYAN, 2.6)
        self.booms.append([0.25, p.x, p.y, 1.8])
        self.flash, self.flash_col = 0.7, (255, 255, 255)
        self.slow_t = 1.3
        self.sfx.play("bigboom", 50)
        self.over_t = 0.0
        if self.score > self.high:
            self.high = self.score
            self.new_high = True
            save_high(self.high)

    def apply_pickup(self, pk):
        p = self.player
        self.sfx.play("pickup", 40)
        col = PICK_COLORS[pk.kind]
        self.add_ring(pk.x, pk.y, col, 8, 0.4, 260)
        self.add_spark_burst(pk.x, pk.y, col, 14, 260, 0.5, 2)
        if pk.kind == "hp":
            p.hp = min(p.max_hp, p.hp + 30)
            self.float_text(pk.x, pk.y, "REPAIR", col, True)
        elif pk.kind == "weapon":
            if p.weapon < 5:
                p.weapon += 1
                self.float_text(pk.x, pk.y, f"WEAPON LV {p.weapon}", col, True)
            else:
                self.score += 500
                self.float_text(pk.x, pk.y, "+500", col, True)
        elif pk.kind == "shield":
            p.shield = min(60.0, p.shield + 40.0)
            self.float_text(pk.x, pk.y, "SHIELD", col, True)
        elif pk.kind == "bomb":
            p.bombs = min(5, p.bombs + 1)
            self.float_text(pk.x, pk.y, "+1 BOMB", col, True)
        elif pk.kind == "rapid":
            p.rapid = 10.0
            self.float_text(pk.x, pk.y, "RAPID FIRE", col, True)

    def enemy_fire(self, x, y, ang, speed, r=6, color=PINK):
        self.ebullets.append(EBullet(x, y, math.cos(ang) * speed, math.sin(ang) * speed, r, color))

    def player_fire(self):
        p = self.player
        lvl = p.weapon
        ca, sa = math.cos(p.angle), math.sin(p.angle)
        mx, my = p.x + ca * 22, p.y + sa * 22
        dmg = 1.0 if lvl < 5 else 1.3
        pierce = 0 if lvl < 5 else 1
        color = CYAN if lvl < 5 else (255, 230, 120)
        for ao, lat in WEAPONS[lvl]:
            a = p.angle + ao + random.uniform(-0.012, 0.012)
            self.bullets.append(Bullet(mx - sa * lat, my + ca * lat, math.cos(a) * BULLET_SPEED,
                                       math.sin(a) * BULLET_SPEED, dmg, pierce, color))
        self.add_particle(mx, my, 0, 0, 0.07, color, 34, "glow")
        self.add_spark_burst(mx, my, color, 2, 160, 0.15, 2)
        p.fire_cd = FIRE_INT[lvl - 1] * (0.6 if p.rapid > 0 else 1.0)
        self.firing_pulse = 1.0
        self.sfx.play("shoot", 55)

    # ------------------------------------------------------------- update
    def update(self, dt):
        self.t += dt
        if self.state == "paused":
            return
        for s in self.stars:
            s[1] += s[2] * 14 * dt
            if s[1] > H:
                s[1] -= H
        if self.state == "menu":
            for e in self.menu_enemies:
                e.t += dt
                e.angle += e.spin * dt * 0.5
                e.x += e.vx * dt
                e.y += e.vy * dt
                if e.x < AX0 + 40 or e.x > AX1 - 40:
                    e.vx = -e.vx
                if e.y < AY0 + 40 or e.y > AY1 - 40:
                    e.vy = -e.vy
            return

        ts = 0.35 if self.slow_t > 0 else 1.0
        if self.slow_t > 0:
            self.slow_t -= dt
        sdt = dt * ts
        self.update_world(sdt, dt)
        if self.state == "play" and not self.player.alive:
            self.over_t += dt
            if self.over_t > 2.4:
                self.state = "over"

    def update_world(self, dt, real_dt):
        p = self.player
        self.time_alive += dt if p.alive else 0
        self.disp_score += (self.score - self.disp_score) * min(1.0, 8 * real_dt)
        if abs(self.score - self.disp_score) < 1:
            self.disp_score = self.score
        self.shake = max(0.0, self.shake - 38 * real_dt)
        self.flash = max(0.0, self.flash - 2.2 * real_dt)
        self.hurt_flash = max(0.0, self.hurt_flash - 1.8 * real_dt)
        self.firing_pulse = max(0.0, self.firing_pulse - 6 * real_dt)
        if self.banner:
            self.banner[2] += real_dt
            if self.banner[2] >= self.banner[3]:
                self.banner = None
        if self.combo_t > 0:
            self.combo_t -= dt
            if self.combo_t <= 0:
                self.combo = 0
                self.mult = 1

        if p.alive:
            self.update_player(dt)
            self.update_waves(dt)

        # delayed explosions
        for b in self.booms[:]:
            b[0] -= dt
            if b[0] <= 0:
                self.booms.remove(b)
                self.explode(b[1], b[2], random.choice((PINK, ORANGE, YELLOW, WHITE)), b[3])
                self.sfx.play("boom", 30)
                if b[3] >= 4:
                    self.flash, self.flash_col = 0.9, (255, 255, 255)
                    self.shake = 30

        # enemies
        for e in self.enemies:
            self.update_enemy(e, dt)
        self.enemies = [e for e in self.enemies if not e.dead]

        # player bullets
        for b in self.bullets:
            b.x += b.vx * dt
            b.y += b.vy * dt
            b.life -= dt
            if b.x < AX0 or b.x > AX1 or b.y < AY0 or b.y > AY1 or b.life <= 0:
                if b.life > 0:
                    self.add_spark_burst(clamp(b.x, AX0, AX1), clamp(b.y, AY0, AY1), b.color, 3, 140, 0.2, 2)
                b.life = 0
                continue
            for e in self.enemies:
                if e.dead or e.spawn > 0 or e.id in b.hit:
                    continue
                if math.hypot(e.x - b.x, e.y - b.y) < e.r + 4:
                    b.hit.add(e.id)
                    self.damage_enemy(e, b.dmg)
                    if b.pierce > 0:
                        b.pierce -= 1
                    else:
                        b.life = 0
                        break
        self.bullets = [b for b in self.bullets if b.life > 0]
        self.enemies = [e for e in self.enemies if not e.dead]

        # enemy bullets
        for b in self.ebullets:
            b.x += b.vx * dt
            b.y += b.vy * dt
            b.life -= dt
            if b.x < AX0 - 20 or b.x > AX1 + 20 or b.y < AY0 - 20 or b.y > AY1 + 20:
                b.life = 0
            elif p.alive and math.hypot(p.x - b.x, p.y - b.y) < p.r + b.r - 1:
                if p.iframes <= 0:
                    self.hurt_player(10, b.x, b.y, 120)
                    b.life = 0
        self.ebullets = [b for b in self.ebullets if b.life > 0]

        # contact damage
        if p.alive:
            for e in self.enemies:
                if e.dead or e.spawn > 0:
                    continue
                if math.hypot(p.x - e.x, p.y - e.y) < p.r + e.r * 0.85:
                    if p.iframes <= 0:
                        if e.kind in ("drone", "swarm", "mini"):
                            self.hurt_player(12, e.x, e.y, 200)
                            self.kill_enemy(e)
                        else:
                            self.hurt_player(20, e.x, e.y, 420)

        # shockwaves (bomb)
        for sw in self.shocks:
            sw.r += sw.speed * dt
            for e in self.enemies:
                if e.dead or e.id in sw.hit or e.spawn > 0:
                    continue
                if math.hypot(e.x - sw.x, e.y - sw.y) < sw.r + e.r:
                    sw.hit.add(e.id)
                    self.damage_enemy(e, 30 if e.kind != "boss" else 18, sparks=False)
                    self.add_spark_burst(e.x, e.y, WHITE, 8, 300, 0.4, 2)
            for b in self.ebullets:
                if math.hypot(b.x - sw.x, b.y - sw.y) < sw.r + 10:
                    b.life = 0
                    self.add_spark_burst(b.x, b.y, b.color, 4, 160, 0.3, 2)
        self.shocks = [s for s in self.shocks if not s.done]
        self.enemies = [e for e in self.enemies if not e.dead]

        # pickups
        for pk in self.pickups:
            pk.t += dt
            pk.life -= dt
            if p.alive:
                dx, dy = p.x - pk.x, p.y - pk.y
                d = math.hypot(dx, dy) or 1
                if d < 190:
                    pull = (1 - d / 190) * 1400 + 200
                    pk.vx += dx / d * pull * dt
                    pk.vy += dy / d * pull * dt
                if d < 30:
                    self.apply_pickup(pk)
                    pk.life = 0
            k = max(0.0, 1 - 1.8 * dt)
            pk.vx *= k
            pk.vy *= k
            pk.x = clamp(pk.x + pk.vx * dt, AX0 + 12, AX1 - 12)
            pk.y = clamp(pk.y + pk.vy * dt, AY0 + 12, AY1 - 12)
        self.pickups = [pk for pk in self.pickups if pk.life > 0]

        # particles
        for q in self.particles:
            q.life -= dt
            if q.kind not in ("ring", "glow"):
                if q.drag:
                    k = max(0.0, 1 - q.drag * dt)
                    q.vx *= k
                    q.vy *= k
                q.x += q.vx * dt
                q.y += q.vy * dt
                q.rot += q.vrot * dt
        self.particles = [q for q in self.particles if q.life > 0]
        for tx in self.texts:
            tx[1] -= 38 * dt
            tx[4] -= dt
        self.texts = [tx for tx in self.texts if tx[4] > 0]

    def update_player(self, dt):
        p = self.player
        mx, my = pygame.mouse.get_pos()
        p.angle = math.atan2(my - p.y, mx - p.x)
        dx, dy = self.move_dir()
        if p.iframes > 0:
            p.iframes -= dt
        if p.dash_cd > 0:
            p.dash_cd -= dt
        if p.rapid > 0:
            p.rapid -= dt
        if p.fire_cd > 0:
            p.fire_cd -= dt
        if p.dash_t > 0:
            p.dash_t -= dt
            p.vx, p.vy = p.dash_dx * DASH_SPEED, p.dash_dy * DASH_SPEED
            self.add_particle(p.x, p.y, 0, 0, 0.3, CYAN, 34, "glow")
        else:
            k = min(1.0, 14 * dt)
            p.vx += (dx * PLAYER_SPEED - p.vx) * k
            p.vy += (dy * PLAYER_SPEED - p.vy) * k
        p.x = clamp(p.x + p.vx * dt, AX0 + p.r, AX1 - p.r)
        p.y = clamp(p.y + p.vy * dt, AY0 + p.r, AY1 - p.r)
        moving = dx != 0 or dy != 0 or p.dash_t > 0
        p.thrust += ((1.0 if moving else 0.0) - p.thrust) * min(1.0, 10 * dt)
        if moving and random.random() < 0.7:
            ca, sa = math.cos(p.angle), math.sin(p.angle)
            ex, ey = p.x - ca * 14, p.y - sa * 14
            self.add_particle(ex, ey, -p.vx * 0.1 + random.uniform(-30, 30), -p.vy * 0.1 + random.uniform(-30, 30),
                              random.uniform(0.25, 0.45), (80, 170, 255), random.uniform(2, 4), "ember", 3.0)
        buttons = pygame.mouse.get_pressed()
        if buttons[0] and p.fire_cd <= 0 and p.dash_t <= 0:
            self.player_fire()

    def update_enemy(self, e, dt):
        p = self.player
        e.t += dt
        if e.flash > 0:
            e.flash -= dt
        if e.spawn > 0:
            e.spawn -= dt
            return
        dx, dy = p.x - e.x, p.y - e.y
        d = math.hypot(dx, dy) or 1.0
        ux, uy = dx / d, dy / d
        k = e.kind

        if k in ("drone", "mini", "swarm", "splitter"):
            if k == "swarm":
                off = math.sin(e.t * 7 + e.id) * 0.7
                ux, uy = ux * math.cos(off) - uy * math.sin(off), ux * math.sin(off) + uy * math.cos(off)
            steer = 6.0 if k == "swarm" else 3.5
            s = min(1.0, steer * dt)
            e.vx += (ux * e.speed - e.vx) * s
            e.vy += (uy * e.speed - e.vy) * s
            if k in ("drone", "swarm"):
                e.angle = math.atan2(e.vy, e.vx)
            else:
                e.angle += e.spin * dt
        elif k == "shooter":
            e.dir_t -= dt
            if e.dir_t <= 0:
                e.dir = -e.dir
                e.dir_t = random.uniform(1.2, 2.6)
            if d > 400:
                mx, my = ux, uy
            elif d < 290:
                mx, my = -ux, -uy
            else:
                mx, my = -uy * e.dir, ux * e.dir
            s = min(1.0, 3.0 * dt)
            e.vx += (mx * e.speed - e.vx) * s
            e.vy += (my * e.speed - e.vy) * s
            e.angle += e.spin * dt
            e.cd -= dt
            if e.cd <= 0:
                e.cd = 1.9
                self.enemy_fire(e.x, e.y, math.atan2(dy, dx), 340, 6, CYAN)
                self.sfx.play("eshoot", 60)
        elif k == "tank":
            if d > 320:
                mx, my = ux, uy
            else:
                mx, my = -uy * e.dir * 0.4, ux * e.dir * 0.4
            s = min(1.0, 2.0 * dt)
            e.vx += (mx * e.speed - e.vx) * s
            e.vy += (my * e.speed - e.vy) * s
            e.angle += e.spin * dt * 0.4
            e.cd -= dt
            if e.cd <= 0:
                e.cd = 2.6
                base = math.atan2(dy, dx)
                for off in (-0.28, 0, 0.28):
                    self.enemy_fire(e.x, e.y, base + off, 290, 8, PURPLE)
                self.sfx.play("eshoot", 60)
        elif k == "boss":
            self.update_boss(e, dt, ux, uy)

        # keep enemies from stacking
        if k != "boss":
            for o in self.enemies:
                if o is e or o.dead or o.spawn > 0 or o.kind == "boss":
                    continue
                ox, oy = e.x - o.x, e.y - o.y
                dist = math.hypot(ox, oy)
                rs = e.r + o.r
                if 0 < dist < rs:
                    push = (rs - dist) * 0.4
                    e.x += ox / dist * push
                    e.y += oy / dist * push

        e.x += e.vx * dt
        e.y += e.vy * dt
        if e.x < AX0 + e.r:
            e.x, e.vx = AX0 + e.r, abs(e.vx)
        elif e.x > AX1 - e.r:
            e.x, e.vx = AX1 - e.r, -abs(e.vx)
        if e.y < AY0 + e.r:
            e.y, e.vy = AY0 + e.r, abs(e.vy)
        elif e.y > AY1 - e.r:
            e.y, e.vy = AY1 - e.r, -abs(e.vy)

    def update_boss(self, e, dt, ux, uy):
        rage = 1.0 if e.hp / e.max_hp > 0.5 else 1.45
        e.angle += dt * 0.5
        pattern = int(e.t // 6) % 3
        if pattern in (0, 1):
            tx = W / 2 + math.cos(e.t * 0.45) * 280
            ty = H / 2 - 70 + math.sin(e.t * 0.7) * 110
            e.x += (tx - e.x) * min(1.0, 1.4 * dt)
            e.y += (ty - e.y) * min(1.0, 1.4 * dt)
            e.vx = e.vy = 0.0
        if pattern == 0:
            e.cd -= dt
            if e.cd <= 0:
                e.cd = 0.085 / rage
                e.spin_a += 0.33
                for arm in (0, math.pi):
                    self.enemy_fire(e.x, e.y, e.spin_a + arm, 270, 7, PINK)
        elif pattern == 1:
            e.cd2 -= dt
            if e.cd2 <= 0:
                e.cd2 = 1.25 / rage
                n = 22
                off = random.uniform(0, math.tau)
                for i in range(n):
                    self.enemy_fire(e.x, e.y, off + i * math.tau / n, 235, 7, ORANGE)
                self.sfx.play("eshoot", 60)
        else:
            e.ct -= dt
            if e.cstate == "aim":
                n = math.hypot(ux, uy) or 1
                e.cdx, e.cdy = ux / n, uy / n
                e.vx = e.vy = 0.0
                if e.ct <= 0:
                    e.cstate, e.ct = "dash", 0.65
            elif e.cstate == "dash":
                e.vx, e.vy = e.cdx * 680 * rage, e.cdy * 680 * rage
                if e.ct <= 0:
                    e.cstate, e.ct = "rest", 0.9
                    e.vx = e.vy = 0.0
                    self.add_ring(e.x, e.y, PINK, 20, 0.5, 500)
                    self.shake = max(self.shake, 10)
                    if len(self.enemies) < 14:
                        for sgn in (-1, 1):
                            self.spawn_enemy("drone", clamp(e.x + sgn * 90, AX0 + 30, AX1 - 30), e.y, instant=True)
            else:
                e.vx = e.vy = 0.0
                if e.ct <= 0:
                    e.cstate, e.ct = "aim", 0.9

    # --------------------------------------------------------------- draw
    def draw_stars(self, s):
        px = (self.player.x - W / 2) * 0.05
        py = (self.player.y - H / 2) * 0.05
        for x, y, z, ph in self.stars:
            sx = (x - px * z) % W
            sy = (y - py * z) % H
            b = (0.45 + 0.55 * math.sin(self.t * (1 + z) + ph) ** 2) * z
            c = (int(120 * b + 40), int(150 * b + 40), int(255 * b))
            pygame.draw.circle(s, c, (int(sx), int(sy)), 1 if z < 0.6 else 2)

    def draw_arena(self, s):
        boss = self.boss is not None
        col = (190, 50, 100) if boss else (40, 120, 190)
        pulse = 0.7 + 0.3 * math.sin(self.t * 2.2)
        pygame.draw.rect(s, sc(col, pulse), ARENA, 3)
        br = (255, 120, 160) if boss else (120, 225, 255)
        L = 46
        for (cx, cy, sx_, sy_) in ((AX0, AY0, 1, 1), (AX1, AY0, -1, 1), (AX0, AY1, 1, -1), (AX1, AY1, -1, -1)):
            pygame.draw.line(s, br, (cx, cy), (cx + L * sx_, cy), 5)
            pygame.draw.line(s, br, (cx, cy), (cx, cy + L * sy_), 5)

    def draw_enemy(self, s, e):
        if e.spawn > 0:
            f = e.spawn / e.spawn_max
            r = e.r * (1.0 + 2.6 * f)
            col = sc(e.color, 1.0 - f * 0.4)
            pygame.draw.circle(s, col, (int(e.x), int(e.y)), max(2, int(r)), 2)
            pygame.draw.circle(s, sc(col, 0.6), (int(e.x), int(e.y)), max(2, int(r * 0.6)), 1)
            for i in range(4):
                a = self.t * 4 + i * math.pi / 2
                pygame.draw.line(s, col, (e.x + math.cos(a) * r * 0.7, e.y + math.sin(a) * r * 0.7),
                                 (e.x + math.cos(a) * r * 1.15, e.y + math.sin(a) * r * 1.15), 2)
            draw_glow(s, e.x, e.y, e.color, r * 1.6, 0.4 + 0.3 * (1 - f))
            return
        if e.kind == "boss":
            self.draw_boss(s, e)
            return
        col = e.color
        warn = e.kind in ("shooter", "tank") and e.cd < 0.35
        draw_glow(s, e.x, e.y, col, e.r * 2.7, 0.55 + (0.35 if warn else 0.0))
        ang = e.angle + (math.pi / 4 if e.sides == 4 else 0.0)
        r = e.r * (1.0 + 0.06 * math.sin(self.t * 8 + e.id)) if e.kind == "splitter" else e.r
        pts = poly(e.x, e.y, r, e.sides, ang)
        fill = WHITE if e.flash > 0 else sc(col, 0.24)
        pygame.draw.polygon(s, fill, pts)
        pygame.draw.polygon(s, col if e.flash <= 0 else WHITE, pts, 3)
        inner = poly(e.x, e.y, r * 0.52, e.sides, ang + (math.pi / e.sides))
        pygame.draw.polygon(s, sc(col, 0.75), inner, 1)
        if e.kind in ("shooter", "tank"):
            pygame.draw.circle(s, WHITE if warn else sc(col, 1.2), (int(e.x), int(e.y)), max(2, int(r * 0.18)))
        if e.max_hp >= 5 and e.hp < e.max_hp:
            w = e.r * 1.6
            pygame.draw.rect(s, (20, 20, 30), (e.x - w / 2, e.y - e.r - 12, w, 5))
            pygame.draw.rect(s, col, (e.x - w / 2, e.y - e.r - 12, w * max(0, e.hp) / e.max_hp, 5))

    def draw_boss(self, s, e):
        col = e.color
        hp_f = e.hp / e.max_hp
        rage = hp_f <= 0.5
        glow_col = RED if rage else col
        draw_glow(s, e.x, e.y, glow_col, e.r * 3.0, 0.7)
        if e.cstate == "aim" and int(e.t // 6) % 3 == 2:
            pygame.draw.line(s, (255, 120, 140), (e.x, e.y),
                             (e.x + e.cdx * 1400, e.y + e.cdy * 1400), 2)
            draw_glow(s, e.x + e.cdx * 90, e.y + e.cdy * 90, RED, 50, 0.6)
        outer = poly(e.x, e.y, e.r, 8, e.angle)
        pygame.draw.polygon(s, WHITE if e.flash > 0 else sc(col, 0.2), outer)
        pygame.draw.polygon(s, glow_col, outer, 4)
        mid = poly(e.x, e.y, e.r * 0.72, 6, -e.angle * 1.6)
        pygame.draw.polygon(s, sc(glow_col, 0.35), mid)
        pygame.draw.polygon(s, sc(glow_col, 1.1), mid, 3)
        for i in range(6):
            a = e.t * 1.3 + i * math.tau / 6
            nx, ny = e.x + math.cos(a) * e.r * 1.2, e.y + math.sin(a) * e.r * 1.2
            pygame.draw.circle(s, glow_col, (int(nx), int(ny)), 7)
            pygame.draw.circle(s, WHITE, (int(nx), int(ny)), 3)
            draw_glow(s, nx, ny, glow_col, 26, 0.6)
        pulse = 0.6 + 0.4 * math.sin(e.t * (9 if rage else 4))
        pygame.draw.circle(s, sc(WHITE, 0.6 + 0.4 * pulse), (int(e.x), int(e.y)), int(e.r * 0.26))
        draw_glow(s, e.x, e.y, WHITE, e.r * 0.9, 0.5 * pulse)

    def draw_player(self, s):
        p = self.player
        if not p.alive:
            return
        ca, sa = math.cos(p.angle), math.sin(p.angle)

        def T(lx, ly):
            return (p.x + lx * ca - ly * sa, p.y + lx * sa + ly * ca)

        fl = (8 + 26 * p.thrust) * (0.7 + 0.3 * random.random())
        pygame.draw.polygon(s, (255, 150, 60), [T(-10, -5), T(-10 - fl, 0), T(-10, 5)])
        pygame.draw.polygon(s, (255, 240, 210), [T(-10, -2.5), T(-10 - fl * 0.55, 0), T(-10, 2.5)])
        ex, ey = T(-12, 0)
        draw_glow(s, ex, ey, (80, 190, 255), 30 + 14 * p.thrust, 0.65)
        draw_glow(s, p.x, p.y, CYAN, 46, 0.45)
        blink = p.iframes > 0 and p.dash_t <= 0 and int(p.iframes * 18) % 2 == 0
        if not blink:
            hull = [T(22, 0), T(-2, -7), T(-14, -16), T(-9, -4), T(-12, 0), T(-9, 4), T(-14, 16), T(-2, 7)]
            pygame.draw.polygon(s, (16, 34, 58), hull)
            pygame.draw.polygon(s, CYAN, hull, 2)
            pygame.draw.line(s, (120, 230, 255), T(18, 0), T(-6, 0), 1)
            pygame.draw.line(s, sc(CYAN, 0.7), T(-2, -7), T(-11, -12), 1)
            pygame.draw.line(s, sc(CYAN, 0.7), T(-2, 7), T(-11, 12), 1)
            cx, cy = T(5, 0)
            pygame.draw.circle(s, WHITE, (int(cx), int(cy)), 3)
        if p.shield > 0:
            pul = 0.65 + 0.35 * math.sin(self.t * 6)
            pygame.draw.circle(s, sc(BLUE, pul), (int(p.x), int(p.y)), 27, 2)
            draw_glow(s, p.x, p.y, BLUE, 52, 0.35 * pul)

    def draw_pickup(self, s, pk):
        col = PICK_COLORS[pk.kind]
        blink = pk.life < 3 and int(pk.life * 8) % 2 == 0
        if blink:
            return
        bob = math.sin(pk.t * 4) * 3
        x, y = pk.x, pk.y + bob
        pul = 0.7 + 0.3 * math.sin(pk.t * 6)
        draw_glow(s, x, y, col, 40, 0.75 * pul)
        pygame.draw.circle(s, sc(col, 0.22), (int(x), int(y)), 15)
        pygame.draw.circle(s, col, (int(x), int(y)), 15, 2)
        if pk.kind == "hp":
            pygame.draw.rect(s, col, (x - 7, y - 2, 14, 4))
            pygame.draw.rect(s, col, (x - 2, y - 7, 4, 14))
        elif pk.kind == "weapon":
            pygame.draw.polygon(s, col, star(x, y, 9, 4, pk.t * 2 - math.pi / 2))
        elif pk.kind == "shield":
            pygame.draw.circle(s, col, (int(x), int(y)), 8, 2)
            pygame.draw.circle(s, col, (int(x), int(y)), 3)
        elif pk.kind == "bomb":
            pygame.draw.circle(s, col, (int(x), int(y)), 7)
            pygame.draw.circle(s, WHITE, (int(x), int(y)), 3)
            for i in range(6):
                a = pk.t * 3 + i * math.pi / 3
                pygame.draw.line(s, col, (x + math.cos(a) * 9, y + math.sin(a) * 9),
                                 (x + math.cos(a) * 13, y + math.sin(a) * 13), 2)
        elif pk.kind == "rapid":
            for dx_ in (-4, 3):
                pygame.draw.polygon(s, col, [(x + dx_ - 3, y - 6), (x + dx_ + 4, y), (x + dx_ - 3, y + 6)])

    def draw_particles(self, s):
        for q in self.particles:
            f = q.life / q.max
            k = q.kind
            if k == "spark":
                c = sc(q.color, min(1.0, f * 1.5))
                pygame.draw.line(s, c, (q.x, q.y), (q.x - q.vx * 0.04, q.y - q.vy * 0.04),
                                 max(1, int(q.size * f + 0.5)))
                if q.size >= 3 and f > 0.4:
                    draw_glow(s, q.x, q.y, q.color, 12, f * 0.6)
            elif k == "ring":
                r = q.size + q.vx * (q.max - q.life)
                pygame.draw.circle(s, sc(q.color, f), (int(q.x), int(q.y)), max(1, int(r)), max(1, int(5 * f)))
            elif k == "glow":
                draw_glow(s, q.x, q.y, q.color, q.size * (0.5 + 0.5 * f), f)
            elif k == "shard":
                dx_, dy_ = math.cos(q.rot) * q.size / 2, math.sin(q.rot) * q.size / 2
                pygame.draw.line(s, sc(q.color, f), (q.x - dx_, q.y - dy_), (q.x + dx_, q.y + dy_), 2)
            elif k == "ember":
                pygame.draw.circle(s, sc(q.color, f), (int(q.x), int(q.y)), max(1, int(q.size * f)))

    def draw_crosshair(self, s):
        mx, my = pygame.mouse.get_pos()
        p = self.player
        over = any(math.hypot(e.x - mx, e.y - my) < e.r + 6 and e.spawn <= 0 for e in self.enemies)
        col = RED if over else (230, 250, 255)
        r = 13 + 5 * self.firing_pulse
        pygame.draw.circle(s, col, (mx, my), int(r), 2)
        for a in (0, 1, 2, 3):
            ang = a * math.pi / 2 + self.t * 0.8
            pygame.draw.line(s, col, (mx + math.cos(ang) * (r + 3), my + math.sin(ang) * (r + 3)),
                             (mx + math.cos(ang) * (r + 10), my + math.sin(ang) * (r + 10)), 2)
        pygame.draw.circle(s, col, (mx, my), 2)
        draw_glow(s, mx, my, col, 26, 0.35)
        if p.alive:
            pygame.draw.line(s, (40, 70, 100), (p.x, p.y), (mx, my), 1)

    def draw_world(self, s):
        s.blit(self.bg, (0, 0))
        self.draw_stars(s)
        self.draw_arena(s)
        if self.state == "menu":
            for e in self.menu_enemies:
                self.draw_enemy(s, e)
            return
        for sw in self.shocks:
            f = 1 - sw.r / sw.max_r
            pygame.draw.circle(s, sc(WHITE, f), (int(sw.x), int(sw.y)), int(sw.r), max(2, int(14 * f)))
            pygame.draw.circle(s, sc(PINK, f), (int(sw.x), int(sw.y)), int(sw.r * 0.93), max(1, int(8 * f)))
        for pk in self.pickups:
            self.draw_pickup(s, pk)
        for e in self.enemies:
            if e.spawn > 0:
                self.draw_enemy(s, e)
        for b in self.ebullets:
            draw_glow(s, b.x, b.y, b.color, b.r * 3.4, 0.8)
            pygame.draw.circle(s, b.color, (int(b.x), int(b.y)), b.r)
            pygame.draw.circle(s, WHITE, (int(b.x), int(b.y)), max(1, b.r // 2))
        for e in self.enemies:
            if e.spawn <= 0:
                self.draw_enemy(s, e)
        for b in self.bullets:
            draw_glow(s, b.x, b.y, b.color, 18, 0.6)
            pygame.draw.line(s, sc(b.color, 0.8), (b.x, b.y), (b.x - b.vx * 0.05, b.y - b.vy * 0.05), 3)
            pygame.draw.line(s, (235, 252, 255), (b.x, b.y), (b.x - b.vx * 0.026, b.y - b.vy * 0.026), 3)
        self.draw_player(s)
        self.draw_particles(s)
        for tx in self.texts:
            f = clamp(tx[4] / tx[5], 0, 1)
            font = self.f_med if tx[6] else self.f_small
            self.text(s, tx[2], font, tx[3], (tx[0], tx[1]), "center", True, int(255 * min(1.0, f * 2)))

    def post_bloom(self):
        try:
            c = self.canvas
            small = pygame.transform.smoothscale(c, (W // 4, H // 4))
            tiny = pygame.transform.smoothscale(small, (W // 14, H // 14))
            small.fill((135, 135, 135), special_flags=pygame.BLEND_RGB_MULT)
            tiny.fill((215, 215, 215), special_flags=pygame.BLEND_RGB_MULT)
            pygame.transform.smoothscale(small, (W, H), self.bloom_a)
            pygame.transform.smoothscale(tiny, (W, H), self.bloom_b)
            c.blit(self.bloom_a, (0, 0), special_flags=pygame.BLEND_RGB_ADD)
            c.blit(self.bloom_b, (0, 0), special_flags=pygame.BLEND_RGB_ADD)
        except Exception:
            self.bloom = False

    def text(self, surf, txt, font, color, pos, anchor="topleft", shadow=True, alpha=255):
        img = font.render(txt, True, color)
        if alpha < 255:
            img.set_alpha(alpha)
        r = img.get_rect(**{anchor: pos})
        if shadow:
            sh = font.render(txt, True, (0, 0, 0))
            if alpha < 255:
                sh.set_alpha(alpha)
            surf.blit(sh, r.move(2, 2))
        surf.blit(img, r)
        return r

    def draw_hud(self, s):
        p = self.player
        x, y, w, h = 30, 28, 330, 18
        rrect(s, (10, 14, 28), (x - 4, y - 4, w + 8, h + 8), 8)
        frac = clamp(p.hp / p.max_hp, 0, 1)
        col = mixc(RED, YELLOW, frac * 2) if frac < 0.5 else mixc(YELLOW, GREEN, (frac - 0.5) * 2)
        if frac > 0:
            rrect(s, col, (x, y, int(w * frac), h), 5)
        for i in range(1, 10):
            pygame.draw.line(s, (10, 14, 28), (x + w * i / 10, y), (x + w * i / 10, y + h), 2)
        rrect(s, sc(col, 1.0), (x, y, w, h), 5, 2)
        self.text(s, "HULL", self.f_small, (200, 220, 255), (x + 6, y + 1), shadow=False)
        if p.shield > 0:
            rrect(s, BLUE, (x, y + h + 7, int(w * p.shield / 60.0), 6), 3)
        by = y + h + 24
        self.text(s, "BOMBS", self.f_small, (180, 190, 220), (x, by))
        for i in range(5):
            cx = x + 78 + i * 26
            if i < p.bombs:
                pygame.draw.circle(s, PINK, (cx, by + 10), 8)
                pygame.draw.circle(s, WHITE, (cx, by + 10), 3)
            else:
                pygame.draw.circle(s, (50, 40, 70), (cx, by + 10), 8, 2)
        wy = by + 28
        self.text(s, "WEAPON", self.f_small, (180, 190, 220), (x, wy))
        for i in range(5):
            c = YELLOW if i < p.weapon else (50, 50, 70)
            pygame.draw.rect(s, c, (x + 78 + i * 26, wy + 3, 20, 12))
        if p.rapid > 0:
            self.text(s, f"RAPID {p.rapid:0.0f}s", self.f_small, ORANGE, (x + 220, wy))
        dy_ = wy + 28
        self.text(s, "DASH", self.f_small, (180, 190, 220), (x, dy_))
        ready = 1.0 - clamp(p.dash_cd / DASH_CD, 0, 1)
        pygame.draw.rect(s, (30, 36, 60), (x + 78, dy_ + 4, 130, 10))
        pygame.draw.rect(s, CYAN if ready >= 1 else (60, 110, 150), (x + 78, dy_ + 4, int(130 * ready), 10))

        self.text(s, f"{int(self.disp_score):,}", self.f_big, WHITE, (W // 2, 26), "midtop")
        self.text(s, f"HI {max(self.high, self.score):,}", self.f_small, (150, 170, 210), (W // 2, 78), "midtop")
        self.text(s, f"WAVE {max(1, self.wave)}", self.f_med, CYAN, (W - 34, 28), "topright")
        self.text(s, f"{self.kills} kills", self.f_small, (150, 170, 210), (W - 34, 62), "topright")

        if self.combo >= 2:
            fr = clamp(self.combo_t / 3.2, 0, 1)
            cx = W // 2
            self.text(s, f"COMBO x{self.mult}", self.f_big, mixc(ORANGE, YELLOW, self.mult / 10.0),
                      (cx, H - 86), "midtop")
            pygame.draw.rect(s, (30, 30, 50), (cx - 110, H - 34, 220, 7))
            pygame.draw.rect(s, YELLOW, (cx - 110, H - 34, int(220 * fr), 7))
            self.text(s, f"{self.combo} chain", self.f_small, (200, 200, 220), (cx, H - 56), "midtop")

        b = self.boss
        if b is not None and b.spawn <= 0:
            bw = 560
            bx = W // 2 - bw // 2
            rrect(s, (16, 10, 24), (bx - 4, 106, bw + 8, 20), 8)
            rrect(s, PINK if b.hp / b.max_hp > 0.5 else RED, (bx, 110, int(bw * max(0, b.hp) / b.max_hp), 12), 5)
            self.text(s, "OVERLORD", self.f_small, (255, 190, 220), (W // 2, 130), "midtop")

        if self.banner:
            txt, sub, t, dur = self.banner
            a = clamp(min(t, dur - t) * 3.0, 0, 1)
            col = RED if txt == "WARNING" else WHITE
            self.text(s, txt, self.f_huge if len(txt) < 12 else self.f_big, col, (W // 2, H // 2 - 130),
                      "center", True, int(255 * a))
            if sub:
                self.text(s, sub, self.f_med, (200, 220, 255), (W // 2, H // 2 - 60), "center", True, int(255 * a))

    def draw_menu(self, s):
        t = self.t
        dim = pygame.Surface((W, H), pygame.SRCALPHA)
        dim.fill((0, 0, 10, 120))
        s.blit(dim, (0, 0))
        pul = 0.75 + 0.25 * math.sin(t * 2.5)
        draw_glow(s, W // 2, 190, PINK, 380, 0.25 * pul)
        draw_glow(s, W // 2, 190, CYAN, 300, 0.18 * pul)
        self.text(s, "NEON SIEGE", self.f_huge, (255, 255, 255), (W // 2, 190), "center")
        self.text(s, "T W I N - S T I C K   A R E N A   S H O O T E R", self.f_small, (150, 210, 255),
                  (W // 2, 262), "center")
        lines = [("WASD", "move"), ("MOUSE", "aim  /  hold LEFT CLICK to fire"),
                 ("SHIFT / RIGHT CLICK", "dash (brief invulnerability)"), ("SPACE", "bomb"),
                 ("P", "pause"), ("G", "toggle bloom")]
        for i, (k, v) in enumerate(lines):
            y = 330 + i * 32
            self.text(s, k, self.f_small, YELLOW, (W // 2 - 20, y), "topright")
            self.text(s, v, self.f_small, (215, 225, 245), (W // 2 + 4, y), "topleft")
        if int(t * 2) % 2 == 0:
            self.text(s, "PRESS  ENTER  TO  START", self.f_med, (255, 240, 140), (W // 2, 580), "center")
        if self.high:
            self.text(s, f"HIGH SCORE  {self.high:,}", self.f_med, (170, 200, 255), (W // 2, 635), "center")

    def draw_over(self, s):
        dim = pygame.Surface((W, H), pygame.SRCALPHA)
        dim.fill((0, 0, 10, 170))
        s.blit(dim, (0, 0))
        self.text(s, "SHIP DESTROYED", self.f_big, RED, (W // 2, 160), "center")
        self.text(s, f"{self.score:,}", self.f_huge, WHITE, (W // 2, 265), "center")
        if self.new_high:
            self.text(s, "NEW HIGH SCORE!", self.f_med, YELLOW, (W // 2, 340), "center")
        else:
            self.text(s, f"HIGH SCORE  {self.high:,}", self.f_small, (170, 200, 255), (W // 2, 340), "center")
        mins = int(self.time_alive // 60)
        secs = int(self.time_alive % 60)
        self.text(s, f"Wave {self.wave}    Kills {self.kills}    Time {mins}:{secs:02d}", self.f_med,
                  (215, 225, 245), (W // 2, 410), "center")
        if int(self.t * 2) % 2 == 0:
            self.text(s, "PRESS  ENTER  TO  PLAY  AGAIN", self.f_med, (255, 240, 140), (W // 2, 500), "center")

    def draw(self):
        c = self.canvas
        self.draw_world(c)
        self.draw_crosshair(c)
        if self.bloom:
            self.post_bloom()
        c.blit(self.vig_dark, (0, 0))
        if self.hurt_flash > 0:
            self.vig_red.set_alpha(int(255 * clamp(self.hurt_flash, 0, 1)))
            c.blit(self.vig_red, (0, 0))
        if self.flash > 0:
            r, g, b = self.flash_col
            self.flash_surf.fill((r, g, b, int(200 * clamp(self.flash, 0, 1))))
            c.blit(self.flash_surf, (0, 0))

        ox = oy = 0
        if self.shake > 0 and self.state != "paused":
            m = min(self.shake, 18)
            ox, oy = int(random.uniform(-m, m) * 0.5), int(random.uniform(-m, m) * 0.5)
        self.screen.fill((0, 0, 0))
        self.screen.blit(c, (ox, oy))

        if self.state == "menu":
            self.draw_menu(self.screen)
        elif self.state in ("play", "paused", "over"):
            self.draw_hud(self.screen)
            if self.state == "paused":
                dim = pygame.Surface((W, H), pygame.SRCALPHA)
                dim.fill((0, 0, 10, 150))
                self.screen.blit(dim, (0, 0))
                self.text(self.screen, "PAUSED", self.f_huge, WHITE, (W // 2, H // 2 - 30), "center")
                self.text(self.screen, "press P to resume", self.f_med, (200, 215, 240),
                          (W // 2, H // 2 + 50), "center")
            elif self.state == "over":
                self.draw_over(self.screen)
        pygame.display.flip()

    # --------------------------------------------------------------- loop
    def run(self):
        while True:
            dt = min(self.clock.tick(FPS) / 1000.0, 1 / 30.0)
            for event in pygame.event.get():
                self.handle_event(event)
            self.update(dt)
            self.draw()


if __name__ == "__main__":
    Game().run()
