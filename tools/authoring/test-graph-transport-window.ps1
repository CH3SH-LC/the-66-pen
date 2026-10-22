#Requires -Version 5.1
# Offline response-window regression for tools/authoring/graph-transport.ps1.
#
# WHY THIS FILE EXISTS
#
# 2026-10-09: `author.py graph catalog` died with `BRIDGE_TRANSPORT_FAILED` at
# `stage=send`, and the bridge logged `response write failed: IOException`. Neither was a
# connection failure. graph-transport.ps1 waited 15000 ms for the reply, while
# call-bridge.ps1 -- the transport it is a copy of -- grants the SAME registry-walking op
# 60000 ms, having already measured that walk at ~12.48 s and written the reason into its
# own source ("10s cut the client off mid-response"). This copy never received the
# correction, so the shorter window survived and a real catalog call hit it. The timeout
# then surfaced under the 'send' stage, which reads like a send failure and sent the
# first diagnosis in this project the wrong way.
#
# WHAT MUST STAY TRUE
#
#   1. The window graph-transport.ps1 grants is FAR ABOVE the measured registry walk
#      (~12.48 s) -- with margin, because that figure is a sample, not a bound.
#   2. It is BELOW the 60 s client timeout of elevated_graph_call. At or above 60 s the
#      helper would write its reply to a client that had already given up: the same
#      defect in the other direction.
#   3. A reply arriving after 12 s is read, not cut off -- driven through the production
#      pipe tail, against a local fixture, under the production window policy.
#   4. The refusal semantics of a lost reply are UNCHANGED: `stage` stays 'send' and
#      `outcomeUncertain` stays `($stage -eq 'send')`, so a timed-out WRITE is still
#      reported uncertain and cannot be mistaken for proof that nothing happened.
#      (Pinned statically: reaching the real catch needs a valid compatibility pin,
#      which this offline fixture cannot mint.)
#
# Nothing outside this file's own temporary fixture directory is touched: no game, no
# editor, no process lookup, no DLL hash, no production named pipe. The production
# scope/identity/compatibility prefix is never executed -- only the pipe tail of the
# production try body, taken from the file's own AST.
$ErrorActionPreference = 'Stop'

$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$graphSource = Join-Path $root 'tools/authoring/graph-transport.ps1'
$callSource = Join-Path $root 'tools/editor-bridge/call-bridge.ps1'
$policyName = 'Get-GraphResponseWindowMs'
#: The measured shared-registry walk, quoted from call-bridge.ps1's own comment.
$measuredWalkMs = 12480

$checks = [Collections.Generic.List[object]]::new()
function Check([bool]$value, [string]$name) {
    $checks.Add([pscustomobject]@{ name = $name; passed = $value })
    if ($value) { Write-Host ('PASS ' + $name) } else { Write-Host ('FAIL ' + $name) }
}

function Get-Parsed([string]$path) {
    $tokens = $null; $errors = $null
    $ast = [Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw ('SOURCE_PARSE_FAILED:' + $path) }
    return $ast
}

$graphAst = Get-Parsed $graphSource

# --- the window policy must exist and be a named, testable decision ---------------
$policy = @($graphAst.FindAll({
    param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and
              $n.Name -ceq $policyName
}, $true))
$checks.Add([pscustomobject]@{ name = ('graph transport names its window policy (' + $policyName + ')'); passed = ($policy.Count -eq 1) })
$policyLabel = if ($checks[-1].passed) { 'PASS ' } else { 'FAIL ' }
Write-Host ($policyLabel + $checks[-1].name)
if ($policy.Count -ne 1) {
    Write-Host 'result=False; a hardcoded inline window cannot be asserted against'
    exit 1
}
$productionPolicy = [scriptblock]::Create($policy[0].Extent.Text)
. $productionPolicy

# --- the inline 15000 must be gone ------------------------------------------------
$inline = @($graphAst.FindAll({
    param($n) $n -is [Management.Automation.Language.CommandAst] -and
              $n.Extent.Text -match '\.Wait\(\s*15000\s*\)'
}, $true))
Check ($inline.Count -eq 0) 'no inline Wait(15000) survives in the graph transport'

# --- bounds -----------------------------------------------------------------------
$catalogWindow = Get-GraphResponseWindowMs 'catalog'
$authorGraphWindow = Get-GraphResponseWindowMs 'author-graph'
Check ($catalogWindow -ge (2 * $measuredWalkMs)) `
    ('catalog window is at least twice the measured walk (window=' + $catalogWindow + 'ms, walk=' + $measuredWalkMs + 'ms)')
Check ($catalogWindow -lt 60000) `
    ('catalog window stays below the 60s elevated_graph_call client timeout (window=' + $catalogWindow + 'ms)')
