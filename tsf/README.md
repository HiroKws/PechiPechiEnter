# er_tip — enter-router の観測用テキストサービス（TSF）

日本語入力と同じ層（TSF）で**未確定文字列の有無だけ**を観測し、共有メモリに書き出す
小さなテキストサービスです。Enter の握り潰し・回数判定・設定は Python 側（enter-router
本体）が行います。

**キーは一切扱いません。** `ITfKeyEventSink` を実装していないので、Google 日本語入力や
MS-IME の動作を変えず、キーの横取りも起きません。

| 項目 | 内容 |
|---|---|
| 共有メモリ名 | `Local\enter-router-tsf`（セッション内のみ） |
| 書き込む内容 | スレッドごとに `composing`（1 = 未確定あり）と更新時刻 |
| 問い合わせ方法 | `ITfContextComposition::EnumCompositions` を 40ms ごと |
| 出力 | `build/er_tip_x64.dll` / `build/er_tip_x86.dll` |

レイアウト（`er_tip.cpp` と `check_state.py` で共通、固定幅・パック済み）:

```
Shared { int32 magic('ERTS'); int64 updated; Slot[32] }
Slot   { int32 tid; int32 composing; int64 tick; int32 seq }
```

---

## 1. ビルド

**必要なもの**

- Visual Studio 2019 BuildTools（MSVC v142）または同等の C++ コンパイラ
- Windows SDK 10（検証は 10.0.19041.0）
- このリポジトリの `tsf/` ディレクトリ

**手順**

```
cd tsf
build.bat
```

`build.bat` は x64 と x86 の両方を作ります（`vcvarsall.bat` を x64 → x86 の順に呼ぶだけ）。

```
=== x64 ===
er_tip.cpp
=== x86 ===
er_tip.cpp
OK: C:\Users\hirok\enter-router\tsf\build\er_tip_x64.dll and er_tip_x86.dll
```

出力:

| ファイル | 用途 |
|---|---|
| `build/er_tip_x64.dll` | 64bit アプリ用（Hermes / Chrome / Edge / Firefox はこれ） |
| `build/er_tip_x86.dll` | 32bit アプリ用（使っていないなら不要） |

ビルドが通らないときの確認点:

- `cl` が見つからない → `build.bat` の `VCVARS` のパスを自分の環境に合わせる
- `C4819`（コードページ）→ `/utf-8` が付いているか（付いていないと日本語コメントで壊れる）
- `LNK2019: __imp_CreateWindowExW` → `user32.lib` のリンク漏れ
- 32bit のリンクで失敗 → `vcvarsall.bat x86` を呼んだあとに `cl` を実行しているか

## 2. インストール（管理者権限が要ります）

```
regsvr32 C:\Users\hirok\enter-router\tsf\build\er_tip_x64.dll
```

32bit アプリも対象にする場合だけ、こちらも実行します（`SysWOW64` の regsvr32 を使う）:

```
C:\Windows\SysWOW64\regsvr32.exe C:\Users\hirok\enter-router\tsf\build\er_tip_x86.dll
```

`regsvr32` は次の 2 つを登録します（`DllRegisterServer` の中身）。

1. COM: `HKLM\SOFTWARE\Classes\CLSID\{6E2A7C31-2E4B-4F0A-9A57-8E4E6B2D1C01}\InprocServer32`
2. TSF の言語プロファイル: 日本語 `0x0411` と英語 `0x0409` に
   `ITfInputProcessorProfileMgr::RegisterProfile`（表示名は `enter-router observer`）

**反映**（登録しただけでは既に動いているアプリには入りません）:

```
taskkill /f /im ctfmon.exe
```

`ctfmon.exe` は自動で再起動します。入り切らないアプリは一度終了して起動し直してください。
サインアウト／サインインでも同じです。

**確認**:

```
python tsf\check_state.py --watch
```

日本語入力をオンにして何か入力すると、その行の `composing` が `1`（未確定あり）になり、
確定すると `0` に戻ります。

