using System.Diagnostics;
using System.Text;
using System.Text.Json;

internal static class Guard
{
    const string Editor=@"C:\Games\Genshin Impact Game\BeyondAssets\BeyondAssistEditor\BeyondEditor.exe";
    internal static string Root() {
        for(var p=new DirectoryInfo(AppContext.BaseDirectory);p!=null;p=p.Parent)
            if(File.Exists(Path.Combine(p.FullName,"AGENT.md")))return p.FullName;
        throw new ScopeError("PROJECT_ROOT_MISSING");
    }
    internal static void Validate(string run,int target)
    {
        if(!OperatingSystem.IsWindows())throw new ScopeError("WINDOWS_REQUIRED");
        string file=Path.Combine(Root(),".runtime","verification","editor-host",run,"events.jsonl");
        if(!File.Exists(file)||new FileInfo(file).Length>65536)throw new ScopeError("HOST_RECORD_INVALID");
        var lines=File.ReadAllLines(file).Where(x=>!string.IsNullOrWhiteSpace(x)).ToArray();
        if(lines.Length!=1)throw new ScopeError("HOST_RECORD_NOT_ACTIVE");
        using var record=JsonDocument.Parse(lines[0]);var start=record.RootElement;
        if(start.GetProperty("event").GetString()!="started"||start.GetProperty("source").GetString()!="project-python-parent-not-genshin")throw new ScopeError("HOST_RECORD_NOT_ACTIVE");
        int host=start.GetProperty("hostPID").GetInt32(),child=start.GetProperty("editorPID").GetInt32();
        var argv=start.GetProperty("argv").EnumerateArray().Select(x=>x.GetString()).ToArray();
        if(argv.Length<5||argv[0]!=Editor||argv[3]!="-sourcepid"||argv[4]!=host.ToString())throw new ScopeError("HOST_RECORD_INVALID");
        string script="$ErrorActionPreference='Stop';[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false);$r=@(Get-CimInstance Win32_Process|ForEach-Object {@{pid=[int]$_.ProcessId;parent=[int]$_.ParentProcessId;name=$_.Name;path=$_.ExecutablePath;hostCommand=$(if($_.ProcessId -eq "+host+"){ $_.CommandLine }else{ $null })}});ConvertTo-Json -InputObject $r -Compress";
        // 必须显式指定 UTF-8：子脚本按 UTF-8 写出（见上面的 [Console]::OutputEncoding），
        // 而 .NET 的 StandardOutputEncoding 默认取父进程控制台编码 —— 中文 Windows 上是 GB2312/936。
        // 用 GB2312 解码 UTF-8 会错位，尾字节可能落在 0x5C('\\') 或 0x22('"')，
        // 从而向 JSON 注入伪转义序列，使下面的 JsonDocument.Parse 抛 JsonReaderException。
        // 实测（2026-09-15）：不设此值 -> 解析失败「无法识别的转义序列」(39261)；设为 UTF8 -> 成功(495 进程)。
        // 详见 .runtime/verification/editor-experiment-2/ROOT-CAUSE-guard-encoding.md
        var psi=new ProcessStartInfo("powershell.exe"){UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true,StandardOutputEncoding=new UTF8Encoding(false),StandardErrorEncoding=new UTF8Encoding(false)};
        foreach(var arg in new[]{"-NoProfile","-NonInteractive","-EncodedCommand",Convert.ToBase64String(Encoding.Unicode.GetBytes(script))})psi.ArgumentList.Add(arg);
        using var query=Process.Start(psi)??throw new ScopeError("PROCESS_QUERY_FAILED");
        var output=query.StandardOutput.ReadToEndAsync();var errors=query.StandardError.ReadToEndAsync();
        if(!query.WaitForExit(15000)){query.Kill();query.WaitForExit();throw new ScopeError("PROCESS_QUERY_FAILED");}
        if(query.ExitCode!=0)throw new ScopeError("PROCESS_QUERY_FAILED");
        using var snapshot=JsonDocument.Parse(output.GetAwaiter().GetResult());
        ValidateRows(snapshot.RootElement,target,host,child);
        using var hp=Process.GetProcessById(host);using var tp=Process.GetProcessById(target);
        if(hp.HasExited||tp.HasExited||hp.StartTime.ToUniversalTime()>File.GetLastWriteTimeUtc(file)||tp.StartTime.ToUniversalTime()<hp.StartTime.ToUniversalTime())throw new ScopeError("TARGET_RESTARTED");
        if(!File.ReadAllText(file).Trim().Equals(lines[0].Trim(),StringComparison.Ordinal))throw new ScopeError("HOST_RECORD_NOT_ACTIVE");
    }
    internal static void ValidateRows(JsonElement snapshot,int target,int host,int child)
    {
        var rows=snapshot.EnumerateArray().ToDictionary(r=>r.GetProperty("pid").GetInt32());
        var chain=new HashSet<int>();int current=target;
        for(int i=0;i<10&&current!=host;i++) {
            if(!chain.Add(current)||!rows.TryGetValue(current,out var row)||!string.Equals(row.GetProperty("path").GetString(),Editor,StringComparison.OrdinalIgnoreCase))throw new ScopeError("PEER_CHAIN_INVALID");
            current=row.GetProperty("parent").GetInt32();
        }
        if(current!=host||!chain.Contains(child)||!rows.TryGetValue(host,out var h))throw new ScopeError("PEER_CHAIN_INVALID");
        string command=h.GetProperty("hostCommand").GetString()??"";
        if(!command.Contains("-m bridge.editor_host run --lease-seconds ",StringComparison.Ordinal)||!(h.GetProperty("name").GetString()??"").Equals("python.exe",StringComparison.OrdinalIgnoreCase))throw new ScopeError("HOST_IDENTITY_INVALID");
        foreach(var row in rows.Values) {
            string name=row.GetProperty("name").GetString()??"",path=row.GetProperty("path").GetString()??"";
            if(name.Length==0&&path.Length==0)throw new ScopeError("PROCESS_QUERY_FAILED");
            if(name.Equals("YuanShen.exe",StringComparison.OrdinalIgnoreCase)||name.Equals("GenshinImpact.exe",StringComparison.OrdinalIgnoreCase))throw new ScopeError("GAME_PRESENT");
            if((name.Equals("BeyondEditor.exe",StringComparison.OrdinalIgnoreCase)||path.Equals(Editor,StringComparison.OrdinalIgnoreCase))&&!chain.Contains(row.GetProperty("pid").GetInt32()))throw new ScopeError("UNOWNED_EDITOR");
        }
    }
    internal static void SelfTest()
    {
        var baseline=new[]{new{pid=40,parent=30,name="BeyondEditor.exe",path=Editor,hostCommand=""},new{pid=30,parent=1,name="python.exe",path="fixture-python",hostCommand="python -m bridge.editor_host run --lease-seconds 60"}};
        using(var good=JsonDocument.Parse(JsonSerializer.Serialize(baseline)))ValidateRows(good.RootElement,40,30,40);
        foreach(string mode in new[]{"game","other","path","parent","host"})
        {
            var rows=baseline.ToList();
            if(mode=="game")rows.Add(new{pid=41,parent=1,name="YuanShen.exe",path="",hostCommand=""});
            if(mode=="other")rows.Add(new{pid=41,parent=1,name="BeyondEditor.exe",path=Editor,hostCommand=""});
            if(mode=="path")rows[0]=new{pid=40,parent=30,name="BeyondEditor.exe",path="wrong",hostCommand=""};
            if(mode=="parent")rows[0]=new{pid=40,parent=1,name="BeyondEditor.exe",path=Editor,hostCommand=""};
            if(mode=="host")rows[1]=new{pid=30,parent=1,name="python.exe",path="fixture-python",hostCommand="unrelated"};
            using var doc=JsonDocument.Parse(JsonSerializer.Serialize(rows));bool refused=false;
            try{ValidateRows(doc.RootElement,40,30,40);}catch(ScopeError){refused=true;}
            if(!refused)throw new ScopeError("GUARD_TEST_FAILED");
        }
    }
}
