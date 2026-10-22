# Execute only the production reply publisher, never start the helper or game.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot '../elevated-runner.ps1'),[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Runner syntax errors'}
$fn=@($ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq 'Write-JsonFile'},$true))
if($fn.Count -ne 1){throw 'Reply publisher must be unique'}
. ([scriptblock]::Create($fn[0].Extent.Text))
$fixture=Join-Path $projectRoot ('.runtime/map-foundation-20261015/integration/heartbeat-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $fixture | Out-Null
$heartbeatPath=Join-Path $fixture 'runner.heartbeat'
$utf8NoBom=[Text.UTF8Encoding]::new($false)
$handled=10
$responsePath=Join-Path $fixture 'response.json'
[IO.File]::WriteAllText($heartbeatPath,([DateTime]::UtcNow.AddMinutes(-2).ToString('o')+" pid=$PID handled=9"),$utf8NoBom)
$reply=[pscustomobject]@{ok=$true;cleanupVerified=$true;outcomeUncertain=$false}
# Serialization itself observes the heartbeat, proving the write happened before
# any completed response can be read by the next caller.
$reply | Add-Member -MemberType ScriptProperty -Name heartbeatFreshAtSerialization -Value {
  $text=[IO.File]::ReadAllText($heartbeatPath)
  $stamp=[DateTimeOffset]::Parse(($text -split ' ')[0])
  if(([DateTimeOffset]::UtcNow-$stamp).TotalSeconds -gt 5){throw 'Stale heartbeat published with reply'}
  return $true
}
Write-JsonFile $responsePath $reply
$saved=Get-Content -LiteralPath $responsePath -Raw | ConvertFrom-Json
if(-not $saved.ok -or -not $saved.heartbeatFreshAtSerialization){throw 'Serial continuation remains stale'}
if([IO.File]::ReadAllText($heartbeatPath) -notmatch " pid=$PID handled=10$"){throw 'Heartbeat identity changed'}
$uncertain=Join-Path $fixture 'uncertain.json'
Write-JsonFile $uncertain @{ok=$false;outcomeUncertain=$true;safeToRelease=$false}
$saved=Get-Content -LiteralPath $uncertain -Raw | ConvertFrom-Json
if($saved.ok -or -not $saved.outcomeUncertain -or $saved.safeToRelease){throw 'Outcome fields changed'}
$heartbeatPath=$fixture
$failedResponse=Join-Path $fixture 'must-not-publish.json'
$refused=$false
try{Write-JsonFile $failedResponse @{ok=$true}}catch{$refused=$true}
if(-not $refused -or (Test-Path -LiteralPath $failedResponse)){throw 'Heartbeat failure published a success'}
@{ok=$true;checks=4;fixture=$fixture;scope='offline-real-reply-publisher'} | ConvertTo-Json -Compress
