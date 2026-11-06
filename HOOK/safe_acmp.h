#include <shellapi.h>
#include <aclapi.h>

/* Only the verified ExHIBIT acmp call site is intercepted. */
static DWORD GrantSaveAccess(char *path, PSID sid) {
    PACL oldAcl=NULL, merged=NULL; PSECURITY_DESCRIPTOR sd=NULL;
    DWORD attrs=GetFileAttributesA(path);
    if (attrs==INVALID_FILE_ATTRIBUTES) return GetLastError();
    if (attrs & FILE_ATTRIBUTE_REPARSE_POINT) return ERROR_NOT_SUPPORTED;
    DWORD err=GetNamedSecurityInfoA(path,SE_FILE_OBJECT,DACL_SECURITY_INFORMATION,
                                   NULL,NULL,&oldAcl,NULL,&sd);
    if (err) return err;
    /* A NULL DACL already allows access; do not restrict it. */
    if (oldAcl) {
        EXPLICIT_ACCESSA ea; ZeroMemory(&ea,sizeof(ea));
        ea.grfAccessPermissions=FILE_GENERIC_READ|FILE_GENERIC_WRITE|FILE_GENERIC_EXECUTE|DELETE;
        ea.grfAccessMode=GRANT_ACCESS;
        ea.grfInheritance=(attrs & FILE_ATTRIBUTE_DIRECTORY) ? SUB_CONTAINERS_AND_OBJECTS_INHERIT : NO_INHERITANCE;
        ea.Trustee.TrusteeForm=TRUSTEE_IS_SID;
        ea.Trustee.TrusteeType=TRUSTEE_IS_USER;
        ea.Trustee.ptstrName=(LPSTR)sid;
        err=SetEntriesInAclA(1,&ea,oldAcl,&merged);
        if (!err) err=SetNamedSecurityInfoA(path,SE_FILE_OBJECT,DACL_SECURITY_INFORMATION,
                                           NULL,NULL,merged,NULL);
        if (merged) LocalFree(merged);
    }
    LocalFree(sd);
    if (err || !(attrs & FILE_ATTRIBUTE_DIRECTORY)) return err;
    char pattern[MAX_PATH]; WIN32_FIND_DATAA data;
    if (strlen(path)+3>=MAX_PATH) return ERROR_FILENAME_EXCED_RANGE;
    snprintf(pattern,sizeof(pattern),"%s\\*",path);
    HANDLE search=FindFirstFileA(pattern,&data);
    if (search==INVALID_HANDLE_VALUE) {
        err=GetLastError(); return err==ERROR_FILE_NOT_FOUND ? ERROR_SUCCESS : err;
    }
    do {
        if (!strcmp(data.cFileName,".") || !strcmp(data.cFileName,"..")) continue;
        if (data.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) continue;
        char child[MAX_PATH];
        if (strlen(path)+strlen(data.cFileName)+2>MAX_PATH) {err=ERROR_FILENAME_EXCED_RANGE;break;}
        snprintf(child,sizeof(child),"%s\\%s",path,data.cFileName);
        err=GrantSaveAccess(child,sid);
        if (err) break;
    } while (FindNextFileA(search,&data));
    if (!err && GetLastError()!=ERROR_NO_MORE_FILES) err=GetLastError();
    FindClose(search); return err;
}

static BOOL WINAPI SafeAcmpExecute(SHELLEXECUTEINFOA *info) {
    char expected[MAX_PATH], actual[MAX_PATH] = {0};
    if (!info || info->cbSize!=sizeof(*info) || !info->lpFile || !overlayBase[0])
        return ShellExecuteExA(info);
    snprintf(expected,sizeof(expected),"%sacmp.exe",overlayBase);
    DWORD n=GetFullPathNameA(info->lpFile,MAX_PATH,actual,NULL);
    if (!n || n>=MAX_PATH || _stricmp(actual,expected)) return ShellExecuteExA(info);
    /* The original executable passes the userdata directory as its parameter.
       Accept only that exact path, optionally enclosed in quotes. */
    char arg[MAX_PATH]; const char *p=info->lpParameters;
    if (!p || strlen(p)>=sizeof(arg)) return ShellExecuteExA(info);
    strcpy(arg,p); size_t len=strlen(arg);
    if (len>=2 && arg[0]=='"' && arg[len-1]=='"') {arg[len-1]=0;memmove(arg,arg+1,len-1);}
    n=GetFullPathNameA(arg,MAX_PATH,actual,NULL);
    snprintf(expected,sizeof(expected),"%suserdata",overlayBase);
    len=strlen(actual); if (n && n<MAX_PATH && len && actual[len-1]=='\\') actual[len-1]=0;
    if (!n || n>=MAX_PATH || _stricmp(actual,expected)) return ShellExecuteExA(info);
    HANDLE token=NULL; DWORD size=0,err=ERROR_SUCCESS;
    if (!OpenProcessToken(GetCurrentProcess(),TOKEN_QUERY,&token)) {err=GetLastError();goto failed;}
    GetTokenInformation(token,TokenUser,NULL,0,&size);
    TOKEN_USER *user=(TOKEN_USER*)LocalAlloc(LPTR,size);
    if (!user) {CloseHandle(token);err=ERROR_NOT_ENOUGH_MEMORY;goto failed;}
    if (!GetTokenInformation(token,TokenUser,user,size,&size)) err=GetLastError();
    else err=GrantSaveAccess(actual,user->User.Sid);
    LocalFree(user);CloseHandle(token);
    if (err) goto failed;
    /* This game only waits on hProcess; a signaled event satisfies that contract. */
    info->hProcess=NULL;
    if (info->fMask & SEE_MASK_NOCLOSEPROCESS) {
        info->hProcess=CreateEventA(NULL,TRUE,TRUE,NULL);
        if (!info->hProcess) {err=GetLastError();goto failed;}
    }
    info->hInstApp=(HINSTANCE)33;
    DbgLog("[ClearHook] acmp replaced: userdata access granted successfully\n");
    return TRUE;
failed:
    DbgLog("[ClearHook] acmp replacement failed: %lu\n",err);
    info->hInstApp=(HINSTANCE)SE_ERR_ACCESSDENIED; info->hProcess=NULL;
    SetLastError(err);return FALSE;
}
