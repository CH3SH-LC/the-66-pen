# Actual subprocess UTF8 boundary regression; no helper startup or live contact.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$runner=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../elevated-runner.ps1'))
$ast=[Management.Automation.Language.Parser]::ParseFile($runner,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
foreach($name in @('Get-ValidatedNativeSceneRequest','Assert-DispatchOrdinaryPath','Write-ExclusiveDispatchJson','Test-NativeTerminalSafe','Invoke-FixedNativeScene')) {
 $fn=$ast.Find({param($a)$a -is [Management.Automation.Language.FunctionDefinitionAst] -and $a.Name -ceq $name},$true)
 if($null -eq $fn){throw ('Missing '+$name)}
 . ([scriptblock]::Create($fn.Extent.Text))
}
$ops=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot '../elevated-fs-ops.ps1'),[ref]$tokens,[ref]$errors)
$fn=$ops.Find({param($a)$a -is [Management.Automation.Language.FunctionDefinitionAst] -and $a.Name -ceq 'Get-JsonField'},$true)
. ([scriptblock]::Create($fn.Extent.Text))
$script:passed=0
function Check([bool]$value,[string]$name){if(-not$value){throw ('FAILED:'+ $name)};$script:passed++}
function Refuses([scriptblock]$action,[string]$name){$caught=$false;try{&$action|Out-Null}catch{$caught=$true};Check $caught $name}
$projectRoot=Join-Path ([IO.Path]::GetTempPath()) ('native-utf8-offline-'+[Guid]::NewGuid().ToString('N'))
$nativeDispatchRoot=Join-Path $projectRoot '.runtime/native-dispatch';[IO.Directory]::CreateDirectory($nativeDispatchRoot)|Out-Null
$nativeActivePath=Join-Path $nativeDispatchRoot 'native-active.json'
$session=Join-Path $projectRoot '.runtime/session.json';[IO.File]::WriteAllText($session,'{}')
$fixture=Join-Path $projectRoot 'print-fixture.py'
$utf8NoBom=[Text.UTF8Encoding]::new($false)
$nativePython=Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Programs/Python/Python313/python.exe'
$dispatchPins=@{};$startedUtc=[DateTime]::UtcNow
function Lock-DispatchPins {return ,([Collections.Generic.List[IDisposable]]::new())}
# Only routing/pin acquisition are replaced in the isolated test scope; the child,
# stdout bytes, production capture, parsing, receipt and gate handling are real.
function Get-NativeSceneArguments {return ,([string[]]@('-B','-I','-S',$fixture))}
$body=[pscustomobject]@{kind='native-scene';action='inspect';sessionPath=$session;levelId=1073741839}
$original=[Console]::OutputEncoding
try {
 [Console]::OutputEncoding=[Text.Encoding]::GetEncoding(936)
 $pythonCode=@('import json,sys',"sys.stdout.reconfigure(encoding='utf-8')","print(json.dumps({'ok':True,'cleanupVerified':True,'nativeStarted':True,'source':'C:/\u539f\u795e/\u4e2d\u6587/\U0001f4be.gil','hash':'abc123','bytes':16015},ensure_ascii=False))") -join [Environment]::NewLine
 [IO.File]::WriteAllText($fixture,$pythonCode,$utf8NoBom)
 $id=[Guid]::NewGuid().ToString('N')
 $reply=Invoke-FixedNativeScene $body $id
 $expected='C:/原神/中文/'+[char]::ConvertFromUtf32(0x1f4be)+'.gil'
 Check ($reply.source -ceq $expected) 'actual Python UTF8 stdout is decoded exactly'
 Check ($reply.ok -eq $true -and $reply.cleanupVerified -eq $true -and $reply.nativeStarted -eq $true) 'business flags intact'
 Check ($reply.bytes -eq 16015 -and $reply.hash -ceq 'abc123') 'ASCII business values intact'
 Check ([Console]::OutputEncoding.CodePage -eq 936) 'native console restored after success'
 Check (-not(Test-Path -LiteralPath $nativeActivePath)) 'normal cleanup releases native gate'
 $stored=[IO.File]::ReadAllText((Join-Path $nativeDispatchRoot ($id+'/stdout.json')),$utf8NoBom)|ConvertFrom-Json
 Check ($stored.source -ceq $expected) 'saved capture preserves exact Unicode'
 Check ($reply.helper.requestId -ceq $id) 'helper identity retained'
 [IO.File]::WriteAllText($fixture,("import sys"+"\n"+"sys.stdout.reconfigure(encoding='utf-8')"+"\n"+"print('\u539f\u795e')").Replace('\n',[Environment]::NewLine),$utf8NoBom)
 Refuses {Invoke-FixedNativeScene $body ([Guid]::NewGuid().ToString('N'))} 'malformed native stdout refused'
 Check ([Console]::OutputEncoding.CodePage -eq 936) 'native console restored after parse failure'
 Check (Test-Path -LiteralPath $nativeActivePath) 'parse failure preserves uncertain gate'
 Remove-Item -LiteralPath $nativeActivePath
 $nativePython=Join-Path $projectRoot 'nonexistent-fixture-python.exe'
 Refuses {Invoke-FixedNativeScene $body ([Guid]::NewGuid().ToString('N'))} 'executable start failure refused'
 Check ([Console]::OutputEncoding.CodePage -eq 936) 'native console restored when invocation throws'
 Check (Test-Path -LiteralPath $nativeActivePath) 'invocation exception preserves gate'

 # Extract only the actual graph capture encoding block, without its admin check,
 # attempt marker, graph transport or pipe access.
 $graph=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../authoring/graph-elevated-once.ps1'))
 $graphAst=[Management.Automation.Language.Parser]::ParseFile($graph,[ref]$tokens,[ref]$errors)
 if($errors.Count){throw ($errors|Out-String)}
 $guard=$graphAst.Find({param($a)$a -is [Management.Automation.Language.TryStatementAst] -and $null -ne $a.Finally -and $a.Finally.Extent.Text -match 'taskPreviousOutputEncoding'},$true)
 if($null -eq $guard){throw 'Missing real graph encoding try/finally'}
 $capture=[scriptblock]::Create('$taskPreviousOutputEncoding=[Console]::OutputEncoding'+[Environment]::NewLine+$guard.Extent.Text)
 $taskTransport=Join-Path $projectRoot 'graph-output-fixture.ps1'
 $taskSettings='fixture-only';$taskRequestPath='fixture-only'
 $graphCode=@('param($SettingsPath,$RequestPath)','$ErrorActionPreference="Stop"','[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)','[ordered]@{ok=$true;source="C:/原神/中文.gil";name="中文节点";bytes=16015}|ConvertTo-Json -Compress') -join [Environment]::NewLine
 [IO.File]::WriteAllText($taskTransport,$graphCode,[Text.UTF8Encoding]::new($true))
 . $capture
 $graphReply=($taskReply -join [Environment]::NewLine)|ConvertFrom-Json
 Check ($graphReply.source -ceq 'C:/原神/中文.gil' -and $graphReply.name -ceq '中文节点') 'real PowerShell graph child UTF8 paths/text preserved'
 Check ($graphReply.ok -eq $true -and $graphReply.bytes -eq 16015) 'graph business values preserved'
 Check ([Console]::OutputEncoding.CodePage -eq 936) 'graph console restored after success'
 # A real child exits unsuccessfully; console state still restores, and the caller
 # retains its native exit code rather than treating process completion as success.
 [IO.File]::WriteAllText($taskTransport,'exit 7',[Text.UTF8Encoding]::new($true))
 . $capture
 Check ($LASTEXITCODE -eq 7) 'graph child failure code preserved'
 Check ([Console]::OutputEncoding.CodePage -eq 936) 'graph console restored after child failure'
 & {
   # Only the executable path is replaced to force invocation itself to throw;
   # the production try/finally body is unchanged.
   function Join-Path {param($Path,$ChildPath) return ([IO.Path]::Combine($projectRoot,'nonexistent-graph-powershell.exe'))}
   Refuses {. $capture} 'graph invocation failure refused'
   Check ([Console]::OutputEncoding.CodePage -eq 936) 'graph console restored when invocation throws'
 }
 Write-Output ('PASS '+$script:passed+' real subprocess UTF8 checks; isolated fixture only')
} finally {
 [Console]::OutputEncoding=$original
 $resolved=[IO.Path]::GetFullPath($projectRoot);$temp=[IO.Path]::GetFullPath([IO.Path]::GetTempPath())
 if($resolved.StartsWith($temp,[StringComparison]::OrdinalIgnoreCase) -and [IO.Path]::GetFileName($resolved).StartsWith('native-utf8-offline-')){Remove-Item -LiteralPath $resolved -Recurse -Force}
}

