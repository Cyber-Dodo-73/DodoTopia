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
AppPublisher=Cyber-Dodo
AppPublisherURL=https://dodotopia.cyber-dodo.fr
AppSupportURL=https://dodotopia.cyber-dodo.fr/#questions
AppUpdatesURL=https://dodotopia.cyber-dodo.fr/#telecharger
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}
OutputDir=release
OutputBaseFilename=DodoTopia-{#AppVersion}-Setup
SetupIconFile=assets\logo.ico
LicenseFile=legal\CGU-fr.rtf
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
Name: "english"; MessagesFile: "compiler:Default.isl"; LicenseFile: "legal\CGU-en.rtf"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Liens dodotopia:// (site, Discord) : ouverts par DodoTopia, qui demande confirmation avant d'agir.
; HKCU (PrivilegesRequired=lowest) ; la cle entiere est retiree a la desinstallation.
Root: HKCU; Subkey: "Software\Classes\dodotopia"; ValueType: string; ValueName: ""; ValueData: "URL:DodoTopia"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\dodotopia"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\dodotopia\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"",0"
Root: HKCU; Subkey: "Software\Classes\dodotopia\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --url ""%1"""

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
; Mise a jour automatique (installeur lance en /SILENT par DodoTopia) : relance l'app avec --updated
Filename: "{app}\{#AppExe}"; Parameters: "--updated"; Flags: nowait skipifnotsilent
