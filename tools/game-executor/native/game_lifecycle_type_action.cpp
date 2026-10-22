#include "game_context_snapshot.h"
#if HR_ACTION != 4 || GS_BOOTSTRAP_READONLY || !GS_REVIEWED_ACTION_PROFILE || HR_ACTION_PROFILE_REVIEWED != 1 || HR_REOPEN_ACTION_REVIEWED != 1
#error "Reopen capture core requires an explicitly reviewed action-4 build"
#endif
#include "game_lifecycle_type_core.inc"
