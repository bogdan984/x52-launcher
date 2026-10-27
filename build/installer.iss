; X52 Launcher — установщик (Inno Setup 6). Собирается build/build.sh.
#define AppName "X52 Launcher"
#ifndef AppVersion
  #define AppVersion "5.0.0"
#endif

[Setup]
AppId={{2B0E0AC4-A537-4B81-8E1B-53C726CB2B8B}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=X52 Launcher
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=X52_Launcher_Setup_{#AppVersion}
SetupIconFile=..\x52_launcher.ico
UninstallDisplayIcon={app}\X52 Launcher.exe
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
PrivilegesRequired=admin
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Ярлык на рабочем столе"; GroupDescription: "Ярлыки:"
Name: "vigem"; Description: "Установить драйвер ViGEmBus (виртуальный геймпад для ACE COMBAT 8 и других игр только с геймпадом)"; GroupDescription: "Драйвер:"; Check: not ViGEmInstalled

[Files]
Source: "..\dist\X52 Launcher\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\MANUAL.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "redist\ViGEmBus_setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Tasks: vigem

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\X52 Launcher.exe"
Name: "{group}\Руководство"; Filename: "{app}\MANUAL.txt"
Name: "{group}\Удалить {#AppName}"; Filename: "{uninstallexe}"
; на рабочий стол пользователя — там ярлык ищет и создаёт сам лаунчер («Установка» → «Ярлык»)
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\X52 Launcher.exe"; Tasks: desktopicon

[Run]
Filename: "{tmp}\ViGEmBus_setup.exe"; Parameters: "/passive /norestart"; StatusMsg: "Установка драйвера ViGEmBus…"; Flags: waituntilterminated; Tasks: vigem
Filename: "{app}\X52 Launcher.exe"; Description: "Запустить {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
function ViGEmInstalled: Boolean;
begin
  Result := RegKeyExists(HKLM, 'SYSTEM\CurrentControlSet\Services\ViGEmBus');
end;
