using System;
using System.Collections.Generic;
using System.Reflection;
using System.Reflection.Emit;

namespace Miliastra.EditorBridge;

// Bounded, read-only verifier for the runtime-emitted proxy delegates the native editor uses
// in place of some interface slots. The editor (ConfuserEx) realises those proxies as
// DynamicMethod-backed delegates whose IL loads the declared parameters and then calls the
// real method; "the slot is a delegate that points at X" is therefore a claim about emitted
// IL, not about a MethodInfo name. This class checks that claim at the IL level.
//
// Evidence for the private runtime layout this decodes against:
//   .runtime/verification/update-repair-20260925/adapter-port/dynamic-resolver-corelib.cs
//   .runtime/verification/update-repair-20260925/adapter-port/dynamic-scope-corelib.cs
// Both are decompilations of System.Private.CoreLib for the runtime the bridge runs on.
//
// What a positive result means, and what it does not:
//   * It never invokes the delegate, the target method or any constructor; it never asks the
//     inspected method for an ILGenerator or DynamicILInfo. The only reads are metadata plus
//     GetValue on the handful of BCL fields the DynamicMethod resolver itself stores.
//   * Verified == true means: the proxy's emitted IL loads exactly the declared arguments and
//     calls exactly the expected MethodInfo, resolved through the runtime's own token scope.
//     It is NOT a claim that calling the delegate is safe, and says nothing about what the
//     target method does when called.
//   * Everything is fail-closed. An unknown runtime layout, a signature that is merely
//     similar, a cast that is merely plausible, or any IL shape not modelled in full here is
//     a rejection with an exact reason, not a pass.
internal static class DynamicProxyVerifier
{
    const string Prefix = "DYNAMIC_PROXY_VERIFY_";
    const BindingFlags InstanceAny = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
    const int MaxIlBytes = 256;
    const int MaxTokens = 128;

    // ---- result surface -------------------------------------------------------------

    // Strongly typed, all-public-property evidence. Deliberately excludes the raw token table:
    // only tokens that the verified IL actually used are reported.
    internal sealed record Evidence
    {
        public string IlHex { get; init; } = "";
        public int IlLength { get; init; }
        public int StackSize { get; init; } = -1;
        public string LocalSignatureHex { get; init; } = "";
        public string DynamicSignature { get; init; } = "";
        public string ExpectedSignature { get; init; } = "";
        public string DynamicMethodName { get; init; } = "";
        public string CoreLibVersion { get; init; } = "";
        public string CoreLibMvid { get; init; } = "";
        public int ArgumentCount { get; init; }
        public string ForwardingShape { get; init; } = "";
        public string CallOpcode { get; init; } = "";
        public int CallToken { get; init; }
        public string TokenKind { get; init; } = "";
        public string ResolvedDeclaringType { get; init; } = "";
        public string ResolvedSignature { get; init; } = "";
        public string ResolvedMvid { get; init; } = "";
        public int ResolvedMetadataToken { get; init; }
        public string ExpectedDeclaringType { get; init; } = "";
        public string ExpectedMvid { get; init; } = "";
        public int ExpectedMetadataToken { get; init; }
        public string[] Casts { get; init; } = Array.Empty<string>();
        public bool LayoutUnchangedAfterDecode { get; init; }
    }

    internal sealed record Result
    {
        public bool Verified { get; init; }
        public string Reason { get; init; } = "";
        public Evidence? Evidence { get; init; }
    }

    // ---- entry point ----------------------------------------------------------------

    internal static Result Verify(Delegate proxy, MethodInfo expected)
    {
        var capture = new Capture();
        try
        {
            var evidence = VerifyCore(proxy, expected, capture);
            return new Result { Verified = true, Reason = Prefix + "OK", Evidence = evidence };
        }
        catch (Reject reject)
        {
            return new Result { Verified = false, Reason = reject.Message, Evidence = capture.Snapshot() };
        }
        catch (Exception ex)
        {
            // Nothing is allowed to escape; an unexpected failure is still a rejection.
            return new Result
            {
                Verified = false,
                Reason = Prefix + "EXCEPTION:" + ex.GetType().Name + ": " + ex.Message,
                Evidence = capture.Snapshot()
            };
        }
    }

