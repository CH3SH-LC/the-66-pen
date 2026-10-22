# Offline only: extract pure validation functions and the call dispatch clause by AST.
# The actual runner, scope creation, call-bridge and any resident helper never run.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$runner = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../elevated-runner.ps1'))
$tokens = $null; $parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($runner,[ref]$tokens,[ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
$names = @('Assert-RequestIdsScope','Get-ValidatedCallArguments')
foreach ($name in $names) {
  $fn = $ast.Find({ param($a) $a -is [Management.Automation.Language.FunctionDefinitionAst] -and $a.Name -ceq $name },$true)
  if ($null -eq $fn) { throw "Missing function $name" }
  . ([scriptblock]::Create($fn.Extent.Text))
}
$script:passed=0
function Check([bool]$ok,[string]$name) { if(-not $ok){throw "FAILED:$name"}; $script:passed++ }
function Refuses([scriptblock]$action,[string]$prefix,[string]$name) {
  $caught=$null
  try { & $action | Out-Null } catch { $caught=$_.Exception.Message }
  Check ($null -ne $caught -and $caught.StartsWith($prefix)) "$name / $caught"
}
$run='11111111-1111-1111-1111-111111111111'
function Request([object]$ids) { [pscustomobject]@{kind='call';runId=$run;op='node-definitions';ids=$ids} }
$valid = ('{"kind":"call","runId":"'+$run+'","op":"node-definitions","ids":[71,1,4294967295]}') | ConvertFrom-Json
Assert-RequestIdsScope $valid
$arguments=Get-ValidatedCallArguments $valid
Check ($arguments['Ids'] -is [uint32[]]) 'typed uint32 array'
Check (($arguments['Ids'] -join ',') -eq '71,1,4294967295') 'JSON integer order and uint32 max'
Check ($arguments.Count -eq 3 -and $arguments.ContainsKey('RunId') -and $arguments.ContainsKey('Operation')) 'only fixed splat keys'
$one=Get-ValidatedCallArguments (Request ([object[]]@(1)))
Check ($one.Ids.Count -eq 1 -and $one.Ids[0] -eq 1) 'single-item array preserved'
$max=Get-ValidatedCallArguments (Request ([object[]]@(1)*64))
Check ($max.Ids.Count -eq 64) '64 IDs allowed'
$ping=Get-ValidatedCallArguments ([pscustomobject]@{kind='call';runId=$run;op='ping'})
Check ($ping.Count -eq 2 -and -not $ping.ContainsKey('Ids')) 'ordinary call no added payload'
Refuses {Get-ValidatedCallArguments ([pscustomobject]@{kind='call';runId=$run;op='node-definitions'})} 'NODE_QUERY_IDS_REQUIRED' 'missing IDs'
foreach($json in @('null','[]','0','71','"71"','true','{}','[0]','[-1]','[4294967296]','[1.0]','[1e0]','[true]','[false]','[null]','["71"]','[[71]]','[{"id":71}]')) {
  $requestJson='{"kind":"call","runId":"'+$run+'","op":"node-definitions","ids":'+$json+'}'
  $bad=$requestJson | ConvertFrom-Json
  Refuses {Get-ValidatedCallArguments $bad} 'NODE_QUERY_IDS_INVALID' "reject $json"
}
Refuses {Get-ValidatedCallArguments (Request ([object[]]@(1)*65))} 'NODE_QUERY_IDS_INVALID' '65 IDs rejected'
foreach($value in @([decimal]1,[double]1,[float]1,[uint64]::MaxValue)) {
  Refuses {Get-ValidatedCallArguments (Request ([object[]]@($value)))} 'NODE_QUERY_IDS_INVALID' ('reject CLR '+$value.GetType().Name)
}
foreach($ids in @($null,@(),@(71))) {
  Refuses {Get-ValidatedCallArguments ([pscustomobject]@{kind='call';runId=$run;op='ping';ids=$ids})} 'IDS_NOT_ALLOWED' 'other op presence rejected'
}
foreach($kind in @('status','load','fs','CALL')) {
  Refuses {Assert-RequestIdsScope ([pscustomobject]@{kind=$kind;ids=@(71)})} 'IDS_NOT_ALLOWED' "ids kind $kind"
}
Refuses {Assert-RequestIdsScope ([pscustomobject]@{kind='fs';IDS=$null})} 'IDS_NOT_ALLOWED' 'case variant ids on fs'
Refuses {Get-ValidatedCallArguments ([pscustomobject]@{kind='call';runId=$run;op='NODE-DEFINITIONS'})} 'CALL_REQUEST_INVALID' 'case variant operation rejected'
Refuses {Get-ValidatedCallArguments ([pscustomobject]@{kind='call';runId=$run;op='node-definitions';Ids=@(71)})} 'CALL_FIELD_NOT_ALLOWED' 'case variant field rejected'
Refuses {Get-ValidatedCallArguments ([pscustomobject]@{kind='call';runId=$run;op='node-definitions';ids=@(71);payload=@{command='x'}})} 'CALL_FIELD_NOT_ALLOWED' 'arbitrary payload rejected'
Refuses {Get-ValidatedCallArguments ([pscustomobject]@{kind='call';runId=$run;op='node-definitions';ids=@(71);TimeoutMs=1})} 'CALL_FIELD_NOT_ALLOWED' 'arbitrary splat rejected'
Refuses {Get-ValidatedCallArguments ([pscustomobject]@{kind='call';runId='invalid';op='node-definitions';ids=@(71)})} 'BAD_RUN_ID' 'bad run ID'
Refuses {Get-ValidatedCallArguments ([pscustomobject]@{kind='call';runId=$run;op=@('node-definitions');ids=@(71)})} 'CALL_REQUEST_INVALID' 'op array'

$variant=Get-ValidatedCallArguments ([pscustomobject]@{kind='call';runId=$run;op='node-definition-variants';ids=@(200301,300005)})
Check (($variant.Ids -join ',') -eq '200301,300005') 'variant query ids forwarded'
Refuses {Get-ValidatedCallArguments ([pscustomobject]@{kind='call';runId=$run;op='NODE-DEFINITION-VARIANTS';ids=@(1)})} 'CALL_REQUEST_INVALID' 'variant case rejected'
Refuses {Get-ValidatedCallArguments ([pscustomobject]@{kind='call';runId=$run;op='node-definition-variants'})} 'NODE_QUERY_IDS_REQUIRED' 'variant missing ids'
Refuses {Get-ValidatedCallArguments ([pscustomobject]@{kind='call';runId=$run;op='node-definition-variants';ids=@(0)})} 'NODE_QUERY_IDS_INVALID' 'variant zero rejected'
Refuses {Get-ValidatedCallArguments ([pscustomobject]@{kind='call';runId=$run;op='node-definition-variants';ids=([object[]]@(1)*65)})} 'NODE_QUERY_IDS_INVALID' 'variant 65 rejected'

# Execute the real call clause in isolation with a recording stub in place of call-bridge.
$clause=$null
foreach($statement in $ast.FindAll({param($a) $a -is [Management.Automation.Language.IfStatementAst]},$true)) {
  foreach($item in $statement.Clauses) {
    if($item.Item1.Extent.Text -eq '$kind -eq ''call''') { $clause=$item.Item2 }
  }
}
if($null -eq $clause){throw 'No actual call clause found'}
$bodyText=$clause.Extent.Text
$dispatch=[scriptblock]::Create($bodyText.Substring(1,$bodyText.Length-2))
function Get-AllowedOps { @('node-definitions','ping') }
function Write-Log([string]$message) { }
$testRoot=Join-Path ([IO.Path]::GetTempPath()) ('node-query-offline-'+[Guid]::NewGuid().ToString('N'))
$runsRoot=Join-Path $testRoot 'runs'
New-Item -ItemType Directory -Path (Join-Path $runsRoot $run) -Force | Out-Null
$responsePath=Join-Path $testRoot 'response.json'
$script:stubCalls=0
$callScript={param([Guid]$RunId,[string]$Operation,[uint32[]]$Ids)
  $script:stubCalls++
  $script:lastCall=@{RunId=$RunId.ToString();Operation=$Operation;Ids=$Ids}
  [ordered]@{ok=$true;ids=$Ids} | ConvertTo-Json -Compress
}
$body=$valid
& $dispatch
Check ($script:stubCalls -eq 1 -and ($script:lastCall.Ids -join ',') -eq '71,1,4294967295') 'actual runner clause forwards IDs into stub'
Check ((Get-Content -LiteralPath $responsePath -Raw | ConvertFrom-Json).ok -eq $true) 'actual clause stores reply'
$body=[pscustomobject]@{kind='call';runId=$run;op='node-definitions'}
Refuses {& $dispatch} 'NODE_QUERY_IDS_REQUIRED' 'dispatch rejects missing IDs before stub'
Check ($script:stubCalls -eq 1) 'invalid request did not invoke stub'
$body=[pscustomobject]@{kind='call';runId=$run;op='not-allowed'}
Refuses {& $dispatch} 'OP_NOT_ALLOWED' 'existing whitelist preserved'
Check ($script:stubCalls -eq 1) 'unknown op did not invoke stub'
# This directory is uniquely generated beneath Temp; verify that boundary before cleanup.
$resolved=[IO.Path]::GetFullPath($testRoot)
$tempBoundary=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')+'\'
if(-not $resolved.StartsWith($tempBoundary,[StringComparison]::OrdinalIgnoreCase)){throw 'UNSAFE_TEST_CLEANUP'}
Remove-Item -LiteralPath $resolved -Recurse -Force
[ordered]@{ok=$true;passed=$script:passed;bridgeInvocations=0;stubInvocations=$script:stubCalls;runtime=$PSVersionTable.PSVersion.ToString();scope='AST-extracted pure validation and real call clause, recording stub only'} | ConvertTo-Json -Compress
