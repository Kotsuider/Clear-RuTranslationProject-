#include <windows.h>
#include <stdio.h>

static void DbgLog(const char* fmt, ...) {
    char buf[1024];
    va_list args;
    va_start(args, fmt);
    vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);
    OutputDebugStringA(buf);

    FILE* fp = fopen("clear_hook.log", "a");
    if (fp) {
        fputs(buf, fp);
        fclose(fp);
    }
}

// Real version.dll handle & functions
static HMODULE hRealVersion = NULL;
typedef BOOL (WINAPI *PFN_GetFileVersionInfoA)(LPCSTR, DWORD, DWORD, LPVOID);
typedef BOOL (WINAPI *PFN_GetFileVersionInfoW)(LPCWSTR, DWORD, DWORD, LPVOID);
typedef DWORD (WINAPI *PFN_GetFileVersionInfoSizeA)(LPCSTR, LPDWORD);
typedef DWORD (WINAPI *PFN_GetFileVersionInfoSizeW)(LPCWSTR, LPDWORD);
typedef BOOL (WINAPI *PFN_VerQueryValueA)(LPCVOID, LPCSTR, LPVOID*, PUINT);
typedef BOOL (WINAPI *PFN_VerQueryValueW)(LPCVOID, LPCWSTR, LPVOID*, PUINT);

static PFN_GetFileVersionInfoA pfnGetFileVersionInfoA = NULL;
static PFN_GetFileVersionInfoW pfnGetFileVersionInfoW = NULL;
static PFN_GetFileVersionInfoSizeA pfnGetFileVersionInfoSizeA = NULL;
static PFN_GetFileVersionInfoSizeW pfnGetFileVersionInfoSizeW = NULL;
static PFN_VerQueryValueA pfnVerQueryValueA = NULL;
static PFN_VerQueryValueW pfnVerQueryValueW = NULL;

BOOL WINAPI RealGetFileVersionInfoA(LPCSTR lptstrFilename, DWORD dwHandle, DWORD dwLen, LPVOID lpData) {
    if (pfnGetFileVersionInfoA) return pfnGetFileVersionInfoA(lptstrFilename, dwHandle, dwLen, lpData);
    return FALSE;
}

BOOL WINAPI RealGetFileVersionInfoW(LPCWSTR lptstrFilename, DWORD dwHandle, DWORD dwLen, LPVOID lpData) {
    if (pfnGetFileVersionInfoW) return pfnGetFileVersionInfoW(lptstrFilename, dwHandle, dwLen, lpData);
    return FALSE;
}

DWORD WINAPI RealGetFileVersionInfoSizeA(LPCSTR lptstrFilename, LPDWORD lpdwHandle) {
    if (pfnGetFileVersionInfoSizeA) return pfnGetFileVersionInfoSizeA(lptstrFilename, lpdwHandle);
    return 0;
}

DWORD WINAPI RealGetFileVersionInfoSizeW(LPCWSTR lptstrFilename, LPDWORD lpdwHandle) {
    if (pfnGetFileVersionInfoSizeW) return pfnGetFileVersionInfoSizeW(lptstrFilename, lpdwHandle);
    return 0;
}

BOOL WINAPI RealVerQueryValueA(LPCVOID pBlock, LPCSTR lpSubBlock, LPVOID *lplpBuffer, PUINT puLen) {
    if (pfnVerQueryValueA) return pfnVerQueryValueA(pBlock, lpSubBlock, lplpBuffer, puLen);
    return FALSE;
}

BOOL WINAPI RealVerQueryValueW(LPCVOID pBlock, LPCWSTR lpSubBlock, LPVOID *lplpBuffer, PUINT puLen) {
    if (pfnVerQueryValueW) return pfnVerQueryValueW(pBlock, lpSubBlock, lplpBuffer, puLen);
    return FALSE;
}

static char g_FontNameA[LF_FACESIZE] = "CTNekokoi";
static WCHAR g_FontNameW[LF_FACESIZE] = L"CTNekokoi";

