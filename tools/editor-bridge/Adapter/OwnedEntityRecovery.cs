using System;
namespace Miliastra.EditorBridge;
internal sealed partial class EditorAdapter
{
    // Historical single-session recovery is deliberately not distributed.
    public object BeginOwnedEntityCleanup() => throw new InvalidOperationException("PRIVATE_SESSION_RECOVERY_NOT_DISTRIBUTED");
    public object InspectOwnedEntityCleanup() => throw new InvalidOperationException("PRIVATE_SESSION_RECOVERY_NOT_DISTRIBUTED");
    public object DeleteOwnedEntityCleanup() => throw new InvalidOperationException("PRIVATE_SESSION_RECOVERY_NOT_DISTRIBUTED");
}
