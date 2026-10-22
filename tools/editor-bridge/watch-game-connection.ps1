param(
    [int]$Pid_ = 113168,
    [int]$PollSeconds = 5,
    [int]$TimeoutMinutes = 480
)
$ErrorActionPreference='Continue'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$report = Join-Path $root '.runtime/editor-bridge/game-connection-watch.log'
$gameLog = 'C:/Users/PUBLIC_USER/AppData/LocalLow/miHoYo/原神/LocalLog.log'

# Why this exists: two explanations for the failed playtest check look identical from the
# outside - the demo graph is rejected, or the playtest upload step cannot reach the server.
# The playtest flow is documented as "validation and upload", and this machine's network has
# dropped repeatedly today (EnetPingTimeout / EnetTimeout / Disconnect). Recording the
# connection state at the moment of the attempt is what separates those two, and it costs
# nothing while waiting.
#
# Read-only: it queries TCP state and tails a log. It never sends anything, and it does not
# touch the game, the editor or the level.
function Note([string]$text) {
    $line = ('{0}  {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $text)
    Add-Content -LiteralPath $report -Value $line -Encoding utf8
}

# The parameter must NOT be named $pid: that is a PowerShell automatic variable, and a
# parameter of that name silently fails to bind, which logged an empty count.
function Established([int]$processId) {
    try {
        return @(Get-NetTCPConnection -OwningProcess $processId -State Established -ErrorAction SilentlyContinue |
                 Where-Object { $_.RemoteAddress -notlike '127.*' -and $_.RemoteAddress -ne '0.0.0.0' }).Count
    } catch { return -1 }
}

# Full picture, not just a count: the playtest is reported to fail during its upload step,
# so which remote endpoints the game is reaching - and in what state - is the evidence that
# matters. Non-established states are included on purpose; a connection stuck in SYN_SENT
# is exactly what a blocked upload looks like.
function EndpointSummary([int]$processId) {
    try {
        $rows = @(Get-NetTCPConnection -OwningProcess $processId -ErrorAction SilentlyContinue |
                  Where-Object { $_.RemoteAddress -notlike '127.*' -and $_.RemoteAddress -ne '0.0.0.0' -and $_.RemoteAddress -ne '::' })
        if ($rows.Count -eq 0) { return 'none' }
        return (($rows | ForEach-Object { "$($_.RemoteAddress):$($_.RemotePort)/$($_.State)" } | Sort-Object -Unique) -join ',')
    } catch { return 'unreadable' }
}

function LastNetworkEvent() {
    try {
        $m = Select-String -LiteralPath $gameLog -Pattern 'EnetPingTimeout|EnetTimeout|Disconnect|DelayReconnect' -ErrorAction SilentlyContinue |
             Select-Object -Last 1
        if (-not $m) { return 'none' }
        return ($m.Line -replace '\s+', ' ').Substring(0, [Math]::Min(110, $m.Line.Length))
    } catch { return 'unreadable' }
}

Note "watch start; pid=$Pid_ poll=${PollSeconds}s window=${TimeoutMinutes}m"
$lastSig = ''
$deadline = (Get-Date).AddMinutes($TimeoutMinutes)
while ((Get-Date) -lt $deadline) {
    $alive = Get-Process -Id $Pid_ -ErrorAction SilentlyContinue
    $est = if ($alive) { Established $Pid_ } else { -2 }
    $eps = if ($alive) { EndpointSummary $Pid_ } else { "gone" }
    $net = LastNetworkEvent
    $sig = "$est|$eps|$net"
    # Only write on change: a quiet log is what makes a burst of lines meaningful.
    if ($sig -ne $lastSig) {
        Note ("established=$est endpoints=$eps lastNetworkEvent=$net")
        $lastSig = $sig
    }
    Start-Sleep -Seconds $PollSeconds
}
Note 'watch end'