typedef HFONT (WINAPI *PFN_CreateFontIndirectA)(const LOGFONTA*);
typedef HFONT (WINAPI *PFN_CreateFontIndirectW)(const LOGFONTW*);

static PFN_CreateFontIndirectA Real_CreateFontIndirectA = NULL;
static PFN_CreateFontIndirectW Real_CreateFontIndirectW = NULL;

static HFONT WINAPI Hook_CreateFontIndirectA(const LOGFONTA* lplf) {
    if (!lplf) return Real_CreateFontIndirectA(lplf);

    DbgLog("[ClearHook] CreateFontIndirectA: Face='%s', Charset=%u, Height=%d, Width=%d, Weight=%d\n",
           lplf->lfFaceName, (unsigned char)lplf->lfCharSet, lplf->lfHeight, lplf->lfWidth, lplf->lfWeight);

    // If font is System or empty, do not touch
    if (lplf->lfFaceName[0] == '\0' || strstr(lplf->lfFaceName, "System") != NULL) {
        return Real_CreateFontIndirectA(lplf);
    }

    LOGFONTA lf = *lplf;
    lstrcpynA(lf.lfFaceName, g_FontNameA, LF_FACESIZE);
    lf.lfCharSet = lplf->lfCharSet;
    HFONT hRes = Real_CreateFontIndirectA(&lf);
    DbgLog("[ClearHook] -> Overridden to CTNekokoi (charset=%u), HFONT=%p\n", (unsigned char)lf.lfCharSet, hRes);
    return hRes;
}

static HFONT WINAPI Hook_CreateFontIndirectW(const LOGFONTW* lplf) {
    if (!lplf) return Real_CreateFontIndirectW(lplf);

    if (lplf->lfFaceName[0] == L'\0' || wcsstr(lplf->lfFaceName, L"System") != NULL) {
        return Real_CreateFontIndirectW(lplf);
    }

    LOGFONTW lf = *lplf;
    lstrcpynW(lf.lfFaceName, g_FontNameW, LF_FACESIZE);
    lf.lfCharSet = lplf->lfCharSet;
    return Real_CreateFontIndirectW(&lf);
}

// Hook CharNextA to properly advance 2 bytes for Shift-JIS lead bytes on non-Japanese systems
static LPSTR WINAPI Hook_CharNextA(LPCSTR lpCurrentChar) {
    if (!lpCurrentChar || *lpCurrentChar == '\0') {
        return (LPSTR)lpCurrentChar;
    }
    unsigned char b = (unsigned char)*lpCurrentChar;
    if ((b >= 0x81 && b <= 0x9F) || (b >= 0xE0 && b <= 0xFC)) {
        if (*(lpCurrentChar + 1) != '\0') {
            return (LPSTR)(lpCurrentChar + 2);
        }
    }
    return (LPSTR)(lpCurrentChar + 1);
}

// Character substitution mapping:
// source_characters: "><+%=#^@"
// target_characters: "ÓÕ¹²×É«»"
// > -> Ó (U+00D3)
// < -> Õ (U+00D5)
// + -> ¹ (U+00B9)
// % -> ² (U+00B2)
// = -> × (U+00D7)
// # -> É (U+00C9)
// ^ -> « (U+00AB)
// @ -> » (U+00BB)
static UINT RemapCharacterToUnicode(UINT ch) {
    switch (ch) {
        case '>': return 0x00D3; // Ó
        case '<': return 0x00D5; // Õ
        case '+': return 0x00B9; // ¹
        case '%': return 0x00B2; // ²
        case '=': return 0x00D7; // ×
        case '#': return 0x00C9; // É
        case '^': return 0x00AB; // «
        case '@': return 0x00BB; // »
        default:  return ch;
    }
}

static WCHAR RemapCharW(char c) {
    switch (c) {
        case '>': return 0x00D3;
        case '<': return 0x00D5;
        case '+': return 0x00B9;
        case '%': return 0x00B2;
        case '=': return 0x00D7;
        case '#': return 0x00C9;
        case '^': return 0x00AB;
        case '@': return 0x00BB;
        default:  return 0;
    }
}

