# Pure helper contract checks. Extract only functions; never start the runner.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
$runner=Join-Path $projectRoot 'tools/editor-bridge/elevated-runner.ps1'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($runner,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ('Runner syntax errors: '+($errors.Message -join '; '))}
foreach($name in @('Assert-DispatchOrdinaryPath','Get-NativeMapDispatch','Test-NativeTerminalSafe','Get-StreamSha256','Write-ExclusiveDispatchJson','Invoke-FixedNativeMap')){
    $function=$ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst]},$true) | Where-Object Name -CEQ $name
    if(@($function).Count -ne 1){throw ('Missing or duplicate function '+$name)}
    Invoke-Expression $function.Extent.Text
}
$opsAst=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot '../elevated-fs-ops.ps1'),[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'JSON utility syntax errors'}
$jsonFunction=$opsAst.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq 'Get-JsonField'},$true)
. ([scriptblock]::Create($jsonFunction.Extent.Text))
$fixture=Join-Path $projectRoot ('.runtime/map-foundation-20261015/integration/helper-contract-'+[Guid]::NewGuid().ToString('N'))
$run=Join-Path $fixture '.runtime/map-foundation-20261015/transform/prepared/card'
New-Item -ItemType Directory -Path $run -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $fixture 'tools/entity-transform') -Force | Out-Null
[IO.File]::WriteAllText((Join-Path $run 'prepared.json'),'{}')
[IO.File]::WriteAllText((Join-Path $fixture 'tools/entity-transform/cli.py'),'# fixture, never executed')
$preparedSha=(Get-FileHash -LiteralPath (Join-Path $run 'prepared.json') -Algorithm SHA256).Hash.ToLowerInvariant()
$good=@{kind='native-map';tool='entity-transform';runPath=$run;preparedSha256=$preparedSha}
$route=Get-NativeMapDispatch $good $fixture
if($route.Action -cne 'dispatch' -or $route.Script -cne (Join-Path $fixture 'tools/entity-transform/cli.py')){throw 'Wrong fixed route'}
$playtestRun=Join-Path $fixture '.runtime/playtest-control-20261016/prepared/observation'
New-Item -ItemType Directory -Path $playtestRun -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $fixture 'tools/playtest-control') -Force | Out-Null
[IO.File]::WriteAllText((Join-Path $playtestRun 'prepared.json'),'{}')
[IO.File]::WriteAllText((Join-Path $fixture 'tools/playtest-control/cli.py'),'# fixture, never executed')
$playtest=@{kind='native-map';tool='playtest-control';runPath=$playtestRun;preparedSha256=$preparedSha}
$playtestRoute=Get-NativeMapDispatch $playtest $fixture
if($playtestRoute.Action -cne 'dispatch' -or $playtestRoute.Script -cne (Join-Path $fixture 'tools/playtest-control/cli.py')){throw 'Wrong observation route'}
$assetRun=Join-Path $fixture '.runtime/asset-inspection-20261017/prepared/assets'
New-Item -ItemType Directory -Path $assetRun -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $fixture 'tools/game-executor') -Force | Out-Null
[IO.File]::WriteAllText((Join-Path $assetRun 'prepared.json'),'{}')
[IO.File]::WriteAllText((Join-Path $fixture 'tools/game-executor/asset_inspection.py'),'# fixture, never executed')
$asset=@{kind='native-map';tool='asset-inspection';runPath=$assetRun;preparedSha256=$preparedSha}
$assetRoute=Get-NativeMapDispatch $asset $fixture
if($assetRoute.Action -cne 'dispatch' -or $assetRoute.Script -cne (Join-Path $fixture 'tools/game-executor/asset_inspection.py')){throw 'Wrong asset inspection route'}
$materialRun=Join-Path $fixture '.runtime/entity-material-20261017/prepared/material'
New-Item -ItemType Directory -Path $materialRun -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $fixture 'tools/entity-material') -Force | Out-Null
[IO.File]::WriteAllText((Join-Path $materialRun 'prepared.json'),'{}')
[IO.File]::WriteAllText((Join-Path $fixture 'tools/entity-material/cli.py'),'# fixture, never executed')
$material=@{kind='native-map';tool='entity-material';runPath=$materialRun;preparedSha256=$preparedSha}
$materialRoute=Get-NativeMapDispatch $material $fixture
if($materialRoute.Action -cne 'dispatch' -or $materialRoute.Script -cne (Join-Path $fixture 'tools/entity-material/cli.py')){throw 'Wrong material route'}
$waterRun=Join-Path $fixture '.runtime/terrain-water-20261017/prepared/water'
New-Item -ItemType Directory -Path $waterRun -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $fixture 'tools/terrain-water') -Force | Out-Null
[IO.File]::WriteAllText((Join-Path $waterRun 'prepared.json'),'{}')
[IO.File]::WriteAllText((Join-Path $fixture 'tools/terrain-water/cli.py'),'# fixture, never executed')
$water=@{kind='native-map';tool='terrain-water';runPath=$waterRun;preparedSha256=$preparedSha}
$waterRoute=Get-NativeMapDispatch $water $fixture
if($waterRoute.Action -cne 'execute' -or $waterRoute.Script -cne (Join-Path $fixture 'tools/terrain-water/cli.py')){throw 'Wrong water route'}
$propertiesRun=Join-Path $fixture '.runtime/template-properties-20261017/v2-prepared/properties'
New-Item -ItemType Directory -Path $propertiesRun -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $fixture 'tools/template-properties/v2') -Force | Out-Null
[IO.File]::WriteAllText((Join-Path $propertiesRun 'prepared.json'),'{}')
[IO.File]::WriteAllText((Join-Path $fixture 'tools/template-properties/v2/cli.py'),'# fixture, never executed')
$properties=@{kind='native-map';tool='template-properties';runPath=$propertiesRun;preparedSha256=$preparedSha}
$propertiesRoute=Get-NativeMapDispatch $properties $fixture
if($propertiesRoute.Action -cne 'dispatch' -or $propertiesRoute.Script -cne (Join-Path $fixture 'tools/template-properties/v2/cli.py')){throw 'Wrong template properties route'}
$propertiesV1Run=Join-Path $fixture '.runtime/template-properties-20261017/prepared/legacy'
New-Item -ItemType Directory -Path $propertiesV1Run -Force | Out-Null
[IO.File]::WriteAllText((Join-Path $propertiesV1Run 'prepared.json'),'{}')
$cardRequests=@()
New-Item -ItemType Directory -Path (Join-Path $fixture 'tools/editor-bridge/native-card') -Force | Out-Null
[IO.File]::WriteAllText((Join-Path $fixture 'tools/editor-bridge/native-card/dispatch.py'),'# fixture, never executed')
foreach($tool in @('template-item','template-currency','generalized-tabs','mondstadt-dropstuff','mondstadt-combat','role-template-bag')){
    $cardRun=Join-Path $fixture ('.runtime/native-card-20261017/prepared/'+$tool+'/card')
    New-Item -ItemType Directory -Path $cardRun -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $cardRun 'prepared.json'),'{}')
    $request=@{kind='native-map';tool=$tool;runPath=$cardRun;preparedSha256=$preparedSha}
    $cardRoute=Get-NativeMapDispatch $request $fixture
    if($cardRoute.Action -cne $tool -or $cardRoute.Script -cne (Join-Path $fixture 'tools/editor-bridge/native-card/dispatch.py')){throw 'Wrong native card route'}
    $cardRequests += $request
}
$cases=@(
    @{kind='native-map';tool='entity-transform';runPath=$run;preparedSha256=$preparedSha;script='arbitrary.ps1'},
    @{kind='native-map';tool='terrain';runPath=$run;preparedSha256=$preparedSha},
    @{kind='native-map';tool='playtest-control';runPath=$run;preparedSha256=$preparedSha},
    @{kind='native-map';tool='entity-transform';runPath=$playtestRun;preparedSha256=$preparedSha},
    @{kind='native-map';tool='asset-inspection';runPath=$run;preparedSha256=$preparedSha},
    @{kind='native-map';tool='terrain';runPath=$assetRun;preparedSha256=$preparedSha},
    @{kind='native-map';tool='entity-material';runPath=$run;preparedSha256=$preparedSha},
    @{kind='native-map';tool='entity-transform';runPath=$materialRun;preparedSha256=$preparedSha},
    @{kind='native-map';tool='mondstadt-combat';runPath=$materialRun;preparedSha256=$preparedSha},
    @{kind='native-map';tool='terrain-water';runPath=$run;preparedSha256=$preparedSha},
    @{kind='native-map';tool='terrain';runPath=$waterRun;preparedSha256=$preparedSha},
    @{kind='native-map';tool='entity-material';runPath=$waterRun;preparedSha256=$preparedSha},
    @{kind='native-map';tool='terrain-water';runPath=$materialRun;preparedSha256=$preparedSha},
    @{kind='native-map';tool='template-properties';runPath=$materialRun;preparedSha256=$preparedSha},
    @{kind='native-map';tool='entity-material';runPath=$propertiesRun;preparedSha256=$preparedSha},
    @{kind='native-map';tool='template-item';runPath=$propertiesRun;preparedSha256=$preparedSha},
    @{kind='native-map';tool='role-template-bag';runPath=$propertiesRun;preparedSha256=$preparedSha},
    @{kind='native-map';tool='template-properties';runPath=$propertiesRun;preparedSha256=$preparedSha;action='other'},
    @{kind='native-map';tool='template-properties';runPath=$propertiesV1Run;preparedSha256=$preparedSha},
    @{kind='native-map';tool='unknown';runPath=$run;preparedSha256=$preparedSha},
    @{kind='native-map';tool='entity-transform';runPath=($run+'\..');preparedSha256=$preparedSha},
    @{kind='native-map';tool='entity-transform';runPath=$fixture;preparedSha256=$preparedSha},
    @{kind='native-map';tool='entity-transform';runPath=$run;preparedSha256=('0'*64)}
)
foreach($bad in $cases){
    $refused=$false
    try{Get-NativeMapDispatch $bad $fixture | Out-Null}catch{$refused=$true}
    if(-not $refused){throw 'Invalid map request accepted'}
}
if(Test-NativeTerminalSafe ([pscustomobject]@{ok=$true;cleanupVerified=$true;outcomeUncertain=$true})){throw 'Uncertain result released lock'}
if(Test-NativeTerminalSafe ([pscustomobject]@{ok=$true;cleanupVerified='true'})){throw 'Nonboolean cleanup accepted'}
if(-not(Test-NativeTerminalSafe ([pscustomobject]@{ok=$true;cleanupVerified=$true;outcomeUncertain=$false}))){throw 'Verified cleanup rejected'}
if(-not(Test-NativeTerminalSafe ([pscustomobject]@{ok=$false;safeToRelease=$true;outcomeUncertain=$false}))){throw 'Prelaunch refusal rejected'}
# Run the production dispatcher against a recording child stub, never an executable.
$projectRoot=$fixture
$nativeDispatchRoot=Join-Path $fixture '.runtime/dispatch'
New-Item -ItemType Directory -Path $nativeDispatchRoot -Force | Out-Null
$nativeActivePath=Join-Path $nativeDispatchRoot 'native-active.json'
$utf8NoBom=[Text.UTF8Encoding]::new($false)
$dispatchPins=@{}
function Lock-DispatchPins {return ,([Collections.Generic.List[IDisposable]]::new())}
$script:calls=0
$script:reply='{"ok":true,"cleanupVerified":true}'
$nativePython={ $script:calls++;$script:argv=@($args);$global:LASTEXITCODE=0;$script:reply }
$requestId=[Guid]::NewGuid().ToString('N')
$result=Invoke-FixedNativeMap $good $requestId
if(-not $result.ok -or $script:calls -ne 1 -or (Test-Path -LiteralPath $nativeActivePath)){throw 'Clean dispatch did not release lock'}
if(($script:argv[0..2]-join ',') -cne '-B,-I,-S' -or $script:argv[4] -cne 'dispatch' -or $script:argv[6] -cne $run){throw 'Fixed dispatch arguments changed'}
$refused=$false
try{Invoke-FixedNativeMap $good $requestId | Out-Null}catch{$refused=$true}
if(-not $refused -or $script:calls -ne 1){throw 'Repeated queue request executed'}
$script:reply='{"ok":false,"safeToRelease":true,"nativeStarted":false}'
$result=Invoke-FixedNativeMap $good ([Guid]::NewGuid().ToString('N'))
if($result.ok -or (Test-Path -LiteralPath $nativeActivePath)){throw 'Safe prelaunch refusal did not release lock'}
$script:reply='{"ok":true,"cleanupVerified":true,"outcomeUncertain":false}'
$result=Invoke-FixedNativeMap $playtest ([Guid]::NewGuid().ToString('N'))
if(-not $result.ok -or (Test-Path -LiteralPath $nativeActivePath) -or $script:argv[3] -cne (Join-Path $fixture 'tools/playtest-control/cli.py') -or $script:argv[6] -cne $playtestRun){throw 'Observation did not use fixed arguments'}
foreach($request in $cardRequests){
    $result=Invoke-FixedNativeMap $request ([Guid]::NewGuid().ToString('N'))
    if(-not $result.ok -or (Test-Path -LiteralPath $nativeActivePath) -or $script:argv[4] -cne $request.tool -or $script:argv[6] -cne $request.runPath){throw 'Card arguments not fixed'}
}
$result=Invoke-FixedNativeMap $material ([Guid]::NewGuid().ToString('N'))
if(-not $result.ok -or (Test-Path -LiteralPath $nativeActivePath) -or $script:argv[3] -cne (Join-Path $fixture 'tools/entity-material/cli.py') -or $script:argv[4] -cne 'dispatch' -or $script:argv[6] -cne $materialRun){throw 'Material arguments not fixed'}
$result=Invoke-FixedNativeMap $water ([Guid]::NewGuid().ToString('N'))
if(-not $result.ok -or (Test-Path -LiteralPath $nativeActivePath) -or $script:argv[3] -cne (Join-Path $fixture 'tools/terrain-water/cli.py') -or $script:argv[4] -cne 'execute' -or $script:argv[6] -cne $waterRun -or $script:argv[7] -cne '--direct-elevated'){throw 'Water arguments not fixed'}
$result=Invoke-FixedNativeMap $properties ([Guid]::NewGuid().ToString('N'))
if(-not $result.ok -or (Test-Path -LiteralPath $nativeActivePath) -or $script:argv[3] -cne (Join-Path $fixture 'tools/template-properties/v2/cli.py') -or $script:argv[4] -cne 'dispatch' -or $script:argv[6] -cne $propertiesRun -or $script:argv[7] -cne '--direct-elevated'){throw 'Template properties arguments not fixed'}
$script:reply='{"ok":false,"outcomeUncertain":true}'
$propertiesResult=Invoke-FixedNativeMap $properties ([Guid]::NewGuid().ToString('N'))
if(-not $propertiesResult.outcomeUncertain -or -not(Test-Path -LiteralPath $nativeActivePath)){throw 'Unknown template properties did not retain lock'}
$propertyCalls=$script:calls;$propertyRefused=$false
try{Invoke-FixedNativeMap $properties ([Guid]::NewGuid().ToString('N'))|Out-Null}catch{$propertyRefused=$true}
if(-not $propertyRefused -or $script:calls -ne $propertyCalls){throw 'Unknown template properties was replayed'}
# Fixture-only reset to exercise the other route's independent unknown case.
[IO.File]::Delete($nativeActivePath)
$script:reply='{"ok":false,"outcomeUncertain":true}'
$assetResult=Invoke-FixedNativeMap $asset ([Guid]::NewGuid().ToString('N'))
if($script:argv[3] -cne (Join-Path $fixture 'tools/game-executor/asset_inspection.py') -or $script:argv[6] -cne $assetRun -or -not(Test-Path -LiteralPath $nativeActivePath)){throw 'Asset observation route or unknown-outcome lock changed'}
$assetCalls=$script:calls;$assetRefused=$false
try{Invoke-FixedNativeMap $asset ([Guid]::NewGuid().ToString('N'))|Out-Null}catch{$assetRefused=$true}
if(-not $assetRefused -or $script:calls -ne $assetCalls){throw 'Unknown asset observation was replayed'}
# Fixture-only reset lets the existing entity-transform unknown-result case run.
[IO.File]::Delete($nativeActivePath)
$result=Invoke-FixedNativeMap $good ([Guid]::NewGuid().ToString('N'))
if(-not (Test-Path -LiteralPath $nativeActivePath)){throw 'Unknown result lost persistent lock'}
$callsBefore=$script:calls;$refused=$false
try{Invoke-FixedNativeMap $good ([Guid]::NewGuid().ToString('N')) | Out-Null}catch{$refused=$true}
if(-not $refused -or $script:calls -ne $callsBefore){throw 'Unknown result was followed by another dispatch'}
# Keep this small fixture as test evidence; no game/file outside this project was touched.
@{ok=$true;scope='offline-fixed-map-transport';schemaRejections=$cases.Count;childInvocations=$script:calls;fixture=$fixture} | ConvertTo-Json -Compress
