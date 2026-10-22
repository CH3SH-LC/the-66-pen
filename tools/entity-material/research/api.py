"""Bounded, disk-only IL2CPP queries; explicit output is the sole write boundary."""
from __future__ import annotations
import bisect
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import struct
import sys

sys.dont_write_bytecode = True
try:
    from .metadata_core import Metadata, i32, u32, u64
    from .semantics import TYPE_ENUM, attributes, domains
except ImportError:
    from metadata_core import Metadata, i32, u32, u64
    from semantics import TYPE_ENUM, attributes, domains

PROJECT = Path(__file__).resolve().parents[3]
SCOPE = "current-build disk metadata and code only; no runtime state, native execution or gameplay semantic proof"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_output(value):
    """Validate without creating anything, including nonexistent parents."""
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT / path
    path = Path(os.path.abspath(path))
    require(path != PROJECT and path.is_relative_to(PROJECT), "OUTPUT_MUST_BE_INSIDE_PROJECT")
    for part in (path, *path.parents):
        if part.exists() or part.is_symlink():
            require(not part.is_symlink() and not (getattr(part.stat(), "st_file_attributes", 0) & 0x400), "OUTPUT_REPARSE_POINT_REFUSED")
        if part == PROJECT:
            break
    require(path.resolve().is_relative_to(PROJECT), "OUTPUT_RESOLVES_OUTSIDE_PROJECT")
    require(not path.exists() or path.is_dir(), "OUTPUT_MUST_BE_DIRECTORY")
    return path


