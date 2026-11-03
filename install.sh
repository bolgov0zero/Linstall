#!/usr/bin/env bash
# Linstall: установка и запуск одной командой.
#   curl -fsSL https://raw.githubusercontent.com/bolgov0zero/Linstall/main/install.sh | bash
set -euo pipefail

DIR=/opt/linstall
RAW=https://raw.githubusercontent.com/bolgov0zero/Linstall/main

[ "$(id -u)" -eq 0 ] || { echo "Запусти от root."; exit 1; }
command -v apt-get >/dev/null || { echo "Нужен Debian или Ubuntu (apt-get)."; exit 1; }

export DEBIAN_FRONTEND=noninteractive
if ! command -v python3 >/dev/null || ! python3 -c 'import venv, ensurepip' 2>/dev/null; then
  apt-get update -y
  apt-get install -y python3 python3-venv python3-pip curl ca-certificates
fi

mkdir -p "$DIR"
curl -fsSL "$RAW/linstall.py" -o "$DIR/linstall.py"
[ -x "$DIR/venv/bin/python" ] || python3 -m venv "$DIR/venv"
"$DIR/venv/bin/pip" install -q --upgrade textual

exec "$DIR/venv/bin/python" "$DIR/linstall.py" < /dev/tty
