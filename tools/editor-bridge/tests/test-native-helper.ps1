# Offline: production functions only, never runner startup or a real executable.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$runner=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../elevated-runner.ps1'))
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($runner,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
# ALL function definitions from the runner and its sibling modules -- every function, none
# of the top-level statements.  MEASURED 2026-10-04: a hand-written name list CANNOT work.
# Get-DispatchPinFiles calls Get-ReopenAcceptancePinFiles (reopen-lifecycle.ps1), which
# calls Assert-ReopenOrdinary; each was its own CommandNotFoundException, and this file
# executed not one Check until all of them resolved.  "production functions only, never
# runner startup" is preserved by taking FunctionDefinitionAst and nothing else.
foreach($source in @($runner,(Join-Path $PSScriptRoot '../reopen-lifecycle.ps1'),(Join-Path $PSScriptRoot '../call-bridge.ps1'))) {
  if(-not [IO.File]::Exists($source)){continue}
  $srcT=[IO.File]::ReadAllText($source)
  $srcAst=[Management.Automation.Language.Parser]::ParseInput($srcT,[ref]$tokens,[ref]$errors)
  if($errors.Count){throw ($source+': '+($errors|Out-String))}
  foreach($fn in @($srcAst.FindAll({param($a)$a -is [Management.Automation.Language.FunctionDefinitionAst]},$true))) {
    . ([scriptblock]::Create($fn.Extent.Text))
  }
}
$opsAst=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot '../elevated-fs-ops.ps1'),[ref]$tokens,[ref]$errors)
$fn=$opsAst.Find({param($a)$a -is [Management.Automation.Language.FunctionDefinitionAst] -and $a.Name -ceq 'Get-JsonField'},$true)
. ([scriptblock]::Create($fn.Extent.Text))

