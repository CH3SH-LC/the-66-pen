#pragma once
#include "native_contact.h"
constexpr unsigned kDirectoryRows=8192;
struct DirectoryRow {std::uint64_t record,klass;std::uint32_t editorGuid,templateId;std::uint64_t templateRecord;};
struct DirectorySample {
    std::uint64_t global,levelManager,levelData,editData,commonData,container,containerClass,list,entries,enumerator,enumeratorMethodInfo,capacity;
    std::uint64_t editClass,commonClass,expectedEditClass,expectedCommonClass,expectedContainerClass;
    std::uint32_t status,count,listVersion,virtualCount,recordCount,reserved[3];
    unsigned char containerHeader[32],listHeader[32];
    DirectoryRow rows[kDirectoryRows];
};
struct DirectoryReceipt {
    std::uint32_t bytes,version,status,seh,stage,operation,nativeCalls,resourcesReleased,stable,reserved[3];
    std::uint64_t moduleBase,reserved64;
    ContactReceipt contact;
    DirectorySample first,second;
};
static_assert(sizeof(DirectoryRow)==32&&sizeof(DirectorySample)==262376&&sizeof(DirectoryReceipt)==9581008,"directory ABI");
void ExecuteDirectory(DirectoryReceipt*) noexcept;
