#include "game_context_snapshot.h"
#if !HR_READ_LIFECYCLE_TYPE || !GS_BOOTSTRAP_READONLY || HR_ACTION != 0
#error "lifecycle type extension is strictly read-only"
#endif
#include "game_lifecycle_type_core.inc"