// Hook GetGlyphOutlineA
typedef DWORD (WINAPI *PFN_GetGlyphOutlineA)(HDC, UINT, UINT, LPGLYPHMETRICS, DWORD, LPVOID, const MAT2*);
static PFN_GetGlyphOutlineA Real_GetGlyphOutlineA = NULL;

static DWORD WINAPI Hook_GetGlyphOutlineA(HDC hdc, UINT uChar, UINT fuFormat,
                                         LPGLYPHMETRICS lpgm, DWORD cjBuffer,
                                         LPVOID pvBuffer, const MAT2 *lpmat2) {
    UINT remapped = RemapCharacterToUnicode(uChar);
    if (remapped != uChar) {
        // Fetch outline using GetGlyphOutlineW for exact Unicode glyph metrics and bitmap
        return GetGlyphOutlineW(hdc, remapped, fuFormat, lpgm, cjBuffer, pvBuffer, lpmat2);
    }
    if (Real_GetGlyphOutlineA) {
        return Real_GetGlyphOutlineA(hdc, uChar, fuFormat, lpgm, cjBuffer, pvBuffer, lpmat2);
    }
    return GetGlyphOutlineA(hdc, uChar, fuFormat, lpgm, cjBuffer, pvBuffer, lpmat2);
}

// Hook GetTextExtentPoint32A
typedef BOOL (WINAPI *PFN_GetTextExtentPoint32A)(HDC, LPCSTR, int, LPSIZE);
static PFN_GetTextExtentPoint32A Real_GetTextExtentPoint32A = NULL;

static BOOL WINAPI Hook_GetTextExtentPoint32A(HDC hdc, LPCSTR lpString, int c, LPSIZE lpSize) {
    if (!lpString || c <= 0) {
        if (Real_GetTextExtentPoint32A) return Real_GetTextExtentPoint32A(hdc, lpString, c, lpSize);
        return GetTextExtentPoint32A(hdc, lpString, c, lpSize);
    }

    // Convert lpString to wide string, replacing source characters with target Unicode characters
    WCHAR wbuf[1024];
    int wlen = 0;
    for (int i = 0; i < c && wlen < 1023; ) {
        unsigned char b = (unsigned char)lpString[i];
        if ((b >= 0x81 && b <= 0x9F) || (b >= 0xE0 && b <= 0xFC)) {
            // Shift-JIS lead byte
            if (i + 1 < c) {
                MultiByteToWideChar(932, 0, &lpString[i], 2, &wbuf[wlen++], 1);
                i += 2;
                continue;
            }
        }
        WCHAR repl = RemapCharW(lpString[i]);
        if (repl) {
            wbuf[wlen++] = repl;
        } else {
            // Russian CP1251 or ASCII
            MultiByteToWideChar(1251, 0, &lpString[i], 1, &wbuf[wlen++], 1);
        }
        i++;
    }
    wbuf[wlen] = L'\0';

    return GetTextExtentPoint32W(hdc, wbuf, wlen, lpSize);
}

// Hook GetTextExtentExPointA
typedef BOOL (WINAPI *PFN_GetTextExtentExPointA)(HDC, LPCSTR, int, int, LPINT, LPINT, LPSIZE);
static PFN_GetTextExtentExPointA Real_GetTextExtentExPointA = NULL;

