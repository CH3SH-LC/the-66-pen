using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;

namespace Miliastra.EditorBridge;

// Real-machine verification of the interface surface that was recovered statically
// from BeyondEditor.dll (see docs/editor-catalog/CODE-SURFACE.md and COMMAND-CHANNEL.md).
//
// The static work produced, for each obfuscated method-proxy slot, the method it
// really points at (34,728 mappings, tools/editor-catalog/resolve-proxy.py). That is
// a claim about the *file*. This class tests the same claim against the *running
// editor process*: it reads each slot field's value and, when that value is a
// delegate, asks the runtime for Delegate.Method. A match is direct evidence that
// the static mapping describes the live program.
//
// STRICTLY READ-ONLY. It never invokes the dispatcher, never sends a command to the
// game, never mutates a model. Dynamic proxies are inspected through their CoreLib
// resolver metadata and IL; neither their delegates nor their target methods run.
internal sealed partial class EditorAdapter
{
    readonly record struct Slot(string Owner, string Field, string TargetType, string TargetMethod);

    // Generated from .runtime/editor-catalog/proxy-map-full.json.
    // Regenerate with the snippet in docs/editor-catalog/INTERFACE-VERIFICATION.md.
    static Slot[] VerifySlots => new Slot[]
    {
        new Slot(B("BrjMRrl2xRXv5aqZQkDJ"), B("BQel2dOESVB"), B("kJebiGi0wckPoYphgKNO.TC9Tn2i0BNsxu8MM0XOF"), B("Daxi0kkneV1")),
        new Slot(B("BrjMRrl2xRXv5aqZQkDJ"), B("snthqqZ3HCR"), B("tbLtNPi0Ktj7XmlZMWvt.mCglXsi0ijgrwvs0SPGh"), B("Ikci0qkvMZX")),
        new Slot(B("HOlfE6lSftgl74pgvnRM"), B("wtRlSp6GrvH"), B("gRNKAfiARUIARICiA4q4.vh0ExpiAUXNaxFjnJLHP"), B("qFQi3il61x5")),
        new Slot(B("HOlfE6lSftgl74pgvnRM"), B("P9plSZjW9OJ"), B("gRNKAfiARUIARICiA4q4.vh0ExpiAUXNaxFjnJLHP"), B("wyni3ubhjqm")),
        new Slot(B("HOlfE6lSftgl74pgvnRM"), B("KJZlSrdSUL1"), B("gRNKAfiARUIARICiA4q4.vh0ExpiAUXNaxFjnJLHP"), B("zSti3Yyn65w")),
        new Slot(B("HOlfE6lSftgl74pgvnRM"), B("TnxlzlI8Hk0"), B("lZwT4qiDfrIniFQAXhy3.tW2HrGiD6SS0P41IfVkY"), B("LsmiDw1hrGh")),
        new Slot(B("HOlfE6lSftgl74pgvnRM"), B("Oerlz9Jdbnf"), B("lZwT4qiDfrIniFQAXhy3.tW2HrGiD6SS0P41IfVkY"), B("d7RiDt3rWyw")),
        new Slot(B("HOlfE6lSftgl74pgvnRM"), B("VdghK1XTDpm"), "miTools.AppCommon.AppUtility", "get_AppLocalDataFolder"),
        new Slot(B("HOlfE6lSftgl74pgvnRM"), B("cN5hqlJY835"), B("gRNKAfiARUIARICiA4q4.vh0ExpiAUXNaxFjnJLHP"), B("eQHi3vwxAyn")),
        new Slot(B("HOlfE6lSftgl74pgvnRM"), B("YSDhqo1YVyx"), B("gRNKAfiARUIARICiA4q4.vh0ExpiAUXNaxFjnJLHP"), B("yPFiAIrmqCV")),
        new Slot(B("HOlfE6lSftgl74pgvnRM"), B("Is6hqU640RJ"), B("gRNKAfiARUIARICiA4q4.vh0ExpiAUXNaxFjnJLHP"), B("YrFi3A6H2I8")),
        new Slot(B("HOlfE6lSftgl74pgvnRM"), B("BsxLvIOuJMp"), B("gRNKAfiARUIARICiA4q4.vh0ExpiAUXNaxFjnJLHP"), B("jtXi3msT74g")),
        new Slot(B("HOlfE6lSftgl74pgvnRM"), B("Cg3LuDiYIgD"), B("gRNKAfiARUIARICiA4q4.vh0ExpiAUXNaxFjnJLHP"), B("d3di3bdsTUl")),
        new Slot(B("HOlfE6lSftgl74pgvnRM"), B("JxZLSauoPXi"), B("gRNKAfiARUIARICiA4q4.vh0ExpiAUXNaxFjnJLHP"), B("SiKi359WufY")),
        new Slot(B("HOlfE6lSftgl74pgvnRM"), B("boGLyQBJv9p"), B("gRNKAfiARUIARICiA4q4.vh0ExpiAUXNaxFjnJLHP"), B("w5vi3EMKm7u")),
        new Slot(B("Yko1Gll2ZJdSIZmJQ0Vn"), B("W88l2rgbNcI"), B("yqZNjiiAvUGtexJ8Y8LW.IxtFOgiA4qhGnLhEyLFv"), B("bKliA0tj1p1")),
        new Slot(B("JYlR8al2G1g7yXucJnaB"), B("FIbl2Ce3f4N"), B("yqZNjiiAvUGtexJ8Y8LW.IxtFOgiA4qhGnLhEyLFv"), B("h8diA3iOGmJ")),
        new Slot(B("U7lOPGl2tdSf63xl7lBN"), B("WYQl2BdTD7C"), B("yqZNjiiAvUGtexJ8Y8LW.IxtFOgiA4qhGnLhEyLFv"), B("wNLiAK8Wcix")),
        new Slot(B("w7uAqULvzhHRAFYTbySr"), B("CXBL05s2Aiw"), B("gRNKAfiARUIARICiA4q4.vh0ExpiAUXNaxFjnJLHP"), B("L8IiACRvPVs")),
        // First live run corrected this row: the slot really targets the channel type's
        // gdQiAJcF6Eg, not the Param type's. The proxy map said so; the hand-written
        // expectation was wrong. Kept corrected, with the history recorded here.
        new Slot(B("YdqubEhqRh94bTsZgI9h"), B("fWIhqNuB4sF"), B("gRNKAfiARUIARICiA4q4.vh0ExpiAUXNaxFjnJLHP"), B("gdQiAJcF6Eg")),
        new Slot(B("YlKu2QYfNaDsptndNkxX"), B("EOHYfjqMv7P"), B("qmcI6kYhr1tEjgMBZY1r.Y9F2H0YhZJ8wH9Xl5wuT"), B("cBVYLdhAhVY")),
    };

