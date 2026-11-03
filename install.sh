#!/usr/bin/env bash
# Linstall: установка и запуск одной командой.
#   wget -qO- https://raw.githubusercontent.com/bolgov0zero/Linstall/main/install.sh | bash
# Здесь только wget: curl на чистой системе может не быть, Linstall поставит его сам.
set -euo pipefail

DIR=${LINSTALL_DIR:-/opt/linstall}
LOG=${LINSTALL_LOG:-/var/log/linstall-setup.log}
RAW=https://raw.githubusercontent.com/bolgov0zero/Linstall/main

[ "$(id -u)" -eq 0 ] || { echo "Запусти от root."; exit 1; }
command -v apt-get >/dev/null || { echo "Нужен Debian или Ubuntu (apt-get)."; exit 1; }

export DEBIAN_FRONTEND=noninteractive
STATUS=$(mktemp)
trap 'printf "\033[?25h"; rm -f "$STATUS"' EXIT
: > "$LOG"

# ---- окно «Подготовка скрипта»: весь вывод уходит в лог, на экране только прогресс

W=40
PCT=0; MSG=""; SPI=0; FIRST=1
SP='|/-\'
RULE=$(printf '─%.0s' $(seq 1 $((W + 8))))

draw() {
  [ -t 1 ] || return 0
  [ "$FIRST" = 1 ] || printf '\033[5A'
  FIRST=0
  local f=$((PCT * W / 100)) bar="" i
  for ((i = 0; i < W; i++)); do
    if ((i < f)); then bar+="█"; else bar+="░"; fi
  done
  printf '\r\033[K  %s\n' "$RULE"
  printf '\r\033[K  \033[1mПодготовка скрипта\033[0m\n'
  printf '\r\033[K  %s %3d%%\n' "$bar" "$PCT"
  printf '\r\033[K  %s %s\n' "${SP:SPI:1}" "$MSG"
  printf '\r\033[K  %s\n' "$RULE"
}

fail() {
  printf '\033[?25h\n\033[31mОшибка на шаге: %s\033[0m\nЛог: %s\n\n' "$1" "$LOG"
  tail -n 15 "$LOG"
  exit 1
}

# step ОТ ДО "что делаем" команда...   Процент берётся из apt (Status-Fd), у остальных команд просто идёт спиннер.
step() {
  local lo=$1 hi=$2 last p pid
  MSG=$3; shift 3
  : > "$STATUS"; PCT=$lo; draw
  "$@" 3>>"$STATUS" >>"$LOG" 2>&1 &
  pid=$!
  while kill -0 "$pid" 2>/dev/null; do
    SPI=$(((SPI + 1) % 4))
    last=$(tail -n 1 "$STATUS" 2>/dev/null || true)
    case $last in
      dlstatus:*) p=$(awk -F: '{printf "%d", $3 / 2}' <<<"$last") ;;
      pmstatus:*) p=$(awk -F: '{printf "%d", 50 + $3 / 2}' <<<"$last") ;;
      *) p=0 ;;
    esac
    PCT=$((lo + (hi - lo) * p / 100))
    draw; sleep 0.15
  done
  wait "$pid" || fail "$MSG"
  PCT=$hi; draw
}

apt_update()  { apt-get -o APT::Status-Fd=3 update -y; }
apt_install() { apt-get -o APT::Status-Fd=3 install -y --no-install-recommends python3 python3-venv ca-certificates; }
fetch()       { mkdir -p "$DIR" && wget -qO "$DIR/linstall.py" "$RAW/linstall.py"; }
make_venv()   { [ -x "$DIR/venv/bin/python" ] || python3 -m venv "$DIR/venv"; }
pip_textual() { "$DIR/venv/bin/pip" install -q --upgrade textual; }

[ -t 1 ] && printf '\033[2J\033[H'
printf '\033[?25l'
if ! command -v python3 >/dev/null || ! python3 -c 'import venv, ensurepip' 2>/dev/null; then
  step 0 20 "Обновление списка пакетов" apt_update
  step 20 60 "Установка Python" apt_install
  step 60 65 "Загрузка Linstall" fetch
  step 65 70 "Создание окружения" make_venv
  step 70 100 "Установка компонентов интерфейса" pip_textual
else
  step 0 10 "Загрузка Linstall" fetch
  step 10 20 "Создание окружения" make_venv
  step 20 100 "Установка компонентов интерфейса" pip_textual
fi

rm -f "$STATUS"
printf '\033[?25h\033[2J\033[H'
exec "$DIR/venv/bin/python" "$DIR/linstall.py" < /dev/tty
