#ifndef GAME_EXECUTOR_PIPE_SERVER_H
#define GAME_EXECUTOR_PIPE_SERVER_H
#include "game_executor.h"
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

#define GE_PIPE_MAGIC 0x31504547u
#define GE_PIPE_VERSION 1u
#define GE_PIPE_TOKEN_BYTES 32u
#define GE_PIPE_CONNECTION_TIMEOUT_MS 10000u
#define GE_PIPE_STOP_TIMEOUT_MS 2000u

typedef struct GE_PipeServer GE_PipeServer;
typedef enum GE_PipeOperation {
    GE_PIPE_HELLO=1, GE_PIPE_SUBMIT=2, GE_PIPE_RESULT=3
} GE_PipeOperation;

/* Windows x64 little-endian, default struct alignment; never pointers on wire. */
typedef struct GE_PipeRequestHeader {
    uint32_t magic, version, operation, payload_bytes;
} GE_PipeRequestHeader;
typedef struct GE_PipeResponseHeader {
    uint32_t magic, version;
    int32_t code;
    uint32_t payload_bytes;
} GE_PipeResponseHeader;
typedef struct GE_PipeHello {
    uint32_t process_id, abi_version, request_size, result_size;
} GE_PipeHello;

/* Start outside DllMain. Name must be exactly
 * \\.\pipe\Miliastra.GameExecutor.<GetCurrentProcessId()>.<16..64 hex digits>.
 * The caller supplies an unpredictable nonzero 32-byte token and shares it via
 * its own trusted channel. The token is never logged or written to disk here.
 * DACL admits only the effective caller token's logon SID; remote clients fail.
 * The executor must remain alive until Stop succeeds. Host must continue Pump
 * on its bound owner thread. This worker only calls Submit/GetResult.
 * Host serializes Start/Stop and stops clients before destroying the executor.
 * One request per connection; client reads complete response then closes.
 * Connect, reads and writes have bounded waits. No shutdown flush is performed.
 * Valid SUBMIT/RESULT return a 240-byte result even on non-OK core return; inspect
 * it only when code==GE_OK. Bad auth/protocol returns GE_INVALID, payload0.
 * Stop does not remove requests already accepted by the executor queue.
 */
GE_API int32_t GE_CALL GE_PipeStart(GE_Executor* executor, const wchar_t* pipe_name,
    const uint8_t token[GE_PIPE_TOKEN_BYTES], GE_PipeServer** out_server);
/* Stop signals and cancels pending I/O; joins for at most2000ms. On GE_BUSY or
 * GE_INTERNAL the server remains owned by caller: retry Stop, and retain the
 * executor and module. GE_OK consumes the server pointer. No concurrent Stop.
 */
GE_API int32_t GE_CALL GE_PipeStop(GE_PipeServer* server);

#ifdef __cplusplus
}
static_assert(sizeof(void*)==8, "Pipe ABI requires Windows x64");
static_assert(sizeof(GE_PipeRequestHeader)==16, "request header ABI");
static_assert(sizeof(GE_PipeResponseHeader)==16, "response header ABI");
static_assert(sizeof(GE_PipeHello)==16, "hello ABI");
static_assert(sizeof(GE_Request)==88, "request ABI");
static_assert(sizeof(GE_Result)==240, "result ABI");
#endif
#endif
