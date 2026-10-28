@echo off
rem AUTO SERE - sobe o gateway do WhatsApp (Docker). Precisa do Docker Desktop aberto.
cd /d "%~dp0"
docker compose -f docker\whatsapp\docker-compose.yml up -d
if errorlevel 1 (
  echo.
  echo Nao consegui subir. O Docker Desktop esta aberto?
  pause
  exit /b 1
)
echo.
echo Gateway no ar. Abra o AUTO SERE e va em "WhatsApp".
pause
