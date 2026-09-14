; Installeur DodoTopia (Inno Setup 6)
; Relancer un installeur plus recent met a jour l'installation en place :
; les musiques et reglages sont dans %APPDATA%\DodoTopia et ne sont pas touches.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppName "DodoTopia"
#define AppExe "DodoTopia.exe"

[Setup]
AppId={{3B7D9C42-6F1A-4E58-9A2D-D0D0D0D0701A}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Dodo
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}
OutputDir=release
OutputBaseFilename=DodoTopia-{#AppVersion}-Setup
SetupIconFile=assets\logo.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
CloseApplications=yes
RestartApplications=no
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
; Mise a jour automatique (installeur lance en /SILENT par DodoTopia) : relance l'app avec --updated
Filename: "{app}\{#AppExe}"; Parameters: "--updated"; Flags: nowait skipifnotsilent
