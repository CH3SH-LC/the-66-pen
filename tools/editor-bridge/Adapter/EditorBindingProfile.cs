using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;

namespace Miliastra.EditorBridge;

// Central, fail-closed runtime resolver for the native editor assembly ("BeyondEditor").
//
// The adapter reaches the native editor by reflection over update-mangled names. An update
// renames them, and a name that resolves to the WRONG member is worse than a name that
// fails to resolve, because it silently calls something else. So every native name goes
// through Resolve(), and Resolve() is only reachable through RequireEditor(), which refuses
// to hand back an assembly it cannot positively identify: the file must hash to a known
// SHA-256 on disk AND the loaded module must carry a known MVID AND every recorded contract
// must exist with the exact kind, staticness and signature.
//
// Rules this file is written to honour:
//   1. Nothing here invokes a target method, constructor or field getter. Validation is
//      metadata-only: GetType/GetFields/GetMethods plus Type/FieldInfo/MethodInfo/
//      ParameterInfo properties. A wrong guess cannot run anything.
//   2. Every failure throws InvalidOperationException with the EDITOR_BINDING_PROFILE_
//      prefix and no fallback. There is no environment variable, no test-host switch and
//      no dynamic-assembly special case that bypasses a check.
//   3. The cache is written only after hash + MVID + all contract checks have passed.
//   4. The generated static data (Profiles/LegacySymbols, sibling partial) never touches
//      BeyondEditor. No static constructor in this file reflects on anything.
internal static partial class EditorBindingProfile
{
    internal const string EditorSimpleName = "BeyondEditor";
    internal const string ErrorPrefix = "EDITOR_BINDING_PROFILE_";
    internal const int Sha256HexLength = 64;

    // The expected assembly identity is "simple name BeyondEditor, version 1.0.0.0,
    // culture neutral, unsigned". Confirmed by static PE metadata (metadata-7.1.json);
    // this does not require loading or executing the editor assembly.
    static readonly Version ExpectedVersion = new(1, 0, 0, 0);

    // DeclaredOnly is load-bearing: a contract must name the type that actually declares
    // the member, not a base type it happens to inherit from.
    const BindingFlags DeclaredMembers =
        BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly;

    internal enum BindingKind
    {
        Type = 0,
        Field = 1,
        Method = 2,
        Property = 3,
    }

    // Signature is a deterministic managed-name string produced by DescribeType /
    // DescribeMethodSignature below. The generator must compute it with these same helpers
    // rather than re-implementing the format, so the data can never drift from the checker.
    internal sealed record BindingContract(
        string TypeFullName,
        string? MemberName,
        BindingKind Kind,
        string Signature,
        bool IsStatic);

    internal sealed record Profile(
        string Id,
        string Sha256,
        Guid Mvid,
        IReadOnlyDictionary<string, string> Symbols,
        IReadOnlyList<BindingContract> Contracts);

    sealed class ValidatedEditor
    {
        internal ValidatedEditor(Assembly assembly, Profile profile)
        {
            Assembly = assembly;
            Profile = profile;
        }

        internal Assembly Assembly { get; }
        internal Profile Profile { get; }
    }

    // Written once, after every check has passed; read without the lock. The lock only
    // serialises the (idempotent) validation work, and is never held while calling a
    // method that could take it again -- hashing and reflection run outside it.
    static volatile ValidatedEditor? validated;
    static readonly object gate = new();

    // Resolves one native name for the loaded, verified editor build.
    //
    // Order matters: the loaded editor is validated first, so a mapping can never be
    // produced from an unverified profile; only then is the profile consulted. A name that
    // the generated data lists as a known legacy symbol but that this build's profile does
    // not map is a hard error. Unregistered names are also refused: stable framework names
    // do not need this resolver and must never become an implicit native-binding fallback.
    internal static string Resolve(string legacy)
    {
        if (legacy == null) throw Fail("SYMBOL_NULL", "");
        var entry = RequireValidatedEditor();
        return ResolveInProfile(entry.Profile, legacy);
    }

    // Pure: profile data plus the generated LegacySymbols set, no assembly access. Kept
    // separate so the mapping rules are testable without a native editor present.
    internal static string ResolveInProfile(Profile profile, string legacy)
    {
        if (profile == null) throw Fail("RESOLVE_PROFILE_NULL", "");
        if (legacy == null) throw Fail("SYMBOL_NULL", "");
        var symbols = profile.Symbols ?? throw Fail("PROFILE_SYMBOLS_NULL", profile.Id ?? "<null>");
        if (symbols.TryGetValue(legacy, out var mapped))
        {
            if (string.IsNullOrEmpty(mapped)) throw Fail("BINDING_EMPTY", profile.Id + " " + legacy);
            return mapped;
        }
        if (LegacySymbols != null && LegacySymbols.Contains(legacy))
            throw Fail("REQUIRED_BINDING_MISSING", profile.Id + " " + legacy);
        throw Fail("UNREGISTERED_SYMBOL", profile.Id + " " + legacy);
    }

