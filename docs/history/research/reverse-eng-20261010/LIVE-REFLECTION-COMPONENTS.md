> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# LIVE-REFLECTION-COMPONENTS — task #2: use the reflection probe against the live editor

Wave: `reverse-eng-20261010`. Owner file: this document.
Date: 2026-10-10 (UTC). Author: task #2 agent.

---

## 0. HEADLINE (read this first)

**The decisive experiment could not be executed — and it was NOT the bridge, NOT the
probe, and NOT the loaded assembly that stopped it. It was the STANDING ELEVATED
HELPER, whose in-memory copy of `Get-ValidatedCallArguments` predates the
`nameContains`/`memberContains` field allowlist that task #1 added.**

Consequences, stated plainly:

* The live-assembly reflection probe (`reflection-probe`) **exists**, is **registered**,
  and is **compiled into the loaded revision** (R276).
* The bridge **pipe is live and answers read-only ops** (a `ping` succeeded; see §3).
* The one op that answers the component question carries a request field
  (`nameContains`) that **the running helper refuses at its closed-schema gate**,
  before anything is dispatched to the editor.
* Therefore the question "did the LIVE assembly reveal a component-add method the
  static corpus did not?" is **UNANSWERED — not negative**. There is *no* live
  evidence either way, because no probe request ever reached the editor.

The rest of this document is the raw evidence behind those four statements, plus the
exact unblock.

---

## 1. What was asked vs. what could be run

| Step (from the task) | Result |
|---|---|
| 1. Load the newest revision; read the runId from the reply | **Partial.** R275 load → refused (`payload returned 1`). R276 was found already loaded by a sibling (run `484cbe64…`, `accepted=true`, lease to 08:30:23Z). I did not re-bump; see §6. |
| 2. Invoke `reflection-probe` with `nameContains` ∈ {Component, Comp, EditObjComponent}; report the RAW reply | **BLOCKED.** All three attempts were rejected by the helper with `CALL_FIELD_NOT_ALLOWED:nameContains`. Nothing was dispatched. |
| 3. Identify add-suggesting methods (Add/Create/Insert/Append/New/添加) | **N/A** — no type/method list was ever produced. |
| 4. Ask for `*Service*` types and their methods | **N/A** — same block. |
| 5. Did the live assembly reveal a component-add method the corpus did not? | **UNANSWERED — GATED, not refuted.** |

This is a `WAIT/REPORT` outcome, not a "the assembly has no such method" outcome. Do
not read it as a fifth instance of "searched and found nothing".

---

## 2. The probe genuinely exists (so this is not the "op not built" branch)

Task #1 built a real, read-only reflection probe. Verified in the tree:

* `tools/editor-bridge/Adapter/ReflectionProbe.cs:` — `ValidateReflectionProbe`
  (line 52) + `ReflectionProbe()` (line 84). It enumerates `AppDomain.CurrentDomain
  .GetAssemblies()` → `GetTypes()` → `GetMethods(DeclaredOnly)`, names only, bounded to
  64 types × 40 method names, `nameContains` required and length-bounded (4..200). It
  invokes nothing and reads no property getter.
* `tools/editor-bridge/ManagedBridge/BridgeServer.cs:345` — `case "reflection-probe":`
  validates, then runs the probe on the WPF dispatcher.
* `tools/editor-bridge/call-bridge.ps1:` — `reflection-probe` is in the `ValidateSet`
  (line 1), the params `[string]$NameContains,[string]$MemberContains` are declared
  (line 2), and the branch at lines 49–51 does:
  `if([string]::IsNullOrEmpty($NameContains)){throw 'REFLECTION_NAME_CONTAINS_REQUIRED'}
  $request['nameContains']=$NameContains`.
* `tools/editor-bridge/elevated-request.py:279` — `validate_call_reflection()` wires
  `--name-contains` / `--member-contains` into the `call` sub-command.

