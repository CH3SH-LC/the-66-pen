using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;

namespace Miliastra.EditorBridge;

// Read-only. The editor's command names are NOT recoverable from its binary: BeyondEditor.dll
// is protected with ConfuserEx (anti-tamper resource names {11111-22222-...}, "Debugger
// Detected", "is tampered."), and ConfuserEx string encryption moves every string literal OUT
// of the metadata #US heap -- measured 2026-10-11, the shipped assembly's #US stream is 684
// bytes while the file is 18,404,248 bytes. So a byte-grep of the dll is a false negative by
// construction, and Module.ResolveString can only ever return that empty heap.
//
// At RUNTIME the editor must materialise the plaintext or its own UI cannot dispatch. Those
// decrypted System.String objects live on this process's heap as plain UTF-16LE. This op reads
// THIS process's own committed, readable pages -- no other process, no writes, nothing invoked
// -- and reports every string that looks like an editor command.
//
// THE INSTRUMENT MUST NOT BE PART OF THE MEASUREMENT (learned the hard way, 2026-10-11)
//   First cut failed: the bridge dll is mapped into the same process AND the CLR interns its
//   string literals onto the same GC heap, so a needle table written as literals found itself.
//   Two independent defences now apply:
//     1. MAPPED-FILE EXCLUSION -- any page whose backing file name contains "miliastra" is
//        skipped (GetMappedFileNameW). That removes every bridge revision's image strings.
//     2. NO PLAINTEXT NEEDLE IN THIS ASSEMBLY -- the control list is carried as HEX of the
//        ASCII bytes (a hex literal cannot spell a command) and is decoded ONLY AFTER the scan
//        finishes, so the scan can never observe its own needles.
//   With both, a hit is a string that some OTHER code put in memory.
//
// WHY A SELF-SCAN AND NOT AN EXTERNAL ONE
//   BeyondEditor.exe runs ELEVATED; a same-user OpenProcess(PROCESS_VM_READ) is refused with
//   ERROR_ACCESS_DENIED (measured 2026-10-11). The bridge is already inside the process, so a
//   self-scan needs no elevation, no UAC and no second injection channel.
internal sealed partial class EditorAdapter
{
    const long MineMaxBytes = 2L * 1024 * 1024 * 1024;
    const int MineChunkBytes = 1 << 20;
    const int MineOverlapBytes = 96;
    const int MineMaxRegions = 400000;
    const int MineMaxDistinct = 8000;
    const int MineMaxTokenLen = 120;

    [StructLayout(LayoutKind.Sequential)]
    struct MemBasicInformation64
    {
        public IntPtr BaseAddress;
        public IntPtr AllocationBase;
        public uint AllocationProtect;
        public uint Alignment1;
        public IntPtr RegionSize;
        public uint State;
        public uint Protect;
        public uint Type;
        public uint Alignment2;
    }

    const uint MemCommit = 0x1000;
    const uint MemImage = 0x1000000;
    const uint MemMapped = 0x40000;
    const uint PageNoAccess = 0x01;
    const uint PageGuard = 0x100;

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern IntPtr VirtualQuery(IntPtr lpAddress, out MemBasicInformation64 lpBuffer, IntPtr dwLength);

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool ReadProcessMemory(IntPtr hProcess, IntPtr lpBaseAddress, [Out] byte[] lpBuffer,
        IntPtr dwSize, out IntPtr lpNumberOfBytesRead);

    [DllImport("kernel32.dll")]
    static extern IntPtr GetCurrentProcess();

