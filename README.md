# Tetris 2099
A modern Tetris interpretaion of the timeless classic written in Python 

<img width="1920" height="1080" alt="image" src="https://github.com/user-attachments/assets/dbaeebac-34df-4431-8609-f85a8c833c3d" />



## Features

- SRS rotation with wall kicks, ghost piece, hold (with a "next queue" preview)
- Score, levels, combos and back-to-back tracking, persisted high score
- Procedurally generated sound effects and light particle/animation polish
- Windowed or fullscreen mode (`F11`), with a responsive layout
- **Automatic save/resume**: closing the game or pausing saves your current run, so you can pick it up later from the main menu ("Continue")
- Main menu and pause menu, navigable with both keyboard and mouse

## Requirements

- Python 3.9+
- pygame (`pip install pygame`)

## Run

```bash
install the venv with the given installer.bat
run the tetris.bat file
```

## Controls

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

## Save data

The game automatically creates these files next to the script:

- `savestate.json` — current run in progress (created/updated during play, removed on game over)
- `highscore.json` — personal best score
- `settings.json` — preferences (e.g. fullscreen)

## License

Personal project, provided as-is with no warranty. Feel free to use and modify.
