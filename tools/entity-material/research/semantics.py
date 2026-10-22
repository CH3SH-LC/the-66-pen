"""Metadata vocabulary only; no IO, game component inference, or ABI guessing."""

TYPE_ENUM = {
    0x00: "END", 0x01: "VOID", 0x02: "BOOLEAN", 0x03: "CHAR",
    0x04: "I1", 0x05: "U1", 0x06: "I2", 0x07: "U2", 0x08: "I4",
    0x09: "U4", 0x0a: "I8", 0x0b: "U8", 0x0c: "R4", 0x0d: "R8",
    0x0e: "STRING", 0x0f: "PTR", 0x10: "BYREF", 0x11: "VALUETYPE",
    0x12: "CLASS", 0x13: "VAR", 0x14: "ARRAY", 0x15: "GENERICINST",
    0x16: "TYPEDBYREF", 0x18: "I", 0x19: "U", 0x1b: "FNPTR",
    0x1c: "OBJECT", 0x1d: "SZARRAY", 0x1e: "MVAR", 0x1f: "CMOD_REQD",
    0x20: "CMOD_OPT", 0x21: "INTERNAL", 0x40: "MODIFIER", 0x41: "SENTINEL",
    0x45: "PINNED", 0x55: "ENUM",
}
ACCESS = {0: "CompilerControlled", 1: "Private", 2: "FamANDAssem", 3: "Assembly",
          4: "Family", 5: "FamORAssem", 6: "Public", 7: "Reserved"}


def attributes(value, domain):
    """The same bit can mean different things in each ECMA-335 domain."""
    if domain == "MethodAttributes":
        bits = {0x8: "UnmanagedExport", 0x10: "Static", 0x20: "Final", 0x40: "Virtual",
                0x80: "HideBySig", 0x100: "NewSlot", 0x200: "CheckAccessOnOverride",
                0x400: "Abstract", 0x800: "SpecialName", 0x1000: "RTSpecialName",
                0x2000: "PInvokeImpl", 0x4000: "HasSecurity", 0x8000: "RequireSecObject"}
    elif domain == "FieldAttributes":
        bits = {0x10: "Static", 0x20: "InitOnly", 0x40: "Literal", 0x80: "NotSerialized",
                0x100: "HasFieldRVA", 0x200: "SpecialName", 0x400: "RTSpecialName",
                0x1000: "HasFieldMarshal", 0x2000: "PInvokeImpl", 0x8000: "HasDefault"}
    elif domain == "ParameterAttributes":
        bits = {0x1: "In", 0x2: "Out", 0x4: "Lcid", 0x8: "Retval", 0x10: "Optional",
                0x1000: "HasDefault", 0x2000: "HasFieldMarshal"}
    else:
        raise ValueError("UNSUPPORTED_ATTRIBUTE_DOMAIN")
    known = sum(bits) | (7 if domain != "ParameterAttributes" else 0)
    result = dict(value=value, hex=hex(value), domain=domain,
                  flags=[name for bit, name in bits.items() if value & bit],
                  unknownBits=hex(value & ~known), vocabulary="ECMA-335 metadata flags")
    if domain != "ParameterAttributes":
        result["visibility"] = ACCESS[value & 7]
    return result


def domains():
    return dict(
        schemaVersion=2,
        domains={
            "TypeDefinitionIndex": "Class/struct definition table index; argument to class/fields/methods/properties/vtable.",
            "Il2CppTypeIndex": "Index into the registered 16-byte Il2CppType array; argument to type. It is not a TypeDefinitionIndex.",
            "Il2CppTypeEnum": "Representation category in Il2CppType byte +10. Decimal 18 (0x12) means CLASS, never runtime component 18.",
            "FieldDefinitionIndex": "Global field definition table index. fields().fields[].fieldIndex is in this domain.",
            "DeclaredFieldOrdinal": "Zero-based position within one declaring class; requires the class definition index.",
            "MethodDefinitionIndex": "Global method definition index; argument to method. RVA lookup can return multiple definitions.",
            "ParameterDefinitionIndex": "Global parameter definition index. Parameters are declared arguments excluding implicit this.",
            "MetadataUsageKind": "High three bits in an encoded metadata usage. Distinct from Il2CppTypeEnum and gameplay kind.",
            "RuntimeComponentKind": "Gameplay component discriminator; this instrument does not infer it from any metadata index, type kind, or name.",
            "SerializedFieldNumber": "Wire/schema field number; this instrument does not infer it from fieldIndex or ordinal.",
        },
        attributeDomains={"MethodAttributes.0x10": "Static", "FieldAttributes.0x10": "Static",
                          "ParameterAttributes.0x10": "Optional"},
        nativeAbiResolved=False,
        limitation="Static/instance is metadata proof only. Hidden MethodInfo/context, value-type this, return buffers, thunks and register placement require separate ABI evidence.")
