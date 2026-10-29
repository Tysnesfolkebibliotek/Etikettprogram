@echo off
cd /d "%~dp0"
title Boketikettar
python server.py %*
if errorlevel 1 (
    echo.
    echo Programmet stoppa. Koeyr installer.bat foerst viss du ikkje har gjort det.
    pause
)
