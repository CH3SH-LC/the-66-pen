@echo off
setlocal
rem Host-only static library and stub test. No DLL, injector, helper or game IPC.
for %%I in ("%~dp0..\..\..") do set "TA_REPO=%%~fI"
set "TA_OUT=%TA_REPO%\.runtime\game-executor\template-authoring\build"
set "TA_VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%TA_VSWHERE%" exit /b 2
for /f "usebackq tokens=*" %%I in (`"%TA_VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "TA_VS=%%I"
if not defined TA_VS exit /b 3
call "%TA_VS%\VC\Auxiliary\Build\vcvars64.bat"
if errorlevel 1 exit /b 4
if not exist "%TA_OUT%" mkdir "%TA_OUT%"
pushd "%TA_OUT%"
cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /utf-8 /c "%~dp0template_calls.cpp"
if errorlevel 1 goto failed
lib /nologo /OUT:template_calls.lib template_calls.obj
if errorlevel 1 goto failed
cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /utf-8 "%~dp0tests\template_calls_test.cpp" template_calls.lib /Fe:template_calls_test.exe
if errorlevel 1 goto failed
cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /utf-8 "%~dp0tests\template_catalog_test.cpp" /Fe:template_catalog_test.exe
if errorlevel 1 goto failed
cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /utf-8 "%~dp0component_binding_calls.cpp" "%~dp0tests\component_binding_calls_test.cpp" /Fe:component_binding_calls_test.exe
if errorlevel 1 goto failed
cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /utf-8 "%~dp0item_calls.cpp" "%~dp0tests\item_calls_test.cpp" template_calls.lib /Fe:item_calls_test.exe
if errorlevel 1 goto failed
cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /utf-8 "%~dp0skill_calls.cpp" "%~dp0tests\skill_calls_test.cpp" template_calls.lib /Fe:skill_calls_test.exe
if errorlevel 1 goto failed
cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /utf-8 "%~dp0template_catalog_capture.cpp" "%~dp0tests\template_catalog_capture_test.cpp" /Fe:template_catalog_capture_test.exe
if errorlevel 1 goto failed
cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /utf-8 "%~dp0currency_action.cpp" "%~dp0template_catalog_capture.cpp" "%~dp0tests\currency_action_test.cpp" template_calls.lib /Fe:currency_action_test.exe
if errorlevel 1 goto failed
cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /utf-8 "%~dp0component_attachment.cpp" "%~dp0tests\component_attachment_test.cpp" /Fe:component_attachment_test.exe
if errorlevel 1 goto failed
cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /utf-8 "%~dp0item_calls.cpp" "%~dp0item_action.cpp" "%~dp0template_catalog_capture.cpp" "%~dp0tests\item_action_test.cpp" template_calls.lib /Fe:item_action_test.exe
if errorlevel 1 goto failed
cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /utf-8 "%~dp0binding_action.cpp" "%~dp0component_attachment.cpp" "%~dp0component_binding_calls.cpp" "%~dp0owner_notification_calls.cpp" "%~dp0template_catalog_capture.cpp" "%~dp0tests\binding_action_test.cpp" /Fe:binding_action_test.exe
if errorlevel 1 goto failed
cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /utf-8 "%~dp0trigger_calls.cpp" "%~dp0tests\trigger_calls_test.cpp" /Fe:trigger_calls_test.exe
if errorlevel 1 goto failed
cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /utf-8 "%~dp0item_properties_capture.cpp" "%~dp0tests\item_properties_capture_test.cpp" /Fe:item_properties_capture_test.exe
if errorlevel 1 goto failed
cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /utf-8 "%~dp0trigger_calls.cpp" "%~dp0trigger_region_add.cpp" "%~dp0tests\trigger_region_add_test.cpp" /Fe:trigger_region_add_test.exe
if errorlevel 1 goto failed
cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /utf-8 "%~dp0binding_action.cpp" "%~dp0component_attachment.cpp" "%~dp0component_binding_calls.cpp" "%~dp0owner_notification_calls.cpp" "%~dp0template_catalog_capture.cpp" "%~dp0tests\binding_edit_test.cpp" /Fe:binding_edit_test.exe
if errorlevel 1 goto failed
cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /utf-8 "%~dp0skill_action.cpp" "%~dp0template_catalog_capture.cpp" "%~dp0tests\skill_action_test.cpp" template_calls.lib /Fe:skill_action_test.exe
if errorlevel 1 goto failed
cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /utf-8 "%~dp0trigger_parent_calls.cpp" "%~dp0tests\trigger_parent_calls_test.cpp" /Fe:trigger_parent_calls_test.exe
if errorlevel 1 goto failed
popd
exit /b 0
:failed
popd
exit /b 5
