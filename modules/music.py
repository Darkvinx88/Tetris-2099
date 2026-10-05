"""
modules/music.py - musica di sottofondo per tetris.py

Gestisce una playlist di musica (incluse tracce chiptune in formato MOD/
IT/XM/S3M, oltre a ogg/mp3/wav) SENZA toccare la logica di gioco: usa il
canale "music" di pygame.mixer (separato da quello degli Sfx sintetizzati
in tetris.py), quindi effetti e musica convivono senza conflitti.

Formati supportati
-------------------
pygame.mixer.music si appoggia a SDL2_mixer, che nella stragrande
maggioranza delle build (le wheel di pygame/pygame-ce da PyPI comprese)
include un player MOD integrato capace di leggere MOD, S3M, IT e XM, oltre
a ogg/mp3/wav/flac. Quindi i classici chiptune "da keygen" in .it/.xm
funzionano di norma SENZA bisogno di convertirli: basta metterli nella
cartella e MusicManager li carica cosi' come sono.

Se una particolare build di SDL2_mixer non li supportasse (capita di rado,
dipende da come e' stato compilato pygame), il caricamento fallisce in modo
pulito: MusicManager stampa un avviso e passa al brano successivo, invece
di far crashare il gioco. In quel caso, come fallback, si puo' convertire
il file in .ogg con uno strumento esterno (es. openmpt123, mikmod, o
esportando da un tracker come MilkyTracker/OpenMPT) e usare quello al
posto dell'originale.

Uso in tetris.py (poche righe di integrazione):

    from modules.music import MusicManager
    ...
    music = MusicManager("music")     # cartella con le tracce
    music.play()                      # avvia la playlist (shuffle di default)
    ...
    # nel game loop, una volta per frame:
    music.update()
    ...
    # per legare il volume musica allo stesso mute (M) degli Sfx:
    music.set_muted(not game.sfx.enabled)
    ...
    # alla chiusura:
    music.stop()
"""
import random
from pathlib import Path

import pygame

# Estensioni cercate nella cartella musica, in ordine di preferenza per il
# glob (l'ordine qui non conta per la riproduzione: la playlist viene
# comunque mescolata da play()/_advance()).
EXTENSIONS = (".it", ".xm", ".s3m", ".mod", ".ogg", ".mp3", ".wav", ".flac")

MUSIC_END_EVENT = pygame.USEREVENT + 17  # id "personale", improbabile collida con altri


class MusicManager:
    def __init__(self, folder="music", volume=0.6, shuffle=True, loop_single=False):
        """
        folder:       cartella (relativa o assoluta) con i file musicali.
        volume:       0.0-1.0, volume "nominale" (quello usato quando non mutato).
        shuffle:      True = ordine casuale della playlist, si rimescola ad ogni giro.
        loop_single:  True = ogni brano si ripete all'infinito invece di passare
                      al successivo (utile per una singola chiptune in loop).
        """
        self.folder = Path(folder)
        self.volume = max(0.0, min(1.0, volume))
        self.shuffle = shuffle
        self.loop_single = loop_single
        self.muted = False
        self.enabled = True
        self._playlist = []
        self._idx = -1

        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            pygame.mixer.music.set_endevent(MUSIC_END_EVENT)
            self._scan()
        except pygame.error:
            self.enabled = False

    # ---- scoperta file ----
    def _scan(self):
        self._playlist = sorted(
            p for p in self.folder.glob("*") if p.suffix.lower() in EXTENSIONS
        )
        if self.shuffle:
            random.shuffle(self._playlist)
        if not self._playlist:
            self.enabled = False

    # ---- riproduzione ----
    def play(self):
        """Avvia (o riavvia) la playlist dal primo brano."""
        if not self.enabled or not self._playlist:
            return
        self._idx = -1
        self._advance()

    def _advance(self):
        if not self.enabled or not self._playlist:
            return
        self._idx = (self._idx + 1) % len(self._playlist)
        if self._idx == 0 and self.shuffle:
            random.shuffle(self._playlist)
        track = self._playlist[self._idx]
        try:
            pygame.mixer.music.load(str(track))
            pygame.mixer.music.set_volume(0.0 if self.muted else self.volume)
            pygame.mixer.music.play(loops=-1 if self.loop_single else 0)
        except pygame.error as e:
            # Formato non supportato da questa build di SDL2_mixer (raro per
            # .it/.xm/.mod, ma possibile): salta al brano successivo invece
            # di bloccare il gioco. Se capita spesso con lo stesso file,
            # conviene convertirlo in .ogg.
            print(f"[music] could not load {track.name}: {e}")
            self._playlist.pop(self._idx)
            self._idx -= 1
            if self._playlist:
                self._advance()
            else:
                self.enabled = False

    def update(self, events=None):
        """Da chiamare una volta per frame. Se si passa la lista di eventi
        gia' letta nel game loop (pygame.event.get()), evita una seconda
        chiamata a pygame.event.get(); altrimenti la fa da se'."""
        if not self.enabled or self.loop_single:
            return
        ev_list = events if events is not None else pygame.event.get(MUSIC_END_EVENT)
        for e in ev_list:
            if e.type == MUSIC_END_EVENT:
                self._advance()

    def handle_event(self, e):
        """Alternativa a update(events=...): da chiamare nel ciclo eventi
        principale, un evento alla volta, come si fa gia' con joypad.handle_event(e, game)."""
        if self.enabled and not self.loop_single and e.type == MUSIC_END_EVENT:
            self._advance()

    # ---- controlli ----
    def set_muted(self, muted):
        self.muted = muted
        if self.enabled:
            pygame.mixer.music.set_volume(0.0 if muted else self.volume)

    def toggle_muted(self):
        self.set_muted(not self.muted)

    def set_volume(self, volume):
        self.volume = max(0.0, min(1.0, volume))
        if self.enabled and not self.muted:
            pygame.mixer.music.set_volume(self.volume)

    def pause(self):
        if self.enabled:
            pygame.mixer.music.pause()

    def unpause(self):
        if self.enabled:
            pygame.mixer.music.unpause()

    def stop(self):
        if self.enabled:
            pygame.mixer.music.stop()

    def next_track(self):
        self._advance()
