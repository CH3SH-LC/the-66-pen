param([switch]$Native, [switch]$Research)
$ErrorActionPreference='Stop'
$penRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$projects=@(
  'tools/editor-bridge/Bootstrap/Bootstrap.csproj',
  'tools/editor-bridge/ManagedBridge/Miliastra.EditorBridge.csproj',
  'tools/editor-bridge/TestHost/TestHost.csproj'
)
if($Research){$projects+= 'tools/editor-catalog/ilspy-dump/ilspy-dump.csproj'}
foreach($project in $projects){
  & dotnet build (Join-Path $penRoot $project) -c Release --nologo
  if($LASTEXITCODE -ne 0){throw "BUILD_FAILED:$project"}
}
if($Native){
  & (Join-Path $penRoot 'tools/game-executor/native/build.ps1')
  if($LASTEXITCODE -ne 0){throw 'NATIVE_BUILD_FAILED'}
}
Write-Output 'Source build completed. No game process was discovered, started or contacted.'
