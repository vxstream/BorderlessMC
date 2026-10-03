# BorderlessMC

Находит уже запущенный **Minecraft** (`javaw.exe` / `java.exe`) и превращает его окно
в **borderless fullscreen**: без рамки, без заголовка, на весь экран.

Один файл, ноль зависимостей (только `ctypes` + `tkinter` из стандартной библиотеки).

---

## Возможности

- Сканирует процессы и находит окна Minecraft (по имени процесса, классу окна
  GLFW/LWJGL и заголовку).
- GUI: список окон с PID, заголовком, монитором и состоянием.
- «Бордерлесс фуллскрин» / «Восстановить» / «Восстановить все».
- Выбор монитора для окна (по умолчанию тот, на котором окно).
- Горячая клавиша **F11** — переключение бордерлесс ↔ назад.
- Состояние окон сохраняется в `%APPDATA%\BorderlessMC\state.json`, поэтому
  «Восстановить» возвращает исходный размер и стиль.
- CLI: `--list`, `--pid N`, `--restore`.

---

## Запуск из исходника (Windows)

Нужен Python 3.10+ с tkinter:

```
python borderless_mc.py            # GUI
python borderless_mc.py --list     # список окон Minecraft
python borderless_mc.py --pid 1234 # применить к процессу
python borderless_mc.py --restore  # восстановить всё и выйти
```

---

## Сборка .exe

Сборка Windows-бинарника из Linux без Wine невозможна: PyInstaller компилирует
байткод тем же интерпретатором, на котором запускается, а Linux-интерпретатор
не знает формат PE. Вариантов три, все описаны ниже.

### Вариант 1. GitHub Actions (без Wine, без локальной установки)

В репозитории уже лежит `.github/workflows/build.yml`. Достаточно:

```
git init
git add .
git commit -m "BorderlessMC"
git branch -M main
git remote add origin https://github.com/<твой-ник>/BorderlessMC.git
git push -u origin main
```

Дальше: **Actions → Build BorderlessMC → Run workflow**. Сборка идёт на
`windows-latest`, на выходе `dist/BorderlessMC.exe` как артефакт
(скачивается из вкладки Artifacts). Теги вида `v1.0` тоже запускают сборку.

### Вариант 2. Из Linux через Wine

```
sudo pacman -S --needed wine
./build_linux_wine.sh
```

Скрипт поднимает отдельный префикс `~/.wine-borderlessmc`, ставит туда
portable Windows-Python и собирает `.exe` в `dist/`.

### Вариант 3. Нативно на Windows

Запусти `build_windows.bat` в cmd. Результат — `dist\BorderlessMC.exe`.

---

## Как это работает

Бордерлесс-фуллскрин делается напрямую через Win32, без хуков:

1. Запоминаются `GWL_STYLE`, `GWL_EXSTYLE` и `RECT` окна.
2. Из стиля вырезаются `WS_CAPTION | WS_THICKFRAME | WS_BORDER | WS_DLGFRAME |
   WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU`, добавляется `WS_POPUP`.
3. `DwmExtendFrameIntoClientArea` с полями `-1` убирает остатки рамки DWM.
4. `SetWindowPos` растягивает окно на `rcMonitor` нужного монитора с
   флагом `SWP_FRAMECHANGED`.

Восстановление возвращает сохранённые стиль и размер, поэтому окно
возвращается ровно таким, каким было.

## Ограничения

- Работает только под Windows (проверка `os.name` в `main`).
- Окно должно быть создано — у развёрнутого/свёрнутого окна Minecraft на
  отдельном десктопе есть нюансы с `SetWindowPos`; в коде есть
  `ShowWindow(SW_RESTORE)` перед применением.
- Игра в полноэкранном F11-режиме Minecraft сама перехватывает ввод — сначала
  выйди из полного экрана средствами игры, потом применяй бордерлесс.