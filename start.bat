@echo off
cd /d "%~dp0"
python app.py
if errorlevel 1 (
    echo.
    echo Programmet krasjet. Koeyr installer.bat foerst viss du ikkje har gjort det.
    pause
)