    [DllImport("psapi.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern uint GetMappedFileNameW(IntPtr hProcess, IntPtr lpv, StringBuilder lpFilename, uint nSize);

    static bool MineReadable(uint protect)
    {
        if ((protect & PageGuard) != 0) return false;
        if ((protect & PageNoAccess) != 0) return false;
        uint basic = protect & 0xFF;
        return basic == 0x02 || basic == 0x04 || basic == 0x08 || basic == 0x20 || basic == 0x40 || basic == 0x80;
    }

    // True when this page is backed by a file whose name identifies the instrument itself.
    // The bridge payload, the bootstrap and every previously injected revision are mapped this
    // way; their #US heaps hold OUR command literals and must never be counted as the editor's.
    static bool MineIsInstrumentPage(IntPtr hProcess, IntPtr baseAddress)
    {
        var sb = new StringBuilder(512);
        uint n = GetMappedFileNameW(hProcess, baseAddress, sb, (uint)sb.Capacity);
        if (n == 0) return false;
        return sb.ToString().IndexOf("miliastra", StringComparison.OrdinalIgnoreCase) >= 0;
    }

    // Full-identifier discovery. Three shapes, all read-only and all free of any complete
    // command literal (so none can match itself):
    //   For-family  -- the verb "For" joins a verb to its target (DeleteComponentForEditObj)
    //   Named       -- an identifier naming a component / graph / prefab / edit-object
    //   Verb+CamelCase -- a known command verb followed by an UpperCased noun (FocusLight)
    static readonly Regex MineForFamily =
        new(@"\b[A-Za-z][A-Za-z0-9_]*For[A-Za-z0-9_]*\b", RegexOptions.Compiled);
    static readonly Regex MineNamed =
        new(@"\b[A-Za-z][A-Za-z0-9_]*(Component|InstructionGraph|EditObj|Prefab|EditObject)[A-Za-z0-9_]*\b", RegexOptions.Compiled);
    static readonly Regex MineVerbNoun =
        new(@"\b(Focus|Modify|Delete|Add|Request|Apply|Jump|Import|Export|Create|Set|Write|Attach|Insert|Copy|Alias|Acquire|Refresh)[A-Z][A-Za-z0-9_]{3,}\b", RegexOptions.Compiled);

    // The control list, HEX of the ASCII bytes. Deliberately unintelligible: this assembly must
    // not contain the plaintext it is looking for. Decoded only after the walk, in MineDecode.
    static readonly string[] MineControlHex =
    {
        // positive controls demanded by the task
        "44656C657465436F6D706F6E656E74466F72456469744F626A", // DeleteComponentForEditObj
        "416464496E737472756374696F6E4772617068466F72456469744F626A", // AddInstructionGraphForEditObj
        // the other 25 of the native FNV-1a dispatcher set (docs/research/reverse-eng-20261011)
        "466F6375734C6F63616C42756C6C6574", "416464496E737472756374696F6E4772617068466F72507265666162",
        "4D6F6469667946616374696F6E466F72507265666162", "4D6F6469667946616374696F6E466F72456469744F626A",
        "44656C657465496E737472756374696F6E4772617068466F72456469744F626A", "466F637573436861726163746572",
        "4D6F64696679507265666162546167", "44656C657465496E737472756374696F6E4772617068466F72507265666162",
        "44656C657465436F6D706F6E656E74466F72507265666162", "4170706C79507265666162496E7374616E63654368616E6765",
        "44656C657465456469744F626A", "466F637573456469744F626A", "466F6375734265796F6E6454696C654D6170",
        "44656C657465507265666162", "4A756D70436F6D62617453657474696E67", "52657175657374507265666162496E7374616E6365",
        "4D6F64696679456469744F626A4E616D65", "466F637573457370", "466F637573507265666162496E7374616E6365",
        "4D6F646966795072656661624E616D65", "4D6F64696679456469746F626A546167", "466F63757344726F70476174686572",
        "466F63757353637265656E73686F74", "4D6F646966795375697465", "466F6375734C69676874",
        // second dispatcher (beyondExportService)
        "446F4578706F7274", "446F496D706F7274", "496D706F727444656275674C6F67",
        "496D706F7274416C6C44656275674C6F67", "44656C65746544656275674C6F67", "52656672657368457869737444656275674C6F675265706F7274",
        // channels (recovered live by verify-channels)
        "6265796F6E64456469744F626A53657276696365", "6265796F6E64496E737472756374696F6E477261706853657276696365",
        "6265796F6E644578706F727453657276696365", "6265796F6E64504347496E7374616E636553657276696365",
        "777066417564696F53657276696365", "777066496E737472756374696F6E477261706853657276696365",
        // hypotheses whose ABSENCE is the point
        "416464436F6D706F6E656E74466F72456469744F626A", "416464436F6D706F6E656E74466F72507265666162",
        "437265617465436F6D706F6E656E74466F72456469744F626A", "417474616368436F6D706F6E656E74466F72456469744F626A",
        "496E73657274436F6D706F6E656E74466F72456469744F626A", "416464436F6D706F6E656E74", "437265617465436F6D706F6E656E74",
        "417474616368436F6D706F6E656E74", "496E73657274436F6D706F6E656E74", "43726561746554656D706C617465",
        "4372656174654173736574", "4D6F646966795465727261696E", "5365745465727261696E", "57726974655465727261696E", "456469745465727261696E",
        "4164644576656E74436F6D706F6E656E74466F72456469744F626A", "5365745465727261696E486569676874",
        // live-only names observed in the first (contaminated) pass; absent from every bridge dll
        "44656C657465436F6D706F6E656E74466F7250726566616232", "416C696173436F6D706F6E656E74",
        "437573746F6D496E737472756374696F6E4772617068", "437573746F6D507265666162",
        // SENTINEL: a token no code in this process can contain. It calibrates the false-positive
        // floor of the walk; a non-zero `present` here invalidates the whole reply.
        "51715A7A496E737472756D656E7453656E74696E656C546F6B656E",
    };

    static string MineDecode(string hex)
    {
        var bytes = new byte[hex.Length / 2];
        for (int i = 0; i < bytes.Length; i++)
            bytes[i] = byte.Parse(hex.Substring(i * 2, 2), NumberStyles.HexNumber, CultureInfo.InvariantCulture);
        return Encoding.ASCII.GetString(bytes);
    }

    public object MineProcessStrings()
    {
        var sw = Stopwatch.StartNew();
        var handle = GetCurrentProcess();
        var ascii = Encoding.Latin1;
        var utf16 = Encoding.Unicode;

        var commandLike = new Dictionary<string, int[]>(StringComparer.Ordinal);
        bool distinctCapped = false;

        long scanned = 0, readableBytes = 0, excludedBytes = 0;
        int regions = 0, regionsScanned = 0, regionsExcluded = 0, readFailures = 0;

        var chunk = new byte[MineChunkBytes + MineOverlapBytes];
        long address = 0x10000;
        const long ceiling = 0x00007FFFFFFFFFFF;

        while (address < ceiling && regions < MineMaxRegions && scanned < MineMaxBytes)
        {
            if (VirtualQuery(new IntPtr(address), out var mbi, new IntPtr(Marshal.SizeOf<MemBasicInformation64>())) == IntPtr.Zero)
                break;
            regions++;
            long baseAddr = mbi.BaseAddress.ToInt64();
            long regionSize = mbi.RegionSize.ToInt64();
            if (regionSize <= 0) break;

            bool eligible = mbi.State == MemCommit && MineReadable(mbi.Protect) && mbi.Type != 0;
            if (eligible && (mbi.Type == MemImage || mbi.Type == MemMapped) && MineIsInstrumentPage(handle, mbi.BaseAddress))
            {
                eligible = false;
                regionsExcluded++;
                excludedBytes += regionSize;
            }
            if (eligible)
            {
                readableBytes += regionSize;
                regionsScanned++;
                long cursor = baseAddr, regionEnd = baseAddr + regionSize;
                while (cursor < regionEnd && scanned < MineMaxBytes)
                {
                    int want = (int)Math.Min(chunk.Length, regionEnd - cursor);
                    if (ReadProcessMemory(handle, new IntPtr(cursor), chunk, new IntPtr(want), out var got))
                    {
                        int have = (int)got.ToInt64();
                        if (have > 0)
                        {
                            MineHarvest(ascii.GetString(chunk, 0, have), commandLike, ref distinctCapped);
                            MineHarvest(utf16.GetString(chunk, 0, have & ~1), commandLike, ref distinctCapped);
                            scanned += have;
                        }
                    }
                    else readFailures++;
                    long step = want - MineOverlapBytes;
                    cursor += step > 0 ? step : want;
                }
            }
            long next = baseAddr + regionSize;
            if (next <= address) break;
            address = next;
        }

        // The instrument's own needles are materialised ONLY here, after the walk is over, so
        // they cannot have been observed by it.
        var needles = MineControlHex
            .Select(h => MineDecode(h))
            .Select(n => new
            {
                name = n,
                present = commandLike.ContainsKey(n),
                hits = commandLike.TryGetValue(n, out var c) ? c[0] + c[1] : 0,
            })
            .ToArray();

        var tokens = commandLike
            .OrderBy(kv => kv.Key, StringComparer.Ordinal)
            .Select(kv => new { token = kv.Key, asciiHits = kv.Value[0], utf16Hits = kv.Value[1] })
            .ToArray();

        return new
        {
            ok = true,
            status = "process-string-mine-read-only",
            pid = Environment.ProcessId,
            scope = "VirtualQuery + ReadProcessMemory on GetCurrentProcess() only; pages backed by a " +
                    "Miliastra* module are excluded; the op's own needles are not present in this assembly " +
                    "until after the walk; no other handle, no write, no VirtualProtect, nothing invoked",
            bytesScanned = scanned,
            readableBytesSeen = readableBytes,
            instrumentBytesExcluded = excludedBytes,
            regionsVisited = regions,
            regionsScanned,
            regionsExcluded,
            readFailures,
            bytesBudgetHit = scanned >= MineMaxBytes,
            distinctCapped,
            elapsedMs = sw.ElapsedMilliseconds,
            needleCount = needles.Length,
            presentNeedleCount = needles.Count(n => n.present),
            needles,
            commandLikeCount = tokens.Length,
            commandLike = tokens,
            methodInvoked = false,
            nativeMutationInvoked = false,
            localModelWritten = false,
            sentToGame = false,
            persistentSaveVerified = false,
        };
    }

    static void MineHarvest(string text, Dictionary<string, int[]> into, ref bool capped)
    {
        MineHarvestOne(MineForFamily, text, into, ref capped);
        MineHarvestOne(MineNamed, text, into, ref capped);
        MineHarvestOne(MineVerbNoun, text, into, ref capped);
    }

    static void MineHarvestOne(Regex re, string text, Dictionary<string, int[]> into, ref bool capped)
    {
        foreach (Match m in re.Matches(text))
        {
            string tok = m.Value;
            if (tok.Length == 0 || tok.Length > MineMaxTokenLen) continue;
            if (!into.TryGetValue(tok, out var c))
            {
                if (into.Count >= MineMaxDistinct) { capped = true; continue; }
                c = new int[2];
                into[tok] = c;
            }
            c[ReferenceEquals(re, MineForFamily) || ReferenceEquals(re, MineVerbNoun) ? 1 : 0]++;
        }
    }
}
