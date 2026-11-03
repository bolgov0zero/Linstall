# Linstall

TUI-скрипт для Debian и Ubuntu: отмечаешь нужное, нажимаешь «Установить», всё ставится по очереди.

## Запуск

```bash
curl -fsSL https://raw.githubusercontent.com/bolgov0zero/Linstall/main/install.sh | bash
```

Нужен root. Скрипт сам поставит Python и [Textual](https://github.com/Textualize/textual) в `/opt/linstall`.

## Что умеет

- **Настройка системы:** вход под root, порт SSH, обновление, зеркало apt, часовой пояс, имя машины, BBR.
- **Базовые утилиты:** curl, wget, git, unzip, micro, mc, tmux, neofetch.
- **Мониторинг:** btop, iotop, ncdu.
- **Безопасность:** [LinFW](https://github.com/bolgov0zero/LinFW).
- **Docker:** Docker Engine с Compose.

При запуске система проверяется: что уже стоит, помечается `[✔]`. У порта, часового пояса, имени и зеркала показывается текущее значение, их можно менять.
Пункты с вводом (порт, имя, часовой пояс, зеркало) открывают окно сразу после отметки.

## Управление

| Клавиша | Действие |
|---|---|
| стрелки | перемещение |
| пробел или клик | отметить |
| Enter | установить |
| q | выход |

Лог установки: `/var/log/linstall.log`.

## Разработка

```bash
pip install -r requirements.txt
python3 linstall.py --demo   # без root, ничего не меняет в системе
```
