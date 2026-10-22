param([Parameter(Mandatory=$true)][int]$TargetPid)
$ErrorActionPreference='Stop'
$projectRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
. ([IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'compatibility-guard.ps1')))

$proc=Get-Process -Id $TargetPid
if($proc.ProcessName -notin $script:MiliastraCompatibility.AllowedProcessNames){throw 'TARGET_NOT_ALLOWED:process-name:'+$proc.ProcessName}
$startTicks=$proc.StartTime.ToUniversalTime().Ticks
if($startTicks -le 0){throw 'START_TICKS_MISSING'}
try{$imagePath=$proc.MainModule.FileName}catch{throw 'TARGET_IMAGE_UNREADABLE:'+$proc.ProcessName}

# Version gate, before ANY run-directory or scope artifact exists. An updated or missing
# editor assembly is refused here with EDITOR_VERSION_UNSUPPORTED / EDITOR_DLL_MISSING,
# so no scope is ever minted against an editor build the Adapter was not adapted to.
# TestHost at its project-owned exact path does not load the editor assembly and is
# exempt; its identity is still pinned.
$pin=Get-MiliastraCompatibilityPin -ProjectRoot $projectRoot -ProcessName $proc.ProcessName -ImagePath $imagePath -StartUtcTicks $startTicks

$run=[Guid]::NewGuid().ToString('D')
$runDir=Join-Path $projectRoot ('.runtime/editor-bridge/runs/'+$run)
New-Item -ItemType Directory -Path $runDir | Out-Null
$nonceBytes=New-Object byte[] 32
$rng=[Security.Cryptography.RandomNumberGenerator]::Create();$rng.GetBytes($nonceBytes);$rng.Dispose()
$nonce=([BitConverter]::ToString($nonceBytes)).Replace('-','')
# bridge-settings.json keeps its fixed six-member schema: the bridge parses it strictly
# and rejects unknown members, so the compatibility pin goes in its own file below.
$scope=@{pid=$TargetPid;startUtcTicks=[string]$startTicks;nonce=$nonce;pipeName=('miliastra-bridge-'+$run);expiresUtc=[DateTimeOffset]::UtcNow.AddMinutes(60).ToString('o');expectedExe=$pin.expectedImagePath}
$utf8=[Text.UTF8Encoding]::new($false)
[IO.File]::WriteAllText((Join-Path $runDir 'bridge-settings.json'),($scope|ConvertTo-Json),$utf8)
$frozen=@{
 bootstrap=(Get-FileHash (Join-Path $projectRoot 'tools/editor-bridge/ManagedBridge/bin/Release/net8.0-windows/Miliastra.Bootstrap.Net8R301.dll') -Algorithm SHA256).Hash
 bridge=(Get-FileHash (Join-Path $projectRoot 'tools/editor-bridge/ManagedBridge/bin/Release/net8.0-windows/Miliastra.EditorBridge.Net8R301.dll') -Algorithm SHA256).Hash
 launcher=(Get-FileHash (Join-Path $projectRoot '.runtime/editor-bridge/vendor/snoop-6.1.1/Snoop.InjectorLauncher.x64.exe') -Algorithm SHA256).Hash
 native=(Get-FileHash (Join-Path $projectRoot '.runtime/editor-bridge/vendor/snoop-6.1.1/Snoop.GenericInjector.x64.dll') -Algorithm SHA256).Hash
}
[IO.File]::WriteAllText((Join-Path $runDir 'frozen.json'),($frozen|ConvertTo-Json),$utf8)
# The pin is re-verified by load-bridge.ps1 before the injector is invoked.
[IO.File]::WriteAllText((Join-Path $runDir 'compatibility.json'),($pin|ConvertTo-Json),$utf8)
@{runId=$run;pid=$TargetPid;expiresUtc=$scope.expiresUtc;compatibilityVerdict=$pin.verdict;editorDllGateApplied=$pin.editorDllGateApplied} | ConvertTo-Json