    // Slot fields are static; the inherited Fields flag set only covers instance members.
    const BindingFlags Statics = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;

    // Named types the interface surface depends on.
    static (string Name, string Role)[] VerifyTypes => new (string Name, string Role)[]
    {
        (B("BrjMRrl2xRXv5aqZQkDJ"), "命令派发委托"),
        (B("tbLtNPi0Ktj7XmlZMWvt.mCglXsi0ijgrwvs0SPGh"), "生产者/传输"),
        (B("HOlfE6lSftgl74pgvnRM"), "代理槽位容器"),
        (B("gRNKAfiARUIARICiA4q4.vh0ExpiAUXNaxFjnJLHP"), "通道方法所在类型"),
        (B("yqZNjiiAvUGtexJ8Y8LW.IxtFOgiA4qhGnLhEyLFv"), "参数类型"),
        (B("qmcI6kYhr1tEjgMBZY1r.Y9F2H0YhZJ8wH9Xl5wuT"), "字符串表解码"),
        (B("ACE1cmiYtEdXg5frDhMg.Lpts7HiY2aTvYryR0pre"), "资源注册表"),
        (B("mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q"), "编辑器管理器"),
        (B("Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr"), "实体实例模型"),
        (B("nWLQffitWoLLGIT98hlP.hRwGGsitgmhQZo9c1XOp"), "预制模型"),
        (B("IpVbUoKHNx7P6wEKeDT2.jxqH4eKHRgIc1AAI2M9C"), "节点定义模型(Kind 6)"),
        (B("cwoW1eKmGGThJGs9Wxvm.A8NrPMKmnpQkIiiyYetH"), "节点图模型(Kind 9)"),
    };

