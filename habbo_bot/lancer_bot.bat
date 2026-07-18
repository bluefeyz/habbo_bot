@echo off
title Habbo Bot - Interface
cd /d "%~dp0"

echo ============================================
echo   HABBO BOT - interface graphique
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

echo [*] Installation des dependances (le 1er lancement peut prendre 1-3 min)...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERREUR] Echec de l'installation des dependances ^(pas d'internet ?^).
    echo Copie/colle le message ci-dessus pour que je t'aide.
    pause
    exit /b
)

echo.
echo [*] Verification de Tkinter (interface graphique)...
python -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo.
    echo [ERREUR] Ton installation Python n'a PAS Tkinter ^(interface graphique^).
    echo Solution : reinstalle Python depuis https://www.python.org/downloads/
    echo   - coche "Add Python to PATH"
    echo   - et laisse coche "tcl/tk and IDLE" pendant l'installation.
    echo ^(Astuce : evite la version "Microsoft Store" de Python.^)
    pause
    exit /b
)

echo.
echo [*] Ouverture de l'interface... (une fenetre grise doit s'afficher)
python interface.py
set EXITCODE=%errorlevel%

echo.
if not "%EXITCODE%"=="0" (
    echo [ERREUR] L'interface s'est fermee avec le code %EXITCODE%.
    echo Copie/colle TOUT le texte rouge ci-dessus pour que je corrige.
) else (
    echo [*] Interface fermee normalement.
)
echo.
pause
