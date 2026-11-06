@echo off
cd /d "%~dp0"
title Uploading FreeFire-Core to GitHub
echo ========================================================
echo Pushing to GitHub: https://github.com/userkxm00/FreeFire-Core.git
echo Folder: %CD%
echo ========================================================
echo.
"C:\Program Files\Git\cmd\git.exe" push -u origin main
echo.
if %ERRORLEVEL% EQU 0 (
    echo ========================================================
    echo SUCCESS! Project uploaded to GitHub successfully.
    echo ========================================================
) else (
    echo ========================================================
    echo Error or Browser Authorization needed.
    echo ========================================================
)
echo.
pause