    // Separate from VerifyInterfaces because this one INVOKES things. It calls only the
    // zero-argument static methods returning string that the live runtime itself reports
    // as such -- i.e. the channel selectors the command dispatcher is handed. Nothing is
    // sent to the game, no model is touched, no instance is created. Kept as its own
    // operation so the pure read-only check stays pure.
    // The 13 readers in INTERFACE-VERIFICATION.md section four. Other VerifySlots
    // entries are commands/parameter helpers and must never be invoked here.
    static HashSet<string> RequiredChannelFields => new(StringComparer.Ordinal)
    {
        B("YSDhqo1YVyx"), B("BsxLvIOuJMp"), B("cN5hqlJY835"), B("Is6hqU640RJ"),
        B("Cg3LuDiYIgD"), B("JxZLSauoPXi"), B("boGLyQBJv9p"), B("wtRlSp6GrvH"),
        B("P9plSZjW9OJ"), B("KJZlSrdSUL1"), B("TnxlzlI8Hk0"), B("Oerlz9Jdbnf"), B("VdghK1XTDpm")
    };

    public object VerifyChannels() => VerifyChannelsCore(Editor(), VerifySlots, RequiredChannelFields);

    // Production always enters through the version gate above; the core accepts metadata
    // explicitly so offline fixtures can check coverage without pretending to be a real editor.
    static object VerifyChannelsCore(Assembly asm, Slot[] slots, HashSet<string> required)
    {
        var results = new List<object>();
        int succeeded = 0, failed = 0, skipped = 0;
        var covered = new HashSet<string>(StringComparer.Ordinal);
        foreach (var slot in slots.Where(s => required.Contains(s.Field)))
        {
            if (!covered.Add(slot.Field)) { failed++; continue; }
            try
            {
                var owner = asm.GetType(slot.Owner, false);
                var fi = owner?.GetField(slot.Field, Statics);
                if (fi?.GetValue(null) is not Delegate del)
                {
                    skipped++;
                    results.Add(new { slot = slot.Owner + "." + slot.Field, error = "REQUIRED_SELECTOR_MISSING" });
                    continue;
                }
                var m = del.Method;
                if (!m.IsStatic || m.GetParameters().Length != 0 || m.ReturnType != typeof(string) ||
                    m.DeclaringType?.FullName != slot.TargetType || m.Name != slot.TargetMethod)
                {
                    skipped++;
                    results.Add(new { slot = slot.Owner + "." + slot.Field, error = "REQUIRED_SELECTOR_CONTRACT_MISMATCH",
                        declaringType = m.DeclaringType?.FullName, name = m.Name });
                    continue;
                }
                var result = m.Invoke(null, null) as string;
                if (string.IsNullOrWhiteSpace(result)) throw new InvalidOperationException("EMPTY_SELECTOR_RESULT");
                succeeded++;
                results.Add(new { slot = slot.Owner + "." + slot.Field,
                    target = slot.TargetType + "::" + slot.TargetMethod, channel = result });
            }
            catch (Exception ex)
            {
                failed++;
                results.Add(new { slot = slot.Owner + "." + slot.Field, error = ex.GetType().Name + ": " + ex.Message });
            }
        }
        bool complete = succeeded > 0 && succeeded == required.Count &&
            covered.SetEquals(required) && failed == 0 && skipped == 0;
        return new
        {
            ok = complete,
            status = complete ? "channel-selectors-returned-values" : "required-channel-selectors-incomplete",
            scope = "invoked ONLY verified zero-argument static string readers; nothing sent to the game; no model mutated",
            counts = new { required = required.Count, covered = covered.Count, invoked = succeeded, failed, skipped },
            channels = results,
            sentToGame = false
        };
    }
    public object VerifyInterfaces()
    {
        var asm = Editor();

