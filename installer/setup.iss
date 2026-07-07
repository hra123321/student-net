; 校园网登录助手 - Inno Setup 安装脚本
#define MyAppName "校园网登录助手"
#define MyAppVersion "1.4.3"
#define MyAppPublisher "CampusNet"
#define MyAppURL "https://github.com/hra123321/student-net"
#define MyAppExeName "校园网登录助手_v1.4.3.exe"
#define MyAppBuildDir "校园网登录助手_v1.4.3"
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
OutputBaseFilename=校园网登录助手_Setup_v1.4.3
SetupIconFile=
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
PrivilegesRequired=lowest
AlwaysRestart=no
ShowLanguageDialog=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "{#SrcDir}\dist_v1.4.3\{#MyAppBuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SrcDir}\config.example.json"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
Name: "{app}\data"

[Icons]
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--show"; Tasks: desktopicon
Name: "{commonprograms}\{#MyAppName}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--show"
Name: "{commonprograms}\{#MyAppName}\卸载"; Filename: "{uninstallexe}"

[Tasks]
Name: "desktopicon"; Description: "Create desktop shortcut"; GroupDescription: "Shortcuts:"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue

[UninstallRun]
Filename: "taskkill"; Parameters: "/f /im {#MyAppExeName}"; Flags: runhidden