    // Returns the loaded native editor, but only after identity, disk hash, module MVID and
    // every contract have been verified for this exact assembly instance.
    internal static Assembly RequireEditor() => RequireValidatedEditor().Assembly;

    // Explicit capability used only by the synchronous reopen-content resource walk.
    // Resolve/RequireEditor remain unchanged: unrelated operations never consult this object.
    internal sealed class ReopenContentReadBinding : IDisposable
    {
        readonly ValidatedEditor entry;
        readonly int threadId = Environment.CurrentManagedThreadId;
        bool disposed;
        ReopenContentReadBinding(ValidatedEditor value) { entry = value; }
        internal static ReopenContentReadBinding Begin() => new(RequireValidatedEditor());
        internal string Resolve(string legacy)
        {
            if (disposed) throw Fail("READ_SCOPE_DISPOSED", "");
            if (threadId != Environment.CurrentManagedThreadId) throw Fail("READ_SCOPE_THREAD", "");
            return ResolveInProfile(entry.Profile, legacy);
        }
        public void Dispose()
        {
            if (disposed) return;
            disposed = true; // no reusable capability survives any end-check failure
            if (threadId != Environment.CurrentManagedThreadId) throw Fail("READ_SCOPE_THREAD", "");
            // Full enumeration and ValidateIdentity, including any newly loaded second editor.
            var after = RequireValidatedEditor();
            if (!ReferenceEquals(entry.Assembly, after.Assembly)) throw Fail("READ_SCOPE_EDITOR_CHANGED", "");
        }
    }

    static ValidatedEditor RequireValidatedEditor()
    {
        var matches = LoadedEditorAssemblies();
        AssemblyName? name = matches.Length == 1 ? TryGetAssemblyName(matches[0]) : null;
        bool isDynamic = matches.Length == 1 && matches[0].IsDynamic;
        string? location = matches.Length == 1 ? TryGetLocation(matches[0]) : null;
        ValidateIdentity(matches.Length, name, isDynamic, location);

        var editor = matches[0];
        var cached = validated;
        if (cached != null && ReferenceEquals(cached.Assembly, editor)) return cached;
        return ValidateAndCache(editor);
    }

    static ValidatedEditor ValidateAndCache(Assembly editor)
    {
        var profile = MatchProfile(editor);
        ValidateContracts(profile, editor);
        var entry = new ValidatedEditor(editor, profile);
        lock (gate)
        {
            // Re-check under the lock: another thread may have finished first. Both results
            // describe the same assembly instance, so either is equally valid.
            var existing = validated;
            if (existing != null && ReferenceEquals(existing.Assembly, editor)) return existing;
            validated = entry;
        }
        return entry;
    }

    static Profile MatchProfile(Assembly editor)
    {
        if (Profiles == null || Profiles.Length == 0)
            throw Fail("NO_PROFILES", EditorSimpleName + " is loaded but no build profile is registered");

        // Shape-check the whole table before matching. A malformed entry is a generator
        // bug, and failing loudly beats silently skipping the entry that would have matched.
        var seenIds = new HashSet<string>(StringComparer.Ordinal);
        foreach (var profile in Profiles)
        {
            if (profile == null) throw Fail("PROFILE_NULL", "");
            if (string.IsNullOrEmpty(profile.Id)) throw Fail("PROFILE_ID_EMPTY", "");
            if (profile.Sha256 == null || profile.Sha256.Length != Sha256HexLength || !IsHex(profile.Sha256))
                throw Fail("PROFILE_HASH_INVALID", profile.Id);
            if (profile.Mvid == Guid.Empty) throw Fail("PROFILE_MVID_EMPTY", profile.Id);
            if (profile.Symbols == null) throw Fail("PROFILE_SYMBOLS_NULL", profile.Id);
            if (profile.Contracts == null) throw Fail("PROFILE_CONTRACTS_NULL", profile.Id);
            if (!seenIds.Add(profile.Id)) throw Fail("PROFILE_ID_DUPLICATE", profile.Id);
        }

        var location = TryGetLocation(editor) ?? throw Fail("EDITOR_LOCATION_MISSING", EditorSimpleName);
        var hash = HashFile(location);
        Guid mvid;
        try
        {
            mvid = editor.ManifestModule.ModuleVersionId;
        }
        catch (Exception ex)
        {
            throw Fail("MVID_UNREADABLE", ex.GetType().Name);
        }
        if (mvid == Guid.Empty) throw Fail("MVID_EMPTY", hash);

        return SelectProfile(hash, mvid);
    }