    static Evidence VerifyCore(Delegate proxy, MethodInfo expected, Capture capture)
    {
        capture.CoreLibVersion = typeof(object).Assembly.GetName().Version?.ToString() ?? "unknown";
        capture.CoreLibMvid = SafeMvid(typeof(object).Module);

        if (proxy is null) throw R("PROXY_NULL");
        if (expected is null) throw R("EXPECTED_NULL");

        // One invocation, no bound receiver: a bound or multicast delegate cannot be a bare
        // emitted static proxy, and its Method would not carry the whole story.
        if (proxy.GetInvocationList().Length != 1) throw R("PROXY_MULTICAST");
        if (proxy.Target is not null) throw R("PROXY_HAS_TARGET");

        var method = proxy.Method;
        if (method.GetType() != typeof(DynamicMethod))
            throw R("PROXY_METHOD_NOT_DYNAMICMETHOD:" + method.GetType().FullName);
        var dm = (DynamicMethod)method;
        if (!dm.IsStatic) throw R("DYNAMIC_METHOD_NOT_STATIC");

        var invoke = proxy.GetType().GetMethod("Invoke", BindingFlags.Public | BindingFlags.Instance);
        if (invoke is null) throw R("DELEGATE_INVOKE_MISSING");

        // The expected method must be an ordinary metadata method this verifier can compare
        // against by module + token. Anything generic needs context the IL does not carry,
        // and an emitted method carries no stable module/token to compare against.
        if (!IsOrdinaryMetadataMethod(expected))
            throw R("EXPECTED_NOT_ORDINARY_METHODINFO:" + expected.GetType().FullName);
        if (expected.IsAbstract) throw R("EXPECTED_ABSTRACT");
        if (expected.IsGenericMethod || expected.IsGenericMethodDefinition || expected.ContainsGenericParameters)
            throw R("EXPECTED_GENERIC");
        var declaring = expected.DeclaringType;
        if (declaring is null) throw R("EXPECTED_DECLARING_TYPE_NULL");
        if (declaring.IsGenericType) throw R("EXPECTED_DECLARING_TYPE_GENERIC:" + Describe(declaring));
        if (declaring.IsValueType) throw R("EXPECTED_DECLARING_TYPE_VALUE_TYPE:" + Describe(declaring));
        if ((expected.CallingConvention & CallingConventions.VarArgs) != 0) throw R("EXPECTED_VARARG");

        capture.ExpectedSignature = EditorBindingProfile.DescribeMethodSignature(expected);
        capture.ExpectedDeclaringType = Describe(declaring);
        capture.ExpectedMvid = SafeMvid(expected.Module);
        capture.ExpectedMetadataToken = SafeToken(expected);
        if (capture.ExpectedMetadataToken < 0) throw R("EXPECTED_METADATA_TOKEN_UNAVAILABLE");

        capture.DynamicSignature = EditorBindingProfile.DescribeMethodSignature(dm);
        capture.DynamicMethodName = dm.Name ?? "";

        // The dynamic method must have exactly the delegate's Invoke signature.
        var dynParams = dm.GetParameters();
        var invokeParams = invoke.GetParameters();
        if (dynParams.Length != invokeParams.Length) throw R("DYNAMIC_PARAM_COUNT_VS_DELEGATE");
        for (int i = 0; i < dynParams.Length; i++)
            if (dynParams[i].ParameterType != invokeParams[i].ParameterType)
                throw R("DYNAMIC_PARAM_TYPE_VS_DELEGATE:" + i + ":" + Describe(dynParams[i].ParameterType));
        if (dm.ReturnType != invoke.ReturnType)
            throw R("DYNAMIC_RETURN_VS_DELEGATE:" + Describe(dm.ReturnType));

        // Stack arguments the call site must supply: instance receiver first, then parameters.
        var targetParamInfos = expected.GetParameters();
        int argCount = targetParamInfos.Length + (expected.IsStatic ? 0 : 1);
        if (dynParams.Length != argCount)
            throw R("DYNAMIC_PARAM_COUNT_VS_TARGET:" + dynParams.Length.ToString() + "!=" + argCount.ToString());
        var expectedArgs = new Type[argCount];
        int offset = 0;
        if (!expected.IsStatic) { expectedArgs[0] = declaring; offset = 1; }
        for (int i = 0; i < targetParamInfos.Length; i++) expectedArgs[offset + i] = targetParamInfos[i].ParameterType;

        if (dm.ReturnType != expected.ReturnType) throw R("RETURN_TYPE_MISMATCH:" + Describe(dm.ReturnType));
        for (int i = 0; i < dynParams.Length; i++)
        {
            var t = dynParams[i].ParameterType;
            if (t.IsByRef || t.IsPointer || t.IsValueType) throw R("PARAM_TYPE_UNSUPPORTED:" + i + ":" + Describe(t));
        }
        // An exact value return stays on the evaluation stack between call and ret;
        // no boxing, conversion, copying or construction is admitted by the grammar.
        // This includes the editor's one-uint request receipt struct. All three
        // signatures (delegate, dynamic method and expected target) already agree.
        if (dm.ReturnType.IsByRef || dm.ReturnType.IsPointer || dm.ReturnType.IsFunctionPointer ||
            dm.ReturnType.IsByRefLike || dm.ReturnType.ContainsGenericParameters)
            throw R("RETURN_TYPE_UNSUPPORTED:" + Describe(dm.ReturnType));

        // ---- private runtime layout, asserted exactly ---------------------------------
        var layout = ResolveLayout();

        var resolver = layout.ResolverField.GetValue(dm);
        if (resolver is null || resolver.GetType() != layout.ResolverType) throw R("RESOLVER_FIELD_UNEXPECTED");
        if (!ReferenceEquals(layout.MethodField.GetValue(resolver), dm)) throw R("RESOLVER_METHOD_FIELD_MISMATCH");

        var ilRef = layout.CodeField.GetValue(resolver) as byte[];
        if (ilRef is null) throw R("RESOLVER_CODE_NULL");
        if (ilRef.Length < 1 || ilRef.Length > MaxIlBytes) throw R("IL_LENGTH_OUT_OF_RANGE:" + ilRef.Length.ToString());
        var code = (byte[])ilRef.Clone();
        capture.IlHex = Hex(code);
        capture.IlLength = code.Length;

        var scope = layout.ScopeField.GetValue(resolver);
        if (scope is null || scope.GetType() != layout.ScopeType) throw R("RESOLVER_SCOPE_UNEXPECTED");
        var tokens = layout.TokensField.GetValue(scope) as List<object>;
        if (tokens is null) throw R("SCOPE_TOKENS_NULL");
        if (tokens.Count < 1 || tokens.Count > MaxTokens) throw R("SCOPE_TOKEN_COUNT_OUT_OF_RANGE:" + tokens.Count.ToString());
        var tokenSnapshot = tokens.ToArray();
        if (tokenSnapshot[0] is not null) throw R("SCOPE_TOKEN_ZERO_NOT_NULL");

        var localSig = layout.LocalSignatureField.GetValue(resolver) as byte[];
        if (localSig is null) throw R("LOCAL_SIGNATURE_NULL");
        if (localSig.Length > 3) throw R("LOCAL_SIGNATURE_LENGTH_UNSUPPORTED:" + localSig.Length);
        var localSnapshot = (byte[])localSig.Clone();
        capture.LocalSignatureHex = Hex(localSnapshot);
        if (!IsZeroLocals(localSnapshot)) throw R("LOCAL_SIGNATURE_NOT_ZERO_LOCALS:" + capture.LocalSignatureHex);

        var exceptions = layout.ExceptionsField.GetValue(resolver) as Array;
        if (exceptions is not null && exceptions.Length != 0)
            throw R("EXCEPTION_CLAUSES_PRESENT:" + exceptions.Length.ToString());
        var ehHeader = layout.ExceptionHeaderField.GetValue(resolver) as byte[];
        if (ehHeader is not null && ehHeader.Length != 0)
            throw R("EXCEPTION_HEADER_PRESENT:" + ehHeader.Length.ToString());

        capture.ArgumentCount = argCount;
        if (layout.StackSizeField is not null && layout.StackSizeField.FieldType == typeof(int))
            capture.StackSize = (int)layout.StackSizeField.GetValue(resolver)!; // diagnostic only

        // ---- strict IL grammar --------------------------------------------------------
        // The 7.1 emitter OpFPXw6L1ZQ uses an object receiver, Emit(Ldarg_S, int 4)
        // (which leaves exactly three zero bytes), then tail.callvirt. This exact
        // 17-byte shape is observed on both live proxies; no arbitrary nop/tail or
        // erased-parameter pattern is admitted. See the adjacent offline evidence.
        bool editorTailForwarder = !expected.IsStatic && dynParams.Length == 5 &&
            dynParams[0].ParameterType == typeof(object) && IsEditorTailForwarder(code);
        capture.ForwardingShape = editorTailForwarder ? "editor-7.1-object-receiver-tailcallvirt" : "explicit-arguments-call-ret";
        int pos = 0;
        for (int i = 0; i < argCount; i++)
        {
            int index = ReadArg(code, ref pos, i);
            if (index != i) throw R("IL_ARG_ORDER:" + index.ToString() + "!=" + i.ToString());

            var dynType = dynParams[i].ParameterType;
            var expType = expectedArgs[i];
            if (dynType != expType)
            {
                // Only this exact editor template erases the reference receiver.
                // The receiver value is not inspected or invoked; the call token is
                // still required to resolve to the precise non-overridable target.
                if (editorTailForwarder && i == 0 && dynType == typeof(object) && expType == declaring)
                    continue;
                if (editorTailForwarder) throw R("EDITOR_TAIL_NON_RECEIVER_TYPE_MISMATCH:" + i);
                // Only a legal reference conversion may bridge the two, and it must be spelled
                // out as an explicit castclass to exactly the expected type.
                if (!IsLegalReferenceConversion(dynType, expType))
                    throw R("CAST_ILLEGAL:" + i.ToString() + ":" + Describe(dynType) + "->" + Describe(expType));
                if (pos >= code.Length || code[pos] != 0x74) throw R("IL_MISSING_CASTCLASS:" + i.ToString());
                pos++;
                if (pos + 4 > code.Length) throw R("IL_TRUNCATED_CAST_TOKEN");
                uint castToken = ReadUInt32(code, pos);
                pos += 4;
                if ((castToken >> 24) != 0x02)
                    throw R("CAST_TOKEN_PREFIX_NOT_TYPE:0x" + (castToken >> 24).ToString("X2"));
                var castTo = ResolveTypeToken(castToken, tokenSnapshot);
                if (castTo != expType)
                    throw R("CAST_TOKEN_TYPE_MISMATCH:" + Describe(castTo) + "!=" + Describe(expType));
                capture.Casts.Add(Describe(expType));
            }
            else if (pos < code.Length && code[pos] == 0x74)
            {
                throw R("CAST_NOT_ALLOWED_SAME_TYPE:" + i.ToString());
            }
        }

        if (editorTailForwarder)
        {
            if (pos != 6) throw R("EDITOR_TAIL_ARGUMENT_LAYOUT_MISMATCH");
            pos += 5; // exactly 00 00 00 FE 14, already matched in full above
        }
        if (pos >= code.Length) throw R("IL_MISSING_CALL");
        byte callOp = code[pos];
        pos++;
        if (callOp != 0x28 && callOp != 0x6F) throw R("IL_EXPECTED_CALL:0x" + callOp.ToString("X2"));
        if (pos + 4 > code.Length) throw R("IL_TRUNCATED_CALL_TOKEN");
        uint callToken = ReadUInt32(code, pos);
        pos += 4;
        if ((callToken >> 24) != 0x06)
            throw R("CALL_TOKEN_PREFIX_NOT_METHOD:0x" + (callToken >> 24).ToString("X2"));

        // callvirt dispatches virtually; on an overridable target the callee is not
        // determined by the token, so only non-virtual, final or sealed targets are allowed.
        if (callOp == 0x6F)
        {
            if (expected.IsStatic) throw R("CALLVIRT_ON_STATIC_TARGET");
            if (expected.IsVirtual && !expected.IsFinal && !declaring.IsSealed)
                throw R("CALLVIRT_ON_OVERRIDABLE_TARGET");
        }

        var resolved = ResolveCallToken(callToken, tokenSnapshot, layout, out string tokenKind);
        capture.CallOpcode = callOp == 0x28 ? "call" : "callvirt";
        capture.CallToken = unchecked((int)callToken);
        capture.TokenKind = tokenKind;

        // Resolved through the runtime's own token scope, so this compares the very method the
        // JIT would bind, not a name that merely looks right.
        if (!IsOrdinaryMetadataMethod(resolved))
            throw R("CALL_TOKEN_NOT_ORDINARY_METHODINFO:" + resolved.GetType().FullName);
        if (resolved.IsGenericMethod || resolved.ContainsGenericParameters) throw R("CALL_TOKEN_GENERIC_METHOD");
        if (!ReferenceEquals(resolved.Module, expected.Module)) throw R("CALL_TOKEN_MODULE_MISMATCH");
        if (resolved.Module.ModuleVersionId != expected.Module.ModuleVersionId) throw R("CALL_TOKEN_MVID_MISMATCH");

        capture.ResolvedDeclaringType = Describe(resolved.DeclaringType);
        capture.ResolvedSignature = EditorBindingProfile.DescribeMethodSignature(resolved);
        capture.ResolvedMvid = SafeMvid(resolved.Module);
        capture.ResolvedMetadataToken = SafeToken(resolved);

        if (capture.ResolvedMetadataToken != capture.ExpectedMetadataToken)
            throw R("CALL_TOKEN_METADATA_TOKEN_MISMATCH:" +
                capture.ResolvedMetadataToken.ToString() + "!=" + capture.ExpectedMetadataToken.ToString());
        if (resolved.DeclaringType != declaring)
            throw R("CALL_TOKEN_DECLARING_TYPE_MISMATCH:" + capture.ResolvedDeclaringType);
        if (resolved.Name != expected.Name) throw R("CALL_TOKEN_NAME_MISMATCH:" + resolved.Name);
        if (resolved.IsStatic != expected.IsStatic) throw R("CALL_TOKEN_STATIC_MISMATCH");
        if (capture.ResolvedSignature != capture.ExpectedSignature)
            throw R("CALL_TOKEN_SIGNATURE_MISMATCH:" + capture.ResolvedSignature);

        if (pos >= code.Length || code[pos] != 0x2A) throw R("IL_MISSING_RET");
        pos++;
        if (pos != code.Length) throw R("IL_TRAILING_BYTES:" + (code.Length - pos).ToString());

        // Nothing decoded above may have written back into the resolver: every reference and
        // the IL bytes themselves must still be what we captured at the start.
        bool unchanged =
            ReferenceEquals(layout.ResolverField.GetValue(dm), resolver) &&
            ReferenceEquals(layout.MethodField.GetValue(resolver), dm) &&
            ReferenceEquals(layout.CodeField.GetValue(resolver), ilRef) &&
            ReferenceEquals(layout.ScopeField.GetValue(resolver), scope) &&
            ReferenceEquals(layout.LocalSignatureField.GetValue(resolver), localSig) &&
            ReferenceEquals(layout.ExceptionsField.GetValue(resolver), exceptions) &&
            ReferenceEquals(layout.ExceptionHeaderField.GetValue(resolver), ehHeader) &&
            ReferenceEquals(layout.TokensField.GetValue(scope), tokens) &&
            TokenSnapshotEqual(tokenSnapshot, tokens) &&
            ByteEqual(localSnapshot, localSig) &&
            ByteEqual(code, layout.CodeField.GetValue(resolver) as byte[]) &&
            resolved.Equals(ResolveCallToken(callToken, tokenSnapshot, layout, out _));
        capture.LayoutUnchangedAfterDecode = unchanged;
        if (!unchanged) throw R("RESOLVER_LAYOUT_CHANGED_DURING_DECODE");

        return capture.Snapshot();
    }

