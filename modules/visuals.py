"""
modules/visuals.py - sfondi dinamici audio-reattivi per tetris.py

Due parti, indipendenti dalla logica di gioco:

1. ANALISI AUDIO (in un thread in background, con cache su disco)
   - ogg/mp3/wav/flac: la traccia viene decodificata (pygame.mixer.Sound, o
     librosa se installata e pygame non ce la fa) e se ne calcola con numpy
     un inviluppo di energia per bassi / medi / alti a 100 Hz, piu' i colpi
     (kick sui bassi, snare sui medi, hat sugli alti) tramite spectral flux.
   - tracker (.it .xm .s3m .mod): il modulo viene eseguito offline da
     libopenmpt (via ctypes: nessun binding Python da installare, serve solo
     la libreria di sistema) e si leggono riga per riga le note di ogni
     canale. Gli strumenti vengono classificati dal nome del sample/strumento
     (kick/bd, snare/clap, hat/cymbal, bass...), quindi i colpi sono
     ESATTI, non stimati. Dove i nomi non dicono nulla si ricade sull'analisi
     audio del rendering di libopenmpt.
   - le tracce successive della playlist vengono analizzate in anticipo.

2. SFONDI (VisualsManager.draw): "synthwave" (sole + griglia prospettica),
   "starfield" (stelle in parallasse), "plasma" (numpy) e "squares" (i
   quadrati fluttuanti originali). La velocita' scala col livello; il kick
   fa pulsare, le medie spostano i colori, gli alti fanno brillare.

Uso in tetris.py (vedi tetris_patched.py):

    from visuals import VisualsManager
    ...
    visuals = VisualsManager(music, mode="synthwave", colors=list(COLORS.values()))
    ...
    # nel game loop, al posto dello sfondo ambient:
    visuals.update(dt, game)
    visuals.draw(screen)
    # negli eventi KEYDOWN:   visuals.handle_event(e)

Tasti: B = prossimo sfondo (Shift+B = precedente), F3 = HUD di debug,
[ e ] = anticipa/ritarda la sincronia di 10 ms (se senti i flash fuori tempo).

Provarlo da solo:   python visuals.py cartella_musica
"""
import colorsys
import ctypes
import ctypes.util
import math
import os
import random
import re
import sys
import threading
from pathlib import Path

import pygame

try:
    import numpy as np
except ImportError:              # senza numpy: niente analisi, niente plasma
    np = None

ENV_HZ = 100                      # risoluzione degli inviluppi (campioni/s)
CACHE_VERSION = 1
TRACKER_EXTS = {".it", ".xm", ".s3m", ".mod"}
MAX_RENDER_SECONDS = 1200         # tetto di sicurezza per moduli "infiniti"

MODES = ("synthwave", "starfield", "plasma", "squares")
LEVEL_HUES = (0.83, 0.55, 0.95, 0.10, 0.38, 0.70)   # tinta base per livello (ciclica)


# ============================================================================
# Utility colore
# ============================================================================
def _hsv(h, s, v):
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, max(0.0, min(1.0, s)), max(0.0, min(1.0, v)))
    return int(r * 255), int(g * 255), int(b * 255)


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _scale(c, f):
    return tuple(max(0, min(255, int(v * f))) for v in c)