The op is also in the *live* op whitelist: the helper's `Get-AllowedOps`
(`elevated-runner.ps1:123`) re-reads `call-bridge.ps1`'s `ValidateSet` **per request**,
so `reflection-probe` is accepted as an op name by the running helper. §4 proves this.

---

## 3. Control experiment: the bridge channel is LIVE and read-only ops work

Before blaming the channel, I proved it works. `ping` against the live R276 run
(`484cbe64-b542-4947-96a6-f8a8ef459574`) returned, verbatim:


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


So: the editor process (pid 120204) is up, the bridge is loaded, 119 assemblies are in
the AppDomain — exactly the surface the probe was meant to enumerate — and the queue →
helper → bridge path carries read-only ops end to end.

Meanwhile, in the same window, a sibling request for the probe failed at the helper:


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


The bridge is healthy; the probe's *input* is not deliverable.

---

## 4. THE BLOCKER — raw, reproducible, and diagnostic

### 4.1 The raw reply


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


Same for `Comp` and `EditObjComponent`. Reproduced across the whole wave — every
probe attempt in `runner.log` since the helper started:


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


Note: no corresponding `call op=reflection-probe …` success line exists. The request
never reached the bridge.

### 4.2 Where the refusal is thrown (and where it is NOT)

* `CALL_FIELD_NOT_ALLOWED:` is emitted in exactly one place: `elevated-runner.ps1:285`
  (`if ($allowedFields -cnotcontains ([string]$name)) { throw ('CALL_FIELD_NOT_ALLOWED:' + …) }`).
* On disk, the CURRENT `Get-ValidatedCallArguments` **does** whitelist the two needles
  (`elevated-runner.ps1:277-279`):
  `if(… $props['op'] -ceq 'reflection-probe'){$allowedFields=@('kind','runId','op','nameContains','memberContains')}`.
* The refusal therefore comes from a copy of that function that does **not** contain
  those lines — i.e. the one already resident in the running helper process.

### 4.3 The diagnostic that nails it: ops are LIVE, fields are BAKED

