#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
elif command -v sudo >/dev/null 2>&1; then
  SUDO="sudo"
else
  SUDO=""
fi

install_python_linux() {
  echo "Python not found. Forcing installation..."
  if command -v apt-get >/dev/null 2>&1; then
    $SUDO apt-get update -y && $SUDO apt-get install -y python3 python3-pip python3-websockets
  elif command -v dnf >/dev/null 2>&1; then
    $SUDO dnf install -y python3 python3-pip python3-websockets
  elif command -v pacman >/dev/null 2>&1; then
    $SUDO pacman -Sy --noconfirm python python-pip python-websockets
  elif command -v apk >/dev/null 2>&1; then
    $SUDO apk add --no-cache python3 py3-pip py3-websockets
  else
    echo "[ERROR] No supported package manager found to auto-install Python."
    exit 1
  fi
}

PY_BIN=""
if command -v python3 >/dev/null 2>&1; then
  PY_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PY_BIN="python"
else
  install_python_linux
  if command -v python3 >/dev/null 2>&1; then
    PY_BIN="python3"
  elif command -v python >/dev/null 2>&1; then
    PY_BIN="python"
  else
    echo "[ERROR] Python installation failed."
    exit 1
  fi
fi

if ! "$PY_BIN" -c "import websockets" >/dev/null 2>&1; then
  echo "Installing websockets..."
  "$PY_BIN" -m pip install --break-system-packages websockets 2>/dev/null \
    || "$PY_BIN" -m pip install websockets 2>/dev/null \
    || ${SUDO:+$SUDO }apt-get install -y python3-websockets 2>/dev/null \
    || true
fi

open_browser() {
  local url="$1"
  if command -v xdg-open >/dev/null 2>&1; then
    nohup xdg-open "$url" >/dev/null 2>&1 &
  elif command -v gio >/dev/null 2>&1; then
    nohup gio open "$url" >/dev/null 2>&1 &
  elif command -v sensible-browser >/dev/null 2>&1; then
    nohup sensible-browser "$url" >/dev/null 2>&1 &
  fi
}

echo "Starting Spelling Bee Server..."
"$PY_BIN" "$SCRIPT_DIR/server.py" &
SERVER_PID=$!

sleep 2
open_browser "http://localhost:8000/teacher.html"

wait "$SERVER_PID"