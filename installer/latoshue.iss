; SPDX-License-Identifier: AGPL-3.0-only
; Copyright (C) 2026 Denvolatos and contributors
; Inno Setup script for Latos Hue (the desktop app). Build with build_app.ps1 -Installer (it passes /DAppVer=x.y.z).
; Per-user install, no administrator rights. It installs the app folder (build\app_dist\LatosHue) and the Lightroom plug-in
; (staged by build_app.ps1 in build\stage_app\LrMcp.lrplugin, without the development helpers). It does NOT register anything
; with Claude Code / Codex: Latos Hue starts the AI itself.
; Test switches: /PLUGINDIR=<folder> installs the plug-in there instead of %APPDATA%\Adobe\Lightroom\Modules\LrMcp.lrplugin,
;                /NOPLUGIN skips the plug-in. (Use them together with /DIR= and /NOICONS to test without touching the real Lightroom.)
#ifndef AppVer
  #define AppVer "0.0.0"
#endif
#define AppExe "LatosHue.exe"
#define PluginName "LrMcp.lrplugin"

[Setup]
AppId={{C3A5D8F2-6B41-4E97-A1D0-8F2E7B9C4A15}
AppName=Latos Hue
AppVersion={#AppVer}
AppVerName=Latos Hue {#AppVer}
AppPublisher=Denvolatos
AppPublisherURL=https://github.com/Denvolatos/lightroom-mcp-win
DefaultDirName={localappdata}\Programs\Latos Hue
DefaultGroupName=Latos Hue
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\build\installer
OutputBaseFilename=LatosHue-Setup-{#AppVer}
SetupIconFile=..\app\web\assets\latos-hue-ribbon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName=Latos Hue
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\LICENSE
InfoBeforeFile=latoshue_before.txt
InfoAfterFile=latoshue_after.txt
; only offer to close Latos Hue itself - never Lightroom (the plug-in files are not matched by this filter)
CloseApplications=yes
CloseApplicationsFilter={#AppExe},latoshue-helper.exe
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
DesktopIconTask=Create a &desktop shortcut / 创建桌面快捷方式
WebView2Title=Missing component / 缺少组件
WebView2Missing=Latos Hue shows its window with Microsoft Edge WebView2, and it was not found on this computer.
WebView2Missing2=Latos Hue 的窗口依赖 Microsoft Edge WebView2 运行库，但没有在这台电脑上找到（Windows 11 自带，部分 Windows 10 没有）。
WebView2Missing3=You can install now and get WebView2 afterwards from / 可以先继续安装，之后到这里下载安装：
WebView2Continue=Install anyway / 继续安装
WebView2Open=Open download page and quit / 打开下载页并退出
WebView2Cancel=Cancel / 取消
PluginUpdated=The Lightroom plug-in was installed or updated. If Lightroom Classic is open, please restart it. / Lightroom 插件已安装或更新；如果 Lightroom Classic 正开着，请重启它。
PluginSkipped=The Lightroom plug-in was NOT installed (skipped). / Lightroom 插件没有安装（已跳过）。
PluginRefused=The plug-in folder was left alone because it holds something that is not a plug-in. / 插件目标文件夹里有不属于插件的东西，所以没有动它：
AskDeleteData=Also delete your settings and experience notes (folder %1)? Your photos are never deleted. Choose No to keep them.%n%n是否同时删除设置和经验笔记等个人数据（文件夹 %1）？你的照片永远不会被删除。选“否”保留。
LaunchApp=&Run Latos Hue / 立即运行 Latos Hue

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIconTask}"; Flags: unchecked

[Files]
; the app folder (PyInstaller onedir: LatosHue.exe, latoshue-helper.exe and _internal must stay together)
Source: "..\build\app_dist\LatosHue\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; licence texts: this project's licence, the third-party notices and copies of the bundled packages' licence files
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\licenses\*"; DestDir: "{app}\licenses"; Flags: recursesubdirs createallsubdirs ignoreversion
; the Lightroom plug-in; the old folder is removed in CurStepChanged(ssInstall) first, so an update replaces it completely
Source: "..\build\stage_app\{#PluginName}\*"; DestDir: "{code:PluginDir}"; Flags: recursesubdirs createallsubdirs ignoreversion; Check: PluginWanted

[Icons]
Name: "{autoprograms}\Latos Hue"; Filename: "{app}\{#AppExe}"
Name: "{autoprograms}\Uninstall Latos Hue"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Latos Hue"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchApp}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\plugin-dir.txt"

[Code]
const
  PluginMarker = 'plugin-dir.txt';
  WebView2Guid = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

var
  PluginUpdated: Boolean;
  PluginRefusedDir: String;

function ParamIsSwitch(const Name: String): Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), '/' + Name) = 0 then
      Result := True;
end;

function NoPlugin: Boolean;
begin
  Result := ParamIsSwitch('NOPLUGIN');
end;

function PluginDir(Param: String): String;
begin
  Result := RemoveBackslash(ExpandConstant('{param:PLUGINDIR|}'));
  if Result = '' then
    Result := ExpandConstant('{userappdata}\Adobe\Lightroom\Modules\{#PluginName}');
end;

{ A folder is safe to clean and replace only if it is missing, empty, or already holds a Lightroom plug-in (Info.lua).
  Never a drive root or another very short path. }
function PluginDirIsOurs(const Dir: String): Boolean;
var
  FindRec: TFindRec;
begin
  Result := False;
  if Length(Dir) < 8 then Exit;
  if not DirExists(Dir) then begin Result := True; Exit; end;
  if FileExists(Dir + '\Info.lua') then begin Result := True; Exit; end;
  Result := True;
  if FindFirst(Dir + '\*', FindRec) then
  try
    repeat
      if (FindRec.Name <> '.') and (FindRec.Name <> '..') then Result := False;
    until not FindNext(FindRec);
  finally
    FindClose(FindRec);
  end;
end;

function PluginWanted: Boolean;
begin
  Result := (not NoPlugin) and (PluginRefusedDir = '');
end;

function WebView2Present: Boolean;
var
  Pv, Key: String;
begin
  Key := 'SOFTWARE\Microsoft\EdgeUpdate\Clients\' + WebView2Guid;
  Result := False;
  if RegQueryStringValue(HKLM32, Key, 'pv', Pv) and (Pv <> '') and (Pv <> '0.0.0.0') then Result := True;
  if (not Result) and RegQueryStringValue(HKCU32, Key, 'pv', Pv) and (Pv <> '') and (Pv <> '0.0.0.0') then Result := True;
  if (not Result) and RegQueryStringValue(HKCU64, Key, 'pv', Pv) and (Pv <> '') and (Pv <> '0.0.0.0') then Result := True;
end;

function InitializeSetup: Boolean;
var
  Choice, ErrCode: Integer;
begin
  Result := True;
  { silent installs never ask }
  if (not WizardSilent) and (not WebView2Present) then
  begin
    Choice := TaskDialogMsgBox(CustomMessage('WebView2Title'),
      CustomMessage('WebView2Missing') + #13#10 + CustomMessage('WebView2Missing2') + #13#10#13#10 +
      CustomMessage('WebView2Missing3') + #13#10 + 'https://developer.microsoft.com/microsoft-edge/webview2/',
      mbInformation, MB_YESNOCANCEL, [CustomMessage('WebView2Continue'), CustomMessage('WebView2Open'), CustomMessage('WebView2Cancel')], 0);
    if Choice = IDNO then
    begin
      ShellExec('open', 'https://developer.microsoft.com/microsoft-edge/webview2/', '', '', SW_SHOWNORMAL, ewNoWait, ErrCode);
      Result := False;
    end
    else if Choice <> IDYES then
      Result := False;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Dir: String;
begin
  if (CurStep = ssInstall) and (not NoPlugin) then
  begin
    Dir := PluginDir('');
    if PluginDirIsOurs(Dir) then
    begin
      if DirExists(Dir) then DelTree(Dir, True, True, True);   { update = remove the old plug-in files first }
      PluginUpdated := True;
    end
    else
      PluginRefusedDir := Dir;
  end;
  if (CurStep = ssPostInstall) and PluginUpdated then
    { remember where the plug-in went, so the uninstaller removes exactly that folder }
    SaveStringToFile(ExpandConstant('{app}\' + PluginMarker), PluginDir(''), False);
end;

procedure CurPageChanged(CurPageID: Integer);
var
  Extra: String;
begin
  if CurPageID = wpFinished then
  begin
    if PluginRefusedDir <> '' then
      Extra := CustomMessage('PluginRefused') + #13#10 + PluginRefusedDir
    else if PluginUpdated then
      Extra := CustomMessage('PluginUpdated')
    else
      Extra := CustomMessage('PluginSkipped');
    WizardForm.FinishedLabel.Caption := WizardForm.FinishedLabel.Caption + #13#10#13#10 + Extra;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Marker, Dir, DataDir: String;
  Lines: TArrayOfString;
begin
  if CurUninstallStep = usUninstall then
  begin
    { only the one recorded plug-in folder (default: ...\Modules\LrMcp.lrplugin), and only if it really is a plug-in folder }
    Marker := ExpandConstant('{app}\' + PluginMarker);
    if FileExists(Marker) and LoadStringsFromFile(Marker, Lines) and (GetArrayLength(Lines) > 0) then
    begin
      Dir := RemoveBackslash(Trim(Lines[0]));
      if (Length(Dir) >= 8) and DirExists(Dir) and FileExists(Dir + '\Info.lua') then
        DelTree(Dir, True, True, True);
    end;
  end;
  if CurUninstallStep = usPostUninstall then
  begin
    { Personal data (settings, notes, presets, favourites) is kept unless the user says yes; a silent uninstall never deletes it.
      This is only the app's own data folder - the photo folder the user picked is never touched. }
    DataDir := ExpandConstant('{%USERPROFILE}\LrMcp');
    if (not UninstallSilent) and DirExists(DataDir) then
      if MsgBox(FmtMessage(CustomMessage('AskDeleteData'), [DataDir]), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
