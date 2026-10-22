#include "game_context_snapshot.h"
#if !HR_READ_REOPEN_GUARDS || !HR_READ_CONTEXT || !HR_READ_LEVEL_CATALOG || !HR_READ_LIFECYCLE_TYPE || !HR_READ_SCHEDULER_COROUTINES || !GS_BOOTSTRAP_READONLY || HR_ACTION != 0
#error "reopen guard bundle requires all read-only prerequisites and no action"
#endif
#include "game_reopen_guards_capture_core.inc"
