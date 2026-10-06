"""
modules/joypad.py - supporto joypad/controller per tetris.py

Aggiunge il supporto ai controller (Xbox, PlayStation, generici USB/Bluetooth)
SENZA toccare la logica di gioco in tetris.py: gli input del joypad vengono
tradotti negli stessi "tasti" che il gioco gia' conosce (KEYS_L/R/DOWN/ROT/
HOLD, P, M, ecc.), quindi DAS/ARR, rotazioni SRS, hold, pausa e menu si
comportano in modo identico sia con tastiera sia con joypad.

"""
import pygame

JOY_DEADZONE = 0.45

# Mappatura pulsanti in stile standard Xbox/DirectInput (indici SDL2 tipici:
# 0=A 1=B 2=X 3=Y 4=LB 5=RB 6=Back/Select 7=Start). Su controller PlayStation
# collegati via SDL i pulsanti fisici Croce/Cerchio/Quadrato/Triangolo/
# L1/R1/Share/Options arrivano di norma sugli stessi indici. Se il tuo
# controller ha una mappatura diversa, modifica semplicemente questo dict.
BUTTON_KEYS = {
    0: (pygame.K_x, pygame.K_RETURN),   # A / Croce   -> ruota orario, conferma nei menu
    1: (pygame.K_SPACE,),               # B / Cerchio -> hard drop (conferma anche nei menu)
    2: (pygame.K_z,),                   # X / Quadrato-> ruota antiorario
    3: (pygame.K_c,),                   # Y / Triangolo -> hold
    4: (pygame.K_c,),                   # LB / L1     -> hold (alternativo)
    5: (pygame.K_z,),                   # RB / R1     -> ruota antiorario (alternativo)
    # Bottone 6 e 7/9 (Options/Start/Share, a seconda del controller) sono
    # gestiti a parte in handle_event() tramite START_BUTTONS, perche' il
    # loro significato dipende dallo stato di gioco (pausa oppure conferma
    # nei menu): inviare sempre entrambi i tasti causava pausa+conferma nello
    # stesso istante, annullando la pausa appena attivata.
}

# Indici "Start/Options/Share" osservati sui vari controller (Xbox=7,
# PS4=varia molto a seconda di OS/driver: sul controller di test e' risultato
# essere 6). Aggiungiamo tutti gli indici noti: non c'e' rischio di falsi
# positivi perche' un solo bottone fisico per volta generera' l'evento.
START_BUTTONS = (6, 7, 9)

# Su PS4, con alcuni driver (in particolare su macOS o con vecchie versioni
# di SDL), il D-pad non viene riportato come hat (JOYHATMOTION) ma come 4
# pulsanti digitali distinti. Gli indici tipici sono 11=UP 12=DOWN 13=LEFT
# 14=RIGHT: li gestiamo sia come eventi singoli (JOYBUTTONDOWN, per la
# navigazione nei menu) sia nel polling continuo (per il movimento in
# partita), esattamente come gia' avviene per l'hat.
DPAD_BUTTON_KEYS = {
    11: pygame.K_UP,
    12: pygame.K_DOWN,
    13: pygame.K_LEFT,
    14: pygame.K_RIGHT,
}


# Rumble per evento di gioco: nome Sfx -> (motore grave, motore acuto, durata ms).
# Agganciato a Sfx.play() da JoypadManager.attach_sfx(): ogni suono di gioco
# produce anche la sua vibrazione. "rotate" e' escluso (troppo frequente);
# per averlo aggiungi "rotate": (0.0, 0.12, 30).
RUMBLE_EVENTS = {
    "hold":   (0.00, 0.25, 50),
    "lock":   (0.30, 0.00, 70),
    "hard":   (0.65, 0.25, 120),
    "clear":  (0.45, 0.65, 200),
    "level":  (0.35, 0.55, 280),   # anche T-Spin
    "tetris": (0.85, 1.00, 450),
    "over":   (1.00, 0.60, 900),
}


