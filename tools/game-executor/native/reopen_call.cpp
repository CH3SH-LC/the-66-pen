#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "reopen_call.h"
namespace ge::scene {
ReopenCallResult dispatch_reopen(ReopenCurrent fn,void* levelManager,void* record) noexcept {
 ReopenCallResult result{sizeof(ReopenCallResult),1,ReopenCallCode::missing_binding,0,0,0,0,0,0};
 if(!fn||!levelManager||!record)return result;
 result.nativeCallAttempted=1;
 // Both normal return and exception can follow asynchronous or partial work.
 // Only independent post-load evidence may release the outer business lock.
 result.businessPending=1;
 __try {fn(levelManager,record,nullptr);result.nativeCallReturned=1;result.code=ReopenCallCode::returned;}
 __except(EXCEPTION_EXECUTE_HANDLER) {result.exceptionCode=GetExceptionCode();result.code=ReopenCallCode::exception;}
 return result;
}}
