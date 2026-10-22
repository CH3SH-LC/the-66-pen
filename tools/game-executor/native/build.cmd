@echo off
setlocal
rem Build only our DLL and independent host. No game process discovery/loading.
for %%I in ("%~dp0..\..\..") do set "GE_REPO=%%~fI"
set "GE_OUT=%GE_REPO%\.runtime\game-executor\build"
set "GE_VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%GE_VSWHERE%" exit /b 2
for /f "usebackq tokens=*" %%I in (`"%GE_VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "GE_VS=%%I"
if not defined GE_VS exit /b 3
call "%GE_VS%\VC\Auxiliary\Build\vcvars64.bat"
if errorlevel 1 exit /b 4
if not exist "%GE_OUT%" mkdir "%GE_OUT%"
pushd "%GE_OUT%"
if /I "%~1"=="--scene-calls-only" goto scene_calls
if /I "%~1"=="--test-host-only" goto test_host
cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /LD /DGE_BUILD "%GE_REPO%\tools\game-executor\native\game_executor.cpp" "%GE_REPO%\tools\game-executor\native\pipe_server.cpp" /Fe:game_executor.dll /link /IMPLIB:game_executor.lib Advapi32.lib
if errorlevel 1 (popd & exit /b 5)
:test_host
if not exist game_executor.dll (popd & exit /b 7)
if not exist game_executor.lib (popd & exit /b 8)
cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD "%GE_REPO%\tools\game-executor\tests\native_test_host.cpp" game_executor.lib /Fe:native_test_host.exe
if errorlevel 1 (popd & exit /b 6)
popd
exit /b 0
:scene_calls
cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /c "%GE_REPO%\tools\game-executor\native\scene_calls.cpp"
if errorlevel 1 (popd & exit /b 9)
lib /nologo /OUT:scene_calls.lib scene_calls.obj
if errorlevel 1 (popd & exit /b 9)
cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD "%GE_REPO%\tools\game-executor\tests\scene_calls_test.cpp" scene_calls.lib /Fe:scene_calls_test.exe
if errorlevel 1 (popd & exit /b 9)
popd
exit /b 0
