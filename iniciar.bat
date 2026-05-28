@echo off
chcp 65001 >nul
title Agente Info Clasificados
cd /d "%~dp0"
echo.
echo ================================================
echo   AGENTE INFO CLASIFICADOS - Iniciando...
echo ================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python no esta instalado o no esta en el PATH.
    echo Descargalo desde https://www.python.org/downloads/
    pause
    exit /b 1
)

echo Verificando dependencias...
python -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo ERROR: No se pudieron instalar las dependencias.
    pause
    exit /b 1
)

echo.
echo Iniciando servidor...
echo Se abrira el navegador automaticamente.
echo Pulsa Ctrl+C para detener.
echo.

python app.py

pause
