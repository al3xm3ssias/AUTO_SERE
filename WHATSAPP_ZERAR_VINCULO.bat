@echo off
rem AUTO SERE - ZERA o vinculo do WhatsApp (apaga o login salvo neste computador).
rem Use quando o numero foi desvinculado pelo celular ou para trocar de numero.
cd /d "%~dp0"
echo Isto apaga o login do WhatsApp guardado neste computador. Sera preciso ler um QR Code novo.
echo Feche o AUTO SERE e a janela do WhatsApp antes de continuar.
choice /m "Continuar"
if errorlevel 2 exit /b 0
rem Modo sem Docker (whatsplay): apaga o perfil do navegador
if exist "credenciais\whatsapp_sessao" rmdir /s /q "credenciais\whatsapp_sessao"
rem Modo Docker (blake): apaga o volume da sessao e sobe de novo (ignorado se nao usa Docker)
where docker >nul 2>nul
if not errorlevel 1 (
  docker compose -f docker\whatsapp\docker-compose.yml down -v >nul 2>nul
  docker compose -f docker\whatsapp\docker-compose.yml up -d >nul 2>nul
)
echo.
echo Pronto. Abra o AUTO SERE, va em "WhatsApp" e inicie a conexao.
pause
