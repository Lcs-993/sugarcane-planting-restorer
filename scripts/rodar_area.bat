@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (echo Rode scripts\instalar.bat primeiro. & pause & exit /b 1)
set AREA=%~1
if "%AREA%"=="" set /p AREA=Nome da area (pasta dentro de dados\areas): 
".venv\Scripts\python.exe" scripts\rodar_area.py "dados\areas\%AREA%"
pause
