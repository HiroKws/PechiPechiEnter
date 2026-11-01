@echo off
setlocal
set "VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvarsall.bat"
set "HERE=%~dp0"
set "OUT=%HERE%build"
if not exist "%OUT%" mkdir "%OUT%"
if not exist "%OUT%\obj_x64" mkdir "%OUT%\obj_x64"
if not exist "%OUT%\obj_x86" mkdir "%OUT%\obj_x86"

echo === x64 ===
call "%VCVARS%" x64
if errorlevel 1 goto :err
cl /nologo /LD /EHsc /O2 /W3 /utf-8 /DUNICODE /D_UNICODE /Fo"%OUT%\obj_x64\\" /Fe"%OUT%\er_tip_x64.dll" "%HERE%er_tip.cpp" /link /DEF:"%HERE%er_tip.def" /MACHINE:X64 ole32.lib oleaut32.lib uuid.lib advapi32.lib comctl32.lib user32.lib gdi32.lib
if errorlevel 1 goto :err

echo === x86 ===
call "%VCVARS%" x86
if errorlevel 1 goto :err
cl /nologo /LD /EHsc /O2 /W3 /utf-8 /DUNICODE /D_UNICODE /Fo"%OUT%\obj_x86\\" /Fe"%OUT%\er_tip_x86.dll" "%HERE%er_tip.cpp" /link /DEF:"%HERE%er_tip.def" /MACHINE:X86 ole32.lib oleaut32.lib uuid.lib advapi32.lib comctl32.lib user32.lib gdi32.lib
if errorlevel 1 goto :err

echo.
echo OK: %OUT%\er_tip_x64.dll and er_tip_x86.dll
exit /b 0
:err
echo BUILD FAILED
exit /b 1