        // Second half of the claim: not only "the slot points at X", but "X exists and is
        // shaped like a real callable". A runtime-emitted proxy slot cannot be name-matched,
        // so the target method's own presence on its declaring type is what carries the
        // claim there. Signature check is on parameter count and static-ness.
        var targetResults = new List<object>();
        int targetOk = 0, targetBad = 0;
        foreach (var (tName, mName) in VerifySlots.Select(s => (s.TargetType, s.TargetMethod)).Distinct())
        {
            // Some slots target methods outside BeyondEditor (e.g. miTools.AppCommon), so
            // search every loaded assembly, not just the editor's.
            var t = asm.GetType(tName, false)
                ?? AppDomain.CurrentDomain.GetAssemblies()
                       .Select(a => { try { return a.GetType(tName, false); } catch { return null; } })
                       .FirstOrDefault(x => x != null);
            if (t == null)
            {
                targetBad++;
                targetResults.Add(new { type = tName, method = mName, typeFound = false, methodFound = false });
                continue;
            }
            var candidates = t.GetMethods(Statics | Fields).Where(m => m.Name == mName).ToArray();
            if (candidates.Length == 0)
            {
                targetBad++;
                targetResults.Add(new { type = tName, method = mName, typeFound = true, methodFound = false });
                continue;
            }
            targetOk++;
            var m0 = candidates[0];
            targetResults.Add(new { type = tName, method = mName, typeFound = true, methodFound = true,
                isStatic = m0.IsStatic, parameterCount = m0.GetParameters().Length,
                returnType = m0.ReturnType.FullName, overloads = candidates.Length });
        }

        // The producer the command dispatcher is handed must be the very singleton the
        // editor's own sync path uses; resolving it here ties the command channel to the
        // object that talks to the running game.
        object? producerState;
        bool producerOk = false;
        try
        {
            var producer = ExistingSingleton(asm, Producer);
            var dispatcher = producer.GetType().GetMethods(Statics | Fields).FirstOrDefault(m => m.Name == B("Ikci0qkvMZX"));
            producerOk = dispatcher != null;
            producerState = new { resolved = true, type = producer.GetType().FullName,
                dispatcherMethodPresent = dispatcher != null,
                dispatcherParameterCount = dispatcher?.GetParameters().Length };
        }
        catch (Exception ex)
        {
            producerState = new { resolved = false, error = ex.Message };
        }

        var typeResults = new List<object>();
        int requiredTypesMissing = 0;
        foreach (var (name, role) in VerifyTypes)
        {
            var t = asm.GetType(name, false);
            if (t == null) requiredTypesMissing++;
            typeResults.Add(new { name, role, found = t != null,
                isDelegate = t != null && typeof(Delegate).IsAssignableFrom(t),
                baseType = t?.BaseType?.FullName, methodCount = t?.GetMethods(Fields).Length });
        }

