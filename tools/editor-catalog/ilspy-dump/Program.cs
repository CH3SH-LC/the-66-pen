// ilspy-dump — inventory tool for the (name-obfuscated) Miliastra editor assemblies.
//
// The editor's own assemblies have had every type/method/field renamed to a random
// string, so symbol names carry no meaning. String literals, however, are left in
// plaintext. Those literals are therefore the only reliable anchor for working out
// what an otherwise anonymous method does.
//
// Commands:
//   strings <asm> <outFile> [minLen]   every ldstr literal, as TYPE\tMETHOD\tSTRING
//   all     <asm> <outDir>             full decompile, filesystem-safe file names
//   il      <asm> <typeFullName> <methodName> raw method IL to stdout
//   decomp  <asm> <typeFullName>       decompile one type to stdout
//   findstr <asm> <substr> <outFile>   types/methods whose literals contain substr
//   types   <asm> <outFile>            type list
//
// Read-only with respect to the editor install: nothing here writes into the game
// directory. Output goes only to the paths given on the command line.

using System.Reflection.Metadata;
using System.Reflection.Metadata.Ecma335;
using System.Reflection.PortableExecutable;
using System.Text;
using ICSharpCode.Decompiler;
using ICSharpCode.Decompiler.CSharp;
using ICSharpCode.Decompiler.Metadata;

class Program
{
    // ---- IL operand size tables (ECMA-335) -------------------------------
    static readonly HashSet<byte> One = new()
    {
        0x0E, 0x0F, 0x10, 0x11, 0x12, 0x13, 0x1F,
        0x2B, 0x2C, 0x2D, 0x2E, 0x2F, 0x30, 0x31, 0x32, 0x33,
        0x34, 0x35, 0x36, 0x37, 0xDE,
    };

    static readonly HashSet<byte> Four = new()
    {
        0x20, 0x22, 0x27, 0x28, 0x29, 0x38, 0x39, 0x3A, 0x3B, 0x3C, 0x3D,
        0x3E, 0x3F, 0x40, 0x41, 0x42, 0x43, 0x44,
        0x70, 0x71, 0x72, 0x73, 0x74, 0x75, 0x79, 0x7B, 0x7C, 0x7D, 0x7E,
        0x7F, 0x80, 0x81, 0x8C, 0x8D, 0x8F, 0xA3, 0xA4, 0xA5, 0xC2, 0xC6,
        0xD0, 0xDD,
    };

    static readonly HashSet<byte> Eight = new() { 0x21, 0x23 };

    static readonly HashSet<byte> FeOne = new() { 0x12, 0x19 };
    static readonly HashSet<byte> FeTwo = new() { 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E };
    static readonly HashSet<byte> FeFour = new() { 0x06, 0x07, 0x15, 0x16, 0x1C };

    /// <summary>Walks a method body and yields the metadata token of every ldstr.</summary>
    static IEnumerable<int> LdstrTokens(byte[] il)
    {
        int i = 0;
        while (i < il.Length)
        {
            byte op = il[i];
            if (op == 0xFE)
            {
                if (i + 1 >= il.Length) yield break;
                byte b1 = il[i + 1];
                int len = FeTwo.Contains(b1) ? 3 : FeFour.Contains(b1) ? 6 : FeOne.Contains(b1) ? 3 : 2;
                i += len;
                continue;
            }
            if (op == 0x72) // ldstr
            {
                if (i + 5 <= il.Length) yield return BitConverter.ToInt32(il, i + 1);
                i += 5;
                continue;
            }
            if (op == 0x45) // switch
            {
                if (i + 5 > il.Length) yield break;
                int n = BitConverter.ToInt32(il, i + 1);
                if (n < 0 || n > 0x100000) yield break;
                i += 5 + 4 * n;
                continue;
            }
            int size = Four.Contains(op) ? 5 : Eight.Contains(op) ? 9 : One.Contains(op) ? 2 : 1;
            i += size;
        }
    }

