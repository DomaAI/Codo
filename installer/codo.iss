; Codo for Windows: installer (Inno Setup 6). Built by .github/workflows/release.yml:
;   iscc /DAppVersion=0.29.0 /DSourceExe=..\out\codo.exe installer\codo.iss
; No administrator rights: installs for the current user into %LOCALAPPDATA%\Programs\Codo
; and adds that folder to the user's PATH, so `codo` works in any new terminal.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceExe
  #define SourceExe "..\out\codo.exe"
#endif

[Setup]
AppId={{6E0C2F7B-4D1A-4B8E-9C3D-C0D0A11C0D01}
AppName=Codo
AppVersion={#AppVersion}
AppVerName=Codo {#AppVersion}
AppPublisher=MADD
AppPublisherURL=https://domaai.pl/pobierz-codo.html
AppSupportURL=https://github.com/DomaAI/Codo/issues
AppUpdatesURL=https://domaai.pl/pobierz-codo.html
AppCopyright=Copyright (C) 2026 MADD
VersionInfoVersion={#AppVersion}
VersionInfoDescription=Codo Setup
DefaultDirName={localappdata}\Programs\Codo
DefaultGroupName=Codo
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
ChangesEnvironment=yes
CloseApplications=yes
WizardStyle=modern
WizardSizePercent=110
WizardImageFile=wizard-large-100.bmp,wizard-large-150.bmp,wizard-large-200.bmp
WizardSmallImageFile=wizard-small-100.bmp,wizard-small-150.bmp,wizard-small-200.bmp
SetupIconFile=..\assets\codo.ico
UninstallDisplayIcon={app}\codo.exe
UninstallDisplayName=Codo
LicenseFile=..\LICENSE
OutputDir=..\out
OutputBaseFilename=CodoSetup-x64
Compression=lzma2/max
SolidCompression=yes
ShowLanguageDialog=auto

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "polish"; MessagesFile: "compiler:Languages\Polish.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "dutch"; MessagesFile: "compiler:Languages\Dutch.isl"
Name: "czech"; MessagesFile: "compiler:Languages\Czech.isl"
Name: "danish"; MessagesFile: "compiler:Languages\Danish.isl"
Name: "ukrainian"; MessagesFile: "compiler:Languages\Ukrainian.isl"
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[CustomMessages]
AddToPath=Add the codo command to PATH (use Codo in any terminal)
Shortcuts=Shortcuts:
polish.AddToPath=Dodaj komendę codo do PATH (Codo w każdym terminalu)
polish.Shortcuts=Skróty:
german.AddToPath=Befehl codo zum PATH hinzufügen (Codo in jedem Terminal)
french.AddToPath=Ajouter la commande codo au PATH (Codo dans tout terminal)
spanish.AddToPath=Añadir el comando codo al PATH (Codo en cualquier terminal)
italian.AddToPath=Aggiungi il comando codo al PATH (Codo in ogni terminale)
brazilianportuguese.AddToPath=Adicionar o comando codo ao PATH (Codo em qualquer terminal)
dutch.AddToPath=Opdracht codo aan PATH toevoegen (Codo in elke terminal)
czech.AddToPath=Přidat příkaz codo do PATH (Codo v každém terminálu)
danish.AddToPath=Tilføj kommandoen codo til PATH (Codo i enhver terminal)
ukrainian.AddToPath=Додати команду codo до PATH (Codo у будь-якому терміналі)
turkish.AddToPath=codo komutunu PATH'e ekle (her terminalde Codo)
japanese.AddToPath=codo コマンドを PATH に追加 (どのターミナルでも Codo を使用)

[Tasks]
Name: "path"; Description: "{cm:AddToPath}"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:Shortcuts}"

[Files]
Source: "{#SourceExe}"; DestDir: "{app}"; DestName: "codo.exe"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; "Codo": the app window (Edge/Chrome app mode), the console starts minimized
Name: "{autoprograms}\Codo"; Filename: "{app}\codo.exe"; Parameters: "okno"; WorkingDir: "{%USERPROFILE}"; Comment: "Codo"; Flags: runminimized
; "Codo Terminal": the agent in a terminal, like on Linux and macOS
Name: "{autoprograms}\Codo Terminal"; Filename: "{cmd}"; Parameters: "/k ""{app}\codo.exe"""; WorkingDir: "{%USERPROFILE}"; IconFilename: "{app}\codo.exe"; Comment: "Codo in a terminal"
Name: "{autodesktop}\Codo"; Filename: "{app}\codo.exe"; Parameters: "okno"; WorkingDir: "{%USERPROFILE}"; Flags: runminimized; Tasks: desktopicon

[Run]
Filename: "{app}\codo.exe"; Parameters: "okno"; WorkingDir: "{%USERPROFILE}"; Description: "{cm:LaunchProgram,Codo}"; Flags: nowait postinstall skipifsilent runminimized

[Code]
const EnvKey = 'Environment';

function PathHas(const Paths, Dir: string): Boolean;
begin
  Result := Pos(';' + Uppercase(Dir) + ';', ';' + Uppercase(Paths) + ';') > 0;
end;

procedure AddToUserPath(const Dir: string);
var Paths: string;
begin
  if not RegQueryStringValue(HKCU, EnvKey, 'Path', Paths) then Paths := '';
  if PathHas(Paths, Dir) then exit;
  if (Paths <> '') and (Copy(Paths, Length(Paths), 1) <> ';') then Paths := Paths + ';';
  RegWriteExpandStringValue(HKCU, EnvKey, 'Path', Paths + Dir);
end;

procedure RemoveFromUserPath(const Dir: string);
var Paths, Rest, Part, Kept: string; P: Integer;
begin
  if not RegQueryStringValue(HKCU, EnvKey, 'Path', Paths) then exit;
  Rest := Paths; Kept := '';
  while Rest <> '' do
  begin
    P := Pos(';', Rest);
    if P = 0 then begin Part := Rest; Rest := ''; end
    else begin Part := Copy(Rest, 1, P - 1); Delete(Rest, 1, P); end;
    if (Part <> '') and (CompareText(RemoveBackslashUnlessRoot(Part), RemoveBackslashUnlessRoot(Dir)) <> 0) then
    begin
      if Kept <> '' then Kept := Kept + ';';
      Kept := Kept + Part;
    end;
  end;
  RegWriteExpandStringValue(HKCU, EnvKey, 'Path', Kept);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('path') then
    AddToUserPath(ExpandConstant('{app}'));
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RemoveFromUserPath(ExpandConstant('{app}'));
end;