    // ---- runtime layout -------------------------------------------------------------

    sealed class Layout
    {
        public Type ResolverType = null!;
        public Type ScopeType = null!;
        public Type GenericMethodInfoType = null!;
        public FieldInfo ResolverField = null!;
        public FieldInfo MethodField = null!;
        public FieldInfo CodeField = null!;
        public FieldInfo ScopeField = null!;
        public FieldInfo LocalSignatureField = null!;
        public FieldInfo ExceptionsField = null!;
        public FieldInfo ExceptionHeaderField = null!;
        public FieldInfo? StackSizeField;
        public FieldInfo TokensField = null!;
        public FieldInfo GmiMethodHandleField = null!;
        public FieldInfo GmiContextField = null!;
    }

    static Layout ResolveLayout()
    {
        int major = Environment.Version.Major;
        if (major != 8 && major != 9) throw R("RUNTIME_VERSION_UNSUPPORTED:" + Environment.Version.ToString());

        // The private classes must come from the CoreLib that owns DynamicMethod -- not from
        // some other assembly that happens to define a same-named type.
        var coreLib = typeof(DynamicMethod).Assembly;
        var resolverType = coreLib.GetType("System.Reflection.Emit.DynamicResolver", false);
        var scopeType = coreLib.GetType("System.Reflection.Emit.DynamicScope", false);
        var gmiType = coreLib.GetType("System.Reflection.Emit.GenericMethodInfo", false);
        if (resolverType is null) throw R("LAYOUT_RESOLVER_TYPE_MISSING");
        if (scopeType is null) throw R("LAYOUT_SCOPE_TYPE_MISSING");
        if (gmiType is null) throw R("LAYOUT_GENERICMETHODINFO_TYPE_MISSING");
        if (!resolverType.IsSealed || !scopeType.IsSealed || !gmiType.IsSealed) throw R("LAYOUT_TYPE_NOT_SEALED");

        FieldInfo Field(Type owner, string name, Func<Type, bool> expectedType, string code)
        {
            var field = owner.GetField(name, InstanceAny);
            if (field is null) throw R("LAYOUT_" + code + "_MISSING");
            if (!expectedType(field.FieldType))
                throw R("LAYOUT_" + code + "_TYPE_MISMATCH:" + Describe(field.FieldType));
            return field;
        }

        return new Layout
        {
            ResolverType = resolverType,
            ScopeType = scopeType,
            GenericMethodInfoType = gmiType,
            ResolverField = Field(typeof(DynamicMethod), "_resolver", t => t == resolverType, "DYNAMICMETHOD_RESOLVER"),
            MethodField = Field(resolverType, "m_method", t => t == typeof(DynamicMethod), "RESOLVER_M_METHOD"),
            CodeField = Field(resolverType, "m_code", t => t == typeof(byte[]), "RESOLVER_M_CODE"),
            ScopeField = Field(resolverType, "m_scope", t => t == scopeType, "RESOLVER_M_SCOPE"),
            LocalSignatureField = Field(resolverType, "m_localSignature", t => t == typeof(byte[]), "RESOLVER_M_LOCALSIGNATURE"),
            ExceptionsField = Field(resolverType, "m_exceptions",
                t => t == coreLib.GetType("System.Reflection.Emit.__ExceptionInfo", false)?.MakeArrayType(), "RESOLVER_M_EXCEPTIONS"),
            ExceptionHeaderField = Field(resolverType, "m_exceptionHeader", t => t == typeof(byte[]), "RESOLVER_M_EXCEPTIONHEADER"),
            // Diagnostic only: absence is not a layout failure.
            StackSizeField = resolverType.GetField("m_stackSize", InstanceAny),
            TokensField = Field(scopeType, "m_tokens",
                t => t.IsGenericType && t.GetGenericTypeDefinition() == typeof(List<>) &&
                     t.GetGenericArguments()[0] == typeof(object), "SCOPE_M_TOKENS"),
            GmiMethodHandleField = Field(gmiType, "m_methodHandle", t => t == typeof(RuntimeMethodHandle), "GMI_M_METHODHANDLE"),
            GmiContextField = Field(gmiType, "m_context", t => t == typeof(RuntimeTypeHandle), "GMI_M_CONTEXT"),
        };
    }

