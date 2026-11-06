static char overlayBase[MAX_PATH];
static char translationFolder[64] = "translation";

static void LoadOverlayConfig(void) {
    if (!overlayBase[0]) return;
    char iniPath[MAX_PATH];
    snprintf(iniPath, sizeof(iniPath), "%sfontconf.ini", overlayBase);
    char buf[64] = {0};
    DWORD ret = GetPrivateProfileStringA("Translation", "Directory", "translation", buf, sizeof(buf), iniPath);
    if (ret > 0) {
        // Strip trailing slash/backslash if present
        while (ret > 0 && (buf[ret - 1] == '\\' || buf[ret - 1] == '/')) {
            buf[--ret] = '\0';
        }
        if (ret > 0) {
            strncpy(translationFolder, buf, sizeof(translationFolder) - 1);
            translationFolder[sizeof(translationFolder) - 1] = '\0';
        }
    }
}

static BOOL OverlayPath(LPCSTR name, char *out) {
    char full[MAX_PATH]; DWORD saved = GetLastError(); BOOL ok = FALSE;
    if (name && overlayBase[0]) {
        DWORD n = GetFullPathNameA(name, MAX_PATH, full, NULL);
        size_t base = strlen(overlayBase);
        if (n && n < MAX_PATH && !_strnicmp(full, overlayBase, base)) {
            const char *rel = full + base;
            if ((!_strnicmp(rel, "rld\\", 4) || !_strnicmp(rel, "res\\", 4)) &&
                base + strlen(translationFolder) + 2 + strlen(rel) < MAX_PATH) {
                strcpy(out, overlayBase);
                strcat(out, translationFolder);
                strcat(out, "\\");
                strcat(out, rel);
                DWORD a = GetFileAttributesA(out);
                ok = a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY);
            }
        }
    }
    SetLastError(saved); return ok;
}
static HANDLE WINAPI OverlayOpen(LPCSTR n, DWORD a, DWORD s, LPSECURITY_ATTRIBUTES p,
    DWORD d, DWORD f, HANDLE t) {
    char path[MAX_PATH];
    if (d == OPEN_EXISTING && !(a & ~(GENERIC_READ | FILE_READ_DATA | FILE_READ_EA |
        FILE_READ_ATTRIBUTES | READ_CONTROL | SYNCHRONIZE)) &&
        !(f & FILE_FLAG_DELETE_ON_CLOSE) && OverlayPath(n, path)) {
        DWORD saved = GetLastError();
        HANDLE h = CreateFileA(path, a, s, p, d, f, t);
        if (h != INVALID_HANDLE_VALUE) return h;
        SetLastError(saved);
    }
    return CreateFileA(n, a, s, p, d, f, t);
}
static DWORD WINAPI OverlayAttributes(LPCSTR n) {
    char path[MAX_PATH];
    return GetFileAttributesA(OverlayPath(n, path) ? path : n);
}
static void InstallFileOverlay(void) {
    const char *names[] = {NULL, "resident.dll", "sc00.dll"};
    DWORD saved = GetLastError();
    for (unsigned i=0; i<3; ++i) {
        HMODULE m = GetModuleHandleA(names[i]);
        if (!m) continue;
        HookIAT(m, "KERNEL32.dll", "CreateFileA", (void*)OverlayOpen);
        HookIAT(m, "KERNEL32.dll", "GetFileAttributesA", (void*)OverlayAttributes);
    }
    SetLastError(saved);
}
static void InitFileOverlay(void) {
    DWORD n = GetModuleFileNameA(NULL, overlayBase, MAX_PATH);
    if (!n || n >= MAX_PATH) { overlayBase[0]=0; return; }
    char *end = strrchr(overlayBase, '\\');
    if (!end) { overlayBase[0]=0; return; }
    end[1]=0;
    LoadOverlayConfig();
    InstallFileOverlay();
}
