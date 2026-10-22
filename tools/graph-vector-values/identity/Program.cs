using System;
using System.IO;
using System.Linq;
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;
using System.Security.Cryptography;
using System.Text.Json;

// Reads PE metadata only. The candidate DLL's code is never loaded or executed.
public static class Program
{
    public static int Main(string[] args)
    {
        var path=Path.GetFullPath(args[0]);
        var bytes=File.ReadAllBytes(path);
        using var file=new MemoryStream(bytes,false);
        using var pe=new PEReader(file);
        var metadata=pe.GetMetadataReader();
        var definition=metadata.GetAssemblyDefinition();
        var names=metadata.MethodDefinitions.Select(h=>metadata.GetString(metadata.GetMethodDefinition(h).Name)).ToHashSet();
        var required=new[]{"AuthorVectorPayload","AuthorWriteVector3","AuthorReadVector3","AuthorRunVectorWrite"};
        Console.WriteLine(JsonSerializer.Serialize(new {
            path,name=metadata.GetString(definition.Name),
            mvid=metadata.GetGuid(metadata.GetModuleDefinition().Mvid).ToString("D"),
            sha256=Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant(),
            vectorMethods=required.Where(names.Contains).ToArray()
        }));
        return 0;
    }
}
