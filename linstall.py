#!/usr/bin/env python3
"""Linstall: TUI для установки программ и настройки Debian/Ubuntu."""
from __future__ import annotations

import glob
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widget import Widget
from textual.widgets import Button, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

SSHD_CONFIG = "/etc/ssh/sshd_config"
SSHD_DROPINS = "/etc/ssh/sshd_config.d/*.conf"
LINFW_URL = "https://raw.githubusercontent.com/bolgov0zero/LinFW/main/install.sh"
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

# (название, хост для Debian, хост для Ubuntu); None: зеркала для дистрибутива нет.
MIRRORS = [
    ("Яндекс, Россия", "mirror.yandex.ru", "mirror.yandex.ru"),
    ("МИФИ, Россия", "mirror.mephi.ru", None),
    ("TrueNetwork, Россия", "mirror.truenetwork.ru", "mirror.truenetwork.ru"),
    ("Selectel, Россия", "mirror.selectel.ru", "mirror.selectel.ru"),
    ("Финляндия", "ftp.fi.debian.org", "fi.archive.ubuntu.com"),
    ("Эстония", "ftp.ee.debian.org", "ee.archive.ubuntu.com"),
    ("Швеция", "ftp.se.debian.org", "se.archive.ubuntu.com"),
    ("Литва", "ftp.lt.debian.org", "lt.archive.ubuntu.com"),
    ("Чехия", "ftp.cz.debian.org", "cz.archive.ubuntu.com"),
    ("Германия", "ftp.de.debian.org", "de.archive.ubuntu.com"),
    ("Польша", "ftp.pl.debian.org", "pl.archive.ubuntu.com"),
]

TIMEZONES = [
    ("Europe/Kaliningrad", "Калининград, UTC+2"),
    ("Europe/Moscow", "Москва, UTC+3"),
    ("Europe/Minsk", "Минск, UTC+3"),
    ("Europe/Samara", "Самара, UTC+4"),
    ("Asia/Yekaterinburg", "Екатеринбург, UTC+5"),
    ("Asia/Almaty", "Алматы, UTC+5"),
    ("Asia/Omsk", "Омск, UTC+6"),
    ("Asia/Novosibirsk", "Новосибирск, UTC+7"),
    ("Asia/Krasnoyarsk", "Красноярск, UTC+7"),
    ("Asia/Irkutsk", "Иркутск, UTC+8"),
    ("Asia/Yakutsk", "Якутск, UTC+9"),
    ("Asia/Vladivostok", "Владивосток, UTC+10"),
    ("Asia/Magadan", "Магадан, UTC+11"),
    ("Asia/Kamchatka", "Камчатка, UTC+12"),
    ("UTC", "UTC"),
]


# ---------------------------------------------------------------- система

def distro() -> str:
    try:
        data = open("/etc/os-release").read().lower()
    except OSError:
        return "debian"
    ids = re.findall(r'^(?:id|id_like)="?([^"\n]*)', data, re.M)
    return "ubuntu" if any("ubuntu" in i for i in ids) else "debian"


def run_out(cmd: List[str]) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
        return p.stdout.strip() if p.returncode == 0 else ""
    except Exception:
        return ""


def sshd_get(key: str) -> Optional[str]:
    """Действующее значение параметра sshd (sshd -T, иначе разбор файлов)."""
    key = key.lower()
    sshd = shutil.which("sshd") or "/usr/sbin/sshd"
    for line in run_out([sshd, "-T"]).splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == key:
            return parts[1].strip().lower()
    files = sorted(glob.glob(SSHD_DROPINS)) + [SSHD_CONFIG]
    for path in files:
        try:
            for line in open(path):
                m = re.match(r"\s*(\S+)\s+(.+)", line)
                if m and m.group(1).lower() == key:
                    return m.group(2).strip().lower()
        except OSError:
            continue
    return None


