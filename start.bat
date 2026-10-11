@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo Ambiente virtual nao encontrado. Execute setup.bat primeiro.
    pause
    exit /b 1
)

if not exist "%~dp0.env" (
    echo Arquivo .env nao encontrado. Execute setup.bat primeiro.
    pause
    exit /b 1
)

"%VENV_PY%" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
if errorlevel 1 (
    echo A aplicacao encerrou com erro.
    pause
    exit /b 1
)
exit /b 0