static BOOL WINAPI Hook_GetTextExtentExPointA(HDC hdc, LPCSTR lpszStr, int cchString,
                                             int nMaxExtent, LPINT lpnFit, LPINT alpDx, LPSIZE lpSize) {
    if (!lpszStr || cchString <= 0) {
        if (Real_GetTextExtentExPointA) return Real_GetTextExtentExPointA(hdc, lpszStr, cchString, nMaxExtent, lpnFit, alpDx, lpSize);
        return GetTextExtentExPointA(hdc, lpszStr, cchString, nMaxExtent, lpnFit, alpDx, lpSize);
    }

    WCHAR wbuf[1024];
    int wlen = 0;
    for (int i = 0; i < cchString && wlen < 1023; ) {
        unsigned char b = (unsigned char)lpszStr[i];
        if ((b >= 0x81 && b <= 0x9F) || (b >= 0xE0 && b <= 0xFC)) {
            if (i + 1 < cchString) {
                MultiByteToWideChar(932, 0, &lpszStr[i], 2, &wbuf[wlen++], 1);
                i += 2;
                continue;
            }
        }
        WCHAR repl = RemapCharW(lpszStr[i]);
        if (repl) {
            wbuf[wlen++] = repl;
        } else {
            MultiByteToWideChar(1251, 0, &lpszStr[i], 1, &wbuf[wlen++], 1);
        }
        i++;
    }
    wbuf[wlen] = L'\0';

    return GetTextExtentExPointW(hdc, wbuf, wlen, nMaxExtent, lpnFit, alpDx, lpSize);
}

// Hook TextOutA
typedef BOOL (WINAPI *PFN_TextOutA)(HDC, int, int, LPCSTR, int);
static PFN_TextOutA Real_TextOutA = NULL;

static BOOL WINAPI Hook_TextOutA(HDC hdc, int x, int y, LPCSTR lpString, int c) {
    if (!lpString || c <= 0) {
        if (Real_TextOutA) return Real_TextOutA(hdc, x, y, lpString, c);
        return TextOutA(hdc, x, y, lpString, c);
    }

    WCHAR wbuf[1024];
    int wlen = 0;
    for (int i = 0; i < c && wlen < 1023; ) {
        unsigned char b = (unsigned char)lpString[i];
        if ((b >= 0x81 && b <= 0x9F) || (b >= 0xE0 && b <= 0xFC)) {
            if (i + 1 < c) {
                MultiByteToWideChar(932, 0, &lpString[i], 2, &wbuf[wlen++], 1);
                i += 2;
                continue;
            }
        }
        WCHAR repl = RemapCharW(lpString[i]);
        if (repl) {
            wbuf[wlen++] = repl;
        } else {
            MultiByteToWideChar(1251, 0, &lpString[i], 1, &wbuf[wlen++], 1);
        }
        i++;
    }
    wbuf[wlen] = L'\0';

    return TextOutW(hdc, x, y, wbuf, wlen);
}

static void HookIAT(HMODULE hMod, const char* targetDll, const char* funcName, void* newFunc) {
    if (!hMod) return;

    BYTE* pBase = (BYTE*)hMod;
    IMAGE_DOS_HEADER* pDos = (IMAGE_DOS_HEADER*)pBase;
    if (pDos->e_magic != IMAGE_DOS_SIGNATURE) return;

    IMAGE_NT_HEADERS* pNt = (IMAGE_NT_HEADERS*)(pBase + pDos->e_lfanew);
    if (pNt->Signature != IMAGE_NT_SIGNATURE) return;

    IMAGE_DATA_DIRECTORY* pDataDir = &pNt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (!pDataDir->VirtualAddress || !pDataDir->Size) return;

    IMAGE_IMPORT_DESCRIPTOR* pImport = (IMAGE_IMPORT_DESCRIPTOR*)(pBase + pDataDir->VirtualAddress);

    for (; pImport->Name; pImport++) {
        char* modName = (char*)(pBase + pImport->Name);
        if (_stricmp(modName, targetDll) == 0) {
            IMAGE_THUNK_DATA* pThunk = (IMAGE_THUNK_DATA*)(pBase + pImport->FirstThunk);
            IMAGE_THUNK_DATA* pOrigThunk = pImport->OriginalFirstThunk ?
                (IMAGE_THUNK_DATA*)(pBase + pImport->OriginalFirstThunk) : pThunk;

            for (; pOrigThunk->u1.AddressOfData; pOrigThunk++, pThunk++) {
                if (!(pOrigThunk->u1.Ordinal & IMAGE_ORDINAL_FLAG)) {
                    IMAGE_IMPORT_BY_NAME* pName = (IMAGE_IMPORT_BY_NAME*)(pBase + pOrigThunk->u1.AddressOfData);
                    if (strcmp((char*)pName->Name, funcName) == 0) {
                        DWORD oldProtect;
                        VirtualProtect(&pThunk->u1.Function, sizeof(void*), PAGE_EXECUTE_READWRITE, &oldProtect);
                        pThunk->u1.Function = (DWORD)newFunc;
                        VirtualProtect(&pThunk->u1.Function, sizeof(void*), oldProtect, &oldProtect);
                        DbgLog("[ClearHook] HookIAT: Successfully patched %s in module %p\n", funcName, hMod);
                        return;
                    }
                }
            }
        }
    }
}

