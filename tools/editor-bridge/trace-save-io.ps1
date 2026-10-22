param([ValidatePattern('^save-io[-a-z0-9]*$')][string]$RunName='save-io')
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$out=Join-Path $root ('.runtime/verification/realtime-injection-20260920/'+$RunName)
$profile=Join-Path $out 'save-io.wprp'
$instance='Miliastra-'+$RunName
if(Test-Path (Join-Path $out 'save-io.etl')){throw 'TRACE_ALREADY_EXISTS'}
$save='C:/Users/PUBLIC_USER/AppData/LocalLow/miHoYo/原神/BeyondLocal/100000001/Beyond_Local_Save_Level/1073741832.gil'
$baseline=(Get-Item -LiteralPath $save).LastWriteTimeUtc

$started=$false
try {
 & wpr -start ($profile+'!SaveIO') -filemode -recordtempto $out -instancename $instance 2>&1 | Out-File (Join-Path $out 'start.log')
 if($LASTEXITCODE -ne 0){throw "WPR_START_FAILED_$LASTEXITCODE"}
 $started=$true
 [DateTimeOffset]::UtcNow.ToString('o') | Set-Content (Join-Path $out 'ready.txt')
 $deadline=[DateTimeOffset]::UtcNow.AddSeconds(180)
 while([DateTimeOffset]::UtcNow -lt $deadline){
  Start-Sleep -Milliseconds 500
  if((Get-Item -LiteralPath $save).LastWriteTimeUtc -gt $baseline){
   [DateTimeOffset]::UtcNow.ToString('o') | Set-Content (Join-Path $out 'save-detected.txt')
   Start-Sleep -Seconds 3
   break
  }
 }
} catch { $_ | Out-File (Join-Path $out 'error.txt') } finally {
 if($started){
  & wpr -stop (Join-Path $out 'save-io.etl') 'Manual experimental level save' -skipPdbGen -instancename $instance 2>&1 | Out-File (Join-Path $out 'stop.log')
  if($LASTEXITCODE -ne 0){& wpr -cancel -instancename $instance 2>&1 | Out-File (Join-Path $out 'cancel.log')}
 }
 [DateTimeOffset]::UtcNow.ToString('o') | Set-Content (Join-Path $out 'finished.txt')
}
