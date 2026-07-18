@echo off
title Habbo Bot
cd /d "%~dp0"

echo ============================================
echo   HABBO BOT - installation + lancement
echo ============================================
echo.

REM --- verifie que Python est installe ---
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python n'est pas installe ou pas dans le PATH.
    echo Telecharge-le sur https://www.python.org/downloads/
    echo et coche "Add Python to PATH" pendant l'installation.
    pause
    exit /b
)

REM --- cree un environnement virtuel la premiere fois ---
if not exist ".venv" (
    echo [*] Creation de l'environnement Python...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

REM --- installe les dependances (rapide si deja fait) ---
echo [*] Installation des dependances...
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

echo.
echo [*] Lancement du bot... (appuie sur 'p' dans le jeu, 'q' pour quitter)
echo.
python habbo_bot.py

pause