    // ---- token resolution -----------------------------------------------------------

    static MethodInfo ResolveCallToken(uint token, object?[] tokens, Layout layout, out string kind)
    {
        int index = (int)(token & 0xFFFFFF);
        if (index < 1 || index >= tokens.Length) throw R("CALL_TOKEN_INDEX_OUT_OF_RANGE:" + index.ToString());
        object? entry = tokens[index];
        if (entry is null) throw R("CALL_TOKEN_ENTRY_NULL");

        MethodBase resolved;
        if (entry is RuntimeMethodHandle handle)
        {
            kind = "RuntimeMethodHandle";
            resolved = FromHandle(() => MethodBase.GetMethodFromHandle(handle));
        }
        else if (entry.GetType() == layout.GenericMethodInfoType)
        {
            kind = "GenericMethodInfo";
            var methodHandle = (RuntimeMethodHandle)layout.GmiMethodHandleField.GetValue(entry)!;
            var context = (RuntimeTypeHandle)layout.GmiContextField.GetValue(entry)!;
            resolved = FromHandle(() => MethodBase.GetMethodFromHandle(methodHandle, context));
        }
        else
        {
            // Covers DynamicMethod and VarArgMethod entries, which are explicitly not accepted.
            throw R("CALL_TOKEN_UNSUPPORTED_ENTRY:" + entry.GetType().FullName);
        }

        if (resolved is not MethodInfo info)
            throw R("CALL_TOKEN_NOT_A_METHOD:" + (resolved?.GetType().FullName ?? "<null>"));
        return info;
    }

