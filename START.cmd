@echo off
chcp 65001 >nul
title Numbers - UnifAI Toolkit
cd /d "%~dp0"
rem Python finden, ohne einen Pfad zu veroeffentlichen: erst der
rem Windows-Launcher, dann was im PATH steht.
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
  echo   Python nicht gefunden. Bitte Python 3.9 oder neuer installieren.
  pause & exit /b 1
)
echo.
echo   ================================================================
echo    NUMBERS - Toolkit fuer das UnifAI-Netz
echo   ================================================================
echo.
if "%UNIFAI_TOOLKIT_API_KEY%"=="" (
  echo   Kein Schluessel gesetzt - zeige nur, was registriert WUERDE.
  echo   Schluessel gibt es gratis unter console.unifai.network
  echo.
  %PY% run.py --dry-run
) else (
  echo   Schluessel gefunden. Toolkit geht live.
  echo.
  %PY% run.py
)
echo.
pause
