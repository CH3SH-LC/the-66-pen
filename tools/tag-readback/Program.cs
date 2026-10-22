using Microsoft.Diagnostics.Runtime;
using System.Collections.Immutable;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text.Json;

internal static class Program
{
    internal const string TagType="nhvlt3i2jU53g9xeFtUu.mha7Cmi2N9yPWiDcXdhA";
    internal const string Name="MW_SYNTHETIC_TAG_PROBE";
    internal const uint FixtureId=123;

    // Registration category path. Static evidence (read-only, no editor attached):
    //   .runtime/verification/tag-readback-diagnostic/tag-category-factory.cs:1079-1082
    //       dttKlHAIjhe() -> xyVYfsr3qg0(10003u, 50013u, Es0hy4xvTTi)   => path = [10003, 50013]
    //   .runtime/verification/resource-sync-payload/tag-handler.cs
    //       new FevvcZiBkS31NrEJZJIG(dttKlHAIjhe(), num4)                => that path feeds this ctor
    //   .runtime/verification/resource-sync-payload/key-registration.cs:215-267
    //       Fevvc(Ixx,uint): list = Ixx.DHKiYfgICJr; oLyiwZX255H=list[0];
    //       AwbiwrjxUDX=list[1]; UFWiwJNegmh=list[2]; RBTiwn649Hy=list[3];
    //       namiwGPRyPS = P_1 (the id). Missing entries default to 0.
    // Hence a real registration key reads as (10003, 50013, 0, 0) with the id in namiwGPRyPS.
    // 23 is a message/model enum (MKsX9paFsZ86yhmuNdMg) and lives on a different layer -- it is
    // NOT interchangeable with the registration path and must never be written into a group field.
    internal static readonly uint[] CategoryPath={10003,50013,0,0};
    // FevvcZiBkS31NrEJZJIG field declaration order (key-registration.cs:19-27): five sequential
    // uint fields => offsets 0/4/8/12/16. Read by name, never by hardcoded offset.
    internal static readonly string[] CategoryFields={"oLyiwZX255H","AwbiwrjxUDX","UFWiwJNegmh","RBTiwn649Hy"};
    internal const string IdField="namiwGPRyPS";

    // Active-registry singleton. Static evidence (registry-annotated.cs:1592-1596, singleton.cs:6-58):
    //   Lpts7HiY2aTvYryR0pre.F4yixx2sq3y()
    //     => vSwq2Ui3deULA6AUjQxt<Lpts7HiY2aTvYryR0pre>.pZgi3PiTIE8()
    //     => private static readonly Lazy<T> rZmi38av5uw .Value
    internal const string RegistryType="ACE1cmiYtEdXg5frDhMg.Lpts7HiY2aTvYryR0pre";
    internal const string SingletonTypeOuter="yT2GjCi3sEnq3X39OnMH.vSwq2Ui3deULA6AUjQxt";
    internal static string RealSingletonTypeName=>SingletonTypeOuter+"<"+RegistryType+">";

    // VisitedLimit 原为 2_000_000，与 TimeLimit(20s) 严重不成比例：
    // 2026-09-15 实机实测，遍历 2_000_001 个对象仅耗 1011 ms，即约 2M 对象/秒，
    // 于是数量上限比时间上限早约 20 倍触发，使正常规模的编辑器堆必然判 budget-exceeded。
    // 提到 20_000_000 后，按实测速度约 10 s，仍稳落在 TimeLimit 之内 —— 两个界都保留意义，
    // 且真正约束的是时间界（更符合「有界引用遍历，不得无限扩大堆扫描」的本意）。
    internal const int VisitedLimit=20000000,TargetObjectLimit=256,FindingsEmittedLimit=16;
    internal static readonly TimeSpan TimeLimit=TimeSpan.FromSeconds(20);

