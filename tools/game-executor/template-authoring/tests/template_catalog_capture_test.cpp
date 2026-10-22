#include "../template_catalog_capture.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

using namespace ge::templates;
namespace {
constexpr std::uint64_t module = 0x140000000ULL, global = 0x100000, manager = 0x120000;
constexpr std::uint64_t primary_dict = 0x130000, companion_dict = 0x140000;
constexpr std::uint64_t primary_buckets = 0x150000, primary_entries = 0x160000;
constexpr std::uint64_t companion_buckets = 0x180000, companion_entries = 0x190000;
constexpr std::uint64_t primary_objects = 0x500000, companion_objects = 0x700000;
constexpr std::uint32_t first_id = 0x42000001;
int checks = 0;
void Check(bool value, const char* name) {
    ++checks; if (!value) { std::fprintf(stderr, "FAIL: %s\n", name); std::exit(1); }
}
struct Memory {
    std::vector<unsigned char> bytes = std::vector<unsigned char>(0x800000);
    std::uint64_t global_slot = global, fail_address = 0, watch_address = 0, change_address = 0;
    std::uint32_t watch_hit = 0, change_on_hit = 2, new_value = 0;
    template<class T> void Put(std::uint64_t address, T value) {
        std::memcpy(bytes.data() + static_cast<std::size_t>(address - global), &value, sizeof(value));
    }
    template<class T> T Get(std::uint64_t address) const {
        T value{}; std::memcpy(&value, bytes.data() + static_cast<std::size_t>(address - global), sizeof(value)); return value;
    }
    static bool Read(void* context, std::uint64_t address, void* target, std::size_t size) noexcept {
        auto& m = *static_cast<Memory*>(context);
        if (address == m.fail_address) return false;
        if (address == m.watch_address && ++m.watch_hit == m.change_on_hit)
            m.Put(m.change_address, m.new_value);
        if (address == module + kTemplateGlobalSlotRva && size == 8) {
            std::memcpy(target, &m.global_slot, 8); return true;
        }
        if (address < global || address - global > m.bytes.size() || size > m.bytes.size() - static_cast<std::size_t>(address - global)) return false;
        std::memcpy(target, m.bytes.data() + static_cast<std::size_t>(address - global), size); return true;
    }
    void Dictionary(std::uint64_t d, std::uint64_t buckets, std::uint64_t entries,
        std::uint32_t count, std::uint32_t capacity, bool companion) {
        Put<std::uint64_t>(d, 0x300000); Put(d + 0x20, buckets); Put(d + 0x28, entries);
        Put(d + 0x38, count); Put<std::uint32_t>(d + 0x3c, 17); Put<std::int32_t>(d + 0x44, -1);
        Put<std::uint64_t>(buckets + 0x18, capacity); Put<std::uint64_t>(entries + 0x18, capacity);
        for (std::uint32_t i = 0; i < count; ++i) {
            const auto key = first_id + i;
            const auto hash = key & 0x7fffffffU;
            const auto bucket_address = buckets + 0x20 + (hash % capacity) * 4;
            const auto head = Get<std::int32_t>(bucket_address);
            const auto pointer = (companion ? companion_objects : primary_objects) + i * 0x100;
            const TemplateNativeEntry row{static_cast<std::int32_t>(hash), head - 1, key, 0, pointer};
            Put(entries + 0x20 + i * sizeof(row), row); Put(bucket_address, static_cast<std::int32_t>(i + 1));
            Put<std::uint64_t>(pointer, companion ? 0x320000 : 0x310000);
            Put<std::uint32_t>(pointer + 0x10, 0); Put<std::uint32_t>(pointer + 0x14, 1);
            Put<std::uint32_t>(pointer + 0x18, companion ? 4 : 3);
            Put(pointer + 0x1c, key); // Independent GUID domains may share numeric IDs.
            Put<std::uint32_t>(pointer + (companion ? 0xa8 : 0xb4), companion ? key : 9);
        }
    }
    explicit Memory(std::uint32_t count = 1, std::uint32_t capacity = 7) {
        Put(global + 0xa420, manager); Put(manager + 0x40, primary_dict); Put(manager + 0x10, companion_dict);
        Dictionary(primary_dict, primary_buckets, primary_entries, count, capacity, false);
        Dictionary(companion_dict, companion_buckets, companion_entries, count, capacity, true);
    }
};
GameContextSnapshot Baseline() {
    GameContextSnapshot b{}; b.structSize = sizeof(b); b.version = 1; b.status = GS_OK; b.flags = 1951;
    b.moduleBase = module; b.global = global; b.peImageSize = 0x6000000; b.reserved = 1073741842;
    b.entityCaptured = b.entityValidEntries = 12; return b;
}
TemplateCatalogCapture output{};
TemplateCatalogCaptureWorkspace workspace{};
TemplateCaptureCode Capture(Memory& m, const GameContextSnapshot& b) {
    CaptureTemplateCatalog(&b, {&m, Memory::Read}, &workspace, &output); return output.code;
}
}
int main() {
    const auto b = Baseline();
    {
        Memory m;
        Check(Capture(m, b) == TemplateCaptureCode::complete, "two complete catalogs");
        Check(output.primary.row_count == 1 && output.companion.row_count == 1, "independent counts");
        Check(output.primary_rows[0].id == first_id && output.companion_rows[0].key == first_id &&
            output.companion_rows[0].parent_id == first_id && output.companion_rows[0].own_id == first_id,
            "companion key parent and independent numeric ID");
        Check(output.companion_rows[0].guid_domain[2] == 4 && output.companion_rows[0].klass == 0x320000, "GUID domain and class");
        Check(ValidTemplateCatalog(MainTemplateView(output)) && MainTemplateView(output).complete, "existing pure validator integration");
        Check(output.read_calls && output.bytes_read && output.read_calls < kTemplateCaptureReadBudget, "bounded read accounting");
    }
    {
        Memory m(0); Check(Capture(m, b) == TemplateCaptureCode::complete, "allocated empty dictionaries");
        m.Put<std::uint64_t>(primary_dict + 0x20, 0); m.Put<std::uint64_t>(primary_dict + 0x28, 0);
        m.Put<std::int32_t>(primary_dict + 0x44, 0);
        Check(Capture(m, b) == TemplateCaptureCode::complete, "unallocated empty dictionary");
    }
    {
        Memory m(3, 7);
        const auto key = first_id + 1; const auto bucket = key % 7;
        m.Put<std::int32_t>(primary_buckets + 0x20 + bucket * 4, 0);
        auto entry = m.Get<TemplateNativeEntry>(primary_entries + 0x20 + 24); entry.hash = -1; entry.next = -1;
        m.Put(primary_entries + 0x20 + 24, entry); m.Put<std::uint32_t>(primary_dict + 0x40, 1); m.Put<std::int32_t>(primary_dict + 0x44, 1);
        Check(Capture(m, b) == TemplateCaptureCode::complete && output.primary.row_count == 2, "free-list occupancy");
    }
    {
        Memory m;
        m.Put<std::uint64_t>(primary_dict + 0x30, 0x330000);
        auto e = m.Get<TemplateNativeEntry>(primary_entries + 0x20);
        m.Put<std::int32_t>(primary_buckets + 0x20 + (e.hash % 7) * 4, 0); e.hash = 6;
        m.Put(primary_entries + 0x20, e); m.Put<std::int32_t>(primary_buckets + 0x20 + 6 * 4, 1);
        Check(Capture(m, b) == TemplateCaptureCode::complete, "custom comparer uses stored hash without calling comparer");
    }
    {
        Memory m(4096, 4096);
        Check(Capture(m, b) == TemplateCaptureCode::complete && output.primary.row_count == 4096 && output.companion.row_count == 4096, "full 4096 row capture");
        Check(output.bytes_read <= kTemplateCaptureByteBudget && output.read_calls <= kTemplateCaptureReadBudget, "largest capture within budgets");
    }
    {
        Memory m; auto bad = b; bad.flags &= ~GS_HOTFIX_DEFAULT_CONFIRMED;
        Check(Capture(m, bad) == TemplateCaptureCode::invalid_baseline && output.read_calls == 0, "unverified baseline zero reads");
        bad = b; bad.entityRejected = 1;
        Check(Capture(m, bad) == TemplateCaptureCode::invalid_baseline, "partial baseline refused");
        bad = b; bad.structSize = 0;
        Check(Capture(m, bad) == TemplateCaptureCode::invalid_baseline, "baseline ABI refused");
        CaptureTemplateCatalog(&b, {&m, nullptr}, &workspace, &output);
        Check(output.code == TemplateCaptureCode::invalid_baseline, "missing safe reader refused");
    }
    {
        Memory m; m.global_slot += 8;
        Check(Capture(m, b) == TemplateCaptureCode::unstable, "global changed");
    }
    {
        Memory m; m.fail_address = companion_entries + 0x20;
        Check(Capture(m, b) == TemplateCaptureCode::unreadable && !MainTemplateView(output).complete, "unreadable companion fails whole capture");
    }
    {
        Memory m; m.Put<std::uint64_t>(primary_entries + 0x18, 4097);
        Check(Capture(m, b) == TemplateCaptureCode::limit_exceeded, "capacity cap");
    }
    {
        Memory m; m.Put<std::uint32_t>(primary_dict + 0x38, 4097);
        Check(Capture(m, b) == TemplateCaptureCode::limit_exceeded, "initialized count cap");
    }
    {
        Memory m; m.Put<std::int32_t>(primary_dict + 0x40, 2);
        Check(Capture(m, b) == TemplateCaptureCode::invalid_structure, "free count exceeds initialized");
    }
    {
        Memory m; m.Put<std::int32_t>(primary_entries + 0x24, 0);
        Check(Capture(m, b) == TemplateCaptureCode::invalid_structure, "bucket cycle refused");
    }
    {
        Memory m; m.Put<std::int32_t>(primary_entries + 0x24, -2);
        Check(Capture(m, b) == TemplateCaptureCode::invalid_structure, "negative invalid next refused");
    }
    {
        Memory m; m.Put<std::uint32_t>(primary_objects + 0x1c, first_id + 7);
        Check(Capture(m, b) == TemplateCaptureCode::invalid_structure, "main dictionary key mismatch");
    }
    {
        Memory m; m.Put<std::uint32_t>(companion_objects + 0xa8, first_id + 7);
        Check(Capture(m, b) == TemplateCaptureCode::invalid_structure, "companion parent key mismatch");
    }
    {
        Memory m; m.Put<std::uint32_t>(companion_objects + 0x1c, 0);
        Check(Capture(m, b) == TemplateCaptureCode::invalid_structure, "uninitialized companion GUID");
    }
    {
        Memory m; m.Put<std::uint64_t>(primary_objects, 3);
        Check(Capture(m, b) == TemplateCaptureCode::invalid_structure, "invalid resource class");
    }
    {
        Memory m(2); m.Put<std::uint64_t>(primary_entries + 0x20 + 24 + 16, primary_objects);
        Check(Capture(m, b) == TemplateCaptureCode::invalid_structure, "duplicate object entry");
    }
    {
        Memory m; m.watch_address = primary_dict; m.change_address = primary_dict + 0x3c; m.new_value = 18;
        Check(Capture(m, b) == TemplateCaptureCode::unstable, "version changed during capture");
    }
    {
        Memory m; m.watch_address = companion_entries + 0x20; m.change_address = companion_entries + 0x20 + 12; m.new_value = 5;
        Check(Capture(m, b) == TemplateCaptureCode::unstable, "complete entry array compared including padding");
    }
    {
        Memory m; m.watch_address = primary_objects; m.change_address = primary_objects; m.new_value = 0x350000;
        Check(Capture(m, b) == TemplateCaptureCode::unstable, "resource class rechecked");
    }
    {
        Memory m; m.watch_address = companion_objects; m.change_address = companion_objects + 0x18; m.new_value = 5;
        Check(Capture(m, b) == TemplateCaptureCode::unstable, "companion GUID rechecked");
    }
    {
        Memory m; m.watch_address = manager + 0x40; m.change_address = manager + 0x40; m.new_value = 0x150000;
        Check(Capture(m, b) == TemplateCaptureCode::unstable, "manager directory pointer rechecked");
    }
    std::printf("template_catalog_capture_test: %d checks passed; host-only synthetic memory\n", checks);
}
