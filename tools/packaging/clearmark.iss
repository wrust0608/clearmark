; Script generated for ClearMark Windows Desktop Host
; Target: ClearMark v2.2.0-rc1
; Per-user non-admin installer with uninstall safety and graceful shutdown

#define MyAppName "ClearMark"
#define MyAppVersion "2.2.0-rc1"
#define MyAppPublisher "ClearMark Project"
#define MyAppURL "https://github.com/wrust0608/clearmark"
#define MyAppExeName "ClearMark.exe"

[Setup]
AppId={{C8E19B24-8D4C-4D66-A528-66B81C92EF4D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={localappdata}\Programs\ClearMark
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Lowest privilege required: installs into user's %LOCALAPPDATA%\Programs without UAC prompt
PrivilegesRequired=lowest
OutputDir=..\..\dist\release
OutputBaseFilename=ClearMark-Setup-v{#MyAppVersion}
SetupIconFile=..\..\assets\ClearMark.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\..\dist\ClearMark\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\ClearMark.ico"
Name: "{group}\Stop {#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--stop"; IconFilename: "{app}\assets\ClearMark.ico"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\ClearMark.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
// Helper function to stop any running instance of ClearMark gracefully
function StopRunningClearMark(AppPath: String): Boolean;
var
  ResultCode: Integer;
  ExePath: String;
begin
  Result := True;
  ExePath := AppPath + '\{#MyAppExeName}';
  if FileExists(ExePath) then
  begin
    // Attempt graceful stop via ClearMark.exe --stop
    Exec(ExePath, '--stop', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Sleep(500);
  end;
end;

function InitializeSetup(): Boolean;
var
  InstalledExe: String;
begin
  InstalledExe := ExpandConstant('{localappdata}\Programs\ClearMark\{#MyAppExeName}');
  if FileExists(InstalledExe) then
  begin
    StopRunningClearMark(ExpandConstant('{localappdata}\Programs\ClearMark'));
  end;
  Result := True;
end;

function InitializeUninstall(): Boolean;
var
  AppDir: String;
begin
  AppDir := ExpandConstant('{app}');
  // Ensure running ClearMark is stopped before uninstaller attempts to delete files
  StopRunningClearMark(AppDir);
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  AppDataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    AppDataDir := ExpandConstant('{localappdata}\ClearMark');
    if DirExists(AppDataDir) then
    begin
      // Ask user if they wish to clean up runtime cache/state
      if MsgBox('Do you also want to remove ClearMark runtime cache and state files?' #13#10 '(Log files will be preserved if you choose No).', mbConfirmation, MB_YESNO) = IDYES then
      begin
        DelTree(AppDataDir + '\state', True, True, True);
        DelTree(AppDataDir + '\cache', True, True, True);
        DelTree(AppDataDir + '\logs', True, True, True);
        RemoveDir(AppDataDir);
      end
      else
      begin
        // Always clean up ephemeral state even if preserving logs
        DelTree(AppDataDir + '\state', True, True, True);
        DelTree(AppDataDir + '\cache', True, True, True);
      end;
    end;
  end;
end;
