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

# Dedicated project-owned test process. No administrator prompt is involved anywhere in
# this file: TestHost runs at the caller's own integrity level, which is exactly why it
# can validate the bridge contract without touching the editor or the game.
$fixture=Start-Process $hostExe -ArgumentList @('--bridge',('"'+$dll+'"'),'--no-autoload','--timeout','120') -WindowStyle Hidden -PassThru
$scopeInfo=(& (Join-Path $PSScriptRoot 'new-scope.ps1') -TargetPid $fixture.Id | ConvertFrom-Json)
$runDir=Join-Path $root ('.runtime/editor-bridge/runs/'+$scopeInfo.runId)
$settings=Join-Path $runDir 'bridge-settings.json'
if($fixture.ProcessName -ne 'TestHost' -or $fixture.MainModule.FileName -ine $hostExe){throw 'FIXTURE_IDENTITY_MISMATCH'}
& $launcher --targetPID $fixture.Id --assembly $dll --className Miliastra.EditorBridge.Entry --methodName Start --settingsFile $settings *> (Join-Path $runDir 'fixture-loader.txt')
if($LASTEXITCODE -ne 0){throw 'FIXTURE_LOAD_FAILED'}
$scope=Get-Content $settings -Raw | ConvertFrom-Json

function Send-Body([hashtable]$body,[string]$nonce){
    $payload=$body.Clone(); $payload['nonce']=$nonce
    $pipe=[IO.Pipes.NamedPipeClientStream]::new('.',$scope.pipeName,[IO.Pipes.PipeDirection]::InOut,[IO.Pipes.PipeOptions]::Asynchronous)
    try{
        $pipe.Connect(3000)
        $writer=[IO.StreamWriter]::new($pipe,[Text.UTF8Encoding]::new($false),1024,$true)
        $reader=[IO.StreamReader]::new($pipe,[Text.UTF8Encoding]::new($false),$false,1024,$true)
        $writer.AutoFlush=$true
        $writer.WriteLine(($payload|ConvertTo-Json -Compress -Depth 6))
        $read=$reader.ReadLineAsync()
        if(-not $read.Wait(5000)){throw 'RESPONSE_TIMEOUT_NOT_PROOF_OF_NO_EFFECT'}
        return ($read.Result|ConvertFrom-Json)
    }finally{if($reader){$reader.Dispose()};if($writer){$writer.Dispose()};$pipe.Dispose()}
}
function Send-Op([string]$operation,[string]$nonce){ return Send-Body @{id='fixture';op=$operation} $nonce }

$checks=[ordered]@{}
try{
    $bad=Send-Body @{id='fixture';op='ping'} ('0'*64)
    $checks['badNonceRejected']=($bad.ok -eq $false -and $bad.error -eq 'nonce_mismatch')

    $ping=Send-Op 'ping' $scope.nonce
    $checks['pingIdentity']=($ping.ok -and $ping.pid -eq $fixture.Id)

    $unknown=Send-Op 'definitely-not-an-op' $scope.nonce
    $checks['unknownOpStillRejected']=($unknown.ok -eq $false -and $unknown.error -eq 'unknown_op')

    # Registered-but-unrunnable is the expected fixture outcome for every editor operation:
    # the adapter must answer with adapter:*, never unknown_op. That distinction is what
    # proves the operation reached the adapter rather than falling off the whitelist.
    foreach($op in @('node-definitions','create-gameloop-graph','build-gameloop-graph',
                     'export-gameloop-graph','bind-gameloop-graph','repair-gameloop-score-order',
                     'repair-gameloop-settlement-status',
                     'unbind-gameloop-graph','build-gameloop-variant-no-scoreboard',
                     'build-gameloop-variant-core','bind-gameloop-variant-no-scoreboard',
                     'bind-gameloop-variant-core')){
        $r=Send-Op $op $scope.nonce
        $checks["registered:$op"]=($r.ok -eq $false -and $r.error -like 'adapter:*')
    }

    # Boundary behaviour of the new parameter reader. Each of these must be refused by the
    # adapter, and each must be refused for its own stated reason.
    $empty=Send-Body @{id='fixture';op='node-definitions';ids=@()} $scope.nonce
    $checks['emptyIdListRefused']=($empty.error -like '*NODE_QUERY_EMPTY*')
    $tooMany=Send-Body @{id='fixture';op='node-definitions';ids=(1..70)} $scope.nonce
    $checks['oversizeIdListRefused']=($tooMany.error -like '*NODE_QUERY_TOO_LARGE*')
    $malformed=Send-Body @{id='fixture';op='node-definitions';ids=@('not-a-number')} $scope.nonce
    $checks['malformedIdListRefused']=($malformed.error -like '*NODE_QUERY_EMPTY*')
    $wrongKind=Send-Body @{id='fixture';op='node-definitions';ids='77'} $scope.nonce
    $checks['nonArrayIdsRefused']=($wrongKind.error -like '*NODE_QUERY_EMPTY*')

    $stop=Send-Op 'stop' $scope.nonce
    $checks['stopClean']=($stop.stopped -and -not $stop.hostProcessTerminated)

    $alive=Get-Process -Id $fixture.Id
    $checks['hostStillResponding']=$alive.Responding
}finally{
    try{ if(-not (Get-Process -Id $fixture.Id -ErrorAction SilentlyContinue)){} }catch{}
}
$failed=@($checks.Keys | Where-Object { -not $checks[$_] })
$result=[ordered]@{ok=($failed.Count -eq 0);runId=$scopeInfo.runId;checks=$checks;failed=$failed;
    bridgeSha256=(Get-FileHash $dll -Algorithm SHA256).Hash;runtimeVerified=$false;
    note='Fixture only: proves the bridge contract and the new operations are registered and bounded. It does not create, export or bind any real graph.'}
$result|ConvertTo-Json -Depth 6 | Tee-Object -FilePath (Join-Path $runDir 'gameloop-fixture-verification.json')
if($failed.Count -ne 0){exit 1}
