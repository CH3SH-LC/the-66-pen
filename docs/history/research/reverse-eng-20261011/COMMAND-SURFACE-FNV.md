> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# The engine command surface, re-derived and hardened (FNV dispatcher ground truth)

Date: 2026-10-11.  **Read-only, disk only.**  No process started, connected or
restarted; no UAC; no save written; no file under `D:/games` or `LocalLow` written.
Everything below is a static read of `YuanShen.exe`.

Supersedes the enumeration in `NATIVE-COMMAND-SURFACE.md` (wave29A).  That file is
kept as history; two of its numbers were wrong and are corrected here and in place.

Reproduce everything with a single offline tool:
`tools/editor-catalog/fnv_command_surface.py`（历史来源：`../../../tools/editor-catalog/fnv_command_surface.py`）
(+ tests in `tools/editor-catalog/tests/test_fnv_command_surface.py`).

---

## 0. TL;DR

* The engine dispatches editor commands by **FNV-1a-32 over the command name's
  UTF-16 code units**, compared as `cmp ecx, imm32` in a binary-search chain.
* Two dispatchers carry the editor command family, and **both are fully decoded
  to their `.pdata` end with zero indirect jumps** — so their compared immediates
  are their **complete** key set:
  * **main** `beyondEditObjService` / `beyondInstructionGraphService`
    — RVA `0xcba3130`–`0xcba43d7` (4,775 B, 1,029 insns), **27 keys, 37 cmp sites**.
  * **export** `beyondExportService`
    — RVA `0xf03eb40`–`0xf03f396` (2,134 B, 478 insns), **9 keys, 12 cmp sites**.
* **36/36 keys are now named** (wave29A left 4 unnamed; §5).
* The wave29A "91 naive imm hits" line is resolved: **all 91 are chance
  coincidences**, rejected by a single explicit filter (§6).
* **Answer to the real question:** in either dispatcher there is **no** command
  that adds a component, creates a template/asset, or writes terrain (§7).  This
  is a proof-grade negative — surface enumerated, positive control reproduced,
  three independent methods (§8).

---

## 1. The hash, re-derived from the bytes (not quoted)

The hash loop sits at the top of each dispatcher.  For the main dispatcher the
evidence as this checkout actually decodes is:


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

The export dispatcher carries its own copy (`mov ecx,0x811c9dc5` @ `0xf03ec68`,
`imul ecx,edi,0x1000193` @ `0xf03ec96`).  The loop reads a **16-bit code unit** per
iteration (`movzx edi, word ptr [rsi-6]`) and XORs it into `ecx`.  For ASCII
command names this is bit-for-bit identical to byte-wise FNV-1a, which is why an
ASCII dictionary reproduces the constants exactly.


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

Nothing here is taken from wave29A: the function, its bounds and its immediates
are read from the file; the names are then produced by hashing candidates.

---

## 2. Why the key set is complete (the surface, enumerated)

* **Function bounds come from `.pdata`, not from a guess.**  The hand-picked
  ranges above equal the `RUNTIME_FUNCTION` entries exactly:
  `main = [0xcba3130, 0xcba43d7)`, `export = [0xf03eb40, 0xf03f396)` (checked in
  the tool; the image end bound is computed from the section table, never a literal).
* **`complete_decode = True`**: capstone decodes byte-for-byte to the function end
  with no undecoded tail, so no trailing compare is missed.
* **Zero indirect jumps** (`jmp r/m64`, `jmp rax`, …) in either function, so there
  is no dispatch table hiding keys — the compared immediates are the whole key set.
* The compared values are all `cmp ecx, imm32`; the tool counts **27** distinct
  immediates over **37** sites (main) and **9** over **12** (export).  Repeated
  sites are binary-search tree re-tests of the same key, not new keys.

---

## 3. Main dispatcher — all 27 keys (`0xcba3130`–`0xcba43d7`)

Every row verified by hashing the name with the loop above and matching the
immediate byte-for-byte.  "src" is where the name string is attested.

