"""
modes.py - modalita' di gioco extra per tetris.py

Ogni modalita' e' una piccola classe (Mode) con degli "hook" che Game chiama
nei punti giusti (reset, lock, righe completate, update, disegno...). La
logica di gioco di base (SRS, DAS/ARR, hold, T-Spin...) resta in tetris.py.

Modalita'
---------
  classic   Infinita, come prima.
  sprint    40 linee il piu' in fretta possibile (classifica a tempo).
  ultra     2 minuti, piu' punti possibile (classifica a punteggio).
  marathon  15 livelli / 150 linee: se le completi hai vinto.
  zen       Nessun game over (il campo si svuota). +/- cambia livello:
            ideale per provare sfondi (B) e musica.
  cheese    10 righe sporche da scavare, vince chi finisce prima.
  2099      Caos: eventi casuali ogni 7-11 pezzi: gravita' invertita,
            pezzi glitchati, bombe (area 5x5), laser (riga intera),
            overclock (caduta x2.5).

Classifiche: records.json accanto al gioco (top 10 per modalita', ne mostra 5).

Integrazione in tetris.py (gia' applicata nel file fornito):
    import modes as gm
    gm.register_pieces(SHAPES, COLORS)          # dopo la creazione di SHAPES
    gm.bind_ui(F, draw_text, uiscale, lambda: (BOARD_X, BOARD_Y, CELL))
    game.mode_id = settings["mode"]
"""
import json
import math
import random
import time
from pathlib import Path

import pygame

# devono coincidere con W, H, HID di tetris.py (non si importa tetris per
# evitare import circolari quando viene lanciato come __main__)
COLS, ROWS, HIDDEN = 10, 20, 2

RECORDS_FILE = Path(__file__).with_name("records.json")
KEEP, SHOW = 10, 5

TEXT_DIM = (150, 158, 190)
TEXT_BRIGHT = (245, 247, 255)
NEON_CYAN = (0, 240, 255)
NEON_MAGENTA = (255, 45, 170)
NEON_AMBER = (255, 214, 90)
C_I, C_O, C_S, C_T, C_Z = (34, 211, 238), (250, 204, 21), (74, 222, 128), (192, 132, 252), (248, 113, 113)
GARBAGE_COLOR = (112, 118, 140)
LASER_COLOR = (235, 250, 255)


# ----------------------------------------------------------------------------
# Collegamento con la UI di tetris.py (font, draw_text, scala, geometria board)
# ----------------------------------------------------------------------------
class _UI:
    F = None
    text = None
    scale = staticmethod(lambda v: v)
    geom = staticmethod(lambda: (200, 30, 32))


UI = _UI()


def bind_ui(fonts, draw_text, uiscale, geometry):
    UI.F, UI.text, UI.scale, UI.geom = fonts, draw_text, uiscale, geometry


