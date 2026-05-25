; Inno Setup script for Pythinker on Windows
;
; Produces PythinkerSetup-{version}.exe — a per-user installer that:
;   * Lands the PyInstaller bundle under %LOCALAPPDATA%\Programs\Pythinker
;   * Adds the install dir to the user's PATH (HKCU\Environment)
;   * Broadcasts WM_SETTINGCHANGE so new shells see the PATH edit
;   * Supports silent install / uninstall for `pythinker-ai update`
;
; Compile from a Windows runner with Inno Setup 6:
;     iscc /DAppVersion=2.7.0 packaging\inno\pythinker.iss
;
; CI passes /DAppVersion from the workflow.

#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif

#define MyAppName        "Pythinker"
#define MyAppPublisher   "Mohamed Elkholy"
#define MyAppURL         "https://github.com/mohamed-elkholy95/Pythinker"
#define MyAppExeName     "pythinker-ai.exe"

[Setup]
AppId={{F6E0E5D2-2A7B-4F60-9F36-PYTHINKERAI001}}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={localappdata}\Programs\Pythinker
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=PythinkerSetup-{#AppVersion}
OutputDir=..\..\dist\windows
Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
ChangesEnvironment=yes
CloseApplications=yes
RestartApplications=no
; Allow `pythinker-ai update` to upgrade silently in-place.
SetupLogging=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "addtopath"; Description: "Add {#MyAppName} to my PATH"; GroupDescription: "Shell integration:"; Flags: checkedonce

[Files]
; The PyInstaller --onedir output lives at ..\..\dist\pythinker on the runner.
Source: "..\..\dist\pythinker\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Registry]
; HKCU PATH addition; Inno's `Tasks:` test skips this if user unchecked the box.
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "PATH"; \
    ValueData: "{olddata};{app}"; Check: NeedsAddPath('{app}'); Tasks: addtopath

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "--version"; Description: "Verify install"; \
    Flags: postinstall nowait skipifsilent runascurrentuser

[Code]
function NeedsAddPath(Param: string): Boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'PATH', OrigPath) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Param + ';', ';' + OrigPath + ';') = 0;
end;

// NOTE: do not add a CurStepChanged that calls `setx PATH "%PATH%"` —
// in a child cmd.exe `%PATH%` expands to the concatenated HKLM+HKCU value,
// and `setx` (a) writes that into HKCU (duplicating every HKLM entry) and
// (b) truncates to 1024 chars, corrupting long PATHs.
// The `ChangesEnvironment=yes` directive in `[Setup]` already makes Inno
// broadcast WM_SETTINGCHANGE after the registry edit; no manual step needed.
