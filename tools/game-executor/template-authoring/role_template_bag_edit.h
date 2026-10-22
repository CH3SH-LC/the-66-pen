#pragma once
#include "owner_notification_calls.h"

// Same native edit protocol, but the owner is the independently verified root4
// role prefab. The old scene-only environment guard is deliberately unchanged.
namespace ge::role_template_edit {
using namespace ge::component_edit;
Code CheckReady(ge::templates::TemplateReadSource, const Evidence&, EditState*) noexcept;
void Begin(ge::templates::TemplateReadSource, const NativeCalls&, const Evidence&, Result*) noexcept;
void Complete(ge::templates::TemplateReadSource, const NativeCalls&, const Evidence&, Result*) noexcept;
}
