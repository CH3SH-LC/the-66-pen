using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;

namespace Miliastra.EditorBridge;

// Report the assembly actually executing inside the host, not a revision
// guessed from a filename. A cached old assembly cannot acquire this receipt.
internal static class BuildIdentity
{
    internal static object Snapshot()
    {
        var assembly=typeof(BuildIdentity).Assembly;
        try {
            return new Dictionary<string,object?> {
                ["name"]=assembly.GetName().Name,
                ["mvid"]=assembly.ManifestModule.ModuleVersionId.ToString("D"),
                ["path"]=Path.GetFullPath(assembly.Location),
                ["sha256"]=Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(assembly.Location))).ToLowerInvariant(),
                ["graphVector3Contract"]=1,
            };
        } catch(Exception error) {
            return new Dictionary<string,object?> { ["error"]=error.GetType().Name,
                ["name"]=assembly.GetName().Name, ["graphVector3Contract"]=0 };
        }
    }
}