def set_sshd(key: str, value: str) -> None:
    """Задаёт параметр в sshd_config так, чтобы он остался единственным."""
    kre = re.compile(rf"^\s*{key}\s", re.I)
    cre = re.compile(rf"^\s*#\s*{key}\s", re.I)
    for path in sorted(glob.glob(SSHD_DROPINS)):
        lines = open(path).read().splitlines()
        kept = [l for l in lines if not kre.match(l)]
        if kept != lines:
            open(path, "w").write("\n".join(kept) + "\n")
    if not os.path.exists(SSHD_CONFIG + ".linstall.bak"):
        shutil.copy2(SSHD_CONFIG, SSHD_CONFIG + ".linstall.bak")
    lines = open(SSHD_CONFIG).read().splitlines()
    end = next((i for i, l in enumerate(lines) if re.match(r"\s*Match\s", l, re.I)), len(lines))
    head, tail, out, placed = lines[:end], lines[end:], [], False
    for l in head:
        if kre.match(l):
            if not placed:
                out.append(f"{key} {value}")
                placed = True
            continue
        out.append(l)
    if not placed:
        for i, l in enumerate(out):
            if cre.match(l):
                out[i] = f"{key} {value}"
                placed = True
                break
    if not placed:
        out.append(f"{key} {value}")
    open(SSHD_CONFIG, "w").write("\n".join(out + tail) + "\n")


def current_mirror() -> Optional[str]:
    paths = ["/etc/apt/sources.list"] + sorted(glob.glob("/etc/apt/sources.list.d/*.list")) \
        + sorted(glob.glob("/etc/apt/sources.list.d/*.sources"))
    for path in paths:
        try:
            m = re.search(r"https?://([A-Za-z0-9.-]+)/(?:debian|ubuntu)/", open(path).read())
        except OSError:
            continue
        if m and m.group(1) not in ("security.ubuntu.com", "security.debian.org"):
            return m.group(1)
    return None


def set_mirror(host: str) -> None:
    pat = re.compile(r"(https?://)([A-Za-z0-9.-]+)(/(?:debian|ubuntu)/)")

    def sub(m):
        if m.group(2) in ("security.ubuntu.com", "security.debian.org"):
            return m.group(0)
        return m.group(1) + host + m.group(3)

    paths = ["/etc/apt/sources.list"] + glob.glob("/etc/apt/sources.list.d/*.list") \
        + glob.glob("/etc/apt/sources.list.d/*.sources")
    for path in paths:
        try:
            src = open(path).read()
        except OSError:
            continue
        new = pat.sub(sub, src)
        if new != src:
            if not os.path.exists(path + ".linstall.bak"):
                shutil.copy2(path, path + ".linstall.bak")
            open(path, "w").write(new)


# --------------------------------------------------------------- установка

class Runner:
    """Выполняет шаги установки и пишет вывод в лог."""

    def __init__(self, demo: bool) -> None:
        self.demo = demo
        self.apt_updated = False
        self.path = os.path.join(tempfile.gettempdir(), "linstall.log") if demo else "/var/log/linstall.log"
        self.log = open(self.path, "a")

    def sh(self, cmd: str) -> int:
        self.log.write(f"\n$ {cmd.strip()}\n")
        self.log.flush()
        if self.demo:
            time.sleep(random.uniform(0.8, 1.8))
            return 0
        env = dict(os.environ, DEBIAN_FRONTEND="noninteractive")
        p = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", cmd], stdin=subprocess.DEVNULL,
                           stdout=self.log, stderr=subprocess.STDOUT, env=env)
        return p.returncode

    def must(self, cmd: str) -> None:
        rc = self.sh(cmd)
        if rc:
            raise RuntimeError(f"код выхода {rc}")

    def apt(self, packages: str) -> None:
        if not self.apt_updated:
            self.must("apt-get update -y")
            self.apt_updated = True
        self.must(f"apt-get install -y -o DPkg::Lock::Timeout=120 {packages}")


def real_only(fn: Callable) -> Callable:
    """В демо-режиме файлы не трогаем, только имитируем работу."""
    def wrap(r: Runner, v: Optional[str]) -> None:
        if r.demo:
            r.sh("# demo")
        else:
            fn(r, v)
    return wrap


