// er_tip.cpp — enter-router の観測用テキストサービス（TSF / キーは一切扱わない）
//
// 目的: 「いま日本語入力の未確定文字列があるか」を、日本語入力と同じ層（TSF）で
//       観測して共有メモリに書き出す。Enter の握り潰しや回数判定は Python 側が行う。
//
// 設計上の約束:
//   * キーシンク（ITfKeyEventSink）は実装しない。キーを消費しないので順序問題が無く、
//     日本語入力（Google 日本語入力 / MS-IME など）の動作を一切変えない。
//   * 未確定の有無は ITfContextComposition::EnumCompositions で問い合わせる
//     （キーが誰に消費されたかとは無関係に判定できる）。
//   * 状態は名前付き共有メモリ "Local\enter-router-tsf" にスレッド単位で書く。
//     x86 / x64 の両方から同じレイアウトで読めるよう固定幅の型だけを使う。
//   * 例外を投げない・落ちない（インプロセスなので落とすとホストアプリが落ちる）。
//
// ビルド: build.bat（x64 と x86 の両方）
// 登録:   regsvr32 er_tip_x64.dll（管理者で実行）

#define _WIN32_WINNT 0x0601
#define WIN32_LEAN_AND_MEAN

#include <windows.h>
#include <commctrl.h>
#include <msctf.h>
#include <wrl/client.h>

#include <cstdint>
#include <new>
#include <string>

using Microsoft::WRL::ComPtr;

// {6E2A7C31-2E4B-4F0A-9A57-8E4E6B2D1C01}
static const GUID CLSID_ErTip =
    {0x6E2A7C31, 0x2E4B, 0x4F0A, {0x9A, 0x57, 0x8E, 0x4E, 0x6B, 0x2D, 0x1C, 0x01}};
// {6E2A7C31-2E4B-4F0A-9A57-8E4E6B2D1C02}
static const GUID GUID_ErTipProfile =
    {0x6E2A7C31, 0x2E4B, 0x4F0A, {0x9A, 0x57, 0x8E, 0x4E, 0x6B, 0x2D, 0x1C, 0x02}};

static const wchar_t kDescription[] = L"enter-router observer";
static const wchar_t kSharedName[] = L"Local\\enter-router-tsf";
static const wchar_t kWindowClass[] = L"ErTipWatchWindow";
static const DWORD kMagic = 0x53545245;   // 'ERTS'
static const int kSlots = 32;
static const UINT_PTR kTimerId = 1;
static const UINT kPollMs = 40;

#pragma pack(push, 1)
struct Slot {
    volatile LONG tid;        // 0 = 空き
    volatile LONG composing;  // 1 = 未確定あり
    volatile LONGLONG tick;   // GetTickCount64 (ms)
    volatile LONG seq;
};
struct Shared {
    volatile LONG magic;
    volatile LONGLONG updated;
    Slot slots[kSlots];
};
#pragma pack(pop)

static HINSTANCE g_inst = nullptr;
static HANDLE g_map = nullptr;
static Shared* g_shared = nullptr;

// ---------------------------------------------------------------- 共有メモリ
static void EnsureShared() noexcept {
    if (g_shared) return;
    if (!g_map) {
        g_map = CreateFileMappingW(INVALID_HANDLE_VALUE, nullptr, PAGE_READWRITE, 0,
                                   static_cast<DWORD>(sizeof(Shared)), kSharedName);
    }
    if (g_map && !g_shared) {
        void* view = MapViewOfFile(g_map, FILE_MAP_ALL_ACCESS, 0, 0, sizeof(Shared));
        if (view) {
            g_shared = static_cast<Shared*>(view);
            if (g_shared->magic != kMagic) g_shared->magic = kMagic;
        }
    }
}