`Get-AllowedOps` (`elevated-runner.ps1:123`) re-reads `call-bridge.ps1` from disk on
every request ("The operation name must match the ValidateSet … which is re-read per
request so the two cannot drift" — `elevated-runner.ps1:22-23`). `Get-ValidatedCallArguments`
is a normal function, parsed once when the helper started.

That asymmetry is exactly what we observe:

* `reflection-probe` is **accepted as an op** (otherwise the error would be
  `OP_NOT_ALLOWED:reflection-probe`, thrown later at the `Get-AllowedOps` check) — so
  the *fresh* `call-bridge.ps1` is being read.
* `nameContains` is **refused as a field** — so the *stale* in-memory validator is
  being run.

### 4.4 Timestamps: the helper predates the field allowlist


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


Task #1 edited the runner (adding the `nameContains` allowlist) at 07:24Z; the helper
had already been standing since 06:19Z. A PowerShell process does not reload its own
script body, so the new allowlist never took effect. The helper's `handled` counter
(`runner.heartbeat` → `pid=188156 handled=41`) confirms a single long-lived process
has served the whole wave.

### 4.5 The transport is elevation-gated (why we cannot simply poke the pipe)

The bridge pipe is created from the elevated editor with
`PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly` (`ManagedBridge/Entry.cs:190-205`); a
medium-integrity client is refused. That is the entire reason the elevated helper
exists ("a non-elevated client is refused" — `elevated-runner.ps1:5-6`). So "just
connect to the pipe from Python" is not an available path, and using one would bypass
the helper's closed-schema gate, which is a deliberate authorization control.

---

## 5. What this means for the wave's question

* **The live-assembly question is still open.** We have *not* learned whether the
  running editor exposes a component-add method the decompiled corpus lacks. The
  instrument was built and loaded; it was simply never allowed to speak.
* **Do not record this as a negative result.** The static corpus came back negative
  twice; a live negative would be meaningful. This is not that. It is a tooling gate.
* One incidental fact did come back from the live process (§3): `loadedAssemblyCount:
  119`, `beyondEditorAssemblyNames: ["BeyondEditor"]` — so the AppDomain the probe
  would enumerate is large and real, not stub-thin.

---

## 6. How to unblock (each is a decision for the orchestrator, not this agent)

**Option A — refresh the helper (cleanest, but needs one UAC / a restart).**
The `nameContains` allowlist is already on disk and correct; only a process that
loaded it *after* 07:24Z will honor it. This is the "widening costs one UAC prompt"
cost the runner's own comment describes (`elevated-runner.ps1:42-43`). Doing this is
explicitly out of scope here (hard rule: never restart the helper, never request a
UAC), so this agent did not attempt it.

**Option B — make the probe field-free.**
Because the helper re-reads *ops* but not *fields*, an op whose needle is fixed in the
op NAME (e.g. `reflection-scan-component`, `reflection-scan-service`, added to
`call-bridge.ps1`'s `ValidateSet`, each hard-mapping to one `nameContains`) would ride
the **existing** helper untouched: the generic field set `('kind','runId','op','ids')`
(`elevated-runner.ps1:265`) already admits it. This requires editing `call-bridge.ps1`
and rebuilding, which is outside this agent's file ownership ("Own ONLY your named
files"), so it is proposed, not done.

**Option C — a fresh revision does NOT help.**
Bumping `next-revision.ps1` → R277 and re-loading rebuilds the *bridge DLL*, but the
gate lives in the *PowerShell helper process*, not the bridge. A new revision would
load fine and still be refused `nameContains`. (R275 had already been burnt —
`_startAttempted`/`_server` — so loading it returned `payload returned 1`; see §7.)

**Recommended sequence once a helper carrying the 07:24Z runner is standing:**


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


---

## 7. Appendix — every load/scan fact this task touched

Stale premise in the wave brief: it states the live bridge is run `33152ae3`
(R272, lease `expiresUtc 2026-10-10T06:28:02Z`). That run is long dead
(`lease-closed.json` present; bootstrap `payload loaded: …Net8R272 … payload returned 0`).
The live runs actually observed were:

| runId | revision | bootstrap | accepted | lease |
|---|---|---|---|---|
| `33152ae3…` | R272 | 06:23:03Z | true | expired 06:28:02Z (dead) |
| `c256952f…` | R275 | 07:35:32Z | true | expired 07:40:31Z (dead, no `lease-closed.json`) |
| `c82eed62…` | R275 | 08:22:26Z | **refused (returned 1)** | expired 08:27:25Z |
| `c1ced5f5…` | R275 | 08:23:45Z | **refused (returned 1)** | expired 08:28:45Z |
| `f4c328ec…` | R275 | 08:24:50Z | **refused (returned 1)** — mine | n/a |
| `484cbe64…` | **R276** | 08:25:23Z | **true** — sibling build+load | expired 08:30:23Z |
| `8cf8ebcf…` | R276 | 08:25:55Z | **refused (returned 1)** | n/a |

R275 was injected once at 07:35Z (`payload returned 0`), so `Assembly.LoadFrom` for
R275 is a no-op and every later R275 load returns `Entry.CodeAlreadyStarted = 1`
(`ManagedBridge/Entry.cs:28,62-65`). This is the documented "one injection per revision
per process" rule (`next-revision.ps1` header). R276 is the same story after 08:25:23Z.

Repo state note: `git log` shows no commits (`Recent commits:` empty), so the "which
files changed at 07:24Z" evidence rests on filesystem mtimes and the runner's own log,
both quoted above.

### Test-coverage note (adjacent finding, not fixed here)

`reflection-probe` / `nameContains` appear in **no** test file — a repo-wide search
over `scripts/` and `tools/editor-bridge/tests/` found them only in
`elevated-request.py`, `call-bridge.ps1`, and `elevated-runner.ps1` (the plumbing), plus
the compiled `BridgeServer.cs` case label. The wave's "tests must pass" bar is met
trivially (nothing changed), but the probe plumbing itself is untested — which is
precisely why a baked-field/stale-helper mismatch could ship unnoticed.
