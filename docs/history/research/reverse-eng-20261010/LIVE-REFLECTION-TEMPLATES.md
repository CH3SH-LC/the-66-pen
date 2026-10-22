> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# LIVE-REFLECTION-TEMPLATES — does the LIVE editor assembly expose a template-create path?

Task #3 of wave `reverse-eng-20261010`. Owner: this file only.
Instrument: the read-only `reflection-probe` bridge op (`tools/editor-bridge/Adapter/ReflectionProbe.cs`),
which enumerates the types/methods of every assembly loaded in the editor's AppDomain — immune to a
gap in the decompiled corpus, because it asks the LIVE assembly instead.

Method: invoke `reflection-probe` with `nameContains` values aimed at the panel/service names
(Template, Shop, Currency, Item, Stuff, Bag, Inventory, StuffBag), then `nameContains=Service`, and
report the raw replies.

## VERDICT (plain, upfront)

**The probe was NOT invoked. Every attempt was refused by the live transport before dispatch, with
`CALL_FIELD_NOT_ALLOWED:nameContains`.** Nine identical refusals are recorded in the live runner log
(the task's own attempts plus a concurrent sibling's). The op exists in the source and is compiled into
the newest bridge build, but the **resident elevated helper predates the probe's parameter plumbing and
cannot carry `nameContains`**. Fixing this requires restarting the helper, which this task is forbidden
to do. Per the task's own escape hatch ("if the op is missing, report and stop"), I report and stop.

**Therefore no live-assembly answer for template/service type or method enumeration can be produced
under the current live state.** The `nameContains` lists in the task could not be executed.

---

## 1. The op IS present and loaded — in every layer except the one that is running

| Layer | Has the probe? | Evidence |
|---|---|---|
| Adapter source | yes | `tools/editor-bridge/Adapter/ReflectionProbe.cs:84` `ReflectionProbe(JsonElement)`; `:52` `ValidateReflectionProbe` |
| BridgeServer dispatch | yes | `tools/editor-bridge/ManagedBridge/BridgeServer.cs:345` `case "reflection-probe":` |
| Compiled DLL | yes (R274+) | byte-scan of `bin/Release/net8.0-windows/Miliastra.EditorBridge.Net8R276.dll` contains the type `ReflectionProbe`, the method `ValidateReflectionProbe`, and the UTF-16 op string `reflection-probe` |
| `call-bridge.ps1` op name | yes | `tools/editor-bridge/call-bridge.ps1:1` ValidateSet contains `'reflection-probe'`; `:49-51` builds `nameContains` |
| `elevated-request.py` CLI | yes | `tools/editor-bridge/elevated-request.py:279` `validate_call_reflection`, `--name-contains` flag |
| **resident helper (pid 188156)** | **NO** | runner's in-memory `Get-ValidatedCallArguments` has no reflection branch → refuses the field |

The build was also injected and accepted: run `484cbe64` bootstrap log says
`payload loaded: Miliastra.EditorBridge.Net8R276 … payload returned 0`, and its `bridge.log` says
`bridge accepted for pid 120204`. So the *bridge half* of the op is live; only the *PowerShell transport
half* is not.

## 2. Why the transport refuses — the resident helper is stale

- Helper started: **2026-10-10T06:19:14.88Z** (`runner.log:1773`, `runner started; pid=188156 … ops=137`).
- `tools/editor-bridge/elevated-runner.ps1` mtime: **2026-10-10T07:24:44Z** — i.e. the script on disk was
  edited **~65 minutes AFTER the helper process started**.
- The runner reads the *op name* whitelist from `call-bridge.ps1` on every request (`Get-AllowedOps`), but
  the *field* allowlist is a function (`Get-ValidatedCallArguments`, `elevated-runner.ps1:250`) compiled
  into the running process at load. The on-disk version has the reflection branch at
  `elevated-runner.ps1:279` (`$allowedFields=@('kind','runId','op','nameContains','memberContains')`) and
  the forwarder at `:378-388`; **the running process does not have them.**
- Consequence: for `op=reflection-probe` the running process falls through to the generic
  `$allowedFields=@('kind','runId','op','ids')`, so any request carrying `nameContains` is refused at
  `elevated-runner.ps1:285` with `CALL_FIELD_NOT_ALLOWED:nameContains` — before `call-bridge.ps1` or the
  bridge ever see it. A request *without* `nameContains` passes the field gate, reaches
  `call-bridge.ps1:49-50`, and is refused there with `REFLECTION_NAME_CONTAINS_REQUIRED` (seen once).

Corroboration that the helper was not restarted: the log's last three `runner started` lines are
`2026-10-09T15:28:54Z pid=176324`, then `2026-10-10T06:19:14Z pid=188156`. Nothing newer. The heartbeat
at 2026-10-10T08:29:55Z still reads `pid=188156 handled=41`.