def fmt_time(sec):
    sec = max(0.0, float(sec))
    m = int(sec // 60)
    return f"{m}:{sec - 60 * m:05.2f}"


# ----------------------------------------------------------------------------
# Pezzi speciali (usati da 2099): registrati nei dizionari SHAPES / COLORS
# ----------------------------------------------------------------------------
SPECIAL = {
    "B": [(1, 1)],                                           # bomba
    "R": [(1, 1)],                                           # laser
    "G1": [(0, 0), (2, 0), (1, 1), (0, 2), (2, 2)],          # X (solo diagonali)
    "G2": [(0, 0), (1, 0), (1, 1), (1, 2), (2, 2)],          # pentomino S
    "G3": [(1, 0), (0, 1), (1, 1), (2, 1), (1, 2)],          # croce
    "G4": [(0, 0), (2, 0), (1, 1), (2, 2)],                  # scollegato
}
GLITCH = ("G1", "G2", "G3", "G4")
SPECIAL_COLORS = {"B": (255, 120, 40), "R": LASER_COLOR, **{g: NEON_MAGENTA for g in GLITCH}}


def register_pieces(shapes, colors):
    """Aggiunge i pezzi speciali (box 3x3, stessa rotazione SRS dei pezzi normali)."""
    for name, cells in SPECIAL.items():
        rots = [cells]
        for _ in range(3):
            rots.append([(2 - y, x) for x, y in rots[-1]])
        shapes[name] = rots
        colors[name] = SPECIAL_COLORS[name]


# ----------------------------------------------------------------------------
# Classifiche
# ----------------------------------------------------------------------------
class Records:
    KINDS = {"sprint": "time", "cheese": "time", "ultra": "score", "marathon": "score", "2099": "score"}

    def __init__(self, path=RECORDS_FILE):
        self.path = Path(path)
        self.data = {}
        try:
            raw = json.loads(self.path.read_text())
            if isinstance(raw, dict):
                self.data = raw
        except (OSError, ValueError):
            pass

    def _save(self):
        try:
            self.path.write_text(json.dumps(self.data))
        except OSError:
            pass

    def top(self, mode_id, n=SHOW):
        return list(self.data.get(mode_id, []))[:n]

    def best(self, mode_id):
        lst = self.data.get(mode_id)
        return lst[0] if lst else None

    def submit(self, mode_id, value, extra=None):
        """Inserisce un risultato. Ritorna la posizione (0 = record) o None."""
        kind = self.KINDS.get(mode_id)
        if not kind:
            return None
        entry = {"value": value, "date": time.strftime("%d/%m/%y")}
        entry.update(extra or {})
        lst = self.data.setdefault(mode_id, [])
        lst.append(entry)
        lst.sort(key=lambda e: e["value"], reverse=(kind == "score"))   # stabile: a pari merito resta sotto
        del lst[KEEP:]
        rank = next((i for i, e in enumerate(lst) if e is entry), None)
        self._save()
        return rank

    def label(self, mode_id):
        if mode_id not in self.KINDS:
            return None
        b = self.best(mode_id)
        if not b:
            return "NO RECORD YET"
        what = "BEST TIME" if self.KINDS[mode_id] == "time" else "BEST SCORE"
        return f"{what}  {format_value(mode_id, b['value'])}"


def format_value(mode_id, value):
    if Records.KINDS.get(mode_id) == "time":
        return fmt_time(value)
    return f"{int(value):,}"


# ----------------------------------------------------------------------------
# Classe base
# ----------------------------------------------------------------------------
class Mode:
    id = "base"
    name = "BASE"
    long_name = "BASE"
    desc = ""
    COUNTDOWN = 0.0          # secondi di 3-2-1 prima di iniziare
    counts_high = False      # usa l'high score globale (highscore.json)
    has_result = False       # a fine partita mostra schermata risultati + classifica

    def __init__(self):
        self.elapsed = 0.0
        self.pieces = 0
        self.countdown = self.COUNTDOWN
        self.go_t = 0.0
        self.done = None     # None | "win" | "lose"
        self.result = None

    # ---- hook di gioco ----
    def setup(self, game):
        pass

    def level(self, game):
        return game.lines // 10 + 1

    def gravity_mult(self, game):
        return 1.0

    def update(self, game, dt):
        """Ritorna True mentre il conto alla rovescia e' in corso."""
        if self.go_t > 0:
            self.go_t = max(0.0, self.go_t - dt)
        if self.countdown > 0:
            prev = math.ceil(self.countdown)
            self.countdown = max(0.0, self.countdown - dt)
            cur = math.ceil(self.countdown)
            if cur != prev:
                game.sfx.play("level" if cur == 0 else "hold")
                if cur == 0:
                    self.go_t = 0.7
            return True
        if not self.done:                    # il tempo si ferma all'ultima linea
            self.elapsed += dt
        return False

    def keydown(self, game, key):
        return False

    def on_lock(self, game, piece):
        self.pieces += 1

    def after_write(self, game, piece, cells):
        pass

    def on_lines(self, game, n, full_rows, tspin, perfect):
        pass

    def on_top_out(self, game):
        """True = gestito dalla modalita' (niente game over)."""
        return False

    # ---- HUD ----
    def hud_items(self, game):
        return None

    def hints(self):
        return ()

    def post_board(self, game, cv, rect):
        pass

    def draw_overlay(self, game, cv):
        bx, by, cell = UI.geom()
        cx = bx + COLS * cell // 2
        cy = by + ROWS * cell // 2 - UI.scale(40)
        if self.countdown > 0:
            n = math.ceil(self.countdown)
            a = int(255 * (1 - 0.8 * (n - self.countdown)))
            UI.text(cv, UI.F["title"], str(n), NEON_CYAN, (cx, cy), "center", alpha=a)
        elif self.go_t > 0:
            UI.text(cv, UI.F["title"], "GO!", NEON_AMBER, (cx, cy), "center", alpha=int(255 * self.go_t / 0.7))

    # ---- fine partita ----
    def record_value(self, game, win):
        return None

    def record_extra(self, game):
        return {"pieces": self.pieces}

    def title(self, win):
        return "VICTORY!" if win else "GAME OVER"

    def result_stats(self, game, win):
        return []

    def finish(self, game):
        if not self.has_result:
            return
        win = self.done == "win"
        value = self.record_value(game, win)
        rank = game.records.submit(self.id, value, self.record_extra(game)) if value is not None else None
        self.result = {"title": self.title(win), "win": win,
                       "stats": self.result_stats(game, win), "rank": rank}

    def draw_result(self, game, cv, cx, cy):
        res, F, s = self.result, UI.F, UI.scale
        y = cy + s(38)
        for text, color in res["stats"]:
            UI.text(cv, F["mid"], text, color, (cx, y), "center")
            y += s(30)
        if res["rank"] == 0:
            UI.text(cv, F["mid"], "NEW RECORD!", NEON_AMBER, (cx, y), "center")
            y += s(30)
        if self.id in Records.KINDS:
            y += s(10)
            UI.text(cv, F["small"], "// TOP 5", TEXT_DIM, (cx, y), "center", shadow=False)
            y += s(24)
            for i, e in enumerate(game.records.top(self.id)):
                hl = (i == res["rank"])
                txt = f"{'>' if hl else ' '} {i + 1}.  {format_value(self.id, e['value'])}   {e.get('date', '')}"
                UI.text(cv, F["small"], txt, NEON_CYAN if hl else TEXT_BRIGHT, (cx, y), "center", shadow=False)
                y += s(22)
        pulse = int(140 + 115 * math.sin(game.t * 4))
        UI.text(cv, F["small"], "ENTER retry   /   ESC menu", TEXT_BRIGHT, (cx, y + s(18)), "center", alpha=pulse)

    # ---- persistenza (continua partita) ----
    def to_dict(self):
        return {"elapsed": self.elapsed, "pieces": self.pieces}

    def from_dict(self, d):
        self.elapsed = float(d.get("elapsed", 0.0))
        self.pieces = int(d.get("pieces", 0))


def _best_text(game, mode_id, fmt):
    b = game.records.best(mode_id)
    return fmt(b["value"]) if b else "--"


# ----------------------------------------------------------------------------
# Classic
# ----------------------------------------------------------------------------
class ClassicMode(Mode):
    id, name, long_name = "classic", "CLASSIC", "CLASSIC"
    desc = "ENDLESS. SURVIVE AS LONG AS YOU CAN."
    counts_high = True


# ----------------------------------------------------------------------------
# Sprint 40 linee
# ----------------------------------------------------------------------------
class SprintMode(Mode):
    id, name, long_name = "sprint", "SPRINT", "SPRINT 40L"
    desc = "CLEAR 40 LINES AS FAST AS YOU CAN."
    COUNTDOWN = 3.0
    has_result = True
    GOAL = 40

    def on_lines(self, game, n, full_rows, tspin, perfect):
        if game.lines >= self.GOAL:
            self.done = "win"

    def hud_items(self, game):
        return [("TIME", fmt_time(self.elapsed), TEXT_BRIGHT),
                ("LINES", f"{min(game.lines, self.GOAL)}/{self.GOAL}", C_S),
                ("BEST", _best_text(game, self.id, fmt_time), C_O),
                ("PIECES", str(self.pieces), C_I)]

    def record_value(self, game, win):
        return round(self.elapsed, 2) if win else None

    def title(self, win):
        return "FINISH!" if win else "GAME OVER"

    def result_stats(self, game, win):
        if win:
            return [(f"Time  {fmt_time(self.elapsed)}", TEXT_BRIGHT), (f"Pieces  {self.pieces}", TEXT_DIM)]
        return [(f"Lines  {game.lines} / {self.GOAL}", TEXT_BRIGHT)]


# ----------------------------------------------------------------------------
# Ultra 2 minuti
# ----------------------------------------------------------------------------
class UltraMode(Mode):
    id, name, long_name = "ultra", "ULTRA", "ULTRA 2:00"
    desc = "SCORE AS MUCH AS YOU CAN IN 2 MINUTES."
    COUNTDOWN = 3.0
    has_result = True
    LIMIT = 120.0

    def update(self, game, dt):
        if super().update(game, dt):
            return True
        if not self.done and self.elapsed >= self.LIMIT:
            self.elapsed = self.LIMIT
            self.done = "win"
        return False

    def hud_items(self, game):
        return [("TIME LEFT", fmt_time(self.LIMIT - self.elapsed), TEXT_BRIGHT),
                ("SCORE", f"{int(game.disp_score):,}", C_O),
                ("BEST", _best_text(game, self.id, lambda v: f"{int(v):,}"), C_T),
                ("LINES", str(game.lines), C_S)]

    def record_value(self, game, win):
        return game.score if game.score > 0 else None

    def title(self, win):
        return "TIME UP!" if win else "GAME OVER"

    def result_stats(self, game, win):
        return [(f"Score  {game.score:,}", TEXT_BRIGHT), (f"Lines  {game.lines}   Pieces  {self.pieces}", TEXT_DIM)]


# ----------------------------------------------------------------------------
# Marathon: livelli finiti, vinci a 150 linee
# ----------------------------------------------------------------------------
class MarathonMode(Mode):
    id, name, long_name = "marathon", "MARATHON", "MARATHON"
    desc = "15 LEVELS. CLEAR 150 LINES TO WIN."
    COUNTDOWN = 3.0
    has_result = True
    MAX_LEVEL, GOAL = 15, 150

    def level(self, game):
        return min(self.MAX_LEVEL, game.lines // 10 + 1)

    def on_lines(self, game, n, full_rows, tspin, perfect):
        if game.lines >= self.GOAL:
            self.done = "win"

    def hud_items(self, game):
        return [("SCORE", f"{int(game.disp_score):,}", TEXT_BRIGHT),
                ("BEST", _best_text(game, self.id, lambda v: f"{int(v):,}"), C_O),
                ("LEVEL", f"{self.level(game)}/{self.MAX_LEVEL}", C_I),
                ("LINES", f"{min(game.lines, self.GOAL)}/{self.GOAL}", C_S)]

    def record_value(self, game, win):
        return game.score if game.score > 0 else None

    def record_extra(self, game):
        return {"lines": game.lines, "win": bool(self.done == "win"), "time": round(self.elapsed, 1)}

    def title(self, win):
        return "VICTORY!" if win else "GAME OVER"

    def result_stats(self, game, win):
        return [(f"Score  {game.score:,}", TEXT_BRIGHT),
                (f"Lines  {min(game.lines, self.GOAL)}/{self.GOAL}   Time  {fmt_time(self.elapsed)}", TEXT_DIM)]


# ----------------------------------------------------------------------------
# Zen / Practice
# ----------------------------------------------------------------------------
class ZenMode(Mode):
    id, name, long_name = "zen", "ZEN", "ZEN"
    desc = "NO GAME OVER. + / - CHANGES LEVEL. B = BACKGROUND."

    def __init__(self):
        super().__init__()
        self.zen_level = 1

    def level(self, game):
        return self.zen_level

    def keydown(self, game, key):
        d = 1 if key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS) else \
            -1 if key in (pygame.K_MINUS, pygame.K_KP_MINUS) else 0
        if d:
            new = max(1, min(20, self.zen_level + d))
            if new != self.zen_level:
                self.zen_level = new
                game._popup(f"LEVEL {new}", C_S, -60)
            return True
        return False

    def on_top_out(self, game):
        for y, row in enumerate(game.grid):
            if y < HIDDEN:
                continue
            for x, c in enumerate(row):
                if c is not None:
                    game.burst_cell(x, y, c, 1)
        game.grid[:] = [[None] * COLS for _ in range(ROWS + HIDDEN)]
        game.squash.clear()
        game._popup("BOARD RESET", C_S, -60)
        game.sfx.play("clear")
        game.shake, game.aber = 8, 0.5
        return True

    def hud_items(self, game):
        return [("LEVEL", str(self.zen_level), C_I),
                ("LINES", str(game.lines), C_S),
                ("SCORE", f"{int(game.disp_score):,}", TEXT_BRIGHT),
                ("TIME", fmt_time(self.elapsed), C_O)]

    def hints(self):
        return ("+ / -  level", "B  background")

    def to_dict(self):
        d = super().to_dict()
        d["zen_level"] = self.zen_level
        return d

    def from_dict(self, d):
        super().from_dict(d)
        self.zen_level = max(1, min(20, int(d.get("zen_level", 1))))


# ----------------------------------------------------------------------------
# Cheese race: scava le righe sporche
# ----------------------------------------------------------------------------
class CheeseMode(Mode):
    id, name, long_name = "cheese", "CHEESE", "CHEESE RACE"
    desc = "DIG THROUGH 10 GARBAGE ROWS. FASTEST WINS."
    COUNTDOWN = 3.0
    has_result = True
    GARBAGE_ROWS = 10

    def setup(self, game):
        hole = random.randrange(COLS)
        for i in range(self.GARBAGE_ROWS):
            if random.random() < 0.7:                 # per lo piu' buchi in colonne diverse
                hole = random.choice([c for c in range(COLS) if c != hole])
            y = ROWS + HIDDEN - 1 - i
            game.grid[y] = [GARBAGE_COLOR if x != hole else None for x in range(COLS)]

    @staticmethod
    def _remaining(game, skip=()):
        return sum(1 for y, row in enumerate(game.grid)
                   if y not in skip and any(c == GARBAGE_COLOR for c in row))

    def on_lines(self, game, n, full_rows, tspin, perfect):
        if self._remaining(game, set(full_rows)) == 0:
            self.done = "win"

    def hud_items(self, game):
        return [("TIME", fmt_time(self.elapsed), TEXT_BRIGHT),
                ("CHEESE LEFT", str(self._remaining(game)), C_Z),
                ("BEST", _best_text(game, self.id, fmt_time), C_O),
                ("PIECES", str(self.pieces), C_I)]

    def record_value(self, game, win):
        return round(self.elapsed, 2) if win else None

    def title(self, win):
        return "CLEARED!" if win else "GAME OVER"

    def result_stats(self, game, win):
        if win:
            return [(f"Time  {fmt_time(self.elapsed)}", TEXT_BRIGHT), (f"Pieces  {self.pieces}", TEXT_DIM)]
        return [(f"Rows left  {self._remaining(game)}", TEXT_BRIGHT)]


# ----------------------------------------------------------------------------
# 2099 CHAOS: eventi casuali
# ----------------------------------------------------------------------------
class Mode2099(Mode):
    id, name, long_name = "2099", "2099", "2099 CHAOS"
    desc = "RANDOM EVENTS: GRAVITY FLIP, GLITCHES, BOMBS, LASERS."
    has_result = True
    EVENTS = {
        "invert":    ("GRAVITY FLIP", NEON_CYAN),
        "overclock": ("OVERCLOCK", C_Z),
        "glitch":    ("GLITCH STORM", NEON_MAGENTA),
        "bomb":      ("BOMB INBOUND", (255, 120, 40)),
        "laser":     ("LASER INBOUND", LASER_COLOR),
    }
    INVERT_TIME, OVERCLOCK_TIME = 9.0, 8.0

    def __init__(self):
        super().__init__()
        self.next_in = random.randint(7, 11)
        self.inv_t = self.oc_t = 0.0
        self.flip_p, self.flip_target = 0.0, 0.0     # 0 = normale, 1 = capovolto
        self.banner, self.banner_t = "", 0.0

    def setup(self, game):
        self.next_in = random.randint(7, 11)

    # ---- eventi ----
    def on_lock(self, game, piece):
        super().on_lock(game, piece)
        self.next_in -= 1
        if self.next_in <= 0:
            self.fire(game)
            self.next_in = random.randint(7, 11)

    def fire(self, game, ev=None):
        if ev is None:
            ev = random.choice([e for e in self.EVENTS
                                if not (e == "invert" and self.inv_t > 0)
                                and not (e == "overclock" and self.oc_t > 0)])
        label, color = self.EVENTS[ev]
        if ev == "invert":
            self.inv_t, self.flip_target = self.INVERT_TIME, 1.0
        elif ev == "overclock":
            self.oc_t = self.OVERCLOCK_TIME
        elif ev == "glitch":
            self._inject(game, 2, None)
        elif ev == "bomb":
            self._inject(game, 1, "B")
        elif ev == "laser":
            self._inject(game, 1, "R")
        game._popup("EVENT: " + label, color, -90)
        game.aber, game.shake = max(game.aber, 0.9), max(game.shake, 6)
        game.sfx.play("level")
        self.banner, self.banner_t = label, 2.5

    @staticmethod
    def _inject(game, count, name):
        free = [i for i in range(1, min(4, len(game.queue))) if game.queue[i] not in SPECIAL]
        for i in random.sample(free, min(count, len(free))):
            game.queue[i] = name or random.choice(GLITCH)

    def gravity_mult(self, game):
        return 2.5 if self.oc_t > 0 else 1.0

    def update(self, game, dt):
        if super().update(game, dt):
            return True
        if self.inv_t > 0:
            self.inv_t -= dt
            if self.inv_t <= 0:
                self.flip_target = 0.0
                game._popup("GRAVITY NORMAL", C_S, -90)
        if self.oc_t > 0:
            self.oc_t -= dt
        if self.banner_t > 0:
            self.banner_t -= dt
        step = dt * 2.2
        self.flip_p += max(-step, min(step, self.flip_target - self.flip_p))
        return False

    # ---- pezzi speciali al lock ----
    def after_write(self, game, piece, cells):
        name = piece.name
        if name == "B":
            self._explode(game, cells[0])
        elif name == "R":
            self._laser(game, cells[0][1])
        elif name in GLITCH:
            game.aber, game.shake = max(game.aber, 0.7), max(game.shake, 5)

    def _explode(self, game, cell):
        cx, cy = cell
        destroyed = 0
        for y in range(cy - 2, cy + 3):
            for x in range(cx - 2, cx + 3):
                if 0 <= x < COLS and 0 <= y < ROWS + HIDDEN:
                    c = game.grid[y][x]
                    if c is not None:
                        destroyed += 1
                        game.grid[y][x] = None
                    game.burst_cell(x, y, c or (255, 150, 40), 2)
        game.score += destroyed * 15 * game.level()
        game.shake, game.aber, game.zoom = 14, 1.0, 0.02
        game.sfx.play("hard")
        game.sfx.play("tetris")
        game._popup("BOOM!", (255, 120, 40), 0)
        if destroyed:
            game._popup(f"{destroyed} BLOCKS", TEXT_BRIGHT, 34)

    def _laser(self, game, y):
        row = game.grid[y]
        for x in range(COLS):
            if row[x] is None:
                row[x] = LASER_COLOR       # riga piena -> la gestisce il normale line clear
        game._popup("LASER!", LASER_COLOR, 0)

    # ---- disegno ----
    def post_board(self, game, cv, rect):
        """Flip verticale (a 'card flip') della sola board: la logica non cambia,
        ma vista capovolta la gravita' sembra verso l'alto."""
        if self.flip_p <= 0.001:
            return
        rect = rect.clip(cv.get_rect())
        sub = cv.subsurface(rect).copy()
        k = math.cos(math.pi * self.flip_p)
        if k < 0:
            sub = pygame.transform.flip(sub, False, True)
        h = max(2, int(rect.height * abs(k)))
        if h != rect.height:
            sub = pygame.transform.smoothscale(sub, (rect.width, h))
        cv.fill((0, 0, 0, 0), rect)
        cv.blit(sub, (rect.x, rect.centery - h // 2))

    def draw_overlay(self, game, cv):
        bx, by, cell = UI.geom()
        cx = bx + COLS * cell // 2
        y = by + UI.scale(22)
        status = []
        if self.inv_t > 0:
            status.append((f"GRAVITY FLIP  {self.inv_t:0.0f}s", NEON_CYAN))
        if self.oc_t > 0:
            status.append((f"OVERCLOCK  {self.oc_t:0.0f}s", C_Z))
        for text, color in status:
            UI.text(cv, UI.F["small"], text, color, (cx, y), "center",
                    alpha=int(170 + 85 * math.sin(game.t * 8)))
            y += UI.scale(20)

    def hud_items(self, game):
        return [("SCORE", f"{int(game.disp_score):,}", TEXT_BRIGHT),
                ("LEVEL", str(game.level()), C_I),
                ("LINES", str(game.lines), C_S),
                ("NEXT EVENT", f"{max(0, self.next_in)} PCS", NEON_MAGENTA)]

    def hints(self):
        return ("ORANGE = BOMB", "WHITE = LASER")

    def record_value(self, game, win):
        return game.score if game.score > 0 else None

    def record_extra(self, game):
        return {"lines": game.lines, "time": round(self.elapsed, 1)}

    def result_stats(self, game, win):
        return [(f"Score  {game.score:,}", TEXT_BRIGHT),
                (f"Lines  {game.lines}   Time  {fmt_time(self.elapsed)}", TEXT_DIM)]

    def to_dict(self):
        d = super().to_dict()
        d["next_in"] = self.next_in
        return d

    def from_dict(self, d):
        super().from_dict(d)
        self.next_in = int(d.get("next_in", 8))


# ----------------------------------------------------------------------------
# Registro
# ----------------------------------------------------------------------------
MODE_ORDER = ("classic", "sprint", "ultra", "marathon", "zen", "cheese", "2099")
_REGISTRY = {c.id: c for c in (ClassicMode, SprintMode, UltraMode, MarathonMode, ZenMode, CheeseMode, Mode2099)}


def create_mode(mode_id):
    return _REGISTRY.get(mode_id, ClassicMode)()


def mode_name(mode_id):
    return _REGISTRY.get(mode_id, ClassicMode).name


def mode_desc(mode_id):
    return _REGISTRY.get(mode_id, ClassicMode).desc


def cycle_mode_id(mode_id, step=1):
    i = MODE_ORDER.index(mode_id) if mode_id in MODE_ORDER else 0
    return MODE_ORDER[(i + step) % len(MODE_ORDER)]