Check ($authorGraphWindow -ge (2 * $measuredWalkMs)) `
    ('author-graph gets the same order of window (window=' + $authorGraphWindow + 'ms)')
Check ($authorGraphWindow -lt 60000) `
    ('author-graph window stays below the 60s client timeout (window=' + $authorGraphWindow + 'ms)')

# --- the sibling transport's figure is the context this was derived from -----------
$callAst = Get-Parsed $callSource
$callSelectorAst = @($callAst.FindAll({
    param($n) $n -is [Management.Automation.Language.AssignmentStatementAst] -and
              $n.Left.Extent.Text -ceq '$responseTimeoutMs'
}, $true))
if ($callSelectorAst.Count -ne 1) { throw 'CALL_TIMEOUT_ASSIGNMENT_NOT_UNIQUE' }
$callSelector = [scriptblock]::Create($callSelectorAst[0].Extent.Text)
$Operation = 'catalog'; . $callSelector
Check ($responseTimeoutMs -eq 60000) 'call-bridge still grants catalog 60000ms (the correction this file was missing)'

# --- refusal semantics of a lost reply must not drift ------------------------------
$graphTry = @($graphAst.FindAll({
    param($n) $n -is [Management.Automation.Language.TryStatementAst] -and
              $n.Body.Extent.Text.Contains('$pipe.Connect(5000)')
}, $true))
if ($graphTry.Count -ne 1) { throw 'GRAPH_TRANSPORT_BLOCK_NOT_UNIQUE' }
$catchText = $graphTry[0].CatchClauses[0].Body.Extent.Text
Check ($catchText.Contains("outcomeUncertain=(`$stage -eq 'send')")) `
    'a lost reply stays uncertain: outcomeUncertain is still ($stage -eq send)'
Check ($catchText.Contains("'BRIDGE_TRANSPORT_FAILED'")) 'transport failure code unchanged'

# --- dynamic: drive the production pipe tail against a local fixture ---------------
Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.IO.Pipes;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
public sealed class GraphWindowFixture : IDisposable {
 public readonly NamedPipeServerStream Pipe;
 public Task Work; public string Request;
 public GraphWindowFixture(string name) {
  Pipe = new NamedPipeServerStream(name, PipeDirection.InOut, 1,
      PipeTransmissionMode.Byte, PipeOptions.Asynchronous);
 }
 public void Start(int delayMs, string reply) {
  Work = Task.Run((Action)(() => {
   try {
    Pipe.WaitForConnection();
    using (var reader = new StreamReader(Pipe, new UTF8Encoding(false), false, 1024, true))
    using (var writer = new StreamWriter(Pipe, new UTF8Encoding(false), 1024, true)) {
     Request = reader.ReadLine();
     Thread.Sleep(delayMs);
     if (reply != null) { writer.WriteLine(reply); writer.Flush(); }
    }
   } catch (Exception) { }
  }));
 }
 public void Dispose() { Pipe.Dispose(); }
}
'@

$bodyStatements = @($graphTry[0].Body.Statements)
$firstPipeStatement = @($bodyStatements | Where-Object {
    $_.Extent.Text.Contains('[IO.Pipes.NamedPipeClientStream]::new')
})[0]
if ($null -eq $firstPipeStatement) { throw 'GRAPH_TRANSPORT_TAIL_NOT_FOUND' }
$tailStatements = @($bodyStatements | Where-Object {
    $_.Extent.StartOffset -ge $firstPipeStatement.Extent.StartOffset
})
if ($tailStatements.Count -lt 4) { throw 'GRAPH_TRANSPORT_TAIL_TOO_SHORT' }
$tail = ($tailStatements | ForEach-Object { $_.Extent.Text }) -join [Environment]::NewLine

# The recorded verdict is produced by the PRODUCTION catch text, taken from the AST.
# The production catch EMITS its refusal as JSON (and exits, which is stripped here);
# it does not assign to a variable, so the emitted text is what the caller must read.
#
# Take the catch's STATEMENTS, never its whole Extent.Text: a StatementBlockAst extent
# includes its own braces, and interpolating `{ ... }` into `catch { ... }` makes the
# body a scriptblock LITERAL -- evaluated and emitted as an object instead of run. That
# silently turned this case into "the catch returned a ScriptBlockInfo" and was visible
# only in the recorded scenario, not as an error.
$catchBody = (@($graphTry[0].CatchClauses[0].Body.Statements |
    ForEach-Object { $_.Extent.Text }) -join [Environment]::NewLine) -replace '(?m)^\s*exit\s+2\s*$', ''
$harness = [scriptblock]::Create(@"
try {
$tail
    `$script:observed = @{ ok = `$true; code = `$null; stage = `$stage; outcomeUncertain = `$false; reply = `$taskRead.Result }
} catch {
$catchBody
}
"@)

function Run-Tail([string]$name, [int]$delay, [string]$reply) {
    $script:observed = $null
    $script:payload = $null
    $pipeName = 'mw-graph-window-' + [Guid]::NewGuid().ToString('N')
    $server = [GraphWindowFixture]::new($pipeName)
    $scope = [pscustomobject]@{ pipeName = $pipeName; nonce = 'offline-fixture-only' }
    $request = [pscustomobject]@{ op = 'catalog' }
    $line = '{"op":"catalog"}'
    $pipe = $null; $reader = $null; $writer = $null
    $stage = 'connect'; $taskRead = $null; $payload = $null
    $server.Start($delay, $reply)
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $failure = $null
    $emitted = $null
    try { $emitted = & $harness } catch { $failure = $_.Exception.Message }
    $watch.Stop()
    # The catch branch emits the production refusal as JSON; only the try branch sets
    # the variable directly.
    if ($null -eq $script:observed -and $emitted) {
        try { $script:observed = (($emitted | Where-Object { $_ -is [string] }) -join "`n") | ConvertFrom-Json }
        catch { $failure = 'VERDICT_NOT_PARSEABLE' }
    }
    [void]$server.Work.Wait(30000)
    $server.Dispose(); if ($pipe) { $pipe.Dispose() }
    return [pscustomobject]@{ name = $name; elapsedMs = $watch.ElapsedMilliseconds
        verdict = $script:observed; failure = $failure; emitted = $emitted }
}