static void HookCharNextEverywhere() {
    HMODULE hResident = GetModuleHandleA("resident.dll");
    if (hResident) {
        HookIAT(hResident, "USER32.dll", "CharNextA", (void*)Hook_CharNextA);
    }
    HMODULE hExe = GetModuleHandleA(NULL);
    if (hExe) {
        HookIAT(hExe, "USER32.dll", "CharNextA", (void*)Hook_CharNextA);
    }
}

// Fixed version of resident.dll+0x33330 that clamps coordinates to buffer boundaries
// Original: (Height - Y - 1) * pitch + X + buf_start
// Calling convention: thiscall (ecx = surface object), stack: [esp+4] = X, [esp+8] = Y
__declspec(naked) void PatchedRowOffset33330() {
    __asm__(
        ".intel_syntax noprefix\n"
        "mov eax, [ecx + 8]\n"          // eax = surface desc
        "mov edx, [eax + 8]\n"          // edx = Height
        "test edx, edx\n"
        "jge 1f\n"
        "neg edx\n"
        "1:\n"
        // Clamp Y in [esp+8] to [0, Height - 1]
        "mov edx, [esp + 8]\n"          // edx = Y
        "test edx, edx\n"
        "jge 2f\n"
        "xor edx, edx\n"                // if (Y < 0) Y = 0
        "mov [esp + 8], edx\n"
        "2:\n"
        "mov eax, [ecx + 8]\n"
        "mov edx, [eax + 8]\n"
        "test edx, edx\n"
        "jge 3f\n"
        "neg edx\n"
        "3:\n"
        "dec edx\n"                     // edx = Height - 1
        "cmp [esp + 8], edx\n"
        "jle 4f\n"
        "mov [esp + 8], edx\n"          // if (Y > Height - 1) Y = Height - 1
        "4:\n"
        // Clamp X in [esp+4] to [0, Width - 1]
        "mov edx, [esp + 4]\n"          // edx = X
        "test edx, edx\n"
        "jge 5f\n"
        "xor edx, edx\n"                // if (X < 0) X = 0
        "mov [esp + 4], edx\n"
        "5:\n"
        "mov eax, [ecx + 8]\n"
        "mov edx, [eax + 4]\n"          // edx = Width
        "dec edx\n"                     // edx = Width - 1
        "cmp [esp + 4], edx\n"
        "jle 6f\n"
        "mov [esp + 4], edx\n"          // if (X > Width - 1) X = Width - 1
        "6:\n"
        // Original computation with clamped X and Y
        "mov eax, [ecx + 8]\n"
        "mov edx, [eax + 8]\n"
        "test edx, edx\n"
        "jge 7f\n"
        "neg edx\n"
        "7:\n"
        "mov eax, [eax + 4]\n"          // eax = Width
        "sub edx, [esp + 8]\n"          // edx = Height - Y
        "add eax, 3\n"
        "and eax, 0xFFFFFFFC\n"         // eax = pitch = (Width + 3) & ~3
        "dec edx\n"                     // edx = Height - Y - 1
        "imul eax, edx\n"               // eax = row_offset
        "add eax, [ecx + 0xC]\n"        // eax = buf_start + row_offset
        "add eax, [esp + 4]\n"          // eax = buf_start + row_offset + X
        "ret 8\n"
        ".att_syntax prefix\n"
    );
}

