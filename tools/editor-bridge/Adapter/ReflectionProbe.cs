using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Text.Json;

namespace Miliastra.EditorBridge;

// Read-only. This is the instrument the whole "is the primitive really absent?" question
// needs: every OTHER adapter op resolves a symbol by a name harvested STATICALLY from the
// decompiled corpus (EditorBindingProfile / the typed 71 consts). That makes every one of
// them blind to a gap in the corpus. This probe asks the LIVE assembly instead.
//
//   * It enumerates the types of every assembly LOADED in the editor's AppDomain and keeps
//     the ones whose short Name or FullName contains `nameContains` (case-insensitive).
//   * For each kept type it lists its own METHOD names (DeclaredOnly), optionally filtered
//     by `memberContains`.
//   * It NEVER invokes a method and NEVER reads a property getter. The only reflection
//     calls are GetTypes() and GetMethods() on Type objects -- both enumerations.
//
// It is deliberately bounded so the reply can never be the whole assembly:
//   nameContains must be >= 4 chars (a 1-3 char needle is a wildcard-everything scan),
//   at most 64 matching types are returned, at most 40 method names per type. When a cap
//   bites the reply says so (truncated / methodsTruncated) -- a truncated list must never
//   read back as an authoritative member set, exactly the discipline ComponentCollectionCap
//   applies on the read side.
//
// WHY IT LIVES IN ITS OWN partial file with its own consts (the AuthorEntityTag /
// EntityComponentProbe idiom): a wrong name in EditorBindingProfile.Generated.cs fails
// EVERY op closed (EditorBindingProfile.cs ValidateContracts), while this op has no typed
// contract to get wrong -- it reports whatever the live assembly is, by construction.
internal sealed partial class EditorAdapter
{
    // A full member-set reply is not the goal -- a NARROWED one is. 64/40 keeps the whole
    // reply small (well under a second's worth of names) while a real member hunt narrows
    // by `memberContains` / a longer `nameContains` rather than by raising these.
    const int ReflectionMaxTypes = 64;
    const int ReflectionMaxMethodsPerType = 40;
    // A 1-3 character needle matches thousands of framework types and proves nothing; the
    // lenient floor is what stops an accidental "scan everything" from being answered.
    const int ReflectionMinNameLength = 4;
    const int ReflectionMaxNameLength = 200;
    // The type's OWN members only. DeclaredOnly keeps the list about the type named in the
    // reply (no object.ToString/WaitHandle noise), so a hit is a hit on THAT type.
    const BindingFlags ReflectionMethods =
        BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance |
        BindingFlags.Static | BindingFlags.DeclaredOnly;

    // WHY THE EDITOR-SCOPED SIBLINGS EXIST (the reflection-editor-* ops below)
    //   The two probes above match a TYPE name. In the editor assembly the TYPE names are
    //   OBFUSCATED -- the real editor types are called things like "LhusWLXd5NUZ7IineV1x" --
    //   so a human needle such as "Component" can never match one, and the framework
    //   assemblies fill the 64-type cap first. But the editor's METHOD names are PLAIN TEXT
    //   ("AddInstructionGraphForEditObj", "DeleteComponentForEditObj") and its SERVICE names
    //   are plain too ("beyondEditObjService"). So the decisive instrument scopes to the ONE
    //   assembly whose simple name is "BeyondEditor" and filters by MEMBER name, where the
    //   obfuscation of type names stops mattering.
    //
    //   Reused from the editor binding profile rather than respelled, so the two cannot drift
    //   on which assembly "the editor" is.
    const string ReflectionEditorAssemblyName = EditorBindingProfile.EditorSimpleName;

    // Refuses unknown or duplicate request fields before any reflection runs. nameContains
    // is required and length-bounded; memberContains is optional. The probe takes no target,
    // no path, no id -- only the two name needles.
    internal static void ValidateReflectionProbe(JsonElement request)
    {
        var allowed = new HashSet<string> { "id", "op", "nonce", "nameContains", "memberContains" };
        var seen = new HashSet<string>();
        foreach (var property in request.EnumerateObject())
            if (!allowed.Contains(property.Name) || !seen.Add(property.Name))
                throw new InvalidOperationException("REFLECTION_PROBE_UNKNOWN_OR_DUPLICATE_FIELD:" + property.Name);
        if (!request.TryGetProperty("nameContains", out var name) || name.ValueKind != JsonValueKind.String)
            throw new InvalidOperationException("REFLECTION_PROBE_REQUIRED_STRING:nameContains");
        var needle = name.GetString();
        if (needle is null || needle.Length < ReflectionMinNameLength)
            throw new InvalidOperationException("REFLECTION_PROBE_NAME_TOO_SHORT");
        if (needle.Length > ReflectionMaxNameLength)
            throw new InvalidOperationException("REFLECTION_PROBE_NAME_TOO_LONG");
        if (!request.TryGetProperty("memberContains", out var member)) return;
        if (member.ValueKind != JsonValueKind.String)
            throw new InvalidOperationException("REFLECTION_PROBE_MEMBER_NOT_STRING");
        if ((member.GetString()?.Length ?? 0) > ReflectionMaxNameLength)
            throw new InvalidOperationException("REFLECTION_PROBE_MEMBER_TOO_LONG");
    }