    static void Emit(object o)=>Console.WriteLine(JsonSerializer.Serialize(o,new JsonSerializerOptions{WriteIndented=true}));
    public static int Main(string[] args)
    {
        try {
            if(args.Length==0){Emit(new{status="disabled-by-default",commands=new[]{"self-test","registry-self-test","inspect <active-host-run-uuid> <editor-pid> <expected-uint-id>","registry-inspect <active-host-run-uuid> <editor-pid> <expected-uint-id>"}});return 0;}
            if(args.Length==2&&args[0]=="fixture"){Fixture(args[1]);return 0;}
            if(args.Length==2&&args[0]=="registry-fixture"){RegistryFixture.Run(args[1]);return 0;}
            if(args.Length==1&&args[0]=="self-test")return SelfTest();
            if(args.Length==1&&args[0]=="registry-self-test"){var s=RegistrySuite();Emit(new{status=s.Ok?"tests-passed":"test-failed",suite="registry-membership",cases=s.Cases,passed=s.Passed,editorAttached=false,gameAttached=false,results=s.Results});return s.Ok?0:2;}
            if(args.Length==4&&(args[0]=="inspect"||args[0]=="registry-inspect"))
            {
                if(!Guid.TryParseExact(args[1],"N",out _)||!int.TryParse(args[2],out int pid)||pid<=0||!uint.TryParse(args[3],out uint id)||id<0xe0000000)throw new InvalidOperationException("INVALID_FIXED_SCOPE_ARGUMENTS");
                Guard.Validate(args[1],pid);
                if(args[0]=="inspect")
                {
                    var result=Trim(Inspect(pid,id,false));Emit(result);return result.Status=="confirmed"?0:2;
                }
                var q=RealQuery(id,false);
                // One PSS snapshot, two independent conclusions. ModelObjectMatch comes from the
                // readback engine's own bounded heap scan; RegistryMembershipVerified additionally
                // requires the full category path + id lookup to resolve to the very same object
                // reference, with a complete heap walk.
                var walk=WalkProcess(pid,q,out int clrVersions);
                Emit(new{
                    status=walk.Status,
                    modelObjectMatch=walk.ModelObjectMatch,
                    registryMembershipVerified=walk.RegistryMembershipVerified,
                    gameVerified=false,
                    editorAttached=true,gameAttached=false,clrVersionsScanned=clrVersions,
                    snapshotKind="pss-readonly",
                    registry=walk
                });
                return walk.RegistryMembershipVerified?0:2;
            }
            throw new InvalidOperationException("INVALID_FIXED_SCOPE_ARGUMENTS");
        } catch(Exception ex){Emit(new{status="unreadable-or-refused",errorType=ex.GetType().Name,reason=ex is ScopeError?ex.Message:"DIAGNOSTIC_FAILED",registryMembershipVerified=false,gameVerified=false});return 2;}
    }
    internal static RegistryQuery RealQuery(uint id,bool fixture)=>new(TagType,RealSingletonTypeName,CategoryPath,CategoryFields,IdField,Name,id,fixture);
    internal static RegistryResult WalkProcess(int pid,RegistryQuery q,out int clrVersions)
    {
        if(!OperatingSystem.IsWindows())throw new ScopeError("WINDOWS_REQUIRED");
        using var target=DataTarget.CreateSnapshotAndAttach(pid);
        target.FileLocator=new NoFiles();
        if(target.ClrVersions.Length==0)throw new ScopeError("CLR_UNAVAILABLE");
        RegistryResult? first=null;int n=0;
        foreach(var info in target.ClrVersions)
        {
            string dac=Path.Combine(Path.GetDirectoryName(info.ModuleInfo.FileName)!,"mscordaccore.dll");
            if(!File.Exists(dac))throw new ScopeError("LOCAL_DAC_MISSING");
            using var runtime=info.CreateRuntime(dac);
            if(!runtime.Heap.CanWalkHeap)throw new ScopeError("HEAP_NOT_WALKABLE");
            n++;
            var r=RegistryReadback.Walk(runtime,q);
            first??=r;
            if(r.Status=="confirmed-registered"){first=r;break;}
        }
        clrVersions=n;
        return first??throw new ScopeError("CLR_UNAVAILABLE");
    }
    internal sealed record Finding(int Ordinal,bool NameMatches,bool IdMatches,bool CategoryMatches,bool SameObjectMatches,uint[] CategoryValuesRead,object[] Fields);
    internal sealed record Result(string Status,int TargetObjects,int UnreadableObjects,int MatchedObjects,bool ScanComplete,string ScanStopReason,long ObjectsVisited,long ElapsedMs,uint[] CategoryPathExpected,bool FindingsTruncated,bool SyntheticFixture,bool ModelObjectMatch,bool RegistryMembershipVerified,bool GameVerified,List<Finding> Findings);
    static Result Trim(Result r)=>r.Findings.Count<=FindingsEmittedLimit?r:r with{FindingsTruncated=true,Findings=r.Findings.Take(FindingsEmittedLimit).ToList()};
    static Result Inspect(int pid,uint expected,bool fixture)
    {
        if(!OperatingSystem.IsWindows())throw new ScopeError("WINDOWS_REQUIRED");
        using var target=DataTarget.CreateSnapshotAndAttach(pid);
        target.FileLocator=new NoFiles();
        int count=0,unreadable=0,matched=0;long visited=0;bool complete=true;string stop="completed";
        var findings=new List<Finding>();var watch=Stopwatch.StartNew();
        if(target.ClrVersions.Length==0)throw new ScopeError("CLR_UNAVAILABLE");
        foreach(var info in target.ClrVersions) {
            string dac=Path.Combine(Path.GetDirectoryName(info.ModuleInfo.FileName)!,"mscordaccore.dll");
            if(!File.Exists(dac))throw new ScopeError("LOCAL_DAC_MISSING");
            using var runtime=info.CreateRuntime(dac);
            if(!runtime.Heap.CanWalkHeap)throw new ScopeError("HEAP_NOT_WALKABLE");
            foreach(var obj in runtime.Heap.EnumerateObjects()) {
                if(++visited>VisitedLimit){complete=false;stop="visited-object-limit";break;}
                if(watch.Elapsed>TimeLimit){complete=false;stop="elapsed-time-limit";break;}
                if(obj.Type?.Name!=TagType)continue;
                if(++count>TargetObjectLimit){complete=false;stop="target-object-limit";break;}
                try {
                    // Same field-read function the registry readback engine uses: a single source of
                    // truth for the name / identity / category field chain, no getter is invoked.
                    var r=TagFields.Read(obj,CategoryFields,CategoryPath,IdField,Name,expected);
                    if(r.SameObjectMatches)matched++;
                    findings.Add(new(count,r.NameMatches,r.IdMatches,r.CategoryMatches,r.SameObjectMatches,r.CategoryValuesRead,r.Fields));
                } catch{unreadable++;}
            }
            if(!complete)break;
        }
        watch.Stop();
        // Incomplete scan is never reported as "not-found" or as a full success; the stop reason is
        // reported alongside so a budget stop cannot be mistaken for a completed walk.
        string status=!complete?"unreadable":matched>0?"confirmed":unreadable>0?"unreadable":count==0?"not-found":"mismatch";
        return new(status,count,unreadable,matched,complete,stop,visited,watch.ElapsedMilliseconds,CategoryPath,false,fixture,complete&&matched>0,false,false,findings);
    }
    internal sealed class NoFiles:IFileLocator {
        public string? FindPEImage(string f,int t,int s,bool p)=>null;
        public string? FindPEImage(string f,SymbolProperties p,ImmutableArray<byte> b,OSPlatform o,bool c)=>null;
        public string? FindElfImage(string f,SymbolProperties p,ImmutableArray<byte> b,bool c)=>null;
        public string? FindMachOImage(string f,SymbolProperties p,ImmutableArray<byte> b,bool c)=>null;
    }
    static readonly List<object> Keep=new();
    static void Fixture(string mode) {
        switch(mode) {
            // Positive: real registration quad (10003,50013,0,0) + fixed name + expected id.
            case "match":Keep.Add(new nhvlt3i2jU53g9xeFtUu.mha7Cmi2N9yPWiDcXdhA(Name,FixtureId));break;
            // Negative 1: stale hypothesis quad (23,0,0,0) -- message/model enum in a category field.
            case "stale-category":Keep.Add(new nhvlt3i2jU53g9xeFtUu.mha7Cmi2N9yPWiDcXdhA(Name,FixtureId,23u,0u,0u,0u));break;
            // Negative 2: same name, different id.
            case "wrong-id":Keep.Add(new nhvlt3i2jU53g9xeFtUu.mha7Cmi2N9yPWiDcXdhA(Name,FixtureId+1));break;
            // Negative 3: name and id live on two different objects; neither has both.
            case "split":Keep.Add(new nhvlt3i2jU53g9xeFtUu.mha7Cmi2N9yPWiDcXdhA(Name,FixtureId+1));Keep.Add(new nhvlt3i2jU53g9xeFtUu.mha7Cmi2N9yPWiDcXdhA("unrelated-do-not-output",FixtureId));break;
            // Negative 4: name wrapper unreadable/null.
            case "unreadable":Keep.Add(new nhvlt3i2jU53g9xeFtUu.mha7Cmi2N9yPWiDcXdhA(null,FixtureId));break;
            // Negative 5: more target objects than the per-run budget.
            case "limit":for(int i=0;i<TargetObjectLimit+1;i++)Keep.Add(new nhvlt3i2jU53g9xeFtUu.mha7Cmi2N9yPWiDcXdhA(Name,FixtureId));break;
            // No target type at all.
            case "empty":break;
            default:throw new ScopeError("UNKNOWN_FIXTURE_MODE");
        }
        Console.WriteLine("fixture-ready");Console.In.ReadLine();GC.KeepAlive(Keep);
    }
    // Matched = MatchedObjects>0 (per-object hits found); ModelMatch = ModelObjectMatch (the tool's
    // own "complete scan + matched" verdict). They differ exactly in the budget-stop case: objects
    // were found but the walk did not complete, so no success may be reported.
    internal sealed record FixtureCase(string Fixture,string Status,bool Matched,bool CategoryOk,bool Unreadable,bool ScanComplete,string StopReason,bool ModelMatch);
    internal static void Require(bool ok,string what){if(!ok)throw new ScopeError("SELF_TEST_ASSERTION_FAILED:"+what);}
    internal static bool AssertThrows(Action a){try{a();return false;}catch(ScopeError){return true;}}
    internal sealed record RegistrySuiteOutcome(bool Ok,int Cases,int Passed,List<object> Results);
    // Runs the registry-membership fixtures. Each case derives its own child process which builds the
    // scenario itself; the expected verdicts are hardcoded literals in RegistryFixture.Cases and are
    // never derived from the walker.
    internal static RegistrySuiteOutcome RegistrySuite()
    {
        var results=new List<object>();int passed=0;bool ok=true;
        // Invariant checked on EVERY result: RegistryMembershipVerified may be true only for
        // confirmed-registered. This is the assertion that makes a false positive impossible to
        // report silently.
        static bool OnlyConfirmedTrue(IEnumerable<RegistryResult> rs)=>rs.All(r=>r.RegistryMembershipVerified==(r.Status=="confirmed-registered"));
        var all=new List<RegistryResult>();
        foreach(var item in RegistryFixture.Cases)
        {
            RegistryResult result;string? failed=null;
            try
            {
                var psi=new ProcessStartInfo(Environment.ProcessPath!){UseShellExecute=false,CreateNoWindow=true,RedirectStandardInput=true,RedirectStandardOutput=true};
                psi.ArgumentList.Add("registry-fixture");psi.ArgumentList.Add(item.Name);
                using var child=Process.Start(psi)!;
                if(child.StandardOutput.ReadLine()!="registry-fixture-ready")throw new ScopeError("FIXTURE_NOT_READY");
                var q=RegistryFixture.QueryFor(item);
                result=WalkProcess(child.Id,q,out int _);
                child.StandardInput.WriteLine();child.StandardInput.Close();
                if(!child.WaitForExit(5000)){child.Kill();child.WaitForExit();}
            }
            catch(Exception ex){Emit(new{status="test-failed",fixture=item.Name,errorType=ex.GetType().Name,reason=ex is ScopeError?ex.Message:"DIAGNOSTIC_FAILED"});return new(false,RegistryFixture.Cases.Length,passed,results);}
            bool caseOk=true;void Check(bool pass,string what){if(caseOk&&!pass){caseOk=false;failed=what;}}
            Check(result.Status==item.ExpectStatus,"status");
            Check(result.StatusDetail.StartsWith(item.ExpectDetailPrefix,StringComparison.Ordinal),"statusDetail");
            Check(result.RegistryMembershipVerified==item.ExpectMembership,"registryMembershipVerified");
            Check(result.ModelObjectMatch==item.ExpectModelObjectMatch,"modelObjectMatch");
            Check(result.ScanStopReason==item.ExpectStopReason,"scanStopReason");
            Check(result.SyntheticFixture,"syntheticFixture");
            Check(!result.GameVerified&&!result.EditorAttached,"neverGameOrEditorVerified");
            Check(result.CategoryPathExpected.SequenceEqual(CategoryPath),"categoryPathExpected");
            // Walk path = quad truncated at the first zero component (key-registration.cs:554-615).
            Check(result.WalkPathUsed.SequenceEqual(new uint[]{10003,50013}),"walkPathUsed");
            Check(result.PathTrace.Length==result.PathResolvedDepth+1,"pathTrace");
            Check(result.HeapScanComplete==item.ExpectHeapScanComplete,"heapScanComplete");
            // Measured limitation, asserted rather than assumed: ClrMD 3.1 reaches only the generic
            // type DEFINITION's MethodTable, whose static storage is empty. If a future ClrMD can
            // read the constructed generic's static field, StaticFieldReadable becomes true and this
            // assertion fails on purpose, flagging that the evidence must be re-derived.
            Check(result.Layout.SingletonFound,"singletonTypeFound");
            Check(result.Layout.SingletonTypeMatchMode=="open-generic-typedef-mt","singletonTypeMatchMode");
            Check(result.Layout.StaticFieldFound,"staticFieldDeclared");
            Check(result.Layout.StaticFieldReadable==false,"staticFieldNotReadableByClrMd31");
            Check(result.Layout.StaticFieldAgreesWithStorage==null,"staticFieldNotUsableAsSource");
            Check(result.Layout.StorageRoute==RegistryReadback.StorageRoute,"storageRoute");
            Check(result.Layout.StorageInstanceCount==1,"storageInstanceCount");
            if(item.ExpectCategoryFieldsApplied)
            {
                // The SortedDictionary layout names actually resolved, recorded so a silent fallback
                // to a different field name cannot pass unnoticed.
                Check(result.Layout.DictSetFieldName=="_set","dict._set");
                Check(result.Layout.DictRootFieldName=="root","dict.root");
                Check(result.Layout.DictItemFieldName=="<Item>k__BackingField","dict.item");
                Check(result.Layout.DictLeftFieldName=="<Left>k__BackingField","dict.left");
                Check(result.Layout.DictRightFieldName=="<Right>k__BackingField","dict.right");
                Check(result.Layout.DictPairKeyFieldName=="key","dict.pair.key");
                Check(result.Layout.DictPairValueFieldName=="value","dict.pair.value");
                Check(result.Layout.DictCountFieldName=="count","dict.count");
                Check(result.Layout.StorageLayoutKind=="netcore","lazy.layout");
                Check(result.Layout.ValueFieldName=="_value","lazy.valueField");
                Check(result.Layout.RootFieldName=="bwbixDw3yob","registry.rootField");
                Check(result.Layout.SubMapFieldName=="pIxYiE5REC8","node.subMap");
                // Declared types as they actually read in the fixture (registry-annotated.cs:393,397).
                Check(result.Layout.SubMapDeclaredType.Contains("SortedDictionary"),"subMapIsSortedDictionary");
                Check(result.Layout.SubMapDeclaredType.Contains("cwS4IdY3T3bVCku4mc2X"),"subMapValueType");
                if(item.ExpectModelMapReached)
                {
                    Check(result.Layout.ModelMapFieldName=="JkmYibSuDZr","node.modelMap");
                    Check(result.Layout.ModelMapDeclaredType.Contains("SortedDictionary"),"modelMapIsSortedDictionary");
                    Check(result.Layout.ModelMapDeclaredType.Contains("HjteTyiYhKgSp79CEtgX"),"modelMapValueType");
                }
            }
            if(item.ExpectRegistryObjectTypeName!=null)Check(result.RegistryObjectTypeName==item.ExpectRegistryObjectTypeName,"registryObjectTypeName");
            if(item.ExpectObjectNotModelType)Check(!result.RegistryObjectIsModelType,"registryObjectIsModelType");
            if(item.ExpectReferenceEquals)Check(result.RegistryReferenceEqualsHeapCandidate,"referenceEqualsHeapCandidate");
            else Check(!result.RegistryReferenceEqualsHeapCandidate,"referenceNotEquals");
            // Ground truth for "the object was in the heap": the scenario, not the tool, decides.
            Check(result.HeapCandidatesSameObject>0==item.ExpectHeapCandidate,"heapCandidatesSameObject");
            if(item.ExpectMembership)Check(result.RegistryObjectNameMatches&&result.RegistryObjectIdMatches&&result.RegistryObjectCategoryMatches,"registryObjectIdentity");
            // The whole point of the task: a same-name same-id heap object must NOT be upgraded.
            if(!item.ExpectMembership)Check(!result.RegistryMembershipVerified,"noFalsePositive");
            all.Add(result);
            results.Add(new{fixture=item.Name,expectStatus=item.ExpectStatus,actualStatus=result.Status,statusDetail=result.StatusDetail,expectMembership=item.ExpectMembership,actualMembership=result.RegistryMembershipVerified,expectModelObjectMatch=item.ExpectModelObjectMatch,actualModelObjectMatch=result.ModelObjectMatch,heapCandidatesSameObject=result.HeapCandidatesSameObject,passed=caseOk,failedAssertion=failed,constructedBy=item.ConstructedBy,layout=new{singletonTypeMatchMode=result.Layout.SingletonTypeMatchMode,staticFieldDeclaredType=result.Layout.StaticFieldDeclaredType,staticFieldReportsInitialized=result.Layout.StaticFieldReportsInitialized,staticFieldReadable=result.Layout.StaticFieldReadable,staticFieldAgreesWithStorage=result.Layout.StaticFieldAgreesWithStorage,storageRoute=result.Layout.StorageRoute,storageInstanceCount=result.Layout.StorageInstanceCount,storageObjectTypeName=result.Layout.StorageObjectTypeName,storageProvenanceTarget=result.Layout.StorageProvenanceTarget,storageLayoutKind=result.Layout.StorageLayoutKind,storageInitReason=result.Layout.StorageInitReason,rootField=result.Layout.RootFieldName,subMap=result.Layout.SubMapFieldName,subMapDeclaredType=result.Layout.SubMapDeclaredType,modelMap=result.Layout.ModelMapFieldName,modelMapDeclaredType=result.Layout.ModelMapDeclaredType,dictSet=result.Layout.DictSetFieldName,dictRoot=result.Layout.DictRootFieldName,dictCount=result.Layout.DictCountFieldName,dictItem=result.Layout.DictItemFieldName,dictPairKey=result.Layout.DictPairKeyFieldName,dictPairValue=result.Layout.DictPairValueFieldName},registry=result});
            if(caseOk)passed++;else ok=false;
        }
        // 1. The invariant must hold on every real result: membership may be verified ONLY for
        //    confirmed-registered. This is what makes a false positive impossible to report silently.
        Require(OnlyConfirmedTrue(all),"onlyConfirmedRegisteredMayVerify");
        // 2. Sensitivity, three independent ways. All three MUST throw; if any silently passes the
        //    assertion helper is a no-op and every check above is worthless. None of them depend on
        //    the walker's own verdict, so a green suite can never make them vacuous.
        var contradictory=all[0] with {Status="object-not-found",RegistryMembershipVerified=true};
        bool invariantThrew=AssertThrows(()=>Require(OnlyConfirmedTrue(new[]{contradictory}),"onlyConfirmedRegisteredMayVerify"));
        bool invertedThrew=AssertThrows(()=>Require(all.All(r=>r.Status=="definitely-not-a-status"),"deliberatelyFalsePredicate"));
        bool impossibleThrew=AssertThrows(()=>Require(all[0].Status=="confirmed-registered"&&all[0].Status=="object-not-found","deliberatelyImpossible"));
        bool positiveCaseIsActuallyPositive=RegistryFixture.Cases[0].ExpectStatus=="confirmed-registered"&&RegistryFixture.Cases[0].ExpectMembership;
        bool wrongExpectationThrew=AssertThrows(()=>Require(!(RegistryFixture.Cases[0].ExpectMembership),"deliberatelyWrongExpectationOnPositiveCase"));
        if(!invariantThrew||!invertedThrew||!impossibleThrew||!positiveCaseIsActuallyPositive||!wrongExpectationThrew)
        {Emit(new{status="assertion-sensitivity-failed",res=new{invariantThrew,invertedThrew,impossibleThrew,positiveCaseIsActuallyPositive,wrongExpectationThrew}});return new(false,RegistryFixture.Cases.Length,passed,results);}
        results.Add(new{assertionSensitivity=new{invariantThrewOnContradictoryResult=invariantThrew,falsePredicateThrew=invertedThrew,impossibleAssertionThrew=impossibleThrew,positiveCaseDeclaredPositive=positiveCaseIsActuallyPositive,wrongExpectationThrew}});
        return new(ok,RegistryFixture.Cases.Length,passed,results);
    }
    static int SelfTest() {
        var results=new List<object>();
        Guard.SelfTest();
        var cases=new[]{
            new FixtureCase("match",         "confirmed", true,  true,  false, true,  "completed",           true),
            new FixtureCase("stale-category","mismatch",  false, false, false, true,  "completed",           false),
            new FixtureCase("wrong-id",      "mismatch",  false, true,  false, true,  "completed",           false),
            new FixtureCase("split",         "mismatch",  false, true,  false, true,  "completed",           false),
            new FixtureCase("empty",         "not-found", false, true,  false, true,  "completed",           false),
            new FixtureCase("unreadable",    "unreadable",false, true,  true,  true,  "completed",           false),
            new FixtureCase("limit",         "unreadable",true,  true,  false, false, "target-object-limit", false),
        };
        Result? matchResult=null, staleResult=null;
        foreach(var item in cases) {
            var psi=new ProcessStartInfo(Environment.ProcessPath!){UseShellExecute=false,CreateNoWindow=true,RedirectStandardInput=true,RedirectStandardOutput=true};
            psi.ArgumentList.Add("fixture");psi.ArgumentList.Add(item.Fixture);
            using var child=Process.Start(psi)!;
            Result result;
            try {
                if(child.StandardOutput.ReadLine()!="fixture-ready")throw new ScopeError("FIXTURE_NOT_READY");
                result=Inspect(child.Id,FixtureId,true);
            } finally {child.StandardInput.WriteLine();child.StandardInput.Close();if(!child.WaitForExit(5000)){child.Kill();child.WaitForExit();}}
            bool ok=true;string? failed=null;
            void Check(bool pass,string what){if(ok&&!pass){ok=false;failed=what;}}
            Check(result.Status==item.Status,"status");
            Check((result.MatchedObjects>0)==item.Matched,"matchedObjects");
            Check(result.ScanComplete==item.ScanComplete,"scanComplete");
            Check(result.ScanStopReason==item.StopReason,"scanStopReason");
            Check((result.UnreadableObjects>0)==item.Unreadable,"unreadableObjects");
            Check(result.ObjectsVisited>0,"objectsVisited");
            Check(result.ElapsedMs>=0,"elapsedMs");
            Check(result.SyntheticFixture,"syntheticFixture");
            Check(result.ModelObjectMatch==item.ModelMatch,"modelObjectMatch");
            Check(!result.RegistryMembershipVerified&&!result.GameVerified,"neverVerified");
            Check(result.CategoryPathExpected.SequenceEqual(CategoryPath),"categoryPathExpected");
            Check((result.TargetObjects>0)==(item.Fixture!="empty"),"targetObjects");
            if(item.Fixture=="limit")Check(result.TargetObjects>TargetObjectLimit,"targetObjectOverLimit");
            if(item.StopReason!="completed")Check(!result.ScanComplete,"budgetStopIncomplete");
            // Category verdict must be exactly as expected on every readable finding.
            if(result.Findings.Count>0)Check(result.Findings.All(f=>f.CategoryMatches==item.CategoryOk),"categoryMatchesAllFindings");
            // A stale-quad fixture must still be recognised by name+id, and must be rejected on category alone.
            if(!item.CategoryOk)Check(result.Findings.Any(f=>f.NameMatches&&f.IdMatches&&!f.CategoryMatches&&f.CategoryValuesRead.SequenceEqual(new uint[]{23,0,0,0})),"staleQuadShape");
            // An unreadable finding must never be silently turned into a match.
            if(item.Unreadable)Check(result.MatchedObjects==0&&result.Findings.Count==0,"unreadableNotMatch");
            if(item.Fixture=="match")matchResult=result;
            if(item.Fixture=="stale-category")staleResult=result;
            results.Add(new{fixture=item.Fixture,expectedStatus=item.Status,passed=ok,failedAssertion=failed,findingsRead=result.Findings.Count,findingsEmitted=Math.Min(result.Findings.Count,FindingsEmittedLimit),result=Trim(result)});
            if(!ok){Emit(new{status="test-failed",results});return 2;}
        }
        // Anti-tautology: the assertions above must be able to fail. Invert a predicate that is
        // known-true on the positive fixture and require the inverted assertion to throw; then
        // require a self-contradictory assertion to throw. If either silently passes, the
        // assertion helper is a no-op and the whole suite is worthless.
        Result m=matchResult??throw new ScopeError("SELF_TEST_ASSERTION_FAILED:matchResultMissing");
        Result s=staleResult??throw new ScopeError("SELF_TEST_ASSERTION_FAILED:staleResultMissing");
        Require(m.Findings.Count>0,"matchFindingsPresent");
        Require(s.Findings.Count>0,"staleFindingsPresent");
        Require(m.Findings.All(f=>f.CategoryMatches),"matchCategoryPrecondition");
        Require(s.Findings.All(f=>!f.CategoryMatches),"staleCategoryPrecondition");
        bool invertedThrew=AssertThrows(()=>Require(!m.Findings.All(f=>f.CategoryMatches),"deliberatelyInverted"));
        bool impossibleThrew=AssertThrows(()=>Require(m.Status=="confirmed"&&m.Status=="mismatch","deliberatelyImpossible"));
        bool realPredicateThrew=AssertThrows(()=>Require(s.Findings.All(f=>f.CategoryMatches),"realCategoryPredicateOnStaleFixture"));
        if(!invertedThrew||!impossibleThrew||!realPredicateThrew){Emit(new{status="assertion-sensitivity-failed",res= new{invertedThrew,impossibleThrew,realPredicateThrew}});return 2;}
        var registry=RegistrySuite();
        if(!registry.Ok){Emit(new{status="test-failed",failedSuite="registry-membership",fixtureCases=cases.Length,registrySuite=new{cases=registry.Cases,passed=registry.Passed,results=registry.Results}});return 2;}
        Emit(new{status="tests-passed",fixtureCases=cases.Length,positiveCases=1,negativeCases=6,guardCases=6,categoryPathExpected=CategoryPath,
                 assertionSensitivity=new{invertedCategoryAssertionThrew=invertedThrew,impossibleAssertionThrew=impossibleThrew,realCategoryPredicateRejectsStaleQuad=realPredicateThrew},
                 editorAttached=false,gameAttached=false,registryMembershipVerified=false,gameVerified=false,results,
                 registrySuite=new{cases=registry.Cases,passed=registry.Passed,results=registry.Results}});
        return 0;
    }
}
internal sealed class ScopeError(string message):Exception(message);

