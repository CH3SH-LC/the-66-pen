param([Parameter(Mandatory=$true)][Guid]$RunId)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$dir=Join-Path $root ('.runtime/editor-bridge/runs/'+$RunId.ToString('D'))
$nativeLog='C:\Games\Genshin Impact Game\BeyondAssets\BeyondAssistEditor\Log\log.txt'
function Call([string]$op){
    $result=(& (Join-Path $PSScriptRoot 'call-bridge.ps1') -RunId $RunId -Operation $op | ConvertFrom-Json)
    if(-not $result.ok){throw ($op+': '+$result.error)}
    return $result
}
try {
    & (Join-Path $PSScriptRoot 'load-bridge.ps1') -RunId $RunId
    $null=Call 'catalog'
    Copy-Item (Join-Path $dir 'catalog-response.json') (Join-Path $dir 'catalog-before-sync.json')
    $started=[DateTimeOffset]::Now.ToString('o')
    $null=Call 'sync-editor-changes'
    Start-Sleep -Seconds 5
    $null=Call 'catalog'
    $null=Call 'runtime-evidence'
    Get-Content -LiteralPath $nativeLog -Encoding utf8 -Tail 100 | Where-Object {
        $line=$_
        if($line -match '^(\d{4}/\d{1,2}/\d{1,2} \d{2}:\d{2}:\d{2}):' ){
            $stamp=[datetime]::ParseExact($Matches[1],'yyyy/M/d HH:mm:ss',[Globalization.CultureInfo]::InvariantCulture)
            $stamp -ge ([DateTimeOffset]::Parse($started).LocalDateTime.AddSeconds(-1)) -and $line -match 'sync cost time|can.t do sync|level state|Tcp|clear level'
        }
    } | Set-Content (Join-Path $dir 'native-sync-log.txt') -Encoding utf8
    @{started=$started;invoked=$true;persistentSaveVerified=$false;playtestVerified=$false}|ConvertTo-Json|Set-Content (Join-Path $dir 'sync-observation.json') -Encoding utf8
} catch {
    @{error=$_.Exception.Message}|ConvertTo-Json|Set-Content (Join-Path $dir 'probe-error.json') -Encoding utf8
} finally {
    try{$null=Call 'stop'}catch{}
}
