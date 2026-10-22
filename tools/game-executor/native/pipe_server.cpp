#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include "pipe_server.h"
#include <cstring>
#include <cwchar>
#include <new>

#pragma comment(lib, "advapi32.lib")

struct GE_PipeServer {
    GE_Executor* executor=nullptr;
    HANDLE pipe=INVALID_HANDLE_VALUE;
    HANDLE stop=nullptr;
    HANDLE io_event=nullptr;
    HANDLE thread=nullptr;
    uint8_t token[GE_PIPE_TOKEN_BYTES]{};
};

namespace {
bool stopping(const GE_PipeServer* s) {
    return WaitForSingleObject(s->stop,0)!=WAIT_TIMEOUT;
}
DWORD remaining(ULONGLONG deadline) {
    const ULONGLONG now=GetTickCount64();
    if(now>=deadline) return 0;
    const ULONGLONG delta=deadline-now;
    return static_cast<DWORD>(delta>MAXDWORD-1 ? MAXDWORD-1 : delta);
}
bool valid_name(const wchar_t* name) {
    if(!name) return false;
    wchar_t prefix[80]{};
    const int length=swprintf_s(prefix,L"\\\\.\\pipe\\Miliastra.GameExecutor.%lu.",GetCurrentProcessId());
    if(length<=0 || wcsncmp(name,prefix,static_cast<size_t>(length))!=0) return false;
    const wchar_t* nonce=name+length;
    size_t count=0;
    for(;count<=64 && nonce[count];++count) {
        const wchar_t c=nonce[count];
        if(!((c>=L'0' && c<=L'9') || (c>=L'a' && c<=L'f') || (c>=L'A' && c<=L'F'))) return false;
    }
    return count>=16 && count<=64;
}
bool logon_sid(BYTE (&sid)[SECURITY_MAX_SID_SIZE]) {
    HANDLE token=nullptr;
    if(!OpenThreadToken(GetCurrentThread(),TOKEN_QUERY,TRUE,&token)) {
        if(GetLastError()!=ERROR_NO_TOKEN || !OpenProcessToken(GetCurrentProcess(),TOKEN_QUERY,&token)) return false;
    }
    DWORD bytes=0;
    GetTokenInformation(token,TokenLogonSid,nullptr,0,&bytes);
    if(!bytes) { CloseHandle(token); return false; }
    auto* groups=static_cast<TOKEN_GROUPS*>(HeapAlloc(GetProcessHeap(),HEAP_ZERO_MEMORY,bytes));
    bool ok=false;
    if(groups && GetTokenInformation(token,TokenLogonSid,groups,bytes,&bytes) &&
        groups->GroupCount==1 && IsValidSid(groups->Groups[0].Sid) &&
        (groups->Groups[0].Attributes&SE_GROUP_LOGON_ID)==SE_GROUP_LOGON_ID &&
        GetLengthSid(groups->Groups[0].Sid)<=SECURITY_MAX_SID_SIZE) {
        ok=CopySid(SECURITY_MAX_SID_SIZE,sid,groups->Groups[0].Sid)!=FALSE;
    }
    if(groups) HeapFree(GetProcessHeap(),0,groups);
    CloseHandle(token);
    return ok;
}
void release(GE_PipeServer* s) {
    if(s->thread) CloseHandle(s->thread);
    if(s->pipe!=INVALID_HANDLE_VALUE) CloseHandle(s->pipe);
    if(s->io_event) CloseHandle(s->io_event);
    if(s->stop) CloseHandle(s->stop);
    SecureZeroMemory(s->token,sizeof(s->token));
    delete s;
}

/* OVERLAPPED remains live until cancellation has actually completed. In the
 * exceptional case of stalled kernel cancellation, only this worker waits;
 * public Stop returns GE_BUSY within its bound and retains all resources. */
bool finish_io(GE_PipeServer* s,OVERLAPPED& ov,ULONGLONG deadline,DWORD& count) {
    HANDLE events[2]{s->stop,s->io_event};
    const DWORD rc=WaitForMultipleObjects(2,events,FALSE,remaining(deadline));
    if(rc==WAIT_OBJECT_0+1 && !stopping(s)) {
        return GetOverlappedResult(s->pipe,&ov,&count,FALSE)!=FALSE;
    }
    CancelIoEx(s->pipe,&ov);
    DWORD ignored=0;
    GetOverlappedResult(s->pipe,&ov,&ignored,TRUE);
    return false;
}
bool transfer(GE_PipeServer* s,void* buffer,DWORD length,bool write,ULONGLONG deadline) {
    auto* bytes=static_cast<BYTE*>(buffer);
    DWORD completed=0;
    while(completed<length) {
        if(stopping(s) || !remaining(deadline)) return false;
        OVERLAPPED ov{};ov.hEvent=s->io_event;
        if(!ResetEvent(s->io_event)) return false;
        DWORD count=0;
        const BOOL immediate=write ? WriteFile(s->pipe,bytes+completed,length-completed,&count,&ov)
                                   : ReadFile(s->pipe,bytes+completed,length-completed,&count,&ov);
        if(!immediate) {
            if(GetLastError()!=ERROR_IO_PENDING || !finish_io(s,ov,deadline,count)) return false;
        }
        if(!count || count>length-completed) return false;
        completed+=count;
    }
    return !stopping(s);
}
bool connect(GE_PipeServer* s) {
    if(stopping(s)) return false;
    OVERLAPPED ov{};ov.hEvent=s->io_event;
    if(!ResetEvent(s->io_event)) return false;
    if(ConnectNamedPipe(s->pipe,&ov)) return true;
    const DWORD error=GetLastError();
    if(error==ERROR_PIPE_CONNECTED) return !stopping(s);
    if(error!=ERROR_IO_PENDING) return false;
    DWORD count=0;
    return finish_io(s,ov,GetTickCount64()+GE_PIPE_CONNECTION_TIMEOUT_MS,count);
}
bool authenticated(const uint8_t* expected,const uint8_t* received) {
    volatile unsigned difference=0;
    for(size_t i=0;i<GE_PIPE_TOKEN_BYTES;++i) difference=difference|static_cast<unsigned>(expected[i]^received[i]);
    return difference==0;
}
void respond(GE_PipeServer* s,int32_t code,const void* payload,uint32_t length,ULONGLONG deadline) {
    BYTE bytes[sizeof(GE_PipeResponseHeader)+sizeof(GE_Result)]{};
    if(length>sizeof(GE_Result)) return;
    const GE_PipeResponseHeader header{GE_PIPE_MAGIC,GE_PIPE_VERSION,code,length};
    std::memcpy(bytes,&header,sizeof(header));
    if(length) std::memcpy(bytes+sizeof(header),payload,length);
    if(!transfer(s,bytes,static_cast<DWORD>(sizeof(header)+length),true,deadline)) return;
    // The client closes after reading. Waiting avoids discarding a buffered
    // response at DisconnectNamedPipe, without an unbounded FlushFileBuffers.
    BYTE unexpected=0;
    transfer(s,&unexpected,1,false,deadline);
}
void serve(GE_PipeServer* s) {
    const ULONGLONG deadline=GetTickCount64()+GE_PIPE_CONNECTION_TIMEOUT_MS;
    GE_PipeRequestHeader header{};
    uint8_t token[GE_PIPE_TOKEN_BYTES]{};
    if(!transfer(s,&header,sizeof(header),false,deadline) ||
       !transfer(s,token,sizeof(token),false,deadline)) {
        SecureZeroMemory(token,sizeof(token));return;
    }
    const bool allowed=authenticated(s->token,token);
    SecureZeroMemory(token,sizeof(token));
    const bool shape=(header.operation==GE_PIPE_HELLO && header.payload_bytes==0) ||
        (header.operation==GE_PIPE_SUBMIT && header.payload_bytes==sizeof(GE_Request)) ||
        (header.operation==GE_PIPE_RESULT && header.payload_bytes==sizeof(uint64_t));
    if(!allowed || header.magic!=GE_PIPE_MAGIC || header.version!=GE_PIPE_VERSION || !shape) {
        respond(s,GE_INVALID,nullptr,0,deadline);return;
    }
    if(header.operation==GE_PIPE_HELLO) {
        const GE_PipeHello hello{GetCurrentProcessId(),GE_ApiVersion(),sizeof(GE_Request),sizeof(GE_Result)};
        respond(s,GE_OK,&hello,sizeof(hello),deadline);return;
    }
    GE_Result result{};
    int32_t code=GE_INVALID;
    if(header.operation==GE_PIPE_SUBMIT) {
        GE_Request request{};
        if(!transfer(s,&request,sizeof(request),false,deadline) || stopping(s)) return;
        code=GE_Submit(s->executor,&request,&result);
    } else {
        uint64_t id=0;
        if(!transfer(s,&id,sizeof(id),false,deadline) || stopping(s)) return;
        code=GE_GetResult(s->executor,id,&result);
    }
    respond(s,code,&result,sizeof(result),deadline);
}
DWORD WINAPI worker(void* context) {
    auto* s=static_cast<GE_PipeServer*>(context);
    while(!stopping(s)) {
        if(connect(s) && !stopping(s)) serve(s);
        DisconnectNamedPipe(s->pipe);
    }
    return 0;
}
}

