#include "item_properties_capture.h"
#include <cstring>

namespace ge::templates {
namespace {
template<class T> T At(const unsigned char* data, std::size_t offset) noexcept {
    T value{}; std::memcpy(&value, data + offset, sizeof(value)); return value;
}
bool Pointer(std::uint64_t value) noexcept {
    return value >= 0x10000 && value < 0x0000800000000000ULL && !(value & 7);
}
struct Reader {
    TemplateReadSource source;
    ItemPropertiesCapture& out;
    bool Fail(ItemPropertiesCode code) noexcept { out.code = code; return false; }
    bool Block(std::uint64_t pointer, unsigned char* bytes, std::size_t size) noexcept {
        if (!Pointer(pointer) || size > 0x0000800000000000ULL - pointer)
            return Fail(ItemPropertiesCode::invalid_input);
        ++out.read_calls;
        return source.read(source.context, pointer, bytes, size) || Fail(ItemPropertiesCode::unreadable);
    }
    bool Object(std::uint64_t pointer, std::uint64_t klass, unsigned char* bytes, std::size_t size) noexcept {
        if (!Block(pointer, bytes, size)) return false;
        return At<std::uint64_t>(bytes, 0) == klass || Fail(ItemPropertiesCode::class_mismatch);
    }
    bool Compare(std::uint64_t pointer, const unsigned char* bytes, std::size_t size) noexcept {
        unsigned char current[0x48]{};
        if (!Block(pointer, current, size)) return false;
        return !std::memcmp(current, bytes, size) || Fail(ItemPropertiesCode::unstable);
    }
};
}
void CaptureItemProperties(std::uint64_t property, ItemPropertiesClasses classes,
    TemplateReadSource source, ItemPropertiesCapture* out) noexcept {
    if (!out) return;
    *out = {}; out->code = ItemPropertiesCode::invalid_input; out->property = property;
    if (!source.read || !Pointer(classes.property) || !Pointer(classes.data) ||
        !Pointer(classes.basic) || !Pointer(classes.inter)) return;
    Reader r{source, *out};
    if (!r.Object(property, classes.property, out->property_bytes, sizeof(out->property_bytes))) return;
    out->data = At<std::uint64_t>(out->property_bytes, 0x30);
    if (!r.Object(out->data, classes.data, out->data_bytes, sizeof(out->data_bytes))) return;
    out->basic = At<std::uint64_t>(out->data_bytes, 0x18);
    out->inter = At<std::uint64_t>(out->data_bytes, 0x28);
    if (!r.Object(out->basic, classes.basic, out->basic_bytes, sizeof(out->basic_bytes)) ||
        !r.Object(out->inter, classes.inter, out->inter_bytes, sizeof(out->inter_bytes))) return;
    out->matches_inter_reset = true;
    for (std::size_t i = 0; i < 5; ++i) {
        const auto value = out->inter_bytes[kItemInterOffsets[i]];
        out->inter_values[i] = value;
        if (value > 1) { out->code = ItemPropertiesCode::invalid_boolean; return; }
        if (value != kItemInterResetValues[i]) out->matches_inter_reset = false;
    }
    out->basic_word_38 = At<std::uint32_t>(out->basic_bytes, 0x38);
    out->basic_word_3c = At<std::uint32_t>(out->basic_bytes, 0x3c);
    out->stack_limit = At<std::uint32_t>(out->basic_bytes, 0x40);
    out->is_tradeable = out->inter_values[0] != 0;
    // Compare children before roots: changing/replacing either object is visible.
    if (!r.Compare(out->inter, out->inter_bytes, sizeof(out->inter_bytes)) ||
        !r.Compare(out->basic, out->basic_bytes, sizeof(out->basic_bytes)) ||
        !r.Compare(out->data, out->data_bytes, sizeof(out->data_bytes)) ||
        !r.Compare(property, out->property_bytes, sizeof(out->property_bytes))) return;
    out->code = ItemPropertiesCode::complete;
}
}