static void Publish(BOOL composing) noexcept {
    EnsureShared();
    if (!g_shared) return;
    const DWORD tid = GetCurrentThreadId();
    Slot* slot = nullptr;
    for (int i = 0; i < kSlots; ++i) {
        if (g_shared->slots[i].tid == static_cast<LONG>(tid)) {
            slot = &g_shared->slots[i];
            break;
        }
    }
    if (!slot) {
        for (int i = 0; i < kSlots; ++i) {
            if (g_shared->slots[i].tid == 0) {
                slot = &g_shared->slots[i];
                break;
            }
        }
    }
    if (!slot) {                              // 満杯: 最も古いスロットを再利用
        slot = &g_shared->slots[0];
        LONGLONG oldest = slot->tick;
        for (int i = 1; i < kSlots; ++i) {
            if (g_shared->slots[i].tick < oldest) {
                oldest = g_shared->slots[i].tick;
                slot = &g_shared->slots[i];
            }
        }
    }
    const LONGLONG now = static_cast<LONGLONG>(GetTickCount64());
    slot->tid = static_cast<LONG>(tid);
    slot->composing = composing ? 1 : 0;
    slot->tick = now;
    slot->seq = slot->seq + 1;
    g_shared->updated = now;
}

// ------------------------------------------------------------------- 本体
class ErTip final : public ITfTextInputProcessorEx,
                    public ITfThreadMgrEventSink {
public:
    // IUnknown
    STDMETHODIMP QueryInterface(REFIID riid, void** ppv) override {
        if (!ppv) return E_POINTER;
        *ppv = nullptr;
        if (IsEqualIID(riid, IID_IUnknown) ||
            IsEqualIID(riid, IID_ITfTextInputProcessor) ||
            IsEqualIID(riid, IID_ITfTextInputProcessorEx)) {
            *ppv = static_cast<ITfTextInputProcessorEx*>(this);
        } else if (IsEqualIID(riid, IID_ITfThreadMgrEventSink)) {
            *ppv = static_cast<ITfThreadMgrEventSink*>(this);
        } else {
            return E_NOINTERFACE;
        }
        AddRef();
        return S_OK;
    }
    STDMETHODIMP_(ULONG) AddRef() override {
        return static_cast<ULONG>(InterlockedIncrement(&_ref));
    }
    STDMETHODIMP_(ULONG) Release() override {
        const LONG n = InterlockedDecrement(&_ref);
        if (n == 0) delete this;
        return static_cast<ULONG>(n);
    }

    // ITfTextInputProcessor / ITfTextInputProcessorEx
    STDMETHODIMP Activate(ITfThreadMgr* mgr, TfClientId tid) override {
        return ActivateEx(mgr, tid, 0);
    }
    STDMETHODIMP Deactivate() override {
        if (_hwnd) {
            KillTimer(_hwnd, kTimerId);
            RemoveWindowSubclass(_hwnd, WatchProc, 1);
            DestroyWindow(_hwnd);
            _hwnd = nullptr;
        }
        if (_mgrSource && _mgrCookie) _mgrSource->UnadviseSink(_mgrCookie);
        _mgrSource.Reset();
        _mgrCookie = 0;
        _ctx.Reset();
        _mgr.Reset();
        _tid = 0;
        return S_OK;
    }
    STDMETHODIMP ActivateEx(ITfThreadMgr* mgr, TfClientId tid, DWORD) override {
        if (!mgr) return E_INVALIDARG;
        _tid = tid;
        _mgr = mgr;

        ComPtr<ITfSource> src;
        if (SUCCEEDED(mgr->QueryInterface(IID_PPV_ARGS(&src))) && src) {
            if (SUCCEEDED(src->AdviseSink(IID_ITfThreadMgrEventSink,
                                          static_cast<ITfThreadMgrEventSink*>(this),
                                          &_mgrCookie))) {
                _mgrSource = src;
            }
        }
        TrackFocus();
        EnsureWatchWindow();
        return S_OK;
    }

    // ITfThreadMgrEventSink
    STDMETHODIMP OnInitDocumentMgr(ITfDocumentMgr*) override { return S_OK; }
    STDMETHODIMP OnUninitDocumentMgr(ITfDocumentMgr*) override { return S_OK; }
    STDMETHODIMP OnSetFocus(ITfDocumentMgr* focus, ITfDocumentMgr*) override {
        if (focus) {
            ComPtr<ITfContext> ctx;
            if (SUCCEEDED(focus->GetTop(&ctx)) && ctx) {
                _ctx = ctx;
            } else {
                _ctx.Reset();
            }
        } else {
            _ctx.Reset();
        }
        if (!_ctx) Publish(FALSE);
        return S_OK;
    }
    STDMETHODIMP OnPushContext(ITfContext*) override { return S_OK; }
    STDMETHODIMP OnPopContext(ITfContext*) override { return S_OK; }

    // タイマー（アプリの UI スレッド上）で未確定の有無を問い合わせる
    void OnTimer() noexcept {
        if (!_ctx) {
            TrackFocus();
            if (!_ctx) {
                Publish(FALSE);
                return;
            }
        }
        BOOL composing = FALSE;
        ComPtr<ITfContextComposition> comp;
        if (SUCCEEDED(_ctx->QueryInterface(IID_PPV_ARGS(&comp))) && comp) {
            ComPtr<IEnumITfCompositionView> views;
            if (SUCCEEDED(comp->EnumCompositions(&views)) && views) {
                ComPtr<ITfCompositionView> view;
                ULONG fetched = 0;
                if (views->Next(1, view.GetAddressOf(), &fetched) == S_OK &&
                    fetched == 1) {
                    composing = TRUE;
                }
            }
        }
        Publish(composing);
    }

    // 隠しウィンドウのサブクラスプロシージャ（WM_TIMER を拾う）
    static LRESULT CALLBACK WatchProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp,
                                      UINT_PTR, DWORD_PTR ref) {
        if (msg == WM_TIMER && wp == kTimerId && ref) {
            reinterpret_cast<ErTip*>(ref)->OnTimer();
            return 0;
        }
        return DefSubclassProc(hwnd, msg, wp, lp);
    }