    static Type ResolveTypeToken(uint token, object?[] tokens)
    {
        int index = (int)(token & 0xFFFFFF);
        if (index < 1 || index >= tokens.Length) throw R("CAST_TOKEN_INDEX_OUT_OF_RANGE:" + index.ToString());
        object? entry = tokens[index];
        if (entry is null) throw R("CAST_TOKEN_ENTRY_NULL");
        if (entry is not RuntimeTypeHandle handle)
            throw R("CAST_TOKEN_ENTRY_NOT_RUNTIME_TYPE_HANDLE:" + entry.GetType().FullName);
        return Type.GetTypeFromHandle(handle) ?? throw R("CAST_TOKEN_UNRESOLVED");
    }

    // MethodBase.GetMethodFromHandle is metadata-only: it resolves a handle to the same
    // MethodInfo the runtime would use and executes nothing.
    static MethodBase FromHandle(Func<MethodBase?> resolve)
    {
        try { return resolve() ?? throw R("CALL_TOKEN_RESOLVED_NULL"); }
        catch (Exception ex) { throw R("CALL_TOKEN_RESOLVE_FAILED:" + ex.GetType().Name + ": " + ex.Message); }
    }

    // ---- IL helpers -----------------------------------------------------------------

    // Ordinary means: a real metadata method the runtime itself hands out, not one of the
    // emitted forms (DynamicMethod, MethodBuilder). The runtime's own implementation lives in
    // CoreLib under System.Reflection; the Emit forms live in CoreLib under
    // System.Reflection.Emit, and a foreign subclass is not something this verifier models.
    static bool IsOrdinaryMetadataMethod(MethodInfo method)
    {
        var runtimeMethodType = typeof(MethodInfo).Assembly.GetType("System.Reflection.RuntimeMethodInfo", false);
        return runtimeMethodType is not null && method.GetType() == runtimeMethodType;
    }

