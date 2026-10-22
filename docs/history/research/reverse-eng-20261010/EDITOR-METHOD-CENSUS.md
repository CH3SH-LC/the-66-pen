> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# EDITOR-METHOD-CENSUS — task #2: the full method census of the editor assembly

Wave: `reverse-eng-20261010`. Owner files: `.runtime/scratch/editor-method-census.json`
(this census), `docs/research/reverse-eng-20261010/EDITOR-METHOD-CENSUS.md` (this document).
Date: 2026-10-10 (UTC). Author: task #2 agent. Read-only: nothing was invoked, written, saved,
restarted or escalated.

---

## 0. HEADLINE

**The census is done. `BeyondEditor` has 15,653 types and 41,725 distinct declared method
names, and the whole thing is now a local grep in `.runtime/scratch/editor-method-census.json`
(5.0 MB).** Three things a future hunt needs to know before it greps:

1. **The editor's METHOD names are mostly OBFUSCATED, not plain text.** 99.6% of the 41,725
   method names are identifier-shaped random alnum (e.g. `mQVBNEwR69P`, `Trnk2yNtPJgWJHkcTaWX`).
   The wave premise ("method names are plain text") is **only ~0.4% true** — the plain residue is
   the WPF-generated surface (`InitializeComponent`, `get_*`/`set_*`, `*Command` accessors), a
   handful of domain methods (`ModifyEditObjName`, `ModifyPrefabName`, `ModifyPCGInstanceName`,
   `DeletePCGInstance`), and the `BeyondEditor.ViewModelCore.*Converter` types. **`AddInstructionGraphForEditObj`
   and `DeleteComponentForEditObj` do not exist anywhere in the assembly** — a raw byte grep of the
   DLL returns 0 hits for both.
2. **A substring method filter over this assembly is ~90% coincidence.** Filtering by `New`
   returns 20 names and **none is a real "new"** — every hit is random alnum that happens to
   contain the letters `new` (`o78mNewS0ST`, `mQVBNEwR69P`). Filtering by `Bag` returns 15 names,
   **all coincidence** (`Hk4BagVS0iv`, `Bagxd4Tupjo`). Any future "did the editor reveal an
   add-X primitive?" answer **must** classify hits as verb-at-word-start, not substring.
3. **There is no component-add primitive in the assembly's *method names*.** The only `Component`
   names in 15,653 types are `InitializeComponent` (WPF codegen) and the `IComponentConnector.Connect`
   interface impl. `Create`+`Add`+`Insert` for components: nothing. **This is the method-name layer
   only — it does NOT close the command-level question.** Command names are *encrypted string
   literals*, never method names, so a method-name census cannot see them: the positive control in
   §8.1 shows `DeleteComponentForEditObj` / `AddInstructionGraphForEditObj` — both demonstrably
   present in the string tables — return **0** method-name hits. The command-level `AddComponent*`
   negative rests on the two build corpora (7.0 / 7.1), not on this census.

---

## 1. The op from task #1 — it IS built, IS loaded, and IS live (verified)

Task #1's assembly-scoped reflection ops exist and run. Verified in the tree and in the queue:

* Adapter (task #1): `tools/editor-bridge/Adapter/ReflectionProbe.cs`
  * `reflection-editor-add` → `ReflectionEditorAdd` (`:133`) — member needle `["Add"]`
  * `reflection-editor-create` → `ReflectionEditorCreate` (`:136`) — member needles `["Create","New"]`
  * `reflection-editor-services` → `ReflectionEditorServices` (`:139`) — type needle `"Service"`
  * `reflection-editor-types` → `ReflectionEditorTypes` (`:142`) — **count only**
  * assembly scope `ReflectionEditorAssemblyName = EditorBindingProfile.EditorSimpleName` (`:61`);
    `EditorBindingProfile.cs:32` = `"BeyondEditor"`.
  * caps: `ReflectionMaxTypes = 64` (`:37`), `ReflectionMaxMethodsPerType = 40` (`:38`).
* Dispatch: `ManagedBridge/BridgeServer.cs:399-402` (case labels), `:423-425` (the four entry points).
* Whitelist + timeout: `call-bridge.ps1:1` (op `ValidateSet`, now **145 ops**), `call-bridge.ps1:80`
  (these four get `60000` ms).
* **Field-free by design** — they read NO request field, so they ride the resident helper whose
  in-memory `Get-ValidatedCallArguments` predates `nameContains` (`elevated-runner.ps1:277-279` is
  the on-disk allowlist that only a fresh helper would honour). This is the exact unblock option B
  named in `LIVE-REFLECTION-COMPONENTS.md §6`.
* **Live, this session.** Revision **R277** was superseded by **R278** (`Miliastra.EditorBridge.Net8R278.dll`,
  built 17:19 local) and loaded into pid 120204 at `2026-10-10T09:20:02Z`, run
  `5b8beecf-a52d-4b93-af14-59d654aee09b` (`accepted=True`). The eight newest queue replies are
  reflection responses; e.g. `.../99d696562db64fd5acd7f393287ec5da.response.json`:

  
（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


  So the live assembly the editor has loaded exposes **15,653** types right now.

---

## 2. Why the op cannot *be* the census — and what I changed

Step 1 said "if the probe caps types, add a paged variant or raise the cap." **It caps, and neither
fix is usable on the wire, so I did not change the probe.** The reasons are mechanical:

* `reflection-editor-types` is deliberately **count-only** (`ReflectionProbe.cs:142`, `:179-196`) —
  it returns `editorTypeCount` and **zero rows**. The row-returning siblings cap at **64 types**
  (`:37`) with **40 method names** each (`:38`).
* 15,653 types ÷ 64 = **245 pages**; ×40 method cap means each type's full member set is also cut.
* **Paging parameters cannot ride the wire.** The resident helper refuses any request field it did
  not know at launch (`CALL_FIELD_NOT_ALLOWED:<name>`, `elevated-runner.ps1:285`), so `offset`/`limit`
  fields are refused exactly like `nameContains` was. Paging could only be spelled in the **op name**,
  i.e. 245 new `ValidateSet` entries.
* **Raising the cap in one reply** would push a multi-MB JSON down a 60 s named pipe from the WPF
  dispatcher — and it would still edit `ReflectionProbe.cs` under task #1, which was **still
  dispatching** while this task ran (last probe call `2026-10-10T09:21:24Z`).

**What I changed instead: nothing in the bridge.** I read the *same* assembly the live probe reads —
`BeyondEditor.dll` on disk — **offline, via its CLI metadata**, which is uncapped, deterministic and
complete. §3 proves it is the same assembly the live probe enumerated.

> Ownership note: `ReflectionProbe.cs` / `BridgeServer.cs` / `call-bridge.ps1` are task #1's working
> set and were being edited concurrently (mtimes 17:18-17:19). Editing them would have risked both
> task #1's work and the "one injection per revision" budget. The offline reader needs none of that.

---

## 3. The instrument, and the equivalence proof

* **Instrument:** `.runtime/scratch/_census_parse.py` — a pure-Python ECMA-335 reader. It opens the
  DLL **read-only**, walks the PE → COM descriptor → `#~` stream with correct row sizes (schema in
  the file), and reads the `TypeDef` / `MethodDef` / `NestedClass` tables. It never loads, JITs or
  invokes anything, and never writes the DLL. Output is sorted by `fullName` (deterministic).
* **Source:** `D:/games/Genshin Impact Game/BeyondAssets/BeyondAssistEditor/BeyondEditor.dll`
  (18,404,248 B; sha256 `565dda11883f0220bae050438fcf52b2288f26b61ed656e2b4cd6d69b41a678a`;
  mtime 2026-09-09). **Read-only**, never executed (it is the game's signed editor binary).

**Equivalence to the LIVE assembly (the test):**

| check | offline census | live probe | verdict |
|---|---|---|---|
| type count | 15,653 (`<Module>` pseudo-row dropped) | `editorTypeCount: 15653` | **equal** |
| `HeCtlTLkCaoHHC3Jl0uJ.oOyw7OLk1LeavVX8xh4M`2` | contains `Add`, `add_CollectionChanged` (26 methods) | reported `["Add","add_CollectionChanged"]` (40-cap) | **subset match** |
| `G2oK7Vj8pTg704eoB8dd.DrkZ0Hj8QyWekcvHG4Jl` | contains `AddToShow`, `OnAddToTreeNode` | reported both | **subset match** |
| all 40 `reflection-editor-add` rows | 40/40 present | 40/40 | **no missing** |
| all 21 `reflection-editor-create` rows | 21/21 present, every live method present | 21/21 | **no missing** |

Live replies compared: `.../76187588474740488934d9e407037b66.response.json` (add),
`.../66b7272683c2471a81065a18aff63378.response.json` (create),
`.../d714556210f043ccb550d5aa7f65d8fc.response.json` (services → **0** matches),
`.../99d696562db64fd5acd7f393287ec5da.response.json` (count). Reproduce: `.runtime/scratch/_census_check.py`.

The offline census **is** the live assembly's member set.

---

## 4. The census file

`.runtime/scratch/editor-method-census.json` — `schema: editor-method-census/1`, 5,008,377 B.


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


Each row: `{ fullName, name, namespace, isNested, methods:[…], methodCount }`. `fullName` uses the
reflection separator (`Ns.Outer+Inner`, arity suffix `` `n `` kept), so it lines up with the live
probe's `fullName`. Namespaces are **also** obfuscated: 12,435 of 15,653 types sit in the global
namespace, ~3,200 have a namespace, and **only 14** are the recognisable `BeyondEditor.*`
(`BeyondEditor.BaseUtil.*`, `BeyondEditor.CustomControl.*`, `BeyondEditor.ViewModelCore.*`).
499 types declare zero methods; the largest single type (`BeyondEditor.ViewModelCore.FrameworkPropertyExtension`)
declares 260.

Grep it directly (Bash — the Grep tool skips `.runtime/`):


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


---

## 5. Step 3 — every method containing Add / Create / New / Insert / Delete / Set / Modify

Classification rule (stated so it can be challenged): a hit is **GENUINE** when the verb sits at the
**start of the identifier** (after stripping a `System...`/`get_`/`set_`/`add_`/`remove_`/`op_`
prefix); otherwise it is **COINCIDENTAL** — random alnum that happens to contain the letters. This is
the single most important methodological point: **a substring match is not a word match here.**

| verb | total hits | genuine | coincidental | genuine names (the ones that mean something) |
|---|---:|---:|---:|---|
| **Add** | 30 | 8 | 22 | `Add`, `AddToShow`, `add3p5NWoGnvCjTYnDVW`, `ADDPi9Hjthj`, `op_Addition`, `ICollection<…>.Add`, `IDictionary.Add`, `IList.Add` |
| **Create** | 1 | 1 | 0 | `CreateProperty` |
| **New** | 20 | 1 | 19 | `neWLEM2sYwt` (still obfuscated) — **no real Create-New method exists** |
| **Insert** | 2 | 2 | 0 | `Insert`, `IList.Insert` |
| **Delete** | 1 | 1 | 0 | `DeletePCGInstance` |
| **Set** | 81 | 63 | 18 | `Set*Command` WPF accessors (`SetButtonClickCommand`, `SetTreeViewItemSelectedCommand`, …), `SetStateMachine`, `SetOwner`, `SetTextBlockRichText`, `SetTextBoxAutoSelectAll`, `SetExtraGeometry`, `SetPosition`/`SetTreeNode` via `set_*` |
| **Modify** | 4 | 3 | 1 | `ModifyEditObjName`, `ModifyPCGInstanceName`, `ModifyPrefabName` |

Notable negative: outside `Modify*`, **there is no domain `Add*`/`Create*`/`Insert*` for any editor
concept** — the genuine `Add`/`Insert` hits are .NET collection members or one WPF handler
(`AddToShow`). This is a **method-name** fact only — it does **not** confirm the corpus-level zero the
repo recorded for the *command* names `AddComponent`/`CreateComponent`: those are encrypted string
literals that never appear as method names (positive control in §8.1), so a method-name census is
blind to them. The command-level negative rests on the two build corpora (7.0 / 7.1).

Full raw lists (so this is a local grep too): `.runtime/scratch/_census_analyze.out`.

---

## 6. Step 4 — the asked-for nouns

| noun | hits | what they are |
|---|---:|---|
| **component** | 2 | `InitializeComponent` (WPF codegen), `System.Windows.Markup.IComponentConnector.Connect` — **no domain component method** |
| **item** | 30 | WPF `get_Item`/`set_Item`, `GetListBoxItemSelectedCommand`, and the resource-item getters `BeyondEditor.Model.IResourceItem.get_resourceItem{Name,ViewType,ModelType,FactionId,IsInvisible,IsMarked,EntityTypeUint,TextGuid,TextType,TextModifyTime}` |
| **stuff** | 0 | — |
| **bag** | 15 | **ALL coincidence** — `Hk4BagVS0iv`, `Bagxd4Tupjo`, `qSCMdvnRzfJBagO5W0Dq`, … |
| **currency** | 0 | — |
| **shop** | 1 | coincidence — `shOpFiCs1i` |
| **template** | 0 | — |
| **prefab** | 1 | `ModifyPrefabName` (the only real prefab verb; there is **no** Create/Duplicate prefab method) |

The `resourceItem*` getters are genuinely useful: they are the read side of an entity's resource
item and live on a **plain-named** type (`BeyondEditor.Model.IResourceItem`, interface) — a rare
foothold for a future component/item read hunt.

---

## 7. Step 5 — already used by the bridge vs UNKNOWN

Cross-reference: every quoted string literal in `tools/editor-bridge/Adapter/*.cs` (3,368 literals)
intersected with the census's method names → **100 method names are already referenced by the
bridge** (`.runtime/scratch/_census_analyze.py`). Of the *highlighted* names above:

**ALREADY USED by the bridge (evidence is a real reflective lookup, not just a string):**

| name | evidence |
|---|---|
| `ModifyEditObjName` | `Adapter/EditorAdapter.cs:569`, `Adapter/EntityCrudProbe.cs:207` (`.GetMethod("ModifyEditObjName", …)`) |
| `GetPin` | `Adapter/EditorAdapter.cs:659` |
| `DeepCopy` | `Adapter/ClassicTeleportRepair.cs:73`, `Adapter/FinishMinimalDiagnostic.cs:113`, `Adapter/FinishSettlementDiagnostic.cs:105` |
| `Recycle` | `Adapter/ClassicTeleportRepair.cs:126-127`, `Adapter/EditorAdapter.cs:880`, `Adapter/FinishMinimalDiagnostic.cs:75` |
| `PlayMusic` / `PlaySoundEffect` / `Stop` | name-compared in `Adapter/AudioEvidence.cs:85` |
| `Add`, `Remove`, `Equals`, `Value`, `CopyValue`, `Stop` | appear as literals used by the node-graph/typed-const plumbing |

**UNKNOWN (no reference anywhere in `Adapter/*.cs`) — the candidate surface for future primitives:**

`ModifyPrefabName`, `ModifyPCGInstanceName`, `DeletePCGInstance`, `CreateProperty`,
`AddToShow`, `OnAddToTreeNode`, `SetOwner`, `SetTextBlockRichText`, `SetTextBoxAutoSelectAll`,
`SetStateMachine`, `InitializeComponent`, `IComponentConnector.Connect`, and **all** of the
`resourceItem*` getters. In particular `ModifyPrefabName` is the only prefab write verb in the whole
assembly and the bridge does **not** use it — a concrete, unexplored candidate.

> Caveat on "used": a name appearing in `Adapter/*.cs` can come from several symbol namespaces
> (editor-binding symbols, native-action names, node-type names). Where the file row above shows a
> `GetMethod(<name>)` call it is a genuine reflective use; the plain-literal rows are name-level hits
> only. The census cannot prove *which* namespace a literal belongs to — that is what
> `EditorBindingProfile`'s legacy/actual split exists for.

---

## 8. Findings and caveats

1. **The "plain method names" premise is false for ~99.6% of the assembly.** Only the WPF surface
   and a few domain verbs are plain. Any hunt that assumes `Add*=plain` will read framework
   coincidences as editor capabilities. (Raw bytes: `AddInstructionGraphForEditObj` = 0 hits,
   `DeleteComponentForEditObj` = 0 hits, `beyondEditObjService` = 0 hits in the DLL.)
2. **Substring method filters are dominated by coincidence** (§5/§6). Classify by word-start.
3. **No component-add / template / bag / currency / shop primitive in the *method names*.** Confirmed
   across all 15,653 types, not a 64-type page. **Wrong-layer caveat:** this is the method-name layer;
   command names are encrypted string literals invisible to it (positive control §8.1 —
   `DeleteComponentForEditObj` = 0 method-name hits though it demonstrably exists), so this census
   neither confirms nor refutes the command-level `AddComponent*` negative. That rests on the two
   build corpora.
4. **The uncapped census instrument is the on-disk DLL, not the bridge.** The bridge op is the
   right tool for "is this live *right now*"; the offline reader is the right tool for "what does
   the assembly contain" — and §3 shows they agree.
5. **Scope/bounds:** this census is *declared* members (`DeclaredOnly` semantics), names only — no
   signatures, no bodies, no fields/properties beyond their accessor methods. It does not tell you
   which methods are reachable, callable, or safe; it tells you what names exist. Types are keyed by
   `fullName`; obfuscated names are stable for **this** DLL build (sha256 above) and may change on a
   game update.
6. **Not a negative-result-only artifact:** the `resourceItem*` getters, `ModifyPrefabName`,
   `ModifyPCGInstanceName` and `DeletePCGInstance` are concrete, previously-uncatalogued names a
   later task can act on.

---

## 9. Reproduction


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


Files owned / produced by this task: `.runtime/scratch/editor-method-census.json`,
`docs/research/reverse-eng-20261010/EDITOR-METHOD-CENSUS.md`; helpers
`_census_parse.py`, `_census_analyze.py`, `_census_check.py`, `_census_analyze.out` (all under
`.runtime/scratch/`). No file outside this list was modified.