| imm | name | cmp site(s) |
|---|---|---|
| `0x0b69f28d` | **DeleteComponentForEditObj** | `0xcba3428` |
| `0x1880a8de` | FocusLocalBullet | `0xcba3434` |
| `0x1a33f6f9` | AddInstructionGraphForPrefab | `0xcba341c`, `0xcba3440` |
| `0x1f56cd02` | ModifyFactionForPrefab | `0xcba3715` |
| `0x25139089` | ModifyFactionForEditObj | `0xcba3721` |
| `0x2c4eda76` | DeleteInstructionGraphForEditObj *(preimage, §5)* | `0xcba3410`, `0xcba372d` |
| `0x3f5d30b2` | FocusCharacter | `0xcba359c` |
| `0x460c83db` | ModifyPrefabTag | `0xcba35a8` |
| `0x5a1a25f3` | DeleteInstructionGraphForPrefab *(preimage, §5)* | `0xcba3590`, `0xcba35b4` |
| `0x5c27df0e` | **DeleteComponentForPrefab** | `0xcba388e` |
| `0x68677bd6` | ApplyPrefabInstanceChange | `0xcba3882`, `0xcba389a` |
| `0x755a10f3` | DeleteEditObj | `0xcba3b7d` |
| `0x78eb3304` | FocusEditObj | `0xcba3404`, `0xcba3b89` |
| `0x7ca8b102` | FocusBeyondTileMap | `0xcba352b` |
| `0x83668ec8` | DeletePrefab | `0xcba3513` |
| `0x89cf06af` | JumpCombatSetting | `0xcba3507`, `0xcba351f` |
| `0x9f65756b` | RequestPrefabInstance | `0xcba37e9` |
| `0x9fe1144f` | ModifyEditObjName | `0xcba37dd`, `0xcba37f5` |
| `0x9ffa4fa9` | FocusEsp | `0xcba3a93` |
| `0xa8a12ee8` | **AddInstructionGraphForEditObj** | `0xcba34fb`, `0xcba3a9f` |
| `0xb202598a` | FocusPrefabInstance | `0xcba3653` |
| `0xb7f550fe` | ModifyPrefabName | `0xcba365f` |
| `0xbd40da3c` | ModifyEditobjTag *(lower-case `o` is original; FNV is case-sensitive)* | `0xcba3647`, `0xcba366b` |
| `0xbf0390c9` | FocusDropGather | `0xcba3911` |
| `0xc7280e4f` | FocusScreenshot | `0xcba3905`, `0xcba391d` |
| `0xd807fbc5` | ModifySuite | `0xcba3bf4` |
| `0xe703f83d` | FocusLight | `0xcba3c00` |

**Verb census (corrected):** Focus ×9, Modify ×7, Delete ×6, Add ×2, Apply ×1,
Jump ×1, Request ×1 = **27**.  (wave29A printed "Focus ×11", which summed to 29
against 27 keys; the true count is 9.  Fixed in `NATIVE-COMMAND-SURFACE.md`.)

---

## 4. Export dispatcher — all 9 keys (`0xf03eb40`–`0xf03f396`)

| imm | name | cmp site(s) | verification basis |
|---|---|---|---|
| `0x07724773` | ImportDebugLog | `0xf03ed0c` | corpus + string-table + `command_route` |
| `0x08aee119` | **DoImportClientScript** | `0xf03ed00`, `0xf03ed18` | hash preimage + sibling of the confirmed `DoExportClientScript` (§5) |
| `0x0a2d8704` | ImportAllDebugLog | `0xf03ee95` | corpus + string-table |
| `0x26e623fe` | **DoExportClientScript** | `0xf03ecf4`, `0xf03eea1` | **date-confirmed**: `.runtime/verification/docs-71-20260926/native-command-rescan-all38.json` records `cmp ecx,0x26e623fe` @`0xf03ecf4`/`0xf03eea1` under this exact name; `tools/editor-bridge/Adapter/ClientScriptExportProbe.cs:51` invokes `beyondExportService`/`DoExportClientScript` live |
| `0x5986b6f9` | DeleteDebugLog | `0xf03ed92` | corpus + string-table |
| `0x6e900256` | RefreshExistDebugLogReport | `0xf03ed86`, `0xf03ed9e` | corpus + string-table |
| `0xc9824659` | DoImport | `0xf03ef30` | corpus + string-table + `command_route` |
| `0xd19570b8` | ImportPerformanceReport | `0xf03ef3c` | corpus + string-table |
| `0xd8aae5e2` | DoExport | `0xf03ef48` | corpus + string-table + `command_route` |

