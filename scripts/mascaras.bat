@echo off
setlocal
rem PROJ_LIB/PROJ_DATA de outro programa (ex.: PostGIS) quebram o rasterio: ele usa a PROJ que vem junto
set PROJ_LIB=
set PROJ_DATA=
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (echo Rode scripts\instalar.bat primeiro. & pause & exit /b 1)
rem chcp 65001 (acentos da saida do Python) so depois das perguntas: com ele o set /p nao le entrada redirecionada
set PY=chcp 65001 ^>nul ^& ".venv\Scripts\python.exe" scripts\mascaras_area.py
if not "%~1"=="" (%PY% %* & pause & exit /b)

echo Fluxo da mascara de classes (docs\guia-execucao.md, secao 5)
echo   1 pseudo       rotulos de treino a partir da ultima deteccao sem mascara de uma area
echo   2 treinar      treina o modelo com os rotulos de uma ou mais areas
echo   3 classificar  grava a mascara em entrada\mascara de uma area
echo   4 avaliar      IoU contra os poligonos de entrada\teste_mascara
echo   Etapa 2 (cana x daninha com os pontos de entrada\amostras_pontos):
echo   5 objetos-treinar      treina com os pontos de uma ou mais areas
echo   6 objetos-classificar  grava a mascara em entrada\mascara de uma area
set /p PASSO=Passo (1 a 6):
if "%PASSO%"=="1" goto pseudo
if "%PASSO%"=="2" goto treinar
if "%PASSO%"=="3" goto classificar
if "%PASSO%"=="4" goto avaliar
if "%PASSO%"=="5" goto objetos_treinar
if "%PASSO%"=="6" goto objetos_classificar
echo Passo invalido. & pause & exit /b 1

:pseudo
set /p AREA=Nome da area (pasta dentro de dados\areas):
%PY% pseudo %AREA%
goto fim

:treinar
set /p MODELO=Nome do modelo (ex.: nivel1):
set /p AREAS=Areas de treino, separadas por espaco (ex.: area_01 area_02):
%PY% treinar %MODELO% %AREAS%
goto fim

:classificar
set /p AREA=Nome da area a classificar:
set /p MODELO=Nome do modelo (ex.: nivel1):
%PY% classificar %AREA% %MODELO%
goto fim

:avaliar
set /p AREA=Nome da area:
%PY% avaliar %AREA%
goto fim

:objetos_treinar
set /p MODELO=Nome do modelo (ex.: objetos1):
set /p AREAS=Areas com pontos, separadas por espaco (ex.: area_01 area_02):
%PY% objetos-treinar %MODELO% %AREAS%
goto fim

:objetos_classificar
set /p AREA=Nome da area a classificar:
set /p MODELO=Nome do modelo (ex.: objetos1):
%PY% objetos-classificar %AREA% %MODELO%
goto fim

:fim
pause
