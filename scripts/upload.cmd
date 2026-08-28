@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0upload.ps1" %*
exit /b %errorlevel%