private:
    void TrackFocus() noexcept {
        if (!_mgr) return;
        ComPtr<ITfDocumentMgr> doc;
        if (SUCCEEDED(_mgr->GetFocus(&doc)) && doc) {
            ComPtr<ITfContext> ctx;
            if (SUCCEEDED(doc->GetTop(&ctx)) && ctx) _ctx = ctx;
        }
    }

    void EnsureWatchWindow() noexcept {
        if (_hwnd || !g_inst) return;
        WNDCLASSEXW wc = {};
        wc.cbSize = sizeof(wc);
        wc.lpfnWndProc = DefWindowProcW;
        wc.hInstance = g_inst;
        wc.lpszClassName = kWindowClass;
        RegisterClassExW(&wc);                 // 既に登録済みでも問題ない
        _hwnd = CreateWindowExW(0, kWindowClass, L"", 0, 0, 0, 0, 0, HWND_MESSAGE,
                                nullptr, g_inst, nullptr);
        if (!_hwnd) return;
        SetWindowSubclass(_hwnd, WatchProc, 1, reinterpret_cast<DWORD_PTR>(this));
        SetTimer(_hwnd, kTimerId, kPollMs, nullptr);
    }

    LONG _ref = 1;
    TfClientId _tid = 0;
    HWND _hwnd = nullptr;
    ComPtr<ITfThreadMgr> _mgr;
    ComPtr<ITfSource> _mgrSource;
    DWORD _mgrCookie = 0;
    ComPtr<ITfContext> _ctx;
};

// -------------------------------------------------------- クラスファクトリ
class ClassFactory final : public IClassFactory {
public:
    STDMETHODIMP QueryInterface(REFIID riid, void** ppv) override {
        if (!ppv) return E_POINTER;
        if (IsEqualIID(riid, IID_IUnknown) || IsEqualIID(riid, IID_IClassFactory)) {
            *ppv = static_cast<IClassFactory*>(this);
            AddRef();
            return S_OK;
        }
        *ppv = nullptr;
        return E_NOINTERFACE;
    }
    STDMETHODIMP_(ULONG) AddRef() override {
        return static_cast<ULONG>(InterlockedIncrement(&_ref));
    }
    STDMETHODIMP_(ULONG) Release() override {
        const LONG n = InterlockedDecrement(&_ref);
        if (n == 0) delete this;
        return static_cast<ULONG>(n);
    }
    STDMETHODIMP CreateInstance(IUnknown* outer, REFIID riid, void** ppv) override {
        if (outer) return CLASS_E_NOAGGREGATION;
        auto* tip = new (std::nothrow) ErTip();
        if (!tip) return E_OUTOFMEMORY;
        const HRESULT hr = tip->QueryInterface(riid, ppv);
        tip->Release();
        return hr;
    }
    STDMETHODIMP LockServer(BOOL lock) override {
        if (lock) InterlockedIncrement(&_locks);
        else InterlockedDecrement(&_locks);
        return S_OK;
    }

private:
    LONG _ref = 1;
    LONG _locks = 0;
};