def restart_ssh(r: Runner) -> None:
    r.must("sshd -t || /usr/sbin/sshd -t")
    r.must("systemctl daemon-reload; systemctl restart ssh.socket 2>/dev/null || true; "
           "systemctl restart ssh 2>/dev/null || systemctl restart sshd")


@real_only
def run_root(r, v):
    set_sshd("PermitRootLogin", "yes")
    restart_ssh(r)


@real_only
def run_port(r, v):
    set_sshd("Port", v)
    restart_ssh(r)


def run_update(r, v):
    r.must("apt-get update -y && apt-get full-upgrade -y -o Dpkg::Options::=--force-confold "
           "-o DPkg::Lock::Timeout=120 && apt-get autoremove -y")
    r.apt_updated = True


@real_only
def run_mirror(r, v):
    set_mirror(v)
    r.apt_updated = False


def run_tz(r, v):
    r.must(f"timedatectl set-timezone {v}")


def run_host(r, v):
    r.must(f"""hostnamectl set-hostname {v}
if grep -q '^127.0.1.1' /etc/hosts; then sed -i -E 's/^127\\.0\\.1\\.1.*/127.0.1.1 {v}/' /etc/hosts
else echo '127.0.1.1 {v}' >> /etc/hosts; fi""")


def run_bbr(r, v):
    r.must("""printf 'net.core.default_qdisc=fq\\nnet.ipv4.tcp_congestion_control=bbr\\n' > /etc/sysctl.d/99-linstall-bbr.conf
modprobe tcp_bbr || true
sysctl --system > /dev/null
[ "$(sysctl -n net.ipv4.tcp_congestion_control)" = bbr ]""")


def run_neofetch(r, v):
    if r.sh("apt-cache show neofetch > /dev/null 2>&1") == 0 or r.demo:
        r.apt("neofetch")
    else:
        r.apt("fastfetch")


def run_linfw(r, v):
    r.must(f"curl -fsSL {LINFW_URL} | bash")


def run_docker(r, v):
    r.must("curl -fsSL https://get.docker.com | sh")
    r.must("docker compose version > /dev/null 2>&1 || apt-get install -y docker-compose-plugin")


# ------------------------------------------------------------------ пункты

@dataclass
class Item:
    section: str
    name: str
    desc: str
    run: Callable
    order: int = 40
    prompt: Optional[str] = None
    detect: Optional[Callable[[], Tuple[bool, Optional[str]]]] = None
    cmd: str = ""
    label: Optional[Callable[[], str]] = None
    note: str = ""
    repeatable: bool = False
    locked: bool = False     # обязательный пункт: если не установлен, отметка не снимается

    def command(self) -> str:
        return self.label() if self.label else self.cmd


def d_root():
    return sshd_get("permitrootlogin") == "yes", None


def d_port():
    port = sshd_get("port") or "22"
    return port != "22", port


def d_tz():
    tz = run_out(["timedatectl", "show", "-p", "Timezone", "--value"])
    if not tz:
        try:
            tz = open("/etc/timezone").read().strip()
        except OSError:
            tz = ""
    return bool(tz) and tz not in ("UTC", "Etc/UTC", "Etc/UCT"), tz or None


def d_host():
    name = socket.gethostname()
    return name not in ("localhost", "debian", "ubuntu"), name


def d_mirror():
    host = current_mirror()
    known = {m[1] for m in MIRRORS} | {m[2] for m in MIRRORS if m[2]}
    return host in known, host


def d_bbr():
    try:
        return open("/proc/sys/net/ipv4/tcp_congestion_control").read().strip() == "bbr", None
    except OSError:
        return False, None


def d_docker():
    ok = bool(shutil.which("docker")) and subprocess.run(
        ["docker", "compose", "version"], capture_output=True).returncode == 0
    return ok, None