    static int ReadArg(byte[] code, ref int pos, int ordinal)
    {
        if (pos >= code.Length) throw R("IL_TRUNCATED_BEFORE_ARG:" + ordinal.ToString());
        byte op = code[pos];
        if (op >= 0x02 && op <= 0x05) { pos += 1; return op - 0x02; }
        if (op == 0x0E)
        {
            if (pos + 2 > code.Length) throw R("IL_TRUNCATED_LDARG_S:" + ordinal.ToString());
            int index = code[pos + 1];
            pos += 2;
            return index;
        }
        if (op == 0xFE)
        {
            if (pos + 4 > code.Length) throw R("IL_TRUNCATED_LDARG:" + ordinal.ToString());
            if (code[pos + 1] != 0x09)
                throw R("IL_UNEXPECTED_OPCODE_ARG:" + ordinal.ToString() + ":FE" + code[pos + 1].ToString("X2"));
            int index = code[pos + 2] | (code[pos + 3] << 8);
            pos += 4;
            return index;
        }
        throw R("IL_UNEXPECTED_OPCODE_ARG:" + ordinal.ToString() + ":0x" + op.ToString("X2"));
    }

    static bool IsEditorTailForwarder(byte[] code)
    {
        ReadOnlySpan<byte> prefix = new byte[] { 0x02, 0x03, 0x04, 0x05, 0x0e, 0x04,
            0x00, 0x00, 0x00, 0xfe, 0x14, 0x6f };
        if (code.Length != 17 || code[16] != 0x2a) return false;
        for (int i = 0; i < prefix.Length; i++) if (code[i] != prefix[i]) return false;
        return true;
    }

