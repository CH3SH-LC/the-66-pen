#include "../item_properties_capture.h"
#include <cassert>
#include <cstring>
#include <cstdio>
using namespace ge::templates;
struct Fixture {
    unsigned char objects[4][0x48]{};
    int reads = 0, fail_on = 0, mutate_on = 0;
    static bool Read(void* context, std::uint64_t address, void* data, std::size_t size) noexcept {
        auto& f = *static_cast<Fixture*>(context); ++f.reads;
        if (f.reads == f.fail_on) return false;
        if (f.reads == f.mutate_on) f.objects[3][0x35] = 1;
        if (address < 0x10000 || address > 0x10300 || ((address - 0x10000) % 0x100) || size > 0x48) return false;
        std::memcpy(data, f.objects[(address - 0x10000) / 0x100], size); return true;
    }
    template<class T> void Put(int object, std::size_t offset, T value) {
        std::memcpy(objects[object] + offset, &value, sizeof(value));
    }
    Fixture() {
        for (int i = 0; i < 4; ++i) Put<std::uint64_t>(i, 0, 0x20000 + static_cast<std::uint64_t>(i) * 0x100);
        Put<std::uint64_t>(0, 0x30, 0x10100); Put<std::uint64_t>(1, 0x18, 0x10200); Put<std::uint64_t>(1, 0x28, 0x10300);
        // Independent values from the disassembled eb79650 reset stores.
        objects[3][0x28] = 1; objects[3][0x29] = 1; objects[3][0x34] = 1; objects[3][0x35] = 0; objects[3][0x36] = 1;
        Put<std::uint32_t>(2, 0x38, 4200); Put<std::uint32_t>(2, 0x3c, 99);
        Put<std::uint32_t>(2, 0x40, 9999);
    }
    ItemPropertiesCapture Capture() {
        ItemPropertiesCapture out{};
        CaptureItemProperties(0x10000, {0x20000, 0x20100, 0x20200, 0x20300}, {this, Read}, &out); return out;
    }
};
int main() {
    Fixture good; auto result = good.Capture();
    assert(result.code == ItemPropertiesCode::complete && result.read_calls == 8);
    assert(result.matches_inter_reset && result.basic_word_38 == 4200 && result.basic_word_3c == 99);
    assert(result.stack_limit == 9999 && result.is_tradeable);
    assert(result.inter_values[3] == 0 && result.inter_values[4] == 1);
    Fixture changed; changed.objects[3][0x35] = 1; changed.objects[3][0x28] = 0; result = changed.Capture();
    assert(result.code == ItemPropertiesCode::complete && !result.matches_inter_reset && !result.is_tradeable);
    Fixture wrong; wrong.Put<std::uint64_t>(3, 0, 0x20400); result = wrong.Capture();
    assert(result.code == ItemPropertiesCode::class_mismatch && wrong.reads == 4);
    Fixture missing; missing.Put<std::uint64_t>(1, 0x28, 0); result = missing.Capture();
    assert(result.code == ItemPropertiesCode::invalid_input && missing.reads == 3);
    Fixture invalid; invalid.objects[3][0x34] = 2; result = invalid.Capture();
    assert(result.code == ItemPropertiesCode::invalid_boolean);
    Fixture unreadable; unreadable.fail_on = 4; result = unreadable.Capture();
    assert(result.code == ItemPropertiesCode::unreadable && unreadable.reads == 4);
    Fixture unstable; unstable.mutate_on = 5; result = unstable.Capture();
    assert(result.code == ItemPropertiesCode::unstable && unstable.reads == 5);
    std::puts("item_properties_capture: 7 host cases passed; no native execution");
}
