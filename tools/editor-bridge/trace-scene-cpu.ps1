param([ValidateSet('cpu-baseline','cpu-move','cpu-numeric','cpu-focus','cpu-focus-2','cpu-create-drag','cpu-crud-create-20260921')][string]$RunName='cpu-baseline')
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$out=Join-Path $root ('.runtime/verification/realtime-injection-20260920/'+$RunName)
New-Item -ItemType Directory -Path $out -Force | Out-Null
if(Test-Path (Join-Path $out 'cpu.etl')){throw 'TRACE_ALREADY_EXISTS'}
$profile=Join-Path $out 'cpu.wprp'
@'
<?xml version="1.0" encoding="utf-8"?>
<WindowsPerformanceRecorder Version="1.0" Author="Miliastra local research"><Profiles>
<SystemCollector Id="SC" Name="MiliastraCPU"><BufferSize Value="64"/><Buffers Value="256"/></SystemCollector>
<SystemProvider Id="SP"><Keywords><Keyword Value="ProcessThread"/><Keyword Value="Loader"/><Keyword Value="SampledProfile"/></Keywords><Stacks><Stack Value="SampledProfile"/></Stacks></SystemProvider>
<Profile Id="SceneCPU.Verbose.File" Name="SceneCPU" Description="Bounded scene CPU stacks" LoggingMode="File" DetailLevel="Verbose"><Collectors><SystemCollectorId Value="SC"><SystemProviderId Value="SP"/></SystemCollectorId></Collectors></Profile>
</Profiles></WindowsPerformanceRecorder>
'@ | Set-Content -LiteralPath $profile -Encoding UTF8
$instance='Miliastra-'+$RunName
$started=$false
try {
 & wpr -start ($profile+'!SceneCPU') -filemode -recordtempto $out -instancename $instance 2>&1 | Out-File (Join-Path $out 'start.log')
 if($LASTEXITCODE -ne 0){throw "WPR_START_FAILED_$LASTEXITCODE"}
 $started=$true
 [DateTimeOffset]::UtcNow.ToString('o') | Set-Content (Join-Path $out 'ready.txt')
 $duration=12
 if($RunName -ne 'cpu-baseline'){$duration=180}
 if($RunName -like 'cpu-focus*'){$duration=30}
 $deadline=[DateTimeOffset]::UtcNow.AddSeconds($duration)
 while([DateTimeOffset]::UtcNow -lt $deadline){
  Start-Sleep -Milliseconds 500
  if(Test-Path (Join-Path $out 'stop-requested.txt')){break}
 }
} catch { $_ | Out-File (Join-Path $out 'error.txt') } finally {
 if($started){
  [DateTimeOffset]::UtcNow.ToString('o') | Set-Content (Join-Path $out 'stop-began.txt')
  & wpr -stop (Join-Path $out 'cpu.etl') 'Experimental scene CPU observation' -skipPdbGen -instancename $instance 2>&1 | Out-File (Join-Path $out 'stop.log')
  if($LASTEXITCODE -ne 0){& wpr -cancel -instancename $instance 2>&1 | Out-File (Join-Path $out 'cancel.log')}
 }
 [DateTimeOffset]::UtcNow.ToString('o') | Set-Content (Join-Path $out 'finished.txt')
}
