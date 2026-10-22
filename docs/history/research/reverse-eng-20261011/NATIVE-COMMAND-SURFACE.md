> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# Native command surface of the editor command dispatcher (binary mine)

Date: 2026-10-11.  Read-only, disk only. No process touched, no save written.

## 0. TL;DR

The editor's command dispatcher is **not string comparison and not managed method names**.
It is a **FNV-1a 32-bit hash compare chain** compiled into **`YuanShen.exe`** (the game engine
binary the editor drives). A command string is hashed and dispatched; the command *name* never
appears in the binary, only its hash.

* Main dispatcher (`beyondEditObjService` / `beyondInstructionGraphService` command family):
  **`YuanShen.exe` RVA `0xcba3130`–`0xcba43d7`** (file offset `0xC358D30`), **27 commands**.
* Second dispatcher (`beyondExportService` — see `EditorAdapter.cs:937`): RVA `0xf03eb40`–`0xf03f396`
  (file `0xE7F4740`), 9 constants (7 named).

**Answer to the real question:** the full enumerated surface contains **NO command that adds a
component, creates a template/asset, or writes terrain**. The only component commands are
*deletes*.

## 1. The hash function (recovered from the loop at `0xcba337e`–`0xcba3402`)


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


FNV-1a, 32-bit, seed `0x811c9dc5`, prime `0x01000193`, iterated over the string's **16-bit code
units** (unrolled 4x). For ASCII names this is identical to byte-wise FNV-1a, which is why an
ASCII dictionary reproduces the constants exactly.

## 2. The dispatcher

`0xcba3130`–`0xcba43d7` (size 4775). Prologue `push r15..rbx; sub rsp,0x118`; computes the hash of
arg1 (an il2cpp `String*`, chars at `+0x14`, length in arg2) and walks a **compare tree** built
from `cmp ecx, imm32` + `ja/je/jne`. **No indirect jump table** (`grep -E "jmp (qword|rax|..)"` on
the full disassembly = 0 hits), so the compared immediates are the complete key set.

Hash-loop evidence: `0xcba337e mov ecx,0x811c9dc5`, `0xcba33a6 imul ecx,esi,0x1000193`.
Chain start: `0xcba3404 cmp ecx,0x78eb3304 ; ja 0xcba34fb`.

## 3. Full command set of the main dispatcher (27/27 named)

| RVA of `cmp ecx,imm` | file offset | imm | command |
|---|---|---|---|
| 0xcba3428 | 0xC359028 | 0x0b69f28d | **DeleteComponentForEditObj** |
| 0xcba3434 | 0xC359034 | 0x1880a8de | FocusLocalBullet |
| 0xcba341c | 0xC35901c | 0x1a33f6f9 | AddInstructionGraphForPrefab |
| 0xcba3715 | 0xC359315 | 0x1f56cd02 | ModifyFactionForPrefab |
| 0xcba3721 | 0xC359321 | 0x25139089 | ModifyFactionForEditObj |
| 0xcba3410 | 0xC359010 | 0x2c4eda76 | DeleteInstructionGraphForEditObj |
| 0xcba359c | 0xC35919c | 0x3f5d30b2 | FocusCharacter |
| 0xcba35a8 | 0xC3591a8 | 0x460c83db | ModifyPrefabTag |
| 0xcba3590 | 0xC359190 | 0x5a1a25f3 | DeleteInstructionGraphForPrefab |
| 0xcba388e | 0xC35948e | 0x5c27df0e | **DeleteComponentForPrefab** |
| 0xcba3882 | 0xC359482 | 0x68677bd6 | ApplyPrefabInstanceChange |
| 0xcba3b7d | 0xC35977d | 0x755a10f3 | DeleteEditObj |
| 0xcba3404 | 0xC359004 | 0x78eb3304 | FocusEditObj |
| 0xcba352b | 0xC35912b | 0x7ca8b102 | FocusBeyondTileMap |
| 0xcba3513 | 0xC359113 | 0x83668ec8 | DeletePrefab |
| 0xcba3507 | 0xC359107 | 0x89cf06af | JumpCombatSetting |
| 0xcba37e9 | 0xC3593e9 | 0x9f65756b | RequestPrefabInstance |
| 0xcba37dd | 0xC3593dd | 0x9fe1144f | ModifyEditObjName |
| 0xcba3a93 | 0xC359693 | 0x9ffa4fa9 | FocusEsp |
| 0xcba34fb | 0xC3590fb | 0xa8a12ee8 | **AddInstructionGraphForEditObj** |
| 0xcba3653 | 0xC359253 | 0xb202598a | FocusPrefabInstance |
| 0xcba365f | 0xC35925f | 0xb7f550fe | ModifyPrefabName |
| 0xcba3647 | 0xC359247 | 0xbd40da3c | ModifyEditobjTag |
| 0xcba3911 | 0xC359511 | 0xbf0390c9 | FocusDropGather |
| 0xcba3905 | 0xC359505 | 0xc7280e4f | FocusScreenshot |
| 0xcba3bf4 | 0xC3597f4 | 0xd807fbc5 | ModifySuite |
| 0xcba3c00 | 0xC359800 | 0xe703f83d | FocusLight |

