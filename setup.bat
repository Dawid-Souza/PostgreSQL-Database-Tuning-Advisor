@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "VENV=%~dp0.venv"
set "VENV_PY=%VENV%\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo Criando ambiente virtual em .venv ...
    py -3 -m venv "%VENV%"
    if errorlevel 1 (
        echo Nao foi possivel criar o ambiente virtual Python.
        pause
        exit /b 1
    )
) else (
    echo Ambiente virtual ja existe. Atualizando dependencias...
)

echo Atualizando pip...
"%VENV_PY%" -m pip install --upgrade pip
if errorlevel 1 (
    echo Nao foi possivel atualizar o pip.
    pause
    exit /b 1
)

echo Instalando dependencias no .venv ...
"%VENV_PY%" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo Nao foi possivel instalar as dependencias.
    pause
    exit /b 1
)

if not exist "%~dp0.env" (
    if exist "%~dp0.env.example" (
        copy /y "%~dp0.env.example" "%~dp0.env" >nul
        echo Arquivo .env criado a partir de .env.example
    ) else (
        echo Aviso: .env.example nao encontrado. Crie o .env manualmente.
    )
)

echo.
echo Instalacao concluida em .venv
echo Execute start.bat e abra http://127.0.0.1:8000
pause
exit /b 0