def package(section: str, name: str, desc: str, cmd: str, order: int = 40, locked: bool = False) -> Item:
    return Item(section, name, desc, lambda r, v: r.apt(cmd), order, cmd=cmd,
                detect=lambda: (bool(shutil.which(cmd)), None), locked=locked)


SYS, UTIL, MON, SEC, DOCK = "НАСТРОЙКА СИСТЕМЫ", "БАЗОВЫЕ УТИЛИТЫ", "МОНИТОРИНГ", "БЕЗОПАСНОСТЬ", "DOCKER"

ITEMS = [
    Item(SYS, "Вход под root", "Разрешает вход по SSH под root (PermitRootLogin yes) и перезапускает ssh.",
         run_root, 10, detect=d_root),
    Item(SYS, "Порт SSH", "Меняет порт SSH в sshd_config. Порт вводится в окне.", run_port, 11,
         prompt="port", detect=d_port, note="открой новый порт в файрволе"),
    Item(SYS, "Обновить систему", "apt update, full-upgrade и autoremove.", run_update, 20, repeatable=True),
    Item(SYS, "Зеркало apt", "Зеркало, доступное из РФ. Выбор из списка.", run_mirror, 5,
         prompt="mirror", detect=d_mirror),
    Item(SYS, "Часовой пояс", "Устанавливает часовой пояс. Выбор из списка.", run_tz, 12,
         prompt="tz", detect=d_tz),
    Item(SYS, "Имя машины", "Меняет hostname. Имя вводится в окне.", run_host, 13,
         prompt="host", detect=d_host),
    Item(SYS, "BBR", "Включает TCP BBR для более быстрой сети.", run_bbr, 14, detect=d_bbr),
    package(UTIL, "curl", "Запросы и загрузка файлов по HTTP. Нужен LinFW и Docker.", "curl", order=1, locked=True),
    package(UTIL, "wget", "Скачивание файлов, умеет докачку.", "wget"),
    package(UTIL, "git", "Система контроля версий.", "git"),
    package(UTIL, "unzip", "Распаковка zip-архивов.", "unzip"),
    package(UTIL, "micro", "Простой консольный редактор.", "micro"),
    package(UTIL, "mc", "Midnight Commander, файловый менеджер.", "mc"),
    package(UTIL, "tmux", "Сессии, не обрываются при потере SSH.", "tmux"),
    Item(UTIL, "neofetch", "Сводка о системе в одну команду.", run_neofetch, 40, cmd="neofetch",
         label=lambda: "neofetch" if shutil.which("neofetch") else "fastfetch",
         detect=lambda: (bool(shutil.which("neofetch") or shutil.which("fastfetch")), None)),
    package(MON, "btop", "Монитор процессора, памяти, диска и сети.", "btop"),
    package(MON, "iotop", "Какие процессы нагружают диск.", "iotop"),
    package(MON, "ncdu", "Что занимает место на диске.", "ncdu"),
    Item(SEC, "LinFW", "Файрвол LinFW, ставится скриптом с GitHub.", run_linfw, 80, cmd="linfw",
         detect=lambda: (bool(shutil.which("linfw")), None)),
    Item(DOCK, "Docker", "Docker Engine. Compose ставится вместе с ним.", run_docker, 90,
         cmd="docker, docker compose", detect=d_docker),
]


# ---------------------------------------------------------------- валидация

def check_port(v: str) -> str:
    return "" if v.isdigit() and 1 <= int(v) <= 65535 else "Нужно число от 1 до 65535"


def check_host(v: str) -> str:
    ok = re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?", v)
    return "" if ok else "Только латиница, цифры и дефис"


# ------------------------------------------------------------------- окна

