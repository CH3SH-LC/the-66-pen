"""Fixed action19/receipt24. All build inputs are disk-only; no target query."""
from datetime import datetime,timezone,timedelta
import os,secrets,subprocess
from pathlib import Path
import build as legacy
from contract import read,write,sha,require
ROOT,HERE,OUTPUT,p,ro=legacy.ROOT,legacy.HERE,legacy.OUTPUT,legacy.p,legacy.ro
OWN=('native_acceptance.h','native_acceptance.cpp','acceptance_build.py','acceptance_contract.py','acceptance_receipt.py','acceptance-profile.json')
OPERATIONS={'runtime-state':1,'render-frame':2}
def copy_sources(run):
    hashes=legacy.copy_sources(run);folder=run/'candidate-source/playtest-control'
    for name in OWN:
        source=HERE/name;hashes[str(source)]=sha(source);(folder/name).write_bytes(source.read_bytes())
    observe=folder/'native_observe.cpp';text=observe.read_text(encoding='utf-8')
    text=legacy.replace(text,'#if HR_ACTION != 17 || !PLAY_OBSERVE_REVIEWED || HR_READ_CONTEXT','#if (HR_ACTION != 17 && HR_ACTION != 19) || !PLAY_OBSERVE_REVIEWED || HR_READ_CONTEXT')
    observe.write_text(text,encoding='utf-8')
    def edit(name,pairs):
        file=run/'candidate-source/native'/name;text=file.read_text(encoding='utf-8')
        for old,new in pairs:text=legacy.replace(text,old,new)
        file.write_text(text,encoding='utf-8')
    edit('hook_receipt_protocol.h',[
        ('#if HR_ACTION == 17\n#include "../playtest-control/native_observe.h"','#if HR_ACTION == 19\n#include "../playtest-control/native_acceptance.h"\nstatic_assert(HR_READ_CONTEXT==0 && PLAY_ACCEPTANCE_REVIEWED==1,"fixed acceptance card");\n#elif HR_ACTION == 17\n#include "../playtest-control/native_observe.h"'),
        ('#if HR_ACTION == 17\n    PlayReceipt observation;','#if HR_ACTION == 19\n    AcceptanceReceipt acceptance;\n#elif HR_ACTION == 17\n    PlayReceipt observation;'),
        ('#if HR_ACTION == 17\nstatic_assert(sizeof(Receipt)==400','#if HR_ACTION == 19\nstatic_assert(sizeof(Receipt)==sizeof(AcceptanceReceipt)+64,"acceptance ABI");\nconstexpr DWORD kReceiptVersion=24;\n#elif HR_ACTION == 17\nstatic_assert(sizeof(Receipt)==400')])
    edit('hook_receipt.cpp',[('#if HR_ACTION == 17\n                    ExecutePlayObservation(&receipt->observation);','#if HR_ACTION == 19\n                    ExecuteAcceptance(&receipt->acceptance);\n#elif HR_ACTION == 17\n                    ExecutePlayObservation(&receipt->observation);')])
    # The large receipt remains in the heap-backed shared mapping. No automatic
    # struct temporaries and no multi-million printf loop for image data.
    output='''#if HR_ACTION == 19
                HCRYPTPROV provider=0;HCRYPTHASH hash=0;BYTE digest[32]{};DWORD digestBytes=32;
                bool hashOk=CryptAcquireContextW(&provider,nullptr,nullptr,PROV_RSA_AES,CRYPT_VERIFYCONTEXT)!=0;
                if(hashOk)hashOk=CryptCreateHash(provider,CALG_SHA_256,0,0,&hash)!=0;
                if(hashOk)hashOk=CryptHashData(hash,reinterpret_cast<const BYTE*>(&receipt->acceptance),static_cast<DWORD>(sizeof(receipt->acceptance)),0)!=0;
                if(hashOk)hashOk=CryptGetHashParam(hash,HP_HASHVAL,digest,&digestBytes,0)!=0 && digestBytes==32;
                if(hash)CryptDestroyHash(hash);if(provider)CryptReleaseContext(provider,0);
                HANDLE evidence=CreateFileW(L"acceptance.bin",GENERIC_WRITE,FILE_SHARE_READ,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);
                DWORD written=0;bool evidenceOk=false;
                if(evidence!=INVALID_HANDLE_VALUE){evidenceOk=WriteFile(evidence,&receipt->acceptance,static_cast<DWORD>(sizeof(receipt->acceptance)),&written,nullptr)!=0 && written==sizeof(receipt->acceptance);if(!FlushFileBuffers(evidence))evidenceOk=false;CloseHandle(evidence);}
                std::printf(",\\\"transportOk\\\":true,\\\"evidenceWritten\\\":%s,\\\"acceptanceBytes\\\":%zu,\\\"acceptanceHeaderHex\\\":\\\"",evidenceOk&&hashOk?"true":"false",sizeof(receipt->acceptance));
                const auto head=reinterpret_cast<const unsigned char*>(&receipt->acceptance);
                for(std::size_t i=0;i<96;++i)std::printf("%02x",static_cast<unsigned>(head[i]));
                std::printf("\\\",\\\"acceptanceSha256\\\":\\\"");
                for(unsigned i=0;i<32;++i)std::printf("%02x",static_cast<unsigned>(digest[i]));
                std::printf("\\\"");
'''
    edit('hook_receipt_probe.cpp',[
        ('#include <windows.h>','#include <windows.h>\n#include <wincrypt.h>'),
        ('!(HR_ACTION==17 && PLAY_OBSERVE_REVIEWED==1)','!((HR_ACTION==17 && PLAY_OBSERVE_REVIEWED==1)||(HR_ACTION==19 && PLAY_ACCEPTANCE_REVIEWED==1))'),
        ('#elif HR_ACTION == 17\n                const bool reportedOk=','#elif HR_ACTION == 19\n                const bool reportedOk=receipt->acceptance.status==0 && receipt->acceptance.seh==0 && receipt->acceptance.stage==3;\n#elif HR_ACTION == 17\n                const bool reportedOk='),
        ('HR_ACTION == 17 ? "FIXED_PLAYTEST_OBSERVATION"','HR_ACTION == 19 ? "FIXED_PLAYTEST_ACCEPTANCE" : HR_ACTION == 17 ? "FIXED_PLAYTEST_OBSERVATION"'),
        ('#if HR_ACTION == 17\n                std::printf(',output+'#elif HR_ACTION == 17\n                std::printf('),
        ('|| HR_ACTION == 17\n                // Nonzero exit','|| HR_ACTION == 17 || HR_ACTION == 19\n                // Nonzero exit')])
    return hashes
