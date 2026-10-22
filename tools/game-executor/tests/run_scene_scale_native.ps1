# Private-host compilation and execution only. Never launches or accesses the game.
param([string]$OutputDirectory)
$ErrorActionPreference='Stop'
$taskRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
if(-not $OutputDirectory){$OutputDirectory=Join-Path $taskRoot ('.runtime/map-foundation-20261015/scale/native-tests-'+[DateTime]::UtcNow.ToString('yyyyMMdd-HHmmssfff'))}
$taskOutput=[IO.Path]::GetFullPath($OutputDirectory)
if(-not $taskOutput.StartsWith((Join-Path $taskRoot '.runtime')+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'OUTPUT_MUST_BE_PROJECT_RUNTIME'}
New-Item -ItemType Directory -Path $taskOutput | Out-Null
$taskVswhere=Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
$taskVs=& $taskVswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
$taskVc=Join-Path $taskVs 'VC/Auxiliary/Build/vcvars64.bat'
$taskCases=@('readonly_snapshot_guard_test','reviewed_action_guard_test','large_snapshot_walk_test','large_scene_identity_test','large_batch_guard_test')
$taskLines=@('@echo off',('call "'+$taskVc+'" >nul'),'if errorlevel 1 exit /b 1')
foreach($taskCase in $taskCases){
  $taskSource=Join-Path $PSScriptRoot ($taskCase+'.cpp')
  $taskExe=Join-Path $taskOutput ($taskCase+'.exe')
  $taskObj=Join-Path $taskOutput ($taskCase+'.obj')
  $taskCallObj=Join-Path $taskOutput 'scene_calls.obj'
  $taskCalls=Join-Path $PSScriptRoot '../native/scene_calls.cpp'
  if($taskCase -match 'identity|reviewed_action|batch_guard'){
    $taskLines+=('cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /c "'+$taskCalls+'" /Fo:"'+$taskCallObj+'"')
    $taskLines+='if errorlevel 1 exit /b 1'
    $taskLink=' "'+$taskCallObj+'"'
  }else{$taskLink=''}
  $taskLines+=('cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD "'+$taskSource+'" /Fo:"'+$taskObj+'" /Fe:"'+$taskExe+'"'+$taskLink)
  $taskLines+='if errorlevel 1 exit /b 1'
  $taskLines+=('"'+$taskExe+'"')
  $taskLines+='if errorlevel 1 exit /b 1'
}
$taskLines+='exit /b 0'
$taskCommand=Join-Path $taskOutput 'build-and-run.cmd'
[IO.File]::WriteAllText($taskCommand,($taskLines -join "`r`n"),[Text.UTF8Encoding]::new($false))
Push-Location $taskOutput
try { & cmd.exe /d /c $taskCommand 2>&1 | Tee-Object -FilePath (Join-Path $taskOutput 'result.log'); if($LASTEXITCODE){throw ('NATIVE_SCALE_TEST_FAILED:'+ $taskOutput)} }
finally { Pop-Location }
Write-Output ('NATIVE_SCALE_TESTS_PASSED: '+$taskOutput)