    static uint ReadUInt32(byte[] code, int pos)
        => (uint)(code[pos] | (code[pos + 1] << 8) | (code[pos + 2] << 16) | (code[pos + 3] << 24));

    // A castclass between two unrelated reference types would fail at run time, so it is
    // rejected here rather than trusted. No covariance is improvised anywhere else either.
    static bool IsLegalReferenceConversion(Type from, Type to)
    {
        if (from.IsValueType || to.IsValueType) return false;
        if (from.IsByRef || to.IsByRef || from.IsPointer || to.IsPointer) return false;
        return to.IsAssignableFrom(from) || from.IsAssignableFrom(to);
    }

    // Zero locals are spelled as an empty signature array or a LOCAL_SIG header with a
    // compressed count of zero. Anything else means locals exist, which this verifier does
    // not model, so it fails closed rather than guessing.
    static bool IsZeroLocals(byte[] signature)
    {
        if (signature.Length == 0) return true;
        if (signature[0] != 0x07) return false;
        if (signature.Length == 2) return signature[1] == 0x00;
        if (signature.Length == 3) return signature[1] == 0x00 && signature[2] == 0x00;
        return false;
    }

    static bool TokenSnapshotEqual(object?[] snapshot, List<object> tokens)
    {
        if (snapshot.Length != tokens.Count) return false;
        for (int i = 0; i < snapshot.Length; i++)
            if (!ReferenceEquals(snapshot[i], tokens[i])) return false;
        return true;
    }

