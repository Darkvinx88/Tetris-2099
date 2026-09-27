
import array
import json
import math
import random
import sys
from pathlib import Path

import pygame

from joypad import JoypadManager
from music import MusicManager

# ----------------------------------------------------------------------------
# Costanti
# ----------------------------------------------------------------------------
W, H, HID = 10, 20, 2            # colonne, righe visibili, righe nascoste sopra
FPS = 60

# Valori "base" (finestra di default, scala 1x). CELL, BOARD_X/Y, WIN_W/H sono
# ricalcolati a runtime da rebuild_layout() in base alla risoluzione reale dello
# schermo, cosi' in schermo intero il gioco si ridisegna alla risoluzione nativa
# del monitor invece di essere renderizzato piccolo e poi stirato/sgranato.
BASE_CELL = 32
BASE_BOARD_X, BASE_BOARD_Y = 200, 30
BASE_WIN_W = 720
BASE_WIN_H = H * BASE_CELL + 2 * BASE_BOARD_Y
BASE_FONTS = {"title": 92, "big": 34, "mid": 24, "small": 16, "tiny": 15}
MIN_SCALE, MAX_SCALE = 0.6, 1.75

CELL = BASE_CELL
BOARD_X, BOARD_Y = BASE_BOARD_X, BASE_BOARD_Y
WIN_W, WIN_H = BASE_WIN_W, BASE_WIN_H
UI_SCALE = 1.0


def uiscale(v):
    """Scala un valore in pixel 'di base' (calibrato a finestra 720x700) in base
    a UI_SCALE, cosi' anche gli offset scritti a mano nei pannelli (non derivati
    da CELL) restano in proporzione quando cambia la risoluzione."""
    return round(v * UI_SCALE)

DAS, ARR = 0.16, 0.04            # auto-repeat laterale (secondi)
LOCK_DELAY, MAX_RESETS = 0.5, 15
CLEAR_TIME = 0.40
SQUASH_T = 0.18                  # durata dell'effetto "atterraggio" dei blocchi
HIGHSCORE_FILE = Path(__file__).with_name("highscore.json")
SETTINGS_FILE = Path(__file__).with_name("settings.json")
SAVESTATE_FILE = Path(__file__).with_name("savestate.json")

TEXT_DIM = (150, 158, 190)
TEXT_BRIGHT = (245, 247, 255)
ACCENT = (110, 200, 255)

COLORS = {
    "I": (34, 211, 238), "O": (250, 204, 21), "T": (192, 132, 252),
    "S": (74, 222, 128), "Z": (248, 113, 113), "J": (96, 165, 250),
    "L": (251, 146, 60),
}

# nome: (dimensione box, celle nello stato 0) - orientamento SRS
BASE = {
    "I": (4, [(0, 1), (1, 1), (2, 1), (3, 1)]),
    "O": (2, [(0, 0), (1, 0), (0, 1), (1, 1)]),
    "T": (3, [(1, 0), (0, 1), (1, 1), (2, 1)]),
    "S": (3, [(1, 0), (2, 0), (0, 1), (1, 1)]),
    "Z": (3, [(0, 0), (1, 0), (1, 1), (2, 1)]),
    "J": (3, [(0, 0), (0, 1), (1, 1), (2, 1)]),
    "L": (3, [(2, 0), (0, 1), (1, 1), (2, 1)]),
}
SHAPES = {}
for _name, (_n, _cells) in BASE.items():
    _rots = [_cells]
    for _ in range(3):
        _rots.append([(_n - 1 - y, x) for x, y in _rots[-1]])
    SHAPES[_name] = _rots

# Wall kick SRS (coordinate con y verso l'alto, come nel wiki: si inverte y quando si applicano)
KICKS_JLSTZ = {
    (0, 1): [(0, 0), (-1, 0), (-1, 1), (0, -2), (-1, -2)],
    (1, 0): [(0, 0), (1, 0), (1, -1), (0, 2), (1, 2)],
    (1, 2): [(0, 0), (1, 0), (1, -1), (0, 2), (1, 2)],
    (2, 1): [(0, 0), (-1, 0), (-1, 1), (0, -2), (-1, -2)],
    (2, 3): [(0, 0), (1, 0), (1, 1), (0, -2), (1, -2)],
    (3, 2): [(0, 0), (-1, 0), (-1, -1), (0, 2), (-1, 2)],
    (3, 0): [(0, 0), (-1, 0), (-1, -1), (0, 2), (-1, 2)],
    (0, 3): [(0, 0), (1, 0), (1, 1), (0, -2), (1, -2)],
}
KICKS_I = {
    (0, 1): [(0, 0), (-2, 0), (1, 0), (-2, -1), (1, 2)],
    (1, 0): [(0, 0), (2, 0), (-1, 0), (2, 1), (-1, -2)],
    (1, 2): [(0, 0), (-1, 0), (2, 0), (-1, 2), (2, -1)],
    (2, 1): [(0, 0), (1, 0), (-2, 0), (1, -2), (-2, 1)],
    (2, 3): [(0, 0), (2, 0), (-1, 0), (2, 1), (-1, -2)],
    (3, 2): [(0, 0), (-2, 0), (1, 0), (-2, -1), (1, 2)],
    (3, 0): [(0, 0), (1, 0), (-2, 0), (1, -2), (-2, 1)],
    (0, 3): [(0, 0), (-1, 0), (2, 0), (-1, 2), (2, -1)],
}

KEYS_L = (pygame.K_LEFT, pygame.K_a)
KEYS_R = (pygame.K_RIGHT, pygame.K_d)
KEYS_DOWN = (pygame.K_DOWN, pygame.K_s)
KEYS_ROT = (pygame.K_UP, pygame.K_x, pygame.K_w)
KEYS_ROT_CCW = (pygame.K_z, pygame.K_LCTRL)
KEYS_HOLD = (pygame.K_c, pygame.K_LSHIFT, pygame.K_RSHIFT)

F = {}  # font, inizializzati in main()


# ----------------------------------------------------------------------------
# Audio sintetizzato 
# ----------------------------------------------------------------------------
class Sfx:
    def __init__(self, volume=1.0):
        self.enabled = True
        self.volume = max(0.0, min(1.0, volume))
        self.sounds = {}
        try:
            pygame.mixer.init(44100, -16, 1, 512)
            spec = {
                "rotate": (440, 540, 50, 0.22), "lock": (150, 90, 90, 0.4),
                "hard": (220, 55, 150, 0.5), "hold": (340, 260, 90, 0.3),
                "clear": (600, 1000, 230, 0.3), "tetris": (400, 1500, 450, 0.35),
                "level": (700, 1200, 300, 0.3), "over": (320, 70, 800, 0.4),
            }
            for k, v in spec.items():
                self.sounds[k] = self._tone(*v)
        except pygame.error:
            self.enabled = False

    @staticmethod
    def _tone(f0, f1, ms, vol):
        rate = 44100
        n = int(rate * ms / 1000)
        buf, phase = array.array("h"), 0.0
        for i in range(n):
            f = f0 + (f1 - f0) * i / n
            phase += 2 * math.pi * f / rate
            env = (1 - i / n) ** 1.5
            buf.append(int(32767 * vol * env * math.sin(phase)))
        return pygame.mixer.Sound(buffer=buf.tobytes())

    def play(self, name):
        if self.enabled and name in self.sounds:
            self.sounds[name].set_volume(self.volume)
            self.sounds[name].play()

    def set_volume(self, pct):
        self.volume = max(0.0, min(1.0, pct))


