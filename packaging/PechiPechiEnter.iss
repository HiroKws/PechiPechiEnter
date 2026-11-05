; ぺちぺちエンター / PechiPechiEnter — Windows 11 (x64) installer
;
; Build (from the repository root, after PyInstaller and tsf\build.bat):
;     "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" /DMyAppVersion=1.0.0 packaging\PechiPechiEnter.iss
; or, if Inno is installed machine-wide:
;     "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DMyAppVersion=1.0.0 packaging\PechiPechiEnter.iss
;
; 管理者権限が要る理由: TSF のテキストサービス（tsf\er_tip_x64.dll）を
; HKLM に COM 登録 + 言語プロファイル登録するため（tsf/README.md §2）。
; アプリ本体は通常ユーザー権限で動くので、exe 側のマニフェストは asInvoker のまま。

#define MyAppName "ぺちぺちエンター"
#define MyAppNameEn "PechiPechiEnter"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppPublisher "Hirohisa Kawase"
#define MyAppExeName MyAppNameEn + ".exe"

[Setup]
; AppId は「このプロダクト」の身元。バージョン間で変えると別アプリとして
; 別々にインストールされてしまうので、変えないこと。
AppId={{F5B90223-8995-4AB0-A437-1952F9F6CDC3}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppSupportURL=https://github.com/HiroKws/PechiPechiEnter
DefaultDirName={autopf}\{#MyAppNameEn}
DisableProgramGroupPage=yes
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename={#MyAppNameEn}-Setup-{#MyAppVersion}
SetupIconFile=..\src\enter_router\assets\enter-router.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Windows 11 のみ（README の動作環境）
MinVersion=10.0.22000
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; TSF 登録に HKLM が要る
PrivilegesRequired=admin
; {userstartup} / {userappdata} は「管理者として上げた本人」のユーザー領域を指す。
; 対象は個人の 1 ユーザー環境（管理者＝利用者本人）なので意図どおりだが、Inno は
; これを警告する。標準ユーザーが別の管理者に昇格してもらった場合だけ、自動起動の
; ショートカットが管理者側のプロファイルに入る（README の「うまく動かないとき」参照）。
UsedUserAreasWarning=no
; 実行中の常駐プロセスは自前で落とす（[Code] PrepareToInstall）
CloseApplications=no
VersionInfoVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} セットアップ
VersionInfoCopyright=MIT License

[Languages]
Name: "ja"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "デスクトップにショートカットを作る"; GroupDescription: "追加タスク:"; Flags: unchecked
Name: "autostart"; Description: "Windows 起動時に自動で開始する"; GroupDescription: "追加タスク:"

[Files]
; PyInstaller の onedir 出力（PechiPechiEnter.exe / PechiPechiEnterCmd.exe + _internal）
Source: "..\dist\{#MyAppNameEn}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; TSF テキストサービス（ビルド済み DLL を同梱。利用者に MSVC は要求しない）
Source: "..\tsf\build\er_tip_x64.dll"; DestDir: "{app}\tsf"; Flags: ignoreversion
Source: "..\tsf\build\er_tip_x86.dll"; DestDir: "{app}\tsf"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\config\sample.config.json"; DestDir: "{app}\config"; Flags: ignoreversion
Source: "..\config\chat-default.config.json"; DestDir: "{app}\config"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{#MyAppName} を終了"; Filename: "{sys}\taskkill.exe"; Parameters: "/f /im {#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\ログフォルダを開く"; Filename: "{sys}\explorer.exe"; Parameters: """{userappdata}\enter-router\logs"""
Name: "{group}\設定ファイルを開く"; Filename: "{sys}\explorer.exe"; Parameters: """{userappdata}\enter-router"""
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{#MyAppName} を今すぐ起動する"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; 登録解除 → ctfmon を再起動して反映（RunOnceId で 1 回だけ）
Filename: "{sys}\regsvr32.exe"; Parameters: "/u /s ""{app}\tsf\er_tip_x64.dll"""; Flags: runhidden waituntilterminated; RunOnceId: "UnregTipX64"
Filename: "{syswow64}\regsvr32.exe"; Parameters: "/u /s ""{app}\tsf\er_tip_x86.dll"""; Flags: runhidden waituntilterminated; RunOnceId: "UnregTipX86"
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im ctfmon.exe"; Flags: runhidden; RunOnceId: "RestartCtfmon"
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im {#MyAppExeName}"; Flags: runhidden; RunOnceId: "KillApp"

[Code]
{ ---------------------------------------------------------------------------
  1) 実行中の常駐プロセスを落とす（閉じる確認は出さない・黙って再起動できない
     トレイアプリなので、ファイル差し替えの前に確実に終了させる）
  2) インストール後に TSF の DLL を登録し、失敗を *黙って飲まない*
     （HKLM の登録は 1 つでも欠けると日本語入力の判定が効かなくなる）
  3) 登録後 ctfmon.exe を再起動して、既に動いているアプリへ反映させる
--------------------------------------------------------------------------- }
function RunHidden(const FileName, Params: String; var Code: Integer): Boolean;
begin
  Result := Exec(FileName, Params, '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  Result := '';
  NeedsRestart := False;
  { 終了していないと Uninstall/Install でファイルが置き換えられない }
  RunHidden(ExpandConstant('{sys}\taskkill.exe'),
            '/f /im {#MyAppExeName}', Code);
end;

procedure RegisterTSF();
var
  Code: Integer;
  Dll: String;
  Failed: String;
begin
  Failed := '';

  Dll := ExpandConstant('{app}\tsf\er_tip_x64.dll');
  if FileExists(Dll) then
  begin
    if (not RunHidden(ExpandConstant('{sys}\regsvr32.exe'),
                      '/s "' + Dll + '"', Code)) or (Code <> 0) then
      Failed := Failed + '  - 64bit: ' + Dll + ' (code ' + IntToStr(Code) + ')' + #13#10;
  end
  else
    Failed := Failed + '  - 64bit: ファイルがありません ' + Dll + #13#10;

  Dll := ExpandConstant('{app}\tsf\er_tip_x86.dll');
  if IsWin64 and FileExists(Dll) then
  begin
    if (not RunHidden(ExpandConstant('{syswow64}\regsvr32.exe'),
                      '/s "' + Dll + '"', Code)) or (Code <> 0) then
      Failed := Failed + '  - 32bit: ' + Dll + ' (code ' + IntToStr(Code) + ')' + #13#10;
  end;

  { ctfmon は自動で再起動する。落とせなくても致命的ではない }
  RunHidden(ExpandConstant('{sys}\taskkill.exe'), '/f /im ctfmon.exe', Code);

  if Failed <> '' then
    MsgBox('日本語入力の状態を読む部品（TSF テキストサービス）の登録に失敗しました。'
           + #13#10#13#10 + Failed + #13#10
           + '管理者権限で次のコマンドを実行すると直ることがあります:' + #13#10
           + '  regsvr32 "' + ExpandConstant('{app}\tsf\er_tip_x64.dll') + '"'
           + #13#10#13#10
           + 'この部品が無くても Enter の振り分けは動きますが、日本語入力の'
           + '判定は「未確定あり」とみなして素通しになります。',
           mbError, MB_OK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    RegisterTSF();
end;
