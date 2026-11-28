; AUTO SERE - instalador (Inno Setup 6)
; Gera Output\AUTO_SERE_Setup_<versao>.exe  (compilar: installer\compilar_instalador.bat)
;
; O que o setup.exe faz:
;   1. pergunta a pasta (padrao C:\AUTO_SERE; nao aceita Arquivos de Programas, rede nem disco removivel)
;   2. copia o programa (SEM dados de alunos, credenciais, config da escola, patches, testes)
;   3. roda scripts\windows\instalar.ps1 -Silencioso: Python proprio, bibliotecas, navegadores, pastas e
;      o administrador PROVISORIO (usuario admin / senha admin; troca obrigatoria no 1o login, minimo 8 caracteres)
;   4. cria os atalhos e o desinstalador
; Atualizar = rodar o setup novo por cima: dados\, credenciais\ e config_usuario.json sao preservados.
; Requer internet na instalacao (Python portatil, bibliotecas e navegadores sao baixados). Nao requer administrador.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppName "AUTO SERE"

[Setup]
AppId={{CED815FE-E194-44B7-8C05-504B1A013B9E}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Escola Municipal Profa Judith Macedo Silveira
DefaultDirName=C:\AUTO_SERE
DisableProgramGroupPage=yes
DisableDirPage=no
UsePreviousAppDir=yes
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=AUTO_SERE_Setup_{#AppVersion}
SetupIconFile=..\src\web\static\img\auto-sere.ico
UninstallDisplayIcon={app}\src\web\static\img\auto-sere.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=no
InfoAfterFile=LEIA_ME_INSTALACAO.txt

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Files]
; Programa. NUNCA entram: dados de alunos, credenciais, config da escola, ambiente local, patches, testes, backups de merge.
Source: "..\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion; \
  Excludes: "dados\*,credenciais\*,runtime\*,logs\*,tests\*,installer\*,.git\*,.github\*,.venv\*,__pycache__\*,*.pyc,*.patch,*.orig,*.rej,*.o5r3vMJ,*.zip,*.exe,config\config_usuario.json,Output\*"

[Dirs]
Name: "{app}\dados"
Name: "{app}\credenciais"

[Run]
Filename: "{app}\AUTO_SERE.bat"; Description: "Abrir o AUTO SERE agora"; Flags: postinstall nowait skipifsilent shellexec

[UninstallRun]
Filename: "{app}\PARAR_AUTO_SERE.bat"; Flags: runhidden skipifdoesntexist; RunOnceId: "PararServidor"

[UninstallDelete]
; So o que o setup criou/baixou. dados\, credenciais\, config\ e logs\ ficam (sao da escola); apague a pasta a mao se quiser.
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\src\__pycache__"
Type: files; Name: "{autodesktop}\AUTO SERE.lnk"
Type: files; Name: "{userprograms}\AUTO SERE.lnk"

[Code]
function DiscoOk(const Dir: String; var Motivo: String): Boolean;
var
  D: String;
begin
  Result := False;
  D := Uppercase(ExpandConstant('{commonpf64}'));
  if (Length(Dir) < 4) or (Dir[2] <> ':') or (Dir[3] <> '\') then
  begin Motivo := 'Informe um caminho completo de um disco local, por exemplo C:\AUTO_SERE'; Exit; end;
  if (Pos(Uppercase(ExpandConstant('{commonpf32}')), Uppercase(Dir)) = 1) or (Pos(D, Uppercase(Dir)) = 1)
     or (Pos(Uppercase(ExpandConstant('{win}')), Uppercase(Dir)) = 1) then
  begin Motivo := 'Essa pasta exige permissao de administrador. Escolha outra, por exemplo C:\AUTO_SERE'; Exit; end;
  Result := True;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Motivo: String;
begin
  Result := True;
  if CurPageID = wpSelectDir then
    if not DiscoOk(WizardDirValue, Motivo) then
    begin
      MsgBox(Motivo, mbError, MB_OK);
      Result := False;
    end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Codigo: Integer;
  Params: String;
begin
  if CurStep = ssPostInstall then
  begin
    WizardForm.StatusLabel.Caption := 'Preparando Python, bibliotecas e navegadores (pode levar varios minutos)...';
    Params := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\scripts\windows\instalar.ps1') +
              '" -Destino "' + ExpandConstant('{app}') + '" -Silencioso';
    if not Exec('powershell.exe', Params, ExpandConstant('{app}'), SW_SHOW, ewWaitUntilTerminated, Codigo) or (Codigo <> 0) then
      MsgBox('Os arquivos foram copiados, mas a preparacao do ambiente nao terminou (codigo ' + IntToStr(Codigo) + ').' + #13#10 +
             'Verifique a internet e rode de novo este instalador: ele continua de onde parou e nao apaga seus dados.',
             mbError, MB_OK);
  end;
end;
