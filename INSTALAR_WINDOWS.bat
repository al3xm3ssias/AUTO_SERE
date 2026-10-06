@echo off
rem AUTO SERE - assistente de instalacao no Windows.
rem Pergunta a pasta de instalacao, instala um Python proprio dentro dela,
rem as bibliotecas e os navegadores, e cria o atalho "AUTO SERE".
rem Pode ser executado de novo sem problema. Requer internet na primeira vez.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\windows\instalar.ps1" %*
if errorlevel 2 (
  echo.
  echo Instalacao cancelada.
  pause
  exit /b 2
)
if errorlevel 1 (
  echo.
  echo A instalacao nao foi concluida. Leia a mensagem de erro acima.
  pause
  exit /b 1
)
pause
exit /b 0
