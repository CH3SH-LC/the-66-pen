param()
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$build=Join-Path $root ('.runtime/editor-bridge/fixture-builds/'+[Guid]::NewGuid().ToString('N'))
$dotnet='C:\Program Files\dotnet\dotnet.exe'
& $dotnet build (Join-Path $PSScriptRoot 'ManagedBridge/Miliastra.EditorBridge.csproj') -c Release -o $build --nologo
if($LASTEXITCODE -ne 0){throw 'BUILD_FAILED'}
$dll=Join-Path $build 'Miliastra.EditorBridge.Net8R300.dll'
$hostExe=Join-Path $PSScriptRoot 'TestHost/bin/Release/net8.0-windows/TestHost.exe'
$launcher=Join-Path $root '.runtime/editor-bridge/vendor/snoop-6.1.1/Snoop.InjectorLauncher.x64.exe'
if((Get-AuthenticodeSignature $launcher).Status -ne 'Valid'){throw 'INVALID_LOADER_SIGNATURE'}
$fixture=Start-Process $hostExe -ArgumentList @('--bridge',('"'+$dll+'"'),'--no-autoload','--timeout','90') -WindowStyle Hidden -PassThru
$scopeInfo=(& (Join-Path $PSScriptRoot 'new-scope.ps1') -TargetPid $fixture.Id | ConvertFrom-Json)
$runDir=Join-Path $root ('.runtime/editor-bridge/runs/'+$scopeInfo.runId)
$settings=Join-Path $runDir 'bridge-settings.json'
# Dedicated project-owned test process only; never select an editor or game PID here.
if($fixture.ProcessName -ne 'TestHost' -or $fixture.MainModule.FileName -ine $hostExe){throw 'FIXTURE_IDENTITY_MISMATCH'}
& $launcher --targetPID $fixture.Id --assembly $dll --className Miliastra.EditorBridge.Entry --methodName Start --settingsFile $settings *> (Join-Path $runDir 'fixture-loader.txt')
if($LASTEXITCODE -ne 0){throw 'FIXTURE_LOAD_FAILED'}
$scope=Get-Content $settings -Raw | ConvertFrom-Json
function Send-TestRequest([string]$operation,[string]$nonce){
    $pipe=[IO.Pipes.NamedPipeClientStream]::new('.',$scope.pipeName,[IO.Pipes.PipeDirection]::InOut,[IO.Pipes.PipeOptions]::Asynchronous)
    try{
        $pipe.Connect(3000)
        $writer=[IO.StreamWriter]::new($pipe,[Text.UTF8Encoding]::new($false),1024,$true)
        $reader=[IO.StreamReader]::new($pipe,[Text.UTF8Encoding]::new($false),$false,1024,$true)
        $writer.AutoFlush=$true
        $writer.WriteLine((@{id='fixture';op=$operation;nonce=$nonce}|ConvertTo-Json -Compress))
        $read=$reader.ReadLineAsync()
        if(-not $read.Wait(3000)){throw 'RESPONSE_TIMEOUT_NOT_PROOF_OF_NO_EFFECT'}
        return ($read.Result|ConvertFrom-Json)
    }finally{if($reader){$reader.Dispose()};if($writer){$writer.Dispose()};$pipe.Dispose()}
}
$bad=Send-TestRequest 'ping' ('0'*64)
if($bad.ok -ne $false -or $bad.error -ne 'nonce_mismatch'){throw 'BAD_NONCE_ACCEPTED'}
$ping=Send-TestRequest 'ping' $scope.nonce
if(-not $ping.ok -or $ping.pid -ne $fixture.Id -or $ping.framework -notlike '.NET 8.*'){throw 'PING_IDENTITY_FAILED'}
$unknown=Send-TestRequest 'not-allowed' $scope.nonce
if($unknown.ok -ne $false -or $unknown.error -ne 'unknown_op'){throw 'UNKNOWN_OPERATION_ACCEPTED'}
$catalog=Send-TestRequest 'catalog' $scope.nonce
if($catalog.ok -ne $false -or $catalog.error -notlike 'adapter:*'){throw 'FIXTURE_FALSE_CATALOG_SUCCESS'}
$stop=Send-TestRequest 'stop' $scope.nonce
if(-not $stop.stopped -or $stop.hostProcessTerminated){throw 'STOP_RESPONSE_FAILED'}
$probe=[IO.Pipes.NamedPipeClientStream]::new('.',$scope.pipeName,[IO.Pipes.PipeDirection]::InOut)
$closed=$false
try{$probe.Connect(700)}catch [TimeoutException]{$closed=$true}finally{$probe.Dispose()}
if(-not $closed){throw 'STOP_LISTENER_STILL_ACTIVE'}
$alive=Get-Process -Id $fixture.Id
if(-not $alive.Responding){throw 'FIXTURE_NOT_RESPONDING'}
@{runId=$scopeInfo.runId;framework=$ping.framework;badNonceRejected=$true;unknownOperationRejected=$true;missingEditorFails=$true;pipeClosed=$closed;hostResponding=$alive.Responding;bridgeSha256=(Get-FileHash $dll -Algorithm SHA256).Hash}|ConvertTo-Json | Tee-Object -FilePath (Join-Path $runDir 'fixture-verification.json')