// Safe pixel write hook for resident.dll+0xAA98D..0xAA995
// Original at 0xAA98D (8 bytes):
//   0xAA98D: add %cl, %bl
//   0xAA98F: sub $1, %bl
//   0xAA992: mov %bl, (%esi, %eax, 1)
// We check if the destination address (%esi + %eax) is valid/writable before writing %bl.
__declspec(naked) void SafeGlyphWrite_AA992() {
    __asm__(
        ".intel_syntax noprefix\n"
        "add bl, cl\n"                  // original instruction: add %cl, %bl
        "sub bl, 1\n"                   // original instruction: sub $1, %bl
        "push edx\n"                    // save edx
        "lea edx, [esi + eax]\n"        // edx = target write address
        // Verify target address is within user-space valid memory [0x10000, 0x7FFE0000]
        "cmp edx, 0x00010000\n"
        "jb 1f\n"
        "cmp edx, 0x7FFE0000\n"
        "jae 1f\n"
        // Also verify memory page is accessible / not a guard page
        "push eax\n"
        "push ecx\n"
        "push edx\n"                    // arg to IsBadWritePtr: lp, ucb
        "push 1\n"
        "push edx\n"
        "call _IsBadWritePtr@8\n"
        "test eax, eax\n"
        "pop edx\n"
        "pop ecx\n"
        "pop eax\n"
        "jnz 1f\n"                      // if IsBadWritePtr returns non-zero, skip write!
        "mov [edx], bl\n"               // safely write pixel!
        "1:\n"
        "pop edx\n"                     // restore edx
        "ret\n"                         // return to resident.dll+0xAA995
        ".att_syntax prefix\n"
    );
}

static void PatchResidentDll() {
    HMODULE hResident = GetModuleHandleA("resident.dll");
    if (!hResident) {
        DbgLog("[ClearHook] PatchResidentDll: resident.dll not loaded yet\n");
        return;
    }

    BYTE* pBase = (BYTE*)hResident;

    // 1. Signature check at RVA 0x33330: 8b 41 08 8b 50 08 85 d2 7d 02
    static const BYTE sig33330[10] = { 0x8B, 0x41, 0x08, 0x8B, 0x50, 0x08, 0x85, 0xD2, 0x7D, 0x02 };
    BYTE* target33330 = pBase + 0x33330;
    if (memcmp(target33330, sig33330, sizeof(sig33330)) == 0) {
        DWORD oldProtect;
        VirtualProtect(target33330, 5, PAGE_EXECUTE_READWRITE, &oldProtect);
        target33330[0] = 0xE9;
        *(DWORD*)(target33330 + 1) = (DWORD)PatchedRowOffset33330 - (DWORD)(target33330 + 5);
        VirtualProtect(target33330, 5, oldProtect, &oldProtect);
        DbgLog("[ClearHook] Successfully patched resident.dll+0x33330 (RowOffset clamp hook)!\n");
    } else {
        DbgLog("[ClearHook] Signature mismatch at resident.dll+0x33330!\n");
    }

    // 2. Hook pixel write at RVA 0xAA98D: 02 d9 80 eb 01 88 1c 06 (8 bytes)
    static const BYTE sigAA98D[8] = { 0x02, 0xD9, 0x80, 0xEB, 0x01, 0x88, 0x1C, 0x06 };
    BYTE* targetAA98D = pBase + 0xAA98D;
    if (memcmp(targetAA98D, sigAA98D, sizeof(sigAA98D)) == 0) {
        DWORD oldProtect;
        VirtualProtect(targetAA98D, 8, PAGE_EXECUTE_READWRITE, &oldProtect);
        // Call SafeGlyphWrite_AA992 (E8 rel32), followed by 3 NOPs to fill 8 bytes
        targetAA98D[0] = 0xE8;
        *(DWORD*)(targetAA98D + 1) = (DWORD)SafeGlyphWrite_AA992 - (DWORD)(targetAA98D + 5);
        targetAA98D[5] = 0x90;
        targetAA98D[6] = 0x90;
        targetAA98D[7] = 0x90;
        VirtualProtect(targetAA98D, 8, oldProtect, &oldProtect);
        DbgLog("[ClearHook] Successfully patched resident.dll+0xAA98D (SafeGlyphWrite_AA992 hook)!\n");
    } else {
        DbgLog("[ClearHook] Signature mismatch at resident.dll+0xAA98D!\n");
    }

    // Also Hook CharNextA in resident.dll IAT
    HookIAT(hResident, "USER32.dll", "CharNextA", (void*)Hook_CharNextA);

    // Hook GDI text functions in resident.dll IAT for character substitution
    HookIAT(hResident, "GDI32.dll", "GetGlyphOutlineA", (void*)Hook_GetGlyphOutlineA);
    HookIAT(hResident, "GDI32.dll", "GetTextExtentPoint32A", (void*)Hook_GetTextExtentPoint32A);
    HookIAT(hResident, "GDI32.dll", "GetTextExtentExPointA", (void*)Hook_GetTextExtentExPointA);
    HookIAT(hResident, "GDI32.dll", "TextOutA", (void*)Hook_TextOutA);
}