    // Types of one assembly, tolerating a partially-loadable assembly: a ReflectionTypeLoad
    // failure still yields the types that DID load (the nulls are dropped). A dynamic or
    // otherwise unsupported assembly is skipped rather than failing the whole probe -- the
    // instrument must report over the assemblies it CAN read, not refuse because one is odd.
    static IEnumerable<Type> LoadedTypes(Assembly assembly)
    {
        try { return assembly.GetTypes(); }
        catch (ReflectionTypeLoadException ex) { return ex.Types.Where(t => t != null)!; }
        catch (Exception) { return Array.Empty<Type>(); }
    }

    // The ONE copy of "a type's own method names, optionally narrowed by a member needle".
    // Both the field-driven probe and the assembly-scoped editor probe run this, so a
    // member hunt can never answer a different question in each. `memberNeedles` is
    // ANY-OF (a name is kept when it contains any needle); null means "list them all".
    // Distinct keeps 40 rows = 40 distinct names. A type whose method table cannot be read
    // is reported with no methods rather than dropped -- the type name is still an answer.
    static string[] DeclaredMethodNames(Type type, string[]? memberNeedles)
    {
        try
        {
            return type.GetMethods(ReflectionMethods)
                .Select(m => m.Name)
                .Where(n => memberNeedles is null ||
                            memberNeedles.Length == 0 ||
                            memberNeedles.Any(needle => n.IndexOf(needle, StringComparison.OrdinalIgnoreCase) >= 0))
                .Distinct(StringComparer.Ordinal)
                .OrderBy(n => n, StringComparer.Ordinal)
                .ToArray();
        }
        catch (Exception)
        {
            return Array.Empty<string>();
        }
    }

    // ---- the ASSEMBLY-SCOPED, MEMBER-NAME-FILTERED siblings (reflection-editor-*) --------
    //
    // Same read-only guarantee as the probes above (GetTypes + GetMethods only; nothing is
    // invoked). The difference is the two filters:
    //   * scope    -- ONE assembly, by simple name (ReflectionEditorAssemblyName = "BeyondEditor"),
    //                 never a type-name match, because the editor's type names are obfuscated.
    //   * member   -- a method-name needle (any-of), which in the editor IS plain text.
    // The public entry points take the needles as COMPILE-TIME constants and read NO request
    // field, so a resident helper whose in-memory field allowlist predates these ops still
    // admits them (only its op whitelist is re-read per request).
    public object ReflectionEditorAdd(JsonElement request) =>
        ReflectionEditorFixed(request, null, new[] { "Add" }, false);

    public object ReflectionEditorCreate(JsonElement request) =>
        ReflectionEditorFixed(request, null, new[] { "Create", "New" }, false);

    public object ReflectionEditorServices(JsonElement request) =>
        ReflectionEditorFixed(request, "Service", null, false);

    public object ReflectionEditorTypes(JsonElement request) =>
        ReflectionEditorFixed(request, null, null, true);

    // A request that names a needle against a fixed-needle op would carry a value the op's
    // compile-time needle contradicts, so it is refused by name rather than silently ignored
    // -- the same discipline ReflectionProbeFixed applies above.
    object ReflectionEditorFixed(JsonElement request, string? typeNameContains, string[]? memberNeedles, bool countOnly)
    {
        foreach (var property in request.EnumerateObject())
            if (property.Name == "nameContains" || property.Name == "memberContains")
                throw new InvalidOperationException("REFLECTION_PROBE_FIXED_TAKES_NO_NEEDLE:" + property.Name);
        return RunEditorProbe(typeNameContains, memberNeedles, countOnly);
    }

    // The core the four editor-scoped entry points run. Scopes to the editor assembly by
    // SIMPLE NAME, then (optionally) filters by a type-name substring and by method names.
    // `countOnly` short-circuits to the bare type count (op reflection-editor-types), whose
    // whole answer is that number -- it does not need, and deliberately does not build, rows.
    object RunEditorProbe(string? typeNameContains, string[]? memberNeedles, bool countOnly)
    {
        if (string.IsNullOrEmpty(typeNameContains)) typeNameContains = null;
        if (memberNeedles is { Length: 0 }) memberNeedles = null;