# ----------------------------------------------------------------------------
# Rendering helpers
# ----------------------------------------------------------------------------
_cache = {}


def shade(c, f):
    return tuple(max(0, min(255, int(v * f))) for v in c)


def block_surf(color, size, kind="solid"):
    key = (color, size, kind)
    if key in _cache:
        return _cache[key]
    s = pygame.Surface((size, size), pygame.SRCALPHA)
    r = max(3, size // 7)
    if kind == "ghost":
        pygame.draw.rect(s, (*color, 45), (1, 1, size - 2, size - 2), border_radius=r)
        pygame.draw.rect(s, (*color, 190), (1, 1, size - 2, size - 2), width=2, border_radius=r)
    else:
        pygame.draw.rect(s, shade(color, 0.55), (0, 0, size, size), border_radius=r)
        pygame.draw.rect(s, color, (2, 2, size - 4, size - 4), border_radius=r)
        pygame.draw.rect(s, shade(color, 1.35), (2, 2, size - 4, size - 4), width=1, border_radius=r)
        gloss = pygame.Surface((size - 8, max(3, size // 3)), pygame.SRCALPHA)
        pygame.draw.rect(gloss, (255, 255, 255, 60), gloss.get_rect(), border_radius=r)
        s.blit(gloss, (4, 4))
    _cache[key] = s
    return s


def glow_surf(color, radius):
    key = (color, radius, "glow")
    if key in _cache:
        return _cache[key]
    s = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
    for i in range(radius, 0, -2):
        a = int(38 * (1 - i / radius) ** 1.6)
        pygame.draw.circle(s, (*color, a), (radius, radius), i)
    _cache[key] = s
    return s


def white_flash(size, alpha):
    s = pygame.Surface((size, size))
    s.fill((255, 255, 255))
    s.set_alpha(alpha)
    return s


def draw_text(surf, font, text, color, pos, anchor="topleft", shadow=True, alpha=255):
    img = font.render(text, True, color)
    rect = img.get_rect(**{anchor: pos})
    if shadow:
        sh = font.render(text, True, (0, 0, 0))
        sh.set_alpha(int(alpha * 0.5))
        surf.blit(sh, rect.move(2, 2))
    if alpha < 255:
        img.set_alpha(alpha)
    surf.blit(img, rect)
    return rect


def panel(surf, rect, title=None):
    rect = pygame.Rect(rect)
    s = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(s, (10, 12, 26, 200), s.get_rect(), border_radius=14)
    pygame.draw.rect(s, (255, 255, 255, 35), s.get_rect(), width=1, border_radius=14)
    surf.blit(s, rect)
    if title:
        draw_text(surf, F["small"], title, TEXT_DIM, (rect.centerx, rect.y + uiscale(14)), "center", shadow=False)


def draw_preview(surf, name, cx, cy, size, dimmed=False):
    cells = SHAPES[name][0]
    xs, ys = [c[0] for c in cells], [c[1] for c in cells]
    w, h = (max(xs) - min(xs) + 1) * size, (max(ys) - min(ys) + 1) * size
    ox, oy = cx - w // 2 - min(xs) * size, cy - h // 2 - min(ys) * size
    color = (85, 90, 108) if dimmed else COLORS[name]
    bs = block_surf(color, size)
    for x, y in cells:
        surf.blit(bs, (ox + x * size, oy + y * size))


def make_background(w=WIN_W, h=WIN_H):
    bg = pygame.Surface((w, h))
    top, bot = (16, 18, 42), (5, 6, 14)
    for y in range(h):
        t = y / h
        pygame.draw.line(bg, tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)), (0, y), (w, y))
    return bg


def make_board_bg():
    pad = uiscale(16)
    s = pygame.Surface((W * CELL + pad, H * CELL + pad), pygame.SRCALPHA)
    pygame.draw.rect(s, (7, 9, 20, 225), s.get_rect(), border_radius=uiscale(12))
    for i in range(1, W):
        pygame.draw.line(s, (26, 30, 52), (pad // 2 + i * CELL, pad // 2), (pad // 2 + i * CELL, pad // 2 + H * CELL))
    for j in range(1, H):
        pygame.draw.line(s, (26, 30, 52), (pad // 2, pad // 2 + j * CELL), (pad // 2 + W * CELL, pad // 2 + j * CELL))
    pygame.draw.rect(s, (120, 135, 200, 150), s.get_rect(), width=2, border_radius=uiscale(12))
    return s


# ----------------------------------------------------------------------------
# Persistenza high score
# ----------------------------------------------------------------------------
def load_high():
    try:
        data = json.loads(HIGHSCORE_FILE.read_text())
        return int(data["high"] if isinstance(data, dict) else data)
    except (OSError, ValueError, KeyError, TypeError):
        return 0


def save_high(v):
    try:
        HIGHSCORE_FILE.write_text(json.dumps({"high": v}))
    except OSError:
        pass


def load_settings():
    try:
        data = json.loads(SETTINGS_FILE.read_text())
        return {
            "fullscreen": bool(data.get("fullscreen", False)),
            "volume": max(0.0, min(1.0, float(data.get("volume", 0.6)))),
            "sfx_volume": max(0.0, min(1.0, float(data.get("sfx_volume", 0.6)))),
        }
    except (OSError, ValueError, AttributeError, TypeError):
        return {"fullscreen": False, "volume": 0.6, "sfx_volume": 0.6}


def save_settings(settings):
    try:
        SETTINGS_FILE.write_text(json.dumps(settings))
    except OSError:
        pass


# ----------------------------------------------------------------------------
# Persistenza savestate (continua partita)
# ----------------------------------------------------------------------------
def load_savestate():
    try:
        return json.loads(SAVESTATE_FILE.read_text())
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_savestate(data):
    try:
        SAVESTATE_FILE.write_text(json.dumps(data))
    except OSError:
        pass


def clear_savestate():
    try:
        SAVESTATE_FILE.unlink()
    except OSError:
        pass


def draw_fullscreen_button(surf, rect, hovered, active):
    """Icona in alto a destra per attivare/disattivare lo schermo intero."""
    s = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(s, (255, 255, 255, 70 if hovered else 32), s.get_rect(), border_radius=8)
    pygame.draw.rect(s, (255, 255, 255, 100), s.get_rect(), width=1, border_radius=8)
    surf.blit(s, rect)
    ln, pad = 7, 8
    corners = [(rect.left + pad, rect.top + pad, 1, 1), (rect.right - pad, rect.top + pad, -1, 1),
               (rect.left + pad, rect.bottom - pad, 1, -1), (rect.right - pad, rect.bottom - pad, -1, -1)]
    for x, y, sx, sy in corners:
        if active:  # schermo intero attivo -> frecce verso l'interno (esci)
            x0, y0 = x + sx * ln, y + sy * ln
            pygame.draw.line(surf, TEXT_BRIGHT, (x0, y0), (x, y0), 2)
            pygame.draw.line(surf, TEXT_BRIGHT, (x0, y0), (x0, y), 2)
        else:       # frecce verso l'esterno (entra in schermo intero)
            pygame.draw.line(surf, TEXT_BRIGHT, (x, y), (x + sx * ln, y), 2)
            pygame.draw.line(surf, TEXT_BRIGHT, (x, y), (x, y + sy * ln), 2)


# ----------------------------------------------------------------------------
# Logica di gioco
# ----------------------------------------------------------------------------
class Piece:
    def __init__(self, name):
        self.name = name
        self.rot = 0
        self.x = 4 if name == "O" else 3
        self.y = 1
        self.ox = self.oy = 0.0   # offset visivo (in celle) per l'animazione fluida

    def cells(self):
        return [(self.x + cx, self.y + cy) for cx, cy in SHAPES[self.name][self.rot]]


class Game:
    def __init__(self, high, sfx, music=None, on_settings_change=None):
        self.high = high
        self.sfx = sfx
        self.music = music
        self.on_settings_change = on_settings_change or (lambda: None)
        self.t = 0.0
        self.particles = []
        self.popups = []
        self.trails = []          # scie dell'hard drop
        self.squash = {}          # (x, y) -> tempo dall'atterraggio
        self.shake = 0.0
        self.zoom = 0.0
        self.aber = 0.0
        self._track_save = False   # evita di toccare il file durante l'init "a vuoto"
        self.reset()
        self.state = "menu"
        self.has_save = SAVESTATE_FILE.exists()
        self._track_save = True
        self.menu_sel = 0
        self.menu_rects = []
        self.menu_music_rect = None
        self.menu_sfx_rect = None
        self.menu_in_options = False
        self.pause_sel = 0
        self.pause_rects = []
        self.pause_music_rect = None
        self.pause_sfx_rect = None
        self.pause_in_options = False
        self.want_quit = False

    # ---- salvataggio/continua ----
    def save_state(self):
        if not self._track_save or self.state not in ("play", "clearing"):
            return
        p = self.piece
        data = {
            "grid": [[list(c) if c else None for c in row] for row in self.grid],
            "score": self.score, "lines": self.lines,
            "combo": self.combo, "b2b": self.b2b,
            "bag": self.bag, "queue": self.queue,
            "hold": self.hold, "hold_used": self.hold_used,
            "piece": {"name": p.name, "rot": p.rot, "x": p.x, "y": p.y},
            "state": self.state, "clear_rows": self.clear_rows,
        }
        save_savestate(data)
        self.has_save = True

    def clear_save(self):
        if not self._track_save:
            return
        clear_savestate()
        self.has_save = False

    def load_state(self):
        data = load_savestate()
        if not data:
            self.reset()
            return
        try:
            self.grid = [[tuple(c) if c else None for c in row] for row in data["grid"]]
            self.score, self.lines = data["score"], data["lines"]
            self.disp_score = float(self.score)
            self.combo, self.b2b = data["combo"], data["b2b"]
            self.bag, self.queue = data["bag"], data["queue"]
            self.hold, self.hold_used = data["hold"], data["hold_used"]
            self.paused, self.new_high = False, False
            self.hdir, self.das_t, self.arr_t = 0, 0.0, 0.0
            self.clear_rows, self.clear_t = data.get("clear_rows", []), 0.0
            self.particles.clear(); self.popups.clear(); self.trails.clear(); self.squash.clear()
            self.shake = self.zoom = self.aber = 0.0
            pd = data["piece"]
            self.piece = Piece(pd["name"])
            self.piece.rot, self.piece.x, self.piece.y = pd["rot"], pd["x"], pd["y"]
            self.fall_t = self.lock_t = 0.0
            self.resets = 0
            self.lowest = self.piece.y
            self.last_action_rotate = False
            self.last_kick_index = -1
            self.state = data.get("state", "play")
            if self.state == "clearing" and not self.clear_rows:
                self.state = "play"
        except (KeyError, TypeError, ValueError, IndexError):
            self.reset()

    def menu_options(self):
        if self.menu_in_options:
            return ["music", "sfx", "esci"]
        base = ["continua"] if self.has_save else []
        return base + ["nuova", "opzioni", "esci"]

    def pause_options(self):
        if self.pause_in_options:
            return ("music", "sfx", "esci")
        return ("continua", "opzioni", "esci")

    def music_pct(self):
        return round((self.music.volume if self.music else 0.0) * 100)

    def sfx_pct(self):
        return round((self.sfx.volume if self.sfx else 0.0) * 100)

    def now_playing_name(self):
        m = self.music
        if not m or not getattr(m, "enabled", False):
            return ""
        playlist = getattr(m, "_playlist", None)
        idx = getattr(m, "_idx", -1)
        if playlist and 0 <= idx < len(playlist):
            return Path(playlist[idx]).stem
        return ""

    def adjust_music(self, delta_pct):
        if not self.music:
            return
        self.music.set_volume(self.music.volume + delta_pct / 100.0)
        self.on_settings_change()

    def adjust_sfx(self, delta_pct):
        if not self.sfx:
            return
        self.sfx.set_volume(self.sfx.volume + delta_pct / 100.0)
        self.on_settings_change()

    def menu_activate(self, action):
        if action == "continua":
            self.menu_in_options = False
            self.load_state()
        elif action == "nuova":
            self.menu_in_options = False
            self.reset()
        elif action == "opzioni":
            self.menu_in_options = True
            self.menu_sel = 0
        elif action == "esci":
            if self.menu_in_options:
                self.menu_in_options = False
                self.menu_sel = 0
            else:
                self.want_quit = True

    def pause_activate(self, action):
        if action == "continua":
            self.pause_in_options = False
            self.paused = False
        elif action == "opzioni":
            self.pause_in_options = True
            self.pause_sel = 0
        elif action == "esci":
            if self.pause_in_options:
                self.pause_in_options = False
                self.pause_sel = 0
            else:
                self.want_quit = True

    # ---- setup ----
    def reset(self):
        self.clear_save()
        self.grid = [[None] * W for _ in range(H + HID)]
        self.score = self.lines = 0
        self.disp_score = 0.0
        self.combo, self.b2b = -1, False
        self.bag = []
        self.queue = [self._draw() for _ in range(5)]
        self.hold, self.hold_used = None, False
        self.paused, self.new_high = False, False
        self.hdir, self.das_t, self.arr_t = 0, 0.0, 0.0
        self.clear_rows, self.clear_t = [], 0.0
        self.particles.clear()
        self.popups.clear()
        self.trails.clear()
        self.squash.clear()
        self.zoom = self.aber = 0.0
        self.state = "play"
        self.spawn()

    def _draw(self):
        if not self.bag:                      # 7-bag: distribuzione equa dei pezzi
            self.bag = list(SHAPES)
            random.shuffle(self.bag)
        return self.bag.pop()

    def level(self):
        return self.lines // 10 + 1

    def spawn(self, name=None):
        if name is None:
            name = self.queue.pop(0)
            self.queue.append(self._draw())
        self.piece = Piece(name)
        self.fall_t = self.lock_t = 0.0
        self.resets = 0
        self.lowest = self.piece.y
        self.last_action_rotate = False
        self.last_kick_index = -1
        if self.collides(name, 0, self.piece.x, self.piece.y):
            self.game_over()
        else:
            self.save_state()

    # ---- collisioni / movimento ----
    def collides(self, name, rot, px, py):
        for cx, cy in SHAPES[name][rot]:
            x, y = px + cx, py + cy
            if x < 0 or x >= W or y >= H + HID:
                return True
            if y >= 0 and self.grid[y][x] is not None:
                return True
        return False

    def grounded(self):
        p = self.piece
        return self.collides(p.name, p.rot, p.x, p.y + 1)

    def ghost_y(self):
        p, y = self.piece, self.piece.y
        while not self.collides(p.name, p.rot, p.x, y + 1):
            y += 1
        return y

    def _after_move(self):
        p = self.piece
        if p.y > self.lowest:
            self.lowest, self.resets, self.lock_t = p.y, 0, 0.0
        elif self.grounded() and self.resets < MAX_RESETS:
            self.lock_t, self.resets = 0.0, self.resets + 1

    def try_move(self, dx, dy):
        p = self.piece
        if self.collides(p.name, p.rot, p.x + dx, p.y + dy):
            return False
        p.x += dx
        p.y += dy
        p.ox = max(-1.0, min(1.0, p.ox - dx))
        p.oy = max(-1.0, min(1.0, p.oy - dy))
        self._after_move()
        self.last_action_rotate = False
        return True

    def rotate(self, d):
        p = self.piece
        if p.name == "O":
            return
        new = (p.rot + d) % 4
        table = KICKS_I if p.name == "I" else KICKS_JLSTZ
        for i, (kx, ky) in enumerate(table[(p.rot, new)]):
            if not self.collides(p.name, new, p.x + kx, p.y - ky):
                p.rot, p.x, p.y = new, p.x + kx, p.y - ky
                p.ox, p.oy = p.ox - kx, p.oy + ky
                self._after_move()
                self.sfx.play("rotate")
                self.last_action_rotate = True
                self.last_kick_index = i
                return

    def do_hold(self):
        if self.hold_used:
            return
        cur = self.piece.name
        old, self.hold, self.hold_used = self.hold, cur, True
        self.sfx.play("hold")
        self.spawn(old)

    def hard_drop(self):
        p = self.piece
        gy = self.ghost_y()
        d = gy - p.y
        if d > 0:                              # una scia per ogni colonna occupata dal pezzo
            for col_x in {x for x, _ in p.cells()}:
                top = min(y for x, y in p.cells() if x == col_x)
                self.trails.append([col_x, top, top + d, COLORS[p.name], 0.28, 0.28])
        self.score += 2 * d
        p.y = gy
        p.ox = p.oy = 0.0
        self.shake = max(self.shake, 6)
        col = COLORS[p.name]
        for x, y in p.cells():
            self._burst(BOARD_X + x * CELL + CELL / 2, BOARD_Y + (y - HID) * CELL + CELL / 2, col, 2, up=True)
        self.sfx.play("hard")
        self.lock()

    # ---- T-Spin (regola dei 3 angoli, standard SRS/Guideline) ----
    def _tspin_type(self):
        
        p = self.piece
        if p.name != "T" or not self.last_action_rotate:
            return None
        cx, cy = p.x + 1, p.y + 1  # centro del box 3x3 (coincide col pivot SRS)

        def occ(dx, dy):
            x, y = cx + dx, cy + dy
            if x < 0 or x >= W or y >= H + HID:
                return True          # il muro/fondo conta come "occupato"
            if y < 0:
                return False         # sopra la zona nascosta: sempre libero
            return self.grid[y][x] is not None

        tl, tr, bl, br = occ(-1, -1), occ(1, -1), occ(-1, 1), occ(1, 1)
        front_map = {0: (tl, tr), 1: (tr, br), 2: (bl, br), 3: (tl, bl)}
        back_map = {0: (bl, br), 1: (tl, bl), 2: (tl, tr), 3: (tr, br)}
        f0, f1 = front_map[p.rot]
        b0, b1 = back_map[p.rot]
        if f0 and f1:
            return "full"
        if b0 and b1 and (f0 or f1):
            return "full" if self.last_kick_index == 4 else "mini"
        return None

    # ---- lock & clear ----
    def lock(self):
        p = self.piece
        col = COLORS[p.name]
        cells = p.cells()
        for x, y in cells:
            self.grid[y][x] = col
        if all(y < HID for _, y in cells):     # lock-out: tutto sopra la zona visibile
            self.game_over()
            return

        tspin = self._tspin_type()
        full = [y for y in range(H + HID) if all(c is not None for c in self.grid[y])]
        n, lvl = len(full), self.level()

        if not full:
            for c in cells:
                self.squash[c] = 0.0
            self.combo = -1
            if tspin:                          # T-Spin (Mini) senza linee: punti comunque
                pts = (400 if tspin == "full" else 100) * lvl
                self.score += pts
                self._popup("T-SPIN" if tspin == "full" else "T-SPIN MINI", COLORS["T"], 0)
                self.sfx.play("level")
            self.hold_used = False
            self.sfx.play("lock")
            self.spawn()
            return

        if tspin:
            base = {"full": (400, 800, 1200, 1600), "mini": (100, 200, 400, 600)}[tspin]
            pts = base[n] * lvl
            label = ("T-SPIN" if tspin == "full" else "T-SPIN MINI") + ("", " SINGLE", " DOUBLE", " TRIPLE")[n]
            difficult = True                   # conta come "clear difficile" per il B2B
        else:
            pts = (0, 100, 300, 500, 800)[n] * lvl
            label = ("", "SINGLE", "DOUBLE", "TRIPLE", "TETRIS!")[n]
            difficult = (n == 4)

        was_b2b, self.b2b = self.b2b, difficult
        if difficult and was_b2b:
            pts = int(pts * 1.5)
            label = "BACK-TO-BACK " + label

        # Perfect Clear (All Clear): dopo aver tolto le righe piene non resta nulla
        full_set = set(full)
        perfect = all(self.grid[y][x] is None for y in range(H + HID)
                      for x in range(W) if y not in full_set)
        if perfect:
            pts += (0, 800, 1200, 1800, 2000)[n] * lvl

        self.combo += 1
        if self.combo > 0:
            pts += 50 * self.combo * lvl
            self._popup(f"COMBO x{self.combo}", (255, 200, 90), 60)
        self._popup(label, COLORS["T"] if tspin else (COLORS["I"] if n < 4 else COLORS["O"]), 0)
        if perfect:
            self._popup("PERFECT CLEAR", (255, 255, 255), -30)
        self.score += pts
        self.lines += n
        if self.level() > lvl:
            self._popup(f"LEVEL {self.level()}", COLORS["S"], -60)
            self.sfx.play("level")
        self.sfx.play("tetris" if n == 4 else "clear")
        self.shake = 4 + 3 * n
        self.zoom = 0.012 * n
        self.aber = 1.0 if n == 4 else 0.35 * n / 3
        self.squash.clear()
        for y in full:
            for x in range(W):
                self._burst(BOARD_X + x * CELL + CELL / 2, BOARD_Y + (y - HID) * CELL + CELL / 2, self.grid[y][x], 3)
        self.clear_rows, self.clear_t = full, 0.0
        self.state = "clearing"

    def _finish_clear(self):
        gone = set(self.clear_rows)
        kept = [r for i, r in enumerate(self.grid) if i not in gone]
        self.grid = [[None] * W for _ in range(len(gone))] + kept
        self.clear_rows = []
        self.hold_used = False
        self.state = "play"
        self.spawn()

    def game_over(self):
        self.state = "over"
        self.hdir = 0
        self.sfx.play("over")
        self.shake = 10
        self.finalize_high()
        self.clear_save()

    def finalize_high(self):
        if self.score > self.high:
            self.high = self.score
            self.new_high = True
            save_high(self.high)

    # ---- effetti ----
    def _burst(self, x, y, color, count, up=False):
        for _ in range(count):
            a = random.uniform(0, math.tau)
            sp = random.uniform(80, 320)
            vy = math.sin(a) * sp - (200 if up else 120)
            life = random.uniform(0.4, 0.9)
            self.particles.append([x, y, math.cos(a) * sp, vy, life, life, color])

    def _popup(self, text, color, dy):
        if text:
            self.popups.append([text, color, dy, 0.0])

    # ---- update ----
    def update(self, dt):
        self.t += dt
        for p in self.particles:
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[3] += 900 * dt
            p[4] -= dt
        self.particles = [p for p in self.particles if p[4] > 0]
        for pu in self.popups:
            pu[3] += dt
        self.popups = [pu for pu in self.popups if pu[3] < 1.3]
        self.shake = max(0.0, self.shake - dt * 30)
        self.zoom *= math.exp(-dt * 7)
        self.aber = max(0.0, self.aber - dt * 3)
        for tr in self.trails:
            tr[4] -= dt
        self.trails = [tr for tr in self.trails if tr[4] > 0]
        for c in list(self.squash):
            self.squash[c] += dt
            if self.squash[c] >= SQUASH_T:
                del self.squash[c]
        self.disp_score += (self.score - self.disp_score) * min(1.0, dt * 10)
        if abs(self.score - self.disp_score) < 1:
            self.disp_score = self.score

        if self.state == "clearing":
            self.clear_t += dt
            if self.clear_t >= CLEAR_TIME:
                self._finish_clear()
            return
        if self.state != "play" or self.paused:
            return

        k = math.exp(-dt * 38)                 # il pezzo "scivola" verso la posizione logica
        self.piece.ox *= k
        self.piece.oy *= k
        if abs(self.piece.ox) < 0.01:
            self.piece.ox = 0.0
        if abs(self.piece.oy) < 0.01:
            self.piece.oy = 0.0

        keys = pygame.key.get_pressed()
        left = any(keys[k] for k in KEYS_L)
        right = any(keys[k] for k in KEYS_R)
        prev = self.hdir
        if self.hdir == -1 and not left:
            self.hdir = 1 if right else 0
        elif self.hdir == 1 and not right:
            self.hdir = -1 if left else 0
        if self.hdir != prev:
            self.das_t = self.arr_t = 0.0
        if self.hdir:
            self.das_t += dt
            if self.das_t >= DAS:
                self.arr_t += dt
                while self.arr_t >= ARR:
                    self.arr_t -= ARR
                    if not self.try_move(self.hdir, 0):
                        break

        soft = any(keys[k] for k in KEYS_DOWN)
        lvl = min(self.level(), 20)
        g = max(0.01, (0.8 - (lvl - 1) * 0.007) ** (lvl - 1))
        interval = min(g, 0.04) if soft else g
        self.fall_t += dt
        while self.fall_t >= interval:
            self.fall_t -= interval
            if self.try_move(0, 1):
                if soft:
                    self.score += 1
            else:
                self.fall_t = 0.0
                break

        if self.grounded():
            self.lock_t += dt
            if self.lock_t >= LOCK_DELAY:
                self.lock()
        else:
            self.lock_t = 0.0

    # ---- input a evento ----
    def keydown(self, key):
        if key == pygame.K_m:
            self.sfx.enabled = not self.sfx.enabled
            return
        if self.state == "menu":
            opts = self.menu_options()
            if key in (pygame.K_UP, pygame.K_w):
                self.menu_sel = (self.menu_sel - 1) % len(opts)
            elif key in (pygame.K_DOWN, pygame.K_s):
                self.menu_sel = (self.menu_sel + 1) % len(opts)
            elif opts[self.menu_sel] == "music" and key in KEYS_L:
                self.adjust_music(-5)
            elif opts[self.menu_sel] == "music" and key in KEYS_R:
                self.adjust_music(5)
            elif opts[self.menu_sel] == "sfx" and key in KEYS_L:
                self.adjust_sfx(-5)
            elif opts[self.menu_sel] == "sfx" and key in KEYS_R:
                self.adjust_sfx(5)
            elif key in (pygame.K_RETURN, pygame.K_SPACE):
                self.menu_activate(opts[self.menu_sel])
            return
        if key == pygame.K_r or (self.state == "over" and key in (pygame.K_RETURN, pygame.K_SPACE)):
            self.reset()
            return
        if key in (pygame.K_p, pygame.K_ESCAPE) and self.state in ("play", "clearing"):
            if self.paused and self.pause_in_options:
                self.pause_in_options = False
                self.pause_sel = 0
                return
            self.paused = not self.paused
            if self.paused:
                self.save_state()
            else:
                self.pause_in_options = False
            return
        if self.paused and self.state in ("play", "clearing"):
            opts = self.pause_options()
            if key in (pygame.K_UP, pygame.K_w):
                self.pause_sel = (self.pause_sel - 1) % len(opts)
            elif key in (pygame.K_DOWN, pygame.K_s):
                self.pause_sel = (self.pause_sel + 1) % len(opts)
            elif opts[self.pause_sel] == "music" and key in KEYS_L:
                self.adjust_music(-5)
            elif opts[self.pause_sel] == "music" and key in KEYS_R:
                self.adjust_music(5)
            elif opts[self.pause_sel] == "sfx" and key in KEYS_L:
                self.adjust_sfx(-5)
            elif opts[self.pause_sel] == "sfx" and key in KEYS_R:
                self.adjust_sfx(5)
            elif key in (pygame.K_RETURN, pygame.K_SPACE):
                self.pause_activate(opts[self.pause_sel])
            return
        if self.state != "play" or self.paused:
            return
        if key in KEYS_L:
            self.hdir, self.das_t, self.arr_t = -1, 0.0, 0.0
            self.try_move(-1, 0)
        elif key in KEYS_R:
            self.hdir, self.das_t, self.arr_t = 1, 0.0, 0.0
            self.try_move(1, 0)
        elif key in KEYS_ROT:
            self.rotate(1)
        elif key in KEYS_ROT_CCW:
            self.rotate(-1)
        elif key == pygame.K_SPACE:
            self.hard_drop()
        elif key in KEYS_HOLD:
            self.do_hold()

    # ---- disegno ----
    def draw(self, cv, board_bg):
        if self.state == "menu":
            self.draw_menu(cv)
            return
        self.draw_panels(cv)
        cv.blit(board_bg, (BOARD_X - uiscale(8), BOARD_Y - uiscale(8)))

        # blocchi bloccati
        p_clear = self.clear_t / CLEAR_TIME
        for gy in range(HID, H + HID):
            row = self.grid[gy]
            for x in range(W):
                col = row[x]
                if col is None:
                    continue
                pos = (BOARD_X + x * CELL, BOARD_Y + (gy - HID) * CELL)
                if self.state == "clearing" and gy in self.clear_rows:
                    if abs(x - 4.5) / 4.5 < p_clear:
                        continue
                    cv.blit(block_surf(col, CELL), pos)
                    cv.blit(white_flash(CELL, int(230 * (1 - p_clear))), pos)
                else:
                    sq = self.squash.get((x, gy))
                    if sq is None:
                        cv.blit(block_surf(col, CELL), pos)
                    else:
                        k = sq / SQUASH_T
                        h = max(1, int(CELL * (1 - 0.22 * math.sin(math.pi * k))))
                        cv.blit(pygame.transform.smoothscale(block_surf(col, CELL), (CELL, h)),
                                (pos[0], pos[1] + CELL - h))
                        cv.blit(white_flash(CELL, int(90 * (1 - k))), pos)

        # scie dell'hard drop
        for col_x, top, end, col, life, mx in self.trails:
            y0 = max(top, HID)
            if end <= y0:
                continue
            h = (end - y0) * CELL
            s = pygame.Surface((CELL - 8, h), pygame.SRCALPHA)
            bands = 10
            for i in range(bands):
                a = int(150 * (life / mx) * ((i + 1) / bands) ** 2)
                pygame.draw.rect(s, (*shade(col, 1.3), a), (0, h * i // bands, CELL - 8, h // bands + 1))
            cv.blit(s, (BOARD_X + col_x * CELL + 4, BOARD_Y + (y0 - HID) * CELL))

        # ghost + pezzo corrente
        if self.state == "play":
            p = self.piece
            col = COLORS[p.name]
            gy = self.ghost_y()
            gs = block_surf(col, CELL, "ghost")
            if self.grounded():                # il ghost pulsa quando il pezzo sta per bloccarsi
                gs = gs.copy()
                gs.set_alpha(int(150 + 105 * math.sin(self.t * 16)))
            for cx, cy in SHAPES[p.name][p.rot]:
                if gy + cy >= HID:
                    cv.blit(gs, (BOARD_X + (p.x + cx) * CELL, BOARD_Y + (gy + cy - HID) * CELL))
            vx, vy = p.ox * CELL, p.oy * CELL
            for x, y in p.cells():
                if y >= HID:
                    px = int(round(BOARD_X + x * CELL + vx))
                    py = int(round(BOARD_Y + (y - HID) * CELL + vy))
                    cv.blit(glow_surf(col, CELL), (px + CELL // 2 - CELL, py + CELL // 2 - CELL))
            for x, y in p.cells():
                if y >= HID:
                    px = int(round(BOARD_X + x * CELL + vx))
                    py = int(round(BOARD_Y + (y - HID) * CELL + vy))
                    cv.blit(block_surf(col, CELL), (px, py))

        # particelle
        for x, y, _vx, _vy, life, mx, col in self.particles:
            k = life / mx
            s = max(2, int(7 * k))
            pygame.draw.rect(cv, (*shade(col, 1.2), int(255 * k)), (x - s / 2, y - s / 2, s, s), border_radius=2)

        # popup testuali
        cx, cy = BOARD_X + W * CELL // 2, BOARD_Y + H * CELL // 2 - uiscale(40)
        for text, color, dy, t in self.popups:
            a = int(255 * max(0.0, 1 - max(0.0, t - 0.7) / 0.6))
            draw_text(cv, F["mid"], text, color, (cx, cy + dy - t * uiscale(40)), "center", alpha=a)

        # overlay
        if self.state == "over":
            self.draw_overlay(cv, "GAME OVER", (255, 100, 100))
            draw_text(cv, F["mid"], f"Punteggio  {self.score:,}", TEXT_BRIGHT, (cx, cy + uiscale(50)), "center")
            if self.new_high:
                draw_text(cv, F["mid"], "NUOVO RECORD!", COLORS["O"], (cx, cy + uiscale(84)), "center")
            pulse = int(140 + 115 * math.sin(self.t * 4))
            draw_text(cv, F["small"], "INVIO per rigiocare", TEXT_BRIGHT, (cx, cy + uiscale(124)), "center", alpha=pulse)
        elif self.paused:
            prefix_shift = F["big"].size("   ")[0] // 2
            self.draw_overlay(cv, "PAUSA", TEXT_BRIGHT, x_offset=prefix_shift)
            opts = self.pause_options()
            labels = {"continua": "CONTINUA", "opzioni": "OPZIONI", "music": "MUSIC", "sfx": "SFX", "esci": "ESCI"}
            self.pause_sel = min(self.pause_sel, len(opts) - 1)
            self.pause_rects = []
            self.pause_music_rect = None
            self.pause_sfx_rect = None
            y = cy + uiscale(50)
            for i, opt in enumerate(opts):
                sel = (i == self.pause_sel)
                pulse = int(150 + 105 * math.sin(self.t * 3.5)) if sel else 235
                color = TEXT_BRIGHT if sel else TEXT_DIM
                if opt == "music":
                    rect, bar_rect = self.draw_slider_row(cv, cx, y, sel, color, pulse, "MUSIC", self.music_pct())
                    self.pause_music_rect = bar_rect
                elif opt == "sfx":
                    rect, bar_rect = self.draw_slider_row(cv, cx, y, sel, color, pulse, "SFX", self.sfx_pct())
                    self.pause_sfx_rect = bar_rect
                else:
                    text = ("> " if sel else "   ") + labels[opt]
                    rect = draw_text(cv, F["big"], text, color, (cx, y), "center", alpha=pulse)
                self.pause_rects.append((rect.inflate(uiscale(40), uiscale(14)), opt, i))
                y += uiscale(50)
            

    def draw_slider_row(self, cv, cx, y, sel, color, pulse, label, pct):
        """Disegna un'etichetta + uno slider orizzontale, e restituisce
        (rect_riga_per_selezione, rect_barra_per_i_click)."""
        text = ("> " if sel else "   ") + label
        label_r = draw_text(cv, F["big"], text, color, (cx - uiscale(90), y), "midright", alpha=pulse)
        bar_w, bar_h = uiscale(140), uiscale(14)
        bar = pygame.Rect(0, 0, bar_w, bar_h)
        bar.midleft = (cx - uiscale(60), label_r.centery)
        pygame.draw.rect(cv, (255, 255, 255, 40), bar, border_radius=bar_h // 2)
        fill = bar.copy()
        fill.width = max(bar_h, int(bar_w * (pct / 100.0)))
        pygame.draw.rect(cv, ACCENT if sel else TEXT_DIM, fill, border_radius=bar_h // 2)
        pygame.draw.rect(cv, TEXT_BRIGHT, bar, width=1, border_radius=bar_h // 2)
        draw_text(cv, F["small"], f"{pct}%", color, (bar.right + uiscale(14), label_r.centery),
                  "midleft", alpha=pulse)
        full_rect = label_r.union(bar)
        return full_rect, bar

    def apply_music_click(self, bar_rect, mx):
        """Imposta il volume musica in base al punto cliccato/trascinato dentro la barra."""
        if not bar_rect or bar_rect.width <= 0:
            return
        pct = max(0.0, min(1.0, (mx - bar_rect.x) / bar_rect.width))
        if self.music:
            self.music.set_volume(pct)
            self.on_settings_change()

    def apply_sfx_click(self, bar_rect, mx):
        """Imposta il volume effetti in base al punto cliccato/trascinato dentro la barra."""
        if not bar_rect or bar_rect.width <= 0:
            return
        pct = max(0.0, min(1.0, (mx - bar_rect.x) / bar_rect.width))
        if self.sfx:
            self.sfx.set_volume(pct)
            self.on_settings_change()

    def draw_overlay(self, cv, title, color, x_offset=0):
        ov = pygame.Surface((W * CELL + uiscale(16), H * CELL + uiscale(16)), pygame.SRCALPHA)
        pygame.draw.rect(ov, (0, 0, 0, 170), ov.get_rect(), border_radius=uiscale(12))
        cv.blit(ov, (BOARD_X - uiscale(8), BOARD_Y - uiscale(8)))
        draw_text(cv, F["big"], title, color,
                  (BOARD_X + W * CELL // 2 + x_offset, BOARD_Y + H * CELL // 2 - uiscale(40)), "center")

    def draw_panels(self, cv):
        # sinistra: HOLD + statistiche
        hold = pygame.Rect(uiscale(20), BOARD_Y - uiscale(8), uiscale(160), uiscale(130))
        panel(cv, hold, "HOLD")
        if self.hold:
            draw_preview(cv, self.hold, hold.centerx, hold.centery + uiscale(10), uiscale(24), dimmed=self.hold_used)
        stats = pygame.Rect(uiscale(20), BOARD_Y + uiscale(137), uiscale(160), H * CELL - uiscale(129))
        panel(cv, stats)
        items = (
            ("PUNTEGGIO", f"{int(self.disp_score):,}", TEXT_BRIGHT),
            ("RECORD", f"{max(self.high, self.score):,}", COLORS["O"]),
            ("LIVELLO", str(self.level()), COLORS["I"]),
            ("RIGHE", str(self.lines), COLORS["S"]),
        )
        y = stats.y + uiscale(18)
        for label, val, col in items:
            draw_text(cv, F["small"], label, TEXT_DIM, (stats.x + uiscale(16), y), shadow=False)
            draw_text(cv, F["big"], val, col, (stats.right - uiscale(16), y + uiscale(18)), "topright")
            y += uiscale(84)

        # now playing (nome traccia, scorrevole se troppo lungo per la colonna)
        now = self.now_playing_name()
        pad = uiscale(16)
        avail_w = stats.width - pad * 2
        label_y = stats.bottom - uiscale(34)
        name_y = label_y + uiscale(16)
        draw_text(cv, F["tiny"], "NOW PLAYING", TEXT_DIM, (stats.x + pad, label_y), shadow=False)
        name_surf = F["tiny"].render(now or "-", True, TEXT_BRIGHT)
        clip_rect = pygame.Rect(stats.x + pad, name_y, avail_w, name_surf.get_height())
        if name_surf.get_width() <= avail_w:
            cv.blit(name_surf, (clip_rect.x, name_y))
        else:
            old_clip = cv.get_clip()
            cv.set_clip(clip_rect)
            gap = uiscale(40)
            total_w = name_surf.get_width() + gap
            offset = (self.t * uiscale(30)) % total_w
            x = clip_rect.x - offset
            cv.blit(name_surf, (x, name_y))
            cv.blit(name_surf, (x + total_w, name_y))
            cv.set_clip(old_clip)

        # destra: NEXT + comandi
        nx = BOARD_X + W * CELL + uiscale(20)
        nxt = pygame.Rect(nx, BOARD_Y - uiscale(8), uiscale(160), uiscale(5 * 62 + 46))
        panel(cv, nxt, "NEXT")
        for i, name in enumerate(self.queue):
            size = uiscale(24) if i == 0 else uiscale(19)
            draw_preview(cv, name, nxt.centerx, nxt.y + uiscale(66) + i * uiscale(62), size)
        help_r = pygame.Rect(nx, nxt.bottom + uiscale(12), uiscale(160), H * CELL + uiscale(8) - nxt.height - uiscale(12))
        panel(cv, help_r, "COMANDI")
        lines = ("← → muovi", "↑ X ruota", "Z ruota indietro", "↓ soft drop", "SPAZIO hard drop", "C hold", "P pausa  M audio")
        for i, l in enumerate(lines):
            draw_text(cv, F["tiny"], l, TEXT_DIM, (help_r.x + uiscale(10), help_r.y + uiscale(36) + i * uiscale(22)), shadow=False)

    def draw_menu(self, cv):
        cx = WIN_W // 2
        letters = "TETRIS"
        names = ["I", "O", "T", "S", "Z", "L"]
        total = sum(F["title"].size(c)[0] + uiscale(6) for c in letters)
        x = cx - total // 2
        for i, c in enumerate(letters):
            img = F["title"].render(c, True, COLORS[names[i]])
            y = uiscale(140) + math.sin(self.t * 2.5 + i * 0.7) * uiscale(10)
            cv.blit(img, (x, y))
            x += img.get_width() + uiscale(6)
        draw_text(cv, F["mid"], "Il classico, in versione moderna", TEXT_DIM, (cx, uiscale(275)), "center")

        opts = self.menu_options()
        labels = {"continua": "CONTINUA", "nuova": "NUOVA PARTITA", "opzioni": "OPZIONI",
                  "music": "MUSIC", "sfx": "SFX", "esci": "ESCI"}
        self.menu_sel = min(self.menu_sel, len(opts) - 1)
        self.menu_rects = []
        self.menu_music_rect = None
        self.menu_sfx_rect = None
        y = uiscale(370)
        for i, opt in enumerate(opts):
            sel = (i == self.menu_sel)
            pulse = int(150 + 105 * math.sin(self.t * 3.5)) if sel else 235
            color = TEXT_BRIGHT if sel else TEXT_DIM
            if opt == "music":
                rect, bar_rect = self.draw_slider_row(cv, cx, y, sel, color, pulse, "MUSIC", self.music_pct())
                self.menu_music_rect = bar_rect
            elif opt == "sfx":
                rect, bar_rect = self.draw_slider_row(cv, cx, y, sel, color, pulse, "SFX", self.sfx_pct())
                self.menu_sfx_rect = bar_rect
            else:
                text = ("> " if sel else "   ") + labels[opt]
                rect = draw_text(cv, F["big"], text, color, (cx, y), "center", alpha=pulse)
            self.menu_rects.append((rect.inflate(uiscale(40), uiscale(14)), opt, i))
            y += uiscale(50)

        draw_text(cv, F["small"], f"Record: {self.high:,}", COLORS["O"], (cx, y + uiscale(6)), "center")
        


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    pygame.init()

    settings = load_settings()
    fullscreen = settings["fullscreen"]

    def apply_display_mode():
        
        pygame.display.quit()
        pygame.display.init()
        if fullscreen:
            surf = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            surf = pygame.display.set_mode((BASE_WIN_W, BASE_WIN_H), pygame.RESIZABLE)
        pygame.display.set_caption("Tetris")
        return surf

    screen = apply_display_mode()
    clock = pygame.time.Clock()

    joypad = JoypadManager()
    joypad.install()

    music_folder = Path(__file__).resolve().parent.parent / "assets" / "music"
    music = MusicManager(music_folder, volume=settings["volume"])   # cerca .it/.xm/.mod/.s3m/.ogg/.mp3/.wav qui dentro
    music.play()

    def persist_settings():
        save_settings({"fullscreen": fullscreen, "volume": music.volume, "sfx_volume": game.sfx.volume})

    def toggle_fullscreen():
        nonlocal screen, fullscreen
        fullscreen = not fullscreen
        screen = apply_display_mode()
        persist_settings()

    fam = "segoeui,helveticaneue,arial,dejavusans"
    fam_cmds = "consolascondensed,cascadiacode,jetbrainsmono,consolas,menlo,couriernew,dejavusansmono"
    layout = {"scale": None, "board_bg": None, "canvas": None}

    def rebuild_layout(scale):
        
        global CELL, BOARD_X, BOARD_Y, WIN_W, WIN_H, UI_SCALE
        CELL = max(8, round(BASE_CELL * scale))
        BOARD_X = round(BASE_BOARD_X * scale)
        BOARD_Y = round(BASE_BOARD_Y * scale)
        WIN_W = round(BASE_WIN_W * scale)
        WIN_H = H * CELL + 2 * BOARD_Y
        UI_SCALE = scale
        for name, size in BASE_FONTS.items():
            
            f = fam_cmds if name == "tiny" else fam
            eff_size = size * 0.72 if name == "tiny" else size
            F[name] = pygame.font.SysFont(f, max(8, round(eff_size * scale)), bold=(name != "tiny"))
        layout["board_bg"] = make_board_bg()
        layout["canvas"] = pygame.Surface((WIN_W, WIN_H), pygame.SRCALPHA)
        layout["scale"] = scale

    def ensure_layout(sw, sh):
        target = max(MIN_SCALE, min(MAX_SCALE, min(sw / BASE_WIN_W, sh / BASE_WIN_H)))
        if layout["scale"] != target:
            rebuild_layout(target)
        return layout["board_bg"], layout["canvas"]

    board_bg, canvas = ensure_layout(*screen.get_size())

    # sfondo "ambient" che riempie tutto lo schermo dietro al riquadro di gioco,
    # rigenerato solo quando cambiano le dimensioni reali della finestra/schermo
    ambient = {"size": None, "bg": None, "fx": None, "squares": None}

    def ensure_ambient(sw, sh):
        if ambient["size"] == (sw, sh):
            return
        ambient["size"] = (sw, sh)
        ambient["bg"] = make_background(sw, sh)
        ambient["fx"] = pygame.Surface((sw, sh), pygame.SRCALPHA)
        n = min(90, max(22, (sw * sh) // 28000))
        ambient["squares"] = [[random.uniform(0, sw), random.uniform(0, sh), random.randint(14, 60),
                                random.uniform(8, 32), random.choice(list(COLORS.values()))] for _ in range(n)]

    game = Game(load_high(), Sfx(volume=settings["sfx_volume"]), music, persist_settings)

    def quit_game():
        game.save_state()
        game.finalize_high()
        music.stop()
        pygame.quit()
        sys.exit()

    while True:
        dt = min(clock.tick(FPS) / 1000.0, 0.05)
        sw, sh = screen.get_size()
        ensure_ambient(sw, sh)
        board_bg, canvas = ensure_layout(sw, sh)
        fs_btn = pygame.Rect(sw - 44, 12, 32, 32)

        
        m_scale = min(sw / WIN_W, sh / WIN_H)
        m_sx0 = (sw - WIN_W * m_scale) / 2
        m_sy0 = (sh - WIN_H * m_scale) / 2

        def to_canvas(pos):
            return ((pos[0] - m_sx0) / m_scale, (pos[1] - m_sy0) / m_scale)

        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                quit_game()
            elif e.type == pygame.KEYDOWN:
                if e.key == pygame.K_F11:
                    toggle_fullscreen()
                    continue
                if e.key == pygame.K_ESCAPE and game.state == "menu":
                    if game.menu_in_options:
                        game.menu_in_options = False
                        game.menu_sel = 0
                    else:
                        quit_game()
                    continue
                game.keydown(e.key)
            elif e.type == pygame.MOUSEMOTION and (game.state == "menu" or game.paused):
                mc = to_canvas(e.pos)
                music_rect = game.menu_music_rect if game.state == "menu" else game.pause_music_rect
                sfx_rect = game.menu_sfx_rect if game.state == "menu" else game.pause_sfx_rect
                if e.buttons[0] and music_rect and music_rect.collidepoint(mc):
                    game.apply_music_click(music_rect, mc[0])
                    continue
                if e.buttons[0] and sfx_rect and sfx_rect.collidepoint(mc):
                    game.apply_sfx_click(sfx_rect, mc[0])
                    continue
                rects = game.menu_rects if game.state == "menu" else game.pause_rects
                for rect, _opt, i in rects:
                    if rect.collidepoint(mc):
                        if game.state == "menu":
                            game.menu_sel = i
                        else:
                            game.pause_sel = i
                        break
            elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                if fs_btn.collidepoint(e.pos):
                    toggle_fullscreen()
                elif game.state == "menu":
                    mc = to_canvas(e.pos)
                    if game.menu_music_rect and game.menu_music_rect.collidepoint(mc):
                        game.apply_music_click(game.menu_music_rect, mc[0])
                    elif game.menu_sfx_rect and game.menu_sfx_rect.collidepoint(mc):
                        game.apply_sfx_click(game.menu_sfx_rect, mc[0])
                    else:
                        for rect, opt, i in game.menu_rects:
                            if rect.collidepoint(mc):
                                game.menu_sel = i
                                game.menu_activate(opt)
                                break
                elif game.paused:
                    mc = to_canvas(e.pos)
                    if game.pause_music_rect and game.pause_music_rect.collidepoint(mc):
                        game.apply_music_click(game.pause_music_rect, mc[0])
                    elif game.pause_sfx_rect and game.pause_sfx_rect.collidepoint(mc):
                        game.apply_sfx_click(game.pause_sfx_rect, mc[0])
                    else:
                        for rect, opt, i in game.pause_rects:
                            if rect.collidepoint(mc):
                                game.pause_sel = i
                                game.pause_activate(opt)
                                break
            elif e.type == pygame.WINDOWFOCUSLOST and game.state == "play":
                game.paused = True
                game.save_state()
            else:
                music.handle_event(e)
                joypad.handle_event(e, game)

        if game.want_quit:
            quit_game()

        joypad.update(dt, game)
        music.set_muted(not game.sfx.enabled)
        game.update(dt)

        # sfondo animato a piena finestra/schermo (mai barre nere)
        screen.blit(ambient["bg"], (0, 0))
        fxs = ambient["fx"]
        fxs.fill((0, 0, 0, 0))
        for s in ambient["squares"]:
            s[1] -= s[3] * dt
            if s[1] < -s[2]:
                s[0], s[1] = random.uniform(0, sw), sh + s[2]
            pygame.draw.rect(fxs, (*s[4], 22), (s[0], s[1], s[2], s[2]), width=2, border_radius=8)
        screen.blit(fxs, (0, 0))

        canvas.fill((0, 0, 0, 0))
        game.draw(canvas, board_bg)
        shk = int(game.shake)
        off = (random.randint(-shk, shk), random.randint(-shk, shk)) if shk else (0, 0)
        frame, pos = canvas, off
        if game.zoom > 0.002:                  # piccolo zoom della camera sulle righe cancellate
            zw, zh = int(WIN_W * (1 + game.zoom)), int(WIN_H * (1 + game.zoom))
            frame = pygame.transform.smoothscale(canvas, (zw, zh))
            pos = (off[0] - (zw - WIN_W) // 2, off[1] - (zh - WIN_H) // 2)
        if game.aber > 0.02:                   # aberrazione cromatica: frange rossa e blu
            a = max(1, int(7 * game.aber))
            work = frame.copy()
            for shift, mask in ((-a, (255, 0, 0, 255)), (a, (0, 0, 255, 255))):
                ch = frame.copy()
                ch.fill(mask, special_flags=pygame.BLEND_RGBA_MULT)
                work.blit(ch, (shift, 0), special_flags=pygame.BLEND_RGB_ADD)
            frame = work

        # scala il riquadro di gioco per riempire lo schermo mantenendo le proporzioni
        # (a finestra "di default" scale == 1 e il risultato è identico a prima)
        scale = min(sw / WIN_W, sh / WIN_H)
        box_w, box_h = WIN_W * scale, WIN_H * scale
        sx0, sy0 = (sw - box_w) / 2, (sh - box_h) / 2

        pad = 14
        frame_rect = pygame.Rect(int(sx0 - pad), int(sy0 - pad), int(box_w + 2 * pad), int(box_h + 2 * pad))
        pygame.draw.rect(screen, (9, 10, 20), frame_rect, border_radius=18)
        pygame.draw.rect(screen, ACCENT, frame_rect, width=2, border_radius=18)

        fw, fh = frame.get_size()
        scaled = pygame.transform.smoothscale(frame, (max(1, int(fw * scale)), max(1, int(fh * scale))))
        screen.blit(scaled, (sx0 + pos[0] * scale, sy0 + pos[1] * scale))

        hovered = fs_btn.collidepoint(pygame.mouse.get_pos())
        draw_fullscreen_button(screen, fs_btn, hovered, fullscreen)
        pygame.display.flip()


if __name__ == "__main__":
    main()