    // Pure selector used by the production path after reading disk SHA and loaded MVID.
    internal static Profile SelectProfile(string hash, Guid mvid)
    {
        var byHash = new List<Profile>();
        foreach (var profile in Profiles)
            if (string.Equals(profile.Sha256, hash, StringComparison.OrdinalIgnoreCase)) byHash.Add(profile);
        if (byHash.Count == 0) throw Fail("UNKNOWN_BUILD_HASH", hash);

        var byMvid = new List<Profile>();
        foreach (var profile in byHash)
            if (profile.Mvid == mvid) byMvid.Add(profile);
        if (byMvid.Count == 0)
            throw Fail("UNKNOWN_BUILD_MVID", mvid.ToString("D") + " for hash " + hash);
        if (byMvid.Count > 1)
            throw Fail("AMBIGUOUS_PROFILE", string.Join(",", byMvid.Select(p => p.Id)));

        return byMvid[0];
    }

    static string HashFile(string path)
    {
        try
        {
            // ReadWrite|Delete: the editor keeps its own image mapped, so a stricter share
            // mode would refuse to open the very file we need to hash.
            using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
            return Convert.ToHexString(SHA256.HashData(stream));
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or NotSupportedException
            or System.Security.SecurityException or ArgumentException or PathTooLongException)
        {
            throw Fail("EDITOR_LOCATION_UNREADABLE", path + " (" + ex.GetType().Name + ")");
        }
    }

    static Assembly[] LoadedEditorAssemblies()
    {
        var matches = new List<Assembly>();
        foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
        {
            var name = TryGetAssemblyName(assembly);
            if (name != null && string.Equals(name.Name, EditorSimpleName, StringComparison.Ordinal))
                matches.Add(assembly);
        }
        return matches.ToArray();
    }

    static AssemblyName? TryGetAssemblyName(Assembly assembly)
    {
        try
        {
            return assembly.GetName();
        }
        catch (Exception)
        {
            return null;
        }
    }

    static string? TryGetLocation(Assembly assembly)
    {
        try
        {
            var location = assembly.Location;
            return string.IsNullOrEmpty(location) ? null : location;
        }
        catch (Exception)
        {
            return null;
        }
    }

    // Pure identity gate: no I/O, no reflection over any loaded assembly, no cache access.
    // The offline test drives every branch directly by fabricating AssemblyName values,
    // including the cases production cannot easily produce (zero or several candidates).
    internal static void ValidateIdentity(int editorAssemblyCount, AssemblyName? name, bool isDynamic, string? location)
    {
        if (editorAssemblyCount == 0)
            throw Fail("EDITOR_NOT_LOADED", "no loaded assembly is named " + EditorSimpleName);
        if (editorAssemblyCount != 1)
            throw Fail("MULTIPLE_EDITOR_ASSEMBLIES", "count=" + editorAssemblyCount);
        if (name == null) throw Fail("IDENTITY_UNREADABLE", EditorSimpleName);
        if (isDynamic) throw Fail("IDENTITY_DYNAMIC", EditorSimpleName);
        if (string.IsNullOrEmpty(location)) throw Fail("IDENTITY_NO_LOCATION", EditorSimpleName);
        if (!string.Equals(name.Name, EditorSimpleName, StringComparison.Ordinal))
            throw Fail("IDENTITY_NAME_MISMATCH", name.Name ?? "<null>");
        if (name.Version == null || name.Version != ExpectedVersion)
            throw Fail("IDENTITY_VERSION_MISMATCH", (name.Version?.ToString() ?? "<null>") + " expected " + ExpectedVersion);
        if (!string.IsNullOrEmpty(name.CultureName))
            throw Fail("IDENTITY_CULTURE_MISMATCH", name.CultureName!);
        var token = name.GetPublicKeyToken();
        if (token != null && token.Length != 0)
            throw Fail("IDENTITY_SIGNED_ASSEMBLY", EditorSimpleName + " must be unsigned");
    }