```
12:34:56
slots=1
  tid=12345   未確定あり(日本語入力中)   age=      8ms seq=42
```

## 3. アンインストール

```
regsvr32 /u C:\Users\hirok\enter-router\tsf\build\er_tip_x64.dll
C:\Windows\SysWOW64\regsvr32.exe /u C:\Users\hirok\enter-router\tsf\build\er_tip_x86.dll
taskkill /f /im ctfmon.exe
```

そのあと DLL を削除して構いません。`regsvr32 /u` は COM の CLSID キーと TSF の言語
プロファイルの両方を消します。

## 4. 実測での確認（2026-11-01）

ビルド・登録後、この環境で確認した結果です。

**読み込まれているプロセス**（`Get-Process | Where Modules -like '*er_tip_x64.dll'`）:

```
Hermes, firefox, msedge, explorer, Notepad, Docker Desktop, RadeonSoftware, msrdc
```

対象の 3 ブラウザと Hermes（Electron）に実際に読み込まれています。

**状態の遷移**（`python tsf/selftest.py`、Edge の入力欄で 日本語入力オン → k → a → Enter）:

| 時点 | TIP が書いた composing | 意味 |
|---|---|---|
| 起動直後 | 0 | 未確定なし |
| `k` の後 | **1** | 日本語入力中 |
| `ka` の後 | **1** | 未確定の「か」がある |
| `Enter`（確定）の後 | 0 | 確定後 |

同じ実行で 14 スレッド分のスロットが書かれており、複数アプリが同時に観測できています。

## 5. ルーターとの統合

ルーター（Python）は Enter の瞬間に `platform/tsf_state.composing(hwnd)` を読みます。

| 値 | 意味 | ルーターの動作 |
|---|---|---|
| `True` | 日本語入力中（未確定あり） | **何もせず IME に渡す**（数えない・注入しない） |
| `False` | 確定後・未入力 | Enter の回数で振り分ける（1回=改行、2回=送信…） |
| `None` | er_tip 未登録・対象外アプリ・記録が 500ms より古い | 安全側（日本語入力中とみなして素通し） |

該当するコード: `src/enter_router/platform/tsf_state.py`（Win32 読み出し）と
`src/enter_router/core/tsf_state.py`（解析・純粋）、`app/main.py` の Enter 分岐。

## 6. 設計メモ（なぜこの形か）

- **外からは未確定文字列が読めない**。実測（2026-11-01、Edge/Chromium、ページ側の
  composition イベントを正解にして確認）では、IMM の `ImmGetContext` は他プロセスの窓で
  常に 0、`MSCTFIME Composition` などのウィンドウは **Google 日本語入力では出ない**
  （変換 UI は Google 側のプロセスにある）、MSAA は入力欄の子要素を公開しない、
  UIA は値を読めるが「未確定かどうか」のフラグは無い、UIA のイベントも発火しない。
- **TSF の中なら読める**。`ITfContextComposition::EnumCompositions` はアプリの文脈に
  ある未確定（composition）を列挙できる。これが唯一の確実な信号。
- **キーは触らない**。`ITfKeyEventSink` を実装すると「日本語入力より先か後か」という
  順序問題に入る（TSF は処理した時点で連鎖を止めるので、後ろに並ぶことはできない）。
  キーを扱わなければ順序問題自体が発生しない。
- **40ms のタイマー**はアプリの UI スレッド上で回す。TSF のオブジェクトは
  アパートメントスレッドに属するため、別スレッドから触らずに済ませるため。

## 7. 既知の制約

- **Windows 専用**
- 64bit アプリには 64bit DLL、32bit アプリには 32bit DLL が必要（自動では切り替わらない）
- TSF を使わないアプリ（一部の古い Win32・コンソール）では動かない
- インプロセスで動くため、この DLL がクラッシュするとホストのアプリも落ちる
  （コードは `__try` を使わず、例外を投げない書き方にしてある）
- アンチウイルス／EDR がテキストサービスの登録を不審がることがある
- 登録は `HKLM` なので**管理者権限が必要**。個人利用でも 1 回だけ UAC を通す
