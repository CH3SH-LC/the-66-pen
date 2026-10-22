# Fixed, one-shot, read-only session query; no caller-provided commands or paths.
param()
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
$result=Join-Path $projectRoot '.runtime/verification/interface-experiments-20260926/p02/reload-native/catalog-standalone-elevated.json'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$principal=[Security.Principal.WindowsPrincipal]::new($identity)
if(-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'ADMIN_REQUIRED'}
if([DateTime]::UtcNow -ge [DateTime]::Parse('2026-09-26T21:19:04.5057727Z').ToUniversalTime()){throw 'ORIGINAL_SESSION_DEADLINE_EXPIRED'}
$pins=@{
    'tools/game-executor/native-level-catalog/NativeLevelCatalog.csproj' = 'ded7029689a15ed7b3aa7ea7b04abe6b6edfccc26a2f8a7de2a221d5fcc8cb4f'
    'tools/game-executor/native-level-catalog/Program.cs' = '7858bda96596e311cc87811d1e9352e53bfcfe917041ccf295dab244e09b34c5'
    'tools/editor-bridge/Adapter/NativeSaveCatalogEvidence.cs' = 'c6cee2c0c1d24e3b327abcd3cefc96ed5baeb91654259ff0199c00dbe490a590'
    'tools/game-executor/native-level-catalog/bin/Release/net9.0/NativeLevelCatalog.exe' = '9b0b0d01304f3bd6cc7d50e8771187ce18e9678290c6341a8f1fdb4035e46c51'
    'tools/game-executor/native-level-catalog/bin/Release/net9.0/NativeLevelCatalog.dll' = '35763291c7500d8974fd1eef526b3f5a9f247183a22e184835cffe584005563b'
    'tools/game-executor/native-level-catalog/bin/Release/net9.0/NativeLevelCatalog.deps.json' = 'a4d6cad8c900047539c4b5e729cb0c1b83f81abfea45d73d3eead0251b7f2871'
    'tools/game-executor/native-level-catalog/bin/Release/net9.0/NativeLevelCatalog.runtimeconfig.json' = '3c0bf772b95c93363a0a14e5df78e4ec408c90f04cb7103205af97b2d276fab0'
}
$held=[Collections.Generic.List[IDisposable]]::new()
try {
  foreach($relative in $pins.Keys) {
    $path=Join-Path $projectRoot $relative
    $part=[IO.Path]::GetFullPath($path)
    while($part) {
      if(([IO.File]::GetAttributes($part) -band [IO.FileAttributes]::ReparsePoint)-ne 0){throw 'REPARSE_PATH'}
      $part=[IO.Path]::GetDirectoryName($part)
    }
    $stream=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    $held.Add($stream)
    $sha=[Security.Cryptography.SHA256]::Create()
    try {$hash=([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-','').ToLowerInvariant()} finally {$sha.Dispose()}
    if($hash -cne $pins[$relative]){throw 'SOURCE_OR_BINARY_CHANGED'}
  }
  $destination=[IO.File]::Open($result,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
  $held.Add($destination)
  $exe=Join-Path $projectRoot 'tools/game-executor/native-level-catalog/bin/Release/net9.0/NativeLevelCatalog.exe'
  $raw=(& $exe) -join [Environment]::NewLine
  $code=$LASTEXITCODE
  $reply=$raw|ConvertFrom-Json
  if(-not ($reply.ok -is [bool]) -or ($reply.ok -and $code -ne 0)){throw 'REPLY_INVALID'}
  $reply|Add-Member -NotePropertyName helper -NotePropertyValue @{kind='one-shot-fixed-read-only';pid=$PID;admin=$true;exitCode=$code;deadlineUtc='2026-09-26T21:19:04.5057727Z';completedUtc=[DateTime]::UtcNow.ToString('o')}
  $bytes=[Text.Encoding]::UTF8.GetBytes(($reply|ConvertTo-Json -Depth 12))
  $destination.Write($bytes,0,$bytes.Length)
  exit $code
} finally {foreach($stream in $held){$stream.Dispose()}}
