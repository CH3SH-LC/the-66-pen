#Requires -Version 5.1
# Offline named-pipe fixture only: execute the production transport AST against
# random fixture pipes; never execute its scope, process or compatibility prefix.
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
$source=Join-Path $root 'tools/editor-bridge/call-bridge.ps1'
$evidence=Join-Path $root '.runtime/verification/interface-experiments-20260926/query-timeout'
$runRoot=Join-Path $evidence ('fixture-'+[Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($runRoot)|Out-Null
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'SOURCE_PARSE_FAILED'}
$tries=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.TryStatementAst] -and $n.Body.Extent.Text.Contains('$pipe.Connect(5000)')},$true))
if($tries.Count-ne1){throw 'TRANSPORT_BLOCK_NOT_UNIQUE'}
$transport=[scriptblock]::Create($tries[0].Extent.Text)
$assignment=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -ceq '$responseTimeoutMs'},$true))
if($assignment.Count-ne1){throw 'TIMEOUT_ASSIGNMENT_NOT_UNIQUE'}
$selector=[scriptblock]::Create($assignment[0].Extent.Text)
$checks=[Collections.Generic.List[object]]::new()
function Check([bool]$value,[string]$name){
 $checks.Add([pscustomobject]@{name=$name;passed=$value})
 if(-not $value){Write-Host ('FAIL '+$name)}else{Write-Host ('PASS '+$name)}
}
$ops=@(($ast.ParamBlock.Parameters|Where-Object {$_.Name.VariablePath.UserPath-ceq'Operation'}).Attributes|Where-Object {$_.TypeName.Name-ceq'ValidateSet'}).PositionalArguments.Value
foreach($op in $ops){$Operation=$op;. $selector;if($responseTimeoutMs-ne$(if($op-ceq'catalog' -or $op-ceq'node-definition-variants' -or $op-ceq'node-definitions' -or $op-ceq'prefab-catalog' -or $op-ceq'prefab-fields'){60000}else{10000})){throw ('WINDOW_DRIFT:'+ $op)}}
Check ($ops.Count-gt90) 'all production operation windows: only exact catalog, two node queries and two prefab queries 60000, others 10000'
Check ($tries[0].Extent.Text -notmatch 'Get-Process|Get-MiliastraCompatibilityPin|bridge-settings') 'fixture excludes live scope and process guards'
Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.IO.Pipes;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
public sealed class CatalogWaitFixture : IDisposable {
 public readonly NamedPipeServerStream Pipe;
 public Task Work; public string Request; public string Error;
 public int RequestCount; public bool Wrote; public string Extra;
 readonly string reply; readonly int delay;
 public CatalogWaitFixture(string name,string text,int ms) {
  Pipe=new NamedPipeServerStream(name,PipeDirection.InOut,1,PipeTransmissionMode.Byte,PipeOptions.Asynchronous);
  reply=text;delay=ms;
 }
 public static bool IsDisposed(NamedPipeClientStream p){try{return p.SafePipeHandle.IsClosed;}catch(ObjectDisposedException){return true;}}
 public void Start(){Work=Task.Run((Action)Run);}
 void Run(){
  try {
   Pipe.WaitForConnection();
   using(var reader=new StreamReader(Pipe,new UTF8Encoding(false),false,1024,true))
   using(var writer=new StreamWriter(Pipe,new UTF8Encoding(false),1024,true)){
    Request=reader.ReadLine();if(Request!=null)RequestCount++;
    Thread.Sleep(delay);
    if(String.IsNullOrEmpty(reply)){Pipe.Dispose();return;}
    writer.WriteLine(reply);writer.Flush();Wrote=true;
    Extra=reader.ReadLine();if(Extra!=null)RequestCount++;
   }
  } catch(Exception ex){Error=ex.GetType().Name;}
 }
 public void Dispose(){Pipe.Dispose();}
}
'@
function Run-Case([string]$name,[string]$Operation,[string]$response,[int]$delay){
 $pipeName='mw-offline-catalog-'+[Guid]::NewGuid().ToString('N')
 if([string]::IsNullOrEmpty($response)){$response=$null}
 $server=[CatalogWaitFixture]::new($pipeName,$response,$delay)
 $pipe=[IO.Pipes.NamedPipeClientStream]::new('.',$pipeName,[IO.Pipes.PipeDirection]::InOut,[IO.Pipes.PipeOptions]::Asynchronous)
 $scope=[pscustomobject]@{nonce='offline-fixture-only'}
 $reader=$null;$writer=$null;$Ids=$null
 $runDir=Join-Path $runRoot $name
 [IO.Directory]::CreateDirectory($runDir)|Out-Null
 $server.Start();$watch=[Diagnostics.Stopwatch]::StartNew()
 $reply=$null;$failure=$null
 try{$reply=. $transport}catch{$failure=$_.Exception.Message}
 $watch.Stop()
 $finished=$server.Work.Wait(20000)
 $disposed=[CatalogWaitFixture]::IsDisposed($pipe)
 $row=[pscustomobject]@{name=$name;operation=$Operation;elapsedMs=$watch.ElapsedMilliseconds;reply=$reply;error=$failure;serverFinished=$finished;requestCount=$server.RequestCount;wireOp=($server.Request|ConvertFrom-Json).op;wrote=$server.Wrote;serverError=$server.Error;disposed=$disposed;responseFileExists=(Test-Path -LiteralPath (Join-Path $runDir ($Operation+'-response.json')))}
 $server.Dispose();$pipe.Dispose()
 return $row
}
$results=[Collections.Generic.List[object]]::new()
$ok='{"ok":true,"count":235,"message":"千星目录：原神"}'
$a=Run-Case 'catalog-delay' 'catalog' $ok 12000;$results.Add($a)
Check ($a.error-eq$null -and $a.reply-ceq$ok -and $a.elapsedMs-ge11000 -and $a.elapsedMs-lt60000) 'real catalog reply after 12 seconds and Chinese preserved'
Check ($a.requestCount-eq1 -and $a.wireOp-ceq'catalog' -and $a.wrote -and $a.responseFileExists -and $a.disposed) 'catalog sent once, response persisted and transport disposed'
$v=Run-Case 'variants-delay' 'node-definition-variants' $ok 12000;$results.Add($v)
Check ($v.error-eq$null -and $v.reply-ceq$ok -and $v.elapsedMs-ge11000 -and $v.requestCount-eq1 -and $v.disposed) 'variant query accepts delayed response without retry'
$n=Run-Case 'nodes-delay' 'node-definitions' $ok 12000;$results.Add($n)
Check ($n.error-eq$null -and $n.reply-ceq$ok -and $n.elapsedMs-ge11000 -and $n.requestCount-eq1 -and $n.disposed) 'legacy node query accepts delayed response without retry'
foreach($prefabOp in @('prefab-catalog','prefab-fields')){
 $p=Run-Case ($prefabOp+'-delay') $prefabOp $ok 12000;$results.Add($p)
 Check ($p.error-eq$null -and $p.reply-ceq$ok -and $p.elapsedMs-ge11000 -and $p.elapsedMs-lt60000 -and $p.requestCount-eq1 -and $p.responseFileExists -and $p.disposed) ($prefabOp+' delayed response once with persisted evidence and cleanup')
}
$bad='{"ok":false,"error":"目录失败"}'
$b=Run-Case 'catalog-failure' 'catalog' $bad 50;$results.Add($b)
Check ($b.reply-ceq$bad -and ($b.reply|ConvertFrom-Json).ok-eq$false -and $b.requestCount-eq1 -and $b.disposed) 'business failure remains false without retry'
$c=Run-Case 'write-timeout' 'rename-entity-crud-probe' '{"ok":true}' 12000;$results.Add($c)
Check ($c.error-ceq'RESPONSE_TIMEOUT_NOT_PROOF_OF_NO_EFFECT' -and $c.elapsedMs-ge9500 -and $c.elapsedMs-lt11500) 'noncatalog retains real 10 second uncertain timeout'
Check ($c.requestCount-eq1 -and -not$c.responseFileExists -and $c.disposed) 'timeout sends once, writes no response evidence and disposes'
$d=Run-Case 'eof' 'ping' $null 50;$results.Add($d)
Check ($d.error-ceq'BRIDGE_CLOSED_WITHOUT_RESPONSE' -and $d.requestCount-eq1 -and $d.disposed) 'EOF failure and disposal preserved'
$report=[ordered]@{ok=(@($checks|Where-Object {-not $_.passed}).Count-eq0);observedUtc=[DateTime]::UtcNow.ToString('o');host=$PSVersionTable.PSVersion.ToString();productionSha256=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant();checks=$checks;scenarios=$results;operationCount=$ops.Count;liveContact=$false;note='Actual production transport AST; only random local fixture pipes. 60s ceiling selected statically; actual long delay12s and noncatalog timeout10s.'}
[IO.File]::WriteAllText((Join-Path $evidence 'catalog-timeout-result.json'),($report|ConvertTo-Json -Depth 8),[Text.UTF8Encoding]::new($false))
Write-Host ('result='+$report.ok+'; '+$checks.Count+' checks; '+$ops.Count+' operation timeout choices')

if(-not $report.ok){exit 1}