class InputModal(ModalScreen[Optional[str]]):
    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(self, title: str, desc: str, default: str, check: Callable[[str], str]) -> None:
        super().__init__()
        self.title_, self.desc, self.default, self.check = title, desc, default, check

    def compose(self) -> ComposeResult:
        with Vertical(classes="dlg"):
            yield Label(self.title_, classes="dtitle")
            yield Label(self.desc, classes="ddesc")
            yield Input(value=self.default, id="inp")
            yield Label("", id="err")
            with Horizontal(classes="btns"):
                yield Button("Отмена", id="cancel")
                yield Button("Готово", id="ok", variant="primary")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_changed(self) -> None:
        self.query_one("#err", Label).update("")

    def _accept(self) -> None:
        value = self.query_one(Input).value.strip()
        error = self.check(value)
        if error:
            self.query_one("#err", Label).update(error)
        else:
            self.dismiss(value)

    def on_input_submitted(self) -> None:
        self._accept()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self._accept() if event.button.id == "ok" else self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ChoiceModal(ModalScreen[Optional[str]]):
    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(self, title: str, desc: str, options: List[Tuple[str, str]], current: Optional[str]) -> None:
        super().__init__()
        self.title_, self.desc, self.options, self.current = title, desc, options, current

    def compose(self) -> ComposeResult:
        with Vertical(classes="dlg"):
            yield Label(self.title_, classes="dtitle")
            yield Label(self.desc, classes="ddesc")
            yield OptionList(*[Option(label, id=value) for value, label in self.options])
            with Horizontal(classes="btns"):
                yield Button("Отмена", id="cancel")

    def on_mount(self) -> None:
        ol = self.query_one(OptionList)
        ids = [v for v, _ in self.options]
        ol.highlighted = ids.index(self.current) if self.current in ids else 0
        ol.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def on_button_pressed(self) -> None:
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmModal(ModalScreen[bool]):
    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(self, title: str, desc: str) -> None:
        super().__init__()
        self.title_, self.desc = title, desc

    def compose(self) -> ComposeResult:
        with Vertical(classes="dlg"):
            yield Label(self.title_, classes="dtitle")
            yield Label(self.desc, classes="ddesc")
            with Horizontal(classes="btns"):
                yield Button("Отмена", id="cancel")
                yield Button("Перезагрузить", id="ok", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "ok")

    def action_cancel(self) -> None:
        self.dismiss(False)


def make_modal(item: Item, current: Optional[str]) -> ModalScreen:
    if item.prompt == "port":
        return InputModal("Порт SSH", "Введи новый порт SSH (1–65535).", current or "22", check_port)
    if item.prompt == "host":
        return InputModal("Имя машины", "Введи новое имя (hostname).", current or "server", check_host)
    if item.prompt == "tz":
        opts = [(v, f"{v}  {d}" if d != v else v) for v, d in TIMEZONES]
        if current and current not in [v for v, _ in opts]:
            opts.insert(0, (current, current))
        return ChoiceModal("Часовой пояс", "Выбери часовой пояс.", opts, current or "Europe/Moscow")
    idx = 2 if distro() == "ubuntu" else 1
    opts = [(m[idx], f"{m[idx]}  {m[0]}") for m in MIRRORS if m[idx]]
    return ChoiceModal("Зеркало apt", "Выбери зеркало.", opts, current or opts[0][0])


# ---------------------------------------------------------------- виджеты

