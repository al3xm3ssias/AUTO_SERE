@echo off
rem AUTO SERE - abre o sistema como aplicativo (Chrome em modo app).
rem Sobe o servidor local se ainda nao estiver rodando e abre a janela.
cd /d "%~dp0"
set "PYW=runtime\python\pythonw.exe"
if not exist "%PYW%" set "PYW=.venv\Scripts\pythonw.exe"
if not exist "%PYW%" (
  echo Ambiente nao instalado. Execute INSTALAR_WINDOWS.bat primeiro.
  pause
  exit /b 1
)
start "" "%PYW%" -m src.launcher
exit /b 0