static void InstallHook(void* target, void* hook, void** original, const char* name) {
    if (!target || !hook) return;

    DWORD oldProtect;
    BYTE* p = (BYTE*)target;
    BYTE* tramp = (BYTE*)VirtualAlloc(NULL, 32, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!tramp) return;
    memcpy(tramp, p, 5);
    tramp[5] = 0xE9;
    *(DWORD*)(tramp + 6) = (DWORD)(p + 5) - (DWORD)(tramp + 10);
    *original = tramp;

    VirtualProtect(p, 5, PAGE_EXECUTE_READWRITE, &oldProtect);
    p[0] = 0xE9;
    *(DWORD*)(p + 1) = (DWORD)hook - (DWORD)(p + 5);
    VirtualProtect(p, 5, oldProtect, &oldProtect);
    DbgLog("[ClearHook] Hook installed for %s\n", name);
}

// Hook LoadLibraryA to catch dynamic loading of resident.dll
typedef HMODULE (WINAPI *PFN_LoadLibraryA)(LPCSTR);
typedef HMODULE (WINAPI *PFN_LoadLibraryExA)(LPCSTR, HANDLE, DWORD);

static PFN_LoadLibraryA Real_LoadLibraryA = NULL;
static PFN_LoadLibraryExA Real_LoadLibraryExA = NULL;

static HMODULE WINAPI Hook_LoadLibraryA(LPCSTR lpLibFileName) {
    HMODULE hMod = Real_LoadLibraryA(lpLibFileName);
    if (hMod && lpLibFileName && strstr(lpLibFileName, "resident.dll") != NULL) {
        DbgLog("[ClearHook] Hook_LoadLibraryA caught resident.dll (%p) -> Patching...\n", hMod);
        PatchResidentDll();
    }
    return hMod;
}

static HMODULE WINAPI Hook_LoadLibraryExA(LPCSTR lpLibFileName, HANDLE hFile, DWORD dwFlags) {
    HMODULE hMod = Real_LoadLibraryExA(lpLibFileName, hFile, dwFlags);
    if (hMod && lpLibFileName && strstr(lpLibFileName, "resident.dll") != NULL) {
        DbgLog("[ClearHook] Hook_LoadLibraryExA caught resident.dll (%p) -> Patching...\n", hMod);
        PatchResidentDll();
    }
    return hMod;
}

static void LoadPrivateFont() {
    char exePath[MAX_PATH];
    char fontPath[MAX_PATH];

    if (GetModuleFileNameA(NULL, exePath, MAX_PATH)) {
        char* lastSlash = strrchr(exePath, '\\');
        if (lastSlash) {
            *lastSlash = '\0';
            snprintf(fontPath, sizeof(fontPath), "%s\\CTNekokoi.ttf", exePath);
        } else {
            snprintf(fontPath, sizeof(fontPath), ".\\CTNekokoi.ttf");
        }
    } else {
        snprintf(fontPath, sizeof(fontPath), ".\\CTNekokoi.ttf");
    }

    int res = AddFontResourceExA(fontPath, FR_PRIVATE, NULL);
    DbgLog("[ClearHook] AddFontResourceExA('%s'): added %d font(s)\n", fontPath, res);
}