def write_result(out, command, result, text=None):
    """Only called explicitly by CLI/caller. Never overwrites prior evidence."""
    out = validate_output(out)
    require(re.fullmatch(r"[a-z0-9-]+", command), "INVALID_ARTIFACT_COMMAND")
    folder = out / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + command + "-" + secrets.token_hex(3))
    folder.mkdir(parents=True, exist_ok=False)
    with (folder / "result.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    if text is not None:
        with (folder / "code.asm").open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
    return folder / "result.json"


class Research:
    """Construct once for several queries. All methods return values; none write."""
    def __init__(self, image_path=None, metadata_path=None):
        self.m = Metadata(image_path, metadata_path)
        self.m.md.detail = True
        self._class_ids = None
        self._usage_bounds = None
        self._pairs = None
        self._method_index = None

    def envelope(self, operation, data):
        return dict(ok=True, operation=operation, scope=SCOPE, imageSha256=self.m.sha,
                    metadataSha256=self.m.metadata_sha, gameConnected=False,
                    nativeCalled=False, data=data)

    def class_ids(self):
        if self._class_ids is None:
            m = self.m
            count = m.d(m.types_registration + 0x30) ^ 0x28a0fa2d
            require(count == 683568, "TYPE_REGISTRATION_COUNT_CHANGED")
            raw = m.get(m.q(m.types_registration + 0x50) - m.base, count * 16)
            self._class_ids = sorted({struct.unpack_from("<I", raw, i)[0]
                                     for i in range(0, len(raw), 16) if raw[i + 10] in (17, 18)})
        return self._class_ids

    def definition(self, index):
        require(type(index) is int and index in self.class_ids(), "CLASS_DEFINITION_NOT_REGISTERED")
        return self._definition_record(index)

    def _definition_record(self, index):
        return dict(self.m.definition_name(index), typeDefinitionIndex=index,
                    indexDomain="TypeDefinitionIndex", runtimeComponentKind=None,
                    runtimeComponentKindKnown=False)

    @staticmethod
    def domains():
        return domains()

    def classes(self, name="", *, regex=False, offset=0, limit=100):
        require(0 <= offset and 1 <= limit <= 100000, "CLASS_PAGE_BOUNDS")
        pattern = re.compile(name, re.I) if regex else None
        found = []
        for index in self.class_ids():
            row = self._definition_record(index)
            title = (row["identifier"] or {}).get("name", "")
            if (pattern.search(title) if regex else name.casefold() in title.casefold()):
                found.append(row)
        return dict(total=len(found), offset=offset, limit=limit, rows=found[offset:offset + limit],
                    registeredDefinitionCount=len(self.class_ids()), hasMore=offset + limit < len(found))

    def type(self, index):
        require(type(index) is int and 0 <= index < 683568, "TYPE_INDEX_RANGE")
        row = self.m.type(index)
        if row["definitionIndex"] is not None:
            row["definition"] = self._definition_record(row["definitionIndex"])
        # Exact low 16 bits of the native Il2CppType record; do not infer field
        # behavior, storage ownership or thread-static addressing from names.
        row["attributeBitsRaw"] = struct.unpack_from("<H", bytes.fromhex(row["hex"]), 8)[0]
        row.update(typeIndex=index, indexDomain="Il2CppTypeIndex", kindDomain="Il2CppTypeEnum",
                   kindName=TYPE_ENUM.get(row["kind"], "UNKNOWN"),
                   definitionIndexDomain="TypeDefinitionIndex", runtimeComponentKind=None,
                   runtimeComponentKindKnown=False,
                   attributeBitsDomain="Context dependent; interpreted by containing field or parameter, not by type alone",
                   remainingTypeBitsRaw=bytes.fromhex(row["hex"])[11:].hex(),
                   remainingTypeBitsDecoded=False,
                   dataMeaning="TypeDefinitionIndex" if row["kind"] in (17, 18) else "Not recursively decoded; no generic/array/pointer layout claim")
        return row

    def method(self, index):
        require(type(index) is int and 0 <= index < (0x2e16c70 - 0x2871c70) // 8, "METHOD_INDEX_RANGE")
        m = self.m
        method = m.method_owner(index)
        method.update(methodDefinitionIndex=index, indexDomain="MethodDefinitionIndex")
        method["owner"] = self._definition_record(method["owner"]["index"])
        if m.q(0x2871c70 + index * 8) == 0:
            method["functionRva"] = None
        at = method["recordBodyOffset"]
        k = u32(index * 0x4e94) ^ 0x62d8b7b8
        k = u32(k * 0x7572748a + 0x1f4d9eea) ^ 0x6e8931d6
        mix = u32(k * 0x39036375)
        count = (m.body[at + 0x18] + 0x8c - mix) & 255
        start = u32((m.bd(at + 8) ^ 0x20d55d01) - mix)
        ret = u32(m.bd(at) + u32(k * 0xc6fc9c8b) + 0xe5ee4081)
        name = m.identifier(u32((m.bd(at + 4) ^ 0x0613ace3) - mix))
        flags = (struct.unpack_from("<H", m.body, at + 0x12)[0] - mix - 0x7269) & 0xffff
        # Native 515766 swaps words +14/+16 before subtract/broadcast add.
        require(m.get(0x3909610, 16).hex() == "9f4d81aa000000000000000000000000", "METHOD_WORD_CONSTANT_CHANGED")
        slot_raw = (struct.unpack_from("<H", m.body, at + 0x16)[0] - mix + 0x4d9f) & 0xffff
        adjacent_word = (struct.unpack_from("<H", m.body, at + 0x14)[0] - mix + 0xaa81) & 0xffff
        require(count < 256, "METHOD_PARAMETER_COUNT")
        table = i32(m.d(m.header + 0x68)) ^ 0x146be503
        params = []
        for i in range(count):
            j = start + i
            v = u64(j * 0x4a23) ^ 0x5f268fcf
            v = u64(v * 0x2b0352a0) >> 9
            v = u32((u32(v) ^ 0x1028ea75) + 0x68b376f1) ^ 0x4f86a723
            a = table + j * 8
            t = u32((m.bd(a) ^ 0x76621606) - v)
            typed = self.type(t) if t != 0xffffffff else None
            params.append(dict(position=i, sourceIndex=j, parameterDefinitionIndex=j,
                               indexDomain="ParameterDefinitionIndex", positionDomain="DeclaredParameterOrdinal",
                               type=typed, parameterAttributes=attributes(typed["attributeBitsRaw"], "ParameterAttributes") if typed else None,
                               implicitThis=False,
                               name=m.identifier(u32((m.bd(a + 4) ^ 0x6b95f108) - v))))
        return dict(method=method, name=name, returnType=self.type(ret) if ret != 0xffffffff else None,
                    declaringType=method["owner"], methodDefinitionIndex=index,
                    methodAttributes=attributes(flags, "MethodAttributes"),
                    isStatic=bool(flags & 0x10), isInstance=not bool(flags & 0x10),
                    isVirtual=bool(flags & 0x40), isAbstract=bool(flags & 0x400),
                    isConstructor=name["name"] in (".ctor", ".cctor") and bool(flags & 0x1000),
                    parameterCount=count, declaredParameterCount=count, parameters=params,
                    parametersIncludeImplicitThis=False,
                    hasImplicitThis=not bool(flags & 0x10),
                    vtableSlot=None if slot_raw == 0xffff else slot_raw, vtableSlotRaw=slot_raw,
                    vtableSlotDomain="MethodDefinitionSlot",
                    vtableSlotLimitation="MethodInfo slot, not every class table row containing this method; duplicate mappings and interface/runtime offsets are separate.",
                    nativeWord2c=dict(value=adjacent_word, hex=hex(adjacent_word), semanticVerified=False),
                    metadataSemanticsSource=dict(constructorRva="0x5153f0", attributesWriteRva="0x515753",
                                                 staticBitConsumerRva="0x53f255", slotConsumerRva="0x517518"),
                    nativeAbiResolved=False,
                    nativeAbiLimitation="Declared signature only; implicit this is not in parameters. Hidden MethodInfo/context, return buffers, value-type this and thunk/register placement are not resolved.")

    def methods(self, definition, *, signatures=True):
        cls = self.definition(definition)
        at = cls["recordBodyOffset"]
        begin = i32(self.m.bd(at + 8)) ^ 0x0478af59
        count = struct.unpack_from("<H", self.m.body, at + 0x3c)[0] ^ 0x8811
        require(count <= 65535 and begin >= 0, "CLASS_METHOD_RANGE")
        getter = self.method if signatures else self.m.method_owner
        return dict(classInfo=cls, methodBegin=begin, methodCount=count,
                    methods=[getter(i) for i in range(begin, begin + count)])

    def method_at(self, rva):
        if self._method_index is None:
            m = self.m
            data = m.get(0x2871c70, 0x2e16c70 - 0x2871c70)
            self._method_index = {}
            for index, (pointer,) in enumerate(struct.iter_unpack("<Q", data)):
                if pointer:
                    self._method_index.setdefault(pointer - m.base, []).append(index)
        return [self.method(index) for index in self._method_index.get(rva, [])]

    def fields(self, definition):
        """Actual metadata field names/types and offset table, native 5135b0."""
        m = self.m
        cls = self.definition(definition)
        at = cls["recordBodyOffset"]
        count = struct.unpack_from("<H", m.body, at + 0x30)[0] ^ 0x9a6b
        begin = m.bd(at) ^ 0x72628007
        table = i32(u32(m.d(m.header + 0x4c) + 0xe5d249bf))
        map_table = i32(m.d(m.header + 0x198)) ^ 0x5303f399
        layout_table = i32(m.d(m.header + 0x1a4)) ^ 0x0d8c5d0a
        layout_index = i32(m.bd(map_table + definition * 4))
        require(layout_index >= 0 and count <= 65535, "FIELD_LAYOUT_RANGE")
        layout_at = layout_table + layout_index * 12
        offset_begin = m.bd(layout_at + 8)
        offsets = i32(m.d(m.header + 0x1e4)) ^ 0x67102427
        rows = []
        for local in range(count):
            index = begin + local
            mix = u64(u64((u64(index * 0x23cf) ^ 0x3d27c42e) * 0x7f76a166) + 0xf06651fc0b8a) >> 16
            mix = u32(mix + 0x49acdcbc)
            f = table + index * 8
            t = u32(m.bd(f + 4) + 0xb36b852d) ^ mix ^ 0x4f6e2a1d
            raw_offset = m.bd(offsets + (offset_begin + local) * 4)
            special = bool(raw_offset & 0x01000000)
            typed = self.type(t) if t != 0xffffffff else None
            field_flags = typed["attributeBitsRaw"] if typed else None
            rows.append(dict(ordinal=local, fieldIndex=index, fieldDefinitionIndex=index,
                             indexDomain="FieldDefinitionIndex", ordinalDomain="DeclaredFieldOrdinal",
                             declaringTypeDefinitionIndex=definition,
                             serializedFieldNumber=None, serializedFieldNumberKnown=False,
                             recordBodyOffset=f,
                             recordHex=m.body[f:f + 8].hex(),
                             name=m.identifier(m.bd(f) ^ mix ^ 0x048e6373),
                             type=typed,
                             fieldAttributes=attributes(field_flags, "FieldAttributes") if typed else None,
                             isStatic=bool(field_flags & 0x10) if typed else None,
                             offsetTableIndex=offset_begin + local, offsetRaw=hex(raw_offset),
                             offset=raw_offset if not special else None,
                             offsetHex=hex(raw_offset) if not special else None,
                             specialOffsetFlag=special,
                             specialOffsetPayload=(raw_offset & 0xffffff) if special else None))
        return dict(classInfo=cls, fieldBegin=begin, fieldCount=count, fields=rows,
                    layoutIndex=layout_index, layoutRecordHex=m.body[layout_at:layout_at + 12].hex(),
                    sourceRva="0x5135b0", declaredOnly=True, runtimeOffsetsVerified=False,
                    limitation="Definition offsets only; inherited fields are queried on their declaring class. Generic inflation and special/thread-static addresses require runtime state and are not guessed.")

    def field(self, definition, *, ordinal=None, index=None):
        require((ordinal is None) != (index is None), "ONE_FIELD_SELECTOR_REQUIRED")
        data = self.fields(definition)
        selected = ordinal if ordinal is not None else index - data["fieldBegin"]
        require(type(selected) is int and 0 <= selected < data["fieldCount"], "FIELD_OUTSIDE_DECLARING_CLASS")
        return dict(classInfo=data["classInfo"], field=data["fields"][selected], declaredOnly=True,
                    runtimeOffsetsVerified=False)

    def properties(self, definition):
        """Real PropertyDefinition table and class-relative accessors, 515fc0."""
        m = self.m
        methods = self.methods(definition, signatures=False)
        cls = methods["classInfo"]
        at = cls["recordBodyOffset"]
        count = m.body[at + 0x43] ^ 0x86
        begin = u32(m.bd(at + 0x24) + 0xce2141cc)
        table = i32(u32(m.d(m.header + 0x158) + 0xe2aba334))
        rows = []
        for local in range(count):
            index = begin + local
            p = table + index * 10
            mix = u64(u64((u64(index * 0xa593) ^ 0x3ca3ffa0) * 0x5cd0b62e) + 0x63a341e6) ^ 0x2411ed71
            getter = ((struct.unpack_from("<H", m.body, p + 4)[0] - 0x238f) ^ mix) & 0xffff
            setter = (struct.unpack_from("<H", m.body, p + 8)[0] ^ mix ^ 0xdb1) & 0xffff
            attrs = (mix ^ (struct.unpack_from("<H", m.body, p + 6)[0] + 0x720a)) & 0xffff
            def accessor(ordinal):
                if ordinal == 0xffff:
                    return None
                require(ordinal < methods["methodCount"], "PROPERTY_ACCESSOR_OUTSIDE_CLASS")
                return dict(ordinal=ordinal, **self.method(methods["methodBegin"] + ordinal))
            rows.append(dict(ordinal=local, propertyIndex=index, indexDomain="PropertyDefinitionIndex",
                             declaringTypeDefinitionIndex=definition, recordBodyOffset=p,
                             recordHex=m.body[p:p + 10].hex(),
                             name=m.identifier(u32(m.bd(p) + 0xee8895ea) ^ u32(mix)),
                             attributes=attrs, attributesDomain="PropertyAttributes",
                             getter=accessor(getter), setter=accessor(setter)))
        return dict(classInfo=cls, propertyBegin=begin, propertyCount=count, properties=rows,
                    sourceRva="0x515fc0", inferredFromMethodNames=False)

    def vtable(self, definition):
        cls = self.definition(definition)
        m = self.m
        at = cls["recordBodyOffset"]
        start = i32(m.bd(at + 0x20)) ^ 0x6c9a5100
        count = m.body[at + 0x40] ^ 6
        table = i32(m.d(m.header + 0x98)) ^ 0x76a06155
        rows = []
        for slot in range(count):
            encoded = m.bd(table + (start + slot) * 4)
            kind, index = encoded >> 29, encoded & 0x1fffffff
            row = dict(slot=slot, offset=hex(0xd0 + slot * 8), kind=kind,
                       kindDomain="EncodedMethodIndexKind", methodIndex=index,
                       methodIndexDomain="MethodDefinitionIndex" if kind == 3 else "Generic/non-definition index; unresolved")
            if kind == 3:
                row["method"] = self.method(index)
                row["isMethodDefinitionSlot"] = row["method"]["vtableSlot"] == slot
            else:
                row["limitation"] = "Encoded generic/non-definition method; not resolved as a direct method."
            rows.append(row)
        return dict(classInfo=cls, vtableBegin=start, vtableCount=count, rows=rows,
                    slotDomain="ClassVtableRow", runtimeDispatchResolved=False,
                    limitation="One method may appear at multiple rows. MethodInfo.vtableSlot is a separate value; interface offsets and runtime/inflated table bases are not resolved.")

    def class_info(self, definition):
        cls = self.definition(definition)
        return dict(classInfo=cls, aliases=[self.type(row["index"]) for row in self.m.definition_aliases(definition)],
                    fields=self.fields(definition), properties=self.properties(definition),
                    methods=self.methods(definition), vtable=self.vtable(definition))

    def instructions(self, start, end):
        require(type(start) is int and type(end) is int and 0 <= start < end and end - start <= 2 * 1024 * 1024, "CODE_RANGE_1_TO_2M")
        from capstone.x86_const import X86_OP_MEM, X86_REG_RIP
        raw = self.m.get(start, end - start)
        rows = []
        for ins in self.m.md.disasm(raw, start):
            refs = [hex(ins.address + ins.size + op.mem.disp) for op in ins.operands
                    if op.type == X86_OP_MEM and op.mem.base == X86_REG_RIP]
            rows.append(dict(rva=hex(ins.address), size=ins.size, hex=ins.bytes.hex(),
                             mnemonic=ins.mnemonic, operands=ins.op_str, ripTargets=refs))
        covered = sum(row["size"] for row in rows)
        return dict(start=hex(start), end=hex(end), byteCount=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                    decodedBytes=covered, linearDecodeComplete=covered == len(raw),
                    undecodedTailHex=raw[covered:covered + 64].hex(), instructions=rows,
                    limitation="Linear decode and PE unwind bounds are not a control-flow proof; embedded tables and unreachable bytes may be present.")

    def dump(self, rva, *, leaf_bytes=256):
        require(1 <= leaf_bytes <= 65536, "LEAF_BYTE_BOUND")
        bounds = self.m.containing(rva)
        start, end = bounds if bounds else (rva, rva + leaf_bytes)
        data = self.instructions(start, end)
        data.update(requestedRva=hex(rva), unwindBounds=[hex(x) for x in bounds] if bounds else None,
                    methods=self.method_at(start), exactMethodAtRequestedRva=self.method_at(rva) if rva != start else None)
        return data

    def usage(self, index):
        require(0 <= index < 311730, "USAGE_INDEX_RANGE")
        data = self.m.usage(index)
        for row in data["entries"]:
            row["kindDomain"] = "MetadataUsageKind"
            if row["kind"] == 1:
                row["type"] = self.type(row["source"])
                if row["type"]["definitionIndex"] is not None:
                    row["definition"] = row["type"]["definition"]
            elif row["kind"] == 3:
                row["method"] = self.method(row["source"])
            elif row["kind"] == 4:
                row["fieldReference"] = self.field_reference(row["source"])
        return data

    def field_reference(self, index):
        m = self.m
        at = i32(u32(m.d(m.header + 0x9c) + 0xe6d5928c)) + index * 8
        mix = u32(index * 0x9a864480)
        type_index = u32(m.bd(at) + mix + 0x85fc4cb6)
        ordinal = u32((m.bd(at + 4) ^ 0x747bb38b) + mix + 0x01c1c314)
        typed = self.type(type_index)
        result = dict(type=typed, fieldOrdinal=ordinal, fieldOrdinalDomain="DeclaredFieldOrdinal",
                      fieldReferenceIndex=index, indexDomain="FieldReferenceIndex", sourceRva="0x5244c8")
        if typed["definitionIndex"] is not None:
            fields = self.fields(typed["definitionIndex"])
            require(ordinal < fields["fieldCount"], "FIELD_REFERENCE_OUTSIDE_CLASS")
            result["field"] = fields["fields"][ordinal]
        else:
            result["limitation"] = "Generic/non-definition field owner needs inflation; no guessed field."
        return result

    def pairs(self):
        if self._pairs is not None:
            return self._pairs
        m = self.m
        count = u32(m.d(m.header + 0x1a0) + 0x80130d0f) // 4 - 1
        bounds_at = i32(m.d(m.header + 0x19c)) ^ 0x159fbc84
        pairs_at = i32(m.d(m.header + 0x14c)) ^ 0x2f249c2f
        bounds = []
        for i in range(count + 1):
            mix = u64(u64((u64(i * 0x6536) ^ 0x138d67f3) * 0x44b1aad4) + 0x1f9ea55ad057d0) >> 21
            bounds.append(u32(u32(mix) * 0xd0dc29d5 + (m.bd(bounds_at + i * 4) ^ 0x15a6f604) + 0xe6495e3d))
        require(bounds[0] == 0 and bounds[-1] == 788057 and all(a <= b for a, b in zip(bounds, bounds[1:])), "USAGE_PAIR_BOUNDS_CHANGED")
        fields = {0:0x38, 1:0x50, 2:None, 3:8, 4:0x58, 5:0x28, 6:8, 7:0x18}
        rows = []
        for j in range(bounds[-1]):
            key = u32((u32(u64(j * 0x3c5f6dc3f5d0) >> 20) ^ 0x615eb706) + 0x63d46a21)
            encoded = m.bd(pairs_at + j * 8 + 4) ^ key ^ 0x5cd30101
            kind, source = encoded >> 29, encoded & 0x1fffffff
            destination = key ^ u32(m.bd(pairs_at + j * 8) + 0x8ab89515)
            actual = destination & 0xffffff if kind in (0, 7) else destination
            field = fields[kind]
            slot = m.q(m.registration + field) - m.base + actual * 8 if field is not None else None
            rows.append(dict(pair=j, usage=bisect.bisect_right(bounds, j) - 1, kind=kind, kindDomain="MetadataUsageKind",
                             source=source, destination=destination, slot=hex(slot) if slot is not None else None))
        self._pairs, self._usage_bounds = rows, bounds
        return rows

    def bindings(self, *, slot=None, literal=None, definition=None):
        require(sum(x is not None for x in (slot, literal, definition)) == 1, "ONE_BINDING_FILTER_REQUIRED")
        sources = None
        if definition is not None:
            self.definition(definition)
            sources = {x["index"] for x in self.m.definition_aliases(definition)}
        rows = [dict(row) for row in self.pairs() if
                (slot is not None and row["slot"] == hex(slot)) or
                (literal is not None and row["kind"] == 5 and row["source"] == literal) or
                (sources is not None and row["kind"] in (1, 7) and row["source"] in sources)]
        for row in rows:
            if row["kind"] == 5:
                row["literal"] = self.m.literal(row["source"])
            if row["kind"] == 1:
                row["type"] = self.type(row["source"])
            if row["kind"] == 3:
                row["method"] = self.method(row["source"])
        return dict(rows=rows, pairCount=788057, runtimeSlotValueRead=False)

    def literals(self, text, *, regex=False, limit=100):
        require(1 <= limit <= 10000, "LITERAL_LIMIT")
        pattern = re.compile(text, re.I) if regex else None
        sources = sorted({row["source"] for row in self.pairs() if row["kind"] == 5})
        rows, matched = [], 0
        for source in sources:
            item = self.m.literal(source)
            if pattern.search(item["utf8"]) if regex else text.casefold() in item["utf8"].casefold():
                matched += 1
                if len(rows) < limit:
                    rows.append(item)
        return dict(rows=rows, matched=matched, limit=limit, truncated=matched > limit,
                    searchedLiteralCount=len(sources), scope="literal sources referenced by current metadataUsagePairs")

    def usage_callers(self, groups):
        """Regenerate the exact immediate-call index; never trust stale cache."""
        groups = set(groups)
        rows, total, dynamic = [], 0, 0
        m = self.m
        for _, va, size, offset, flags in m.sections:
            if not flags & 0x20000000:
                continue
            raw = m.data[offset:offset + size]
            for match in re.finditer(b"\xe8", raw):
                pos = match.start()
                if pos + 5 > len(raw) or va + pos + 5 + struct.unpack_from("<i", raw, pos + 1)[0] != 0x524250:
                    continue
                total += 1
                if pos < 5 or raw[pos - 5] != 0xb9:
                    dynamic += 1
                    continue
                group = struct.unpack_from("<I", raw, pos - 4)[0]
                if group not in groups:
                    continue
                point = va + pos
                bounds = m.containing(point)
                if not bounds:
                    continue
                instructions = self.instructions(*bounds)["instructions"]
                by_rva = {int(i["rva"], 16): i for i in instructions}
                before, call = by_rva.get(point - 5), by_rva.get(point)
                if before and call and before["mnemonic"] == "mov" and before["operands"] == "ecx, " + hex(group) and call["mnemonic"] == "call" and call["operands"] == "0x524250":
                    rows.append(dict(usage=group, callRva=hex(point), function=[hex(x) for x in bounds],
                                     methods=self.method_at(bounds[0]), instructionBytes=raw[pos - 5:pos + 5].hex()))
        return dict(rows=rows, exactRel32CandidateCount=total, nonImmediateNotAttributed=dynamic,
                    coverage="Exact mov ecx,imm32; call 524250 instructions inside PE unwind function boundaries. Register-fed/indirect initializers are not attributed.")

    def binding_xrefs(self, *, slot=None, literal=None, definition=None):
        bindings = self.bindings(slot=slot, literal=literal, definition=definition)
        pairs = bindings["rows"]
        callers = self.usage_callers({row["usage"] for row in pairs})
        wanted = {row["slot"] for row in pairs if row["slot"]}
        functions = {tuple(int(v, 16) for v in row["function"]) for row in callers["rows"]}
        refs = []
        for bounds in sorted(functions):
            for ins in self.instructions(*bounds)["instructions"]:
                hits = sorted(set(ins["ripTargets"]) & wanted)
                if hits:
                    refs.append(dict(function=[hex(x) for x in bounds], methods=self.method_at(bounds[0]),
                                     instruction=ins, slots=hits))
        return dict(bindings=bindings, initializerCallers=callers, ripReferences=refs,
                    coverage="Real RIP references within the exact initializer caller functions for these metadata usage pairs. Does not claim all code references; use rip-xrefs with explicit range or --all-unwind-functions for a wider scan.",
                    literalIndexImmediateScanUsed=False, runtimeSlotValueRead=False)

    def rip_xrefs(self, targets, *, start=None, end=None, all_unwind=False, limit=10000):
        require(1 <= len(targets) <= 32 and 1 <= limit <= 100000, "XREF_BOUNDS")
        require(bool(all_unwind) != bool(start is not None and end is not None), "EXACT_RANGE_OR_ALL_UNWIND_REQUIRED")
        wanted = {hex(value) for value in targets}
        rows, ranges, incomplete, truncated = [], 0, 0, False
        spans = self.m.funcs if all_unwind else [(start, end)]
        for a, b in spans:
            body = self.instructions(a, b)
            ranges += 1
            incomplete += not body["linearDecodeComplete"]
            for ins in body["instructions"]:
                hits = sorted(set(ins["ripTargets"]) & wanted)
                if hits:
                    if len(rows) == limit:
                        truncated = True
                        break
                    rows.append(dict(range=[hex(a), hex(b)], instruction=ins, targets=hits,
                                     methods=self.method_at(a)))
            if truncated:
                break
        return dict(rows=rows, scannedRanges=ranges, incompleteLinearRanges=incomplete, truncated=truncated,
                    coverage="All linearly decoded instructions in explicit range" if not all_unwind else "PE unwind function ranges only; leaf code without unwind and embedded undecoded tails are excluded.")

    def callers(self, targets, *, limit=10000):
        wanted = set(targets)
        require(1 <= len(wanted) <= 32 and 1 <= limit <= 100000, "CALLER_BOUNDS")
        rows, truncated = [], False
        m = self.m
        for _, va, size, offset, flags in m.sections:
            if not flags & 0x20000000:
                continue
            raw = m.data[offset:offset + size]
            for match in re.finditer(b"[\xe8\xe9]", raw):
                pos = match.start()
                if pos + 5 > len(raw):
                    continue
                target = va + pos + 5 + struct.unpack_from("<i", raw, pos + 1)[0]
                if target not in wanted:
                    continue
                point = va + pos
                bounds = m.containing(point)
                if not bounds:
                    continue
                ins = next((x for x in self.instructions(*bounds)["instructions"] if int(x["rva"], 16) == point), None)
                if ins and ins["mnemonic"] in ("call", "jmp") and ins["operands"] == hex(target):
                    if len(rows) == limit:
                        truncated = True
                        break
                    rows.append(dict(target=hex(target), instruction=ins, function=[hex(x) for x in bounds], methods=self.method_at(bounds[0])))
            if truncated:
                break
        return dict(rows=rows, truncated=truncated, coverage="Validated direct rel32 call/jmp instructions in PE unwind ranges only; indirect callers are excluded.")