def _q(c, step=8):
    return tuple((v // step) * step for v in c)


def _hsv_np(h, s, v):
    """hsv->rgb vettoriale (h,s,v array in 0..1) -> uint8 (N,3)."""
    h = (h % 1.0) * 6.0
    i = np.floor(h).astype(np.int32)
    f = h - i
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    i = i % 6
    r = np.select([i == 0, i == 1, i == 2, i == 3, i == 4], [v, q, p, p, t], v)
    g = np.select([i == 0, i == 1, i == 2, i == 3, i == 4], [t, v, v, q, p], p)
    b = np.select([i == 0, i == 1, i == 2, i == 3, i == 4], [p, p, t, v, v], q)
    return (np.stack([r, g, b], axis=1).clip(0, 1) * 255).astype(np.uint8)


# ============================================================================
# Risultato dell'analisi
# ============================================================================
class Analysis:
    """Inviluppi campionati a ENV_HZ.
    lo/mid/hi : energia continua 0..1 (bassi, medi, alti)
    tone      : "brillantezza" 0..1 (centroide spettrale) -> sposta i colori
    kick/snare/hat/bassnote/tick : impulsi sparsi (0 = niente, 0..1 = forza)
    exact     : ruoli ricavati dai dati del tracker (non stimati dall'audio)
    """
    FIELDS = ("lo", "mid", "hi", "tone", "kick", "snare", "hat", "bassnote", "tick")

    def __init__(self, n, duration):
        self.n = n
        self.duration = duration
        self.exact = set()
        for f in self.FIELDS:
            setattr(self, f, np.zeros(n, np.float32))

    def save(self, path):
        np.savez_compressed(path, duration=self.duration, exact=",".join(sorted(self.exact)),
                            **{f: getattr(self, f) for f in self.FIELDS})

    @classmethod
    def load(cls, path):
        d = np.load(path, allow_pickle=False)
        a = cls(len(d["lo"]), float(d["duration"]))
        for f in cls.FIELDS:
            setattr(a, f, d[f].astype(np.float32))
        ex = str(d["exact"])
        a.exact = set(ex.split(",")) if ex else set()
        return a


# ============================================================================
# Analisi spettrale (numpy)
# ============================================================================
def _normalize_db(a):
    db = 20.0 * np.log10(a + 1e-9)
    lo, hi = np.percentile(db, 5), np.percentile(db, 99)
    out = np.clip((db - lo) / (hi - lo + 1e-6), 0.0, 1.0)
    return (out ** 1.4).astype(np.float32)


def _pick_onsets(band, rate=ENV_HZ, min_gap=0.11, k=1.35, floor=0.06):
    """Peak picking con soglia adattiva sul flusso positivo di una banda."""
    d = band - np.roll(band, 3)
    d[:3] = 0.0
    flux = np.maximum(d, 0.0)
    w = int(rate * 0.6) | 1
    thr = np.convolve(flux, np.ones(w) / w, mode="same") * k + floor
    ref = np.percentile(flux, 99.5) + 1e-9
    out = np.zeros(len(flux), np.float32)
    gap, last = int(min_gap * rate), -10 ** 9
    for i in range(1, len(flux) - 1):
        if flux[i] > thr[i] and flux[i] >= flux[i - 1] and flux[i] >= flux[i + 1] and i - last >= gap:
            out[i] = min(1.0, max(0.4, flux[i] / ref))
            last = i
    return out


def _band_analysis(x, sr):
    hop = max(1, int(round(sr / ENV_HZ)))
    win = 2048 if sr >= 32000 else 1024
    n = max(1, len(x) // hop)
    xp = np.concatenate([np.zeros(win // 2, np.float32), x.astype(np.float32, copy=False),
                         np.zeros(win + hop, np.float32)])
    need = (n - 1) * hop + win
    if len(xp) < need:
        xp = np.concatenate([xp, np.zeros(need - len(xp), np.float32)])
    window = np.hanning(win).astype(np.float32)
    freqs = np.fft.rfftfreq(win, 1.0 / sr)
    m_lo = (freqs >= 30) & (freqs < 160)
    m_mid = (freqs >= 160) & (freqs < 2200)
    m_hi = (freqs >= 2200) & (freqs < min(14000.0, sr / 2))
    m_cent = (freqs >= 160) & (freqs < 8000)
    lo, mid, hi, cent = (np.zeros(n, np.float32) for _ in range(4))
    for f0 in range(0, n, 512):
        f1 = min(n, f0 + 512)
        seg = xp[f0 * hop: (f1 - 1) * hop + win]
        frames = np.lib.stride_tricks.sliding_window_view(seg, win)[::hop]
        mag = np.abs(np.fft.rfft(frames * window, axis=1))
        lo[f0:f1] = mag[:, m_lo].sum(1)
        mid[f0:f1] = mag[:, m_mid].sum(1)
        hi[f0:f1] = mag[:, m_hi].sum(1)
        mc = mag[:, m_cent]
        cent[f0:f1] = (mc * freqs[m_cent]).sum(1) / (mc.sum(1) + 1e-9)

    an = Analysis(n, len(x) / float(sr))
    an.lo, an.mid, an.hi = _normalize_db(lo), _normalize_db(mid), _normalize_db(hi)
    quiet = mid < np.percentile(mid, 5)
    tone = np.clip(np.log2(np.maximum(cent, 200.0) / 200.0) / 5.0, 0.0, 1.0)
    tone[quiet] = 0.5
    an.tone = np.convolve(tone, np.ones(9) / 9, mode="same").astype(np.float32)
    an.kick = _pick_onsets(an.lo)
    an.snare = _pick_onsets(an.mid, min_gap=0.15, k=1.5)
    an.hat = _pick_onsets(an.hi, min_gap=0.06, k=1.4)
    an.tick = an.kick.copy()
    return an


# ============================================================================
# Decodifica file normali
# ============================================================================
def _decode_samples(path):
    """-> (mono float32, sample rate) oppure None."""
    try:
        init = pygame.mixer.get_init()
        if init:
            snd = pygame.mixer.Sound(str(path))
            a = pygame.sndarray.array(snd)
            if a.dtype.kind == "i":
                a = a.astype(np.float32) / float(np.iinfo(a.dtype).max)
            elif a.dtype.kind == "u":
                a = (a.astype(np.float32) - 128.0) / 128.0
            else:
                a = a.astype(np.float32)
            if a.ndim == 2:
                a = a.mean(axis=1)
            return a, init[0]
    except Exception as e:       # formato non supportato, ecc.
        print(f"[visuals] pygame non decodifica {Path(path).name}: {e}")
    try:
        import librosa
        x, sr = librosa.load(str(path), sr=22050, mono=True)
        return x.astype(np.float32), sr
    except Exception as e:
        print(f"[visuals] impossibile analizzare {Path(path).name}: {e}")
    return None


# ============================================================================
# libopenmpt via ctypes (tracker)
# ============================================================================
_LIB = {"tried": False, "lib": None}


def _openmpt():
    if _LIB["tried"]:
        return _LIB["lib"]
    _LIB["tried"] = True
    here = Path(__file__).resolve().parent
    names = [ctypes.util.find_library("openmpt"), "libopenmpt.so.0", "libopenmpt-0.dll",
             "libopenmpt.dll", "libopenmpt.0.dylib", "libopenmpt.dylib",
             "/opt/homebrew/lib/libopenmpt.dylib", "/usr/local/lib/libopenmpt.dylib"]
    for pattern in ("libopenmpt*.dll", "libopenmpt*.dylib", "libopenmpt*.so*"):
        names += [str(p) for p in here.glob(pattern)]      # DLL messa accanto al gioco
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(str(here))
        except OSError:
            pass
    for name in names:
        if not name:
            continue
        try:
            lib = ctypes.CDLL(name)
            _LIB["lib"] = _setup_openmpt(lib)
            return _LIB["lib"]
        except (OSError, AttributeError):
            continue
    print("[visuals] libopenmpt non trovata: i tracker useranno lo sfondo senza sync "
          "(Linux: apt install libopenmpt0 | macOS: brew install libopenmpt | "
          "Windows: metti libopenmpt.dll accanto a visuals.py)")
    return None


def _setup_openmpt(lib):
    c_i32, c_vp = ctypes.c_int32, ctypes.c_void_p
    sig = {
        "openmpt_module_create_from_memory2": (c_vp, [ctypes.c_char_p, ctypes.c_size_t, c_vp, c_vp, c_vp, c_vp,
                                                     ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_char_p), c_vp]),
        "openmpt_module_destroy": (None, [c_vp]),
        "openmpt_module_set_repeat_count": (ctypes.c_int, [c_vp, c_i32]),
        "openmpt_module_read_float_mono": (ctypes.c_size_t, [c_vp, c_i32, ctypes.c_size_t, ctypes.POINTER(ctypes.c_float)]),
        "openmpt_module_get_current_row": (c_i32, [c_vp]),
        "openmpt_module_get_current_order": (c_i32, [c_vp]),
        "openmpt_module_get_current_pattern": (c_i32, [c_vp]),
        "openmpt_module_get_num_channels": (c_i32, [c_vp]),
        "openmpt_module_get_num_instruments": (c_i32, [c_vp]),
        "openmpt_module_get_num_samples": (c_i32, [c_vp]),
        "openmpt_module_get_instrument_name": (c_vp, [c_vp, c_i32]),
        "openmpt_module_get_sample_name": (c_vp, [c_vp, c_i32]),
        "openmpt_module_get_pattern_row_channel_command": (ctypes.c_uint8, [c_vp, c_i32, c_i32, c_i32, ctypes.c_int]),
        "openmpt_free_string": (None, [c_vp]),
    }
    for name, (res, args) in sig.items():
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = res, args
    return lib


# Ruoli dedotti dal nome di strumento/sample.
_ROLE_RE = (
    ("kick", re.compile(r"kick|kik|bass ?drum|bassdrum|\bbd\b|^bd|bd\d|\bbdrum|stomp|909k|808k", re.I)),
    ("snare", re.compile(r"snare|\bsn\b|^sn\d|\bsd\b|clap|rim ?shot|\bcp\b", re.I)),
    ("hat", re.compile(r"hi ?hat|hihat|\bhh\b|^hh|cymb|crash|\bride\b|\bcy\b|shaker|tamb|\boh\b|\bch\b", re.I)),
    ("bassnote", re.compile(r"bass|\bbs\b|^bs\d|\bsub\b|reese", re.I)),
)


def _role_for_name(name):
    for role, rx in _ROLE_RE:
        if rx.search(name):
            return role
    return None


def _render_tracker(path, sr=44100):
    """Esegue il modulo offline. -> (mono float32, sr, eventi) o None.
    eventi = {"kick": [(t, forza)], "snare": ..., "hat": ..., "bassnote": ..., "tick": ...}"""
    lib = _openmpt()
    if lib is None:
        return None
    data = Path(path).read_bytes()
    err, msg = ctypes.c_int(0), ctypes.c_char_p()
    mod = lib.openmpt_module_create_from_memory2(data, len(data), None, None, None, None,
                                                 ctypes.byref(err), ctypes.byref(msg), None)
    if not mod:
        print(f"[visuals] libopenmpt non apre {Path(path).name}: {msg.value}")
        return None
    try:
        lib.openmpt_module_set_repeat_count(mod, 0)
        n_ch = lib.openmpt_module_get_num_channels(mod)

        def _name(fn, i):
            ptr = fn(mod, i)
            if not ptr:
                return ""
            try:
                return ctypes.string_at(ptr).decode("latin-1", "replace")
            finally:
                lib.openmpt_free_string(ptr)

        n_inst = lib.openmpt_module_get_num_instruments(mod)
        if n_inst > 0:
            names = [_name(lib.openmpt_module_get_instrument_name, i) for i in range(n_inst)]
        else:                                           # MOD / S3M: la colonna "strumento" indica un sample
            names = [_name(lib.openmpt_module_get_sample_name, i)
                     for i in range(lib.openmpt_module_get_num_samples(mod))]
        roles = [_role_for_name(n) for n in names]

        chunk = sr // ENV_HZ
        buf = (ctypes.c_float * chunk)()
        cmd = lib.openmpt_module_get_pattern_row_channel_command
        parts, events = [], {"kick": [], "snare": [], "hat": [], "bassnote": [], "tick": []}
        last, t_frames = None, 0
        for _ in range(MAX_RENDER_SECONDS * ENV_HZ):
            got = lib.openmpt_module_read_float_mono(mod, sr, chunk, buf)
            if got == 0:
                break
            parts.append(np.frombuffer(buf, np.float32, got).copy())
            pos = (lib.openmpt_module_get_current_order(mod), lib.openmpt_module_get_current_row(mod))
            if pos != last:
                last = pos
                t = t_frames / float(sr)
                pat, row = lib.openmpt_module_get_current_pattern(mod), pos[1]
                events["tick"].append((t, 1.0 if row % 4 == 0 else 0.35))
                for ch in range(n_ch):
                    note = cmd(mod, pat, row, ch, 0)
                    if not 1 <= note <= 120:            # niente nota (o note-off/cut)
                        continue
                    inst = cmd(mod, pat, row, ch, 1)
                    if not 1 <= inst <= len(roles) or roles[inst - 1] is None:
                        continue
                    vol = cmd(mod, pat, row, ch, 4)
                    events[roles[inst - 1]].append((t, 0.55 + 0.45 * vol / 64.0 if vol else 1.0))
            t_frames += got
        if not parts:
            return None
        return np.concatenate(parts), sr, events
    finally:
        lib.openmpt_module_destroy(mod)


def _impulses(events, n):
    arr = np.zeros(n, np.float32)
    for t, s in events:
        i = int(t * ENV_HZ)
        if 0 <= i < n:
            arr[i] = max(arr[i], s)
    return arr


def _apply_events(an, events):
    for role in ("kick", "snare", "hat"):
        if len(events[role]) >= 4:                     # ruolo davvero presente nel brano
            setattr(an, role, _impulses(events[role], an.n))
            an.exact.add(role)
    an.bassnote = _impulses(events["bassnote"], an.n)
    if events["bassnote"]:
        an.exact.add("bassnote")
    an.tick = _impulses(events["tick"], an.n)
    an.exact.add("tick")


def analyze_file(path):
    """Analisi completa di un file (bloccante). -> Analysis o None."""
    if np is None:
        return None
    path = Path(path)
    events = None
    if path.suffix.lower() in TRACKER_EXTS:
        res = _render_tracker(path)
        if res is None:
            return None
        x, sr, events = res
    else:
        res = _decode_samples(path)
        if res is None:
            return None
        x, sr = res
    if len(x) < sr // 4:
        return None
    an = _band_analysis(x, sr)
    if events:
        _apply_events(an, events)
    return an


def _analyze_cached(path, cache_dir):
    path = Path(path)
    cfile = None
    if cache_dir is not None:
        try:
            st = path.stat()
            cfile = Path(cache_dir) / f"{path.name}.{st.st_size}.{int(st.st_mtime)}.v{CACHE_VERSION}.npz"
            if cfile.exists():
                return Analysis.load(cfile)
        except Exception:
            cfile = None
    an = analyze_file(path)
    if an is not None and cfile is not None:
        try:
            cfile.parent.mkdir(parents=True, exist_ok=True)
            an.save(cfile)
        except Exception:
            pass
    return an


class _Analyzer:
    """Un thread che analizza le tracce in coda (la corrente per prima)."""

    def __init__(self, cache_dir=None):
        self.cache_dir = cache_dir
        self.results = {}                     # path -> Analysis | False (fallita)
        self._queue = []
        self._cv = threading.Condition()
        self._thread = None

    def request(self, path, urgent=False):
        path = Path(path)
        with self._cv:
            if path in self.results:
                return
            if path in self._queue:
                if urgent:
                    self._queue.remove(path)
                    self._queue.insert(0, path)
                return
            self._queue.insert(0, path) if urgent else self._queue.append(path)
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, daemon=True, name="visuals-analysis")
                self._thread.start()
            self._cv.notify()

    def _run(self):
        while True:
            with self._cv:
                while not self._queue:
                    self._cv.wait()
                path = self._queue.pop(0)
            try:
                an = _analyze_cached(path, self.cache_dir)
            except Exception as e:
                print(f"[visuals] analisi fallita per {path.name}: {e}")
                an = None
            self.results[path] = an if an is not None else False


# ============================================================================
# Manager
# ============================================================================
class VisualsManager:
    def __init__(self, music=None, mode="synthwave", colors=None, sync_offset_ms=0, cache_dir=None):
        self.music = music
        self.mode = mode if mode in MODES else MODES[0]
        if np is None and self.mode == "plasma":
            self.mode = "synthwave"
        self.colors = list(colors) if colors else [(34, 211, 238), (250, 204, 21), (192, 132, 252),
                                                   (74, 222, 128), (248, 113, 113), (96, 165, 250)]
        self.sync_offset = sync_offset_ms / 1000.0
        self.debug = False

        if cache_dir is None and music is not None:
            cache_dir = Path(music.folder) / ".visuals_cache"
        self._analyzer = _Analyzer(cache_dir) if np is not None else None
        self.track = None
        self.analysis = None

        # orologio sincronizzato con la musica
        self._clock = 0.0
        self._prev_clock = 0.0
        self._clock_ok = False
        self._last_pos = None
        self._stall = 0

        # stato reattivo (tutto 0..1)
        self.lo = self.mid = self.hi = 0.0
        self.tone = 0.5
        self.kick = self.snare = self.hat = self.bassnote = self.tick = 0.0

        # animazione
        self.dt = 1 / 60
        self.speed = 1.0
        self.anim = 0.0
        self.grid_pos = 0.0
        self.kick_phase = 0.0
        self.hue = LEVEL_HUES[0]
        self.level = 1

        self.size = None
        self._grads, self._glows = {}, {}
        self._stars = self._squares = self._mountains = self._plasma = None
        self._font = None

    # ---- controlli ----
    def set_mode(self, mode):
        if mode in MODES and not (mode == "plasma" and np is None):
            self.mode = mode

    def next_mode(self, step=1):
        modes = [m for m in MODES if not (m == "plasma" and np is None)]
        self.mode = modes[(modes.index(self.mode) + step) % len(modes)] if self.mode in modes else modes[0]

    def handle_event(self, e):
        """True se l'evento e' stato consumato."""
        if e.type != pygame.KEYDOWN:
            return False
        if e.key == pygame.K_b:
            self.next_mode(-1 if e.mod & pygame.KMOD_SHIFT else 1)
        elif e.key == pygame.K_F3:
            self.debug = not self.debug
        elif e.key == pygame.K_LEFTBRACKET:
            self.sync_offset -= 0.01
        elif e.key == pygame.K_RIGHTBRACKET:
            self.sync_offset += 0.01
        else:
            return False
        return True

    # ---- update ----
    def update(self, dt, game=None):
        self.dt = dt
        level = 1
        if game is not None:
            try:
                level = max(1, int(game.level()))
            except Exception:
                pass
        self.level = level
        target = 1.0 + 0.16 * (min(level, 25) - 1)
        if game is not None and getattr(game, "paused", False):
            target *= 0.3
        elif game is not None and getattr(game, "state", "play") in ("menu", "gameover", "game_over"):
            target = max(0.8, target * 0.7)
        self.speed += (target - self.speed) * min(1.0, dt * 2.5)
        self.anim += dt * self.speed

        # tinta: segue il livello lungo l'arco piu' corto
        th = LEVEL_HUES[(level - 1) % len(LEVEL_HUES)]
        d = ((th - self.hue + 0.5) % 1.0) - 0.5
        self.hue = (self.hue + d * min(1.0, dt * 1.2)) % 1.0

        self._track_sync()
        self._update_clock(dt)
        self._react(dt)

    def _track_sync(self):
        if self.music is None or self._analyzer is None:
            return
        trk = getattr(self.music, "current_track", None)
        if trk is None:
            return
        trk = Path(trk)
        if trk != self.track:
            self.track = trk
            self.analysis = None
            self._clock_ok = False
            self._analyzer.request(trk, urgent=True)
            for p in getattr(self.music, "playlist", []):      # prefetch del resto della playlist
                self._analyzer.request(p)
        if self.analysis is None:
            res = self._analyzer.results.get(trk)
            if res:
                self.analysis = res

    def _update_clock(self, dt):
        """Orologio liscio agganciato a pygame.mixer.music.get_pos()."""
        self._prev_clock = self._clock
        if self.analysis is None or not pygame.mixer.get_init():
            self._clock_ok = False
            return
        pos = pygame.mixer.music.get_pos()
        if pos < 0:
            self._clock_ok = False
            return
        p = pos / 1000.0
        dur = self.analysis.duration
        if dur > 0 and p > dur + 0.5:                         # brano in loop
            p %= dur
        self._stall = self._stall + 1 if p == self._last_pos else 0
        self._last_pos = p
        if not self._clock_ok or abs(p - self._clock) > 0.25 or self._stall >= 4:
            self._clock = p                                   # aggancio / pausa
        else:
            self._clock += dt
            self._clock += (p - self._clock) * 0.15           # correzione dolce del jitter di get_pos
        self._clock_ok = True

    def _react(self, dt):
        a = self.analysis
        if a is not None and self._clock_ok:
            t1 = self._clock + self.sync_offset
            t0 = min(self._prev_clock + self.sync_offset, t1)
            i1 = max(0, min(a.n - 1, int(t1 * ENV_HZ)))
            i0 = max(0, min(i1, int(t0 * ENV_HZ)))
            if i1 - i0 > 30:                                  # salto: non scandire il passato
                i0 = i1
            tgt = {"lo": a.lo[i1], "mid": a.mid[i1], "hi": a.hi[i1], "tone": a.tone[i1]}
            hits = {f: float(getattr(a, f)[i0:i1 + 1].max()) for f in ("kick", "snare", "hat", "bassnote", "tick")}
        else:                                                 # nessuna analisi: respiro lento
            ph = self.anim
            tgt = {"lo": 0.30 + 0.08 * math.sin(ph * 1.3), "mid": 0.30 + 0.08 * math.sin(ph * 0.9 + 1),
                   "hi": 0.25 + 0.06 * math.sin(ph * 1.7 + 2), "tone": 0.5}
            hits = {f: 0.0 for f in ("kick", "snare", "hat", "bassnote", "tick")}

        for name in ("lo", "mid", "hi"):                      # attacco rapido, rilascio piu' lento
            cur = getattr(self, name)
            rate = 45.0 if tgt[name] > cur else 7.0
            setattr(self, name, cur + (tgt[name] - cur) * (1 - math.exp(-dt * rate)))
        self.tone += (tgt["tone"] - self.tone) * (1 - math.exp(-dt * 0.8))
        for name, decay in (("kick", 8.0), ("snare", 10.0), ("hat", 15.0), ("bassnote", 7.0), ("tick", 9.0)):
            setattr(self, name, max(getattr(self, name) * math.exp(-dt * decay), hits[name]))
        self.grid_pos += dt * 0.5 * self.speed * (1 + 2.2 * self.kick)
        self.kick_phase += dt * (1.5 + 9.0 * self.kick)

    # ---- cache superfici ----
    def _ensure(self, sw, sh):
        if self.size == (sw, sh):
            return
        self.size = (sw, sh)
        self._grads.clear()
        self._glows.clear()
        self._plasma = None
        rnd = random.Random(7)
        area = sw * sh
        self._stars = [[rnd.uniform(0, sw), rnd.uniform(0, sh), layer, rnd.random()]
                       for layer, cnt in enumerate((area // 9000, area // 16000, area // 40000)) for _ in range(cnt)]
        n = min(90, max(22, area // 28000))
        self._squares = [[rnd.uniform(0, sw), rnd.uniform(0, sh), rnd.randint(14, 60), rnd.uniform(8, 32),
                          rnd.choice(self.colors)] for _ in range(n)]
        hz = int(sh * 0.50)
        pts, step, h = [], max(8, sw // 16), 0.0
        for x in range(0, sw + step, step):
            h = max(0.02, min(0.14, h * 0.4 + rnd.uniform(0.02, 0.16) * 0.6))
            pts.append((x, hz - int(h * sh)))
        self._mountains = pts

    def _grad(self, key, size, c0, c1):
        k = (size, c0, c1)
        hit = self._grads.get(key)
        if hit and hit[0] == k:
            return hit[1]
        small = pygame.Surface((2, 64), 0, 32)
        for y in range(64):
            pygame.draw.line(small, _lerp(c0, c1, y / 63), (0, y), (1, y))
        surf = pygame.transform.smoothscale(small, (max(1, size[0]), max(1, size[1])))
        self._grads[key] = (k, surf)
        return surf

    def _glow(self, radius, color):
        radius = max(8, (int(radius) // 8) * 8)
        key = (radius, _q(color, 12))
        s = self._glows.get(key)
        if s is None:
            if len(self._glows) > 12:
                self._glows.clear()
            s = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
            steps = 26
            for i in range(steps):
                r = int(radius * (1 - i / steps))
                pygame.draw.circle(s, (*color, int(210 * (i / steps) ** 2)), (radius, radius), r)
            self._glows[key] = s
        return s

    # ---- draw ----
    def draw(self, screen):
        sw, sh = screen.get_size()
        self._ensure(sw, sh)
        mode = self.mode
        if mode == "plasma" and np is None:
            mode = "synthwave"
        getattr(self, "_draw_" + mode)(screen, sw, sh)
        if self.debug:
            self._draw_debug(screen)

    def _h(self):
        """Tinta corrente (livello + leggera deriva dalle medie), quantizzata per la cache."""
        return round((self.hue + (self.tone - 0.5) * 0.12) * 60) / 60.0

    # -- synthwave --
    def _draw_synthwave(self, scr, sw, sh):
        h, kick = self._h(), self.kick
        hz, cx = int(sh * 0.50), sw // 2
        sky = self._grad("sky", (sw, hz + 1), _q(_hsv(h - 0.08, 0.9, 0.10)), _q(_hsv(h, 0.85, 0.42)))
        scr.blit(sky, (0, 0))

        # stelle in cielo (brillano con gli alti)
        for i, (x, y, layer, ph) in enumerate(self._stars):
            if layer == 1 and y < hz - 6:
                b = 0.35 + 0.35 * math.sin(self.anim * 2 + ph * 20) + 0.6 * self.hat * (ph > 0.5)
                c = _scale((255, 240, 255), max(0.1, min(1.0, b)))
                scr.fill(c, (int(x), int(y), 2, 2))

        # sole: alone + disco a gradiente con strisce
        R = int(sh * 0.19 * (1 + 0.07 * kick))
        cy = hz - int(R * 0.25)
        glow = self._glow(R * 1.9, _hsv(h + 0.05, 0.9, 1.0))
        glow.set_alpha(int(255 * min(1.0, 0.25 + 0.55 * kick + 0.2 * self.lo)))
        scr.blit(glow, glow.get_rect(center=(cx, cy)))
        top, bot = _hsv(h + 0.27, 0.8, 1.0), _hsv(h + 0.02, 0.95, 1.0)
        period = max(10, int(R * 0.16))
        phase = (self.anim * 14) % period
        for y in range(cy - R, min(hz, cy + R)):
            dy = y - cy
            if dy > -R * 0.05 and ((dy - phase) % period) < period * (0.12 + 0.55 * dy / R):
                continue
            hw = int(math.sqrt(max(0, R * R - dy * dy)))
            pygame.draw.line(scr, _lerp(top, bot, (y - (cy - R)) / (2.0 * R)), (cx - hw, y), (cx + hw, y))

        # montagne
        neon = _hsv(h - 0.30 + 0.05 * self.mid, 0.75, 1.0)
        poly = [(0, hz)] + self._mountains + [(sw, hz)]
        pygame.draw.polygon(scr, _hsv(h - 0.05, 0.8, 0.10), poly)
        pygame.draw.lines(scr, _scale(neon, 0.35 + 0.6 * self.lo + 0.3 * kick), False, self._mountains, max(1, sh // 350))

        # terreno + griglia prospettica
        ground = self._grad("gnd", (sw, sh - hz), _q(_hsv(h, 0.9, 0.16)), _q(_hsv(h - 0.05, 0.9, 0.03)))
        scr.blit(ground, (0, hz))
        gh = sh - hz
        bright = 0.55 + 0.45 * kick
        n_h = 16
        frac = self.grid_pos % 1.0
        for i in range(n_h):
            z = (i + frac) / n_h
            y = hz + int(gh * z ** 2.6)
            col = _scale(_lerp(_hsv(h, 0.9, 0.2), neon, 0.1 + 0.9 * z), bright + 0.25 * self.hat)
            pygame.draw.line(scr, col, (0, y), (sw, y), max(1, int(z * 3 * sh / 700 + 0.5)))
        step = sw / 9.0
        for k in range(-13, 14):
            xb = cx + k * step
            for seg in range(3):
                z0, z1 = seg / 3.0, (seg + 1) / 3.0
                col = _scale(neon, (0.12 + 0.88 * (seg + 1) / 3.0) * bright)
                pygame.draw.line(scr, col, (cx + k * step * z0, hz + gh * z0), (cx + k * step * z1, hz + gh * z1), max(1, sh // 450))
        pygame.draw.line(scr, _scale(neon, 1.0), (0, hz), (sw, hz), max(2, sh // 300))

    # -- starfield --
    def _draw_starfield(self, scr, sw, sh):
        h, kick, dt = self._h(), self.kick, self.dt
        scr.blit(self._grad("sfbg", (sw, sh), _q(_hsv(h + 0.02, 0.8, 0.07)), _q(_hsv(h - 0.06, 0.9, 0.02))), (0, 0))
        r = min(sw, sh) * 0.75
        for idx, (hue_off, fx, fy, k) in enumerate(((0.0, 0.30, 0.35, self.lo), (0.35, 0.72, 0.65, self.mid))):
            g = self._glow(r, _hsv(h + hue_off, 0.85, 0.65))
            g.set_alpha(int(255 * min(1.0, 0.10 + 0.40 * k + 0.30 * kick * (idx == 0))))
            ox = math.sin(self.anim * 0.15 + idx * 2) * sw * 0.05
            oy = math.cos(self.anim * 0.12 + idx) * sh * 0.05
            scr.blit(g, g.get_rect(center=(int(sw * fx + ox), int(sh * fy + oy))))

        sc = sh / 700.0
        speeds = (24 * sc, 70 * sc, 170 * sc)
        boosts = (1.0, 1 + 1.2 * kick, 1 + 3.2 * kick)
        base_b = (0.45, 0.75, 1.0)
        tint = _hsv(h + 0.1, 0.45, 1.0)
        for s in self._stars:
            layer = s[2]
            s[1] += speeds[layer] * boosts[layer] * self.speed * dt
            s[0] += math.sin(self.anim * 0.3) * speeds[layer] * 0.12 * dt
            if s[1] > sh:
                s[0], s[1] = random.uniform(0, sw), -4.0
            s[0] %= sw
            tw = 0.7 + 0.3 * math.sin(self.anim * 3 + s[3] * 30)
            b = min(1.0, base_b[layer] * tw + (0.7 * self.hat if s[3] > 0.6 else 0.0))
            col = _scale(_lerp((255, 255, 255), tint, 0.4), b)
            x, y = int(s[0]), int(s[1])
            if layer == 2:
                ln = int(3 + speeds[2] * boosts[2] * self.speed * 0.045)
                pygame.draw.line(scr, col, (x, y), (x, y - ln), max(1, int(2 * sc + 0.5)))
            elif layer == 1:
                scr.fill(col, (x, y, 2, 2))
            else:
                scr.fill(col, (x, y, 1, 1))

    # -- plasma --
    def _draw_plasma(self, scr, sw, sh):
        g = self._plasma
        if g is None:
            gw = max(48, min(128, sw // 10))
            gh = max(27, int(gw * sh / sw))
            asp = sw / float(sh)
            x, y = np.meshgrid(np.linspace(0, asp, gw), np.linspace(0, 1, gh), indexing="ij")
            g = self._plasma = {"x": x.astype(np.float32), "y": y.astype(np.float32),
                                "d": np.sqrt((x - asp / 2) ** 2 + (y - 0.5) ** 2).astype(np.float32),
                                "small": pygame.Surface((gw, gh), 0, 32), "big": pygame.Surface((sw, sh), 0, 32)}
        t = self.anim * 0.55
        x, y, d = g["x"], g["y"], g["d"]
        zoom = 1.0 + 0.35 * self.lo
        v = (np.sin(x * 7 * zoom + t) + np.sin(y * 6 - t * 1.3) + np.sin((x + y) * 5 + t * 0.7)
             + np.sin(d * 11 - self.kick_phase * 1.2))
        idx = (((v + 4.0) / 8.0 * 0.9 + self.anim * 0.02) * 256).astype(np.int32) % 256
        i = np.linspace(0, 1, 256, endpoint=False)
        hue = self.hue + 0.22 * np.sin(i * 2 * math.pi) + (self.tone - 0.5) * 0.2
        val = 0.14 + 0.30 * (0.5 + 0.5 * np.sin(i * 4 * math.pi + 1)) + 0.18 * self.lo + 0.22 * self.kick
        lut = _hsv_np(hue, 0.85 - 0.25 * self.kick, np.clip(val, 0, 1))
        pygame.surfarray.blit_array(g["small"], lut[idx])
        pygame.transform.smoothscale(g["small"], (sw, sh), g["big"])
        scr.blit(g["big"], (0, 0))

    # -- quadrati fluttuanti (lo sfondo originale) --
    def _draw_squares(self, scr, sw, sh):
        h, kick = self._h(), self.kick
        bg0, bg1 = _q(_hsv(h, 0.8, 0.10)), _q(_hsv(h - 0.05, 0.8, 0.02))
        scr.blit(self._grad("sqbg", (sw, sh), bg0, bg1), (0, 0))
        mix_bg = _lerp(bg0, bg1, 0.5)
        for s in self._squares:
            s[1] -= s[3] * self.dt * self.speed * (1 + 1.5 * kick)
            if s[1] < -s[2]:
                s[0], s[1] = random.uniform(0, sw), sh + s[2]
            size = int(s[2] * (1 + 0.18 * kick))
            col = _lerp(mix_bg, s[4], min(1.0, 0.16 + 0.35 * kick + 0.12 * self.mid))
            off = (size - s[2]) // 2
            pygame.draw.rect(scr, col, (int(s[0]) - off, int(s[1]) - off, size, size), width=2, border_radius=8)

    # -- HUD di debug --
    def _draw_debug(self, scr):
        if self._font is None:
            self._font = pygame.font.Font(None, 18)
        x0, y0, bw = 12, 12, 90
        pygame.draw.rect(scr, (0, 0, 0), (x0 - 6, y0 - 6, bw + 190, 118), border_radius=6)
        rows = (("LO", self.lo), ("MID", self.mid), ("HI", self.hi), ("KICK", self.kick),
                ("SNARE", self.snare), ("HAT", self.hat), ("BASS", self.bassnote))
        for i, (name, val) in enumerate(rows):
            y = y0 + i * 14
            scr.blit(self._font.render(name, True, (200, 200, 220)), (x0, y))
            pygame.draw.rect(scr, (90, 220, 160), (x0 + 50, y + 2, int(bw * max(0, min(1, val))), 9))
        a = self.analysis
        info = [f"{self.mode}  lvl {self.level}  x{self.speed:.2f}",
                f"t {self._clock:6.2f}s  off {self.sync_offset * 1000:+.0f}ms",
                ("exact: " + ",".join(sorted(a.exact))) if a else "analisi: in corso/assente",
                (self.track.name[:26] if self.track else "-")]
        for i, line in enumerate(info):
            scr.blit(self._font.render(line, True, (200, 200, 220)), (x0 + 150, y0 + i * 14))


# ============================================================================
# Demo standalone:  python visuals.py [cartella_musica]
# ============================================================================
def _demo(folder):
    pygame.init()
    screen = pygame.display.set_mode((960, 600), pygame.RESIZABLE)
    pygame.display.set_caption("visuals demo  -  B sfondo | frecce su/giu livello | F3 debug | [ ] sync")
    music = None
    try:
        from music import MusicManager
        music = MusicManager(folder)
        music.play()
    except Exception as e:
        print("[demo] musica non disponibile:", e)

    class _G:
        level_n, paused, state = 1, False, "play"
        def level(self):
            return self.level_n

    game, clock = _G(), pygame.time.Clock()
    vis = VisualsManager(music)
    while True:
        dt = min(clock.tick(60) / 1000.0, 0.05)
        for e in pygame.event.get():
            if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                pygame.quit()
                return
            if music:
                music.handle_event(e)
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_UP:
                    game.level_n = min(30, game.level_n + 1)
                elif e.key == pygame.K_DOWN:
                    game.level_n = max(1, game.level_n - 1)
                elif e.key == pygame.K_SPACE and music:
                    music.next_track()
            vis.handle_event(e)
        vis.update(dt, game)
        vis.draw(screen)
        pygame.display.flip()


if __name__ == "__main__":
    _demo(sys.argv[1] if len(sys.argv) > 1 else "music")