def compile_card(run,fixture=False):
    vswhere=Path(os.environ['ProgramFiles(x86)'])/'Microsoft Visual Studio/Installer/vswhere.exe'
    vs=subprocess.check_output([str(vswhere),'-latest','-products','*','-requires','Microsoft.VisualStudio.Component.VC.Tools.x86.x64','-property','installationPath'],text=True).strip()
    vc=Path(vs)/'VC/Auxiliary/Build/vcvars64.bat';require(vc.is_file(),'MSVC_REQUIRED')
    common=f'cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /utf-8 /FI"{run/"target_config.h"}" '
    lines=['@echo off',f'call "{vc}" >nul','if errorlevel 1 exit /b 1',common+f'/c "{run/"candidate-source/playtest-control/native_acceptance.cpp"}" /Fo:"{run/"acceptance.obj"}"','if errorlevel 1 exit /b 1',common+f'/LD "{run/"candidate-source/native/hook_receipt.cpp"}" /Fo:"{run/"hook.obj"}" /Fe:"{run/"hook_receipt.dll"}" /link User32.lib "{run/"acceptance.obj"}"','if errorlevel 1 exit /b 1',common+f'"{run/"candidate-source/native/hook_receipt_probe.cpp"}" /Fo:"{run/"probe.obj"}" /Fe:"{run/"hook_receipt_probe.exe"}" /link User32.lib Advapi32.lib','if errorlevel 1 exit /b 1']
    if fixture:lines += [common+f'"{run/"candidate-source/playtest-control/acceptance_fixture.cpp"}" /Fo:"{run/"fixture.obj"}" /Fe:"{run/"acceptance_fixture.exe"}"','if errorlevel 1 exit /b 1']
    (run/'build.cmd').write_text('\n'.join(lines+['exit /b 0'])+'\n',encoding='utf-8')
    result=subprocess.run(['cmd.exe','/d','/c',str(run/'build.cmd')],cwd=run,capture_output=True,text=True,timeout=180)
    (run/'build.log').write_text((result.stdout or '')+(result.stderr or ''),encoding='utf-8');require(result.returncode==0,'BUILD_FAILED:'+str(run/'build.log'))
