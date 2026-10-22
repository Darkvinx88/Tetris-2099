# Tetris 2099

A modern take on the classic, written in Python with pygame.

<img width="1920" height="1080" alt="image" src="https://github.com/user-attachments/assets/556d0c26-9fe8-4867-83f3-95d902926c25" />


## Features

- SRS rotation with wall kicks, ghost piece, hold and a next-queue preview
- Score, levels, combos and back-to-back tracking, with a persisted high score
- **7 game modes**: Classic, Sprint 40L, Ultra 2:00, Marathon, Zen, Cheese Race and 2099 Chaos, with timers, goals and local Top 5 leaderboards
- **2099 Chaos** mode with random events: gravity flip, glitched pieces, bombs, lasers and overclock
- Synthesized sound effects, plus background music from a playlist (chiptune trackers supported)
- Audio-reactive animated backgrounds (synthwave, starfield, plasma, squares) that follow the beat of the current track and speed up with your level
- Keyboard, mouse and gamepad support, with rumble feedback on supported controllers
- Windowed or fullscreen mode (`F11`) with a responsive layout
- Automatic save/resume: closing the game or pausing stores your current run (including the game mode and its timers), and you can pick it up from the main menu ("Continue")
- Main menu and pause menu (Resume, Restart, Options, Main menu, Quit), navigable with keyboard, mouse or gamepad
- Options for music volume, effects volume, vibration and starting background, all saved between sessions

## Screenshots

<img width="1920" height="1080" alt="image" src="https://github.com/user-attachments/assets/0e47af07-4e8d-44ea-b754-c73210803354" />
Main HUD
<img width="1920" height="1080" alt="image" src="https://github.com/user-attachments/assets/12f2597b-4718-475a-93b5-425816fcd5a3" />
Pause Menu

## Requirements

- Python 3.10+
- pygame (`pip install pygame`)
- numpy (`pip install numpy`): needed for the audio analysis and the plasma background. The game runs without it, just without beat-reactive visuals and plasma
- libopenmpt (optional): a system library that gives exact beat sync on tracker music (`.it`, `.xm`, `.s3m`, `.mod`). Without it the game works the same, and trackers just use the background without exact sync

## Run

Set up the virtual environment with `installer.bat`, then start the game with `tetris.bat`.
On Linux just use `installer.sh`, then start the game with `tetris.sh`.

The Linux installer checks for libopenmpt and, if it is missing, offers to install it with your package manager (apt, pacman, dnf, zypper). On immutable systems such as Bazzite it prints the `rpm-ostree` command instead. You can skip this step: it is optional.