    // Verifies every recorded contract against the assembly's metadata. Pure: read-only
    // reflection over the passed assembly, no invocation, no state. The offline test passes
    // its own assembly here, with a profile built from that assembly's real hash and MVID.
    internal static void ValidateContracts(Profile profile, Assembly editor)
    {
        if (profile == null) throw Fail("CONTRACTS_PROFILE_NULL", "");
        if (editor == null) throw Fail("CONTRACTS_EDITOR_NULL", "");
        foreach (var legacy in LegacySymbols)
            if (!profile.Symbols.TryGetValue(legacy, out var mapped) || string.IsNullOrWhiteSpace(mapped))
                throw Fail("REQUIRED_BINDING_MISSING", profile.Id + " " + legacy);
        var contracts = profile.Contracts ?? throw Fail("CONTRACTS_NULL", profile.Id ?? "<null>");
        for (int i = 0; i < contracts.Count; i++)
        {
            var contract = contracts[i] ?? throw Fail("CONTRACT_NULL", (profile.Id ?? "<null>") + "[" + i + "]");
            ValidateContract(profile, editor, contract, i);
        }
    }

    static void ValidateContract(Profile profile, Assembly editor, BindingContract contract, int index)
    {
        string where = (profile.Id ?? "<null>") + "[" + index + "]";
        if (string.IsNullOrEmpty(contract.TypeFullName))
            throw Fail("CONTRACT_TYPE_NAME_EMPTY", where);

        var type = TryGetType(editor, contract.TypeFullName!) ?? throw Fail("CONTRACT_TYPE_MISSING", where + " " + contract.TypeFullName);

        // A forwarded type resolves to the assembly that really declares it. That is only
        // ever acceptable as a type-existence contract for a stable shared reference type;
        // member contracts on such a type cannot be checked with the target assembly alone,
        // so they are refused rather than waved through.
        if (type.Assembly != editor)
        {
            if (contract.Kind != BindingKind.Type || contract.MemberName != null)
                throw Fail("CONTRACT_EXTERNAL_MEMBER_UNSUPPORTED", where + " " + contract.TypeFullName);
            if (contract.IsStatic)
                throw Fail("CONTRACT_TYPE_STATIC_UNSUPPORTED", where + " " + contract.TypeFullName);
            return;
        }

        switch (contract.Kind)
        {
            case BindingKind.Type:
                if (contract.MemberName != null) throw Fail("CONTRACT_MEMBER_NOT_ALLOWED", where + " " + contract.TypeFullName);
                if (contract.IsStatic) throw Fail("CONTRACT_TYPE_STATIC_UNSUPPORTED", where + " " + contract.TypeFullName);
                ExpectSignature(where, contract.Signature, DescribeType(type));
                return;

            case BindingKind.Field:
            {
                string member = RequireMemberName(contract, where);
                var fields = type.GetFields(DeclaredMembers).Where(f => f.Name == member).ToArray();
                if (fields.Length == 0) throw Fail("CONTRACT_FIELD_MISSING", where + " " + contract.TypeFullName + "." + member);
                if (fields.Length > 1) throw Fail("CONTRACT_FIELD_AMBIGUOUS", where + " " + contract.TypeFullName + "." + member);
                if (fields[0].IsStatic != contract.IsStatic)
                    throw Fail("CONTRACT_STATIC_MISMATCH", where + " " + contract.TypeFullName + "." + member);
                ExpectSignature(where, contract.Signature, DescribeType(fields[0].FieldType));
                return;
            }

            case BindingKind.Property:
            {
                string member = RequireMemberName(contract, where);
                var properties = type.GetProperties(DeclaredMembers).Where(p => p.Name == member).ToArray();
                if (properties.Length != 1 || properties[0].GetIndexParameters().Length != 0)
                    throw Fail("CONTRACT_PROPERTY_MISSING_OR_AMBIGUOUS", where + " " + member);
                var accessor = properties[0].GetGetMethod(true);
                if (accessor == null || accessor.IsStatic != contract.IsStatic)
                    throw Fail("CONTRACT_PROPERTY_ACCESSOR_MISMATCH", where + " " + member);
                ExpectSignature(where, contract.Signature, DescribeType(properties[0].PropertyType));
                return;
            }

            case BindingKind.Method:
            {
                string member = RequireMemberName(contract, where);
                var candidates = type.GetMethods(DeclaredMembers).Where(m => m.Name == member).ToArray();
                if (candidates.Length == 0) throw Fail("CONTRACT_METHOD_MISSING", where + " " + contract.TypeFullName + "." + member);
                // No ambiguous methods: exactly one overload must match the recorded
                // signature, and staticness is part of that match.
                string signature = contract.Signature ?? "";
                var matched = candidates
                    .Where(m => m.IsStatic == contract.IsStatic && string.Equals(DescribeMethodSignature(m), signature, StringComparison.Ordinal))
                    .ToArray();
                if (matched.Length == 0)
                    throw Fail("CONTRACT_METHOD_SIGNATURE_MISSING", where + " " + contract.TypeFullName + "." + member + contract.Signature);
                if (matched.Length > 1)
                    throw Fail("CONTRACT_METHOD_AMBIGUOUS", where + " " + contract.TypeFullName + "." + member + contract.Signature);
                return;
            }

            default:
                throw Fail("CONTRACT_KIND_UNSUPPORTED", where + " kind=" + (int)contract.Kind);
        }
    }

