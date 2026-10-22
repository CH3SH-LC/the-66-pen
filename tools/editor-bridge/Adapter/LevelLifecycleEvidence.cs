using System;
using System.Reflection;

namespace Miliastra.EditorBridge;

internal sealed partial class EditorAdapter
{
    // 7.1 initialization payload retained by B17XM7hK1R9. The actual getter
    // K43RBEVRCA5 skips an unreachable obfuscation call and reads yoJRBJp4HeU.
    // Evidence: interface-experiments-20260926/p02/reopen-audit/exact-getters.json.
    // Reading this cache neither initiates a level load nor proves a fresh load.
    object LevelLifecycleSnapshot()
    {
        object? ReadExact(object owner, string ownerType, string name, string fieldType)
        {
            if (owner.GetType().FullName != ownerType)
                throw new InvalidOperationException("LEVEL_CONTEXT_OWNER_TYPE_MISMATCH");
            var field = owner.GetType().GetField(name, Fields | BindingFlags.DeclaredOnly);
            if (field == null || field.FieldType.FullName != fieldType)
                throw new InvalidOperationException("LEVEL_CONTEXT_FIELD_CONTRACT_MISMATCH");
            return field.GetValue(owner);
        }

        var manager = ExistingSingleton(Editor(), B("mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q"));
        const string managerType = "RBvsLtXoVfy2fj2abowI.cnQXC4XoSIRRZGYUssnx";
        const string payloadType = "FnULH5Rwt7ZoyShipQfM.G1dmgnRwicSy3RHXRPwM";
        const string headerType = "PvFe2SR2cEiUZJHHMgIk.MduRq9R20uL9IPOAZEbw";
        var payload = ReadExact(manager, managerType, "YwCXahy5RIN", payloadType);
        var header = payload == null ? null : ReadExact(payload, payloadType, "RmVRLESORxj", headerType);
        uint? identity = header == null ? null : (uint)ReadExact(header, headerType, "yoJRBJp4HeU", "System.UInt32")!;
        return new {
            observedUtc = DateTime.UtcNow,
            source = "editor-retained-level-initialization-payload",
            payloadPresent = payload != null, headerPresent = header != null,
            levelIdCandidate = identity,
            fieldPath = "YwCXahy5RIN.RmVRLESORxj.yoJRBJp4HeU",
            nativeMethodsInvoked = false, sentToGame = false,
            freshnessVerified = false, reloadInvoked = false, reopenVerified = false
        };
    }
}
