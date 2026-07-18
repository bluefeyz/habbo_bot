@echo off
title Habbo Bot - Interface
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python n'est pas installe ou pas dans le PATH.
    echo Telecharge-le sur https://www.python.org/downloads/
    echo et coche "Add Python to PATH" pendant l'installation.
    pause
    exit /b
)

if not exist ".venv" (
    echo [*] Creation de l'environnement Python...
    python -m venv .venv
)
call .venv\Scripts\activate.bat

echo [*] Installation des dependances...
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

echo.
echo [*] Ouverture de l'interface...
python interface.py

pause
