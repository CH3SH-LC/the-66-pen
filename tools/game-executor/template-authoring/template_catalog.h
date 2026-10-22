#pragma once
#include <cstddef>
#include <cstdint>

// Pure comparison of two complete native MAIN resource observations. An adapter must
// capture manager+0x40 on the verified game thread. This header does not capture
// memory and a passing comparison does not prove defaults, names, companion
// registration in manager+0x10, or persistence.
namespace ge::templates {
constexpr std::uint32_t kMaxTemplateRows = 4096;
struct TemplateIdentity {
    std::uint32_t id, subtype;
    std::uint64_t resource, klass;
};
struct TemplateCatalogView {
    const TemplateIdentity* rows;
    std::uint32_t count;
    std::uint64_t manager;
    std::uint32_t level_id;
    bool complete;
};
enum class CatalogCode : std::uint32_t {
    verified = 0, incomplete = 1, invalid_catalog = 2, context_changed = 3,
    invalid_request = 4, count_mismatch = 5, prior_resource_changed = 6,
    added_resource_mismatch = 7
};
struct TemplateDelta {
    CatalogCode code;
    TemplateIdentity added;
};
inline bool TemplatePointer(std::uint64_t value) noexcept {
    return value >= 0x10000 && value < 0x0000800000000000ULL && !(value & 7);
}
inline bool ValidTemplateCatalog(const TemplateCatalogView& value) noexcept {
    if (!TemplatePointer(value.manager) || !value.level_id ||
        value.count > kMaxTemplateRows || (value.count && !value.rows)) return false;
    for (std::uint32_t i=0; i<value.count; ++i) {
        const auto& row=value.rows[i];
        if (!row.id || !row.subtype || !TemplatePointer(row.resource) ||
            !TemplatePointer(row.klass)) return false;
        for (std::uint32_t j=0; j<i; ++j)
            if (row.id==value.rows[j].id || row.resource==value.rows[j].resource) return false;
    }
    return true;
}
// Native subtype -> official configuration-ID band, from current 83688d0 table.
// This describes only manager+0x40. Ordinary items additionally create a
// companion in manager+0x10, keyed by the same primary ID; verify that separately.
// Skills are not enabled here until their full receipt contract is integrated.
inline std::uint32_t ExpectedTemplateBand(std::uint32_t subtype) noexcept {
    switch (subtype) {case 9:return 8; case 11:return 10; default:return 0;}
}
inline TemplateDelta VerifySingleMainTemplateCreated(
    const TemplateCatalogView& before, const TemplateCatalogView& after,
    std::uint32_t expected_subtype, std::uint64_t expected_class,
    std::uint64_t returned_resource=0) noexcept {
    const auto fail=[](CatalogCode code) noexcept {return TemplateDelta{code,{}};};
    if (!before.complete || !after.complete) return fail(CatalogCode::incomplete);
    if (!ValidTemplateCatalog(before) || !ValidTemplateCatalog(after))
        return fail(CatalogCode::invalid_catalog);
    if (before.manager!=after.manager || before.level_id!=after.level_id)
        return fail(CatalogCode::context_changed);
    const auto band=ExpectedTemplateBand(expected_subtype);
    if (!band || !TemplatePointer(expected_class) ||
        (returned_resource && !TemplatePointer(returned_resource)))
        return fail(CatalogCode::invalid_request);
    if (after.count != before.count+1) return fail(CatalogCode::count_mismatch);
    for (std::uint32_t i=0; i<before.count; ++i) {
        const auto& old=before.rows[i]; bool found=false;
        for (std::uint32_t j=0; j<after.count; ++j) {
            const auto& row=after.rows[j];
            if (old.id==row.id && old.subtype==row.subtype &&
                old.resource==row.resource && old.klass==row.klass) {found=true;break;}
        }
        if (!found) return fail(CatalogCode::prior_resource_changed);
    }
    for (std::uint32_t j=0; j<after.count; ++j) {
        const auto& row=after.rows[j]; bool existed=false;
        for (std::uint32_t i=0; i<before.count; ++i)
            if (row.id==before.rows[i].id) {existed=true;break;}
        if (existed) continue;
        if (row.subtype!=expected_subtype || row.klass!=expected_class ||
            (returned_resource && row.resource!=returned_resource) ||
            (row.id & 0xe0000000U)!=0x40000000U || ((row.id>>22)&127U)!=band)
            return fail(CatalogCode::added_resource_mismatch);
        return {CatalogCode::verified,row};
    }
    return fail(CatalogCode::added_resource_mismatch);
}
}
