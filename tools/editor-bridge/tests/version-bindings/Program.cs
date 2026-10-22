// =============================================================================
// ORPHANED MANUAL SELF-CHECK -- NOT WIRED INTO ANY RUNNER, NOT A LIVE GATE.
// =============================================================================
// Nothing in this repository builds or launches this program. scripts/run-tests.ps1
// discovers only Python (test_*.py) and PowerShell (test_*.ps1) suites and never
// compiles or runs C#; no .sln or build script names VersionBindings. It is a
// MANUAL one-shot validator: pass the built bridge assembly (args[0]) and the real
// BeyondEditor.exe (args[1]) and it re-validates every generated profile contract
// against the editor's PE metadata via MetadataLoadContext (metadata only -- the
// target is never executed and never injected). Because no runner invokes it, it can
// never report a failure on its own; it is kept only as a runnable reference and must
// NOT be treated as evidence that a check passed.
//
// The program formerly asserted hardcoded counts (257 symbols / 263 contracts) that
// silently drifted from the generated profile (now 307 / 313). Those literals are gone:
// the expectations are DERIVED from the profile itself (see Main), so the program can no
// longer assert a stale number. Note docs/research/reverse-eng-20261010/MINED-INTERFACES.md
// still quotes the removed literals as evidence of the drift.
using System.IO;
using System.Reflection;
using System.Reflection.Emit;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Collections;
public class ContractFixture { public int Value; public static string Text => throw new Exception("getter must not run"); public void Run(int i) => throw new Exception("never invoke"); public void Run(string s)=>throw new Exception("never invoke"); }
public class SceneModelFixture { }
public class SceneFolderFixture : Dictionary<string,object?> { }
static class Program {
 static int checks;
 static void Check(bool ok,string name){if(!ok)throw new Exception("FAILED:"+name);checks++;}
 static object? Call(Type t,string name,params object?[] args){try{return t.GetMethod(name,BindingFlags.NonPublic|BindingFlags.Static)!.Invoke(null,args);}catch(TargetInvocationException e){throw e.InnerException!;}}
 static void Refuses(Action action,string code){try{action();throw new Exception("DID_NOT_REFUSE:"+code);}catch(InvalidOperationException e){Check(e.Message.StartsWith("EDITOR_BINDING_PROFILE_"+code),e.Message);}}
 static int Main(string[] args){
  var bridge=Assembly.LoadFrom(Path.GetFullPath(args[0]));var resolver=bridge.GetType("Miliastra.EditorBridge.EditorBindingProfile",true)!;var profile=((Array)resolver.GetField("Profiles",BindingFlags.Static|BindingFlags.NonPublic)!.GetValue(null)!).GetValue(0)!;var ptype=profile.GetType();
  var symbols=(IReadOnlyDictionary<string,string>)ptype.GetProperty("Symbols")!.GetValue(profile)!;var contracts=(Array)ptype.GetProperty("Contracts")!.GetValue(profile)!;var ctype=contracts.GetType().GetElementType()!;var ktype=resolver.GetNestedType("BindingKind",BindingFlags.NonPublic)!;
  object Profile(IReadOnlyDictionary<string,string> s,Array c)=>Activator.CreateInstance(ptype,new object[]{"fixture",new string('A',64),Guid.NewGuid(),s,c})!;
  object Contract(string owner,string? member,string kind,string signature,bool stat)=>Activator.CreateInstance(ctype,new object?[]{owner,member,Enum.Parse(ktype,kind),signature,stat})!;
  Array C(params object[] values){var a=Array.CreateInstance(ctype,values.Length);for(int i=0;i<values.Length;i++)a.SetValue(values[i],i);return a;}
  // Counts are DERIVED, never hardcoded. The resolver's sibling LegacySymbols set is the
  // one other representation of the same symbol universe: if the generated map and the
  // generated set disagree, the generator emitted two inconsistent artifacts. The contract
  // list has no second local representation, so it is only checked structurally here and
  // then validated in full -- every entry against the real PE metadata -- below.
  var legacySymbols=(IReadOnlyCollection<string>)resolver.GetField("LegacySymbols",BindingFlags.NonPublic|BindingFlags.Static)!.GetValue(null)!;
  Check(symbols.Count==legacySymbols.Count,"symbol map count matches LegacySymbols set");
  Check(legacySymbols.All(symbols.ContainsKey),"all legacy symbols present in profile map");
  Check(contracts.Length>0,"profile declares generated metadata contracts");
  Refuses(()=>Call(resolver,"ValidateIdentity",0,null,false,null),"EDITOR_NOT_LOADED");
  Refuses(()=>Call(resolver,"ValidateIdentity",2,null,false,null),"MULTIPLE_EDITOR_ASSEMBLIES");
  Refuses(()=>Call(resolver,"ValidateIdentity",1,new AssemblyName("Wrong, Version=1.0.0.0"),false,"fixture"),"IDENTITY_NAME_MISMATCH");
  Refuses(()=>Call(resolver,"ValidateIdentity",1,new AssemblyName("BeyondEditor, Version=2.0.0.0"),false,"fixture"),"IDENTITY_VERSION_MISMATCH");
  Refuses(()=>Call(resolver,"ValidateIdentity",1,new AssemblyName("BeyondEditor, Version=1.0.0.0"),true,"fixture"),"IDENTITY_DYNAMIC");
  var pinnedHash=(string)ptype.GetProperty("Sha256")!.GetValue(profile)!;
  var pinnedMvid=(Guid)ptype.GetProperty("Mvid")!.GetValue(profile)!;
  Refuses(()=>Call(resolver,"SelectProfile",new string('0',64),pinnedMvid),"UNKNOWN_BUILD_HASH");
  Refuses(()=>Call(resolver,"SelectProfile",pinnedHash,Guid.NewGuid()),"UNKNOWN_BUILD_MVID");
  Refuses(()=>Call(resolver,"ResolveInProfile",profile,"UnregisteredNativeBinding"),"UNREGISTERED_SYMBOL");
  var missing=new Dictionary<string,string>(symbols);missing.Remove(symbols.Keys.First());
  Refuses(()=>Call(resolver,"ValidateContracts",Profile(missing,C()),typeof(Program).Assembly),"REQUIRED_BINDING_MISSING");
  var good=Profile(symbols,C(Contract(nameof(ContractFixture),"Value","Field","System.Int32",false),Contract(nameof(ContractFixture),"Run","Method","(System.Int32):System.Void",false),Contract(nameof(ContractFixture),"Text","Property","System.String",true)));
  Call(resolver,"ValidateContracts",good,typeof(Program).Assembly);Check(true,"metadata field method property signatures pass without getters");
  foreach(var item in new[]{("Field","Value","System.String",false,"CONTRACT_SIGNATURE_MISMATCH"),("Field","Missing","System.Int32",false,"CONTRACT_FIELD_MISSING"),("Field","Value","System.Int32",true,"CONTRACT_STATIC_MISMATCH"),("Method","Run","():System.Void",false,"CONTRACT_METHOD_SIGNATURE_MISSING"),("Property","Text","System.String",false,"CONTRACT_PROPERTY_ACCESSOR_MISMATCH")})
   Refuses(()=>Call(resolver,"ValidateContracts",Profile(symbols,C(Contract(nameof(ContractFixture),item.Item2,item.Item1,item.Item3,item.Item4))),typeof(Program).Assembly),item.Item5);
  var names=new List<string>();names.AddRange(Directory.GetFiles(RuntimeEnvironment.GetRuntimeDirectory(),"*.dll"));
  names.AddRange(Directory.GetFiles(Path.GetDirectoryName(typeof(System.Windows.Application).Assembly.Location)!,"*.dll"));
  names.AddRange(Directory.GetFiles(Path.GetDirectoryName(Path.GetFullPath(args[1]))!,"*.dll"));
  using var mlc=new MetadataLoadContext(new PathAssemblyResolver(names.Distinct()),"System.Private.CoreLib");
  var editor=mlc.LoadFromAssemblyPath(Path.GetFullPath(args[1]));
  Check(!AppDomain.CurrentDomain.GetAssemblies().Any(a=>a.GetName().Name=="BeyondEditor"),"target only in MetadataLoadContext, never runtime loaded");
  Call(resolver,"ValidateContracts",profile,editor);Check(true,"all real PE contracts in the profile pass");
  var selected=Call(resolver,"MatchProfile",editor);Check(ReferenceEquals(profile,selected),"disk SHA and metadata MVID select expected profile");
  Refuses(()=>Call(resolver,"RequireEditor"),"EDITOR_NOT_LOADED");
  // Exercise actual coverage logic using fabricated delegate slots. No target binary is run.
  var adapter=bridge.GetType("Miliastra.EditorBridge.EditorAdapter",true)!;
  var slotType=adapter.GetNestedType("Slot",BindingFlags.NonPublic)!;
  var fakeFixture=AssemblyBuilder.DefineDynamicAssembly(new AssemblyName("OfflineChannelFixture"),AssemblyBuilderAccess.Run);
  var module=fakeFixture.DefineDynamicModule("Fixture");var builder=module.DefineType("SelectorFixture",TypeAttributes.Public|TypeAttributes.Class);
  foreach(var name in new[]{"One","Two"}){var method=builder.DefineMethod(name,MethodAttributes.Public|MethodAttributes.Static,typeof(string),Type.EmptyTypes);var il=method.GetILGenerator();il.Emit(OpCodes.Ldstr,name);il.Emit(OpCodes.Ret);builder.DefineField(name+"Slot",typeof(Delegate),FieldAttributes.Public|FieldAttributes.Static);}
  var selector=builder.CreateType()!;
  var slotArray=Array.CreateInstance(slotType,2);int index=0;
  foreach(var name in new[]{"One","Two"}){selector.GetField(name+"Slot")!.SetValue(null,selector.GetMethod(name)!.CreateDelegate(typeof(Func<string>)));slotArray.SetValue(Activator.CreateInstance(slotType,new object[]{"SelectorFixture",name+"Slot","SelectorFixture",name}),index++);}
  var required=new HashSet<string>{"OneSlot","TwoSlot"};
  JsonElement Channels(Array slots,HashSet<string> req)=>JsonSerializer.SerializeToElement(Call(adapter,"VerifyChannelsCore",fakeFixture,slots,req));
  Check(Channels(slotArray,required).GetProperty("ok").GetBoolean(),"all required selectors pass");
  Check(!Channels(Array.CreateInstance(slotType,0),required).GetProperty("ok").GetBoolean(),"zero covered selectors fail");
  Check(!Channels(slotArray,new HashSet<string>{"OneSlot","TwoSlot","Missing"}).GetProperty("ok").GetBoolean(),"absent required coverage fails");
  selector.GetField("TwoSlot")!.SetValue(null,null);
  Check(!Channels(slotArray,required).GetProperty("ok").GetBoolean(),"skipped null selector fails");
  selector.GetField("TwoSlot")!.SetValue(null,selector.GetMethod("One")!.CreateDelegate(typeof(Func<string>)));
  Check(!Channels(slotArray,required).GetProperty("ok").GetBoolean(),"wrong target fails");
  // Actual scene resolver against a field-only fixture. Runtime IDs deliberately vary;
  // no captions, target binary, getters or native enumerators participate.
  Dictionary<string,object?> Obj(params (string,object?)[] fields)=>fields.ToDictionary(x=>x.Item1,x=>x.Item2);
  SceneFolderFixture Folder(uint id,object? model,int container=3)=>new(){
   ["vQPKy8Qu9ev"]=Obj(("containerType",container),("y30KBtqRTpg",Obj(("ol3iwzG1HRm",id),("yKiiwIS6frK",1)))),
   ["DKWKyl77ARt"]=model,["gnkKXFN3UAC"]=Obj(("jN4igqhC7U3",new List<object>()))};
  Func<object,string,object?> read=(o,k)=>((Dictionary<string,object?>)o)[k];
  (Dictionary<string,object?> Registry,List<object> Managers,SceneFolderFixture Root,SceneFolderFixture Scene,IDictionary Owners) Scene(uint id){
   var model=new SceneModelFixture();var scene=Folder(id,model);var tree=Folder(40390,null);
   ((Dictionary<string,object?>)tree["gnkKXFN3UAC"]!)["jN4igqhC7U3"]=new List<object>{scene};
   IDictionary owners=new Hashtable{{id,model}};
   // The real R164 prefix has zero direct owners; scene owns the full four-tag leaf.
   var registry=Obj(("JkmYibSuDZr",owners));
   foreach(uint tag in new uint[]{40004,41101,40003,40000})
    registry=Obj(("JkmYibSuDZr",new Hashtable()),("pIxYiE5REC8",new Hashtable{{tag,registry}}));
   return (registry,new List<object>{Obj(("lleKeqZguxf",Obj(("JiLKB1xsFfb",tree))))},tree,scene,owners);
  }
  JsonElement Resolve(object registry,IReadOnlyList<object> managers,int limit=4096){
   var r=Call(adapter,"ResolveSceneFolderCore",registry,managers,read,typeof(SceneFolderFixture),typeof(SceneModelFixture),limit)!;
   return JsonSerializer.SerializeToElement(r.GetType().GetMethod("Evidence",BindingFlags.Instance|BindingFlags.NonPublic)!.Invoke(r,null));
  }
  void SceneRefuses(string expected,Action<Dictionary<string,object?>,List<object>,SceneFolderFixture,SceneFolderFixture,IDictionary> change,int limit=4096){
   var f=Scene(40392);change(f.Registry,f.Managers,f.Root,f.Scene,f.Owners);var r=Resolve(f.Registry,f.Managers,limit);
   Check(!r.GetProperty("ok").GetBoolean()&&!r.GetProperty("invoked").GetBoolean()&&r.GetProperty("status").GetString()==expected,"scene refuses "+expected);
  }
  foreach(uint runtimeId in new uint[]{40392,99999}){var f=Scene(runtimeId);var r=Resolve(f.Registry,f.Managers);Check(r.GetProperty("ok").GetBoolean()&&r.GetProperty("complete").GetBoolean()&&r.GetProperty("folderId").GetUInt32()==runtimeId,"scene resolves changed runtime ID by exact model identity");}
  Dictionary<string,object?> Prefix(Dictionary<string,object?> r){
   var a=(Dictionary<string,object?>)((IDictionary)r["pIxYiE5REC8"]!)[40000u]!;
   return (Dictionary<string,object?>)((IDictionary)a["pIxYiE5REC8"]!)[40003u]!;
  }
  SceneRefuses("scene-category-tag-missing",(r,m,t,n,o)=>{
   var prefix=Prefix(r);prefix["JkmYibSuDZr"]=o;((IDictionary)prefix["pIxYiE5REC8"]!).Clear();
  });
  {var f=Scene(70001);Prefix(f.Registry)["JkmYibSuDZr"]=new Hashtable{{40392u,new SceneModelFixture()}};
   var r=Resolve(f.Registry,f.Managers);Check(r.GetProperty("ok").GetBoolean()&&r.GetProperty("folderId").GetUInt32()==70001,"scene full path ignores decoy prefix owner");}
  SceneRefuses("scene-category-tag-missing",(r,m,t,n,o)=>((IDictionary)r["pIxYiE5REC8"]!).Clear());
  SceneRefuses("scene-resource-manager-not-unique",(r,m,t,n,o)=>m.Add(m[0]));
  SceneRefuses("scene-category-owner-not-unique",(r,m,t,n,o)=>o.Add(999u,new SceneModelFixture()));
  SceneRefuses("scene-category-owner-invalid",(r,m,t,n,o)=>o[40392u]=new object());
  SceneRefuses("scene-category-owner-key-mismatch",(r,m,t,n,o)=>n["DKWKyl77ARt"]=new SceneModelFixture());
  SceneRefuses("scene-category-owner-key-mismatch",(r,m,t,n,o)=>((Dictionary<string,object?>)((Dictionary<string,object?>)n["vQPKy8Qu9ev"]!)["y30KBtqRTpg"]!)["ol3iwzG1HRm"]=17u);
  SceneRefuses("scene-category-tree-container-mismatch",(r,m,t,n,o)=>((Dictionary<string,object?>)n["vQPKy8Qu9ev"]!)["containerType"]=4);
  SceneRefuses("scene-folder-not-unique",(r,m,t,n,o)=>((List<object>)((Dictionary<string,object?>)t["gnkKXFN3UAC"]!)["jN4igqhC7U3"]!).Add(Folder(40392,o[40392u])));
  SceneRefuses("scene-category-tree-repeated-node",(r,m,t,n,o)=>((List<object>)((Dictionary<string,object?>)n["gnkKXFN3UAC"]!)["jN4igqhC7U3"]!).Add(t));
  SceneRefuses("scene-category-tree-node-limit",(r,m,t,n,o)=>{},1);
  SceneRefuses("scene-folder-not-unique",(r,m,t,n,o)=>((List<object>)((Dictionary<string,object?>)t["gnkKXFN3UAC"]!)["jN4igqhC7U3"]!).Clear());
  SceneRefuses("scene-category-tree-node-type-mismatch",(r,m,t,n,o)=>((List<object>)((Dictionary<string,object?>)t["gnkKXFN3UAC"]!)["jN4igqhC7U3"]!).Add(new object()));
  SceneRefuses("scene-category-items-list-invalid",(r,m,t,n,o)=>((Dictionary<string,object?>)n["gnkKXFN3UAC"]!)["jN4igqhC7U3"]=new ArrayList());
  // The actual reader must take the configuration reference, never the optional
  // prefab association cache; a cache zero and a real template ID may coexist.
  var templateRef=new Dictionary<string,object>{{"pgfitPOV3oW",20001034u}};
  var entityFixture=new Dictionary<string,object>{{"dmhiSVca7Ew",templateRef},{"TuuiS94iUgu",0u}};
  var fieldReads=new List<string>();
  Func<object,string,object> readTemplate=(o,k)=>{fieldReads.Add(k);return ((Dictionary<string,object>)o)[k];};
  object? Template()=>Call(adapter,"ReadSceneTemplateIdCore",entityFixture,readTemplate);
  Check((uint)Template()! == 20001034u,"template reader uses config reference despite zero association cache");
  Check(fieldReads.SequenceEqual(new[]{"dmhiSVca7Ew","pgfitPOV3oW"}),"template reader uses only two exact fields");
  templateRef["pgfitPOV3oW"]=0u;Check((uint)Template()! == 0u,"zero template remains zero, never filled with expected ID");
  templateRef["pgfitPOV3oW"]=uint.MaxValue;Check((uint)Template()! == uint.MaxValue,"template reader preserves uint32 max");
  foreach(object bad in new object[]{20001034,"20001034",true,1.0}) {
   templateRef["pgfitPOV3oW"]=bad;
   try{Template();throw new Exception("DID_NOT_REFUSE:template id type");}
   catch(InvalidOperationException e){Check(e.Message=="SCENE_TEMPLATE_ID_TYPE_MISMATCH","template ID type fails closed");}
  }
  var fake=AssemblyBuilder.DefineDynamicAssembly(new AssemblyName("BeyondEditor"){Version=new Version(1,0,0,0)},AssemblyBuilderAccess.Run);
  Refuses(()=>Call(resolver,"RequireEditor"),"IDENTITY_DYNAMIC");
  Console.WriteLine(JsonSerializer.Serialize(new{ok=true,checks,symbols=symbols.Count,contracts=contracts.Length,scope="Actual compiled resolver; synthetic contracts plus MetadataLoadContext on current disk binary; no target business code or game/editor process contact"}));return 0;
 }
}