# A reply slower than the measured walk must be read, not cut off.
$late = Run-Tail 'late-12s' 12000 '{"ok":true,"graphs":[{"id":1073741825}]}'
Check ($null -ne $late.verdict -and $late.verdict.ok -eq $true -and $late.elapsedMs -ge 11000) `
    ('a reply arriving after 12s is accepted under the production window (' + $late.elapsedMs + 'ms)')

# A server that STAYS CONNECTED AND SILENT must still refuse as uncertain. Holding the
# pipe open matters: a server that closes instead raises IOException, which is a
# different branch and would not exercise the timeout. The policy is stubbed short so
# the suite does not spend the production window proving a branch the static checks
# above already pin -- what is exercised here is the production TAIL's handling of the
# throw. The stub is removed from the production path by those static checks, which read
# the real function text out of the file's AST.
function Get-GraphResponseWindowMs([string]$Op) { return 2000 }
$silent = Run-Tail 'silent' 30000 $null
Check ($null -ne $silent.verdict -and $silent.verdict.ok -eq $false -and
       $silent.verdict.code -ceq 'BRIDGE_TRANSPORT_FAILED' -and
       $silent.verdict.stage -ceq 'send' -and $silent.verdict.outcomeUncertain -eq $true -and
       $silent.elapsedMs -ge 1800 -and $silent.elapsedMs -lt 20000) `
    ('a silent server still refuses as uncertain after the granted window (' + $silent.elapsedMs + 'ms)')

$report = [ordered]@{
    ok                = (@($checks | Where-Object { -not $_.passed }).Count -eq 0)
    observedUtc       = [DateTime]::UtcNow.ToString('o')
    host              = $PSVersionTable.PSVersion.ToString()
    graphSourceSha256 = (Get-FileHash -LiteralPath $graphSource -Algorithm SHA256).Hash.ToLowerInvariant()
    callSourceSha256  = (Get-FileHash -LiteralPath $callSource -Algorithm SHA256).Hash.ToLowerInvariant()
    windows           = [ordered]@{ catalog = $catalogWindow; authorGraph = $authorGraphWindow
                                    callBridgeCatalog = 60000; measuredWalkMs = $measuredWalkMs }
    checks            = $checks
    scenarios         = @($late, $silent)
    liveContact       = $false
    note              = 'AST of the production transports plus local fixture pipes. No game, editor, process or DLL touched.'
}
$evidence = Join-Path $root '.runtime/verification/game-b-nodes-20261009'
[IO.Directory]::CreateDirectory($evidence) | Out-Null
[IO.File]::WriteAllText((Join-Path $evidence 'graph-transport-window-result.json'),
    ($report | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
Write-Host ('result=' + $report.ok + '; ' + $checks.Count + ' checks')

if (-not $report.ok) { exit 1 }
