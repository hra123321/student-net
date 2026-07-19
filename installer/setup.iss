; 校园网登录助手 - Inno Setup 安装脚本
#define MyAppName "校园网登录助手"
#define MyAppVersion "1.4.5"
#define MyAppPublisher "CampusNet"
#define MyAppURL "https://github.com/hra123321/student-net"
#define MyAppExeName "校园网登录助手_v1.4.5.exe"
#define MyAppBuildDir "校园网登录助手_v1.4.5"
#define SrcDir "C:\Users\123\Documents\校园网登录助手"

[Setup]
AppId={{7A8B1C2D-3E4F-5A6B-7C8D-9E0F1A2B3C4D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={localappdata}\{#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
OutputDir={#SrcDir}\installer
OutputBaseFilename=校园网登录助手_Setup_v1.4.5
SetupIconFile=
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
PrivilegesRequired=admin
AlwaysRestart=no
ShowLanguageDialog=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "{#SrcDir}\dist_v1.4.5\{#MyAppBuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SrcDir}\config.example.json"; DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
Type: files; Name: "{app}\校园网登录助手_v*.exe"
Type: filesandordirs; Name: "{app}\_internal"

[Dirs]
Name: "{app}\data"

[Icons]
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--show"
Name: "{commonprograms}\{#MyAppName}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--show"
Name: "{commonprograms}\{#MyAppName}\卸载"; Filename: "{uninstallexe}"

[Run]
Filename: "{sys}\schtasks.exe"; Parameters: "/Create /F /TN ""{#MyAppName}"" /TR ""{app}\{#MyAppExeName} --background"" /SC ONLOGON /RL HIGHEST"; Flags: runhidden waituntilterminated; StatusMsg: "正在配置开机后台自启..."

[UninstallRun]
Filename: "taskkill"; Parameters: "/f /im {#MyAppExeName}"; Flags: runhidden; RunOnceId: "StopCampusNetAssistant"
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /F /TN ""{#MyAppName}"""; Flags: runhidden; RunOnceId: "DeleteCampusNetAssistantTask"

[Code]
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM "校园网登录助手_v*.exe"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\schtasks.exe'), '/Delete /F /TN "{#MyAppName}"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', '{#MyAppName}');
  Result := True;
end;