// --------------------------------------------------------------- エクスポート
STDAPI DllGetClassObject(REFCLSID clsid, REFIID riid, void** ppv) {
    if (!IsEqualCLSID(clsid, CLSID_ErTip)) return CLASS_E_CLASSNOTAVAILABLE;
    auto* factory = new (std::nothrow) ClassFactory();
    if (!factory) return E_OUTOFMEMORY;
    const HRESULT hr = factory->QueryInterface(riid, ppv);
    factory->Release();
    return hr;
}

static HRESULT SetRegString(HKEY root, const wchar_t* sub, const wchar_t* name,
                            const wchar_t* value) {
    HKEY key = nullptr;
    LSTATUS st = RegCreateKeyExW(root, sub, 0, nullptr, 0, KEY_WRITE, nullptr, &key,
                                 nullptr);
    if (st != ERROR_SUCCESS) return HRESULT_FROM_WIN32(st);
    st = RegSetValueExW(key, name, 0, REG_SZ,
                        reinterpret_cast<const BYTE*>(value),
                        static_cast<DWORD>((wcslen(value) + 1) * sizeof(wchar_t)));
    RegCloseKey(key);
    return HRESULT_FROM_WIN32(st);
}

static HRESULT RegisterProfile(LANGID langid) {
    ComPtr<ITfInputProcessorProfileMgr> mgr;
    HRESULT hr = CoCreateInstance(CLSID_TF_InputProcessorProfiles, nullptr,
                                  CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&mgr));
    if (FAILED(hr)) return hr;
    return mgr->RegisterProfile(CLSID_ErTip, langid, GUID_ErTipProfile, kDescription,
                                static_cast<ULONG>(wcslen(kDescription)),
                                nullptr, 0, 0, nullptr, 0, TRUE, 0);
}

static void UnregisterProfile(LANGID langid) {
    ComPtr<ITfInputProcessorProfileMgr> mgr;
    if (SUCCEEDED(CoCreateInstance(CLSID_TF_InputProcessorProfiles, nullptr,
                                   CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&mgr)))) {
        mgr->UnregisterProfile(CLSID_ErTip, langid, GUID_ErTipProfile, 0);
    }
}

STDAPI DllRegisterServer() {
    wchar_t path[MAX_PATH] = {0};
    if (!GetModuleFileNameW(g_inst, path, MAX_PATH)) return E_FAIL;

    wchar_t clsid[64] = {0};
    StringFromGUID2(CLSID_ErTip, clsid, 64);

    std::wstring base = L"SOFTWARE\\Classes\\CLSID\\";
    base += clsid;
    HRESULT hr = SetRegString(HKEY_LOCAL_MACHINE, base.c_str(), nullptr, kDescription);
    if (FAILED(hr)) return hr;
    std::wstring inproc = base + L"\\InprocServer32";
    hr = SetRegString(HKEY_LOCAL_MACHINE, inproc.c_str(), nullptr, path);
    if (FAILED(hr)) return hr;
    hr = SetRegString(HKEY_LOCAL_MACHINE, inproc.c_str(), L"ThreadingModel",
                      L"Apartment");
    if (FAILED(hr)) return hr;

    // 日本語 (0x0411) と英語 (0x0409) の両方に登録する（アプリのキーボード設定が
    // 英数でも TSF の文脈は作られるため、両方ある方が確実に読み込まれる）。
    hr = RegisterProfile(0x0411);
    if (FAILED(hr)) return hr;
    return RegisterProfile(0x0409);
}

STDAPI DllUnregisterServer() {
    UnregisterProfile(0x0411);
    UnregisterProfile(0x0409);

    wchar_t clsid[64] = {0};
    StringFromGUID2(CLSID_ErTip, clsid, 64);
    std::wstring base = L"SOFTWARE\\Classes\\CLSID\\";
    base += clsid;
    std::wstring inproc = base + L"\\InprocServer32";
    RegDeleteKeyW(HKEY_LOCAL_MACHINE, inproc.c_str());
    RegDeleteKeyW(HKEY_LOCAL_MACHINE, base.c_str());
    return S_OK;
}

BOOL APIENTRY DllMain(HMODULE mod, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        g_inst = mod;
        DisableThreadLibraryCalls(mod);
        EnsureShared();
    }
    return TRUE;
}