class ItemRow(Widget, can_focus=True):
    DEFAULT_CSS = """
    ItemRow { layout: horizontal; height: auto; width: 100%; padding: 0 1; }
    ItemRow:hover { background: $boost; }
    ItemRow:focus { background: $accent 30%; }
    ItemRow .mark { width: 5; height: auto; }
    ItemRow .body { width: 1fr; height: auto; }
    ItemRow .desc { color: $text-muted; }
    ItemRow .val { color: $warning; }
    """
    BINDINGS = [
        Binding("space", "toggle", show=False),
        Binding("up", "move('up')", show=False),
        Binding("down", "move('down')", show=False),
        Binding("left", "move('left')", show=False),
        Binding("right", "move('right')", show=False),
    ]

    def __init__(self, item: Item) -> None:
        super().__init__()
        self.item = item
        self.state = ""          # "", "on" (выбрано), "ok" (уже установлено)
        self.base = ""           # состояние, которое нашла проверка системы
        self.value: Optional[str] = None
        self.current: Optional[str] = None

    def compose(self) -> ComposeResult:
        yield Static("", classes="mark")
        with Vertical(classes="body"):
            yield Static(Text(self.item.name), classes="name")
            yield Static(Text(self.item.desc), classes="desc")
            yield Static("", classes="val")

    def on_mount(self) -> None:
        self.paint()

    def paint(self) -> None:
        mark = {"": ("[ ]", "dim"), "on": ("[x]", "bold yellow"), "ok": ("[✔]", "bold green")}[self.state]
        self.query_one(".mark", Static).update(Text(mark[0], style=mark[1]))
        val = self.query_one(".val", Static)
        if self.state == "on" and self.value:
            val.update(Text("→ " + self.value, style="yellow"))
            val.display = True
        elif self.state == "on" and self.item.locked:
            val.update(Text("обязательный пункт", style="dim"))
            val.display = True
        elif self.current and self.item.prompt:
            val.update(Text("сейчас: " + self.current, style="dim"))
            val.display = True
        else:
            val.display = False

    def apply_detect(self, ok: bool, value: Optional[str]) -> None:
        self.base = "ok" if ok else ("on" if self.item.locked else "")
        self.current = value
        if self.state != "on":
            self.state = self.base
        self.paint()

    def action_toggle(self) -> None:
        item = self.item
        if self.state == "on" and item.locked:
            self.app.notify("Обязательный пункт, снять нельзя")
            return
        if self.state == "on":
            self.state, self.value = self.base, None
        elif self.state == "ok" and not item.prompt:
            self.app.notify("Уже установлено")
            return
        elif item.prompt:
            self.app.push_screen(make_modal(item, self.current), self._chosen)
            return
        else:
            self.state = "on"
        self.paint()
        self.screen.update_count()

    def _chosen(self, value: Optional[str]) -> None:
        if value is not None:
            self.value, self.state = value, "on"
            self.paint()
            self.screen.update_count()

    def on_click(self) -> None:
        self.focus()
        self.action_toggle()

    def action_move(self, direction: str) -> None:
        self.screen.move_focus(self, direction)


# ------------------------------------------------------------------ экраны

