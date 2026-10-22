#include "game_context_snapshot.h"
#if !HR_READ_LEVEL_CATALOG || !GS_BOOTSTRAP_READONLY || HR_ACTION != 0
#error "catalog extension is strictly read-only"
#endif
#include "game_level_catalog_core.inc"