// Single source of truth for reading the tag model's name / identity / category fields straight out
// of the object graph. No property getter or method of the target is ever invoked: every value comes
// from a ClrMD field read. Used by both the model scan (Program.Inspect) and the registry readback
// engine (RegistryReadback.Walk) so the two conclusions cannot drift apart.
internal sealed record TagReadResult(bool NameMatches,bool IdMatches,bool CategoryMatches,bool SameObjectMatches,uint[] CategoryValuesRead,object[] Fields);
internal static class TagFields
{
    internal const string NameWrapper="WAAiS5WkxlA";
    internal const string IdWrapper="Qi8iCzKCkTt";
    internal const string ValueField="VpIiRZgdEln";
    internal static object Field(ClrType type,string name) {
        for(ClrType? t=type;t!=null;t=t.BaseType){var f=t.Fields.FirstOrDefault(f=>f.Name==name);if(f!=null)return new{lookupType=t.Name,field=name,offset=f.Offset,kind=f.ElementType.ToString()};}
        throw new ScopeError("FIELD_SCHEMA_MISMATCH");
    }
    internal static ClrInstanceField Find(ClrType type,string name) {
        for(ClrType? t=type;t!=null;t=t.BaseType){var field=t.Fields.FirstOrDefault(f=>f.Name==name);if(field!=null)return field;}
        throw new ScopeError("FIELD_SCHEMA_MISMATCH");
    }
    internal static TagReadResult Read(ClrObject obj,string[] categoryFields,uint[] categoryPath,string idField,string expectedName,uint expectedId)
    {
        var nw=Find(obj.Type!,"WAAiS5WkxlA").ReadObject(obj.Address,false);var iw=Find(obj.Type!,"Qi8iCzKCkTt").ReadObject(obj.Address,false);
        if(!nw.IsValid||nw.IsNull||!iw.IsValid||iw.IsNull)throw new ScopeError("FIELD_SCHEMA_MISMATCH");
        var nameObject=Find(nw.Type!,"VpIiRZgdEln").ReadObject(nw.Address,false);
        if(nameObject.Type?.IsString!=true)throw new ScopeError("FIELD_SCHEMA_MISMATCH");
        string? name=nameObject.AsString(expectedName.Length+1);
        var key=iw.ReadValueTypeField("VpIiRZgdEln");
        uint id=key.ReadField<uint>(idField);
        var quad=new uint[categoryFields.Length];
        for(int i=0;i<categoryFields.Length;i++)quad[i]=key.ReadField<uint>(categoryFields[i]);
        bool cm=true;
        for(int i=0;i<categoryFields.Length&&cm;i++)cm=quad[i]==categoryPath[i];
        bool nm=name==expectedName,im=id==expectedId;
        var fields=new List<object>{Field(obj.Type!,"WAAiS5WkxlA"),Field(nw.Type!,"VpIiRZgdEln"),Field(obj.Type!,"Qi8iCzKCkTt"),Field(iw.Type!,"VpIiRZgdEln")};
        foreach(var cf in categoryFields)fields.Add(Field(key.Type!,cf));
        fields.Add(Field(key.Type!,idField));
        return new(nm,im,cm,nm&&im&&cm,quad,fields.ToArray());
    }
}