    static bool ByteEqual(byte[] left, byte[]? right)
    {
        if (right is null || left.Length != right.Length) return false;
        for (int i = 0; i < left.Length; i++) if (left[i] != right[i]) return false;
        return true;
    }

    static string Hex(byte[] bytes) => Convert.ToHexString(bytes);

    static string Describe(Type? type) => type is null ? "<null>" : EditorBindingProfile.DescribeType(type);

    static string SafeMvid(Module module)
    {
        try { return module.ModuleVersionId.ToString(); }
        catch (Exception ex) { return "unavailable:" + ex.GetType().Name; }
    }

    static int SafeToken(MethodBase method)
    {
        try { return method.MetadataToken; }
        catch { return -1; }
    }

    // ---- plumbing -------------------------------------------------------------------

    sealed class Capture
    {
        public int StackSize = -1;
        public string IlHex = "";
        public int IlLength;
        public string LocalSignatureHex = "";
        public string DynamicSignature = "";
        public string ExpectedSignature = "";
        public string DynamicMethodName = "";
        public string CoreLibVersion = "";
        public string CoreLibMvid = "";
        public int ArgumentCount;
        public string ForwardingShape = "";
        public string CallOpcode = "";
        public int CallToken;
        public string TokenKind = "";
        public string ResolvedDeclaringType = "";
        public string ResolvedSignature = "";
        public string ResolvedMvid = "";
        public int ResolvedMetadataToken;
        public string ExpectedDeclaringType = "";
        public string ExpectedMvid = "";
        public int ExpectedMetadataToken;
        public bool LayoutUnchangedAfterDecode;
        public readonly List<string> Casts = new List<string>();

        public Evidence Snapshot() => new Evidence
        {
            IlHex = IlHex,
            IlLength = IlLength,
            StackSize = StackSize,
            LocalSignatureHex = LocalSignatureHex,
            DynamicSignature = DynamicSignature,
            ExpectedSignature = ExpectedSignature,
            DynamicMethodName = DynamicMethodName,
            CoreLibVersion = CoreLibVersion,
            CoreLibMvid = CoreLibMvid,
            ArgumentCount = ArgumentCount,
            ForwardingShape = ForwardingShape,
            CallOpcode = CallOpcode,
            CallToken = CallToken,
            TokenKind = TokenKind,
            ResolvedDeclaringType = ResolvedDeclaringType,
            ResolvedSignature = ResolvedSignature,
            ResolvedMvid = ResolvedMvid,
            ResolvedMetadataToken = ResolvedMetadataToken,
            ExpectedDeclaringType = ExpectedDeclaringType,
            ExpectedMvid = ExpectedMvid,
            ExpectedMetadataToken = ExpectedMetadataToken,
            Casts = Casts.ToArray(),
            LayoutUnchangedAfterDecode = LayoutUnchangedAfterDecode,
        };
    }

    sealed class Reject : Exception
    {
        public Reject(string reason) : base(reason) { }
    }

    static Reject R(string code) => new Reject(Prefix + code);
}