Verb census (**corrected 2026-10-11 after independent re-derivation — this line
first said "Focus ×11", which made the parts sum to 29 against 27 keys; the true
count is Focus ×9**): Focus ×9, Modify ×7, Delete ×6, Add ×2 (both
*InstructionGraph*), Request ×1, Apply ×1, Jump ×1 = 27.
The two `Add*` commands bind a node **graph** to an object — they do not add
an entity component and do not create an asset. The 9 export-dispatcher keys
re-derive to: Import ×3, Do ×2, Delete ×1, Refresh ×1, DoImportClientScript,
DoExportClientScript — see `COMMAND-SURFACE-FNV.md`.

## 4. Second dispatcher — `beyondExportService` (RVA 0xf03eb40, file 0xE7F4740)

| RVA | imm | command |
|---|---|---|
| 0xf03ed0c | 0x07724773 | ImportDebugLog |
| 0xf03ed00 | 0x08aee119 | *(unnamed — 4-byte imm present, name not in any recovered dictionary)* |
| 0xf03ee95 | 0x0a2d8704 | ImportAllDebugLog |
| 0xf03ecf4 | 0x26e623fe | *(unnamed — same)* |
| 0xf03ed92 | 0x5986b6f9 | DeleteDebugLog |
| 0xf03ed86 | 0x6e900256 | RefreshExistDebugLogReport |
| 0xf03ef30 | 0xc9824659 | DoImport |
| 0xf03ef3c | 0xd19570b8 | ImportPerformanceReport |
| 0xf03ef48 | 0xd8aae5e2 | DoExport |

## 5. What is NOT in this binary (negative, with surface)

Client-side command names that are **absent** from `YuanShen.exe` (hash immediate count = 0), i.e.
not dispatched by this engine — they live in the editor's own managed layer / other modules:

* `DeletePCGInstance`, `FocusPCGInstance`, `ModifyPCGInstanceName` (service `beyondPCGInstanceService`)
* `PlayMusic`, `PlaySoundEffect` (`beyondAudioService`)
* `RequestStreaming`, `RequestTypeUrl`, `SetFocus`, `OpenResourceExplorerMainWithTag`,
  `EndLoadAllDebugLog`, `ButtonClickCommand`, and the WPF menu/UI command set.

Search surface: all 3023 distinct string literals recovered in
`.runtime/editor-catalog/resolved/*.cs` (12375 files) + `.runtime/editor-catalog/string-table.json`,
hashed and searched as 4-byte immediates across the whole 445 MB image (`data.find(struct.pack('<I',
fnv1a(name)))`, 0 hits ⇒ absent).

## 5b. Direct probe for the verbs the question asks about (fully negative)

A dictionary of 4764 names built from {Add, Create, Insert, Attach, New, Make, Instantiate,
Apply, Register, Build, Generate, Mount, Equip, Set, Push, Append} × {Component, Template, Asset,
Prefab, Entity, Instance, Node, Terrain, Tile, Cell, Map, Region, Material, …} × {ForEditObj,
ForPrefab, InEditObj, …} plus 20 terrain-write names was hashed and searched.

* Naive "4-byte value present anywhere in the 445 MB file" ⇒ **91 hits** — but this is
  **worthless**: 111M windows × 4764 targets / 2³² ⇒ ~120 expected random collisions.
* Rigorous test (each hit must appear as a real `81 F8..FF <imm32>` = `cmp reg,imm32` instruction)
  ⇒ **0 hits** (`verify_hits.py`: "0x81 sites: 1024432 … candidates appearing as a real cmp
  reg,imm32 site: 0").

So none of `AddComponent*`, `CreateTemplate*`, `InsertComponentForEditObj`, `NewTemplateForEditObj`,
`RegisterTemplateToEditObj`, `AddTerrain*`, `SetTerrain*`, `PaintTerrain`, `SetCell/Tile`, … is a
dispatch constant anywhere in the binary. **Naive imm-scanning in this image over-claims by ~120×
— always require the cmp-site test.**

## 6. Why "no add-component / no create-template / no terrain-write" is proof-grade here

*Surface (1):* the dispatcher function is fully disassembled (1029 insns, `complete=True` against
`.pdata`); it contains **no indirect jump**, so its compared immediates are its complete key set
— 27 keys, all named. *Positive control (2):* the enumeration method reproduces both required
truths — `DeleteComponentForEditObj` @ `0xcba3428` and `AddInstructionGraphForEditObj` @ `0xcba34fb`
— plus `DoImport`/`DoExport` @ `0xf03ef30`/`0xf03ef48`. *Three approaches (3):* (a) hash-constant
scan of the whole image; (b) FNV-hash-loop signature grouping per `.pdata` function; (c) corpus
string-literal dictionary attack (recovered the 2 internal tree-node keys
`DeleteInstructionGraphForEditObj`/`ForPrefab`).

## 7. Method / reproduction


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

