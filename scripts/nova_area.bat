@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
set NOME=%~1
if "%NOME%"=="" set /p NOME=Nome da nova area (ex.: area_03): 
for %%D in (entrada\ortomosaico entrada\talhoes entrada\referencia entrada\mds entrada\mdt saida) do mkdir "dados\areas\%NOME%\%%D" 2>nul
echo Criada a pasta dados\areas\%NOME%
pause
