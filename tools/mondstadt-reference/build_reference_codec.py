"""Build the audited open-source decompression core without its CLI/DLL loader."""
from pathlib import Path
import json
import subprocess
from reference_cli import digest, write_json
from source_chain_reference import WORK


def main():
    source=WORK/'ooz-source';out=WORK/'ooz-build-v2'
    if out.exists():raise ValueError('Immutable build output already exists')
    lock=json.loads((WORK/'ooz-source-lock.json').read_text(encoding='utf-8'))
    for r in lock['files']:
        if digest(Path(r['path']))!=r['sha256']:raise ValueError('Locked source mismatch')
    out.mkdir()
    text=(source/'kraken.cpp').read_text(encoding='utf-8')
    marker='// The decompressor will write outside of the target buffer.'
    if text.count(marker)!=1:raise ValueError('Audited pure-core boundary changed')
    core=text.split(marker)[0]
    forbidden=['LoadLibrary','GetProcAddress','fopen(','fwrite(','system(','CreateProcess','socket(','WinExec']
    for n in forbidden:
        if n in core:raise ValueError('Unexpected core capability '+n)
    (out/'kraken_core.cpp').write_text(core,encoding='utf-8')
    for name in ['bitknit.cpp','lzna.cpp','stdafx.h','targetver.h']:
        body=(source/name).read_bytes();(out/name).write_bytes(body)
        if name.endswith('.cpp') and any(n in body.decode('utf-8') for n in forbidden):raise ValueError('Unexpected codec capability')
    wrapper='''#include <stddef.h>
int Kraken_Decompress(const unsigned char*, size_t, unsigned char*, size_t);
extern "C" __declspec(dllexport) int reference_decompress(const unsigned char* src, size_t src_len, unsigned char* dst, size_t dst_len) {
  if (!src || !dst || src_len < 2 || src_len > 67108864 || dst_len > 67108864) return -2;
  return Kraken_Decompress(src, src_len, dst, dst_len);
}
'''
    (out/'wrapper.cpp').write_text(wrapper,encoding='utf-8')
    vc=Path('C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Auxiliary/Build/vcvars64.bat')
    if not vc.is_file():raise ValueError('Audited local MSVC environment unavailable')
    command=f'@echo off\ncall "{vc}" >nul\nif errorlevel 1 exit /b %errorlevel%\ncl /nologo /O2 /EHsc /LD /MT kraken_core.cpp bitknit.cpp lzna.cpp wrapper.cpp /Fe:reference_codec.dll /link /INCREMENTAL:NO\n'
    (out/'build.cmd').write_text(command,encoding='ascii')
    r=subprocess.run(['cmd.exe','/d','/c',str(out/'build.cmd')],cwd=out,capture_output=True,text=True,encoding='utf-8',errors='replace')
    (out/'build.log').write_text(r.stdout+r.stderr,encoding='utf-8')
    write_json(out/'build-receipt.json',{'schema':1,'upstreamCommit':lock['commit'],'sourceSha256':digest(source/'kraken.cpp'),
        'removedCapabilities':'upstream file I/O, CLI, proprietary DLL loading and compression path removed after exact core boundary',
        'exitCode':r.returncode,'gameDllLoaded':False,'gameProcessAccess':False,
        'files':{p.name:digest(p) for p in out.iterdir() if p.suffix in ['.cpp','.h','.dll']}})
    print(r.stdout[-3000:]+r.stderr[-1000:])
    if r.returncode:raise RuntimeError('Codec compilation failed')


if __name__=='__main__':main()