On Windows, the release package already includes the libopenmpt DLLs. If you run the game from a plain clone of the repository instead, download libopenmpt from [lib.openmpt.org](https://lib.openmpt.org/) and put `libopenmpt.dll` (and the DLLs it ships with) next to `visuals.py`.

Or, if you prefer doing it by hand:

```bash
pip install pygame numpy
python tetris.py
```

Manual install of libopenmpt on Linux:

```bash
# Debian / Ubuntu
sudo apt install libopenmpt0
# Fedora
sudo dnf install libopenmpt
# Arch
sudo pacman -S libopenmpt
```

## Game modes

Pick a mode from the **MODE** row in the main menu (right under **NEW GAME**): use ←/→ (or Enter, or a click) to change it, then select **NEW GAME** to start. The selected mode is remembered between sessions.

| Mode | Goal | Leaderboard |
|---|---|---|
| **Classic** | Endless stacking: survive as long as you can | High score |
| **Sprint 40L** | Clear 40 lines as fast as you can (3-2-1 countdown) | Best time |
| **Ultra 2:00** | Score as much as possible in 2 minutes | Best score |
| **Marathon** | 15 levels: clear 150 lines to win | Best score |
| **Zen** | No game over, the board clears itself when it fills up. Use `+` / `-` to change the level and `B` to change the background: perfect for trying out backgrounds and music | None |
| **Cheese Race** | Dig through 10 garbage rows as fast as you can | Best time |
| **2099 Chaos** | Classic scoring, with a random event every 7-11 pieces | Best score |

### 2099 Chaos events

| Event | Effect |
|---|---|
| **Gravity Flip** | The board flips upside down for 9 seconds and gravity seems to pull upwards |
| **Glitch Storm** | A couple of upcoming pieces become glitched, with odd or disconnected shapes |
| **Bomb** | An orange single-block piece that blasts a 5x5 area when it lands |
| **Laser** | A white single-block piece that clears the whole row it lands on |
| **Overclock** | Gravity runs 2.5x faster for 8 seconds |

The timed and goal-based modes show a Top 5 leaderboard and a "NEW RECORD!" highlight on the results screen. Press `Enter` to retry or `Esc` to go back to the main menu.

## Controls

### Keyboard

| Key | Action |
|---|---|
| ← / → | Move |
| ↓ | Soft drop |
| ↑ / X | Rotate |
| Z | Rotate (opposite direction) |
| Space | Hard drop |
| C / Shift | Hold |
| P / Esc | Pause (on the results / game over screen: Esc returns to the main menu) |
| R | Restart |
| M | Toggle sound effects |
| + / - | Change level (Zen mode only) |
| B / Shift+B | Next / previous background (this session only) |
| F3 | Background debug HUD |
| [ / ] | Shift the beat sync earlier / later by 10 ms |
| F11 | Toggle fullscreen |

In the main menu and pause menu: ↑/↓ to navigate, Enter/Space to confirm, ←/→ to adjust sliders, switches and the game mode, or click with the mouse.

### Gamepad

Xbox, PlayStation and generic USB/Bluetooth controllers work out of the box, and can be plugged in or removed while the game is running.

| Input | Action |
|---|---|
| Left stick / D-pad | Move, soft drop, navigate menus |
| A / Cross | Rotate, confirm in menus |
| B / Circle | Hard drop |
| X / Square | Rotate (opposite direction) |
| Y / Triangle, LB / L1 | Hold |
| RB / R1 | Rotate (opposite direction) |
| Start / Options | Pause, confirm in the main menu |

Button indices can differ between controllers and drivers. If something is mapped wrong on your pad, edit the `BUTTON_KEYS` and `START_BUTTONS` tables at the top of `modules/joypad.py`.

### Vibration

On controllers that support it, the pad rumbles together with the game sound effects: a light tap for hold and lock, a heavier thump for hard drop, stronger bursts for line clears and level ups, and the strongest rumble for a Tetris and for game over.


## Options

Open **Options** from the main menu:

| Option | What it does |
|---|---|
| Music | Background music volume |
| SFX | Sound effects volume |
| Vibration | Gamepad rumble on / off. Turning it on gives a short test rumble |
| Background | Background shown when the game starts: synthwave, starfield, plasma or squares. The change is previewed immediately |

Music and SFX are also available from the pause menu. All options are saved in `settings.json` and restored the next time you start the game. The `B` key switches background during play without changing the saved one.

## Music

Drop your tracks into the `music` folder and they are picked up automatically and played in shuffled order. Supported formats: `.it`, `.xm`, `.s3m`, `.mod`, `.ogg`, `.mp3`, `.wav`, `.flac`. The game ships with a set of royalty-free tracks.

Tracker formats (`.it`, `.xm`, `.s3m`, `.mod`) rely on the MOD player bundled with SDL2_mixer, which is included in most pygame builds. If a file fails to load, the game skips it and moves on; converting it to `.ogg` is the usual workaround.

## Backgrounds

The animated backgrounds react to the music that is playing:

- **Synthwave**: sun and perspective grid
- **Starfield**: stars in parallax
- **Plasma**: flowing colour field (needs numpy)
- **Squares**: floating squares

Bass drives the pulse, mids shift the colours, highs add sparkle, and the speed grows with your level. Each track is analysed in a background thread the first time it plays, and the result is cached in a `.visuals_cache` folder inside your music folder, so later runs start instantly. Upcoming tracks in the playlist are analysed ahead of time.

For ogg/mp3/wav/flac the beat is estimated from the audio. For trackers, libopenmpt reads the notes of every channel and instruments are classified by sample name (kick, snare, hat, bass...), so the hits are exact. Where names say nothing, it falls back to analysing the rendered audio.

## Project layout

```
tetris.py            main game
modules/modes.py     game modes (Sprint, Ultra, Marathon, Zen, Cheese, 2099) and leaderboards
modules/joypad.py    gamepad support and rumble
modules/music.py     background music playlist
modules/visuals.py   audio-reactive backgrounds
music/               your tracks
```

## Save data

The game creates these files next to the script:

- `savestate.json`: current run in progress, with its game mode (updated during play, removed on game over)
- `highscore.json`: personal best score (Classic mode)
- `records.json`: Top 10 results for Sprint, Ultra, Marathon, Cheese Race and 2099 Chaos
- `settings.json`: preferences such as fullscreen, music and effects volume, vibration, starting background and selected game mode

The audio analysis cache is stored separately, in `.visuals_cache` inside the music folder.

## License

Personal project, provided as-is with no warranty. Feel free to use and modify it.
