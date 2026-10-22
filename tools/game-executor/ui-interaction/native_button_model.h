#pragma once
#include <array>
#include <cstdint>
#include <cstring>

// Current-build accessor component, intentionally without any process discovery,
// loader, action registration, persistence, or dispatch. The coordinator must
// validate PE/metadata SHA, edit-level identity, class78893, and main-thread scope
// before supplying a detached newly-created SkillButton model here.
namespace miliastra_ui {
inline constexpr char kImageSha256[] = "7f89938da606c1281659607d464702cddb9a09a7d4320a196630f60a811ec38e";
inline constexpr char kMetadataSha256[] = "469eccd43aa48fe7a2df4e1caf66fa1268a17f5a4a03fa209e1427e467cb0161";
inline constexpr std::uint32_t kKeyboardProperty = 0x57be76bc;
inline constexpr std::int32_t kZSelector = 26;
inline constexpr std::uint32_t kInteractionModeProperty = 0xe1617c66;
inline constexpr std::int32_t kInteractionEventMode = 2;
inline constexpr std::int32_t kSkillButtonComponentKind = 22;
inline constexpr std::uint32_t kSkillButtonDefinition = 78893;

struct IntProperty {
    std::uint32_t property_hash;
    std::uint32_t protobuf_field;
    std::uint32_t model_offset;
};

inline constexpr std::array<IntProperty, 8> kIntegerProperties{{
    {0x8f60e6fd, 501, 0xa4}, {0x3453cd4d, 502, 0x9c},
    {0xe1617c66, 503, 0x90}, {0xb7ac520c, 505, 0x88},
    {0xb3679614, 510, 0xac}, {0x81fd23fa, 511, 0xa8},
    {kKeyboardProperty, 513, 0x8c}, {0x4b42604c, 514, 0x98},
}};

struct ButtonApi {
    using Getter = std::int32_t (*)(void*, std::uint32_t, void*);
    using Setter = void (*)(void*, std::uint32_t, std::int32_t, void*);
    using Factory = void* (*)(void*, void*);
    using Initializer = void (*)(void*, void*);
    Getter get_integer;
    Getter get_keyboard;
    Setter set_keyboard;
    Factory create_model = nullptr;
    Initializer initialize_defaults = nullptr;
    void** expected_button_class_slot = nullptr;
    Getter get_interaction_mode = nullptr;
    Setter set_interaction_mode = nullptr;
};

// Does not perform calls. RVA bindings were derived from typed native signatures.
inline ButtonApi BindButtonApi(std::uintptr_t verified_module_base) {
    return {
        reinterpret_cast<ButtonApi::Getter>(verified_module_base + 0x8b3a5b0),
        reinterpret_cast<ButtonApi::Getter>(verified_module_base + 0x8b3bc70),
        reinterpret_cast<ButtonApi::Setter>(verified_module_base + 0x8b3b840),
        reinterpret_cast<ButtonApi::Factory>(verified_module_base + 0x95f6410),
        reinterpret_cast<ButtonApi::Initializer>(verified_module_base + 0x8b3b5e0),
        reinterpret_cast<void**>(verified_module_base + 0x57d6178),
        reinterpret_cast<ButtonApi::Getter>(verified_module_base + 0x8b3b4a0),
        reinterpret_cast<ButtonApi::Setter>(verified_module_base + 0x8b38c00),
    };
}

struct KeyboardResult {
    std::int32_t before;
    std::int32_t after;
    bool setter_called;
    bool readback_matched;
};

// Entry prologues explicitly move RCX -> RDX, EDX -> R8D (and R8D -> R9D
// for setters). The source signatures are this-first; inspecting only their
// later field accesses would incorrectly suggest an extra leading argument.
inline KeyboardResult SetInteractionEventMode(const ButtonApi& api, void* model) {
    KeyboardResult result{};
    if (!model || !api.get_interaction_mode || !api.set_interaction_mode)
        return result;
    result.before = api.get_interaction_mode(model, kInteractionModeProperty, nullptr);
    if (result.before != kInteractionEventMode) {
        api.set_interaction_mode(model, kInteractionModeProperty,
                                 kInteractionEventMode, nullptr);
        result.setter_called = true;
    }
    result.after = api.get_interaction_mode(model, kInteractionModeProperty, nullptr);
    result.readback_matched = result.after == kInteractionEventMode;
    return result;
}

inline std::array<std::int32_t, 8> ReadIntegerProperties(
    const ButtonApi& api, void* verified_button_model) {
    std::array<std::int32_t, 8> values{};
    for (std::size_t i = 0; i < values.size(); ++i) {
        values[i] = api.get_integer(verified_button_model,
                                   kIntegerProperties[i].property_hash, nullptr);
    }
    return values;
}

// Only the keyboard property changes. The caller must separately establish the
// interaction-event mode and parent group; this alone does not activate a UI.
inline KeyboardResult SetZOnDetachedButton(
    const ButtonApi& api, void* verified_detached_button_model) {
    KeyboardResult result{};
    if (!verified_detached_button_model || !api.get_keyboard || !api.set_keyboard)
        return result;
    result.before = api.get_keyboard(verified_detached_button_model,
                                    kKeyboardProperty, nullptr);
    if (result.before != kZSelector) {
        api.set_keyboard(verified_detached_button_model,
                         kKeyboardProperty, kZSelector, nullptr);
        result.setter_called = true;
    }
    result.after = api.get_keyboard(verified_detached_button_model,
                                   kKeyboardProperty, nullptr);
    result.readback_matched = result.after == kZSelector;
    return result;
}

struct DetachedButtonResult {
    void* model = nullptr;
    bool factory_returned = false;
    bool class_matched = false;
    bool defaults_initialized = false;
    KeyboardResult keyboard{};
};

// Pass a normal IL2CPP String containing "BydUICompSkillButtonEditData" from the
// coordinator's established string API. The native factory allocates through its
// official pool and invokes vtable slots 0x2d8 and 0x260 (9606ecb..9606efa).
// A result remains detached: it has no parent registration, group index, or save.
// If a later stage fails, preserve the result for diagnosis; do not auto-replay.
inline DetachedButtonResult CreateDetachedZButton(
    const ButtonApi& api, void* skill_button_type_name) {
    DetachedButtonResult result;
    if (!skill_button_type_name || !api.create_model || !api.initialize_defaults ||
        !api.expected_button_class_slot || !api.get_keyboard || !api.set_keyboard)
        return result;
    result.model = api.create_model(skill_button_type_name, nullptr);
    result.factory_returned = result.model != nullptr;
    if (!result.factory_returned)
        return result;
    void* expected = *api.expected_button_class_slot;
    result.class_matched = expected && *static_cast<void**>(result.model) == expected;
    if (!result.class_matched)
        return result;
    api.initialize_defaults(result.model, nullptr);
    result.defaults_initialized = true;
    result.keyboard = SetZOnDetachedButton(api, result.model);
    return result;
}
struct UiHandle16 {
    std::uint32_t words[4]{};
};
static_assert(sizeof(UiHandle16) == 16, "Native UI handle is exactly 16 bytes");

using ReadBytes = bool (*)(const void*, void*, std::size_t);

struct ComponentApi {
    using Add = void* (*)(const UiHandle16*, std::int32_t, bool, bool, void*);
    using GetData = void* (*)(void*, void*);
    Add add_component;
    GetData get_data_list;
};

inline ComponentApi BindComponentApi(std::uintptr_t verified_module_base) {
    return {
        reinterpret_cast<ComponentApi::Add>(verified_module_base + 0x10616220),
        reinterpret_cast<ComponentApi::GetData>(verified_module_base + 0xbc16250),
    };
}

struct UiEditApi {
    using Open = void* (*)(void*, bool, bool);
    using Snapshot = void (*)(void*, void*, std::int32_t);
    using Notify = void (*)(void*, void*);
    using Close = void (*)(void*);
    Open open;
    Snapshot snapshot;
    Notify notify;
    Close close;
};
inline UiEditApi BindUiEditApi(std::uintptr_t verified_module_base) {
    return {reinterpret_cast<UiEditApi::Open>(verified_module_base + 0xe827750),
            reinterpret_cast<UiEditApi::Snapshot>(verified_module_base + 0x107abdf0),
            reinterpret_cast<UiEditApi::Notify>(verified_module_base + 0x9c26c70),
            reinterpret_cast<UiEditApi::Close>(verified_module_base + 0xc7bab90)};
}

enum class ButtonStage { none, add, read_model, open, snapshot, mode, keyboard, notify, close, complete };
struct AttachedButtonResult {
    void* component = nullptr;
    void* model = nullptr;
    UiHandle16 owner{};
    std::int32_t data_count = 0;
    std::uint32_t matching_models = 0;
    std::uint8_t model_flag20 = 0;
    void* transaction = nullptr;
    ButtonStage stage = ButtonStage::none;
    bool open_called = false;
    bool snapshot_called = false;
    bool notify_called = false;
    bool close_called = false;
    bool transaction_may_be_open = false;
    bool outcome_uncertain = false;
    bool calls_returned = false;
    bool add_called = false;
    bool list_read_complete = false;
    bool owner_matched = false;
    KeyboardResult keyboard{};
    KeyboardResult interaction_mode{};
};

template <typename T>
inline bool ReadAt(ReadBytes read, const void* base, std::size_t offset, T& out) {
    return base && read(reinterpret_cast<const void*>(
        reinterpret_cast<std::uintptr_t>(base) + offset), &out, sizeof(out));
}

// Formal node component creation, not appending raw managed-list memory.
// PRECONDITION: the coordinator has just created/verified this owner node and
// proved it has no kind22 component. Never call this again after add_called.
// Caller resolves exact expected_button_class through initialized metadata before
// entering, and supplies its bounded current-process memory reader. No save here.
// The native path creates the edit data and calls its official default initializer
// through bc162b0 -> 7340610 -> SkillButton vtable368, so no manual reset is used.
inline void AttachNewZInteractionButtonInto(
    const ComponentApi& components, const ButtonApi& button,
    const UiHandle16& verified_fresh_owner, void* expected_button_class,
    ReadBytes read, const UiEditApi& edit, void* verified_edit_manager,
    AttachedButtonResult* out) {
    if (!out || out->add_called) return;
    auto& result = *out;
    if (!edit.open || !edit.snapshot || !edit.notify || !edit.close ||
        !verified_edit_manager || !components.add_component || !components.get_data_list || !read ||
        !expected_button_class || !button.get_keyboard || !button.set_keyboard ||
        !button.get_interaction_mode || !button.set_interaction_mode ||
        verified_fresh_owner.words[3] == 0)
        return;
    result.add_called = true;
    result.outcome_uncertain = true;
    result.stage = ButtonStage::add;
    result.component = components.add_component(&verified_fresh_owner,
        kSkillButtonComponentKind, true, true, nullptr);
    if (!result.component) return;
    result.stage = ButtonStage::read_model;
    void* list = components.get_data_list(result.component, nullptr);
    void* array = nullptr;
    std::uint64_t capacity = 0;
    if (!ReadAt(read, list, 0x18, result.data_count) || result.data_count < 1 ||
        result.data_count > 32 || !ReadAt(read, list, 0x10, array) ||
        !ReadAt(read, array, 0x18, capacity) || capacity <
            static_cast<std::uint64_t>(result.data_count) || capacity > 4096)
        return;
    for (std::int32_t i = 0; i < result.data_count; ++i) {
        void* candidate = nullptr;
        void* actual_class = nullptr;
        if (!ReadAt(read, array, 0x20 + static_cast<std::size_t>(i)*8, candidate) ||
            !ReadAt(read, candidate, 0, actual_class)) return;
        if (actual_class == expected_button_class) {
            ++result.matching_models;
            result.model = candidate;
        }
    }
    result.list_read_complete = true;
    if (result.matching_models != 1 ||
        !ReadAt(read, result.model, 0x24, result.owner) ||
        !ReadAt(read, result.model, 0x20, result.model_flag20)) return;
    result.owner_matched = std::memcmp(&result.owner, &verified_fresh_owner, 16) == 0;
    if (!result.owner_matched) return;
    result.stage = ButtonStage::open;
    result.open_called = true;
    result.transaction_may_be_open = true;
    result.transaction = edit.open(nullptr, false, false);
    if (!result.transaction) return;
    result.stage = ButtonStage::snapshot;
    result.snapshot_called = true;
    edit.snapshot(result.component, nullptr, 0);
    result.stage = ButtonStage::mode;
    result.interaction_mode = SetInteractionEventMode(button, result.model);
    if (!result.interaction_mode.readback_matched) return;
    result.stage = ButtonStage::keyboard;
    result.keyboard = SetZOnDetachedButton(button, result.model);
    if (!result.keyboard.readback_matched) return;
    result.stage = ButtonStage::notify;
    result.notify_called = true;
    edit.notify(verified_edit_manager, result.component);
    result.stage = ButtonStage::close;
    result.close_called = true;
    edit.close(result.transaction);
    result.transaction_may_be_open = false;
    result.stage = ButtonStage::complete;
    result.calls_returned = true;
    // Independent pending-state capture and native export/save/readback remain
    // mandatory. Returning from calls is not a persistence acceptance claim.
    return;
}
}  // namespace miliastra_ui
