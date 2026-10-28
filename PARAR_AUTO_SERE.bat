@echo off
rem Encerra o servidor do AUTO SERE iniciado pelo atalho.
cd /d "%~dp0"
set "PY=runtime\python\python.exe"
if not exist "%PY%" set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Ambiente nao instalado.
  pause
  exit /b 1
)
"%PY%" -m src.launcher --parar
pause
