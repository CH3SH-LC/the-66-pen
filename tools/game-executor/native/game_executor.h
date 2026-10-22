#ifndef GAME_EXECUTOR_H
#define GAME_EXECUTOR_H
#include <stdint.h>

#if defined(GE_BUILD)
#define GE_API __declspec(dllexport)
#else
#define GE_API __declspec(dllimport)
#endif
#define GE_CALL __cdecl

#ifdef __cplusplus
extern "C" {
#endif

#define GE_ABI_VERSION 1u
#define GE_QUEUE_CAPACITY 32u
#define GE_HISTORY_CAPACITY 256u
#define GE_MAX_TTL_MS 86400000ull
#define GE_MESSAGE_CAPACITY 192u

typedef struct GE_Executor GE_Executor;
typedef enum GE_Code {
    GE_OK=0, GE_INVALID=1, GE_UNAVAILABLE=2, GE_WRONG_THREAD=3,
    GE_BUSY=4, GE_QUEUE_FULL=5, GE_HISTORY_FULL=6, GE_NOT_FOUND=7,
    GE_ID_CONFLICT=8, GE_INTERNAL=9
} GE_Code;
typedef enum GE_Operation { GE_CREATE_INSTANCE=1, GE_SAVE_LEVEL=2 } GE_Operation;
typedef enum GE_State {
    GE_QUEUED=0, GE_RUNNING=1, GE_COMPLETED=2, GE_FAILED=3,
    GE_EXPIRED=4, GE_SCENE_CHANGED=5, GE_RESULT_UNAVAILABLE=6
} GE_State;

/* Default Windows x64 alignment; no packed structs. Angles/units are adapter-defined.
 * SAVE_LEVEL requires template_id and all three vectors to be zero.
 * ttl_ms is relative to first accepted Submit, and is part of request identity. */
typedef struct GE_Request {
    uint32_t struct_size;
    uint32_t operation;
    uint64_t request_id;
    uint64_t scene_id;
    uint64_t scene_revision;
    uint64_t ttl_ms;
    uint64_t template_id;
    float position[3];
    float rotation[3];
    float scale[3];
} GE_Request;

typedef struct GE_Scene { uint64_t scene_id; uint64_t revision; } GE_Scene;

/* Callback return 0 means it completed its contract; any other return is failure.
 * A COMPLETED save is solely an executor/adapter receipt, never GIL verification. */
typedef struct GE_AdapterResult {
    uint64_t entity_id;
    int32_t detail_code;
    char message[GE_MESSAGE_CAPACITY];
} GE_AdapterResult;
typedef int32_t (GE_CALL *GE_ReadScene)(void*, GE_Scene*);
typedef int32_t (GE_CALL *GE_Execute)(void*, const GE_Request*, GE_AdapterResult*);
typedef struct GE_Adapter {
    uint32_t struct_size;
    uint32_t abi_version;
    void* context;
    GE_ReadScene read_scene;
    GE_Execute create_instance;
    GE_Execute save_level;
} GE_Adapter;

typedef struct GE_Result {
    uint32_t struct_size;
    uint32_t state;
    uint64_t request_id;
    uint32_t operation;
    int32_t detail_code;
    uint64_t scene_id;
    uint64_t scene_revision;
    uint64_t entity_id;
    char message[GE_MESSAGE_CAPACITY];
} GE_Result;

/* Output structures are fully initialized by the library. A GE_OK Submit may
 * return QUEUED or a cached terminal result. Non-OK API return rejects the call.
 * On a rejected Submit/GetResult, inspect only API return; output is zeroed. */
GE_API uint32_t GE_CALL GE_GetAbiVersion(void);
GE_API uint32_t GE_CALL GE_ApiVersion(void);
/* kind: 1=Request, 2=Result, 3=Adapter, 4=AdapterResult; unknown -> 0. */
GE_API uint32_t GE_CALL GE_StructureSize(uint32_t kind);
GE_API uint64_t GE_CALL GE_NowMs(void);
GE_API int32_t GE_CALL GE_Create(GE_Executor** out_executor);
/* Destroy requires external quiescence: join Submit/GetResult callers first.
 * When bound, only the owner may Destroy. Do not Destroy from a callback. */
GE_API int32_t GE_CALL GE_Destroy(GE_Executor* executor);
/* Bind on the host's chosen owner thread; it is never supplied by the client.
 * Callback/context lifetime must extend to successful Unbind/Destroy.
 * read_scene is required. Missing operation callbacks return UNAVAILABLE.
 * Host must serialize its scene mutation on this same owner thread. */
GE_API int32_t GE_CALL GE_Bind(GE_Executor* executor, const GE_Adapter* adapter);
GE_API int32_t GE_CALL GE_Unbind(GE_Executor* executor);
GE_API int32_t GE_CALL GE_Submit(GE_Executor* executor, const GE_Request* request, GE_Result* result);
GE_API int32_t GE_CALL GE_GetResult(GE_Executor* executor, uint64_t request_id, GE_Result* result);
GE_API int32_t GE_CALL GE_Pump(GE_Executor* executor, uint32_t max_requests, uint32_t* processed);

#ifdef __cplusplus
}
#endif
#endif
