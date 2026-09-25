@echo off
echo ================================
echo    Tetris - A modern version
echo ================================
echo.

:: Checking if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found!
    echo Please install Python 3.10 or higher from https://www.python.org
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

:: Checking minimum Python version (3.10)
python -c "import sys; exit(0) if sys.version_info >= (3,10) else exit(1)" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python version too old!
    for /f "tokens=*" %%i in ('python --version') do echo Detected: %%i
    echo Required: Python 3.10 or higher
    echo Please update Python from https://www.python.org
    pause
    exit /b 1
)

:: Shows the version found
for /f "tokens=*" %%i in ('python --version') do echo [OK] Found %%i

:: Crea virtual environment
echo.
echo Creating virtual environment...
python -m venv venv
if errorlevel 1 (
    echo [ERROR] Failed to create virtual environment.
    pause
    exit /b 1
)
echo [OK] Virtual environment created.

:: Activate Virtual Environment
call venv\Scripts\activate
if errorlevel 1 (
    echo [ERROR] Failed to activate virtual environment.
    pause
    exit /b 1
)
echo [OK] Virtual environment activated.

:: Install Dependencies
echo.
echo Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    echo Check your internet connection and try again.
    pause
    exit /b 1
)
echo [OK] Dependencies installed.

echo.
echo ================================
echo   Installation complete!
echo   Use Tetris.exe to launch the game.
echo ================================
pause
