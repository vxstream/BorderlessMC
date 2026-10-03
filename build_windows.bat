@echo off
REM Сборка BorderlessMC.exe на Windows (нативно, без wine)
setlocal

cd /d "%~dp0"

echo === Создаём venv ===
python -m venv .venv || goto :err
call .venv\Scripts\activate.bat || goto :err

echo === Ставим PyInstaller ===
python -m pip install --upgrade pip
python -m pip install pyinstaller || goto :err

echo === Собираем .exe ===
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name BorderlessMC ^
    --hidden-import tkinter ^
    borderless_mc.py || goto :err

echo.
echo Готово: %CD%\dist\BorderlessMC.exe
echo Упаково одной папкой: powershell -c "Compress-Archive -Path dist\BorderlessMC.exe -DestinationPath dist\BorderlessMC-windows.zip"
goto :eof

:err
echo.
echo ОШИБКА сборки.
exit /b 1