@echo off
cd /d "%~dp0"
echo ============================================
echo   Boketikett-generator - Installasjon
echo ============================================
echo.
python --version >nul 2>&1
if errorlevel 1 (
    echo FEIL: Python er ikkje installert.
    pause
    exit /b 1
)
echo Installerer avhengigheiter...
pip install -r requirements.txt --quiet
echo.
echo ============================================
echo   Installasjon fullfort! Start med start.bat
echo ============================================
pause