class _MergedKeys:
    """Oggetto 'tipo array' restituito al posto di pygame.key.get_pressed():
    si comporta come l'originale ma risulta True anche per i tasti virtuali
    tenuti premuti dal joypad (frecce/soft-drop)."""
    __slots__ = ("_real", "_extra")

    def __init__(self, real, extra):
        self._real = real
        self._extra = extra

    def __getitem__(self, key):
        return bool(self._real[key]) or key in self._extra


class JoypadManager:
    def __init__(self, rumble=True, rumble_scale=1.0):
        pygame.joystick.init()
        self.sticks = {}
        self.rumble_enabled = rumble
        self.rumble_scale = rumble_scale
        self._rumble_until = 0       # ms (pygame.time.get_ticks) di fine vibrazione
        self._rumble_power = 0.0     # intensita' della vibrazione in corso
        self._scan()
        self._last_axis_dir = 0     # per la navigazione nei menu con lo stick

    # ---- collegamento / scollegamento a caldo ----
    def _scan(self):
        for i in range(pygame.joystick.get_count()):
            js = pygame.joystick.Joystick(i)
            js.init()
            self.sticks[js.get_instance_id()] = js

    # ---- rumble ----
    def attach_sfx(self, sfx):
        """Avvolge sfx.play(): a ogni effetto sonoro corrisponde una vibrazione."""
        if getattr(sfx, "_joypad_rumble_wrapped", False):
            return
        original_play = sfx.play
        manager = self

        def play_with_rumble(name):
            original_play(name)
            manager.rumble(name)

        sfx.play = play_with_rumble
        sfx._joypad_rumble_wrapped = True

    def rumble(self, name):
        """Fa vibrare tutti i controller per l'evento 'name'. SDL tiene una
        sola vibrazione per volta: una piu' debole non sostituisce una piu'
        forte ancora in corso (es. lock subito dopo hard drop)."""
        spec = RUMBLE_EVENTS.get(name)
        if not spec or not self.rumble_enabled or not self.sticks:
            return
        low, high, ms = spec
        low = max(0.0, min(1.0, low * self.rumble_scale))
        high = max(0.0, min(1.0, high * self.rumble_scale))
        power = max(low, high)
        now = pygame.time.get_ticks()
        if now < self._rumble_until and power < self._rumble_power:
            return
        for js in self.sticks.values():
            try:
                js.rumble(low, high, ms)
            except (pygame.error, AttributeError, NotImplementedError):
                pass   # controller senza rumble / pygame vecchio: ignora
        self._rumble_until = now + ms
        self._rumble_power = power

    def stop_rumble(self):
        for js in self.sticks.values():
            try:
                js.stop_rumble()
            except (pygame.error, AttributeError, NotImplementedError):
                pass
        self._rumble_until = 0
        self._rumble_power = 0.0

    def install(self):
        """Fa il monkeypatch di pygame.key.get_pressed una sola volta, cosi'
        il movimento continuo (stick/D-pad) alimenta il DAS/ARR esistente."""
        if getattr(pygame.key, "_joypad_installed", False):
            return
        original_get_pressed = pygame.key.get_pressed
        manager = self

        def patched_get_pressed():
            return _MergedKeys(original_get_pressed(), manager._held_virtual_keys())

        pygame.key.get_pressed = patched_get_pressed
        pygame.key._joypad_installed = True

    # ---- eventi (azioni singole + hot-plug) ----
    def handle_event(self, e, game):
        if e.type == pygame.JOYDEVICEADDED:
            self._scan()
        elif e.type == pygame.JOYDEVICEREMOVED:
            self.sticks.pop(e.instance_id, None)
        elif e.type == pygame.JOYBUTTONDOWN:
            if e.button in START_BUTTONS:
                # Start/Options: in menu conferma/avvia, altrimenti mette in
                # pausa. Mai entrambi insieme, altrimenti pausa e conferma
                # scatterebbero nello stesso istante annullandosi a vicenda.
                if game.state == "menu":
                    game.keydown(pygame.K_RETURN)
                else:
                    game.keydown(pygame.K_p)
            elif e.button in DPAD_BUTTON_KEYS:
                # D-pad riportato come pulsanti digitali (PS4 su alcuni
                # driver): stesso comportamento del ramo JOYHATMOTION qui
                # sotto, per la navigazione nei menu / azioni singole.
                game.keydown(DPAD_BUTTON_KEYS[e.button])
            else:
                for key in BUTTON_KEYS.get(e.button, ()):
                    game.keydown(key)
        elif e.type == pygame.JOYHATMOTION:
            hx, hy = e.value
            if hx == -1:
                game.keydown(pygame.K_LEFT)
            elif hx == 1:
                game.keydown(pygame.K_RIGHT)
            if hy == 1:
                game.keydown(pygame.K_UP)
            elif hy == -1:
                game.keydown(pygame.K_DOWN)

    # ---- polling per-frame: solo per la navigazione a stick nei menu ----
    # NB: qui si usa SOLO la levetta analogica (_stick_axis_y), non il D-pad:
    # il D-pad genera gia' un evento JOYHATMOTION singolo (vedi handle_event)
    # che chiama game.keydown() direttamente. Se anche questo polling avesse
    # incluso il D-pad (come faceva _axis_y), ogni pressione avrebbe generato
    # DUE keydown invece di uno: nel menu pausa, dove la selezione e' un
    # semplice toggle a due stati, i due keydown si annullavano a vicenda e
    # il D-pad sembrava non funzionare (mentre lo stick, che passa solo da
    # qui, funzionava regolarmente).
    def update(self, dt, game):
        if not self.sticks:
            return
        ay = self._stick_axis_y()
        direction = -1 if ay < -JOY_DEADZONE else (1 if ay > JOY_DEADZONE else 0)
        if direction != self._last_axis_dir:
            self._last_axis_dir = direction
            if direction and (game.state == "menu" or game.paused):
                game.keydown(pygame.K_UP if direction == -1 else pygame.K_DOWN)

    # ---- stato interno ----
    def _axis_x(self):
        val = 0.0
        for js in self.sticks.values():
            if js.get_numaxes() >= 1:
                a = js.get_axis(0)
                if abs(a) > abs(val):
                    val = a
            if js.get_numhats():
                hx, _ = js.get_hat(0)
                if hx:
                    val = float(hx)
            # D-pad riportato come pulsanti digitali (PS4 su alcuni driver)
            n = js.get_numbuttons()
            if n > 14 and js.get_button(14):
                val = 1.0
            elif n > 13 and js.get_button(13):
                val = -1.0
        return val

    def _stick_axis_y(self):
        """Solo levetta analogica (usata per la navigazione nei menu, dove il
        D-pad e' gia' gestito via JOYHATMOTION: vedi update())."""
        val = 0.0
        for js in self.sticks.values():
            if js.get_numaxes() >= 2:
                a = js.get_axis(1)
                if abs(a) > abs(val):
                    val = a
        return val

    def _axis_y(self):
        """Levetta + D-pad, usata per il movimento continuo in partita
        (_held_virtual_keys): qui niente doppio evento, quindi includere
        anche l'hat va bene."""
        val = self._stick_axis_y()
        for js in self.sticks.values():
            if js.get_numhats():
                _, hy = js.get_hat(0)
                if hy:
                    val = float(-hy)   # l'asse Y della levetta e' invertito rispetto all'hat
            # D-pad riportato come pulsanti digitali (PS4 su alcuni driver)
            n = js.get_numbuttons()
            if n > 12 and js.get_button(12):
                val = 1.0
            elif n > 11 and js.get_button(11):
                val = -1.0
        return val

    def _held_virtual_keys(self):
        extra = set()
        ax, ay = self._axis_x(), self._axis_y()
        if ax < -JOY_DEADZONE:
            extra.add(pygame.K_LEFT)
        elif ax > JOY_DEADZONE:
            extra.add(pygame.K_RIGHT)
        if ay > JOY_DEADZONE:
            extra.add(pygame.K_DOWN)
        return extra
