param([Parameter(Mandatory=$true)][Guid]$RunId)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$runDir = Join-Path $projectRoot ('.runtime/editor-bridge/runs/' + $RunId.ToString('D'))
$settingsPath = Join-Path $runDir 'bridge-settings.json'
$resultPath = Join-Path $runDir 'loader-result.json'
. ([IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'compatibility-guard.ps1')))
try {
    $scope = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
    $frozen = Get-Content -LiteralPath (Join-Path $runDir 'frozen.json') -Raw | ConvertFrom-Json
    $pinPath = Join-Path $runDir 'compatibility.json'
    if (-not (Test-Path -LiteralPath $pinPath -PathType Leaf)) { throw 'COMPATIBILITY_PIN_INVALID:missing-file' }
    $pin = Get-Content -LiteralPath $pinPath -Raw | ConvertFrom-Json
    if ([DateTimeOffset]::UtcNow -ge [DateTimeOffset]::Parse($scope.expiresUtc)) { throw 'SCOPE_EXPIRED' }
    $proc = Get-Process -Id ([int]$scope.pid)
    $startTicks = $proc.StartTime.ToUniversalTime().Ticks
    if ($startTicks -ne [long]$scope.startUtcTicks) { throw 'START_TIME_MISMATCH' }
    if ($startTicks -le 0) { throw 'START_TICKS_MISSING' }
    try { $imagePath = $proc.MainModule.FileName } catch { throw 'TARGET_IMAGE_UNREADABLE:' + $proc.ProcessName }
    # Same identity policy as new-scope: name, exact image path, positive start ticks.
    $null = Assert-MiliastraTargetIdentity -ProjectRoot $projectRoot -ProcessName $proc.ProcessName `
        -ImagePath $imagePath -StartUtcTicks $startTicks
    if ($imagePath -ine $scope.expectedExe) { throw 'TARGET_NOT_ALLOWED:scope-image-path' }
    if ($proc.ProcessName -ne $pin.kind) { throw 'TARGET_NOT_ALLOWED:pin-kind' }
    # Re-checked here, not only at scope creation: an editor update that lands between
    # the two steps must stop the loader. This runs BEFORE loader.claim, so a refused
    # version cannot consume the single injection attempt for this scope.
    $null = Assert-MiliastraCompatibilityPin -Pin $pin -ProjectRoot $projectRoot -ProcessName $proc.ProcessName -ImagePath $imagePath -StartUtcTicks $startTicks
    $dll = Join-Path $projectRoot 'tools/editor-bridge/ManagedBridge/bin/Release/net8.0-windows/Miliastra.EditorBridge.Net8R301.dll'
    $launcher = Join-Path $projectRoot '.runtime/editor-bridge/vendor/snoop-6.1.1/Snoop.InjectorLauncher.x64.exe'
    $native = Join-Path $projectRoot '.runtime/editor-bridge/vendor/snoop-6.1.1/Snoop.GenericInjector.x64.dll'
    $bootstrap = Join-Path (Split-Path $dll) 'Miliastra.Bootstrap.Net8R301.dll'
    foreach ($item in @(@($dll,$frozen.bridge),@($bootstrap,$frozen.bootstrap),@($launcher,$frozen.launcher),@($native,$frozen.native))) {
        if ((Get-FileHash -LiteralPath $item[0] -Algorithm SHA256).Hash -ne $item[1]) { throw 'ARTIFACT_HASH_MISMATCH' }
    }
    if ((Get-AuthenticodeSignature -LiteralPath $launcher).Status -ne 'Valid' -or (Get-AuthenticodeSignature -LiteralPath $native).Status -ne 'Valid') { throw 'UPSTREAM_SIGNATURE_INVALID' }
    # A single launch attempt per scope. Do not remove this claim after failures.
    $claim = [IO.File]::Open((Join-Path $runDir 'loader.claim'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    $claim.Dispose()
    & $launcher --targetPID ([string]$scope.pid) --assembly $bootstrap --className 'Miliastra.Bootstrap.Entry' --methodName 'Start' --settingsFile $settingsPath 1> (Join-Path $runDir 'loader.stdout.txt') 2> (Join-Path $runDir 'loader.stderr.txt')
    @{phase='loader-returned';exitCode=$LASTEXITCODE;pid=$proc.Id;startUtcTicks=[string]$scope.startUtcTicks;readyFilePresent=(Test-Path (Join-Path $runDir 'bridge-ready.json'));compatibilityVerdict=$pin.verdict} | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding utf8
} catch {
    @{phase='loader-refused-or-failed';error=$_.Exception.Message} | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding utf8
    exit 2
}


