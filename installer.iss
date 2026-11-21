#define AppVer "0.4.2-beta"
[Setup]
AppId={{8E3B1C0A-5D7F-4B7E-9A55-C41C4E1C0A01}
AppName=Chicken AI
AppVersion={#AppVer}
AppPublisher=cezary-lonski
DefaultDirName={autopf}\Chicken AI
DefaultGroupName=Chicken AI
PrivilegesRequired=lowest
OutputDir=installer_out
OutputBaseFilename=ChickenAI-Setup
SetupIconFile=assets\chicken.ico
UninstallDisplayIcon={app}\ChickenAI.exe
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
RestartApplications=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "polish"; MessagesFile: "compiler:Languages\Polish.isl"

[Files]
Source: "C:\cb\dist\ChickenAI\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Chicken AI"; Filename: "{app}\ChickenAI.exe"
Name: "{autodesktop}\Chicken AI"; Filename: "{app}\ChickenAI.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Utwórz skrót na pulpicie"

[Run]
Filename: "{app}\ChickenAI.exe"; Description: "Uruchom Chicken AI"; Flags: nowait postinstall skipifsilent