        var slotResults = new List<object>();
        int matched = 0, matchedNull = 0, mismatched = 0, missing = 0, dynamicMethods = 0;
        int dynamicVerified = 0, dynamicUnresolved = 0;
        foreach (var slot in VerifySlots)
        {
            // The first VerifySlots entry names its owner through the field's own type
            // for the string-table decoder; look the field up on its declaring type.
            var ownerName = slot.Owner;
            var owner = asm.GetType(ownerName, false);
            if (owner == null)
            {
                missing++;
                slotResults.Add(new { slot = ownerName + "." + slot.Field, error = "OWNER_TYPE_NOT_FOUND", expected = slot.TargetType + "::" + slot.TargetMethod });
                continue;
            }
            var fi = owner.GetField(slot.Field, Statics);
            if (fi == null)
            {
                missing++;
                slotResults.Add(new { slot = ownerName + "." + slot.Field, error = "FIELD_NOT_FOUND", expected = slot.TargetType + "::" + slot.TargetMethod });
                continue;
            }
            object? value;
            try { value = fi.GetValue(null); }
            catch (Exception ex)
            {
                slotResults.Add(new { slot = ownerName + "." + slot.Field, error = "GETVALUE_FAILED:" + ex.GetType().Name, expected = slot.TargetType + "::" + slot.TargetMethod });
                mismatched++;
                continue;
            }
            if (value == null)
            {
                matchedNull++;
                slotResults.Add(new { slot = ownerName + "." + slot.Field, fieldType = fi.FieldType.FullName,
                    isStatic = fi.IsStatic, valueIsNull = true,
                    expected = slot.TargetType + "::" + slot.TargetMethod,
                    verdict = "slot-null-in-live-process" });
                continue;
            }
            if (value is Delegate del)
            {
                var m = del.Method;
                // A generated proxy is only a match after its full forwarding body and
                // resolved call token agree with the already-validated editor profile.
                if (m.DeclaringType == null)
                {
                    dynamicMethods++;
                    bool dynamicMatch = false;
                    object dynamicEvidence;
                    try
                    {
                        var candidates = asm.GetType(slot.TargetType, false)?.GetMethods(Statics | Fields)
                            .Where(target => target.Name == slot.TargetMethod).ToArray();
                        if (candidates == null || candidates.Length != 1)
                        {
                            dynamicEvidence = new { Verified = false, Reason = "expected-target-not-unique",
                                candidateCount = candidates?.Length ?? 0 };
                        }
                        else
                        {
                            var verification = DynamicProxyVerifier.Verify(del, candidates[0]);
                            dynamicMatch = verification.Verified;
                            dynamicEvidence = verification;
                        }
                    }
                    catch (Exception ex)
                    {
                        dynamicEvidence = new { Verified = false, Reason = "dynamic-verification-exception",
                            error = ex.GetType().Name + ": " + ex.Message };
                    }
                    if (dynamicMatch) { matched++; dynamicVerified++; }
                    else { mismatched++; dynamicUnresolved++; }
                    slotResults.Add(new { slot = ownerName + "." + slot.Field, fieldType = fi.FieldType.FullName,
                        isStatic = fi.IsStatic, valueIsNull = false,
                        delegateType = del.GetType().FullName,
                        methodRuntimeType = m.GetType().FullName,
                        expected = slot.TargetType + "::" + slot.TargetMethod,
                        verdict = dynamicMatch ? "MATCH" : "DYNAMIC-UNVERIFIED",
                        verificationKind = "read-only-dynamic-il", dynamicEvidence });
                    continue;
                }
                var actualType = m.DeclaringType.FullName;
                var actualMethod = m.Name;
                var ok = actualType == slot.TargetType && actualMethod == slot.TargetMethod;
                if (ok) matched++; else mismatched++;
                slotResults.Add(new { slot = ownerName + "." + slot.Field, fieldType = fi.FieldType.FullName,
                    isStatic = fi.IsStatic, valueIsNull = false,
                    delegateType = del.GetType().FullName,
                    actualTarget = actualType + "::" + actualMethod,
                    expected = slot.TargetType + "::" + slot.TargetMethod,
                    verdict = ok ? "MATCH" : "MISMATCH" });
                continue;
            }
            slotResults.Add(new { slot = ownerName + "." + slot.Field, fieldType = fi.FieldType.FullName,
                isStatic = fi.IsStatic, valueIsNull = false,
                valueType = value.GetType().FullName,
                expected = slot.TargetType + "::" + slot.TargetMethod,
                verdict = "not-a-delegate" });
            mismatched++;
        }

        // The resource registry is the object every editing operation acts on; count it
        // from the live process so the interface claim is tied to real content.
        int resourceCount = -1, graphCount = -1, entityCount = -1, prefabCount = -1;
        string registryError = "";
        try
        {
            var resources = Resources();
            resourceCount = resources.Count;
            graphCount = resources.Count(r => r.Kind == 9);
            entityCount = entities.Count;
            prefabCount = prefabModels.Count;
        }
        catch (Exception ex) { registryError = ex.Message; }
        // Missing or unresolved required evidence is incomplete, not a match.
        bool complete = VerifySlots.Length > 0 && matched == VerifySlots.Length &&
            missing == 0 && mismatched == 0 && matchedNull == 0 && dynamicUnresolved == 0 &&
            targetBad == 0 && requiredTypesMissing == 0 && producerOk &&
            registryError.Length == 0 && resourceCount >= 0;

        return new
        {
            ok = complete,
            status = complete ? "live-interface-surface-matches-static-analysis"
                                                    : "live-interface-surface-requires-review",
            scope = "read-only reflection; no dispatcher invocation, no command sent, no model mutated",
            counts = new { slots = VerifySlots.Length, matched, matchedNull, mismatched, missing, dynamicMethods,
                           dynamicVerified, dynamicUnresolved,
                           targetsOk = targetOk, targetsBad = targetBad, requiredTypesMissing },
            types = typeResults,
            targets = targetResults,
            producer = producerState,
            slots = slotResults,
            liveRegistry = new { resourceCount, graphCount, entityCount, prefabCount, error = registryError },
            sentToGame = false,
            persistentSaveVerified = false,
            playtestVerified = false
        };
    }
}
