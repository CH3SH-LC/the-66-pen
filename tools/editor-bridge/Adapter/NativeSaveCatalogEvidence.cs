using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Security.Cryptography;

namespace Miliastra.EditorBridge;

// Session-specific, external ReadProcessMemory observation. No game function,
// remote allocation, callback, write access, IPC or scene transition is used.
// Layout evidence: interface-experiments-20260926/p02/reload-native/*.asm.
internal static class NativeSaveCatalogEvidence
{
    internal sealed record LevelRow(uint levelId, uint dictionaryKey, string recordPointer);
    const int MaxEntries = 512;
    const string Image = "C:/Games/Genshin Impact Game/YuanShen.exe";
    const string ImageHash = "7f89938da606c1281659607d464702cddb9a09a7d4320a196630f60a811ec38e";
    static readonly uint[] HotfixBytes = {0x56f4a0d,0x5730794,0x56fb435,0x574f93a,0x574f943,0x57756a2,0x57756aa};
    static readonly (uint Rva,int Length,string Hash)[] Anchors = {
        (0x13568db0,0xe5,"845348c0842ad56a9c758bc8bf5461c997d5d6d5377ab25ab15297061689064b"),
        (0x11fc69d0,0xcf,"9b1af9171331d7959395c2355c7fd33295cde89b6ee14b35d3d4fe536f072372"),
        (0x173770b0,0x297,"595ee75edd852d83e7115a124088f9ded61b332c5efb79ca00a5e1a748493623"),
        (0x110004a0,0x15f,"4e2e5660154ffaeb25524f3462f0e0a889ca400cbdc0b21d31ae01b2f6ef4080"),
        (0x11fe3700,0x82,"778e60dc18365e71b2f98e74a50c06362ad6763e0c069fbdc00857668849e6ea")
    };
    static void Require(bool ok,string reason) { if(!ok) throw new InvalidOperationException(reason); }
    static string Hash(byte[] data) => Convert.ToHexString(SHA256.HashData(data)).ToLowerInvariant();

    // Pure parser used by the live reader and corruption fixtures. Occupancy comes
    // from bucket reachability, never from a guessed free-slot marker.
    internal static LevelRow[] ParseDictionary(byte[] header, byte[] buckets, byte[] entries, Func<ulong,uint> readId)
    {
        Require(header.Length==0x48 && buckets.Length>=4 && buckets.Length%4==0 &&
            entries.Length>=24 && entries.Length%24==0,"ARCHIVE_ARRAY_SHAPE");
        int bucketCount=buckets.Length/4, capacity=entries.Length/24;
        Require(bucketCount<=MaxEntries && capacity<=MaxEntries,"ARCHIVE_ARRAY_LIMIT");
        int count=BitConverter.ToInt32(header,0x38),free=BitConverter.ToInt32(header,0x40);
        Require(count>=0 && count<=capacity && free>=0 && free<=count,"ARCHIVE_COUNT_INVALID");
        var seen=new HashSet<int>(); var ids=new HashSet<uint>(); var result=new List<LevelRow>();
        for(int bucket=0;bucket<bucketCount;bucket++)
        {
            int head=BitConverter.ToInt32(buckets,bucket*4);
            Require(head>=0 && head<=capacity,"ARCHIVE_BUCKET_INVALID");
            int index=head-1;
            while(index!=-1)
            {
                Require(index>=0 && index<count && seen.Add(index),"ARCHIVE_CHAIN_INVALID");
                int offset=index*24;
                int hash=BitConverter.ToInt32(entries,offset),next=BitConverter.ToInt32(entries,offset+4);
                uint key=BitConverter.ToUInt32(entries,offset+8);
                ulong value=BitConverter.ToUInt64(entries,offset+16);
                Require(hash>=0 && hash%bucketCount==bucket && hash==(key&0x7fffffff) &&
                    next>=-1 && next<capacity && key!=0 && ids.Add(key),"ARCHIVE_ENTRY_INVALID");
                Require(value>=0x10000 && value<0x0000800000000000 && (value&7)==0,"ARCHIVE_RECORD_POINTER");
                uint id=readId(value);
                Require(id==key,"ARCHIVE_KEY_RECORD_MISMATCH");
                result.Add(new LevelRow(id,key,"0x"+value.ToString("x")));
                index=next;
            }
        }
        Require(result.Count==count-free,"ARCHIVE_OCCUPANCY_INCOMPLETE");
        return result.OrderBy(x=>x.levelId).ToArray();
    }