static void InitHooks() {
    HMODULE hGdi = GetModuleHandleA("gdi32.dll");
    if (!hGdi) hGdi = LoadLibraryA("gdi32.dll");
    if (hGdi) {
        void* pCFIA = (void*)GetProcAddress(hGdi, "CreateFontIndirectA");
        if (pCFIA) InstallHook(pCFIA, (void*)Hook_CreateFontIndirectA, (void**)&Real_CreateFontIndirectA, "CreateFontIndirectA");

        void* pCFIW = (void*)GetProcAddress(hGdi, "CreateFontIndirectW");
        if (pCFIW) InstallHook(pCFIW, (void*)Hook_CreateFontIndirectW, (void**)&Real_CreateFontIndirectW, "CreateFontIndirectW");
    }

    HMODULE hKernel = GetModuleHandleA("kernel32.dll");
    if (hKernel) {
        void* pLLA = (void*)GetProcAddress(hKernel, "LoadLibraryA");
        if (pLLA) InstallHook(pLLA, (void*)Hook_LoadLibraryA, (void**)&Real_LoadLibraryA, "LoadLibraryA");

        void* pLLE = (void*)GetProcAddress(hKernel, "LoadLibraryExA");
        if (pLLE) InstallHook(pLLE, (void*)Hook_LoadLibraryExA, (void**)&Real_LoadLibraryExA, "LoadLibraryExA");
    }

    PatchResidentDll();
    HookCharNextEverywhere();

    HMODULE hExe = GetModuleHandleA(NULL);
    if (hExe) {
        HookIAT(hExe, "GDI32.dll", "GetGlyphOutlineA", (void*)Hook_GetGlyphOutlineA);
        HookIAT(hExe, "GDI32.dll", "GetTextExtentPoint32A", (void*)Hook_GetTextExtentPoint32A);
        HookIAT(hExe, "GDI32.dll", "GetTextExtentExPointA", (void*)Hook_GetTextExtentExPointA);
        HookIAT(hExe, "GDI32.dll", "TextOutA", (void*)Hook_TextOutA);
    }
}

static void LoadSystemVersionDll() {
    char sysDir[MAX_PATH];
    GetSystemDirectoryA(sysDir, MAX_PATH);
    strcat(sysDir, "\\version.dll");
    hRealVersion = LoadLibraryA(sysDir);
    if (hRealVersion) {
        pfnGetFileVersionInfoA = (PFN_GetFileVersionInfoA)GetProcAddress(hRealVersion, "GetFileVersionInfoA");
        pfnGetFileVersionInfoW = (PFN_GetFileVersionInfoW)GetProcAddress(hRealVersion, "GetFileVersionInfoW");
        pfnGetFileVersionInfoSizeA = (PFN_GetFileVersionInfoSizeA)GetProcAddress(hRealVersion, "GetFileVersionInfoSizeA");
        pfnGetFileVersionInfoSizeW = (PFN_GetFileVersionInfoSizeW)GetProcAddress(hRealVersion, "GetFileVersionInfoSizeW");
        pfnVerQueryValueA = (PFN_VerQueryValueA)GetProcAddress(hRealVersion, "VerQueryValueA");
        pfnVerQueryValueW = (PFN_VerQueryValueW)GetProcAddress(hRealVersion, "VerQueryValueW");
    }
}

BOOL WINAPI DllMain(HINSTANCE hinstDLL, DWORD fdwReason, LPVOID lpvReserved) {
    if (fdwReason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(hinstDLL);
        DbgLog("[ClearHook] === version.dll attached (PID=%u) ===\n", GetCurrentProcessId());
        LoadSystemVersionDll();
        LoadPrivateFont();
        InitHooks();
    }
    return TRUE;
}

