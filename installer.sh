#!/bin/bash

echo "================================"
echo "   Tetris 2099 - Installer"
echo "================================"
echo

# Script directory
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

# Fix permissions
echo "Setting permissions..."
chmod +x "$DIR/installer.sh" 2>/dev/null
chmod +x "$DIR/Tetris.sh" 2>/dev/null
echo "[OK] Permissions set."
echo

# Checks if  Python3 is installed
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] Python3 not found!"
    echo "Please install Python 3.10 or higher."
    echo "  Ubuntu/Debian: sudo apt install python3 python3-venv"
    echo "  Fedora/Bazzite: sudo dnf install python3"
    echo "  Arch: sudo pacman -S python"
    exit 1
fi

# checks python minimum version (3.10)
python3 -c "import sys; exit(0) if sys.version_info >= (3,10) else exit(1)" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "[ERROR] Python version too old!"
    echo "Detected: $(python3 --version)"
    echo "Required: Python 3.10 or higher"
    exit 1
fi

echo "[OK] Found $(python3 --version)"

# Checks if python3-venv is available
python3 -m venv --help &>/dev/null
if [ $? -ne 0 ]; then
    echo "[ERROR] python3-venv not found!"
    echo "Please install it:"
    echo "  Ubuntu/Debian: sudo apt install python3-venv"
    echo "  Fedora/Bazzite: sudo dnf install python3"
    exit 1
fi



# Crea virtual environment
echo
echo "Creating virtual environment..."
python3 -m venv "$DIR/venv"
if [ $? -ne 0 ]; then
    echo "[ERROR] Failed to create virtual environment."
    exit 1
fi
echo "[OK] Virtual environment created."

# Activate Venv
source "$DIR/venv/bin/activate"
if [ $? -ne 0 ]; then
    echo "[ERROR] Failed to activate virtual environment."
    exit 1
fi
echo "[OK] Virtual environment activated."

# Install dependencies
echo
echo "Installing dependencies..."
pip install -r "$DIR/requirements.txt"
if [ $? -ne 0 ]; then
    echo "[ERROR] Failed to install dependencies."
    echo "Check your internet connection and try again."
    exit 1
fi
echo "[OK] Dependencies installed."

# ---------------------------------------------------------------------------
# libopenmpt (system library, OPTIONAL)
# Used by visuals.py (via ctypes) for exact beat sync on tracker music
# (.it .xm .s3m .mod). pip cannot install it. Without it the game still
# works: trackers just get the background without exact sync.
# ---------------------------------------------------------------------------
echo
have_openmpt() {
    ldconfig -p 2>/dev/null | grep -q "libopenmpt\.so" && return 0
    ls "$DIR"/libopenmpt*.so* &>/dev/null && return 0
    return 1
}

if have_openmpt; then
    echo "[OK] libopenmpt found."
else
    echo "[WARN] libopenmpt not found (optional: beat sync for tracker music)."
    PM_CMD=""
    if command -v apt-get &>/dev/null; then
        PM_CMD="sudo apt-get install -y libopenmpt0"
    elif command -v pacman &>/dev/null; then
        PM_CMD="sudo pacman -S --needed --noconfirm libopenmpt"
    elif command -v rpm-ostree &>/dev/null; then
        echo "  Immutable system detected (Bazzite/Silverblue): the library"
        echo "  would need a layered package + reboot:"
        echo "    sudo rpm-ostree install libopenmpt"
        echo "  Skipping. You can do it later; the game works without it."
    elif command -v dnf &>/dev/null; then
        PM_CMD="sudo dnf install -y libopenmpt"
    elif command -v zypper &>/dev/null; then
        PM_CMD="sudo zypper install -y libopenmpt0"
    fi

    if [ -n "$PM_CMD" ]; then
        echo "  Command: $PM_CMD"
        if [ -t 0 ]; then
            read -r -p "  Install it now? [y/N] " ANS
        else
            ANS="n"
        fi
        if [[ "$ANS" =~ ^[Yy]$ ]]; then
            if $PM_CMD && have_openmpt; then
                echo "[OK] libopenmpt installed."
            else
                echo "[WARN] Could not install libopenmpt. Continuing without it."
            fi
        else
            echo "  Skipped. Run the command above later if you want beat sync."
        fi
    fi
fi

echo
echo "================================"
echo "  Installation complete!"
echo "  Run ./Tetris.sh to start."
echo "================================"
