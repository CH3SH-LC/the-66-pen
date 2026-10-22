using System;
using System.IO;
using System.Reflection;
namespace Miliastra.Bootstrap;
public static class Entry
{
    public static int Start(string settingsPath)
    {
        var path=Path.GetFullPath(settingsPath);
        var root=@"<SOURCE_ROOT>\.runtime\editor-bridge\runs\";
        if(!path.StartsWith(root,StringComparison.OrdinalIgnoreCase) || Path.GetFileName(path)!="bridge-settings.json") return 21;
        var log=Path.Combine(Path.GetDirectoryName(path)!,"bootstrap.log");
        try
        {
            File.AppendAllText(log,DateTime.UtcNow.ToString("O")+" bootstrap started; runtime="+Environment.Version+Environment.NewLine);
            var payload=Path.Combine(Path.GetDirectoryName(typeof(Entry).Assembly.Location)!,"Miliastra.EditorBridge.Net8R301.dll");
            var assembly=Assembly.LoadFrom(payload);
            File.AppendAllText(log,"payload loaded: "+assembly.FullName+Environment.NewLine);
            // Log the payload's verdict. Without this the log ends at "payload loaded" whether
            // the bridge came up or was refused, because the rejection paths return a code
            // rather than throwing -- and a refused injection then looks exactly like a hang.
            var code=(int)assembly.GetType("Miliastra.EditorBridge.Entry",true)!.GetMethod("Start")!.Invoke(null,new object[]{path})!;
            File.AppendAllText(log,"payload returned "+code+Environment.NewLine);
            return code;
        }
        catch(Exception ex)
        {
            File.AppendAllText(log,ex.ToString()+Environment.NewLine);
            return 22;
        }
    }
}


