# mw.editor.controls.read -- read-only UI Automation snapshot of the Miliastra
# Wonderland sandbox ("千星沙箱") editor window. Never invokes, focuses, types or
# activates anything, and never reads another process's automation tree. Takes no
# argument and interpolates no caller input; the caller owns the deadline (run it
# as a child process and kill it on timeout). Windows PowerShell 5.1 only -- PS7
# has no UIAutomationClient. stdout is always exactly one UTF-8 JSON object, and
# the exit code is 0 only when ok=true.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$METHOD = 'mw.editor.controls.read'
$PROCESS_NAME = 'BeyondEditor'
$WINDOW_TITLE = '千星沙箱'
$MAX_ELEMENTS = 250
$MAX_DEPTH = 8

function Write-Result([bool]$ok, $payload) {
    $obj = [ordered]@{ ok = $ok; method = $METHOD }
    foreach ($k in $payload.Keys) { $obj[$k] = $payload[$k] }
    [Console]::Out.Write(($obj | ConvertTo-Json -Depth 12 -Compress))
}

function Fail([string]$code, [string]$message, $extra) {
    $err = [ordered]@{ code = $code; message = $message }
    if ($extra) { foreach ($k in $extra.Keys) { $err[$k] = $extra[$k] } }
    Write-Result $false @{ error = $err }
    exit 1
}

function Read-Node($el, [int]$depth) {
    $c = $el.Current
    $pat = [ordered]@{}
    foreach ($p in @(@('invoke', [System.Windows.Automation.InvokePattern]::Pattern), @('expandCollapse', [System.Windows.Automation.ExpandCollapsePattern]::Pattern), @('selectionItem', [System.Windows.Automation.SelectionItemPattern]::Pattern))) {
        $o = $null
        $pat[$p[0]] = [bool]$el.TryGetCurrentPattern($p[1], [ref]$o)
    }
    $ct = $c.ControlType
    $ctName = if ($ct) { [string]$ct.ProgrammaticName -replace '^ControlType\.', '' } else { $null }
    # Off-screen/vanished elements report NaN or infinite bounds; they are kept as
    # null rather than coerced (an [int] cast overflows on infinity).
    $r = $c.BoundingRectangle
    $finite = -not ([double]::IsNaN($r.X) -or [double]::IsInfinity($r.X) -or [double]::IsNaN($r.Y) -or [double]::IsInfinity($r.Y) -or [double]::IsNaN($r.Width) -or [double]::IsInfinity($r.Width) -or [double]::IsNaN($r.Height) -or [double]::IsInfinity($r.Height))
    $bounds = $null
    if ($finite) { $bounds = [ordered]@{ x = [double]$r.X; y = [double]$r.Y; width = [double]$r.Width; height = [double]$r.Height } }
    [ordered]@{
        depth = $depth; name = [string]$c.Name; controlType = $ctName
        automationId = [string]$c.AutomationId; isEnabled = [bool]$c.IsEnabled; patterns = $pat
        boundsAvailable = $finite; bounds = $bounds
    }
}

# Control view, depth-first, capped at $MAX_ELEMENTS nodes and $MAX_DEPTH levels.
function Walk($el, [int]$depth) {
    if ($script:controls.Count -ge $MAX_ELEMENTS) { $script:truncated = $true; return }
    $node = $null
    try { $node = Read-Node $el $depth } catch {
        $node = [ordered]@{ depth = $depth; readError = $_.Exception.Message }
        [void]$script:errors.Add('read depth ' + $depth + ': ' + $_.Exception.Message)
        $script:partial = $true
    }
    [void]$script:controls.Add($node)
    if ($depth -ge $MAX_DEPTH) {
        try { if ($null -ne $script:walker.GetFirstChild($el)) { $script:depthLimited = $true } } catch {
            [void]$script:errors.Add('probe depth ' + $depth + ': ' + $_.Exception.Message)
            $script:partial = $true
        }
        return
    }
    $child = $null
    try { $child = $script:walker.GetFirstChild($el) } catch {
        [void]$script:errors.Add('child of depth ' + $depth + ': ' + $_.Exception.Message)
        $script:partial = $true
        return
    }
    while ($null -ne $child) {
        Walk $child ($depth + 1)
        if ($script:controls.Count -ge $MAX_ELEMENTS) { $script:truncated = $true; return }
        try { $child = $script:walker.GetNextSibling($child) } catch {
            [void]$script:errors.Add('sibling at depth ' + $depth + ': ' + $_.Exception.Message)
            $script:partial = $true
            return
        }
    }
}

try {
    Add-Type -AssemblyName UIAutomationClient
    Add-Type -AssemblyName UIAutomationTypes
    $procs = @(Get-Process -Name $PROCESS_NAME -ErrorAction SilentlyContinue)
    if ($procs.Count -eq 0) { Fail 'EDITOR_NOT_FOUND' "no running process named $PROCESS_NAME" $null }

    # Several windows under one PID are normal and not ambiguity; only the exact
    # main-window title decides.
    $hit = @($procs | Where-Object { $_.MainWindowHandle -ne 0 -and ([string]$_.MainWindowTitle).Trim() -ceq $WINDOW_TITLE })
    if ($hit.Count -eq 0) {
        $seen = @($procs | Where-Object { $_.MainWindowHandle -ne 0 } | ForEach-Object { [string]$_.MainWindowTitle })
        Fail 'WINDOW_NOT_FOUND' "no $PROCESS_NAME window titled '$WINDOW_TITLE'" @{ processCount = $procs.Count; windowTitles = $seen }
    }
    if ($hit.Count -gt 1) { Fail 'WINDOW_AMBIGUOUS' "$($hit.Count) $PROCESS_NAME windows titled '$WINDOW_TITLE'" @{ pids = @($hit | ForEach-Object { $_.Id }) } }
    $target = $hit[0]
    $hwnd = [long]$target.MainWindowHandle

    $root = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$hwnd)
    if ($null -eq $root) { Fail 'UIA_UNAVAILABLE' 'FromHandle returned no element for the editor window' @{ hwnd = $hwnd } }
    $script:walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
    $script:controls = New-Object System.Collections.ArrayList
    $script:truncated = $false
    $script:depthLimited = $false
    $script:partial = $false
    $script:errors = New-Object System.Collections.ArrayList
    try { Walk $root 0 } catch {
        [void]$script:errors.Add('walk: ' + $_.Exception.Message)
        $script:partial = $true
    }

    $meta = [ordered]@{
        pid = $target.Id; hwnd = $hwnd; processName = $PROCESS_NAME; windowTitle = $target.MainWindowTitle
        readOnly = $true; maxElements = $MAX_ELEMENTS; maxDepth = $MAX_DEPTH
        count = $script:controls.Count; truncated = $script:truncated; depthLimited = $script:depthLimited
        partial = $script:partial; errors = @($script:errors); controls = @($script:controls)
    }
    # A lone root (or nothing readable below it) is not a successful read.
    $readable = @($script:controls | Where-Object { $_.depth -gt 0 -and -not $_.Contains('readError') })
    if ($readable.Count -eq 0) {
        $meta['error'] = [ordered]@{ code = 'NO_ACCESSIBLE_CONTROLS'; message = 'no readable control below the editor window root (nodes=' + $script:controls.Count + ', errors=' + $script:errors.Count + ')' }
        Write-Result $false $meta
        exit 1
    }
    Write-Result $true $meta
    exit 0
} catch {
    Fail 'INTERNAL' ($_.Exception.GetType().Name + ': ' + $_.Exception.Message) $null
}
