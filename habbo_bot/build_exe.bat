@echo off
title Habbo Bot - Build EXE
cd /d "%~dp0"

REM Genere un executable autonome (Habbo Bot.exe) avec l'interface graphique.
REM Le .exe apparaitra dans le dossier "dist".

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python requis. https://www.python.org/downloads/ (cocher "Add to PATH")
    pause
    exit /b
)

if not exist ".venv" ( python -m venv .venv )
call .venv\Scripts\activate.bat

echo [*] Installation des dependances + PyInstaller...
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
pip install --quiet pyinstaller

echo [*] Compilation de l'executable (peut prendre 1-2 min)...
pyinstaller --noconfirm --onefile --windowed --name "Habbo Bot" ^
    --collect-all cv2 --collect-all mss --collect-all pynput interface.py

echo.
echo [OK] Executable genere dans le dossier "dist\Habbo Bot.exe"
echo Astuce : lance-le en tant qu'administrateur pour le controle souris/clavier.
pause
