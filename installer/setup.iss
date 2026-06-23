; 校园网登录助手 - Inno Setup 安装脚本
#define MyAppName "校园网登录助手"
#define MyAppVersion "1.3.6"
#define MyAppPublisher "CampusNet"
#define MyAppURL "https://github.com/hra123321/student-net"
#define MyAppExeName "校园网登录助手_v1.3.6.exe"
#define SrcDir "C:\Users\123\Documents\校园网登录助手"

[Setup]
AppId={{7A8B1C2D-3E4F-5A6B-7C8D-9E0F1A2B3C4D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
OutputDir={#SrcDir}\installer
OutputBaseFilename=校园网登录助手_Setup_v1.3.6
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
Source: "{#SrcDir}\dist_v1.3.6\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SrcDir}\config.example.json"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
Name: "{app}\data"

[Icons]
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{commonprograms}\{#MyAppName}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{commonprograms}\{#MyAppName}\卸载"; Filename: "{uninstallexe}"

[Tasks]
Name: "desktopicon"; Description: "Create desktop shortcut"; GroupDescription: "Shortcuts:"

[Run]
Filename: "{sys}\schtasks.exe"; Parameters: "/Create /F /TN ""{#MyAppName}"" /TR """"""{app}\{#MyAppExeName}"""""" /SC ONLOGON /RL HIGHEST"; Flags: runhidden waituntilterminated
Filename: "{app}\{#MyAppExeName}"; Description: "Run 校园网登录助手"; Flags: nowait postinstall skipifsilent shellexec

[UninstallRun]
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /F /TN ""{#MyAppName}"""; Flags: runhidden waituntilterminated
Filename: "taskkill"; Parameters: "/f /im {#MyAppExeName}"; Flags: runhidden
