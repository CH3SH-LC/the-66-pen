#include "game_context_snapshot.h"
#if !HR_READ_SCHEDULER_COROUTINES || !HR_READ_LIFECYCLE_TYPE || !GS_BOOTSTRAP_READONLY || HR_ACTION != 0
#error "scheduler extension requires current read-only type binding and no action"
#endif
#include "game_scheduler_coroutines_core.inc"