    [DllImport("kernel32.dll",SetLastError=true)] static extern IntPtr OpenProcess(uint access,bool inherit,int pid);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool ReadProcessMemory(IntPtr process,IntPtr address,byte[] buffer,UIntPtr size,out UIntPtr read);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
    sealed class Reader : IDisposable
    {
        readonly IntPtr handle;
        internal int Calls,Bytes;
        internal Reader(int pid)
        {
            handle=OpenProcess(0x1010,false,pid); // QUERY_LIMITED_INFORMATION | VM_READ only
            Require(handle!=IntPtr.Zero,"ARCHIVE_OPEN_READ_FAILED:"+Marshal.GetLastWin32Error());
        }
        internal byte[] Read(ulong address,int length)
        {
            Require(length>0 && length<=65536 && address>=0x10000 &&
                address<0x0000800000000000-(ulong)length,"ARCHIVE_READ_RANGE");
            Calls++; Bytes+=length; Require(Calls<=4096 && Bytes<=1048576,"ARCHIVE_READ_BUDGET");
            var data=new byte[length];
            Require(ReadProcessMemory(handle,new IntPtr(checked((long)address)),data,(UIntPtr)length,out var read) &&
                read.ToUInt64()==(ulong)length,"ARCHIVE_READ_FAILED:"+Marshal.GetLastWin32Error());
            return data;
        }
        internal ulong Ptr(ulong address) { ulong p=BitConverter.ToUInt64(Read(address,8)); Require(p>=0x10000 && p<0x0000800000000000 && (p&7)==0,"ARCHIVE_POINTER_INVALID"); return p; }
        internal uint U32(ulong address)=>BitConverter.ToUInt32(Read(address,4));
        public void Dispose()=>CloseHandle(handle);
    }

