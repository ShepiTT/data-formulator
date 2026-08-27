; Data Formulator 中文定制版 — Windows 安装程序脚本（Inno Setup 6）
;
; 构建方法（在仓库根目录）：
;   1. yarn build
;   2. uv run pyinstaller packaging/data_formulator_desktop.spec --noconfirm
;   3. ISCC packaging\installer.iss
; 产物：dist\installer\DataFormulator-Setup-<版本>.exe

#define MyAppName "Data Formulator"
#define MyAppVersion "0.8.0"
#define MyAppExeName "Data Formulator.exe"

[Setup]
; 固定的应用 ID，升级安装时用于识别旧版本
AppId={{6B1C7A2E-DF08-4A11-9C40-3B7E51F0AD27}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=Data Formulator 中文定制版
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=..\dist\installer
OutputBaseFilename=DataFormulator-Setup-{#MyAppVersion}
SetupIconFile=icons\data-formulator.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; 默认按当前用户安装（无需管理员权限，装到用户目录）；
; 弹窗允许选择"为所有用户安装"（需要管理员权限）
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; 关闭正在运行的实例后再安装
CloseApplications=yes

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\Data Formulator\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; WebView2 运行时引导程序 — 仅在目标机器缺少 WebView2 时安装
Source: "MicrosoftEdgeWebView2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: not IsWebView2Installed

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{tmp}\MicrosoftEdgeWebView2Setup.exe"; Parameters: "/silent /install"; \
    StatusMsg: "正在安装 Microsoft Edge WebView2 运行时（首次需要）..."; \
    Check: not IsWebView2Installed; Flags: waituntilterminated
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 应用自身目录下运行期生成的文件（用户数据在 %USERPROFILE%\.data_formulator，卸载时保留）
Type: filesandordirs; Name: "{app}\_internal"

[Code]
function IsWebView2Installed: Boolean;
var
  Version: String;
begin
  Result :=
    RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) or
    RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) or
    RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version);
  Result := Result and (Version <> '') and (Version <> '0.0.0.0');
end;