    static string RequireMemberName(BindingContract contract, string where)
    {
        var member = contract.MemberName;
        if (string.IsNullOrEmpty(member)) throw Fail("CONTRACT_MEMBER_NAME_EMPTY", where + " " + contract.TypeFullName);
        // Constructors and type initialisers are not in scope: this resolver validates
        // through GetMethods only, and a contract that could not be checked must not exist.
        if (member == ".ctor" || member == ".cctor")
            throw Fail("CONTRACT_CONSTRUCTOR_UNSUPPORTED", where + " " + contract.TypeFullName + " " + member);
        return member!;
    }

    static void ExpectSignature(string where, string? actual, string expected)
    {
        if (!string.Equals(actual, expected, StringComparison.Ordinal))
            throw Fail("CONTRACT_SIGNATURE_MISMATCH", where + " recorded=" + (actual ?? "<null>") + " actual=" + expected);
    }

    static Type? TryGetType(Assembly editor, string fullName)
    {
        try
        {
            return editor.GetType(fullName, throwOnError: false, ignoreCase: false);
        }
        catch (Exception ex) when (ex is ArgumentException or TypeLoadException or FileLoadException or BadImageFormatException)
        {
            throw Fail("CONTRACT_TYPE_LOOKUP_FAILED", fullName + " (" + ex.GetType().Name + ")");
        }
    }

    static bool IsHex(string value)
    {
        foreach (char c in value)
            if (!Uri.IsHexDigit(c)) return false;
        return true;
    }

    // Deterministic managed name. Type.FullName is used when available (nested types then
    // keep their '+' form, generic definitions keep their backtick arity); Type.Name is the
    // fallback for generic parameters, whose FullName is null. Arrays and byrefs are
    // suffixes so the same spelling round-trips through generated data unchanged.
    internal static string DescribeType(Type type)
    {
        if (type == null) throw Fail("DESCRIBE_TYPE_NULL", "");
        if (type.IsByRef) return DescribeType(type.GetElementType()!) + "&";
        if (type.IsPointer) return DescribeType(type.GetElementType()!) + "*";
        if (type.IsArray)
        {
            var element = DescribeType(type.GetElementType()!);
            int rank = type.GetArrayRank();
            return rank == 1 ? element + "[]" : element + "[" + new string(',', rank - 1) + "]";
        }
        if (type.IsGenericParameter) return type.Name;
        if (type.IsGenericTypeDefinition) return type.FullName ?? type.Name;
        if (type.IsGenericType)
        {
            var definition = type.GetGenericTypeDefinition();
            var arguments = type.GetGenericArguments();
            var parts = new string[arguments.Length];
            for (int i = 0; i < arguments.Length; i++) parts[i] = DescribeType(arguments[i]);
            return (definition.FullName ?? definition.Name) + "<" + string.Join(",", parts) + ">";
        }
        return type.FullName ?? type.Name;
    }

    // "(params):return", no member name -- the name lives in BindingContract.MemberName and
    // already carries method generic arity via MethodInfo.Name. An out parameter keeps the
    // "out " prefix on top of the byref "&" suffix; IsOut is metadata, read only.
    internal static string DescribeMethodSignature(MethodInfo method)
    {
        if (method == null) throw Fail("DESCRIBE_METHOD_NULL", "");
        var parameters = method.GetParameters();
        var parts = new string[parameters.Length];
        for (int i = 0; i < parameters.Length; i++)
        {
            var parameter = parameters[i];
            parts[i] = parameter.IsOut ? "out " + DescribeType(parameter.ParameterType) : DescribeType(parameter.ParameterType);
        }
        return "(" + string.Join(",", parts) + "):" + DescribeType(method.ReturnType);
    }

    static InvalidOperationException Fail(string code, string detail)
        => new InvalidOperationException(ErrorPrefix + code + (string.IsNullOrEmpty(detail) ? "" : ": " + detail));
}