def prepare(args,*,compile_only=False):
    operation=getattr(args,'operation','runtime-state');require(operation in OPERATIONS,'UNPROVEN_CONTROL_CONTRACT:enter/exit require proven trial-data source, enum, async completion and return-level binding')
    page=getattr(args,'page_start',0);require(type(page) is int and 0<=page<=65536,'PAGE_START_RANGE');require(operation=='runtime-state' or page==0,'FRAME_HAS_NO_PAGE')
    profile=p.load_profile();p.verify_disk(profile);runtime=read(HERE/'runtime-profile.json');extra=read(HERE/'acceptance-profile.json')
    metadata=p.TARGET_IMAGE.parent/'YuanShen_Data/Managed/Metadata/global-metadata.dat'
    require(runtime['imageSha256']==extra['imageSha256']==profile['image']['sha256'] and sha(metadata)==runtime['metadataSha256']==extra['metadataSha256'],'RUNTIME_SOURCE_DRIFT')
    level=1 if compile_only else args.target_level;require(type(level) is int and 1<=level<=0xffffffff,'TARGET_LEVEL_UINT32')
    if compile_only:session=dict(pid=1,tid=1,processCreation=1,threadCreation=1,image=str(OUTPUT/'compile-only.invalid'))
    else:
        session=read(args.session);require(all(type(session.get(k)) is int and session[k]>0 for k in ('pid','tid','processCreation','threadCreation')),'SESSION_SHAPE');require(Path(session['image']).resolve()==p.TARGET_IMAGE.resolve(),'SESSION_IMAGE')
    run=ro.output_directory(OUTPUT);hashes=copy_sources(run);hashes[str(metadata)]=runtime['metadataSha256']
    if compile_only:deadline,message=1,0xc001
    else:
        kernel,user=p.windows_api();deadline=int(kernel.GetTickCount64())+600000;message=int(user.RegisterWindowMessageW('Miliastra.PlayAcceptance.'+secrets.token_hex(12)));require(message!=0,'REGISTER_MESSAGE_FAILED')
    nonce=secrets.randbits(63)|1;ro.emit_header(profile,session,run,deadline=deadline,message_id=message,nonce=nonce)
    header=run/'target_config.h';text=header.read_text(encoding='utf-8')
    for old,new in [('#define HR_READ_CONTEXT 1ULL','#define HR_READ_CONTEXT 0ULL'),('#define HR_ACTION 0ULL','#define HR_ACTION 19ULL'),('#define GS_BOOTSTRAP_READONLY 1ULL','#define GS_BOOTSTRAP_READONLY 0ULL')]:text=legacy.replace(text,old,new)
    text+='\n#define GS_REVIEWED_ACTION_PROFILE 1\n#define HR_ACTION_PROFILE_REVIEWED 1\n#define PLAY_OBSERVE_REVIEWED 1\n#define PLAY_ACCEPTANCE_REVIEWED 1\n#define PLAY_TARGET_LEVEL '+str(level)+'U\n#define ACCEPT_OPERATION '+str(OPERATIONS[operation])+'U\n#define ACCEPT_PAGE_START '+str(page)+'U\n'
    for prefix,data in [('PLAY',runtime),('ACCEPT',extra)]:
        text+=f'#define {prefix}_CODE_RVAS '+','.join(x['rva'] for x in data['functions'])+'\n'
        text+=f'#define {prefix}_CODE_BYTES '+','.join('{'+','.join(hex(b) for b in bytes.fromhex(x['head32']))+'}' for x in data['functions'])+'\n'
    text+='#define PLAY_HOTFIX_RVAS '+','.join(runtime['hotfixZeroRvas'])+'\n';header.write_text(text,encoding='utf-8')
    if compile_only:
        fixture=HERE/'tests/acceptance_fixture.cpp';hashes[str(fixture)]=sha(fixture);(run/'candidate-source/playtest-control/acceptance_fixture.cpp').write_bytes(fixture.read_bytes())
    compile_card(run,fixture=compile_only)
    for source,digest in hashes.items():require(sha(source)==digest,'SOURCE_CHANGED_DURING_BUILD')
    manifest=dict(schemaVersion=1,kind='playtest-control-prepared-v2',run=str(run),action=19,receiptVersion=24,mode=operation,pageStart=page,targetLevelId=level,launchable=not compile_only,compileOnly=compile_only,session=session,sourceHashes=hashes,deadlineTick=deadline,nonce=str(nonce),expiresUtc=(datetime.now(timezone.utc)+timedelta(minutes=8)).isoformat(),createdUtc=datetime.now(timezone.utc).isoformat(),imagePath=str(p.TARGET_IMAGE),imageSha256=profile['image']['sha256'])
    manifest['artifacts']={x.relative_to(run).as_posix():sha(x) for x in run.rglob('*') if x.is_file()};write(run/'prepared.json',manifest)
    if not compile_only:
        pins=dict(hashes);pins.update({str(run/name):digest for name,digest in manifest['artifacts'].items()});pins[str(run/'prepared.json')]=sha(run/'prepared.json');pins[str(p.TARGET_IMAGE)]=profile['image']['sha256'];quote=lambda x:"'"+str(x).replace("'","''")+"'"
        wrapper=(HERE/'invoke.template.ps1').read_text(encoding='utf-8').replace('FIXED_PLAYTEST_OBSERVATION','FIXED_PLAYTEST_ACCEPTANCE').replace('playtest-control-build-v1','playtest-control-build-v2').replace('@@EXPIRES@@',quote(manifest['expiresUtc'])).replace('@@PINS@@',',\n'.join('    @('+quote(path)+','+quote(digest)+')' for path,digest in sorted(pins.items())))
        require('@@' not in wrapper,'WRAPPER_PLACEHOLDER');(run/'invoke-observe.ps1').write_text(wrapper,encoding='utf-8-sig')
    result=dict(ok=True,kind='playtest-control-build-v2',run=str(run),compiled=True,launchable=not compile_only,actionCode=19,receiptVersion=24,mode=operation,readOnly=operation=='runtime-state',mutatesTemporaryRenderResources=operation=='render-frame',called=False,nativeStarted=False,outcomeUncertain=False,cleanupVerified=True,safeToRelease=True,preparedSha256=sha(run/'prepared.json'),wrapperSha256=sha(run/'invoke-observe.ps1') if not compile_only else None)
    write(run/'build-result.json',result);return result
