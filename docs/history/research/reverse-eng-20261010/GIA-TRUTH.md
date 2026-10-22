> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# GIA-TRUTH — settling the `.gia` claims

> Created 2026-10-10. This is the only file this task writes.
> Scope: task #6 — a sibling decoded `.gia` (`tools/beyond-save/gia.py`) and a verifier
> REFUTED part of its premise (that the project had never examined a `.gia`). This doc
> settles four things:
> (1) prior `.gia` handling that predates `gia.py`; (2) what `gia.py` proves vs assumes;
> (3) whether a `.gia` can carry the graph node/edge list in a walkable form; (4) verdict —
> what a `.gia` can prove that a `.gil` cannot, and what neither can prove.
>
> **All read-only.** No bridge/native request sent, no game/editor touched, nothing read or
> written under `C:\Users\PUBLIC_USER\AppData\LocalLow\miHoYo\`. Every byte cited below comes from
> `.runtime/` artifacts already in the repo. The one experiment run (edges, §3) is offline
> decoding of an existing export. No image/PDF was read.

---

## 0. Verdicts up front

| Claim under test | Verdict | Where |
|---|---|---|
| "The project had never examined a `.gia`." | **FALSE — refuted.** The repo has read/parsed `.gia` since **2026-09-16** (66+ MB of vendored source, a purpose-built edge decoder, and a design-checker that asserts edges). | §1 |
| `gia.py` proves the framing = the `.gil` container (subtype 3). | **TRUE**, byte-for-byte round-trip on 67 real files; 22 tests pass. | §2 |
| `gia.py`'s "no separate edge list in the graph body" | **TRUE but narrow.** Edges are not a body-level field; they live one level deeper, inside each node's pins. | §2, §3 |
| "These `.gia` contain no edge encoding" (`GIA-EXPORT-MINE.md` §4) | **REFUTED.** A real export's decoded edges match its build plan **16/16 + 15/15 node defs**. Edges are walkable. | §3 |
| A `.gia` can carry the graph node **and edge** list in a walkable form. | **YES** — with bytes, and independently cross-checked against a ground-truth plan. | §3 |
| The `.gia` export *reply* carries the content. | **NO** — all 67 replies are `{"receivedUtc":…, "rows":[]}`. The FILE is the evidence, not the reply. | §4 |

---

## 1. Prior `.gia` handling BEFORE `gia.py` (task item 1)

`gia.py` was authored 2026-10-10 04:36. The premise that no `.gia` had been handled before it is
false. Bash `grep -rIl '\.gia'` over `tools/`, `docs/`, and `.runtime/` (the Grep tool skips
`.runtime/`, so Bash was used) finds a large body of earlier work. Grouped by what it did:

### 1.1 Read / decode a `.gia` (the load-bearing ones)

| file:line | what it does |
|---|---|
| `tools/editor-bridge/inspect-graph.py:12` (`def inspect`), `:22-25` (container check), `:27` (`bundle.ParseFromString`), `:35-54` (node + **edge** loop), `:58-63` (report with `nodes`, `links`, `directedEdges`) | **Full `.gia` graph decoder.** Validates the `0x326/kind 3/0x679` container by hand (`:22-25`), then parses the payload with the vendored proto schema `gia_graph_pb2` and emits every node, every **link** (`{from,to,fromKind,toKind}`, `:41`) and every normalised **directed edge** (`:50`). Dated **2026-09-16**. |
| `tools/editor-bridge/scan-pin-value-state.py:1-8` (docstring), `:19-22` (schema import) | Read-only `.gia` scanner that opens the container and the proto schema directly and reports every pin where `is_value_set` is true but the value oneof is empty. Deliberately *not* via `inspect-graph.py`. Dated **2026-09-17**. |
| `tools/editor-bridge/verify-runtime-audit.py:22-24` (loads `inspect-graph.py` as a module), `:95` (`inspect_graph.inspect(path)`) | Reuses the decoder; "read exported `.gia` bytes … and compared against its design" (`:4`). |
| `tools/editor-bridge/verify-gameloop-graph.py:53` (design `EDGES`), `:66-68` (asserts decoded `directedEdges == design`) | A **design-checker**: it asserts the decoded `.gia` edge set equals the graph's intended flow+data links. Dated **2026-09-22**. |
| `tools/editor-bridge/verify-static-level-draft.py:56` | Runs the decoder on a packaged `tiled.gia`. |
| `mvp/generate_mvp.py:37,:231,:349`, `mvp/asset_api.py:831`, `mvp/stage_api.py:83` | Generate/verify `mvp/build/platformer_min.gia` from `evidence/sample.gia`. |

### 1.2 Write / rewrap a `.gia`

| file:line | what it does |
|---|---|
| `tools/editor-bridge/build-tiled-route.py:75` | Emits a `.gia` envelope: `struct.pack('>5I', len+20, 1, 0x326, 3, len) + packed + struct.pack('>I', 0x679)`. |
| `tools/editor-bridge/build-route-placement.py:59` | Same envelope writer. |
| `tools/editor-bridge/build-static-course-asset.py:25` (template), `:296` | Clones entities from `mvp/build/platformer_min.gia`. |
| `tools/editor-bridge/repair-static-course-envelope.py:47-51,:253` | Repairs a `.gia` envelope; writes a single candidate. |
| `tools/editor-bridge/backup-live-course.ps1:45-47` | Backs up exported `.gia` by sha256. |
| `tools/editor-bridge/Adapter/ServerPlacement…`/`EditorAdapter.cs` / `ClientScriptExportProbe.cs` | Produce `.gia` (see §4). |

### 1.3 Vendored third-party `.gia` code and schemas under `.runtime/` (Bash-only visible)

`.runtime/research-sources/` holds cloned community repos (all predate `gia.py`):

* `file-formats/auto-miliastra/` (C02, `marcos0318/auto-miliastra`, head `4de39f3`): `src/miliastra_agent/core/proto_gen/gia_graph_pb2.py`, `gia_pb2.py`, `parsers/node_graphs.py` (`parse_gil_node_graphs`, reads graphs out of GIL **field 10**), `parsers/gil.py`, `generators/gia_encode.py` (encode `EntityPlacement` → GIA). Dated 2026-09-14.
* `file-formats/genshin-miliastra-file-format/` (C01), `file-formats/UGC-File-Generate-Utils/` (C03), and C04 `UGC-Gia-Gil-ProtoBuf` — hand-reconstructed `.proto` only. Per `.runtime/research-sources/file-formats/evidence/evidence.json:44,67`, C02's encoder is *ported* from C03, and C04's README states its fields are "reverse-engineered guesses".
* `file-formats/evidence/sample.gia` (162 B, sha256 `b925100a…38ee`) — a synthetic community artifact; `evidence.json:121` records "no generated `.gia` was ever imported into the game".
* `ecosystem/Ayaya_Miliastra_Editor/…` — a full third-party editor with `…/shape-editor/shape_editor_backend/export_gia.py:530` (`export_canvas_payload_to_gia`), `private_extensions/ugc_file_tools/beyond_local_export.py`, and multiple `…/commands/{create,export}/*_gia.py`. (NOTE — memory: `Ayaya ugc_file_tools` is **read-only, must not be run**; nothing here ran it.)

### 1.4 Docs that already claimed `.gia` was decoded (predating this wave)

* `docs/archive/project-cleanup-20260924/STRUCTURE.before-cleanup.md:1094` — "inspect-graph.py 只读校验 GIA 容器、节点、参数及**连线**"; `:1100` — "inspect-graph.py 同时报告完整引脚和**归一化连线方向**"; `:1221` — `scan-pin-value-state.py` described as an independent `.gia` reader.
* `docs/gameplay/AUTHORING-CLI-LIVE-TEST-20260923.md:58` — parses a 350 B exported `.gia` with `inspect-graph.py`.

**Conclusion for §1.** The premise behind `GIA-EXPORT-MINE.md:4` ("工程从未分析过一个 `.gia`") is
false and was already self-corrected at `GIA-EXPORT-MINE.md:27`. The verifier's refutation is
CONFIRMED. The repo had, since 2026-09-16, a working `.gia` graph decoder that reads **nodes and
edges**, not merely a container probe.

---

## 2. What `gia.py` actually proves, and what it assumes (task item 2)

Files: `tools/beyond-save/gia.py` (383 lines), `tools/beyond-save/test_gia.py` (309 lines).
I ran the suite: **22 passed in 0.59 s.**

### 2.1 Proves (byte-level, on real files)

* **Framing = the `.gil` container, subtype 3.** `GIA_SUBTYPE = 3` (`gia.py:100`). `decode_gia` calls
  `gil_container.decode_container` (`:322`) and **rejects any non-3 subtype** with a named error
  (`:324-327`). Tested on **all 67 real exports** — `test_real_gia_files_decode_with_the_gil_container_framing`
  (`test_gia.py:86`) and `test_gia_container_and_payload_round_trip_is_byte_identical` (`:99`), which
  re-encodes with `gil_container.encode_container`/`encode_fields` and asserts byte-identical output.
* **Three payload shapes are distinguished.** Single envelope + graph body field 13 → `"graph"`;
  single envelope + client-script body field 35 → `"client-script"`; multiple top-level field-1
  entries → `"entities"` (`gia.py:336-362`). I confirmed against the real corpus:
  **61 graph + 6 client-script = 67**.
* **The graph node table is walkable and correct.** For the calibration graph, decoded kinds
  `[71,73,14,2,252,1]` and positions `(0,0)(0,300)(350,250)(700,0)(1050,0)(1450,0)` reproduce the
  `Add(kind,x,y)` calls in `EditorAdapter.cs:773` (`test_gia.py:190-205`). Node indices are 1-based
  and consecutive (`:209`); every node carries category `(10001,20000,22000)` (`:216`).
* **The "no separate edge list" negative is real but body-scoped.** `_parse_graph` asserts the graph
  body's child field numbers are a subset of `{1,2,3}` = header, name, repeated node — a fourth,
  body-level field would raise `GiaError` (`gia.py:259-261`; `test_a_graph_body_has_no_edge_list`
  `:224-237`, run across *all* real graph exports). The same module docstring states it plainly
  (`gia.py:49-51,71-80`): links, *if any*, are inside a node's repeated `field 4` (ports), "and that
  encoding is not decoded here."

### 2.2 Assumes (must not be read as proven)

* **That the body-field check generalises.** The `⊆{1,2,3}` invariant holds over the 61 exports in
  the repo — a finite, project-owned sample. It is an observed negative, not a vendor guarantee.
* **That field numbers are stable.** `gia.py:35-43` says explicitly these are "evidence, not a vendor
  schema."
* **Nothing about port/edge encoding.** `GiaNode.ports` returns raw `Field`s and `test_gia.py:241-251`
  asserts only that no `edges` attribute exists on the node/graph objects — a scoping claim about
  this module, not a claim that edges are absent from the file (see §3).
* **`proto3` zero-omission.** `_float32` maps absent `field 5/6` to `None` = `0.0` (`gia.py:159-163`),
  which the calibration test encodes at `test_gia.py:199-204`. Correct for these files; an assumption
  about the writer.

**What `gia.py` is, precisely:** a self-contained, dependency-free reader of the container + the
node table, that deliberately stops at "nodes, not edges."

---

## 3. Can a `.gia` carry the graph node/edge list in a walkable form? (task item 3)

**Yes — nodes and edges both, with bytes, verified against ground truth.** The claim in
`GIA-EXPORT-MINE.md` §4 ("在这些 `.gia` 里找不到'边'的显式编码") is **refuted**.

### 3.1 A real `.gia` exists (bytes)

`mvp/build/platformer_min.gia` — 790 B, header
`00 00 03 12 | 00 00 00 01 | 00 00 03 26 | 00 00 00 03 | 00 00 02 fe`, trailer `00 00 06 79`.
An **entity** export: 6 entities `MVP_StartPad,MVP_Platform_01..04,MVP_GoalPad`, entity_ids
`1078000000..5`, kind 3.

Graph exports: 61 files under `.runtime/editor-bridge/exports/*/*.gia` (e.g. the 39-node
`MW_Route_Tiled_20260916`, the 29-node `MW_Game_Loop_20260917`).

### 3.2 The edge encoding, read straight from a real file

Node record = body `field 3`; its `field 4` = pins; **each pin's `field 5` = a repeated connection**:


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


This is exactly the `PinInstance.connections` → `NodeConnection{target_node_index=1, target_pin_shell=2,
target_pin_kernel=3}` shape in the vendored `gia_graph_pb2` (verified by introspection:
`NodeInstance.pins=4`, `PinInstance.connections=5`, `NodeConnection.target_node_index=1`).

### 3.3 Independent cross-check against a ground-truth plan (the decisive test)

`.runtime/scratch/MW_API_FARM_DEMO-plan.json` is the build *plan* (15 nodes / 17 edge entries / 13
values). Its export exists
(`.runtime/editor-bridge/exports/miliastra-bridge-9b9a2e09-…/bridge-export-35756012….gia`, 1657 B).
Decoding the `.gia` via `inspect-graph.py` and comparing to the plan:


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


16/16 edges and 15/15 node definitions match, index-for-index. The export is the editor's real
graph (`GIA-EXPORT-MINE.md:190-192` independently proved the node table is not a request echo).

### 3.4 Why `GIA-EXPORT-MINE.md` §4 got it wrong

`GIA-EXPORT-MINE.md:155,209` labelled pin `field 5` as `{f1:<序号>, f2:{f1:<侧>}, f3:{f1:<侧>}}`
("sequence number" and "side"). The bytes are right; the semantics are not. `field5.f1` is the
**target node index** (values 1..N, e.g. `2` above), and `field5.f2.f1` / `field5.f3.f1` are the
**target pin kind** (1=IN_FLOW, 2=OUT_FLOW, 3=IN_PARAM, 4=OUT_PARAM), not a "side". §4.3 searched
`f1.f2`/`f2.f2` (the pin *slot* index, legitimately ≤7) for a node index and so missed it; the node
index lives in `field5.f1`. The "no edge found" conclusion is therefore a mis-read, not a real
absence — §3.3 settles it.

### 3.5 Caveats that remain honest

* The edge decode depends on the **third-party** `gia_graph_pb2` schema (C02/C04). But the plan↔gia
  agreement (§3.3) is an *independent* validation that the connection field numbers reproduce a
  ground-truth design — the schema is not merely "plausible"; it decodes a known graph correctly.
* `verify-gameloop-graph.py` currently **fails** on every `MW_Game_Loop_20260917` export now on disk
  (`ValueError: Node definitions do not match the design`); the design-conformant 3612 B export the
  docs cite (`PROGRESS-LITE.before-cleanup.md:265`) has been pruned. The claim that the checker ever
  passed is doc-only, not reproducible from the current tree. The FARM_DEMO check in §3.3 *is*
  reproducible and is the stronger evidence.
* I did not run the byte-diff experiment proposed at `GIA-EXPORT-MINE.md:217-227`; it is not needed —
  §3.3 already proves the edges are present.

---

## 4. The export code path and the `.gia` reply fields (task item 3, second half)

**Producer.** `EditorAdapter.ExportResource` (`tools/editor-bridge/Adapter/EditorAdapter.cs:914-951`):
builds the argument list, names the file `bridge-export-<guid>.gia` (`:927`), registers an
`ExportReplyCapture`, then dispatches `beyondExportService.DoExport` (`:937`, symbol `Ikci0qkvMZX`).
It returns
`{ok, status:"invoked-not-confirmed", receiptFields, path, replyPath, callbackWindowSeconds:30, category, id, modelType}` (`:950`).
The client-script variant is `ClientScriptExportProbe.ExportClientScriptProbe`
(`Adapter/ClientScriptExportProbe.cs:12`), which writes `client-script-<guid>.gia` (`:30`) via
`beyondExportService/DoExportClientScript` (`:51`).

**Reply.** `ExportReplyCapture.Receive` (`EditorAdapter.cs:890-904`) writes only `{receivedUtc, rows}`
from primitive fields of the returned rows. In practice **all 67 reply sidecars are
`{"receivedUtc":"…","rows":[]}`** — I checked all of them; zero non-empty. A task-level receipt
(`.runtime/authoring/requests/…/elevated-response.json`) carries `receiptFields:{"aNVLbapd8Hk":9}` and
`status:"invoked-not-confirmed"`.

**So the reply proves nothing about content.** The `.gia` on disk is the only evidence, and it is
real — §3.3 proves the node/edge content is the editor's, not an echo.

---

## 5. Final verdict (task item 4)

### What a `.gia` can prove that a `.gil` cannot

* **Per-resource, name-keyed fidelity.** A `.gia` is one exported *user resource* (`resource_id` /
  name / model kind: 9 = node graph, 69 = Lua graph; `gia.py:40-43`, `GIA-EXPORT-MINE.md:112`). You
  can ask "what does the editor hold for the graph named `X`?" and get that graph's node table **and
  edges** (§3.3) as a standalone asset — independent of which level it lives in.
* **The serialised asset form.** A `.gia` is the byte form that would be moved between accounts/levels
  via the official import/export flow (`docs/official-docs/chapters/mhxbd59urbfu.json:38`). A `.gil`
  is the *level save* (entities + terrain field 7 + graphs field 10); it shows the level, not the
  portable resource.
* **A `.gia` is polyvalent.** Same container/suffix carries graphs, client scripts, and entity bundles
  (`platformer_min.gia`) — a `.gil` does not.

### What NEITHER can prove

* **That the graph runs, or that the level is playable.** Both are files; both correspond to
  `"invoked-not-confirmed"` / `persistenceVerified:false`. `evidence.json:121` records that no
  generated `.gia` was ever imported into the game. Neither format is game acceptance.
* **Entity ↔ graph binding.** Which entity executes which graph is not in the exported graph asset
  (nor established here for the `.gil`); a `.gia` proves the graph's *content*, not its *attachment*.
* **That a `.gil` round-trips through the game.** The native save path rewrites the file; a decoded
  snapshot is a claim about bytes-at-rest, not about what the game will keep.
* **Terrain semantics beyond field 7 (`read-only`).** `tools/beyond-save/terrain.py` reads field 7 but
  no persistent write exists (`CLAUDE.md` §6b) — a `.gil` cannot yet be *shown* to accept terrain edits.

### One-line answer

A `.gia` is exactly as strong as a `.gil` for *reading*: both are containers the repo can decode
offline. The `.gia`'s distinctive power is that it hands you one named graph's node **and edge** list
in a portable asset — which §3.3 proves is walkable and correct — but like the `.gil` it proves
nothing about running, binding, or game acceptance.

### Corrections this doc files

1. `GIA-EXPORT-MINE.md:23` ("桥导出 `.gia` 里有边… 未找到") is **wrong** for the repo's own schema
   decoder; `.gia` edges are present and match a plan 16/16 (§3.3). Recommend annotating that row.
2. `gia.py`'s docstring is correct in scope but a reader could infer edges are unknowable; the edge
   decode lives in `tools/editor-bridge/inspect-graph.py` (predates `gia.py` by ~3 weeks) via the
   vendored `gia_graph_pb2`. Recommend a cross-reference in `gia.py`'s "What this module does NOT
   establish" section.
3. The premise "the project had never examined a `.gia`" is false (§1); anything built on it should
   be re-based on §1's inventory.
