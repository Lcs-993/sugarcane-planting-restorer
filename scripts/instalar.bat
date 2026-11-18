@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% --version
if errorlevel 1 (echo Python nao encontrado. Instale o Python 3.10 ou mais novo e marque "Add python.exe to PATH". & pause & exit /b 1)
if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install -e .
if errorlevel 1 (echo A instalacao falhou. Veja as mensagens acima. & pause & exit /b 1)
echo.
echo Instalacao concluida. Agora use scripts\nova_area.bat e scripts\rodar_area.bat.
pause
