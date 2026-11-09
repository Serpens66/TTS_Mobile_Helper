@echo off
setlocal

cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_pyinstaller.ps1" %*
set "BUILD_EXIT_CODE=%ERRORLEVEL%"

echo.
echo Build Exit-Code: %BUILD_EXIT_CODE%
pause
exit /b %BUILD_EXIT_CODE%
