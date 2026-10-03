#!/usr/bin/env bash
# Сборка BorderlessMC.exe из Linux через Wine.
# Нужен wine + Windows-Python внутри префикса wine.
set -euo pipefail

cd "$(dirname "$0")"

PYVER="${PYVER:-3.12}"
PREFIX="${WINE_PREFIX:-$HOME/.wine-borderlessmc}"

if ! command -v wine >/dev/null 2>&1; then
    echo "wine не найден. Установи его, например:"
    echo "  sudo pacman -S --needed wine"
    exit 1
fi

if [ ! -d "$PREFIX" ]; then
    echo "=== Создаём wine-префикс $PREFIX ==="
    wineboot -u || true
fi

export WINEPREFIX="$PREFIX"
export WINEARCH="${WINEARCH:-win64}"

echo "=== Качаем Windows-Python $PYVER ==="
if [ ! -f "python-$PYVER-amd64.exe" ]; then
    curl -fsSL -o "python-$PYVER-amd64.exe" \
        "https://www.python.org/ftp/python/$PYVER/python-$PYVER-amd64.exe"
fi

echo "=== Ставим Python в префикс (silent) ==="
if [ ! -d "$PREFIX/drive_c/Python312" ]; then
    wine python-$PYVER-amd64.exe /quiet \
        TargetDir="C:\Python312" \
        Include_pip=1 \
        Include_tcltk=1 \
        Include_launcher=0 \
        PrependPath=0 \
        Shortcuts=0 \
        AssociateFiles=0 \
        Include_doc=0 \
        Include_test=0
fi

WINPY="$PREFIX/drive_c/Python312/python.exe"
[ -f "$WINPY" ] || WINPY="$PREFIX/drive_c/Python312/python3.exe"
[ -f "$WINPY" ] || { echo "Windows-Python не установлен."; exit 1; }
WINPY_WIN=$(winepath -w "$WINPY")

echo "=== Ставим PyInstaller ==="
wine "$WINPY" -m pip install --upgrade pip
wine "$WINPY" -m pip install pyinstaller

echo "=== Собираем .exe ==="
wine "$WINPY" -m PyInstaller \
    --noconfirm --clean --onefile --windowed \
    --name BorderlessMC \
    --hidden-import tkinter \
    "$(winepath -w "$PWD/borderless_mc.py")"

echo
echo "Готово: $PWD/dist/BorderlessMC.exe"
( cd dist && zip -q BorderlessMC-windows.zip BorderlessMC.exe && echo "Архив: $PWD/dist/BorderlessMC-windows.zip" )