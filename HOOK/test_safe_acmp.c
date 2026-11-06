#include <windows.h>
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
static char overlayBase[MAX_PATH];
static void DbgLog(const char *f,...) {}
#include "safe_acmp.h"
int main(void) {
 char temp[MAX_PATH],root[MAX_PATH],dir[MAX_PATH],file[MAX_PATH];
 GetTempPathA(MAX_PATH,temp); GetTempFileNameA(temp,"acl",0,root); DeleteFileA(root);
 if(!CreateDirectoryA(root,NULL)) return 1;
 snprintf(overlayBase,MAX_PATH,"%s\\",root);
 snprintf(dir,MAX_PATH,"%s\\userdata",root);CreateDirectoryA(dir,NULL);
 snprintf(file,MAX_PATH,"%s\\udb",dir);
 HANDLE h=CreateFileA(file,GENERIC_WRITE,0,NULL,CREATE_NEW,0,NULL); if(h==INVALID_HANDLE_VALUE)return 2;CloseHandle(h);
 ACL acl;InitializeAcl(&acl,sizeof(acl),ACL_REVISION);
 if(SetNamedSecurityInfoA(file,SE_FILE_OBJECT,DACL_SECURITY_INFORMATION|PROTECTED_DACL_SECURITY_INFORMATION,NULL,NULL,&acl,NULL))return 3;
 SHELLEXECUTEINFOA info;ZeroMemory(&info,sizeof(info));info.cbSize=sizeof(info);info.fMask=SEE_MASK_NOCLOSEPROCESS;
 char helper[MAX_PATH];snprintf(helper,MAX_PATH,"%sacmp.exe",overlayBase);info.lpFile=helper;info.lpParameters=dir;
 if(!SafeAcmpExecute(&info)) {printf("hook failed %lu\n",GetLastError());return 4;}
 if(WaitForSingleObject(info.hProcess,0)!=WAIT_OBJECT_0)return 5;CloseHandle(info.hProcess);
 h=CreateFileA(file,GENERIC_READ|GENERIC_WRITE,0,NULL,OPEN_EXISTING,0,NULL);
 if(h==INVALID_HANDLE_VALUE)return 6;CloseHandle(h);
 DeleteFileA(file);RemoveDirectoryA(dir);RemoveDirectoryA(root);
 puts("PASS: empty protected ACL repaired; read/write works; wait handle signaled");return 0;
}
