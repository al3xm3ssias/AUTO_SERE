@echo off
rem Gera o setup.exe do AUTO SERE. Requer o Inno Setup 6 (gratuito): https://jrsoftware.org/isdl.php
cd /d "%~dp0"
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
  echo Inno Setup 6 nao encontrado. Instale em https://jrsoftware.org/isdl.php e rode de novo.
  pause
  exit /b 1
)
set "VERSAO=%~1"
if "%VERSAO%"=="" set "VERSAO=1.0.0"
"%ISCC%" /DAppVersion=%VERSAO% AUTO_SERE.iss
if errorlevel 1 ( echo Falha ao compilar. & pause & exit /b 1 )
echo.
echo Pronto: installer\Output\AUTO_SERE_Setup_%VERSAO%.exe
pause