## 3. RAW evidence (verbatim)

### 3a. My own attempt (this task), run-id `484cbe64-b542-4947-96a6-f8a8ef459574`

Submission `.runtime/editor-bridge/elevated-queue/aaaa0000bbbb1111cccc2222dddd3333.submission.json`:

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

Reply — no `.response.json` was written; the runner wrote `.error.txt`:

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

`runner.log`: `2026-10-10T08:27:53.9976853Z error id=aaaa0000bbbb1111cccc2222dddd3333 : CALL_FIELD_NOT_ALLOWED:nameContains`

### 3b. Every `reflection-probe` attempt in the live runner log (verify the list yourself)


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

Total `CALL_FIELD_NOT_ALLOWED:nameContains` = **8** (plus 1 `REFLECTION_NAME_CONTAINS_REQUIRED`). The
submissions behind the sibling's entries, verbatim:

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

Every one is exactly the shape the CLI (`elevated-request.py`) produces; the refusal is on the field, not
the needle — so it would be identical for Shop / Currency / Item / Stuff / Bag / Inventory / StuffBag /
Service.

### 3c. Proof the transport itself works (read-only ops that do NOT need `nameContains`)

`describe` — a REAL live reflection over the editor AppDomain — answered normally (run-id `484cbe64`):

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

`ping` (same scope):

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

`verify-interfaces` (same scope) returned `status":"live-interface-surface-matches-static-analysis`,
21/21 slots matched, and live method COUNTS for the interesting models — e.g. `预制模型` (prefab model) 78
methods, `节点定义模型(Kind 6)` 112, `节点图模型(Kind 9)` 122, `实体实例模型` 79, `编辑器管理器` 154,
`资源注册表` 26. This proves the editor AppDomain is enumerable by reflection, and that the ONLY missing
piece is the arbitrary-name `reflection-probe` reaching the bridge.

Note on 3c: `describe` reports `assembly: Miliastra.EditorBridge.Net8R264` because `LookupType`
(`BridgeServer.cs:791`) walks `AppDomain.CurrentDomain.GetAssemblies()` and returns the FIRST assembly
that owns the type — residual older revision assemblies coexist. The bridge that actually served the
`484cbe64` lease is the one whose bootstrap log says `payload returned 0` and whose `bridge.log` says
`bridge accepted`, i.e. `Net8R276` (which does contain the probe). So `describe`'s "R264" is not a claim
about the serving revision; it is only "some R264 residue is loaded first".

## 4. Answers to the task's numbered questions

1. **Probe op loaded?** Present and compiled in the live-serving build (`Net8R276`), accepted into
   pid 120204 — but UNREACHABLE from the queue, because the resident helper's field allowlist rejects its
   required `nameContains` argument. This is the "op is missing" case from the transport's point of view.
2. **Invoke with the needle list / raw replies:** attempted; refused identically for every needle. See §3.
   No `types` array was ever returned.
3. **Methods whose name suggests CREATE (New/Create/Add/Insert/Clone/Copy) with declaring type:**
   **not obtainable** — no probe reply exists to filter.
4. **Live SERVICE types (`nameContains=Service`) and their methods:** **not obtainable** for the same
   reason. The claim that "13 services exist" could not be confirmed or extended against the live
   assembly this way.
5. **Does the LIVE assembly reveal a template-create path?** **Undetermined from the live assembly.**
   The instrument that would answer it cannot be driven while the current helper is resident. This is a
   transport block, NOT a negative result — it must not be read as "no template-create path exists".

## 5. The one unblock (outside this task's authority)

The resident helper (pid 188156) must be replaced by one started AFTER
`tools/editor-bridge/elevated-runner.ps1` mtime 2026-10-10T07:24:44Z, so its in-memory
`Get-ValidatedCallArguments` gains the `reflection-probe` branch (`elevated-runner.ps1:279`). The helper
is explicitly not to be restarted by this task; the decision belongs to the orchestrator/user. Until
then, no `nameContains` value can traverse the sanctioned channel and this whole wave's premise
("invoke the probe") is unexecutable. A second, independent gap to watch once the helper is fresh: the
`load` handler will inject and `Entry.Start` will return `CodeAlreadyStarted` (1) into a process that
already hosts an older revision, so confirm the serving build is a probe-bearing revision via a positive
probe reply, not via `describe`.

## 6. Mechanics of the attempt (for reproduction)

Load (succeeded, ready file appeared for `484cbe64`):

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

Probe call (refused before dispatch):

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

Read-only work only: no save, no mutation, nothing written under LocalLow, helper not restarted, no UAC.
`describe` / `ping` / `verify-interfaces` were used purely to prove the transport is otherwise healthy.