class MainScreen(Screen):
    BINDINGS = [Binding("enter", "install", show=False)]
    HINT = "пробел или клик: отметить · Enter: установить · q: выход"

    def __init__(self) -> None:
        super().__init__()
        self.groups: List[List[ItemRow]] = []
        for name in dict.fromkeys(i.section for i in ITEMS):
            self.groups.append([ItemRow(i) for i in ITEMS if i.section == name])

    def compose(self) -> ComposeResult:
        with Horizontal(id="bar"):
            yield Label("Linstall", id="title")
            yield Label("", id="count")
        with VerticalScroll(id="list"):
            for rows in self.groups:
                yield Label(rows[0].item.section, classes="section")
                with Grid(classes="grid"):
                    for row in rows:
                        yield row
        with Horizontal(id="foot"):
            yield Label("Проверяю систему…", id="hint")
            yield Button("Выход", id="quit")
            yield Button("Установить", id="go", variant="primary")

    def on_mount(self) -> None:
        self.groups[0][0].focus()
        self.update_count()
        self.run_worker(self._detect, thread=True)

    def _detect(self) -> None:
        for rows in self.groups:
            for row in rows:
                if row.item.detect:
                    try:
                        ok, value = row.item.detect()
                    except Exception:
                        ok, value = False, None
                    self.app.call_from_thread(row.apply_detect, ok, value)
        self.app.call_from_thread(self.set_hint, self.HINT)

    def set_hint(self, text: str, error: bool = False) -> None:
        hint = self.query_one("#hint", Label)
        hint.update(text)
        hint.set_class(error, "error")

    def selected(self) -> List[ItemRow]:
        return [r for rows in self.groups for r in rows if r.state == "on"]

    def update_count(self) -> None:
        self.query_one("#count", Label).update(f"выбрано: {len(self.selected())}")
        self.set_hint(self.HINT)

    def move_focus(self, row: ItemRow, direction: str) -> None:
        for si, sec in enumerate(self.groups):
            if row in sec:
                break
        i, col, target = sec.index(row), sec.index(row) % 2, None
        if direction == "left" and col == 1:
            target = sec[i - 1]
        elif direction == "right" and col == 0 and i + 1 < len(sec):
            target = sec[i + 1]
        elif direction == "down":
            if i + 2 < len(sec):
                target = sec[i + 2]
            elif (i // 2 + 1) * 2 < len(sec):
                target = sec[-1]
            elif si + 1 < len(self.groups):
                nxt = self.groups[si + 1]
                target = nxt[col] if col < len(nxt) else nxt[0]
        elif direction == "up":
            if i >= 2:
                target = sec[i - 2]
            elif si > 0:
                prev = self.groups[si - 1]
                idx = (len(prev) - 1) // 2 * 2 + col
                target = prev[idx] if idx < len(prev) else prev[-1]
        if target:
            target.focus()

    def action_install(self) -> None:
        rows = sorted(self.selected(), key=lambda r: r.item.order)
        if not any(not r.item.locked for r in rows):
            self.set_hint("Отметь хотя бы один пункт", error=True)
            return
        self.app.push_screen(InstallScreen([(r.item, r.value) for r in rows]), self._finished)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "go":
            self.action_install()
        else:
            self.app.exit()

    def _finished(self, results: Optional[list]) -> None:
        by_name = {r.item.name: r for rows in self.groups for r in rows}
        for item, value, error in results or []:
            row = by_name[item.name]
            if error is None and not item.repeatable:
                row.base = "ok"
                if value and item.prompt:
                    row.current = value
            row.state, row.value = row.base, None
            row.paint()
        self.update_count()


class InstallScreen(Screen):
    BINDINGS = [Binding("enter", "back", show=False), Binding("escape", "back", show=False)]

    def __init__(self, jobs: List[Tuple[Item, Optional[str]]]) -> None:
        super().__init__()
        self.jobs = jobs
        self.results: list = []
        self.done = False
        self.running = -1
        self.frame = 0

    def line(self, item: Item, value: Optional[str], error: Optional[str] = None, finished: bool = False) -> Text:
        text = Text(item.name)
        if value:
            text.append("  → " + value, style="yellow")
        if finished and error is None:
            if item.command():
                text.append("  (команда: ", style="dim")
                text.append(item.command(), style="bold green")
                text.append(")", style="dim")
            if item.note:
                text.append("  (" + item.note + ")", style="dim")
        if error:
            text.append(f"  ошибка: {error}", style="red")
        return text

    def compose(self) -> ComposeResult:
        with Horizontal(id="bar"):
            yield Label("Linstall", id="title")
            yield Label("установка", id="count")
        with VerticalScroll(id="steps"):
            for item, value in self.jobs:
                with Horizontal(classes="step"):
                    yield Static(Text("·", style="dim"), classes="icon")
                    yield Static(self.line(item, value), classes="stext")
        with Horizontal(id="foot"):
            yield Label("", id="hint")
            yield Button("Перезагрузить", id="reboot", variant="error")
            yield Button("Назад", id="back", variant="primary")

    def on_mount(self) -> None:
        self.app.installing = True
        self.query_one("#back").display = False
        self.query_one("#reboot").display = False
        self.set_interval(0.08, self._spin)
        self.run_worker(self._run, thread=True)

    def _spin(self) -> None:
        if self.running >= 0 and not self.done:
            self.frame += 1
            icon = self.query(".icon").nodes[self.running]
            icon.update(Text(SPINNER[self.frame % len(SPINNER)], style="cyan"))

    def _run(self) -> None:
        runner = Runner(self.app.demo)
        total = len(self.jobs)
        for i, (item, value) in enumerate(self.jobs):
            self.app.call_from_thread(self._start, i, total)
            try:
                item.run(runner, value)
                error = None
            except Exception as exc:
                error = f"{exc} (см. {runner.path})"
            self.results.append((item, value, error))
            self.app.call_from_thread(self._finish, i, error)
        self.app.call_from_thread(self._all_done)

    def _start(self, i: int, total: int) -> None:
        self.running = i
        self.query_one("#hint", Label).update(f"Идёт установка… {i + 1} из {total}")

    def _finish(self, i: int, error: Optional[str]) -> None:
        item, value = self.jobs[i]
        self.running = -1    # иначе таймер спиннера успеет затереть галочку
        icon = self.query(".icon").nodes[i]
        icon.update(Text("✔", style="bold green") if error is None else Text("✗", style="bold red"))
        self.query(".stext").nodes[i].update(self.line(item, value, error, finished=True))

    def _all_done(self) -> None:
        self.done = True
        self.app.installing = False
        failed = sum(1 for _, _, e in self.results if e)
        ok = len(self.results) - failed
        self.query_one("#count", Label).update("готово")
        self.query_one("#hint", Label).update(
            f"Готово: установлено {ok}" + (f", с ошибками {failed}" if failed else ""))
        self.query_one("#reboot").display = True
        back = self.query_one("#back")
        back.display = True
        back.focus()

    def action_back(self) -> None:
        if self.done:
            self.dismiss(self.results)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "reboot":
            self.app.push_screen(
                ConfirmModal("Перезагрузка", "Сервер перезагрузится сразу, ssh-сессия оборвётся."),
                self._reboot)
        else:
            self.action_back()

    def _reboot(self, confirmed: Optional[bool]) -> None:
        if not confirmed:
            return
        if self.app.demo:
            self.app.notify("Демо: перезагрузка пропущена")
            return
        subprocess.Popen(["systemctl", "reboot"])
        self.app.exit()


# --------------------------------------------------------------- приложение

class Linstall(App):
    TITLE = "Linstall"
    BINDINGS = [Binding("q", "quit", "Выход")]
    CSS = """
    #bar { dock: top; height: 1; background: $panel; padding: 0 1; }
    #title { width: 1fr; text-style: bold; }
    #count { width: auto; color: $text-muted; }
    #foot { dock: bottom; height: 3; background: $panel; padding: 0 1; }
    #hint { width: 1fr; height: 3; content-align: left middle; color: $text-muted; }
    #hint.error { color: $error; }
    #foot Button { margin-left: 1; }
    .section { color: $accent; text-style: bold; margin: 1 2 0 2; width: 100%; border-bottom: solid $panel; }
    .grid { grid-size: 2; grid-rows: auto; grid-gutter: 0 1; height: auto; padding: 0 1; }
    .step { height: auto; padding: 0 2; }
    .icon { width: 3; height: auto; }
    .stext { width: 1fr; height: auto; }
    InputModal, ChoiceModal, ConfirmModal { align: center middle; background: $background 60%; }
    .dlg { width: 64; height: auto; max-height: 90%; border: round $accent; background: $surface; padding: 1 2; }
    .dtitle { color: $accent; text-style: bold; }
    .ddesc { color: $text-muted; margin-bottom: 1; }
    #err { color: $error; height: 1; }
    .btns { height: auto; align-horizontal: right; margin-top: 1; }
    .btns Button { margin-left: 1; }
    ChoiceModal OptionList { height: auto; max-height: 16; }
    """

    def __init__(self, demo: bool = False) -> None:
        super().__init__()
        self.demo = demo
        self.installing = False

    def on_mount(self) -> None:
        self.push_screen(MainScreen())

    async def action_quit(self) -> None:
        if self.installing:
            self.notify("Идёт установка, дождись окончания", severity="warning")
        else:
            self.exit()


def main() -> None:
    demo = "--demo" in sys.argv
    if not demo:
        if os.geteuid() != 0:
            sys.exit("Linstall нужно запускать от root: sudo python3 linstall.py")
        if not shutil.which("apt-get"):
            sys.exit("Linstall работает только на Debian и Ubuntu (нужен apt-get).")
    Linstall(demo=demo).run()


if __name__ == "__main__":
    main()
