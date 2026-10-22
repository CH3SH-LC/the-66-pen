#pragma once
#include "template_catalog_capture.h"

namespace ge::templates {
// Current-image evidence: a9e1ed0 CSV export explicitly names isTradeable and
// stackLimit; their hashes match eb7a7e0/ebabe30. Other flags remain unnamed.
constexpr std::uint32_t kItemTradeableHash = 0xf4ce55d9;
constexpr std::uint32_t kItemStackLimitHash = 0x13abec4a;
constexpr std::uint32_t kItemDefaultStackLimit = 9999;
constexpr bool kItemAutoUseSemanticKnown = false;
constexpr std::uint32_t kItemInterHashes[5] = {
    0xf4ce55d9, 0x1144b655, 0x1ef38265, 0x3f1443fb, 0x768e8e89};
constexpr std::uint32_t kItemInterOffsets[5] = {0x28, 0x29, 0x34, 0x35, 0x36};
constexpr std::uint8_t kItemInterResetValues[5] = {1, 1, 1, 0, 1};
enum class ItemPropertiesCode : std::uint32_t {
    complete = 0, invalid_input = 1, unreadable = 2, class_mismatch = 3,
    invalid_boolean = 4, unstable = 5
};
// Resolved and verified by the eventual adapter for current image/hotfix.
// Definitions: property 41484; data 30464; basic 20018; inter 82466.
struct ItemPropertiesClasses { std::uint64_t property, data, basic, inter; };
struct ItemPropertiesCapture {
    ItemPropertiesCode code;
    std::uint32_t read_calls;
    std::uint64_t property, data, basic, inter;
    unsigned char property_bytes[0x38], data_bytes[0x38];
    unsigned char basic_bytes[0x48], inter_bytes[0x38];
    std::uint8_t inter_values[5];
    bool matches_inter_reset;
    bool is_tradeable;
    std::uint8_t reserved;
    std::uint32_t basic_word_38, basic_word_3c, stack_limit;
};
// Only caller-provided reads. No native methods, allocation, reset, or setter.
// Complete proves classes/bytes, the two named settings, and an interval
// stability comparison, but does not prove automatic-use semantics,
// registration, completed trade, persistence, or gameplay.
void CaptureItemProperties(std::uint64_t property, ItemPropertiesClasses classes,
    TemplateReadSource source, ItemPropertiesCapture* out) noexcept;
}