        if (!System.Windows.Application.Current.Dispatcher.CheckAccess())
            throw new InvalidOperationException("WRONG_THREAD");

        var editor = AppDomain.CurrentDomain.GetAssemblies()
            .FirstOrDefault(a => string.Equals(a.GetName().Name, ReflectionEditorAssemblyName, StringComparison.Ordinal));
        // A missing editor assembly is a real refusal, not an empty answer: it means the
        // bridge is not loaded into the editor (or it is loaded somewhere else), and a zero
        // count would be read as "the editor exposes nothing" instead of "we did not look".
        if (editor is null)
            throw new InvalidOperationException("REFLECTION_EDITOR_ASSEMBLY_NOT_LOADED:" + ReflectionEditorAssemblyName);

        var edgeTypes = LoadedTypes(editor).Where(t => t is not null).ToList();
        var editorTypeCount = edgeTypes.Count;

        if (countOnly)
            return new
            {
                ok = true,
                status = "reflection-editor-type-count-read-only-live-assembly",
                assemblyName = ReflectionEditorAssemblyName,
                editorTypeCount,
                typeMatchCount = editorTypeCount,
                returnedTypeCount = 0,
                truncated = false,
                types = Array.Empty<object>(),
                scope = "GetTypes only on the BeyondEditor assembly; names counted, none invoked",
                methodInvoked = false,
                nativeMutationInvoked = false,
                localModelWritten = false,
                sentToGame = false,
                persistentSaveVerified = false,
            };

        var matches = new List<Type>();
        foreach (var type in edgeTypes)
        {
            if (typeNameContains is not null &&
                type.Name.IndexOf(typeNameContains, StringComparison.OrdinalIgnoreCase) < 0 &&
                (type.FullName?.IndexOf(typeNameContains, StringComparison.OrdinalIgnoreCase) ?? -1) < 0)
                continue;
            if (memberNeedles is not null)
            {
                var names = DeclaredMethodNames(type, null);
                if (!names.Any(n => memberNeedles.Any(needle =>
                        n.IndexOf(needle, StringComparison.OrdinalIgnoreCase) >= 0)))
                    continue;
            }
            matches.Add(type);
        }

        // Sort BEFORE the cap so the same needles return the same rows whatever order the
        // loader enumerated types in.
        var ordered = matches
            .OrderBy(t => t.FullName ?? t.Name, StringComparer.Ordinal)
            .ToList();

        var truncated = ordered.Count > ReflectionMaxTypes;
        var rows = new List<object>(Math.Min(ordered.Count, ReflectionMaxTypes));
        foreach (var type in ordered.Take(ReflectionMaxTypes))
        {
            var methodNames = DeclaredMethodNames(type, memberNeedles);
            var methodsTruncated = methodNames.Length > ReflectionMaxMethodsPerType;
            if (methodsTruncated) truncated = true;
            rows.Add(new
            {
                fullName = type.FullName ?? type.Name,
                assemblyName = ReflectionEditorAssemblyName,
                methods = methodNames.Take(ReflectionMaxMethodsPerType).ToArray(),
                methodsTruncated,
            });
        }

        return new
        {
            ok = true,
            status = "reflection-editor-probe-read-only-live-assembly",
            assemblyName = ReflectionEditorAssemblyName,
            typeNameContains,
            memberNeedles = memberNeedles ?? Array.Empty<string>(),
            editorTypeCount,
            maxTypes = ReflectionMaxTypes,
            maxMethodsPerType = ReflectionMaxMethodsPerType,
            typeMatchCount = matches.Count,
            returnedTypeCount = rows.Count,
            truncated,
            types = rows.ToArray(),
            scope = "GetTypes + GetMethods on the BeyondEditor assembly only; names only; no " +
                    "method invoked, no property getter read, no field written, nothing " +
                    "dispatched to the game",
            methodInvoked = false,
            nativeMutationInvoked = false,
            localModelWritten = false,
            sentToGame = false,
            persistentSaveVerified = false,
        };
    }

    public object ReflectionProbe(JsonElement request)
    {
        ValidateReflectionProbe(request);
        var nameContains = request.GetProperty("nameContains").GetString()!;
        var memberFilter = request.TryGetProperty("memberContains", out var memberElement)
            ? memberElement.GetString()
            : null;
        return RunReflectionProbe(nameContains, memberFilter);
    }