**Verb census:** Import ×3, Do ×2, Delete ×1, Refresh ×1, ImportClientScript,
ExportClientScript.

Note the **service registration literal tells the truth about the family**: the
five decompiled files that reference the `beyondExportService` accessor register
**exactly 7** commands (ImportDebugLog, ImportAllDebugLog, DeleteDebugLog,
RefreshExistDebugLogReport, DoImport, DoExport, ImportPerformanceReport).  The two
`*ClientScript` keys are the **backend superset** — engine-side slots with no
current editor registration, exactly like `AddInstructionGraphForPrefab` /
`ApplyPrefabInstanceChange` are for the main table.

---

## 5. Naming the four keys that no corpus literal covers

wave29A left `0x2c4eda76`, `0x5a1a25f3` (main) and `0x08aee119`, `0x26e623fe`
(export) unnamed.  All four now have a name, at three clearly separated tiers:

| imm | name | how | independent source |
|---|---|---|---|
| `0x2c4eda76` | DeleteInstructionGraphForEditObj | **hash preimage** (exact) | `docs/gameplay/FRONTEND-BACKEND-TRACE-20260920.md:160` reached the same name on 2026-09-20 and flagged it "inferred, not plaintext-recovered"; symmetric with `AddInstructionGraphForEditObj` @`0xcba34fb` |
| `0x5a1a25f3` | DeleteInstructionGraphForPrefab | **hash preimage** (exact) | same line of the same 2026-09-20 doc; symmetric with `AddInstructionGraphForPrefab` @`0xcba341c` |
| `0x26e623fe` | DoExportClientScript | **hash preimage** (exact) | the dated 7.1 evidence json AND the live bridge probe both name it (§4) |
| `0x08aee119` | DoImportClientScript | **hash preimage** (exact) | the other `*ClientScript` key in the same dispatcher as the confirmed `DoExportClientScript`; unique match among 22 tested `*ClientScript` names; only local attestation is today's prose, so it stays `(inferred)` |

A hash preimage proves *"this string hashes to this constant"*, which is exactly
the engine's dispatch criterion — but it does **not** by itself prove the engine
was compiled with *that* string rather than some other preimage.  The tool keeps
that distinction: a name is a **dictionary hit** only when a decompiled literal,
a registration table or the dated evidence json attests it; a name attested **only
by project prose** is reported **`(inferred)`**.  So `DoExportClientScript` prints
as a dictionary hit (evidence-sourced) while the other three rows above print as
`(inferred)` — `0x08aee119` in particular rests on symmetry plus its own exact
preimage, not on an independent attestation.

What was searched to place these names (all local, all read-only): every literal
in the 12,375-file decompiled corpus and the 2,830-entry string table; every text
value in both research sqlite DBs; the prior native hash index; a 92,016-candidate
domain brute force; and a token sweep of `docs/**/*.md` (24,414 distinct tokens).

---

## 6. The truncated "91 naive hits" claim — resolved

wave29A said: *"4764 add-component/create-template/terrain-write candidate names
-> 91 naive imm hits, ALL ran …"*.  Reproduced exactly
(`--collision-check`, and `.runtime/scratch/20261011/fnv/hits91.py`):

| stage | method | names hit |
|---|---|---|
| 1 | 4-byte value present **anywhere** in the 445,006,744-byte image (4 phases) | **91** |
| 1-ctl | same method, **random** targets of the same count | **97** |
| 2 | value must be the immediate of a real `cmp r32, imm32` | **0** |
| 3 | that site must live inside an FNV-hash-loop function | **0** |
| ctl+ | the 36 known dispatch constants through stage 2 | **36/36** (49 sites) |

**All 91 were rejected.**  The random control lands at 97 — the naive count is
*below* the noise floor, so the naive method carries no signal at all.  Expected
random occurrences = `4764 × 445,006,744 / 2³² ≈ 494` (wave29A's "~120" used the
single-phase window count, 111,251,686; both framings agree that 91 is chance).

**The exact filter** (this is the collision handling the report must show):

