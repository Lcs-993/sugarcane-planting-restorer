@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
set NOME=%~1
if "%NOME%"=="" set /p NOME=Nome da nova area (ex.: area_03): 
for %%D in (entrada\ortomosaico entrada\talhoes entrada\referencia entrada\mds entrada\mdt entrada\mascara entrada\correcoes_mascara entrada\teste_mascara entrada\amostras_pontos saida) do mkdir "dados\areas\%NOME%\%%D" 2>nul
echo Criada a pasta dados\areas\%NOME%
pause