    // A FIXED-NEEDLE sibling of ReflectionProbe. It answers the same question ("what does the
    // live assembly have for names containing X") with X a COMPILE-TIME constant and NO request
    // field at all. That is the whole point: the resident elevated helper re-reads the op
    // whitelist from call-bridge.ps1 on every request, so a NEW op NAME is accepted at once,
    // but its IN-MEMORY field allowlist is fixed at launch -- a request that carries
    // nameContains against the stale helper is refused (CALL_FIELD_NOT_ALLOWED:nameContains)
    // before it is ever queued. A request that carries NO extra field passes the list it has
    // always had. So the needle moves out of the request and into the op's name.
    //
    // The request must carry no needle: a value silently ignored by the runner would only
    // contradict the op name here, so it is refused by name rather than dropped.
    public object ReflectionProbeFixed(JsonElement request, string nameContains, string? memberFilter)
    {
        foreach (var property in request.EnumerateObject())
            if (property.Name == "nameContains" || property.Name == "memberContains")
                throw new InvalidOperationException("REFLECTION_PROBE_FIXED_TAKES_NO_NEEDLE:" + property.Name);
        return RunReflectionProbe(nameContains, memberFilter);
    }

    // The shared core: the enumeration BOTH public entry points run. Taking the two needles as
    // arguments (rather than reading them from the request inside) is what lets the field-driven
    // op and its fixed-needle siblings reuse ONE copy of the reflection, so the two can never
    // drift into answering different questions.
    object RunReflectionProbe(string nameContains, string? memberFilter)
    {
        if (string.IsNullOrEmpty(memberFilter)) memberFilter = null;

        if (!System.Windows.Application.Current.Dispatcher.CheckAccess())
            throw new InvalidOperationException("WRONG_THREAD");

        // Pass 1 -- collect the matching (assembly, type) pairs. The match is on the type's
        // short Name OR its FullName, case-insensitive. Sorting BEFORE the cap makes the
        // reply deterministic (assembly name, then full name), so the same needle returns the
        // same 64 rows whatever order the loader happened to enumerate assemblies in.
        var assemblies = AppDomain.CurrentDomain.GetAssemblies();
        var matches = new List<(string Assembly, Type Type)>();
        foreach (var assembly in assemblies)
            foreach (var type in LoadedTypes(assembly))
            {
                if (type is null) continue;
                var matchesName = type.Name.IndexOf(nameContains, StringComparison.OrdinalIgnoreCase) >= 0
                    || (type.FullName?.IndexOf(nameContains, StringComparison.OrdinalIgnoreCase) >= 0);
                if (!matchesName) continue;
                var assemblyName = type.Assembly.GetName().Name ?? "?";
                matches.Add((assemblyName, type));
            }
        var ordered = matches
            .OrderBy(m => m.Assembly, StringComparer.Ordinal)
            .ThenBy(m => m.Type.FullName ?? m.Type.Name, StringComparer.Ordinal)
            .ToList();

        var truncated = ordered.Count > ReflectionMaxTypes;
        var rows = new List<object>(Math.Min(ordered.Count, ReflectionMaxTypes));
        foreach (var (assemblyName, type) in ordered.Take(ReflectionMaxTypes))
        {
            // Distinct (a name can repeat across overloads) keeps 40 rows = 40 distinct
            // names, which is what a member hunt reads; the overload count is not.
            var methodNames = DeclaredMethodNames(type, memberFilter is null ? null : new[] { memberFilter });
            var methodsTruncated = methodNames.Length > ReflectionMaxMethodsPerType;
            if (methodsTruncated) truncated = true;
            rows.Add(new
            {
                fullName = type.FullName ?? type.Name,
                assemblyName,
                methods = methodNames.Take(ReflectionMaxMethodsPerType).ToArray(),
                methodsTruncated,
            });
        }

        return new
        {
            ok = true,
            status = "reflection-probe-read-only-live-assembly",
            nameContains,
            memberContains = memberFilter,
            maxTypes = ReflectionMaxTypes,
            maxMethodsPerType = ReflectionMaxMethodsPerType,
            minNameLength = ReflectionMinNameLength,
            assemblyCount = assemblies.Length,
            typeMatchCount = matches.Count,
            returnedTypeCount = rows.Count,
            truncated,
            types = rows.ToArray(),
            scope = "GetTypes + GetMethods on Type objects only; names only; no method invoked, " +
                    "no property getter read, no field written, nothing dispatched to the game",
            methodInvoked = false,
            nativeMutationInvoked = false,
            localModelWritten = false,
            sentToGame = false,
            persistentSaveVerified = false,
        };
    }
}