extern "C" {
int32_t GE_CALL GE_PipeStart(GE_Executor* executor,const wchar_t* name,
    const uint8_t token[GE_PIPE_TOKEN_BYTES],GE_PipeServer** out) {
    if(!out) return GE_INVALID;
    *out=nullptr;
    if(!executor || !token || !valid_name(name)) return GE_INVALID;
    unsigned nonzero=0;
    for(size_t i=0;i<GE_PIPE_TOKEN_BYTES;++i) nonzero|=token[i];
    if(!nonzero) return GE_INVALID;
    BYTE sid[SECURITY_MAX_SID_SIZE]{};
    if(!logon_sid(sid)) return GE_UNAVAILABLE;
    alignas(ACL) BYTE acl_bytes[sizeof(ACL)+sizeof(ACCESS_ALLOWED_ACE)+SECURITY_MAX_SID_SIZE]{};
    auto* acl=reinterpret_cast<ACL*>(acl_bytes);
    SECURITY_DESCRIPTOR descriptor{};
    if(!InitializeAcl(acl,sizeof(acl_bytes),ACL_REVISION) ||
       !AddAccessAllowedAceEx(acl,ACL_REVISION,0,FILE_GENERIC_READ|FILE_GENERIC_WRITE,sid) ||
       !InitializeSecurityDescriptor(&descriptor,SECURITY_DESCRIPTOR_REVISION) ||
       !SetSecurityDescriptorDacl(&descriptor,TRUE,acl,FALSE) ||
       !SetSecurityDescriptorControl(&descriptor,SE_DACL_PROTECTED,SE_DACL_PROTECTED)) return GE_INTERNAL;
    SECURITY_ATTRIBUTES attributes{sizeof(SECURITY_ATTRIBUTES),&descriptor,FALSE};
    auto* s=new(std::nothrow) GE_PipeServer();
    if(!s) return GE_INTERNAL;
    s->executor=executor;std::memcpy(s->token,token,sizeof(s->token));
    s->stop=CreateEventW(nullptr,TRUE,FALSE,nullptr);
    s->io_event=CreateEventW(nullptr,TRUE,FALSE,nullptr);
    if(!s->stop || !s->io_event) { release(s);return GE_INTERNAL; }
    s->pipe=CreateNamedPipeW(name,PIPE_ACCESS_DUPLEX|FILE_FLAG_OVERLAPPED|FILE_FLAG_FIRST_PIPE_INSTANCE,
        PIPE_TYPE_BYTE|PIPE_READMODE_BYTE|PIPE_WAIT|PIPE_REJECT_REMOTE_CLIENTS,1,512,512,
        GE_PIPE_CONNECTION_TIMEOUT_MS,&attributes);
    if(s->pipe==INVALID_HANDLE_VALUE) {
        const DWORD error=GetLastError();release(s);
        return error==ERROR_ACCESS_DENIED || error==ERROR_PIPE_BUSY ? GE_BUSY : GE_INTERNAL;
    }
    s->thread=CreateThread(nullptr,0,worker,s,0,nullptr);
    if(!s->thread) { release(s);return GE_INTERNAL; }
    *out=s;return GE_OK;
}
int32_t GE_CALL GE_PipeStop(GE_PipeServer* s) {
    if(!s) return GE_INVALID;
    if(!SetEvent(s->stop)) return GE_INTERNAL;
    CancelIoEx(s->pipe,nullptr);
    const DWORD status=WaitForSingleObject(s->thread,GE_PIPE_STOP_TIMEOUT_MS);
    if(status==WAIT_TIMEOUT) return GE_BUSY;
    if(status!=WAIT_OBJECT_0) return GE_INTERNAL;
    release(s);return GE_OK;
}
}
