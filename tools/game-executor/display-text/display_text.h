#pragma once
#include "../native/game_context_snapshot.h"
#include "../template-authoring/component_attachment.h"
#include "../template-authoring/owner_notification_calls.h"
struct TabRow {
    std::uint64_t pointer,klass;
    std::int32_t index,sort,textLength;
    std::uint32_t icon,filter;
    std::uint8_t active,enabled;
    char16_t text[48];
};
struct TabHostResult {
    std::uint32_t entityId,status,optionCount,colliderCount,readbackVerified;
    std::uint64_t owner,config,collider,sphere;
    std::int32_t colliderShape;
    float radius;
    TabRow options[2];
    ge::component_attachment::AttachmentWorkspace attachmentWork;
    ge::component_attachment::AttachmentResult attachment;
    ge::component_edit::Result edit;
};
struct DisplayTextReceipt {
    std::uint32_t size,version,status,stage,sehCode,attempted,sceneUnchanged;
    std::uint32_t failedRva,failedValue,metadataCalls,completedHosts;
    GameContextSnapshot expectedScene,afterScene;
    TabHostResult hosts[2];
    std::uint64_t textProperty;
    std::uint32_t beforeCount,afterCount,language,translatedCount;
    struct TextRow {std::int32_t index,sourceLength,beforeLength,afterLength;std::uint32_t language;std::uint8_t enabled;char16_t source[64],before[64],after[64];} texts[6];
};
void ExecuteDisplayTextAction(const GameContextSnapshot*,DisplayTextReceipt*) noexcept;