> an FNV-1a-32 hash is a **dispatch key** only when the 4-byte little-endian value
> occurs as the **imm32 operand of a real `cmp r32, imm32` instruction** — i.e.
> opcode `0x81`, a modrm byte with `(modrm & 0xF8) == 0xF8` (group-1 opcode /7 =
> CMP, register operand), and 5 more bytes available.  A raw 4-byte coincidence
> anywhere else in the image is discarded.

The runtime is collision-safe in the same spirit: each dispatch branch re-checks
the whole string (pointer → length → UTF-16 equality, `0x19537450` in this build),
so a hash collision cannot mis-route at run time either.

---

## 7. Does *any* key add a component, create a template, or write terrain?  No.

Census of the **full 36-key surface** (both dispatchers, all keys named):

| category | verbs present | verdict |
|---|---|---|
| **add a component** | component noun appears **only** in `DeleteComponentForEditObj` / `DeleteComponentForPrefab` | **NO** add/attach/insert |
| **create a template / asset** | no `Create*`, `New*`, `Make*`, `Instantiate*`, `Register*` key at all.  The two `Add*` keys bind a node **graph**; `ApplyPrefabInstanceChange` applies a change to an *existing* prefab instance; `RequestPrefabInstance` only *looks one up* | **NO** |
| **write terrain** | no key mentions Terrain / Tile / Cell / Map except `FocusBeyondTileMap`, which is a *focus* command (panel switch) | **NO** |

`AddComponent` / `CreateComponent` / `AttachComponent` / `InsertComponent` /
`CreateTemplate` / `CreateAsset` / `SetTerrain` / `PaintTerrain` / … are absent as
dispatch keys (§8 shows this is not "I didn't look").

---

## 8. Why §7 is a proof-grade negative — and what it does *not* prove

**(1) Surface enumerated.**  Both dispatchers are fully decoded to their `.pdata`
bounds (`complete_decode=True`) and contain **no indirect jump**, so the compared
immediates are the complete key set: 27 + 9 = 36 keys, all named, all in §3/§4.
Command: `python tools/editor-catalog/fnv_command_surface.py`.

**(2) Positive control.**  The same method reproduces the two truths the question
turns on — `DeleteComponentForEditObj` @`0xcba3428` and `AddInstructionGraphForEditObj`
@`0xcba34fb` — plus `DoImport`/`DoExport` @`0xf03ef30`/`0xf03ef48`, and the whole-image
filter keeps **36/36** known constants with 49 real cmp sites (§6).

**(3) Three structurally different approaches.**
  a. **Direct bounded disassembly** of the two dispatcher functions (§2–§4).
  b. **Whole-image cmp-site hash scan** over the add/create/terrain verb space —
     4,764 candidate names, filter of §6 → 0 (§6).
  c. **Client-side registration sweep** — the editor's own registration literals
     for `beyondExportService` yield exactly 7 commands; the corpus/string-table/
     sqlite/docs universe is hashed against both dispatchers and names 33 of 36
     keys outright (§5).

**Boundary (read this before quoting §7).**  This proves absence *for a
dispatcher that compares a literal `imm32` of FNV-1a-32 over the UTF-16 name*, in
the two functions located.  It does **not** cover: a dispatcher using a different
hash; a table-driven dispatch; keys built at run time; or a name arriving by a
route other than this one.  The service-name layer already proved one thing is
invisible to a hash sweep — it compares service names through a managed object's
virtual `GetHashCode` (`docs/research/beyondeditor-backend/05-`).  A name that
dispatches through managed code is not visible here.  Also: `global-metadata.dat`
is `MHY`-encrypted (magic `4D485900`, standard IL2CPP would be `FAB11BAF`), so
the literal string heap is not readable statically — the names above are recovered
by **hashing candidates**, not by reading the strings.

---

## 9. Reproduction


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


`capstone` lives under `.runtime/native-analysis/deps`; the tool finds it there,
and its immediate-extraction path is pure-byte so it still runs without it.
`numpy` accelerates the image scan; a stdlib fallback exists.

**Not done this round:** no process started/connected/restarted; no UAC; no game
memory read; **no address executed**; no packet sent; no file under `D:/games` or
`LocalLow` written; `global-metadata.dat` not decrypted.