$script:passed=0
function Check([bool]$value,[string]$name){if(-not$value){throw ('FAILED:'+ $name)};$script:passed++}
function Refuses([scriptblock]$body,[string]$name){$caught=$false;try{&$body|Out-Null}catch{$caught=$true};Check $caught $name}
$projectRoot=Join-Path ([IO.Path]::GetTempPath()) ('native-helper-offline-'+[Guid]::NewGuid().ToString('N'))
$runtime=Join-Path $projectRoot '.runtime'
New-Item -ItemType Directory -Path $runtime -Force|Out-Null
$utf8NoBom=[Text.UTF8Encoding]::new($false)
$session=Join-Path $runtime 'session.json';$review=Join-Path $runtime 'review.json'
[IO.File]::WriteAllText($session,'{}');[IO.File]::WriteAllText($review,'{}')
function Make([string]$action='inspect') {
  $x=@{kind='native-scene';action=$action;sessionPath=$session;levelId=1073741839}
  if($action -ne 'inspect'){$x.reviewPath=$review}
  if($action -eq 'create'){$x.templateId=20001200;$x.position=@(0,1,2);$x.rotation=@(0,0,0);$x.scale=@(1,1,1)}
  if($action -eq 'create-batch'){$x.placements=@(@{template_id=20001200;position=@(0,1,2);rotation=@(0,0,0);scale=@(1,1,1)})}
  return $x
}
try {
  foreach($action in @('inspect','create','save','create-batch')){
    $x=Get-ValidatedNativeSceneRequest (Make $action) $projectRoot
    Check ($x.action -ceq $action -and $x.levelId -is [uint32]) ('valid '+$action)
  }
  foreach($key in @('script','exe','run','wrapper','hash','plan','baseline','ids')){$x=Make;$x[$key]='x';Refuses {Get-ValidatedNativeSceneRequest $x $projectRoot} ('closed '+$key)}
  foreach($id in @($null,0,-1,4294967296,[double]1,$true,'1')){$x=Make;$x.levelId=$id;Refuses {Get-ValidatedNativeSceneRequest $x $projectRoot} 'ID invalid'}
  $x=Make 'save';$x.Remove('reviewPath');Refuses {Get-ValidatedNativeSceneRequest $x $projectRoot} 'review required'
  foreach($path in @('relative.json',(Join-Path $projectRoot 'outside.json'),($session+':evil'),($session+'.'),(Join-Path $runtime 'missing.json'))){$x=Make;$x.sessionPath=$path;Refuses {Get-ValidatedNativeSceneRequest $x $projectRoot} 'path refused'}
  foreach($vector in @(@(1,2),@(1,2,3,4),@($true,1,2),@('1',1,2),@([double]::NaN,1,2),@(1e40,1,2))){$x=Make 'create';$x.position=$vector;Refuses {Get-ValidatedNativeSceneRequest $x $projectRoot} 'vector refused'}
  $x=Make 'create';$x.scale=@(0,1,1);Refuses {Get-ValidatedNativeSceneRequest $x $projectRoot} 'positive scale'
  # 2026-10-11: the template whitelist is gone (2026-10-09) so templateId=1 is now valid;
  # the refusal that remains is a value outside the uint32 range.
  $x=Make 'create';$x.templateId=4294967296;Refuses {Get-ValidatedNativeSceneRequest $x $projectRoot} 'template id out of range'
  $x=Make 'create-batch';$x.placements=@();Refuses {Get-ValidatedNativeSceneRequest $x $projectRoot} 'empty batch'
  $x=Make 'create-batch';$x.placements=@($x.placements[0])*257;Refuses {Get-ValidatedNativeSceneRequest $x $projectRoot} 'oversize batch'
  $x=Make 'create-batch';$x.placements[0].script='x';Refuses {Get-ValidatedNativeSceneRequest $x $projectRoot} 'closed placement'
  $x=Make 'create-batch';$x.placements=@($x.placements[0])*256;$c=Get-ValidatedNativeSceneRequest $x $projectRoot
  Check ($c.placements.Count -eq 256 -and $c.placements[0].ContainsKey('template_id')) 'max batch canonical keys'
  $argv=Get-NativeSceneArguments (Get-ValidatedNativeSceneRequest (Make 'create') $projectRoot) $projectRoot
  Check (($argv[0..2]-join ',') -ceq '-B,-I,-S') 'isolated Python flags'
  Check ($argv[3] -eq (Join-Path $projectRoot 'tools/game-executor/scene_cli.py') -and $argv[5] -ceq '--direct-elevated') 'fixed CLI direct path'
  Check (($argv -contains '--review') -and -not($argv -contains 'RunAs')) 'review retained no extra elevation'
  Refuses {Get-NativeSceneArguments (Get-ValidatedNativeSceneRequest (Make 'create-batch') $projectRoot) $projectRoot} 'batch internal plan required'
  foreach($reply in @(@{ok=$true},@{cleanupVerified='true'},@{safeToRelease=1},@{cleanupVerified=$true;outcomeUncertain=$true},@{safeToRelease=$true;outcomeUncertain='false'})) {Check (-not(Test-NativeTerminalSafe ([pscustomobject]$reply))) 'no unsafe release'}
  Check (Test-NativeTerminalSafe ([pscustomobject]@{ok=$false;safeToRelease=$true})) 'prelaunch refusal releases'
  Check (Test-NativeTerminalSafe ([pscustomobject]@{ok=$false;cleanupVerified=$true})) 'cleaned business failure releases'

  # Exercise real pin enumeration and held FileShare.Read locks with a fake runtime tree.
  #
  # MEASURED 2026-10-04 -- this block had two defects that made the assertion worthless:
  #   1. it never created `tools/game-executor/native`, and Get-DispatchPinFiles does
  #      `Get-ChildItem` on exactly that directory.  With $ErrorActionPreference='Stop'
  #      (:3) the missing directory THREW, so the run died before reaching the check --
  #      the test could not run at all.
  #   2. the count was a hardcoded 9, a snapshot of how many files the real native/ held
  #      when it was written.  The real directory has since grown (40), so even a runnable
  #      version would now fail for a reason that has nothing to do with pinning.
  # The fixture below therefore creates a KNOWN set and asserts the pin set contains
  # exactly that set.  A fixture test must describe its own world, never the repository's.
  $nativePython=Join-Path $projectRoot 'python/python.exe'
  $fixedPowerShell=Join-Path $projectRoot 'powershell.exe'
  foreach($dir in @('python/Lib/site-packages','python/Lib/__pycache__','python/DLLs','tools/game-executor/native','tools/entity-transform','tools/map-terrain','tools/playtest-control','tools/editor-bridge/native-card','tools/game-executor/native-options','tools/game-executor/template-authoring')){New-Item -ItemType Directory -Path (Join-Path $projectRoot $dir) -Force|Out-Null}
  foreach($file in @('tools/editor-bridge/native-card/dispatch.py','tools/game-executor/native-options/build_generalized.py','tools/game-executor/template-authoring/prepare_item.py','tools/game-executor/template-authoring/prepare_currency.py')){[IO.File]::WriteAllText((Join-Path $projectRoot $file),'fixture')}
  foreach($file in @('python/python.exe','python/Lib/stdlib.py','python/Lib/__pycache__/cache.pyc','python/Lib/site-packages/unrelated.py','python/DLLs/native.pyd')){[IO.File]::WriteAllText((Join-Path $projectRoot $file),'fixture')}
  # Two of the named native inputs (they are listed by name in Get-DispatchPinFiles) and
  # two that only the directory glob can reach, so both routes are exercised.
  $nativeFixture=@('game_reopen_guards.h','game_reopen_guards.cpp','globbed_extra.cpp','globbed_extra.inc')
  foreach($file in $nativeFixture){[IO.File]::WriteAllText((Join-Path $projectRoot ('tools/game-executor/native/'+$file)),'fixture')}
  foreach($file in @('cli.py','native_observation.cpp','runtime-profile.json')){[IO.File]::WriteAllText((Join-Path $projectRoot ('tools/playtest-control/'+$file)),'fixture')}
  # Get-ReopenAcceptancePinFiles (via Get-DispatchPinFiles) REQUIRES seven files and seven
  # directories to exist and throws REOPEN_VERIFIER_DEPENDENCY_DIRECTORY otherwise.  They
  # are part of what pinning covers, so the fixture has to contain them; leaving them out
  # is the fourth and last reason this file could not run.  Every one is created empty --
  # nothing here is read, only enumerated.
  $reopenFiles=@('tools/game-executor/native_reopen_acceptance.py','tools/game-executor/verify-created-save.py','tools/editor-bridge/audit-native-enums.py','tools/editor-bridge/build-newdemo-static.py','tools/editor-bridge/build-static-level-draft.py','tools/editor-bridge/connection-evidence.py','tools/beyond-save/gil_container.py')
  foreach($file in $reopenFiles){$p=Join-Path $projectRoot $file;[IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($p))|Out-Null;[IO.File]::WriteAllText($p,'fixture')}
  $sitePkgs=Join-Path $projectRoot 'python/Lib/site-packages'
  [IO.Directory]::CreateDirectory($sitePkgs)|Out-Null
  [IO.File]::WriteAllText((Join-Path $sitePkgs 'typing_extensions.py'),'fixture')
  $reopenDirs=@('third_party/auto-miliastra/src/miliastra_agent','python/Lib/site-packages/google/protobuf','python/Lib/site-packages/google/_upb','python/Lib/site-packages/pydantic','python/Lib/site-packages/pydantic_core','python/Lib/site-packages/typing_inspection','python/Lib/site-packages/annotated_types')
  foreach($dir in $reopenDirs){[IO.Directory]::CreateDirectory((Join-Path $projectRoot $dir))|Out-Null}
  $paths=@(Get-DispatchPinFiles $projectRoot $nativePython)
  foreach($file in @('tools/editor-bridge/native-card/dispatch.py','tools/game-executor/native-options/build_generalized.py','tools/game-executor/template-authoring/prepare_item.py','tools/game-executor/template-authoring/prepare_currency.py')){
    $want=Join-Path $projectRoot $file
    Check ([bool]($paths|Where-Object {$_ -eq $want})) ('native card dependency pinned: '+$file)
  }
  # ``site-packages`` is NOT a forbidden pattern: Get-ReopenAcceptancePinFiles legitimately
  # pins site-packages/typing_extensions.py and the six verifier dependency packages under
  # it.  The blanket directory pattern predates that and made this Check fail for a reason
  # that has nothing to do with exclusion.  What the Check MEANS is "an UNRELATED file is
  # not pinned", so it names the unrelated file the fixture created.
  Check (-not [bool]($paths|Where-Object {$_ -match 'unrelated\.py$|\.pyc$|new-scope|load-bridge|test_|scene_chain'})) 'pins exclude unrelated files and caches'
  Check ([bool]($paths|Where-Object {$_ -match 'typing_extensions\.py$'})) 'the reopen verifier dependency IS pinned (the pattern above must not have excluded it)'
  # A COUNT over the whole native/ prefix is the wrong assertion and always was: the named
  # list adds its entries whether or not the file exists, so the count reflects how many
  # names that list happens to hold -- 9 when this line was written, 19 now.  The property
  # worth asserting is that every native input THIS FIXTURE created is pinned, and that the
  # two the name list cannot reach ARE reached by the directory glob.
  foreach($file in $nativeFixture){
    $want=Join-Path $projectRoot ('tools/game-executor/native/'+$file)
    Check ([bool]($paths|Where-Object {$_ -eq $want})) ("native input pinned: "+$file)
  }
  Check (@($paths|Where-Object {$_ -match 'globbed_extra'}).Count -eq 2) 'the directory glob reaches inputs the name list does not'
  foreach($file in @('cli.py','native_observation.cpp','runtime-profile.json')){
    $want=Join-Path $projectRoot ('tools/playtest-control/'+$file)
    Check ([bool]($paths|Where-Object {$_ -eq $want})) ('playtest observation input pinned: '+$file)
  }
  foreach($path in $paths){if(-not[IO.File]::Exists($path)){[IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($path))|Out-Null;[IO.File]::WriteAllText($path,'fixture')}}
  $dispatchPins=New-DispatchPins $projectRoot $nativePython
  $held=Lock-DispatchPins $projectRoot $nativePython $dispatchPins
  Refuses {[IO.File]::WriteAllText($nativePython,'changed')} 'held lock refuses write'
  foreach($stream in $held){$stream.Dispose()}
  [IO.File]::WriteAllText($nativePython,'changed')
  Refuses {Lock-DispatchPins $projectRoot $nativePython $dispatchPins} 'source mutation refused'
  [IO.File]::WriteAllText($nativePython,'fixture')
  # Replace only pin provider and executable with recording stubs below.
  function Lock-DispatchPins {return ,([Collections.Generic.List[IDisposable]]::new())}
  $nativeDispatchRoot=Join-Path $runtime 'editor-bridge/native-dispatch';[IO.Directory]::CreateDirectory($nativeDispatchRoot)|Out-Null
  $nativeActivePath=Join-Path $nativeDispatchRoot 'native-active.json';$startedUtc=[DateTime]::UtcNow
  $script:childCalls=0;$script:childReply='{"ok":true,"cleanupVerified":true}'
  $nativePython={ $script:childCalls++;$script:childArgs=@($args);$global:LASTEXITCODE=0;$script:childReply }
  $reply=Invoke-FixedNativeScene (Make) ([Guid]::NewGuid().ToString('N'))
  Check ($reply.ok -and $script:childCalls -eq 1 -and -not(Test-Path -LiteralPath $nativeActivePath)) 'clean receipt releases native lock'
  Check ($reply.helper.kind -ceq 'native-scene' -and $script:childArgs[3] -eq (Join-Path $projectRoot 'tools/game-executor/scene_cli.py')) 'native fixed route and helper metadata'
  $reply=Invoke-FixedNativeScene (Make 'create-batch') ([Guid]::NewGuid().ToString('N'))
  $plan=$script:childArgs[-1];$saved=[IO.File]::ReadAllText($plan)|ConvertFrom-Json
  Check ($saved.placements.Count -eq 1 -and $saved.placements[0].template_id -eq 20001200) 'batch generated plan preserves data'
  $script:childReply='{"ok":false,"safeToRelease":true,"nativeStarted":false}'
  $reply=Invoke-FixedNativeScene (Make 'save') ([Guid]::NewGuid().ToString('N'))
  Check (-not$reply.ok -and -not(Test-Path -LiteralPath $nativeActivePath)) 'definite prelaunch refusal preserved'
  $script:childReply='{"ok":false,"outcomeUncertain":true}'
  $reply=Invoke-FixedNativeScene (Make) ([Guid]::NewGuid().ToString('N'))
  $calls=$script:childCalls
  Check ((Test-Path -LiteralPath $nativeActivePath) -and -not$reply.ok) 'uncertain reply keeps persistent lock'
  Refuses {Invoke-FixedNativeScene (Make) ([Guid]::NewGuid().ToString('N'))} 'next native refused after uncertainty'
  Check ($script:childCalls -eq $calls) 'uncertain request never retried'

  $graph=@{kind='author-graph';runId='11111111-1111-1111-1111-111111111111';requestId='request_1'}
  $journal=Join-Path $runtime 'authoring/requests/request_1';[IO.Directory]::CreateDirectory($journal)|Out-Null
  foreach($file in @('claim.json','bridge-request.json')){[IO.File]::WriteAllText((Join-Path $journal $file),'{}')}
  $route=Get-AuthorGraphDispatch $graph $projectRoot
  Check ($route.Script -eq (Join-Path $projectRoot 'tools/authoring/graph-elevated-once.ps1')) 'graph fixed route'
  foreach($key in @('script','payload','path')){$bad=$graph.Clone();$bad[$key]='x';Refuses {Get-AuthorGraphDispatch $bad $projectRoot} 'graph closed fields'}
  foreach($id in @('../escape','-leading',('a'*81))){$bad=$graph.Clone();$bad.requestId=$id;Refuses {Get-AuthorGraphDispatch $bad $projectRoot} 'graph ID closed'}
  Refuses {Invoke-FixedAuthorGraph $graph} 'uncertain native blocks graph'
  Remove-Item -LiteralPath $nativeActivePath
  $fixedPowerShell={ $script:childCalls++;$script:graphArgs=@($args);$global:LASTEXITCODE=0;[IO.File]::WriteAllText((Join-Path $journal 'elevated-attempt.used'),'fixture');[IO.File]::WriteAllText((Join-Path $journal 'elevated-response.json'),'{"ok":true,"graph":{"id":7}}') }
  $reply=Invoke-FixedAuthorGraph $graph
  Check ($reply.ok -and $reply.graph.id -eq 7 -and $script:graphArgs[2] -eq $route.Script) 'graph reply and fixed argv preserved'
  $calls=$script:childCalls
  Refuses {Invoke-FixedAuthorGraph $graph} 'graph second attempt refused'
  Check ($script:childCalls -eq $calls) 'graph never redispatched'
  Write-Output ('PASS '+$script:passed+' isolated PowerShell checks; no helper startup or game/editor contact')
} finally {
  $resolved=[IO.Path]::GetFullPath($projectRoot);$temp=[IO.Path]::GetFullPath([IO.Path]::GetTempPath())
  if($resolved.StartsWith($temp,[StringComparison]::OrdinalIgnoreCase) -and [IO.Path]::GetFileName($resolved).StartsWith('native-helper-offline-')){Remove-Item -LiteralPath $resolved -Recurse -Force}
}
