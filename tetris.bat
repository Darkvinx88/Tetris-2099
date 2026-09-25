@echo off
cd /d "%~dp0"

:: Activate virtual environment

call venv\Scripts\activate.bat

:: Run Launcher in the venv
python ./modules/tetris.py