    static string TypeFullName(MetadataReader md, TypeDefinitionHandle h)
    {
        var td = md.GetTypeDefinition(h);
        string ns = md.GetString(td.Namespace), nm = md.GetString(td.Name);
        var self = string.IsNullOrEmpty(ns) ? nm : ns + "." + nm;
        var decl = td.GetDeclaringType();
        return decl.IsNil ? self : TypeFullName(md, decl) + "/" + nm;
    }

    static string SafeName(string s)
    {
        var sb = new StringBuilder(s.Length);
        foreach (char c in s)
            sb.Append(char.IsLetterOrDigit(c) || c == '.' || c == '_' || c == '-' ? c : '_');
        var r = sb.ToString();
        return r.Length <= 180 ? r : r.Substring(0, 180);
    }

    // The #US heap also carries a "won't be used" marker; the token high byte is 0x70.
    static string ResolveUserString(MetadataReader md, int token, UserStringHandle[] none = null)
    {
        if ((token & unchecked((int)0xFF000000)) != unchecked((int)0x70000000)) return null;
        var h = MetadataTokens.UserStringHandle(token & 0x00FFFFFF);
        try { return md.GetUserString(h); } catch { return null; }
    }

    static int Main(string[] args)
    {
        if (args.Length < 2) { Console.Error.WriteLine("usage: <cmd> <asm> [...]"); return 2; }
        string cmd = args[0], path = args[1];
        try
        {
            switch (cmd)
            {
                case "types":
                {
                    using var fs = File.OpenRead(path);
                    using var pe = new PEReader(fs);
                    var md = pe.GetMetadataReader();
                    var sb = new StringBuilder();
                    foreach (var h in md.TypeDefinitions) sb.AppendLine(TypeFullName(md, h));
                    if (args.Length > 2) File.WriteAllText(args[2], sb.ToString());
                    else Console.Write(sb.ToString());
                    Console.Error.WriteLine("types written");
                    break;
                }

                case "strings":
                {
                    string outFile = args.Length > 2 ? args[2] : null;
                    int minLen = args.Length > 3 ? int.Parse(args[3]) : 2;
                    using var fs = File.OpenRead(path);
                    using var pe = new PEReader(fs);
                    var md = pe.GetMetadataReader();
                    var sb = new StringBuilder();
                    int n = 0;
                    foreach (var h in md.TypeDefinitions)
                    {
                        var td = md.GetTypeDefinition(h);
                        string full = TypeFullName(md, h);
                        foreach (var mh in td.GetMethods())
                        {
                            var m = md.GetMethodDefinition(mh);
                            if (m.RelativeVirtualAddress == 0) continue;
                            byte[] il;
                            try { il = pe.GetMethodBody(m.RelativeVirtualAddress).GetILBytes(); }
                            catch { continue; }
                            string mname = md.GetString(m.Name);
                            foreach (int tok in LdstrTokens(il))
                            {
                                var s = ResolveUserString(md, tok);
                                if (s == null || s.Length < minLen) continue;
                                sb.Append(full).Append('\t').Append(mname).Append('\t')
                                  .Append(s.Replace("\r", "\\r").Replace("\n", "\\n")).Append('\n');
                                n++;
                            }
                        }
                    }
                    if (outFile != null) File.WriteAllText(outFile, sb.ToString());
                    else Console.Write(sb.ToString());
                    Console.Error.WriteLine($"ldstr literals: {n}");
                    break;
                }

                case "il":
                {
                    if(args.Length != 4) throw new ArgumentException("il <asm> <typeFullName> <methodName>");
                    using var module = new PEFile(path);
                    var metadata = module.Metadata;
                    int matches = 0;
                    var dis = new ICSharpCode.Decompiler.Disassembler.ReflectionDisassembler(
                        new ICSharpCode.Decompiler.PlainTextOutput(Console.Out), CancellationToken.None);
                    foreach(var th in metadata.TypeDefinitions)
                    {
                        if(TypeFullName(metadata, th) != args[2]) continue;
                        foreach(var mh in metadata.GetTypeDefinition(th).GetMethods())
                        {
                            if(metadata.GetString(metadata.GetMethodDefinition(mh).Name) != args[3]) continue;
                            dis.DisassembleMethod(module, mh);
                            matches++;
                        }
                    }
                    if(matches == 0) throw new InvalidOperationException("METHOD_NOT_FOUND");
                    break;
                }

                case "decomp":
                {
                    var settings = new DecompilerSettings(LanguageVersion.Latest)
                    { ThrowOnAssemblyResolveErrors = false, ShowXmlDocumentation = false };
                    var decomp = new CSharpDecompiler(path, settings);
                    Console.WriteLine(decomp.DecompileTypeAsString(
                        new ICSharpCode.Decompiler.TypeSystem.FullTypeName(args[2])));
                    break;
                }

                case "all":
                {
                    string outdir = args[2];
                    Directory.CreateDirectory(outdir);
                    var settings = new DecompilerSettings(LanguageVersion.Latest)
                    { ThrowOnAssemblyResolveErrors = false, ShowXmlDocumentation = false };
                    var decomp = new CSharpDecompiler(path, settings);
                    using var fs = File.OpenRead(path);
                    using var pe = new PEReader(fs);
                    var md = pe.GetMetadataReader();
                    int ok = 0, err = 0;
                    foreach (var h in md.TypeDefinitions)
                    {
                        string full = TypeFullName(md, h);
                        if (full.StartsWith("<")) continue;
                        string safe = SafeName(full);
                        try
                        {
                            var txt = decomp.DecompileTypeAsString(
                                new ICSharpCode.Decompiler.TypeSystem.FullTypeName(full));
                            File.WriteAllText(Path.Combine(outdir, safe + ".cs"), txt);
                            ok++;
                        }
                        catch (Exception ex)
                        {
                            File.WriteAllText(Path.Combine(outdir, "_ERR_" + safe + ".txt"), ex.ToString());
                            err++;
                        }
                        if ((ok + err) % 500 == 0) Console.Error.WriteLine($"  ...{ok + err}");
                    }
                    Console.Error.WriteLine($"decompiled: {ok}, errors: {err}");
                    break;
                }

                case "findstr":
                {
                    string sub = args[2];
                    using var fs = File.OpenRead(path);
                    using var pe = new PEReader(fs);
                    var md = pe.GetMetadataReader();
                    var sb = new StringBuilder();
                    int hits = 0;
                    foreach (var h in md.TypeDefinitions)
                    {
                        var td = md.GetTypeDefinition(h);
                        string full = TypeFullName(md, h);
                        foreach (var mh in td.GetMethods())
                        {
                            var m = md.GetMethodDefinition(mh);
                            if (m.RelativeVirtualAddress == 0) continue;
                            byte[] il;
                            try { il = pe.GetMethodBody(m.RelativeVirtualAddress).GetILBytes(); }
                            catch { continue; }
                            foreach (int tok in LdstrTokens(il))
                            {
                                var s = ResolveUserString(md, tok);
                                if (s == null || s.IndexOf(sub, StringComparison.OrdinalIgnoreCase) < 0) continue;
                                sb.Append(full).Append('\t').Append(md.GetString(m.Name))
                                  .Append('\t').Append(s.Replace("\r", "\\r").Replace("\n", "\\n")).Append('\n');
                                hits++;
                            }
                        }
                    }
                    if (args.Length > 3) File.WriteAllText(args[3], sb.ToString());
                    else Console.Write(sb.ToString());
                    Console.Error.WriteLine($"hits: {hits}");
                    break;
                }

                default: Console.Error.WriteLine("unknown cmd"); return 2;
            }
            return 0;
        }
        catch (Exception ex) { Console.Error.WriteLine("ERR: " + ex); return 1; }
    }
}
