# Tetris 2099

A modern take on the classic, written in Python with pygame.

<img width="1920" height="1080" alt="Tetris 2099 screenshot" src="https://github.com/user-attachments/assets/dbaeebac-34df-4431-8609-f85a8c833c3d" />

## Features

- SRS rotation with wall kicks, ghost piece, hold and a next-queue preview
- Score, levels, combos and back-to-back tracking, with a persisted high score
- Synthesized sound effects, plus background music from a playlist (chiptune trackers supported)
- Keyboard, mouse and gamepad support
- Windowed or fullscreen mode (`F11`) with a responsive layout
- Automatic save/resume: closing the game or pausing stores your current run, and you can pick it up from the main menu ("Continue")
- Main menu and pause menu, navigable with keyboard, mouse or gamepad

## Requirements

- Python 3.9+
- pygame (`pip install pygame`)

## Run

Set up the virtual environment with `installer.bat`, then start the game with `tetris.bat`.
On linux just use the `installer.sh`, then start the game with `tetris.sh`.

Or, if you prefer doing it by hand:

```bash
pip install pygame
python tetris.py
```

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
| P / Esc | Pause |
| R | Restart |
| M | Toggle audio |
| F11 | Toggle fullscreen |

In the main menu and pause menu: ↑/↓ to navigate, Enter/Space to confirm, or click with the mouse.

### Gamepad

Xbox, PlayStation and generic USB/Bluetooth controllers work out of the box, and can be plugged in or removed while the game is running.

| Input | Action |
|---|---|
| Left stick / D-pad | Move, soft drop |
| A / Cross | Rotate, confirm in menus |
| B / Circle | Hard drop |
| X / Square | Rotate (opposite direction) |
| Y / Triangle, LB / L1 | Hold |
| RB / R1 | Rotate (opposite direction) |
| Start / Options | Pause, confirm in the main menu |

Button indices can differ between controllers and drivers. If something is mapped wrong on your pad, edit the `BUTTON_KEYS` and `START_BUTTONS` tables at the top of `modules/joypad.py`.

## Music

Drop your tracks into the `music` folder and they are picked up automatically and played in shuffled order. Supported formats: `.it`, `.xm`, `.s3m`, `.mod`, `.ogg`, `.mp3`, `.wav`, `.flac`.

Tracker formats (`.it`, `.xm`, `.s3m`, `.mod`) rely on the MOD player bundled with SDL2_mixer, which is included in most pygame builds. If a file fails to load, the game skips it and moves on; converting it to `.ogg` is the usual workaround.

## Project layout

```
tetris.py          main game
modules/joypad.py  gamepad support
modules/music.py   background music playlist
music/             your tracks
```

## Save data

The game creates these files next to the script:

- `savestate.json`: current run in progress (updated during play, removed on game over)
- `highscore.json`: personal best score
- `settings.json`: preferences such as fullscreen

## License

Personal project, provided as-is with no warranty. Feel free to use and modify it.
