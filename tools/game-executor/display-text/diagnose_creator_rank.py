"""Historical profile-field probe, NOT creator rank.

The +128 field is unrelated to the text privilege check. Use
diagnose_runtime_text_gate.py for property 10074 and permission 4 instead.
No game methods called. Historical receipts retain their original labels.
"""
from pathlib import Path
import sys,json,shutil
HERE=Path(__file__).resolve().parent;EX=HERE.parent;ROOT=EX.parents[1]
sys.path.insert(0,str(EX))
import build_readonly_profile as ro
import native_profiles as p

def replace(s,a,b):
 p.require(s.count(a)==1,'SOURCE_PATTERN_CHANGED:'+a[:60]);return s.replace(a,b,1)

def main():
 profile=p.load_profile();p.verify_disk(profile)
 stage=ro.output_directory(ROOT/'.runtime/display-text/rank-source')
 for name in ro.SOURCES:(stage/name).write_bytes((ro.NATIVE/name).read_bytes())
 with p.TARGET_IMAGE.open('rb') as f:
  pe=p.inspect_pe(f.read(8192));off=p.rva_offset(pe['sections'],0x9f73bb0,0xd3,p.TARGET_IMAGE.stat().st_size)
  f.seek(off);code=f.read(0xd3)
 header='''#pragma once
#include "game_context_snapshot.h"
struct CreatorRankSnapshot { unsigned status,rank,rankAfter,hotfix; };
void CaptureCreatorRank(const GameContextSnapshot*,CreatorRankSnapshot*) noexcept;
'''
 (stage/'creator_rank.h').write_text(header,encoding='utf8')
 capture=r'''
#include "creator_rank.h"
void CaptureCreatorRank(const GameContextSnapshot* context,CreatorRankSnapshot* out) noexcept {
 *out={};out->status=1;
 if(!context || context->status!=GS_OK || context->reserved!=1073741842 || !(context->flags&GS_LEVEL_OBSERVED))return;
 const unsigned char expected[]={@CODE@};
 __try {
  const auto base=context->moduleBase;
  if(std::memcmp(reinterpret_cast<void*>(base+0x9f73bb0),expected,sizeof(expected))!=0){out->status=2;return;}
  out->hotfix=*reinterpret_cast<unsigned char*>(base+0x56f862b) | *reinterpret_cast<unsigned char*>(base+0x56f8629);
  if(out->hotfix){out->status=3;return;}
  const auto g=*reinterpret_cast<std::uint64_t*>(base+0x5783de8);
  if(g!=context->global){out->status=4;return;}
  const auto mod=*reinterpret_cast<std::uint64_t*>(g+0xa440);
  if(mod<0x10000){out->status=5;return;}
  const auto data=*reinterpret_cast<std::uint64_t*>(mod+0x118);
  if(data<0x10000){out->status=6;return;}
  out->rank=*reinterpret_cast<volatile unsigned*>(data+0x128);
  out->rankAfter=*reinterpret_cast<volatile unsigned*>(data+0x128);
  if(out->rank!=out->rankAfter || out->rank>100 || mod!=*reinterpret_cast<std::uint64_t*>(g+0xa440) || data!=*reinterpret_cast<std::uint64_t*>(mod+0x118)){out->status=7;return;}
  out->status=0;
 } __except(EXCEPTION_EXECUTE_HANDLER){out->status=8;}
}
'''.replace('@CODE@',','.join(hex(x) for x in code))
 with (stage/'game_context_snapshot.cpp').open('a',encoding='utf8') as f:f.write(capture)
 path=stage/'hook_receipt_protocol.h';s=path.read_text();s=replace(s,'struct Receipt {','#include "creator_rank.h"\nstruct Receipt {');s=replace(s,'    GameContextSnapshot context;','    GameContextSnapshot context;\n    CreatorRankSnapshot creatorRank;');s=replace(s,'constexpr DWORD kReceiptVersion = HR_READ_REOPEN_GUARDS','constexpr DWORD kReceiptVersion = 17; // isolated rank diagnostic\n/* constexpr DWORD unusedVersion = HR_READ_REOPEN_GUARDS');s=replace(s,'HR_ACTION ? 3 : 2;','HR_ACTION ? 3 : 2; */');path.write_text(s,encoding='utf8')
 path=stage/'hook_receipt.cpp';s=path.read_text();s=replace(s,'                    CaptureGameContextSnapshot(&receipt->context);','                    CaptureGameContextSnapshot(&receipt->context);\n                    CaptureCreatorRank(&receipt->context,&receipt->creatorRank);');path.write_text(s,encoding='utf8')
 path=stage/'hook_receipt_probe.cpp';s=path.read_text();s=replace(s,'bool reportedOk = receipt->context.status == GS_OK;','bool reportedOk = receipt->context.status == GS_OK && receipt->creatorRank.status==0;');s=replace(s,'                std::printf("}\\n");',r'''                std::printf(",\"profileDisplayField\":{\"status\":%u,\"value\":%u,\"repeat\":%u,\"hotfix\":%u},\"gameMethodsCalled\":false}",receipt->creatorRank.status,receipt->creatorRank.rank,receipt->creatorRank.rankAfter,receipt->creatorRank.hotfix);
                std::printf("\n");''');path.write_text(s,encoding='utf8')
 ro.NATIVE=stage;ro.SOURCES=ro.SOURCES+('creator_rank.h',)
 result=ro.prepare(ROOT/'.runtime/scratch/native-tabs-20261014/session-1323.json',output_root=ROOT/'.runtime/display-text/rank-readonly',ttl_seconds=300)
 (ROOT/'.runtime/display-text/latest-rank-readonly.json').write_text(json.dumps(result,indent=2),encoding='utf8')
 print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
