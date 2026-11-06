@echo off
cd /d "%~dp0"
title Uploading FreeFire-Core to GitHub
echo ========================================================
echo Pushing to GitHub: https://github.com/userkxm00/FreeFire-Core.git
echo Folder: %CD%
echo ========================================================
echo.

set "GIT_CMD=git"
where git >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    if exist "C:\Program Files\Git\cmd\git.exe" (
        set "GIT_CMD=C:\Program Files\Git\cmd\git.exe"
    ) else (
        echo Error: Git was not found in PATH or standard installation directory.
        pause
        exit /b 1
    )
)

"%GIT_CMD%" push -u origin main
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