    internal static object Capture()
    {
        // Historical identity is scrubbed; Capture refuses until a newly reviewed local profile exists.
        string stage="process-identity";
        try
        {
            using var editor=Process.GetProcessById(0);
            using var game=Process.GetProcessById(0);
            Require(editor.Id==0 && editor.StartTime.ToUniversalTime().ToFileTimeUtc()==0L &&
                game.StartTime.ToUniversalTime().ToFileTimeUtc()==0L,"ARCHIVE_SESSION_CHANGED");
            stage="main-module";
            var module=game.MainModule ?? throw new InvalidOperationException("ARCHIVE_MAIN_MODULE_MISSING");
            Require(string.Equals(Path.GetFullPath(module.FileName),Path.GetFullPath(Image),StringComparison.OrdinalIgnoreCase),"ARCHIVE_IMAGE_PATH_CHANGED");
            stage="disk-image-hash";
            using(var file=new FileStream(Image,FileMode.Open,FileAccess.Read,FileShare.Read))
                Require(Convert.ToHexString(SHA256.HashData(file)).ToLowerInvariant()==ImageHash,"ARCHIVE_DISK_IMAGE_CHANGED");
            ulong image=checked((ulong)module.BaseAddress.ToInt64());
            stage="open-read-handle";
            using var reader=new Reader(game.Id);
            stage="loaded-code-anchors";
            Require(reader.Read(image,2).SequenceEqual(new byte[]{0x4d,0x5a}),"ARCHIVE_PE_DOS");
            uint pe=reader.U32(image+60); Require(pe<4096,"ARCHIVE_PE_OFFSET");
            Require(reader.U32(image+pe)==0x4550 && reader.U32(image+pe+8)==1788945104 &&
                reader.U32(image+pe+24+56)==453693440,"ARCHIVE_LOADED_IMAGE_CHANGED");
            foreach(var anchor in Anchors) Require(Hash(reader.Read(image+anchor.Rva,anchor.Length))==anchor.Hash,"ARCHIVE_CODE_ANCHOR_CHANGED:"+anchor.Rva.ToString("x"));
            void Hotfix() { foreach(uint rva in HotfixBytes) Require(reader.Read(image+rva,1)[0]==0,"ARCHIVE_HOTFIX_ACTIVE:"+rva.ToString("x")); }
            Hotfix();
            stage="manager-roots";
            ulong global=reader.Ptr(image+0x5783de8),save=reader.Ptr(global+0xdb50),level=reader.Ptr(global+0xa960);
            ulong gate=reader.Ptr(global+0xa430),mode=reader.Ptr(global+0xa440);
            reader.Ptr(gate+0x50);
            Require(reader.U32(mode+0x1cc)==0xb993 && reader.Read(level+0xc9,1)[0]==1,"ARCHIVE_NOT_EDITING");
            uint levelId=reader.U32(level+0x98); Require(levelId==1073741840,"ARCHIVE_TEST_LEVEL_CHANGED");
            ulong catalog=reader.Ptr(save+0x48),dictionary=reader.Ptr(catalog+0x28);
            uint selected=reader.U32(catalog+0x38); Require(selected==levelId,"ARCHIVE_SELECTION_MISMATCH");
            stage="dictionary-snapshot";
            byte[] header=reader.Read(dictionary,0x48);
            ulong bucketArray=BitConverter.ToUInt64(header,0x20),entryArray=BitConverter.ToUInt64(header,0x28);
            Require(bucketArray>=0x10000 && bucketArray<0x0000800000000000 && (bucketArray&7)==0 &&
                entryArray>=0x10000 && entryArray<0x0000800000000000 && (entryArray&7)==0,"ARCHIVE_ARRAY_POINTER");
            ulong bucketLength=BitConverter.ToUInt64(reader.Read(bucketArray+0x18,8));
            ulong entryLength=BitConverter.ToUInt64(reader.Read(entryArray+0x18,8));
            Require(bucketLength>0 && bucketLength<=MaxEntries && entryLength>0 && entryLength<=MaxEntries,"ARCHIVE_ARRAY_LIMIT");
            byte[] buckets=reader.Read(bucketArray+0x20,checked((int)bucketLength*4));
            byte[] entries=reader.Read(entryArray+0x20,checked((int)entryLength*24));
            var records=new Dictionary<ulong,uint>();
            var rows=ParseDictionary(header,buckets,entries,p=> { uint id=reader.U32(p+0x2c);records.Add(p,id);return id; });
            Require(rows.Any(x=>x.levelId==levelId),"ARCHIVE_ACTIVE_RECORD_MISSING");
            stage="snapshot-recheck";
            Require(header.SequenceEqual(reader.Read(dictionary,0x48)) &&
                buckets.SequenceEqual(reader.Read(bucketArray+0x20,buckets.Length)) &&
                entries.SequenceEqual(reader.Read(entryArray+0x20,entries.Length)) &&
                records.All(x=>reader.U32(x.Key+0x2c)==x.Value),"ARCHIVE_SNAPSHOT_UNSTABLE");
            Require(reader.Ptr(image+0x5783de8)==global && reader.Ptr(global+0xdb50)==save &&
                reader.Ptr(global+0xa960)==level && reader.Ptr(save+0x48)==catalog &&
                reader.Ptr(catalog+0x28)==dictionary && reader.U32(level+0x98)==levelId &&
                reader.U32(catalog+0x38)==selected && reader.Read(level+0xc9,1)[0]==1 &&
                reader.U32(mode+0x1cc)==0xb993,"ARCHIVE_ROOTS_CHANGED");
            Hotfix();
            Require(game.StartTime.ToUniversalTime().ToFileTimeUtc()==0L && !game.HasExited,"ARCHIVE_PROCESS_CHANGED");
            return new {ok=true,observedUtc=DateTime.UtcNow,source="game-save-manager-memory-read-only",
                levelId,selectedLevelId=selected,levelCount=rows.Length,levels=rows,
                dictionaryVersion=BitConverter.ToUInt32(header,0x3c),bucketCapacity=bucketLength,entryCapacity=entryLength,
                bytesRead=reader.Bytes,readCalls=reader.Calls,structureRechecked=true,
                gameMethodsCalled=0,mutationAttempted=false,usableForWrites=false,reopenVerified=false};
        }
        catch(Exception ex)
        {
            return new {ok=false,observedUtc=DateTime.UtcNow,source="game-save-manager-memory-read-only",
                stage,reason=ex is InvalidOperationException?ex.Message:ex.GetType().Name,
                nativeErrorCode=ex is System.ComponentModel.Win32Exception win32?(int?)win32.NativeErrorCode:null,
                gameMethodsCalled=0,mutationAttempted=false,usableForWrites=false,reopenVerified=false};
        }
    }
}
